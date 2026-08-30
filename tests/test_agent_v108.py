from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v108 import main as v108
from tests.test_agent_v105 import baseline_targets, make_obs


def _active_decision(money: float) -> dict:
    baseline = deepcopy(baseline_targets())
    return {
        "active": True,
        "changed": True,
        "reason": "v107-active",
        "baseline": baseline,
        "candidate_animals": deepcopy(baseline[0]),
        "candidate_crops": deepcopy(baseline[1]),
        "v107_current_money": money,
    }


def test_v108_uses_exclusive_round_liquidity_ceiling(monkeypatch) -> None:
    obs = make_obs()
    args = (obs, obs["farms"][0], obs["farms"][1], obs["private"])
    monkeypatch.setattr(v108, "_SAFE_V107_GATE_DECISION", lambda *_args: _active_decision(4_999))
    assert v108._gate_decision(*args)["reason"] == "v108-active"
    monkeypatch.setattr(v108, "_SAFE_V107_GATE_DECISION", lambda *_args: _active_decision(5_000))
    rejected = v108._gate_decision(*args)
    assert not rejected["active"]
    assert rejected["reason"] == "v108-high-cash-fallback"


def test_v108_preserves_v107_rejection(monkeypatch) -> None:
    monkeypatch.setattr(
        v108,
        "_SAFE_V107_GATE_DECISION",
        lambda *_args: {"active": False, "changed": False, "reason": "v107-demand-misaligned"},
    )
    obs = make_obs()
    decision = v108._gate_decision(obs, obs["farms"][0], obs["farms"][1], obs["private"])
    assert decision["reason"] == "v107-demand-misaligned"


def test_v108_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    v108.reset_runtime_state()
    assert v108.ENABLE_V108_LIQUIDITY_GATE
    assert v108.v102._gate_decision is v108._gate_decision
    assert v108.v105._resource_emergency is v108.v106._resource_emergency
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v108.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v108.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v108" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v108" / entry["source"]).resolve()
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
