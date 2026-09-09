"""Gold opponent fixture: exact public V43 with the full default route forced."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

FORCED_ROUTE = "default"
SHARED_ANCESTRY_ID = "public-v43-exact-69f06a802b62"


def _load_frozen_base():
    path = Path(__file__).resolve().parent.parent / "public_v43_frozen_base" / "main.py"
    spec = importlib.util.spec_from_file_location(
        f"_public_v43_fixture_base_{FORCED_ROUTE}_{uuid.uuid4().hex}", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import frozen public V43 base: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _load_frozen_base()
_POLICY = _BASE._v43_build(_BASE._V43_ROUTES, _BASE._V43_CONFIG).children[FORCED_ROUTE]

FIXTURE_METADATA = {
    "fixture_id": "public_v43_forced_default",
    "gold_grade": "Gold",
    "forced_route": FORCED_ROUTE,
    "source_sha256": _BASE.EXPECTED_SOURCE_SHA256,
    "shared_ancestry_id": SHARED_ANCESTRY_ID,
    "executor": "public_v43.v23_sparse_planner",
    "outer_exception_policy": "public_v43_safe_pass",
    "production_agent_modified": False,
}
FIXTURE_TELEMETRY = {"fallback_count": 0}


def reset_runtime_state() -> None:
    global _POLICY
    router = _BASE._v43_build(_BASE._V43_ROUTES, _BASE._V43_CONFIG)
    _POLICY = router.children[FORCED_ROUTE]
    FIXTURE_TELEMETRY["fallback_count"] = 0


def agent(obs, configuration=None):
    try:
        return _POLICY(obs, configuration)
    except Exception:
        FIXTURE_TELEMETRY["fallback_count"] += 1
        seat = 1 if int(_BASE._v43_get(obs, "player", 0) or 0) == 1 else 0
        farms = list(_BASE._v43_get(obs, "farms", []) or [])
        farm = farms[seat] if seat < len(farms) else {}
        return {
            "farmer": ["PASS"],
            "hands": [["PASS"] for _ in (_BASE._v43_get(farm, "hands", []) or [])],
            "market": [],
        }


def _kaggle_submission_entrypoint(obs, configuration=None):
    return agent(obs, configuration)
