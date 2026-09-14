"""neuropilot — NN-guided agent (neuroevolution Phase 1, ADR-0008, #64).

A small pure-Python MLP → knob controller; stdlib-only, fresh controller.
"""
from __future__ import annotations
import collections, json, math, os, random
from kaggisim import actions as acts
from kaggisim import economy
from kaggisim import pricing
from kaggisim.strategy import Strategy

TURNS_PER_DAY = economy.CONFIG_DEFAULTS["turnsPerDay"]
SEASON_DAYS = economy.CONFIG_DEFAULTS["episodeSteps"] // TURNS_PER_DAY
MAX_HANDS = 9
N_COW, N_SHEEP = 9, 4

# Ordered feature list — the plan pins this; changing order changes the genome contract.
_PRICE_ITEMS = ("MELON", "WHEAT", "MILK", "WOOL")

def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v

def _count_tiles(tiles, pred) -> int:
    return sum(1 for row in tiles for t in row if pred(t))

def features(state) -> list[float]:
    """Fixed-length normalized feature vector (never raises)."""
    try:
        me = state["farms"][state["player"]]
        opp = state["farms"][1 - state["player"]]
        day = state.get("day", 0); hour = state.get("hour", 0)
        tiles = me["tiles"]; money = me.get("money", 0)
        prices = state.get("market", {}).get("prices", {})
        shed = state.get("private", {}).get("shed", {})
        unlocked = me.get("unlocked_quadrants", ["NW"])
        hands = me.get("hands", []) or []
        n_crop = max(1, _count_tiles(tiles, lambda t: t is None) + _count_tiles(
            tiles, lambda t: isinstance(t, dict) and t.get("kind") == "PLANT"))
        f = [
            _clamp01(day / SEASON_DAYS),
            _clamp01(hour / TURNS_PER_DAY),
            _clamp01(1.0 - day / SEASON_DAYS),
            _clamp01(math.log1p(max(0, money)) / 12.0),
            _clamp01(money / (money + opp.get("money", 0) + 1.0)),
        ]
        for item in _PRICE_ITEMS:
            base = economy.base_price(item) or 1.0
            f.append(_clamp01((prices.get(item, base) / base) / 2.0))
        f += [
            _clamp01(_count_tiles(tiles, lambda t: t is None) / n_crop),
            _clamp01(_count_tiles(tiles, lambda t: isinstance(t, dict) and t.get("kind") == "PLANT") / n_crop),
            _clamp01(_count_tiles(tiles, lambda t: isinstance(t, dict) and t.get("kind") == "WEED") / max(1, n_crop)),
            _clamp01(_count_tiles(tiles, lambda t: isinstance(t, dict) and t.get("animal") == "COW") / N_COW),
            _clamp01(_count_tiles(tiles, lambda t: isinstance(t, dict) and t.get("animal") == "SHEEP") / N_SHEEP),
            1.0 if "NE" in unlocked else 0.0,
            1.0 if "SW" in unlocked else 0.0,
            _clamp01(len(hands) / MAX_HANDS),
            _clamp01(shed.get("MELON", 0) / 50.0),
            _clamp01(shed.get("WHEAT", 0) / 50.0),
            _clamp01(shed.get("FERTILIZER", 0) / 20.0),
        ]
        return f
    except Exception:
        return NEUTRAL_FEATURES

N_FEATURES = 20
NEUTRAL_FEATURES = [0.5] * N_FEATURES

H1 = 16
N_KNOBS = 8


def _sigmoid(z: float) -> float:
    if z < 0:
        e = math.exp(z); return e / (1.0 + e)
    return 1.0 / (1.0 + math.exp(-z))


def genome_size(n_in: int, h1: int, n_out: int) -> int:
    return (h1 * n_in + h1) + (n_out * h1 + n_out)


def random_genome(n_in: int, h1: int, n_out: int, seed: int) -> list[float]:
    r = random.Random(seed)
    return [r.uniform(-1.0, 1.0) for _ in range(genome_size(n_in, h1, n_out))]


class MLP:
    def __init__(self, w1, b1, w2, b2):
        self.w1, self.b1, self.w2, self.b2 = w1, b1, w2, b2

    @classmethod
    def from_genome(cls, genome, n_in, h1, n_out):
        i = 0
        w1 = [genome[i + j*n_in : i + (j+1)*n_in] for j in range(h1)]; i += h1*n_in
        b1 = genome[i:i+h1]; i += h1
        w2 = [genome[i + j*h1 : i + (j+1)*h1] for j in range(n_out)]; i += n_out*h1
        b2 = genome[i:i+n_out]
        return cls(w1, b1, w2, b2)

    def forward(self, features):
        h = [math.tanh(sum(w*x for w, x in zip(row, features)) + b)
             for row, b in zip(self.w1, self.b1)]
        return [_sigmoid(sum(w*x for w, x in zip(row, h)) + b)
                for row, b in zip(self.w2, self.b2)]


#: The evolved champion genome ships INSIDE the strategies package so it travels in
#: the submission tarball — build/package.py copies strategies/ (and kaggisim/), NOT
#: harness/. Without this, a submitted neuropilot would find no genome at eval time
#: and silently fall back to random weights. The harness path below is where the
#: evolution loop writes during dev; promoting a champion = copy it to _LOCAL_GENOME.
_LOCAL_GENOME = os.path.join(os.path.dirname(__file__), "champion_genome.json")
_GENOME_ARTIFACT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "harness", "genomes", "champion_genome.json")


def load_champion_genome(path=_GENOME_ARTIFACT):
    """The evolved champion genome if present and shape-correct, else None (never raises)."""
    try:
        with open(path) as fh:
            g = json.load(fh)["genome"]
        return g if len(g) == genome_size(N_FEATURES, H1, N_KNOBS) else None
    except Exception:
        return None


# Prefer the package-local champion (travels in the tarball); fall back to the
# harness artifact (in-repo dev), then to the seeded-random default.
_loaded = load_champion_genome(_LOCAL_GENOME) or load_champion_genome()
DEFAULT_GENOME = _loaded if _loaded is not None else random_genome(N_FEATURES, H1, N_KNOBS, seed=20260812)


