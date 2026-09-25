"""Create Round7 reproducibility metadata, hashes, and a self-contained evidence bundle."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_next_20260921.common import (  # noqa: E402
    ACTOR_TOKENS,
    MARKET_TOKENS,
    actor_feature_names,
    bc_actor_feature_names,
    market_feature_names,
    state_feature_names,
)

EXPERIMENT = ROOT / "experiments/learning_round7_20260922"
REPRO = EXPERIMENT / "reproducibility"
SUBMISSIONS = ROOT / "artifacts/submissions"
ENGINE_PACKAGE = ROOT / ".venv/Lib/site-packages/kaggle_environments"
BUNDLE = SUBMISSIONS / "learning_round7_20260922_evidence_bundle.tar.gz"
HASH_MANIFEST = EXPERIMENT / "ARTIFACT_SHA256.json"
BUNDLE_HASH = EXPERIMENT / "EVIDENCE_BUNDLE_SHA256.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def command(arguments: list[str]) -> dict[str, Any]:
    completed = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True, check=False)
    return {
        "arguments": arguments,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def generate_metadata() -> Path:
    REPRO.mkdir(parents=True, exist_ok=True)
    dependencies = command([sys.executable, "-m", "pip", "freeze"])
    (REPRO / "dependencies.txt").write_text(dependencies["stdout"], encoding="utf-8")
    write_json(REPRO / "dependency_capture.json", dependencies)

    engine = ENGINE_PACKAGE / "envs/kaggriculture/kaggriculture.py"
    loader = ENGINE_PACKAGE / "agent.py"
    write_json(
        REPRO / "engine_identity.json",
        {
            "kaggle_environments_version": "1.32.7",
            "engine_source": str(engine.relative_to(ROOT)),
            "engine_sha256": sha256(engine),
            "loader_source": str(loader.relative_to(ROOT)),
            "loader_sha256": sha256(loader),
            "loader_contract": "build_agent(path, builtin_agents, environment_name), empty exec globals",
        },
    )

    prefix_names = [
        *[f"same_turn_prefix:normalized_count:{token}" for token in ACTOR_TOKENS],
        *[f"same_turn_prefix:previous_token:{token}" for token in ACTOR_TOKENS],
    ]
    features = {
        "state": list(state_feature_names()),
        "actor_base": list(actor_feature_names()),
        "actor_with_previous_turn": list(bc_actor_feature_names()),
        "actor_same_turn_prefix": prefix_names,
        "actor_final": [*bc_actor_feature_names(), *prefix_names],
        "market": list(market_feature_names()),
        "actor_quantity": [*bc_actor_feature_names(), *prefix_names, *[f"token:{v}" for v in ACTOR_TOKENS]],
        "market_quantity": [*market_feature_names(), *[f"token:{v}" for v in MARKET_TOKENS]],
        "known_limitation": (
            "same-turn prefix stores token frequencies and the previous token, not prior quantities or targets; "
            "the Round7 runtime ledger tracks quantities/resources after decode"
        ),
    }
    write_json(
        REPRO / "feature_specification.json",
        {
            "dimensions": {name: len(values) for name, values in features.items() if isinstance(values, list)},
            "features": features,
            "feature_name_sha256": {
                name: hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
                for name, values in features.items()
                if isinstance(values, list)
            },
        },
    )

    source_manifest = ROOT / "experiments/learning_next_20260921/source_manifest.json"
    split_manifest = ROOT / "experiments/learning_next_20260921/split_manifest.json"
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    causal = next(
        row for row in source["files"] if int(row["episode_id"]) == 109590135 and int(row["seat"]) == 1
    )
    causal_path = ROOT / causal["path"]
    write_json(
        REPRO / "teacher_and_split_manifest.json",
        {
            "source_manifest": {
                "path": str(source_manifest.relative_to(ROOT)),
                "sha256": sha256(source_manifest),
                "source_appearances": source["source_appearances"],
                "unique_episodes": source["unique_episodes"],
            },
            "split_manifest": {
                "path": str(split_manifest.relative_to(ROOT)),
                "sha256": sha256(split_manifest),
            },
            "round6_sequence_dataset_manifest": {
                "path": "experiments/learning_round6_20260922/datasets/sequence_bc_v1/dataset_manifest.json",
                "sha256": sha256(
                    ROOT
                    / "experiments/learning_round6_20260922/datasets/sequence_bc_v1/dataset_manifest.json"
                ),
            },
            "causal_teacher_episode": {
                **causal,
                "actual_sha256": sha256(causal_path),
                "included_in_bundle": True,
            },
            "full_teacher_payload_included": False,
            "full_teacher_payload_limit": (
                "The roughly 1 GB local teacher arrays/replays are not duplicated in the bundle; their complete "
                "manifests and the causal episode are included."
            ),
        },
    )

    git = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "head": command(["git", "rev-parse", "HEAD"]),
        "status_porcelain_v2": command(["git", "status", "--porcelain=v2", "--untracked-files=all"]),
        "staged_name_status": command(["git", "diff", "--cached", "--name-status"]),
        "unstaged_name_status": command(["git", "diff", "--name-status"]),
        "staged_numstat": command(["git", "diff", "--cached", "--numstat"]),
        "unstaged_patch": command(["git", "diff", "--binary"]),
        "limit": (
            "A monolithic binary patch for the pre-existing staged Round6 replay/NPY payload was not duplicated. "
            "Its full status/name/numstat and the frozen Round6 inventory hashes are retained; all Round7 sources "
            "and artifacts are included verbatim in the evidence bundle."
        ),
    }
    write_json(REPRO / "git_snapshot.json", git)
    return causal_path


def selected_files() -> list[Path]:
    files: set[Path] = set()
    for path in EXPERIMENT.rglob("*"):
        if path.is_file() and path not in {HASH_MANIFEST, BUNDLE_HASH}:
            files.add(path)
    for directory in (
        ROOT / "agents/learning_round7_20260922_r6_loaderfix",
        ROOT / "agents/learning_round7_20260922_ledger",
        ROOT / "agents/learning_round7_20260922_plan",
        ROOT / "agents/learning_round7_20260922_capacity",
    ):
        files.update(path for path in directory.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    files.update(ROOT.glob("scripts/*round7*.py"))
    files.add(ROOT / "tests/test_round7_contracts.py")
    files.add(ROOT / "agents/learning_round6_20260922_v1/main.py")
    files.add(ROOT / "agents/learning_next_20260921/common.py")
    files.add(ROOT / "experiments/learning_next_20260921/source_manifest.json")
    files.add(ROOT / "experiments/learning_next_20260921/split_manifest.json")
    files.add(ROOT / "experiments/learning_round6_20260922/datasets/sequence_bc_v1/dataset_manifest.json")
    files.update(SUBMISSIONS.glob("learning_round7_20260922*.tar.gz"))
    files.add(SUBMISSIONS / "learning_round6_20260922_sequence_bc_v1.tar.gz")
    files.update(SUBMISSIONS / f"{name}.tar.gz" for name in ("v122", "v123", "v124"))
    files.add(ENGINE_PACKAGE / "agent.py")
    files.update(
        path
        for path in (ENGINE_PACKAGE / "envs/kaggriculture").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    return sorted(path for path in files if path.is_file())


def archive_name(path: Path) -> str:
    if path.is_relative_to(ROOT):
        return str(path.relative_to(ROOT)).replace("\\", "/")
    if path == ENGINE_PACKAGE / "agent.py":
        return "fixed_environment/kaggle_environments/agent.py"
    if path.is_relative_to(ENGINE_PACKAGE / "envs/kaggriculture"):
        relative = path.relative_to(ENGINE_PACKAGE / "envs/kaggriculture")
        return "fixed_environment/kaggle_environments/envs/kaggriculture/" + str(relative).replace("\\", "/")
    raise ValueError(path)


def main() -> None:
    causal_path = generate_metadata()
    files = selected_files()
    files.append(causal_path)
    files = sorted(set(files))
    write_json(
        HASH_MANIFEST,
        {
            "created_at_utc": datetime.now(UTC).isoformat(),
            "scope": "Round7 evidence, source, candidate/baseline archives, fixed engine, and causal teacher episode",
            "self_excluded": str(HASH_MANIFEST.relative_to(ROOT)),
            "files": [
                {
                    "path": archive_name(path) if path != causal_path else f"teacher_case/{causal_path.name}",
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
                for path in files
            ],
        },
    )
    files.append(HASH_MANIFEST)
    if BUNDLE.exists():
        raise FileExistsError(f"refusing to overwrite {BUNDLE}")
    with tarfile.open(BUNDLE, "w:gz") as stream:
        for path in sorted(set(files)):
            name = f"teacher_case/{path.name}" if path == causal_path else archive_name(path)
            stream.add(path, arcname=name)
    write_json(
        BUNDLE_HASH,
        {
            "created_at_utc": datetime.now(UTC).isoformat(),
            "bundle": str(BUNDLE.relative_to(ROOT)),
            "bytes": BUNDLE.stat().st_size,
            "sha256": sha256(BUNDLE),
            "manifest": str(HASH_MANIFEST.relative_to(ROOT)),
            "manifest_sha256": sha256(HASH_MANIFEST),
        },
    )
    print((BUNDLE_HASH).read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
