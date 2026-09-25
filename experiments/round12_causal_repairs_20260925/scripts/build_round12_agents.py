"""Build isolated Round12 arms from the immutable B1 and checked templates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROUND12 = Path(__file__).resolve().parents[1]
B1 = ROOT / "experiments/Kaggriculture_Round11_Research_Revision_20260924/inputs/agents/B1.py"
EXPECTED_B1 = "b6553c296c556aff5b5e2d12b75618e505fa4d852afb5338414ac6d6e039cb02"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    if digest(B1) != EXPECTED_B1:
        raise RuntimeError(f"immutable B1 mismatch: {digest(B1)}")
    base_bytes = B1.read_bytes()
    base = base_bytes.decode("utf-8")
    patch = (ROUND12 / "templates/runtime_patch.pyfrag").read_text(encoding="utf-8")
    route = (ROUND12 / "templates/strawberry_route.py").read_text(encoding="utf-8")
    modes = {
        "P0M0_B1": None,
        "P0_ledger_only": (True, False, False),
        "P0_censor_only": (False, True, False),
        "P0_ledger_censor": (True, True, False),
        "P0M1_market": (True, True, True),
    }
    manifest = {}
    for name, flags in modes.items():
        target = ROUND12 / "agents" / name / "main.py"
        if flags is None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base_bytes)
        else:
            ledger, censor, market = flags
            controls = (
                f"\n_R12_ENABLE_LEDGER = {ledger!r}\n"
                f"_R12_ENABLE_CENSOR = {censor!r}\n"
                f"_R12_ENABLE_MARKET = {market!r}\n"
            )
            text = base + controls + patch
            write(target, text)
        manifest[name] = {"path": target.relative_to(ROUND12).as_posix(), "sha256": digest(target), "base_sha256": EXPECTED_B1}
    for mode in ("M0", "M1"):
        name = f"P1{mode}_strawberry_route"
        target = ROUND12 / "agents" / name / "main.py"
        write(target, route.replace("__MARKET_MODE__", mode))
        manifest[name] = {"path": target.relative_to(ROUND12).as_posix(), "sha256": digest(target), "base_sha256": None}
    output = ROUND12 / "agents/generated_manifest.json"
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
