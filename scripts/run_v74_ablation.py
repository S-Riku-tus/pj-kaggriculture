"""Run V74 with the paired role diagnostic harness."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v74 import main as v74  # noqa: E402
from scripts import run_v58_ablation as runner  # noqa: E402

runner.v58 = v74.v58
runner.runner.v54 = v74.v58
runner.runner.common.v14 = v74.v14


if __name__ == "__main__":
    runner.main()
