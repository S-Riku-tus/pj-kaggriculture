from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v8.main import (
    EXPERT_OPENING,
    POLICY_FEATURE_NAMES,
    POLICY_MODEL,
    TARGET_NAMES,
    _add_rotation_tasks,
    _blend_target,
    _distance_confidence,
    _field_tasks,
    _safe_expert_opening,
    agent,
    base,
)

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
ANIMALS = ("GOOSE", "COW", "SHEEP")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")


def make_obs(
    *,
    day: int = 10,
    hour: int = 0,
    hands: int = 0,
    unlocked: int = 3,
    money: float = 5000,
) -> dict:
    quadrants = ["NW", "NE", "SW", "SE"][:unlocked]

    def farm() -> dict:
        tiles = []
        for y in range(10):
            row = []
            for x in range(10):
                quadrant = "NW" if x < 5 and y < 5 else ("NE" if y < 5 else ("SW" if x < 5 else "SE"))
                row.append(None if quadrant in quadrants else "LOCKED")
            tiles.append(row)
        return {
            "money": money,
            "tiles": tiles,
            "farmer": [4, 4],
            "hands": [[4, 4] for _ in range(hands)],
            "unlocked_quadrants": quadrants,
            "hires_today": hands,
        }

    return {
        "player": 0,
        "step": day * 24 + hour,
        "day": day,
        "hour": hour,
        "farms": [farm(), farm()],
        "private": {
            "shed": {item: 0 for item in (*PRODUCTS, *ANIMALS)},
            "seeds": {crop: 0 for crop in CROPS},
            "inventories": [{} for _ in range(hands + 1)],
        },
        "market": {
            "inventory": {item: 10000 for item in PRODUCTS},
            "prices": {
                "WHEAT": 25,
                "CARROT": 35,
                "TOMATO": 60,
                "STRAWBERRY": 120,
                "MELON": 250,
                "EGG": 50,
                "MILK": 160,
                "WOOL": 200,
                "FERTILIZER": 100,
            },
        },
        "town": {"unlocked_shops": []},
    }


def test_v8_models_and_validation_evidence_are_present() -> None:
    assert POLICY_MODEL is not None
    assert tuple(POLICY_MODEL["feature_names"]) == POLICY_FEATURE_NAMES
    assert tuple(POLICY_MODEL["target_names"]) == TARGET_NAMES
    assert len(POLICY_MODEL["forests"]["h24"]) >= 20
    assert len(POLICY_MODEL["forests"]["h72"]) >= 20
    for horizon in ("h24", "h72"):
        assert POLICY_MODEL["validation"]["horizons"][horizon]["model_improvement_vs_v7"] > 0


def test_v8_is_observation_pure_and_fails_closed() -> None:
    obs = make_obs(day=0, hour=0, hands=0, unlocked=1, money=3000)
    before = deepcopy(obs)
    action = agent(obs)
    assert obs == before
    assert action["farmer"] == ["BUILD_PASTURE"]
    assert agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}


def test_v8_expert_opening_is_position_gated() -> None:
    assert len(EXPERT_OPENING) == 5 * 24
    obs = make_obs(day=1, hour=0, hands=0, unlocked=1, money=142)
    scripted = _safe_expert_opening(obs, obs["farms"][0])
    assert scripted is not None
    assert scripted[0]["farmer"] == ["PICKUP", "WHEAT", 2]
    obs["farms"][0]["farmer"] = [3, 4]
    assert _safe_expert_opening(obs, obs["farms"][0]) is None


def test_v8_confidence_gate_rejects_far_states() -> None:
    assert POLICY_MODEL is not None
    profile = POLICY_MODEL["profiles"]["10:0"]
    features = [0.0] * len(POLICY_FEATURE_NAMES)
    for index, center in zip(profile["feature_indices"], profile["center"], strict=True):
        features[int(index)] = float(center)
    near, near_distance = _distance_confidence(features, 10, 0)
    assert near == 1.0
    assert near_distance == 0.0
    for index in profile["feature_indices"]:
        features[int(index)] += 100.0
    far, far_distance = _distance_confidence(features, 10, 0)
    assert far < 0.05
    assert far_distance > profile["distance_p99"]


