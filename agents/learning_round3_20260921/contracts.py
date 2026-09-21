"""Typed support checks and enforceable continuation-plan contracts.

This module intentionally uses only the Python standard library so the same
checks can be copied into an isolated Kaggle submission.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

REQUIRED_CONTRACT_FIELDS = (
    "candidate_id",
    "preconditions",
    "actor_identity",
    "reserved_materials",
    "reserved_cash",
    "reserved_shed_capacity",
    "deadline_step",
    "continuation",
    "safe_rejoin_boundary",
    "expected_rejoin",
    "primitive_postconditions",
    "economic_postconditions",
    "abort_policy",
    "replanning_policy",
)


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def actor_identity(observation: Mapping[str, Any], actor_index: int) -> dict[str, Any]:
    """Return an identity that cannot survive hand disappearance/index reuse."""

    seat = _integer(observation.get("player"))
    day = _integer(observation.get("day"))
    farm = observation["farms"][seat]
    positions = [farm.get("farmer", [0, 0]), *(farm.get("hands") or [])]
    if not 0 <= actor_index < len(positions):
        raise IndexError(actor_index)
    role = "farmer" if actor_index == 0 else "hand"
    return {
        "seat": seat,
        "role": role,
        "actor_index": actor_index,
        "day_epoch": None if role == "farmer" else day,
        "observed_position": list(positions[actor_index]),
    }


def actor_identity_matches(observation: Mapping[str, Any], identity: Mapping[str, Any]) -> bool:
    index = _integer(identity.get("actor_index"), -1)
    try:
        current = actor_identity(observation, index)
    except (IndexError, KeyError, TypeError):
        return False
    return (
        current["seat"] == identity.get("seat")
        and current["role"] == identity.get("role")
        and current["day_epoch"] == identity.get("day_epoch")
    )


def validate_contract(contract: Mapping[str, Any]) -> list[str]:
    reasons = [f"MISSING_CONTRACT_FIELD:{field}" for field in REQUIRED_CONTRACT_FIELDS if field not in contract]
    continuation = contract.get("continuation")
    boundary = contract.get("safe_rejoin_boundary")
    if not continuation and not boundary:
        reasons.append("NO_COMPLETE_CONTINUATION_OR_SAFE_REJOIN")
    if contract.get("abort_policy") not in {"KEEP", "SAFE_REPLAN"}:
        reasons.append("INVALID_ABORT_POLICY")
    if contract.get("replanning_policy") not in {"STATE_BASED_ACTOR_REPLAN", "PROVEN_REJOIN"}:
        reasons.append("INVALID_REPLANNING_POLICY")
    if _integer(contract.get("deadline_step"), -1) < 0:
        reasons.append("INVALID_DEADLINE")
    return reasons


def normalize_typed(
    values: Mapping[str, Any], schema: Mapping[str, Mapping[str, Any]]
) -> tuple[list[float], list[str]]:
    """Normalize without applying tiny continuous std-dev to binary features."""

    normalized: list[float] = []
    reasons: list[str] = []
    for name, spec in schema.items():
        raw = values.get(name)
        kind = str(spec.get("kind"))
        try:
            value = float(raw)
        except (TypeError, ValueError):
            normalized.append(0.0)
            reasons.append(f"NONFINITE_OR_MISSING:{name}")
            continue
        if not math.isfinite(value):
            normalized.append(0.0)
            reasons.append(f"NONFINITE_OR_MISSING:{name}")
            continue
        if kind == "binary":
            if value not in {0.0, 1.0}:
                reasons.append(f"INVALID_BINARY:{name}")
                normalized.append(0.0)
            elif bool(spec.get("constant")) and value != float(spec.get("constant_value", 0.0)):
                reasons.append(f"UNSEEN_BINARY_CATEGORY:{name}")
                normalized.append(0.0)
            else:
                normalized.append(value)
        elif kind == "continuous":
            lower = float(spec.get("minimum", -math.inf))
            upper = float(spec.get("maximum", math.inf))
            if value < lower or value > upper:
                reasons.append(f"CONTINUOUS_OUT_OF_SUPPORT:{name}")
            scale = float(spec.get("scale", 0.0))
            if not math.isfinite(scale) or scale <= 0:
                normalized.append(0.0)
                reasons.append(f"INVALID_CONTINUOUS_SCALE:{name}")
            else:
                normalized.append((value - float(spec.get("mean", 0.0))) / scale)
        else:
            normalized.append(0.0)
            reasons.append(f"UNKNOWN_FEATURE_TYPE:{name}")
    return normalized, reasons


def _unit_actions(action: Mapping[str, Any], count: int) -> list[list[Any]]:
    farmer = action.get("farmer")
    result = [list(farmer) if isinstance(farmer, Sequence) and farmer else ["PASS"]]
    for candidate in action.get("hands") or []:
        result.append(list(candidate) if isinstance(candidate, Sequence) and candidate else ["PASS"])
    result.extend([["PASS"] for _ in range(max(0, count - len(result)))])
    return result[:count]


def _inventory(observation: Mapping[str, Any], actor: int) -> Mapping[str, Any]:
    inventories = observation["private"].get("inventories") or []
    return inventories[actor] if actor < len(inventories) else {}


def plan_preserves_obligations(
    observation: Mapping[str, Any], control_action: Sequence[Any], contract: Mapping[str, Any]
) -> list[str]:
    """Reject replacements that erase required acquisition/movement obligations."""

    reasons: list[str] = []
    actor = _integer(contract.get("actor_identity", {}).get("actor_index"), -1)
    continuation = [list(row) for row in contract.get("continuation") or []]
    op = str(control_action[0]) if control_action else "PASS"
    if op == "PICKUP" and len(control_action) >= 2:
        item = str(control_action[1])
        quantity = _integer(control_action[2], 1) if len(control_action) >= 3 else 1
        replacement_pickup = sum(
            _integer(action[2], 1) if len(action) >= 3 else 1
            for action in continuation
            if len(action) >= 2 and action[0] == "PICKUP" and str(action[1]) == item
        )
        reserved = _integer(contract.get("reserved_materials", {}).get(f"actor:{actor}:{item}"))
        obligations = _integer(contract.get("preconditions", {}).get(f"remaining_{item.lower()}_uses"))
        carried = _integer(_inventory(observation, actor).get(item)) if actor >= 0 else 0
        if carried + replacement_pickup + reserved < max(quantity, obligations):
            reasons.append(f"REQUIRED_PICKUP_REMOVED:{item}")
    if op in {"NORTH", "SOUTH", "EAST", "WEST"}:
        if not any(action and action[0] == op for action in continuation) and not contract.get("safe_rejoin_boundary"):
            reasons.append(f"REQUIRED_MOVEMENT_REMOVED:{op}")
    return reasons


def validate_joint_action(
    observation: Mapping[str, Any], action: Mapping[str, Any], contracts: Sequence[Mapping[str, Any]] = ()
) -> list[str]:
    """Enforce shared shed/material/capacity reservations on the final action."""

    reasons: list[str] = []
    seat = _integer(observation.get("player"))
    farm = observation["farms"][seat]
    count = 1 + len(farm.get("hands") or [])
    units = _unit_actions(action, count)
    shed = {str(key): _integer(value) for key, value in observation["private"].get("shed", {}).items()}
    reserved_shed: Counter[str] = Counter()
    reserved_carried: Counter[tuple[int, str]] = Counter()
    reserved_capacity = 0
    for contract in contracts:
        for key, value in (contract.get("reserved_materials") or {}).items():
            parts = str(key).split(":")
            if len(parts) == 2 and parts[0] == "shed":
                reserved_shed[parts[1]] += _integer(value)
            elif len(parts) == 3 and parts[0] == "actor":
                reserved_carried[(_integer(parts[1]), parts[2])] += _integer(value)
        reserved_capacity += _integer(contract.get("reserved_shed_capacity"))

    pickup: Counter[str] = Counter()
    deposit = 0
    for actor, unit in enumerate(units):
        if not unit:
            continue
        op = str(unit[0])
        inventory = _inventory(observation, actor)
        if op == "PICKUP" and len(unit) >= 2:
            item = str(unit[1])
            pickup[item] += max(1, _integer(unit[2], 1) if len(unit) >= 3 else 1)
        elif op == "PLACE" and len(unit) >= 2:
            item = str(unit[1])
            if item not in {"GOOSE", "COW", "SHEEP"}:
                deposit += min(_integer(inventory.get(item)), max(1, _integer(unit[2], 1) if len(unit) >= 3 else 1))
        elif op == "DROP":
            for item, quantity in inventory.items():
                if reserved_carried[(actor, str(item))] > 0 and _integer(quantity) > 0:
                    reasons.append(f"DROP_VIOLATES_FUTURE_RESERVATION:a{actor}:{item}")
            deposit += sum(max(0, _integer(value)) for value in inventory.values())

    for item, quantity in pickup.items():
        available = max(0, shed.get(item, 0) - reserved_shed[item])
        if quantity > available:
            reasons.append(f"SHED_MATERIAL_DOUBLE_USE:{item}:{quantity}>{available}")
    capacity = _integer(observation.get("configuration", {}).get("shedCapacity"), 100)
    occupied = sum(max(0, quantity) for quantity in shed.values()) - sum(pickup.values())
    if occupied + deposit + reserved_capacity > capacity:
        reasons.append(f"SHED_CAPACITY_OVERBOOKED:{occupied + deposit + reserved_capacity}>{capacity}")
    if len(action.get("market") or []) > _integer(observation.get("configuration", {}).get("maxMarketOrdersPerTurn"), 10):
        reasons.append("MARKET_SLOT_OVERBOOKED")
    return reasons


def rejoin_status(observation: Mapping[str, Any], contract: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Return PROVEN_REJOIN, REPLAN, or ABORT from observed postconditions."""

    reasons = validate_contract(contract)
    if not actor_identity_matches(observation, contract.get("actor_identity", {})):
        reasons.append("ACTOR_IDENTITY_CHANGED")
    if _integer(observation.get("step"), _integer(observation.get("day")) * 24 + _integer(observation.get("hour"))) > _integer(contract.get("deadline_step")):
        reasons.append("DEADLINE_EXCEEDED")
    expected = contract.get("expected_rejoin") or {}
    actor = _integer(contract.get("actor_identity", {}).get("actor_index"), -1)
    if actor >= 0:
        farm = observation["farms"][_integer(observation.get("player"))]
        positions = [farm.get("farmer"), *(farm.get("hands") or [])]
        actual_position = list(positions[actor]) if actor < len(positions) else None
        if expected.get("position") is not None and actual_position != list(expected["position"]):
            reasons.append("REJOIN_POSITION_MISMATCH")
        inventory = _inventory(observation, actor)
        for item, quantity in (expected.get("minimum_inventory") or {}).items():
            if _integer(inventory.get(item)) < _integer(quantity):
                reasons.append(f"REJOIN_INVENTORY_MISMATCH:{item}")
    if reasons:
        if contract.get("replanning_policy") == "STATE_BASED_ACTOR_REPLAN" and "ACTOR_IDENTITY_CHANGED" not in reasons:
            return "REPLAN", reasons
        return "ABORT", reasons
    return "PROVEN_REJOIN", []


