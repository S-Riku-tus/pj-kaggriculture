from __future__ import annotations

import copy
import gzip
import importlib.util
import json
import sys
import tarfile
from pathlib import Path

import pytest
from kaggle_environments import make
from kaggle_environments.errors import InvalidArgument

ROOT = Path(__file__).resolve().parents[1]
ROUND6_ARCHIVE = ROOT / "artifacts/submissions/learning_round6_20260922_sequence_bc_v1.tar.gz"
PLAN_ARCHIVE = ROOT / "artifacts/submissions/learning_round7_20260922_plan_v1.tar.gz"
FINAL_ARCHIVE = ROOT / "artifacts/submissions/learning_round7_20260922_arm_b_plan_v3.tar.gz"
DAY1_REPLAY = (
    ROOT
    / "experiments/learning_round6_20260922/development_evaluation/replays/round6_sequence_bc_v1/v122"
    / "seed_2026102201_seat_1.json.gz"
)


def _extract(archive: Path, target: Path) -> Path:
    target.mkdir()
    with tarfile.open(archive, "r:gz") as stream:
        stream.extractall(target, filter="data")
    return target


def _load_main(path: Path, name: str):
    for module_name in ("policy", "runtime", "common", name):
        sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    sys.path.insert(0, str(path.parent))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def _observation(replay: dict, step: int, seat: int) -> dict:
    public = copy.deepcopy(replay["steps"][step][0]["observation"])
    private = replay["steps"][step][seat]["observation"]
    public["player"] = seat
    public["private"] = copy.deepcopy(private["private"])
    public["remainingOverageTime"] = private.get("remainingOverageTime", 60)
    public["step"] = step
    return public


def test_round6_archive_fails_fixed_official_path_loader(tmp_path: Path) -> None:
    extracted = _extract(ROUND6_ARCHIVE, tmp_path / "round6")
    env = make("kaggriculture", configuration={"episodeSteps": 2}, debug=True)
    with pytest.raises(InvalidArgument, match="__name__"):
        env.run([str(extracted / "main.py"), "pass"])


def test_round7_archive_passes_fixed_official_path_loader(tmp_path: Path) -> None:
    extracted = _extract(PLAN_ARCHIVE, tmp_path / "round7")
    env = make("kaggriculture", configuration={"episodeSteps": 3, "seed": 20260922}, debug=True)
    env.run([str(extracted / "main.py"), "pass"])
    assert [state.status for state in env.steps[-1]] == ["DONE", "DONE"]


def test_day1_failure_is_reassigned_to_the_wheat_carrier(tmp_path: Path) -> None:
    extracted = _extract(PLAN_ARCHIVE, tmp_path / "plan")
    module = _load_main(extracted / "main.py", "round7_plan_day1")
    with gzip.open(DAY1_REPLAY, "rt", encoding="utf-8") as stream:
        replay = json.load(stream)
    emitted = [module.agent(_observation(replay, step, 1), {}) for step in range(28)]
    assert emitted[26]["farmer"] == ["PICKUP", "WHEAT", 2]
    assert emitted[27]["farmer"] == ["FEED"]
    assert emitted[27]["hands"][2] != ["FEED"]


def test_final_capacity_archive_uses_two_hidden_layers_and_completes_day1_feed(tmp_path: Path) -> None:
    extracted = _extract(FINAL_ARCHIVE, tmp_path / "final_capacity")
    module = _load_main(extracted / "main.py", "round7_final_capacity")
    policy = sys.modules["policy"]
    assert len(policy.ACTOR_MODEL.layers) == 3
    assert [tuple(weight.shape) for weight, _bias in policy.ACTOR_MODEL.layers] == [
        (407, 128),
        (128, 64),
        (64, 44),
    ]
    with gzip.open(DAY1_REPLAY, "rt", encoding="utf-8") as stream:
        replay = json.load(stream)
    emitted = [module.agent(_observation(replay, step, 1), {}) for step in range(28)]
    assert emitted[26]["farmer"] == ["PICKUP", "WHEAT", 2]
    assert emitted[27]["farmer"] == ["FEED"]


def test_final_wrapper_keeps_agent_as_last_callable(tmp_path: Path) -> None:
    extracted = _extract(FINAL_ARCHIVE, tmp_path / "final_loader")
    env = make("kaggriculture", configuration={"episodeSteps": 3, "seed": 20260922}, debug=True)
    env.run([str(extracted / "main.py"), "pass"])
    assert [state.status for state in env.steps[-1]] == ["DONE", "DONE"]


