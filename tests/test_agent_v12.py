from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v12 import main as v12


def make_obs(*, day: int = 10, hour: int = 0, hands: int = 0) -> dict:
    products = (
        "WHEAT",
        "CARROT",
        "TOMATO",
        "STRAWBERRY",
        "MELON",
        "EGG",
        "MILK",
        "WOOL",
        "FERTILIZER",
    )

    def farm() -> dict:
        return {
            "money": 10_000,
            "tiles": [[None for _x in range(10)] for _y in range(10)],
            "farmer": [4, 4],
            "hands": [[4, 4] for _ in range(hands)],
            "unlocked_quadrants": ["NW", "NE", "SW"],
            "hires_today": hands,
        }

    return {
        "player": 0,
        "step": day * 24 + hour,
        "day": day,
        "hour": hour,
        "farms": [farm(), farm()],
        "private": {
            "shed": {item: 0 for item in (*products, "GOOSE", "COW", "SHEEP")},
            "seeds": {crop: 0 for crop in v12.CROPS},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10_000 for item in products},
            "prices": dict(v12.base.BASE_PRICE),
        },
        "town": {"unlocked_shops": ["BRUNCH_SPOT", "SMOOTHIE_SHOP"]},
    }


def plant(crop: str, day: int = 1) -> dict:
    return {
        "kind": "PLANT",
        "crop": crop,
        "planted_day": day,
        "watered_today": True,
        "consecutive_unwatered": 0,
        "yield_units": 0,
        "fertilized_until_day": -1,
    }


def animal(kind: str = "COW", *, fed: bool, cared: bool = False, consecutive: int = 0) -> dict:
    return {
        "kind": "PASTURE",
        "animal": kind,
        "fed_today": fed,
        "cared_today": cared,
        "consecutive_unfed": consecutive,
        "yield_units": 0,
        "fertilizer_available": False,
    }


def baseline_targets() -> tuple[dict, dict, int, int, dict, int]:
    return (
        {"GOOSE": 0, "COW": 10, "SHEEP": 4},
        {"WHEAT": 30, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 20, "MELON": 9},
        12,
        3,
        {},
        14,
    )


def expert_prediction(confidence: float = 0.8) -> tuple[dict, dict, float, float]:
    targets = {target: 0.0 for target in v12.v8.TARGET_NAMES}
    return targets, targets, confidence, 0.2


def add_strawberries(obs: dict, count: int) -> None:
    for index in range(count):
        obs["farms"][0]["tiles"][index // 10][index % 10] = plant("STRAWBERRY")


def test_v12_relative_branch_is_supported_and_ood_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(v12, "ENABLE_RELATIVE_POLICY", True)
    obs = make_obs()
    add_strawberries(obs, 11)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    monkeypatch.setattr(v12.v8, "_expert_prediction", lambda *_args: expert_prediction())
    prediction = v12._relative_prediction(obs, farm, opponent, private)
    assert prediction["active"]
    assert prediction["expert"] == "rank2"

    obs["farms"][0]["tiles"] = [[None for _x in range(10)] for _y in range(10)]
    prediction = v12._relative_prediction(obs, farm, opponent, private)
    assert not prediction["active"]
    assert prediction["reason"] == "ood-own_focus"


def test_v12_changes_only_supported_macro_targets(monkeypatch) -> None:
    monkeypatch.setattr(v12, "ENABLE_RELATIVE_POLICY", True)
    obs = make_obs()
    add_strawberries(obs, 11)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    monkeypatch.setattr(v12.v11, "_strategy_targets", lambda *_args: deepcopy(baseline_targets()))
    monkeypatch.setattr(v12.v8, "_expert_prediction", lambda *_args: expert_prediction())

    animals, crops, hands, land, weights, pastures = v12._strategy_targets(obs, farm, opponent, private)
    assert animals == {"GOOSE": 0, "COW": 7, "SHEEP": 3}
    assert crops == {
        "WHEAT": 20,
        "CARROT": 0,
        "TOMATO": 0,
        "STRAWBERRY": 35,
        "MELON": 8,
    }
    assert sum(animals.values()) + sum(crops.values()) == 73
    assert (hands, land, weights, pastures) == (12, 3, {}, 10)


def test_v12_wheat_pickup_is_capped_by_observable_demand(monkeypatch) -> None:
    monkeypatch.setattr(v12, "ENABLE_WHEAT_BATCH_FIX", True)
    obs = make_obs(hands=3)
    farm, private = obs["farms"][0], obs["private"]
    for index in range(5):
        farm["tiles"][0][index] = animal(fed=False)
    private["shed"]["WHEAT"] = 50
    private["inventories"][0]["WHEAT"] = 1
    tasks = [
        {
            "pos": (4, 4),
            "action": ["PICKUP", "WHEAT", 3],
            "priority": 12_600,
            "label": "pickup-wheat",
            "unit": unit,
        }
        for unit in range(4)
    ]
    tasks.append({"pos": (0, 0), "action": ["WATER"], "priority": 10_000, "label": "water"})

    result = v12._rightsize_wheat_pickups(tasks, farm, private, private["inventories"])
    pickups = [task for task in result if task.get("label") == "pickup-wheat"]
    assert len(pickups) == 2
    assert sum(task["action"][2] for task in pickups) == 4
    assert any(task.get("label") == "water" for task in result)


def test_v12_local_care_yields_to_survival_emergency(monkeypatch) -> None:
    monkeypatch.setattr(v12, "ENABLE_LOCAL_ANIMAL_COMPLETION", True)
    obs = make_obs()
    farm = obs["farms"][0]
    farm["farmer"] = [0, 0]
    farm["tiles"][0][0] = animal(fed=True)
    assert v12._complete_local_animal_service(obs, farm, [(0, 0)], [["EAST"]]) == [["CARE"]]

    farm["tiles"][0][1] = animal(kind="SHEEP", fed=False, consecutive=1)
    assert v12._complete_local_animal_service(obs, farm, [(0, 0)], [["EAST"]]) == [["EAST"]]


def test_v12_agent_is_pure_and_submission_is_self_contained(monkeypatch, tmp_path: Path) -> None:
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v12.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v12.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v12" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v12" / entry["source"]).resolve()
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
assert namespace["RELATIVE_POLICY"] is not None
assert namespace["v11"].v10.MODEL is not None
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
