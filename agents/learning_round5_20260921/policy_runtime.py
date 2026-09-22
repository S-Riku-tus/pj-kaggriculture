"""Shared BC base, Round5 executor, and interchangeable selector modes."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (Path("/kaggle_simulations/agent"), *(Path(value) for value in reversed(sys.path) if value), Path.cwd())
    return next((value.resolve() for value in candidates if (value / "policy_runtime.py").is_file()), Path.cwd())


MODULE_DIR = _module_dir()
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

try:
    from .action_codec import normalize_action
    from .contracts import harvestability
    from .executor import ExecutionCoordinator
    from .selector import SkillSelector
except ImportError:
    from action_codec import normalize_action  # type: ignore
    from contracts import harvestability  # type: ignore
    from executor import ExecutionCoordinator  # type: ignore
    from selector import SkillSelector  # type: ignore


def _load_base() -> Any:
    packaged = MODULE_DIR / "bc_agent.py"
    if not packaged.is_file():
        # Repository execution must not rely on the top-level package name
        # ``agents``: kaggle-environments also imports modules with that name.
        packaged = MODULE_DIR.parent / "learning_next_20260921" / "bc_agent.py"
    if packaged.is_file():
        spec = importlib.util.spec_from_file_location("_round5_bc", packaged)
        if spec is None or spec.loader is None:
            raise ImportError(packaged)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    raise ImportError(f"BC base source was not found: {packaged}")


class RuntimePolicy:
    def __init__(self, mode: str) -> None:
        if mode not in {"none", "rule", "learned"}:
            raise ValueError(mode)
        self.mode = mode
        self.base = _load_base()
        self.selector = SkillSelector(MODULE_DIR / "strategy_model.json") if mode == "learned" else None
        self.coordinator = ExecutionCoordinator(f"round5-{mode}")
        self.reset_runtime_state()

    def reset_runtime_state(self) -> None:
        self.coordinator.reset()
        if self.selector is not None:
            self.selector.inference_calls = 0
        if hasattr(self.base, "reset_runtime_state"):
            self.base.reset_runtime_state()
        self.stats = {
            "model_loads": 3 if self.selector is not None else 2,
            "strategy_inference_calls": 0,
            "base_inference_calls": 0,
            "actual_action_differences": 0,
            "silent_fallbacks": 0,
            "explicit_commits": 0,
        }

    def _rule_scores(self, observation: Mapping[str, Any]) -> dict[str, float]:
        seat = int(observation.get("player", 0))
        farm = observation["farms"][seat]
        animal = any(isinstance(tile, Mapping) and tile.get("animal") for row in farm.get("tiles") or [] for tile in row)
        harvest = any(harvestability(observation, actor).applicable for actor in range(1 + len(farm.get("hands") or [])))
        shed = observation.get("private", {}).get("shed", {})
        return {
            "ANIMAL_LIFECYCLE_REALIZATION": float(animal),
            "HARVEST_AND_LAND_CONVERSION": float(harvest),
            "SELL_AND_REINVEST": float(any(int(value or 0) > 0 for value in shed.values())),
        }

    def _scores(self, observation: Mapping[str, Any]) -> dict[str, float]:
        if self.mode == "learned":
            assert self.selector is not None
            self.stats["strategy_inference_calls"] += 1
            return self.selector.scores(observation)
        if self.mode == "rule":
            return self._rule_scores(observation)
        return {}

    def _commit_actual(self, observation: Mapping[str, Any], action: Mapping[str, Any]) -> None:
        seat = int(observation.get("player", 0))
        hand_count = len(observation["farms"][seat].get("hands", []))
        shaped = normalize_action(action, hand_count)
        units = [shaped["farmer"], *shaped["hands"]]
        if hasattr(self.base, "_previous_actor") and hasattr(self.base, "action_token"):
            self.base._previous_actor[seat] = [self.base.action_token(value) for value in units]
        if hasattr(self.base, "_probes") and hasattr(self.base, "make_actor_probe"):
            self.base._probes[seat] = [
                self.base.make_actor_probe(observation, index, value)
                for index, value in enumerate(units)
                if value and value[0] != "PASS"
            ]
        if hasattr(self.base, "_previous_market"):
            self.base._previous_market[seat] = shaped["market"]
        self.stats["explicit_commits"] += 1

    def agent(self, observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
        step = int(observation.get("step", 24 * int(observation.get("day", 0)) + int(observation.get("hour", 0))))
        if step == 0:
            self.reset_runtime_state()
        before_calls = int(getattr(self.base, "_stats", {}).get("inference_calls", 0))
        proposal = self.base.agent(observation, configuration)
        emitted = self.coordinator.repair(observation, proposal, self._scores(observation))
        self._commit_actual(observation, emitted)
        after_calls = int(getattr(self.base, "_stats", {}).get("inference_calls", before_calls))
        self.stats["base_inference_calls"] += max(0, after_calls - before_calls)
        self.stats["actual_action_differences"] += int(normalize_action(proposal) != normalize_action(emitted))
        return emitted

    def diagnostics(self) -> dict[str, Any]:
        base_diagnostics = self.base.policy_diagnostics() if hasattr(self.base, "policy_diagnostics") else {}
        return {
            "arm": f"round5_{self.mode}",
            **self.stats,
            "selector_runtime_calls": self.selector.inference_calls if self.selector is not None else 0,
            "base": base_diagnostics,
            "executor": self.coordinator.diagnostics(),
            "animal_plans": self.coordinator.animal_plans(),
        }


__all__ = ["RuntimePolicy"]
