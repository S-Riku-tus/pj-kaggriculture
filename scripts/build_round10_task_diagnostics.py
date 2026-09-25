from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "round10_public_learning_20260924"


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def joined_rows() -> list[dict[str, object]]:
    labels = load_csv(EXP / "training" / "task_labels" / "task_labels.csv")
    predictions = load_csv(EXP / "training" / "ranker_predictions.csv")
    prediction_by_key = {(row["group_id"], row["seat"], row["candidate_id"]): row for row in predictions}
    rows: list[dict[str, object]] = []
    for row in labels:
        key = (row["group_id"], row["seat"], row["candidate_id"])
        prediction = prediction_by_key[key]
        rows.append(
            {
                "label": row,
                "prediction": prediction,
                "margin_delta": float(row["margin_delta"]),
                "probability": float(prediction["probability"]),
                "positive": int(prediction["label"]) == 1,
                "rule_selected": int(prediction["rule_selected"]) == 1,
            }
        )
    return rows


def render_example(name: str, joined: dict[str, object]) -> dict[str, object]:
    row = joined["label"]
    prediction = joined["prediction"]
    assert isinstance(row, dict)
    assert isinstance(prediction, dict)
    diagnostics = json.loads(row["diagnostics_json"])
    return {
        "name": name,
        "identity": {
            "candidate_id": row["candidate_id"],
            "group_id": row["group_id"],
            "seed": int(row["seed"]),
            "seat": int(row["seat"]),
            "opponent_id": row["opponent_id"],
            "split": prediction["split"],
        },
        "observation_features": json.loads(row["features_json"]),
        "candidate_contract": json.loads(row["contract_json"]),
        "model_scoring": {
            "probability": float(prediction["probability"]),
            "threshold": 0.95,
            "learned_selected": bool(int(prediction["selected"])),
            "rule_selected": bool(int(prediction["rule_selected"])),
            "correction": ("abstain_to_B1" if not int(prediction["selected"]) else "execute_candidate"),
        },
        "forced_teacher_execution": {
            "events": diagnostics["events"],
            "tasks_started": int(row["tasks_started"]),
            "tasks_completed": int(row["tasks_completed"]),
            "contract_failures": int(row["contract_failures"]),
            "remaining_obligations": json.loads(row["remaining_obligations_json"]),
            "prefix_match": bool(int(row["prefix_match"])),
        },
        "terminal_label": {
            "baseline_margin": float(row["baseline_margin"]),
            "treatment_margin": float(row["treatment_margin"]),
            "margin_delta": float(row["margin_delta"]),
            "win_delta": int(row["win_delta"]),
            "future_result_is_training_label_only": True,
        },
        "evidence": {
            "baseline_replay": row["baseline_replay"],
            "treatment_replay": row["treatment_replay"],
            "treatment_replay_sha256": row["treatment_replay_sha256"],
        },
    }


def main() -> None:
    rows = joined_rows()
    best_positive = max((row for row in rows if row["positive"]), key=lambda x: x["margin_delta"])
    highest_scored_negative = max((row for row in rows if not row["positive"]), key=lambda x: x["probability"])
    most_harmful_rule = min((row for row in rows if row["rule_selected"]), key=lambda x: x["margin_delta"])

    fresh = json.loads((EXP / "analysis" / "task_selector_seed_holdout_summary.json").read_text(encoding="utf-8"))
    learned_groups = [row for row in fresh["groups"] if row["arm"] == "learned_selector"]
    learned_fresh = {
        "games": sum(row["games"] for row in learned_groups),
        "model_loaded_games": sum(row["model_loaded_games"] for row in learned_groups),
        "model_calls": sum(row["model_calls"] for row in learned_groups),
        "model_selected_tasks": sum(row["model_selected_tasks"] for row in learned_groups),
        "model_changed_final_actions": sum(row["model_changed_final_actions"] for row in learned_groups),
        "contract_failures": sum(row["contract_failures"] for row in learned_groups),
        "conclusion": "model loaded and scored candidates, but abstained in every fresh game",
    }

    payload = {
        "pipeline": [
            "observation",
            "candidate_contract",
            "model_score",
            "threshold_correction",
            "actual_execution",
            "completion_check",
            "terminal_training_label",
        ],
        "information_boundary": {
            "features": "current public observation, own executed state/history, and candidate specification",
            "excluded_from_agent": [
                "opponent private state",
                "future shop sequence",
                "future opponent actions",
                "terminal fork label",
            ],
            "oracle": "terminal labels are diagnostic/training data only",
        },
        "examples": [
            render_example("largest_positive_teacher_fork", best_positive),
            render_example("highest_scored_negative", highest_scored_negative),
            render_example("most_harmful_rule_selected_fork", most_harmful_rule),
        ],
        "fresh_interactive_evaluation": learned_fresh,
        "honest_status": (
            "learning contribution not established because the learned selector "
            "changed zero fresh actions"
        ),
    }
    destination = EXP / "analysis" / "task_diagnostic_examples.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
