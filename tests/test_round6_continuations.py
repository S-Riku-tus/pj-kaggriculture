from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_round6_continuations.py"
SPEC = importlib.util.spec_from_file_location("round6_continuations", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_planned_horizons_include_required_lengths_and_remaining() -> None:
    assert MODULE.planned_horizons(720, 96) == [24, 48, 96, 192, 624]


def test_exact_fields_excludes_action_and_reward() -> None:
    state = {
        "action": {"farmer": ["PASS"]},
        "reward": 1,
        "observation": {
            "farms": [],
            "market": {},
            "town": {},
            "day": 0,
            "hour": 0,
            "private": {},
        },
    }
    assert set(MODULE.exact_fields(state)) == {"farms", "market", "town", "day", "hour", "private"}
