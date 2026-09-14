"""Two crews, one bank account: the crop line AND the herd, both at full size.

Experiment for issue #196, ADR-0007.

#157 decomposed 63 real ladder matches. Our crop line is the strongest thing in
that data -- 55,958 median revenue against the winning field's 28,361 -- and we
earn none of the 60,154 they take from livestock and fertilizer. Two attempts
have each taken one half and dropped the other:

                         planted  animals  livestock share   vs champion
    neuropilot (ours)         62        0               0%   --
    balanced_farm (#193)      20        7              51%   69%

#187 explains why the obvious combination failed. It is not that the champion
lacks livestock machinery -- it has all of it -- but that **one crew shares one
job queue**. `candidate_jobs` sorts ties by position and `assign_workers` keeps
the first, so an animal job worth the same as a crop job loses every tie to the
low-coordinate crop tiles: 13 FEED actions a season against the field's 153.
Raise the animal job's value instead and workers abandon the 62-tile crop line
and the farm collapses.

The fix here is structural rather than another weighting. **The ranch gets its
own workers.** The crop brain keeps the champion's genome, its knobs and its
whole job queue, and simply never sees the tail of the crew; the ranch crew is
driven straight from `_animal_job_action` against `ANIMAL_TILES`. Neither can
starve the other, because they never bid for the same worker.

That is safe because the two tile sets are disjoint: `crop_plots` returns 62
tiles, `ANIMAL_TILES` 13, and their intersection is empty -- the champion's own
controller already reserves the animal land.

Three things the champion left switched off are switched on, and no more:

- `hire_target` to full strength. The field runs 11 workers to our 8, and a
  split crew needs the bodies.
- `herd_target_scale` off its evolved ~0.0098, which `_herd_targets` rounds to
  zero animals for the entire game.
- **feed**. `neuropilot`'s only `BUY_PRODUCT` is FERTILIZER; it never buys
  wheat, so FEED finds an empty shed and the herd starves at
  `consecutive_unfed >= 2` unless `crop_mix` happens to pick wheat.

`livestock_labor_share` is deliberately **not** touched. Raising it is what
collapsed #187, and giving the ranch its own crew removes any need to.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies import neuropilot as npx

#: Workers dedicated to the herd, taken from the tail of the crew. Worker 0 is
#: the farmer, who spawns shed-adjacent and is the crop brain's best unit.
#: Three covers 13 animal tiles at the field's observed feeding cadence.
RANCH_WORKERS = 3

#: Crew size below which nobody is diverted. Peeling a worker off a two-hand
#: farm costs crop tiles for a herd we cannot yet afford.
MIN_CREW_BEFORE_SPLIT = 6

#: Animals to keep. The field holds 10-11 from day 16 (#157); the champion's
#: reachable comp is 13 (N_COW 9 + N_SHEEP 4).
TARGET_HERD = 11

#: Wheat per animal. One per FEED, and an animal escapes at
#: `consecutive_unfed >= 2`, so two covers a feeding plus the trip back.
FEED_PER_ANIMAL = 2

MAX_ORDERS = npx.economy.CONFIG_DEFAULTS["maxMarketOrdersPerTurn"]


def ranch_indices(n_workers: int) -> tuple:
    """Worker indices assigned to the herd -- the tail of the crew, or none."""
    if n_workers < MIN_CREW_BEFORE_SPLIT:
        return ()
    return tuple(range(max(1, n_workers - RANCH_WORKERS), n_workers))


def floor_knobs(knobs):
    """The champion's knobs with the crew and the herd switched on.

    Floors, not pins: where the network already asks for more it keeps
    authority. `livestock_labor_share` is passed through untouched on purpose --
    raising it is what collapsed #187, and a dedicated crew makes it moot.
    """
    herd_floor = TARGET_HERD / (npx.N_COW + npx.N_SHEEP)
    if knobs.hire_target >= 1.0 and knobs.herd_target_scale >= herd_floor:
        return knobs
    return knobs._replace(
        hire_target=max(knobs.hire_target, 1.0),
        herd_target_scale=max(knobs.herd_target_scale, herd_floor),
    )


def feed_orders(animals: int, shed, money: float, price: int, room: int) -> list:
    """A `BUY_PRODUCT WHEAT` order when the herd is short of feed.

    Appended only into slots the controller left free, so feed can never
    displace a sell. Length three is not optional -- the sim's `_parse_order`
    discards a shorter order without a word, which reads exactly like being
    unable to afford it.
    """
    if animals <= 0 or room <= 0:
        return []
    short = FEED_PER_ANIMAL * animals - int((shed or {}).get("WHEAT", 0))
    if short <= 0:
        return []
    buy = min(short, int(money // max(1, price)))
    return [["BUY_PRODUCT", "WHEAT", buy]] if buy > 0 else []


#: Wheat a ranch worker loads in one visit to the shed. The champion's
#: `_animal_job_action` fetches ONE per trip, and the animal tiles sit 4-5 tiles
#: from the shed, so each feeding cost a ~10-turn round trip: measured, 1,127
#: walking actions against 14 FEED in a season, for a herd wanting ~5.5 feeds a
#: day. Carrying a load turns that into one trip per several feedings.
CARRY_FEED = 6


def shed_pickup(pos, inv, shed, animals: int):
    """A bulk `PICKUP WHEAT` for a ranch worker standing at the shed, or None.

    Only fires at the shed, only with a herd to feed, and only when the worker
    is not already carrying a useful load -- so it costs a turn the worker was
    going to spend walking away empty-handed anyway.
    """
    if animals <= 0:
        return None
    if [pos[0], pos[1]] != [npx.SHED_TILE[0], npx.SHED_TILE[1]]:
        return None
    # An animal waiting in the shed outranks feed: both are picked up at the
    # same tile, so loading wheat first means walking away without the cow on
    # every visit, and the herd never grows past whatever was placed before the
    # first feed run.
    if any((shed or {}).get(kind, 0) > 0 for kind in ("COW", "SHEEP")):
        return None
    available = int((shed or {}).get("WHEAT", 0))
    if available <= 0:
        return None
    if int((inv or {}).get("WHEAT", 0)) >= min(CARRY_FEED, animals):
        return None
    return ["PICKUP", "WHEAT", min(CARRY_FEED, available)]


def tile_priority(candidates, tiles, inv, shed, unlocked) -> list:
    """`candidates` that still want work, most urgent first.

    Three bands, and the ordering is the whole point of this function:

    1. **A hungry placed animal.** It escapes at `consecutive_unfed >= 2`,
       losing the entire 400-500 purchase. Nothing outranks that.
    2. **Standing a pasture up** -- building it, fetching the bought animal,
       placing it. Capital before income.
    3. **Everything else** -- harvest, care, collecting fertilizer.

    Without this ordering a first-match scan never leaves band 3, because
    `COLLECT_FERTILIZER` regenerates every day: a tile holding an animal is
    never "done", so the worker harvests the byproduct of the herd it already
    has and never builds the rest of it. Measured that way, 3 animals were
    placed all season while 6 cows and 2 sheep sat unplaced in the shed.
    """
    banded = []
    for tile_pos, kind in candidates:
        if not wants_work(tile_pos, kind, tiles, inv, shed, unlocked):
            continue
        tile = npx._tile_at(tiles, tile_pos)
        if npx._is_animal(tile):
            band = 0 if not tile.get("fed_today", False) else 2
        else:
            band = 1
        banded.append((band, tile_pos, kind))
    banded.sort(key=lambda b: (b[0], b[1]))
    return [(pos, kind) for _, pos, kind in banded]


def wants_work(tile_pos, kind, tiles, inv, shed, unlocked) -> bool:
    """Does this animal tile still want something from a worker?

    Asks `_animal_chore`, which returns None when the tile is fully tended.
    `_animal_job_action` is the wrong question here: it never returns None -- it
    always yields *some* action, a walk included -- so using it to test for work
    pins each ranch worker to its first tile for the whole game. Measured that
    way: exactly 3 pastures and 3 animals a season, one per ranch worker, while
    six cows and two sheep sat unplaced in the shed.
    """
    chore = npx._animal_chore(tile_pos, kind, tile_pos, tiles, inv, shed, unlocked)
    return chore is not None


class SplitBrainStrategy(Strategy):
    """The champion's crop brain, plus a ranch crew of its own."""

    name = "splitbrain"
    benchmark = False

    def __init__(self, genome=None):
        g = genome if genome is not None else npx.DEFAULT_GENOME
        self.mlp = npx.MLP.from_genome(g, npx.N_FEATURES, npx.H1, npx.N_KNOBS)

    def act(self, state) -> dict:
        knobs = floor_knobs(npx.decode_knobs(self.mlp.forward(npx.features(state))))
        action = npx.controller(knobs, state)

        player = state.get("player", 0)
        me = state["farms"][player]
        hands = me.get("hands") or []
        positions = [me["farmer"], *hands]
        ranch = ranch_indices(len(positions))
        if not ranch:
            return action

        private = state.get("private") or {}
        shed = private.get("shed") or {}
        inventories = private.get("inventories") or []
        tiles = me["tiles"]
        unlocked = me.get("unlocked_quadrants") or ["NW"]

        # Each ranch worker owns a stride of the animal tiles, so two never walk
        # to the same pasture and every tile is somebody's responsibility.
        animals_now = sum(1 for row in tiles for t in row
                          if isinstance(t, dict) and t.get("animal"))
        hand_actions = list(action.get("hands") or [])
        for slot, worker in enumerate(ranch):
            mine = npx.ANIMAL_TILES[slot::len(ranch)]
            inv = inventories[worker] if worker < len(inventories) else {}
            pos = positions[worker]
            chosen = shed_pickup(pos, inv, shed, animals_now) or ["PASS"]
            if chosen != ["PASS"]:
                if worker - 1 < len(hand_actions):
                    hand_actions[worker - 1] = chosen
                continue
            for tile_pos, kind in tile_priority(mine, tiles, inv, shed, unlocked):
                chosen = npx._animal_job_action(tile_pos, kind, pos, tiles,
                                                inv, shed, unlocked)
                break
            if worker - 1 < len(hand_actions):
                hand_actions[worker - 1] = chosen
        action["hands"] = hand_actions

        market = list(action.get("market") or [])
        animals = animals_now
        prices = (state.get("market") or {}).get("prices") or {}
        market += feed_orders(animals, shed, me.get("money", 0),
                              int(prices.get("WHEAT", 25)), MAX_ORDERS - len(market))
        action["market"] = market[:MAX_ORDERS]
        return action


STRATEGY = SplitBrainStrategy
