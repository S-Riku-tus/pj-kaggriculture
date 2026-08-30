from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v109 import main as v109
from tests.test_agent_v105 import make_obs


def _action(hands: int, label: str = "PASS") -> dict:
    return {
        "farmer": [label],
        "hands": [["PASS"] for _ in range(hands)],
        "market": [],
    }


def test_v109_vendors_the_exact_public_source() -> None:
    path = Path(v109.__file__).with_name("public_v43_base.py")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == v109.PUBLIC_SOURCE_SHA256


def test_v109_normalizes_missing_step_without_mutating_input(monkeypatch) -> None:
    v109.reset_runtime_state()
    seen: list[int] = []

    def route(obs, _configuration=None):
        seen.append(obs["step"])
        return _action(2, "NORTH")

    monkeypatch.setattr(v109.public_v43, "agent", route)
    obs = make_obs(day=3, hour=5, hands=2)
    obs["step"] = None
    before = deepcopy(obs)
    assert v109.agent(obs) == _action(2, "NORTH")
    assert seen == [77]
    assert obs == before


def test_v109_confirms_land_lag_before_latching(monkeypatch) -> None:
    v109.reset_runtime_state()
    monkeypatch.setattr(
        v109.public_v43,
        "agent",
        lambda obs, _cfg=None: _action(len(obs["farms"][0]["hands"]), "NORTH"),
    )
    monkeypatch.setattr(v109.safe_rule, "agent", lambda obs: _action(len(obs["farms"][0]["hands"]), "SOUTH"))
    obs = make_obs(day=7, hour=0, hands=1)
    obs["farms"][0]["unlocked_quadrants"] = ["NW"]
    assert v109.agent(obs)["farmer"] == ["NORTH"]
    obs["step"] += 1
    obs["hour"] += 1
    assert v109.agent(obs)["farmer"] == ["SOUTH"]
    diagnostic = v109.policy_diagnostics(obs)
    assert diagnostic["fallback_latched"]
    assert diagnostic["fallback_reason"] == "second-land-missing"
    assert diagnostic["fallback_step"] == 169


def test_v109_does_not_latch_a_transient_land_warning(monkeypatch) -> None:
    v109.reset_runtime_state()
    monkeypatch.setattr(v109.public_v43, "agent", lambda obs, _cfg=None: _action(0))
    first = make_obs(day=7, hour=0)
    first["farms"][0]["unlocked_quadrants"] = ["NW"]
    v109.agent(first)
    recovered = make_obs(day=7, hour=1)
    recovered["farms"][0]["unlocked_quadrants"] = ["NW", "NE"]
    v109.agent(recovered)
    diagnostic = v109.policy_diagnostics(recovered)
    assert not diagnostic["fallback_latched"]
    assert diagnostic["warning_streak"] == 0


def test_v109_observes_but_does_not_fallback_on_missing_third_land(monkeypatch) -> None:
    v109.reset_runtime_state()
    monkeypatch.setattr(v109.public_v43, "agent", lambda obs, _cfg=None: _action(0, "NORTH"))
    monkeypatch.setattr(v109.safe_rule, "agent", lambda _obs: _action(0, "SOUTH"))
    obs = make_obs(day=11, hour=0)
    obs["farms"][0]["unlocked_quadrants"] = ["NW", "NE"]
    assert v109.agent(obs)["farmer"] == ["NORTH"]
    obs["step"] += 1
    obs["hour"] += 1
    assert v109.agent(obs)["farmer"] == ["NORTH"]
    diagnostic = v109.policy_diagnostics(obs)
    assert not diagnostic["fallback_latched"]
    assert diagnostic["current_warning"] == "third-land-missing-observe-only"


