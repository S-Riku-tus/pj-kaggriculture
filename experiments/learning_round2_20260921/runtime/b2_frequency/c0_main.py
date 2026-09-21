"""V126 control plus isolated, rejected experiments built on live V125.

The default flags preserve V125 behavior exactly.  Actor-local execution jobs,
service intensity, fertilizer allocation and animal purchase guards remain in
this module only as independently switchable development arms.  None passed
the paired adoption gate, so no new behavior is enabled in the packaged
control candidate.
"""

from __future__ import annotations

import copy
import gzip
import importlib.util
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

BOARD_SIZE = 10
SHED_CAPACITY = 100
MAX_MARKET_ORDERS = 10
MOVES = {
    "NORTH": (0, -1),
    "SOUTH": (0, 1),
    "EAST": (1, 0),
    "WEST": (-1, 0),
}
ANIMAL_STRUCTURE = {"GOOSE": "COOP", "COW": "PASTURE", "SHEEP": "PASTURE"}
STRUCTURE_ANIMAL = {"COOP": "GOOSE", "PASTURE": "SHEEP"}
ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
ANIMAL_RULES = {
    "GOOSE": {"first": 4, "interval": 1, "max_held": 4},
    "COW": {"first": 8, "interval": 2, "max_held": 6},
    "SHEEP": {"first": 6, "interval": 3, "max_held": 6},
}
CROP_RULES = {
    "WHEAT": {"first": 2, "max_day": 4, "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT": {"first": 2, "max_day": 3, "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO": {"first": 8, "max_day": 8, "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"first": 10, "max_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON": {"first": 10, "max_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}
BASE_PRODUCT_PRICE = {"EGG": 50, "MILK": 160, "WOOL": 200}

# Independent experimental flags.  The promoted execution candidate leaves
# both false.  Thin sibling wrappers enable one or both for the four-arm test.
ENABLE_SERVICE_POLICY = False
ENABLE_FERTILIZER_POLICY = False
ENABLE_ANIMAL_PURCHASE_GUARD = False
ENABLE_GENERAL_JOB_RECOVERY = False
ENABLE_EXECUTION_TRANSACTIONS = False


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v126_exec",
        Path.cwd(),
    )
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if (candidate / "v125_exec_base.py").is_file()
            or (candidate.parent / "v125_exec" / "main.py").is_file()
        ),
        Path.cwd(),
    )


def _load_v125() -> Any:
    module_dir = _module_dir()
    packaged = module_dir / "v125_exec_base.py"
    repository = module_dir.parent / "v125_exec" / "main.py"
    source = packaged if packaged.is_file() else repository
    spec = importlib.util.spec_from_file_location("_kaggriculture_v126_v125", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import live V125 base: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_v125()
_OPENING_MODEL: dict[str, Any] | None = None


def _v124_module() -> Any:
    """Return the live V124 module nested below the V125 execution wrapper."""
    return base.base


def _load_opening_model() -> dict[str, Any]:
    global _OPENING_MODEL
    if _OPENING_MODEL is None:
        path = _module_dir() / "opening_routes.json.gz"
        if not path.is_file():
            path = Path(__file__).resolve().parent / "opening_routes.json.gz"
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            model = json.load(stream)
        if model.get("format") != "v126-opening-route-source-v1":
            raise RuntimeError("v126 opening route model format mismatch")
        _OPENING_MODEL = model
    return _OPENING_MODEL


def _opening_row(
    observation: Mapping[str, Any], source: int | None = None
) -> list[Any] | None:
    step = _step(observation)
    steps = list(_load_opening_model().get("steps") or [])
    if not (0 <= step < len(steps)):
        return None
    rows = list(steps[step] or [])
    v120 = _v124_module().sparse.base
    count = v120.unit_count(observation)
    compatible = [row for row in rows if _integer(row[0]) == count]
    pool = compatible or rows
    if source is not None:
        sourced = [row for row in pool if len(row) >= 4 and _integer(row[3], -1) == source]
        if not sourced:
            return None
        pool = sourced
    if not pool:
        return None
    query = v120.feature_vector(observation)
    return min(pool, key=lambda row: v120.feature_distance(query, row[1]))


def _current_route_source(observation: Mapping[str, Any] | None = None) -> int:
    if observation is not None and _step(observation) < _v124_module().sparse.OPENING_END:
        row = _opening_row(observation)
        return _integer(row[3], -1) if row is not None and len(row) >= 4 else -1
    sparse = _v124_module().sparse
    return _integer(sparse._STATE.get("last_action_source"), -1)


def _source_actor_action(source: int, step: int, actor: int) -> list[Any] | None:
    """Read one recorded route action without using future game observations."""
    sparse = _v124_module().sparse
    if step < sparse.OPENING_END:
        steps = list(_load_opening_model().get("steps") or [])
        rows = list(steps[step] or []) if 0 <= step < len(steps) else []
        matching = [row for row in rows if len(row) >= 4 and _integer(row[3], -1) == source]
        action = _mapping(matching[0][2]) if matching else {}
        hands = list(action.get("hands") or [])
        candidate = action.get("farmer") if actor == 0 else (
            hands[actor - 1] if actor - 1 < len(hands) else None
        )
        return list(candidate) if isinstance(candidate, list | tuple) and candidate else None
    model = sparse._MODEL
    steps = list(_mapping(model).get("steps") or [])
    if source < 0 or not (0 <= step < len(steps)):
        return None
    for row in steps[step] or []:
        if _integer(row[sparse.ROW_SOURCE], -1) != source:
            continue
        action = _mapping(row[sparse.ROW_ACTION])
        candidate = action.get("farmer") if actor == 0 else (
            list(action.get("hands") or [])[actor - 1]
            if actor - 1 < len(list(action.get("hands") or []))
            else None
        )
        if isinstance(candidate, list | tuple) and candidate:
            return list(candidate)
    return None


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _seat(observation: Mapping[str, Any]) -> int:
    return 1 if _integer(observation.get("player")) == 1 else 0


def _step(observation: Mapping[str, Any]) -> int:
    return 24 * _integer(observation.get("day")) + _integer(observation.get("hour"))


def _farm(observation: Mapping[str, Any]) -> Mapping[str, Any]:
    farms = list(observation.get("farms") or [])
    seat = _seat(observation)
    return _mapping(farms[seat]) if seat < len(farms) else {}


def _positions(farm: Mapping[str, Any]) -> list[tuple[int, int]]:
    raw = [farm.get("farmer") or (0, 0), *(farm.get("hands") or [])]
    return [(int(position[0]), int(position[1])) for position in raw]


def _inventories(observation: Mapping[str, Any], count: int) -> list[Mapping[str, Any]]:
    raw = list(_mapping(observation.get("private")).get("inventories") or [])
    return [_mapping(raw[index]) if index < len(raw) else {} for index in range(count)]


def _unit_actions(action: Mapping[str, Any], count: int) -> list[list[Any]]:
    farmer = action.get("farmer")
    result = [list(farmer) if isinstance(farmer, list | tuple) and farmer else ["PASS"]]
    result.extend(
        list(candidate) if isinstance(candidate, list | tuple) and candidate else ["PASS"]
        for candidate in action.get("hands") or []
    )
    result.extend([["PASS"] for _ in range(max(0, count - len(result)))])
    return result[:count]


def _shed_tiles(board_size: int) -> tuple[tuple[int, int], ...]:
    half = board_size // 2
    return (
        (half - 1, half - 1),
        (half, half - 1),
        (half - 1, half),
        (half, half),
    )


def _is_shed(position: tuple[int, int], board_size: int) -> bool:
    return position in _shed_tiles(board_size)


def _distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1])


