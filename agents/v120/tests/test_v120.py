from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AGENT = ROOT / "agents/v120/main.py"
MODEL = ROOT / "agents/v120/model.json.gz"
TRAINING_REPLAY = ROOT / "data/replays/v119_submission_56298336/episode_110067832.json"


def load_agent():
    spec = importlib.util.spec_from_file_location("v120_test_policy", AGENT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_feature_contract_and_replay_alignment() -> None:
    policy = load_agent()
    replay = json.loads(TRAINING_REPLAY.read_text(encoding="utf-8"))
    observation = replay["steps"][0][0]["observation"]
    assert len(policy.feature_vector(observation)) == policy.FEATURE_LENGTH == 558
    assert policy.agent(observation) == replay["steps"][1][0]["action"]


def test_runtime_model_has_no_identity_or_outcome_fields() -> None:
    with gzip.open(MODEL, "rt", encoding="utf-8") as stream:
        model = json.load(stream)
    assert set(model) == {"format", "feature_length", "target_opening_hash", "steps"}
    assert len(model["steps"]) == 719
    assert sum(map(len, model["steps"])) == 26_603
    first_case = model["steps"][0][0]
    assert len(first_case) == 3
    assert len(first_case[1]) == 558


def test_output_has_one_action_per_worker() -> None:
    policy = load_agent()
    replay = json.loads(TRAINING_REPLAY.read_text(encoding="utf-8"))
    for replay_step in (1, 144, 360, 600, 718):
        observation = replay["steps"][replay_step][0]["observation"]
        action = policy.agent(observation)
        hands = observation["farms"][observation["player"]]["hands"]
        assert set(action) == {"farmer", "hands", "market"}
        assert len(action["hands"]) == len(hands)
        assert len(action["market"]) <= 10

