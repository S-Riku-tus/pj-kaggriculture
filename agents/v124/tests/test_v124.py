from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AGENT = ROOT / "agents/v124/main.py"
MODEL = ROOT / "agents/v124/policy_model.json.gz"
REPLAY = ROOT / "data/replays/v123_submission_56346090/episode_110716345.json"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, AGENT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_promoted_feature_gates_match_validation_evidence() -> None:
    policy = _load("v124_flags_test")
    assert policy.ENABLE_CURRENT_META_LIBRARY
    assert not policy.ENABLE_SEGMENT_ROUTER
    assert not policy.ENABLE_SELL_FORECAST
    assert not policy.base.ENABLE_CLONE_PREEMPTION


def test_canonical_clock_ignores_seat_dependent_step_field() -> None:
    policy = _load("v124_clock_test")
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    observation = dict(replay["steps"][319][1]["observation"])
    observation["step"] = -999
    canonical = policy._canonical_observation(observation)
    assert canonical["step"] == 24 * int(observation["day"]) + int(observation["hour"])
    assert canonical["step"] == 319


def test_current_meta_model_is_anonymous_and_has_44_sources() -> None:
    with gzip.open(MODEL, "rt", encoding="utf-8") as stream:
        model = json.load(stream)
    assert set(model) == {"format", "feature_length", "beam_size", "gate_steps", "steps"}
    assert model["format"] == "v121-sparse-continuation-v1"
    assert len(model["steps"]) == 719
    rows = model["steps"][288]
    assert len({int(row[1]) for row in rows}) == 44
    assert all(len(row) == 6 and len(row[4]) == 558 for row in rows)


def test_three_day_segment_latches_without_replay_drift() -> None:
    policy = _load("v124_segment_test")
    policy.ENABLE_SEGMENT_ROUTER = True
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    policy.reset_runtime_state()
    for step in range(312):
        observation = replay["steps"][step][0]["observation"]
        action = policy.agent(observation, replay["configuration"])
        assert set(action) == {"farmer", "hands", "market"}
    diagnostic = policy.policy_diagnostics(observation)
    assert diagnostic["segment_source"] is not None
    assert diagnostic["segment_selected_at"] == 288
    assert diagnostic["segment_holds"] > 0
    assert diagnostic["segment_emergency_fallbacks"] == 0
    assert diagnostic["preemptions"] == 0


def test_submission_manifest_is_complete() -> None:
    manifest_path = ROOT / "agents/v124/submission_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {entry["target"] for entry in manifest["files"]} == {
        "main.py",
        "v123_base.py",
        "v121_sparse.py",
        "v120_base.py",
        "market_overlay.py",
        "policy_model.json.gz",
        "opponent_sell_model.json",
        "model_metadata.json",
        "NOTICE.md",
    }
    for entry in manifest["files"]:
        assert (manifest_path.parent / entry["source"]).resolve().is_file()
