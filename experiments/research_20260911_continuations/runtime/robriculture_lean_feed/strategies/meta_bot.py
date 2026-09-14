"""meta_bot — the FROZEN readonly benchmark, hard-coded to the field's top-Elo comp (#59).

This module is **not an experiment**. It is a fixed benchmark opponent
(``benchmark = True``, from the Task-1 base-class flag): always available as a
tournament / promotion opponent, but never eligible to be designated champion
(see ``harness.promotion``). Its job is to reproduce the *field's modal winner*
so our own agents are measured against the meta, not just against each other. It
must be **stable and actually stand up the herd** — it need not be optimal.

Provenance of every constant below: the Phase-0 feasibility spike recorded on
issue #59 (``.superpowers/.../task-3-report.md``), which drove a live episode of
the installed ``kaggle_environments`` kaggriculture sim to confirm the observed
comp is legal and reachable with zero substitutions. The recovered comp:

    9 COW (NE 3x3 block) + 4 SHEEP (SW row) + a melon / wheat-catch-crop crew
    + up to 9 hired hands (10 workers total) + fertilizer income from the herd
    starting day 2, land unlocked NW -> NE -> SW (skipping the $4000 SE).

Why this is more than a `ranch_hands` scale-up, and how the labor is routed
(the honest hard part — 13 animals under a 10-worker budget):

- **Land + pasture + placement setup.** Standing up 13 animals needs ``BUY_LAND``
  x2 (NE then SW, the sim's fixed order, $1000 + $2000 — a prerequisite before
  those tiles are buildable), then a free ``BUILD_PASTURE`` on each animal tile,
  then a ``PLACE``. All gated behind money buffers so the melon engine — which
  funds everything — is never starved. The herd therefore stands up *gradually*
  as melon income accrues (NE + cows first, then SW + sheep), which is expected
  from a $3000 start, not a defect.
- **Income-funded, never capital-funded.** From a $3000 start, buying land +
  13 animals up front bankrupts the melon engine before it earns a cent (melon's
  first yield is ~day 10). So every land / animal / feed purchase is gated behind
  a protected ``MELON_RESERVE`` of working capital: the herd stands up only from
  the *surplus* the melon crew has already banked, i.e. gradually from ~mid-game.
- **Five livestock hands that double as melon hands until their land opens.**
  The five highest worker indices (5-9 — the crew's farthest, lowest-value melon
  tiles) split the herd into small beats: three cover the 9 NE cows (3 each), two
  cover the 4 SW sheep (2 each). Until a beat's land is unlocked those hands
  simply farm their melon plot (no labor wasted idling — and land opens ~mid-game
  when melon is already closing); once it opens they peel off to livestock. Small
  beats are the whole point: a hand resets to the shed each night, so with only 2
  cow hands it could never re-walk, build, place AND feed 9 cows before some
  starved (an animal escapes after two unfed days). At 2-3 animals per hand every
  animal is comfortably fed and placed each day.
- **Fertilizer from day 2 = the free herd byproduct.** Phase-0's key refinement:
  the "fertilizer from day 2" the meta shows is the free ``COLLECT_FERTILIZER``
  animal byproduct (available the day after placement, up to 13 units/day), not
  ``BUY_PRODUCT``. Livestock hands collect it; it flushes to the shed overnight
  and either feeds the farmer's melon ``FERTILIZE`` loop (free, preferred) or
  clears as byproduct income. We ``BUY_PRODUCT FERTILIZER`` only as a fallback
  when the farmer's melon wants it and no free unit is on hand.

All decisions live in pure module-level helpers (``land_orders``,
``animal_buy_orders``, ``fertilizer_orders``, ``melon_plot_for``,
``livestock_action`` / ``animal_chore``, ``_sell_orders_keep_feed``) so they
unit-test without a full 720-turn game; ``act`` only wires them and clamps
``market[:10]``. Existing machinery is reused wherever it fits: the melon /
catch-crop micro-loop and hiring from ``catch_hands`` / ``wide_hands`` /
``hired_hands``, the livestock feed/harvest/care state-machine shape and the
feed-buffer sell rule from ``ranch_hands``, and the fertilize loop from
``fertilized_hands``.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies import catch_hands as ch
from strategies import fertilized_hands as fh
from strategies import hired_hands as hh
from strategies import ranch_hands as rh
from strategies import wide_hands as wh

# --- inherited machinery -----------------------------------------------------

MELON = ch.MELON
CROPS = ch.CROPS
SEASON_DAYS = ch.SEASON_DAYS

#: 9 hired hands => 10 workers total (farmer + 9). Phase-0 read of "10 hands" as
#: total headcount, matching our own promoted `wide_hands` empirical optimum.
MAX_HANDS = wh.MAX_HANDS  # 9

#: Melon plots — the champion's 10-tile NW crew (all x,y <= 4, collision-free
#: with the NE/SW animal blocks and the shed-access tiles).
MELON_PLOTS = wh.PLOTS

#: Only (4, 4) is an always-unlocked shed-access tile (the other three corners
#: sit on locked NE/SW/SE land where every tile op — PICKUP included — no-ops),
#: so all shed draws happen here. Reused from `ranch_hands`.
SHED_TILE = rh.SHED_TILE  # (4, 4)

ANIMAL_COST = rh.ANIMAL_COST  # {"COW": 400, "SHEEP": 500}

# --- the reachable comp (Phase-0 constants, task-3-report) -------------------

N_COW = 9
N_SHEEP = 4

#: The exact collision-free layout from Phase-0: a compact NE 3x3 cow block and
#: an SW 4-tile sheep row. Neither touches a shed-access tile or a melon plot.
ANIMAL_TILES: list = [
    ((5, 0), "COW"), ((6, 0), "COW"), ((7, 0), "COW"),
    ((5, 1), "COW"), ((6, 1), "COW"), ((7, 1), "COW"),
    ((5, 2), "COW"), ((6, 2), "COW"), ((7, 2), "COW"),
    ((0, 5), "SHEEP"), ((1, 5), "SHEEP"), ((2, 5), "SHEEP"), ((3, 5), "SHEEP"),
]
assert sum(1 for _, k in ANIMAL_TILES if k == "COW") == N_COW
assert sum(1 for _, k in ANIMAL_TILES if k == "SHEEP") == N_SHEEP

_COW_TILES = [t for t, k in ANIMAL_TILES if k == "COW"]
_SHEEP_TILES = [t for t, k in ANIMAL_TILES if k == "SHEEP"]

#: Worker indices that run a livestock beat once their land opens (until then
#: they farm their own melon plot). The crew's five farthest / lowest-value
#: tiles, so peeling them off costs the melon half the least.
LIVESTOCK_INDICES = (5, 6, 7, 8, 9)

#: The herd, partitioned into five small contiguous beats — three cow beats
#: (3 each, of the NE block) and two sheep beats (2 each) — so a hand can build,
#: place AND feed its whole beat within a day even after its nightly shed reset.
BEATS: dict = {
    5: [(t, "COW") for t in _COW_TILES[0:3]],
    6: [(t, "COW") for t in _COW_TILES[3:6]],
    7: [(t, "COW") for t in _COW_TILES[6:9]],
    8: [(t, "SHEEP") for t in _SHEEP_TILES[0:2]],
    9: [(t, "SHEEP") for t in _SHEEP_TILES[2:4]],
}

#: Land the two extra quadrants cost, in the sim's fixed unlock order (NE, SW,
#: SE); we buy the first two only. Transcribed from the sim (LAND_PRICES).
LAND_PRICES = [1000, 2000, 4000]

#: Melon working capital protected from every herd purchase (land, animals,
#: feed). The herd is funded only from surplus banked above this, so the melon
#: engine — which pays for everything — is never starved into a stall.
MELON_RESERVE = 2000
LAND_MONEY_BUFFER = MELON_RESERVE
ANIMAL_MONEY_BUFFER = MELON_RESERVE

#: Feed logistics: hold this much crop-wheat in the shed as herd feed, never
#: selling below it (a margin over the 13-animal daily need so five hands drawing
#: at once never leave a beat unfed). Each hand carries only its own beat's worth
#: per trip so it never hoards another beat's feed.
WHEAT_BUFFER = 20


# --- small predicates --------------------------------------------------------

def _on(pos, tile_pos) -> bool:
    return [pos[0], pos[1]] == [tile_pos[0], tile_pos[1]]


def _at_shed(pos) -> bool:
    return _on(pos, SHED_TILE)


def _is_animal(tile) -> bool:
    return isinstance(tile, dict) and "animal" in tile


def _is_empty_pasture(tile) -> bool:
    return isinstance(tile, dict) and tile.get("kind") == "PASTURE" and "animal" not in tile


def _needs_quadrant(kind: str) -> str:
    """The land quadrant an animal of `kind` is placed in (cows NE, sheep SW)."""
    return "NE" if kind == "COW" else "SW"


def _herd_exists(tiles, shed) -> bool:
    """True once any animal is placed on a tile or waiting in the shed — i.e. the
    herd needs a livestock crew hired to keep feeding it."""
    if shed.get("COW", 0) > 0 or shed.get("SHEEP", 0) > 0:
        return True
    return any(_is_animal(t) for row in tiles for t in row)


# --- land purchases ----------------------------------------------------------

def land_orders(unlocked, money: float, buffer: float = LAND_MONEY_BUFFER) -> list:
    """At most one ``BUY_LAND`` this turn, in the sim's fixed NE -> SW order.

    Each ``BUY_LAND`` unlocks the next quadrant in ``LAND_ORDER`` (NE, then SW,
    then SE). We buy exactly the first two (the cheapest two-quadrant expansion,
    skipping the $4000 SE), gated so a purchase never spends the melon engine's
    working capital below ``buffer``. Returns ``[]`` once NW+NE+SW are all owned.
    """
    n_extra = len(unlocked) - 1  # NW is always unlocked; 0 => only NW
    if n_extra >= 2:             # already own NE and SW — never reach for SE
        return []
    price = LAND_PRICES[n_extra]
    if money >= price + buffer:
        return [["BUY_LAND"]]
    return []


# --- animal purchases --------------------------------------------------------

def _count_existing(kind: str, tiles, shed, inventories) -> int:
    """How many animals of `kind` are already accounted for — placed on a tile,
    waiting in the shed, or held in a worker's inventory."""
    placed = sum(
        1 for row in tiles for t in row
        if isinstance(t, dict) and t.get("animal") == kind
    )
    in_shed = shed.get(kind, 0)
    in_inv = sum(inv.get(kind, 0) for inv in inventories)
    return placed + in_shed + in_inv


