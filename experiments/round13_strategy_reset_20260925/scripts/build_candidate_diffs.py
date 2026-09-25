"""Write reproducible B1-to-candidate unified diffs."""

from __future__ import annotations

import difflib
from pathlib import Path


ROUND13 = Path(__file__).resolve().parents[1]
BASE = ROUND13 / "agents/D0_B1/main.py"


def main() -> None:
    before = BASE.read_text(encoding="utf-8").splitlines(keepends=True)
    output = ROUND13 / "analysis/diffs"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("M1_deadline_market", "P_EARLY4", "P_ROTATE2", "C_EARLY4_M1"):
        candidate = ROUND13 / "agents" / name / "main.py"
        after = candidate.read_text(encoding="utf-8").splitlines(keepends=True)
        diff = difflib.unified_diff(
            before,
            after,
            fromfile="D0_B1/main.py",
            tofile=f"{name}/main.py",
            n=3,
        )
        (output / f"{name}.patch").write_text("".join(diff), encoding="utf-8", newline="\n")
    print(output)


if __name__ == "__main__":
    main()
