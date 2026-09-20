"""Audit the local V125 execution archive against the two live submissions.

Exact replay-action agreement is behavioral evidence, not remote byte
authentication.  The output keeps that distinction explicit.
"""

from __future__ import annotations

import argparse
import csv
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

SUBMISSIONS = (56384917, 56384919)
ARCHIVE = ROOT / "artifacts/submissions/v125_exec_candidate.tar.gz"
DEFAULT_OUTPUT = ROOT / "experiments/research_20260920_v126/phase0_live_identity.json"


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
    name = f"_v125_live_{role}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "reset_runtime_state"):
        module.reset_runtime_state()
    return module


def _rows(submission_id: int) -> list[dict[str, str]]:
    path = ROOT / f"data/submissions/v125_submission_{submission_id}/episodes.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _replay_path(submission_id: int, episode_id: int) -> Path:
    return ROOT / f"data/replays/v125_submission_{submission_id}/episode_{episode_id}.json"


def _target_seats(row: dict[str, str], submission_id: int) -> list[int]:
    return [
        seat
        for seat in (0, 1)
        if int(row.get(f"agent_{seat}_submission_id") or -1) == submission_id
    ]


def _fidelity(
    main: Path, submission_id: int, row: dict[str, str], seat: int
) -> dict[str, Any]:
    episode_id = int(row["episode_id"])
    replay_path = _replay_path(submission_id, episode_id)
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    module = _import_agent(main, f"{submission_id}_{episode_id}_{seat}")
    recorded_digest = hashlib.sha256()
    emitted_digest = hashlib.sha256()
    mismatches: list[dict[str, Any]] = []
    decisions = max(0, len(replay.get("steps") or []) - 1)
    for step in range(decisions):
        obs = observation(replay, step, seat)
        if obs is None:
            continue
        recorded = action(replay, step, seat)
        emitted = module.agent(obs)
        recorded_key = canonical_action(recorded)
        emitted_key = canonical_action(emitted)
        recorded_digest.update(recorded_key.encode("utf-8") + b"\n")
        emitted_digest.update(emitted_key.encode("utf-8") + b"\n")
        if recorded_key != emitted_key and len(mismatches) < 5:
            mismatches.append(
                {"step": step, "recorded": recorded, "local": emitted}
            )
    mismatch_count = 0
    if recorded_digest.digest() != emitted_digest.digest():
        # Re-run only in the exceptional case to count all mismatches while
        # preserving the first-pass runtime state semantics.
        module = _import_agent(main, f"recount_{submission_id}_{episode_id}_{seat}")
        for step in range(decisions):
            obs = observation(replay, step, seat)
            if obs is None:
                continue
            mismatch_count += canonical_action(module.agent(obs)) != canonical_action(
                action(replay, step, seat)
            )
    return {
        "submission_id": submission_id,
        "episode_id": episode_id,
        "episode_type": row.get("episode_type"),
        "seat": seat,
        "decisions": decisions,
        "exact_matches": decisions - mismatch_count,
        "mismatches": mismatch_count,
        "first_examples": mismatches,
        "recorded_action_sha256": recorded_digest.hexdigest(),
        "local_action_sha256": emitted_digest.hexdigest(),
        "replay_sha256": _sha256(replay_path),
        "configuration_sha256": hashlib.sha256(
            json.dumps(
                replay.get("configuration") or {}, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
    }


def _members(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    with tarfile.open(path, "r:gz") as handle:
        for member in handle.getmembers():
            if not member.isfile():
                continue
            stream = handle.extractfile(member)
            payload = b"" if stream is None else stream.read()
            result.append(
                {
                    "name": member.name,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    return sorted(result, key=lambda item: item["name"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--all-public",
        action="store_true",
        help="audit every public perspective as well as both validation seats",
    )
    args = parser.parse_args()

    engine = (
        ROOT
        / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
    )
    spec = engine.with_name("kaggriculture.json")
    contexts: list[dict[str, Any]] = []
    inventories: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="v125_live_identity_") as raw:
        extracted = Path(raw)
        with tarfile.open(ARCHIVE, "r:gz") as handle:
            handle.extractall(extracted, filter="data")
        main_path = extracted / "main.py"
        for submission_id in SUBMISSIONS:
            rows = _rows(submission_id)
            selected = [
                row
                for row in rows
                if args.all_public
                or row.get("episode_type") == "EPISODE_TYPE_VALIDATION"
            ]
            inventories[str(submission_id)] = {
                "episodes": len(rows),
                "public": sum(
                    row.get("episode_type") == "EPISODE_TYPE_PUBLIC" for row in rows
                ),
                "validation": sum(
                    row.get("episode_type") == "EPISODE_TYPE_VALIDATION" for row in rows
                ),
                "first_create_time": min(row["create_time"] for row in rows),
                "last_create_time": max(row["create_time"] for row in rows),
            }
            for row in selected:
                for seat in _target_seats(row, submission_id):
                    contexts.append(_fidelity(main_path, submission_id, row, seat))

    summary: dict[str, Any] = {}
    for submission_id in SUBMISSIONS:
        values = [
            context
            for context in contexts
            if context["submission_id"] == submission_id
        ]
        summary[str(submission_id)] = {
            "contexts": len(values),
            "decisions": sum(value["decisions"] for value in values),
            "exact_matches": sum(value["exact_matches"] for value in values),
            "mismatches": sum(value["mismatches"] for value in values),
        }

    fixed = [
        ARCHIVE,
        ROOT / "agents/v125_exec/main.py",
        ROOT / "agents/v124/main.py",
        ROOT / "agents/v124/policy_model.json.gz",
        ROOT / "agents/v124/opponent_sell_model.json",
        engine,
        spec,
    ]
    payload = {
        "format": "kaggriculture-v125-live-identity-v1",
        "evidence": "recorded-observation action fidelity; not remote archive byte authentication",
        "remote_archive_sha256": "UNAVAILABLE",
        "conclusion_rule": (
            "Zero mismatches establishes behavioral identity on audited observations only. "
            "The local archive SHA256 must not be claimed as a remote byte hash."
        ),
        "git": {
            "head": _git("rev-parse", "HEAD"),
            "v124_source_commit": _git(
                "log", "-1", "--format=%H", "--", "agents/v124/main.py"
            ),
            "v125_exec_source_commit": _git(
                "log", "-1", "--format=%H", "--", "agents/v125_exec/main.py"
            ),
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "kaggle_environments": importlib.metadata.version("kaggle-environments"),
        },
        "runtime": {
            "entrypoint": "main.py::agent",
            "call_chain": [
                "v125_exec.main.agent",
                "v124_base.agent",
                "v121_market.agent via v124",
                "v125_exec.main.repair_action",
            ],
            "always_on_repairs": [
                "start-of-turn seed PLANT cap",
                "shed-overflow DROP bounding",
            ],
            "inherited_v124_flags": {
                "ENABLE_CURRENT_META_LIBRARY": True,
                "ENABLE_SEGMENT_ROUTER": False,
                "ENABLE_SELL_FORECAST": False,
                "ENABLE_CLONE_PREEMPTION": False,
            },
        },
        "fixed_files": [
            {
                "path": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in fixed
        ],
        "archive_members": _members(ARCHIVE),
        "episode_inventory": inventories,
        "fidelity_scope": "all" if args.all_public else "validation",
        "fidelity_summary": summary,
        "fidelity_contexts": contexts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
