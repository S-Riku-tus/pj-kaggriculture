"""Feasible continuation research; unique artifacts, spent seeds, no submission."""

# ruff: noqa: E501, I001

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXPERIMENT = "research_20260911_continuations"
OUT = ROOT / "experiments" / EXPERIMENT
EVAL = ROOT / "data/evaluation" / EXPERIMENT
OLD = ROOT / "experiments/research_20260910"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL).decode("utf-8")


def audit():
    import importlib.metadata

    if (OUT / "initial_audit.json").exists():
        raise SystemExit("Initial audit already frozen")
    tracked = git("ls-files").splitlines()
    extra = git("ls-files", "--others", "--exclude-standard").splitlines()
    # Preserve hashes of the existing tracked work and explicitly named untracked inputs.
    files = sorted(set(tracked + extra))
    before = {name: digest(ROOT / name) for name in files if (ROOT / name).is_file()}
    engine = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
    identities = {
        "source": digest(ROOT / "agents/v111/main.py"),
        "archive": digest(OLD / "champion_v111.tar.gz"),
        "engine": digest(engine),
    }
    assert identities == {
        "source": "699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660",
        "archive": "85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e",
        "engine": "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e",
    }, identities
    raw = ROOT / "data/evaluation/research_20260910"
    protected = set(range(10091101, 10091113)) | set(range(10091901, 10091913))
    used = set()
    for file in raw.rglob("*.jsonl"):
        for line in file.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            value = row.get("requested_seed", row.get("seed"))
            if value is not None:
                used.add(int(value))
    save(OUT / "initial_audit.json", {
        "created_at": datetime.now(UTC).isoformat(), "branch": git("branch", "--show-current").strip(),
        "head": git("rev-parse", "HEAD").strip(), "status": git("status", "--short"),
        "log": git("log", "-6", "--oneline"), "before_hashes": before,
        "identities": identities, "engine_version": importlib.metadata.version("kaggle-environments"),
        "old_evaluation_file_hashes": {str(p.relative_to(ROOT)): digest(p) for p in raw.rglob("*.jsonl")},
        "used_old_research_seeds": sorted(used), "protected_overlap": sorted(used & protected),
        "remote_artifact_identity": "unknown; action similarity is not archive identity",
        "budget_deadline_utc": "2026-09-11T08:54:00+00:00",
    })
    assert not (used & protected)
    save(OUT / "holdout_manifest.json", {
        "spent_discovery": list(range(10091001, 10091005)),
        "spent_development": list(range(10091011, 10091015)),
        "promotion_reserved": list(range(10091101, 10091113)),
        "fresh_reserved": list(range(10091901, 10091913)),
        "status": "SEALED; no simulation or replay-body access permitted before qualification",
        "replay_body_reservations": "8; metadata contains outcomes and is not fully blind",
        "qualification": "Frozen executable candidate; delivery; no new hard safety events; positive paired outcome; >=3 independent ancestry groups; robust seed-block uncertainty; then E5 once",
    })
    print(json.dumps({"identities": identities, "files": len(before), "used_seeds": sorted(used)}), flush=True)


def refresh():
    import requests

    from scripts import acquire_research_field_20260910 as acquisition

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    acquisition.OUT = OUT / "remote" / stamp
    acquisition.fetch("leaderboard", "competitions.LeaderboardService/GetLeaderboard", {"competitionId": 147734})
    acquisition.fetch("our_team", "competitions.SubmissionService/ListTeamPublicSubmissions", {"teamId": 16749257})
    url = "https://api.github.com/search/repositories?q=kaggriculture&sort=updated&per_page=50"
    response = requests.get(url, timeout=45)
    save(acquisition.OUT / "github_search.json", {
        "fetched_at": datetime.now(UTC).isoformat(), "url": url,
        "status": response.status_code, "data": response.json(),
    })
    for repo in ("alvaromendizabal/kaggriculture", "robsartin/robriculture", "conchocon154/kaggriculture-agent", "OscarLegoupil/agriculture-agent"):
        metadata = requests.get(f"https://api.github.com/repos/{repo}", timeout=30).json()
        branch = metadata.get("default_branch", "main")
        commit = requests.get(f"https://api.github.com/repos/{repo}/commits/{branch}", timeout=30).json()
        sha = commit.get("sha", branch)
        tree = requests.get(f"https://api.github.com/repos/{repo}/git/trees/{sha}?recursive=1", timeout=30)
        readme = requests.get(f"https://raw.githubusercontent.com/{repo}/{sha}/README.md", timeout=30)
        save(acquisition.OUT / (repo.replace("/", "__") + ".json"), {
            "fetched_at": datetime.now(UTC).isoformat(), "repository": repo, "commit": sha,
            "license": metadata.get("license"), "tree_status": tree.status_code, "tree": tree.json(),
            "readme_status": readme.status_code, "readme": readme.text,
        })
        print(repo, sha, tree.status_code, readme.status_code, flush=True)
    print(str(acquisition.OUT), flush=True)


