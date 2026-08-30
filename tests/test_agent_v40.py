from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from agents.v40 import main as v40


def _pasture() -> dict[str, object]:
    return {"kind": "PASTURE"}


def test_v40_boosts_only_finishable_day_6_or_8_cow_tasks(monkeypatch) -> None:
    monkeypatch.setattr(v40, "ENABLE_LATE_COW_COMPLETION", True)
    farm = {"tiles": [[{}, _pasture(), {}, {}]]}
    tasks = [
        {"pos": (0, 0), "action": ["PICKUP", "COW", 1], "unit": 0, "label": "pickup-COW", "priority": 11600},
        {"pos": (1, 0), "action": ["PLACE", "COW"], "unit": 1, "label": "place-COW", "priority": 13600},
        {"pos": (0, 0), "action": ["PICKUP", "SHEEP", 1], "unit": 2, "label": "pickup-SHEEP", "priority": 11600},
    ]
    result = v40._prioritize_finishable_cows(
        {"day": 6, "hour": 20}, farm, [(0, 0), (1, 0), (0, 0)], tasks
    )
    assert result[0]["priority"] == v40.PICKUP_PRIORITY
    assert result[1]["priority"] == v40.PLACE_PRIORITY
    assert result[2]["priority"] == 11600


def test_v40_preserves_time_and_day_gates(monkeypatch) -> None:
    monkeypatch.setattr(v40, "ENABLE_LATE_COW_COMPLETION", True)
    farm = {"tiles": [[{}, {}, {}, _pasture()]]}
    task = {
        "pos": (0, 0),
        "action": ["PICKUP", "COW", 1],
        "unit": 0,
        "label": "pickup-COW",
        "priority": 11600,
    }
    assert v40._prioritize_finishable_cows(
        {"day": 6, "hour": 17}, farm, [(0, 0)], [task]
    )[0]["priority"] == 11600
    assert v40._prioritize_finishable_cows(
        {"day": 7, "hour": 20}, farm, [(0, 0)], [task]
    )[0]["priority"] == 11600
    assert v40._prioritize_finishable_cows(
        {"day": 6, "hour": 22}, farm, [(0, 0)], [task]
    )[0]["priority"] == 11600


def test_v40_wrapper_runs_safe_executor_first(monkeypatch) -> None:
    calls = []

    def safe(*args):
        calls.append(args)
        return ([{"pos": (0, 0), "action": ["PASS"], "priority": 0}], set())

    monkeypatch.setattr(v40, "_SAFE_FIELD_TASKS", safe)
    tasks, reserved = v40._field_tasks(
        {"day": 6, "hour": 20},
        {"tiles": [[{}]]},
        {},
        [(0, 0)],
        [{}],
        {},
        {},
        {},
        0,
    )
    assert calls
    assert tasks[0]["action"] == ["PASS"]
    assert reserved == set()


def test_v40_submission_is_self_contained(tmp_path: Path) -> None:
    assert v40.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v40" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v40" / entry["source"]).resolve()
        shutil.copyfile(source, submission / entry["target"])

    code = """
import os
import sys
from pathlib import Path
submission = Path(sys.argv[1]).resolve()
os.chdir(sys.argv[2])
sys.path.append(str(submission))
namespace = {}
main_path = submission / "main.py"
exec(compile(main_path.read_text(encoding="utf-8"), str(main_path), "exec"), namespace)
assert namespace["MODULE_DIR"] == submission
assert namespace["v14"].WINNER_MODEL is not None
assert namespace["v10"]._field_tasks is namespace["_field_tasks"]
assert namespace["v14"].v11.v10.MODEL is not None
assert set(namespace["agent"]({})) == {"farmer", "hands", "market"}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
