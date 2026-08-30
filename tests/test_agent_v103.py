from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v103 import main as v103


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
            "seeds": {crop: 0 for crop in v103.v14.CROPS},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10_000 for item in products},
            "prices": dict(v103.base.BASE_PRICE),
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


def candidate_targets() -> tuple[dict, dict]:
    return deepcopy(baseline_targets()[0]), {**baseline_targets()[1], "STRAWBERRY": 24}


def reset_state() -> None:
    v103._COMMIT_LAST_STEP = -1
    v103._COMMIT_ACTIVATIONS = 0
    v103._COMMIT_CONTINUATION_STEPS = 0
    v103._reset_commitment()


def install_models(monkeypatch) -> None:
    monkeypatch.setattr(v103, "ENABLE_RECOVERY_COMMITMENT", True)
    monkeypatch.setattr(v103, "_SAFE_STRATEGY_TARGETS", lambda *_args: deepcopy(baseline_targets()))

    def entry(obs, *_args):
        active = int(obs["step"]) == 240
        return {
            "active": active,
            "baseline": deepcopy(baseline_targets()),
            "candidate_animals": candidate_targets()[0],
            "candidate_crops": candidate_targets()[1],
        }

    monkeypatch.setattr(v103.v102, "_gate_decision", entry)
    monkeypatch.setattr(
        v103.v14,
        "_winner_prediction",
        lambda *_args: {
            "active": True,
            "confidence": 0.8,
            "uncertainty": 0.1,
            "money_gap_ratio": -0.2,
            "h72": {},
        },
    )
    monkeypatch.setattr(v103.v14, "_project_targets", lambda *_args: candidate_targets())


def select(obs: dict) -> tuple:
    return v103._strategy_targets(obs, obs["farms"][0], obs["farms"][1], obs["private"])


def test_v103_holds_goal_for_at_most_twelve_turns(monkeypatch) -> None:
    reset_state()
    install_models(monkeypatch)
    first = select(make_obs(day=10, hour=0))
    continued = select(make_obs(day=10, hour=1))
    expired = select(make_obs(day=10, hour=12))
    assert first[1]["STRAWBERRY"] == 24
    assert continued[1]["STRAWBERRY"] == 24
    assert expired == baseline_targets()
    assert v103._COMMIT_ACTIVATIONS == 1
    assert v103._COMMIT_CONTINUATION_STEPS == 1


def test_v103_fails_closed_when_continuation_leaves_safe_envelope(monkeypatch) -> None:
    reset_state()
    install_models(monkeypatch)
    assert select(make_obs(day=10, hour=0))[1]["STRAWBERRY"] == 24
    monkeypatch.setattr(
        v103.v14, "_winner_prediction", lambda *_args: {"active": False, "reason": "ood"}
    )
    assert select(make_obs(day=10, hour=1)) == baseline_targets()
    assert v103._COMMIT_UNTIL_STEP == -1


def test_v103_does_not_retrigger_same_day_and_resets_new_episode(monkeypatch) -> None:
    reset_state()
    install_models(monkeypatch)
    select(make_obs(day=10, hour=0))
    select(make_obs(day=10, hour=12))

    monkeypatch.setattr(
        v103.v102,
        "_gate_decision",
        lambda *_args: {
            "active": True,
            "baseline": deepcopy(baseline_targets()),
            "candidate_animals": candidate_targets()[0],
            "candidate_crops": candidate_targets()[1],
        },
    )
    assert select(make_obs(day=10, hour=13)) == baseline_targets()
    assert v103._COMMIT_ACTIVATIONS == 1

    monkeypatch.setattr(
        v103.v102,
        "_gate_decision",
        lambda *_args: {"active": False, "baseline": deepcopy(baseline_targets())},
    )
    reset_obs = make_obs(day=0, hour=1)
    assert select(reset_obs) == baseline_targets()
    monkeypatch.setattr(
        v103.v102,
        "_gate_decision",
        lambda *_args: {
            "active": True,
            "baseline": deepcopy(baseline_targets()),
            "candidate_animals": candidate_targets()[0],
            "candidate_crops": candidate_targets()[1],
        },
    )
    assert select(make_obs(day=10, hour=13))[1]["STRAWBERRY"] == 24
    assert v103._COMMIT_ACTIVATIONS == 2


def test_v103_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    reset_state()
    assert not v103.ENABLE_RECOVERY_COMMITMENT
    assert v103.v14._strategy_targets is v103._strategy_targets
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v103.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v103.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v103" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v103" / entry["source"]).resolve()
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
