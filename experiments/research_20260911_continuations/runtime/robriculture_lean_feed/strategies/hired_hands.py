"""Dynamic farm-hand hiring on the melon loop (experiment #6, ADR-0007).

The single technique under test, layered on `greedy_horizon`'s melon loop:

**Dynamic farm-hand hiring.** `greedy_horizon` is a strong *single-tile* melon
loop — one farmer, one home tile. Its ceiling is throughput: one worker can only
tend one melon at a time. This experiment scales that loop across many tiles by
*hiring farm hands*, giving each hand its own melon plot. A hand is hired only
when its projected marginal output over the remaining horizon beats its wage, so
we grow the crew while melons still have time to mature and stop paying for hands
that can't earn back their cost.

Everything else mirrors `greedy_horizon` and is deliberately minimal: melon only,
water daily, harvest at maturity, liquidate the shed into the market, respect the
same season-horizon plantability gate. The *only* new variable is the crew.

Hiring economics (verified against the installed sim, ADR-0002):

- Hands are cleared every night and re-hired each morning; there is **no ongoing
  wage**. The cost of the k-th hand of the day is ``mult * fib(k-1)`` (1, 1, 2,
  3, 5, 8, ...), so over-hiring in a single day is what "wage" punishes.
- A fresh hand spawns on a shed-access tile and walks to its assigned plot.
- Harvested produce auto-drops to the shed overnight, so every hand's melons
  reach the shed to be sold — no manual hauling needed.

Decisions live in pure module-level helpers (`hand_wage`, `plan_hands`,
`tile_action`, `harvest_ready`, `step_toward`, `max_live_index`) so the technique
can be unit-tested without a full game.
"""

from __future__ import annotations

from kaggisim import economy
from kaggisim.strategy import Strategy
from strategies.greedy_horizon import SEASON_DAYS, plantable, sell_orders

CROPS = economy.CROPS

#: The one crop this experiment grows — melon, the ROI king, exactly as in the
#: greedy_horizon foundation. Holding the crop fixed isolates the hiring variable.
CROP = "MELON"

#: Turns in a day (0..TURNS_PER_DAY-1); the last turn is a bad time to plant
#: (a plant unwatered on its birth night dies), so we gate late-day planting.
TURNS_PER_DAY = economy.CONFIG_DEFAULTS["turnsPerDay"]

#: Max hands to hire in a day. One plot per worker (farmer + hands), so the crew
#: caps at MAX_HANDS + 1 tiles. Kept modest to fit the 10-order/turn market cap
#: (hires + one sell + one seed buy) and keep navigation tight.
MAX_HANDS = 6

#: One melon plot per worker, in the NW (only unlocked) quadrant, ordered by
#: nearness to the farmer's spawn / shed-access tile at (4, 4) so a freshly hired
#: hand reaches its plot in a few steps and waters it the same day.
PLOTS = [
    (4, 4),  # worker 0 (main farmer, shed-adjacent) — the greedy_horizon tile
    (3, 4),
    (4, 3),
    (3, 3),
    (2, 4),
    (4, 2),
    (2, 3),
]

def _fib(n: int) -> int:
    """Sim-compatible Fibonacci: _fib(0)=1, _fib(1)=1, _fib(2)=2, _fib(3)=3, ..."""
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def hand_wage(k: int, mult: int = 1) -> int:
    """Cost of the k-th hand hired in a day (k is 1-indexed).

    The sim charges ``mult * fib(hires_today)`` per hire, and ``hires_today``
    starts at 0, so the first hand of the day (k=1) costs ``mult * fib(0)`` = 1.
    """
    return mult * _fib(k - 1)


def melon_tile_value(day: int, season_days: int = SEASON_DAYS) -> float:
    """Rough gross value of a *fresh* melon plot started today, or 0 if the
    horizon has closed on it (it could never mature and sell in time)."""
    if not plantable(CROP, day, season_days):
        return 0.0
    c = CROPS[CROP]
    return c["max_yield"] * c["base"] - c["seed"]


def plan_hands(
    day: int,
    money: float,
    max_live: int,
    season_days: int = SEASON_DAYS,
    max_hands: int = MAX_HANDS,
    mult: int = 1,
) -> int:
    """How many hands to hire this morning — the marginal-output-vs-wage rule.

    While a fresh melon can still mature (`plantable`), we grow the crew toward
    ``max_hands`` new plots. Once the horizon closes we stop growing and hire
    only enough hands to keep the *already-planted* plots watered (a plot is
    worker ``i``'s responsibility, so covering the highest live plot index needs
    that many hands). Each hand is added only while it is *affordable* and its
    marginal tile value strictly exceeds its escalating wage.
    """
    if plantable(CROP, day, season_days):
        target = max_hands
    else:
        target = min(max_hands, max(0, max_live))

    new_value = melon_tile_value(day, season_days)
    live_value = CROPS[CROP]["max_yield"] * CROPS[CROP]["base"]

    hired = 0
    budget = money
    for k in range(1, target + 1):
        wage = hand_wage(k, mult)
        if budget < wage:
            break
        # Hand k covers plot k (plot 0 is the farmer's). Covering a live plot
        # realises that melon's value; covering a new plot is worth a fresh one.
        value = live_value if k <= max_live else new_value
        if value <= wage:
            break
        hired += 1
        budget -= wage
    return hired


