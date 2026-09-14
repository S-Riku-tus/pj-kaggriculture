"""Catch-crop tile packing on the wide melon crew (experiment #27, ADR-0007).

Foundation: `wide_hands`, the current champion — a 10-tile melon crew on the
unlocked NW quadrant (`hired_hands` widened to `MAX_HANDS = 9`). Its melon micro-
loop, hiring wage curve, navigation and market plumbing are reused *verbatim* by
importing the pure helpers from `hired_hands` / `wide_hands`.

The single technique under test — the one variable — is **catch cropping the
idle tail**. A melon needs ~10 days to first yield, so a plot fits at most two
melon cycles (roughly days 0-10 and 10-20) before the horizon closes on melon
(`plantable("MELON", day)` is false past day 18). After its last melon a plot
sits **idle for the remaining ~9 days**. `wide_hands` leaves it fallow; this
agent plants a **fast one-time catch crop** there instead — carrot or wheat —
waters it through its yield window, harvests at full maturity, and sells it.

Why this can be a genuine gain and not just more melon:

- Carrot/wheat sell into their **own markets** (CARROT / WHEAT), decoupled from
  the shared, easily-depressed melon market that both 1v1 players dump into. A
  catch-crop coin is a coin the opponent's melon flood cannot erode.
- The melon loop is untouched — melon tiles plant/water/harvest exactly as in
  `wide_hands`, so the win-rate delta attributes to the otherwise-fallow tail.

Two changes are needed beyond the empty-tile decision, both forced by the tail:

1. **Crew staffing.** `plan_hands` stops growing the crew once melon closes, so
   there would be no workers to plant the catch crop. `plan_hands_multicrop`
   keeps the full crew while a catch crop is still plantable to full maturity.
2. **Seed.** The seed buffer restocks the catch crop (not melon) in the tail.

Catch-crop economics (verified against the installed sim, ADR-0002):

- A one-time crop accrues yield **only from watering** on days whose age falls in
  ``[(max_day+1)//2, max_day]`` (+1 each, unfertilized). Full unfertilized yield
  is therefore carrot 3, wheat 4 — reached by watering daily and harvesting at
  age ``max_day`` *after* that day's water (water-first, then harvest), which is
  also safe from decay (decay starts at age ``max_day + 1``).
- We only plant a catch crop that can reach **full maturity** before the buzzer
  (``day + max_day <= final_day``), so no tile is stranded half-grown.

Decisions live in pure module-level helpers (`catch_crop_full_yield`,
`catch_crop_gross`, `cc_plantable`, `choose_catch_crop`, `catch_tile_action`,
`plan_hands_multicrop`) so the technique is unit-testable without a full game.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies import hired_hands as hh
from strategies import wide_hands as wh

CROPS = hh.CROPS

#: The melon crop and crew width are inherited unchanged from the champion.
MELON = wh.CROP
MAX_HANDS = wh.MAX_HANDS
PLOTS = wh.PLOTS
TURNS_PER_DAY = hh.TURNS_PER_DAY
SEASON_DAYS = hh.SEASON_DAYS

#: Fast one-time crops eligible as catch crops (melon and the ongoing crops are
#: excluded — melon is the primary loop; ongoing crops are slow to first yield).
CATCH_CROPS = ("CARROT", "WHEAT")


def catch_crop_full_yield(crop: str) -> int:
    """Full *unfertilized* yield of a one-time crop: base 1 plus one unit per
    watered day inside the yield window ``[(max_day+1)//2, max_day]``, capped."""
    c = CROPS[crop]
    max_day = c["max_day"]
    window_start = (max_day + 1) // 2
    watered_units = max(0, max_day - window_start + 1)
    return min(c["max_yield"], 1 + watered_units)


def catch_crop_gross(crop: str) -> int:
    """Gross base-price revenue of a fully matured catch crop."""
    return catch_crop_full_yield(crop) * CROPS[crop]["base"]


def catch_crop_profit(crop: str) -> int:
    """Gross revenue minus one seed — the per-cycle coin value of a catch crop."""
    return catch_crop_gross(crop) - CROPS[crop]["seed"]


def cc_plantable(crop: str, day: int, season_days: int = SEASON_DAYS) -> bool:
    """Can `crop`, planted on `day`, reach **full maturity** (age ``max_day``)
    and be harvested on or before the final day? Stricter than the melon-style
    first-yield gate: a catch crop is only worth it if it fills out."""
    final_day = season_days - 1
    return day + CROPS[crop]["max_day"] <= final_day


def choose_catch_crop(day: int, season_days: int = SEASON_DAYS):
    """The catch crop to plant on `day`: the full-maturity-plantable fast crop
    with the best profit **per occupied day** (shorter cycles fit more times in
    the tail), or ``None`` when the horizon has closed on every fast crop."""
    best = None
    best_rate = 0.0
    for crop in CATCH_CROPS:
        if not cc_plantable(crop, day, season_days):
            continue
        rate = catch_crop_profit(crop) / CROPS[crop]["max_day"]
        if rate > best_rate:
            best, best_rate = crop, rate
    return best


def catch_tile_action(tile, day: int):
    """Water/harvest loop for a standing catch crop (never melon).

    Water first every day — this keeps the plant alive and, on days inside the
    yield window, accrues its +1. Once it has reached ``max_day`` *and* been
    watered that day, harvest it at full yield (safe: decay only begins the day
    after ``max_day``). On the final day, grab whatever yield it holds."""
    crop = tile.get("crop")
    if crop not in CROPS:
        return ["PASS"]
    age = day - tile.get("planted_day", day)
    max_day = CROPS[crop]["max_day"]
    if not tile.get("watered_today", False):
        return ["WATER"]
    if age >= max_day and tile.get("yield_units", 0) > 0:
        return ["HARVEST"]
    return ["PASS"]


def plan_hands_multicrop(
    day: int,
    money: float,
    max_live: int,
    catch: str | None,
    season_days: int = SEASON_DAYS,
    max_hands: int = MAX_HANDS,
    mult: int = 1,
) -> int:
    """How many hands to hire this morning across the melon and catch-crop phases.

    While melon is still plantable this is exactly the champion's rule. Once the
    melon horizon closes we keep growing the crew toward ``max_hands`` as long as
    a catch crop can still be planted (there is productive tail work); otherwise
    we hire only enough to keep the already-standing plots staffed for harvest.
    Each hand is added only while affordable and worth more than its wage."""
    if hh.plantable(MELON, day, season_days):
        return hh.plan_hands(day, money, max_live, season_days, max_hands, mult)

    if catch is not None:
        target = max_hands
        # A fresh catch plot is worth its gross; covering a live plot is worth at
        # least as much. Either dwarfs the fib wage across the whole crew.
        value = catch_crop_gross(catch)
    else:
        target = min(max_hands, max(0, max_live))
        value = catch_crop_gross("CARROT")  # only used to staff live plots

    hired = 0
    budget = money
    for k in range(1, target + 1):
        wage = hh.hand_wage(k, mult)
        if budget < wage or value <= wage:
            break
        hired += 1
        budget -= wage
    return hired


def _decide(tile, day: int, hour: int, catch: str | None, season_days: int):
    """The action for a worker standing on its plot: melon loop untouched, with a
    catch crop planted on / tended in the idle tail."""
    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        return ["DIG"]
    if tile is None:
        if hh.plantable(MELON, day, season_days) and hour < TURNS_PER_DAY - 1:
            return ["PLANT", MELON]
        if catch is not None and hour < TURNS_PER_DAY - 1:
            return ["PLANT", catch]
        return ["PASS"]
    if hh._is_live_plant(tile):
        if tile.get("crop") == MELON:
            # Melon plots behave byte-for-byte as in wide_hands / hired_hands.
            return hh.tile_action(tile, day, hour, season_days)
        return catch_tile_action(tile, day)
    return ["PASS"]


class CatchHandsStrategy(Strategy):
    name = "catch_hands"

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

        catch = choose_catch_crop(day, season_days)
        melon_open = hh.plantable(MELON, day, season_days)

        # --- Market: liquidate the shed FIRST (before hires), so our melon SELL
        # sits at slot 0. The sim processes market orders slot-by-slot across both
        # players with a per-unit shared quote; melon's sell curve is steep, so
        # burying the SELL behind HIRE orders means selling into the crater the
        # opponent already dug. Selling first keeps our melon price competitive. ---
        market: list = list(hh.sell_orders(shed))

        # --- Hire the crew for the day (mornings only; hands persist all day). ---
        n_hire = 0
        if hour == 0:
            n_hire = plan_hands_multicrop(
                day, money, hh.max_live_index(tiles, PLOTS), catch, season_days, MAX_HANDS
            )
            market.extend([["HIRE"]] * n_hire)

        # --- One action per existing worker: navigate to its plot, then farm it. ---
        positions = [me["farmer"], *hands]
        planted_this_turn: dict[str, int] = {}
        actions = []
        for i, pos in enumerate(positions):
            plot = PLOTS[i] if i < len(PLOTS) else PLOTS[-1]
            if [pos[0], pos[1]] != [plot[0], plot[1]]:
                actions.append(hh.step_toward(pos, plot))
                continue
            tile = hh.tile_at(tiles, plot)
            action = _decide(tile, day, hour, catch, season_days)
            if action and action[0] == "PLANT":
                # Atomic-plant rule is per crop: only plant as many of a crop this
                # turn as we hold seed for, or the sim voids every plant of it.
                crop = action[1]
                if planted_this_turn.get(crop, 0) < seeds.get(crop, 0):
                    planted_this_turn[crop] = planted_this_turn.get(crop, 0) + 1
                else:
                    action = ["WATER"] if hh._is_live_plant(tile) else ["PASS"]
            actions.append(action)

        farmer_action = actions[0]
        hand_actions = actions[1:]

        # Seed buffer covering every empty active plot so arriving hands can plant
        # without stalling. In the melon phase we restock melon; in the tail we
        # restock the catch crop. Buy only the affordable shortfall that fits.
        active_plots = min(len(PLOTS), 1 + (n_hire if hour == 0 else len(hands)))
        empty_active = sum(
            1 for plot in PLOTS[:active_plots] if hh.tile_at(tiles, plot) is None
        )
        restock = MELON if melon_open else catch
        if restock is not None and empty_active > 0:
            want_seed = max(0, empty_active - seeds.get(restock, 0))
            if want_seed > 0:
                affordable = int(money // CROPS[restock]["seed"])
                buy = min(want_seed, affordable, 10 - len(market))
                if buy > 0:
                    market.append(["BUY_SEED", restock, buy])

        return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


STRATEGY = CatchHandsStrategy
