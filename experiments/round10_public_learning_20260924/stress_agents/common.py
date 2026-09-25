"""Opening-funding stress wrappers around the public Ahmed V57 policy.

Only the engine step-0 market list is replaced.  The wrapped policy is called
on every step, including step 0, so its private runtime follows the real
closed-loop episode after the deliberate opening perturbation.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

BASE_PATH = (
    Path(__file__).resolve().parents[1]
    / "public_agents"
    / "ahmed_v57"
    / "main.py"
)


def _load_last_callable(path: Path) -> Callable[..., Any]:
    namespace: dict[str, Any] = {"__file__": str(path), "__name__": "_round10_stress_base"}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    values = [value for value in namespace.values() if callable(value)]
    if not values:
        raise RuntimeError(f"no callable entry point in {path}")
    return values[-1]


def make_agent(opening_orders: Sequence[Sequence[Any]]) -> Callable[..., dict[str, Any]]:
    base = _load_last_callable(BASE_PATH)

    def agent(observation: dict[str, Any], configuration: dict[str, Any] | None = None) -> dict[str, Any]:
        action = base(observation)
        result = {
            "farmer": list(action.get("farmer") or ["PASS"]),
            "hands": [list(value) for value in (action.get("hands") or [])],
            "market": [list(value) for value in (action.get("market") or [])],
        }
        if int(observation.get("step", 0) or 0) == 0:
            result["market"] = copy.deepcopy(list(opening_orders))
        return result

    return agent
