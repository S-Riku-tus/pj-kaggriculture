from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v10 import main as v10


def make_obs(*, day: int = 7, hour: int = 0, hands: int = 0, money: float = 300) -> dict:
    products = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
    crops = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")

    def farm() -> dict:
        return {
            "money": money,
            "tiles": [[None if x < 5 or y < 5 else "LOCKED" for x in range(10)] for y in range(10)],
            "farmer": [4, 4],
            "hands": [[4, 4] for _ in range(hands)],
            "unlocked_quadrants": ["NW", "NE"],
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
            "prices": dict(v10.base.BASE_PRICE),
        },
        "town": {"unlocked_shops": ["BAKERY", "YARN_STORE"]},
    }


def test_v10_capital_recovery_uses_future_crop_gap_and_fails_closed(monkeypatch) -> None:
    obs = make_obs(day=7, money=2000)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    short = {target: 0.0 for target in v10.v8.TARGET_NAMES}
    short.update({"WHEAT": 13.0, "STRAWBERRY": 13.0})
    monkeypatch.setattr(v10.v8, "_expert_prediction", lambda *_args: (short, short, 0.8, 0.5))
    assert v10._capital_recovery(obs, farm, opponent, private)["active"]

    monkeypatch.setattr(v10.v8, "_expert_prediction", lambda *_args: (short, short, 0.2, 2.0))
    diagnostic = v10._capital_recovery(obs, farm, opponent, private)
    assert not diagnostic["active"]
    assert diagnostic["reason"] == "low-confidence"


def test_v10_herd_calibration_preserves_scale_and_owned_animals(monkeypatch) -> None:
    obs = make_obs(day=10)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    short = {target: 0.0 for target in v10.v8.TARGET_NAMES}
    monkeypatch.setattr(v10.v8, "_expert_prediction", lambda *_args: (short, short, 0.8, 0.2))
    monkeypatch.setattr(
        v10.v9,
        "_strategy_targets",
        lambda *_args: (
            {"GOOSE": 0, "COW": 6, "SHEEP": 4},
            {crop: 0 for crop in v10.CROPS},
            10,
            3,
            {},
            10,
        ),
    )
    animals, crops, *_rest = v10._strategy_targets(obs, farm, opponent, private)
    assert animals == {"GOOSE": 0, "COW": 8, "SHEEP": 2}
    assert crops["WHEAT"] >= 12
    assert sum(animals.values()) + sum(crops.values()) == 72

    private["shed"]["SHEEP"] = 5
    animals, *_rest = v10._strategy_targets(obs, farm, opponent, private)
    assert animals["SHEEP"] == 5


def test_v10_late_rotation_uses_confident_wheat_floor(monkeypatch) -> None:
    obs = make_obs(day=24)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    short = {target: 0.0 for target in v10.v8.TARGET_NAMES}
    monkeypatch.setattr(
        v10.v9,
        "_strategy_targets",
        lambda *_args: (
            {"GOOSE": 0, "COW": 8, "SHEEP": 4},
            {crop: (20 if crop == "WHEAT" else 0) for crop in v10.CROPS},
            10,
            3,
            {},
            12,
        ),
    )
    monkeypatch.setattr(v10.v8, "_expert_prediction", lambda *_args: (short, short, 0.8, 0.2))
    _animals, crops, *_rest = v10._strategy_targets(obs, farm, opponent, private)
    assert crops["WHEAT"] == 36

    monkeypatch.setattr(v10.v8, "_expert_prediction", lambda *_args: (short, short, 0.2, 2.0))
    _animals, crops, *_rest = v10._strategy_targets(obs, farm, opponent, private)
    assert crops["WHEAT"] == 20


