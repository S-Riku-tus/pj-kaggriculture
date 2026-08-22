from __future__ import annotations

import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v4.main import (
    MODEL,
    _assign_tasks,
    _market_plan,
    _strategy_targets,
    _water_is_useful,
    agent,
)

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
ANIMALS = ("GOOSE", "COW", "SHEEP")


def make_obs(
    *,
    day: int = 0,
    hour: int = 0,
    hands: int = 0,
    money: float = 3000,
    unlocked: int = 1,
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


def _animal(animal: str, day: int = 0) -> dict:
    return {
        "kind": "PASTURE",
        "animal": animal,
        "placed_day": day,
        "yield_units": 0,
        "consecutive_unfed": 0,
        "fed_today": False,
        "cared_today": False,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }


def test_v4_keeps_v3_model_and_opening_without_mutating_observation() -> None:
    assert MODEL is not None
    obs = make_obs()
    before = deepcopy(obs)
    action = agent(obs)
    assert obs == before
    assert action["farmer"] == ["BUILD_PASTURE"]
    assert len(action["market"]) == 10


def test_v4_targets_top_scale_and_blocks_late_long_horizon_reinvestment() -> None:
    obs = make_obs(day=20, hands=10, unlocked=3)
    animals, crops, hands, land, _weights, pastures = _strategy_targets(
        obs, obs["farms"][0], obs["farms"][1], obs["private"]
    )
    assert animals["COW"] >= 9
    assert animals["SHEEP"] >= 6
    assert crops["MELON"] == 0
    assert crops["STRAWBERRY"] == 0
    assert hands >= 11
    assert land == 3
    assert pastures >= animals["COW"] + animals["SHEEP"]


def test_v4_waters_for_survival_or_yield_not_every_day() -> None:
    ordinary = {
        "kind": "PLANT",
        "crop": "STRAWBERRY",
        "planted_day": 5,
        "watered_today": False,
        "consecutive_unwatered": 0,
        "yield_units": 0,
        "fertilized_until_day": -1,
    }
    assert not _water_is_useful(ordinary, 8)
    ordinary["consecutive_unwatered"] = 1
    assert _water_is_useful(ordinary, 8)


def test_v4_assignment_finishes_local_animal_work_before_distant_travel() -> None:
    positions = [(0, 0)]
    inventories = [{"WHEAT": 1}]
    tasks = [
        {"pos": (0, 0), "action": ["CARE"], "priority": 9000, "required": None, "unit": None, "label": "care"},
        {"pos": (5, 0), "action": ["FEED"], "priority": 11000, "required": "WHEAT", "unit": None, "label": "feed"},
    ]
    assert _assign_tasks(positions, inventories, tasks) == [["CARE"]]


def test_v4_animal_purchase_is_backed_by_pasture_capacity() -> None:
    obs = make_obs(day=12, hands=11, money=10000, unlocked=3)
    farm = obs["farms"][0]
    for index, animal in enumerate(("COW", "COW", "SHEEP", "SHEEP")):
        farm["tiles"][index][0] = _animal(animal)
    obs["private"]["shed"]["WHEAT"] = 50
    summary = __import__("agents.v4.main", fromlist=["base"]).base._farm_summary(farm)
    common = dict(
        obs=obs,
        farm=farm,
        private=obs["private"],
        summary=summary,
        animal_targets={"GOOSE": 0, "COW": 7, "SHEEP": 5},
        crop_targets={"WHEAT": 20, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 20, "MELON": 0},
        target_hands=11,
        target_land=3,
        weights={"rank1": 0.5, "rank2": 0.3, "rank3": 0.2},
        pasture_target=12,
        reserved=set(),
    )
    no_build = _market_plan(actions=[["PASS"]], **common)
    one_build = _market_plan(actions=[["BUILD_PASTURE"]], **common)
    assert not any(order[0] == "BUY_ANIMAL" for order in no_build)
    assert sum(order[2] for order in one_build if order[0] == "BUY_ANIMAL") <= 1


def test_v4_missing_observation_fails_closed() -> None:
    assert agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}


def test_v4_submission_resolves_all_packaged_helpers_from_another_cwd(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    for source, target in (
        (root / "agents" / "v4" / "main.py", "main.py"),
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
