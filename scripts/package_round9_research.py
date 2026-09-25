"""Build verified complete and compact Round9 research ZIP archives."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP_REL = Path("experiments/round9_teacher_reproduction_and_closed_loop_bc_20260923")
EXP = ROOT / EXP_REL
AGENT_REL = Path("agents/round9_teacher_reproduction_and_closed_loop_bc_20260923")
OUT = ROOT / "artifacts/research"
FULL = OUT / "round9_teacher_reproduction_and_closed_loop_bc_20260923_complete_v2.zip"
AUDIT = OUT / "round9_teacher_reproduction_and_closed_loop_bc_20260923_audit_v2.zip"
BUNDLES = EXP / "bundles"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def files_under(relative: Path) -> list[Path]:
    return [path for path in (ROOT / relative).rglob("*") if path.is_file()]


def unique_existing(paths: list[Path]) -> list[Path]:
    result, seen = [], set()
    for path in paths:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        key = str(path).casefold()
        if key not in seen:
            result.append(path)
            seen.add(key)
    return sorted(result, key=lambda value: str(value).casefold())


def entry(path: Path) -> dict:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def write_manifest(name: str, paths: list[Path], not_included: list[str]) -> Path:
    BUNDLES.mkdir(parents=True, exist_ok=True)
    target = BUNDLES / f"{name}_contents.json"
    payload = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "bundle": name,
        "file_count_excluding_this_manifest": len(paths),
        "total_bytes_excluding_this_manifest": sum(path.stat().st_size for path in paths),
        "files": [entry(path) for path in paths],
        "not_included": not_included,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def build_zip(target: Path, paths: list[Path]) -> dict:
    if target.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
        for index, path in enumerate(paths, 1):
            archive.write(path, path.relative_to(ROOT).as_posix())
            if index % 100 == 0:
                print(f"{target.name}: {index}/{len(paths)}")
    expected = {path.relative_to(ROOT).as_posix(): sha256(path) for path in paths}
    with zipfile.ZipFile(target, "r") as archive:
        names = archive.namelist()
        if len(names) != len(expected) or set(names) != set(expected):
            raise AssertionError("ZIP member set mismatch")
        for index, name in enumerate(names, 1):
            digest = hashlib.sha256(archive.read(name)).hexdigest()
            if digest != expected[name]:
                raise AssertionError(f"ZIP hash mismatch: {name}")
            if index % 100 == 0:
                print(f"verify {target.name}: {index}/{len(names)}")
    return {
        "path": target.relative_to(ROOT).as_posix(),
        "bytes": target.stat().st_size,
        "sha256": sha256(target),
        "files": len(paths),
    }


def main() -> None:
    dataset_manifest = json.loads((EXP / "a2_prefix_bc/dataset_v1/dataset_manifest.json").read_text(encoding="utf-8"))
    source_replays = [ROOT / item["path"] for item in dataset_manifest["episodes"]]
    source_replays.append(ROOT / "data/replays/submission_56216119/episode_109118332.json")

    experiment_files = [path for path in files_under(EXP_REL) if BUNDLES not in path.parents]
    scripts = [
        ROOT / "scripts/train_round9_prefix_bc.py",
        ROOT / "scripts/run_round9_contract_controls.py",
        ROOT / "scripts/run_round9_engine_fixtures.py",
        ROOT / "scripts/evaluate_round9_t1_t2_t3.py",
        ROOT / "scripts/audit_round9_economy.py",
        ROOT / "scripts/build_round9_recovery_states.py",
        ROOT / "scripts/validate_round9_archive.py",
        ROOT / "scripts/package_round9_research.py",
        ROOT / "scripts/evaluate_round7_pilot.py",
        ROOT / "scripts/learning_next_evaluate.py",
    ]
    archives = [
        ROOT / "artifacts/submissions/round8_spatial_bc_20260922_seed20260922_pure_v6.tar.gz",
        ROOT / "artifacts/submissions/round9_20260923_a1_prefix_legality_v3.tar.gz",
        ROOT / "artifacts/submissions/round9_20260923_a2_prefix_bc_seed20260924_v3.tar.gz",
        ROOT / "artifacts/submissions/v122.tar.gz",
        ROOT / "artifacts/submissions/v124.tar.gz",
    ]
    fixed_engine = [
        ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py",
        ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.json",
        ROOT / ".venv/Lib/site-packages/kaggle_environments/agent.py",
    ]
    manifests = [
        ROOT / "experiments/learning_next_20260921/source_manifest.json",
        ROOT / "experiments/learning_next_20260921/split_manifest.json",
    ]
    supplied_review = files_under(Path(".tmp/round9_input_20260923"))
    full_files = unique_existing(
        experiment_files
        + files_under(AGENT_REL)
        + scripts
        + archives
        + fixed_engine
        + manifests
        + source_replays
        + supplied_review
    )
    full_manifest = write_manifest(
        "complete_v2",
        full_files,
        [
            "558 locally available but unused teacher episodes are not duplicated; "
            "see AUDIT_BUNDLE_NOT_INCLUDED.md and source_manifest.json"
        ],
    )
    full_files = unique_existing(full_files + [full_manifest])

    top_names = {
        "REPORT_JA.md",
        "RESUME.md",
        "PREREGISTRATION.md",
        "METRIC_CONTRACT.json",
        "METRIC_RESULTS.json",
        "DATA_USAGE_FUNNEL.json",
        "ENVIRONMENT.json",
        "INPUT_MANIFEST.json",
        "COMMANDS.md",
        "IMPLEMENTATION_DIFF.md",
        "AUDIT_BUNDLE_NOT_INCLUDED.md",
        "fixed_engine_fixtures_v1.json",
        "final_archive_loader_validation.json",
    }
    compact = [EXP / name for name in top_names]
    compact += [
        EXP / "contract_controls_v2/summary.json",
        EXP / "trajectory_control_episode_109118332_v1/dataset/manifest.json",
        EXP / "trajectory_t1_t2_t3_v2/summary.json",
        EXP / "trajectory_t1_t2_t3_v2/trajectory_memorizer_seed20260925_t3_replay.json.gz",
        EXP / "trajectory_t1_t2_t3_v2/trajectory_memorizer_seed20260925_t3_runtime_trace.json.gz",
        EXP / "a2_prefix_bc/dataset_v1/dataset_manifest.json",
        EXP / "a2_prefix_bc/dataset_v1/actor_row_provenance.csv.gz",
        EXP / "a2_prefix_bc/dataset_v1/market_row_provenance.csv.gz",
        EXP / "recovery_states_v1/manifest.json",
        EXP / "recovery_states_v1/states.json.gz",
        ROOT / "data/replays/submission_56216119/episode_109118332.json",
        ROOT / "artifacts/submissions/round9_20260923_a2_prefix_bc_seed20260924_v3.tar.gz",
    ]
    for seed in ("seed_20260923", "seed_20260924"):
        compact += files_under(EXP_REL / "a2_prefix_bc/models_v1" / seed / "training_logs")
        compact.append(EXP / "a2_prefix_bc/models_v1" / seed / "training_summary.json")
    compact += files_under(AGENT_REL / "a2")
    compact += scripts
    for panel in (
        "development_panel_a0",
        "development_panel_a1_v2",
        "development_panel_a2_v3",
        "development_panel_a2_v2_expanded64",
    ):
        compact += [EXP / panel / "games.csv", EXP / panel / "summary.json", EXP / panel / "evaluation_manifest.json"]
    compact += [
        EXP / "development_panel_a2_v3/replays/v122/seed_2026102201_seat_0.json.gz",
        EXP / "development_panel_a2_v3/diagnostics/v122_seed_2026102201_seat_0.json.gz",
        EXP / "economy_audit_v1/development_panel_a0/summary.json",
        EXP / "economy_audit_v1/development_panel_a2_v2/summary.json",
        EXP / "economy_audit_v1/development_panel_a2_v2_expanded64/summary.json",
    ]
    audit_files = unique_existing(compact)
    audit_manifest = write_manifest(
        "audit_v2",
        audit_files,
        ["See experiments/round9_teacher_reproduction_and_closed_loop_bc_20260923/AUDIT_BUNDLE_NOT_INCLUDED.md"],
    )
    audit_files = unique_existing(audit_files + [audit_manifest])

    results = {"complete": build_zip(FULL, full_files), "audit": build_zip(AUDIT, audit_files)}
    result_path = BUNDLES / "archives_v2.json"
    result_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
