"""Paired V111/V113 benchmark over an independent executable-family panel.

This evaluator is deliberately separate from the immutable V113 60-pair
promotion experiment.  It treats V111 as the clean causal control and V113 as
the live-validated field benchmark, then runs both from turn zero against the
same executable opponent, requested seed, and focal seat.

The input manifest's statistical unit is ``behavior_family_id``.  Source or
submission names are retained only as provenance.  Long runs are checkpointed
one complete V111/V113 pair per JSONL row and can be resumed without rerunning
completed pairs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import random
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluation.divergence import audit_pair  # noqa: E402
from scripts.evaluation.replay import lineage_hash  # noqa: E402
from scripts.evaluation.runner import _run_game  # noqa: E402
from scripts.evaluation.safety import (  # noqa: E402
    analyze_safety,
    classify_candidate_incidents,
)
from scripts.gold_opponent_pool import (  # noqa: E402
    ACTION_CHECKPOINTS,
    DAY_MARGIN_CHECKPOINTS,
    ROOT,
    dependency_closure_sha256,
    replay_diagnostics,
    sha256_file,
    stable_json_hash,
)

FORMAT = "kaggriculture-v111-v113-expanded-dual-benchmark-v1"
MANIFEST_FORMAT = "kaggriculture-independent-gold-family-panel-v1"
DEFAULT_PANEL = "sensitivity"
FRESH_HOLDOUT = "fresh_holdout"


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_json(path: Path) -> tuple[dict[str, Any], str]:
    encoded = path.read_bytes()
    payload = json.loads(encoded.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("family panel manifest must be a JSON object")
    return payload, _sha256_bytes(encoded)


def _entrypoint_record(raw: Any, label: str) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"entrypoint": raw}
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object or entrypoint string")
    value = raw.get("entrypoint", raw.get("path"))
    if not value:
        raise ValueError(f"{label} has no entrypoint")
    entrypoint = _resolve(str(value))
    if not entrypoint.is_file():
        raise FileNotFoundError(f"{label} entrypoint does not exist: {entrypoint}")
    entrypoint_hash = sha256_file(entrypoint)
    declared_hash = raw.get("entrypoint_sha256")
    if declared_hash and str(declared_hash) != entrypoint_hash:
        raise ValueError(
            f"{label} entrypoint hash mismatch: declared={declared_hash}, actual={entrypoint_hash}"
        )
    dependency_hash = dependency_closure_sha256(entrypoint)
    declared_dependency_hash = raw.get("dependency_closure_sha256")
    if declared_dependency_hash and str(declared_dependency_hash) != dependency_hash:
        raise ValueError(
            f"{label} dependency hash mismatch: declared={declared_dependency_hash}, "
            f"actual={dependency_hash}"
        )
    return {
        "label": label,
        "entrypoint": str(entrypoint),
        "entrypoint_sha256": entrypoint_hash,
        "dependency_closure_sha256": dependency_hash,
    }


def _candidate_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in payload.get("candidates", []):
        if not isinstance(raw, dict) or not raw.get("candidate_id"):
            continue
        result[str(raw["candidate_id"])] = raw
    return result


def _raw_families(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values = payload.get("families") or payload.get("independent_families")
    if values is None:
        values = payload.get("exact_families")
    if values is None and isinstance(payload.get("clustering"), dict):
        values = payload["clustering"].get("exact_families")
    if not isinstance(values, list) or not values:
        raise ValueError("manifest has no non-empty families/exact_families list")
    if not all(isinstance(value, dict) for value in values):
        raise ValueError("every family must be an object")
    return values


def _normalize_families(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = _candidate_lookup(payload)
    result = []
    seen: set[str] = set()
    for raw in _raw_families(payload):
        family_id = str(raw.get("behavior_family_id") or raw.get("family_id") or "")
        if not family_id:
            raise ValueError("family has no behavior_family_id")
        if family_id in seen:
            raise ValueError(f"duplicate behavior_family_id: {family_id}")
        seen.add(family_id)
        representative = str(
            raw.get("representative_candidate_id")
            or raw.get("representative_source_id")
            or ""
        )
        source = raw
        if not raw.get("entrypoint") and not raw.get("path"):
            if not representative or representative not in candidates:
                raise ValueError(
                    f"family {family_id} has no entrypoint and representative "
                    "cannot be resolved through candidates"
                )
            source = {**candidates[representative], **raw}
        entrypoint = _entrypoint_record(source, f"family:{family_id}")
        panels = raw.get("panels") or []
        if isinstance(panels, str):
            panels = [panels]
        result.append(
            {
                "behavior_family_id": family_id,
                "representative_candidate_id": representative or family_id,
                **entrypoint,
                "source_ancestry_ids": sorted(
                    str(value) for value in (raw.get("source_ancestry_ids") or [])
                ),
                "source_members": sorted(
                    str(value) for value in (raw.get("source_members") or [])
                ),
                "family_signature": raw.get("family_signature"),
                "provenance": str(raw.get("provenance") or ""),
                "style_tags": sorted(
                    str(value) for value in (raw.get("style_tags") or [])
                ),
                "meta_vote_group": str(
                    raw.get("meta_vote_group") or family_id
                ),
                "fresh_holdout_eligible": bool(
                    raw.get("fresh_holdout_eligible", False)
                ),
                "v111_probe_strict_win_rate": raw.get(
                    "v111_probe_strict_win_rate"
                ),
                "v111_probe_mean_margin": raw.get("v111_probe_mean_margin"),
                "panels": sorted(str(value) for value in panels),
                "meta_weight": (
                    float(raw["meta_weight"]) if raw.get("meta_weight") is not None else None
                ),
            }
        )
    return sorted(result, key=lambda row: row["behavior_family_id"])


def _normalize_controls(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    controls = payload.get("controls") or payload.get("arms") or {}
    if not isinstance(controls, dict):
        raise ValueError("manifest controls must be an object")
    clean = controls.get("clean_v111", controls.get("control"))
    live = controls.get("live_benchmark_v113", controls.get("treatment"))
    if clean is None or live is None:
        raise ValueError(
            "manifest must define controls.clean_v111 and "
            "controls.live_benchmark_v113"
        )
    return {
        "clean_v111": _entrypoint_record(clean, "clean_v111"),
        "live_benchmark_v113": _entrypoint_record(live, "live_benchmark_v113"),
    }


def _normalize_panel(
    name: str,
    raw: Any,
    families: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(raw, list):
        raw = {"family_ids": raw}
    if not isinstance(raw, dict):
        raise ValueError(f"panel {name} must be an object or family-id list")
    all_family_ids = {row["behavior_family_id"] for row in families}
    family_ids = raw.get("family_ids") or raw.get("families")
    if family_ids is None:
        family_ids = [
            row["behavior_family_id"] for row in families if name in row.get("panels", [])
        ]
    family_ids = [str(value) for value in family_ids]
    if len(set(family_ids)) != len(family_ids):
        raise ValueError(f"panel {name} contains duplicate family ids")
    unknown = sorted(set(family_ids) - all_family_ids)
    if unknown:
        raise ValueError(f"panel {name} references unknown families: {unknown}")
    seeds = raw.get("seeds")
    seed_manifest = payload.get("seed_manifest") or {}
    if seeds is None and isinstance(seed_manifest, dict):
        seeds = seed_manifest.get(name)
    seeds = [] if seeds is None else [int(value) for value in seeds]
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"panel {name} contains duplicate seeds")
    both_seats = raw.get("both_seats")
    seats = raw.get("seats")
    if seats is not None:
        seats = sorted(int(value) for value in seats)
        if seats != [0, 1]:
            raise ValueError(f"panel {name} must use both seats [0, 1]")
    elif both_seats is False:
        raise ValueError(f"panel {name} must use both seats")
    seats = [0, 1]
    if not family_ids and not bool(raw.get("reserved")):
        raise ValueError(f"panel {name} has no families")
    if not seeds and not bool(raw.get("reserved")):
        raise ValueError(f"panel {name} has no seeds")
    supplied_weights = raw.get("meta_weights") or raw.get("weights") or {}
    if supplied_weights and not isinstance(supplied_weights, dict):
        raise ValueError(f"panel {name} weights must be an object")
    by_id = {row["behavior_family_id"]: row for row in families}
    weights = {
        family_id: float(
            supplied_weights.get(
                family_id,
                by_id[family_id]["meta_weight"]
                if by_id[family_id]["meta_weight"] is not None
                else 1.0,
            )
        )
        for family_id in family_ids
    }
    if any(value < 0 for value in weights.values()):
        raise ValueError(f"panel {name} has a negative family weight")
    total_weight = sum(weights.values())
    if family_ids and total_weight <= 0:
        raise ValueError(f"panel {name} family weights sum to zero")
    weights = {
        family_id: value / total_weight for family_id, value in weights.items()
    }
    return {
        "name": name,
        "family_ids": family_ids,
        "seeds": sorted(seeds),
        "seats": seats,
        "both_seats": True,
        "weights": weights,
        "reserved": bool(raw.get("reserved")),
        "description": str(raw.get("description") or ""),
    }


def normalize_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a preferred or common-probe-derived manifest."""
    families = _normalize_families(payload)
    raw_panels = payload.get("panels")
    if not isinstance(raw_panels, dict) or not raw_panels:
        discovered = sorted({panel for row in families for panel in row.get("panels", [])})
        if not discovered:
            raise ValueError("manifest has no panels object or family panel assignments")
        raw_panels = {name: {} for name in discovered}
    panels = {
        str(name): _normalize_panel(str(name), raw, families, payload)
        for name, raw in raw_panels.items()
    }
    return {
        "format": str(payload.get("format") or MANIFEST_FORMAT),
        "dataset_role": payload.get("dataset_role"),
        "selection": payload.get("selection") or {},
        "preregistered_dual_benchmark": payload.get(
            "preregistered_dual_benchmark"
        )
        or {},
        "fresh_holdout_exclusions": payload.get("fresh_holdout_exclusions") or {},
        "controls": _normalize_controls(payload),
        "families": families,
        "panels": panels,
    }


