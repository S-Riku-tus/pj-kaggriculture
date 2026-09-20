"""V125 adaptive arm: base plan plus observation-only economic controls."""

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
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v125_adaptive",
        Path.cwd(),
    )
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if (candidate / "v125_base.py").is_file()
            or (candidate.parent / "v125_base" / "main.py").is_file()
        ),
        Path.cwd(),
    )


def _load_base() -> Any:
    module_dir = _module_dir()
    packaged = module_dir / "v125_base.py"
    repository = module_dir.parent / "v125_base" / "main.py"
    source = packaged if packaged.is_file() else repository
    spec = importlib.util.spec_from_file_location("_kaggriculture_v125_adaptive_base", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import V125 base plan: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base()


def agent(observation: Mapping[str, Any]) -> dict[str, Any]:
    return base.plan_action(observation, adaptive=True)


def latest_diagnostics(seat: int = 0) -> dict[str, Any]:
    return base.latest_diagnostics(seat)

