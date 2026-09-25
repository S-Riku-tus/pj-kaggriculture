"""Build Round13 agents from the immutable, independently verified B1 source."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ROUND13 = Path(__file__).resolve().parents[1]
B1 = ROOT / "experiments/round12_causal_repairs_20260925/agents/P0M0_B1/main.py"
EXPECTED_B1 = "b6553c296c556aff5b5e2d12b75618e505fa4d852afb5338414ac6d6e039cb02"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    observed = sha256(B1)
    if observed != EXPECTED_B1:
        raise RuntimeError(f"immutable B1 mismatch: expected={EXPECTED_B1} observed={observed}")
    base_bytes = B1.read_bytes()
    base = base_bytes.decode("utf-8")
    runtime = (ROUND13 / "templates/runtime.pyfrag").read_text(encoding="utf-8")
    modes = {
        "D0_B1": None,
        "M1_deadline_market": "M1_DEADLINE_MARKET",
        "P_EARLY4": "P_EARLY4",
        "P_ROTATE2": "P_ROTATE2",
        "C_EARLY4_M1": "C_EARLY4_M1",
    }
    manifest: dict[str, dict] = {}
    for name, mode in modes.items():
        target = ROUND13 / "agents" / name / "main.py"
        if mode is None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base_bytes)
        else:
            controls = f"\n_R13_MODE = {mode!r}\n"
            write(target, base + controls + runtime)
        manifest[name] = {
            "path": target.relative_to(ROUND13).as_posix(),
            "sha256": sha256(target),
            "parent_sha256": EXPECTED_B1,
            "entrypoint": "opening_liquidity_agent" if mode is None else "round13_agent",
            "mode": mode or "B1_FROZEN",
        }
    output = ROUND13 / "agents/generated_manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
