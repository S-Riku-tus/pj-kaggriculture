"""Sparse coherent continuation router plus conservative market overlays."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load(name: str, packaged_name: str, repository: Path) -> Any:
    module_dir = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    packaged = module_dir / packaged_name
    source = packaged if packaged.is_file() else repository
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[2] if "__file__" in globals() else Path.cwd()
sparse = _load("_v121_combo_sparse", "v121_sparse.py", ROOT / "agents/v121/main.py")
market = _load("_v121_combo_market", "market_overlay.py", ROOT / "agents/v121_market/main.py")

# The overlay is deliberately policy-agnostic.  Give it the sparse policy and
# its V120 normalization helper instead of V120 itself.
sparse._normalize_output = sparse.base._normalize_output
market.base = sparse


def reset_runtime_state() -> None:
    sparse.reset_runtime_state()
    market.reset_runtime_state()


def policy_diagnostics(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "sparse": sparse.policy_diagnostics(),
        "market": market.policy_diagnostics(observation),
    }


def agent(observation: dict[str, Any], configuration: Any = None) -> dict[str, Any]:
    return market.agent(observation, configuration)


def _kaggle_submission_entrypoint(observation: dict[str, Any], configuration: Any = None) -> dict[str, Any]:
    return agent(observation, configuration)


if __name__ == "__main__":
    import json

    for line in sys.stdin:
        if line.strip():
            request = json.loads(line)
            print(json.dumps(agent(request.get("observation", request), request.get("configuration"))), flush=True)

