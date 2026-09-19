from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V123_PATH = ROOT / "agents/v123/main.py"
V122_PATH = ROOT / "agents/v122/main.py"
CLONE_REPLAY = ROOT / "data/submissions/v122_submission_56330890/episodes/110462734/replay/episode_110462734.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_opening_remains_v122_exact_before_continuation() -> None:
    v122 = _load("v122_opening_test", V122_PATH)
    v123 = _load("v123_opening_test", V123_PATH)
    replay = json.loads(CLONE_REPLAY.read_text(encoding="utf-8"))
    v122.reset_runtime_state()
    v123.reset_runtime_state()
    for step in (0, 24, 48, 72, 96, 120, 192, 287):
        observation = replay["steps"][step][0]["observation"]
        assert v123.agent(observation, replay["configuration"]) == v122.agent(observation, replay["configuration"])


def test_exact_public_opening_latches_clone_without_identity() -> None:
    v123 = _load("v123_clone_test", V123_PATH)
    replay = json.loads(CLONE_REPLAY.read_text(encoding="utf-8"))
    v123.reset_runtime_state()
    observation = None
    for step in (0, 24, 48, 72, 96):
        observation = replay["steps"][step][0]["observation"]
        v123.agent(observation, replay["configuration"])
    assert observation is not None
    diagnostic = v123.policy_diagnostics(observation)
    assert diagnostic["opening_clone"]
    assert diagnostic["clone_confirmations"] == 4


def test_promoted_flags_keep_rejected_coherence_disabled() -> None:
    v123 = _load("v123_flags_test", V123_PATH)
    assert not v123.ENABLE_COHERENCE
    assert v123.ENABLE_CLONE_PREEMPTION


def test_coherent_source_stays_latched_inside_gate_block() -> None:
    v123 = _load("v123_coherence_test", V123_PATH)
    replay = json.loads(CLONE_REPLAY.read_text(encoding="utf-8"))
    v123.reset_runtime_state()
    for step in range(289):
        observation = replay["steps"][step][0]["observation"]
        v123.agent(observation, replay["configuration"])
    source = v123.sparse._STATE["active_source"]
    assert source is not None
    for step in range(289, 312):
        observation = replay["steps"][step][0]["observation"]
        v123.agent(observation, replay["configuration"])
        assert v123.sparse._STATE["active_source"] == source


def test_clone_overlay_only_preempts_existing_next_turn_stock() -> None:
    v123 = _load("v123_preemption_test", V123_PATH)
    replay = json.loads(CLONE_REPLAY.read_text(encoding="utf-8"))
    v123.reset_runtime_state()
    last_observation = None
    for step in range(719):
        last_observation = replay["steps"][step][0]["observation"]
        v123.agent(last_observation, replay["configuration"])
    assert last_observation is not None
    diagnostic = v123.policy_diagnostics(last_observation)
    assert 0 < diagnostic["preemptions"] < 20
    assert diagnostic["last_preemption"]["target"] == diagnostic["last_preemption"]["step"] + 1


def test_submission_manifest_is_complete() -> None:
    manifest = json.loads((ROOT / "agents/v123/submission_manifest.json").read_text(encoding="utf-8"))
    assert {entry["target"] for entry in manifest["files"]} == {
        "main.py",
        "v121_sparse.py",
        "v120_base.py",
        "market_overlay.py",
        "model.json.gz",
        "model_metadata.json",
        "NOTICE.md",
    }
    for entry in manifest["files"]:
        assert (ROOT / "agents/v123" / entry["source"]).resolve().is_file()
