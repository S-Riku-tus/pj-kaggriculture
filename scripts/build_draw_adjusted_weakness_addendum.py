"""Create non-destructive weakness maps with draw-adjusted classification."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_v111_v113_expanded import build_weakness_map  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render(payload: dict[str, Any]) -> str:
    correction = payload["correction_addendum"]
    lines = [
        "# Draw-adjusted V111/V113 Weakness Map addendum",
        "",
        "The immutable experiment result and its original generated Weakness Map are unchanged.",
        "This addendum corrects only weakness-family classification: draws count as 0.5, so an",
        "all-draw calibration matchup is not mislabeled as a 0% opponent win rate.",
        "",
        f"Source result SHA-256: `{correction['source_result_sha256']}`.",
        "",
        "Close 30–70% score families: "
        f"`{payload['close_matchup_family_ids_30_to_70']}`",
        f"Below-50% score families: `{payload['below_50_family_ids']}`",
        "",
        "| Family | V111 strict WR | V111 score | V113 strict WR | V113 score | Priority |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in payload["families"]:
        strict = row["strict_win_probability_diagnostic"]
        score = row["draw_adjusted_win_score"]
        lines.append(
            "| {family} | {v111_wr:.1%} | {v111_score:.1%} | {v113_wr:.1%} | "
            "{v113_score:.1%} | {priority} |".format(
                family=row["behavior_family_id"],
                v111_wr=strict["v111"],
                v111_score=score["v111"],
                v113_wr=strict["v113"],
                v113_score=score["v113"],
                priority=row["priority_class"],
            )
        )
    lines.extend(
        [
            "",
            "Classification is diagnostic E3 evidence. It does not authorize a Best Response,",
            "V114 implementation, promotion, or Fresh Holdout claim.",
            "",
        ]
    )
    return "\n".join(lines)


def build(result_path: Path) -> dict[str, Any]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    payload = build_weakness_map(result)
    payload["format"] = "kaggriculture-draw-adjusted-weakness-map-addendum-v1"
    payload["correction_addendum"] = {
        "non_destructive": True,
        "source_result": str(result_path.resolve()),
        "source_result_sha256": _sha(result_path),
        "reason": (
            "The original generated map classified weakness from strict wins and therefore "
            "misread draw-heavy calibration as sub-50%. This addendum uses win=1, draw=0.5, loss=0."
        ),
        "immutable_experiment_result_modified": False,
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_dirs", nargs="+")
    args = parser.parse_args()
    outputs = []
    for value in args.result_dirs:
        result_dir = Path(value).resolve()
        result_path = result_dir / "experiment_result.json"
        payload = build(result_path)
        json_path = result_dir / "weakness_map_draw_adjusted_addendum.json"
        report_path = result_dir / "weakness_map_draw_adjusted_addendum.md"
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        report_path.write_text(_render(payload), encoding="utf-8")
        outputs.append(
            {
                "result": str(result_path),
                "output": str(json_path),
                "output_sha256": _sha(json_path),
                "close_matchup_family_ids": payload[
                    "close_matchup_family_ids_30_to_70"
                ],
                "below_50_family_ids": payload["below_50_family_ids"],
            }
        )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
