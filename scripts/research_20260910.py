"""Current executable acquisition and experiments using the existing evaluator."""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "experiments/research_20260910"
POOL = ROOT / "artifacts/opponent_pool/current_20260910"
EVAL = ROOT / "data/evaluation/research_20260910"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def package(contents, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as output:
        with gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                for name, content in sorted(contents.items()):
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    info.mode = 0o644
                    info.mtime = 0
                    archive.addfile(info, io.BytesIO(content))


def prepare():
    from scripts.evaluation.runner import extract_archive

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "source_registry.json"
    if target.exists():
        raise SystemExit("Frozen registry already exists")
    control = OUT / "champion_v111.tar.gz"
    shutil.copyfile(ROOT / "artifacts/submissions/v111.tar.gz", control)
    extract_archive(control, OUT / "runtime/control")
    candidates = [
        ("mooman_e052a", "mooman", "agents/kaito_v56_e052a.py", "agent_entry"),
        ("souvik_v4", "souvik", "my/main.py", "agent"),
        ("ggmljs_v16", "ggmljs", "main.py", "agent"),
        ("qeinstein_moev2", "qeinstein", "dist/sub-009-moev2/main.py", "agent"),
    ]
    rows = []
    for cid, repo, path, entry in candidates:
        base = POOL / repo
        source = base / path
        content = source.read_bytes()
        if entry != "agent":
            adapter = (
                b"from pathlib import Path\nimport importlib.util\n"
                b'_spec = importlib.util.spec_from_file_location("_public_policy", '
                b'Path(__file__).with_name("policy.py"))\n'
                b"_policy = importlib.util.module_from_spec(_spec)\n_spec.loader.exec_module(_policy)\n"
                b"def agent(obs, configuration=None):\n    return _policy.agent_entry(obs, configuration)\n"
            )
            contents = {"main.py": adapter, "policy.py": content}
        else:
            contents = {"main.py": content}
        for notice in ("LICENSE", "LICENSE.md", "LICENSE.txt", "THIRD_PARTY_NOTICES.md", "NOTICE.md"):
            if (base / notice).is_file():
                contents[notice] = (base / notice).read_bytes()
        archive = OUT / "opponents" / f"{cid}.tar.gz"
        package(contents, archive)
        runtime = OUT / "runtime" / cid
        extract_archive(archive, runtime)
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=base).decode().strip()
        remote = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=base).decode().strip()
        rows.append(
            {
                "candidate_id": cid,
                "source_repository": remote,
                "source_revision": revision,
                "source_path": str(source.relative_to(ROOT)),
                "source_sha256": digest(source),
                "archive": str(archive.relative_to(ROOT)),
                "archive_sha256": digest(archive),
                "entrypoint": str((runtime / "main.py").relative_to(ROOT)),
                "original_callable": entry,
                "tier": "executable acquired; completion validation pending",
                "ancestry": repo,
                "source_scope": "full published observation-dependent Agent; no fixed replay opponent",
            }
        )
    save(
        target,
        {
            "created_at": datetime.now(UTC).isoformat(),
            "champion_archive": str(control.relative_to(ROOT)),
            "champion_sha256": digest(control),
            "sources": rows,
            "discovery_seeds": [10091001, 10091002, 10091003, 10091004],
            "development_seeds": [10091011, 10091012, 10091013, 10091014],
            "promotion_seeds": list(range(10091101, 10091113)),
            "fresh_holdout_seeds": list(range(10091901, 10091913)),
            "fresh_status": "UNUSED; not simulated or inspected; unlock only for frozen passing Candidate",
        },
    )
    print(target, flush=True)