# --- Knob decode (Task 3, #64) -----------------------------------------------
#
# `Knobs` names the MLP's 8 raw sigmoid outputs positionally; `decode_knobs` is
# an identity mapping (every output is already in [0,1]) — the *meaning* of
# each knob (e.g. hire_target as a fraction of MAX_HANDS) is interpreted by the
# controller below, not here. `livestock_pace`, `livestock_labor_share`,
# `herd_target_scale`, `capital_reserve` and `fertilize_pref` drive the
# livestock + fertilizer vocabulary (Task 4, below).

Knobs = collections.namedtuple(
    "Knobs",
    [
        "sell_throttle", "hire_target", "livestock_pace", "livestock_labor_share",
        "herd_target_scale", "fertilize_pref", "capital_reserve", "crop_mix",
    ],
)


def decode_knobs(raw: list[float]) -> Knobs:
    """Map the MLP's raw output vector positionally onto named, unit-range knobs."""
    vals = [_clamp01(v) for v in raw]
    if len(vals) < N_KNOBS:
        vals += [0.5] * (N_KNOBS - len(vals))
    return Knobs(*vals[:N_KNOBS])


# --- Minimal controller: crop farming + selling + hiring + seed (Task 3) ----
#
# Independent of every other strategy module (ADR-0008) — built only from
# kaggisim.state / kaggisim.economy / kaggisim.actions primitives, plus this
# module's own tiny helpers. Constants that mirror another strategy's layout
# (e.g. the NW crop-plot crew) are re-declared here BY VALUE, not imported.


#: A crop must reach first yield with at least this many days to spare before
#: the final day, or planting it just strands the tile (and its seed cost).
SELL_MARGIN_DAYS = 1

#: FERTILIZER is an INPUT, not a product: applying it grows crops, selling it
#: back is a round trip at a loss (#120). Instrumented over 719 turns the
#: champion bought 25 units, sold 25, and applied 1 -- the shed supply was
#: liquidated before any worker could reach it. Holding it also closes the
#: re-buy loop, because `_fertilizer_on_hand` then stays true and
#: `_fertilizer_buy_order` stops firing. ADR-0008's Phase-2 notes recorded
#: this as a TODO ("it dumps just-collected units") and it was never done.
_UNSELLABLE = frozenset({"FERTILIZER"})

#: Everything the market will actually buy from us, less what we want to keep.
_SELLABLE = frozenset(economy.MARKET_PARAMS) - _UNSELLABLE

#: The two crops the crop crew grows: melon (high value, slow) or wheat (cheap,
#: fast), chosen per-turn by `_crop_for` from the `crop_mix` knob.
_MELON, _WHEAT = "MELON", "WHEAT"
_CARROT, _STRAWBERRY, _TOMATO = "CARROT", "STRAWBERRY", "TOMATO"


def _step_toward(pos, target) -> list:
    """One MOVE (x first, then y) stepping `pos` toward `target`, else PASS.

    Mirrors the sim's coordinate convention: tiles are `tiles[y][x]`; farmer /
    hand positions are `[x, y]`; EAST/WEST move x, NORTH/SOUTH move y (NORTH
    decreases y, SOUTH increases it).
    """
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


def _on(pos, target) -> bool:
    return pos[0] == target[0] and pos[1] == target[1]


def _tile_at(tiles, plot):
    x, y = plot
    return tiles[y][x]


def _is_live_plant(tile) -> bool:
    return isinstance(tile, dict) and tile.get("kind") == "PLANT"


def _plantable(crop: str, day: int, season_days: int = SEASON_DAYS) -> bool:
    """Can `crop`, planted on `day`, reach first yield with a day to sell before
    the season ends?"""
    c = economy.CROPS[crop]
    final_day = season_days - 1
    return day + c["first"] + SELL_MARGIN_DAYS <= final_day


def _harvest_ready(tile, day: int) -> bool:
    """True when a standing plant holds yield and has reached first-yield age."""
    crop = tile.get("crop")
    c = economy.CROPS.get(crop)
    if not c or tile.get("yield_units", 0) <= 0:
        return False
    return day - tile.get("planted_day", day) >= c["first"]


#: The five crops the sim supports, ordered by rough season revenue per tile
#: (#127). Estimated as harvests x max_yield x base_price over a 30-day season,
#: where an `ongoing` crop keeps yielding on its interval and a one-shot crop
#: is replanted:
#:
#:     CARROT      2,100   one-shot, 2-day cycle
#:     WHEAT       2,250   one-shot, 2-day cycle
#:     MELON       4,500   one-shot, 10 days to a single 6-unit payout
#:     STRAWBERRY  5,280   ongoing, first yield day 10 then every 2 days
#:     TOMATO      5,520   ongoing, first yield day 8 then EVERY day
#:
#: Ordered rather than arbitrary so `crop_mix` reads as "commitment to a
#: higher-ceiling crop" and evolution sees a monotonic gradient. We grew only
#: MELON and WHEAT before this -- 2 of 5 crops, and neither of the two that
#: compound. `pilkwang`, which outscores us ~5x, sells 228 STRAWBERRY.
_CROP_LADDER = (_CARROT, _WHEAT, _MELON, _STRAWBERRY, _TOMATO)


def _crop_for(knobs: Knobs, day: int):
    """The crop to grow this turn, selected from `_CROP_LADDER` by `crop_mix`
    band, falling back down the ladder when the pick cannot still mature;
    `None` once nothing can (tail end of the season).

    `crop_mix` was a binary melon-or-wheat switch (#127 widened it). Same knob,
    same 472-weight genome -- reinterpreting it costs no interface bump, where
    adding a crop knob would restart evolution from random.

    Fallback order is *down* the ladder from the pick: a crop that can no
    longer reach first yield only strands the tile and its seed cost, and the
    cheaper, faster crops below are exactly the ones that can still finish.
    """
    n = len(_CROP_LADDER)
    idx = min(n - 1, int(_clamp01(knobs.crop_mix) * n))
    for i in range(idx, -1, -1):
        crop = _CROP_LADDER[i]
        if _plantable(crop, day):
            return crop
    return None


