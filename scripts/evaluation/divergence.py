"""Turn-aligned First Divergence Audit for paired closed-loop replays."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from typing import Any

from .replay import action, decision_count, observation

ANIMALS = ("GOOSE", "COW", "SHEEP")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _tiles(farm: dict[str, Any]):
    for row in farm.get("tiles") or []:
        yield from row or []


def portfolio(farm: dict[str, Any]) -> dict[str, Any]:
    crops: Counter[str] = Counter()
    animals: Counter[str] = Counter()
    structures: Counter[str] = Counter()
    weeds = 0
    for tile in _tiles(farm):
        if not isinstance(tile, dict):
            continue
        kind = str(tile.get("kind") or "")
        crop = str(tile.get("crop") or "")
        animal = str(tile.get("animal") or "")
        if crop in CROPS:
            crops[crop] += 1
        if animal in ANIMALS:
            animals[animal] += 1
        if kind in {"COOP", "PASTURE"}:
            structures[kind] += 1
        weeds += kind == "WEED"
    return {
        "crops": {name: crops[name] for name in CROPS},
        "animals": {name: animals[name] for name in ANIMALS},
        "structures": dict(structures),
        "unlocked_quadrants": list(farm.get("unlocked_quadrants") or []),
        "weeds": weeds,
    }


def workers(farm: dict[str, Any]) -> dict[str, Any]:
    return {
        "farmer": list(farm.get("farmer") or []),
        "hands": [list(value) for value in (farm.get("hands") or [])],
        "hires_today": int(farm.get("hires_today", 0) or 0),
    }


def public_farm_state(farm: dict[str, Any]) -> dict[str, Any]:
    return {
        "money": float(farm.get("money", 0.0) or 0.0),
        "workers": workers(farm),
        "unlocked_quadrants": list(farm.get("unlocked_quadrants") or []),
        "tiles": farm.get("tiles") or [],
    }


def _state_value(obs: dict[str, Any] | None, seat: int, category: str) -> Any:
    if obs is None:
        return None
    farms = list(obs.get("farms") or [])
    own = farms[seat] if seat < len(farms) else {}
    opponent = farms[1 - seat] if 1 - seat < len(farms) else {}
    market = obs.get("market") or {}
    if category == "market_inventory":
        return market.get("inventory") or {}
    if category == "prices":
        return market.get("prices") or {}
    if category == "town":
        return obs.get("town") or {}
    if category == "self_money":
        return float(own.get("money", 0.0) or 0.0)
    if category == "opponent_money":
        return float(opponent.get("money", 0.0) or 0.0)
    if category == "self_portfolio":
        return portfolio(own)
    if category == "opponent_portfolio":
        return portfolio(opponent)
    if category == "self_workers":
        return workers(own)
    if category == "opponent_workers":
        return workers(opponent)
    if category == "self_private":
        return obs.get("private") or {}
    raise KeyError(category)


def _first_action_difference(
    control: dict[str, Any], treatment: dict[str, Any], seat: int
) -> dict[str, Any] | None:
    limit = min(decision_count(control), decision_count(treatment))
    for step in range(limit):
        left = action(control, step, seat)
        right = action(treatment, step, seat)
        if left != right:
            obs = observation(control, step, seat) or {}
            return {
                "step": step,
                "day": int(obs.get("day", step // 24) or 0),
                "hour": int(obs.get("hour", step % 24) or 0),
                "control": left,
                "treatment": right,
            }
    return None


def _first_state_difference(
    control: dict[str, Any],
    treatment: dict[str, Any],
    seat: int,
    category: str,
    predicate: Callable[[Any, Any], bool] | None = None,
) -> dict[str, Any] | None:
    limit = min(len(control.get("steps") or []), len(treatment.get("steps") or []))
    for step in range(limit):
        left = _state_value(observation(control, step, seat), seat, category)
        right = _state_value(observation(treatment, step, seat), seat, category)
        changed = predicate(left, right) if predicate else left != right
        if changed:
            return {"step": step, "control": left, "treatment": right}
    return None


def _expected_animal_rewrite(control: dict[str, Any], treatment: dict[str, Any]) -> bool:
    if control.get("farmer") != treatment.get("farmer"):
        return False
    if (control.get("hands") or []) != (treatment.get("hands") or []):
        return False
    left = list(control.get("market") or [])
    right = list(treatment.get("market") or [])
    if len(left) != len(right):
        return False
    differences = [index for index, pair in enumerate(zip(left, right, strict=True)) if pair[0] != pair[1]]
    if len(differences) != 1:
        return False
    index = differences[0]
    return left[index] == ["BUY_ANIMAL", "COW", 2] and right[index] == ["BUY_ANIMAL", "SHEEP", 2]


def _action_component_delta(difference: dict[str, Any] | None) -> dict[str, Any] | None:
    if difference is None:
        return None
    left = difference["control"]
    right = difference["treatment"]
    changed = []
    if left.get("farmer") != right.get("farmer"):
        changed.append("farmer")
    if (left.get("hands") or []) != (right.get("hands") or []):
        changed.append("hands")
    if (left.get("market") or []) != (right.get("market") or []):
        changed.append("market")
    return {
        "changed_components": changed,
        "control_farmer": left.get("farmer") or ["PASS"],
        "treatment_farmer": right.get("farmer") or ["PASS"],
        "control_hands": left.get("hands") or [],
        "treatment_hands": right.get("hands") or [],
        "control_market": left.get("market") or [],
        "treatment_market": right.get("market") or [],
    }


def audit_pair(
    control: dict[str, Any],
    treatment: dict[str, Any],
    seat: int,
    *,
    gate_requested: bool,
    intended_action_step: int = 248,
) -> dict[str, Any]:
    focal_action = _first_action_difference(control, treatment, seat)
    opponent_action = _first_action_difference(control, treatment, 1 - seat)
    categories = (
        "market_inventory",
        "prices",
        "town",
        "self_money",
        "opponent_money",
        "self_portfolio",
        "opponent_portfolio",
        "self_workers",
        "opponent_workers",
        "self_private",
    )
    first = {category: _first_state_difference(control, treatment, seat, category) for category in categories}
    opponent_benefit = _first_state_difference(
        control,
        treatment,
        seat,
        "opponent_money",
        lambda left, right: float(right or 0.0) > float(left or 0.0),
    )
    first_step = focal_action.get("step") if focal_action else None
    public_categories = tuple(category for category in categories if category != "self_private")
    public_timeline = sorted(
        (
            {"category": category, "step": int(first[category]["step"])}
            for category in public_categories
            if first[category] is not None
        ),
        key=lambda row: (row["step"], row["category"]),
    )
    first_public_step = public_timeline[0]["step"] if public_timeline else None
    opponent_step = opponent_action.get("step") if opponent_action else None
    response_order_valid = bool(
        opponent_step is None
        or (first_step is not None and opponent_step > first_step)
        and (first_public_step is not None and opponent_step >= first_public_step)
    )
    expected = bool(
        focal_action
        and first_step == intended_action_step
        and _expected_animal_rewrite(focal_action["control"], focal_action["treatment"])
    )
    any_state_difference = any(value is not None for value in first.values())
    if focal_action is None:
        behavioral_valid = not any_state_difference
        classification = (
            "requested_but_no_incremental_action"
            if gate_requested
            else "inactive_exact_identity"
        )
    else:
        earliest_state = min(
            (int(value["step"]) for value in first.values() if value is not None),
            default=10**9,
        )
        behavioral_valid = (
            expected and earliest_state >= intended_action_step + 1 and response_order_valid
        )
        if behavioral_valid and opponent_action is not None:
            classification = "intended_intervention_then_closed_loop_opponent_response"
        elif behavioral_valid:
            classification = "intended_intervention_without_opponent_action_response"
        else:
            classification = "unexpected_or_pre_intervention_divergence"
    return {
        "alignment": "observation[t] -> action stored at steps[t+1]",
        "gate_requested": gate_requested,
        "intended_action_step": intended_action_step,
        # Stable channel names used by all future paired-experiment records.
        "first_self_divergence": focal_action,
        "first_opponent_response": opponent_action,
        "first_market_divergence": first["market_inventory"],
        "first_price_divergence": first["prices"],
        "first_money_divergence": {
            "step": min(
                (
                    int(value["step"])
                    for value in (first["self_money"], first["opponent_money"])
                    if value is not None
                ),
                default=None,
            ),
            "self": first["self_money"],
            "opponent": first["opponent_money"],
        },
        "first_focal_action": focal_action,
        "first_opponent_action": opponent_action,
        "first_state_divergence": first,
        "first_opponent_money_benefit": opponent_benefit,
        "own_first_divergence_step": first_step,
        "own_action_component_delta": _action_component_delta(focal_action),
        "first_public_observation_divergence_step": first_public_step,
        "public_diff_timeline": public_timeline,
        "first_opponent_response_step": opponent_step,
        "opponent_response_component_delta": _action_component_delta(opponent_action),
        "opponent_response_lag": {
            "from_own_action": (
                opponent_step - first_step
                if opponent_step is not None and first_step is not None
                else None
            ),
            "from_first_public_signal": (
                opponent_step - first_public_step
                if opponent_step is not None and first_public_step is not None
                else None
            ),
        },
        "response_order_valid": response_order_valid,
        "response_before_market_inventory_divergence": bool(
            opponent_step is not None
            and first["market_inventory"] is not None
            and opponent_step < int(first["market_inventory"]["step"])
        ),
        "response_before_price_divergence": bool(
            opponent_step is not None
            and first["prices"] is not None
            and opponent_step < int(first["prices"]["step"])
        ),
        "candidate_mediator_categories": [
            row["category"]
            for row in public_timeline
            if opponent_step is not None and row["step"] <= opponent_step
        ],
        "mediator_counterfactual_status": "not_run_by_generic_audit",
        "expected_first_intervention": expected,
        "behavioral_isolation_valid": behavioral_valid,
        "incremental_treatment_emitted": expected,
        "classification": classification,
    }
