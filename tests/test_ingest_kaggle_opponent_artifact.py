from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.ingest_kaggle_opponent_artifact import ingest

AGENT_SOURCE = """def agent(obs):
    return {\"farmer\": [\"PASS\"], \"hands\": [], \"market\": []}
"""


def test_ingest_safe_zip_emits_probe_manifest(tmp_path: Path) -> None:
    source = tmp_path / "download.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("main.py", AGENT_SOURCE)
        archive.writestr("README.txt", "public output")

    result = ingest(
        artifact=source,
        candidate_id="public_test_agent",
        source_url="https://www.kaggle.com/code/example/agent/output",
        script_version_id="123",
        output_root=tmp_path / "ingested",
        exact_public_output=True,
    )

    assert result["status"] == "READY_FOR_COMMON_PROBE"
    manifest = json.loads(Path(result["acquisition_manifest"]).read_text(encoding="utf-8"))
    candidate = json.loads(Path(result["candidate_manifest"]).read_text(encoding="utf-8"))
    assert manifest["evidence_status"] == "ACQUISITION_LEAD_NOT_GOLD"
    assert manifest["selected_entrypoint"]["relative_path"] == "main.py"
    assert candidate["candidates"][0]["exact_submitted_or_public_artifact"] is True
    assert "--seed 29114001 --seed 29114002" in result["common_probe_command"]


def test_ingest_rejects_archive_traversal(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../main.py", AGENT_SOURCE)

    with pytest.raises(ValueError, match="unsafe archive member path"):
        ingest(
            artifact=source,
            candidate_id="unsafe_agent",
            source_url="https://example.invalid/output",
            script_version_id=None,
            output_root=tmp_path / "ingested",
        )


def test_ingest_recovers_notebook_writefile(tmp_path: Path) -> None:
    notebook = tmp_path / "agent.ipynb"
    notebook.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "source": ["%%writefile /kaggle/working/main.py\n", AGENT_SOURCE],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = ingest(
        artifact=notebook,
        candidate_id="notebook_agent",
        source_url="https://www.kaggle.com/code/example/notebook",
        script_version_id="7",
        output_root=tmp_path / "ingested",
    )

    assert result["status"] == "READY_FOR_COMMON_PROBE"
    assert result["selected_entrypoint"].endswith("main.py")


def test_ingest_requires_explicit_choice_for_multiple_main_files(tmp_path: Path) -> None:
    source = tmp_path / "ambiguous.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("a/main.py", AGENT_SOURCE)
        archive.writestr("b/main.py", AGENT_SOURCE)

    result = ingest(
        artifact=source,
        candidate_id="ambiguous_agent",
        source_url="https://example.invalid/output",
        script_version_id=None,
        output_root=tmp_path / "ingested",
    )

    assert result["status"] == "NEEDS_ENTRYPOINT_SELECTION"
    assert result["candidate_manifest"] is None
