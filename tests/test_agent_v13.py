from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v13 import main as v13


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
            "seeds": {crop: 0 for crop in v13.CROPS},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10_000 for item in products},
            "prices": dict(v13.base.BASE_PRICE),
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


def baseline_targets() -> tuple[dict, dict, int, int, dict, int]:
    return (
        {"GOOSE": 0, "COW": 10, "SHEEP": 4},
        {"WHEAT": 30, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 20, "MELON": 9},
        12,
        3,
        {},
        14,
    )


def profile(**updates: float) -> dict[str, dict[str, float]]:
    values = {
        "WHEAT": 20.0,
        "CARROT": 0.0,
        "TOMATO": 0.0,
        "STRAWBERRY": 34.0,
        "MELON": 9.0,
        "COW": 7.0,
        "SHEEP": 3.0,
    }
    values.update(updates)
    return {"h24": dict(values), "h72": dict(values)}


def test_v13_model_is_compatible_and_predictions_are_finite() -> None:
    assert v13.CRITIC is not None
    assert v13.CRITIC["enabled"]
    features = [0.0] * len(v13.ACTION_FEATURE_NAMES)
    values, uncertainty = v13._critic_prediction(features)
    assert len(values) == 3
    assert all(value == value for value in (*values, uncertainty))
    assert uncertainty >= 0


def test_v13_candidate_requires_horizon_value_and_confidence(monkeypatch) -> None:
    obs = make_obs()
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    baseline = v13._baseline_profile(*baseline_targets()[:2])
    candidate = profile()
    critic = {
        "profiles": {"branch": {"rank2": {"profile": candidate}}},
        "uncertainty_p90": 0.5,
    }
    monkeypatch.setattr(v13, "ENABLE_RELATIVE_CRITIC", True)
    monkeypatch.setattr(v13, "CRITIC", critic)
    monkeypatch.setattr(v13.v8, "_expert_prediction", lambda *_args: ({}, {}, 0.8, 0.1))
    monkeypatch.setattr(v13.v12, "_relative_context", lambda *_args: {"key": "branch"})
    calls = iter([([0.0, 0.0, 0.0], 0.1), ([0.1, 0.2, 0.3], 0.1)])
    monkeypatch.setattr(v13, "_critic_prediction", lambda *_args: next(calls))
    decision = v13._candidate_decision(obs, farm, opponent, private, baseline)
    assert decision["active"]
    assert decision["selected"]["expert"] == "rank2"

    monkeypatch.setattr(v13.v8, "_expert_prediction", lambda *_args: ({}, {}, 0.2, 0.1))
    assert not v13._candidate_decision(obs, farm, opponent, private, baseline)["active"]


def test_v13_projects_only_macro_targets_and_preserves_capacity(monkeypatch) -> None:
    obs = make_obs()
    for index in range(11):
        obs["farms"][0]["tiles"][index // 10][index % 10] = plant("STRAWBERRY")
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    monkeypatch.setattr(v13.v11, "_strategy_targets", lambda *_args: deepcopy(baseline_targets()))
    monkeypatch.setattr(
        v13,
        "_candidate_decision",
        lambda *_args: {"active": True, "selected": {"profile": profile()}},
    )
    animals, crops, hands, land, weights, pastures = v13._strategy_targets(obs, farm, opponent, private)
    assert animals == {"GOOSE": 0, "COW": 7, "SHEEP": 3}
    assert crops == {
        "WHEAT": 20,
        "CARROT": 0,
        "TOMATO": 0,
        "STRAWBERRY": 34,
        "MELON": 9,
    }
    assert sum(animals.values()) + sum(crops.values()) == 73
    assert (hands, land, weights, pastures) == (12, 3, {}, 10)


def test_v13_agent_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v13.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v13.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v13" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v13" / entry["source"]).resolve()
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
assert namespace["CRITIC"] is not None
assert namespace["v12"].RELATIVE_POLICY is not None
assert namespace["v11"].v10.MODEL is not None
assert set(namespace["agent"]({})) == {"farmer", "hands", "market"}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