def test_v109_immediately_latches_a_repeated_feed_miss(monkeypatch) -> None:
    v109.reset_runtime_state()
    monkeypatch.setattr(v109.public_v43, "agent", lambda obs, _cfg=None: _action(0, "NORTH"))
    monkeypatch.setattr(v109.safe_rule, "agent", lambda _obs: _action(0, "SOUTH"))
    obs = make_obs(day=5, hour=20)
    obs["farms"][0]["tiles"][0][0] = {
        "kind": "PASTURE",
        "animal": "COW",
        "fed_today": False,
        "consecutive_unfed": 2,
    }
    assert v109.agent(obs)["farmer"] == ["SOUTH"]
    assert v109.policy_diagnostics(obs)["fallback_reason"] == "animal-unfed-critical"


def test_v109_leaves_one_missed_feed_to_the_coherent_route(monkeypatch) -> None:
    v109.reset_runtime_state()
    monkeypatch.setattr(v109.public_v43, "agent", lambda obs, _cfg=None: _action(0, "NORTH"))
    monkeypatch.setattr(v109.safe_rule, "agent", lambda _obs: _action(0, "SOUTH"))
    obs = make_obs(day=8, hour=20)
    obs["farms"][0]["tiles"][0][0] = {
        "kind": "PASTURE",
        "animal": "COW",
        "fed_today": False,
        "consecutive_unfed": 1,
    }
    assert v109.agent(obs)["farmer"] == ["NORTH"]
    assert not v109.policy_diagnostics(obs)["fallback_latched"]


def test_v109_respects_terminal_feed_shutdown(monkeypatch) -> None:
    v109.reset_runtime_state()
    monkeypatch.setattr(v109.public_v43, "agent", lambda obs, _cfg=None: _action(0, "NORTH"))
    monkeypatch.setattr(v109.safe_rule, "agent", lambda _obs: _action(0, "SOUTH"))
    obs = make_obs(day=29, hour=20)
    obs["farms"][0]["tiles"][0][0] = {
        "kind": "PASTURE",
        "animal": "COW",
        "fed_today": False,
        "consecutive_unfed": 2,
    }
    assert v109.agent(obs)["farmer"] == ["NORTH"]
    assert not v109.policy_diagnostics(obs)["fallback_latched"]


def test_v109_rejects_a_malformed_route_action(monkeypatch) -> None:
    v109.reset_runtime_state()
    monkeypatch.setattr(
        v109.public_v43,
        "agent",
        lambda _obs, _cfg=None: {"farmer": ["PASS"], "hands": [], "market": []},
    )
    monkeypatch.setattr(v109.safe_rule, "agent", lambda _obs: _action(2, "SOUTH"))
    obs = make_obs(day=2, hands=2)
    assert v109.agent(obs)["farmer"] == ["SOUTH"]
    assert v109.policy_diagnostics(obs)["fallback_reason"] == "hands-action-count"


def test_v109_submission_is_self_contained(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    agent_dir = root / "agents" / "v109"
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = json.loads((agent_dir / "submission_manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        source = (agent_dir / entry["source"]).resolve()
        shutil.copyfile(source, submission / entry["target"])

    code = """
import os
import sys
from pathlib import Path
submission = Path(sys.argv[1]).resolve()
os.chdir(sys.argv[2])
sys.path.append(str(submission))
namespace = {}
main_path = submission / "main.py"
exec(compile(main_path.read_text(encoding="utf-8"), str(main_path), "exec"), namespace)
assert namespace["MODULE_DIR"] == submission
assert len(namespace["public_v43"]._V43_ROUTES["default"]) == 719
assert namespace["safe_rule"].__name__ == "_kaggriculture_v109_rule_fallback"
assert namespace["safe_rule"].v3.MODEL is None
assert namespace["safe_rule"].v8.POLICY_MODEL is None
assert namespace["safe_rule"].v9.DECISION_MODEL is None
assert namespace["agent"]({}) == {"farmer": ["PASS"], "hands": [], "market": []}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        cwd=elsewhere,
        capture_output=True,
        text=True,
    )
