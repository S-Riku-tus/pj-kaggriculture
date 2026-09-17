"""Kaggriculture V119: public-state routed portfolio policy.

V119 deliberately preserves the behavior of the strongest cleanly acquired
candidate in the 2026-09-17 evaluation.  The policy selects one of several
complete route tapes at each six-day boundary from current public market,
town, farm, and portfolio state plus its own private inventory.

The route policy is Apache-2.0 at the notebook level.  Its embedded route-data
provenance file was not present in the public notebook export; see NOTICE.md.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

SOURCE_SHA256 = "91772fda544e2d5768afff819e2de75ecb7a12db8acb40a48ee9edcf76aca434"
UPSTREAM_NOTEBOOK = (
    "https://www.kaggle.com/code/thomastschinkel/"
    "kaggriculture-93-8-win-rate-public-state-router"
)


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v119",
        Path.cwd(),
    )
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if (candidate / "psr_base.py").is_file()
            or (
                candidate
                / "experiments"
                / "research_20260914_clean_psr"
                / "candidates"
                / "P1_psr_clean"
                / "main.py"
            ).is_file()
        ),
        Path.cwd(),
    )


def _load_base():
    module_dir = _module_dir()
    packaged = module_dir / "psr_base.py"
    repository = (
        module_dir.parents[1]
        / "experiments"
        / "research_20260914_clean_psr"
        / "candidates"
        / "P1_psr_clean"
        / "main.py"
        if module_dir.name == "v119"
        else module_dir
        / "experiments"
        / "research_20260914_clean_psr"
        / "candidates"
        / "P1_psr_clean"
        / "main.py"
    )
    source = packaged if packaged.is_file() else repository
    if not source.is_file():
        raise ImportError(f"cannot load V119 policy source: {source}")
    spec = importlib.util.spec_from_file_location("_kaggriculture_v119_psr", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import V119 policy source: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base()


def agent(observation: Any, configuration: Any = None) -> dict[str, Any]:
    """Delegate exactly to the frozen public-state router."""
    return base.agent(observation, configuration)


if __name__ == "__main__":
    import json

    for line in sys.stdin:
        if line.strip():
            request = json.loads(line)
            result = agent(request.get("observation", request), request.get("configuration"))
            print(json.dumps(result), flush=True)
