"""Round5 engine-pinned contracts, typed targets, and effect attribution.

The definitions in this module match kaggle-environments 1.32.7.  They are
standard-library only and are packaged unchanged with every Round5 arm.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Literal

CROP_RULES: dict[str, dict[str, int | bool]] = {
    "WHEAT": {"first_yield_day": 2, "max_yield_day": 4, "ongoing": False},
    "CARROT": {"first_yield_day": 2, "max_yield_day": 3, "ongoing": False},
    "TOMATO": {"first_yield_day": 8, "max_yield_day": 8, "ongoing": True},
    "STRAWBERRY": {"first_yield_day": 10, "max_yield_day": 10, "ongoing": True},
    "MELON": {"first_yield_day": 10, "max_yield_day": 12, "ongoing": False},
}
ANIMAL_RULES: dict[str, dict[str, int | str]] = {
    "GOOSE": {"first_yield_day": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW": {"first_yield_day": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"first_yield_day": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}
SHED_TILES = ((4, 4), (5, 4), (4, 5), (5, 5))
Status = Literal["ESTABLISHED", "FAILED", "UNKNOWN", "NOT_APPLICABLE"]


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def canonical_step(observation: Mapping[str, Any]) -> int:
    if "step" in observation:
        return _integer(observation.get("step"))
    return 24 * _integer(observation.get("day")) + _integer(observation.get("hour"))


def actor_positions(observation: Mapping[str, Any]) -> list[tuple[int, int]]:
    seat = _integer(observation.get("player"))
    farms = list(observation.get("farms") or [])
    if not 0 <= seat < len(farms):
        return []
    farm = farms[seat]
    raw = [farm.get("farmer") or (0, 0), *(farm.get("hands") or [])]
    return [(int(value[0]), int(value[1])) for value in raw]


def actor_inventory(observation: Mapping[str, Any], actor: int) -> Mapping[str, Any]:
    values = list((observation.get("private") or {}).get("inventories") or [])
    return values[actor] if 0 <= actor < len(values) and isinstance(values[actor], Mapping) else {}


def own_farm(observation: Mapping[str, Any]) -> Mapping[str, Any]:
    seat = _integer(observation.get("player"))
    farms = list(observation.get("farms") or [])
    return farms[seat] if 0 <= seat < len(farms) else {}


def tile_at(observation: Mapping[str, Any], position: Sequence[int]) -> Any:
    rows = list(own_farm(observation).get("tiles") or [])
    x, y = _integer(position[0], -1), _integer(position[1], -1)
    return rows[y][x] if 0 <= y < len(rows) and 0 <= x < len(rows[y]) else "LOCKED"


def inventory_total(inventory: Mapping[str, Any]) -> int:
    return sum(max(0, _integer(value)) for value in inventory.values())


def actor_identity(observation: Mapping[str, Any], actor: int) -> dict[str, Any]:
    positions = actor_positions(observation)
    return {
        "seat": _integer(observation.get("player")),
        "actor_index": actor,
        "role": "farmer" if actor == 0 else "hand",
        "day_epoch": _integer(observation.get("day")),
        "position": list(positions[actor]) if 0 <= actor < len(positions) else None,
    }


def actor_identity_matches(observation: Mapping[str, Any], identity: Mapping[str, Any]) -> bool:
    actor = _integer(identity.get("actor_index"), -1)
    positions = actor_positions(observation)
    return (
        _integer(observation.get("player"), -1) == _integer(identity.get("seat"), -2)
        and _integer(observation.get("day"), -1) == _integer(identity.get("day_epoch"), -2)
        and 0 <= actor < len(positions)
    )


def animal_product(tile: Mapping[str, Any]) -> str | None:
    animal = str(tile.get("animal") or "")
    rule = ANIMAL_RULES.get(animal)
    return str(rule["product"]) if rule else None


def target_identity(tile: Any, position: Sequence[int]) -> dict[str, Any]:
    value = tile if isinstance(tile, Mapping) else {}
    if value.get("kind") == "PLANT":
        return {
            "type": "crop",
            "coordinate": [int(position[0]), int(position[1])],
            "resource": value.get("crop"),
            "generation_or_placement_day": value.get("planted_day"),
        }
    if value.get("animal"):
        return {
            "type": "animal",
            "coordinate": [int(position[0]), int(position[1])],
            "resource": value.get("animal"),
            "product": animal_product(value),
            "generation_or_placement_day": value.get("placed_day"),
        }
    return {"type": "tile", "coordinate": [int(position[0]), int(position[1])], "resource": None}


@dataclass(frozen=True)
class Precondition:
    applicable: bool
    reason: str
    actor: int
    target: tuple[int, int] | None
    target_type: str | None = None
    resource: str | None = None
    product: str | None = None
    age_days: int | None = None
    yield_units: int = 0
    generation_or_placement_day: int | None = None


def harvestability(observation: Mapping[str, Any], actor: int) -> Precondition:
    """Return the crop-or-animal HARVEST precondition used by the fixed engine."""
    positions = actor_positions(observation)
    if not 0 <= actor < len(positions):
        return Precondition(False, "ACTOR_MISSING", actor, None)
    position = positions[actor]
    tile = tile_at(observation, position)
    if tile == "LOCKED":
        return Precondition(False, "TARGET_NOT_OWNED_OR_LOCKED", actor, position)
    if not isinstance(tile, Mapping):
        return Precondition(False, "TARGET_NOT_HARVESTABLE", actor, position)
    yield_units = max(0, _integer(tile.get("yield_units")))
    day = _integer(observation.get("day"))
    if tile.get("kind") == "PLANT":
        crop = str(tile.get("crop") or "")
        rule = CROP_RULES.get(crop)
        if rule is None:
            return Precondition(False, "UNKNOWN_CROP", actor, position, "crop", crop)
        planted = _integer(tile.get("planted_day"))
        age = day - planted
        if age < _integer(rule["first_yield_day"]):
            return Precondition(
                False,
                "HARVEST_PRECONDITION_FAILED:IMMATURE",
                actor,
                position,
                "crop",
                crop,
                crop,
                age,
                yield_units,
                planted,
            )
        if yield_units <= 0:
            return Precondition(False, "HARVEST_PRECONDITION_FAILED:NO_YIELD", actor, position, "crop", crop, crop, age, 0, planted)
        return Precondition(True, "HARVESTABLE:CROP", actor, position, "crop", crop, crop, age, yield_units, planted)
    if tile.get("animal"):
        animal = str(tile.get("animal"))
        rule = ANIMAL_RULES.get(animal)
        if rule is None:
            return Precondition(False, "UNKNOWN_ANIMAL", actor, position, "animal", animal)
        placed = _integer(tile.get("placed_day"))
        product = str(rule["product"])
        if yield_units <= 0:
            return Precondition(False, "HARVEST_PRECONDITION_FAILED:NO_YIELD", actor, position, "animal", animal, product, day - placed, 0, placed)
        return Precondition(True, "HARVESTABLE:ANIMAL", actor, position, "animal", animal, product, day - placed, yield_units, placed)
    return Precondition(False, "TARGET_NOT_HARVESTABLE", actor, position)


def crop_harvestability(observation: Mapping[str, Any], actor: int) -> Precondition:
    result = harvestability(observation, actor)
    return result if result.target_type == "crop" else Precondition(False, "TARGET_NOT_CROP", actor, result.target)


def next_animal_production_day(tile: Mapping[str, Any], current_day: int, *, strictly_after: bool = False) -> int | None:
    animal = str(tile.get("animal") or "")
    rule = ANIMAL_RULES.get(animal)
    if not rule:
        return None
    first = _integer(tile.get("placed_day")) + _integer(rule["first_yield_day"])
    target = current_day + (1 if strictly_after else 0)
    if target <= first:
        return first
    interval = max(1, _integer(rule["interval"]))
    return first + ((target - first + interval - 1) // interval) * interval


@dataclass
class TypedPlan:
    plan_id: str
    strategy_mode: str
    job_type: str
    origin: str
    seat: int
    actor_index: int
    day_epoch: int
    created_step: int
    deadline_step: int
    target: tuple[int, int]
    target_identity: dict[str, Any]
    primitives: list[list[Any]]
    required_resources: dict[str, int] = field(default_factory=dict)
    resource_reservations: dict[str, int] = field(default_factory=dict)
    remaining_obligations: dict[str, int] = field(default_factory=dict)
    primitive_postconditions: list[str] = field(default_factory=list)
    completion_postconditions: list[str] = field(default_factory=list)
    abort_and_replan_conditions: list[str] = field(default_factory=list)
    policy_state_digest: str = ""

    @property
    def success_postconditions(self) -> list[str]:
        return self.completion_postconditions

    def contract(self) -> dict[str, Any]:
        result = asdict(self)
        result["target"] = list(self.target)
        result["ordered_primitives"] = result.pop("primitives")
        result["actor_identity"] = {"seat": self.seat, "actor_index": self.actor_index, "day_epoch": self.day_epoch}
        return result


def make_harvest_plan(
    observation: Mapping[str, Any], actor: int, *, strategy_mode: str = "executor", origin: str = "engine_rule"
) -> tuple[TypedPlan | None, Precondition]:
    precondition = harvestability(observation, actor)
    if not precondition.applicable or precondition.target is None or precondition.product is None:
        return None, precondition
    step = canonical_step(observation)
    tile = tile_at(observation, precondition.target)
    plan = TypedPlan(
        plan_id=f"HARVEST:{precondition.target_type}:{precondition.resource}:a{actor}:s{step}",
        strategy_mode=strategy_mode,
        job_type="HARVEST",
        origin=origin,
        seat=_integer(observation.get("player")),
        actor_index=actor,
        day_epoch=_integer(observation.get("day")),
        created_step=step,
        deadline_step=step,
        target=precondition.target,
        target_identity=target_identity(tile, precondition.target),
        primitives=[["HARVEST"]],
        resource_reservations={f"target:{precondition.target[0]},{precondition.target[1]}:{precondition.product}": precondition.yield_units},
        primitive_postconditions=[f"actor_inventory_increased:{precondition.product}", "target_yield_decreased"],
        completion_postconditions=["harvest_attributed_to_actor", "single_owner_for_consumed_yield"],
        abort_and_replan_conditions=["target_changed", "yield_consumed", "actor_identity_changed"],
    )
    return plan, precondition


def _route(left: tuple[int, int], right: tuple[int, int]) -> list[list[str]]:
    x, y = left
    result: list[list[str]] = []
    while (x, y) != right:
        if x < right[0]:
            x += 1
            result.append(["EAST"])
        elif x > right[0]:
            x -= 1
            result.append(["WEST"])
        elif y < right[1]:
            y += 1
            result.append(["SOUTH"])
        else:
            y -= 1
            result.append(["NORTH"])
    return result


def make_feed_plan(
    observation: Mapping[str, Any],
    actor: int,
    target: tuple[int, int],
    required_wheat: int,
    policy_state_digest: str = "",
    *,
    strategy_mode: str = "executor",
    origin: str = "engine_rule",
) -> TypedPlan:
    positions = actor_positions(observation)
    position = positions[actor]
    inventory = actor_inventory(observation, actor)
    primitives: list[list[Any]] = []
    missing = max(0, required_wheat - _integer(inventory.get("WHEAT")))
    if missing:
        shed = min(SHED_TILES, key=lambda value: (abs(value[0] - position[0]) + abs(value[1] - position[1]), value))
        primitives.extend(_route(position, shed))
        primitives.append(["PICKUP", "WHEAT", missing])
        primitives.extend(_route(shed, target))
    else:
        primitives.extend(_route(position, target))
    primitives.append(["FEED"])
    step = canonical_step(observation)
    day = _integer(observation.get("day"))
    target_tile = tile_at(observation, target)
    return TypedPlan(
        plan_id=f"ANIMAL_MAINTAIN:a{actor}:s{step}:{target[0]},{target[1]}",
        strategy_mode=strategy_mode,
        job_type="ANIMAL_MAINTENANCE",
        origin=origin,
        seat=_integer(observation.get("player")),
        actor_index=actor,
        day_epoch=day,
        created_step=step,
        deadline_step=day * 24 + 23,
        target=target,
        target_identity=target_identity(target_tile, target),
        primitives=primitives,
        required_resources={"WHEAT": required_wheat},
        resource_reservations={"WHEAT": required_wheat},
        remaining_obligations={"FEED": required_wheat},
        primitive_postconditions=["actor_wheat_consumed", "target_fed_transition"],
        completion_postconditions=["feed_attributed_to_actor", "remaining_wheat_reserved"],
        abort_and_replan_conditions=["target_already_serviced", "target_gone", "day_epoch_changed", "retirement_selected"],
        policy_state_digest=policy_state_digest,
    )


def observation_digest(observation: Mapping[str, Any], actor: int) -> str:
    payload = {
        "identity": actor_identity(observation, actor),
        "step": canonical_step(observation),
        "hour": _integer(observation.get("hour")),
        "inventory": dict(actor_inventory(observation, actor)),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class RejoinSnapshot:
    identity: dict[str, Any]
    position: tuple[int, int]
    inventory: dict[str, int]
    step: int
    hour: int
    material_reservations: dict[str, int]
    policy_state_digest: str


def capture_rejoin_snapshot(
    observation: Mapping[str, Any], actor: int, material_reservations: Mapping[str, int], policy_state_digest: str
) -> RejoinSnapshot:
    positions = actor_positions(observation)
    return RejoinSnapshot(
        identity=actor_identity(observation, actor),
        position=positions[actor],
        inventory={str(key): _integer(value) for key, value in actor_inventory(observation, actor).items()},
        step=canonical_step(observation),
        hour=_integer(observation.get("hour")),
        material_reservations={str(key): _integer(value) for key, value in material_reservations.items()},
        policy_state_digest=policy_state_digest,
    )


def prove_rejoin(
    observation: Mapping[str, Any], snapshot: RejoinSnapshot, material_reservations: Mapping[str, int], policy_state_digest: str
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    actor = _integer(snapshot.identity.get("actor_index"), -1)
    if not actor_identity_matches(observation, snapshot.identity):
        return False, ["REJOIN_ACTOR_IDENTITY_OR_DAY_MISMATCH"]
    positions = actor_positions(observation)
    if positions[actor] != snapshot.position:
        reasons.append("REJOIN_POSITION_MISMATCH")
    inventory = {str(key): _integer(value) for key, value in actor_inventory(observation, actor).items()}
    if inventory != snapshot.inventory:
        reasons.append("REJOIN_INVENTORY_MISMATCH")
    if canonical_step(observation) != snapshot.step or _integer(observation.get("hour")) != snapshot.hour:
        reasons.append("REJOIN_TIME_MISMATCH")
    if {str(key): _integer(value) for key, value in material_reservations.items()} != snapshot.material_reservations:
        reasons.append("REJOIN_RESERVATION_MISMATCH")
    if policy_state_digest != snapshot.policy_state_digest:
        reasons.append("REJOIN_POLICY_STATE_MISMATCH")
    return not reasons, reasons


def _product_for_harvest(tile: Mapping[str, Any]) -> str | None:
    if tile.get("kind") == "PLANT":
        return str(tile.get("crop") or "") or None
    return animal_product(tile)


def attribute_primitive(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    actor: int,
    action: Sequence[Any],
    target: tuple[int, int] | None = None,
) -> tuple[Status, str]:
    """Attribute effects to the issuing actor; target-only change is insufficient."""
    if not action:
        return "NOT_APPLICABLE", "EMPTY_ACTION"
    op = str(action[0])
    before_positions, after_positions = actor_positions(before), actor_positions(after)
    if not 0 <= actor < len(before_positions) or not 0 <= actor < len(after_positions):
        return "UNKNOWN", "ACTOR_IDENTITY_NOT_OBSERVABLE"
    before_inventory, after_inventory = actor_inventory(before, actor), actor_inventory(after, actor)
    position = target or before_positions[actor]
    before_tile, after_tile = tile_at(before, position), tile_at(after, position)
    before_map = before_tile if isinstance(before_tile, Mapping) else {}
    after_map = after_tile if isinstance(after_tile, Mapping) else {}
    day_boundary = _integer(after.get("day")) != _integer(before.get("day"))
    if op in {"NORTH", "SOUTH", "EAST", "WEST"}:
        if day_boundary:
            return "UNKNOWN", "MOVE_DAY_BOUNDARY_ACTOR_RESET"
        return (("ESTABLISHED", "ACTOR_POSITION_CHANGED") if before_positions[actor] != after_positions[actor] else ("FAILED", "MOVE_NOT_OBSERVED"))
    if op == "PICKUP" and len(action) >= 2:
        item = str(action[1])
        delta = _integer(after_inventory.get(item)) - _integer(before_inventory.get(item))
        return (("ESTABLISHED", f"ACTOR_INVENTORY_DELTA:{item}:{delta}") if delta > 0 else ("FAILED", "PICKUP_NOT_OBSERVED"))
    if op == "HARVEST":
        product = _product_for_harvest(before_map)
        if product is None:
            return "FAILED", "HARVEST_TARGET_NOT_TYPED"
        delta = _integer(after_inventory.get(product)) - _integer(before_inventory.get(product))
        before_yield, after_yield = _integer(before_map.get("yield_units")), _integer(after_map.get("yield_units"))
        target_consumed = before_yield > 0 and (after_yield < before_yield or after_tile is None)
        if not day_boundary and delta > 0 and target_consumed:
            return "ESTABLISHED", f"HARVEST_ATTRIBUTED:{product}:{delta}"
        if day_boundary and target_consumed:
            return "UNKNOWN", f"HARVEST_DAY_BOUNDARY:{product}"
        if delta <= 0 and not target_consumed:
            return "FAILED", "HARVEST_NO_ACTOR_INVENTORY_OR_TARGET_DELTA"
        return "UNKNOWN", "HARVEST_PARTIAL_DELTA_NOT_ATTRIBUTABLE"
    if op == "FEED":
        if day_boundary:
            return "UNKNOWN", "FEED_DAY_BOUNDARY_RESET"
        wheat_delta = _integer(after_inventory.get("WHEAT")) - _integer(before_inventory.get("WHEAT"))
        transition = not bool(before_map.get("fed_today")) and bool(after_map.get("fed_today"))
        if wheat_delta == -1 and transition:
            return "ESTABLISHED", "FEED_ATTRIBUTED_BY_ACTOR_WHEAT_AND_TARGET"
        if transition and wheat_delta == 0:
            return "FAILED", "FEED_TARGET_CHANGED_BY_OTHER_ACTOR"
        if not transition and wheat_delta == 0:
            return "FAILED", "FEED_NO_EFFECT"
        return "UNKNOWN", "FEED_ATTRIBUTION_AMBIGUOUS"
    if op == "WATER":
        if day_boundary:
            return "UNKNOWN", "WATER_DAY_BOUNDARY_RESET"
        transition = not bool(before_map.get("watered_today")) and bool(after_map.get("watered_today"))
        if transition:
            return "ESTABLISHED", "WATER_TARGET_TRANSITION"
        same_plant = (
            before_map.get("kind") == "PLANT"
            and after_map.get("kind") == "PLANT"
            and before_map.get("crop") == after_map.get("crop")
            and before_map.get("planted_day") == after_map.get("planted_day")
        )
        if not same_plant:
            return "UNKNOWN", "WATER_TARGET_CHANGED_LATER_IN_JOINT"
        return "FAILED", "WATER_NO_EFFECT"
    if op == "CARE":
        if day_boundary:
            return "UNKNOWN", "CARE_DAY_BOUNDARY_RESET"
        transition = not bool(before_map.get("cared_today")) and bool(after_map.get("cared_today"))
        return (("ESTABLISHED", "CARE_TARGET_TRANSITION") if transition else ("FAILED", "CARE_NO_EFFECT"))
    if op == "COLLECT_FERTILIZER":
        if day_boundary:
            return "UNKNOWN", "FERTILIZER_DAY_BOUNDARY_INVENTORY_DROP"
        delta = _integer(after_inventory.get("FERTILIZER")) - _integer(before_inventory.get("FERTILIZER"))
        return (("ESTABLISHED", "FERTILIZER_ATTRIBUTED") if delta > 0 else ("FAILED", "FERTILIZER_NOT_OBSERVED"))
    if op == "PLANT":
        crop = str(action[1]) if len(action) > 1 else ""
        ok = after_map.get("kind") == "PLANT" and after_map.get("crop") == crop and before_tile is None
        return (("ESTABLISHED", f"PLANT_ESTABLISHED:{crop}") if ok else ("FAILED", "PLANT_NOT_OBSERVED"))
    if op == "DIG":
        ok = before_tile is not None and not (isinstance(before_tile, Mapping) and before_tile.get("animal")) and after_tile is None
        return (("ESTABLISHED", "DIG_TARGET_REMOVED") if ok else ("FAILED", "DIG_NOT_OBSERVED"))
    if op in {"BUILD_COOP", "BUILD_PASTURE"}:
        expected = "COOP" if op == "BUILD_COOP" else "PASTURE"
        ok = before_tile is None and after_map.get("kind") == expected
        return (("ESTABLISHED", f"BUILD_ESTABLISHED:{expected}") if ok else ("FAILED", "BUILD_NOT_OBSERVED"))
    if op in {"DROP", "PLACE"}:
        return (("ESTABLISHED", "ACTOR_INVENTORY_DECREASED") if inventory_total(after_inventory) < inventory_total(before_inventory) else ("FAILED", "DEPOSIT_NOT_OBSERVED"))
    return "NOT_APPLICABLE", f"UNTRACKED_PRIMITIVE:{op}"


__all__ = [
    "ANIMAL_RULES",
    "CROP_RULES",
    "Precondition",
    "RejoinSnapshot",
    "SHED_TILES",
    "TypedPlan",
    "actor_identity",
    "actor_identity_matches",
    "actor_inventory",
    "actor_positions",
    "animal_product",
    "attribute_primitive",
    "canonical_step",
    "capture_rejoin_snapshot",
    "crop_harvestability",
    "harvestability",
    "inventory_total",
    "make_feed_plan",
    "make_harvest_plan",
    "next_animal_production_day",
    "observation_digest",
    "own_farm",
    "prove_rejoin",
    "target_identity",
    "tile_at",
]
