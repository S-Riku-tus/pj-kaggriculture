from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v101 import main as v101


def make_obs(*, day: int = 10, hands: int = 0, own_berry: int = 12, opponent_berry: int = 20) -> dict:
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

    def farm(money: int, berry: int) -> dict:
        tiles = [[None for _x in range(10)] for _y in range(10)]
        for index in range(berry):
            y, x = divmod(index, 10)
            tiles[y][x] = {
                "kind": "PLANT",
                "crop": "STRAWBERRY",
                "planted_day": 7,
                "watered_today": True,
                "yield_units": 0,
            }
        return {
            "money": money,
            "tiles": tiles,
            "farmer": [4, 4],
            "hands": [[4, 4] for _ in range(hands)],
            "unlocked_quadrants": ["NW", "NE", "SW", "SE"],
            "hires_today": hands,
        }

    return {
        "player": 0,
        "step": day * 24,
        "day": day,
        "hour": 0,
        "farms": [farm(5_000, own_berry), farm(10_000, opponent_berry)],
        "private": {
            "shed": {item: 0 for item in (*products, "GOOSE", "COW", "SHEEP")},
            "seeds": {crop: 0 for crop in v101.v14.CROPS},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10_000 for item in products},
            "prices": dict(v101.base.BASE_PRICE),
        },
        "town": {"unlocked_shops": ["PIZZA_SHOP"]},
    }


def baseline_targets() -> tuple[dict, dict, int, int, dict, int]:
    return (
        {"GOOSE": 0, "COW": 10, "SHEEP": 4},
        {"WHEAT": 30, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 30, "MELON": 9},
        12,
        3,
        {"rank1": 0.6, "rank2": 0.3, "rank3": 0.1},
        14,
    )


def enable_supported_branch(monkeypatch) -> None:
    monkeypatch.setattr(v101, "_SAFE_STRATEGY_TARGETS", lambda *_args: deepcopy(baseline_targets()))
    monkeypatch.setattr(v101.v8, "_expert_prediction", lambda *_args: ({}, {}, 0.9, 0.1))
    monkeypatch.setattr(
        v101.v3,
        "_expert_weights",
        lambda *_args: {"rank1": 0.6, "rank2": 0.3, "rank3": 0.1},
    )


def test_v101_caps_only_strawberry_in_supported_regime(monkeypatch) -> None:
    obs = make_obs()
    enable_supported_branch(monkeypatch)
    monkeypatch.setattr(v101, "ENABLE_EARLY_OPTIONALITY", True)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    baseline = baseline_targets()
    selected = v101._strategy_targets(obs, farm, opponent, private)
    assert selected[0] == baseline[0]
    assert selected[1] == {**baseline[1], "STRAWBERRY": 15}
    assert selected[2:] == baseline[2:]
    decision = v101._branch_decision(obs, farm, opponent, private, baseline[1])
    assert decision["active"]
    assert decision["changed"]
    assert decision["reason"] == "bounded-wait"
    assert decision["withheld_target"] == 15


def test_v101_never_removes_live_crops_and_falls_back(monkeypatch) -> None:
    obs = make_obs(own_berry=25)
    enable_supported_branch(monkeypatch)
    monkeypatch.setattr(v101, "ENABLE_EARLY_OPTIONALITY", True)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    selected = v101._strategy_targets(obs, farm, opponent, private)
    assert selected[1]["STRAWBERRY"] == 25

    monkeypatch.setattr(v101.v8, "_expert_prediction", lambda *_args: None)
    assert v101._strategy_targets(obs, farm, opponent, private) == baseline_targets()


def test_v101_preserves_strong_demand_and_rank3_regimes(monkeypatch) -> None:
    obs = make_obs()
    enable_supported_branch(monkeypatch)
    monkeypatch.setattr(v101, "ENABLE_EARLY_OPTIONALITY", True)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    obs["town"]["unlocked_shops"] = ["BRUNCH_SPOT", "SMOOTHIE_SHOP"]
    assert v101._strategy_targets(obs, farm, opponent, private) == baseline_targets()

    obs["town"]["unlocked_shops"] = ["PIZZA_SHOP"]
    monkeypatch.setattr(
        v101.v3,
        "_expert_weights",
        lambda *_args: {"rank1": 0.2, "rank2": 0.2, "rank3": 0.6},
    )
    assert v101._strategy_targets(obs, farm, opponent, private) == baseline_targets()


def test_v101_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    assert not v101.ENABLE_EARLY_OPTIONALITY
    assert v101.v14._strategy_targets is v101._strategy_targets
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v101.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v101.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v101" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v101" / entry["source"]).resolve()
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
assert namespace["v14"]._strategy_targets is namespace["_strategy_targets"]
assert set(namespace["agent"]({})) == {"farmer", "hands", "market"}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
