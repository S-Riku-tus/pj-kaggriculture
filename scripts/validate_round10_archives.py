"""Safely extract and probe each Round10 archive in an independent process."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CPP_ROOT = ROOT / "experiments/round10_public_learning_20260924/engines/kaggriculture-cppsim"
MINGW_BIN = Path(r"C:\msys64\ucrt64\bin")
V57 = ROOT / "experiments/round10_public_learning_20260924/public_agents/ahmed_v57/main.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_last(path: Path, label: str) -> tuple[Any, dict[str, Any]]:
    namespace: dict[str, Any] = {"__file__": str(path), "__name__": label}
    sys.path.insert(0, str(path.parent))
    try:
        exec(compile(path.read_bytes(), str(path), "exec"), namespace)
    finally:
        sys.path.pop(0)
    values = [value for value in namespace.values() if callable(value)]
    if not values:
        raise RuntimeError(f"no callable in {path}")
    return values[-1], namespace


def invoke(function: Any, observation: dict[str, Any]) -> dict[str, Any]:
    argc = getattr(getattr(function, "__code__", None), "co_argcount", 1)
    raw = function(observation, {"episodeSteps": 720}) if argc >= 2 else function(observation)
    return {
        "farmer": list(raw.get("farmer") or ["PASS"]),
        "hands": [list(value) for value in (raw.get("hands") or [])],
        "market": [list(value) for value in (raw.get("market") or [])],
    }


def worker(directory: Path, seed: int) -> dict[str, Any]:
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(MINGW_BIN))
    sys.path.insert(0, str(CPP_ROOT))
    import kagsim

    agent, namespace = load_last(directory / "main.py", "_round10_archive")
    opponent, _ = load_last(V57, "_round10_v57")
    game = kagsim.Game(seed)
    first_action: dict[str, Any] | None = None
    while not game.done:
        observations = [json.loads(json.dumps(game.observe(player))) for player in (0, 1)]
        actions = [invoke(agent, observations[0]), invoke(opponent, observations[1])]
        first_action = first_action or actions[0]
        game.step(actions[0], actions[1])
    diagnostic_function = namespace.get("latest_diagnostics")
    diagnostics = diagnostic_function() if callable(diagnostic_function) else {}
    return {
        "first_action": first_action,
        "rewards": [float(game.reward(0)), float(game.reward(1))],
        "model_loaded": bool(diagnostics.get("model_loaded")) if diagnostics else None,
        "model_calls": int(diagnostics.get("model_calls", 0) or 0) if diagnostics else None,
        "contract_failures": int(diagnostics.get("contract_failures", 0) or 0) if diagnostics else None,
    }


def safe_extract(archive_path: Path, destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            value = Path(member.name)
            if value.is_absolute() or ".." in value.parts or not member.isfile():
                raise ValueError(f"unsafe archive member: {member.name}")
        archive.extractall(destination, members=members, filter="data")
    return [member.name for member in members]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--seed", type=int, default=2026092428)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker.resolve(), args.seed), separators=(",", ":")))
        return
    if args.manifest is None or args.output is None:
        parser.error("manifest and --output are required")
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    extraction_root = ROOT / "experiments/round10_public_learning_20260924/package_validation/extracted"
    environment = dict(os.environ)
    environment["PATH"] = f"{MINGW_BIN}{os.pathsep}{environment.get('PATH', '')}"
    results = []
    for package in manifest["packages"]:
        archive_path = ROOT / package["archive"]
        destination = extraction_root / package["name"]
        members = safe_extract(archive_path, destination)
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", str(destination), "--seed", str(args.seed)],
            cwd=ROOT,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        probe = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.returncode == 0 else {}
        results.append(
            {
                "name": package["name"],
                "archive_sha256": sha256_file(archive_path),
                "hash_matches_manifest": sha256_file(archive_path) == package["archive_sha256"],
                "members": members,
                "worker_returncode": completed.returncode,
                "worker_stderr": completed.stderr,
                "full_episode_probe": probe,
                "passed": completed.returncode == 0,
            }
        )
    result = {"seed": args.seed, "all_passed": all(value["passed"] for value in results), "results": results}
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
