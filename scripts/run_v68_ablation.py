"""Run V68 with the paired V58/V63 diagnostic harness."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v68 import main as v68  # noqa: E402
from scripts import run_v58_ablation as runner  # noqa: E402

runner.v58 = v68.v58
runner.runner.v54 = v68.v58
runner.runner.common.v14 = v68.v14


if __name__ == "__main__":
    runner.main()
