from __future__ import annotations

import copy
import hashlib
import importlib.util
import sys
import tarfile
from pathlib import Path

from kaggle_environments import make

ROOT = Path(__file__).resolve().parents[1]
F1 = ROOT / "artifacts/submissions/round8_execution_reset_20260922_f1_harvest_v4.tar.gz"
F2 = ROOT / "artifacts/submissions/round8_execution_reset_20260922_f2_consistent_v4.tar.gz"


def _extract(archive: Path, target: Path) -> Path:
    target.mkdir()
    with tarfile.open(archive, "r:gz") as stream:
        stream.extractall(target, filter="data")
    return target


def _load(path: Path, name: str):
    for module_name in ("policy", "runtime", "common", name):
        sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    sys.path.insert(0, str(path.parent))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, sys.modules["runtime"]
    finally:
        sys.path.pop(0)


def _observation(seed: int = 20260922) -> dict:
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 3, "seed": seed, "weedSpawnChance": 0.0},
        debug=True,
    )
    env.reset(2)
    return copy.deepcopy(env.toJSON()["steps"][0][0]["observation"])


def _animal(animal: str, *, day: int = 0, yield_units: int = 0, fed: bool = False, cared: bool = False) -> dict:
    return {
        "kind": "COOP" if animal == "GOOSE" else "PASTURE",
        "animal": animal,
        "placed_day": day,
        "yield_units": yield_units,
        "consecutive_unfed": 0,
        "fed_today": fed,
        "cared_today": cared,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }


def _plant(crop: str, planted_day: int, yield_units: int) -> dict:
    return {
        "kind": "PLANT",
        "crop": crop,
        "planted_day": planted_day,
        "watered_today": False,
        "consecutive_unwatered": 1,
        "yield_units": yield_units,
        "max_lifespan_step": 720,
        "fertilized_until_day": -1,
    }


def test_harvest_contract_matches_saved_ready_cow_and_immature_carrot(tmp_path: Path) -> None:
    extracted = _extract(F2, tmp_path / "f2")
    _module, runtime = _load(extracted / "main.py", "round8_fixtures")
    observation = _observation()
    observation["farms"][0]["farmer"] = [4, 4]
    observation["farms"][0]["tiles"][4][4] = _animal("COW", yield_units=6)
    ready = runtime._contract_legal_tokens(observation, 0, {}, full_contract=True)
    assert "HARVEST" in ready

    observation["day"] = 22
    observation["hour"] = 10
    observation["farms"][0]["farmer"] = [9, 2]
    observation["farms"][0]["tiles"][2][9] = _plant("CARROT", 22, 1)
    immature = runtime._contract_legal_tokens(observation, 0, {}, full_contract=True)
    assert "HARVEST" not in immature


def test_f1_isolates_harvest_while_f2_matches_engine_care_contract(tmp_path: Path) -> None:
    extracted = _extract(F1, tmp_path / "f1")
    _module, runtime = _load(extracted / "main.py", "round8_f1_contract")
    observation = _observation()
    observation["farms"][0]["tiles"][4][4] = _animal("COW", yield_units=2, fed=False)
    f1_legal = runtime._contract_legal_tokens(observation, 0, {}, full_contract=False)
    f2_legal = runtime._contract_legal_tokens(observation, 0, {}, full_contract=True)
    assert "HARVEST" in f1_legal
    assert "CARE" not in f1_legal
    assert "CARE" in f2_legal


def test_final_resolver_prevents_post_plan_pickup_overrequest(tmp_path: Path) -> None:
    extracted = _extract(F2, tmp_path / "f2")
    _module, runtime = _load(extracted / "main.py", "round8_pickup")
    observation = _observation()
    observation["farms"][0]["farmer"] = [4, 4]
    observation["farms"][0]["hands"] = [[4, 4], [4, 4]]
    observation["private"]["inventories"] = [{}, {}, {}]
    observation["private"]["shed"]["WHEAT"] = 2
    proposed = {
        "farmer": ["PICKUP", "WHEAT", 2],
        "hands": [["PICKUP", "WHEAT", 2], ["PICKUP", "WHEAT", 2]],
        "market": [],
    }
    final, trace = runtime.resolve_final_action(observation, proposed)
    assert final == {"farmer": ["PICKUP", "WHEAT", 2], "hands": [["PASS"], ["PASS"]], "market": []}
    assert sum(row["executable_quantity"] for row in trace["actors"]) == 2
    assert trace["actors"][0]["model_requested_quantity"] == 2


def test_same_coordinate_generation_sequence_is_not_blanket_blocked(tmp_path: Path) -> None:
    extracted = _extract(F2, tmp_path / "f2")
    _module, runtime = _load(extracted / "main.py", "round8_generation")
    observation = _observation()
    observation["day"] = 2
    observation["farms"][0]["farmer"] = [1, 1]
    observation["farms"][0]["hands"] = [[1, 1], [1, 1]]
    observation["private"]["inventories"] = [{}, {}, {}]
    observation["private"]["seeds"]["WHEAT"] = 1
    observation["farms"][0]["tiles"][1][1] = _plant("WHEAT", 0, 1)
    proposed = {
        "farmer": ["HARVEST"],
        "hands": [["PLANT", "WHEAT"], ["WATER"]],
        "market": [],
    }
    final, trace = runtime.resolve_final_action(observation, proposed)
    assert final["farmer"] == ["HARVEST"]
    assert final["hands"] == [["PLANT", "WHEAT"], ["WATER"]]
    assert trace["actors"][0]["target_before"]["generation"] == 0
    assert trace["actors"][1]["target_after"]["generation"] == 2
    assert trace["actors"][2]["expected_effect"] == {"watered_today": True}