def aa(workers=2):
    from scripts.evaluation.runner import run_tasks

    registry = json.loads((OLD / "source_registry.json").read_text(encoding="utf-8"))
    tasks = []
    for source in registry["sources"]:
        if source["candidate_id"] not in ("mooman_e052a", "qeinstein_moev2"):
            continue
        for seed in (10091011, 10091012):
            for seat in (0, 1):
                tasks.append({
                    "control_main": str(OLD / "runtime/control/main.py"),
                    "treatment_main": str(OLD / "runtime/control/main.py"),
                    "opponent_main": str(ROOT / source["entrypoint"]), "seed": seed, "seat": seat,
                    "episode_steps": 720, "phase": "aa", "lineage_id": source["candidate_id"],
                    "opponent_name": source["candidate_id"], "opponent_tier": "Gold", "meta_weight": 0.5,
                    "intended_action_step": 153, "inherited_transaction_step": 248,
                    "intervention_kind": "route_choice", "replay_dir": str(EVAL / "aa/replays"),
                    "strict_all_step_safety": True, "save_all_replays": True,
                })
    target = EVAL / "aa/pairs.jsonl"
    if target.exists():
        raise SystemExit("A/A already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()

    def progress(done, total, row):
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(done, total, row["lineage_id"], row["seed"], row["seat"], row["delta_margin"], flush=True)

    rows = run_tasks(tasks, workers, progress)
    elapsed = time.perf_counter() - start
    save(EVAL / "aa/summary.json", {
        "elapsed_seconds": elapsed, "games_per_minute": 2 * len(rows) * 60 / elapsed,
        "pairs": len(rows), "all_identical": all(
            r["behavioral_isolation_valid"] and not r["incremental_treatment"] and not r["delta_margin"]
            and not r["candidate_new_major_regressions"] for r in rows
        ),
        "seed_and_completion_valid": all(
            r[a]["requested_seed"] == r[a]["resolved_seed"] == r["seed"]
            and r["safety"][a]["completed_720"] for r in rows for a in ("control", "treatment")
        ), "workers": workers, "checkpoint_resume": "not used; full rerun with fresh modules",
    })


def freeze_options():
    from scripts.evaluation.runner import extract_archive
    from scripts.research_20260910 import package

    target = OUT / "options_preregistration.json"
    if target.exists():
        raise SystemExit("Options already frozen")
    variants = []
    with tarfile.open(OLD / "champion_v111.tar.gz", "r:gz") as handle:
        original = {m.name: handle.extractfile(m).read() for m in handle.getmembers() if m.isfile()}
    for mode in ("immediate", "town"):
        version = "v115p_" + mode
        settings = {"version": version, "mode": mode, "start": 361, "end": 432, "minimum_cash": 4000}
        contents = dict(original)
        contents["v111_base.py"] = contents.pop("main.py")
        contents["main.py"] = (ROOT / "scripts/continuation_option_template.py").read_bytes()
        contents["option.json"] = json.dumps(settings, indent=2).encode("utf-8")
        directory = ROOT / "agents" / version
        directory.mkdir(exist_ok=False)
        for name, content in contents.items():
            (directory / name).write_bytes(content)
        save(directory / "submission_manifest.json", {"files": [{"target": name, "source": name} for name in sorted(contents)]})
        archive = OUT / f"{version}.tar.gz"
        package(contents, archive)
        extract_archive(archive, OUT / "runtime" / version)
        variants.append({
            **settings, "archive": str(archive.relative_to(ROOT)), "archive_sha256": digest(archive),
            "source_hashes": {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()},
            "runtime": str((OUT / "runtime" / version / "main.py").relative_to(ROOT)),
        })
    save(target, {
        "frozen_at": datetime.now(UTC).isoformat(), "hypothesis": "H1 bounded sale continuation",
        "variants": variants, "control_archive_sha256": digest(OLD / "champion_v111.tar.gz"),
        "protocol": "docs/research_20260911_preregistration.md",
        "protocol_sha256": digest(ROOT / "docs/research_20260911_preregistration.md"),
        "framework_hashes": {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / "scripts/evaluation").glob("*.py")},
        "allowed_seeds": list(range(10091011, 10091015)), "seats": [0, 1],
        "fresh_status": "SEALED", "checkpoint": "never; both arms full rerun", "research_only": True,
    })
    print(json.dumps(variants), flush=True)


