"""Validate the final V119 archive itself in both seats."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any

from kaggle_environments import make

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "artifacts" / "submissions" / "v119.tar.gz"
OPPONENT = ROOT / "agents" / "v117" / "main.py"
OUTPUT = ROOT / "experiments" / "research_20260917_v118" / "package_runtime_validation.json"
EXPECTED_POLICY_SHA256 = "91772fda544e2d5768afff819e2de75ecb7a12db8acb40a48ee9edcf76aca434"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _import_agent(path: Path, label: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"_{label}_{uuid.uuid4().hex}", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "agent", None)):
        raise TypeError(f"missing agent callable: {path}")
    return module.agent


def main() -> None:
    with tempfile.TemporaryDirectory(dir=OUTPUT.parent) as temporary:
        target = Path(temporary)
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            root = target.resolve()
            entries = archive.getnames()
            for member in archive.getmembers():
                if not (target / member.name).resolve().is_relative_to(root):
                    raise ValueError(f"unsafe archive entry: {member.name}")
            archive.extractall(target, filter="data")

        policy_sha256 = _sha256(target / "psr_base.py")
        package_agent = _import_agent(target / "main.py", "v119_package")
        opponent_agent = _import_agent(OPPONENT, "v117_opponent")
        games = []
        for seat in (0, 1):
            env = make(
                "kaggriculture",
                configuration={"episodeSteps": 720, "seed": 2026091741},
                debug=True,
            )
            agents = (
                [package_agent, opponent_agent]
                if seat == 0
                else [opponent_agent, package_agent]
            )
            env.run(agents)
            replay = env.toJSON()
            final = replay["steps"][-1]
            rewards = [float(state.get("reward") or 0.0) for state in final]
            statuses = [str(state.get("status")) for state in final]
            games.append(
                {
                    "seat": seat,
                    "states": len(replay["steps"]),
                    "statuses": statuses,
                    "ours": rewards[seat],
                    "theirs": rewards[1 - seat],
                    "margin": rewards[seat] - rewards[1 - seat],
                }
            )

        passed = (
            entries == ["main.py", "LICENSE", "NOTICE.md", "psr_base.py"]
            and policy_sha256 == EXPECTED_POLICY_SHA256
            and all(game["states"] == 720 for game in games)
            and all(game["statuses"] == ["DONE", "DONE"] for game in games)
        )
        result = {
            "passed": passed,
            "archive": str(ARCHIVE.relative_to(ROOT)).replace("\\", "/"),
            "archive_sha256": _sha256(ARCHIVE),
            "entries": entries,
            "policy_sha256": policy_sha256,
            "expected_policy_sha256": EXPECTED_POLICY_SHA256,
            "games": games,
        }
        OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not passed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
