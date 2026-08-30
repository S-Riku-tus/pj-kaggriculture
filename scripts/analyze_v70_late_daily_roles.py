"""Run the V56 role analysis over the later game phases (days 13-27)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import analyze_v56_daily_roles as analyzer  # noqa: E402


def main() -> None:
    analyzer.DAYS = tuple(range(13, 28))
    old_argv = sys.argv
    sys.argv = [
        old_argv[0],
        "--output",
        "data/analysis/v70_late_daily_roles.json",
    ]
    try:
        analyzer.main()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    main()
