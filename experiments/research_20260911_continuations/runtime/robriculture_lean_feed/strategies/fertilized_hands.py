"""Fertilizing the melon crew to reach the yield cap sooner (experiment #26, ADR-0007).

The single technique under test, layered on the champion `hired_hands` multi-tile
melon loop:

**Fertilize melon tiles.** A fertilized melon accrues yield twice as fast on each
watered day inside its growth window, so it reaches ``max_yield`` (6) by tile-age
8 instead of 10. The hypothesis (issue #26): capping sooner shortens each tile's
cycle, fitting more melon harvests into the fixed 720-turn season.

Everything else mirrors `hired_hands` exactly — dynamic farm-hand hiring, one
melon plot per worker, water daily, harvest at maturity, liquidate the shed. The
*only* new variable is fertilizer: buy it, carry it to the plot, and apply it
during the melon's growth window.

Fertilizer mechanics (verified against the installed sim, ADR-0002 —
``kaggle_environments/envs/kaggriculture/kaggriculture.py``):

- ``FERTILIZE`` consumes one ``FERTILIZER`` from the *worker's own inventory* and
  sets the tile's ``fertilized_until_day`` to ``day + 2`` (covers 3 days).
- Melon (non-ongoing) accrues yield only when **watered** on a day inside the
  window ``[(max_yield_day+1)//2, max_yield_day]`` = ages 6..12; the per-day gain
  is ``+2`` when that day is covered by fertilizer, else ``+1`` (sim WATER op).
- ``FERTILIZER`` is bought via ``BUY_PRODUCT`` (it lands in the *shed*), so a
  worker must ``PICKUP`` it while shed-adjacent before it can ``FERTILIZE``. Of
  the crew, only the main farmer's plot ``(4, 4)`` is a shed-access tile, so
  fertilizing is applied there — the lowest-overhead plot — with no detours that
  would strand a melon (a plant dies after two consecutive unwatered days).

Where the edge actually comes from (verified against the sim, not the issue's
stated reasoning): melon ``HARVEST`` is gated by ``first_yield_day`` (10), so the
cycle length is the *same* fertilized or not. But the yield-accruing WATER and the
HARVEST both want tile-age 10, and `hired_hands` prioritises HARVEST — so an
**unfertilized** melon is harvested at age 10 carrying only **5** units (its
age-10 watering, which would have made the 6th, never happens). A **fertilized**
melon reaches the cap of 6 by age 8, comfortably before the age-10 harvest, so it
is harvested with the full **6**. The technique therefore buys ``+1`` melon unit
per farmer cycle — a small but perfectly consistent gain, not the shorter cycle
the hypothesis imagined. The promotion test is the honest arbiter.

Decisions live in pure module-level helpers (`wants_fertilizer`, `have_fertilizer`,
`fertilize_or_fetch`, `should_buy_fertilizer`) so the technique is unit-testable
without a full game.
"""

from __future__ import annotations

from kaggisim import economy
from kaggisim.strategy import Strategy
from strategies.greedy_horizon import SEASON_DAYS, SELL_MARGIN_DAYS, plantable, sell_orders
from strategies.hired_hands import (
    CROP,
    MAX_HANDS,
    PLOTS,
    max_live_index,
    plan_hands,
    step_toward,
    tile_action,
    tile_at,
)

CROPS = economy.CROPS

#: The traded good this experiment introduces; bought via BUY_PRODUCT, applied
#: with FERTILIZE (both sim-verified).
FERTILIZER = "FERTILIZER"

#: Melon growth constants, transcribed from the installed sim's CROPS table
#: (kaggriculture.py) rather than the locally-drifted economy table, because the
#: fertilizer window depends on them exactly.
MELON_FIRST_YIELD_DAY = 10   # earliest legal HARVEST age (hard gate)
MELON_MAX_YIELD_DAY = 12     # last age a watered day still accrues yield
MELON_MAX_YIELD = 6          # yield cap
#: First tile-age at which a watered day accrues yield: (max_yield_day + 1) // 2.
MELON_WINDOW_START = (MELON_MAX_YIELD_DAY + 1) // 2  # == 6

#: Rough per-unit fertilizer price used only as an affordability guard before
#: emitting a BUY_PRODUCT (the sim quotes the live market price at fill time).
FERTILIZER_PRICE = economy.base_price(FERTILIZER)  # 100