def apply_candidate_or_keep(
    observation: Mapping[str, Any], control: Mapping[str, Any], contract: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Apply only the current primitive, then validate the complete joint action."""

    reasons = validate_contract(contract)
    if not actor_identity_matches(observation, contract.get("actor_identity", {})):
        reasons.append("ACTOR_IDENTITY_CHANGED")
    actor = _integer(contract.get("actor_identity", {}).get("actor_index"), -1)
    farm = observation["farms"][_integer(observation.get("player"))]
    units = _unit_actions(control, 1 + len(farm.get("hands") or []))
    if not 0 <= actor < len(units):
        reasons.append("ACTOR_MISSING")
    continuation = contract.get("continuation") or []
    if not continuation:
        reasons.append("NO_CURRENT_PRIMITIVE")
    if not reasons:
        reasons.extend(plan_preserves_obligations(observation, units[actor], contract))
    candidate = deepcopy(dict(control))
    if not reasons:
        units[actor] = list(continuation[0])
        candidate = {"farmer": units[0], "hands": units[1:], "market": deepcopy(list(control.get("market") or []))}
        reasons.extend(validate_joint_action(observation, candidate, [contract]))
    if reasons:
        return deepcopy(dict(control)), reasons
    return candidate, []


__all__ = [
    "REQUIRED_CONTRACT_FIELDS",
    "actor_identity",
    "actor_identity_matches",
    "apply_candidate_or_keep",
    "normalize_typed",
    "plan_preserves_obligations",
    "rejoin_status",
    "validate_contract",
    "validate_joint_action",
]

