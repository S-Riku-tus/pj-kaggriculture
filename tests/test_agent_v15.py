from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v15 import main as v15


def _farm_with_unfed_animals(count: int) -> dict:
    tiles = [[None for _x in range(10)] for _y in range(10)]
    for index in range(count):
        tiles[index // 10][index % 10] = {"animal": "COW", "fed_today": False}
    return {"tiles": tiles}


def _pickup_tasks(count: int, amount: int = 3) -> list[dict]:
    return [
        {
            "pos": (4, 4),
            "action": ["PICKUP", "WHEAT", amount],
            "priority": 12_600,
            "unit": index,
            "label": "pickup-wheat",
        }
        for index in range(count)
    ]


def test_v15_reduces_load_without_removing_carriers(monkeypatch) -> None:
    monkeypatch.setattr(v15, "ENABLE_DISTRIBUTED_WHEAT", True)
    tasks = _pickup_tasks(4)
    before = deepcopy(tasks)
    result = v15._distribute_wheat_pickups(
        tasks,
        _farm_with_unfed_animals(5),
        {"shed": {"WHEAT": 50}},
        [{"WHEAT": 1}, {}, {}, {}],
    )
    loads = [task["action"][2] for task in result]
    assert len(result) == len(tasks) == 4
    assert sum(loads) == 5
    assert min(loads) >= 1
    assert max(loads) <= 3
    assert tasks == before


def test_v15_falls_back_if_stock_cannot_cover_carriers(monkeypatch) -> None:
    tasks = _pickup_tasks(4)
    assert (
        v15._distribute_wheat_pickups(
            tasks,
            _farm_with_unfed_animals(5),
            {"shed": {"WHEAT": 3}},
            [{}, {}, {}, {}],
        )
        is tasks
    )
    monkeypatch.setattr(v15, "ENABLE_DISTRIBUTED_WHEAT", False)
    assert (
        v15._distribute_wheat_pickups(
            tasks,
            _farm_with_unfed_animals(5),
            {"shed": {"WHEAT": 50}},
            [{}, {}, {}, {}],
        )
        is tasks
    )


def test_v15_handles_malformed_pickup_action(monkeypatch) -> None:
    monkeypatch.setattr(v15, "ENABLE_DISTRIBUTED_WHEAT", True)
    tasks = _pickup_tasks(1)
    tasks[0]["action"] = ["PICKUP"]
    result = v15._distribute_wheat_pickups(
        tasks,
        _farm_with_unfed_animals(1),
        {"shed": {"WHEAT": 2}},
        [{}],
    )
    assert result[0]["action"] == ["PICKUP", "WHEAT", 1]


def test_v15_agent_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    assert not v15.ENABLE_DISTRIBUTED_WHEAT
    obs = {
        "player": 0,
        "step": 240,
        "day": 10,
        "hour": 0,
        "farms": [
            {
                "money": 5_000,
                "tiles": [[None for _x in range(10)] for _y in range(10)],
                "farmer": [4, 4],
                "hands": [],
                "unlocked_quadrants": ["NW", "NE", "SW"],
                "hires_today": 0,
            },
            {
                "money": 10_000,
                "tiles": [[None for _x in range(10)] for _y in range(10)],
                "farmer": [4, 4],
                "hands": [],
                "unlocked_quadrants": ["NW", "NE", "SW"],
                "hires_today": 0,
            },
        ],
        "private": {"shed": {"WHEAT": 0}, "seeds": {}, "inventories": [{}]},
        "market": {"inventory": {}, "prices": {}},
        "town": {"unlocked_shops": []},
    }
    before = deepcopy(obs)
    action = v15.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert v15.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v15" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v15" / entry["source"]).resolve()
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
assert namespace["v11"].v10.MODEL is not None
assert set(namespace["agent"]({})) == {"farmer", "hands", "market"}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
