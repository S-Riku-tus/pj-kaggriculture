"""Diversified, price-aware market farmer (strategic pivot away from melon).

This is a **new design**, not another melon variant. The melon lineage
(`hired_hands` -> `wide_hands` -> `ranch_hands`) pours ~55% of its sells into
MELON, the single most floorable, most contested, zero-replenishment market. A
quantitative market diagnostic showed the ladder rewards *out-earning a diverse
field in a shared 1v1 market*, and that the melon lineage is volume- and
diversity-broken, not cost-broken. This agent fixes that with two ideas the
melon lineage never used:

1. **Roaming multi-tile workers.** A day is 24 turns but a melon plot needs only
   a couple of actions, so the melon lineage's "one worker per plot" wastes ~90%
   of every worker's day. Here each worker is assigned a compact *cluster* of
   tiles (a "beat") of a single product and sweeps it each day — planting,
   watering, harvesting whichever tile nearest to it needs attention. One worker
   now drives a whole product line, so a handful of cheap hands cover five or six
   markets in parallel.

2. **Price-aware selling.** `obs["market"]` exposes the live, shared inventory
   and prices. Before selling, we compute (from the sim's own price curve) how
   many units of a product can clear while its price stays above a per-product
   floor fraction of base, and sell only that many — the rest waits for town
   demand to lift the price back up. Bottomless markets (WHEAT, EGG) clear
   freely; trap markets (MELON, WOOL, MILK) are throttled so we never dump into
   the floor. Because the inventory we read is the *shared* one, a melon-flooder
   opponent crashing the melon price automatically throttles our melon sells and
   shifts nothing of ours into the crater — diversification does the rest.

Product lines (each a roaming worker over a cluster in the free NW quadrant):
  * MELON   — small, high-value early-cash side line (NOT the core), price-capped.
  * CARROT  — deep market, steady $/day.
  * TOMATO  — ongoing, high value once it matures.
  * WHEAT   — bottomless spine; also feeds the animals (free feed) with surplus
              sold into wheat's five-shop-drained market.
  * GOOSE   — bottomless EGG spine; a small flock, fed from grown/bought wheat.
  * COW+SHEEP — capped animal line (milk/wool clear above base at low volume).

All decisions live in pure module-level helpers (`market_price`, `max_sellable`,
`price_aware_sell_orders`, `crop_tile_chore`, `roam_action`, `animal_chore`,
`animal_worker_action`, `plan_crew`) so the design is unit-tested without a full
720-turn game.
"""

from __future__ import annotations

from kaggisim import economy
from kaggisim.pricing import market_price
from kaggisim.strategy import Strategy
from strategies.greedy_horizon import SEASON_DAYS, plantable

CROPS = economy.CROPS
ANIMALS = economy.ANIMALS
MARKET_PARAMS = economy.MARKET_PARAMS

TURNS_PER_DAY = economy.CONFIG_DEFAULTS["turnsPerDay"]
SHED_TILE = (4, 4)  # only unlocked shed-access tile in the starting NW quadrant

# --- Layout: one roaming worker per beat. Workers are declared in a fixed order;
# the NW block is always staffed, the NE block only after that quadrant is bought.
# Each worker's index is stable within a day, so `active_workers(...)[i]` maps
# worker i to its job. Animal workers carry the shed-access corner nearest them.
#
# The bottomless spine is WHEAT + EGG: NE is filled mostly with wheat tiles and
# goose coops (wheat feeds the geese; eggs and surplus wheat clear into their two
# bottomless markets), because every finite market (carrot, tomato, melon...)
# floors once its depth is exhausted, but wheat and eggs do not.
#
# NW shed-access corner is (4,4); NE's is (5,4) (unlocked with the NE quadrant).
NW_SHED = (4, 4)
NE_SHED = (5, 4)

