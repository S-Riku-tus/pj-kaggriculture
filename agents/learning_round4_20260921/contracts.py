"""Engine-pinned preconditions, typed plans, attribution, and rejoin proofs.

The module is standard-library only so the exact same checks are used by local
tests and submission archives.  It is pinned to Kaggriculture 1.32.7.
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
SERVICE_OPS = frozenset({"FEED", "WATER", "CARE"})
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


@dataclass(frozen=True)
class Precondition:
    applicable: bool
    reason: str
    actor: int
    target: tuple[int, int] | None
    crop: str | None = None
    age_days: int | None = None
    yield_units: int = 0


def crop_harvestability(observation: Mapping[str, Any], actor: int) -> Precondition:
    """Return the actual engine HARVEST precondition for an owned crop tile."""
    positions = actor_positions(observation)
    if not 0 <= actor < len(positions):
        return Precondition(False, "ACTOR_MISSING", actor, None)
    position = positions[actor]
    tile = tile_at(observation, position)
    if tile == "LOCKED":
        return Precondition(False, "TARGET_NOT_OWNED_OR_LOCKED", actor, position)
    if not isinstance(tile, Mapping) or tile.get("kind") != "PLANT":
        return Precondition(False, "TARGET_NOT_CROP", actor, position)
    crop = str(tile.get("crop") or "")
    rule = CROP_RULES.get(crop)
    if rule is None:
        return Precondition(False, "UNKNOWN_CROP", actor, position, crop=crop)
    age = _integer(observation.get("day")) - _integer(tile.get("planted_day"))
    yield_units = max(0, _integer(tile.get("yield_units")))
    if age < _integer(rule["first_yield_day"]):
        return Precondition(
            False,
            "HARVEST_PRECONDITION_FAILED:IMMATURE",
            actor,
            position,
            crop=crop,
            age_days=age,
            yield_units=yield_units,
        )
    if yield_units <= 0:
        return Precondition(
            False,
            "HARVEST_PRECONDITION_FAILED:NO_YIELD",
            actor,
            position,
            crop=crop,
            age_days=age,
            yield_units=yield_units,
        )
    return Precondition(True, "HARVESTABLE", actor, position, crop, age, yield_units)


@dataclass
class TypedPlan:
    plan_id: str
    job_type: str
    seat: int
    actor_index: int
    day_epoch: int
    created_step: int
    deadline_step: int
    target: tuple[int, int]
    primitives: list[list[Any]]
    required_resources: dict[str, int] = field(default_factory=dict)
    remaining_obligations: dict[str, int] = field(default_factory=dict)
    primitive_postconditions: list[str] = field(default_factory=list)
    success_postconditions: list[str] = field(default_factory=list)
    abort_and_replan_conditions: list[str] = field(default_factory=list)
    policy_state_digest: str = ""

    def contract(self) -> dict[str, Any]:
        result = asdict(self)
        result["target"] = list(self.target)
        result["continuation"] = result.pop("primitives")
        result["actor_identity"] = {
            "seat": self.seat,
            "actor_index": self.actor_index,
            "day_epoch": self.day_epoch,
        }
        return result


def make_harvest_plan(observation: Mapping[str, Any], actor: int) -> tuple[TypedPlan | None, Precondition]:
    precondition = crop_harvestability(observation, actor)
    if not precondition.applicable or precondition.target is None or precondition.crop is None:
        return None, precondition
    step = canonical_step(observation)
    plan = TypedPlan(
        plan_id=f"HARVEST:{precondition.crop}:a{actor}:s{step}",
        job_type="HARVEST",
        seat=_integer(observation.get("player")),
        actor_index=actor,
        day_epoch=_integer(observation.get("day")),
        created_step=step,
        deadline_step=step,
        target=precondition.target,
        primitives=[["HARVEST"]],
        primitive_postconditions=["actor_crop_inventory_increased", "target_tile_changed"],
        success_postconditions=["harvest_attributed_to_actor"],
        abort_and_replan_conditions=["target_changed", "crop_immature", "actor_identity_changed"],
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
    return TypedPlan(
        plan_id=f"ANIMAL_SERVICE:a{actor}:s{step}:{target[0]},{target[1]}",
        job_type="ANIMAL_SERVICE_WITH_CONTINUATION",
        seat=_integer(observation.get("player")),
        actor_index=actor,
        day_epoch=day,
        created_step=step,
        deadline_step=day * 24 + 23,
        target=target,
        primitives=primitives,
        required_resources={"WHEAT": required_wheat},
        remaining_obligations={"FEED": required_wheat},
        primitive_postconditions=["actor_wheat_consumed", "target_fed_transition"],
        success_postconditions=["feed_attributed_to_actor", "remaining_wheat_reserved"],
        abort_and_replan_conditions=["target_already_serviced", "target_gone", "day_epoch_changed"],
        policy_state_digest=policy_state_digest,
    )


def service_reservations(
    observation: Mapping[str, Any], action: Mapping[str, Any]
) -> tuple[dict[tuple[str, int, int, int], int], dict[int, str]]:
    """Reserve effective same-target services in engine actor order."""
    positions = actor_positions(observation)
    units = [list(action.get("farmer") or ["PASS"]), *[list(value or ["PASS"]) for value in action.get("hands") or []]]
    units = (units + [["PASS"]] * len(positions))[: len(positions)]
    day = _integer(observation.get("day"))
    reserved: dict[tuple[str, int, int, int], int] = {}
    rejected: dict[int, str] = {}
    for actor, unit in enumerate(units):
        op = str(unit[0]) if unit else "PASS"
        if op not in SERVICE_OPS or actor >= len(positions):
            continue
        x, y = positions[actor]
        tile = tile_at(observation, (x, y))
        tile_map = tile if isinstance(tile, Mapping) else {}
        valid = False
        if op == "FEED":
            valid = (
                bool(tile_map.get("animal"))
                and not bool(tile_map.get("fed_today"))
                and _integer(actor_inventory(observation, actor).get("WHEAT")) > 0
            )
        elif op == "WATER":
            valid = tile_map.get("kind") == "PLANT" and not bool(tile_map.get("watered_today"))
        elif op == "CARE":
            valid = bool(tile_map.get("animal")) and not bool(tile_map.get("cared_today"))
        if not valid:
            rejected[actor] = f"{op}_PRECONDITION_FAILED"
            continue
        key = (op, x, y, day)
        if key in reserved:
            rejected[actor] = f"DUPLICATE_SERVICE:{op}:{x},{y}:reserved_by_actor_{reserved[key]}"
        else:
            reserved[key] = actor
    return reserved, rejected


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
    observation: Mapping[str, Any],
    actor: int,
    material_reservations: Mapping[str, int],
    policy_state_digest: str,
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
    observation: Mapping[str, Any],
    snapshot: RejoinSnapshot,
    material_reservations: Mapping[str, int],
    policy_state_digest: str,
) -> tuple[bool, list[str]]:
    """A strict proof; failure requires state-based replanning, never stale resume."""
    reasons: list[str] = []
    actor = _integer(snapshot.identity.get("actor_index"), -1)
    if not actor_identity_matches(observation, snapshot.identity):
        reasons.append("REJOIN_ACTOR_IDENTITY_OR_DAY_MISMATCH")
        return False, reasons
    positions = actor_positions(observation)
    if positions[actor] != snapshot.position:
        reasons.append("REJOIN_POSITION_MISMATCH")
    inventory = {str(key): _integer(value) for key, value in actor_inventory(observation, actor).items()}
    if inventory != snapshot.inventory:
        reasons.append("REJOIN_INVENTORY_MISMATCH")
    if canonical_step(observation) != snapshot.step or _integer(observation.get("hour")) != snapshot.hour:
        reasons.append("REJOIN_TIME_MISMATCH")
    current_reservations = {str(key): _integer(value) for key, value in material_reservations.items()}
    if current_reservations != snapshot.material_reservations:
        reasons.append("REJOIN_RESERVATION_MISMATCH")
    if policy_state_digest != snapshot.policy_state_digest:
        reasons.append("REJOIN_POLICY_STATE_MISMATCH")
    return not reasons, reasons


def attribute_primitive(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    actor: int,
    action: Sequence[Any],
    target: tuple[int, int] | None = None,
) -> tuple[Status, str]:
    """Attribute a primitive to one actor using actor-local and target deltas."""
    if not action:
        return "NOT_APPLICABLE", "EMPTY_ACTION"
    op = str(action[0])
    before_positions, after_positions = actor_positions(before), actor_positions(after)
    if not 0 <= actor < len(before_positions) or not 0 <= actor < len(after_positions):
        return "UNKNOWN", "ACTOR_IDENTITY_NOT_OBSERVABLE"
    before_inventory = actor_inventory(before, actor)
    after_inventory = actor_inventory(after, actor)
    position = target or before_positions[actor]
    before_tile, after_tile = tile_at(before, position), tile_at(after, position)
    before_map = before_tile if isinstance(before_tile, Mapping) else {}
    after_map = after_tile if isinstance(after_tile, Mapping) else {}
    if op in {"NORTH", "SOUTH", "EAST", "WEST"}:
        return (
            ("ESTABLISHED", "ACTOR_POSITION_CHANGED")
            if before_positions[actor] != after_positions[actor]
            else ("FAILED", "MOVE_NOT_OBSERVED")
        )
    if op == "PICKUP" and len(action) >= 2:
        item = str(action[1])
        delta = _integer(after_inventory.get(item)) - _integer(before_inventory.get(item))
        return (
            ("ESTABLISHED", f"ACTOR_INVENTORY_DELTA:{item}:{delta}") if delta > 0 else ("FAILED", "PICKUP_NOT_OBSERVED")
        )
    if op == "HARVEST":
        crop = str(before_map.get("crop") or "")
        delta = _integer(after_inventory.get(crop)) - _integer(before_inventory.get(crop))
        target_changed = after_tile != before_tile
        if delta > 0 and target_changed:
            return "ESTABLISHED", f"HARVEST_ATTRIBUTED:{crop}:{delta}"
        if delta <= 0 and not target_changed:
            return "FAILED", "HARVEST_NO_ACTOR_INVENTORY_OR_TILE_DELTA"
        return "UNKNOWN", "HARVEST_PARTIAL_DELTA_NOT_ATTRIBUTABLE"
    if op == "FEED":
        wheat_delta = _integer(after_inventory.get("WHEAT")) - _integer(before_inventory.get("WHEAT"))
        target_transition = not bool(before_map.get("fed_today")) and bool(after_map.get("fed_today"))
        if wheat_delta == -1 and target_transition:
            return "ESTABLISHED", "FEED_ATTRIBUTED_BY_ACTOR_WHEAT_AND_TARGET"
        if target_transition and wheat_delta == 0:
            return "FAILED", "FEED_TARGET_CHANGED_BY_OTHER_ACTOR"
        if not target_transition and wheat_delta == 0:
            return "FAILED", "FEED_NO_EFFECT"
        return "UNKNOWN", "FEED_ATTRIBUTION_AMBIGUOUS"
    if op == "WATER":
        transition = not bool(before_map.get("watered_today")) and bool(after_map.get("watered_today"))
        return ("ESTABLISHED", "WATER_TARGET_TRANSITION") if transition else ("FAILED", "WATER_NO_EFFECT")
    if op == "CARE":
        transition = not bool(before_map.get("cared_today")) and bool(after_map.get("cared_today"))
        return ("ESTABLISHED", "CARE_TARGET_TRANSITION") if transition else ("FAILED", "CARE_NO_EFFECT")
    if op in {"DROP", "PLACE"}:
        return (
            ("ESTABLISHED", "ACTOR_INVENTORY_DECREASED")
            if inventory_total(after_inventory) < inventory_total(before_inventory)
            else ("FAILED", "DEPOSIT_NOT_OBSERVED")
        )
    return "NOT_APPLICABLE", f"UNTRACKED_PRIMITIVE:{op}"


__all__ = [
    "CROP_RULES",
    "Precondition",
    "RejoinSnapshot",
    "TypedPlan",
    "actor_identity",
    "actor_identity_matches",
    "actor_inventory",
    "actor_positions",
    "attribute_primitive",
    "canonical_step",
    "capture_rejoin_snapshot",
    "crop_harvestability",
    "make_feed_plan",
    "make_harvest_plan",
    "observation_digest",
    "prove_rejoin",
    "service_reservations",
    "tile_at",
]
