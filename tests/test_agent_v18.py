from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v18 import main as v18


def make_obs(*, day: int = 10, hour: int = 9, hands: int = 0) -> dict:
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
            "seeds": {crop: 0 for crop in v18.v14.CROPS},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10_000 for item in products},
            "prices": dict(v18.base.BASE_PRICE),
        },
        "town": {"unlocked_shops": ["BRUNCH_SPOT", "SMOOTHIE_SHOP"]},
    }


def test_v18_model_matches_intraday_runtime_schema() -> None:
    assert v18.HERD_MODEL is not None
    assert v18.HERD_MODEL["enabled"]
    assert v18.HERD_MODEL["feature_names"][-1] == "hour"
    assert len(v18.HERD_MODEL["feature_names"]) == len(v18.v3.FEATURE_NAMES) + 1
    assert v18.HERD_MODEL["training"]["episode_split"] == {
        "test": 78,
        "train": 243,
        "validation": 78,
    }
    assert v18.HERD_MODEL["training"]["rows"] == 44_688
    assert set(v18.HERD_MODEL["profiles"]) == {
        "6-9",
        "10-11",
        "12-13",
        "14-17",
        "18-19",
    }


def test_v18_gate_uses_hour_profile_and_uncertainty(monkeypatch) -> None:
    obs = make_obs(hour=9)
    farm, opponent = obs["farms"]
    monkeypatch.setattr(v18, "ENABLE_INTRADAY_HERD_GATE", True)
    monkeypatch.setattr(v18, "_profile_confidence", lambda *_args: (0.8, 0.2))
    monkeypatch.setattr(v18, "_predict_forest", lambda *_args: (1.0, 0.1))
    prediction = v18._herd_gate_prediction(obs, farm, opponent)
    assert prediction["active"]
    assert prediction["decision"] == "freeze-owned"

    monkeypatch.setattr(v18, "_predict_forest", lambda *_args: (1.0, 99.0))
    prediction = v18._herd_gate_prediction(obs, farm, opponent)
    assert not prediction["active"]
    assert prediction["reason"] == "uncertain"

    monkeypatch.setattr(v18, "_profile_confidence", lambda *_args: (0.0, 99.0))
    prediction = v18._herd_gate_prediction(obs, farm, opponent)
    assert not prediction["active"]
    assert prediction["reason"] == "ood"


def test_v18_freezes_all_owned_animals_without_changing_other_targets(monkeypatch) -> None:
    obs = make_obs(hands=1)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    farm["tiles"][0][0] = {"kind": "PASTURE", "animal": "COW"}
    farm["tiles"][0][1] = {"kind": "PASTURE", "animal": "SHEEP"}
    farm["tiles"][0][2] = {"kind": "PASTURE"}
    private["shed"]["COW"] = 1
    private["inventories"][0]["SHEEP"] = 1
    crops = {"WHEAT": 30, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 20, "MELON": 9}
    baseline = ({"GOOSE": 0, "COW": 10, "SHEEP": 4}, crops, 12, 3, {}, 14)
    monkeypatch.setattr(v18, "_SAFE_STRATEGY_TARGETS", lambda *_args: deepcopy(baseline))
    monkeypatch.setattr(
        v18,
        "_herd_gate_prediction",
        lambda *_args: {"active": True, "decision": "freeze-owned"},
    )
    animals, selected_crops, hands, land, weights, pastures = v18._strategy_targets(obs, farm, opponent, private)
    assert animals == {"GOOSE": 0, "COW": 2, "SHEEP": 2}
    assert selected_crops == crops
    assert (hands, land, weights, pastures) == (12, 3, {}, 4)


def test_v18_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    assert not v18.ENABLE_INTRADAY_HERD_GATE
    assert v18.v14._strategy_targets is v18._strategy_targets
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v18.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v18.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v18" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v18" / entry["source"]).resolve()
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
assert namespace["HERD_MODEL"] is not None
assert namespace["v14"].WINNER_MODEL is not None
assert namespace["v11"].v10.MODEL is not None
assert namespace["v14"]._strategy_targets is namespace["_strategy_targets"]
assert set(namespace["agent"]({})) == {"farmer", "hands", "market"}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
