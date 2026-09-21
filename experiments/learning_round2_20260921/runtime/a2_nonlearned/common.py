"""Shared, submission-safe helpers for learning round 2.

The module deliberately reuses the frozen learning-next feature contract.  A
standalone archive carries that source as ``learning_common.py`` so no repo
import or silent fallback is required.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np

try:
    from agents.learning_next_20260921.common import (
        PRODUCTS,
        WORK_OPS,
        MarketHistory,
        actor_context,
        actor_feature_names,
        actor_features,
        actor_probe_succeeded,
        legal_actor_tokens,
        make_actor_probe,
        safe_action_shape,
        shed_access,
        state_feature_names,
        state_features,
    )
except ImportError:  # standalone archive
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from learning_common import (  # type: ignore[no-redef]
        PRODUCTS,
        WORK_OPS,
        MarketHistory,
        actor_context,
        actor_feature_names,
        actor_features,
        actor_probe_succeeded,
        legal_actor_tokens,
        make_actor_probe,
        safe_action_shape,
        shed_access,
        state_feature_names,
        state_features,
    )

A2_JOB_TYPES = (
    "KEEP_C0",
    "CARE_COLLECT",
    "COLLECT_CARE",
    "FERTILIZE_WATER",
    "WATER_FERTILIZE",
    "HARVEST_DROP",
    "COLLECT_DROP",
)
HORIZONS = (1, 4, 24)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def observation_fingerprint(observation: Mapping[str, Any]) -> str:
    import hashlib

    stable = deepcopy(dict(observation))
    stable.pop("remainingOverageTime", None)
    return hashlib.sha256(canonical_json(stable).encode()).hexdigest()


def _action_for_token(token: str) -> list[Any]:
    if ":" not in token:
        return [token]
    op, item = token.split(":", 1)
    if op in {"PICKUP", "PLACE"}:
        return [op, item, 1]
    return [op, item]


def a2_candidates(
    observation: Mapping[str, Any], control: Mapping[str, Any], *, t_min: int = 240
) -> list[dict[str, Any]]:
    """Return conservative, closed work jobs without mutating inputs.

    Every non-KEEP job retains the actor position, has a day-boundary deadline,
    declares its resource reservation, and owns the actor until its final
    confirmation.  C0 is still called exactly once on every turn, so returning
    control never rewinds its source/router clock.
    """

    step = int(observation.get("step", int(observation.get("day", 0)) * 24 + int(observation.get("hour", 0))))
    if step < t_min:
        return []
    seat = int(observation.get("player", 0))
    hands = observation["farms"][seat].get("hands", [])
    shaped = safe_action_shape(control, len(hands))
    control_units = [shaped["farmer"], *shaped["hands"]]
    result: list[dict[str, Any]] = []
    for actor_index in range(1 + len(hands)):
        legal = legal_actor_tokens(observation, actor_index)
        _farm, position, inventory, tile = actor_context(observation, actor_index)
        control_action = list(control_units[actor_index])
        if not control_action or str(control_action[0]) not in WORK_OPS:
            continue
        base = {
            "actor_index": actor_index,
            "target": list(position),
            "deadline_step": min(718, (step // 24 + 1) * 24 - 1),
            "control_action": control_action,
            "rejoin": {
                "position_unchanged": True,
                "base_called_once_per_turn": True,
                "tape_rewind": False,
            },
        }

        def add(
            job_type: str,
            sequence: Sequence[str],
            reservations: Mapping[str, int],
            effect: str,
            *,
            _control_action: list[Any] = control_action,
            _base: Mapping[str, Any] = base,
            _actor_index: int = actor_index,
        ) -> None:
            first = _action_for_token(sequence[0])
            if first == _control_action and len(sequence) == 1:
                return
            result.append(
                {
                    **deepcopy(_base),
                    "job_type": job_type,
                    "candidate_id": f"{job_type}:a{_actor_index}",
                    "sequence": [list(_action_for_token(token)) for token in sequence],
                    "reservations": dict(reservations),
                    "success_effect": effect,
                    "abort_conditions": ["actor moved", "deadline passed", "next primitive no longer legal"],
                }
            )

        if {"CARE", "COLLECT_FERTILIZER"}.issubset(legal):
            add("CARE_COLLECT", ("CARE", "COLLECT_FERTILIZER"), {}, "care banked and fertilizer carried")
            add("COLLECT_CARE", ("COLLECT_FERTILIZER", "CARE"), {}, "fertilizer carried and care banked")
        if {"FERTILIZE", "WATER"}.issubset(legal) and int(inventory.get("FERTILIZER", 0)) > 0:
            add("FERTILIZE_WATER", ("FERTILIZE", "WATER"), {"carried:FERTILIZER": 1}, "fertilized and watered")
            add("WATER_FERTILIZE", ("WATER", "FERTILIZE"), {"carried:FERTILIZER": 1}, "watered and fertilized")
        if shed_access(position) and "HARVEST" in legal:
            add("HARVEST_DROP", ("HARVEST", "DROP"), {"shed_capacity": 1}, "harvest deposited in shed")
        if shed_access(position) and "COLLECT_FERTILIZER" in legal:
            add("COLLECT_DROP", ("COLLECT_FERTILIZER", "DROP"), {"shed_capacity": 1}, "fertilizer deposited in shed")
    return result[:3]


def a2_feature_names() -> tuple[str, ...]:
    return (
        state_feature_names()
        + tuple(f"candidate_actor:{name}" for name in actor_feature_names())
        + tuple(f"job:{name}" for name in A2_JOB_TYPES)
        + tuple(f"control_op:{name}" for name in WORK_OPS)
        + ("actor_index", "sequence_length", "deadline_slack", "reservation_count")
    )


def a2_features(
    observation: Mapping[str, Any], candidate: Mapping[str, Any] | None, history: MarketHistory | None = None
) -> np.ndarray:
    state = state_features(observation, history)
    job_type = "KEEP_C0" if candidate is None else str(candidate["job_type"])
    actor_index = -1 if candidate is None else int(candidate["actor_index"])
    actor = (
        np.zeros(len(actor_feature_names()), dtype=np.float32)
        if actor_index < 0
        else actor_features(observation, actor_index, history)
    )
    control_op = ""
    if candidate is not None:
        action = candidate.get("control_action") or []
        control_op = str(action[0]) if action else "PASS"
    step = int(observation.get("step", 0))
    deadline = step if candidate is None else int(candidate.get("deadline_step", step))
    tail = [
        *(float(job_type == value) for value in A2_JOB_TYPES),
        *(float(control_op == value) for value in WORK_OPS),
        actor_index / 20.0,
        0.0 if candidate is None else len(candidate.get("sequence", [])) / 4.0,
        max(0, deadline - step) / 24.0,
        0.0 if candidate is None else len(candidate.get("reservations", {})) / 4.0,
    ]
    return np.concatenate((state, actor, np.asarray(tail, dtype=np.float32)))


class A2ValueModel:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"required learned model is missing: {self.path}")
        with np.load(self.path, allow_pickle=False) as data:
            self.mean = data["mean"].astype(np.float32)
            self.scale = data["scale"].astype(np.float32)
            self.w1 = data["w1"].astype(np.float32)
            self.b1 = data["b1"].astype(np.float32)
            self.w2 = data["w2"].astype(np.float32)
            self.b2 = data["b2"].astype(np.float32)

    def predict(self, features: np.ndarray) -> tuple[float, float]:
        x = (np.asarray(features, np.float32) - self.mean) / self.scale
        hidden = np.maximum(0.0, x @ self.w1 + self.b1)
        output = hidden @ self.w2 + self.b2
        return float(output[0]), float(1.0 / (1.0 + np.exp(-np.clip(output[1], -30, 30))))


__all__ = [
    "A2_JOB_TYPES",
    "A2ValueModel",
    "HORIZONS",
    "PRODUCTS",
    "MarketHistory",
    "a2_candidates",
    "a2_feature_names",
    "a2_features",
    "actor_context",
    "actor_probe_succeeded",
    "canonical_json",
    "legal_actor_tokens",
    "make_actor_probe",
    "observation_fingerprint",
    "safe_action_shape",
    "state_features",
]
