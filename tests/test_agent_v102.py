from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v102 import main as v102


def make_obs(*, day: int = 10, hands: int = 0) -> dict:
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
        "step": day * 24,
        "day": day,
        "hour": 0,
        "farms": [farm(5_000), farm(10_000)],
        "private": {
            "shed": {item: 0 for item in (*products, "GOOSE", "COW", "SHEEP")},
            "seeds": {crop: 0 for crop in v102.v14.CROPS},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10_000 for item in products},
            "prices": dict(v102.base.BASE_PRICE),
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


def supported_prediction(**overrides) -> dict:
    value = {
        "active": True,
        "reason": "active",
        "money_gap_ratio": -0.20,
        "confidence": 0.80,
        "uncertainty": 0.10,
        "distance": 0.8,
        "h72": {},
    }
    value.update(overrides)
    return value


def install_candidate(monkeypatch, *, strawberry: int = 24) -> None:
    monkeypatch.setattr(v102, "_SAFE_STRATEGY_TARGETS", lambda *_args: deepcopy(baseline_targets()))
    monkeypatch.setattr(v102.v14, "_winner_prediction", lambda *_args: supported_prediction())
    monkeypatch.setattr(
        v102.v14,
        "_project_targets",
        lambda *_args: (deepcopy(baseline_targets()[0]), {**baseline_targets()[1], "STRAWBERRY": strawberry}),
    )


def test_v102_admits_only_supported_recovery_projection(monkeypatch) -> None:
    obs = make_obs(day=10)
    install_candidate(monkeypatch)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    selected = v102._strategy_targets(obs, farm, opponent, private)
    assert selected[0] == baseline_targets()[0]
    assert selected[1] == {**baseline_targets()[1], "STRAWBERRY": 24}
    assert selected[2:5] == baseline_targets()[2:5]
    decision = v102._gate_decision(obs, farm, opponent, private)
    assert decision["active"]
    assert decision["changed"]
    assert decision["reason"] == "active"


def test_v102_falls_back_for_each_gate_boundary(monkeypatch) -> None:
    obs = make_obs(day=12)
    install_candidate(monkeypatch)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    assert v102._strategy_targets(obs, farm, opponent, private) == baseline_targets()

    obs = make_obs(day=10)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    monkeypatch.setattr(
        v102.v14, "_winner_prediction", lambda *_args: supported_prediction(confidence=0.60)
    )
    assert v102._strategy_targets(obs, farm, opponent, private) == baseline_targets()

    monkeypatch.setattr(
        v102.v14,
        "_winner_prediction",
        lambda *_args: supported_prediction(uncertainty=1.0),
    )
    assert v102._strategy_targets(obs, farm, opponent, private) == baseline_targets()

    monkeypatch.setattr(
        v102.v14,
        "_winner_prediction",
        lambda *_args: supported_prediction(money_gap_ratio=-0.01),
    )
    assert v102._strategy_targets(obs, farm, opponent, private) == baseline_targets()

    monkeypatch.setattr(v102.v14, "_winner_prediction", lambda *_args: supported_prediction())
    monkeypatch.setattr(
        v102.v14,
        "_project_targets",
        lambda *_args: (deepcopy(baseline_targets()[0]), deepcopy(baseline_targets()[1])),
    )
    assert v102._strategy_targets(obs, farm, opponent, private) == baseline_targets()


def test_v102_disabled_and_inactive_paths_are_exact_v11(monkeypatch) -> None:
    obs = make_obs(day=10)
    install_candidate(monkeypatch)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    monkeypatch.setattr(v102, "ENABLE_RECOVERY_META_GATE", False)
    assert v102._strategy_targets(obs, farm, opponent, private) == baseline_targets()
    monkeypatch.setattr(v102, "ENABLE_RECOVERY_META_GATE", True)
    monkeypatch.setattr(
        v102.v14, "_winner_prediction", lambda *_args: {"active": False, "reason": "ood"}
    )
    assert v102._strategy_targets(obs, farm, opponent, private) == baseline_targets()


def test_v102_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    assert v102.ENABLE_RECOVERY_META_GATE
    assert v102.v14._strategy_targets is v102._strategy_targets
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v102.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v102.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v102" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v102" / entry["source"]).resolve()
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
