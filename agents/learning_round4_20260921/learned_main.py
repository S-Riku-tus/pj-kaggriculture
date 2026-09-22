"""Round4 independent learned policy with a verified common executor."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(value) for value in reversed(sys.path) if value),
        Path.cwd(),
    )
    return next((value.resolve() for value in candidates if (value / "strategy_model.json").is_file()), Path.cwd())


MODULE_DIR = _module_dir()
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

try:
    from .action_codec import normalize_action
    from .executor import ExecutionCoordinator
    from .selector import SkillSelector
except ImportError:
    from action_codec import normalize_action  # type: ignore
    from executor import ExecutionCoordinator  # type: ignore
    from selector import SkillSelector  # type: ignore


def _load_independent_bc() -> Any:
    packaged = MODULE_DIR / "bc_agent.py"
    if packaged.is_file():
        spec = importlib.util.spec_from_file_location("_round4_independent_bc", packaged)
        if spec is None or spec.loader is None:
            raise ImportError(packaged)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    from agents.learning_next_20260921 import bc_agent

    return bc_agent


base = _load_independent_bc()
selector = SkillSelector(MODULE_DIR / "strategy_model.json")
coordinator = ExecutionCoordinator("learned-single-teacher")
_stats: dict[str, int] = {}


def reset_runtime_state() -> None:
    global _stats
    coordinator.reset()
    selector.inference_calls = 0
    if hasattr(base, "reset_runtime_state"):
        base.reset_runtime_state()
    _stats = {
        "model_loads": 3,  # two BC heads plus the Round4 strategy selector
        "strategy_inference_calls": 0,
        "base_inference_calls": 0,
        "actual_action_differences": 0,
        "silent_fallbacks": 0,
        "explicit_commits": 0,
    }


def _commit_actual(observation: Mapping[str, Any], action: Mapping[str, Any]) -> None:
    """Commit the emitted action to the BC history after executor repair."""
    seat = int(observation.get("player", 0))
    hand_count = len(observation["farms"][seat].get("hands", []))
    shaped = normalize_action(action, hand_count)
    units = [shaped["farmer"], *shaped["hands"]]
    if hasattr(base, "_previous_actor") and hasattr(base, "action_token"):
        base._previous_actor[seat] = [base.action_token(value) for value in units]
    if hasattr(base, "_probes") and hasattr(base, "make_actor_probe"):
        base._probes[seat] = [
            base.make_actor_probe(observation, index, value)
            for index, value in enumerate(units)
            if value and value[0] != "PASS"
        ]
    if hasattr(base, "_previous_market"):
        base._previous_market[seat] = shaped["market"]
    _stats["explicit_commits"] += 1


def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    if int(observation.get("step", 24 * int(observation.get("day", 0)) + int(observation.get("hour", 0)))) == 0:
        reset_runtime_state()
    before_calls = int(getattr(base, "_stats", {}).get("inference_calls", 0))
    proposal = base.agent(observation, configuration)
    scores = selector.scores(observation)
    emitted = coordinator.repair(observation, proposal, scores)
    _commit_actual(observation, emitted)
    after_calls = int(getattr(base, "_stats", {}).get("inference_calls", before_calls))
    _stats["base_inference_calls"] += max(0, after_calls - before_calls)
    _stats["strategy_inference_calls"] += 1
    _stats["actual_action_differences"] += int(normalize_action(proposal) != normalize_action(emitted))
    return emitted


def policy_diagnostics(_observation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    base_diagnostics = base.policy_diagnostics() if hasattr(base, "policy_diagnostics") else {}
    return {
        "arm": "round4_learned",
        **_stats,
        "selector_runtime_calls": selector.inference_calls,
        "base": base_diagnostics,
        "executor": coordinator.diagnostics(),
    }


def policy_trace() -> list[dict[str, Any]]:
    return coordinator.policy_trace()


reset_runtime_state()