def test_final_plan_reserves_large_farm_workforce_for_non_livestock_work(tmp_path: Path) -> None:
    extracted = _extract(FINAL_ARCHIVE, tmp_path / "final_budget")
    _load_main(extracted / "main.py", "round7_final_budget")
    runtime = sys.modules["runtime"]
    env = make("kaggriculture", configuration={"episodeSteps": 2, "seed": 9}, debug=True)
    env.reset()
    observation = env.toJSON()["steps"][0][0]["observation"]
    farm = observation["farms"][0]
    farm["farmer"] = [4, 4]
    farm["hands"] = [[4, 4] for _ in range(5)]
    observation["private"]["inventories"] = [{"WHEAT": 1} for _ in range(6)]
    for x, y in ((0, 0), (0, 1), (1, 0), (8, 8), (8, 9), (9, 8)):
        farm["tiles"][x][y] = {
            "kind": "PASTURE",
            "animal": "COW",
            "placed_day": 0,
            "yield_units": 0,
            "fed_today": False,
            "consecutive_unfed": 1,
            "cared_today": False,
            "fertilizer_available": False,
            "pending_care_bonus": 0,
        }
    base = {"farmer": ["PASS"], "hands": [["PASS"] for _ in range(5)], "market": []}
    runtime._plans[0] = {"created_step": 0, "signals": [], "source": "test"}
    result = runtime._apply_plan(observation, base)
    changed = sum(action != ["PASS"] for action in [result["farmer"], *result["hands"]])
    trace = runtime.diagnostics()["trace"][0][-1]
    assert trace["service_budget"] == 2
    assert changed == 2


def test_plan_allocates_two_carriers_to_two_translated_targets(tmp_path: Path) -> None:
    extracted = _extract(PLAN_ARCHIVE, tmp_path / "translated")
    _load_main(extracted / "main.py", "round7_plan_translated")
    runtime = sys.modules["runtime"]
    env = make("kaggriculture", configuration={"episodeSteps": 2, "seed": 7}, debug=True)
    env.reset()
    observation = env.toJSON()["steps"][0][0]["observation"]
    farm = observation["farms"][0]
    farm["farmer"] = [1, 1]
    farm["hands"] = [[8, 8]]
    observation["private"]["inventories"] = [{"WHEAT": 1}, {"WHEAT": 1}]
    farm["tiles"][0][1] = {
        "kind": "PASTURE",
        "animal": "COW",
        "placed_day": 0,
        "yield_units": 0,
        "fed_today": False,
        "consecutive_unfed": 1,
        "cared_today": False,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }
    farm["tiles"][9][8] = copy.deepcopy(farm["tiles"][0][1])
    base = {
        "farmer": ["PASS"],
        "hands": [["PASS"]],
        "market": [["BUY_ANIMAL", "COW", 1]],
    }
    result = runtime._apply_plan(observation, base)
    assert result["farmer"] == ["NORTH"]
    assert result["hands"] == [["SOUTH"]]


def test_plan_does_not_force_livestock_survival_in_endgame(tmp_path: Path) -> None:
    extracted = _extract(PLAN_ARCHIVE, tmp_path / "endgame")
    _load_main(extracted / "main.py", "round7_plan_endgame")
    runtime = sys.modules["runtime"]
    env = make("kaggriculture", configuration={"episodeSteps": 2, "seed": 8}, debug=True)
    env.reset()
    observation = env.toJSON()["steps"][0][0]["observation"]
    observation["day"] = 28
    observation["hour"] = 0
    observation["farms"][0]["tiles"][4][4] = {
        "kind": "PASTURE",
        "animal": "COW",
        "placed_day": 28,
        "yield_units": 0,
        "fed_today": False,
        "consecutive_unfed": 1,
        "cared_today": False,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }
    observation["private"]["inventories"] = [{"WHEAT": 1}]
    base = {"farmer": ["WEST"], "hands": [], "market": []}
    runtime._plans[0] = {"created_step": 100, "signals": [], "source": "test"}
    assert runtime._apply_plan(observation, copy.deepcopy(base)) == base


def test_saved_contract_evidence_is_green_and_records_quantity_collapse() -> None:
    fixtures = json.loads(
        (ROOT / "experiments/learning_round7_20260922/minimal_fixtures/engine_contracts.json").read_text(
            encoding="utf-8"
        )
    )
    audit = json.loads(
        (ROOT / "experiments/learning_round7_20260922/phase0/data_contract_audit.json").read_text(encoding="utf-8")
    )
    assert fixtures["all_success_conditions_passed"] is True
    assert audit["feature_parity"]["all_equal"] is True
    assert audit["leakage_and_quantity"]["forbidden_identity_and_future_fields_ignored"] is True
    assert audit["leakage_and_quantity"]["same_token_different_quantity_prefix_equal"] is True
    assert audit["split"]["cross_partition_episode_ids"] == []
