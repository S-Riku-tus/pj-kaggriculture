"""Closed-loop Herd-safe variants differing only in engine step-0 orders."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

BASE_PATH = (
    Path(__file__).resolve().parents[1]
    / "public_agents"
    / "herd_safe"
    / "main.py"
)


def _load_base() -> Callable[..., Any]:
    namespace: dict[str, Any] = {"__file__": str(BASE_PATH), "__name__": "_round10_opening_base"}
    exec(compile(BASE_PATH.read_text(encoding="utf-8"), str(BASE_PATH), "exec"), namespace)
    return [value for value in namespace.values() if callable(value)][-1]


def make_agent(opening: Sequence[Sequence[Any]]) -> Callable[..., dict[str, Any]]:
    base = _load_base()

    def agent(observation: dict[str, Any], configuration: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = base(observation)
        result = {
            "farmer": list(raw.get("farmer") or ["PASS"]),
            "hands": [list(value) for value in (raw.get("hands") or [])],
            "market": [list(value) for value in (raw.get("market") or [])],
        }
        if int(observation.get("step", 0) or 0) == 0:
            result["market"] = [list(value) for value in opening]
        return result

    return agent