def animal_buy_orders(tiles, shed, inventories, money: float,
                      unlocked=("NW", "NE", "SW"), cap: int = 10) -> list:
    """``BUY_ANIMAL`` orders that stand up the herd, cows before sheep.

    Buys up to ``N_COW`` cows then ``N_SHEEP`` sheep, skipping any already placed
    / in the shed / in inventory, gated on the animal's land being unlocked and
    on money staying above ``ANIMAL_MONEY_BUFFER`` per unit. Capped at ``cap``
    orders (the caller passes the remaining market slots; the default 10 is the
    market cap) so these lowest-priority orders never displace a sell.
    """
    orders: list = []
    budget = money
    for kind, target in (("COW", N_COW), ("SHEEP", N_SHEEP)):
        if _needs_quadrant(kind) not in unlocked:
            continue
        have = _count_existing(kind, tiles, shed, inventories)
        for _ in range(max(0, target - have)):
            if len(orders) >= cap:
                return orders
            if budget < ANIMAL_COST[kind] + ANIMAL_MONEY_BUFFER:
                break
            orders.append(["BUY_ANIMAL", kind, 1])
            budget -= ANIMAL_COST[kind]
    return orders


# --- fertilizer (day-2 gate; prefer the free herd byproduct) -----------------

def fertilizer_orders(day: int, tiles, shed, inventories, money: float,
                      season_days: int = SEASON_DAYS) -> list:
    """A single fallback ``BUY_PRODUCT FERTILIZER`` for the farmer's melon, or ``[]``.

    Gated to ``day >= 2`` (Phase-0: the earliest the herd's free byproduct can be
    collected). Buys only when the farmer's melon (plot 0, the shed-adjacent tile
    that can PICKUP + FERTILIZE without abandoning its melon) actually wants
    fertilizer *and* none is already on hand — so a free unit the herd collected
    into the shed is always used before any is bought (``should_buy_fertilizer``
    returns False whenever the shed holds one). Reuses `fertilized_hands`.
    """
    if day < 2:
        return []
    farmer_inv = inventories[0] if inventories else {}
    farmer_tile = hh.tile_at(tiles, MELON_PLOTS[0])
    if fh.should_buy_fertilizer(farmer_tile, day, shed, farmer_inv, money, season_days):
        return [["BUY_PRODUCT", fh.FERTILIZER, 1]]
    return []


