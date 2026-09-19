"""V122: sparse coherent continuations with conservative execution repair."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v122",
        Path.cwd(),
    )
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if (candidate / "v121_sparse.py").is_file()
            or (candidate.parent / "v121" / "main.py").is_file()
        ),
        Path.cwd(),
    )


def _load(name: str, packaged_name: str, repository: Path) -> Any:
    packaged = _module_dir() / packaged_name
    source = packaged if packaged.is_file() else repository
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[2] if "__file__" in globals() else Path.cwd()
sparse = _load("_v122_sparse", "v121_sparse.py", ROOT / "agents/v121/main.py")
market = _load("_v122_market", "market_overlay.py", ROOT / "agents/v121_market/main.py")

# The public-state sparse policy supplies macro actions.  Only overlays that
# survived paired generalization tests are enabled in the promoted artifact.
sparse._normalize_output = sparse.base._normalize_output
market.base = sparse
market.ENABLE_WEED_REPAIR = True
market.ENABLE_DEAD_SELL_REMOVAL = True
market.ENABLE_TERMINAL_LIQUIDATION = True
market.ENABLE_SELL_RANKING = False


def reset_runtime_state() -> None:
    sparse.reset_runtime_state()
    market.reset_runtime_state()


def policy_diagnostics(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": "v122",
        "sparse": sparse.policy_diagnostics(),
        "market": market.policy_diagnostics(observation),
        "sell_ranking": False,
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

