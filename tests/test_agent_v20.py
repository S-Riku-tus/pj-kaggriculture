from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v20 import main as v20


def make_obs(*, day: int = 10, hour: int = 9, hands: int = 0, seat: int = 0) -> dict:
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

    farms = [farm(5_000), farm(10_000)]
    if seat == 1:
        farms.reverse()
    return {
        "player": seat,
        "step": day * 24 + hour,
        "day": day,
        "hour": hour,
        "farms": farms,
        "private": {
            "shed": {item: 0 for item in (*products, "GOOSE", "COW", "SHEEP")},
            "seeds": {crop: 0 for crop in v20.v14.CROPS},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10_000 for item in products},
            "prices": dict(v20.base.BASE_PRICE),
        },
        "town": {"unlocked_shops": ["BRUNCH_SPOT", "SMOOTHIE_SHOP"]},
    }


def test_v20_model_requires_both_horizons() -> None:
    assert v20.COW_MODEL is not None
    assert v20.COW_MODEL["enabled"]
    assert v20.COW_MODEL["horizons"] == ["h24", "h72"]
    assert v20.COW_MODEL["animal"] == "COW"
    assert v20.COW_MODEL["feature_names"][-2:] == ["hour", "seat"]
    assert set(v20.COW_MODEL["forests"]) == {"h24", "h72"}


def test_v20_freezes_only_when_both_models_are_supported(monkeypatch) -> None:
    obs = make_obs(seat=1)
    farm, opponent = obs["farms"][1], obs["farms"][0]
    monkeypatch.setattr(v20, "ENABLE_MULTIHORIZON_COW_GATE", True)
    monkeypatch.setattr(v20, "_profile_confidence", lambda *_args: (0.8, 0.2))
    monkeypatch.setattr(v20, "_predict_forest", lambda *_args: (1.0, 0.1))
    prediction = v20._cow_gate_prediction(obs, farm, opponent)
    assert prediction["decision"] == "freeze-owned"
    assert prediction["seat"] == 1
    assert all(value["supported"] for value in prediction["horizons"].values())

    values = iter(((1.0, 0.1), (-1.0, 0.1)))
    monkeypatch.setattr(v20, "_predict_forest", lambda *_args: next(values))
    prediction = v20._cow_gate_prediction(obs, farm, opponent)
    assert prediction["decision"] == "v11-herd"


def test_v20_changes_cow_only(monkeypatch) -> None:
    obs = make_obs(hands=1)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    farm["tiles"][0][0] = {"kind": "PASTURE", "animal": "COW"}
    farm["tiles"][0][1] = {"kind": "PASTURE", "animal": "SHEEP"}
    farm["tiles"][0][2] = {"kind": "PASTURE"}
    private["shed"]["COW"] = 1
    crops = {"WHEAT": 30, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 20, "MELON": 9}
    baseline = ({"GOOSE": 0, "COW": 10, "SHEEP": 4}, crops, 12, 3, {}, 14)
    monkeypatch.setattr(v20, "_SAFE_STRATEGY_TARGETS", lambda *_args: deepcopy(baseline))
    monkeypatch.setattr(
        v20,
        "_cow_gate_prediction",
        lambda *_args: {"active": True, "decision": "freeze-owned"},
    )
    animals, selected_crops, hands, land, weights, pastures = v20._strategy_targets(obs, farm, opponent, private)
    assert animals == {"GOOSE": 0, "COW": 2, "SHEEP": 4}
    assert selected_crops == crops
    assert (hands, land, weights, pastures) == (12, 3, {}, 6)


def test_v20_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    assert not v20.ENABLE_MULTIHORIZON_COW_GATE
    assert v20.v14._strategy_targets is v20._strategy_targets
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v20.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v20.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v20" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v20" / entry["source"]).resolve()
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
assert namespace["COW_MODEL"] is not None
assert namespace["v19"].HERD_MODEL is not None
assert namespace["v18"].HERD_MODEL is not None
assert namespace["v14"].WINNER_MODEL is not None
assert namespace["v14"]._strategy_targets is namespace["_strategy_targets"]
assert set(namespace["agent"]({})) == {"farmer", "hands", "market"}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
