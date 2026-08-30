from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v11 import main as v11


def make_obs(*, day: int = 24, hour: int = 0, hands: int = 0) -> dict:
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
    crops = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")

    def farm() -> dict:
        return {
            "money": 50_000,
            "tiles": [[None if x < 5 or y < 5 else "LOCKED" for x in range(10)] for y in range(10)],
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
            "seeds": {crop: 0 for crop in crops},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10_000 for item in products},
            "prices": dict(v11.base.BASE_PRICE),
        },
        "town": {"unlocked_shops": ["PET_CAFE", "PET_CAFE", "BAKERY"]},
    }


def _targets() -> tuple[dict, dict, int, int, dict, int]:
    return (
        {"GOOSE": 0, "COW": 8, "SHEEP": 4},
        {"WHEAT": 36, "CARROT": 1, "TOMATO": 0, "STRAWBERRY": 28, "MELON": 0},
        12,
        3,
        {},
        12,
    )


def _prediction(confidence: float = 0.8) -> tuple[dict, dict, float, float]:
    short = {target: 0.0 for target in v11.v8.TARGET_NAMES}
    short.update({"WHEAT": 30.0, "CARROT": 9.0, "STRAWBERRY": 23.0})
    return short, short, confidence, 0.2


def test_v11_activates_only_in_late_demand_window(monkeypatch) -> None:
    obs = make_obs(day=23)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    monkeypatch.setattr(v11.v10, "_strategy_targets", lambda *_args: _targets())
    monkeypatch.setattr(v11.v8, "_expert_prediction", lambda *_args: _prediction())

    assert v11._strategy_targets(obs, farm, opponent, private)[1] == _targets()[1]

    obs["day"] = 24
    crops = v11._strategy_targets(obs, farm, opponent, private)[1]
    assert crops == {
        "WHEAT": 31,
        "CARROT": 6,
        "TOMATO": 0,
        "STRAWBERRY": 23,
        "MELON": 0,
    }
    assert sum(crops.values()) + 12 == 72


def test_v11_fails_closed_without_supported_demand_or_confidence(monkeypatch) -> None:
    obs = make_obs(day=24)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    monkeypatch.setattr(v11.v10, "_strategy_targets", lambda *_args: _targets())
    monkeypatch.setattr(v11.v8, "_expert_prediction", lambda *_args: _prediction())

    obs["town"]["unlocked_shops"] = ["PET_CAFE", "BAKERY"]
    assert v11._strategy_targets(obs, farm, opponent, private)[1] == _targets()[1]

    obs["town"]["unlocked_shops"] = ["PET_CAFE", "PET_CAFE"]
    monkeypatch.setattr(v11.v8, "_expert_prediction", lambda *_args: _prediction(0.2))
    assert v11._strategy_targets(obs, farm, opponent, private)[1] == _targets()[1]


def test_v11_delegates_field_and_market_execution_unchanged(monkeypatch) -> None:
    obs = make_obs(day=24)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    summary = v11.base._farm_summary(farm)
    field_result = ([{"action": ["WATER"], "priority": 12_800}], {(0, 0)})
    market_result = ([['SELL', 'MILK', 3], ['HIRE']], {"active": False})
    monkeypatch.setattr(v11.v10, "_field_tasks", lambda *_args: field_result)
    monkeypatch.setattr(v11.v10, "_market_plan", lambda *_args: market_result)

    assert v11._field_tasks(
        obs,
        farm,
        private,
        [(4, 4)],
        [{}],
        summary,
        _targets()[0],
        _targets()[1],
        12,
        opponent,
    ) == field_result
    assert v11._market_plan(
        obs,
        farm,
        opponent,
        private,
        summary,
        _targets()[0],
        _targets()[1],
        12,
        3,
        {},
        12,
        [["PASS"]],
        set(),
    ) == market_result


def test_v11_diagnostics_explain_fallback_and_agent_is_pure(monkeypatch) -> None:
    obs = make_obs(day=24, hands=2)
    monkeypatch.setattr(v11.v8, "_expert_prediction", lambda *_args: _prediction())
    diagnostic = v11.policy_diagnostics(obs)
    assert diagnostic["v11_rotation"]["active"]
    assert diagnostic["v11_rotation"]["reason"] == "active"

    before = deepcopy(obs)
    action = v11.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v11.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}


def test_v11_submission_resolves_all_helpers_from_another_cwd(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v11" / "submission_manifest.json"
    files = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    for entry in files:
        source = (root / "agents" / "v11" / entry["source"]).resolve()
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
assert namespace["v10"].MODEL is not None
assert namespace["v10"].POLICY_MODEL is not None
assert namespace["v10"].DECISION_MODEL is not None
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
