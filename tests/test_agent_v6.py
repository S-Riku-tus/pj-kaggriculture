from __future__ import annotations

import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v6.main import MODEL, _field_tasks, _market_plan, _strategy_targets, agent

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
ANIMALS = ("GOOSE", "COW", "SHEEP")


def make_obs(
    *,
    day: int = 6,
    hour: int = 12,
    hands: int = 7,
    unlocked: int = 2,
    money: float = 5000,
) -> dict:
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
            "money": money,
            "tiles": tiles,
            "farmer": [4, 4],
            "hands": [[4, 4] for _ in range(hands)],
            "unlocked_quadrants": quadrants,
            "hires_today": hands,
        }

    return {
        "player": 0,
        "step": day * 24 + hour,
        "day": day,
        "hour": hour,
        "farms": [farm(), farm()],
        "private": {
            "shed": {item: 0 for item in (*PRODUCTS, *ANIMALS)},
            "seeds": {crop: 0 for crop in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10000 for item in PRODUCTS},
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


def test_v6_preserves_model_and_observation_purity() -> None:
    assert MODEL is not None
    obs = make_obs(day=0, hour=0, hands=0, unlocked=1, money=3000)
    before = deepcopy(obs)
    action = agent(obs)
    assert obs == before
    assert action["farmer"] == ["BUILD_PASTURE"]
    assert len(action["market"]) == 10
    assert agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}


def test_v6_advances_strawberry_target_before_day7_snapshot() -> None:
    obs = make_obs(day=6)
    _animals, crops, _hands, _land, _weights, _pastures = _strategy_targets(
        obs, obs["farms"][0], obs["farms"][1], obs["private"]
    )
    assert crops["STRAWBERRY"] >= 12


def test_v6_first_land_gate_accepts_wheat_recycle_dip(monkeypatch) -> None:
    captured = {}

    def synthetic_market(*args, **kwargs):
        captured["crop_targets"] = args[5]
        return [["BUY_LAND"]]

    monkeypatch.setattr("agents.v6.main.v4._market_plan", synthetic_market)
    common = dict(
        obs={"day": 5},
        farm={},
        private={"shed": {"WHEAT": 5}, "inventories": [], "seeds": {}},
        animal_targets={"GOOSE": 0, "COW": 3, "SHEEP": 2},
        crop_targets={"WHEAT": 8, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 12, "MELON": 0},
        target_hands=7,
        target_land=2,
        weights={},
        pasture_target=5,
        actions=[],
        reserved=set(),
    )
    accepted = _market_plan(
        summary={
            "unlocked": 1,
            "utilization": 0.62,
            "capacity": 25,
            "animal_total": 5,
            "crops": {"WHEAT": 0, "STRAWBERRY": 0},
        },
        **common,
    )
    blocked = _market_plan(
        summary={
            "unlocked": 1,
            "utilization": 0.40,
            "capacity": 25,
            "animal_total": 5,
            "crops": {"WHEAT": 0, "STRAWBERRY": 0},
        },
        **common,
    )
    assert accepted == [["BUY_LAND"]]
    assert blocked == []
    assert captured["crop_targets"]["WHEAT"] == 0


def test_v6_replaces_discretionary_wheat_tasks_with_early_strawberry(monkeypatch) -> None:
    obs = make_obs(day=6)
    obs["private"]["seeds"]["STRAWBERRY"] = 3
    synthetic = [
        {
            "pos": (x, 0),
            "action": ["PLANT", "WHEAT"],
            "priority": 9000,
            "required": None,
            "unit": None,
            "label": "plant-WHEAT",
        }
        for x in range(3)
    ]
    monkeypatch.setattr("agents.v6.main.v5._field_tasks", lambda *args, **kwargs: (synthetic, set()))
    tasks, _reserved = _field_tasks(
        obs,
        obs["farms"][0],
        obs["private"],
        [(4, 4)],
        [{}],
        {"crops": {crop: 0 for crop in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")}},
        {"GOOSE": 0, "COW": 2, "SHEEP": 2},
        {"WHEAT": 10, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 12, "MELON": 11},
        4,
    )
    plant_actions = [task["action"] for task in tasks if task["action"][0] == "PLANT"]
    assert plant_actions.count(["PLANT", "STRAWBERRY"]) == 3
    assert ["PLANT", "WHEAT"] not in plant_actions


def test_v6_submission_resolves_all_helpers_from_another_cwd(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    for source, target in (
        (root / "agents" / "v6" / "main.py", "main.py"),
        (root / "agents" / "v5" / "main.py", "v5_base.py"),
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
