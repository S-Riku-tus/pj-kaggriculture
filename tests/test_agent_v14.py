from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v14 import main as v14


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

    def farm(money: int) -> dict:
        return {
            "money": money,
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
        "farms": [farm(5_000), farm(10_000)],
        "private": {
            "shed": {item: 0 for item in (*products, "GOOSE", "COW", "SHEEP")},
            "seeds": {crop: 0 for crop in v14.CROPS},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10_000 for item in products},
            "prices": dict(v14.base.BASE_PRICE),
        },
        "town": {"unlocked_shops": ["BRUNCH_SPOT", "SMOOTHIE_SHOP"]},
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


def recovery_prediction() -> dict:
    return {
        "active": True,
        "reason": "active",
        "confidence": 1.0,
        "h72": {
            "WHEAT": 20.0,
            "CARROT": 10.0,
            "TOMATO": 0.0,
            "STRAWBERRY": 34.0,
            "MELON": 0.0,
            "COW": 7.0,
            "SHEEP": 3.0,
        },
    }


def test_v14_model_is_compatible_and_h24_is_not_selected() -> None:
    assert v14.WINNER_MODEL is not None
    assert v14.WINNER_MODEL["enabled"]
    assert v14.WINNER_MODEL["selection"] == {
        "h24": False,
        "h72_recovery": True,
        "controls": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"],
        "recovery_definition": "observable money_gap_ratio < 0",
    }
    values, deviations = v14._predict_forest(
        v14.WINNER_MODEL["forests"]["h72"],
        [0.0] * len(v14.v3.FEATURE_NAMES),
    )
    assert len(values) == len(deviations) == 7
    assert all(value == value for value in (*values, *deviations))


def test_v14_prediction_requires_recovery_confidence_and_uncertainty(monkeypatch) -> None:
    obs = make_obs()
    farm, opponent = obs["farms"]
    monkeypatch.setattr(v14, "_distance_confidence", lambda *_args: (0.9, 0.2))
    monkeypatch.setattr(
        v14,
        "_predict_forest",
        lambda *_args: ([10.0] * 7, [0.01] * 7),
    )
    prediction = v14._winner_prediction(obs, farm, opponent)
    assert prediction["active"]
    assert prediction["money_gap_ratio"] < 0

    farm["money"] = opponent["money"]
    prediction = v14._winner_prediction(obs, farm, opponent)
    assert not prediction["active"]
    assert prediction["reason"] == "not-behind"


def test_v14_projection_preserves_feasibility_and_v11_resources(monkeypatch) -> None:
    obs = make_obs()
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    monkeypatch.setattr(v14.v11, "_strategy_targets", lambda *_args: deepcopy(baseline_targets()))
    monkeypatch.setattr(v14, "_winner_prediction", lambda *_args: recovery_prediction())
    animals, crops, hands, land, weights, pastures = v14._strategy_targets(obs, farm, opponent, private)
    assert animals == {"GOOSE": 0, "COW": 10, "SHEEP": 4}
    assert crops == {
        "WHEAT": 26,
        "CARROT": 2,
        "TOMATO": 0,
        "STRAWBERRY": 25,
        "MELON": 6,
    }
    assert sum(animals.values()) + sum(crops.values()) == 73
    assert crops["WHEAT"] >= 16
    assert (hands, land, weights, pastures) == (12, 3, {}, 14)


def test_v14_agent_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v14.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v14.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v14" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v14" / entry["source"]).resolve()
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
assert namespace["WINNER_MODEL"] is not None
assert namespace["v11"].v10.MODEL is not None
assert set(namespace["agent"]({})) == {"farmer", "hands", "market"}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
