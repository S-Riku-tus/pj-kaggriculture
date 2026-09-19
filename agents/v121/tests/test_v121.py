from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AGENT = ROOT / "agents/v121/main.py"
MODEL = ROOT / "agents/v121/model.json.gz"
V120_MODEL = ROOT / "agents/v120/model.json.gz"
OPENING_REPLAY = ROOT / "data/replays/v119_submission_56298336/episode_110067832.json"
CONTINUATION_REPLAY = ROOT / "data/replays/v120_submission_56317532/episode_110320426.json"


def load_agent():
    spec = importlib.util.spec_from_file_location("v121_test_policy", AGENT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_opening_is_exact_v120_policy() -> None:
    policy = load_agent()
    replay = json.loads(OPENING_REPLAY.read_text(encoding="utf-8"))
    observation = replay["steps"][0][0]["observation"]
    with gzip.open(V120_MODEL, "rt", encoding="utf-8") as stream:
        v120 = json.load(stream)
    expected = v120["steps"][0][0][2]
    policy.reset_runtime_state()
    assert policy.agent(observation) == expected


def test_runtime_model_has_no_analysis_identity_or_outcome_fields() -> None:
    with gzip.open(MODEL, "rt", encoding="utf-8") as stream:
        model = json.load(stream)
    assert set(model) == {"format", "feature_length", "beam_size", "gate_steps", "steps"}
    assert model["format"] == "v121-sparse-continuation-v1"
    assert len(model["steps"]) == 719
    assert len(model["steps"][288][0]) == 6
    assert len(model["steps"][288][0][4]) == 558


def test_sparse_route_latches_and_outputs_match_worker_count() -> None:
    policy = load_agent()
    replay = json.loads(CONTINUATION_REPLAY.read_text(encoding="utf-8"))
    policy.reset_runtime_state()
    for step in (288, 289, 360, 432, 480, 576, 648, 718):
        observation = replay["steps"][step][0]["observation"]
        action = policy.agent(observation)
        assert set(action) == {"farmer", "hands", "market"}
        assert len(action["hands"]) == len(observation["farms"][0]["hands"])
        assert len(action["market"]) <= 10
    diagnostics = policy.policy_diagnostics()
    assert diagnostics["animal_route"] in {policy.BALANCED, policy.MILK, policy.WOOL}
    assert diagnostics["beam"]
    assert diagnostics["last_gate"] == 648


def test_expansion_requires_demand_cash_and_compatible_route() -> None:
    policy = load_agent()
    replay = json.loads(CONTINUATION_REPLAY.read_text(encoding="utf-8"))
    observation = replay["steps"][432][0]["observation"]
    result = policy.expansion_preconditions(observation)
    farm = observation["farms"][0]
    demand = policy.tomato_demand(observation)
    if len(farm["unlocked_quadrants"]) == 3 and farm["money"] >= 20_000 and demand >= 3:
        assert result == (policy.animal_route(observation) != policy.WOOL)