def paired(version, workers):
    from scripts.evaluation.runner import run_tasks
    from scripts.evaluation.statistics import bradley_terry_diagnostic, pairwise_payoff_matrix, robust_meta, summarize_pairs

    prereg_file = {
        "v115p_livestock": "livestock_preregistration.json",
        "v115p_retain_cow": "retain_cow_preregistration.json",
        "v115p_retain_cow_r1": "retain_cow_r1_preregistration.json",
        "v115p_managed_sheep": "managed_animals_preregistration.json",
        "v115p_managed_goose": "managed_animals_preregistration.json",
    }.get(version, "options_preregistration.json")
    prereg = json.loads((OUT / prereg_file).read_text(encoding="utf-8"))
    variant = next(v for v in prereg["variants"] if v["version"] == version)
    assert digest(ROOT / variant["archive"]) == variant["archive_sha256"]
    for name, value in variant["source_hashes"].items():
        assert digest(OUT / "runtime" / version / name) == value
    aa_summary = json.loads((EVAL / "aa/summary.json").read_text(encoding="utf-8"))
    assert aa_summary["all_identical"] and aa_summary["seed_and_completion_valid"]
    registry = json.loads((OLD / "source_registry.json").read_text(encoding="utf-8"))
    target = EVAL / version / "development/pairs.jsonl"
    existing = [json.loads(x) for x in target.read_text(encoding="utf-8").splitlines()] if target.exists() else []
    done_keys = {(r["lineage_id"], r["seed"], r["seat"]) for r in existing}
    tasks = []
    for source in registry["sources"]:
        assert digest(ROOT / source["archive"]) == source["archive_sha256"]
        for seed in prereg["allowed_seeds"]:
            for seat in (0, 1):
                if (source["candidate_id"], seed, seat) in done_keys:
                    continue
                tasks.append({
                    "control_main": str(OLD / "runtime/control/main.py"),
                    "treatment_main": str(ROOT / variant["runtime"]),
                    "opponent_main": str(ROOT / source["entrypoint"]), "seed": seed, "seat": seat,
                    "episode_steps": 720, "phase": "development", "lineage_id": source["candidate_id"],
                    "opponent_name": source["candidate_id"], "opponent_tier": "Gold", "meta_weight": 0.25,
                    "intended_action_step": variant["start"], "activation_window": [variant["start"], variant["end"]],
                    "inherited_transaction_step": 248, "intervention_kind": "route_choice",
                    "replay_dir": str(EVAL / version / "replays"), "strict_all_step_safety": True, "save_all_replays": True,
                    "provenance": {"treatment": variant["archive_sha256"], "control": prereg["control_archive_sha256"],
                                   "opponent": source["archive_sha256"], "engine": "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e"},
                })
    target.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()

    def progress(done, total, row):
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(done, total, row["lineage_id"], row["seed"], row["seat"], row["control"]["result"], row["treatment"]["result"], row["delta_margin"], row["candidate_new_major_regressions"], flush=True)

    rows = existing + run_tasks(tasks, workers, progress)
    weights = {source["candidate_id"]: 0.25 for source in registry["sources"]}
    matrix = pairwise_payoff_matrix(rows, repetitions=2000, bootstrap_seed=20260911)
    save(target.parent / "summary.json", {
        "elapsed_seconds_this_run": time.perf_counter() - start, "summary": summarize_pairs(rows),
        "matrix": matrix, "robust_meta": robust_meta(matrix, weights, radius=0.2), "bt": bradley_terry_diagnostic(rows),
        "invalid": sum(not r["behavioral_isolation_valid"] for r in rows),
        "hard_safety_pairs": sum(bool(r["candidate_new_major_regressions"]) for r in rows),
        "eligible": sum(bool(r["agent_trace"]["treatment"].get("research_decision", {}).get("eligible")) for r in rows),
        "activated": sum(r["incremental_treatment"] for r in rows),
    })