def baseline_task(task):
    from scripts.evaluation.replay import lineage_hash
    from scripts.evaluation.runner import _run_game, _write_replay
    from scripts.gold_opponent_pool import replay_diagnostics

    game = _run_game(Path(task["control"]), Path(task["opponent"]), task["seed"], task["seat"], 720, "control")
    replay = game.pop("replay")
    game.update(
        candidate_id=task["candidate_id"],
        opponent_hashes={
            str(h): lineage_hash(replay, 1 - task["seat"], h) for h in (24, 48, 100, 200, 300, 400, 600, 719)
        },
        self_hashes={str(h): lineage_hash(replay, task["seat"], h) for h in (24, 48, 100, 200, 300, 400, 600, 719)},
        diagnostics=replay_diagnostics(replay, task["seat"], 720),
    )
    file = (
        EVAL
        / task.get("phase", "discovery")
        / "replays"
        / f"{task['candidate_id']}_{task['seed']}_{task['seat']}.json.gz"
    )
    game["replay_path"] = _write_replay(file, replay)
    return game


def probe(workers):
    registry = json.loads((OUT / "source_registry.json").read_text(encoding="utf-8"))
    path = EVAL / "discovery/baseline.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    done = {(row["candidate_id"], row["requested_seed"], row["seat"]) for row in rows}
    tasks = [
        {
            "control": str(OUT / "runtime/control/main.py"),
            "opponent": str(ROOT / source["entrypoint"]),
            "candidate_id": source["candidate_id"],
            "seed": seed,
            "seat": seat,
        }
        for source in registry["sources"]
        for seed in registry["discovery_seeds"]
        for seat in (0, 1)
        if (source["candidate_id"], seed, seat) not in done
    ]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(baseline_task, task): task for task in tasks}
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(row["candidate_id"], row["requested_seed"], row["seat"], row["result"], row["margin"], flush=True)


def freeze_candidate(version):
    from scripts.evaluation.runner import extract_archive
    from scripts.package_submission import submission_files

    directory = ROOT / "agents" / version
    target = OUT / f"{version}_preregistration.json"
    if target.exists():
        raise SystemExit("Candidate already frozen")
    contents = {name: path.read_bytes() for name, path in submission_files(directory).items()}
    archive = ROOT / "artifacts/submissions" / f"{version}.tar.gz"
    package(contents, archive)
    extract_archive(archive, OUT / "runtime" / version)
    registry = json.loads((OUT / "source_registry.json").read_text(encoding="utf-8"))
    spec = {
        "version": version,
        "frozen_at": datetime.now(UTC).isoformat(),
        "hypothesis": "H1 residual-demand second-shop continuation",
        "source_hashes": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
        "archive": str(archive.relative_to(ROOT)),
        "archive_sha256": digest(archive),
        "control_sha256": registry["champion_sha256"],
        "engine_version": "1.32.7",
        "engine_sha256": "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e",
        "framework_hashes": {
            str(path.relative_to(ROOT)): digest(path) for path in (ROOT / "scripts/evaluation").glob("*.py")
        },
        "intervention_kind": "route_choice",
        "intended_action_step": 153,
        "threshold": 2000,
        "supply_scale_scenarios": [0.75, 1.0, 1.25],
        "seats": [0, 1],
        "stored_steps": 720,
        "seeds": {
            "development": registry["development_seeds"],
            "promotion": registry["promotion_seeds"],
            "fresh_holdout": registry["fresh_holdout_seeds"],
        },
        "criteria": {
            "safety": (
                "No candidate-new runtime, incomplete, animal/weed, negative cash, field/market no-op, "
                "partial transaction or missing action count regression."
            ),
            "isolation": "Exact actions and states before t153; only declared route choice at t153 permits divergence.",
            "trigger": "Observed loss-to-win exceeds win-to-loss; no coin-only promotion.",
            "meta": (
                "At least three materially independent reacting policy families, "
                "positive family-cluster lower CI and no major-lineage regression."
            ),
            "robustness": "Positive worst scenario under source/lineage reweighting; Bradley-Terry diagnostic only.",
            "holdout": "Run unused seeds only after all prior gates pass; no retuning. Otherwise remain sealed.",
        },
        "lineage_caution": (
            "mooman/souvik share PSR continuation ancestry; mooman/ggmljs additionally share Kaito ancestry. "
            "Report source matrix plus conservative merged ancestry results."
        ),
        "outcome_selection": "First ordered failed gate rejects; fast screen is negative-only",
    }
    if version == "v114probe":
        spec.update(
            hypothesis="H1 forced-delivery mechanism ablation after inactive V114r1",
            threshold=None,
            supply_scale_scenarios=[],
            research_only=True,
            not_submission_candidate=True,
            purpose=(
                "Separate route cash/execution feasibility from forecast-gate inactivity; "
                "force the same compatible yarn_second suffix at t153 only when baseline selects default. "
                "Development seeds already consumed; no promotion or fresh-holdout claim."
            ),
        )
    save(target, spec)
    print(target, spec["archive_sha256"], flush=True)