# --- market shaping ----------------------------------------------------------

def _sell_orders_keep_feed(shed) -> list:
    """Liquidate the shed, but hold back the herd's wheat feed buffer.

    Every sellable product clears in full except crop-WHEAT, which is sold only
    down to ``WHEAT_BUFFER`` (the feed the livestock hands draw on each dawn), so
    the wheat catch-crop harvest doubles as free feed. The `ranch_hands` rule,
    with the larger 13-animal buffer.
    """
    orders = []
    for order in hh.sell_orders(shed):
        if order[1] == "WHEAT":
            sellable = order[2] - WHEAT_BUFFER
            if sellable > 0:
                orders.append(["SELL", "WHEAT", sellable])
        else:
            orders.append(order)
    return orders


def wheat_orders(tiles, shed, inventories, money: float,
                 reserve: float = MELON_RESERVE, cap: int = 10) -> list:
    """A ``BUY_PRODUCT WHEAT`` top-up to the herd's feed buffer, or ``[]``.

    Fires only once the herd exists (an animal placed or waiting in the shed),
    when on-hand wheat is below ``WHEAT_BUFFER`` and money is above the melon
    reserve. Early game this is the only feed source; once the wheat catch-crop
    is harvesting, ``_sell_orders_keep_feed`` keeps the shed topped up and this
    rarely fires. Capped so it never displaces a sell.
    """
    if not _herd_exists(tiles, shed) or money < reserve:
        return []
    on_hand = shed.get("WHEAT", 0) + sum(inv.get("WHEAT", 0) for inv in inventories)
    want = min(WHEAT_BUFFER - on_hand, cap)
    if want <= 0:
        return []
    return [["BUY_PRODUCT", "WHEAT", want]]


