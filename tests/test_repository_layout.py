from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agents" / "v1"


def test_v1_has_one_versioned_runtime_source() -> None:
    assert not (ROOT / "main.py").exists()
    assert (AGENT_DIR / "main.py").is_file()
    metadata = json.loads((AGENT_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["name"] == "v1"
    assert metadata["version"] == "1.0.0"
    assert metadata["runtime"]["entrypoint"] == "main.py:agent"


def test_data_layout_is_present() -> None:
    for name in ("analysis", "logs", "replays", "runs", "submissions", "summaries"):
        directory = ROOT / "data" / name
        assert directory.is_dir()
        assert (directory / ".gitkeep").is_file()