def test_final_resolver_avoids_atomic_plant_shortage_cancellation(tmp_path: Path) -> None:
    extracted = _extract(F2, tmp_path / "f2")
    _module, runtime = _load(extracted / "main.py", "round8_plant")
    observation = _observation()
    observation["farms"][0]["farmer"] = [1, 1]
    observation["farms"][0]["hands"] = [[2, 1]]
    observation["private"]["inventories"] = [{}, {}]
    observation["private"]["seeds"]["WHEAT"] = 1
    proposed = {"farmer": ["PLANT", "WHEAT"], "hands": [["PLANT", "WHEAT"]], "market": []}
    final, _trace = runtime.resolve_final_action(observation, proposed)
    assert final["farmer"] == ["PLANT", "WHEAT"]
    assert final["hands"] == [["PASS"]]


def test_actor_cannot_use_same_turn_market_purchase(tmp_path: Path) -> None:
    extracted = _extract(F2, tmp_path / "f2")
    _module, runtime = _load(extracted / "main.py", "round8_actor_market")
    observation = _observation()
    observation["farms"][0]["tiles"][4][4] = _animal("COW")
    proposed = {
        "farmer": ["FEED"],
        "hands": [],
        "market": [["BUY_PRODUCT", "WHEAT", 1]],
    }
    final, trace = runtime.resolve_final_action(observation, proposed)
    assert final["farmer"] == ["PASS"]
    assert final["market"] == [["BUY_PRODUCT", "WHEAT", 1]]
    assert trace["actors"][0]["reason"] == "not_executable"


def test_plan_trace_snapshots_do_not_gain_future_signals(tmp_path: Path) -> None:
    extracted = _extract(F2, tmp_path / "f2")
    _module, runtime = _load(extracted / "main.py", "round8_trace_copy")
    observation = _observation()
    observation["farms"][0]["tiles"][4][4] = _animal("COW")
    base = {"farmer": ["FEED"], "hands": [], "market": []}
    _first_action, first_trace = runtime._apply_plan(observation, copy.deepcopy(base), repaired_endgame=True)
    first_signal_count = len(first_trace["plan_snapshot"]["signals"])
    observation["hour"] = 1
    runtime._apply_plan(observation, copy.deepcopy(base), repaired_endgame=True)
    assert len(first_trace["plan_snapshot"]["signals"]) == first_signal_count


def test_official_path_loader_uses_root_main_agent(tmp_path: Path) -> None:
    extracted = _extract(F2, tmp_path / "loader")
    for module_name in ("policy", "runtime", "common"):
        sys.modules.pop(module_name, None)
    env = make("kaggriculture", configuration={"episodeSteps": 3, "seed": 20260922}, debug=True)
    try:
        env.run([str(extracted / "main.py"), "pass"])
        assert [state.status for state in env.steps[-1]] == ["DONE", "DONE"]
    finally:
        for module_name in ("policy", "runtime", "model_compat", "common"):
            sys.modules.pop(module_name, None)


def test_spatial_encoder_distinguishes_f5_east_west_maturity_swap() -> None:
    source = ROOT / "agents" / "round8_execution_reset_20260922"
    sys.path.insert(0, str(source))
    try:
        import spatial

        west = _observation()
        west["day"] = 4
        west["hour"] = 0
        west["farms"][0]["farmer"] = [2, 2]
        west["farms"][0]["tiles"][2][1] = _plant("WHEAT", 0, 2)
        west["farms"][0]["tiles"][2][3] = _plant("WHEAT", 4, 1)
        east = copy.deepcopy(west)
        east["farms"][0]["tiles"][2][1], east["farms"][0]["tiles"][2][3] = (
            east["farms"][0]["tiles"][2][3],
            east["farms"][0]["tiles"][2][1],
        )
        west_features = spatial.grid_features(west)
        east_features = spatial.grid_features(east)
        assert not (west_features == east_features).all()
        assert hashlib.sha256(west_features.tobytes()).hexdigest() != hashlib.sha256(
            east_features.tobytes()
        ).hexdigest()
    finally:
        sys.path.pop(0)
        sys.modules.pop("spatial", None)


def test_spatial_prefix_keeps_quantity_target_and_effect() -> None:
    source = ROOT / "agents" / "round8_execution_reset_20260922"
    sys.path.insert(0, str(source))
    try:
        import spatial

        target = {"position": [4, 4], "resource": "WHEAT", "generation": 3}
        one = [spatial.make_prefix_entry("PICKUP:WHEAT", 1, target, False, ["PASS"])]
        two = [spatial.make_prefix_entry("PICKUP:WHEAT", 2, target, True, ["PICKUP", "WHEAT", 2])]
        assert not (spatial.prefix_extra_features(one) == spatial.prefix_extra_features(two)).all()
    finally:
        sys.path.pop(0)
        sys.modules.pop("spatial", None)
