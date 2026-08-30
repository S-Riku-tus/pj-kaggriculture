"""Check when V68's uncertainty gate changes an existing V63 trajectory."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v68 import main as v68  # noqa: E402
from scripts.train_v12_relative_policy import _observation  # noqa: E402

OUTPUT = ROOT / "data/analysis/v69_v68_equivalence.json"
GROUPS = {
    "v14_calibration": ROOT / "data/runs/v62_phase_late_v14_20265821.json",
    "v14_holdout": ROOT / "data/runs/v63_phase_late_v14_holdout_20265831.json",
    "v18_diagnostic": ROOT / "data/runs/v63_phase_late_v18_20265841.json",
    "v18_holdout_ungated": ROOT
    / "data/runs/v63_phase_late_v18_holdout_20265851.json",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _replay(game: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(game["replay"]))
    if not path.is_absolute():
        path = ROOT / path
    return _load(path)


def _group(path: Path) -> dict[str, Any]:
    payload = _load(path)
    rows = []
    for game in payload["games"]:
        replay = _replay(game)
        for day in (11, 12):
            obs = _observation(replay, day * 24, int(game["seat"]))
            if obs is None:
                continue
            safe = v68.base._safe_observation(obs)
            if safe is None:
                continue
            ungated = v68.v67._ROLE_PREDICT(obs, safe[0], safe[1])
            gated = v68.v67._relative_predict(obs, safe[0], safe[1])
            rows.append(
                {
                    "seed": int(game["seed"]),
                    "seat": int(game["seat"]),
                    "day": day,
                    "ungated_active": bool(ungated.get("active")),
                    "gated_active": bool(gated.get("active")),
                    "ungated_reason": str(ungated.get("reason")),
                    "gated_reason": str(gated.get("reason")),
                    "money_gap_improvement": gated.get("money_gap_improvement"),
                }
            )
    rejected = [
        row for row in rows if row["ungated_active"] and not row["gated_active"]
    ]
    return {
        "games": len(payload["games"]),
        "episode_days": len(rows),
        "ungated_active_days": sum(row["ungated_active"] for row in rows),
        "gated_active_days": sum(row["gated_active"] for row in rows),
        "newly_rejected_days": len(rejected),
        "trajectory_equivalent_by_induction": not rejected,
        "rejected": rejected,
        "rows": rows,
    }


def main() -> None:
    groups = {name: _group(path) for name, path in GROUPS.items()}
    payload = {
        "format": "kaggriculture-v69-v68-equivalence-v1",
        "runtime_policy_enabled": False,
        "tolerance": v68.MAX_PREDICTED_MONEY_GAP_DECLINE,
        "groups": groups,
        "interpretation": (
            "if no previously active day is rejected, identical state and deterministic "
            "policy imply the V68 trajectory equals the stored V63 trajectory by induction"
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                name: {
                    key: value[key]
                    for key in (
                        "games",
                        "ungated_active_days",
                        "gated_active_days",
                        "newly_rejected_days",
                        "trajectory_equivalent_by_induction",
                    )
                }
                for name, value in groups.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
