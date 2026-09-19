from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("v121_combo", ROOT / "agents/v121_combo/main.py")
assert SPEC and SPEC.loader
combo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(combo)


def test_combo_wires_sparse_policy_into_overlay() -> None:
    assert combo.market.base is combo.sparse
    assert combo.sparse._normalize_output is combo.sparse.base._normalize_output


def test_reset_clears_both_runtime_states() -> None:
    combo.market._STATE[0]["probe"] = True
    combo.sparse._STATE["probe"] = True
    combo.reset_runtime_state()
    assert "probe" not in combo.market._STATE[0]
    assert "probe" not in combo.sparse._STATE