def validate_panel_selection(
    manifest: dict[str, Any], selected: list[str], *, allow_fresh_holdout: bool
) -> list[str]:
    names = list(dict.fromkeys(str(value) for value in selected))
    unknown = sorted(set(names) - set(manifest["panels"]))
    if unknown:
        raise ValueError(f"unknown panels: {unknown}")
    if FRESH_HOLDOUT in names and not allow_fresh_holdout:
        raise ValueError(
            "Fresh Holdout is protected; pass --allow-fresh-holdout only for the "
            "pre-registered final holdout run"
        )
    for name in names:
        panel = manifest["panels"][name]
        if panel["reserved"] or not panel["family_ids"] or not panel["seeds"]:
            raise ValueError(f"selected panel {name} is reserved or incomplete")
    return names


def build_tasks(
    manifest: dict[str, Any], selected_panels: list[str], *, episode_steps: int = 720
) -> list[dict[str, Any]]:
    """Build one task per unique family/seed/seat, collapsing panel overlap."""
    families = {row["behavior_family_id"]: row for row in manifest["families"]}
    memberships: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    for panel_name in selected_panels:
        panel = manifest["panels"][panel_name]
        for family_id in panel["family_ids"]:
            for seed in panel["seeds"]:
                for seat in panel["seats"]:
                    memberships[(family_id, int(seed), int(seat))].add(panel_name)
    controls = manifest["controls"]
    tasks = []
    for (family_id, seed, seat), panels in sorted(memberships.items()):
        family = families[family_id]
        tasks.append(
            {
                "task_key": f"{family_id}|{seed}|{seat}",
                "behavior_family_id": family_id,
                "representative_candidate_id": family["representative_candidate_id"],
                "source_ancestry_ids": family["source_ancestry_ids"],
                "panel_memberships": sorted(panels),
                "opponent_main": family["entrypoint"],
                "v111_main": controls["clean_v111"]["entrypoint"],
                "v113_main": controls["live_benchmark_v113"]["entrypoint"],
                "seed": seed,
                "seat": seat,
                "episode_steps": int(episode_steps),
                "intended_action_step": 248,
                "action_checkpoints": list(ACTION_CHECKPOINTS),
            }
        )
    return tasks


def validate_preregistered_task_count(
    manifest: dict[str, Any], tasks: list[dict[str, Any]]
) -> None:
    """Fail closed when the frozen task count and resolved plan disagree."""
    preregistration = manifest.get("preregistered_dual_benchmark") or {}
    declared = preregistration.get("planned_unique_pairs")
    if declared is not None and int(declared) != len(tasks):
        raise ValueError(
            "pre-registered planned_unique_pairs does not match resolved tasks: "
            f"declared={int(declared)}, resolved={len(tasks)}"
        )


def _public_arm(game: dict[str, Any]) -> dict[str, Any]:
    return {
        key: game[key]
        for key in (
            "requested_seed",
            "resolved_seed",
            "seat",
            "ours",
            "theirs",
            "margin",
            "score",
            "result",
            "final_statuses",
        )
    }


def _action_fingerprints(
    replay: dict[str, Any], focal_seat: int, checkpoints: list[int]
) -> dict[str, dict[str, str]]:
    return {
        "focal": {
            str(step): lineage_hash(replay, focal_seat, step) for step in checkpoints
        },
        "opponent": {
            str(step): lineage_hash(replay, 1 - focal_seat, step) for step in checkpoints
        },
    }


def _compact_trace(trace: dict[str, Any]) -> dict[str, Any]:
    reasons = list(trace.get("fallback_reasons") or [])
    reason_counts = Counter(str(row.get("reason") or "UNKNOWN") for row in reasons)
    first_by_reason: dict[str, dict[str, Any]] = {}
    for row in reasons:
        reason = str(row.get("reason") or "UNKNOWN")
        first_by_reason.setdefault(reason, row)
    return {
        "generalized_goal_requested": bool(trace.get("generalized_goal_requested")),
        "generalized_goal": trace.get("generalized_goal"),
        "generalized_goal_step": trace.get("generalized_goal_step"),
        "last_v113_model": trace.get("last_v113_model"),
        "strategy_counts": trace.get("strategy_counts") or {},
        "fallback_steps": int(trace.get("fallback_steps", 0) or 0),
        "fallback_reason_counts": dict(sorted(reason_counts.items())),
        "fallback_first_occurrence": {
            key: first_by_reason[key] for key in sorted(first_by_reason)
        },
        "ood_steps": int(trace.get("ood_steps", 0) or 0),
        "agent_exceptions": trace.get("agent_exceptions") or [],
        "last_diagnostics": trace.get("last_diagnostics") or {},
    }


def _compact_safety(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "engine_action_examples": value.get("engine_action_examples", [])[:10]}


def run_dual_task(task: dict[str, Any]) -> dict[str, Any]:
    """Run V111 and V113 against exactly the same opponent/seed/focal seat."""
    seed = int(task["seed"])
    seat = int(task["seat"])
    episode_steps = int(task.get("episode_steps", 720))
    intended_step = int(task.get("intended_action_step", 248))
    checkpoints = [int(value) for value in task.get("action_checkpoints", ACTION_CHECKPOINTS)]
    v111 = _run_game(
        Path(task["v111_main"]),
        Path(task["opponent_main"]),
        seed,
        seat,
        episode_steps,
        "expanded_v111",
    )
    v113 = _run_game(
        Path(task["v113_main"]),
        Path(task["opponent_main"]),
        seed,
        seat,
        episode_steps,
        "expanded_v113",
    )
    gate_requested = bool(v113["trace"].get("generalized_goal_requested"))
    divergence = audit_pair(
        v111["replay"],
        v113["replay"],
        seat,
        gate_requested=gate_requested,
        intended_action_step=intended_step,
    )
    v111_safety = analyze_safety(
        v111["replay"], seat, v111["trace"], transaction_step=intended_step
    )
    v113_safety = analyze_safety(
        v113["replay"], seat, v113["trace"], transaction_step=intended_step
    )
    incidents = classify_candidate_incidents(v111_safety, v113_safety)
    hard_safety = list(incidents["hard_safety_failures"])
    delivery_issues = list(incidents["treatment_delivery_failures"])
    actual_treatment = bool(divergence.get("incremental_treatment_emitted"))
    action_divergent = divergence.get("first_focal_action") is not None
    compact_trace = _compact_trace(v113["trace"])
    v111_public = _public_arm(v111)
    v113_public = _public_arm(v113)
    pairing_integrity = {
        "same_requested_seed": (
            v111_public["requested_seed"] == v113_public["requested_seed"] == seed
        ),
        "same_resolved_seed": (
            v111_public["resolved_seed"] == v113_public["resolved_seed"]
        ),
        "same_focal_seat": v111_public["seat"] == v113_public["seat"] == seat,
        "v111_completed": v111_public["final_statuses"] == ["DONE", "DONE"],
        "v113_completed": v113_public["final_statuses"] == ["DONE", "DONE"],
    }
    pairing_integrity["both_completed"] = bool(
        pairing_integrity["v111_completed"]
        and pairing_integrity["v113_completed"]
    )
    pairing_integrity["valid"] = all(
        bool(pairing_integrity[key])
        for key in (
            "same_requested_seed",
            "same_resolved_seed",
            "same_focal_seat",
            "both_completed",
        )
    )
    diagnostics = {
        "v111": replay_diagnostics(v111["replay"], seat, episode_steps),
        "v113": replay_diagnostics(v113["replay"], seat, episode_steps),
    }
    return {
        "task_key": task["task_key"],
        "behavior_family_id": task["behavior_family_id"],
        "representative_candidate_id": task["representative_candidate_id"],
        "source_ancestry_ids": task.get("source_ancestry_ids", []),
        "panel_memberships": task["panel_memberships"],
        "seed": seed,
        "seat": seat,
        "pairing_integrity": pairing_integrity,
        "v111": v111_public,
        "v113": v113_public,
        "delta_self_coin": v113_public["ours"] - v111_public["ours"],
        "delta_opponent_coin": v113_public["theirs"] - v111_public["theirs"],
        "delta_margin": v113_public["margin"] - v111_public["margin"],
        "delta_win_score": v113_public["score"] - v111_public["score"],
        "delta_win_probability": float(v113_public["result"] == "win")
        - float(v111_public["result"] == "win"),
        "loss_to_win": v111_public["result"] == "loss"
        and v113_public["result"] == "win",
        "win_to_loss": v111_public["result"] == "win"
        and v113_public["result"] == "loss",
        "gate_requested": gate_requested,
        "actual_treatment": actual_treatment,
        "incremental_treatment": actual_treatment,
        "action_divergent_pair": action_divergent,
        "requested_without_action_divergence": gate_requested and not action_divergent,
        "treatment_delivery_failure": bool(delivery_issues),
        "requested_but_not_delivered": gate_requested and not actual_treatment,
        "safe_baseline_overlap": gate_requested
        and not actual_treatment
        and not bool(delivery_issues)
        and not action_divergent
        and bool(divergence.get("behavioral_isolation_valid")),
        "v113_trace": compact_trace,
        "executed_action_fingerprints": {
            "schema": "cumulative canonical action stream at standard checkpoints",
            "v111_arm": _action_fingerprints(v111["replay"], seat, checkpoints),
            "v113_arm": _action_fingerprints(v113["replay"], seat, checkpoints),
        },
        "diagnostics": diagnostics,
        "divergence_audit": divergence,
        "safety_classification": {
            "hard_safety_failures": hard_safety,
            "treatment_delivery_issues": delivery_issues,
            "legacy_major_regressions": hard_safety,
        },
        "safety": {
            "v111": _compact_safety(v111_safety),
            "v113": _compact_safety(v113_safety),
        },
    }