def paired(version, phase, workers):
    from scripts.evaluation.runner import run_pair_task

    if phase != "development":
        raise SystemExit(
            "Promotion and Fresh Holdout remain sealed: this frozen study has only two conservative "
            "source-ancestry groups and no passing activated candidate. Register a qualified study first."
        )
    registry = json.loads((OUT / "source_registry.json").read_text(encoding="utf-8"))
    spec = json.loads((OUT / f"{version}_preregistration.json").read_text(encoding="utf-8"))
    assert digest(ROOT / spec["archive"]) == spec["archive_sha256"]
    path = EVAL / version / phase / "pairs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    done = {(row["lineage_id"], row["seed"], row["seat"]) for row in rows}
    tasks = [
        {
            "control_main": str(OUT / "runtime/control/main.py"),
            "treatment_main": str(OUT / "runtime" / version / "main.py"),
            "opponent_main": str(ROOT / source["entrypoint"]),
            "lineage_id": source["candidate_id"],
            "opponent_name": source["candidate_id"],
            "opponent_tier": "Gold",
            "meta_weight": 0.25,
            "seed": seed,
            "seat": seat,
            "episode_steps": 720,
            "phase": phase,
            "intended_action_step": spec["intended_action_step"],
            "intervention_kind": spec["intervention_kind"],
            "strict_all_step_safety": True,
            "replay_dir": str(EVAL / version / "replays"),
        }
        for source in registry["sources"]
        for seed in spec["seeds"][phase]
        for seat in (0, 1)
        if (source["candidate_id"], seed, seat) not in done
    ]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_pair_task, task): task for task in tasks}
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                row["lineage_id"],
                row["seed"],
                row["seat"],
                row["control"]["result"],
                row["treatment"]["result"],
                row["delta_margin"],
                row["gate_requested"],
                row["candidate_new_major_regressions"],
                flush=True,
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "probe", "freeze", "paired", "fill-diagnostics"])
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--version", default="v114")
    parser.add_argument("--phase", choices=["development", "promotion", "fresh_holdout"], default="development")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "probe":
        probe(args.workers)
    elif args.command == "freeze":
        freeze_candidate(args.version)
    elif args.command == "fill-diagnostics":
        fill_diagnostics(args.workers)
    else:
        paired(args.version, args.phase, args.workers)


def fill_diagnostics(workers):
    """Retain absolute economy metrics for inactive pairs omitted by the runner."""
    rows = [
        json.loads(line) for line in (EVAL / "v114r1/development/pairs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    registry = json.loads((OUT / "source_registry.json").read_text(encoding="utf-8"))
    sources = {row["candidate_id"]: row for row in registry["sources"]}
    target = EVAL / "development_inactive_controls.jsonl"
    if target.exists():
        raise SystemExit("Diagnostic controls already recorded")
    tasks = []
    for row in rows:
        if row["agent_trace"]["treatment"]["research_decision"]["original"] == "default":
            continue
        tasks.append(
            {
                "control": str(OUT / "runtime/control/main.py"),
                "opponent": str(ROOT / sources[row["lineage_id"]]["entrypoint"]),
                "candidate_id": row["lineage_id"],
                "seed": row["seed"],
                "seat": row["seat"],
                "phase": "development_inactive_controls",
                "expected_margin": row["control"]["margin"],
            }
        )
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(baseline_task, task): task for task in tasks}
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            assert row["margin"] == futures[future]["expected_margin"], "Diagnostic replay changed paired outcome"
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            print("Diagnostic control verified", row["candidate_id"], row["requested_seed"], row["seat"], flush=True)


if __name__ == "__main__":
    main()
