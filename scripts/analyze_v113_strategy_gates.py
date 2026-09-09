"""External validation of V111's animal goal on the 2026-09-01 top corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v111 import main as v111  # noqa: E402
from scripts import train_v111_strategy as trainer  # noqa: E402

SOURCES = {
    "top1": (55905066, "leaderboard_20260831_rank1_tetsuya_submission_55905066"),
    "top2": (55865730, "leaderboard_20260831_rank2_yusuke_hayashi_submission_55865730"),
    "top3": (55867591, "leaderboard_20260831_rank3_mtn_submission_55867591"),
}
STEP = 216
HORIZON = 72


def _episode_rows(name: str) -> dict[int, dict[str, Any]]:
    path = ROOT / "data/submissions" / name / "episode_service_response.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        int(row["id"]): row
        for row in payload.get("episodes", [])
        if isinstance(row, dict) and str(row.get("id", "")).isdigit()
    }


def _seat(row: dict[str, Any], submission_id: int) -> int | None:
    for position, agent in enumerate((row.get("agents") or [])[:2]):
        if isinstance(agent, dict) and int(agent.get("submissionId") or -1) == submission_id:
            return int(agent.get("index", position) or 0)
    return None


def _hash(replay: dict[str, Any], seat: int) -> str:
    digest = hashlib.sha1()
    for step in range(200):
        action = trainer._action(replay, step, seat)
        digest.update(json.dumps(action, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()[:16]


def _residual_score(obs: dict[str, Any], seat: int) -> float:
    farms = obs.get("farms") or []
    own = trainer._portfolio(farms[seat])
    opponent = trainer._portfolio(farms[1 - seat])
    shops = [str(shop) for shop in ((obs.get("town") or {}).get("unlocked_shops") or [])]
    days = HORIZON / 24.0
    milk_demand = trainer._demand_per_day(shops, "MILK") * days
    wool_demand = trainer._demand_per_day(shops, "WOOL") * days
    # Established animals produce roughly every two/three days.  This is a
    # deliberately small, public-state capacity forecast rather than a hidden
    # inventory label.
    milk_supply = (own["COW"] + opponent["COW"]) * days / 2.0
    wool_supply = (own["SHEEP"] + opponent["SHEEP"]) * days / 3.0
    return (wool_demand - wool_supply) / trainer.MARKET_SCALE["WOOL"] - (
        milk_demand - milk_supply
    ) / trainer.MARKET_SCALE["MILK"]


def _rows() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for label, (submission_id, name) in SOURCES.items():
        episode_rows = _episode_rows(name)
        replay_dir = ROOT / "data/replays" / name
        for path in sorted(replay_dir.glob("episode_*.json")):
            episode_id = int(path.stem.removeprefix("episode_"))
            episode_row = episode_rows.get(episode_id)
            if episode_row is None:
                continue
            seat = _seat(episode_row, submission_id)
            if seat not in (0, 1):
                continue
            replay = json.loads(path.read_text(encoding="utf-8"))
            before = trainer._observation(replay, STEP, seat)
            after = trainer._observation(replay, STEP + HORIZON, seat)
            if before is None or after is None:
                continue
            features = trainer._features(before, seat, STEP)
            if features is None:
                continue
            predicted = v111._predict_72(before)
            if predicted is None:
                continue
            prediction, max_z = predicted
            own_before = trainer._portfolio((before.get("farms") or [])[seat])
            own_after = trainer._portfolio((after.get("farms") or [])[seat])
            actual_cow = own_after["COW"] - own_before["COW"]
            actual_sheep = own_after["SHEEP"] - own_before["SHEEP"]
            shops = [str(shop) for shop in ((before.get("town") or {}).get("unlocked_shops") or [])]
            result.append(
                {
                    "label": label,
                    "source_name": name,
                    "episode_id": episode_id,
                    "seat": seat,
                    "replay_path": str(path.relative_to(ROOT)),
                    "lineage": _hash(replay, seat),
                    "shops": shops,
                    "predicted_tilt": float(prediction[-1] - prediction[-2]),
                    "actual_tilt": float(actual_sheep - actual_cow),
                    "actual_cow_delta": actual_cow,
                    "actual_sheep_delta": actual_sheep,
                    "max_abs_z": max_z,
                    "residual_score": _residual_score(before, seat),
                }
            )
    return result


def _gate(rows: list[dict[str, Any]], predicate) -> dict[str, Any]:
    selected = [row for row in rows if predicate(row)]
    material = [row for row in selected if abs(row["actual_tilt"]) >= 1.0]
    no_material = [row for row in selected if abs(row["actual_tilt"]) < 1.0]
    correct = [row for row in material if row["actual_tilt"] > 0]
    lineage_counts = Counter(str(row["lineage"]) for row in selected)
    no_material_lineages = Counter(str(row["lineage"]) for row in no_material)
    return {
        "active": len(selected),
        "total_rows": len(rows),
        "coverage": len(selected) / len(rows) if rows else None,
        "material": len(material),
        "no_material": len(no_material),
        "material_rate_given_trigger": len(material) / len(selected) if selected else None,
        "correct_sheep_direction": len(correct),
        "precision_on_material": len(correct) / len(material) if material else None,
        "conditional_accuracy_scope": (
            "P(Sheep direction | trigger and observed material Cow/Sheep change); "
            "not causal policy value and not accuracy over all triggers"
        ),
        "mean_actual_tilt": mean(row["actual_tilt"] for row in selected) if selected else None,
        "labels": dict(Counter(row["label"] for row in selected)),
        "distinct_lineages": len({row["lineage"] for row in selected}),
        "lineage_distribution": dict(lineage_counts.most_common()),
        "no_material_characterization": {
            "count": len(no_material),
            "exact_zero_tilt": sum(float(row["actual_tilt"]) == 0.0 for row in no_material),
            "labels": dict(Counter(str(row["label"]) for row in no_material)),
            "distinct_lineages": len(no_material_lineages),
            "lineage_distribution": dict(no_material_lineages.most_common()),
            "mean_cow_delta": (
                mean(float(row["actual_cow_delta"]) for row in no_material)
                if no_material
                else None
            ),
            "mean_sheep_delta": (
                mean(float(row["actual_sheep_delta"]) for row in no_material)
                if no_material
                else None
            ),
            "episode_ids": [int(row["episode_id"]) for row in no_material],
        },
    }


def _lineage_direction_accuracy(rows: list[dict[str, Any]]) -> float | None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if abs(row["actual_tilt"]) >= 1.0:
            groups[row["lineage"]].append(row)
    scores = []
    for group in groups.values():
        scores.append(
            mean(
                (row["predicted_tilt"] > 0) == (row["actual_tilt"] > 0)
                for row in group
            )
        )
    return mean(scores) if scores else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v113_strategy_gate_audit.json"),
    )
    args = parser.parse_args()
    rows = _rows()
    in_support = [row for row in rows if row["max_abs_z"] <= v111.OOD_MAX_ABS_Z]
    def third_yarn(row: dict[str, Any]) -> bool:
        return (
            len(row["shops"]) >= 3
            and row["shops"][2] == "YARN_STORE"
            and "YARN_STORE" not in row["shops"][:2]
        )
    payload = {
        "format": "kaggriculture-v113-strategy-gate-audit-v1",
        "step": STEP,
        "horizon": HORIZON,
        "rows": len(rows),
        "in_support": len(in_support),
        "material_direction_accuracy": {
            "episode_weighted": mean(
                (row["predicted_tilt"] > 0) == (row["actual_tilt"] > 0)
                for row in in_support
                if abs(row["actual_tilt"]) >= 1.0
            ),
            "lineage_weighted": _lineage_direction_accuracy(in_support),
        },
        "gates": {
            "v111_third_yarn": _gate(
                rows,
                lambda row: row["max_abs_z"] <= 4.0
                and third_yarn(row)
                and row["predicted_tilt"] >= 2.0,
            ),
            "model_only_2": _gate(
                rows,
                lambda row: row["max_abs_z"] <= 4.0 and row["predicted_tilt"] >= 2.0,
            ),
            "model_only_1_5": _gate(
                rows,
                lambda row: row["max_abs_z"] <= 4.0 and row["predicted_tilt"] >= 1.5,
            ),
            "model_1_residual_positive": _gate(
                rows,
                lambda row: row["max_abs_z"] <= 4.0
                and row["predicted_tilt"] >= 1.0
                and row["residual_score"] > 0.0,
            ),
        },
        "residual_thresholds": {
            str(threshold): _gate(
                rows,
                lambda row, threshold=threshold: row["max_abs_z"] <= 4.0
                and row["predicted_tilt"] >= 1.0
                and row["residual_score"] >= threshold,
            )
            for threshold in (-0.1, -0.05, 0.0, 0.05, 0.1, 0.15, 0.2)
        },
        "rows_detail": rows,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"rows: {len(rows)}")
    print(f"in_support: {len(in_support)}")
    print(json.dumps(payload["material_direction_accuracy"], indent=2))
    print(json.dumps(payload["gates"], indent=2))
    print(f"report: {output}")


if __name__ == "__main__":
    main()
