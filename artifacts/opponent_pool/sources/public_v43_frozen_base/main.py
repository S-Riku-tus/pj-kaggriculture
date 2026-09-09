"""Hash-pinned loader for the exact locally archived public V43 agent.

This is opponent-pool infrastructure, not a production agent.  The loader
refuses to execute if the archived source changes, so an experiment can never
silently evaluate a different public V43 implementation.
"""

from __future__ import annotations

import hashlib
import importlib.util
import uuid
from pathlib import Path

EXPECTED_SOURCE_SHA256 = (
    "69f06a802b62aa08f28705dab5728eb924bb6a7c23ffe0164f65b104cc3dadf3"
)
SHARED_ANCESTRY_ID = "public-v43-exact-69f06a802b62"


def _find_exact_source() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "agents" / "v109" / "public_v43_base.py"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("cannot locate agents/v109/public_v43_base.py")


def _load_exact_source():
    path = _find_exact_source()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(
            "public V43 source hash mismatch: "
            f"expected={EXPECTED_SOURCE_SHA256} actual={actual} path={path}"
        )
    name = f"_public_v43_frozen_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import exact public V43 source: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


_EXACT, EXACT_SOURCE_PATH = _load_exact_source()

# Re-export only the pieces needed by the exact and forced-route entrypoints.
_V43_ROUTES = _EXACT._V43_ROUTES
_V43_CONFIG = _EXACT._V43_CONFIG
_v43_build = _EXACT._v43_build
_v43_get = _EXACT._v43_get
_V43_POLICY = _EXACT._V43_POLICY

FIXTURE_METADATA = {
    "fixture_id": "public_v43_frozen_base",
    "gold_grade": "Gold",
    "source_sha256": EXPECTED_SOURCE_SHA256,
    "shared_ancestry_id": SHARED_ANCESTRY_ID,
    "route_mode": "public_shop_router",
    "production_agent_modified": False,
}
FIXTURE_TELEMETRY = {"fallback_count": 0}


def reset_runtime_state() -> None:
    """Rebuild the exact router so repeated local games cannot share state."""
    global _V43_POLICY
    _V43_POLICY = _v43_build(_V43_ROUTES, _V43_CONFIG)
    FIXTURE_TELEMETRY["fallback_count"] = 0


def agent(obs, configuration=None):
    try:
        return _V43_POLICY(obs, configuration)
    except Exception:
        FIXTURE_TELEMETRY["fallback_count"] += 1
        seat = 1 if int(_v43_get(obs, "player", 0) or 0) == 1 else 0
        farms = list(_v43_get(obs, "farms", []) or [])
        farm = farms[seat] if seat < len(farms) else {}
        return {
            "farmer": ["PASS"],
            "hands": [["PASS"] for _ in (_v43_get(farm, "hands", []) or [])],
            "market": [],
        }


def _kaggle_submission_entrypoint(obs, configuration=None):
    return agent(obs, configuration)