def freeze_livestock():
    from scripts.evaluation.runner import extract_archive
    from scripts.research_20260910 import package

    target = OUT / "livestock_preregistration.json"
    if target.exists():
        raise SystemExit("Livestock option already frozen")
    version = "v115p_livestock"
    with tarfile.open(OLD / "champion_v111.tar.gz", "r:gz") as handle:
        contents = {m.name: handle.extractfile(m).read() for m in handle.getmembers() if m.isfile()}
    contents["v111_base.py"] = contents.pop("main.py")
    contents["main.py"] = (ROOT / "scripts/livestock_option_template.py").read_bytes()
    directory = ROOT / "agents" / version
    directory.mkdir(exist_ok=False)
    for name, content in contents.items():
        (directory / name).write_bytes(content)
    save(directory / "submission_manifest.json", {"files": [{"target": name, "source": name} for name in sorted(contents)]})
    archive = OUT / f"{version}.tar.gz"
    package(contents, archive)
    extract_archive(archive, OUT / "runtime" / version)
    save(target, {
        "frozen_at": datetime.now(UTC).isoformat(), "hypothesis": "H3a two-Sheep transaction route value",
        "variants": [{"version": version, "start": 248, "end": 249,
                      "archive": str(archive.relative_to(ROOT)), "archive_sha256": digest(archive),
                      "source_hashes": {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()},
                      "runtime": str((OUT / "runtime" / version / "main.py").relative_to(ROOT))}],
        "control_archive_sha256": digest(OLD / "champion_v111.tar.gz"),
        "protocol": "docs/research_20260911_livestock_preregistration.md",
        "protocol_sha256": digest(ROOT / "docs/research_20260911_livestock_preregistration.md"),
        "framework_hashes": {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / "scripts/evaluation").glob("*.py")},
        "allowed_seeds": list(range(10091011, 10091015)), "seats": [0, 1], "research_only": True, "fresh_status": "SEALED",
    })


def freeze_retain_cow():
    from scripts.evaluation.runner import extract_archive
    from scripts.research_20260910 import package

    target = OUT / "retain_cow_preregistration.json"
    if target.exists():
        raise SystemExit("Retain-Cow option already frozen")
    version = "v115p_retain_cow"
    with tarfile.open(OLD / "champion_v111.tar.gz", "r:gz") as handle:
        contents = {m.name: handle.extractfile(m).read() for m in handle.getmembers() if m.isfile()}
    contents["v111_base.py"] = contents.pop("main.py")
    contents["main.py"] = (ROOT / "scripts/retain_cow_option_template.py").read_bytes()
    directory = ROOT / "agents" / version
    directory.mkdir(exist_ok=False)
    for name, content in contents.items():
        (directory / name).write_bytes(content)
    save(directory / "submission_manifest.json", {
        "files": [{"target": name, "source": name} for name in sorted(contents)]
    })
    archive = OUT / f"{version}.tar.gz"
    package(contents, archive)
    extract_archive(archive, OUT / "runtime" / version)
    save(target, {
        "frozen_at": datetime.now(UTC).isoformat(),
        "hypothesis": "H3c retain V111's completed Cow continuation",
        "variants": [{
            "version": version, "start": 248, "end": 248,
            "archive": str(archive.relative_to(ROOT)), "archive_sha256": digest(archive),
            "source_hashes": {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()},
            "runtime": str((OUT / "runtime" / version / "main.py").relative_to(ROOT)),
        }],
        "control_archive_sha256": digest(OLD / "champion_v111.tar.gz"),
        "protocol": "docs/research_20260912_retain_cow_preregistration.md",
        "protocol_sha256": digest(ROOT / "docs/research_20260912_retain_cow_preregistration.md"),
        "framework_hashes": {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / "scripts/evaluation").glob("*.py")},
        "allowed_seeds": list(range(10091011, 10091015)), "seats": [0, 1],
        "research_only": True, "fresh_status": "SEALED",
    })


