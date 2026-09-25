"""Transparent Round11 wiring control; invokes the immutable B1 entry once."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[4]
_B1_PATH = (
    _ROOT
    / "experiments"
    / "Kaggriculture_Round11_Research_Revision_20260924"
    / "inputs"
    / "agents"
    / "B1.py"
)
_SPEC = importlib.util.spec_from_file_location("_round11_immutable_b1", _B1_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(_B1_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_CALLABLES = [value for value in vars(_MODULE).values() if callable(value)]
if not _CALLABLES:
    raise RuntimeError("B1 contains no callable")
_HOST = _CALLABLES[-1]


def agent(observation, configuration):
    return _HOST(observation, configuration)
