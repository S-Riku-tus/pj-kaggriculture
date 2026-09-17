from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V119_MAIN = ROOT / "agents" / "v119" / "main.py"
PSR_MAIN = (
    ROOT
    / "experiments"
    / "research_20260914_clean_psr"
    / "candidates"
    / "P1_psr_clean"
    / "main.py"
)
EXPECTED_SHA256 = "91772fda544e2d5768afff819e2de75ecb7a12db8acb40a48ee9edcf76aca434"


def _load_v119():
    spec = importlib.util.spec_from_file_location("test_v119_module", V119_MAIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_policy_source_hash() -> None:
    assert hashlib.sha256(PSR_MAIN.read_bytes()).hexdigest() == EXPECTED_SHA256


def test_agent_delegates_without_mutation(monkeypatch) -> None:
    module = _load_v119()
    expected = {"farmer": ["PASS"], "hands": [], "market": []}
    received = {}

    def fake_agent(observation, configuration=None):
        received["observation"] = observation
        received["configuration"] = configuration
        return expected

    monkeypatch.setattr(module.base, "agent", fake_agent)
    observation = {"step": 7, "player": 1}
    configuration = {"episodeSteps": 720}
    assert module.agent(observation, configuration) is expected
    assert received == {"observation": observation, "configuration": configuration}