def _is_live_melon(tile) -> bool:
    return (
        isinstance(tile, dict)
        and tile.get("kind") == "PLANT"
        and tile.get("crop") == CROP
    )


def wants_fertilizer(tile, day: int, season_days: int = SEASON_DAYS) -> bool:
    """True when fertilizing this melon *now* would speed its yield accrual.

    All must hold: it is a live melon; its age is inside the growth window
    ``[MELON_WINDOW_START, MELON_MAX_YIELD_DAY]`` (only then does a watered day
    accrue yield); it has not yet hit the cap; it is not already fertilizer-
    covered for today (``fertilized_until_day >= day`` would make a fresh unit
    wasted); and the season horizon still lets it reach a harvest (a melon that
    can never be harvested is not worth a cent of fertilizer).
    """
    if not _is_live_melon(tile):
        return False
    age = day - tile.get("planted_day", day)
    if not (MELON_WINDOW_START <= age <= MELON_MAX_YIELD_DAY):
        return False
    if tile.get("yield_units", 0) >= MELON_MAX_YIELD:
        return False
    if tile.get("fertilized_until_day", -1) >= day:
        return False
    return plantable(CROP, tile.get("planted_day", day), season_days)


def have_fertilizer(inv: dict) -> bool:
    """True when this worker's inventory holds a fertilizer unit to apply."""
    return bool(inv) and inv.get(FERTILIZER, 0) > 0


def fertilize_or_fetch(tile, day: int, inv: dict, shed: dict,
                       season_days: int = SEASON_DAYS):
    """The fertilizer action for a *shed-adjacent* worker on its plot, or None.

    Apply straight from inventory when a unit is held; otherwise fetch one from
    the shed (legal only because the caller is shed-adjacent). None when the
    melon doesn't want fertilizer or no unit is reachable — the caller then falls
    back to its ordinary water/harvest loop.
    """
    if not wants_fertilizer(tile, day, season_days):
        return None
    if have_fertilizer(inv):
        return ["FERTILIZE"]
    if shed and shed.get(FERTILIZER, 0) > 0:
        return ["PICKUP", FERTILIZER, 1]
    return None


def should_buy_fertilizer(tile, day: int, shed: dict, inv: dict, money: float,
                          season_days: int = SEASON_DAYS) -> bool:
    """True when a melon wants fertilizer but none is on hand to give it.

    Buys one unit only when: the plot's melon wants fertilizing, neither the shed
    nor the worker already holds a unit, and we can afford it. Keeps the shed from
    accumulating idle fertilizer.
    """
    if not wants_fertilizer(tile, day, season_days):
        return False
    if (shed and shed.get(FERTILIZER, 0) > 0) or (inv and inv.get(FERTILIZER, 0) > 0):
        return False
    return money >= FERTILIZER_PRICE


class FertilizedHandsStrategy(Strategy):
    name = "fertilized_hands"

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
        inventories = private.get("inventories", [{}]) or [{}]
        farmer_inv = inventories[0] if inventories else {}

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

            tile = tile_at(tiles, plot)

            # Fertilizer delta: only the shed-adjacent farmer (plot 0 == (4, 4))
            # can fetch and apply without abandoning its melon. Take priority over
            # the ordinary loop when a fertilizer move is available this turn.
            if i == 0:
                fert = fertilize_or_fetch(tile, day, farmer_inv, shed, season_days)
                if fert is not None:
                    actions.append(fert)
                    continue

            action = tile_action(tile, day, hour, season_days)
            if action and action[0] == "PLANT":
                # Only plant as many melons this turn as we hold seed for, or the
                # sim's atomic-plant rule voids every plant of the crop at once.
                if planted_this_turn < seeds_available:
                    planted_this_turn += 1
                else:
                    action = ["WATER"] if _is_live_melon(tile) else ["PASS"]
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

        # Restock one fertilizer when the farmer's melon wants it and none is on
        # hand (it lands in the shed for the farmer to PICKUP next turn).
        if len(market) < 10 and should_buy_fertilizer(
            tile_at(tiles, PLOTS[0]), day, shed, farmer_inv, money, season_days
        ):
            market.append(["BUY_PRODUCT", FERTILIZER, 1])

        return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


STRATEGY = FertilizedHandsStrategy
