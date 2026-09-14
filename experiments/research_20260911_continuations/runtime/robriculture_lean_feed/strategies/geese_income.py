"""Geese/egg income line layered on the melon loop (experiment #7, ADR-0007).

Foundation: `greedy_horizon`'s single-tile melon loop (the champion). We reuse
its horizon-aware crop choice, harvest rule, and end-game liquidation *verbatim*
by importing it, so the melon side of this agent is byte-for-byte the champion's.

The single technique under test — the one variable — is a **geese income line**:

1. Once cash clears a threshold, the main farmer stands up a coop on the tile
   next to home, buys one goose, and places it.
2. Every day it feeds the goose one wheat (bought from the market, never grown)
   and collects the egg it lays. Eggs ride the end-of-day auto-drop into the shed
   and are sold the next turn, a steady indefinite income stream on top of melons.

Why this can only help: the melon loop's outcome depends only on *which* farmer
actions happen at the home tile each day, not on the exact turn within the day
(watering, harvesting, planting, and dropping are all once-a-day, turn-order
independent). The farmer resets to home every morning, and the melon loop always
takes strict priority — the goose is tended only on the spare turns (a full day
is 24 turns; the melon loop uses a handful). So on any given seed the melon
income equals the champion's exactly, and the agent wins by precisely the goose's
net profit. The whole bet therefore rides on **never letting the goose starve**:
a goose unfed two days running escapes and the $300 is gone, so feeding is the
top goose priority and wheat is kept stocked in the shed ahead of need.

Decisions live in pure module-level helpers (`should_start_geese`, `need_feed`,
`eggs_ready`, `goose_market_orders`, `step_toward`, ...) so they unit-test
without a full game.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies import greedy_horizon as gh

#: Home tile = the default spawn and the only shed-adjacent tile in the starting
#: NW quadrant. The melon loop lives here (same tile greedy_horizon uses).
HOME = (4, 4)

#: The goose lives one tile WEST of home — a free, unlocked NW tile adjacent to
#: home, so the farmer shuttles a single step to feed/collect and back.
COOP = (3, 4)

#: 30 days (0..29). Reused from the melon foundation.
SEASON_DAYS = gh.SEASON_DAYS

#: Stand up the goose line once cash clears this (we start at 3000; a melon
#: replant only needs 80, so this leaves the melon loop amply funded).
GEESE_CASH_THRESHOLD = 500

#: Don't stand up a *fresh* goose so late it can't recoup its $300 + feed.
GEESE_START_CUTOFF_DAY = 15

#: Feeding on the final day yields an egg only at the day's end-of-day refresh,
#: with no later market turn to sell it — pure wasted wheat. Stop one day early.
LAST_FEED_DAY = SEASON_DAYS - 2  # 28

#: Small safety margin added to the wheat stockpile so a feed is never blocked
#: waiting on a purchase (covers the buy/feed lag and the odd wasted unit).
WHEAT_MARGIN = 2

#: Sell everything the market buys — except WHEAT, which is the geese's feed
#: stock and must not be auto-liquidated out from under them.
SELL_ITEMS = frozenset(gh.SELLABLE) - {"WHEAT"}

#: Home-crop produce worth dropping to the shed for a same-day sale (mirrors
#: greedy_horizon's DROP), deliberately excluding WHEAT (feed) and EGG (goose
#: output, handled by the end-of-day auto-drop) so carrying feed/eggs never
#: triggers a spurious melon-side DROP.
DROP_ITEMS = frozenset(gh.CROPS) - {"WHEAT"}

_MOVE_FOR_DELTA = {(1, 0): "EAST", (-1, 0): "WEST", (0, 1): "SOUTH", (0, -1): "NORTH"}


# --- movement ------------------------------------------------------------

def step_toward(pos, target):
    """One MOVE action stepping `pos` toward `target` (x first, then y).

    Returns ``None`` when already there. The board is a simple grid and the only
    two tiles we ever visit (home and coop) are orthogonally adjacent, so a
    greedy axis-at-a-time walk is exact and never overshoots.
    """
    x, y = pos
    tx, ty = target
    if x != tx:
        return [_MOVE_FOR_DELTA[(1 if tx > x else -1, 0)]]
    if y != ty:
        return [_MOVE_FOR_DELTA[(0, 1 if ty > y else -1)]]
    return None


# --- tile classification -------------------------------------------------

def is_goose(tile) -> bool:
    """True iff `tile` is a coop with a goose placed on it."""
    return isinstance(tile, dict) and tile.get("animal") == "GOOSE"


def coop_status(tile) -> str:
    """Classify the coop tile: NONE | WEED | COOP_EMPTY | GOOSE | OTHER."""
    if tile is None:
        return "NONE"
    if isinstance(tile, dict):
        if "animal" in tile:
            return "GOOSE" if tile.get("animal") == "GOOSE" else "OTHER"
        kind = tile.get("kind")
        if kind == "COOP":
            return "COOP_EMPTY"
        if kind == "WEED":
            return "WEED"
    return "OTHER"


def have_goose(coop_tile, shed, my_inv) -> bool:
    """Is a goose already ours — placed, in the shed, or in hand?

    Used to buy exactly one: never rebuy while one is in flight to the coop.
    """
    return (
        is_goose(coop_tile)
        or shed.get("GOOSE", 0) > 0
        or my_inv.get("GOOSE", 0) > 0
    )


# --- decisions -----------------------------------------------------------

def should_start_geese(money, day, coop_tile,
                       threshold=GEESE_CASH_THRESHOLD,
                       cutoff=GEESE_START_CUTOFF_DAY) -> bool:
    """Pursue standing up the goose line: enough cash, early enough, not yet done.

    The setup phase (build coop -> buy goose -> place it) runs until a goose is
    actually *placed*; after that this is False and the agent just keeps it fed.
    """
    return (not is_goose(coop_tile)) and money >= threshold and day <= cutoff


def need_feed(coop_tile, day, last_feed_day=LAST_FEED_DAY) -> bool:
    """Does the goose need feeding this turn? The core escape-risk guard.

    A goose unfed two days running escapes, so we feed every day it is unfed —
    except the final day, whose egg could never be sold anyway.
    """
    return (
        is_goose(coop_tile)
        and not coop_tile.get("fed_today", False)
        and day <= last_feed_day
    )


def eggs_ready(coop_tile) -> bool:
    """Is there at least one egg on the coop to collect?"""
    return is_goose(coop_tile) and coop_tile.get("yield_units", 0) > 0


# --- market --------------------------------------------------------------

def sell_orders(shed) -> list:
    """Liquidate every sellable shed item except the geese's feeding wheat.

    Deterministic (sorted); skips empty slots. Identical to greedy_horizon's
    liquidation for the melon side (the champion never holds wheat), plus eggs.
    """
    return [
        ["SELL", item, shed[item]]
        for item in sorted(shed)
        if item in SELL_ITEMS and shed.get(item, 0) > 0
    ]


def wheat_target(day, last_feed_day=LAST_FEED_DAY, margin=WHEAT_MARGIN) -> int:
    """How much wheat to hold now: one per remaining feed day, plus a margin.

    We buy the *whole* remaining season's feed up front, on the first turn we
    commit to the line, because wheat is cheapest early — town demand steadily
    drains market wheat and drives its price up as the season runs, so dripping
    a unit a day would pay ever-rising prices and erode the egg profit. Buying
    the lot once locks in the low price. The target shrinks in step with daily
    consumption, so after the initial fill no further buying is triggered.
    """
    remaining_feeds = max(0, last_feed_day - day + 1)
    return remaining_feeds + margin if remaining_feeds > 0 else 0


def goose_market_orders(money, day, coop_tile, shed, my_inv,
                        threshold=GEESE_CASH_THRESHOLD,
                        cutoff=GEESE_START_CUTOFF_DAY,
                        last_feed_day=LAST_FEED_DAY,
                        margin=WHEAT_MARGIN) -> list:
    """Purchases for the goose line: buy the goose, stock the season's feed.

    - Buy exactly one goose once we commit to the line and none is in flight.
    - Fill wheat up to the remaining-season target while pursuing/running a
      goose — front-loaded, so the whole feed bill is paid at the low early
      price rather than the inflated late one.
    """
    orders = []
    starting = should_start_geese(money, day, coop_tile, threshold, cutoff)
    if starting and not have_goose(coop_tile, shed, my_inv):
        orders.append(["BUY_ANIMAL", "GOOSE", 1])

    pursuing = starting or is_goose(coop_tile)
    if pursuing:
        target = wheat_target(day, last_feed_day, margin)
        on_hand = shed.get("WHEAT", 0) + my_inv.get("WHEAT", 0)
        if on_hand < target:
            orders.append(["BUY_PRODUCT", "WHEAT", target - on_hand])
    return orders


# --- strategy ------------------------------------------------------------

class GeeseIncomeStrategy(Strategy):
    name = "geese_income"

    def act(self, obs) -> dict:
        player = obs["player"]
        me = obs["farms"][player]
        private = obs["private"]
        day = obs.get("day", 0)
        pos = tuple(me["farmer"])
        money = me["money"]
        seeds = private.get("seeds", {})
        shed = private.get("shed", {})
        inventories = private.get("inventories", [{}])
        my_inv = inventories[0] if inventories else {}

        home_tile = _tile_at(me, HOME)
        coop_tile = _tile_at(me, COOP)

        # --- Market: melon/egg liquidation (keeping feed wheat), melon seed, and
        #     the goose-line purchases. Position-independent, issued every turn.
        market = sell_orders(shed)
        chosen = gh.choose_crop(day, money)
        if home_tile is None and chosen is not None and seeds.get(chosen, 0) <= 0:
            market.append(["BUY_SEED", chosen, 1])
        market.extend(goose_market_orders(money, day, coop_tile, shed, my_inv))

        # --- Farmer: the melon loop has strict priority; whenever it wants an
        #     action we service it at home (heading there first if away). Only
        #     when the melon is idle do we spend the turn on the goose.
        melon_action = _melon_action(home_tile, day, money, seeds, my_inv)
        if melon_action is not None:
            farmer = melon_action if pos == HOME else (step_toward(pos, HOME) or ["PASS"])
        else:
            farmer = _goose_action(pos, coop_tile, day, money, shed, my_inv) or ["PASS"]

        return {"farmer": farmer, "hands": [], "market": market}


def _tile_at(farm, xy):
    x, y = xy
    return farm["tiles"][y][x]


def _carrying_crop(my_inv) -> bool:
    """Holding harvested home-crop produce that wants dropping to the shed."""
    return any(my_inv.get(item, 0) > 0 for item in DROP_ITEMS)


def _melon_action(home_tile, day, money, seeds, my_inv):
    """What the melon loop wants at HOME this turn, or None if it is idle.

    Mirrors greedy_horizon's farmer logic on the home tile, but the "drop
    produce" trigger is limited to home-crop items (never the geese's wheat or
    eggs) so tending the goose can never provoke a spurious melon-side DROP.
    """
    if isinstance(home_tile, dict) and home_tile.get("kind") == "PLANT":
        if gh._should_harvest(home_tile, day, SEASON_DAYS):
            return ["HARVEST"]
        if _carrying_crop(my_inv):
            return ["DROP"]
        if not home_tile.get("watered_today", False):
            return ["WATER"]
        return None
    if _carrying_crop(my_inv):
        return ["DROP"]
    chosen = gh.choose_crop(day, money)
    if home_tile is None and chosen is not None and seeds.get(chosen, 0) > 0:
        return ["PLANT", chosen]
    if isinstance(home_tile, dict) and home_tile.get("kind") == "WEED":
        return ["DIG"]
    return None


def _goose_action(pos, coop_tile, day, money, shed, my_inv):
    """The goose chore for this spare turn, or None. Feeding first (survival),
    then egg collection, then standing the line up."""
    status = coop_status(coop_tile)

    # 1) Keep it alive: feed it. Fetch a wheat from the shed first if unarmed.
    if status == "GOOSE" and need_feed(coop_tile, day):
        if my_inv.get("WHEAT", 0) > 0:
            return _go_or_do(pos, COOP, ["FEED"])
        if shed.get("WHEAT", 0) > 0:
            return _go_or_do(pos, HOME, ["PICKUP", "WHEAT", 1])
        return None  # wheat buy is in flight; wait rather than risk a bad action

    # 2) Collect the egg so production keeps flowing (yield caps otherwise).
    if status == "GOOSE" and eggs_ready(coop_tile):
        return _go_or_do(pos, COOP, ["HARVEST"])

    # 3) Stand the line up: place a bought goose, or build the coop for it.
    if status == "COOP_EMPTY":
        if my_inv.get("GOOSE", 0) > 0:
            return _go_or_do(pos, COOP, ["PLACE", "GOOSE", 1])
        if shed.get("GOOSE", 0) > 0:
            return _go_or_do(pos, HOME, ["PICKUP", "GOOSE", 1])
        return None
    if status in ("NONE", "WEED") and should_start_geese(money, day, coop_tile):
        if status == "WEED":
            return _go_or_do(pos, COOP, ["DIG"])
        return _go_or_do(pos, COOP, ["BUILD_COOP"])
    return None


def _go_or_do(pos, target, action):
    """Do `action` if standing on `target`, else take one step toward it."""
    return action if pos == target else step_toward(pos, target)


STRATEGY = GeeseIncomeStrategy
