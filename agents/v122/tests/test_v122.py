from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("v122", ROOT / "agents/v122/main.py")
assert SPEC and SPEC.loader
v122 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v122)


def test_promoted_overlay_flags() -> None:
    assert v122.market.ENABLE_WEED_REPAIR
    assert v122.market.ENABLE_DEAD_SELL_REMOVAL
    assert v122.market.ENABLE_TERMINAL_LIQUIDATION
    assert not v122.market.ENABLE_SELL_RANKING


def test_submission_manifest_is_complete() -> None:
    agent_dir = ROOT / "agents/v122"
    manifest = json.loads((agent_dir / "submission_manifest.json").read_text(encoding="utf-8"))
    targets = {entry["target"] for entry in manifest["files"]}
    assert targets == {
        "main.py",
        "v121_sparse.py",
        "v120_base.py",
        "market_overlay.py",
        "model.json.gz",
        "model_metadata.json",
        "NOTICE.md",
    }
    for entry in manifest["files"]:
        assert (agent_dir / entry["source"]).resolve().is_file()


def test_reset_clears_component_state() -> None:
    v122.market._STATE[0]["probe"] = True
    v122.sparse._STATE["probe"] = True
    v122.reset_runtime_state()
    assert "probe" not in v122.market._STATE[0]
    assert "probe" not in v122.sparse._STATE

