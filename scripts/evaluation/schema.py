"""Versioned schemas and ordered promotion semantics.

The evaluator deliberately keeps predictive replay evidence separate from
closed-loop policy-value evidence.  A report may contain diagnostics from any
level, but a production promotion must pass the ordered gates and reach E5.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any


class EvidenceLevel(StrEnum):
    E0 = "E0_engine_mechanics"
    E1 = "E1_replay_descriptive_correlation"
    E2 = "E2_lineage_held_out_predictive_validation"
    E3 = "E3_executable_opponent_paired_causal"
    E4 = "E4_diverse_meta_tournament"
    E5 = "E5_fresh_holdout"
    E6 = "E6_live_ladder"


class OpponentTier(StrEnum):
    GOLD = "Gold"
    SILVER = "Silver"
    BRONZE = "Bronze"


class DatasetRole(StrEnum):
    DISCOVERY = "Discovery"
    DEVELOPMENT = "Development"
    PROMOTION = "Promotion"
    FRESH_HOLDOUT = "Fresh Holdout"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
    NOT_RUN = "NOT_RUN"
    BLOCKED = "BLOCKED_BY_EARLIER_GATE"


class SafetyIncidentClass(StrEnum):
    """Mutually reportable incident classes for future paired evaluations.

    A delivery failure means the experimental branch was not delivered while
    the game remained valid.  It must remain visible in the trigger funnel,
    but it is not interchangeable with an engine-integrity failure.
    """

    HARD_SAFETY_FAILURE = "HARD_SAFETY_FAILURE"
    TREATMENT_DELIVERY_FAILURE = "TREATMENT_DELIVERY_FAILURE"


class TransactionState(StrEnum):
    """Required lifecycle for delayed experimental transactions."""

    ARM = "ARM"
    REVALIDATE = "REVALIDATE"
    COMMIT = "COMMIT"
    SAFE_CANCEL = "SAFE_CANCEL"


PROMOTION_GATE_ORDER = (
    "engine_correctness",
    "behavioral_isolation",
    "trigger_causal_uplift",
    "diverse_meta_payoff_improvement",
    "robustness",
    "fresh_holdout",
)

FORMAL_PROMOTION_LEVELS = (EvidenceLevel.E4.value, EvidenceLevel.E5.value)
PREREGISTRATION_FORMAT = "kaggriculture-experiment-preregistration-v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_preregistration(spec: dict[str, Any]) -> None:
    if spec.get("format") != PREREGISTRATION_FORMAT:
        raise ValueError(f"unsupported preregistration format: {spec.get('format')!r}")
    for field in (
        "hypothesis_id",
        "hypothesis",
        "dataset_roles",
        "arms",
        "opponent_pool",
        "seed_manifest",
        "seat_configuration",
        "promotion_criteria",
    ):
        if field not in spec:
            raise ValueError(f"missing preregistration field: {field}")
    if list(spec["seat_configuration"].get("seats", [])) != [0, 1]:
        raise ValueError("formal paired evaluation requires seats [0, 1]")
    if int(spec["seat_configuration"].get("episode_steps", 0)) != 720:
        raise ValueError("formal paired evaluation requires 720 turns")
    phases = spec["seed_manifest"]
    if not phases.get("fast_screen") or not phases.get("formal_promotion"):
        raise ValueError("fast_screen and formal_promotion seeds must be preregistered")
    if set(phases["fast_screen"]) & set(phases["formal_promotion"]):
        raise ValueError("fast-screen and formal-promotion seeds must be disjoint")
    opponents = list(spec["opponent_pool"])
    ids = [str(row.get("lineage_id")) for row in opponents]
    if len(ids) != len(set(ids)):
        raise ValueError("opponent lineage_id values must be unique")
    if any(row.get("tier") != OpponentTier.GOLD.value for row in opponents):
        raise ValueError("closed-loop promotion pools may contain Gold opponents only")
    weight_sum = sum(float(row.get("meta_weight", 0.0)) for row in opponents)
    if abs(weight_sum - 1.0) > 1e-9:
        raise ValueError(f"opponent meta weights must sum to 1, got {weight_sum}")
    criteria = spec["promotion_criteria"]
    if list(criteria) != list(PROMOTION_GATE_ORDER):
        raise ValueError("promotion criteria must use the fixed ordered gate sequence")
    if spec["dataset_roles"].get("top_366_replays") != DatasetRole.DEVELOPMENT.value:
        raise ValueError("the threshold-selected top-366 corpus must be Development")


def load_preregistration(path: Path) -> tuple[dict[str, Any], str]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    validate_preregistration(spec)
    return spec, content_hash(spec)