def _plot_action(tile, day: int, crop):
    """The action for a worker standing on its plot: dig a weed; plant `crop` on
    an empty plot; water an unwatered live plant; harvest a mature one; else
    pass. Seed-availability is enforced by the caller (`controller`)."""
    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        return ["DIG"]
    if tile is None:
        return ["PLANT", crop] if crop is not None else ["PASS"]
    if _is_live_plant(tile):
        # #137: water first when the plant would die at rollover. The sim turns
        # a plant with consecutive_unwatered >= 2 into a WEED, and the counter
        # increments for anything unwatered that day -- so one already at 1 is
        # on its last turn.
        #
        # Harvest used to preempt watering unconditionally. Harmless for a
        # one-shot crop, which becomes harvest-ready once near the end of its
        # natural life; fatal for an ONGOING one, which accrues yield EVERY day
        # after first yield, so every visit was spent harvesting and the plant
        # was never watered again. Measured: 75 of 77 tomatoes died as weeds at
        # a median age of 9 against a 12-day life, delivering one or two of
        # their four yields -- the whole of tomato's 888 reward against melon's
        # 8,995 (#127).
        #
        # A dead plant forfeits every remaining yield plus the seed. The
        # harvest only waits a turn, and the yield keeps accruing meanwhile.
        at_risk = tile.get("consecutive_unwatered", 0) >= 1
        if at_risk and not tile.get("watered_today", False):
            return ["WATER"]
        if _harvest_ready(tile, day):
            return ["HARVEST"]
        if not tile.get("watered_today", False):
            return ["WATER"]
    return ["PASS"]


def _sell_orders(shed: dict, market_inventory: dict, sell_throttle: float) -> list:
    """SELL orders liquidating the shed, deterministic (sorted by item).

    Each item's quantity comes from `kaggisim.pricing.sell_quantity` (#89),
    which walks the *marginal* realised price down that item's own market
    curve and stops once the next unit would clear below `sell_throttle` of
    its base price — a low `sell_throttle` sells freely (down to the market
    floor), a high one holds back hard. This replaces the old all-or-nothing
    dump, which only gated MELON (binarily, on a stale price ratio) and sold
    every other item's whole shed in one order regardless of market depth.
    Steep, shallow curves (MELON, WOOL — `above_func: "sq"`) get capped the
    hardest; deep curves (log/sqrt) clear in full at any sane threshold, so
    unifying the walk across every item costs those markets nothing.

    `sell_throttle` is a bare fraction-of-base *parameter*, not a constant
    baked into this function — the seam #90 (endgame liquidation, e.g. force
    it to 0 near the last day) and #91 (per-item reserve fractions, e.g.
    shrink `have` before the walk) build on without touching this walk.
    """
    orders = []
    for item in sorted(shed):
        have = shed.get(item, 0)
        if item not in _SELLABLE or have <= 0:
            continue
        base = economy.base_price(item) or 1.0
        inv = market_inventory.get(item, economy.MARKET_PARAMS[item]["I0"])
        qty = pricing.sell_quantity(item, inv, have, sell_throttle * base)
        if qty > 0:
            orders.append(["SELL", item, qty])
    return orders


# --- Livestock + fertilizer (Task 4, #64) ------------------------------------
#
# Fresh code, built only from kaggisim.actions / economy / this module's own
# helpers (no strategy imports, per ADR-0008). The sim mechanics below (unlock
# order, build->place->feed order, COLLECT_FERTILIZER, FERTILIZE being
# crop-only) are cross-checked against `meta_bot.animal_chore` /
# `meta_bot.livestock_action` (read for reference, never imported) and against
# the installed sim source (kaggle_environments/envs/kaggriculture/kaggriculture.py).

#: The reachable comp's layout: a compact NE 3x3 cow block and an SW 4-tile
#: sheep row — re-declared BY VALUE from `meta_bot.ANIMAL_TILES` (ADR-0008
#: forbids importing another strategy module).
ANIMAL_TILES: list = [
    ((5, 0), "COW"), ((6, 0), "COW"), ((7, 0), "COW"),
    ((5, 1), "COW"), ((6, 1), "COW"), ((7, 1), "COW"),
    ((5, 2), "COW"), ((6, 2), "COW"), ((7, 2), "COW"),
    ((0, 5), "SHEEP"), ((1, 5), "SHEEP"), ((2, 5), "SHEEP"), ((3, 5), "SHEEP"),
]
assert sum(1 for _, k in ANIMAL_TILES if k == "COW") == N_COW
assert sum(1 for _, k in ANIMAL_TILES if k == "SHEEP") == N_SHEEP

#: The one shed-access tile the crop crew also occupies (CROP_PLOTS[0]) — the
#: only corner every worker can reach a PICKUP/DROP from.
SHED_TILE = (4, 4)

#: Board quadrant bounds (inclusive), mirroring the sim's own
#: `_quadrant_of(x, y, board_size)` (board_size=10, half=5): N/S splits on
#: y < half, W/E splits on x < half. SE is included for completeness even
#: though `_land_order` never buys it -- no ANIMAL_TILES tile lives there.
_QUADRANT_BOUNDS = {
    "NW": (0, 4, 0, 4), "NE": (5, 9, 0, 4), "SW": (0, 4, 5, 9), "SE": (5, 9, 5, 9),
}

#: Positions occupied by the herd -- never crop-workable.
_ANIMAL_POSITIONS = frozenset(pos for pos, _ in ANIMAL_TILES)


