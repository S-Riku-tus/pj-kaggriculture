"""Compare the active public submission's factual actions with local agents.

This is a read-only E1 fidelity audit on downloaded public replay observations.
It cannot authenticate the remote archive and must not be used as a paired
counterfactual evaluation.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluation.replay import action, canonical_action, observation  # noqa: E402
from scripts.evaluation.runner import _call, _import_module  # noqa: E402

DATA = ROOT / "data/current_field_20260915"
SUBMISSION = DATA / "submissions/current_our_20260915_submission_56089444"
OUT = ROOT / "data/analysis/research_20260916_next_strategy/current_submission_fidelity.json"
VERSIONS = ("v109", "v110", "v111", "v113")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def field_part(value: dict[str, Any]) -> tuple[Any, Any]:
    return value.get("farmer"), value.get("hands")


def market_part(value: dict[str, Any]) -> Any:
    return value.get("market")


def market_multiset(value: dict[str, Any]) -> Counter[tuple[Any, ...]]:
    return Counter(tuple(order) for order in (value.get("market") or []))


def main() -> None:
    with (SUBMISSION / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    results: list[dict[str, Any]] = []
    for source in manifest:
        replay_path = DATA / source["replay_path"]
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        seat = int(source["submission_seat"])
        for version in VERSIONS:
            module_path = ROOT / f"agents/{version}/main.py"
            module = _import_module(module_path, f"fidelity_{version}")
            mismatch_steps: list[int] = []
            field_mismatch_steps: list[int] = []
            market_mismatch_steps: list[int] = []
            market_multiset_mismatch_steps: list[int] = []
            mismatch_ops: Counter[str] = Counter()
            errors: list[dict[str, Any]] = []
            examples: list[dict[str, Any]] = []
            for step in range(719):
                expected = action(replay, step, seat)
                try:
                    emitted = _call(module.agent, observation(replay, step, seat), None)
                except Exception as exc:
                    errors.append({"step": step, "type": type(exc).__name__, "message": str(exc)})
                    break
                if canonical_action(emitted) == canonical_action(expected):
                    continue
                mismatch_steps.append(step)
                if field_part(emitted) != field_part(expected):
                    field_mismatch_steps.append(step)
                if market_part(emitted) != market_part(expected):
                    market_mismatch_steps.append(step)
                if market_multiset(emitted) != market_multiset(expected):
                    market_multiset_mismatch_steps.append(step)
                farmer = emitted.get("farmer") or ["PASS"]
                mismatch_ops[str(farmer[0] if farmer else "PASS")] += 1
                if len(examples) < 8:
                    examples.append({"step": step, "remote": expected, "local": emitted})
            results.append(
                {
                    "episode_id": int(source["episode_id"]),
                    "seat": seat,
                    "remote_submission_id": 56089444,
                    "opponent_team": source["opponent_team_name"],
                    "remote_result": source["result"],
                    "version": version,
                    "local_source_sha256": sha256(module_path),
                    "replay_sha256": sha256(replay_path),
                    "matching_actions": None if errors else 719 - len(mismatch_steps),
                    "mismatch_count": None if errors else len(mismatch_steps),
                    "first_mismatch": mismatch_steps[0] if mismatch_steps else None,
                    "field_mismatch_count": len(field_mismatch_steps),
                    "market_mismatch_count": len(market_mismatch_steps),
                    "market_multiset_mismatch_count": len(market_multiset_mismatch_steps),
                    "mismatch_farmer_ops": dict(mismatch_ops),
                    "mismatch_steps": mismatch_steps,
                    "examples": examples,
                    "errors": errors,
                }
            )

    by_version = {}
    for version in VERSIONS:
        rows = [row for row in results if row["version"] == version]
        by_version[version] = {
            "episodes": len(rows),
            "exact_episode_matches": sum(row["mismatch_count"] == 0 for row in rows),
            "total_matching_actions": sum(int(row["matching_actions"] or 0) for row in rows),
            "total_actions": 719 * len(rows),
            "matching_share": (
                sum(int(row["matching_actions"] or 0) for row in rows) / (719 * len(rows)) if rows else None
            ),
            "first_mismatch_by_episode": {
                str(row["episode_id"]): row["first_mismatch"] for row in rows
            },
            "error_episodes": sum(bool(row["errors"]) for row in rows),
            "field_or_hands_mismatches": sum(row["field_mismatch_count"] for row in rows),
            "ordered_market_mismatches": sum(row["market_mismatch_count"] for row in rows),
            "market_multiset_mismatches": sum(
                row["market_multiset_mismatch_count"] for row in rows
            ),
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "evidence_level": "E1_FACTUAL_OBSERVATION_ACTION_FIDELITY",
                "remote_submission_id": 56089444,
                "remote_archive_identity": "UNVERIFIED",
                "interpretation": (
                    "A high action match makes a close relative plausible but cannot authenticate the remote package "
                    "or establish closed-loop equivalence."
                ),
                "by_version": by_version,
                "contexts": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(by_version, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
