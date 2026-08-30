from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v107 import main as v107
from tests.test_agent_v105 import baseline_targets, make_obs


def _decision(monkeypatch, *, day: int, money: int, source: int, destination: int) -> dict:
    baseline = deepcopy(baseline_targets())
    candidate = deepcopy(baseline[1])
    candidate["WHEAT"] -= 3
    candidate["STRAWBERRY"] += 3

    def safe_gate(*_args):
        return {
            "active": True,
            "changed": True,
            "reason": "active",
            "phase": v107.v14._phase(day),
            "baseline": baseline,
            "candidate_animals": deepcopy(baseline[0]),
            "candidate_crops": candidate,
        }

    monkeypatch.setattr(v107, "_SAFE_GATE_DECISION", safe_gate)
    monkeypatch.setattr(
        v107.base,
        "_demand_profile",
        lambda _obs: {"WHEAT": source, "STRAWBERRY": destination},
    )
    obs = make_obs(day=day)
    obs["farms"][0]["money"] = money
    return v107._gate_decision(obs, obs["farms"][0], obs["farms"][1], obs["private"])


def test_v107_accepts_only_supported_phase_cash_and_demand(monkeypatch) -> None:
    accepted = _decision(monkeypatch, day=10, money=500, source=2, destination=3)
    assert accepted["active"]
    assert accepted["reason"] == "v107-active"
    assert accepted["v107_demand_alignment"] == 1.0

    assert _decision(monkeypatch, day=14, money=5_000, source=2, destination=3)["reason"] == (
        "v107-unsupported-phase"
    )
    assert _decision(monkeypatch, day=10, money=499, source=2, destination=3)["reason"] == (
        "v107-cash-floor"
    )
    assert _decision(monkeypatch, day=10, money=5_000, source=3, destination=3)["reason"] == (
        "v107-demand-misaligned"
    )
    assert _decision(monkeypatch, day=11, money=5_000, source=4, destination=3)["reason"] == (
        "v107-demand-misaligned"
    )


def test_v107_preserves_inactive_base_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        v107,
        "_SAFE_GATE_DECISION",
        lambda *_args: {"active": False, "changed": False, "reason": "ood", "baseline": baseline_targets()},
    )
    obs = make_obs()
    decision = v107._gate_decision(obs, obs["farms"][0], obs["farms"][1], obs["private"])
    assert not decision["active"]
    assert decision["reason"] == "ood"


def test_v107_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    v107.reset_runtime_state()
    assert v107.ENABLE_V107_RUNTIME_GATE
    assert v107.v102._gate_decision is v107._gate_decision
    assert v107.v105._resource_emergency is v107.v106._resource_emergency
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v107.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v107.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v107" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v107" / entry["source"]).resolve()
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
assert namespace["v14"].WINNER_MODEL is not None
assert namespace["v11"].v10.MODEL is not None
assert namespace["v102"]._gate_decision is namespace["_gate_decision"]
assert namespace["v105"]._resource_emergency is namespace["v106"]._resource_emergency
assert set(namespace["agent"]({})) == {"farmer", "hands", "market"}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        cwd=elsewhere,
        capture_output=True,
        text=True,
    )