def harvest_ready(tile, day: int) -> bool:
    """True when a standing melon plant is mature enough to harvest for yield."""
    if not (isinstance(tile, dict) and tile.get("kind") == "PLANT"):
        return False
    crop = tile.get("crop")
    if crop not in CROPS:
        return False
    if tile.get("yield_units", 0) <= 0:
        return False
    age = day - tile.get("planted_day", day)
    return age >= CROPS[crop]["first"]


def _is_live_plant(tile) -> bool:
    return isinstance(tile, dict) and tile.get("kind") == "PLANT"


def tile_at(tiles, plot):
    x, y = plot
    return tiles[y][x]


def max_live_index(tiles, plots=PLOTS) -> int:
    """Highest plot index currently holding a live plant, or -1 if none."""
    best = -1
    for i, plot in enumerate(plots):
        if _is_live_plant(tile_at(tiles, plot)):
            best = i
    return best


def step_toward(pos, target):
    """One move verb stepping `pos` toward `target` (x first, then y), or PASS."""
    px, py = pos[0], pos[1]
    tx, ty = target[0], target[1]
    if px < tx:
        return ["EAST"]
    if px > tx:
        return ["WEST"]
    if py < ty:
        return ["SOUTH"]
    if py > ty:
        return ["NORTH"]
    return ["PASS"]


def tile_action(tile, day: int, hour: int = 0, season_days: int = SEASON_DAYS):
    """The action for a worker standing on its plot: dig, plant, water, harvest.

    Planting is gated by the season horizon (never plant a melon that can't
    mature and sell) and by the hour (never plant on the last turn of the day —
    the plant would die unwatered overnight).
    """
    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        return ["DIG"]
    if tile is None:
        if plantable(CROP, day, season_days) and hour < TURNS_PER_DAY - 1:
            return ["PLANT", CROP]
        return ["PASS"]
    if _is_live_plant(tile):
        if harvest_ready(tile, day):
            return ["HARVEST"]
        if not tile.get("watered_today", False):
            return ["WATER"]
    return ["PASS"]


class HiredHandsStrategy(Strategy):
    name = "hired_hands"

    def act(self, obs) -> dict:
        player = obs["player"]
        me = obs["farms"][player]
        private = obs["private"]
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        money = me["money"]
        tiles = me["tiles"]
        hands = me.get("hands", []) or []
        seeds = private.get("seeds", {})
        shed = private.get("shed", {})

        season_days = SEASON_DAYS
        market: list = []

        # --- Hire the crew for the day (mornings only; hands persist all day). ---
        n_hire = 0
        if hour == 0:
            n_hire = plan_hands(day, money, max_live_index(tiles), season_days, MAX_HANDS)
            market.extend([["HIRE"]] * n_hire)

        # --- One action per existing worker: navigate to its plot, then farm it. ---
        positions = [me["farmer"], *hands]
        seeds_available = seeds.get(CROP, 0)
        planted_this_turn = 0
        actions = []
        for i, pos in enumerate(positions):
            plot = PLOTS[i] if i < len(PLOTS) else PLOTS[-1]
            if [pos[0], pos[1]] != [plot[0], plot[1]]:
                actions.append(step_toward(pos, plot))
                continue
            action = tile_action(tile_at(tiles, plot), day, hour, season_days)
            if action and action[0] == "PLANT":
                # Only plant as many melons this turn as we hold seed for, or the
                # sim's atomic-plant rule voids every plant of the crop at once.
                if planted_this_turn < seeds_available:
                    planted_this_turn += 1
                else:
                    action = ["WATER"] if _is_live_plant(tile_at(tiles, plot)) else ["PASS"]
            actions.append(action)

        farmer_action = actions[0]
        hand_actions = actions[1:]

        # --- Market: liquidate melons in the shed, then restock seed. ---
        market.extend(sell_orders(shed))

        # Keep a seed buffer covering every active plot so arriving hands can
        # plant without stalling. Buy only the shortfall we can afford.
        active_plots = min(len(PLOTS), 1 + (n_hire if hour == 0 else len(hands)))
        empty_active = sum(
            1 for plot in PLOTS[:active_plots] if tile_at(tiles, plot) is None
        )
        want_seed = max(0, empty_active - seeds_available)
        if want_seed > 0 and plantable(CROP, day, season_days):
            affordable = int(money // CROPS[CROP]["seed"])
            buy = min(want_seed, affordable, 10 - len(market))
            if buy > 0:
                market.append(["BUY_SEED", CROP, buy])

        return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


STRATEGY = HiredHandsStrategy
