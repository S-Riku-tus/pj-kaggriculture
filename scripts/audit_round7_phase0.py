"""Freeze Round6 inputs and trace the concrete day-1 livestock failure.

This audit is intentionally read-only with respect to every Round6 artifact.  It
writes new evidence only below experiments/learning_round7_20260922.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ROUND6 = ROOT / "experiments" / "learning_round6_20260922"
ROUND7 = ROOT / "experiments" / "learning_round7_20260922"
PHASE0 = ROUND7 / "phase0"
ARCHIVES = ROOT / "artifacts" / "submissions"
CANDIDATE = ARCHIVES / "learning_round6_20260922_sequence_bc_v1.tar.gz"
REPLAY = (
    ROUND6 / "development_evaluation" / "replays" / "round6_sequence_bc_v1" / "v122" / "seed_2026102201_seat_1.json.gz"
)
EXPECTED = {
    "learning_round6_20260922_sequence_bc_v1.tar.gz": (
        "f8d1bc6ea5d69ef8777013995c63aa88e83f8a5c1402b184f356153d2d372434"
    ),
    "v122.tar.gz": "edf5b32565f8c4530959b94df36858a6a64c651d4b42b7aa612ddaca02e9a88c",
    "v123.tar.gz": "0d5296587b1ba6f68cbd7bd5943f164269071b03b852ee3982ce22958edc33f6",
    "v124.tar.gz": "cdc74eb6ae47c53e9c2edfeea45dc55603c67ebfdba48164081458f79c4f46fc",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def archive_members(path: Path) -> list[dict[str, Any]]:
    members = []
    with tarfile.open(path, "r:gz") as stream:
        for member in sorted(stream.getmembers(), key=lambda item: item.name):
            extracted = stream.extractfile(member)
            content = extracted.read() if extracted is not None else b""
            members.append(
                {
                    "name": member.name,
                    "bytes": member.size,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    return members


def restore_observation(states: list[dict[str, Any]], seat: int, step: int) -> dict[str, Any]:
    public = copy.deepcopy(states[0].get("observation") or {})
    private = states[seat].get("observation") or {}
    public["player"] = seat
    public["private"] = copy.deepcopy(private.get("private", {}))
    public["remainingOverageTime"] = private.get("remainingOverageTime", public.get("remainingOverageTime", 60))
    public["step"] = step
    return public


def load_module(main_path: Path) -> Any:
    module_name = f"round6_archive_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(module_name, main_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {main_path}")
    sys.path.insert(0, str(main_path.parent))
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def isolated_archive() -> Path:
    # A sibling of the repository is used so the extracted agent cannot resolve
    # source files from the repository through its current working directory.
    root = Path(tempfile.mkdtemp(prefix="round7_round6_archive_", dir=ROOT.parent))
    with tarfile.open(CANDIDATE, "r:gz") as stream:
        for member in stream.getmembers():
            destination = (root / member.name).resolve()
            if root.resolve() not in destination.parents and destination != root.resolve():
                raise RuntimeError(f"unsafe archive member: {member.name}")
        stream.extractall(root, filter="data")
    return root


def official_loader_probe(archive_root: Path) -> dict[str, Any]:
    code = "\n".join(
        (
            "from kaggle_environments import make",
            "from pathlib import Path",
            f"p = str(Path({str(archive_root / 'main.py')!r}))",
            "env = make('kaggriculture', configuration={'episodeSteps': 4}, debug=True)",
            "env.run([p, 'pass'])",
            "print([(s.status, s.reward) for s in env.steps[-1]])",
        )
    )
    started = datetime.now(UTC)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=archive_root,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    return {
        "loader": "kaggle_environments.make(...).run([absolute_main_path, 'pass'])",
        "cwd": str(archive_root),
        "repository_on_cwd": False,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "elapsed_seconds": (datetime.now(UTC) - started).total_seconds(),
        "passed": result.returncode == 0,
    }


def snapshot_runtime(module: Any) -> dict[str, Any]:
    return {
        "history": copy.deepcopy(module._history),
        "previous_market": copy.deepcopy(module._previous_market),
        "previous_actor": copy.deepcopy(module._previous_actor),
        "probes": copy.deepcopy(module._probes),
        "stats": copy.deepcopy(module._stats),
    }


def restore_runtime(module: Any, state: dict[str, Any]) -> None:
    module._history = state["history"]
    module._previous_market = state["previous_market"]
    module._previous_actor = state["previous_actor"]
    module._probes = state["probes"]
    module._stats = state["stats"]


def predicted_quantity(model: Any, features: np.ndarray) -> int:
    probability = model.probabilities(features)
    return max(1, int(float(model.classes[int(probability.argmax())])))


def actor_decision_trace(module: Any, observation: dict[str, Any]) -> list[dict[str, Any]]:
    seat = int(observation["player"])
    history = copy.deepcopy(module._history.get(seat, module.MarketHistory()))
    history.update(observation, module._previous_market.get(seat))
    previous = module._previous_actor.get(seat, [])
    count = 1 + len(observation["farms"][seat].get("hands", []))
    reserved: dict[str, int] = {}
    current: list[str] = []
    rows = []
    for index in range(count):
        features = module._actor_features(
            observation,
            index,
            previous[index] if index < len(previous) else "PASS",
            history,
            current,
        )
        probability = module.ACTOR_MODEL.probabilities(features)
        ranking = sorted(
            zip(module.ACTOR_MODEL.classes, probability, strict=True),
            key=lambda pair: -float(pair[1]),
        )
        legal = module.legal_actor_tokens(observation, index, reserved)
        raw_token = str(ranking[0][0])
        selected = next((str(token) for token, _score in ranking if token in legal), "PASS")
        quantity_features = np.concatenate((features, module._token_one_hot(selected, module.ACTOR_TOKENS)))
        quantity = (
            predicted_quantity(module.ACTOR_QUANTITY_MODEL, quantity_features)
            if selected.startswith(("PICKUP:", "PLACE:"))
            else 1
        )
        farm, position, inventory, tile = module.actor_context(observation, index)
        rows.append(
            {
                "actor_index": index,
                "position": list(position),
                "inventory": dict(inventory),
                "tile": dict(tile) if isinstance(tile, dict) else tile,
                "feature_sha256": hashlib.sha256(np.asarray(features, dtype=np.float32).tobytes()).hexdigest(),
                "feature_width": int(features.size),
                "previous_turn_token": previous[index] if index < len(previous) else "PASS",
                "same_turn_prefix": list(current),
                "top5": [{"token": str(token), "probability": float(score)} for token, score in ranking[:5]],
                "raw_token": raw_token,
                "raw_legal": raw_token in legal,
                "selected_token": selected,
                "selected_quantity": quantity,
                "correction_reason": None if raw_token == selected else "raw_token_not_in_legal_mask",
                "legal_tokens": sorted(legal),
                "reserved_before": dict(reserved),
            }
        )
        module.reserve_actor_token(reserved, selected, quantity)
        current.append(selected)
    return rows


def animal_tiles(observation: dict[str, Any], seat: int) -> list[dict[str, Any]]:
    result = []
    for y, row in enumerate(observation["farms"][seat]["tiles"]):
        for x, tile in enumerate(row):
            if isinstance(tile, dict) and tile.get("animal"):
                result.append({"x": x, "y": y, **tile})
    return result


def trace_day1(main_path: Path) -> dict[str, Any]:
    module = load_module(main_path)
    module.reset_runtime_state()
    with gzip.open(REPLAY, "rt", encoding="utf-8") as stream:
        replay = json.load(stream)
    seat = 1
    turns = []
    mismatches = []
    for step in range(48):
        before = restore_observation(replay["steps"][step], seat, step)
        after = restore_observation(replay["steps"][step + 1], seat, step + 1)
        saved = replay["steps"][step + 1][seat].get("action") or {}
        actor_trace = actor_decision_trace(module, before)
        checkpoint = snapshot_runtime(module)
        raw = module.predict_raw_action(copy.deepcopy(before))
        restore_runtime(module, checkpoint)
        final = module.agent(copy.deepcopy(before))
        matches = final == saved
        if not matches:
            mismatches.append({"step": step, "record": step + 1, "saved": saved, "replayed": final})
        if step >= 24:
            turns.append(
                {
                    "observation_step": step,
                    "record": step + 1,
                    "day": before.get("day"),
                    "hour": before.get("hour"),
                    "observation_sha256": canonical_hash(before),
                    "raw_action": raw,
                    "corrected_action": final,
                    "saved_action": saved,
                    "saved_action_match": matches,
                    "actor_trace": actor_trace,
                    "before_farmer": before["farms"][seat]["farmer"],
                    "after_farmer": after["farms"][seat]["farmer"],
                    "before_inventories": before["private"]["inventories"],
                    "after_inventories": after["private"]["inventories"],
                    "before_shed_wheat": before["private"]["shed"].get("WHEAT", 0),
                    "after_shed_wheat": after["private"]["shed"].get("WHEAT", 0),
                    "before_animals": animal_tiles(before, seat),
                    "after_animals": animal_tiles(after, seat),
                }
            )
    feed_raw = sum(
        1
        for row in turns
        for action in [row["raw_action"].get("farmer", []), *row["raw_action"].get("hands", [])]
        if action and action[0] == "FEED"
    )
    feed_final = sum(
        1
        for row in turns
        for action in [row["corrected_action"].get("farmer", []), *row["corrected_action"].get("hands", [])]
        if action and action[0] == "FEED"
    )
    return {
        "created_at_utc": utc_now(),
        "source_archive": str(CANDIDATE.relative_to(ROOT)),
        "source_archive_sha256": sha256(CANDIDATE),
        "source_replay": str(REPLAY.relative_to(ROOT)),
        "source_replay_sha256": sha256(REPLAY),
        "timeline_contract": "record t action consumes state t-1 and produces state t",
        "replayed_records": 48,
        "replay_action_mismatches": mismatches,
        "exact_runtime_reproduction": not mismatches,
        "day1_raw_feed_requests": feed_raw,
        "day1_corrected_feed_requests": feed_final,
        "classification": (
            "raw_policy_did_not_request_FEED" if feed_raw == 0 else "decode_or_correction_removed_at_least_one_FEED"
        ),
        "turns": turns,
    }


def inventory(archive_root: Path, loader: dict[str, Any]) -> dict[str, Any]:
    engine = Path(importlib.util.find_spec("kaggle_environments.envs.kaggriculture.kaggriculture").origin)
    agent_loader = Path(importlib.util.find_spec("kaggle_environments.agent").origin)
    source_manifest = ROOT / "experiments" / "learning_next_20260921" / "source_manifest.json"
    split_manifest = ROOT / "experiments" / "learning_next_20260921" / "split_manifest.json"
    dataset_manifest = ROOT / "experiments" / "learning_next_20260921" / "datasets" / "bc" / "dataset_manifest.json"
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    teachers = [row for row in source["files"] if int(row["submission_id"]) == 56216119]
    missing = [row["path"] for row in teachers if not (ROOT / row["path"]).is_file()]
    size_mismatch = [
        row["path"]
        for row in teachers
        if (ROOT / row["path"]).is_file() and (ROOT / row["path"]).stat().st_size != int(row["bytes"])
    ]
    causal = next(row for row in teachers if int(row["episode_id"]) == 109590135)
    causal_path = ROOT / causal["path"]
    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    git_status = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.splitlines()
    files = [
        ROOT / "agents" / "learning_round6_20260922_v1" / "main.py",
        ROOT / "agents" / "learning_next_20260921" / "common.py",
        ROOT / "scripts" / "train_round6_sequence_bc.py",
        source_manifest,
        split_manifest,
        dataset_manifest,
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        engine,
        agent_loader,
    ]
    return {
        "created_at_utc": utc_now(),
        "git": {"head": git_head, "status_short": git_status},
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "engine": {
            "distribution": "kaggle-environments==1.32.7",
            "source": str(engine),
            "sha256": sha256(engine),
            "expected_sha256": "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e",
            "matches_expected": sha256(engine) == "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e",
            "loader_source": str(agent_loader),
            "loader_sha256": sha256(agent_loader),
        },
        "archives": {
            name: {
                "path": str((ARCHIVES / name).relative_to(ROOT)),
                "bytes": (ARCHIVES / name).stat().st_size,
                "sha256": sha256(ARCHIVES / name),
                "expected_sha256": expected,
                "matches_expected": sha256(ARCHIVES / name) == expected,
                "members": archive_members(ARCHIVES / name),
            }
            for name, expected in EXPECTED.items()
        },
        "round6_files": [
            {
                "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        ],
        "teacher_corpus": {
            "manifest_path": str(source_manifest.relative_to(ROOT)),
            "teacher_submission": 56216119,
            "episode_seat_files": len(teachers),
            "seat0": sum(int(row["seat"]) == 0 for row in teachers),
            "seat1": sum(int(row["seat"]) == 1 for row in teachers),
            "missing_files": missing,
            "size_mismatches": size_mismatch,
            "all_existence_and_size_checks_passed": not missing and not size_mismatch,
            "all_content_hashes_recomputed": False,
            "content_hash_scope": (
                "manifest plus causal episode 109590135; all other replay hashes are carried from source_manifest"
            ),
            "causal_episode": {
                **causal,
                "recomputed_sha256": sha256(causal_path),
                "hash_matches_manifest": sha256(causal_path) == causal["sha256"],
            },
        },
        "missing_or_distinguished": {
            "learning_round6_20260922_zip_present": False,
            "note": (
                "The analysis ZIP named in the audit is absent. The repository contains its resulting Round6 "
                "directory, source, models, replays, and manifests; these are not claimed to have been members "
                "of the audit attachment."
            ),
        },
        "isolated_archive_root": str(archive_root),
        "official_path_loader_probe": loader,
    }


def main() -> None:
    PHASE0.mkdir(parents=True, exist_ok=True)
    archive_root = isolated_archive()
    loader = official_loader_probe(archive_root)
    write_json(PHASE0 / "round6_frozen_inventory.json", inventory(archive_root, loader))
    trace = trace_day1(archive_root / "main.py")
    write_json(PHASE0 / "day1_unfed_round6_trace.json", trace)
    print(
        json.dumps(
            {
                "inventory": str(PHASE0 / "round6_frozen_inventory.json"),
                "day1_trace": str(PHASE0 / "day1_unfed_round6_trace.json"),
                "official_loader_passed": loader["passed"],
                "day1_exact_runtime_reproduction": trace["exact_runtime_reproduction"],
                "day1_raw_feed_requests": trace["day1_raw_feed_requests"],
                "day1_corrected_feed_requests": trace["day1_corrected_feed_requests"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
