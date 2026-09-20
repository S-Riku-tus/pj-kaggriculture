"""V126 Service arm: V125 control plus the isolated maintenance policy."""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _load() -> Any:
    packaged = Path(__file__).resolve().with_name("v126_exec_base.py")
    source = packaged if packaged.is_file() else Path(__file__).resolve().parents[1] / "v126_exec/main.py"
    spec = importlib.util.spec_from_file_location("_v126_service_core", source)
    if spec is None or spec.loader is None:
        raise ImportError(source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ENABLE_SERVICE_POLICY = True
    return module


base = _load()
latest_diagnostics = base.latest_diagnostics
reset_runtime_state = base.reset_runtime_state


def agent(observation: Mapping[str, Any]) -> dict[str, Any]:
    return base.agent(observation)


def _kaggle_submission_entrypoint(
    observation: Mapping[str, Any], configuration: Any = None
) -> dict[str, Any]:
    del configuration
    return agent(observation)
