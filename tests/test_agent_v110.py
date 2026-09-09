from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v110 import main as v110
from tests.test_agent_v105 import make_obs


def _action(hands: int = 0, market: list | None = None) -> dict:
    return {
        "farmer": ["PASS"],
        "hands": [["PASS"] for _ in range(hands)],
        "market": list(market or []),
    }


def _state(step: int) -> dict:
    return v110._new_state(step)


def test_v110_clone_front_run_moves_only_a_planned_premium_sale(monkeypatch) -> None:
    obs = make_obs(day=10, hour=0)
    obs["private"]["shed"]["STRAWBERRY"] = 12
    state = _state(obs["step"])
    state["clone_confidence"] = v110.CLONE_MIN_CONFIDENCE
    monkeypatch.setattr(v110, "_route_name", lambda _obs: "default")
    monkeypatch.setattr(
        v110,
        "_planned_sales",
        lambda _route, step: {
            "STRAWBERRY": {"distance": 2, "quantity": 9, "target": step + 2}
        },
    )

    base_action = _action(market=[["HIRE"]])
    result = v110._front_run(obs, base_action, None, state, obs["farms"][1])

    assert result["market"] == [["SELL", "STRAWBERRY", 9], ["HIRE"]]
    assert base_action == _action(market=[["HIRE"]])
    assert state["last_overlay"]["mode"] == "clone-h4"
    assert state["shifted_targets"] == {(obs["step"] + 2, "STRAWBERRY")}


def test_v110_uncertain_market_keeps_the_coherent_route(monkeypatch) -> None:
    obs = make_obs(day=10, hour=0)
    obs["private"]["shed"]["MILK"] = 20
    state = _state(obs["step"])
    monkeypatch.setattr(v110, "_route_name", lambda _obs: "default")
    monkeypatch.setattr(
        v110,
        "_planned_sales",
        lambda _route, step: {"MILK": {"distance": 2, "quantity": 10, "target": step + 2}},
    )

    base_action = _action(market=[["HIRE"]])
    assert v110._front_run(obs, base_action, None, state, obs["farms"][1]) == base_action
    assert state["last_overlay"] is None


def test_v110_phase_only_signal_is_observation_only(monkeypatch) -> None:
    obs = make_obs(day=10, hour=0)
    obs["farms"][0]["money"] = 5_000
    obs["farms"][1]["money"] = 10_000
    obs["private"]["shed"]["STRAWBERRY"] = 20
    for x in range(8):
        obs["farms"][1]["tiles"][0][x] = {
            "kind": "PLANT",
            "crop": "STRAWBERRY",
            "yield_units": 1,
        }
    state = _state(obs["step"])
    # Even a strong phase pattern remains diagnostic-only: live replay
    # playback rejected phase-only front-running on future quote value.
    state["opponent_sales"]["STRAWBERRY"] = [
        (obs["step"] - 11, 1, 14),
        (obs["step"] - 7, 1, 12),
        (obs["step"] - 3, 1, 16),
    ]
    monkeypatch.setattr(v110, "_route_name", lambda _obs: "default")
    monkeypatch.setattr(
        v110,
        "_planned_sales",
        lambda _route, step: {
            "STRAWBERRY": {"distance": 2, "quantity": 10, "target": step + 2}
        },
    )

    result = v110._front_run(obs, _action(), None, state, obs["farms"][1])
    assert result == _action()
    assert state["last_overlay"] is None
    assert v110.ENABLE_PHASE_FRONT_RUN is False


def test_v110_infers_opponent_supply_after_own_sell_and_town_demand() -> None:
    obs = make_obs(day=10, hour=2)
    obs["town"]["unlocked_shops"] = ["SMOOTHIE_SHOP"]
    state = _state(obs["step"])
    previous_step = obs["step"] - 1
    state["previous"] = {
        "step": previous_step,
        "inventory": {**obs["market"]["inventory"], "STRAWBERRY": 10_000},
        "prices": {**obs["market"]["prices"], "STRAWBERRY": 120},
        "shops": ("SMOOTHIE_SHOP",),
        "action": _action(market=[["SELL", "STRAWBERRY", 4]]),
        "projected_shed": {"STRAWBERRY": 4},
        "configuration": None,
        "overlay": None,
    }
    # Previous step is phase 1, so no Town tick.  Delta 13 = own 4 + opponent 9.
    obs["market"]["inventory"]["STRAWBERRY"] = 10_013
    obs["market"]["prices"]["STRAWBERRY"] = 95

    supplies = v110._observe_opponent_sales(obs, None, state)
    assert supplies["STRAWBERRY"] == 9
    assert state["opponent_sales"]["STRAWBERRY"] == [(previous_step, 1, 9)]


def test_v110_does_not_overlay_the_critical_fallback(monkeypatch) -> None:
    v110.reset_runtime_state()
    obs = make_obs(day=7, hour=1)
    base_action = _action()
    monkeypatch.setattr(v110.base, "agent", lambda _obs, _cfg=None: deepcopy(base_action))
    monkeypatch.setattr(
        v110.base,
        "policy_diagnostics",
        lambda _obs: {"fallback_latched": True, "fallback_reason": "test"},
    )

    assert v110.agent(obs) == base_action
    assert v110.policy_diagnostics(obs)["last_overlay"] is None


def test_v110_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    v110.reset_runtime_state()
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v110.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v110.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    agent_dir = root / "agents" / "v110"
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
assert namespace["base"].MODULE_DIR == submission
assert len(namespace["base"].public_v43._V43_ROUTES["default"]) == 719
assert namespace["agent"]({}) == {"farmer": ["PASS"], "hands": [], "market": []}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        cwd=elsewhere,
        capture_output=True,
        text=True,
    )
