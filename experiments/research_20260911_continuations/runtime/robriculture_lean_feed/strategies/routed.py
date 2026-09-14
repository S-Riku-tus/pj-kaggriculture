"""Multi-tile nearest-task routing (experiment #9, ADR-0007).

The single technique under test, layered on `greedy_horizon`'s melon-loop:

**Nearest-task routing across several tiles.** One farmer, one action per turn,
so every wasted MOVE is a lost productive action. `greedy_horizon` works a
*single* tile next to the shed and then PASSes ~23 of every 24 turns — the
farmer is almost entirely idle. Here the same economic loop runs over a small
cluster of tiles instead: every turn we gather the pending tasks across all
managed tiles (harvest a ripe plant, water a dry one, plant an empty one, dig a
weed, or carry produce back to the shed), pick the *nearest* one, and either do
it (if we are standing on its tile) or take one step toward it. Ordering work by
nearest task keeps the walking short, so a single idle-heavy farmer can tend
many melon tiles and out-earn the one-tile champion.

Everything economic is held fixed from `greedy_horizon` — the crop ranking, the
horizon-aware plantability gate, harvest timing, continuous shed liquidation,
and end-game behavior are imported unchanged. The lone variable is *how many
tiles a single farmer services and in what order*, so any win-rate delta versus
`greedy_horizon` attributes to the routing technique alone.

Decisions live in pure module-level helpers (`manhattan`, `step_toward`,
`nearest_task`, `route_action`, `managed_tiles`) so the routing logic is
unit-tested without a full game.
"""

from __future__ import annotations

from kaggisim import economy
from kaggisim.strategy import Strategy
from strategies.greedy_horizon import (
    SEASON_DAYS,
    _has_produce,
    _should_harvest,
    choose_crop,
    sell_orders,
)

CROPS = economy.CROPS

#: The board is 10x10 with four 5x5 quadrants; only the NW quadrant (x,y in
#: 0..4) is unlocked at the start. The single shed-access tile inside NW is its
#: inner corner (4,4) — the only place a farmer can DROP produce into the shed,
#: and the farmer's spawn. We route everything back here to sell.
SHED_TILE = (4, 4)

#: How many tiles a single farmer services. Tuned empirically against
#: `greedy_horizon`: enough tiles to multiply melon output well past the
#: one-tile champion, few enough that every tile still gets its daily watering
#: (a plant left unwatered two days in a row turns to a weed).
NUM_TILES = 6

#: NW quadrant bounds (inclusive).
_NW_MAX = 4


def manhattan(a, b) -> int:
    """L1 distance between two board positions (turns to walk, obstacle-free)."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def step_toward(pos, target):
    """One MOVE op that reduces the distance from `pos` to `target`.

    Closes the wider axis gap first (fewer direction switches on a straight
    run); ties break to the horizontal axis. Returns ``None`` when already on
    the target. Deterministic, so routing is reproducible.
    """
    dx = target[0] - pos[0]
    dy = target[1] - pos[1]
    if dx == 0 and dy == 0:
        return None
    if abs(dx) >= abs(dy):
        return "EAST" if dx > 0 else "WEST"
    return "SOUTH" if dy > 0 else "NORTH"


def nearest_task(pos, tasks):
    """The task whose tile is nearest to `pos`; ``None`` if there are none.

    A task is a ``((x, y), action_list)`` pair. Ties break deterministically by
    target coordinate (x then y) and finally the action, so the same board
    always yields the same route.
    """
    if not tasks:
        return None
    return min(
        tasks,
        key=lambda t: (manhattan(pos, t[0]), t[0][0], t[0][1], t[1]),
    )


def route_action(pos, tasks):
    """Farmer op for this turn: execute the nearest task or step toward it.

    Returns the task's action when we are already on its tile, otherwise a
    single MOVE toward the nearest task, or ``["PASS"]`` when nothing is
    pending.
    """
    task = nearest_task(pos, tasks)
    if task is None:
        return ["PASS"]
    (tx, ty), action = task
    if (pos[0], pos[1]) == (tx, ty):
        return action
    move = step_toward(pos, (tx, ty))
    return [move] if move is not None else action


def managed_tiles(n: int) -> list:
    """The `n` NW-quadrant tiles a single farmer works, nearest the shed first.

    Clustering around the shed keeps routes short and guarantees the drop tile
    (`SHED_TILE`) is always in service. Ordered by distance to the shed, ties by
    coordinate, so the layout is deterministic and a smaller request is a prefix
    of a larger one.
    """
    candidates = [
        (x, y)
        for y in range(_NW_MAX + 1)
        for x in range(_NW_MAX + 1)
    ]
    candidates.sort(key=lambda t: (manhattan(SHED_TILE, t), t[0], t[1]))
    return candidates[:n]


class RoutedStrategy(Strategy):
    name = "routed"

    def act(self, obs) -> dict:
        player = obs["player"]
        me = obs["farms"][player]
        private = obs["private"]
        day = obs.get("day", 0)
        fx, fy = me["farmer"]
        tiles = me["tiles"]
        money = me["money"]
        seeds = private.get("seeds", {})
        shed = private.get("shed", {})
        inventories = private.get("inventories", [{}])
        my_inv = inventories[0] if inventories else {}

        # Market: continuously liquidate the shed, exactly as the champion does.
        market = sell_orders(shed)

        chosen = choose_crop(day, money, SEASON_DAYS)

        # Gather the pending task on each managed tile. One farmer visits them
        # by nearest-task order below.
        tasks = []
        empties = 0
        for (tx, ty) in managed_tiles(NUM_TILES):
            tile = tiles[ty][tx]
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                if _should_harvest(tile, day, SEASON_DAYS):
                    tasks.append(((tx, ty), ["HARVEST"]))
                elif not tile.get("watered_today", False):
                    tasks.append(((tx, ty), ["WATER"]))
            elif isinstance(tile, dict) and tile.get("kind") == "WEED":
                tasks.append(((tx, ty), ["DIG"]))
            elif tile is None:
                empties += 1
                if chosen is not None and seeds.get(chosen, 0) > 0:
                    tasks.append(((tx, ty), ["PLANT", chosen]))

        # Buy enough seed to cover the empty managed tiles we mean to plant,
        # bounded by cash. Seeds sit in their own uncapped slot.
        if chosen is not None and empties > 0:
            seed_cost = CROPS[chosen]["seed"]
            shortfall = empties - seeds.get(chosen, 0)
            affordable = int(money // seed_cost) if seed_cost > 0 else 0
            buy_n = max(0, min(shortfall, affordable))
            if buy_n > 0:
                market.append(["BUY_SEED", chosen, buy_n])

        # Carrying produce -> a trip home to the shed is a task like any other,
        # so nearest-task routing naturally batches harvests before the walk.
        if _has_produce(my_inv):
            tasks.append((SHED_TILE, ["DROP"]))

        farmer = route_action((fx, fy), tasks)
        return {"farmer": farmer, "hands": [], "market": market}


STRATEGY = RoutedStrategy
