"""Run V67 with the same paired diagnostics used for V58/V63."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v67 import main as v67  # noqa: E402
from scripts import run_v58_ablation as runner  # noqa: E402

runner.v58 = v67.v58
runner.runner.v54 = v67.v58
runner.runner.common.v14 = v67.v14


if __name__ == "__main__":
    runner.main()