# --- worker role assignment --------------------------------------------------

def melon_plot_for(i: int):
    """The melon plot for worker ``i`` — the plain wide-crew mapping.

    Every worker gets a melon plot (``MELON_PLOTS[i]``); the livestock indices
    farm theirs too, right up until their beat's land is unlocked and they peel
    off (see ``beat_active``). Indices past the crew clamp to the last plot.
    """
    return MELON_PLOTS[i] if i < len(MELON_PLOTS) else MELON_PLOTS[-1]


def beat_active(beat, unlocked) -> bool:
    """True when a livestock beat's land is unlocked, so its hand should switch
    from melon farming to tending the herd."""
    return _needs_quadrant(beat[0][1]) in unlocked


# --- livestock state machine -------------------------------------------------

def animal_chore(tile_pos, kind: str, pos, tiles, inv, shed, unlocked):
    """This turn's chore for ONE animal, or ``None`` when it wants nothing.

    A pure state machine over one tile: build the pasture, fetch + place the
    animal, then keep it fed / harvested / collected / cared. Returns ``None``
    whenever the animal is fully tended or blocked (waiting on the market / on
    land), so the caller can fall through to the next animal.
    """
    if _needs_quadrant(kind) not in unlocked:
        return None  # its land is not bought yet — nothing buildable here.
    ct = hh.tile_at(tiles, tile_pos)
    on = _on(pos, tile_pos)

    # --- Setup: pasture -> animal in hand -> placed. ---
    if not _is_animal(ct):
        if inv.get(kind, 0) > 0:
            return ["PLACE", kind] if on else hh.step_toward(pos, tile_pos)
        if ct is None:
            return ["BUILD_PASTURE"] if on else hh.step_toward(pos, tile_pos)
        if shed.get(kind, 0) > 0:  # empty pasture; fetch the bought animal.
            return ["PICKUP", kind, 1] if _at_shed(pos) else hh.step_toward(pos, SHED_TILE)
        return None  # not bought yet; the market will buy it.

    # --- Maintain the placed animal (feed is survival-critical, so it leads). ---
    if not ct.get("fed_today", False) and inv.get("WHEAT", 0) > 0:
        return ["FEED"] if on else hh.step_toward(pos, tile_pos)
    if ct.get("yield_units", 0) > 0:
        return ["HARVEST"] if on else hh.step_toward(pos, tile_pos)
    if ct.get("fertilizer_available", False):
        return ["COLLECT_FERTILIZER"] if on else hh.step_toward(pos, tile_pos)
    if not ct.get("cared_today", False) and on:
        return ["CARE"]  # never a trip just to care — only when already there.
    return None


