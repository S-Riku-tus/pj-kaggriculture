"""Validate final V117 archive across seats and consecutive same-process games."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kaggle_environments import make  # noqa: E402

ARCHIVE = ROOT / "artifacts/submissions/v117.tar.gz"
OPPONENT = ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py"
OUTPUT = ROOT / "experiments/research_20260916_v117_live_trial/package_runtime_validation.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_module(path: Path, role: str) -> Any:
    name = f"_v117_package_{role}_{os.getpid()}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "agent", None)):
        raise TypeError(path)
    return module


def semantic(replay: dict[str, Any]) -> list[Any]:
    result = []
    for step in replay["steps"]:
        clean = []
        for state in step:
            obs = state.get("observation") or {}
            if isinstance(obs, str):
                obs = json.loads(obs)
            obs = dict(obs)
            obs.pop("remainingOverageTime", None)
            clean.append(
                {
                    "observation": obs,
                    "action": state.get("action"),
                    "reward": state.get("reward"),
                    "status": state.get("status"),
                }
            )
        result.append(clean)
    return result


def main() -> None:
    with tempfile.TemporaryDirectory(dir=OUTPUT.parent) as temporary:
        target = Path(temporary)
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            root = target.resolve()
            entries = archive.getnames()
            for member in archive.getmembers():
                if not (target / member.name).resolve().is_relative_to(root):
                    raise ValueError(member.name)
            archive.extractall(target, filter="data")
        package = import_module(target / "main.py", "agent")
        opponent = import_module(OPPONENT, "opponent")
        seats = {}
        for seat in (0, 1):
            repeats = []
            for _repeat in range(2):
                env = make(
                    "kaggriculture",
                    configuration={"episodeSteps": 720, "seed": 10091011},
                    debug=True,
                )
                env.run(
                    [package.agent, opponent.agent]
                    if seat == 0
                    else [opponent.agent, package.agent]
                )
                replay = env.toJSON()
                own_cash = []
                hands_shape = True
                for step_index, states in enumerate(replay["steps"]):
                    obs = states[seat].get("observation") or {}
                    if isinstance(obs, str):
                        obs = json.loads(obs)
                    farms = obs.get("farms") or []
                    if seat < len(farms):
                        own_cash.append(float(farms[seat].get("money", 0.0) or 0.0))
                    if step_index > 0:
                        emitted = states[seat].get("action") or {}
                        prior_obs = replay["steps"][step_index - 1][seat].get("observation") or {}
                        if isinstance(prior_obs, str):
                            prior_obs = json.loads(prior_obs)
                        prior_farms = prior_obs.get("farms") or []
                        prior_farm = prior_farms[seat] if seat < len(prior_farms) else {}
                        hands_shape &= (
                            len(emitted.get("hands") or []) == len(prior_farm.get("hands") or [])
                        )
                repeats.append(
                    {
                        "states": len(replay["steps"]),
                        "decisions": len(replay["steps"]) - 1,
                        "final_statuses": [str(state.get("status")) for state in replay["steps"][-1]],
                        "final_rewards": [float(state.get("reward") or 0.0) for state in replay["steps"][-1]],
                        "minimum_cash": min(own_cash),
                        "hands_shape": hands_shape,
                        "semantic": semantic(replay),
                    }
                )
            seats[str(seat)] = {
                "states": [record["states"] for record in repeats],
                "decisions": [record["decisions"] for record in repeats],
                "final_statuses": [record["final_statuses"] for record in repeats],
                "final_rewards": [record["final_rewards"] for record in repeats],
                "minimum_cash": [record["minimum_cash"] for record in repeats],
                "hands_shape": all(record["hands_shape"] for record in repeats),
                "consecutive_semantic_identity": repeats[0]["semantic"] == repeats[1]["semantic"],
            }
        passed = all(
            value["states"] == [720, 720]
            and value["decisions"] == [719, 719]
            and value["hands_shape"]
            and value["consecutive_semantic_identity"]
            and min(value["minimum_cash"]) >= 0
            for value in seats.values()
        )
        output = {
            "passed": passed,
            "archive": str(ARCHIVE.relative_to(ROOT)).replace("\\", "/"),
            "archive_sha256": sha(ARCHIVE),
            "archive_entries": entries,
            "entrypoint": "main.py:agent",
            "same_module_object_across_consecutive_games": True,
            "step_zero_reset_exercised": True,
            "seats": seats,
            "fresh_process_note": (
                "This validator invocation is a fresh Python process; paired runner workers also "
                "independently imported V117 for every control/treatment game."
            ),
        }
        temporary_output = OUTPUT.with_suffix(".json.tmp")
        temporary_output.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary_output.replace(OUTPUT)
        print(json.dumps({"passed": passed, "archive_sha256": sha(ARCHIVE), "seats": seats}))
        if not passed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
