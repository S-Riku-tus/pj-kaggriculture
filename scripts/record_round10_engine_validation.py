"""Re-run and record the pinned C++ simulator's bundled validation suites."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CPP_ROOT = ROOT / "experiments/round10_public_learning_20260924/engines/kaggriculture-cppsim"
MINGW_BIN = Path(r"C:\msys64\ucrt64\bin")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], cwd: Path, environment: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "passed": completed.returncode == 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(CPP_ROOT)
    environment["PATH"] = f"{MINGW_BIN}{os.pathsep}{environment.get('PATH', '')}"
    traces = sorted((CPP_ROOT / "traces").glob("*.txt"))
    def test_command(relative: str) -> list[str]:
        code = (
            "import os,runpy,sys;"
            f"os.add_dll_directory(r'{MINGW_BIN}');"
            f"sys.path.insert(0,r'{CPP_ROOT / 'tests'}');"
            f"runpy.run_path(r'{CPP_ROOT / relative}',run_name='__main__')"
        )
        return [sys.executable, "-c", code]

    commands = [
        run([str(CPP_ROOT / "validate.exe"), *[str(path) for path in traces]], CPP_ROOT, environment),
        run(test_command("tests/test_golden.py"), CPP_ROOT, environment),
        run(test_command("tests/test_l1.py"), CPP_ROOT, environment),
    ]
    commit = subprocess.run(
        ["git", "-c", f"safe.directory={CPP_ROOT}", "rev-parse", "HEAD"],
        cwd=CPP_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "-c", f"safe.directory={CPP_ROOT}", "diff", "--", "setup.py"],
        cwd=CPP_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    result = {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "engine_commit": commit,
        "expected_commit": "f0084b916343c37bbcbdc7de9d833dc96caff78f",
        "engine_version": "1.32.7",
        "extension_sha256": sha256_file(next(CPP_ROOT.glob("kagsim*.pyd"))),
        "local_setup_patch": diff,
        "local_setup_patch_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        "trace_count": len(traces),
        "all_passed": all(command["passed"] for command in commands),
        "commands": commands,
        "scope": "bundled fixed-action golden traces plus L1 observation lockstep; not proof for untested states",
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("engine_commit", "trace_count", "all_passed")}, indent=2))
    if not result["all_passed"] or commit != result["expected_commit"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
