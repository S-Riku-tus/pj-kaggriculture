#!/usr/bin/env python3
"""Preregistered Control/Service/Fertilizer/Joint paired evaluation."""

from __future__ import annotations

from pathlib import Path

import evaluate_v125_candidates as base

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    base.OUT = ROOT / "experiments/research_20260920_v126/four_arm_development"
    base.DEFAULT_SEEDS = (2026092201, 2026092202)
    base.ARMS = {
        "control": ROOT / "agents/v126_exec/main.py",
        "service": ROOT / "agents/v126_service/main.py",
        "fertilizer": ROOT / "agents/v126_fertilizer/main.py",
        "joint": ROOT / "agents/v126_joint/main.py",
    }
    base.CONTROL_ARM = "control"
    base.CONTRIBUTION_CHAIN = ["control", "service", "fertilizer", "joint"]
    base.main()
