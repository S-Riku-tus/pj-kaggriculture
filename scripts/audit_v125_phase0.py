"""Freeze V124/engine provenance and compare the packaged policy to live actions.

This is a factual replay audit.  Exact action agreement can establish behavioral
consistency on the recorded observations, but it cannot authenticate the bytes
that Kaggle executed.  The output says so explicitly.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.metadata
import importlib.util
import json
import platform
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluation.replay import action, canonical_action, observation  # noqa: E402

DEFAULT_OUT = ROOT / "experiments/research_20260920_v125/phase0_manifest.json"
SUBMISSIONS = (56357320, 56360233)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace"
    ).strip()


def _import_agent(path: Path, role: str) -> Any:
    name = f"_v125_phase0_{role}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "reset_runtime_state"):
        module.reset_runtime_state()
    return module


def _replay_path(submission_id: int, episode_id: int) -> Path:
    return (
        ROOT
        / f"data/submissions/v124_submission_{submission_id}/episodes/{episode_id}/replay"
        / f"episode_{episode_id}.json"
    )


def _episode_rows(submission_id: int) -> list[dict[str, str]]:
    path = ROOT / f"data/submissions/v124_submission_{submission_id}/episodes.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _target_seats(row: dict[str, str], submission_id: int) -> list[int]:
    return [
        seat
        for seat in (0, 1)
        if int(row.get(f"agent_{seat}_submission_id") or -1) == submission_id
    ]


def _fidelity_context(agent_main: Path, submission_id: int, row: dict[str, str], seat: int) -> dict[str, Any]:
    episode_id = int(row["episode_id"])
    replay_path = _replay_path(submission_id, episode_id)
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    module = _import_agent(agent_main, f"{submission_id}_{episode_id}_{seat}")
    mismatches: list[int] = []
    examples: list[dict[str, Any]] = []
    emitted_digest = hashlib.sha256()
    recorded_digest = hashlib.sha256()
    decisions = max(0, len(replay.get("steps") or []) - 1)
    for step in range(decisions):
        obs = observation(replay, step, seat)
        expected = action(replay, step, seat)
        emitted = module.agent(obs, replay.get("configuration"))
        expected_key = canonical_action(expected)
        emitted_key = canonical_action(emitted)
        emitted_digest.update(emitted_key.encode("utf-8") + b"\n")
        recorded_digest.update(expected_key.encode("utf-8") + b"\n")
        if emitted_key != expected_key:
            mismatches.append(step)
            if len(examples) < 5:
                examples.append({"step": step, "recorded": expected, "local": emitted})
    info = replay.get("info") or {}
    return {
        "submission_id": submission_id,
        "episode_id": episode_id,
        "episode_type": row.get("episode_type"),
        "seat": seat,
        "recorded_module_version": info.get("ModuleVersion"),
        "recorded_seed_analysis_only": info.get("seed"),
        "replay_sha256": _sha256(replay_path),
        "decisions": decisions,
        "exact_matches": decisions - len(mismatches),
        "mismatch_count": len(mismatches),
        "first_mismatch": mismatches[0] if mismatches else None,
        "recorded_action_sha256": recorded_digest.hexdigest(),
        "local_action_sha256": emitted_digest.hexdigest(),
        "examples": examples,
    }


def _package_members(archive: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            if not member.isfile():
                continue
            stream = handle.extractfile(member)
            payload = b"" if stream is None else stream.read()
            rows.append(
                {
                    "name": member.name,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    return sorted(rows, key=lambda value: value["name"])


def _model_structure() -> dict[str, Any]:
    with gzip.open(ROOT / "agents/v120/model.json.gz", "rt", encoding="utf-8") as stream:
        opening = json.load(stream)
    strawberry_steps = []
    for step, rows in enumerate(opening.get("steps") or []):
        if any(
            any(
                isinstance(unit_action, list)
                and unit_action[:2] == ["PLANT", "STRAWBERRY"]
                for unit_action in [
                    (row[2] or {}).get("farmer"),
                    *((row[2] or {}).get("hands") or []),
                ]
            )
            for row in rows
        ):
            strawberry_steps.append(step)

    with gzip.open(ROOT / "agents/v124/policy_model.json.gz", "rt", encoding="utf-8") as stream:
        continuation = json.load(stream)
    expansion_sources: set[int] = set()
    tomato_steps: list[int] = []
    buy_land_steps: list[int] = []
    for step, rows in enumerate(continuation.get("steps") or []):
        for row in rows:
            if int(row[3]) == 1:
                expansion_sources.add(int(row[1]))
            emitted = row[5] or {}
            unit_actions = [emitted.get("farmer"), *(emitted.get("hands") or [])]
            if any(value and value[:2] == ["PLANT", "TOMATO"] for value in unit_actions):
                tomato_steps.append(step)
            if any(value and value[0] == "BUY_LAND" for value in (emitted.get("market") or [])):
                buy_land_steps.append(step)
    return {
        "opening_case_count": sum(len(rows) for rows in opening.get("steps") or []),
        "first_available_strawberry_plant_step": min(strawberry_steps) if strawberry_steps else None,
        "first_available_strawberry_plant_day": min(strawberry_steps) // 24 if strawberry_steps else None,
        "continuation_sources_at_step_288": len(
            {int(row[1]) for row in continuation["steps"][288]}
        ),
        "expansion_source_count": len(expansion_sources),
        "first_model_buy_land_step": min(buy_land_steps) if buy_land_steps else None,
        "first_model_tomato_plant_step": min(tomato_steps) if tomato_steps else None,
        "router_opening_end_step": 288,
        "router_expansion_gate_step": 432,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--scope",
        choices=("validation", "all"),
        default="validation",
        help="validation audits both self-play seats; all audits every target perspective",
    )
    args = parser.parse_args()

    archive = ROOT / "artifacts/submissions/v124.tar.gz"
    engine_path = (
        ROOT
        / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
    )
    spec_path = engine_path.with_name("kaggriculture.json")
    fixed_files = [
        ROOT / "agents/v124/main.py",
        ROOT / "agents/v124/policy_model.json.gz",
        ROOT / "agents/v124/opponent_sell_model.json",
        ROOT / "agents/v120/model.json.gz",
        archive,
        engine_path,
        spec_path,
        ROOT / "artifacts/v125_analysis_package_20260920/v125_analysis_package/REPORT_JA.md",
        ROOT / "artifacts/v125_analysis_package_20260920/v125_analysis_package/MANIFEST_SHA256.json",
    ]

    contexts: list[dict[str, Any]] = []
    episode_inventory: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="v125_phase0_") as raw:
        extract = Path(raw)
        with tarfile.open(archive, "r:gz") as handle:
            handle.extractall(extract, filter="data")
        agent_main = extract / "main.py"
        for submission_id in SUBMISSIONS:
            rows = _episode_rows(submission_id)
            selected = [
                row
                for row in rows
                if args.scope == "all" or row.get("episode_type") == "EPISODE_TYPE_VALIDATION"
            ]
            episode_inventory[str(submission_id)] = {
                "episodes": len(rows),
                "public_episodes": sum(row.get("episode_type") == "EPISODE_TYPE_PUBLIC" for row in rows),
                "validation_episodes": sum(
                    row.get("episode_type") == "EPISODE_TYPE_VALIDATION" for row in rows
                ),
                "episode_ids": [int(row["episode_id"]) for row in rows],
                "opponent_submission_ids": sorted(
                    {
                        int(row[f"agent_{1 - seat}_submission_id"])
                        for row in rows
                        for seat in _target_seats(row, submission_id)
                        if int(row[f"agent_{1 - seat}_submission_id"] or -1) != submission_id
                    }
                ),
            }
            for row in selected:
                for seat in _target_seats(row, submission_id):
                    contexts.append(_fidelity_context(agent_main, submission_id, row, seat))

    by_submission = {}
    for submission_id in SUBMISSIONS:
        rows = [value for value in contexts if value["submission_id"] == submission_id]
        by_submission[str(submission_id)] = {
            "contexts": len(rows),
            "decisions": sum(value["decisions"] for value in rows),
            "exact_matches": sum(value["exact_matches"] for value in rows),
            "mismatches": sum(value["mismatch_count"] for value in rows),
            "exact_contexts": sum(value["mismatch_count"] == 0 for value in rows),
        }

    payload = {
        "format": "kaggriculture-v125-phase0-audit-v1",
        "evidence": "recorded-observation action fidelity; not remote archive authentication",
        "remote_binary_identity": "UNVERIFIED_NO_REMOTE_ARCHIVE_BYTES",
        "submission_binary_conclusion": (
            "The two submissions are behaviorally compared with the frozen local archive below. "
            "A shared Git commit or exact replay action agreement is not a byte hash."
        ),
        "git": {
            "commit": _git("rev-parse", "HEAD"),
            "branch": _git("branch", "--show-current"),
            "status_porcelain": _git("status", "--porcelain=v1", "--untracked-files=normal").splitlines(),
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "kaggle_environments": importlib.metadata.version("kaggle-environments"),
        },
        "fixed_files": [
            {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": _sha256(path)}
            for path in fixed_files
        ],
        "v124_archive_members": _package_members(archive),
        "episode_inventory": episode_inventory,
        "fidelity_scope": args.scope,
        "fidelity_by_submission": by_submission,
        "fidelity_contexts": contexts,
        "model_structure": _model_structure(),
        "forbidden_runtime_inputs": [
            "opponent private state",
            "future town shops",
            "replay info.seed",
            "future prices",
            "outcome/final cash",
            "submission id/opponent rating",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "fidelity": by_submission}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