def _manhattan(a, b) -> int:
    """L1 distance between two board positions (turns to walk, obstacle-free)."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _quadrant_tiles(quadrant: str) -> list:
    """Every tile in `quadrant` that isn't an animal structure's tile."""
    x0, x1, y0, y1 = _QUADRANT_BOUNDS[quadrant]
    return [
        (x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
        if (x, y) not in _ANIMAL_POSITIONS
    ]


#: Every quadrant's crop-eligible tiles, precomputed once at import -- pure
#: coordinates, no dependency on game state, so `crop_plots` only filters by
#: ownership and sorts each turn instead of rebuilding tile lists.
_ALL_QUADRANT_TILES = {q: _quadrant_tiles(q) for q in _QUADRANT_BOUNDS}


def crop_plots(unlocked) -> list:
    """Every crop-workable tile in the owned (`unlocked`) quadrants, nearest
    `SHED_TILE` first (#113 code, restored by #71 -- replaces the old
    hard-coded 10-tile NW-only `CROP_PLOTS`).

    Ordered by walking distance to the shed, ties broken by (x, y) for a
    deterministic layout. Distance, not quadrant, drives the order: a close
    NE/SW tile can sort ahead of a far NW one, so buying land can hand a
    worker a *shorter* walk than some NW tile it already had. `SHED_TILE` is
    always first (distance 0, and NW is always owned). Animal tiles are never
    included, so a crop plot can never collide with the herd; only tiles in
    `unlocked` quadrants appear, so a plot can never land on unbought land.
    Both properties are structural, not checked at use-time.
    """
    tiles = [t for q in unlocked for t in _ALL_QUADRANT_TILES.get(q, ())]
    tiles.sort(key=lambda t: (_manhattan(SHED_TILE, t), t[0], t[1]))
    return tiles


#: NW-only crop-plot ordering, nearest-first -- kept as a plain constant for
#: callers and tests that just need "the plot at index i with only the
#: starting quadrant owned". The controller calls `crop_plots(unlocked)`
#: fresh each turn, since ownership changes mid-game.
CROP_PLOTS = crop_plots(("NW",))

#: A knob-scaled money floor for livestock spend, sized against the season's
#: starting capital (mirrors `meta_bot.MELON_RESERVE`'s role, but dialed by
#: `capital_reserve` instead of fixed).
_MONEY_FLOOR_BASE = economy.CONFIG_DEFAULTS["startingMoney"]  # 3000


def _needs_quadrant(kind: str) -> str:
    """The land quadrant an animal of `kind` is placed in (cows NE, sheep SW)."""
    return "NE" if kind == "COW" else "SW"


def _is_animal(tile) -> bool:
    return isinstance(tile, dict) and "animal" in tile


def _animal_chore(tile_pos, kind: str, pos, tiles, inv: dict, shed: dict, unlocked):
    """This turn's chore for ONE animal tile, or `None` when it wants nothing.

    A pure state machine over one tile: build the pasture, fetch the bought
    animal from the shed and place it, then keep it fed / harvested /
    collected / cared. Feed leads maintenance — an animal escapes after two
    unfed days, so it is checked before harvest/collect/care. Mirrors
    `meta_bot.animal_chore` (the correctness reference for this state
    machine's shape; not imported).
    """
    if _needs_quadrant(kind) not in unlocked:
        return None  # its land isn't bought yet — nothing buildable here.
    tile = _tile_at(tiles, tile_pos)
    on = _on(pos, tile_pos)

    # --- #211: clear a weed before anything else. ---
    # The sim weeds ANY empty tile at 0.005/day and an animal tile starts
    # empty. A weed is a dict with no "animal" key, so `_is_animal` is False
    # and the setup branch below used to answer PLACE forever -- and the sim's
    # PLACE requires kind == "PASTURE", so on a weed it is a SILENT no-op,
    # stranding the tile and the animal for the rest of the game. DIG clears
    # it back to None, which the BUILD_PASTURE branch then recovers.
    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        return acts.dig() if on else _step_toward(pos, tile_pos)

    # --- Setup: pasture -> animal in hand -> placed. ---
    if not _is_animal(tile):
        if inv.get(kind, 0) > 0:
            return acts.place(kind) if on else _step_toward(pos, tile_pos)
        if tile is None:
            return acts.build_pasture() if on else _step_toward(pos, tile_pos)
        if shed.get(kind, 0) > 0:  # empty pasture; fetch the bought animal.
            return acts.pickup(kind, 1) if _on(pos, SHED_TILE) else _step_toward(pos, SHED_TILE)
        return None  # not bought yet; the market will buy it.

    # --- Maintain the placed animal. ---
    if not tile.get("fed_today", False) and inv.get("WHEAT", 0) > 0:
        return acts.feed() if on else _step_toward(pos, tile_pos)
    if tile.get("yield_units", 0) > 0:
        return acts.harvest() if on else _step_toward(pos, tile_pos)
    if tile.get("fertilizer_available", False):
        return acts.collect_fertilizer() if on else _step_toward(pos, tile_pos)
    if not tile.get("cared_today", False) and on:
        return acts.care()
    return None


def _animal_job_action(tile_pos, kind: str, pos, tiles, inv: dict,
                       shed: dict, unlocked) -> list:
    """The action for the worker assigned to ONE animal tile (never `None`).

    Replaces `_livestock_worker_action` + `_assign_beats` (#71): assignment
    hands out one tile at a time, so there is no beat to walk.

    Feed still leads -- an animal escapes after two unfed days -- so a hungry
    animal whose worker holds no WHEAT sends that worker to the shed first.
    Everything else falls through to `_animal_chore`, which covers setup
    (build the pasture, fetch the bought animal, place it) as well as
    tending; that path is the *only* route to standing a herd up now that the
    `livestock_labor_share` worker-peel is gone.
    """
    tile = _tile_at(tiles, tile_pos)
    hungry = _is_animal(tile) and not tile.get("fed_today", False)
    if hungry and inv.get("WHEAT", 0) <= 0 and shed.get("WHEAT", 0) > 0:
        return acts.pickup("WHEAT", 1) if _on(pos, SHED_TILE) else _step_toward(pos, SHED_TILE)
    chore = _animal_chore(tile_pos, kind, pos, tiles, inv, shed, unlocked)
    if chore is not None:
        return chore
    return acts.pass_() if _on(pos, tile_pos) else _step_toward(pos, tile_pos)


#: Flat-dollar reserve added to price, deliberately *not* scaled by price
#: (#100). #97's `price * 4 * (1/pace - 1)` buffer looked right on paper but
#: was calibrated against nothing observed: it demanded ~$37,000 at the
#: evolved genome's actual pace (~0.097) and ~$77,000 at pace 0.05, while the
#: champion never accumulates more than ~$17,900-$39,000 across a full
#: 720-turn game (harness/production_report.py measurement, #95/#96/#101) —
#: every pace value evolution actually visited was unaffordable, so the
#: "gradient" was flat and fitness-invisible in practice.
#:
#: #100 recalibrates by measurement instead of intuition. `production_report`
#: shows `pilkwang` (outscores us ~9:1) buying both its $1,000 and $2,000
#: quadrants near-broke, days apart, at similar low-thousands cash levels —
#: and our own `meta_rancher` buying both quadrants the same day at similar
#: cash levels too ($10.4k then $4.8k, *less* for the pricier SW). Buffer
#: size tracks observed reserve behaviour, not sale price, so it's additive
#: rather than multiplicative: at pace 0.05 (the highest pace the #97 run
#: ever visited despite it being a dead gene) the buffer is $15,200, putting
#: the ~$16,200 NE requirement and ~$17,200 SW requirement both inside the
#: observed money envelope — reachable late in a game, not never.
_LAND_RESERVE = 800.0


def _land_order(unlocked, money: float, pace: float) -> list:
    """At most one `BUY_LAND` this turn, paced continuously by `livestock_pace`
    (#97 — no hard cliff; #100 — the buffer's *size* recalibrated against
    measured money, not mathematics).

    The required money buffer above price is `_LAND_RESERVE * (1/pace - 1)`:
    at pace 1.0 the buffer is 0 (buy as soon as affordable, matching the
    near-broke external competitor `pilkwang`); it grows without bound as
    pace falls toward 0, monotonically, with no discontinuity anywhere in
    (0, 1] — every pace value has *some* money level that buys, so a genome
    below the old hard 0.5 gate has a gradient to climb instead of a flat,
    fitness-invisible region. `pace` is floored at a small epsilon so the
    formula stays defined (never divides by zero) at pace == 0.

    This is deliberately *not* a hard cutoff, but low pace still behaves as
    "late, not casual" inside one 720-turn game: at pace 0.05 the buffer
    alone is $15,200, close to the top of the champion's observed money
    range — reachable only once cash has actually accumulated, not from
    turn one, so `pace` still means something across the band evolution
    explores instead of every value buying immediately (the mirror-image
    failure mode: too shallow, and the knob stops mattering).

    Follows the sim's fixed NE -> SW unlock order (`kaggisim.economy.LAND_COSTS`),
    capped at those two extra quadrants — no `ANIMAL_TILES` tile lives in the
    $4000 SE quadrant, so it's never worth buying (mirrors `meta_bot.land_orders`'
    `n_extra >= 2` guard, by value, not import). `[]` once NE and SW are both
    owned.
    """
    n_extra = len(unlocked) - 1  # NW is always unlocked; 0 => only NW owned
    if n_extra < 0 or n_extra >= 2:
        return []  # already own NE and SW — never reach for the $4000 SE
    price = economy.LAND_COSTS[n_extra]
    p = max(pace, 1e-6)  # guard div-by-zero; keeps the curve continuous, not a gate
    buffer = _LAND_RESERVE * (1.0 / p - 1.0)
    if money >= price + buffer:
        return [["BUY_LAND"]]
    return []


def _herd_targets(knobs: Knobs) -> tuple:
    """(cow_target, sheep_target) toward `herd_target_scale` of the full
    13-animal comp, cows filled first, each capped at its species maximum."""
    total = max(0, round(knobs.herd_target_scale * (N_COW + N_SHEEP)))
    cow = min(N_COW, total)
    sheep = min(N_SHEEP, max(0, total - N_COW))
    return cow, sheep


def _count_existing(kind: str, tiles, shed: dict, inventories: list) -> int:
    """How many animals of `kind` are already accounted for — placed on a
    tile, waiting in the shed, or held in a worker's inventory."""
    placed = sum(
        1 for row in tiles for t in row
        if isinstance(t, dict) and t.get("animal") == kind
    )
    in_shed = shed.get(kind, 0)
    in_inv = sum(inv.get(kind, 0) for inv in inventories)
    return placed + in_shed + in_inv


def _animal_orders(knobs: Knobs, tiles, shed: dict, inventories: list,
                    money: float, unlocked, cap: int) -> list:
    """`BUY_ANIMAL` orders toward the herd targets, cows before sheep.

    Gated on the animal's land quadrant being unlocked and on money staying
    above a `capital_reserve`-scaled floor per unit; capped at `cap` orders
    (the caller passes the remaining market slots) so these lowest-priority
    orders never displace a sell. Mirrors `meta_bot.animal_buy_orders`.
    """
    cow_target, sheep_target = _herd_targets(knobs)
    floor = knobs.capital_reserve * _MONEY_FLOOR_BASE
    orders: list = []
    budget = money
    for kind, target in (("COW", cow_target), ("SHEEP", sheep_target)):
        if _needs_quadrant(kind) not in unlocked:
            continue
        have = _count_existing(kind, tiles, shed, inventories)
        for _ in range(max(0, target - have)):
            if len(orders) >= cap:
                return orders
            cost = economy.ANIMALS[kind]["cost"]
            if budget < cost + floor:
                break
            orders.append(["BUY_ANIMAL", kind, 1])
            budget -= cost
    return orders


def _wants_fertilizer(tile, day: int) -> bool:
    """True when `tile` is a live plant not already fertilizer-covered for
    `day` (a fresh unit would otherwise be wasted). FERTILIZE is crop-only —
    this mirrors the sim's own `kind == "PLANT"` gate."""
    if not _is_live_plant(tile):
        return False
    return tile.get("fertilized_until_day", -1) < day


def _fertilize_or_fetch(tile, day: int, inv: dict, shed: dict):
    """The fertilizer action for the shed-adjacent farmer plot (CROP_PLOTS[0],
    which doubles as a shed-access tile), or `None`.

    Applies straight from inventory when a unit is held; otherwise `PICKUP`
    one from the shed (legal here only because this plot is shed-adjacent).
    Mirrors `fertilized_hands.fertilize_or_fetch`.
    """
    if not _wants_fertilizer(tile, day):
        return None
    if inv.get("FERTILIZER", 0) > 0:
        return acts.fertilize()
    if shed.get("FERTILIZER", 0) > 0:
        return acts.pickup("FERTILIZER", 1)
    return None


def _fertilizer_on_hand(inventories, shed: dict) -> bool:
    """True when a fertilizer unit exists anywhere we can still act on it --
    in the shed, or already in some worker's hands (#120).

    Enumeration used to ask `_fertilize_or_fetch` with a hardcoded EMPTY
    inventory, which made the fertilize job conditional on the SHED alone. So
    the moment a worker picked a unit up the shed emptied, the job stopped
    being enumerated, and that worker was reassigned still carrying it --
    permanently. Measured over 719 turns the champion bought FERTILIZER 21
    times, sold it 22, and applied it 0. Asking "does a unit exist anywhere"
    is the question both call sites actually need.
    """
    if shed.get("FERTILIZER", 0) > 0:
        return True
    return any(inv.get("FERTILIZER", 0) > 0 for inv in (inventories or ()))


def _fertilize_duty_period(fertilize_pref: float) -> int:
    """Turn the old `fertilize_pref >= 0.5` on/off gate into a continuous
    duty-cycle period, in days (#97).

    `period = round(1 / pref)`: at pref 1.0 every day is a fertilize day
    (period 1); as pref falls the period grows and fertilize days get
    sparser, but never reach zero of them — a pref below the old 0.5 gate
    still gets *some* fertilize days instead of none, monotonically fewer as
    pref falls. `fertilize_pref` is a sigmoid output so it never lands on
    exactly 0.0, but the `<= 0.0` branch keeps the function total (a huge,
    not infinite, period) rather than raising.
    """
    p = _clamp01(fertilize_pref)
    if p <= 0.0:
        return 10**9
    return max(1, round(1.0 / p))


def _is_fertilize_day(fertilize_pref: float, day: int) -> bool:
    """True on the duty-cycle days `_fertilize_duty_period` selects."""
    return day % _fertilize_duty_period(fertilize_pref) == 0


# --- #71: jobs replace the worker-index -> plot mapping ---------------------
#
# The old controller sent worker `i` to `CROP_PLOTS[i]`. There was no notion
# of travel cost, of which job was worth most this turn, or of who was
# nearest to what -- so a worker could walk past a harvest-ready melon to
# reach "its" bare tile, and a newly-bought quadrant's tiles were reachable
# only by workers whose index happened to land on them. Every agent we own
# peaks at 10-11 planted tiles regardless of land owned; `pilkwang` reaches
# 51. Enumerate the work, then assign it.

#: What one turn of a crop tile is nominally worth. Every other value is
#: expressed relative to this, so it is the unit rather than a tunable.
CROP_JOB_VALUE = 1.0

#: Animal-job value at `livestock_labor_share` = 1.0. At the midpoint 0.5 an
#: animal job is worth exactly one crop job, so the knob's old "what fraction
#: of effort goes to the herd" meaning survives the reinterpretation.
ANIMAL_JOB_SCALE = 2.0

#: Value lost per tile of walking. At 0.05 the longest walk on a 10x10 board
#: (18 tiles) costs 0.9 -- just under one crop job, so distance decides
#: between comparable jobs but never outranks a genuinely better one.
#: A constant, not a knob: a ninth knob would be a versioned genome interface
#: bump, restarting evolution from random to tune one scalar.
TRAVEL_COST = 0.05

#: Job kinds that mean "work the animal on this tile". The species doubles as
#: the job kind because `_animal_chore` already takes it as its `kind` arg.
_ANIMAL_KINDS = frozenset(("COW", "SHEEP"))

#: One piece of work: where it is, what kind, and what it is worth this turn.
Job = collections.namedtuple("Job", ["pos", "kind", "value"])


def _crop_tile_has_work(tile, day, crop) -> bool:
    """True when a worker standing on this crop tile would actually do
    something -- dig a weed, plant an empty tile while a crop can still
    mature, or water/harvest a live plant. `_plot_action` is already
    position-independent, so this asks the question directly."""
    return _plot_action(tile, day, crop)[0] != "PASS"


def _animal_tile_has_work(tile_pos, kind: str, tiles, shed: dict, unlocked) -> bool:
    """True when this animal tile still wants something done to it.

    Asked with an EMPTY inventory on purpose: the question is "does this tile
    want work", not "can this particular worker do it". The hunger clause is
    required because `_animal_chore`'s feed branch is gated on the worker
    already holding WHEAT, so a hungry animal would otherwise read as no work
    whenever nobody happens to be carrying any.
    """
    tile = _tile_at(tiles, tile_pos)
    if (_is_animal(tile) and not tile.get("fed_today", False)
            and shed.get("WHEAT", 0) > 0):
        return True
    return _animal_chore(tile_pos, kind, tile_pos, tiles, {}, shed, unlocked) is not None


def candidate_jobs(state, knobs: Knobs) -> list:
    """Every piece of work the farm owns this turn, best-valued first.

    Pure and deterministic. Positions are unique across the returned list --
    animal tiles are excluded from `crop_plots` at construction, and the
    fertilize job *replaces* the shed tile's crop job rather than sitting
    beside it -- so `assign_workers` can never route two workers to one tile.

    Only tiles with actual work are enumerated (#71 review finding 1): every
    crop job carries the same `CROP_JOB_VALUE`, so `_job_score` reduces to
    `value - TRAVEL_COST * distance` and a worker standing on ANY crop tile
    always outscores every other tile -- greedy would hand each worker the
    tile under its feet forever, which is the exact camping #71 exists to
    break. Filtering by "does this tile want work" (not touching values) lets
    a worker whose tile has gone idle become available for real work
    elsewhere, while a null result still means "assignment didn't help"
    rather than "our pricing was wrong".

    Values are deliberately crude: this experiment tests whether *assignment*
    unlocks the land, not whether we can price work correctly. Ranking jobs by
    what they are actually worth is #119.
    """
    player = state.get("player", 0)
    me = state["farms"][player]
    day = state.get("day", 0)
    unlocked = me.get("unlocked_quadrants", ["NW"])
    tiles = me["tiles"]
    private = state.get("private", {})
    shed = private.get("shed", {})
    inventories = private.get("inventories", [])
    crop = _crop_for(knobs, day)

    fertilize_day = _is_fertilize_day(knobs.fertilize_pref, day)
    jobs = []
    for pos in crop_plots(unlocked):
        tile = _tile_at(tiles, pos)
        if (pos == SHED_TILE and fertilize_day and _wants_fertilizer(tile, day)
                and _fertilizer_on_hand(inventories, shed)):
            # Only the shed-adjacent tile can PICKUP + FERTILIZE without
            # leaving, so it is the only tile this job can ever be at. The
            # shed tile yields at most one job -- FERTILIZE here, or the
            # ordinary CROP rule below -- never both.
            jobs.append(Job(pos, "FERTILIZE", CROP_JOB_VALUE + knobs.fertilize_pref))
        elif _crop_tile_has_work(tile, day, crop):
            jobs.append(Job(pos, "CROP", CROP_JOB_VALUE))
    for pos, kind in ANIMAL_TILES:
        if _needs_quadrant(kind) in unlocked and _animal_tile_has_work(pos, kind, tiles, shed, unlocked):
            jobs.append(Job(pos, kind, ANIMAL_JOB_SCALE * knobs.livestock_labor_share))
    # Ties break positionally so the order never depends on how the lists
    # above happened to be built (ADR-0005).
    jobs.sort(key=lambda j: (-j.value, j.pos))
    return jobs


def _job_score(pos, job: Job) -> float:
    """What `job` is worth to the worker standing at `pos`: its value less
    the walk needed to reach it."""
    return job.value - TRAVEL_COST * _manhattan(pos, job.pos)


def assign_workers(positions, jobs) -> list:
    """Give each worker its best remaining job; `None` when none is left.

    Greedy: workers are served in index order, each takes the unclaimed job
    maximising `_job_score`, and a claimed job is never reassigned. Returns
    one entry per worker, in worker order, so the caller can zip it against
    `positions`.

    Deterministic (ADR-0005): `jobs` arrives in a fixed order from
    `candidate_jobs` and `max` keeps the first of any tie, so the same state
    always produces the same assignment.

    Greedy rather than optimal (Hungarian) matching is deliberate: it is
    O(workers x jobs) on single-digit worker counts, stdlib-only, and easy to
    reason about. Optimal matching is not obviously worth the complexity
    before we know assignment helps at all.
    """
    remaining = list(jobs)
    assigned = []
    for pos in positions:
        if not remaining:
            assigned.append(None)
            continue
        best = max(remaining, key=lambda j: _job_score(pos, j))
        remaining.remove(best)
        assigned.append(best)
    return assigned


def _fertilizer_buy_order(knobs: Knobs, state, cap: int) -> list:
    """A single fallback `BUY_PRODUCT FERTILIZER` for the farmer's crop plot,
    or `[]`.

    Scaled by `fertilize_pref` via a duty-cycle frequency (#97: no hard 0.5
    gate) and fires only when the plot's crop actually wants fertilizer *and*
    neither the shed nor the farmer's own inventory already holds a free
    unit — the herd's `COLLECT_FERTILIZER` byproduct is always preferred over
    spending money. Mirrors `meta_bot.fertilizer_orders` /
    `fertilized_hands.should_buy_fertilizer`.
    """
    day = state.get("day", 0)
    if cap <= 0 or not _is_fertilize_day(knobs.fertilize_pref, day):
        return []
    player = state.get("player", 0)
    me = state["farms"][player]
    private = state.get("private", {})
    tiles = me["tiles"]
    shed = private.get("shed", {})
    inventories = private.get("inventories", [])
    tile = _tile_at(tiles, CROP_PLOTS[0])
    if not _wants_fertilizer(tile, day):
        return []
    # #120: any worker's held unit suppresses re-buying, not just the
    # farmer's. Checking inventories[0] alone meant a unit stranded in a
    # hand's inventory never stopped the next purchase.
    if _fertilizer_on_hand(inventories, shed):
        return []
    price = economy.base_price("FERTILIZER") or 1.0
    if me.get("money", 0) < price:
        return []
    return [["BUY_PRODUCT", "FERTILIZER", 1]]


def _livestock_market_orders(knobs: Knobs, state, market_len: int) -> list:
    """Livestock + fertilizer market orders, lowest priority.

    `BUY_LAND` (paced by `livestock_pace`), then `BUY_ANIMAL` toward
    `round(herd_target_scale * (N_COW + N_SHEEP))` (cows before sheep), then a
    fallback fertilizer buy — capped at the market slots the caller has left
    (`maxMarketOrdersPerTurn - market_len`) so these never displace a sell,
    hire or seed order.
    """
    cap = max(0, economy.CONFIG_DEFAULTS["maxMarketOrdersPerTurn"] - market_len)
    if cap <= 0:
        return []
    player = state.get("player", 0)
    me = state["farms"][player]
    private = state.get("private", {})
    money = me.get("money", 0)
    tiles = me["tiles"]
    unlocked = me.get("unlocked_quadrants", ["NW"])
    shed = private.get("shed", {})
    inventories = private.get("inventories", [])

    orders: list = _land_order(unlocked, money, knobs.livestock_pace)[:cap]
    if len(orders) < cap:
        orders += _animal_orders(
            knobs, tiles, shed, inventories, money, unlocked, cap - len(orders)
        )
    if len(orders) < cap:
        orders += _fertilizer_buy_order(knobs, state, cap - len(orders))
    return orders[:cap]


def controller(knobs: Knobs, state) -> dict:
    """A legal `{"farmer", "hands", "market"}` turn from decoded knobs + state.

    Worker roles: `candidate_jobs` enumerates every piece of work the farm
    owns this turn and `assign_workers` gives each worker its best unclaimed
    one, discounted by the walk to reach it (#71). This replaced a fixed
    `worker i -> CROP_PLOTS[i]` mapping that could not route anyone onto
    newly-bought land, and a `livestock_labor_share` peel that split workers
    into crop and herd crews before either had been costed.
    Market: budgeted by priority against `maxMarketOrdersPerTurn` (#117) --
    sells lead and are never truncated, then the seed the assigned crop
    workers need this turn (skip it and planting stalls), then hires up to
    `hire_target * MAX_HANDS` new hands (mornings only, capped to whatever's
    left after sells + seed), then livestock/fertilizer orders fill the rest.
    """
    player = state.get("player", 0)
    me = state["farms"][player]
    private = state.get("private", {})
    day = state.get("day", 0)
    hour = state.get("hour", 0)
    money = me.get("money", 0)
    tiles = me["tiles"]
    hands = me.get("hands", []) or []
    seeds = private.get("seeds", {})
    shed = private.get("shed", {})
    market_inventory = state.get("market", {}).get("inventory", {})
    unlocked = me.get("unlocked_quadrants", ["NW"])
    inventories = private.get("inventories", [])

    crop = _crop_for(knobs, day)

    # --- Jobs: enumerate the work, then assign it (#71). ---
    positions = [me["farmer"], *hands]
    assignment = assign_workers(positions, candidate_jobs(state, knobs))

    planted_this_turn: dict = {}
    actions = []
    for i, (pos, job) in enumerate(zip(positions, assignment, strict=True)):
        inv = inventories[i] if i < len(inventories) else {}
        if job is None:
            # More workers than jobs: passing is legal and safe (ADR-0006).
            actions.append(acts.pass_())
            continue
        if job.kind in _ANIMAL_KINDS:
            actions.append(_animal_job_action(job.pos, job.kind, pos, tiles,
                                              inv, shed, unlocked))
            continue
        # CROP and FERTILIZE both work a crop tile; walk there first.
        if not _on(pos, job.pos):
            actions.append(_step_toward(pos, job.pos))
            continue
        tile = _tile_at(tiles, job.pos)
        action = None
        if job.kind == "FERTILIZE":
            # `_fertilize_or_fetch` returns None when there is nothing to
            # fertilize or fetch, in which case the tile is farmed normally --
            # the same fall-through the old duty-cycle gate had.
            action = _fertilize_or_fetch(tile, day, inv, shed)
        if action is None:
            action = _plot_action(tile, day, crop)
        if action[0] == "PLANT":
            # Only plant as many of `crop` this turn as we hold seed for, or
            # the sim's atomic-plant rule voids every plant of the crop at once.
            planted_crop = action[1]
            if planted_this_turn.get(planted_crop, 0) < seeds.get(planted_crop, 0):
                planted_this_turn[planted_crop] = planted_this_turn.get(planted_crop, 0) + 1
            else:
                action = ["WATER"] if _is_live_plant(tile) else ["PASS"]
        actions.append(action)

    farmer_action = actions[0]
    hand_actions = actions[1:]

    # --- Market: budget by priority against the cap (#117) — sells first
    # (CLAUDE.md: they must never be the ones truncated), then the seed this
    # turn's crop crew needs (skip it and planting stalls, idling the whole
    # engine), then hire, then livestock/fertilizer (lowest priority). Hire
    # is deliberately last even though it's emitted before seed in the list:
    # reaching `hire_target * MAX_HANDS` is a multi-turn target, not a
    # same-turn requirement, so it is what absorbs overflow. To make that
    # true we must know the seed order (and reserve its slot) BEFORE sizing
    # hire, even though seed is appended to the list after hire.
    cap = economy.CONFIG_DEFAULTS["maxMarketOrdersPerTurn"]
    market: list = _sell_orders(shed, market_inventory, knobs.sell_throttle)

    seed_order = None
    if crop is not None and len(market) < cap:
        # Count the tiles workers are actually assigned to, not a prefix of
        # CROP_PLOTS: assignment decides who farms what, so it also decides
        # how much seed this turn needs.
        empty_active = sum(
            1 for j in assignment
            if j is not None and j.kind in ("CROP", "FERTILIZE")
            and _tile_at(tiles, j.pos) is None
        )
        want_seed = max(0, empty_active - seeds.get(crop, 0))
        if want_seed > 0:
            seed_cost = economy.CROPS[crop]["seed"]
            affordable = int(money // seed_cost) if seed_cost > 0 else want_seed
            buy = min(want_seed, affordable, cap - len(market))
            if buy > 0:
                seed_order = ["BUY_SEED", crop, buy]
    seed_reserved = 1 if seed_order is not None else 0

    if hour == 0:
        hire_budget = max(0, cap - len(market) - seed_reserved)
        n_hire = min(max(0, round(knobs.hire_target * MAX_HANDS)), hire_budget)
        market.extend([["HIRE"]] * n_hire)

    if seed_order is not None:
        market.append(seed_order)

    if len(market) < cap:
        market.extend(_livestock_market_orders(knobs, state, len(market)))

    return {"farmer": farmer_action, "hands": hand_actions, "market": market[:cap]}


class NeuroPilotStrategy(Strategy):
    """The NN-driven agent: MLP -> knobs -> controller. Full legal vocabulary —
    crop farming, selling, hiring, livestock (land/pasture/place/feed/harvest/
    collect) and fertilizer (#64) — weak by design (random default weights),
    but legal and crash-free under `ROBRICULTURE_STRICT=1` (the Phase-1
    milestone)."""

    name = "neuropilot"
    benchmark = False

    def __init__(self, genome=None):
        g = genome if genome is not None else DEFAULT_GENOME
        self.mlp = MLP.from_genome(g, N_FEATURES, H1, N_KNOBS)

    def act(self, state) -> dict:
        knobs = decode_knobs(self.mlp.forward(features(state)))
        return controller(knobs, state)


STRATEGY = NeuroPilotStrategy