def test_v10_suppresses_only_early_fertilize_tasks(monkeypatch) -> None:
    tasks = [
        v10.base._task((0, 0), ["FERTILIZE"], 10000, required="FERTILIZER", label="fertilize"),
        v10.base._task((1, 0), ["WATER"], 10000, label="water"),
        v10.base._task((2, 0), ["PLANT", "STRAWBERRY"], 9000, label="plant-STRAWBERRY"),
    ]
    monkeypatch.setattr(v10.v8, "_field_tasks", lambda *_args: (tasks, set()))
    obs = make_obs(day=8)
    filtered, _reserved = v10._field_tasks(
        obs,
        obs["farms"][0],
        obs["private"],
        [(4, 4)],
        [{}],
        v10.base._farm_summary(obs["farms"][0]),
        {"GOOSE": 0, "COW": 2, "SHEEP": 2},
        {crop: (4 if crop == "STRAWBERRY" else 0) for crop in v10.CROPS},
        4,
    )
    assert [task["action"][0] for task in filtered] == ["WATER", "PLANT"]
    assert filtered[1]["priority"] == 13500

    obs["day"] = 11
    obs["farms"][0]["tiles"][0][0] = {
        "kind": "PLANT",
        "crop": "STRAWBERRY",
        "planted_day": 5,
    }
    retained, _reserved = v10._field_tasks(
        obs,
        obs["farms"][0],
        obs["private"],
        [(4, 4)],
        [{}],
        v10.base._farm_summary(obs["farms"][0]),
        {"GOOSE": 0, "COW": 2, "SHEEP": 2},
        {crop: (4 if crop == "STRAWBERRY" else 0) for crop in v10.CROPS},
        4,
    )
    assert [task["action"][0] for task in retained] == ["FERTILIZE", "WATER", "PLANT"]
    assert retained[0]["priority"] == 12700
    assert retained[1]["priority"] == 12800


def test_v10_midgame_refill_stays_below_routine_feed(monkeypatch) -> None:
    tasks = [v10.base._task((2, 0), ["PLANT", "WHEAT"], 8500, label="plant-WHEAT")]
    monkeypatch.setattr(v10.v8, "_field_tasks", lambda *_args: (tasks, set()))
    obs = make_obs(day=15)
    summary = v10.base._farm_summary(obs["farms"][0])
    summary["productive"] = 60
    boosted, _reserved = v10._field_tasks(
        obs,
        obs["farms"][0],
        obs["private"],
        [(4, 4)],
        [{}],
        summary,
        {"GOOSE": 0, "COW": 8, "SHEEP": 4},
        {crop: (30 if crop == "WHEAT" else 0) for crop in v10.CROPS},
        12,
    )
    assert boosted[0]["priority"] == 12000
    assert boosted[0]["priority"] < 12100


def test_v10_places_perishable_purchased_animals_before_field_work(monkeypatch) -> None:
    tasks = [
        v10.base._task(
            (0, 0), ["PICKUP", "COW", 1], 11600, unit=0, label="pickup-COW"
        ),
        v10.base._task(
            (1, 0), ["PLACE", "COW"], 11800, required="COW", unit=1, label="place-COW"
        ),
        v10.base._task((2, 0), ["WATER"], 10600, label="water"),
    ]
    monkeypatch.setattr(v10.v8, "_field_tasks", lambda *_args: (tasks, set()))
    obs = make_obs(day=15, hands=1)
    summary = v10.base._farm_summary(obs["farms"][0])
    boosted, _reserved = v10._field_tasks(
        obs,
        obs["farms"][0],
        obs["private"],
        [(4, 4), (4, 4)],
        [{}, {"COW": 1}],
        summary,
        {"GOOSE": 0, "COW": 8, "SHEEP": 4},
        {crop: 0 for crop in v10.CROPS},
        12,
    )
    assert [task["priority"] for task in boosted] == [13500, 13400, 12800]
    assert boosted[0]["priority"] < 15400


def test_v10_preserves_v9_sales_and_uses_adjusted_purchases(monkeypatch) -> None:
    obs = make_obs(day=7)
    monkeypatch.setattr(v10, "_capital_recovery", lambda *_args: {"active": True})
    monkeypatch.setattr(
        v10.v9,
        "_market_plan",
        lambda *_args: [["SELL", "MILK", 1], ["BUY_SEED", "STRAWBERRY", 4], ["HIRE"]],
    )
    monkeypatch.setattr(
        v10.v9,
        "agent",
        lambda _obs: {
            "farmer": ["PASS"],
            "hands": [],
            "market": [["SELL", "MILK", 3]],
        },
    )
    monkeypatch.setattr(
        v10.v8,
        "_market_plan",
        lambda *_args: [["SELL", "MILK", 5], ["BUY_LAND"], ["BUY_ANIMAL", "SHEEP", 2]],
    )
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    orders, _diagnostic = v10._market_plan(
        obs,
        farm,
        opponent,
        private,
        v10.base._farm_summary(farm),
        {"GOOSE": 0, "COW": 2, "SHEEP": 2},
        {crop: 0 for crop in v10.CROPS},
        4,
        2,
        {},
        4,
        [],
        set(),
    )
    assert orders == [["SELL", "MILK", 3], ["BUY_SEED", "STRAWBERRY", 4], ["HIRE"]]