def _hungry_tiles(beat, tiles):
    return [tp for tp, _ in beat if _is_animal(hh.tile_at(tiles, tp))
            and not hh.tile_at(tiles, tp).get("fed_today", False)]


def _empty_pastures(beat, tiles):
    return [tp for tp, _ in beat if _is_empty_pasture(hh.tile_at(tiles, tp))]


def livestock_action(pos, beat, tiles, inv, shed, unlocked):
    """One livestock hand's action this turn — never ``None``.

    Priority: (1) if its land isn't unlocked, idle toward the shed; (2) while at
    the shed, load the whole beat before walking out — first wheat to feed with,
    then any waiting animal an empty pasture needs — so one trip covers both and
    the last pasture is never orphaned by the feed-walk-out; (3) in the field,
    keep every animal FED (fetching wheat from the shed when empty-handed); (4)
    run the per-tile setup / maintain chore (build, place, harvest, collect
    fertilizer, care); (5) idle toward the beat. Feeding leads so no animal
    starves for setup work.
    """
    kind = beat[0][1]
    if _needs_quadrant(kind) not in unlocked:
        return hh.step_toward(pos, SHED_TILE)  # wait near the shed for the land.

    carry = len(beat)
    hungry = _hungry_tiles(beat, tiles)
    empties = _empty_pastures(beat, tiles)

    # (2) Load up at the shed: wheat first (survival), then a waiting animal, so a
    # single dawn trip carries out feed AND the next animal to place. Doing the
    # animal pickup here — rather than only when hungry — stops the feed-walk-out
    # from perpetually deferring the last pasture's placement.
    if _at_shed(pos):
        if hungry and inv.get("WHEAT", 0) < carry and shed.get("WHEAT", 0) > 0:
            want = min(shed["WHEAT"], carry - inv.get("WHEAT", 0))
            return ["PICKUP", "WHEAT", max(1, want)]
        if empties and inv.get(kind, 0) < len(empties) and shed.get(kind, 0) > 0:
            want = min(shed[kind], len(empties) - inv.get(kind, 0))
            return ["PICKUP", kind, max(1, want)]

    # (3) Feed — survival first. Feed from hand; else head to the shed for wheat.
    if hungry:
        if inv.get("WHEAT", 0) > 0:
            tp = hungry[0]
            return ["FEED"] if _on(pos, tp) else hh.step_toward(pos, tp)
        if shed.get("WHEAT", 0) > 0 and not _at_shed(pos):
            return hh.step_toward(pos, SHED_TILE)

    # (4) Per-tile setup / maintenance chore.
    for tp, k in beat:
        chore = animal_chore(tp, k, pos, tiles, inv, shed, unlocked)
        if chore is not None:
            return chore

    # (4) Idle toward the beat (PASS once there).
    return hh.step_toward(pos, beat[0][0])


# --- the strategy ------------------------------------------------------------

