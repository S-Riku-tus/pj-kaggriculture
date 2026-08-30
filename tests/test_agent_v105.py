from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v105 import main as v105


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
            "seeds": {crop: 0 for crop in v105.v14.CROPS},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10_000 for item in products},
            "prices": dict(v105.base.BASE_PRICE),
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


def install_gate(monkeypatch) -> None:
    monkeypatch.setattr(v105, "_SAFE_STRATEGY_TARGETS", lambda *_args: deepcopy(baseline_targets()))

    def gate(obs, *_args):
        active = int(obs["step"]) == 240
        return {
            "active": active,
            "baseline": deepcopy(baseline_targets()),
            "candidate_animals": deepcopy(baseline_targets()[0]),
            "candidate_crops": {
                **baseline_targets()[1],
                "WHEAT": 36,
                "STRAWBERRY": 24,
            },
        }

    monkeypatch.setattr(v105.v102, "_gate_decision", gate)


def select(obs: dict) -> tuple:
    return v105._strategy_targets(obs, obs["farms"][0], obs["farms"][1], obs["private"])


def test_v105_uses_day_boundary_once_and_holds_intraday(monkeypatch) -> None:
    v105.reset_runtime_state()
    install_gate(monkeypatch)
    assert select(make_obs(day=10, hour=0))[1]["STRAWBERRY"] == 24
    assert select(make_obs(day=10, hour=1))[1]["STRAWBERRY"] == 24
    assert select(make_obs(day=10, hour=23))[1]["STRAWBERRY"] == 24
    assert select(make_obs(day=11, hour=0)) == baseline_targets()
    assert v105._DAILY_ACTIVATIONS == 1
    assert v105._DAILY_ACTIVE_STEPS == 3


def test_v105_never_admits_from_intraday_state(monkeypatch) -> None:
    v105.reset_runtime_state()
    monkeypatch.setattr(v105, "_SAFE_STRATEGY_TARGETS", lambda *_args: deepcopy(baseline_targets()))
    calls = 0

    def gate(*_args):
        nonlocal calls
        calls += 1
        return {"active": True, "baseline": deepcopy(baseline_targets())}

    monkeypatch.setattr(v105.v102, "_gate_decision", gate)
    assert select(make_obs(day=10, hour=1)) == baseline_targets()
    assert calls == 0


def test_v105_emergency_falls_back_and_clears_goal(monkeypatch) -> None:
    v105.reset_runtime_state()
    install_gate(monkeypatch)
    assert select(make_obs(day=10, hour=0))[1]["STRAWBERRY"] == 24
    obs = make_obs(day=10, hour=1)
    obs["farms"][0]["tiles"][0][0] = {
        "kind": "PASTURE",
        "animal": "COW",
        "fed_today": False,
        "consecutive_unfed": 1,
    }
    assert select(obs) == baseline_targets()
    assert v105._DAILY_DELTA is None
    assert v105._DAILY_EMERGENCY_FALLBACKS == 1


def test_v105_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    v105.reset_runtime_state()
    assert v105.ENABLE_DAILY_RECOVERY
    assert v105.v14._strategy_targets is v105._strategy_targets
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v105.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v105.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v105" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v105" / entry["source"]).resolve()
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
