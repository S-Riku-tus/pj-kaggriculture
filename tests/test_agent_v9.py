from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v9 import main as v9_main
from agents.v9.main import (
    DECISION_MODEL,
    INTENT_FEATURE_NAMES,
    INTENT_NAMES,
    MARKET_FEATURE_NAMES,
    MARKET_ITEMS,
    _market_selected,
    _mission_assign,
    agent,
    base,
)


def make_obs(*, day: int = 10, hour: int = 0, hands: int = 0, money: float = 5000) -> dict:
    products = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
    crops = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")

    def farm() -> dict:
        return {
            "money": money,
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
            "inventory": {item: 10000 for item in products},
            "prices": dict(base.BASE_PRICE),
        },
        "town": {"unlocked_shops": ["BAKERY", "YARN_STORE", "SMOOTHIE_SHOP"]},
    }


def test_v9_model_schema_and_selection_evidence_are_present() -> None:
    assert DECISION_MODEL is not None
    assert tuple(DECISION_MODEL["intent_feature_names"]) == INTENT_FEATURE_NAMES
    assert tuple(DECISION_MODEL["market_feature_names"]) == MARKET_FEATURE_NAMES
    assert tuple(DECISION_MODEL["intent_names"]) == INTENT_NAMES
    assert tuple(DECISION_MODEL["market_items"]) == MARKET_ITEMS
    assert DECISION_MODEL["source"]["episode_split"] == {"validation": 25, "train": 69, "test": 39}
    assert DECISION_MODEL["selection"]["intent"]["WAIT_ANIMAL_12"]
    assert not DECISION_MODEL["selection"]["intent"]["BUY_SHEEP_12"]
    assert not DECISION_MODEL["selection"]["market"]["MELON"]
    assert not _market_selected("MELON")


def test_v9_is_observation_pure_and_fails_closed() -> None:
    obs = make_obs(day=0, hour=0, hands=0, money=3000)
    before = deepcopy(obs)
    action = agent(obs)
    assert obs == before
    assert action["farmer"] == ["BUILD_PASTURE"]
    assert agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}


def test_v9_mission_scheduler_continues_same_tile_animal_service(monkeypatch) -> None:
    monkeypatch.setattr(v9_main, "ENABLE_MISSION_CONTINUITY", True)
    positions = [(1, 1), (4, 4)]
    inventories = [{"WHEAT": 1}, {}]
    feed_tasks = [
        base._task((1, 1), ["FEED"], 12100, required="WHEAT", label="feed"),
        base._task((0, 0), ["WATER"], 10600, label="water"),
    ]
    first = _mission_assign(positions, inventories, feed_tasks, step=0)
    assert first[0] == ["FEED"]
    care_tasks = [
        base._task((1, 1), ["CARE"], 9000, label="care"),
        base._task((4, 3), ["WATER"], 16000, label="water"),
    ]
    second = _mission_assign(positions, inventories, care_tasks, step=1)
    assert second[0] == ["CARE"]


def test_v9_action_shape_has_one_action_per_hand() -> None:
    obs = make_obs(day=10, hour=5, hands=4)
    action = agent(obs)
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 4
    assert len(action["market"]) <= 10


def test_v9_submission_resolves_all_helpers_from_another_cwd(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    files = json.loads((root / "agents" / "v9" / "submission_manifest.json").read_text(encoding="utf-8"))["files"]
    for entry in files:
        source = (root / "agents" / "v9" / entry["source"]).resolve()
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
assert namespace["MODEL"] is not None
assert namespace["POLICY_MODEL"] is not None
assert namespace["DECISION_MODEL"] is not None
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
