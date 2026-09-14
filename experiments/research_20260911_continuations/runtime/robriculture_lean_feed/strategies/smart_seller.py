"""Demand-aware, throttled selling on the melon foundation (experiment #5, ADR-0007).

The single technique under test, layered on `greedy_horizon`'s melon loop:

**Demand-aware, throttled selling.** Instead of dumping every harvest the moment
it hits the shed, we (a) *hold* premium produce until the town's demand for it
peaks, (b) *throttle* how many units we release per turn so a single dump doesn't
depress our own sale price, and (c) *prefer* selling the products the town shops
currently demand when market slots are scarce. Everything else is held fixed to
`greedy_horizon` so the win-rate delta attributes to this one variable.

Why this can pay on the melon foundation: melon is in **no** shop's demand list,
so the only buyer is the town center, which consumes it every 12 turns at a
multiplier that ratchets 1x -> 2x -> 4x across the season (schedule below). One
melon tile produces less than the town eats, so melon inventory drifts *down* and
its price climbs monotonically across the game (empirically ~250 -> ~292). The
champion sells each harvest immediately, realizing the lower early prices; holding
into the top-demand window and liquidating there realizes the higher late prices.
The per-turn cap keeps the eventual release from crashing melon's steep (`sq`)
above-anchor price curve.

Decisions live in pure module-level helpers (`demand_priority`, `price_ok`,
`update_floor`, `should_release`, `sell_quantity`, `sell_plan`) so they can be
unit-tested against fixed price/inventory/demand inputs without a full game.
"""

from __future__ import annotations

from kaggisim import economy
from strategies import greedy_horizon as gh

CROPS = economy.CROPS
SEASON_DAYS = gh.SEASON_DAYS

#: Everything the market will actually buy from us (a SELL of anything else is a
#: silent no-op that wastes a market slot). Shared with the melon foundation.
SELLABLE = gh.SELLABLE

#: Which shops demand which products, and how a single-product shop consumes at
#: 2x. Transcribed from the sim's SHOPS table (kaggriculture.py) / economy.py.
SHOP_DEMAND = economy.SHOP_DEMAND

#: The day the town center's demand multiplier reaches its top tier. The sim's
#: TOWN_CENTER_DEMAND_SCHEDULE steps 1x (day>=0) -> 2x (day>=10) -> 4x (day>=20);
#: melon (no shop demand) is only ever bought by the town center, so its price
#: peaks in this final tier. We hold melon until then, then release it.
TOP_DEMAND_DAY = 20

#: Units of a single product we release per turn outside the liquidation window.
#: Small on purpose: one melon tile's whole run is only tens of units, so a low
#: cap spreads the sale across the high-price window without crashing our own price.
SELL_CAP = 3


def demand_priority(item: str, unlocked_shops) -> int:
    """How strongly the currently-unlocked town shops demand `item`.

    Higher means sell it sooner when market slots are scarce. A shop that demands
    only one product consumes it at 2x, so it counts double. Items no unlocked
    shop wants (e.g. MELON) score 0 and fall to the back of the queue.
    """
    score = 0
    for shop in unlocked_shops:
        products = SHOP_DEMAND.get(shop)
        if products and item in products:
            score += 2 if len(products) == 1 else 1
    return score


def price_ok(price: float, floor: float) -> bool:
    """True when the current price is at or above our rolling floor.

    Guards against selling into a self-inflicted dip below what the market has
    already been willing to pay.
    """
    return price >= floor


def update_floor(floor: float, price: float) -> float:
    """Ratchet the rolling floor up to the running peak price.

    The floor never falls, so a temporary price dip (e.g. right after our own
    sale) can't coax us into selling below the market's established level.
    """
    return price if price > floor else floor


def should_release(day: int, season_days: int = SEASON_DAYS, top_demand_day: int = TOP_DEMAND_DAY) -> bool:
    """True once we should start releasing held premium produce.

    We hold until the town center's top demand tier opens (`top_demand_day`),
    and the end-game liquidation window always forces a release so nothing is
    stranded in the shed at the buzzer.
    """
    return day >= top_demand_day or gh.is_endgame(day, season_days)


def sell_quantity(held: int, day: int, season_days: int = SEASON_DAYS, cap: int = SELL_CAP) -> int:
    """How many units of one product to sell this turn.

    Throttled to `cap` per turn during the release window; the cap is lifted in
    the end-game liquidation window so we clear the shed before the game ends.
    Never exceeds what we actually hold.
    """
    if held <= 0:
        return 0
    if gh.is_endgame(day, season_days):
        return held
    return min(held, cap)


def sell_plan(shed, unlocked_shops, day: int, season_days: int = SEASON_DAYS, cap: int = SELL_CAP):
    """SELL orders for this turn: hold until the window, throttle, demand-order.

    Only sellable, non-empty shed items are considered. Before the release
    window we hold everything (empty plan). In the window we release up to `cap`
    units per product, ordered so the town's currently-demanded goods go first
    (they hold their price best); ties break by item name for determinism. In the
    end-game window the cap lifts and everything is liquidated.
    """
    if not should_release(day, season_days):
        return []
    items = [
        item
        for item in shed
        if item in SELLABLE and shed.get(item, 0) > 0
    ]
    items.sort(key=lambda it: (-demand_priority(it, unlocked_shops), it))
    plan = []
    for item in items:
        qty = sell_quantity(shed[item], day, season_days, cap)
        if qty > 0:
            plan.append(["SELL", item, qty])
    return plan


class SmartSellerStrategy(gh.GreedyHorizonStrategy):
    """`greedy_horizon`'s melon loop with demand-aware, throttled selling.

    Only the market side changes: instead of dumping the whole shed every turn,
    we hold premium produce until the peak-demand window and then release it
    under a per-turn cap, preferring the town's demanded goods. Farmer actions
    (plant / water / harvest / drop / dig / end-game harvest) are inherited
    unchanged from the champion foundation.
    """

    name = "smart_seller"

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
        town = obs.get("town", {}) or {}
        unlocked_shops = town.get("unlocked_shops", [])

        season_days = SEASON_DAYS

        # THE ONE TECHNIQUE: demand-aware, throttled selling instead of a full
        # every-turn dump. Hold premium produce until the peak-demand window,
        # then release it under a per-turn cap, demanded goods first.
        market = sell_plan(shed, unlocked_shops, day, season_days, SELL_CAP)

        chosen = gh.choose_crop(day, money, season_days)

        # Buy the seed for the crop we intend to plant, once, when the tile is free.
        if tile is None and chosen is not None and seeds.get(chosen, 0) <= 0:
            market.append(["BUY_SEED", chosen, 1])

        # Farmer actions are the champion melon loop, unchanged.
        farmer = ["PASS"]
        if isinstance(tile, dict) and tile.get("kind") == "PLANT":
            if gh._should_harvest(tile, day, season_days):
                farmer = ["HARVEST"]
            elif gh._has_produce(my_inv):
                farmer = ["DROP"]
            elif not tile.get("watered_today", False):
                farmer = ["WATER"]
        elif gh._has_produce(my_inv):
            farmer = ["DROP"]
        elif tile is None and chosen is not None and seeds.get(chosen, 0) > 0:
            farmer = ["PLANT", chosen]
        elif isinstance(tile, dict) and tile.get("kind") == "WEED":
            farmer = ["DIG"]

        return {"farmer": farmer, "hands": [], "market": market}


STRATEGY = SmartSellerStrategy