#: One entry per worker: a crop beat, or an animal cluster with its shed corner.
#: `quad` is the quadrant that must be unlocked for the worker to be staffed.
WORKERS = [
    # --- NW (always unlocked) ---
    {"role": "crop", "crop": "MELON",  "quad": "NW",
     "beat": [(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (2, 1)]},
    {"role": "crop", "crop": "CARROT", "quad": "NW",
     "beat": [(0, 2), (1, 2), (0, 3), (1, 3), (0, 4), (1, 4)]},
    {"role": "crop", "crop": "TOMATO", "quad": "NW",
     "beat": [(3, 0), (4, 0), (3, 1), (4, 1)]},
    {"role": "crop", "crop": "WHEAT",  "quad": "NW",
     "beat": [(2, 2), (3, 2), (2, 3)]},
    {"role": "animal", "quad": "NW", "shed": NW_SHED,
     "assign": [((4, 3), "GOOSE"), ((3, 4), "GOOSE"), ((4, 2), "GOOSE")]},
    {"role": "animal", "quad": "NW", "shed": NW_SHED,
     "assign": [((3, 3), "COW"), ((2, 4), "SHEEP")]},
    # --- NE (staffed once bought): wheat + geese spine, plus a carrot line ---
    {"role": "crop", "crop": "WHEAT",  "quad": "NE",
     "beat": [(5, 2), (6, 2), (7, 2), (8, 2)]},
    {"role": "crop", "crop": "WHEAT",  "quad": "NE",
     "beat": [(5, 0), (6, 0), (7, 0), (8, 0)]},
    {"role": "animal", "quad": "NE", "shed": NE_SHED,
     "assign": [((5, 3), "GOOSE"), ((6, 3), "GOOSE"), ((7, 3), "GOOSE"), ((8, 3), "GOOSE")]},
    {"role": "animal", "quad": "NE", "shed": NE_SHED,
     "assign": [((5, 1), "GOOSE"), ((6, 1), "GOOSE"), ((7, 1), "GOOSE"), ((8, 1), "GOOSE")]},
    {"role": "crop", "crop": "CARROT", "quad": "NE",
     "beat": [(9, 0), (9, 1), (9, 2), (9, 3), (9, 4), (8, 4)]},
]

#: Buy the NE quadrant once cash clears this (keeps NW working capital intact).
LAND_BUY_MONEY = 1600
LAND_BUY_CUTOFF_DAY = 14  # no point unlocking tiles nothing can mature on

NW_CREW = sum(1 for w in WORKERS if w["quad"] == "NW")
FULL_CREW = len(WORKERS)


def active_workers(unlocked):
    """The worker specs whose quadrant is unlocked (NW block, then NE block)."""
    return [w for w in WORKERS if w["quad"] in unlocked]

#: Per-product floor fraction of base: never sell a product below this * base.
#: Bottomless markets clear low; trap markets are throttled hard.
FLOOR_FRAC = {
    "WHEAT": 0.55,
    "EGG": 0.55,
    "CARROT": 0.55,
    "TOMATO": 0.60,
    "FERTILIZER": 0.50,
    "MELON": 0.66,
    "MILK": 0.62,
    "WOOL": 0.62,
    "STRAWBERRY": 0.62,
}
DEFAULT_FLOOR_FRAC = 0.60

#: Wheat kept in the shed as animal feed buffer (never sold below this).
WHEAT_FEED_BUFFER = 6
#: Wheat a worker grabs per shed visit for feeding.
FEED_BATCH = 6

#: Money buffers so animal purchases never starve crop working capital.
GOOSE_BUFFER = 500
COW_BUFFER = 700
SHEEP_BUFFER = 800

#: Don't buy a fresh animal so late it can't recoup its cost + feed.
ANIMAL_BUY_CUTOFF_DAY = 16

_MOVES = {(1, 0): "EAST", (-1, 0): "WEST", (0, 1): "SOUTH", (0, -1): "NORTH"}


# --- Market pricing: the sim-validated model (kaggisim.pricing, imported above as
# `market_price`), so price-aware selling uses the same curve the sim scores on. --

def max_sellable(item: str, inventory: int, floor_frac: float, cap: int = 400) -> int:
    """Max units to sell now keeping price >= floor_frac * base.

    Selling raises inventory and lowers price along the sim's curve; we count how
    many successive units stay above the floor. `cap` bounds the scan. Selling at
    price 1 does not raise inventory (sim rule), but we never want to sell that
    low anyway, so the floor short-circuits first.
    """
    p = MARKET_PARAMS.get(item)
    if p is None:
        return 0
    floor = floor_frac * p["base"]
    n = 0
    inv = inventory
    while n < cap:
        if market_price(item, inv) < floor:
            break
        n += 1
        inv += 1
    return n


def price_aware_sell_orders(shed, market_inv, floor_frac=None, wheat_buffer=WHEAT_FEED_BUFFER) -> list:
    """SELL orders for everything sellable, each throttled to its market depth.

    `market_inv` is the shared live inventory from obs. Deterministic order
    (sorted). WHEAT is held back by `wheat_buffer` (the live flock's feed reserve)
    so the animals never starve.
    """
    fracs = floor_frac or FLOOR_FRAC
    orders = []
    for item in sorted(shed):
        if item not in MARKET_PARAMS:
            continue
        have = shed.get(item, 0)
        if have <= 0:
            continue
        if item == "WHEAT":
            have -= wheat_buffer
            if have <= 0:
                continue
        inv = market_inv.get(item, MARKET_PARAMS[item]["I0"])
        k = max_sellable(item, inv, fracs.get(item, DEFAULT_FLOOR_FRAC))
        n = min(have, k)
        if n > 0:
            orders.append(["SELL", item, n])
    return orders


# --- Navigation ---------------------------------------------------------------

def step_toward(pos, target):
    """One move verb stepping `pos` toward `target` (x first, then y), or PASS."""
    px, py = pos[0], pos[1]
    tx, ty = target[0], target[1]
    if px != tx:
        return [_MOVES[(1 if tx > px else -1, 0)]]
    if py != ty:
        return [_MOVES[(0, 1 if ty > py else -1)]]
    return ["PASS"]


def _at(pos, tile) -> bool:
    return [pos[0], pos[1]] == [tile[0], tile[1]]


def _dist(pos, tile) -> int:
    return abs(pos[0] - tile[0]) + abs(pos[1] - tile[1])


def _at_shed(pos, shed_tile=SHED_TILE) -> bool:
    return _at(pos, shed_tile)


def _is_animal(tile) -> bool:
    return isinstance(tile, dict) and "animal" in tile


# --- Crop roaming -------------------------------------------------------------

def crop_tile_chore(tile, crop, day, hour, have_seed, season_days=SEASON_DAYS):
    """The pending chore on one crop tile, or ``None`` if it wants nothing.

    Waters a live plant first (survival + yield), harvests only at maturity
    (non-ongoing at ``max_yield_day``; ongoing whenever yield is ready), digs
    weeds, and plants an empty tile when seed and horizon allow.
    """
    if tile is None:
        if have_seed and plantable(crop, day, season_days) and hour < TURNS_PER_DAY - 1:
            return ["PLANT", crop]
        return None
    if not isinstance(tile, dict):
        return None
    kind = tile.get("kind")
    if kind == "WEED":
        return ["DIG"]
    if kind != "PLANT":
        return None
    cd = CROPS.get(tile.get("crop"))
    if cd is None:
        return None
    age = day - tile.get("planted_day", day)
    if not tile.get("watered_today", False):
        return ["WATER"]
    if tile.get("yield_units", 0) > 0 and age >= cd["first"]:
        if cd["ongoing"] or age >= cd["max_day"]:
            return ["HARVEST"]
    return None


def roam_action(pos, tiles, beat, crop, day, hour, have_seed, season_days=SEASON_DAYS):
    """A roaming crop worker's action: service the nearest tile that needs work.

    Sweeps the whole beat over a day; ties on distance break to the lowest tile
    coordinate for determinism. Returns ``PASS`` when the beat is fully tended.
    """
    best = None
    best_key = None
    for (x, y) in beat:
        chore = crop_tile_chore(tiles[y][x], crop, day, hour, have_seed, season_days)
        if chore is None:
            continue
        key = (_dist(pos, (x, y)), x, y)
        if best_key is None or key < best_key:
            best_key = key
            best = ((x, y), chore)
    if best is None:
        return ["PASS"]
    target, chore = best
    return chore if _at(pos, target) else step_toward(pos, target)


def empty_tiles(tiles, beat) -> int:
    """How many tiles in `beat` are empty (plantable)."""
    return sum(1 for (x, y) in beat if tiles[y][x] is None)


# --- Animal roaming -----------------------------------------------------------

def animal_chore(kind, at, pos, tiles, inv, shed, shed_tile=SHED_TILE):
    """This turn's chore for one animal, or ``None`` when it wants nothing.

    Setup (build structure -> fetch animal from shed -> place), then keep it
    harvested and fed; CARE only when already standing on it. `shed_tile` is the
    shed-access corner this worker uses to pick animals/feed out of the shed.
    """
    ct = tiles[at[1]][at[0]]
    on = _at(pos, at)
    structure = ANIMALS[kind]["structure"]

    if not _is_animal(ct):
        if inv.get(kind, 0) > 0:
            return ["PLACE", kind] if on else step_toward(pos, at)
        if ct is None:
            build = "BUILD_COOP" if structure == "COOP" else "BUILD_PASTURE"
            return [build] if on else step_toward(pos, at)
        if isinstance(ct, dict) and ct.get("kind") == structure:
            if shed.get(kind, 0) > 0:
                return (["PICKUP", kind, 1] if _at_shed(pos, shed_tile)
                        else step_toward(pos, shed_tile))
            return None
        return None

    if ct.get("yield_units", 0) > 0:
        return ["HARVEST"] if on else step_toward(pos, at)
    if not ct.get("fed_today", False):
        if inv.get("WHEAT", 0) > 0:
            return ["FEED"] if on else step_toward(pos, at)
        if shed.get("WHEAT", 0) > 0:
            return (["PICKUP", "WHEAT", min(shed["WHEAT"], FEED_BATCH)]
                    if _at_shed(pos, shed_tile) else step_toward(pos, shed_tile))
        return None
    if not ct.get("cared_today", False) and on:
        return ["CARE"]
    return None


def animal_worker_action(pos, tiles, inv, shed, assignments, day, shed_tile=SHED_TILE):
    """A roaming animal worker: proactively grab feed at the shed, then service
    the nearest animal that needs work. Never ``None`` (idles toward the shed)."""
    needs_feed = any(
        _is_animal(tiles[t[1]][t[0]]) and not tiles[t[1]][t[0]].get("fed_today", False)
        for (t, _k) in assignments
    )
    if (
        needs_feed
        and _at_shed(pos, shed_tile)
        and inv.get("WHEAT", 0) < FEED_BATCH
        and shed.get("WHEAT", 0) > 0
    ):
        return ["PICKUP", "WHEAT", min(shed["WHEAT"], FEED_BATCH)]

    best = None
    best_key = None
    for (at, kind) in assignments:
        chore = animal_chore(kind, at, pos, tiles, inv, shed, shed_tile)
        if chore is None:
            continue
        key = (_dist(pos, at), at[0], at[1])
        if best_key is None or key < best_key:
            best_key = key
            best = chore
    if best is not None:
        return best
    return step_toward(pos, shed_tile)


# --- Crew sizing --------------------------------------------------------------

def _fib(n: int) -> int:
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def plan_crew(money, hands_now, target, mult=1) -> int:
    """Hire hands up the wage curve toward `target`, affordability-gated.

    Hands are cleared nightly and re-hired each morning; the k-th hire of the day
    costs ``mult * fib(k-1)`` (1, 1, 2, 3, 5, ...). We keep a full crew because
    every hand drives its own product line, and the whole crew's daily wage is
    trivial next to the revenue it unlocks.
    """
    hired = 0
    budget = money
    for k in range(hands_now + 1, target + 1):
        wage = mult * _fib(k - 1)
        if budget < wage:
            break
        budget -= wage
        hired += 1
    return hired


# --- Animal ownership -----------------------------------------------------------

def _owns(kind, tiles, assignments, shed, inventories) -> int:
    """How many of `kind` are placed / in shed / in hand (for buy-exactly-N)."""
    placed = sum(
        1 for (at, k) in assignments
        if k == kind and _is_animal(tiles[at[1]][at[0]])
        and tiles[at[1]][at[0]].get("animal") == kind
    )
    in_shed = shed.get(kind, 0)
    in_hand = sum(inv.get(kind, 0) for inv in inventories)
    return placed + in_shed + in_hand


class MarketFarmerStrategy(Strategy):
    name = "market_farmer"

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
        inventories = private.get("inventories", [{}])
        market_inv = obs.get("market", {}).get("inventory", {})
        unlocked = set(me.get("unlocked_quadrants", ["NW"]))

        season_days = SEASON_DAYS
        active = active_workers(unlocked)

        # Aggregate the active layout: crop beats grouped by crop, and animal
        # assignments split into the goose flock and the pasture herd.
        crop_beats: dict[str, list] = {}
        geese_assign: list = []
        pasture_assign: list = []
        for w in active:
            if w["role"] == "crop":
                crop_beats.setdefault(w["crop"], []).extend(w["beat"])
            else:
                for (at, kind) in w["assign"]:
                    (geese_assign if kind == "GOOSE" else pasture_assign).append((at, kind))

        # --- Hiring (mornings only). Put HIRE first at dawn so the full active
        # crew is guaranteed against the 10-order cap; deferred sells resume. ---
        hire_orders = []
        if hour == 0:
            n_hire = plan_crew(money, len(hands), target=len(active) - 1)
            hire_orders = [["HIRE"]] * n_hire

        # --- One action per worker, dispatched by its spec. ---
        positions = [me["farmer"], *hands]
        actions = []
        for i, pos in enumerate(positions):
            spec = active[i] if i < len(active) else active[-1]
            if spec["role"] == "crop":
                crop = spec["crop"]
                have_seed = seeds.get(crop, 0) > 0
                actions.append(
                    roam_action(pos, tiles, spec["beat"], crop, day, hour,
                                have_seed, season_days)
                )
            else:
                inv = inventories[i] if i < len(inventories) else {}
                actions.append(
                    animal_worker_action(pos, tiles, inv, shed, spec["assign"],
                                         day, spec["shed"])
                )

        # Plant-atomicity gate: the sim voids ALL plants of a crop if the turn's
        # PLANT requests exceed seeds held. With duplicate crop workers, demote
        # the surplus to PASS so a real plant is never voided.
        planted: dict[str, int] = {}
        for idx, a in enumerate(actions):
            if isinstance(a, list) and len(a) >= 2 and a[0] == "PLANT":
                crop = a[1]
                if planted.get(crop, 0) < seeds.get(crop, 0):
                    planted[crop] = planted.get(crop, 0) + 1
                else:
                    actions[idx] = ["PASS"]

        farmer_action = actions[0]
        hand_actions = actions[1:]

        # --- Market: price-aware sells first, then dawn hires, then land/buys. ---
        live_animals = sum(
            1 for (t, _k) in (geese_assign + pasture_assign)
            if _is_animal(tiles[t[1]][t[0]])
        )
        wheat_buffer = max(WHEAT_FEED_BUFFER, live_animals + 4)
        market: list = price_aware_sell_orders(shed, market_inv, wheat_buffer=wheat_buffer)
        market = hire_orders + market

        # Buy the NE quadrant to unlock the bottomless wheat+egg spine's tiles.
        if ("NE" not in unlocked and day <= LAND_BUY_CUTOFF_DAY
                and money >= LAND_BUY_MONEY and len(market) < 10):
            market.append(["BUY_LAND"])

        # Seed restock: one per empty tile across each crop's active beats.
        for crop, beat in crop_beats.items():
            if len(market) >= 10:
                break
            if not plantable(crop, day, season_days):
                continue
            want = empty_tiles(tiles, beat) - seeds.get(crop, 0)
            if want <= 0:
                continue
            affordable = int(money // CROPS[crop]["seed"])
            buy = min(want, affordable)
            if buy > 0:
                market.append(["BUY_SEED", crop, buy])

        # Animal purchases (staggered, buffered so crops keep their capital).
        if day <= ANIMAL_BUY_CUTOFF_DAY:
            n_geese = _owns("GOOSE", tiles, geese_assign, shed, inventories)
            if (n_geese < len(geese_assign)
                    and money >= ANIMALS["GOOSE"]["cost"] + GOOSE_BUFFER
                    and len(market) < 10):
                market.append(["BUY_ANIMAL", "GOOSE", 1])
            n_cow = _owns("COW", tiles, pasture_assign, shed, inventories)
            want_cow = sum(1 for (_t, k) in pasture_assign if k == "COW")
            if (n_cow < want_cow and money >= ANIMALS["COW"]["cost"] + COW_BUFFER
                    and len(market) < 10):
                market.append(["BUY_ANIMAL", "COW", 1])
            n_sheep = _owns("SHEEP", tiles, pasture_assign, shed, inventories)
            want_sheep = sum(1 for (_t, k) in pasture_assign if k == "SHEEP")
            if (n_cow >= 1 and n_sheep < want_sheep
                    and money >= ANIMALS["SHEEP"]["cost"] + SHEEP_BUFFER
                    and len(market) < 10):
                market.append(["BUY_ANIMAL", "SHEEP", 1])

        # Feed top-up: keep the flock's wheat reserve stocked. Grown wheat usually
        # covers it; buy only the shortfall, never with crop working capital.
        wheat_on_hand = shed.get("WHEAT", 0) + sum(inv.get("WHEAT", 0) for inv in inventories)
        if (live_animals > 0 and wheat_on_hand < wheat_buffer and len(market) < 10
                and money >= COW_BUFFER):
            market.append(["BUY_PRODUCT", "WHEAT", wheat_buffer - wheat_on_hand])

        return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


STRATEGY = MarketFarmerStrategy
