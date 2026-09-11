from types import SimpleNamespace

import pytest

from agents.v114r1 import main as candidate


@pytest.mark.parametrize(
    "shops, expected",
    [
        (["YARN_STORE", "BAKERY"], "yarn_first"),
        (["BAKERY", "YARN_STORE"], "yarn_second"),
        (["BAKERY", "PIZZA_SHOP"], "default"),
    ],
)
def test_checkpoint_accepts_engine_configuration_and_missing_step(monkeypatch, shops, expected):
    candidate.reset_runtime_state()
    monkeypatch.setattr(candidate.base, "agent", lambda obs, configuration: {"farmer": ["PASS"]})
    monkeypatch.setattr(candidate.base, "_fallback_latched", lambda obs: True)
    obs = {"player": 0, "day": 6, "hour": 9, "town": {"unlocked_shops": shops}}
    emitted = candidate.agent(obs, SimpleNamespace(episodeSteps=720, seed=10091011))
    assert emitted == {"farmer": ["PASS"]}
    assert candidate.policy_diagnostics(obs)["research_decision"]["original"] == expected