def _arm_summary(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    return {
        "wins": sum(row[arm]["result"] == "win" for row in rows),
        "draws": sum(row[arm]["result"] == "draw" for row in rows),
        "losses": sum(row[arm]["result"] == "loss" for row in rows),
        "strict_win_probability": mean(
            float(row[arm]["result"] == "win") for row in rows
        ),
        "win_score": mean(float(row[arm]["score"]) for row in rows),
        "mean_self_coin": mean(float(row[arm]["ours"]) for row in rows),
        "mean_opponent_coin": mean(float(row[arm]["theirs"]) for row in rows),
        "mean_margin": mean(float(row[arm]["margin"]) for row in rows),
    }


def _mean_mapping(values: list[dict[str, Any]]) -> dict[str, float]:
    keys = sorted({str(key) for value in values for key in value})
    return {
        key: mean(float(value.get(key, 0.0) or 0.0) for value in values)
        for key in keys
    }


def _terminal_state(diagnostics: dict[str, Any]) -> dict[str, Any]:
    states = diagnostics.get("checkpoint_states") or {}
    if not states:
        return {}
    terminal_step = max(int(step) for step in states)
    value = states.get(str(terminal_step)) or {}
    return value if isinstance(value, dict) else {}


def _mean_portfolio(
    states: list[dict[str, Any]], key: str
) -> dict[str, Any]:
    portfolios = [state.get(key) or {} for state in states]
    animal_values = [value.get("animals") or {} for value in portfolios]
    crop_values = [value.get("crops") or {} for value in portfolios]
    structure_values = [value.get("structures") or {} for value in portfolios]
    return {
        "animals": _mean_mapping(animal_values),
        "crops": _mean_mapping(crop_values),
        "structures": _mean_mapping(structure_values),
        "weeds": mean(float(value.get("weeds", 0.0) or 0.0) for value in portfolios),
        "unlocked_quadrants": mean(
            len(value.get("unlocked_quadrants") or []) for value in portfolios
        ),
    }


def _loss_signal_labels(
    rows: list[dict[str, Any]], arm: str, lead_to_loss: int
) -> list[str]:
    losses = [row for row in rows if row[arm]["result"] == "loss"]
    if not losses:
        return []
    labels = []
    if lead_to_loss:
        labels.append("late_cash_reversal_after_major_checkpoint_lead")
    terminal_states = [
        _terminal_state(row["diagnostics"][arm])
        for row in losses
        if (row.get("diagnostics") or {}).get(arm)
    ]
    if terminal_states:
        own_animals = mean(
            sum(
                float(value or 0.0)
                for value in (state.get("own_portfolio") or {}).get("animals", {}).values()
            )
            for state in terminal_states
        )
        opponent_animals = mean(
            sum(
                float(value or 0.0)
                for value in (state.get("opponent_portfolio") or {})
                .get("animals", {})
                .values()
            )
            for state in terminal_states
        )
        if own_animals + 0.5 < opponent_animals:
            labels.append("terminal_animal_portfolio_deficit")
    loss_market_l1 = [
        float(
            row["diagnostics"][arm]["terminal_market_displacement"].get(
                "price_l1", 0.0
            )
        )
        for row in losses
        if (row.get("diagnostics") or {}).get(arm)
    ]
    wins = [row for row in rows if row[arm]["result"] == "win"]
    win_market_l1 = [
        float(
            row["diagnostics"][arm]["terminal_market_displacement"].get(
                "price_l1", 0.0
            )
        )
        for row in wins
        if (row.get("diagnostics") or {}).get(arm)
    ]
    if loss_market_l1 and win_market_l1 and mean(loss_market_l1) > mean(win_market_l1):
        labels.append("losses_have_higher_terminal_market_price_displacement")
    return labels or ["unresolved_from_aggregate_diagnostics"]


def _arm_weakness_summary(
    rows: list[dict[str, Any]], arm: str
) -> dict[str, Any]:
    available = [
        row for row in rows if isinstance((row.get("diagnostics") or {}).get(arm), dict)
    ]
    if not available:
        return {
            "available": False,
            "reason": "rows predate expanded replay diagnostics",
        }
    checkpoint_summary: dict[str, Any] = {}
    for checkpoint in DAY_MARGIN_CHECKPOINTS:
        selected = [
            row
            for row in available
            if str(checkpoint)
            in row["diagnostics"][arm].get("checkpoint_states", {})
        ]
        if not selected:
            continue
        values = [
            float(
                row["diagnostics"][arm]["checkpoint_states"][str(checkpoint)][
                    "cash_margin"
                ]
            )
            for row in selected
        ]
        checkpoint_summary[str(checkpoint)] = {
            "day": checkpoint // 24,
            "mean_visible_cash_margin": mean(values),
            "median_visible_cash_margin": median(values),
            "lead_to_loss": sum(
                value > 0.0 and row[arm]["result"] == "loss"
                for value, row in zip(values, selected, strict=True)
            ),
            "behind_to_win": sum(
                value < 0.0 and row[arm]["result"] == "win"
                for value, row in zip(values, selected, strict=True)
            ),
        }
    lead_to_loss_any = sum(
        row[arm]["result"] == "loss"
        and any(
            float(
                row["diagnostics"][arm]["checkpoint_states"].get(str(step), {}).get(
                    "cash_margin", 0.0
                )
            )
            > 0.0
            for step in DAY_MARGIN_CHECKPOINTS
        )
        for row in available
    )
    behind_to_win_any = sum(
        row[arm]["result"] == "win"
        and any(
            float(
                row["diagnostics"][arm]["checkpoint_states"].get(str(step), {}).get(
                    "cash_margin", 0.0
                )
            )
            < 0.0
            for step in DAY_MARGIN_CHECKPOINTS
        )
        for row in available
    )
    terminal_states = [_terminal_state(row["diagnostics"][arm]) for row in available]
    terminal_shops = Counter(
        "+".join(state.get("unlocked_shops") or []) or "NONE"
        for state in terminal_states
    )
    market_displacements = [
        row["diagnostics"][arm]["terminal_market_displacement"]
        for row in available
    ]
    focal_profiles = [
        row["diagnostics"][arm]["champion_action_profile"] for row in available
    ]
    opponent_profiles = [
        row["diagnostics"][arm]["opponent_action_profile"] for row in available
    ]
    focal_premium = [
        row["diagnostics"][arm]["focal_premium_market_behavior"]
        for row in available
    ]
    opponent_premium = [
        row["diagnostics"][arm]["opponent_premium_market_behavior"]
        for row in available
    ]
    by_seat = {
        str(seat): _arm_summary(
            [row for row in available if int(row["seat"]) == seat], arm
        )
        for seat in (0, 1)
        if any(int(row["seat"]) == seat for row in available)
    }
    loss_cases = []
    for row in available:
        if row[arm]["result"] != "loss":
            continue
        diagnostics = row["diagnostics"][arm]
        terminal = _terminal_state(diagnostics)
        loss_cases.append(
            {
                "seed": int(row["seed"]),
                "seat": int(row["seat"]),
                "margin": float(row[arm]["margin"]),
                "day_cash_margins": {
                    str(step): float(
                        diagnostics["checkpoint_states"].get(str(step), {}).get(
                            "cash_margin", 0.0
                        )
                    )
                    for step in DAY_MARGIN_CHECKPOINTS
                },
                "terminal_shop_regime": terminal.get("unlocked_shops") or [],
                "terminal_own_portfolio": terminal.get("own_portfolio") or {},
                "terminal_opponent_portfolio": terminal.get("opponent_portfolio") or {},
                "focal_premium_market_behavior": diagnostics[
                    "focal_premium_market_behavior"
                ],
                "opponent_premium_market_behavior": diagnostics[
                    "opponent_premium_market_behavior"
                ],
            }
        )
    arm_summary = _arm_summary(available, arm)
    return {
        "available": True,
        **arm_summary,
        "games_with_diagnostics": len(available),
        "seat_breakdown": by_seat,
        "day_margin_and_reversal": checkpoint_summary,
        "lead_to_loss_any_major_checkpoint": lead_to_loss_any,
        "behind_to_win_any_major_checkpoint": behind_to_win_any,
        "terminal_shop_regimes": dict(sorted(terminal_shops.items())),
        "mean_terminal_market_inventory_delta": _mean_mapping(
            [value.get("inventory_delta") or {} for value in market_displacements]
        ),
        "mean_terminal_market_price_delta": _mean_mapping(
            [value.get("price_delta") or {} for value in market_displacements]
        ),
        "mean_terminal_market_inventory_l1": mean(
            float(value.get("inventory_l1", 0.0)) for value in market_displacements
        ),
        "mean_terminal_market_price_l1": mean(
            float(value.get("price_l1", 0.0)) for value in market_displacements
        ),
        "mean_terminal_portfolio": {
            "own": _mean_portfolio(terminal_states, "own_portfolio"),
            "opponent": _mean_portfolio(terminal_states, "opponent_portfolio"),
        },
        "mean_action_utilization": mean(
            float(value.get("action_utilization", 0.0)) for value in focal_profiles
        ),
        "mean_opponent_action_utilization": mean(
            float(value.get("action_utilization", 0.0)) for value in opponent_profiles
        ),
        "mean_market_quantity": _mean_mapping(
            [value.get("market_item_quantity") or {} for value in focal_profiles]
        ),
        "mean_opponent_market_quantity": _mean_mapping(
            [value.get("market_item_quantity") or {} for value in opponent_profiles]
        ),
        "premium_market_behavior": {
            "mean_focal_premium_sell_quantity": mean(
                float(value.get("premium_sell_quantity", 0.0))
                for value in focal_premium
            ),
            "mean_focal_premium_sell_share": mean(
                float(value.get("premium_share_of_sell_quantity", 0.0))
                for value in focal_premium
            ),
            "mean_opponent_premium_sell_quantity": mean(
                float(value.get("premium_sell_quantity", 0.0))
                for value in opponent_premium
            ),
            "mean_opponent_premium_sell_share": mean(
                float(value.get("premium_share_of_sell_quantity", 0.0))
                for value in opponent_premium
            ),
        },
        "diagnostic_loss_signals": _loss_signal_labels(
            available, arm, lead_to_loss_any
        ),
        "loss_cases": loss_cases,
    }


def _paired_feedback_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    audits = [
        row.get("divergence_audit") or {}
        for row in rows
        if isinstance(row.get("divergence_audit"), dict)
    ]

    def values(path: tuple[str, ...]) -> list[float]:
        result = []
        for audit in audits:
            value: Any = audit
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            if value is not None:
                result.append(float(value))
        return result

    def distribution(path: tuple[str, ...]) -> dict[str, Any]:
        selected = values(path)
        return {
            "observed_pairs": len(selected),
            "median_step_or_lag": median(selected) if selected else None,
            "minimum": min(selected) if selected else None,
            "maximum": max(selected) if selected else None,
        }

    component_counts: Counter[str] = Counter()
    mediator_counts: Counter[str] = Counter()
    for audit in audits:
        component = audit.get("opponent_response_component_delta") or {}
        component_counts.update(str(value) for value in component.get("changed_components") or [])
        mediator_counts.update(str(value) for value in audit.get("candidate_mediator_categories") or [])
    return {
        "available": bool(audits),
        "exact_identity_pairs": sum(
            audit.get("own_first_divergence_step") is None for audit in audits
        ),
        "first_self_divergence": distribution(("own_first_divergence_step",)),
        "first_opponent_response": distribution(("first_opponent_response_step",)),
        "opponent_response_lag_from_own_action": distribution(
            ("opponent_response_lag", "from_own_action")
        ),
        "first_market_divergence": distribution(
            ("first_state_divergence", "market_inventory", "step")
        ),
        "first_price_divergence": distribution(
            ("first_state_divergence", "prices", "step")
        ),
        "first_self_money_divergence": distribution(
            ("first_state_divergence", "self_money", "step")
        ),
        "first_opponent_money_divergence": distribution(
            ("first_state_divergence", "opponent_money", "step")
        ),
        "opponent_response_component_counts": dict(sorted(component_counts.items())),
        "candidate_mediator_category_counts": dict(sorted(mediator_counts.items())),
        "response_before_market_inventory_pairs": sum(
            bool(audit.get("response_before_market_inventory_divergence"))
            for audit in audits
        ),
        "response_before_price_pairs": sum(
            bool(audit.get("response_before_price_divergence")) for audit in audits
        ),
    }


def _family_weakness_summary(
    family_id: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    v111 = _arm_weakness_summary(rows, "v111")
    v113 = _arm_weakness_summary(rows, "v113")
    v111_outcome = _arm_summary(rows, "v111")
    v113_outcome = _arm_summary(rows, "v113")
    v111_wr = float(v111_outcome["strict_win_probability"])
    v113_wr = float(v113_outcome["strict_win_probability"])
    v111_score = float(v111_outcome["win_score"])
    v113_score = float(v113_outcome["win_score"])
    flags = {
        "v111_close_matchup_30_to_70": 0.30 <= v111_score <= 0.70,
        "v113_close_matchup_30_to_70": 0.30 <= v113_score <= 0.70,
        "v111_below_50": v111_score < 0.50,
        "v113_below_50": v113_score < 0.50,
    }
    if flags["v111_below_50"] and flags["v113_below_50"]:
        priority = "BOTH_CONTROLS_WEAK"
    elif flags["v111_below_50"]:
        priority = "V111_WEAK_V113_RELATIVE_BENCHMARK"
    elif flags["v113_below_50"]:
        priority = "V113_WEAK_V111_RELATIVE_BENCHMARK"
    elif flags["v111_close_matchup_30_to_70"] or flags["v113_close_matchup_30_to_70"]:
        priority = "SENSITIVITY_CLOSE_MATCHUP"
    else:
        priority = "REGRESSION_OR_CALIBRATION"
    return {
        "behavior_family_id": family_id,
        "priority_class": priority,
        "selection_priority_score": (1.0 - v111_score) + (1.0 - v113_score),
        "classification_basis": "draw-adjusted win score (win=1, draw=0.5, loss=0)",
        "strict_win_probability_diagnostic": {"v111": v111_wr, "v113": v113_wr},
        "draw_adjusted_win_score": {"v111": v111_score, "v113": v113_score},
        "flags": flags,
        "v111": v111,
        "v113": v113,
        "paired_feedback_channel": _paired_feedback_summary(rows),
        "interpretation_guardrail": (
            "Loss signals are descriptive mediators, not standalone causal attributions."
        ),
    }


def _causal_pair_exclusion_reasons(row: dict[str, Any]) -> list[str]:
    """Return reasons a row cannot support the paired causal comparison.

    A candidate-new hard safety failure is deliberately *not* excluded here:
    it closes the promotion gate, but dropping its outcome would bias the
    strength estimate in the candidate's favour. Pairing-integrity and
    Behavioral-Isolation failures instead invalidate the comparison itself.
    """
    reasons = []
    integrity = row.get("pairing_integrity") or {}
    if integrity and not bool(
        integrity.get(
            "valid",
            all(
                bool(integrity.get(key))
                for key in (
                    "same_requested_seed",
                    "same_resolved_seed",
                    "same_focal_seat",
                    "both_completed",
                )
            ),
        )
    ):
        reasons.append("pairing_integrity")
    divergence = row.get("divergence_audit") or {}
    if divergence and not bool(divergence.get("behavioral_isolation_valid")):
        reasons.append("behavioral_isolation")
    return reasons


def _causal_pair_valid(row: dict[str, Any]) -> bool:
    return not _causal_pair_exclusion_reasons(row)


def summarize_pairs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"total_pairs": 0}
    causal_rows = [row for row in rows if _causal_pair_valid(row)]
    if not causal_rows:
        return {
            "total_pairs": len(rows),
            "causal_valid_pairs": 0,
            "causal_invalid_pairs": len(rows),
            "causal_effect_available": False,
            "causal_exclusion_reason_counts": dict(
                sorted(
                    Counter(
                        reason
                        for row in rows
                        for reason in _causal_pair_exclusion_reasons(row)
                    ).items()
                )
            ),
            "trigger_pairs": sum(bool(row.get("gate_requested")) for row in rows),
            "actual_treatment_pairs": sum(
                bool(row.get("actual_treatment")) for row in rows
            ),
            "action_divergent_pairs": sum(
                bool(row.get("action_divergent_pair")) for row in rows
            ),
            "treatment_delivery_failures": sum(
                bool(row.get("treatment_delivery_failure")) for row in rows
            ),
            "safe_baseline_overlaps": sum(
                bool(row.get("safe_baseline_overlap")) for row in rows
            ),
            "hard_safety_failure_pairs": sum(
                bool(
                    (row.get("safety_classification") or {}).get(
                        "hard_safety_failures"
                    )
                )
                for row in rows
            ),
            "behavioral_isolation_invalid_pairs": sum(
                "behavioral_isolation" in _causal_pair_exclusion_reasons(row)
                for row in rows
            ),
        }
    transitions = Counter(
        f"{row['v111']['result']}->{row['v113']['result']}" for row in causal_rows
    )
    registered_transitions = Counter(
        f"{row['v111']['result']}->{row['v113']['result']}" for row in rows
    )
    actual = [row for row in causal_rows if row.get("actual_treatment")]
    return {
        "total_pairs": len(rows),
        "causal_valid_pairs": len(causal_rows),
        "causal_invalid_pairs": len(rows) - len(causal_rows),
        "causal_effect_available": True,
        "causal_exclusion_reason_counts": dict(
            sorted(
                Counter(
                    reason
                    for row in rows
                    for reason in _causal_pair_exclusion_reasons(row)
                ).items()
            )
        ),
        "independent_seeds": len({int(row["seed"]) for row in causal_rows}),
        "v111": _arm_summary(causal_rows, "v111"),
        "v113": _arm_summary(causal_rows, "v113"),
        "registered_all_pairs_v111_diagnostic": _arm_summary(rows, "v111"),
        "registered_all_pairs_v113_diagnostic": _arm_summary(rows, "v113"),
        "delta_win_probability": mean(
            float(row["delta_win_probability"]) for row in causal_rows
        ),
        "delta_win_score": mean(float(row["delta_win_score"]) for row in causal_rows),
        "mean_delta_self_coin": mean(
            float(row["delta_self_coin"]) for row in causal_rows
        ),
        "mean_delta_opponent_coin": mean(
            float(row["delta_opponent_coin"]) for row in causal_rows
        ),
        "mean_delta_margin": mean(float(row["delta_margin"]) for row in causal_rows),
        "loss_to_win": sum(bool(row["loss_to_win"]) for row in causal_rows),
        "win_to_loss": sum(bool(row["win_to_loss"]) for row in causal_rows),
        "strict_discordant_outcome_pairs": sum(
            bool(row["loss_to_win"] or row["win_to_loss"]) for row in causal_rows
        ),
        "any_outcome_changed_pairs": sum(
            row["v111"]["result"] != row["v113"]["result"] for row in causal_rows
        ),
        "outcome_transition_counts": dict(sorted(transitions.items())),
        "registered_all_pairs_outcome_transition_counts_diagnostic": dict(
            sorted(registered_transitions.items())
        ),
        "trigger_pairs": sum(bool(row.get("gate_requested")) for row in rows),
        "actual_treatment_pairs": sum(
            bool(row.get("actual_treatment")) for row in rows
        ),
        "causal_valid_actual_treatment_pairs": len(actual),
        "action_divergent_pairs": sum(
            bool(row.get("action_divergent_pair")) for row in rows
        ),
        "treatment_delivery_failures": sum(
            bool(row.get("treatment_delivery_failure")) for row in rows
        ),
        "safe_baseline_overlaps": sum(
            bool(row.get("safe_baseline_overlap")) for row in rows
        ),
        "hard_safety_failure_pairs": sum(
            bool(
                (row.get("safety_classification") or {}).get(
                    "hard_safety_failures"
                )
            )
            for row in rows
        ),
        "behavioral_isolation_invalid_pairs": sum(
            "behavioral_isolation" in _causal_pair_exclusion_reasons(row)
            for row in rows
        ),
        "actual_treatment_effect_diagnostic": (
            {
                "pairs": len(actual),
                "loss_to_win": sum(bool(row["loss_to_win"]) for row in actual),
                "win_to_loss": sum(bool(row["win_to_loss"]) for row in actual),
                "mean_delta_win_probability": mean(
                    float(row["delta_win_probability"]) for row in actual
                ),
                "mean_delta_margin": mean(float(row["delta_margin"]) for row in actual),
            }
            if actual
            else {"pairs": 0}
        ),
    }


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


METRICS = {
    "v111_win_probability": lambda row: float(row["v111"]["result"] == "win"),
    "v113_win_probability": lambda row: float(row["v113"]["result"] == "win"),
    "delta_win_probability": lambda row: float(row["delta_win_probability"]),
    "v111_win_score": lambda row: float(row["v111"]["score"]),
    "v113_win_score": lambda row: float(row["v113"]["score"]),
    "delta_win_score": lambda row: float(row["delta_win_score"]),
    "delta_margin": lambda row: float(row["delta_margin"]),
}


def hierarchical_family_seed_bootstrap(
    rows: list[dict[str, Any]],
    family_weights: dict[str, float],
    *,
    repetitions: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    """Bootstrap independent family -> seed while retaining both seats."""
    if not rows:
        raise ValueError("cannot bootstrap an empty panel")
    if repetitions <= 0:
        raise ValueError("bootstrap repetitions must be positive")
    grouped: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        grouped[str(row["behavior_family_id"])][int(row["seed"])].append(row)
    family_ids = sorted(grouped)
    unknown = sorted(set(family_ids) - set(family_weights))
    if unknown:
        raise ValueError(f"missing weights for families: {unknown}")
    total = sum(float(family_weights[family_id]) for family_id in family_ids)
    weights = {
        family_id: float(family_weights[family_id]) / total for family_id in family_ids
    }
    point: dict[str, dict[str, float]] = {"meta_weighted": {}, "macro_lineage": {}}
    for metric_name, metric in METRICS.items():
        family_values = {
            family_id: mean(metric(row) for seed_rows in grouped[family_id].values() for row in seed_rows)
            for family_id in family_ids
        }
        point["meta_weighted"][metric_name] = sum(
            weights[family_id] * family_values[family_id] for family_id in family_ids
        )
        point["macro_lineage"][metric_name] = mean(family_values.values())
    rng = random.Random(bootstrap_seed)
    estimates: dict[str, dict[str, list[float]]] = {
        mode: {metric_name: [] for metric_name in METRICS}
        for mode in ("meta_weighted", "macro_lineage")
    }
    for _ in range(repetitions):
        for mode in ("meta_weighted", "macro_lineage"):
            sampled_families = rng.choices(
                family_ids,
                weights=(
                    [weights[family_id] for family_id in family_ids]
                    if mode == "meta_weighted"
                    else None
                ),
                k=len(family_ids),
            )
            sampled_values = {metric_name: [] for metric_name in METRICS}
            for family_id in sampled_families:
                seed_groups = grouped[family_id]
                seed_ids = sorted(seed_groups)
                sampled_seeds = rng.choices(seed_ids, k=len(seed_ids))
                for metric_name, metric in METRICS.items():
                    sampled_values[metric_name].append(
                        mean(
                            mean(metric(row) for row in seed_groups[seed])
                            for seed in sampled_seeds
                        )
                    )
            for metric_name in METRICS:
                estimates[mode][metric_name].append(mean(sampled_values[metric_name]))
    return {
        "method": (
            "hierarchical cluster bootstrap: independent executable action family -> "
            "episode seed cluster; both seats retained"
        ),
        "independent_families": len(family_ids),
        "independent_seeds_by_family": {
            family_id: len(grouped[family_id]) for family_id in family_ids
        },
        "repetitions": repetitions,
        "family_weights": weights,
        **{
            mode: {
                metric_name: {
                    "estimate": point[mode][metric_name],
                    "low_95": _quantile(values, 0.025),
                    "high_95": _quantile(values, 0.975),
                }
                for metric_name, values in estimates[mode].items()
            }
            for mode in estimates
        },
    }


def seed_cluster_uncertainty(
    rows: list[dict[str, Any]],
    *,
    repetitions: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    """Within-family seed bootstrap; all seats from a sampled seed stay together."""
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["seed"])].append(row)
    seed_ids = sorted(grouped)
    rng = random.Random(bootstrap_seed)
    selected_metrics = {
        key: METRICS[key]
        for key in (
            "v111_win_probability",
            "v113_win_probability",
            "delta_win_probability",
            "delta_win_score",
            "delta_margin",
        )
    }
    estimates = {key: [] for key in selected_metrics}
    for _ in range(repetitions):
        sampled = rng.choices(seed_ids, k=len(seed_ids))
        for key, metric in selected_metrics.items():
            estimates[key].append(
                mean(
                    mean(metric(row) for row in grouped[seed])
                    for seed in sampled
                )
            )
    return {
        "method": "episode-seed cluster bootstrap; both seats retained",
        "independent_seeds": len(seed_ids),
        "repetitions": repetitions,
        **{
            key: {
                "estimate": mean(metric(row) for row in rows),
                "low_95": _quantile(estimates[key], 0.025),
                "high_95": _quantile(estimates[key], 0.975),
            }
            for key, metric in selected_metrics.items()
        },
    }


def summarize_panel(
    rows: list[dict[str, Any]],
    family_weights: dict[str, float],
    *,
    repetitions: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["behavior_family_id"])].append(row)
    causal_rows = [row for row in rows if _causal_pair_valid(row)]
    causal_family_ids = {
        str(row["behavior_family_id"]) for row in causal_rows
    }
    missing_causal_families = sorted(set(grouped) - causal_family_ids)
    matrix = []
    for index, family_id in enumerate(sorted(grouped)):
        selected = grouped[family_id]
        causal_selected = [row for row in selected if _causal_pair_valid(row)]
        by_seat = {
            str(seat): summarize_pairs(
                [row for row in selected if int(row["seat"]) == seat]
            )
            for seat in (0, 1)
        }
        matrix.append(
            {
                "behavior_family_id": family_id,
                "meta_weight": float(family_weights[family_id]),
                **summarize_pairs(selected),
                "weakness_diagnostics": _family_weakness_summary(
                    family_id, selected
                ),
                "seed_cluster_uncertainty": (
                    seed_cluster_uncertainty(
                        causal_selected,
                        repetitions=repetitions,
                        bootstrap_seed=bootstrap_seed + (index + 1) * 7919,
                    )
                    if causal_selected
                    else {
                        "status": "INVALID_FOR_CAUSAL_STRENGTH",
                        "reason": "no pairing-and-behavioral-isolation-valid pairs",
                    }
                ),
                "seat_breakdown": by_seat,
                "seat_delta_win_probability_gap_seat0_minus_seat1": (
                    float(by_seat["0"]["delta_win_probability"])
                    - float(by_seat["1"]["delta_win_probability"])
                    if by_seat["0"].get("causal_effect_available")
                    and by_seat["1"].get("causal_effect_available")
                    else None
                ),
            }
        )
    invalid_reason_counts = Counter(
        reason
        for row in rows
        for reason in _causal_pair_exclusion_reasons(row)
    )
    hard_safety_pairs = sum(
        bool(
            (row.get("safety_classification") or {}).get(
                "hard_safety_failures"
            )
        )
        for row in rows
    )
    validity_gate = {
        "registered_pairs": len(rows),
        "causal_valid_pairs": len(causal_rows),
        "causal_invalid_pairs": len(rows) - len(causal_rows),
        "causal_exclusion_reason_counts": dict(sorted(invalid_reason_counts.items())),
        "families_without_any_causal_valid_pair": missing_causal_families,
        "hard_safety_failure_pairs": hard_safety_pairs,
        "pairing_and_behavioral_isolation_status": (
            "PASS"
            if len(causal_rows) == len(rows) and not missing_causal_families
            else "FAIL"
        ),
        "hard_safety_status": "PASS" if hard_safety_pairs == 0 else "FAIL",
        "promotion_strength_gate_open": (
            len(causal_rows) == len(rows)
            and not missing_causal_families
            and hard_safety_pairs == 0
        ),
    }
    if causal_rows and not missing_causal_families:
        hierarchical: dict[str, Any] = {
            "status": "AVAILABLE",
            **hierarchical_family_seed_bootstrap(
                causal_rows,
                family_weights,
                repetitions=repetitions,
                bootstrap_seed=bootstrap_seed,
            ),
        }
    else:
        hierarchical = {
            "status": "INVALID_FOR_CAUSAL_STRENGTH",
            "reason": "one or more families have no pairing-and-behavioral-isolation-valid pair",
            "independent_families": len(causal_family_ids),
            "families_without_any_causal_valid_pair": missing_causal_families,
        }
    return {
        "validity_gate": validity_gate,
        "pairwise_payoff_matrix": matrix,
        "unweighted_episode_summary_diagnostic": summarize_pairs(rows),
        "seat_breakdown": {
            str(seat): summarize_pairs(
                [row for row in rows if int(row["seat"]) == seat]
            )
            for seat in (0, 1)
        },
        "hierarchical_uncertainty": hierarchical,
    }


