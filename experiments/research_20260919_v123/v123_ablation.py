"""Local-only V123 ablation entrypoint selected by V123_ABLATION."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("_v123_ablation_base", ROOT / "agents/v123/main.py")
if SPEC is None or SPEC.loader is None:
    raise ImportError("cannot load V123")
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)

variant = os.environ.get("V123_ABLATION", "full")
if variant == "clone_only":
    policy.ENABLE_COHERENCE = False
elif variant == "coherence_only":
    policy.ENABLE_CLONE_PREEMPTION = False
elif variant == "v122_equivalent":
    policy.ENABLE_COHERENCE = False
    policy.ENABLE_CLONE_PREEMPTION = False
elif variant != "full":
    raise ValueError(f"unknown V123_ABLATION={variant!r}")

agent = policy.agent
reset_runtime_state = policy.reset_runtime_state
policy_diagnostics = policy.policy_diagnostics