def test_v10_early_fertilizer_sale_is_first_and_bounded() -> None:
    obs = make_obs(day=8)
    obs["private"]["shed"]["FERTILIZER"] = 7
    orders = v10._force_early_fertilizer_sale(
        [["HIRE"], ["SELL", "FERTILIZER", 2], ["BUY_SEED", "STRAWBERRY", 3]],
        obs["private"],
        8,
    )
    assert orders[0] == ["SELL", "FERTILIZER", 7]
    assert sum(order[:2] == ["SELL", "FERTILIZER"] for order in orders) == 1
    assert len(orders) <= 10


def test_v10_prepositions_only_empty_idle_workers_on_manifold(monkeypatch) -> None:
    obs = make_obs(day=7, hands=2)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    short = {target: 0.0 for target in v10.v8.TARGET_NAMES}
    monkeypatch.setattr(v10.v8, "_expert_prediction", lambda *_args: (short, short, 0.8, 0.2))
    tasks = [v10.base._task((0, 0), ["WATER"], 10000, label="water")]
    actions = v10._preposition_idle_workers(
        obs,
        farm,
        opponent,
        private,
        [(4, 4), (4, 4), (4, 4)],
        [{}, {"WHEAT": 1}, {}],
        tasks,
        [["PASS"], ["PASS"], ["WATER"]],
    )
    assert actions[0] != ["PASS"]
    assert actions[1] == ["PASS"]
    assert actions[2] == ["WATER"]

    monkeypatch.setattr(v10.v8, "_expert_prediction", lambda *_args: (short, short, 0.2, 3.0))
    assert v10._preposition_idle_workers(
        obs, farm, opponent, private, [(4, 4)], [{}], tasks, [["PASS"]]
    ) == [["PASS"]]


def test_v10_prefers_safe_local_water_but_not_during_feed_emergency(monkeypatch) -> None:
    obs = make_obs(day=12)
    farm, opponent, private = obs["farms"][0], obs["farms"][1], obs["private"]
    farm["tiles"][4][4] = {"kind": "PLANT", "crop": "WHEAT", "watered_today": False}
    short = {target: 0.0 for target in v10.v8.TARGET_NAMES}
    prediction = (short, short, 0.8, 0.2)
    actions = v10._prefer_local_water(
        obs, farm, opponent, private, [(4, 4)], [{}], [["NORTH"]], prediction
    )
    assert actions == [["WATER"]]

    farm["tiles"][0][0] = {
        "kind": "PASTURE",
        "animal": "COW",
        "fed_today": False,
        "consecutive_unfed": 1,
    }
    actions = v10._prefer_local_water(
        obs, farm, opponent, private, [(4, 4)], [{}], [["NORTH"]], prediction
    )
    assert actions == [["NORTH"]]


def test_v10_is_observation_pure_and_action_shape_is_safe() -> None:
    obs = make_obs(day=7, hour=4, hands=3)
    before = deepcopy(obs)
    action = v10.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 3
    assert len(action["market"]) <= 10
    assert v10.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}


def test_v10_uses_v9_mission_continuity(monkeypatch) -> None:
    obs = make_obs(day=7, hour=4, hands=2)
    observed: dict[str, int] = {}

    def mission(positions, _inventories, _tasks, step):
        observed["units"] = len(positions)
        observed["step"] = step
        return [["PASS"] for _ in positions]

    monkeypatch.setattr(v10.v9, "_mission_assign", mission)
    action = v10.agent(obs)
    assert observed == {"units": 3, "step": 172}
    assert len(action["hands"]) == 2


def test_v10_submission_resolves_all_helpers_from_another_cwd(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    files = json.loads((root / "agents" / "v10" / "submission_manifest.json").read_text(encoding="utf-8"))["files"]
    for entry in files:
        source = (root / "agents" / "v10" / entry["source"]).resolve()
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
