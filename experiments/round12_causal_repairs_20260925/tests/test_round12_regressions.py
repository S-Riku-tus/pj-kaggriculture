from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ROUND12 = Path(__file__).resolve().parents[1]
ROUND11 = ROOT / "experiments/round11_execution_20260924"
REVISION = ROOT / "experiments/Kaggriculture_Round11_Research_Revision_20260924"
_DLL_HANDLE = None


def init_kagsim():
    global _DLL_HANDLE
    engine = ROOT / "experiments/round10_public_learning_20260924/engines/kaggriculture-cppsim"
    mingw = Path(r"C:\msys64\ucrt64\bin")
    sys.path.insert(0, str(engine))
    if os.name == "nt" and hasattr(os, "add_dll_directory") and mingw.is_dir():
        _DLL_HANDLE = _DLL_HANDLE or os.add_dll_directory(str(mingw))
    try:
        import kagsim
    finally:
        sys.path.pop(0)
    return kagsim


def replay(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def exec_namespace(path: Path):
    namespace = {}
    exec(compile(path.read_text(encoding="utf-8"), "<string>", "exec"), namespace)
    entry = [value for value in namespace.values() if callable(value)][-1]
    return entry, namespace


@pytest.fixture(scope="module")
def repaired():
    return exec_namespace(ROUND12 / "agents/P0_ledger_censor/main.py")


def test_final_ledger_matches_final_action_and_fill(repaired):
    _entry, namespace = repaired
    data = replay(ROUND11 / "holdout/m20_kagsim/replays/m20_multi_hypothesis/v57/seed_612609264_seat_0.json.gz")
    record = data["decisions"][645]
    action = record["actions"][0]
    assert action["market"] == [
        ["SELL", "STRAWBERRY", 13],
        ["SELL", "WOOL", 7],
        ["BUY_SEED", "CARROT", 1],
    ]
    fills, left = namespace["_r12_effective_sell_fills"](record["observations"][0], action)
    assert fills["WOOL"] == 7
    assert fills["STRAWBERRY"] == 13
    assert left["WOOL"] == 0
    assert left["STRAWBERRY"] == 5


def test_mid_order_price_floor_censoring(repaired):
    _entry, namespace = repaired
    data = replay(ROUND11 / "holdout/m20_kagsim/replays/B1/v57/seed_612609254_seat_0.json.gz")
    current = data["decisions"][456]
    following = data["decisions"][457]
    observation = current["observations"][0]
    action = current["actions"][0]
    fills, _left = namespace["_r12_effective_sell_fills"](observation, action)
    assert observation["market"]["prices"]["WOOL"] == 37
    assert fills["WOOL"] == 12
    previous = {
        "step": 456,
        "inventory": dict(observation["market"]["inventory"]),
        "prices": dict(observation["market"]["prices"]),
        "own": fills,
        "shops": list(observation["town"]["unlocked_shops"]),
    }
    interval = namespace["_r12_rival_interval"](following["observations"][0], previous, "WOOL")
    assert interval["confidence"] == "censored"
    assert interval["lower"] == 0
    assert interval["upper"] == 100
    # The old point estimate was -6 although the true opponent fill was 12.
    assert interval["lower"] <= 12 <= interval["upper"]

    exact_observation = copy.deepcopy(following["observations"][0])
    exact_observation["market"]["inventory"]["MILK"] = previous["inventory"]["MILK"] + 5
    exact_previous = copy.deepcopy(previous)
    exact_previous["own"]["MILK"] = 2
    exact_previous["shops"] = []
    exact_previous["step"] = 455
    exact_observation["step"] = 456
    exact = namespace["_r12_rival_interval"](exact_observation, exact_previous, "MILK")
    assert exact["confidence"] == "exact"
    assert exact["lower"] == exact["upper"] == 3


def test_cw1_redundant_with_existing_predictor():
    path = ROUND11 / "track_b/conditional_wool_kagsim/replays/B1/B1/seed_532609243_seat_0.json.gz"
    data = replay(path)
    b1_entry, _b1_namespace = exec_namespace(REVISION / "inputs/agents/B1.py")
    cw1_entry, _cw1_namespace = exec_namespace(ROUND11 / "arms/cw1_conditional_wool/main.py")
    b1 = cw1 = None
    for record in data["decisions"][:669]:
        observation = record["observations"][0]
        b1 = b1_entry(observation)
        cw1 = cw1_entry(observation)
    assert b1 == cw1
    assert ["SELL", "WOOL", 3] in b1["market"]
    assert sum(order[:2] == ["SELL", "WOOL"] for order in cw1["market"]) == 1


def test_candidate_evaluation_is_state_pure():
    _entry, namespace = exec_namespace(ROUND12 / "agents/P0M1_market/main.py")
    data = replay(ROUND11 / "holdout/m20_kagsim/replays/B1/v57/seed_612609254_seat_0.json.gz")
    record = data["decisions"][412]
    observation = record["observations"][0]
    before = copy.deepcopy(record["actions"][0])
    before["market"] = [order for order in before["market"] if order[:2] != ["SELL", "WOOL"]]
    baseline = copy.deepcopy(before)
    baseline["market"] = [["SELL", "WOOL", 4], *baseline["market"]]
    capture = {"before": before, "increments": {"WOOL": 4}}
    predictor_state = {"obs": {}}
    snapshots = {
        "race": copy.deepcopy(namespace["_V9_RACE"]),
        "predictor": copy.deepcopy(namespace["_V92_P"]),
        "market": copy.deepcopy(namespace["_R12_M_STATE"]),
        "action": copy.deepcopy(baseline),
    }
    selected, decision = namespace["_r12_evaluate_market_candidates"](
        observation, baseline, capture, predictor_state
    )
    assert isinstance(selected, dict)
    assert len(decision["candidates"]) == 4
    assert namespace["_V9_RACE"] == snapshots["race"]
    assert namespace["_V92_P"] == snapshots["predictor"]
    assert namespace["_R12_M_STATE"] == snapshots["market"]
    assert baseline == snapshots["action"]


def test_branch_opponent_remains_reactive():
    kagsim = init_kagsim()
    opponent, _namespace = exec_namespace(REVISION / "inputs/agents/v57.py")
    calls = []

    def reactive(observation):
        calls.append((observation["step"], observation["market"]["prices"]["WOOL"]))
        return opponent(observation)

    game = kagsim.Game(712609241)
    for _ in range(8):
        observations = [game.observe(0), game.observe(1)]
        action0 = {"farmer": ["PASS"], "hands": [], "market": []}
        action1 = reactive(observations[1])
        game.step(action0, action1)
    assert len(calls) == 8
    assert [step for step, _price in calls] == list(range(8))


def test_new_route_feasibility_and_completion():
    kagsim = init_kagsim()
    route, _namespace = exec_namespace(ROUND12 / "agents/P1M0_strawberry_route/main.py")
    opponent, _opponent_namespace = exec_namespace(REVISION / "inputs/agents/B1.py")
    game = kagsim.Game(712609241)
    first_strawberry_day = None
    peak_strawberries = 0
    while not game.done:
        observations = [game.observe(0), game.observe(1)]
        actions = [route(observations[0]), opponent(observations[1])]
        game.step(actions[0], actions[1])
        farm = game.observe(0)["farms"][0]
        count = sum(
            isinstance(tile, dict) and tile.get("crop") == "STRAWBERRY"
            for row in farm["tiles"]
            for tile in row
        )
        peak_strawberries = max(peak_strawberries, count)
        if count and first_strawberry_day is None:
            first_strawberry_day = int(game.observe(0)["day"])
    assert game.step_count == 719
    assert first_strawberry_day is not None and first_strawberry_day <= 3
    assert peak_strawberries >= 8
    assert game.reward(0) > 0


def test_loader_archive_and_episode_reset(tmp_path):
    from kaggle_environments.agent import get_last_callable

    source_path = ROUND12 / "agents/P1M0_strawberry_route/main.py"
    source = source_path.read_bytes()
    archive = tmp_path / "candidate.tar.gz"
    info = tarfile.TarInfo("main.py")
    info.size = len(source)
    with tarfile.open(archive, "w:gz") as stream:
        stream.addfile(info, io.BytesIO(source))
    with tarfile.open(archive, "r:gz") as stream:
        member = stream.extractfile("main.py")
        assert member is not None
        archived_source = member.read()
    assert hashlib.sha256(archived_source).hexdigest() == hashlib.sha256(source).hexdigest()
    entry0 = get_last_callable(archived_source.decode("utf-8"))
    entry1 = get_last_callable(archived_source.decode("utf-8"))
    assert entry0.__name__ == entry1.__name__ == "strawberry_route_agent"

    kagsim = init_kagsim()
    observation0 = kagsim.Game(712609241).observe(0)
    observation1 = kagsim.Game(712609241).observe(1)
    first0 = entry0(observation0)
    first1 = entry1(observation1)
    repeated0 = entry0(observation0)
    assert first0 == repeated0
    assert first0 == first1
