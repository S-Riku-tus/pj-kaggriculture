from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v16 import main as v16


def test_v16_raises_only_capital_window_water_priority(monkeypatch) -> None:
    monkeypatch.setattr(v16, "ENABLE_CAPITAL_WATER", True)
    farm = {
        "tiles": [
            [{"crop": "MELON"}, {"crop": "STRAWBERRY"}],
        ]
    }
    tasks = [
        {"pos": (0, 0), "action": ["WATER"], "priority": 10_600, "label": "water"},
        {"pos": (0, 0), "action": ["FEED"], "priority": 12_100, "label": "feed"},
        {
            "pos": (1, 0),
            "action": ["WATER"],
            "priority": 10_600,
            "label": "strawberry-water",
        },
        {
            "pos": (0, 0),
            "action": ["WATER"],
            "priority": 15_100,
            "label": "emergency-water",
        },
    ]
    before = deepcopy(tasks)
    result = v16._raise_capital_water(tasks, 6, farm)
    assert [task["priority"] for task in result] == [12_000, 12_100, 10_600, 15_100]
    assert tasks == before
    assert v16._raise_capital_water(tasks, 5, farm) is tasks
    assert v16._raise_capital_water(tasks, 11, farm) is tasks


def test_v16_disable_restores_safe_core(monkeypatch) -> None:
    tasks = [{"pos": (0, 0), "action": ["WATER"], "priority": 10_600}]
    farm = {"tiles": [[{"crop": "MELON"}]]}
    monkeypatch.setattr(v16, "ENABLE_CAPITAL_WATER", False)
    assert v16._raise_capital_water(tasks, 8, farm) is tasks


def test_v16_installs_stable_v11_execution_wrapper() -> None:
    assert not v16.ENABLE_CAPITAL_WATER
    assert v16.v11._field_tasks is v16._field_tasks
    assert v16._SAFE_FIELD_TASKS is not v16._field_tasks
    assert v16.policy_diagnostics({})["v16_capital_water"] == {
        "active": False,
        "priority": 12_000,
        "crops": ["MELON"],
        "window": [6, 10],
    }


def test_v16_submission_is_self_contained(tmp_path: Path) -> None:
    assert v16.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v16" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v16" / entry["source"]).resolve()
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
assert namespace["v11"]._field_tasks is namespace["_field_tasks"]
assert namespace["v11"].v10.MODEL is not None
assert set(namespace["agent"]({})) == {"farmer", "hands", "market"}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