def test_v8_absolute_anchor_does_not_accumulate_a_delta() -> None:
    first = _blend_target(10, 16.0, 30.0, 0.8, change_limit=4)
    second = _blend_target(10, 16.0, 30.0, 0.8, change_limit=4)
    assert first == second
    assert 10 < first <= 20


def test_v8_adds_only_feasible_demand_rotation_tasks() -> None:
    obs = make_obs(day=16, hour=8, hands=2, unlocked=3)
    obs["private"]["seeds"]["TOMATO"] = 3
    obs["private"]["seeds"]["CARROT"] = 5
    tasks: list[dict] = []
    summary = base._farm_summary(obs["farms"][0])
    _add_rotation_tasks(
        tasks,
        set(),
        obs,
        obs["farms"][0],
        obs["private"],
        summary,
        {"WHEAT": 0, "CARROT": 5, "TOMATO": 3, "STRAWBERRY": 0, "MELON": 0},
    )
    assert [task["action"][1] for task in tasks].count("TOMATO") == 3
    assert [task["action"][1] for task in tasks].count("CARROT") == 5
    assert len({task["pos"] for task in tasks}) == len(tasks)


def test_v8_harvests_melon_at_effective_cap_day() -> None:
    obs = make_obs(day=10, hour=0, hands=0, unlocked=2)
    melon = {
        "kind": "PLANT",
        "crop": "MELON",
        "planted_day": 0,
        "watered_today": False,
        "consecutive_unwatered": 0,
        "yield_units": 5,
        "max_lifespan_step": 312,
        "fertilized_until_day": -1,
    }
    obs["farms"][0]["tiles"][0][0] = melon
    farm = obs["farms"][0]
    summary = base._farm_summary(farm)
    tasks, _reserved = _field_tasks(
        obs,
        farm,
        obs["private"],
        [(4, 4)],
        [{}],
        summary,
        {"GOOSE": 0, "COW": 0, "SHEEP": 0},
        {"WHEAT": 0, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 1},
        0,
    )
    matching = [task for task in tasks if task["pos"] == (0, 0) and task["action"] == ["HARVEST"]]
    assert len(matching) == 1
    assert matching[0]["priority"] == 14800


def test_v8_submission_resolves_all_helpers_from_another_cwd(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    for source, target in (
        (root / "agents" / "v8" / "main.py", "main.py"),
        (root / "agents" / "v8" / "expert_policy_model.json", "expert_policy_model.json"),
        (root / "agents" / "v8" / "expert_opening_actions.json", "expert_opening_actions.json"),
        (root / "agents" / "v7" / "main.py", "v7_base.py"),
        (root / "agents" / "v6" / "main.py", "v6_base.py"),
        (root / "agents" / "v5" / "main.py", "v5_base.py"),
        (root / "agents" / "v4" / "main.py", "v4_base.py"),
        (root / "agents" / "v3" / "main.py", "v3_base.py"),
        (root / "agents" / "v2" / "main.py", "v2_base.py"),
        (root / "agents" / "v3" / "feature_schema.py", "feature_schema.py"),
        (root / "agents" / "v3" / "strategy_model.json", "strategy_model.json"),
    ):
        shutil.copyfile(source, submission / target)

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
assert len(namespace["EXPERT_OPENING"]) == 120
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_v8_model_json_is_compact_enough_for_submission() -> None:
    root = Path(__file__).resolve().parents[1]
    model = root / "agents" / "v8" / "expert_policy_model.json"
    opening = root / "agents" / "v8" / "expert_opening_actions.json"
    assert model.stat().st_size < 1_500_000
    assert opening.stat().st_size < 100_000
    assert json.loads(model.read_text(encoding="utf-8"))["format"].endswith("atlas-v1")
