"""Validate the final Round9 archive from an extraction outside the repository."""

from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from pathlib import Path

from kaggle_environments import make
from kaggle_environments.agent import get_last_callable

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "artifacts" / "submissions" / "round9_20260923_a2_prefix_bc_seed20260924_v3.tar.gz"
TARGET = Path(r"C:\tmp\round9_a2_v3_loader_audit_20260923")
OUTPUT = (
    ROOT
    / "experiments"
    / "round9_teacher_reproduction_and_closed_loop_bc_20260923"
    / "final_archive_loader_validation.json"
)
MODULES = ("runtime", "spatial_policy", "spatial", "model_compat", "common")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if TARGET.exists() or OUTPUT.exists():
        raise FileExistsError({"target": str(TARGET), "output": str(OUTPUT)})
    TARGET.mkdir(parents=True)
    with tarfile.open(ARCHIVE, "r:gz") as stream:
        root = TARGET.resolve()
        members = stream.getmembers()
        for member in members:
            if not (TARGET / member.name).resolve().is_relative_to(root):
                raise ValueError(member.name)
        stream.extractall(TARGET, filter="data")
    main_path = TARGET / "main.py"
    raw = main_path.read_text(encoding="utf-8")
    for name in MODULES:
        sys.modules.pop(name, None)
    selected = get_last_callable(raw, path=str(main_path))
    selected_name = getattr(selected, "__name__", None)
    loaded = {}
    for name in MODULES:
        module = sys.modules.get(name)
        path = Path(module.__file__).resolve() if module is not None and getattr(module, "__file__", None) else None
        loaded[name] = {
            "absolute_path": str(path) if path else None,
            "inside_extraction": bool(path and path.is_relative_to(TARGET.resolve())),
            "sha256": sha256(path) if path and path.is_file() else None,
        }
    first_actions = []
    runs = []
    for seed in (2026092301, 2026092302):
        environment = make("kaggriculture", configuration={"episodeSteps": 4, "seed": seed, "weedSpawnChance": 0.0})
        environment.run([selected, "pass"])
        replay = environment.toJSON()
        first_actions.append(replay["steps"][1][0]["action"])
        runtime = sys.modules["runtime"]
        trace = runtime.diagnostics()["trace"].get(0, [])
        runs.append(
            {
                "seed": seed,
                "states": len(replay["steps"]),
                "decisions": len(replay["steps"]) - 1,
                "statuses": [value["status"] for value in replay["steps"][-1]],
                "trace_first_step": trace[0]["step"] if trace else None,
                "trace_steps": len(trace),
            }
        )
    weight_hashes = {
        name: sha256(TARGET / f"{name}.npz")
        for name in ("actor_token", "actor_quantity", "market_token", "market_quantity")
    }
    passed = (
        selected_name == "agent"
        and all(value["inside_extraction"] for value in loaded.values())
        and all(value["states"] == 4 and value["decisions"] == 3 for value in runs)
        and all(value["trace_first_step"] == 0 and value["trace_steps"] == 3 for value in runs)
        and all(value["statuses"] == ["DONE", "DONE"] for value in runs)
    )
    payload = {
        "passed": passed,
        "archive": str(ARCHIVE.relative_to(ROOT)),
        "archive_sha256": sha256(ARCHIVE),
        "extraction_absolute_path": str(TARGET.resolve()),
        "repository_absolute_path": str(ROOT.resolve()),
        "extraction_outside_repository": not TARGET.resolve().is_relative_to(ROOT.resolve()),
        "archive_members": [member.name for member in members],
        "official_loader_selected_callable": selected_name,
        "entrypoint": "main.py:agent",
        "loaded_modules": loaded,
        "weight_hashes": weight_hashes,
        "consecutive_same_callable_runs": runs,
        "step_zero_reset_verified": all(value["trace_first_step"] == 0 and value["trace_steps"] == 3 for value in runs),
        "first_actions": first_actions,
        "numpy_source": __import__("numpy").__file__,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