def freeze_managed_animals():
    from scripts.evaluation.runner import extract_archive
    from scripts.research_20260910 import package

    target = OUT / "managed_animals_preregistration.json"
    if target.exists():
        raise SystemExit("Managed-animal options already frozen")
    with tarfile.open(OLD / "champion_v111.tar.gz", "r:gz") as handle:
        original = {m.name: handle.extractfile(m).read() for m in handle.getmembers() if m.isfile()}
    variants = []
    for species in ("SHEEP", "GOOSE"):
        suffix = species.lower()
        version = f"v115p_managed_{suffix}"
        settings = {"version": version, "species": species}
        contents = dict(original)
        contents["v111_base.py"] = contents.pop("main.py")
        contents["main.py"] = (ROOT / "scripts/managed_animal_template.py").read_bytes()
        contents["animal_option.json"] = json.dumps(settings, indent=2).encode("utf-8")
        directory = ROOT / "agents" / version
        directory.mkdir(exist_ok=False)
        for name, content in contents.items():
            (directory / name).write_bytes(content)
        save(directory / "submission_manifest.json", {
            "files": [{"target": name, "source": name} for name in sorted(contents)]
        })
        archive = OUT / f"{version}.tar.gz"
        package(contents, archive)
        extract_archive(archive, OUT / "runtime" / version)
        variants.append({
            **settings, "start": 248, "end": 718,
            "archive": str(archive.relative_to(ROOT)), "archive_sha256": digest(archive),
            "source_hashes": {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()},
            "runtime": str((OUT / "runtime" / version / "main.py").relative_to(ROOT)),
        })
    save(target, {
        "frozen_at": datetime.now(UTC).isoformat(),
        "hypothesis": "H3b managed two-animal continuations",
        "variants": variants,
        "control_archive_sha256": digest(OLD / "champion_v111.tar.gz"),
        "protocol": "docs/research_20260911_managed_animals_preregistration.md",
        "protocol_sha256": digest(ROOT / "docs/research_20260911_managed_animals_preregistration.md"),
        "framework_hashes": {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / "scripts/evaluation").glob("*.py")},
        "allowed_seeds": list(range(10091011, 10091015)), "seats": [0, 1],
        "research_only": True, "fresh_status": "SEALED",
    })


def freeze_retain_cow_r1():
    from scripts.evaluation.runner import extract_archive
    from scripts.research_20260910 import package

    target = OUT / "retain_cow_r1_preregistration.json"
    if target.exists():
        raise SystemExit("Retain-Cow r1 already frozen")
    version = "v115p_retain_cow_r1"
    with tarfile.open(OLD / "champion_v111.tar.gz", "r:gz") as handle:
        contents = {m.name: handle.extractfile(m).read() for m in handle.getmembers() if m.isfile()}
    contents["v111_base.py"] = contents.pop("main.py")
    contents["main.py"] = (ROOT / "scripts/retain_cow_option_template.py").read_bytes()
    contents["option.json"] = json.dumps({"version": version}, indent=2).encode("utf-8")
    directory = ROOT / "agents" / version
    directory.mkdir(exist_ok=False)
    for name, content in contents.items():
        (directory / name).write_bytes(content)
    save(directory / "submission_manifest.json", {
        "files": [{"target": name, "source": name} for name in sorted(contents)]
    })
    archive = OUT / f"{version}.tar.gz"
    package(contents, archive)
    extract_archive(archive, OUT / "runtime" / version)
    save(target, {
        "frozen_at": datetime.now(UTC).isoformat(),
        "hypothesis": "H3c-r1 retain completed Cow continuation; evaluation-window correction only",
        "invalid_predecessor": "v115p_retain_cow",
        "variants": [{
            "version": version, "start": 248, "end": 249,
            "archive": str(archive.relative_to(ROOT)), "archive_sha256": digest(archive),
            "source_hashes": {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()},
            "runtime": str((OUT / "runtime" / version / "main.py").relative_to(ROOT)),
        }],
        "control_archive_sha256": digest(OLD / "champion_v111.tar.gz"),
        "protocol": "docs/research_20260912_retain_cow_r1_preregistration.md",
        "protocol_sha256": digest(ROOT / "docs/research_20260912_retain_cow_r1_preregistration.md"),
        "framework_hashes": {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / "scripts/evaluation").glob("*.py")},
        "allowed_seeds": list(range(10091011, 10091015)), "seats": [0, 1],
        "research_only": True, "fresh_status": "SEALED",
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["audit", "refresh", "aa", "freeze", "freeze-livestock", "freeze-retain-cow", "freeze-retain-cow-r1", "freeze-managed", "paired"])
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--version")
    args = parser.parse_args()
    if args.mode == "paired":
        paired(args.version, args.workers)
    elif args.mode == "freeze-livestock":
        freeze_livestock()
    elif args.mode == "freeze-retain-cow":
        freeze_retain_cow()
    elif args.mode == "freeze-managed":
        freeze_managed_animals()
    elif args.mode == "freeze-retain-cow-r1":
        freeze_retain_cow_r1()
    elif args.mode == "freeze":
        freeze_options()
    elif args.mode == "aa":
        aa(args.workers)
    else:
        {"audit": audit, "refresh": refresh}[args.mode]()


if __name__ == "__main__":
    main()
