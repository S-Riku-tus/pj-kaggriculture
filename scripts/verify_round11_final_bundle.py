"""Verify every final-bundle member and the retained B1 submission archive."""

from __future__ import annotations

import hashlib
import io
import json
import math
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "experiments/round11_execution_20260924"
EXPECTED_B1_ARCHIVE = "3fff94ec235566fff3416627d2691dec2e502bc80646a9016ee15e6fc2067986"
EXPECTED_B1_MAIN = "b6553c296c556aff5b5e2d12b75618e505fa4d852afb5338414ac6d6e039cb02"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    descriptor = json.loads((WORK / "FINAL_BUNDLE.json").read_text(encoding="utf-8"))
    zip_path = ROOT / descriptor["zip_path"]
    raw_zip = zip_path.read_bytes()
    errors: list[str] = []
    if digest(raw_zip) != descriptor["zip_sha256"]:
        errors.append("zip hash mismatch")
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            errors.append("duplicate ZIP members")
        for name in names:
            value = PurePosixPath(name)
            if value.is_absolute() or ".." in value.parts:
                errors.append(f"unsafe ZIP member: {name}")
        root = PurePosixPath(names[0]).parts[0]
        manifest_name = f"{root}/BUNDLE_MANIFEST.json"
        manifest_raw = archive.read(manifest_name)
        if digest(manifest_raw) != descriptor["bundle_manifest_sha256"]:
            errors.append("manifest hash mismatch")
        manifest = json.loads(manifest_raw)
        for row in manifest["files"]:
            name = f"{root}/{row['path']}"
            try:
                payload = archive.read(name)
            except KeyError:
                errors.append(f"missing member: {name}")
                continue
            if len(payload) != int(row["bytes"]):
                errors.append(f"size mismatch: {name}")
            if digest(payload) != row["sha256"]:
                errors.append(f"hash mismatch: {name}")
        required = {
            "REPORT_JA.md", "FINAL_STATUS.json", "SOURCE_REGISTRY.json", "ARM_REGISTRY.json",
            "EFFECTIVE_DIFFS.md", "EXPERIMENT_COVERAGE.json", "MODEL_USAGE.json", "REPRODUCE.md",
        }
        listed = {row["path"] for row in manifest["files"]}
        missing_required = sorted(required - listed)
        if missing_required:
            errors.append(f"missing required documents: {missing_required}")
        if any(path.startswith("candidate_archive/") for path in listed):
            errors.append("unexpected new candidate archive")

        baseline_name = f"{root}/retained_baseline/round10_20260924_b1_herd_safe.tar.gz"
        baseline = archive.read(baseline_name)
        if digest(baseline) != EXPECTED_B1_ARCHIVE:
            errors.append("retained B1 archive hash mismatch")
        with tarfile.open(fileobj=io.BytesIO(baseline), mode="r:gz") as tar:
            members = tar.getmembers()
            if [member.name for member in members] != ["main.py"] or not members[0].isfile():
                errors.append("unexpected B1 archive members")
            main_raw = tar.extractfile(members[0]).read()  # type: ignore[union-attr]
        if digest(main_raw) != EXPECTED_B1_MAIN:
            errors.append("B1 main.py hash mismatch")

    from kaggle_environments.agent import get_last_callable

    with tempfile.TemporaryDirectory(prefix="round11_b1_loader_", dir=WORK) as temporary:
        main_path = Path(temporary) / "main.py"
        main_path.write_bytes(main_raw)
        first = get_last_callable(main_raw.decode("utf-8"), path=str(main_path))
        second = get_last_callable(main_raw.decode("utf-8"), path=str(main_path))
        if first.__name__ != "opening_liquidity_agent" or second.__name__ != "opening_liquidity_agent":
            errors.append("official get_last_callable selected wrong entry")
        if first is second or first.__globals__ is second.__globals__:
            errors.append("independent loader instances share function/global identity")

        from kaggle_environments import make

        env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 702609241}, debug=True)
        reference = ROOT / "experiments/Kaggriculture_Round11_Research_Revision_20260924/inputs/agents/B1.py"
        env.run([str(main_path), str(reference)])
        states = len(env.steps)
        statuses = [str(value.status) for value in env.steps[-1]]
        rewards = [float(value.reward or 0) for value in env.steps[-1]]
        # Identical policies need not tie: the official simultaneous market still
        # resolves equal-price unit orders in seat order.  Submission compatibility
        # requires a complete finite game, not reward equality.
        if states != 720 or statuses != ["DONE", "DONE"] or not all(map(math.isfinite, rewards)):
            errors.append(f"official full-game archive probe failed: {states}, {statuses}, {rewards}")

    result = {
        "schema": "kaggriculture-round11-final-bundle-verification-v1",
        "zip_path": descriptor["zip_path"],
        "zip_sha256": descriptor["zip_sha256"],
        "manifest_files": manifest["files_excluding_this_manifest"],
        "all_manifest_members_verified": not errors,
        "retained_b1_archive_sha256": digest(baseline),
        "retained_b1_main_sha256": digest(main_raw),
        "official_loader_entry": first.__name__,
        "independent_loader_namespaces": first.__globals__ is not second.__globals__,
        "official_full_game": {"states": states, "decisions": states - 1, "statuses": statuses, "rewards": rewards},
        "errors": errors,
        "passed": not errors,
    }
    output = WORK / "FINAL_BUNDLE_VERIFICATION.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
