"""Build the non-mutating V113 post-hoc evidence and forensic addendum.

This script reads the frozen formal result and saved replays.  It never edits
the preregistration, formal result, or frozen Agent package.  Its output is a
new write-once assessment whose claims are intentionally separated into the
preregistered verdict, current research interpretation, and E6 observation.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import importlib.util
import json
import sys
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.evaluation.divergence import audit_pair  # noqa: E402
from scripts.evaluation.safety import classify_candidate_incidents  # noqa: E402
from scripts.evaluation.schema import file_sha256  # noqa: E402

RESULT = REPO / "data/evaluation/v113_cow_sheep_gate_e3e4_20260901_2024/experiment_result.json"
PREREGISTRATION = REPO / "experiments/v113_cow_sheep_gate_e3e4/preregistration.json"
V14_SOURCE = REPO / "agents/v14/main.py"
KNOWN_RESULT_SHA256 = "70f4e3ebd86b77686247f82ff253300d5374040cc70bc96ba6d3fbdc181597d5"
KNOWN_V14_SHA256 = "727a5e11d735977ba35f27f0c86ed2583fa919aa83d6eb26c34dc3d9783dcdc7"


def _read_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _resolved_artifact(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    candidate = REPO / path
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(path)


def _actions(replay: dict[str, Any], seat: int) -> list[Any]:
    return [
        (states[seat] or {}).get("action") if seat < len(states) else None
        for states in replay.get("steps") or []
    ]


def _step_action(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    # observation[t] emits the action stored at state t+1.
    return copy.deepcopy(replay["steps"][step + 1][seat]["action"])


def _step_observation(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    return copy.deepcopy(replay["steps"][step][seat]["observation"])


def _animal_counts(obs: dict[str, Any], seat: int) -> dict[str, int]:
    counts = {"COW": 0, "SHEEP": 0}
    for row in obs["farms"][seat].get("tiles") or []:
        for tile in row or []:
            if isinstance(tile, dict) and tile.get("animal") in counts:
                counts[str(tile["animal"])] += 1
    return counts


def _trigger_funnel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    requested = [row for row in rows if row["gate_requested"]]
    classifications: list[dict[str, Any]] = []
    for row in requested:
        control_tx = row["safety"]["control"]["transaction"]
        treatment_tx = row["safety"]["treatment"]["transaction"]
        incident = classify_candidate_incidents(
            row["safety"]["control"], row["safety"]["treatment"]
        )
        item: dict[str, Any] = {
            "lineage_id": row["lineage_id"],
            "seed": row["seed"],
            "seat": row["seat"],
            "incremental_treatment": bool(row["incremental_treatment"]),
            "control_purchase_rewrite": bool(control_tx["emitted_purchase_rewrite"]),
            "treatment_purchase_rewrite": bool(treatment_tx["emitted_purchase_rewrite"]),
            "control_purchase_units_committed": int(control_tx["purchase_units_committed"]),
            "treatment_purchase_units_committed": int(treatment_tx["purchase_units_committed"]),
            "incident_classification_under_future_framework": incident,
        }
        if row["incremental_treatment"]:
            item["reason_code"] = "ACTUAL_INCREMENTAL_COW_TO_SHEEP"
            item["delivery_state"] = "COMMIT"
        elif (
            control_tx["emitted_purchase_rewrite"]
            and treatment_tx["emitted_purchase_rewrite"]
            and int(control_tx["purchase_units_committed"]) == 2
            and int(treatment_tx["purchase_units_committed"]) == 2
        ):
            item["reason_code"] = "ALREADY_SATISFIED_BASELINE_ROUTE_OVERLAP"
            item["delivery_state"] = "SAFE_CANCEL"
        else:
            control_path = _resolved_artifact(row["replay_artifacts"]["control"])
            treatment_path = _resolved_artifact(row["replay_artifacts"]["treatment"])
            control = _read_gzip_json(control_path)
            treatment = _read_gzip_json(treatment_path)
            control_action = _step_action(control, 248, int(row["seat"]))
            treatment_action = _step_action(treatment, 248, int(row["seat"]))
            treatment_obs = _step_observation(treatment, 248, int(row["seat"]))
            unique_fallback_reasons = sorted(
                {
                    str(value["reason"])
                    for value in row["agent_trace"]["treatment"]["fallback_reasons"]
                }
            )
            both_action_streams_equal = all(
                _actions(control, seat) == _actions(treatment, seat) for seat in (0, 1)
            )
            hard = incident["hard_safety_failures"]
            assert not hard
            assert both_action_streams_equal
            assert control_action == treatment_action
            assert not any(order[:2] == ["BUY_ANIMAL", "COW"] for order in control_action["market"])
            assert not any(order[:2] == ["BUY_ANIMAL", "SHEEP"] for order in treatment_action["market"])
            item.update(
                {
                    "reason_code": "SAFE_CANCEL_PURCHASE_SLOT_ABSENT",
                    "delivery_state": "SAFE_CANCEL",
                    "legacy_diagnostic": unique_fallback_reasons,
                    "legacy_diagnostic_steps": int(
                        row["agent_trace"]["treatment"]["fallback_steps"]
                    ),
                    "legacy_step_count_semantics": (
                        "one reason latched from step248 through step718; not 471 failures"
                    ),
                    "step248_control_action": control_action,
                    "step248_treatment_action": treatment_action,
                    "step248_money": float(
                        treatment_obs["farms"][int(row["seat"])]["money"]
                    ),
                    "step248_field_animals": _animal_counts(
                        treatment_obs, int(row["seat"])
                    ),
                    "all_control_treatment_actions_equal": both_action_streams_equal,
                    "same_terminal_outcome": row["control"] == row["treatment"],
                    "integrity_checks": {
                        "completed_720": bool(row["safety"]["treatment"]["completed_720"]),
                        "runtime_failures": row["safety"]["treatment"]["runtime_failures"],
                        "animal_loss_delta": int(
                            row["safety"]["treatment"]["animal_loss_total"]
                        )
                        - int(row["safety"]["control"]["animal_loss_total"]),
                        "minimum_cash": float(row["safety"]["treatment"]["minimum_cash"]),
                        "transaction_complete": bool(treatment_tx["complete"]),
                        "behavioral_isolation_valid": bool(
                            row["behavioral_isolation_valid"]
                        ),
                    },
                }
            )
        classifications.append(item)

    counts = Counter(row["reason_code"] for row in classifications)
    assert len(requested) == 29
    assert counts == {
        "ACTUAL_INCREMENTAL_COW_TO_SHEEP": 13,
        "ALREADY_SATISFIED_BASELINE_ROUTE_OVERLAP": 8,
        "SAFE_CANCEL_PURCHASE_SLOT_ABSENT": 8,
    }
    return {
        "formal_pairs": len(rows),
        "gate_requests": len(requested),
        "reason_counts": dict(sorted(counts.items())),
        "accounting_identity": "29 = 13 incremental + 8 baseline overlap + 8 safe cancel",
        "all_requests_classified": True,
        "pairs": classifications,
    }


def _fresh_v14_action(obs: dict[str, Any]) -> dict[str, Any]:
    module_name = f"_v14_posthoc_mediator_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, V14_SOURCE)
    if spec is None or spec.loader is None:
        raise ImportError(V14_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "reset_runtime_state"):
        module.reset_runtime_state()
    return module.agent(copy.deepcopy(obs))


def _tile_differences(
    left: dict[str, Any], right: dict[str, Any], seat: int
) -> list[dict[str, Any]]:
    differences = []
    left_tiles = left["farms"][seat]["tiles"]
    right_tiles = right["farms"][seat]["tiles"]
    for y, (left_row, right_row) in enumerate(zip(left_tiles, right_tiles, strict=True)):
        for x, (left_tile, right_tile) in enumerate(zip(left_row, right_row, strict=True)):
            if left_tile != right_tile:
                differences.append(
                    {"x": x, "y": y, "control": left_tile, "treatment": right_tile}
                )
    return differences


def _v14_mediator(row: dict[str, Any]) -> dict[str, Any]:
    control_path = _resolved_artifact(row["replay_artifacts"]["control"])
    treatment_path = _resolved_artifact(row["replay_artifacts"]["treatment"])
    control = _read_gzip_json(control_path)
    treatment = _read_gzip_json(treatment_path)
    audit = audit_pair(control, treatment, int(row["seat"]), gate_requested=True)
    focal = int(row["seat"])
    opponent = 1 - focal
    response_step = int(audit["first_opponent_response_step"])
    control_obs = _step_observation(control, response_step, opponent)
    treatment_obs = _step_observation(treatment, response_step, opponent)
    recorded_control = _step_action(control, response_step, opponent)
    recorded_treatment = _step_action(treatment, response_step, opponent)

    money_restored = copy.deepcopy(treatment_obs)
    money_restored["farms"][focal]["money"] = control_obs["farms"][focal]["money"]
    tiles_restored = copy.deepcopy(treatment_obs)
    tiles_restored["farms"][focal]["tiles"] = copy.deepcopy(
        control_obs["farms"][focal]["tiles"]
    )
    both_restored = copy.deepcopy(tiles_restored)
    both_restored["farms"][focal]["money"] = control_obs["farms"][focal]["money"]
    source_actions = {
        "control_observation": _fresh_v14_action(control_obs),
        "treatment_observation": _fresh_v14_action(treatment_obs),
        "restore_focal_money_only": _fresh_v14_action(money_restored),
        "restore_focal_public_tiles_only": _fresh_v14_action(tiles_restored),
        "restore_money_and_tiles": _fresh_v14_action(both_restored),
    }
    assert source_actions["control_observation"] == recorded_control
    assert source_actions["treatment_observation"] == recorded_treatment
    assert source_actions["restore_focal_money_only"] == recorded_treatment
    assert source_actions["restore_focal_public_tiles_only"] == recorded_control

    tile_differences = _tile_differences(control_obs, treatment_obs, focal)
    assert len(tile_differences) == 2
    for difference in tile_differences:
        left = copy.deepcopy(difference["control"])
        right = copy.deepcopy(difference["treatment"])
        assert left.pop("animal") == "COW"
        assert right.pop("animal") == "SHEEP"
        assert left == right

    first = audit["first_state_divergence"]
    return {
        "lineage_id": row["lineage_id"],
        "seed": row["seed"],
        "focal_seat": focal,
        "opponent_seat": opponent,
        "timeline": {
            "first_self_action_divergence": audit["own_first_divergence_step"],
            "first_self_money_divergence": first["self_money"]["step"],
            "first_self_portfolio_divergence": first["self_portfolio"]["step"],
            "first_opponent_response": response_step,
            "opponent_response_lag": audit["opponent_response_lag"],
            "first_opponent_money_divergence": first["opponent_money"]["step"],
            "first_market_inventory_divergence": first["market_inventory"]["step"],
            "first_price_divergence": first["prices"]["step"],
            "first_money_divergence": {
                "either_farm": min(
                    int(first["self_money"]["step"]),
                    int(first["opponent_money"]["step"]),
                ),
                "self": first["self_money"]["step"],
                "opponent": first["opponent_money"]["step"],
            },
        },
        "opponent_first_response_action": {
            "changed_component": "market",
            "action_type": "BUY_SEED",
            "item": "STRAWBERRY",
            "control_quantity": 2,
            "treatment_quantity": 1,
            "unchanged_market_order": ["BUY_PRODUCT", "WHEAT", 1],
            "farmer_and_hands_unchanged": (
                recorded_control["farmer"] == recorded_treatment["farmer"]
                and recorded_control["hands"] == recorded_treatment["hands"]
            ),
            "control": recorded_control,
            "treatment": recorded_treatment,
        },
        "observation_immediately_before_response": {
            "focal_money": {
                "control": control_obs["farms"][focal]["money"],
                "treatment": treatment_obs["farms"][focal]["money"],
            },
            "focal_field_animals": {
                "control": _animal_counts(control_obs, focal),
                "treatment": _animal_counts(treatment_obs, focal),
            },
            "focal_tile_differences": tile_differences,
            "market_equal": control_obs["market"] == treatment_obs["market"],
            "town_equal": control_obs["town"] == treatment_obs["town"],
            "opponent_private_equal": control_obs["private"] == treatment_obs["private"],
        },
        "source_counterfactual_probe": source_actions,
        "mediator_conclusion": {
            "most_supported_public_mediator": "focal Cow/Sheep field portfolio",
            "money_difference_sufficient": False,
            "public_tile_difference_sufficient_in_one_step_source_probe": True,
            "interpretation": (
                "V14 changed its Strawberry seed purchase after observing the focal "
                "Cow-to-Sheep portfolio. This is second-order policy feedback and "
                "precedes both market-inventory and price divergence."
            ),
            "scope": (
                "Deterministic one-step source-code mediation diagnostic for this pair; "
                "not a population-level effect estimate."
            ),
        },
        "replay_sha256": {
            "control": file_sha256(control_path),
            "treatment": file_sha256(treatment_path),
        },
    }


def build_addendum() -> dict[str, Any]:
    result_sha256 = file_sha256(RESULT)
    if result_sha256 != KNOWN_RESULT_SHA256:
        raise ValueError(f"immutable result hash changed: {result_sha256}")
    if file_sha256(V14_SOURCE) != KNOWN_V14_SHA256:
        raise ValueError("V14 source no longer matches the preregistered Gold source")
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    rows = list(result["pairs"]["formal_promotion"])
    diagnostic_rows = list(result["pairs"]["diagnostic_reproduction"])
    v14_row = next(
        row
        for row in diagnostic_rows
        if row["lineage_id"] == "gold_v14"
        and int(row["seed"]) == 20260901
        and int(row["seat"]) == 1
    )
    assert result["evaluation"]["decision"] == "REJECTED_SAFETY"
    return {
        "format": "kaggriculture-v113-posthoc-e6-and-forensics-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_records": {
            "immutable_formal_result": str(RESULT.relative_to(REPO)).replace("\\", "/"),
            "immutable_formal_result_sha256": result_sha256,
            "preregistration": str(PREREGISTRATION.relative_to(REPO)).replace("\\", "/"),
            "preregistration_sha256": file_sha256(PREREGISTRATION),
            "v14_gold_source": str(V14_SOURCE.relative_to(REPO)).replace("\\", "/"),
            "v14_gold_source_sha256": file_sha256(V14_SOURCE),
        },
        "separated_interpretations": {
            "preregistered_experiment_verdict": {
                "value": "REJECTED_SAFETY",
                "frozen": True,
                "scope": "the 60-pair preregistered V111-vs-V113 gate experiment",
                "changed_by_this_addendum": False,
            },
            "current_research_interpretation": {
                "value": "LIVE_VIABLE / CAUSAL_UNRESOLVED",
                "promotion_claim": False,
                "v113_greater_than_v111_claim": False,
                "cow_to_sheep_gate_success_claim": False,
            },
            "live_ladder_evidence": {
                "evidence_level": "E6_live_ladder_observational",
                "submission_id": 55933145,
                "reported_final_rating_approx": 1675,
                "source_status": "user-provided external evidence",
                "episode_level_reconstruction": "stored separately when collection completes",
                "supports": "Agent-level live viability in the sampled field",
                "does_not_support": (
                    "a causal gate effect, V113>V111, or promotion without paired E3-E5 evidence"
                ),
            },
        },
        "historical_verdict_preservation": (
            "The old evaluator treated candidate-new fallback as a Safety hard-gate "
            "failure. This post-hoc taxonomy does not rewrite that preregistered verdict."
        ),
        "trigger_funnel": _trigger_funnel(rows),
        "future_safety_taxonomy": {
            "hard_safety_failure": {
                "definition": "game-integrity regression",
                "examples": [
                    "runtime error or incomplete game",
                    "illegal/no-op with material harm",
                    "animal loss or weed regression",
                    "negative cash or transaction corruption",
                ],
                "promotion_effect": "fails Engine Correctness / Safety",
            },
            "treatment_delivery_failure": {
                "definition": (
                    "experimental branch is not delivered and baseline continuation is preserved"
                ),
                "examples": [
                    "purchase slot absent at revalidation",
                    "state changed before commit",
                    "already satisfied by baseline route",
                ],
                "promotion_effect": (
                    "reported in trigger funnel and treatment sample; not a catastrophic "
                    "Safety failure when baseline identity and game integrity are verified"
                ),
            },
        },
        "transaction_controller_design": {
            "state_order": ["ARM", "REVALIDATE", "COMMIT", "SAFE_CANCEL"],
            "ARM": (
                "record intent, trigger observation digest, intended delta, and expiry; emit no rewrite"
            ),
            "REVALIDATE": [
                "the exact baseline purchase slot still exists",
                "the route has not already satisfied the animal target",
                "cash reserve and order-slot capacity remain valid",
                "pasture, shed, pickup/place workers, inventory, and horizon remain feasible",
                "no conflicting baseline continuation owns the same slot",
            ],
            "COMMIT": (
                "rewrite only the validated order, then audit purchase, pickup, and placement atomically"
            ),
            "SAFE_CANCEL": (
                "clear intent, emit the byte-equivalent baseline action, record one reason code, "
                "and do not latch a per-turn fallback diagnostic"
            ),
            "reason_code_mapping": {
                "unexpected-late-purchase-action": "SAFE_CANCEL_PURCHASE_SLOT_ABSENT",
                "baseline-already-converts": "SAFE_CANCEL_ALREADY_SATISFIED",
                "state-changed": "SAFE_CANCEL_STATE_CHANGED",
                "cash-or-capacity-invalid": "SAFE_CANCEL_FEASIBILITY_CHANGED",
            },
            "post_commit_partial_or_corrupt_transaction": "HARD_SAFETY_FAILURE",
        },
        "v14_mediator_analysis": _v14_mediator(v14_row),
        "required_future_paired_fields": [
            "first_self_divergence",
            "first_opponent_response",
            "opponent_response_lag",
            "first_market_divergence",
            "first_price_divergence",
            "first_money_divergence",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_addendum()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(rendered, end="")
        return
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"write-once addendum already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
