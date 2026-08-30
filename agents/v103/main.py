"""Kaggriculture V103: bounded multi-turn strategic goal commitment.

V102's strict episode-held-out recovery gate admits a goal.  V103 then keeps
recomputing V14's bounded crop projection for at most 12 turns, only while the
state remains inside V14's confidence/uncertainty safe envelope and the same
supported phase.  Actions are never pinned; V11's deterministic executor
replans feasibility, survival, movement, assignment, and market orders every
turn.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

if "__file__" in globals():
    MODULE_DIR = Path(__file__).resolve().parent
else:
    _runtime_candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v103",
        Path.cwd(),
    )
    MODULE_DIR = next(
        (
            candidate.resolve()
            for candidate in _runtime_candidates
            if (
                (candidate / "v102_base.py").is_file()
                and (candidate / "v14_base.py").is_file()
                and (candidate / "winner_goal_model.json").is_file()
            )
            or ((candidate / "main.py").is_file() and (candidate.parent / "v102" / "main.py").is_file())
        ),
        Path.cwd(),
    )


def _load_v102_module():
    packaged = MODULE_DIR / "v102_base.py"
    source = packaged if packaged.is_file() else MODULE_DIR.parent / "v102" / "main.py"
    spec = importlib.util.spec_from_file_location("_kaggriculture_v103_entry_gate", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load V102 entry gate: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v102 = _load_v102_module()
v14 = v102.v14
v11 = v102.v11
v10 = v102.v10
v9 = v102.v9
v8 = v102.v8
v7 = v102.v7
v6 = v102.v6
v5 = v102.v5
v4 = v102.v4
v3 = v102.v3
base = v102.base

# The frozen replay-fork evaluation found no emitted-action effect.  Keep the
# experiment available for reproduction, but fail closed to the proven V11
# core unless a caller explicitly enables it.
ENABLE_RECOVERY_COMMITMENT = False
COMMITMENT_TURNS = 12

_SAFE_STRATEGY_TARGETS = v102._SAFE_STRATEGY_TARGETS
_COMMIT_UNTIL_STEP = -1
_COMMIT_PHASE = ""
_COMMIT_USED_DAY = -1
_COMMIT_LAST_STEP = -1
_COMMIT_ACTIVATIONS = 0
_COMMIT_CONTINUATION_STEPS = 0


def _reset_commitment() -> None:
    global _COMMIT_UNTIL_STEP, _COMMIT_PHASE, _COMMIT_USED_DAY
    _COMMIT_UNTIL_STEP = -1
    _COMMIT_PHASE = ""
    _COMMIT_USED_DAY = -1


def _selected_tuple(
    baseline: tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int],
    animals: dict[str, int],
    crops: dict[str, int],
    farm: Any,
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    pastures = max(v8._pasture_count(farm), animals["COW"] + animals["SHEEP"])
    return dict(animals), dict(crops), baseline[2], baseline[3], baseline[4], pastures


def _continuation(
    obs: Any,
    farm: Any,
    opponent_farm: Any,
    private: Any,
    baseline: tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int],
) -> tuple[dict[str, int], dict[str, int]] | None:
    prediction = v14._winner_prediction(obs, farm, opponent_farm)
    if not prediction.get("active"):
        return None
    reference = max(0.05, float(v14.WINNER_MODEL["uncertainty_p90"]["h72"]))
    if float(prediction["uncertainty"]) > reference:
        return None
    return v14._project_targets(obs, farm, private, baseline[0], baseline[1], prediction)


def _strategy_targets(
    obs: Any, farm: Any, opponent_farm: Any, private: Any
) -> tuple[dict[str, int], dict[str, int], int, int, dict[str, float], int]:
    global _COMMIT_ACTIVATIONS, _COMMIT_CONTINUATION_STEPS
    global _COMMIT_LAST_STEP, _COMMIT_PHASE, _COMMIT_UNTIL_STEP, _COMMIT_USED_DAY

    baseline = _SAFE_STRATEGY_TARGETS(obs, farm, opponent_farm, private)
    step = base._as_int(
        base._get(
            obs,
            "step",
            base._as_int(base._get(obs, "day", 0)) * 24
            + base._as_int(base._get(obs, "hour", 0)),
        )
    )
    day = base._as_int(base._get(obs, "day", 0))
    phase = v14._phase(day)
    if step <= _COMMIT_LAST_STEP:
        _reset_commitment()
    _COMMIT_LAST_STEP = step
    if not ENABLE_RECOVERY_COMMITMENT:
        _reset_commitment()
        return baseline

    trigger = v102._gate_decision(obs, farm, opponent_farm, private)
    if step > _COMMIT_UNTIL_STEP and trigger.get("active") and day != _COMMIT_USED_DAY:
        _COMMIT_UNTIL_STEP = step + COMMITMENT_TURNS - 1
        _COMMIT_PHASE = phase
        _COMMIT_USED_DAY = day
        _COMMIT_ACTIVATIONS += 1

    if not (step <= _COMMIT_UNTIL_STEP and phase == _COMMIT_PHASE):
        return baseline
    if trigger.get("active"):
        selected = (dict(trigger["candidate_animals"]), dict(trigger["candidate_crops"]))
    else:
        selected = _continuation(obs, farm, opponent_farm, private, baseline)
        if selected is None:
            _COMMIT_UNTIL_STEP = -1
            _COMMIT_PHASE = ""
            return baseline
        _COMMIT_CONTINUATION_STEPS += 1

    return _selected_tuple(baseline, selected[0], selected[1], farm)


v14._strategy_targets = _strategy_targets


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v11.policy_diagnostics(obs))
    safe = base._safe_observation(obs)
    if safe is None:
        return result
    farm, opponent_farm, private = safe
    trigger = v102._gate_decision(obs, farm, opponent_farm, private)
    trigger.pop("baseline", None)
    result["v103_recovery_commitment"] = {
        "entry": trigger,
        "commitment_turns": COMMITMENT_TURNS,
        "state": {
            "until_step": _COMMIT_UNTIL_STEP,
            "phase": _COMMIT_PHASE,
            "used_day": _COMMIT_USED_DAY,
        },
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v14.agent(obs)
