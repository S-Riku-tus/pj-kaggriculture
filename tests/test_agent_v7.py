from __future__ import annotations

import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v7.main import MODEL, _bounded_demand_herd, _strategy_targets, agent, v6

PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
ANIMALS = ("GOOSE", "COW", "SHEEP")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")


def make_obs(
    *,
    day: int = 10,
    hour: int = 12,
    hands: int = 10,
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


def test_v7_preserves_observation_purity_and_fails_closed() -> None:
    assert MODEL is not None
    obs = make_obs(day=0, hour=0, hands=0, unlocked=1, money=3000)
    before = deepcopy(obs)
    action = agent(obs)
    assert obs == before
    assert action["farmer"] == ["BUILD_PASTURE"]
    assert agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}


def test_v7_bounded_herd_moves_at_most_one_future_slot() -> None:
    milk = _bounded_demand_herd(
        safe_animals={"GOOSE": 0, "COW": 8, "SHEEP": 6},
        economic_animals={"GOOSE": 0, "COW": 14, "SHEEP": 2},
        owned_cow=2,
        owned_sheep=2,
    )
    wool = _bounded_demand_herd(
        safe_animals={"GOOSE": 0, "COW": 8, "SHEEP": 6},
        economic_animals={"GOOSE": 0, "COW": 5, "SHEEP": 9},
        owned_cow=2,
        owned_sheep=2,
    )
    assert milk == {"GOOSE": 0, "COW": 9, "SHEEP": 5}
    assert wool == {"GOOSE": 0, "COW": 7, "SHEEP": 7}
    assert sum(milk.values()) == sum(wool.values()) == 14


def test_v7_bounded_herd_never_reallocates_owned_animals() -> None:
    result = _bounded_demand_herd(
        safe_animals={"GOOSE": 0, "COW": 9, "SHEEP": 6},
        economic_animals={"GOOSE": 0, "COW": 5, "SHEEP": 9},
        owned_cow=9,
        owned_sheep=4,
    )
    assert result["COW"] >= 9
    assert result["SHEEP"] >= 4
    assert result["COW"] + result["SHEEP"] == 15


def test_v7_keeps_every_non_herd_v6_target() -> None:
    obs = make_obs(day=12, unlocked=3)
    ours = _strategy_targets(obs, obs["farms"][0], obs["farms"][1], obs["private"])
    safe = v6._strategy_targets(obs, obs["farms"][0], obs["farms"][1], obs["private"])
    assert sum(ours[0].values()) == sum(safe[0].values())
    assert ours[1:] == safe[1:]


def test_v7_freezes_to_v6_after_animal_purchase_horizon() -> None:
    obs = make_obs(day=21, unlocked=3)
    assert _strategy_targets(obs, obs["farms"][0], obs["farms"][1], obs["private"]) == v6._strategy_targets(
        obs, obs["farms"][0], obs["farms"][1], obs["private"]
    )


def test_v7_submission_resolves_nested_helpers_from_another_cwd(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    for source, target in (
        (root / "agents" / "v7" / "main.py", "main.py"),
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
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