def build_result(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    selected_panels: list[str],
    *,
    repetitions: int,
    bootstrap_seed: int,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    panel_results = {}
    for index, panel_name in enumerate(selected_panels):
        selected = [row for row in rows if panel_name in row["panel_memberships"]]
        panel = manifest["panels"][panel_name]
        panel_results[panel_name] = {
            "configuration": panel,
            **summarize_panel(
                selected,
                panel["weights"],
                repetitions=repetitions,
                bootstrap_seed=bootstrap_seed + index * 104729,
            ),
        }
    return {
        "format": FORMAT,
        "created_at": datetime.now().astimezone().isoformat(),
        "evidence_interpretation": {
            "clean_causal_control": "V111",
            "live_validated_field_benchmark": "V113 submission-equivalent code",
            "paired_executable_evidence": "E3",
            "diverse_meta_eligibility": (
                "E4 only when the selected Meta Panel is demonstrably diverse; "
                "this evaluator does not promote either arm by itself"
            ),
            "live_rating_is_not_gate_causality": True,
        },
        "provenance": provenance,
        "dataset_role": manifest.get("dataset_role"),
        "selection": manifest.get("selection") or {},
        "preregistered_dual_benchmark": manifest.get(
            "preregistered_dual_benchmark"
        )
        or {},
        "fresh_holdout_exclusions": manifest.get("fresh_holdout_exclusions") or {},
        "selected_panels": selected_panels,
        "controls": manifest["controls"],
        "families": manifest["families"],
        "panels": panel_results,
        "pairs": sorted(
            rows,
            key=lambda row: (
                row["behavior_family_id"],
                int(row["seed"]),
                int(row["seat"]),
            ),
        ),
    }


def build_weakness_map(result: dict[str, Any]) -> dict[str, Any]:
    """Build a cross-panel family map without double-counting overlapping panels."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in result.get("pairs") or []:
        grouped[str(row["behavior_family_id"])].append(row)
    metadata = {
        row["behavior_family_id"]: row for row in result.get("families") or []
    }
    families = []
    for family_id, rows in sorted(grouped.items()):
        weakness = _family_weakness_summary(family_id, rows)
        pairwise = summarize_pairs(rows)
        family = metadata.get(family_id) or {}
        families.append(
            {
                **weakness,
                "representative_candidate_id": family.get(
                    "representative_candidate_id"
                ),
                "source_ancestry_ids": family.get("source_ancestry_ids") or [],
                "source_members": family.get("source_members") or [],
                "panel_memberships": sorted(
                    {
                        str(panel)
                        for row in rows
                        for panel in row.get("panel_memberships") or []
                    }
                ),
                "pairwise_v111_to_v113": {
                    "total_pairs": pairwise["total_pairs"],
                    "causal_valid_pairs": pairwise.get("causal_valid_pairs", 0),
                    "causal_effect_available": pairwise.get(
                        "causal_effect_available", False
                    ),
                    "v111_strict_win_probability": (pairwise.get("v111") or {}).get(
                        "strict_win_probability"
                    ),
                    "v113_strict_win_probability": (pairwise.get("v113") or {}).get(
                        "strict_win_probability"
                    ),
                    "v111_win_score": (pairwise.get("v111") or {}).get("win_score"),
                    "v113_win_score": (pairwise.get("v113") or {}).get("win_score"),
                    "delta_win_probability": pairwise.get("delta_win_probability"),
                    "loss_to_win": pairwise.get("loss_to_win", 0),
                    "win_to_loss": pairwise.get("win_to_loss", 0),
                    "mean_delta_self_coin": pairwise.get("mean_delta_self_coin"),
                    "mean_delta_opponent_coin": pairwise.get(
                        "mean_delta_opponent_coin"
                    ),
                    "mean_delta_margin": pairwise.get("mean_delta_margin"),
                    "trigger_pairs": pairwise["trigger_pairs"],
                    "actual_treatment_pairs": pairwise["actual_treatment_pairs"],
                    "strict_discordant_outcome_pairs": pairwise.get(
                        "strict_discordant_outcome_pairs", 0
                    ),
                },
            }
        )
    families.sort(
        key=lambda row: (
            -float(row["selection_priority_score"]),
            str(row["behavior_family_id"]),
        )
    )
    close = [
        row["behavior_family_id"]
        for row in families
        if row["flags"]["v111_close_matchup_30_to_70"]
        or row["flags"]["v113_close_matchup_30_to_70"]
    ]
    sub50 = [
        row["behavior_family_id"]
        for row in families
        if row["flags"]["v111_below_50"] or row["flags"]["v113_below_50"]
    ]
    return {
        "format": "kaggriculture-v111-v113-weakness-map-v1",
        "created_at": result.get("created_at"),
        "source_result": result.get("provenance") or {},
        "evidence_level": (
            "E3 paired executable diagnostics; E4 only for a pre-registered, "
            "diverse Meta Panel"
        ),
        "controls": {
            "clean_causal_control": "V111",
            "live_validated_field_benchmark": "V113 submission-equivalent code",
        },
        "independent_executable_families": len(families),
        "close_matchup_family_ids_30_to_70": close,
        "below_50_family_ids": sub50,
        "families": families,
        "best_response_selection_rule": (
            "Select one large, repeated, experimentally targetable loss regime only "
            "after loss-case review; do not infer a V114 rule from aggregate labels alone."
        ),
        "fresh_holdout_guardrail": (
            "Every family or seed used in common probes or this benchmark remains "
            "Discovery/Development and cannot later be relabeled Fresh Holdout."
        ),
    }


def _weakness_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# V111/V113 executable-family Weakness Map",
        "",
        "This map treats V111 as the clean causal control and V113 as the "
        "live-validated benchmark. Aggregate loss signals are diagnostics, not "
        "causal Best-Response proof.",
        "",
        f"- Independent executable families: {payload['independent_executable_families']}",
        "- Close-matchup families (either arm 30–70% WR): "
        f"`{payload['close_matchup_family_ids_30_to_70']}`",
        f"- Below-50% families: `{payload['below_50_family_ids']}`",
        "",
        "| Family | Panels | V111 WR | V113 WR | ΔWR | V111 margin | V113 margin | "
        "L→W | W→L | Priority |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in payload["families"]:
        paired = row["pairwise_v111_to_v113"]
        v111 = row["v111"]
        v113 = row["v113"]
        v111_wr = paired.get("v111_strict_win_probability")
        v113_wr = paired.get("v113_strict_win_probability")
        delta = paired.get("delta_win_probability")
        lines.append(
            "| {family} | {panels} | {v111_wr} | {v113_wr} | "
            "{delta} | {v111_margin:+.1f} | {v113_margin:+.1f} | "
            "{l2w} | {w2l} | {priority} |".format(
                family=row["behavior_family_id"],
                panels=", ".join(row["panel_memberships"]),
                v111_wr=f"{v111_wr:.1%}" if v111_wr is not None else "n/a",
                v113_wr=f"{v113_wr:.1%}" if v113_wr is not None else "n/a",
                delta=f"{delta:+.1%}" if delta is not None else "n/a",
                v111_margin=v111.get("mean_margin", 0.0),
                v113_margin=v113.get("mean_margin", 0.0),
                l2w=paired["loss_to_win"],
                w2l=paired["win_to_loss"],
                priority=row["priority_class"],
            )
        )
    lines.extend(["", "## Family diagnostics", ""])
    for row in payload["families"]:
        feedback = row["paired_feedback_channel"]
        lines.extend(
            [
                f"### {row['behavior_family_id']}",
                "",
                f"- V111 loss signals: `{row['v111'].get('diagnostic_loss_signals', [])}`",
                f"- V113 loss signals: `{row['v113'].get('diagnostic_loss_signals', [])}`",
                "- Lead→loss (major checkpoints): "
                f"V111 `{row['v111'].get('lead_to_loss_any_major_checkpoint')}`, "
                f"V113 `{row['v113'].get('lead_to_loss_any_major_checkpoint')}`",
                "- First self divergence median: "
                f"`{feedback['first_self_divergence']['median_step_or_lag']}`; "
                "opponent response median: "
                f"`{feedback['first_opponent_response']['median_step_or_lag']}`; "
                "response lag median: "
                f"`{feedback['opponent_response_lag_from_own_action']['median_step_or_lag']}`",
                "- Opponent response components: "
                f"`{feedback['opponent_response_component_counts']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Selection guardrail",
            "",
            payload["best_response_selection_rule"],
            "",
            payload["fresh_holdout_guardrail"],
            "",
        ]
    )
    return "\n".join(lines)


def _markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Expanded V111/V113 paired benchmark",
        "",
        "V111 is the clean causal control; V113 is the live-validated field benchmark. "
        "This report does not modify the immutable prior 60-pair verdict and does not "
        "treat live rating as causal gate evidence.",
        "",
    ]
    for panel_name, panel in result["panels"].items():
        uncertainty = panel["hierarchical_uncertainty"]
        validity = panel["validity_gate"]
        if uncertainty.get("status") != "AVAILABLE":
            lines.extend(
                [
                    f"## {panel_name}",
                    "",
                    "- Paired causal strength: unavailable because pairing/Behavioral "
                    "Isolation coverage is incomplete.",
                    f"- Validity gate: `{validity}`",
                    "",
                ]
            )
            continue
        meta_delta = uncertainty["meta_weighted"]["delta_win_probability"]
        macro_delta = uncertainty["macro_lineage"]["delta_win_probability"]
        meta_score = uncertainty["meta_weighted"]["delta_win_score"]
        macro_score = uncertainty["macro_lineage"]["delta_win_score"]
        lines.extend(
            [
                f"## {panel_name}",
                "",
                f"- Independent executable families: {uncertainty['independent_families']}",
                "- Validity/Safety gate: "
                f"pairing+isolation `{validity['pairing_and_behavioral_isolation_status']}`, "
                f"hard safety `{validity['hard_safety_status']}`; "
                f"causal-valid pairs `{validity['causal_valid_pairs']}/{validity['registered_pairs']}`",
                "- Meta-weighted V113−V111 strict win-probability delta: "
                f"{meta_delta['estimate']:+.1%} "
                f"(family→seed 95% interval {meta_delta['low_95']:+.1%} to "
                f"{meta_delta['high_95']:+.1%})",
                "- Macro-lineage V113−V111 strict win-probability delta: "
                f"{macro_delta['estimate']:+.1%} "
                f"(family→seed 95% interval {macro_delta['low_95']:+.1%} to "
                f"{macro_delta['high_95']:+.1%})",
                "- Pre-registered Meta-weighted V113−V111 win-score delta: "
                f"{meta_score['estimate']:+.1%} "
                f"(95% interval {meta_score['low_95']:+.1%} to "
                f"{meta_score['high_95']:+.1%})",
                "- Pre-registered Macro-family V113−V111 win-score delta: "
                f"{macro_score['estimate']:+.1%} "
                f"(95% interval {macro_score['low_95']:+.1%} to "
                f"{macro_score['high_95']:+.1%})",
                "",
                "| Family | Pairs | V111 WR | V113 WR | ΔWR | L→W | W→L | Trigger | Actual | Δ margin |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in panel["pairwise_payoff_matrix"]:
            lines.append(
                "| {family} | {pairs} | {v111:.1%} | {v113:.1%} | {delta:+.1%} | "
                "{l2w} | {w2l} | {trigger} | {actual} | {margin:+.1f} |".format(
                    family=row["behavior_family_id"],
                    pairs=row["total_pairs"],
                    v111=row["v111"]["strict_win_probability"],
                    v113=row["v113"]["strict_win_probability"],
                    delta=row["delta_win_probability"],
                    l2w=row["loss_to_win"],
                    w2l=row["win_to_loss"],
                    trigger=row["trigger_pairs"],
                    actual=row["actual_treatment_pairs"],
                    margin=row["mean_delta_margin"],
                )
            )
        lines.extend(
            [
                "",
                "`Actual` counts pairs where the intended incremental Cow→Sheep action "
                "was emitted. Total pairs, triggers, actual treatments, and discordant "
                "outcomes remain separate statistical quantities.",
                "",
            ]
        )
    return "\n".join(lines)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid checkpoint JSONL at line {number}: {path}") from exc
    return result


def _validate_checkpoint_rows(
    rows: list[dict[str, Any]], tasks: list[dict[str, Any]]
) -> None:
    """Reject a checkpoint row that does not match its frozen task metadata."""
    expected = {str(task["task_key"]): task for task in tasks}
    for row in rows:
        key = str(row.get("task_key") or "")
        task = expected.get(key)
        if task is None:
            raise ValueError(f"checkpoint contains a task outside this run: {key}")
        comparisons = {
            "behavior_family_id": (
                str(row.get("behavior_family_id")),
                str(task["behavior_family_id"]),
            ),
            "seed": (int(row.get("seed", -1)), int(task["seed"])),
            "seat": (int(row.get("seat", -1)), int(task["seat"])),
            "panel_memberships": (
                sorted(str(value) for value in row.get("panel_memberships") or []),
                sorted(str(value) for value in task["panel_memberships"]),
            ),
        }
        mismatches = [
            name for name, (observed, planned) in comparisons.items() if observed != planned
        ]
        if mismatches:
            raise ValueError(
                f"checkpoint task metadata mismatch for {key}: {mismatches}"
            )


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")
        handle.flush()


def _run_pending(
    tasks: list[dict[str, Any]], workers: int, checkpoint: Path, errors_path: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def record(completed: int, row: dict[str, Any]) -> None:
        rows.append(row)
        _append_jsonl(checkpoint, row)
        print(
            json.dumps(
                {
                    "progress": f"{completed}/{len(tasks)}",
                    "family": row["behavior_family_id"],
                    "seed": row["seed"],
                    "seat": row["seat"],
                    "v111": row["v111"]["result"],
                    "v113": row["v113"]["result"],
                    "trigger": row["gate_requested"],
                    "actual": row["actual_treatment"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    if workers <= 1:
        for completed, task in enumerate(tasks, start=1):
            try:
                record(completed, run_dual_task(task))
            except Exception as exc:  # pragma: no cover - external executable failure
                error = {
                    "task_key": task["task_key"],
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
                errors.append(error)
                _append_jsonl(errors_path, error)
        return rows, errors
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=max(1, workers),
        mp_context=context,
        max_tasks_per_child=1,
    ) as executor:
        futures = {executor.submit(run_dual_task, task): task for task in tasks}
        for completed, future in enumerate(as_completed(futures), start=1):
            task = futures[future]
            try:
                record(completed, future.result())
            except Exception as exc:  # pragma: no cover - external executable failure
                error = {
                    "task_key": task["task_key"],
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
                errors.append(error)
                _append_jsonl(errors_path, error)
    return rows, errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("experiments/independent_gold_pool/family_panel_manifest.json"),
    )
    parser.add_argument("--panel", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--bootstrap-repetitions", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=29116001)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-fresh-holdout", action="store_true")
    args = parser.parse_args()

    manifest_path = _resolve(args.manifest)
    raw_manifest, manifest_sha = _load_json(manifest_path)
    manifest = normalize_manifest(raw_manifest)
    selected_panels = validate_panel_selection(
        manifest,
        args.panel or [DEFAULT_PANEL],
        allow_fresh_holdout=args.allow_fresh_holdout,
    )
    tasks = build_tasks(manifest, selected_panels)
    validate_preregistered_task_count(manifest, tasks)
    evaluator_path = Path(__file__).resolve()
    configuration = {
        "format": FORMAT,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "resolved_input_signature": stable_json_hash(
            {
                "controls": manifest["controls"],
                "families": manifest["families"],
            },
            32,
        ),
        "evaluator": str(evaluator_path),
        "evaluator_sha256": sha256_file(evaluator_path),
        "selected_panels": selected_panels,
        "episode_steps": 720,
        "action_checkpoints": list(ACTION_CHECKPOINTS),
        "bootstrap_repetitions": int(args.bootstrap_repetitions),
        "bootstrap_seed": int(args.bootstrap_seed),
        "planned_task_keys": [task["task_key"] for task in tasks],
    }
    configuration["configuration_signature"] = stable_json_hash(configuration, 32)
    output = _resolve(args.output)
    config_path = output / "run_configuration.json"
    result_path = output / "experiment_result.json"
    checkpoint = output / "pairs.jsonl"
    errors_path = output / "errors.jsonl"
    if output.exists() and not args.resume:
        raise FileExistsError(f"output already exists; use --resume for an incomplete run: {output}")
    if result_path.is_file():
        raise FileExistsError(f"completed immutable result already exists: {result_path}")
    output.mkdir(parents=True, exist_ok=True)
    if config_path.is_file():
        previous = json.loads(config_path.read_text(encoding="utf-8"))
        if previous.get("configuration_signature") != configuration["configuration_signature"]:
            raise ValueError("resume configuration does not match the existing run")
    else:
        config_path.write_text(
            json.dumps(configuration, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    existing = _read_jsonl(checkpoint)
    existing_by_key = {str(row["task_key"]): row for row in existing}
    if len(existing_by_key) != len(existing):
        raise ValueError("checkpoint contains duplicate completed task keys")
    planned_keys = {task["task_key"] for task in tasks}
    unexpected = sorted(set(existing_by_key) - planned_keys)
    if unexpected:
        raise ValueError(f"checkpoint contains tasks outside this run: {unexpected}")
    _validate_checkpoint_rows(existing, tasks)
    pending = [task for task in tasks if task["task_key"] not in existing_by_key]
    new_rows, errors = _run_pending(
        pending,
        max(1, int(args.workers)),
        checkpoint,
        errors_path,
    )
    all_rows = [*existing_by_key.values(), *new_rows]
    if errors or len(all_rows) != len(tasks):
        status = {
            "status": "INCOMPLETE",
            "completed_pairs": len(all_rows),
            "planned_pairs": len(tasks),
            "errors_this_attempt": errors,
            "resume_command_required": True,
        }
        (output / "status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise RuntimeError(
            f"dual benchmark incomplete: completed={len(all_rows)}/{len(tasks)}, "
            f"errors={len(errors)}; rerun with --resume after resolving errors"
        )
    provenance = {
        "source_manifest": str(manifest_path),
        "source_manifest_sha256": manifest_sha,
        "evaluator": str(evaluator_path),
        "evaluator_sha256": configuration["evaluator_sha256"],
        "run_configuration": str(config_path),
        "run_configuration_signature": configuration["configuration_signature"],
        "resolved_input_signature": configuration["resolved_input_signature"],
        "pair_checkpoint": str(checkpoint),
        "reused_completed_pairs": len(existing),
        "new_completed_pairs": len(new_rows),
    }
    result = build_result(
        all_rows,
        manifest,
        selected_panels,
        repetitions=int(args.bootstrap_repetitions),
        bootstrap_seed=int(args.bootstrap_seed),
        provenance=provenance,
    )
    report_path = output / "report.md"
    report_path.write_text(_markdown(result), encoding="utf-8")
    weakness_map = build_weakness_map(result)
    weakness_path = output / "weakness_map.json"
    weakness_report_path = output / "weakness_map.md"
    weakness_path.write_text(
        json.dumps(weakness_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    weakness_report_path.write_text(
        _weakness_markdown(weakness_map), encoding="utf-8"
    )
    # Write the immutable result last among derived artifacts. If report
    # generation fails, --resume can safely reuse the completed pair checkpoint
    # instead of being blocked by a partial finalization marker.
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    immutable_result_manifest_path = output / "immutable_result_manifest.json"
    immutable_result_manifest = {
        "format": "kaggriculture-v111-v113-expanded-result-integrity-v1",
        "result": str(result_path),
        "result_sha256": sha256_file(result_path),
        "pair_checkpoint": str(checkpoint),
        "pair_checkpoint_sha256": sha256_file(checkpoint),
        "source_manifest": str(manifest_path),
        "source_manifest_sha256": manifest_sha,
        "evaluator": str(evaluator_path),
        "evaluator_sha256": configuration["evaluator_sha256"],
        "run_configuration": str(config_path),
        "run_configuration_sha256": sha256_file(config_path),
        "report": str(report_path),
        "report_sha256": sha256_file(report_path),
        "weakness_map": str(weakness_path),
        "weakness_map_sha256": sha256_file(weakness_path),
        "weakness_report": str(weakness_report_path),
        "weakness_report_sha256": sha256_file(weakness_report_path),
    }
    immutable_result_manifest_path.write_text(
        json.dumps(immutable_result_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "status.json").write_text(
        json.dumps(
            {
                "status": "COMPLETE",
                "completed_pairs": len(all_rows),
                "planned_pairs": len(tasks),
                "result": str(result_path),
                "result_sha256": immutable_result_manifest["result_sha256"],
                "weakness_map": str(weakness_path),
                "immutable_result_manifest": str(immutable_result_manifest_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "COMPLETE",
                "pairs": len(all_rows),
                "panels": selected_panels,
                "result": str(result_path),
                "result_sha256": immutable_result_manifest["result_sha256"],
                "report": str(report_path),
                "weakness_map": str(weakness_path),
                "weakness_report": str(weakness_report_path),
                "immutable_result_manifest": str(immutable_result_manifest_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
