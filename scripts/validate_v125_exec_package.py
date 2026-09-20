"""Validate the packaged V125 execution-only candidate against its source."""

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
ARCHIVE = ROOT / "artifacts/submissions/v125_exec_candidate.tar.gz"
SOURCE = ROOT / "agents/v125_exec/main.py"
OPPONENT = ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py"
OUTPUT = ROOT / "experiments/research_20260920_v125/package_validation.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module(path: Path, label: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"_{label}_{uuid.uuid4().hex}", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _game(agent_path: Path, label: str) -> dict[str, Any]:
    focal = _module(agent_path, label)
    opponent = _module(OPPONENT, f"{label}_opponent")
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 2026092101}, debug=True)
    env.run([focal.agent, opponent.agent])
    replay = env.toJSON()
    actions = [state[0].get("action") for state in replay["steps"][1:]]
    final = replay["steps"][-1]
    return {
        "states": len(replay["steps"]),
        "statuses": [state.get("status") for state in final],
        "rewards": [float(state.get("reward") or 0) for state in final],
        "actions": actions,
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=OUTPUT.parent) as temporary:
        target = Path(temporary)
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            entries = archive.getnames()
            root = target.resolve()
            if any(not (target / member.name).resolve().is_relative_to(root) for member in archive.getmembers()):
                raise ValueError("unsafe archive entry")
            archive.extractall(target, filter="data")
        packaged = _game(target / "main.py", "packaged")
        source = _game(SOURCE, "source")
        mismatches = sum(left != right for left, right in zip(packaged["actions"], source["actions"], strict=True))
        passed = (
            entries[0] == "main.py"
            and packaged["states"] == source["states"] == 720
            and packaged["statuses"] == source["statuses"] == ["DONE", "DONE"]
            and packaged["rewards"] == source["rewards"]
            and mismatches == 0
        )
        result = {
            "passed": passed,
            "archive": str(ARCHIVE.relative_to(ROOT)).replace("\\", "/"),
            "archive_sha256": _sha256(ARCHIVE),
            "entries": entries,
            "seed": 2026092101,
            "seat": 0,
            "packaged_rewards": packaged["rewards"],
            "source_rewards": source["rewards"],
            "focal_action_mismatches": mismatches,
        }
        OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not passed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
