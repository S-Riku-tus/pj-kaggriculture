from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v104 import main as v104


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
            "seeds": {crop: 0 for crop in v104.v14.CROPS},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10_000 for item in products},
            "prices": dict(v104.base.BASE_PRICE),
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


def candidate_crops() -> dict[str, int]:
    return {**baseline_targets()[1], "WHEAT": 36, "STRAWBERRY": 24}


def install_models(monkeypatch) -> None:
    monkeypatch.setattr(v104, "_SAFE_STRATEGY_TARGETS", lambda *_args: deepcopy(baseline_targets()))

    def entry(obs, *_args):
        active = int(obs["step"]) == 240
        return {
            "active": active,
            "baseline": deepcopy(baseline_targets()),
            "candidate_animals": deepcopy(baseline_targets()[0]),
            "candidate_crops": candidate_crops(),
        }

    monkeypatch.setattr(v104.v102, "_gate_decision", entry)
    monkeypatch.setattr(
        v104.v14,
        "_winner_prediction",
        lambda *_args: {"active": True, "reason": "active", "confidence": 0.8},
    )


def select(obs: dict) -> tuple:
    return v104._strategy_targets(obs, obs["farms"][0], obs["farms"][1], obs["private"])


def test_v104_latches_delta_until_one_day_limit(monkeypatch) -> None:
    v104.reset_runtime_state()
    install_models(monkeypatch)
    first = select(make_obs(day=10, hour=0))
    continued = select(make_obs(day=10, hour=1))
    expired = select(make_obs(day=11, hour=0))
    assert first[1]["STRAWBERRY"] == 24
    assert continued[1]["STRAWBERRY"] == 24
    assert expired == baseline_targets()
    assert v104._LATCH_ACTIVATIONS == 1
    assert v104._LATCH_SUPPORTED_STEPS == 2


def test_v104_decays_then_fails_closed_out_of_distribution(monkeypatch) -> None:
    v104.reset_runtime_state()
    install_models(monkeypatch)
    assert select(make_obs(day=10, hour=0))[1]["STRAWBERRY"] == 24
    monkeypatch.setattr(
        v104.v14,
        "_winner_prediction",
        lambda *_args: {"active": False, "reason": "uncertain"},
    )
    assert select(make_obs(day=10, hour=1))[1]["STRAWBERRY"] == 27
    assert select(make_obs(day=10, hour=2))[1]["STRAWBERRY"] == 28
    assert select(make_obs(day=10, hour=3)) == baseline_targets()
    assert v104._LATCH_DECAY_STEPS == 3
    assert v104._LATCH_DELTA is None


def test_v104_stops_immediately_after_recovery(monkeypatch) -> None:
    v104.reset_runtime_state()
    install_models(monkeypatch)
    select(make_obs(day=10, hour=0))
    monkeypatch.setattr(
        v104.v14,
        "_winner_prediction",
        lambda *_args: {"active": False, "reason": "not-behind"},
    )
    assert select(make_obs(day=10, hour=1)) == baseline_targets()
    assert v104._LATCH_DELTA is None


def test_v104_current_crop_ownership_is_a_hard_floor(monkeypatch) -> None:
    v104.reset_runtime_state()
    install_models(monkeypatch)
    obs = make_obs(day=10, hour=0)
    for x in range(8):
        obs["farms"][0]["tiles"][0][x] = {
            "kind": "PLANT",
            "crop": "STRAWBERRY",
            "watered_today": True,
        }
    # Add 22 more live Strawberry cells: candidate 24 may never remove them.
    for index in range(22):
        y, x = divmod(index, 10)
        obs["farms"][0]["tiles"][y + 1][x] = {
            "kind": "PLANT",
            "crop": "STRAWBERRY",
            "watered_today": True,
        }
    assert select(obs)[1]["STRAWBERRY"] >= 30


def test_v104_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    v104.reset_runtime_state()
    assert v104.ENABLE_LATCHED_RECOVERY
    assert v104.v14._strategy_targets is v104._strategy_targets
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v104.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v104.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v104" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v104" / entry["source"]).resolve()
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
        cwd=elsewhere,
        capture_output=True,
        text=True,
    )
