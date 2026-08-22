from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from agents.v5.main import (
    MODEL,
    _assign_tasks,
    _bounded_animal_mix,
    _collapse_animal_missions,
    _field_tasks,
    agent,
)


def make_obs(*, day: int = 5, hour: int = 12, hands: int = 4, unlocked: int = 2) -> dict:
    quadrants = ["NW", "NE", "SW", "SE"][:unlocked]

    def farm() -> dict:
        tiles = []
        for y in range(10):
            row = []
            for x in range(10):
                quadrant = "NW" if x < 5 and y < 5 else ("NE" if y < 5 else ("SW" if x < 5 else "SE"))
                row.append(None if quadrant in quadrants else "LOCKED")
            tiles.append(row)
        return {
            "money": 5000,
            "tiles": tiles,
            "farmer": [4, 4],
            "hands": [[4, 4] for _ in range(hands)],
            "unlocked_quadrants": quadrants,
            "hires_today": hands,
        }

    products = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
    return {
        "player": 0,
        "step": day * 24 + hour,
        "day": day,
        "hour": hour,
        "farms": [farm(), farm()],
        "private": {
            "shed": {item: 0 for item in (*products, "GOOSE", "COW", "SHEEP")},
            "seeds": {crop: 0 for crop in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10000 for item in products},
            "prices": {
                "WHEAT": 25,
                "CARROT": 35,
                "TOMATO": 60,
                "STRAWBERRY": 120,
                "MELON": 250,
                "EGG": 50,
                "MILK": 160,
                "WOOL": 200,
                "FERTILIZER": 100,
            },
        },
        "town": {"unlocked_shops": []},
    }


def test_v5_preserves_model_and_fails_closed() -> None:
    assert MODEL is not None
    assert agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}


def test_v5_animal_projection_preserves_adaptive_ratios() -> None:
    milk_heavy = _bounded_animal_mix(
        day=16,
        learned={"GOOSE": 0, "COW": 12, "SHEEP": 2},
        economic={"GOOSE": 0, "COW": 14, "SHEEP": 2},
        owned_cow=2,
        owned_sheep=2,
    )
    wool_heavy = _bounded_animal_mix(
        day=16,
        learned={"GOOSE": 0, "COW": 6, "SHEEP": 9},
        economic={"GOOSE": 0, "COW": 5, "SHEEP": 9},
        owned_cow=2,
        owned_sheep=2,
    )
    assert milk_heavy["COW"] >= 11
    assert milk_heavy["SHEEP"] <= 3
    assert wool_heavy["SHEEP"] > wool_heavy["COW"]
    assert sum(milk_heavy.values()) <= 15
    assert sum(wool_heavy.values()) <= 15


def test_v5_freezes_animal_investment_after_purchase_horizon() -> None:
    targets = _bounded_animal_mix(
        day=21,
        learned={"GOOSE": 0, "COW": 15, "SHEEP": 8},
        economic={"GOOSE": 0, "COW": 14, "SHEEP": 9},
        owned_cow=7,
        owned_sheep=4,
    )
    assert targets == {"GOOSE": 0, "COW": 7, "SHEEP": 4}


def test_v5_blocks_hour_23_plant_tasks(monkeypatch) -> None:
    obs = make_obs(hour=23)
    synthetic = [
        {"pos": (0, 0), "action": ["PLANT", "WHEAT"], "priority": 1},
        {"pos": (1, 0), "action": ["CARE"], "priority": 1},
    ]
    monkeypatch.setattr("agents.v5.main.v4._field_tasks", lambda *args, **kwargs: (synthetic, set()))
    tasks, _reserved = _field_tasks(
        obs,
        obs["farms"][0],
        obs["private"],
        [(4, 4)],
        [{}],
        {},
        {"GOOSE": 0, "COW": 2, "SHEEP": 2},
        {"WHEAT": 10, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 4, "MELON": 11},
        4,
    )
    assert [task["action"][0] for task in tasks] == ["CARE"]


def test_v5_exposes_one_sequential_animal_service_step_per_tile() -> None:
    tasks = [
        {"pos": (1, 1), "action": ["CARE"], "priority": 10000, "label": "care"},
        {"pos": (1, 1), "action": ["FEED"], "priority": 12100, "label": "feed"},
        {
            "pos": (1, 1),
            "action": ["COLLECT_FERTILIZER"],
            "priority": 11300,
            "label": "collect-fertilizer",
        },
        {"pos": (2, 2), "action": ["DIG"], "priority": 8000, "label": "dig-weed"},
    ]
    collapsed = _collapse_animal_missions(tasks)
    assert [task["action"][0] for task in collapsed].count("FEED") == 1
    assert not any(task["action"][0] == "CARE" for task in collapsed)
    assert any(task["action"][0] == "DIG" for task in collapsed)


def test_v5_keeps_worker_on_local_animal_mission() -> None:
    positions = [(0, 0)]
    inventories = [{"WHEAT": 1}]
    tasks = [
        {"pos": (0, 0), "action": ["CARE"], "priority": 10000, "required": None, "unit": None, "label": "care"},
        {
            "pos": (5, 0),
            "action": ["FEED"],
            "priority": 15400,
            "required": "WHEAT",
            "unit": None,
            "label": "feed",
        },
    ]
    assert _assign_tasks(positions, inventories, tasks) == [["CARE"]]


def test_v5_submission_resolves_nested_helpers_from_another_cwd(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    for source, target in (
        (root / "agents" / "v5" / "main.py", "main.py"),
        (root / "agents" / "v4" / "main.py", "v4_base.py"),
        (root / "agents" / "v3" / "main.py", "v3_base.py"),
        (root / "agents" / "v2" / "main.py", "v2_base.py"),
        (root / "agents" / "v3" / "feature_schema.py", "feature_schema.py"),
        (root / "agents" / "v3" / "strategy_model.json", "strategy_model.json"),
    ):
        shutil.copyfile(source, submission / target)

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
assert namespace["MODEL"] is not None
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
