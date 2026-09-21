from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from kaggle_environments import make

from agents.learning_round2_20260921.common import A2ValueModel, a2_candidates, observation_fingerprint
from scripts.learning_round2 import _load_module, _market_transition_labels

ROOT = Path(__file__).resolve().parents[1]


def _pass() -> dict:
    return {"farmer": ["PASS"], "hands": [], "market": []}


def test_a2_candidate_generation_is_read_only() -> None:
    replay = json.loads((ROOT / "data/replays/submission_56216119/episode_111063979.json").read_text(encoding="utf-8"))
    observation = deepcopy(replay["steps"][300][0]["observation"])
    observation["step"] = 300
    control = deepcopy(replay["steps"][301][0]["action"])
    before_observation = observation_fingerprint(observation)
    before_control = json.dumps(control, sort_keys=True)
    candidates = a2_candidates(observation, control, t_min=240)
    assert observation_fingerprint(observation) == before_observation
    assert json.dumps(control, sort_keys=True) == before_control
    assert len(candidates) <= 3
    for candidate in candidates:
        assert candidate["sequence"]
        assert candidate["deadline_step"] >= 300
        assert candidate["rejoin"]["tape_rewind"] is False


def test_missing_a2_model_is_explicit(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="required learned model is missing"):
        A2ValueModel(tmp_path / "missing.npz")


def test_b2_reconstruction_separates_requested_executed_and_impact() -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 2, "seed": 20260921}, debug=True)
    env.reset(2)
    env.state[0].observation.private.shed["WHEAT"] = 3
    action = {**_pass(), "market": [["SELL", "WHEAT", 1000]]}
    env.step([action, _pass()])
    replay = env.toJSON()
    labels = _market_transition_labels(replay, 0)
    assert labels["requested"][0]["WHEAT"] == 1000
    assert labels["executed"][0]["WHEAT"] == 3
    assert labels["impact"][0]["WHEAT"] == 3
    assert labels["revenue"][0]["WHEAT"] > 0
    assert labels["money_match"] and labels["market_match"]


def test_b2_price_floor_sale_executes_without_market_impact() -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 2, "seed": 20260921}, debug=True)
    env.reset(2)
    env.state[0].observation.private.shed["FERTILIZER"] = 1
    env.state[0].observation.market.inventory["FERTILIZER"] = 50000
    action = {**_pass(), "market": [["SELL", "FERTILIZER", 1]]}
    env.step([action, _pass()])
    labels = _market_transition_labels(env.toJSON(), 0)
    assert labels["requested"][0]["FERTILIZER"] == 1
    assert labels["executed"][0]["FERTILIZER"] == 1
    assert labels["impact"][0]["FERTILIZER"] == 0
    assert labels["revenue"][0]["FERTILIZER"] == 1
    assert labels["market_match"]


def test_standalone_common_module_is_isolated_between_arms(tmp_path: Path) -> None:
    modules = []
    for name, value in (("left", 1), ("right", 2)):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "common.py").write_text(f"VALUE = {value}\n", encoding="utf-8")
        (directory / "main.py").write_text(
            "from common import VALUE\n\ndef agent(*_args):\n    return VALUE\n",
            encoding="utf-8",
        )
        modules.append(_load_module(directory / "main.py", name))
    assert [module.agent() for module in modules] == [1, 2]
