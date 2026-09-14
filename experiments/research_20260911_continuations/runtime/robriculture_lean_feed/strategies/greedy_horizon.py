"""Horizon-aware greedy crop loop (experiment #8, ADR-0007).

The single technique under test, layered on `greedy`'s "plant the best crop"
idea:

1. **Horizon-aware crop selection.** Each time the home tile is free, plant the
   highest profit-per-tile-per-day crop we can *both* afford *and* still mature
   (with a day to spare to sell) before turn 720. A strawberry planted on day 26
   never matures, so we never plant it; a melon is the ROI king until the horizon
   closes on it, after which we fall back to the best short crop that still fits.
2. **End-game liquidation.** In the final stretch we stop starting crops that
   can't finish, harvest whatever is standing, and dump every held product to the
   shed and sell it, so nothing is stranded in inventory at the buzzer (the winner
   is coins *at* turn 720).

Everything else is deliberately minimal: one main farmer, one home tile (the
shed-adjacent spawn), water daily, harvest at maturity, sell into the market.
This is a one-variable experiment, not a full agent.

Decisions live in pure module-level helpers (`plantable`, `roi`, `choose_crop`,
`is_endgame`, `sell_orders`) so they can be unit-tested without a full game.
"""

from __future__ import annotations

from kaggisim import economy
from kaggisim.strategy import Strategy

CROPS = economy.CROPS

#: 720 turns / 24 turns-per-day = 30 days (0..29). Derived from the sim defaults.
SEASON_DAYS = economy.CONFIG_DEFAULTS["episodeSteps"] // economy.CONFIG_DEFAULTS["turnsPerDay"]

#: Days at the tail of the season treated as the liquidation window.
ENDGAME_DAYS = 2

#: Leave at least this many days after first yield to harvest, drop, and sell.
SELL_MARGIN_DAYS = 1

#: Everything the market will actually buy from us (a SELL of anything else is a
#: silent no-op that wastes a market slot).
SELLABLE = frozenset(economy.MARKET_PARAMS)


def roi(crop: str) -> float:
    """Rough profit-per-tile-per-day used to rank crops (higher is better).

    Delegates to the shared economy model so the ranking tracks one source of
    truth. It is a *ranking* signal, not a P&L forecast — good enough to prefer
    melon over carrot over wheat, which is all the greedy choice needs.
    """
    return economy.naive_crop_roi(crop)


def ranked_crops() -> list[str]:
    """All crops, best profit-per-tile-per-day first (stable, deterministic)."""
    return sorted(CROPS, key=lambda c: (-roi(c), c))


def plantable(crop: str, day: int, season_days: int = SEASON_DAYS) -> bool:
    """Can `crop`, planted on `day`, reach a meaningful yield and be sold in time?

    Horizon gate: a crop must reach its first yield with at least `SELL_MARGIN_DAYS`
    to spare before the final day, or planting it just strands a tile (and its
    seed cost) that never pays off.
    """
    final_day = season_days - 1
    return day + CROPS[crop]["first"] + SELL_MARGIN_DAYS <= final_day


def choose_crop(day: int, money: float, season_days: int = SEASON_DAYS):
    """The crop to plant now: highest ROI among affordable *and* plantable crops.

    Returns ``None`` when nothing is worth planting (broke, or the horizon has
    closed on everything) — the caller then stops planting and idles/liquidates.
    """
    for crop in ranked_crops():
        if CROPS[crop]["seed"] <= money and plantable(crop, day, season_days):
            return crop
    return None


def is_endgame(day: int, season_days: int = SEASON_DAYS, endgame_days: int = ENDGAME_DAYS) -> bool:
    """True in the final `endgame_days` of the season — the liquidation window."""
    return day >= season_days - endgame_days


def sell_orders(shed: dict) -> list:
    """SELL orders liquidating every sellable product held in the shed.

    Deterministic (sorted by item); skips empty slots and anything the market
    won't buy. Used every turn, so held produce is continuously turned to coins.
    """
    return [
        ["SELL", item, shed[item]]
        for item in sorted(shed)
        if item in SELLABLE and shed.get(item, 0) > 0
    ]


def _has_produce(inventory: dict) -> bool:
    return any(n > 0 for item, n in inventory.items() if item in SELLABLE)


def _should_harvest(tile: dict, day: int, season_days: int) -> bool:
    """Harvest a standing plant at full maturity — or grab whatever it has once
    we're in the end-game liquidation window."""
    crop = tile.get("crop")
    if crop not in CROPS:
        return False
    if tile.get("yield_units", 0) <= 0:
        return False
    age = day - tile.get("planted_day", day)
    if age < CROPS[crop]["first"]:
        return False
    if is_endgame(day, season_days):
        return True
    if CROPS[crop]["ongoing"]:
        return True  # ongoing crops accrue yield in place; take what's ready
    return age >= CROPS[crop]["max_day"]


class GreedyHorizonStrategy(Strategy):
    name = "greedy_horizon"

    def act(self, obs) -> dict:
        player = obs["player"]
        me = obs["farms"][player]
        private = obs["private"]
        day = obs.get("day", 0)
        fx, fy = me["farmer"]
        tile = me["tiles"][fy][fx]
        money = me["money"]
        seeds = private.get("seeds", {})
        shed = private.get("shed", {})
        inventories = private.get("inventories", [{}])
        my_inv = inventories[0] if inventories else {}

        season_days = SEASON_DAYS

        # Market: continuously liquidate the shed. Near the buzzer this is the
        # end-game sell-off; earlier it just keeps produce from piling up.
        market = sell_orders(shed)

        chosen = choose_crop(day, money, season_days)

        # Buy the seed for the crop we intend to plant, once, when the tile is free.
        if tile is None and chosen is not None and seeds.get(chosen, 0) <= 0:
            market.append(["BUY_SEED", chosen, 1])

        farmer = ["PASS"]
        if isinstance(tile, dict) and tile.get("kind") == "PLANT":
            if _should_harvest(tile, day, season_days):
                farmer = ["HARVEST"]
            elif _has_produce(my_inv):
                # Get harvested goods into the shed so they can be sold now
                # instead of waiting for the end-of-day drop (matters on day 29).
                farmer = ["DROP"]
            elif not tile.get("watered_today", False):
                farmer = ["WATER"]
        elif _has_produce(my_inv):
            farmer = ["DROP"]
        elif tile is None and chosen is not None and seeds.get(chosen, 0) > 0:
            farmer = ["PLANT", chosen]
        elif isinstance(tile, dict) and tile.get("kind") == "WEED":
            farmer = ["DIG"]

        return {"farmer": farmer, "hands": [], "market": market}


STRATEGY = GreedyHorizonStrategy
