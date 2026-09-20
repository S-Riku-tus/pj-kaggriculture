#!/usr/bin/env python3
"""Validate the packaged V126 control against its repository source."""

from __future__ import annotations

from pathlib import Path

import validate_v125_exec_package as base

ROOT = Path(__file__).resolve().parents[1]

base.ARCHIVE = ROOT / "artifacts/submissions/v126_control_candidate.tar.gz"
base.SOURCE = ROOT / "agents/v126_exec/main.py"
base.OUTPUT = ROOT / "experiments/research_20260920_v126/package_validation.json"


if __name__ == "__main__":
    base.main()