class MetaBotStrategy(Strategy):
    name = "meta_bot"
    benchmark = True

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
        unlocked = me.get("unlocked_quadrants", ["NW"])
        farmer_inv = inventories[0] if inventories else {}

        season_days = SEASON_DAYS
        catch = ch.choose_catch_crop(day, season_days)
        melon_open = hh.plantable(MELON, day, season_days)

        # --- Market: product SELLs FIRST so the price-sensitive melon/animal
        # sells sit ahead of HIRE/BUY orders and are never truncated by the
        # 10-order cap. Crop-wheat is held back to the herd's feed buffer. ---
        market: list = _sell_orders_keep_feed(shed)

        # --- Hire the crew (mornings only) — the multicrop wage rule, sized on
        # the full 10-worker target (up to 5 of them divert to livestock once
        # their land opens; until then they farm melon). ---
        n_hire = 0
        if hour == 0:
            n_hire = ch.plan_hands_multicrop(
                day, money, hh.max_live_index(tiles, MELON_PLOTS),
                catch, season_days, MAX_HANDS,
            )
            # Once the herd is up, always field the full crew so the livestock
            # hands (the high indices) are never dropped by the crop-driven wage
            # rule — an unhired hand feeds nothing, and the herd would starve out
            # in the tail after the crops close. Hiring is cheap (fib wage).
            if _herd_exists(tiles, shed):
                n_hire = MAX_HANDS
            market.extend([["HIRE"]] * n_hire)

        # --- One action per worker: livestock hands tend their beat; every other
        # worker runs the melon + wheat-catch-crop loop on its plot. ---
        positions = [me["farmer"], *hands]
        planted_this_turn: dict = {}
        actions = []
        for i, pos in enumerate(positions):
            if i in LIVESTOCK_INDICES and beat_active(BEATS[i], unlocked):
                inv = inventories[i] if i < len(inventories) else {}
                actions.append(livestock_action(pos, BEATS[i], tiles, inv, shed, unlocked))
                continue

            plot = melon_plot_for(i)
            if not _on(pos, plot):
                actions.append(hh.step_toward(pos, plot))
                continue

            tile = hh.tile_at(tiles, plot)
            # Farmer's shed-adjacent plot also runs the fertilize loop.
            if i == 0:
                fert = fh.fertilize_or_fetch(tile, day, farmer_inv, shed, season_days)
                if fert is not None:
                    actions.append(fert)
                    continue

            action = ch._decide(tile, day, hour, catch, season_days)
            if action and action[0] == "PLANT":
                crop = action[1]
                if planted_this_turn.get(crop, 0) < seeds.get(crop, 0):
                    planted_this_turn[crop] = planted_this_turn.get(crop, 0) + 1
                else:
                    action = ["WATER"] if hh._is_live_plant(tile) else ["PASS"]
            actions.append(action)

        farmer_action = actions[0]
        hand_actions = actions[1:]

        # --- Seed restock: melon in the melon phase, the catch crop in the tail.
        # (Livestock hands farm melon too until their land opens, so the whole
        # crew's plots count; a peeled-off hand just leaves a little idle seed.) ---
        total_workers = 1 + (n_hire if hour == 0 else len(hands))
        active_plots = min(len(MELON_PLOTS), total_workers)
        empty_active = sum(
            1 for plot in MELON_PLOTS[:active_plots] if hh.tile_at(tiles, plot) is None
        )
        restock = MELON if melon_open else catch
        if restock is not None and empty_active > 0 and len(market) < 10:
            want_seed = max(0, empty_active - seeds.get(restock, 0))
            if want_seed > 0:
                affordable = int(money // CROPS[restock]["seed"])
                buy = min(want_seed, affordable, 10 - len(market))
                if buy > 0:
                    market.append(["BUY_SEED", restock, buy])

        # --- Fertilizer: day-2 fallback buy for the farmer's melon (the free herd
        # byproduct, preferred, is collected by the livestock hands). ---
        if len(market) < 10:
            market.extend(fertilizer_orders(day, tiles, shed, inventories, money, season_days))

        # --- Herd feed: keep the wheat buffer stocked so placed animals never
        # starve (an animal escapes after two unfed days), funded from surplus. ---
        if len(market) < 10:
            market.extend(
                wheat_orders(tiles, shed, inventories, money, cap=10 - len(market))
            )

        # --- Land, then animals — lowest market priority so a sell is never
        # displaced. All funded from surplus above the melon reserve. Buy NE
        # (cows) then SW (sheep); cows before sheep. ---
        if len(market) < 10:
            market.extend(land_orders(unlocked, money))
        if len(market) < 10:
            market.extend(
                animal_buy_orders(tiles, shed, inventories, money, unlocked,
                                  cap=10 - len(market))
            )

        return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


STRATEGY = MetaBotStrategy