def _nearest(position: tuple[int, int], targets: Sequence[tuple[int, int]]) -> tuple[int, int]:
    return min(targets, key=lambda target: (_distance(position, target), target[1], target[0]))


def _move_toward(position: tuple[int, int], target: tuple[int, int]) -> list[str]:
    x, y = position
    tx, ty = target
    if y < ty:
        return ["SOUTH"]
    if y > ty:
        return ["NORTH"]
    if x < tx:
        return ["EAST"]
    if x > tx:
        return ["WEST"]
    return ["PASS"]


def _tile(farm: Mapping[str, Any], position: tuple[int, int]) -> Any:
    tiles = list(farm.get("tiles") or [])
    x, y = position
    if not (0 <= y < len(tiles)):
        return None
    row = list(tiles[y] or [])
    return row[x] if 0 <= x < len(row) else None


def _owned_empty_positions(farm: Mapping[str, Any]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for y, row in enumerate(farm.get("tiles") or []):
        for x, tile in enumerate(row or []):
            if tile is None:
                result.append((x, y))
    return result


def _empty_structures(farm: Mapping[str, Any], structure: str) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for y, row in enumerate(farm.get("tiles") or []):
        for x, raw in enumerate(row or []):
            tile = _mapping(raw)
            if tile.get("kind") == structure and "animal" not in tile:
                result.append((x, y))
    return result


def _animal_positions(
    farm: Mapping[str, Any], *, unfed_only: bool = False
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for y, row in enumerate(farm.get("tiles") or []):
        for x, raw in enumerate(row or []):
            tile = _mapping(raw)
            if "animal" not in tile:
                continue
            if unfed_only and bool(tile.get("fed_today")):
                continue
            result.append((x, y))
    return result


def _spawn_sequence(farm: Mapping[str, Any], count: int, board_size: int) -> list[list[int]]:
    access = list(_shed_tiles(board_size))
    occupied = Counter(position for position in _positions(farm) if position in access)
    result: list[list[int]] = []
    for _ in range(count):
        target = min(access, key=lambda pos: (occupied[pos], access.index(pos)))
        occupied[target] += 1
        result.append([target[0], target[1]])
    return result


def _market_orders(action: Mapping[str, Any]) -> list[list[Any]]:
    return [
        list(order)
        for order in action.get("market") or []
        if isinstance(order, list | tuple)
    ][:MAX_MARKET_ORDERS]


def _next_animal_production_day(tile: Mapping[str, Any], day: int, *, after_today: bool) -> int | None:
    animal = str(tile.get("animal") or "")
    rule = ANIMAL_RULES.get(animal)
    if rule is None:
        return None
    first = _integer(tile.get("placed_day")) + int(rule["first"])
    lower = day + (2 if after_today else 1)
    for candidate in range(max(first, lower), 30):
        if (candidate - first) % int(rule["interval"]) == 0:
            return candidate
    return None


def _service_policy(
    observation: Mapping[str, Any], position: tuple[int, int], action: list[Any]
) -> tuple[list[Any], str | None]:
    if not ENABLE_SERVICE_POLICY or not action:
        return action, None
    op = action[0]
    if op not in {"FEED", "CARE"}:
        return action, None
    tile = _mapping(_tile(_farm(observation), position))
    animal = str(tile.get("animal") or "")
    if not animal:
        return action, None
    day = _integer(observation.get("day"))
    product = ANIMAL_PRODUCT[animal]
    prices = _mapping(_mapping(observation.get("market")).get("prices"))
    price = _integer(prices.get(product))
    wheat_price = _integer(prices.get("WHEAT"))
    rule = ANIMAL_RULES[animal]
    yield_units = _integer(tile.get("yield_units"))
    next_production = _next_animal_production_day(tile, day, after_today=op == "CARE")
    if next_production is None:
        if op == "CARE" or _integer(tile.get("consecutive_unfed")) == 0:
            return ["PASS"], "no_remaining_production"
        return action, None
    if op == "FEED":
        # One missed day is survivable.  Preserve every production-day feed
        # and every rescue feed, but do not spend wheat plus a worker action
        # to bank a low-value care unit on a non-production day.
        production_tomorrow = _next_animal_production_day(tile, day, after_today=False) == day + 1
        if (
            _integer(tile.get("consecutive_unfed")) == 0
            and not production_tomorrow
            and (
                price <= wheat_price + 20
                or (
                    yield_units >= int(rule["max_held"])
                    and _integer(tile.get("pending_care_bonus")) >= int(rule["max_held"])
                )
            )
        ):
            return ["PASS"], "low_value_nonproduction_safe_skip"
        return action, None
    # CARE performed today cannot affect today's scheduled refresh; it enters
    # pending only after production.  Reject it only when its later unit has no
    # sale value or no room to be produced.
    if not bool(tile.get("fed_today")):
        return ["PASS"], "care_without_feed_has_no_effect"
    if price <= wheat_price + 20 and yield_units >= int(rule["max_held"]):
        return ["PASS"], "floor_saturated_care"
    return action, None


def _fertilizer_incremental_units(tile: Mapping[str, Any], day: int) -> int:
    crop = str(tile.get("crop") or "")
    rule = CROP_RULES.get(crop)
    if rule is None or _integer(tile.get("fertilized_until_day"), -1) >= day + 2:
        return 0
    yield_units = _integer(tile.get("yield_units"))
    remaining_capacity = max(0, int(rule["max_yield"]) - yield_units)
    if remaining_capacity <= 0:
        return 0
    if not bool(rule["ongoing"]):
        age = day - _integer(tile.get("planted_day"))
        window_start = (int(rule["max_day"]) + 1) // 2
        eligible = sum(
            window_start <= age + offset <= int(rule["max_day"])
            for offset in range(3)
        )
        return min(remaining_capacity, eligible)
    first = _integer(tile.get("planted_day")) + int(rule["first"])
    interval = int(rule["interval"])
    eligible = sum(
        candidate >= first and (candidate - first) % interval == 0
        for candidate in range(day + 1, min(30, day + 4))
    )
    return min(remaining_capacity, eligible)


def _fertilizer_policy(
    observation: Mapping[str, Any], position: tuple[int, int], action: list[Any], inventory: Mapping[str, Any]
) -> tuple[list[Any], str | None]:
    if not ENABLE_FERTILIZER_POLICY:
        return action, None
    tile = _mapping(_tile(_farm(observation), position))
    if tile.get("kind") != "PLANT":
        return action, None
    op = action[0] if action else "PASS"
    if op not in {"FERTILIZE", "PASS"}:
        return action, None
    crop = str(tile.get("crop") or "")
    units = _fertilizer_incremental_units(tile, _integer(observation.get("day")))
    prices = _mapping(_mapping(observation.get("market")).get("prices"))
    crop_value = units * max(0, _integer(prices.get(crop)))
    fertilizer_value = max(0, _integer(prices.get("FERTILIZER")))
    hurdle = fertilizer_value + 10  # fertilizer sale option plus one action
    if op == "FERTILIZE" and crop_value <= hurdle:
        return ["PASS"], "fertilizer_value_below_hurdle"
    if (
        op == "PASS"
        and crop == "WHEAT"
        and _integer(inventory.get("FERTILIZER")) > 0
        and crop_value > hurdle
    ):
        return ["FERTILIZE"], "profitable_idle_wheat_fertilizer"
    return action, None


class ExecutionCoordinator:
    def __init__(self, seat: int):
        self.seat = seat
        self.day = -1
        self.hand_count = 0
        self.jobs: dict[int, dict[str, Any]] = {}
        self.counts: Counter[str] = Counter()
        self.last_events: list[dict[str, Any]] = []
        self.expected_new_hands: list[list[int]] = []
        self.last_step = -1
        self.source_latch: int | None = None
        self.source_latch_day = -1
        self.source_latch_actor: int | None = None
        self.shadow_positions: dict[int, tuple[int, int]] = {}
        self.shadow_inventory: dict[tuple[int, str], int] = {}
        self.shadow_shed: dict[str, int] = {}
        self.shadow_tiles: dict[tuple[int, int, str], Any] = {}

    def reset(self) -> None:
        self.__init__(self.seat)

    def _event(self, event: str, **values: Any) -> None:
        self.counts[event] += 1
        self.last_events.append({"event": event, **values})
        self.last_events = self.last_events[-20:]

    def _start_job(self, actor: int, kind: str, **values: Any) -> dict[str, Any]:
        job = {
            "kind": kind,
            "created_step": self.last_step,
            "day": self.day,
            "attempts": 0,
            "failed_attempts": 0,
            "awaiting": None,
            **values,
        }
        self.jobs[actor] = job
        if kind in {"feed_prefetch_swap", "deposit_detour"}:
            source = _integer(values.get("route_source"), _current_route_source())
            if source >= 0:
                job["route_source"] = source
                self.source_latch = source
                self.source_latch_day = self.day
                self.source_latch_actor = actor
                self._event("transaction_source_latched", actor=actor, source=source)
        self._event("job_started", actor=actor, kind=kind, values=copy.deepcopy(values))
        return job

    def _finish(self, actor: int, outcome: str) -> None:
        job = self.jobs.pop(actor, None)
        if job is None:
            return
        if actor == self.source_latch_actor:
            self._event(
                "transaction_source_released",
                actor=actor,
                source=self.source_latch,
                outcome=outcome,
            )
            self.source_latch = None
            self.source_latch_day = -1
            self.source_latch_actor = None
        self._event(
            f"job_{outcome}",
            actor=actor,
            kind=job["kind"],
            age=self.last_step - _integer(job.get("created_step")),
            failed_attempts=_integer(job.get("failed_attempts")),
        )

    def _day_sync(self, observation: Mapping[str, Any], positions: list[tuple[int, int]]) -> None:
        day = _integer(observation.get("day"))
        step = _step(observation)
        if step == 0 or step < self.last_step:
            self.reset()
        self.last_step = step
        if day != self.day:
            for actor in list(self.jobs):
                self._finish(actor, "expired_day_boundary")
            self.day = day
            self.hand_count = max(0, len(positions) - 1)
            self.expected_new_hands = []
            self.source_latch = None
            self.source_latch_day = -1
            self.source_latch_actor = None
            self.shadow_positions.clear()
            self.shadow_inventory.clear()
            self.shadow_shed.clear()
            self.shadow_tiles.clear()
            return
        current_hands = max(0, len(positions) - 1)
        if self.expected_new_hands:
            actual = [list(position) for position in positions[1 + self.hand_count :]]
            if actual != self.expected_new_hands:
                self._event(
                    "hire_spawn_mismatch",
                    expected=self.expected_new_hands,
                    actual=actual,
                )
            else:
                self._event("hire_spawn_verified", count=len(actual))
            self.expected_new_hands = []
        if current_hands < self.hand_count:
            for actor in [index for index in self.jobs if index > current_hands]:
                self._finish(actor, "lost_worker")
        self.hand_count = current_hands

    def policy_observation(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        """Hide E-only state deltas from the route chooser until day end."""
        if not (
            self.shadow_positions
            or self.shadow_inventory
            or self.shadow_shed
            or self.shadow_tiles
        ):
            return dict(observation)
        result = copy.deepcopy(dict(observation))
        farms = list(result.get("farms") or [])
        if self.seat < len(farms):
            farm = farms[self.seat]
            for actor, position in self.shadow_positions.items():
                if actor == 0:
                    farm["farmer"] = list(position)
                else:
                    hands = list(farm.get("hands") or [])
                    if actor - 1 < len(hands):
                        hands[actor - 1] = list(position)
                        farm["hands"] = hands
            tiles = list(farm.get("tiles") or [])
            for (x, y, field), value in self.shadow_tiles.items():
                if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
                    tile = tiles[y][x]
                    if isinstance(tile, dict):
                        tile[field] = value
        private = _mapping(result.get("private"))
        inventories = list(private.get("inventories") or [])
        for (actor, item), quantity in self.shadow_inventory.items():
            if actor < len(inventories):
                inventory = dict(_mapping(inventories[actor]))
                inventory[item] = quantity
                inventories[actor] = inventory
        private["inventories"] = inventories
        shed = dict(_mapping(private.get("shed")))
        shed.update(self.shadow_shed)
        private["shed"] = shed
        result["private"] = private
        return result

    def _reserved(self, item: str, *, except_actor: int | None = None) -> int:
        return sum(
            _integer(job.get("reserve"))
            for actor, job in self.jobs.items()
            if actor != except_actor and job.get("item") == item
        )

    def _available_shed(
        self, observation: Mapping[str, Any], item: str, actor: int
    ) -> int:
        shed = _mapping(_mapping(observation.get("private")).get("shed"))
        return max(0, _integer(shed.get(item)) - self._reserved(item, except_actor=actor))

    def _verify_awaiting(
        self,
        actor: int,
        job: dict[str, Any],
        observation: Mapping[str, Any],
        inventory: Mapping[str, Any],
        farm: Mapping[str, Any],
    ) -> None:
        awaiting = _mapping(job.get("awaiting"))
        if not awaiting:
            return
        op = str(awaiting.get("op") or "")
        success = False
        if op == "PICKUP":
            success = _integer(inventory.get(str(awaiting.get("item")))) > _integer(
                awaiting.get("before")
            )
        elif op == "PLACE":
            success = _integer(inventory.get(str(awaiting.get("item")))) < _integer(
                awaiting.get("before")
            )
        elif op == "DROP":
            success = sum(_integer(value) for value in inventory.values()) < _integer(
                awaiting.get("before")
            )
        elif op == "FEED":
            success = bool(_mapping(_tile(farm, tuple(awaiting.get("target") or (0, 0)))).get("fed_today"))
        elif op.startswith("BUILD_"):
            success = (
                _mapping(_tile(farm, tuple(awaiting.get("target") or (0, 0)))).get("kind")
                == awaiting.get("structure")
            )
        elif op == "PLACE_ANIMAL":
            success = (
                _mapping(_tile(farm, tuple(awaiting.get("target") or (0, 0)))).get("animal")
                == awaiting.get("item")
            )
        elif op == "FERTILIZE":
            target = _mapping(_tile(farm, tuple(awaiting.get("target") or (0, 0))))
            success = _integer(target.get("fertilized_until_day"), -1) > _integer(
                awaiting.get("before"), -1
            )
        if success:
            self._event("operation_verified", actor=actor, op=op, kind=job["kind"])
            job["awaiting"] = None
            job["failed_attempts"] = 0
            if job["kind"] == "deposit_detour" and op in {"PLACE", "DROP"}:
                job["phase"] = "return"
                return
            if op in {"PICKUP", "BUILD_PASTURE", "BUILD_COOP"}:
                return
            if job["kind"] == "feed_prefetch_swap" and op == "FEED":
                job["feeds_verified"] = _integer(job.get("feeds_verified")) + 1
                job["phase"] = "service"
                return
            self._finish(actor, "completed")
        else:
            job["awaiting"] = None
            job["failed_attempts"] = _integer(job.get("failed_attempts")) + 1
            self._event("operation_not_observed", actor=actor, op=op, kind=job["kind"])

    def _route_shed(self, position: tuple[int, int], board_size: int) -> list[str]:
        return _move_toward(position, _nearest(position, _shed_tiles(board_size)))

    def _execute_job(
        self,
        actor: int,
        observation: Mapping[str, Any],
        farm: Mapping[str, Any],
        position: tuple[int, int],
        inventory: Mapping[str, Any],
        board_size: int,
    ) -> list[Any]:
        job = self.jobs[actor]
        self._verify_awaiting(actor, job, observation, inventory, farm)
        if actor not in self.jobs:
            source_action = _source_actor_action(
                _integer(job.get("route_source"), -1), self.last_step, actor
            )
            return source_action or ["PASS"]
        job = self.jobs[actor]
        if job.get("awaiting"):
            return ["PASS"]
        if self.last_step - _integer(job.get("created_step")) > 8:
            self._finish(actor, "deadline")
            return ["PASS"]

        kind = str(job["kind"])
        item = str(job.get("item") or "")
        if kind == "feed_prefetch_swap":
            phase = str(job.get("phase") or "pickup")
            if phase == "pickup" and _integer(inventory.get("WHEAT")) <= _integer(job.get("initial")):
                if not _is_shed(position, board_size):
                    self._finish(actor, "position_drift")
                    return ["PASS"]
                available = self._available_shed(observation, "WHEAT", actor)
                if available <= 0:
                    self._finish(actor, "resource_unavailable")
                    return ["PASS"]
                quantity = min(5, available, max(1, _integer(job.get("quantity"), 1)))
                job["attempts"] += 1
                job["awaiting"] = {
                    "op": "PICKUP",
                    "item": "WHEAT",
                    "before": _integer(inventory.get("WHEAT")),
                }
                return ["PICKUP", "WHEAT", quantity]
            if phase in {"feed", "service"}:
                source_action = _source_actor_action(
                    _integer(job.get("route_source"), -1), self.last_step, actor
                )
                if not source_action:
                    self._finish(actor, "source_ended")
                    return ["PASS"]
                source_op = str(source_action[0])
                if source_op == "FEED":
                    if _integer(inventory.get("WHEAT")) <= 0:
                        self._finish(actor, "resource_unavailable")
                        return source_action
                    self.shadow_tiles[(position[0], position[1], "fed_today")] = False
                    job["attempts"] += 1
                    job["awaiting"] = {"op": "FEED", "target": list(position)}
                    return source_action
                if source_op in {*MOVES, "CARE", "COLLECT_FERTILIZER"}:
                    job["phase"] = "service"
                    return source_action
                self._finish(actor, "completed")
                return source_action
            saved_move = list(job.get("saved_move") or ["PASS"])
            job["phase"] = "service"
            self.shadow_positions.pop(actor, None)
            return saved_move

        if kind == "deposit_detour":
            shed_target = tuple(job.get("shed_target") or position)
            rejoin = tuple(job.get("rejoin") or position)
            phase = str(job.get("phase") or "to_shed")
            if phase == "to_shed":
                if position != shed_target:
                    return _move_toward(position, shed_target)
                job["phase"] = "transfer"
                phase = "transfer"
            if phase == "transfer":
                if _integer(inventory.get(item)) <= 0:
                    job["phase"] = "return"
                else:
                    shed = _mapping(_mapping(observation.get("private")).get("shed"))
                    room = max(
                        0,
                        SHED_CAPACITY
                        - sum(max(0, _integer(value)) for value in shed.values()),
                    )
                    if room <= 0:
                        self._finish(actor, "shed_full")
                        return _move_toward(position, rejoin)
                    quantity = min(room, _integer(inventory.get(item)))
                    job["attempts"] += 1
                    job["awaiting"] = {
                        "op": "PLACE",
                        "item": item,
                        "before": _integer(inventory.get(item)),
                    }
                    return ["PLACE", item, quantity]
            if position == rejoin:
                self._finish(actor, "completed")
                source_action = _source_actor_action(
                    _integer(job.get("route_source"), -1), self.last_step, actor
                )
                return source_action or ["PASS"]
            movement = _move_toward(position, rejoin)
            if _distance(position, rejoin) == 1:
                self.shadow_positions[actor] = rejoin
            return movement

        if kind == "pickup":
            if _integer(inventory.get(item)) > _integer(job.get("initial")):
                self._finish(actor, "completed")
                return ["PASS"]
            if not _is_shed(position, board_size):
                return self._route_shed(position, board_size)
            available = self._available_shed(observation, item, actor)
            if available <= 0:
                return ["PASS"]
            quantity = min(max(1, _integer(job.get("quantity"), 1)), available)
            job["attempts"] += 1
            job["awaiting"] = {
                "op": "PICKUP",
                "item": item,
                "before": _integer(inventory.get(item)),
            }
            return ["PICKUP", item, quantity]

        if kind in {"deposit", "deposit_all"}:
            carried = sum(max(0, _integer(value)) for value in inventory.values())
            if carried <= 0 or (kind == "deposit" and _integer(inventory.get(item)) <= 0):
                self._finish(actor, "completed")
                return ["PASS"]
            if not _is_shed(position, board_size):
                return self._route_shed(position, board_size)
            shed = _mapping(_mapping(observation.get("private")).get("shed"))
            room = max(0, SHED_CAPACITY - sum(max(0, _integer(value)) for value in shed.values()))
            if room <= 0:
                return ["PASS"]
            if kind == "deposit_all":
                choices = [
                    (str(key), _integer(value))
                    for key, value in inventory.items()
                    if _integer(value) > 0
                ]
                prices = _mapping(_mapping(observation.get("market")).get("prices"))
                choices.sort(key=lambda pair: (-_integer(prices.get(pair[0])), pair[0]))
                item, quantity = choices[0]
            else:
                quantity = _integer(inventory.get(item))
            quantity = min(quantity, room, max(1, _integer(job.get("quantity"), quantity)))
            job["attempts"] += 1
            job["awaiting"] = {
                "op": "PLACE",
                "item": item,
                "before": _integer(inventory.get(item)),
            }
            return ["PLACE", item, quantity]

        if kind == "feed":
            target = tuple(job.get("target") or position)
            target_tile = _mapping(_tile(farm, target))
            if "animal" not in target_tile:
                candidates = _animal_positions(farm, unfed_only=True)
                if not candidates:
                    self._finish(actor, "target_gone")
                    return ["PASS"]
                target = _nearest(position, candidates)
                job["target"] = list(target)
                target_tile = _mapping(_tile(farm, target))
            if bool(target_tile.get("fed_today")):
                self._finish(actor, "completed")
                return ["PASS"]
            if _integer(inventory.get("WHEAT")) <= 0:
                if not _is_shed(position, board_size):
                    return self._route_shed(position, board_size)
                available = self._available_shed(observation, "WHEAT", actor)
                if available <= 0:
                    return ["PASS"]
                quantity = min(available, max(1, len(_animal_positions(farm, unfed_only=True))))
                job["attempts"] += 1
                job["awaiting"] = {
                    "op": "PICKUP",
                    "item": "WHEAT",
                    "before": _integer(inventory.get("WHEAT")),
                }
                return ["PICKUP", "WHEAT", quantity]
            if position != target:
                return _move_toward(position, target)
            job["attempts"] += 1
            job["awaiting"] = {"op": "FEED", "target": list(target)}
            return ["FEED"]

        if kind == "fertilize":
            target = tuple(job.get("target") or position)
            target_tile = _mapping(_tile(farm, target))
            if target_tile.get("kind") != "PLANT":
                self._finish(actor, "target_gone")
                return ["PASS"]
            if _integer(inventory.get("FERTILIZER")) <= 0:
                if not _is_shed(position, board_size):
                    return self._route_shed(position, board_size)
                available = self._available_shed(observation, "FERTILIZER", actor)
                if available <= 0:
                    self._finish(actor, "resource_unavailable")
                    return ["PASS"]
                job["attempts"] += 1
                job["awaiting"] = {
                    "op": "PICKUP",
                    "item": "FERTILIZER",
                    "before": _integer(inventory.get("FERTILIZER")),
                }
                return ["PICKUP", "FERTILIZER", 1]
            if position != target:
                return _move_toward(position, target)
            job["attempts"] += 1
            job["awaiting"] = {
                "op": "FERTILIZE",
                "target": list(target),
                "before": _integer(target_tile.get("fertilized_until_day"), -1),
            }
            return ["FERTILIZE"]

        if kind == "place_animal":
            structure = ANIMAL_STRUCTURE[item]
            target_raw = job.get("target")
            target = tuple(target_raw) if target_raw else None
            if target is not None:
                target_tile = _mapping(_tile(farm, target))
                if target_tile.get("animal") == item:
                    self._finish(actor, "completed")
                    return ["PASS"]
                target_valid = (
                    target_tile.get("kind") == structure and "animal" not in target_tile
                ) or _tile(farm, target) is None
                if not target_valid:
                    target = None
                    job["target"] = None
            if _integer(inventory.get(item)) <= 0:
                if not _is_shed(position, board_size):
                    return self._route_shed(position, board_size)
                available = self._available_shed(observation, item, actor)
                if available <= 0:
                    return ["PASS"]
                job["attempts"] += 1
                job["awaiting"] = {
                    "op": "PICKUP",
                    "item": item,
                    "before": _integer(inventory.get(item)),
                }
                return ["PICKUP", item, 1]
            if target is None:
                structures = _empty_structures(farm, structure)
                if structures:
                    target = _nearest(position, structures)
                    job["target"] = list(target)
                    job["needs_build"] = False
                else:
                    empties = _owned_empty_positions(farm)
                    if not empties:
                        self._finish(actor, "no_placement_capacity")
                        return ["PASS"]
                    target = _nearest(position, empties)
                    job["target"] = list(target)
                    job["needs_build"] = True
            target_tile = _mapping(_tile(farm, target))
            if position != target:
                return _move_toward(position, target)
            if _tile(farm, target) is None:
                operation = "BUILD_COOP" if structure == "COOP" else "BUILD_PASTURE"
                job["attempts"] += 1
                job["awaiting"] = {
                    "op": operation,
                    "target": list(target),
                    "structure": structure,
                }
                return [operation]
            if target_tile.get("kind") == structure and "animal" not in target_tile:
                job["attempts"] += 1
                job["awaiting"] = {
                    "op": "PLACE_ANIMAL",
                    "target": list(target),
                    "item": item,
                }
                return ["PLACE", item]
            job["target"] = None
            return ["PASS"]

        self._finish(actor, "unknown")
        return ["PASS"]

    def _preflight(
        self,
        actor: int,
        proposed: list[Any],
        observation: Mapping[str, Any],
        farm: Mapping[str, Any],
        position: tuple[int, int],
        inventory: Mapping[str, Any],
        board_size: int,
        market: list[list[Any]],
    ) -> list[Any]:
        if not ENABLE_GENERAL_JOB_RECOVERY:
            return proposed
        if not proposed:
            return ["PASS"]
        op = str(proposed[0])
        tile = _tile(farm, position)
        tile_map = _mapping(tile)
        if op == "PICKUP" and len(proposed) >= 2:
            item = str(proposed[1])
            available = self._available_shed(observation, item, actor)
            bought_this_turn = any(
                order
                and order[0] in {"BUY_PRODUCT", "BUY_ANIMAL"}
                and len(order) >= 2
                and str(order[1]) == item
                for order in market
            )
            if not _is_shed(position, board_size) or (
                available <= 0 and bought_this_turn
            ):
                self._start_job(
                    actor,
                    "pickup",
                    item=item,
                    quantity=max(1, _integer(proposed[2], 1) if len(proposed) >= 3 else 1),
                    initial=_integer(inventory.get(item)),
                    reserve=max(1, _integer(proposed[2], 1) if len(proposed) >= 3 else 1),
                )
                return self._execute_job(
                    actor, observation, farm, position, inventory, board_size
                )
            if available <= 0:
                self._event(
                    "precondition_observed",
                    actor=actor,
                    op=op,
                    reason="shed_item_unavailable",
                )
            return proposed
        if op == "DROP":
            if not _is_shed(position, board_size) and inventory:
                self._start_job(actor, "deposit_all")
                return self._execute_job(
                    actor, observation, farm, position, inventory, board_size
                )
            return proposed
        if op == "PLACE" and len(proposed) >= 2:
            item = str(proposed[1])
            if item in ANIMAL_STRUCTURE:
                valid = (
                    tile_map.get("kind") == ANIMAL_STRUCTURE[item]
                    and "animal" not in tile_map
                    and _integer(inventory.get(item)) > 0
                )
                if not valid and _integer(inventory.get(item)) > 0:
                    self._start_job(
                        actor,
                        "place_animal",
                        item=item,
                        reserve=1,
                        target=None,
                    )
                    return self._execute_job(
                        actor, observation, farm, position, inventory, board_size
                    )
                if not valid:
                    self._event(
                        "precondition_observed",
                        actor=actor,
                        op=op,
                        reason="animal_not_carried",
                    )
                return proposed
            if _integer(inventory.get(item)) <= 0:
                self._event("precondition_rejected", actor=actor, op=op, reason="no_item")
                return ["PASS"]
            if not _is_shed(position, board_size):
                quantity = _integer(proposed[2], _integer(inventory.get(item))) if len(proposed) >= 3 else 1
                self._start_job(
                    actor,
                    "deposit",
                    item=item,
                    quantity=max(1, quantity),
                )
                return self._execute_job(
                    actor, observation, farm, position, inventory, board_size
                )
            return proposed
        if op == "FEED":
            valid = (
                "animal" in tile_map
                and not bool(tile_map.get("fed_today"))
                and _integer(inventory.get("WHEAT")) > 0
            )
            if valid:
                return proposed
            if "animal" in tile_map and bool(tile_map.get("fed_today")):
                self._event("precondition_observed", actor=actor, op=op, reason="already_fed")
                return proposed
            if "animal" in tile_map:
                self._start_job(
                    actor,
                    "feed",
                    item="WHEAT",
                    reserve=1,
                    target=list(position),
                )
                return self._execute_job(
                    actor, observation, farm, position, inventory, board_size
                )
            self._event("precondition_observed", actor=actor, op=op, reason="no_animal")
            return proposed
        if op in {"BUILD_COOP", "BUILD_PASTURE"}:
            if tile is None:
                return proposed
            animal = "GOOSE" if op == "BUILD_COOP" else (
                "COW" if _integer(inventory.get("COW")) > 0 else "SHEEP"
            )
            held = _integer(inventory.get(animal))
            if held > 0:
                self._start_job(
                    actor,
                    "place_animal",
                    item=animal,
                    reserve=1,
                    target=None,
                )
                return self._execute_job(
                    actor, observation, farm, position, inventory, board_size
                )
            self._event("precondition_observed", actor=actor, op=op, reason="occupied_tile")
            return proposed
        if op == "FERTILIZE" and _integer(inventory.get("FERTILIZER")) <= 0:
            self._event("precondition_observed", actor=actor, op=op, reason="no_fertilizer")
            return proposed
        return proposed

    def _guard_animal_purchases(
        self,
        observation: Mapping[str, Any],
        farm: Mapping[str, Any],
        units: list[list[Any]],
        market: list[list[Any]],
    ) -> list[list[Any]]:
        if not ENABLE_ANIMAL_PURCHASE_GUARD or self.day == 0:
            return market
        private = _mapping(observation.get("private"))
        shed = _mapping(private.get("shed"))
        inventories = list(private.get("inventories") or [])
        held = Counter({animal: _integer(shed.get(animal)) for animal in ANIMAL_STRUCTURE})
        for inventory in inventories:
            for animal in ANIMAL_STRUCTURE:
                held[animal] += _integer(_mapping(inventory).get(animal))
        capacity = Counter()
        for animal, structure in ANIMAL_STRUCTURE.items():
            capacity[animal] = len(_empty_structures(farm, structure))
        positions = _positions(farm)
        for actor, unit in enumerate(units):
            if not unit or unit[0] not in {"BUILD_COOP", "BUILD_PASTURE"}:
                continue
            if actor >= len(positions) or _tile(farm, positions[actor]) is not None:
                continue
            if unit[0] == "BUILD_COOP":
                capacity["GOOSE"] += 1
            else:
                # A future pasture can hold either type, but reserve it for an
                # already held animal before authorizing another purchase.
                animal = "COW" if held["COW"] > capacity["COW"] else "SHEEP"
                capacity[animal] += 1
        spare = {animal: max(0, capacity[animal] - held[animal]) for animal in ANIMAL_STRUCTURE}
        result: list[list[Any]] = []
        for order in market:
            if order and order[0] == "BUY_ANIMAL" and len(order) >= 3:
                animal = str(order[1])
                requested = max(0, _integer(order[2]))
                allowed = min(requested, spare.get(animal, 0))
                if allowed <= 0:
                    self._event(
                        "animal_purchase_blocked",
                        animal=animal,
                        requested=requested,
                        capacity=capacity.get(animal, 0),
                        held=held.get(animal, 0),
                    )
                    continue
                if allowed < requested:
                    self._event(
                        "animal_purchase_capped",
                        animal=animal,
                        requested=requested,
                        allowed=allowed,
                    )
                result.append(["BUY_ANIMAL", animal, allowed])
                spare[animal] -= allowed
            else:
                result.append(order)
        return result[:MAX_MARKET_ORDERS]

    def repair(
        self, observation: Mapping[str, Any], action: Mapping[str, Any]
    ) -> dict[str, Any]:
        farm = _farm(observation)
        positions = _positions(farm)
        board_size = len(farm.get("tiles") or []) or BOARD_SIZE
        inventories = _inventories(observation, len(positions))
        units = _unit_actions(action, len(positions))
        market = _market_orders(action)
        self._day_sync(observation, positions)

        for actor in list(self.jobs):
            if actor >= len(positions):
                self._finish(actor, "lost_worker")
        for actor in range(len(units)):
            proposed = units[actor]
            proposed, service_reason = _service_policy(
                observation, positions[actor], proposed
            )
            if service_reason:
                self._event(
                    "service_suppressed", actor=actor, reason=service_reason
                )
            proposed, fertilizer_reason = _fertilizer_policy(
                observation, positions[actor], proposed, inventories[actor]
            )
            if fertilizer_reason:
                self._event(
                    "fertilizer_policy_changed",
                    actor=actor,
                    reason=fertilizer_reason,
                )
            if actor in self.jobs:
                units[actor] = self._execute_job(
                    actor,
                    observation,
                    farm,
                    positions[actor],
                    inventories[actor],
                    board_size,
                )
            else:
                operation = str(proposed[0]) if proposed else "PASS"
                if operation in MOVES:
                    dx, dy = MOVES[operation]
                    destination = (positions[actor][0] + dx, positions[actor][1] + dy)
                    destination_tile = _mapping(_tile(farm, destination))
                    shed = _mapping(_mapping(observation.get("private")).get("shed"))
                    source = (
                        _current_route_source(self.policy_observation(observation))
                        if ENABLE_EXECUTION_TRANSACTIONS
                        else -1
                    )
                    next_action = (
                        _source_actor_action(source, self.last_step + 1, actor)
                        if ENABLE_EXECUTION_TRANSACTIONS
                        else None
                    )
                    following_action = (
                        _source_actor_action(source, self.last_step + 2, actor)
                        if ENABLE_EXECUTION_TRANSACTIONS
                        else None
                    )
                    if (
                        ENABLE_EXECUTION_TRANSACTIONS
                        and
                        _is_shed(positions[actor], board_size)
                        and _integer(inventories[actor].get("WHEAT")) <= 0
                        and _integer(shed.get("WHEAT")) > 0
                        and "animal" in destination_tile
                        and not bool(destination_tile.get("fed_today"))
                        and next_action is not None
                        and len(next_action) >= 2
                        and next_action[0] == "PICKUP"
                        and next_action[1] == "WHEAT"
                        and following_action is not None
                        and following_action[0] == "FEED"
                    ):
                        planned_quantity = (
                            max(1, _integer(next_action[2], 1))
                            if len(next_action) >= 3
                            else 1
                        )
                        self.shadow_positions[actor] = destination
                        self.shadow_inventory[(actor, "WHEAT")] = _integer(
                            inventories[actor].get("WHEAT")
                        )
                        self.shadow_shed.setdefault("WHEAT", _integer(shed.get("WHEAT")))
                        job = self._start_job(
                            actor,
                            "feed_prefetch_swap",
                            item="WHEAT",
                            initial=0,
                            reserve=min(5, planned_quantity),
                            quantity=min(5, planned_quantity),
                            saved_move=list(proposed),
                            target=list(destination),
                            route_source=source,
                        )
                        available = self._available_shed(
                            observation, "WHEAT", actor
                        )
                        quantity = min(
                            5,
                            available,
                            max(1, _integer(job.get("quantity"), 1)),
                        )
                        job["attempts"] += 1
                        job["awaiting"] = {
                            "op": "PICKUP",
                            "item": "WHEAT",
                            "before": 0,
                        }
                        units[actor] = ["PICKUP", "WHEAT", quantity]
                        continue
                    carried_products = [
                        (str(item), _integer(quantity))
                        for item, quantity in inventories[actor].items()
                        if _integer(quantity) > 0
                        and item not in {*ANIMAL_STRUCTURE, "WHEAT", "FERTILIZER"}
                    ]
                    if (
                        ENABLE_EXECUTION_TRANSACTIONS
                        and
                        destination_tile == {}
                        and _tile(farm, destination) == "LOCKED"
                        and carried_products
                        and next_action is not None
                        and len(next_action) >= 2
                        and next_action[0] in {"PLACE", "DROP"}
                        and following_action is not None
                        and following_action[0] in MOVES
                    ):
                        follow_dx, follow_dy = MOVES[str(following_action[0])]
                        rejoin = (
                            destination[0] + follow_dx,
                            destination[1] + follow_dy,
                        )
                        detour_tiles = [
                            target
                            for target in _shed_tiles(board_size)
                            if _distance(positions[actor], target) == 1
                            and _distance(target, rejoin) == 1
                        ]
                        if not detour_tiles:
                            units[actor] = self._preflight(
                                actor,
                                proposed,
                                observation,
                                farm,
                                positions[actor],
                                inventories[actor],
                                board_size,
                                market,
                            )
                            continue
                        prices = _mapping(
                            _mapping(observation.get("market")).get("prices")
                        )
                        carried_products.sort(
                            key=lambda pair: (
                                -_integer(prices.get(pair[0])) * pair[1],
                                pair[0],
                            )
                        )
                        item, quantity = carried_products[0]
                        if next_action[0] == "PLACE" and str(next_action[1]) != item:
                            units[actor] = self._preflight(
                                actor,
                                proposed,
                                observation,
                                farm,
                                positions[actor],
                                inventories[actor],
                                board_size,
                                market,
                            )
                            continue
                        shed_target = min(detour_tiles, key=lambda pos: (pos[1], pos[0]))
                        self.shadow_positions[actor] = destination
                        self.shadow_inventory[(actor, item)] = quantity
                        self.shadow_shed.setdefault(item, _integer(shed.get(item)))
                        self._start_job(
                            actor,
                            "deposit_detour",
                            item=item,
                            quantity=quantity,
                            shed_target=list(shed_target),
                            rejoin=list(rejoin),
                            phase="to_shed",
                            route_source=source,
                        )
                        units[actor] = _move_toward(positions[actor], shed_target)
                        continue
                units[actor] = self._preflight(
                    actor,
                    proposed,
                    observation,
                    farm,
                    positions[actor],
                    inventories[actor],
                    board_size,
                    market,
                )

        market = self._guard_animal_purchases(observation, farm, units, market)
        if _integer(observation.get("hour")) < 23:
            hires = sum(bool(order) and order[0] == "HIRE" for order in market)
            if hires:
                self.expected_new_hands = _spawn_sequence(farm, hires, board_size)
        return {
            "farmer": units[0] if units else ["PASS"],
            "hands": units[1:],
            "market": market,
        }

    def diagnostics(self) -> dict[str, Any]:
        return {
            "version": "v126_exec",
            "step": self.last_step,
            "day": self.day,
            "flags": {
                "execution_jobs": True,
                "execution_transactions": ENABLE_EXECUTION_TRANSACTIONS,
                "animal_purchase_guard": ENABLE_ANIMAL_PURCHASE_GUARD,
                "general_job_recovery": ENABLE_GENERAL_JOB_RECOVERY,
                "service_policy": ENABLE_SERVICE_POLICY,
                "fertilizer_policy": ENABLE_FERTILIZER_POLICY,
            },
            "trigger_counts": dict(self.counts),
            "active_jobs": copy.deepcopy(self.jobs),
            "transaction_source_latch": self.source_latch,
            "expected_new_hands": copy.deepcopy(self.expected_new_hands),
            "recent_events": copy.deepcopy(self.last_events),
        }


_COORDINATORS = {0: ExecutionCoordinator(0), 1: ExecutionCoordinator(1)}

_V125_ROUTE_CHOOSER = _v124_module().sparse._choose_row


def _transaction_choose_row(
    observation: Mapping[str, Any],
    rows: Sequence[list[Any]],
    query: Sequence[int],
) -> list[Any]:
    """Preserve V125's farm-wide router; E latches only the repaired actor."""
    return _V125_ROUTE_CHOOSER(observation, rows, query)


_v124_module().sparse._choose_row = _transaction_choose_row


def reset_runtime_state() -> None:
    if hasattr(base, "base") and hasattr(base.base, "reset_runtime_state"):
        base.base.reset_runtime_state()
    for coordinator in _COORDINATORS.values():
        coordinator.reset()


def latest_diagnostics(seat: int = 0) -> dict[str, Any]:
    return _COORDINATORS[1 if int(seat) == 1 else 0].diagnostics()


def agent(observation: Mapping[str, Any]) -> dict[str, Any]:
    coordinator = _COORDINATORS[_seat(observation)]
    coordinator._day_sync(observation, _positions(_farm(observation)))
    proposed = base.agent(coordinator.policy_observation(observation))
    return coordinator.repair(observation, proposed)
