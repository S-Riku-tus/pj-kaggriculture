from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from agents.v43 import main as v43


def _farm() -> dict[str, object]:
    tiles = [[None for _ in range(10)] for _ in range(10)]
    return {"tiles": tiles, "unlocked_quadrants": ["NW", "NE"]}


def test_v43_relocates_protected_plants_without_reducing_count(monkeypatch) -> None:
    monkeypatch.setattr(v43, "ENABLE_NE_CORE_RESERVATION", True)
    farm = _farm()
    protected = sorted(v43._protected_ne_positions(10))
    tasks = [
        {"pos": protected[0], "action": ["PLANT", "STRAWBERRY"], "label": "plant-STRAWBERRY", "priority": 13500},
        {"pos": protected[1], "action": ["PLANT", "WHEAT"], "label": "plant-WHEAT", "priority": 8500},
    ]
    result = v43._relocate_core_plants({"day": 6}, farm, tasks, set())
    assert len(result) == len(tasks)
    assert not ({task["pos"] for task in result} & set(protected))
    assert [task["action"] for task in result] == [
        ["PLANT", "STRAWBERRY"],
        ["PLANT", "WHEAT"],
    ]


def test_v43_respects_day_land_and_current_pasture_reservations(monkeypatch) -> None:
    monkeypatch.setattr(v43, "ENABLE_NE_CORE_RESERVATION", True)
    farm = _farm()
    protected = sorted(v43._protected_ne_positions(10))
    task = {"pos": protected[0], "action": ["PLANT", "WHEAT"], "priority": 8500}
    assert v43._relocate_core_plants({"day": 9}, farm, [task], set()) == [task]
    farm["unlocked_quadrants"] = ["NW"]
    assert v43._relocate_core_plants({"day": 6}, farm, [task], set()) == [task]
    farm["unlocked_quadrants"] = ["NW", "NE"]
    result = v43._relocate_core_plants({"day": 6}, farm, [task], {(0, 0)})
    assert result[0]["pos"] != (0, 0)


def test_v43_wrapper_runs_safe_executor_first(monkeypatch) -> None:
    calls = []

    def safe(*args):
        calls.append(args)
        return ([{"pos": (0, 0), "action": ["PASS"], "priority": 0}], {(0, 0)})

    monkeypatch.setattr(v43, "_SAFE_FIELD_TASKS", safe)
    tasks, reserved = v43._field_tasks(
        {"day": 6},
        _farm(),
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
    assert reserved == {(0, 0)}


def test_v43_submission_is_self_contained(tmp_path: Path) -> None:
    assert v43.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v43" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v43" / entry["source"]).resolve()
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
