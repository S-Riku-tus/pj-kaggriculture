"""Calibrated sparring opponent — the ladder field, not a candidate (issue #181).

Measured, not guessed. Profiled from 63 downloaded ladder replays, the 43
opponents that actually beat the submitted champion converge on one shape
(medians, sampled mid-day):

    day   melon  straw  wheat  planted  animals  hands  quads
      4      11      0      3       18        3      6      1
      8      12      3      0       20        4      7      1
     12       3     13      1       26        8      9      2
     16       2     15      4       27       10     10      3
     24       0     14      5       22       11     10      3   reward 66,640

The 20 opponents the champion beats never exceed 6 melon or 4 strawberry and
median 35,607 — the two populations separate cleanly on crop mix alone.

This strategy exists to make the benchmark able to express that shape. The five
`DEFAULT_ANCHORS` are swept 20/20 by the champion and **not one of them plants a
single strawberry**, so every paired experiment recorded in this repository was
scored against a saturated instrument (#181).

It is flagged ``benchmark = True``: never packaged by ``scripts/submit.py``
(ADR-0005) and never eligible for promotion (``harness.promotion.top_contender``).
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from kaggle_environments.envs.kaggriculture import kaggriculture as _sim

from kaggisim import economy
from strategies import catch_hands as ch
from strategies import hired_hands as hh

CROPS = hh.CROPS
SEASON_DAYS = hh.SEASON_DAYS

#: Day the measured field swings off melon and into strawberry. In the replays
#: melon is still 12 tiles at day 8 and down to 3 by day 12, while strawberry
#: goes 3 -> 13 over the same span, so the crossover sits at day 10.
PIVOT_DAY = 10

#: What the late tiles carry once strawberry can no longer finish. Wheat is the
#: field's own answer (3-5 tiles from day 20) and the only crop fast enough to
#: fully mature inside the tail.
LATE_CROP = "WHEAT"

#: Tiles the farm will run of each headline crop, from the replay medians (melon
#: 11-12, strawberry 13-15). The cap IS the archetype: both farms sell into one
#: shared market, and a farm that plants every tile it owns crashes the price it
#: is selling into -- measured, strawberry fell from 180 to 14 by day 28 at 25
#: tiles. Restraint is what the winning field does differently (#178).
CROP_CAP = {"MELON": 12, "STRAWBERRY": 15, "WHEAT": 5}


def crop_for_day(day: int, season_days: int = SEASON_DAYS, pivot: int = PIVOT_DAY):
    """The crop this farm plants on `day`, or ``None`` past the horizon.

    Melon before the pivot, strawberry after — the measured field's whole crop
    story. The horizon gate is the champion's own (`hired_hands.plantable`), so a
    seed is never spent on a plant that cannot reach first yield in time.
    `pivot` is the swing day (#252); the module default is the frozen `PIVOT_DAY`.
    """
    crop = "MELON" if day < pivot else "STRAWBERRY"
    if hh.plantable(crop, day, season_days):
        return crop
    # The measured field carries 3-5 wheat tiles through days 20-24, when
    # strawberry can no longer reach first yield. Wheat fills out in four days,
    # so it keeps the late tiles earning instead of idle -- and it doubles as
    # the herd's feed, which we otherwise buy.
    if ch.cc_plantable(LATE_CROP, day, season_days):
        return LATE_CROP
    return None


#: Crew cap. The measured field tops out at 10 hands (11 workers with the
#: farmer); the escalating fib wage makes a wider crew self-defeating (#33).
MAX_HANDS = 10

#: The measured ramps, as ``(from_day, target)`` breakpoints read straight off
#: the replay medians in the module docstring. A step table rather than a curve
#: fit: the numbers are a measurement, and a reader can check them against the
#: table above line by line.
HAND_RAMP = ((0, 6), (8, 7), (12, 9), (16, 10))
LAND_RAMP = ((0, 1), (12, 2), (16, 3))
ANIMAL_RAMP = ((0, 1), (4, 3), (8, 4), (12, 8), (16, 10), (24, 11))


def _ramp(table, day: int) -> int:
    """Value of a step table on `day` — the last breakpoint at or before it."""
    value = table[0][1]
    for from_day, target in table:
        if day >= from_day:
            value = target
    return value


def crop_for_plot(day: int, standing, season_days: int = SEASON_DAYS, caps=None, pivot=None):
    """The crop for one more empty tile, given what is already in the ground.

    The day's headline crop until its cap is met, then wheat: extra tiles are
    worth more filled with a crop whose market we are not already flooding.
    `pivot` is the swing day for a contender (#252); ``None`` keeps the frozen one.
    """
    caps = CROP_CAP if caps is None else caps
    crop = crop_for_day(day, season_days, PIVOT_DAY if pivot is None else pivot)
    if crop and standing.get(crop, 0) < caps.get(crop, 10 ** 6):
        return crop
    if (ch.cc_plantable(LATE_CROP, day, season_days)
            and standing.get(LATE_CROP, 0) < caps.get(LATE_CROP, 10 ** 6)):
        return LATE_CROP
    return None


def hire_target(day: int) -> int:
    """Hands to have working on `day` (6 -> 10 over the season)."""
    return _ramp(HAND_RAMP, day)


def land_target(day: int) -> int:
    """Quadrants to own on `day` (NW only, then NE by day 12, SW by day 16)."""
    return _ramp(LAND_RAMP, day)


def animal_target(day: int) -> int:
    """Livestock head to be running on `day` (1 -> 11 over the season)."""
    return _ramp(ANIMAL_RAMP, day)


#: Board is 10x10 split into four 5x5 quadrants; NW starts unlocked and the rest
#: are bought in the sim's fixed LAND_ORDER (NE, SW, SE). We never reach SE.
BOARD = 10
OWNED_QUADRANTS = ("NW", "NE", "SW")

#: The shed sits at the board centre and each quadrant touches it at exactly one
#: tile. NW's is (4, 4) -- the farmer's spawn and the only shed access we have
#: until day 12, which is why the early layout is packed tight around it.
SHED_ACCESS = {"NW": (4, 4), "NE": (5, 4), "SW": (4, 5), "SE": (5, 5)}

#: Two of the eleven workers run the livestock line; the rest tend crop clusters.
#: Indices 1 and 2 so the ramp's earliest hands are the herders -- the herd has
#: to be established before the crop area outgrows one quadrant.
LIVESTOCK_WORKERS = (1, 2)

#: Tiles per crop worker. Watering is only needed every other day (a plant dies
#: at ``consecutive_unwatered >= 2``), so three tiles fit comfortably inside one
#: worker's 24-turn day without the walk eating the schedule.
CLUSTER = 4


def quadrant_of(x: int, y: int) -> str:
    """The sim's own quadrant rule (`_quadrant_of`), mirrored for planning."""
    half = BOARD // 2
    return ("N" if y < half else "S") + ("W" if x < half else "E")


def _walk_cost(tile) -> int:
    """Manhattan steps from `tile` to its own quadrant's shed-access tile.

    Every trip a worker makes is to or from the shed, so this is the honest
    ordering key: it puts the tiles a worker can service quickly first.
    """
    x, y = tile
    sx, sy = SHED_ACCESS[quadrant_of(x, y)]
    return abs(x - sx) + abs(y - sy)


def _quadrant_tiles(quadrant: str):
    """Every tile of one quadrant, nearest-to-shed first."""
    tiles = [(x, y) for y in range(BOARD) for x in range(BOARD)
             if quadrant_of(x, y) == quadrant]
    return sorted(tiles, key=lambda t: (_walk_cost(t), t))


#: The five NW tiles closest to the shed become pasture: the livestock workers
#: round-trip to the shed for feed wheat every other day, so their walk is the
#: one that has to be short. Everything the herd needs before the day-12 land
#: buy (4 head) fits here; the rest of the block follows into NE.
PASTURE_TILES = tuple(_quadrant_tiles("NW")[1:6] + _quadrant_tiles("NE")[1:8])

#: Crop land is everything else we will ever own, nearest-to-shed first, NW
#: exhausted before NE and NE before SW -- which matches the measured field:
#: ~20 planted inside one quadrant by day 8, jumping to 26 when NE opens.
CROP_TILES = tuple(
    t for q in OWNED_QUADRANTS for t in _quadrant_tiles(q) if t not in PASTURE_TILES
)


def _crop_slot(worker: int, workers=LIVESTOCK_WORKERS):
    """Crop-cluster slot for a worker index, or ``None`` when it is herding.

    `workers` is who runs the livestock line this turn (#239); the module
    default is the benchmark's own pair, so `field_rival` stays frozen (#181).

    The slot LAYOUT is always the frozen one -- derived from
    `LIVESTOCK_WORKERS`, never from `workers` -- so an extra herder gives up
    only its own cluster and every other worker keeps the tiles it was already
    tending. Re-mapping the clusters mid-season would hand a worker standing
    plants it has never watered and orphan the ones it was watering, which is a
    second, unmeasured change on top of the labour split.
    """
    if worker in workers or worker in LIVESTOCK_WORKERS:
        return None
    return worker if worker < LIVESTOCK_WORKERS[0] else worker - len(LIVESTOCK_WORKERS)


def crop_cluster(worker: int, workers=LIVESTOCK_WORKERS, crops=CROP_TILES, cluster=CLUSTER):
    """The tiles worker `worker` is responsible for -- ``()`` for a herder.

    `crops` is the crop layout in slot order (#246); the module default is
    the frozen `CROP_TILES`, so `field_rival` stays frozen (#181). The slot
    LAYOUT still comes from `_crop_slot` -- a contender's layout changes which
    tiles a slot holds, never which worker holds a slot.
    `cluster` is tiles per crop worker (#252); the module default is the frozen `CLUSTER`.
    """
    slot = _crop_slot(worker, workers)
    if slot is None:
        return ()
    return crops[slot * cluster:(slot + 1) * cluster]


TURNS_PER_DAY = hh.TURNS_PER_DAY


def plot_action(tile, crop, day: int, hour: int):
    """The action for a worker standing on one of its crop tiles.

    Harvest before water before plant: a ready tile is money already earned, and
    an ongoing crop (strawberry) keeps offering HARVEST every time it regrows.
    Planting is refused on the final turn of the day -- a new plant carries
    ``consecutive_unwatered = 1`` and dies at 2, so it could never be watered.
    """
    if tile == "LOCKED":
        return ["PASS"]
    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        return ["DIG"]
    if tile is None:
        if crop and hour < TURNS_PER_DAY - 1:
            return ["PLANT", crop]
        return ["PASS"]
    if hh._is_live_plant(tile):
        if hh.harvest_ready(tile, day):
            return ["HARVEST"]
        if not tile.get("watered_today", False):
            return ["WATER"]
    return ["PASS"]


def nearest_shed(pos):
    """The shed-access tile a worker at `pos` can reach fastest.

    All four are usable from day one: the sim resolves shed operations before
    its LOCKED guard and allows movement onto locked tiles, precisely so a hand
    spawned on a locked access tile is never stranded.
    """
    return min(SHED_ACCESS.values(),
               key=lambda t: (abs(t[0] - pos[0]) + abs(t[1] - pos[1]), t))


#: Units a worker carries before it banks. The shed holds 100 items in total, so
#: produce only counts once it is dropped -- and a worker that hoards is a worker
#: whose harvest never reaches the market.
CARRY_LIMIT = 6

#: The sim accepts at most this many market orders in a single turn. Hires, the
#: land buy, animals, seed and sells all compete for the same ten slots, so the
#: order they are appended below IS the priority.
MAX_ORDERS = 10

#: Wheat a herder carries out of the shed in one trip. Each FEED spends one
#: wheat from the worker's own inventory, so this is how many animals a single
#: trip can serve.
FEED_CARRY = 8


def feed_buffer(animals: int) -> int:
    """Wheat to keep in the shed for a herd of `animals`.

    One wheat per animal per feeding, and an animal escapes at
    ``consecutive_unfed >= 2``. A fixed buffer starves the herd as it grows: the
    ramp kept buying and the animals kept escaping, holding steady at 8 of 11.
    """
    return max(FEED_CARRY, 2 * animals)

#: What the market will actually bid on -- taken from the simulator's own
#: PRODUCTS list rather than rebuilt here, so it cannot drift from it again.
#: Livestock is bought through the market but is not a product, so it is absent
#: and a SELL for a cow is a dead order.
#:
#: Fertilizer IS on this list, at a base of 100 -- above wheat, carrot and
#: tomato. An earlier version of this file excluded it as having "no market
#: bid"; what fertilizer is actually excluded from is the town centre, which is
#: a different thing. It is 17% of the winning field's season revenue (#157).
TRADABLE = tuple(_sim.PRODUCTS)

#: Cash held back from the herd for seed, wages and feed. The crop line is what
#: earns; livestock is bought only from what is left after it is funded.
CAPITAL_RESERVE = 1200

#: Animals we buy, cheapest first. Sheep are the better earner (200 vs 160) but
#: cost 500, so the herd starts on cows and upgrades as money allows.
HERD_MIX = ("COW", "SHEEP")


def _tile_at(tiles, tile):
    x, y = tile
    return tiles[y][x]


def crop_worker_action(cluster, tiles, pos, inv, crop, day, hour):
    """One crop worker's action: bank a full load, else tend the first tile in
    its cluster that wants something, else walk any leftovers back to the shed.
    """
    shed_tile = nearest_shed(pos)
    at_shed = [pos[0], pos[1]] == [shed_tile[0], shed_tile[1]]
    carrying = sum(inv.values()) if inv else 0

    if carrying >= CARRY_LIMIT:
        return ["DROP"] if at_shed else hh.step_toward(pos, shed_tile)

    # Nearest first, not cluster order: the cluster is sorted by distance from
    # the shed, which says nothing about where this worker is standing. Serving
    # the first tile in the list instead of the closest one put 52% of all
    # worker-turns into walking.
    best = None
    for tile in cluster:
        action = plot_action(_tile_at(tiles, tile), crop, day, hour)
        if action == ["PASS"]:
            continue
        dist = abs(tile[0] - pos[0]) + abs(tile[1] - pos[1])
        if dist == 0:
            return action
        if best is None or dist < best[0]:
            best = (dist, tile)
    if best is not None:
        return hh.step_toward(pos, best[1])

    if carrying:
        return ["DROP"] if at_shed else hh.step_toward(pos, shed_tile)
    return ["PASS"]


#: The frozen buy order: the crew, the land ramp, seed for every empty tile, and
#: the herd last out of the surplus. A contender may run the same four blocks in
#: another order through the `buy_order` seam (#254); sells stay first and feed
#: last either way.
BUY_ORDER = ("hires", "land", "seed", "herd")


def market_orders(day, hour, money, hands, quadrants, animals, shed, seeds,
                  empty_plots, standing=None, caps=None, prefer=None, target=None,
                  land=None, hire=None, reserve=None, pivot=None, order=None, floor=None,
                  feed=None):
    """This turn's market orders, in priority order under the 10-order cap.

    Sells come first: they are what funds everything below them, and a shed at
    its 100-item cap silently discards the next harvest. Then the crew, the land
    ramp and seed for every empty tile -- the crop line is what earns -- and the
    herd last, out of whatever surplus is left above ``CAPITAL_RESERVE``.

    `prefer`: an animal kind that overrides the budget rule for this turn's
    BUY_ANIMALs (#219); `None` keeps the benchmark's rule.

    `target`: head to be running on `day`, overriding `animal_target` for this
    turn (#237, used only by the placebo arm); `None` keeps the frozen ramp.

    `land`: quadrants to own today, or ``None`` for the frozen `land_target` ramp (#246).

    `hire`: hands to have working today, or ``None`` for the frozen `hire_target` ramp (#252).
    `reserve`: cash held back from the herd, or ``None`` for `CAPITAL_RESERVE` (#252).
    `pivot`: the crop swing day, or ``None`` for the frozen `PIVOT_DAY` (#252).
    `order`: the buy blocks to run and their order, or ``None`` for the frozen `BUY_ORDER` (#254).
    `floor`: cash every spending block after hires leaves unspent this turn -- land, seed and the herd alike -- or ``None`` for no floor (#258). Independent of `reserve`, which is the herd's own;
    hires (dawn, before anything else) and the feed top-up (what the floor is kept for) are exempt.

    `feed`: wheat the shed keeps for the herd, or ``None`` for the frozen `feed_buffer(animals)` (#262).
    """
    sells: list = []
    buys: list = []
    budget = money

    buffer = feed_buffer(animals) if feed is None else feed
    reserved = buffer if animals else 0
    for item, n in sorted(shed.items()):
        # Fertilizer has no market bid and livestock is not a tradable product,
        # so a SELL for either is a dead order burning one of the ten slots. The
        # herd's feed wheat must also survive the sweep -- selling it back would
        # just buy it again next turn.
        if item not in TRADABLE:
            continue
        keep = reserved if item == "WHEAT" else 0
        sell = int(n) - keep
        if sell > 0:
            sells.append(["SELL", item, sell])

    standing = standing or {}
    caps = CROP_CAP if caps is None else caps
    hold = 0 if floor is None else floor

    def hires():
        nonlocal budget
        if hour != 0:
            return
        want = max(0, (hire_target(day) if hire is None else hire) - hands)
        for k in range(1, want + 1):
            wage = hh.hand_wage(hands + k)
            if budget < wage:
                break
            buys.append(["HIRE"])
            budget -= wage

    def land_step():
        nonlocal budget
        want_land = land_target(day) if land is None else land
        if quadrants < want_land and quadrants - 1 < len(economy.LAND_COSTS):
            cost = economy.LAND_COSTS[quadrants - 1]
            if budget - cost >= hold:
                buys.append(["BUY_LAND"])
                budget -= cost

    def seed():
        nonlocal budget
        crop = crop_for_plot(day, standing, caps=caps, pivot=pivot)
        if crop and empty_plots > 0:
            # Never stock more seed of a capped crop than its remaining headroom:
            # buying 25 strawberry seeds to fill 25 tiles is how the price we sell
            # into gets crashed.
            cap = caps.get(crop)
            room = empty_plots if cap is None else max(0, cap - standing.get(crop, 0))
            want = max(0, min(empty_plots, room) - seeds.get(crop, 0))
            seed_cost = CROPS[crop]["seed"]
            buy = min(want, max(0, int((budget - hold) // seed_cost)))
            if buy > 0:
                buys.append(["BUY_SEED", crop, buy])
                budget -= buy * seed_cost

    def herd():
        nonlocal budget
        # The herd comes out of surplus only. Melon does not pay until day 10,
        # so a ramp that spends the opening bankroll leaves nothing for seed and
        # the farm never starts -- measured at 30 reward before this reserve
        # existed.
        #
        # An animal bought lands in the shed and only becomes livestock when a
        # herder walks it out to a pasture. Counting placed head alone re-buys
        # the whole ramp on every one of the day's 24 turns -- measured at 79
        # sheep filling a 100-item shed, which then silently discarded every
        # harvest.
        pending = sum(shed.get(kind, 0) for kind in HERD_MIX)
        want_head = animal_target(day) if target is None else target
        cash_floor = CAPITAL_RESERVE if reserve is None else reserve
        for _ in range(max(0, want_head - animals - pending)):
            kind = prefer or (HERD_MIX[1] if budget >= 3 * economy.ANIMALS[HERD_MIX[1]]["cost"]
                              else HERD_MIX[0])
            cost = economy.ANIMALS[kind]["cost"]
            if budget - cost < cash_floor or budget - cost < hold:
                break
            # The count is not optional: the sim's `_parse_order` rejects a
            # BUY_ANIMAL of length 2 and drops it without a word, which is
            # indistinguishable from having been unable to afford it.
            buys.append(["BUY_ANIMAL", kind, 1])
            budget -= cost

    steps = {"hires": hires, "land": land_step, "seed": seed, "herd": herd}
    names = BUY_ORDER if order is None else tuple(order)
    if len(set(names)) != len(names):
        raise ValueError(f"buy order repeats a block: {names}")
    for name in names:
        steps[name]()

    # Feed wheat for the herd -- bought, never grown, so the crop plan stays the
    # measured melon/strawberry pair.
    want_feed = buffer if animals else 0
    if want_feed and shed.get("WHEAT", 0) < want_feed:
        short = want_feed - shed.get("WHEAT", 0)
        buy = min(short, int(budget // CROPS["WHEAT"]["seed"]))
        if buy > 0:
            buys.append(["BUY_PRODUCT", "WHEAT", buy])

    # At dawn the whole crew is hired in one turn for under 150 in total wages,
    # and money carries overnight -- so the buys claim their slots first and the
    # sell sweep waits a turn. Any other hour, selling leads: the shed caps at
    # 100 items and silently discards whatever arrives after that.
    ordered = buys + sells if hour == 0 else sells + buys
    return ordered[:MAX_ORDERS]


def _pasture_chore(tile_xy, tile, pos, inv, shed, carry=FEED_CARRY):
    """The chore one pasture tile wants, or ``None`` when it is fully tended.

    A pure state machine over the tile's own fields: build it, stock it, then
    keep it harvested, fed and cared for. Feeding is the one that kills -- an
    animal escapes at ``consecutive_unfed >= 2`` -- and FEED spends wheat from
    the worker's own inventory, so the shed trip is part of the loop.

    `carry` is the wheat one shed trip takes (#262); the module default is the
    frozen `FEED_CARRY`.
    """
    on_it = [pos[0], pos[1]] == [tile_xy[0], tile_xy[1]]
    shed_tile = nearest_shed(pos)
    at_shed = [pos[0], pos[1]] == [shed_tile[0], shed_tile[1]]

    if tile == "LOCKED":
        return None
    if tile is None:
        return ["BUILD_PASTURE"] if on_it else hh.step_toward(pos, tile_xy)
    if not isinstance(tile, dict):
        return None

    if tile.get("kind") == "WEED":
        # #211: the sim weeds ANY empty tile at 0.005/day, and a pasture tile
        # starts empty. A weed is a dict with no "animal" key, so it used to
        # fall through to the place/fetch branch below and answer PLACE
        # forever -- and the sim's PLACE requires kind == "PASTURE", so on a
        # weed it is a SILENT no-op. The worker fetched an animal, walked out,
        # placed into nothing and repeated; first-match scanning meant it never
        # moved on to another tile either. DIG clears the tile back to None,
        # and the BUILD_PASTURE branch above recovers it on the next turn.
        return ["DIG"] if on_it else hh.step_toward(pos, tile_xy)

    if "animal" not in tile:
        for kind in HERD_MIX:
            if inv.get(kind, 0) > 0:
                return ["PLACE", kind] if on_it else hh.step_toward(pos, tile_xy)
        for kind in HERD_MIX:
            if shed.get(kind, 0) > 0:
                if at_shed:
                    return ["PICKUP", kind, 1]
                return hh.step_toward(pos, shed_tile)
        return None  # nothing bought yet; the market will see to it

    if tile.get("yield_units", 0) > 0:
        return ["HARVEST"] if on_it else hh.step_toward(pos, tile_xy)
    if not tile.get("fed_today", False):
        if inv.get("WHEAT", 0) > 0:
            return ["FEED"] if on_it else hh.step_toward(pos, tile_xy)
        if shed.get("WHEAT", 0) > 0:
            if at_shed:
                return ["PICKUP", "WHEAT", min(shed["WHEAT"], carry)]
            return hh.step_toward(pos, shed_tile)
        return None  # no feed anywhere; the market will buy some
    if not tile.get("cared_today", False) and on_it:
        return ["CARE"]  # never a trip just to care -- only a free turn on site
    if tile.get("fertilizer_available") and on_it:
        # Free byproduct: a turn, no land, no seed, no growing time, and it
        # clears at 100. Last in the order so it never displaces keeping the
        # animal alive -- an animal escapes at consecutive_unfed >= 2, whereas
        # fertilizer keeps.
        return ["COLLECT_FERTILIZER"]
    return None


def herd_worker_action(pastures, tiles, pos, inv, shed, hour, carry=FEED_CARRY):
    """One herder's action: the first pasture wanting something, else bank."""
    for tile_xy in pastures:
        chore = _pasture_chore(tile_xy, _tile_at(tiles, tile_xy), pos, inv, shed, carry)
        if chore is not None:
            return chore

    produce = sum(n for item, n in (inv or {}).items() if item != "WHEAT")
    if produce:
        shed_tile = nearest_shed(pos)
        if [pos[0], pos[1]] == [shed_tile[0], shed_tile[1]]:
            return ["DROP"]
        return hh.step_toward(pos, shed_tile)
    return ["PASS"]


def active_pastures(day: int, animals: int, count=None, block=PASTURE_TILES):
    """Pasture tiles in play today -- the ramp's target, never fewer than the
    head already on the board (an animal must keep being fed after the ramp
    flattens).

    `count`: how many tiles a contender wants standing this turn (#237);
    ``None`` keeps the benchmark's own rule, so field_rival stays frozen
    (#181). The tile ORDER is not a seam -- it is always the shed-adjacent
    prefix of the block either way. `block` is the pasture layout (#246); the
    module default is the frozen `PASTURE_TILES`.
    """
    if count is not None:
        return block[:count]
    return block[:max(animal_target(day), animals)]


def standing_crops(tiles) -> dict:
    """Live plants on the board, counted by crop."""
    counts: dict = {}
    for row in tiles:
        for t in row:
            if isinstance(t, dict) and t.get("kind") == "PLANT" and t.get("crop"):
                counts[t["crop"]] = counts.get(t["crop"], 0) + 1
    return counts


def count_animals(tiles) -> int:
    return sum(1 for row in tiles for t in row
               if isinstance(t, dict) and t.get("animal"))


def rival_sheep(obs) -> int:
    """How many sheep the OTHER farm has placed, read off its public tiles.

    #219: the one thing worth knowing about the rival is which shallow market
    they are about to flood, and wool (one shop) is the knife-edge one (#146).
    A weed is a dict with no "animal" key and a locked tile is a string; both
    count zero.

    Fail-safe (ADR-0006, whole-branch review): this runs on the same act()
    path the no-crash gate covers, so a malformed observation -- fewer than
    two farms, a non-dict farm, missing tiles -- degrades to 0 rather than
    raising IndexError/TypeError/AttributeError.
    """
    from kaggisim.state import opponent_farm
    try:
        them = opponent_farm(obs)
        if not isinstance(them, dict):
            return 0
        return sum(1 for row in (them.get("tiles") or []) for t in row
                   if isinstance(t, dict) and t.get("animal") == "SHEEP")
    except (LookupError, TypeError):
        return 0


class FieldRivalStrategy(Strategy):
    name = "field_rival"

    #: Readonly sparring opponent. `scripts/submit.py` refuses to package a
    #: benchmark strategy (ADR-0005) and `harness.promotion.top_contender`
    #: refuses to promote one -- this agent exists to be measured against, and
    #: must never become a submission by accident.
    benchmark = True

    #: The crop caps this agent runs. A class attribute so a contender can carry
    #: its own without touching this module's frozen defaults (#202); every
    #: helper above takes `caps` with the module default, so `field_rival`'s own
    #: decisions are unchanged -- pinned by tests/test_dense_farm.py.
    CAPS = CROP_CAP

    def herd_preference(self, obs):
        """The animal kind to buy this turn regardless of budget, or ``None``
        for the benchmark's own rule. A seam for contenders (#219); the
        benchmark itself never prefers, so its decisions stay frozen (#181)."""
        return None

    def pasture_count(self, day, animals):
        """How many pasture tiles to keep in play this turn, or ``None`` for
        the benchmark's own ramp-derived rule. A seam for contenders (#237).

        `animals` is the head already standing on the board
        (``count_animals(tiles)``) -- the *placed* count, which is the same
        number `active_pastures` compares the ramp against, so it is passed
        once rather than as two arguments that could disagree.
        """
        return None

    def herd_target(self, day):
        """Head to be running on `day`, or ``None`` for the frozen
        `animal_target` ramp. A seam for contenders (#237); on the benchmark
        it never fires, so its herd schedule stays frozen (#181)."""
        return None

    def livestock_workers(self, day):
        """Worker indices running the livestock line on `day`, or ``None`` for
        the frozen `LIVESTOCK_WORKERS` pair. A seam for contenders (#239).

        A worker named here herds instead of tending its own crop cluster; no
        other worker's cluster moves (see `_crop_slot`). On the benchmark it
        never fires, so the labour split stays frozen (#181).
        """
        return None

    def layout(self):
        """``(pasture_tiles, crop_tiles)`` for this farm, or ``None`` for the
        frozen `(PASTURE_TILES, CROP_TILES)`. A seam for contenders (#246).

        The pasture block is what `active_pastures` takes its prefix from and
        the crop tiles are what `crop_cluster` slices by slot; the two must be
        disjoint. On the benchmark it never fires, so its layout stays frozen
        (#181).
        """
        return None

    def land_target(self, day):
        """Quadrants to own on `day`, or ``None`` for the frozen `land_target`
        ramp. A seam for contenders (#246); on the benchmark it never fires,
        so its land schedule stays frozen (#181)."""
        return None

    def hire_target(self, day):
        """Hands to have working on `day`, or ``None`` for the frozen
        `hire_target` ramp. A seam for contenders (#252); on the benchmark it
        never fires, so its crew schedule stays frozen (#181)."""
        return None

    def capital_reserve(self, day=None, animals=None):
        """Cash held back from the herd, or ``None`` for `CAPITAL_RESERVE`. A
        seam for contenders (#252); `day` and `animals` (head placed) let a
        floor follow tomorrow's crew and today's herd (#256). Never fires on
        the benchmark."""
        return None

    def pivot_day(self):
        """The day the crop line swings from melon to strawberry, or ``None``
        for the frozen `PIVOT_DAY`. A seam for contenders (#252); never fires
        on the benchmark."""
        return None

    def cluster_size(self):
        """Tiles per crop worker, or ``None`` for the frozen `CLUSTER`. A seam
        for contenders (#252); never fires on the benchmark."""
        return None

    def buy_order(self):
        """The buy blocks to run and their order, or ``None`` for the frozen
        `BUY_ORDER`. A seam for contenders (#254); never fires on the benchmark."""
        return None

    def spend_floor(self, day=None, animals=None, shed=None, prices=None):
        """Cash every spending block after hires leaves unspent this turn, or
        ``None`` for no floor. A seam for contenders (#258): `day`, the placed
        head, the shed and the market prices let a floor follow tomorrow's crew
        and today's feed. Never fires on the benchmark."""
        return None

    def feed_carry(self, animals=None, herders=None):
        """Wheat a herder takes from the shed per trip, or ``None`` for the
        frozen `FEED_CARRY`. A seam for contenders (#262): `animals` is the head
        placed and `herders` how many workers run the livestock line. Never
        fires on the benchmark."""
        return None

    def feed_stock(self, animals=None):
        """Wheat the shed keeps for the herd -- held back from the sell sweep
        and topped up by the feed block -- or ``None`` for the frozen
        `feed_buffer`. A seam for contenders (#262); never fires on the benchmark."""
        return None

    def act(self, obs) -> dict:
        player = obs["player"]
        me = obs["farms"][player]
        private = obs["private"]
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        tiles = me["tiles"]
        hands = me.get("hands") or []
        shed = private.get("shed", {}) or {}
        seeds = private.get("seeds", {}) or {}
        inventories = private.get("inventories") or []

        standing = standing_crops(tiles)
        animals = count_animals(tiles)
        block, crops = self.layout() or (PASTURE_TILES, CROP_TILES)
        pivot = self.pivot_day()
        cluster_size = self.cluster_size()
        cluster = CLUSTER if cluster_size is None else cluster_size
        pastures = active_pastures(day, animals,
                                   count=self.pasture_count(day, animals), block=block)
        workers = self.livestock_workers(day) or LIVESTOCK_WORKERS
        herders = {worker: slot for slot, worker in enumerate(workers)}
        chosen_carry = self.feed_carry(animals, len(workers))
        carry = FEED_CARRY if chosen_carry is None else chosen_carry
        feed = self.feed_stock(animals)

        positions = [me["farmer"], *hands]
        used: dict = {}
        actions = []
        for i, pos in enumerate(positions):
            inv = inventories[i] if i < len(inventories) else {}
            if i in herders:
                mine = pastures[herders[i]::len(workers)]
                actions.append(herd_worker_action(mine, tiles, pos, inv, shed, hour, carry=carry))
                continue
            # Re-read the crop per worker: each plant this turn counts against
            # the cap immediately, so the crew cannot collectively overshoot it.
            crop = crop_for_plot(day, standing, caps=self.CAPS, pivot=pivot)
            mine = crop_cluster(i, workers, crops=crops, cluster=cluster)
            action = crop_worker_action(mine, tiles, pos, inv, crop, day, hour)
            if action[0] == "PLANT":
                # One seed per PLANT, and the sim silently no-ops a plant we
                # cannot pay for -- so a worker past the seed count would just
                # burn its turn.
                if used.get(crop, 0) < seeds.get(crop, 0):
                    used[crop] = used.get(crop, 0) + 1
                    standing[crop] = standing.get(crop, 0) + 1
                else:
                    action = ["PASS"]
            actions.append(action)

        empty = 0
        for i in range(len(positions)):
            for tile_xy in crop_cluster(i, workers, crops=crops, cluster=cluster):
                if _tile_at(tiles, tile_xy) is None:
                    empty += 1

        prices = (obs.get("market") or {}).get("prices") or {}
        market = market_orders(day, hour, me["money"], len(hands),
                               len(me.get("unlocked_quadrants") or ["NW"]),
                               animals, shed, seeds, empty, standing,
                               caps=self.CAPS, prefer=self.herd_preference(obs),
                               target=self.herd_target(day), land=self.land_target(day),
                               hire=self.hire_target(day), reserve=self.capital_reserve(day, animals),
                               pivot=pivot, order=self.buy_order(),
                               floor=self.spend_floor(day, animals, shed, prices), feed=feed)

        return {"farmer": actions[0], "hands": actions[1:], "market": market}


STRATEGY = FieldRivalStrategy
