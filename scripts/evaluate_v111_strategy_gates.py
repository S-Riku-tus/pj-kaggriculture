"""Evaluate V111 strategy gates without using old-agent win rate for selection."""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v111 import main as v111  # noqa: E402
from scripts.train_v111_strategy import _features, _observation, _predict  # noqa: E402

ROWS = ROOT / "data/analysis/v111_strategy_rows.jsonl"
MODEL = ROOT / "agents/v111/strategy_model.json"
V110 = ROOT / "data/submissions/v110_submission_55903573"
OUTPUT = ROOT / "data/analysis/v111_strategy_gate_audit.json"


def _teacher_rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in ROWS.read_text(encoding="utf-8").splitlines() if line]


def _gate_summary(
    rows: list[dict[str, Any]],
    model: dict[str, Any],
    protocol: str,
    split: str,
    step: int,
    shop_match: Callable[[list[str]], bool],
    prediction_match: Callable[[float], bool],
    target_match: Callable[[float], bool],
) -> dict[str, Any]:
    eligible = []
    active = []
    for row in rows:
        if row[f"{protocol}_split"] != split or int(row["step"]) != step:
            continue
        if not shop_match([str(value) for value in row.get("shops") or []]):
            continue
        prediction, max_z = _predict(model, row["features"])
        predicted_tilt = float(prediction[-1] - prediction[-2])
        actual_tilt = float(row["targets"]["72"][-1] - row["targets"]["72"][-2])
        record = {
            "source": row["source"],
            "episode_id": row["episode_id"],
            "predicted_tilt": predicted_tilt,
            "actual_tilt": actual_tilt,
            "max_abs_z": max_z,
        }
        eligible.append(record)
        if max_z <= v111.OOD_MAX_ABS_Z and prediction_match(predicted_tilt):
            active.append(record)
    return {
        "eligible": len(eligible),
        "active": len(active),
        "correct": sum(target_match(float(row["actual_tilt"])) for row in active),
        "precision": (
            mean(target_match(float(row["actual_tilt"])) for row in active) if active else None
        ),
        "mean_actual_tilt": mean(float(row["actual_tilt"]) for row in active) if active else None,
        "active_sources": dict(Counter(str(row["source"]) for row in active)),
    }


def _manifest() -> list[dict[str, str]]:
    with (V110 / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _replay_path(row: dict[str, str]) -> Path:
    direct = ROOT / str(row["replay_path"])
    return direct if direct.is_file() else ROOT / "data" / str(row["replay_path"])


def _v110_observational_audit(model: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for manifest in _manifest():
        replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        seat = int(manifest["submission_seat"])
        for gate, step in (("second-yarn-veto", 153), ("third-yarn-conversion", 216)):
            obs = _observation(replay, step, seat)
            if obs is None:
                continue
            features = _features(obs, seat, step)
            if features is None:
                continue
            prediction, max_z = _predict(model, features)
            tilt = float(prediction[-1] - prediction[-2])
            shops = [str(value) for value in ((obs.get("town") or {}).get("unlocked_shops") or [])]
            active = False
            if gate == "second-yarn-veto":
                active = bool(
                    len(shops) >= 2
                    and shops[0] != "YARN_STORE"
                    and shops[1] == "YARN_STORE"
                    and tilt <= v111.SECOND_YARN_MILK_VETO
                    and max_z <= v111.OOD_MAX_ABS_Z
                )
            else:
                active = bool(
                    len(shops) >= 3
                    and shops[2] == "YARN_STORE"
                    and "YARN_STORE" not in shops[:2]
                    and tilt >= v111.THIRD_YARN_WOOL_GATE
                    and max_z <= v111.OOD_MAX_ABS_Z
                )
            if active:
                rows.append(
                    {
                        "gate": gate,
                        "episode_id": manifest["episode_id"],
                        "recorded_result": manifest["result"],
                        "recorded_margin": float(manifest["own_reward"])
                        - float(manifest["opponent_reward"]),
                        "shops": shops,
                        "predicted_tilt": tilt,
                        "max_abs_z": max_z,
                    }
                )
    return {
        "active_rows": len(rows),
        "active_episodes": len({row["episode_id"] for row in rows}),
        "by_gate": dict(Counter(row["gate"] for row in rows)),
        "by_recorded_result": dict(Counter(row["recorded_result"] for row in rows)),
        "interpretation": (
            "activation coverage only; these V110 outcomes did not select thresholds and are not "
            "counterfactual V111 scores"
        ),
        "records": rows,
    }


def main() -> None:
    rows = _teacher_rows()
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    gates = {
        "second_yarn_milk_veto": {
            "step": 153,
            "threshold": v111.SECOND_YARN_MILK_VETO,
            "runtime_enabled": v111.ENABLE_SECOND_YARN_VETO,
            "selection": "rejected: episode and action-lineage validation disagree",
            "meaning": "select the still-prefix-compatible default route",
            "metrics": {},
        },
        "third_yarn_wool_conversion": {
            "step": 216,
            "threshold": v111.THIRD_YARN_WOOL_GATE,
            "runtime_enabled": True,
            "selection": "retained: direction reproduced on both held-out protocols",
            "meaning": "convert only the final planned two Cow to Sheep",
            "metrics": {},
        },
    }
    for protocol in ("episode", "lineage"):
        for split in ("train", "validation", "test"):
            gates["second_yarn_milk_veto"]["metrics"][f"{protocol}_{split}"] = _gate_summary(
                rows,
                model,
                protocol,
                split,
                153,
                lambda shops: len(shops) >= 2
                and shops[0] != "YARN_STORE"
                and shops[1] == "YARN_STORE",
                lambda tilt: tilt <= v111.SECOND_YARN_MILK_VETO,
                lambda tilt: tilt < 0,
            )
            gates["third_yarn_wool_conversion"]["metrics"][f"{protocol}_{split}"] = (
                _gate_summary(
                    rows,
                    model,
                    protocol,
                    split,
                    216,
                    lambda shops: len(shops) >= 3
                    and shops[2] == "YARN_STORE"
                    and "YARN_STORE" not in shops[:2],
                    lambda tilt: tilt >= v111.THIRD_YARN_WOOL_GATE,
                    lambda tilt: tilt >= 2,
                )
            )
    result = {
        "format": "kaggriculture-v111-strategy-gate-audit-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "teacher_rows": len(rows),
        "selection_rule": "thresholds frozen without candidate-vs-opponent score optimization",
        "ood_max_abs_z": v111.OOD_MAX_ABS_Z,
        "gates": gates,
        "v110_observational_coverage": _v110_observational_audit(model),
        "limitations": [
            "teacher gate cohorts are small",
            "portfolio-direction precision is not a causal score estimate",
            "V110 replay outcomes are coverage labels, not V111 counterfactual outcomes",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"gates": gates, "v110": result["v110_observational_coverage"]}, ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
