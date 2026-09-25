"""Run Round8 final-action fixtures against the frozen 1.32.7 engine."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kaggle_environments import make
from kaggle_environments.envs.kaggriculture import kaggriculture as engine

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "round8_execution_reset_20260922"
ARCHIVE = ROOT / "artifacts/submissions/round8_execution_reset_20260922_f2_consistent_v4.tar.gz"
OUTPUT = EXPERIMENT / "fixtures" / "engine_contracts_v2.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_runtime(target: Path) -> Any:
    target.mkdir()
    with tarfile.open(ARCHIVE, "r:gz") as stream:
        stream.extractall(target, filter="data")
    for name in ("runtime", "policy", "model_compat", "common"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("round8_fixture_main", target / "main.py")
    if spec is None or spec.loader is None:
        raise ImportError(target / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return sys.modules["runtime"]


def observation() -> dict[str, Any]:
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 3, "seed": 20260922, "weedSpawnChance": 0.0},
        debug=True,
    )
    env.reset(2)
    return copy.deepcopy(env.toJSON()["steps"][0][0]["observation"])


def animal(animal_name: str, *, yield_units: int = 0) -> dict[str, Any]:
    return {
        "kind": "COOP" if animal_name == "GOOSE" else "PASTURE",
        "animal": animal_name,
        "placed_day": 0,
        "yield_units": yield_units,
        "consecutive_unfed": 0,
        "fed_today": False,
        "cared_today": False,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }


def plant(crop: str, planted_day: int, yield_units: int) -> dict[str, Any]:
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


def apply_engine_actor_sequence(obs: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(obs)
    farm = result["farms"][0]
    private = result["private"]
    units = [action["farmer"], *action.get("hands", [])]
    # The resolver has already made PLANT demand feasible; run the fixed engine
    # in its actual farmer-then-hands order.
    for index, unit in enumerate(units):
        engine._apply_unit_action(farm, private, index, unit, 10, int(result["day"]), 24, 100)
    return result


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUTPUT}")
    temp_parent = ROOT.parent / ".round8_tmp"
    temp_parent.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="contracts_", dir=temp_parent))
    try:
        runtime = load_runtime(temp / "agent")
        cases: list[dict[str, Any]] = []

        ready = observation()
        ready["day"], ready["hour"] = 8, 0
        ready["farms"][0]["farmer"] = [4, 4]
        ready["farms"][0]["tiles"][4][4] = animal("COW", yield_units=6)
        ready_legal = runtime._contract_legal_tokens(ready, 0, {}, full_contract=True)
        ready_final, ready_trace = runtime.resolve_final_action(
            ready, {"farmer": ["HARVEST"], "hands": [], "market": []}
        )
        ready_after = apply_engine_actor_sequence(ready, ready_final)
        cases.append(
            {
                "name": "episode111952429_record193_ready_cow_contract",
                "source": "saved counterexample reconstructed from focused_checks.json",
                "legal": "HARVEST" in ready_legal,
                "final_action": ready_final,
                "trace": ready_trace["actors"],
                "engine_effect": {
                    "milk_carried": ready_after["private"]["inventories"][0].get("MILK", 0),
                    "tile_yield": ready_after["farms"][0]["tiles"][4][4]["yield_units"],
                },
                "passed": ready_final["farmer"] == ["HARVEST"]
                and ready_after["private"]["inventories"][0].get("MILK", 0) == 6,
            }
        )

        immature = observation()
        immature["day"], immature["hour"] = 22, 10
        immature["farms"][0]["farmer"] = [9, 2]
        immature["farms"][0]["tiles"][2][9] = plant("CARROT", 22, 1)
        immature_legal = runtime._contract_legal_tokens(immature, 0, {}, full_contract=True)
        immature_final, immature_trace = runtime.resolve_final_action(
            immature, {"farmer": ["HARVEST"], "hands": [], "market": []}
        )
        immature_after = apply_engine_actor_sequence(immature, {"farmer": ["HARVEST"], "hands": [], "market": []})
        cases.append(
            {
                "name": "episode111953595_record539_immature_carrot_contract",
                "source": "saved counterexample reconstructed from focused_checks.json",
                "legal": "HARVEST" in immature_legal,
                "final_action": immature_final,
                "trace": immature_trace["actors"],
                "engine_effect_of_raw_request": {
                    "inventory": immature_after["private"]["inventories"][0],
                    "tile_yield": immature_after["farms"][0]["tiles"][2][9]["yield_units"],
                },
                "passed": immature_final["farmer"] == ["PASS"]
                and not immature_after["private"]["inventories"][0],
            }
        )

        pickup = observation()
        pickup["farms"][0]["farmer"] = [4, 4]
        pickup["farms"][0]["hands"] = [[4, 4], [4, 4]]
        pickup["private"]["inventories"] = [{}, {}, {}]
        pickup["private"]["shed"]["WHEAT"] = 2
        request = {
            "farmer": ["PICKUP", "WHEAT", 2],
            "hands": [["PICKUP", "WHEAT", 2], ["PICKUP", "WHEAT", 2]],
            "market": [],
        }
        pickup_final, pickup_trace = runtime.resolve_final_action(pickup, request)
        pickup_after = apply_engine_actor_sequence(pickup, pickup_final)
        cases.append(
            {
                "name": "episode111954710_record98_post_plan_pickup_ledger",
                "source": "saved counterexample shape reconstructed from focused_checks.json",
                "requested": request,
                "final_action": pickup_final,
                "trace": pickup_trace["actors"],
                "engine_inventories": pickup_after["private"]["inventories"],
                "passed": pickup_final["hands"] == [["PASS"], ["PASS"]]
                and pickup_after["private"]["inventories"][0].get("WHEAT") == 2,
            }
        )

        generation = observation()
        generation["day"] = 2
        generation["farms"][0]["farmer"] = [1, 1]
        generation["farms"][0]["hands"] = [[1, 1], [1, 1]]
        generation["private"]["inventories"] = [{}, {}, {}]
        generation["private"]["seeds"]["WHEAT"] = 1
        generation["farms"][0]["tiles"][1][1] = plant("WHEAT", 0, 1)
        generation_request = {
            "farmer": ["HARVEST"],
            "hands": [["PLANT", "WHEAT"], ["WATER"]],
            "market": [],
        }
        generation_final, generation_trace = runtime.resolve_final_action(generation, generation_request)
        generation_after = apply_engine_actor_sequence(generation, generation_final)
        generation_tile = generation_after["farms"][0]["tiles"][1][1]
        cases.append(
            {
                "name": "same_coordinate_new_generation_sequence",
                "requested": generation_request,
                "final_action": generation_final,
                "trace": generation_trace["actors"],
                "engine_tile": generation_tile,
                "passed": generation_final == generation_request
                and generation_tile["planted_day"] == 2
                and generation_tile["watered_today"] is True,
            }
        )

        care = observation()
        care["farms"][0]["tiles"][4][4] = animal("COW")
        care_final, care_trace = runtime.resolve_final_action(
            care, {"farmer": ["CARE"], "hands": [], "market": []}
        )
        care_after = apply_engine_actor_sequence(care, care_final)
        cases.append(
            {
                "name": "care_without_prior_feed_matches_fixed_engine",
                "final_action": care_final,
                "trace": care_trace["actors"],
                "engine_cared_today": care_after["farms"][0]["tiles"][4][4]["cared_today"],
                "passed": care_final["farmer"] == ["CARE"]
                and care_after["farms"][0]["tiles"][4][4]["cared_today"] is True,
            }
        )

        copied_engine = EXPERIMENT / "fixed_engine" / "kaggriculture.py"
        payload = {
            "created_at_utc": datetime.now(UTC).isoformat(),
            "purpose": "contract checks, not game-strength evaluation",
            "engine": {
                "installed_path": str(Path(engine.__file__).relative_to(ROOT)),
                "installed_sha256": sha256(Path(engine.__file__)),
                "copied_path": str(copied_engine.relative_to(ROOT)),
                "copied_sha256": sha256(copied_engine),
                "identical": sha256(Path(engine.__file__)) == sha256(copied_engine),
            },
            "archive": {"path": str(ARCHIVE.relative_to(ROOT)), "sha256": sha256(ARCHIVE)},
            "cases": cases,
            "all_passed": all(case["passed"] for case in cases),
        }
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(OUTPUT), "all_passed": payload["all_passed"]}, indent=2))
    finally:
        shutil.rmtree(temp)


if __name__ == "__main__":
    main()
