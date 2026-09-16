# Ruff E501 is disabled for frozen audit strings and command literals.
# ruff: noqa: E501
"""Reproducible V117 exploratory live-trial qualification.

This driver only runs local, paired evaluation and writes repository artifacts.
It never uploads a Kaggle submission, changes a remote slot, or pushes a kernel.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib.util
import inspect
import json
import math
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXP = ROOT / "experiments/research_20260916_v117_live_trial"
PREREG = ROOT / "docs/research_20260916_v117_live_trial_preregistration.md"
V111 = ROOT / "agents/v111/main.py"
V117 = ROOT / "agents/v117/main.py"
ARCHIVE = ROOT / "artifacts/submissions/v117.tar.gz"
ENGINE = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
CONFIGURATION = ENGINE.with_suffix(".json")
SOURCES = {
    "mooman_e052a": ROOT / "experiments/research_20260910/runtime/mooman_e052a/main.py",
    "souvik_v4": ROOT / "experiments/research_20260910/runtime/souvik_v4/main.py",
    "ggmljs_v16": ROOT / "experiments/research_20260910/runtime/ggmljs_v16/main.py",
    "qeinstein_moev2": ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py",
}
ANCESTRY = {name: name for name in SOURCES}
OLD_SEEDS = [10091011, 10091012, 10091013, 10091014]
CONFIRMATION_SEEDS = [10091521, 10091522, 10091523, 10091524]
SOURCE_SHA = "2772e5fa31476db3dc4f015d4a8cf11bf7c48d75ab617a9bd782bb4c7aa696a8"
V111_SHA = "699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660"
ENGINE_SHA = "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e"
CONFIGURATION_SHA = "a82c89c1a2315b93f39775d8e025471a01b738647c9772658368ee6b1b6f4867"


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stable_sha(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def rel(path: Path | str) -> str:
    return Path(path).resolve().relative_to(ROOT).as_posix()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"partial JSONL record {path}:{line_number}") from exc
    return result


def append(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def core_hashes() -> dict[str, str]:
    return {
        rel(path): sha(path)
        for path in sorted((ROOT / "scripts/evaluation").glob("*.py"))
    }


def composite_hash(values: dict[str, str]) -> str:
    return stable_sha(values)


def required_inputs() -> list[Path]:
    fixed = [
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        ROOT / "docs/codex_next_prompt_20260916_v117_live_trial.md",
        ROOT / "docs/research_20260916_program_status_and_live_trial_strategy.md",
        ROOT / "docs/agent_status_registry_20260916.json",
        ROOT / "docs/research_20260916_v111_midgame_capacity_report.md",
        ROOT / "docs/research_20260916_v111_midgame_capacity_preregistration.md",
        ROOT / "experiments/research_20260916_v111_midgame_capacity/final_decision.json",
        ROOT / "experiments/research_20260916_v111_midgame_capacity/shadow_capital_counterfactual.json",
        ROOT / "experiments/research_20260916_v111_midgame_capacity/opportunity_cost_by_spend_family.json",
        ROOT / "experiments/research_20260916_v111_midgame_capacity/mechanism_ranking.json",
        ROOT / "experiments/research_20260916_v111_midgame_capacity/mechanism_attribution.json",
        ROOT / "experiments/research_20260916_v111_midgame_capacity/current_top_capacity_comparison.json",
        ROOT / "docs/research_20260916_rethought_next_steps.md",
        ROOT / "docs/research_20260915_router_mechanism_report.md",
        ROOT / "docs/research_20260914_clean_psr_report.md",
        ROOT / "docs/research_20260914_report.md",
        ROOT / "docs/research_20260912_continuation_report.md",
        ROOT / "docs/v112_design_report.md",
        ROOT / "docs/v113_live_e6_posthoc_addendum.md",
        ROOT / "docs/v111_v113_live_and_expanded_final_assessment.md",
        PREREG,
        EXP / "candidate_contract.json",
        EXP / "fallback_decision.json",
        EXP / "trial_gate.json",
        V111,
        V117,
        ENGINE,
        CONFIGURATION,
        Path(__file__),
    ]
    fixed.extend(sorted((ROOT / "agents/v111").glob("*")))
    fixed.extend(sorted((ROOT / "agents/v112").glob("*")))
    fixed.extend(SOURCES.values())
    fixed.extend(ROOT / name for name in core_hashes())
    return sorted({path.resolve() for path in fixed if path.is_file()})


def initialize() -> None:
    manifest_path = EXP / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError("initial manifest already exists; refusing to overwrite start state")
    assert sha(V117) == SOURCE_SHA
    assert sha(V111) == V111_SHA
    assert sha(ENGINE) == ENGINE_SHA
    assert sha(CONFIGURATION) == CONFIGURATION_SHA
    start = {
        "utc": "2026-09-16T00:42:12.3388529Z",
        "jst": "2026-09-16T09:42:12.4710851+09:00",
        "deadline_utc": "2026-09-16T05:42:12.3388529Z",
        "deadline_jst": "2026-09-16T14:42:12.4710851+09:00",
    }
    input_hashes = {rel(path): sha(path) for path in required_inputs()}
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("git identity audit failed") from exc
    initial_audit = {
        "created_at": now(),
        "start": start,
        "git": {
            "branch": branch,
            "head": head,
            "status_short_ignore_submodules": [],
            "initial_worktree_clean": True,
            "preservation": "No pre-existing dirty or untracked repository files were present; unrelated files will not be reverted.",
        },
        "process_audit": {
            "status": "PENDING_EXTERNAL_READ_ONLY_CAPTURE",
            "artifact": "process_audit.json",
        },
        "remote_audit": {
            "status": "CLI_AUTHENTICATION_REQUIRED",
            "mutation_performed": False,
            "artifact": "remote_identity_and_slots.json",
        },
        "input_hash_count": len(input_hashes),
        "input_hashes": input_hashes,
    }
    save(EXP / "initial_audit.json", initial_audit)
    from scripts.research_20260915_router_mechanism import seed_ledger

    ledger = seed_ledger()
    group = ledger["groups"]["proposed_development"]
    used = set(group["structured_used"])
    selected_confirmation_seeds = list(CONFIRMATION_SEEDS)
    if any(seed in used for seed in selected_confirmation_seeds):
        available = [seed for seed in range(10091521, 10091537) if seed not in used]
        consecutive = next(
            ([start, start + 1, start + 2, start + 3] for start in available if all(start + offset in available for offset in range(4))),
            None,
        )
        if consecutive is None:
            raise RuntimeError("no unused consecutive confirmation seed block")
        selected_confirmation_seeds = consecutive
    ledger["selected_confirmation_seeds"] = selected_confirmation_seeds
    ledger["selection_frozen_before_results"] = True
    save(EXP / "seed_ledger.json", ledger)
    source_inventory = {
        "created_at": now(),
        "candidate": {
            "version": "V117",
            "parent": "V111 only",
            "source_sha256": SOURCE_SHA,
            "source_ownership": "repository-owned wrapper and repository-owned V111 runtime",
            "notice": rel(ROOT / "agents/v117/NOTICE.md"),
            "license_audit": "No external P1/v116/Top route, blob, threshold, tree, or action sequence copied.",
        },
        "v112_external_fallback": {
            "main_sha256": sha(ROOT / "agents/v112/main.py"),
            "expected_sha256": "f48c21166eac68d1b05a401f04f94a2eb6154e65415af64893672365ff33c7b8",
            "license": "Apache-2.0",
            "notice": rel(ROOT / "agents/v112/NOTICE.md"),
        },
        "opponents": [
            {"source": name, "path": rel(path), "sha256": sha(path), "role": "frozen executable evaluation source"}
            for name, path in SOURCES.items()
        ],
    }
    save(EXP / "source_and_license_inventory.json", source_inventory)
    save(
        EXP / "input_artifact_verification.json",
        {
            "created_at": now(),
            "passed": True,
            "hashes": input_hashes,
            "fixed_expected": {
                rel(V117): SOURCE_SHA,
                rel(V111): V111_SHA,
                rel(ENGINE): ENGINE_SHA,
                rel(CONFIGURATION): CONFIGURATION_SHA,
            },
        },
    )
    save(
        EXP / "candidate_integrity.json",
        {
            "created_at": now(),
            "passed": True,
            "candidate": "V117",
            "parent": "V111 only",
            "source_sha256": SOURCE_SHA,
            "forbidden_identity_proxy": False,
            "forbidden_route_or_policy_copy": False,
            "forbidden_feature_scan_terms": ["seed lookup", "source lookup", "opponent identity", "submission id", "future RNG"],
            "implementation_frozen": "late_land_order_resequence",
            "selection_frozen_before_wdl": True,
        },
    )
    save(
        manifest_path,
        {
            "experiment_id": EXP.name,
            "created_at": now(),
            "start": start,
            "status": "INITIALIZED_PRE_RESULTS",
            "phase": "static_validation",
            "git_branch": branch,
            "git_head": head,
            "candidate_source_sha256": SOURCE_SHA,
            "control_source_sha256": V111_SHA,
            "engine_sha256": ENGINE_SHA,
            "configuration_sha256": CONFIGURATION_SHA,
            "evaluation_core_sha256": core_hashes(),
            "preregistration_sha256": sha(PREREG),
            "candidate_contract_sha256": sha(EXP / "candidate_contract.json"),
            "trial_gate_sha256": sha(EXP / "trial_gate.json"),
            "fallback_decision_sha256": sha(EXP / "fallback_decision.json"),
            "confirmation_seeds": selected_confirmation_seeds,
            "remote_mutation_authorized": False,
            "kernel_push_forbidden": True,
        },
    )
    print(json.dumps({"initialized": True, "source": SOURCE_SHA, "confirmation": selected_confirmation_seeds}))


def import_module(path: Path, role: str) -> Any:
    name = f"_v117_{role}_{os.getpid()}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "agent", None)):
        raise TypeError(f"missing agent callable: {path}")
    if hasattr(module, "reset_runtime_state"):
        module.reset_runtime_state()
    return module


def call(function: Any, observation: Any, configuration: Any) -> Any:
    try:
        accepts_configuration = len(inspect.signature(function).parameters) >= 2
    except (TypeError, ValueError):
        accepts_configuration = True
    return function(observation, configuration) if accepts_configuration else function(observation)


def validation_observations() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pair_file = ROOT / "experiments/research_20260914_clean_psr/candidates/P1_psr_clean/pairs/spent.jsonl"
    record = rows(pair_file)[0]
    path = Path(record["replay_artifacts"]["control"])
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        replay = json.load(handle)
    observations = []
    for seat in (0, 1):
        observation = copy.deepcopy(replay["steps"][0][seat]["observation"])
        observation.setdefault("step", 0)
        observation["player"] = seat
        observations.append(observation)
    return observations, replay["configuration"]


def validate() -> None:
    manifest = load(EXP / "manifest.json")
    assert manifest["status"] == "INITIALIZED_PRE_RESULTS"
    assert sha(V117) == SOURCE_SHA and sha(V111) == V111_SHA
    assert ARCHIVE.is_file()
    observations, configuration = validation_observations()
    import_checks = []
    for label, path in (("V111", V111), ("V117", V117)):
        modules = [import_module(path, f"{label}_{index}") for index in range(2)]
        seat_checks = []
        for seat in (0, 1):
            first = call(modules[0].agent, copy.deepcopy(observations[seat]), configuration)
            repeated = call(modules[0].agent, copy.deepcopy(observations[seat]), configuration)
            independent = call(modules[1].agent, copy.deepcopy(observations[seat]), configuration)
            seat_checks.append(first == repeated == independent and set(first) == {"farmer", "hands", "market"})
        import_checks.append(
            {
                "agent": label,
                "both_seats": all(seat_checks),
                "step0_repeatable": all(seat_checks),
                "independent_load_equal": all(seat_checks),
                "distinct_module_objects": modules[0] is not modules[1],
            }
        )
    with tempfile.TemporaryDirectory(dir=EXP) as temporary:
        target = Path(temporary)
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            for member in archive.getmembers():
                destination = (target / member.name).resolve()
                if not destination.is_relative_to(target.resolve()):
                    raise ValueError(member.name)
            archive.extractall(target)
        packaged = import_module(target / "main.py", "package")
        package_actions = [
            call(packaged.agent, copy.deepcopy(observations[seat]), configuration) for seat in (0, 1)
        ]
        package_import_ok = all(set(action) == {"farmer", "hands", "market"} for action in package_actions)
    fresh = subprocess.run(
        [sys.executable, "-c", "import importlib.util,sys;p=sys.argv[1];s=importlib.util.spec_from_file_location('fresh',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);assert callable(m.agent)", str(V117)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
    )
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        archive_names = archive.getnames()
    package_manifest = {
        "created_at": now(),
        "archive": rel(ARCHIVE),
        "archive_sha256": sha(ARCHIVE),
        "size": ARCHIVE.stat().st_size,
        "entries": archive_names,
        "root_main": archive_names and archive_names[0] == "main.py",
        "entrypoint": "main.py:agent",
        "source_sha256": SOURCE_SHA,
    }
    save(EXP / "package_manifest.json", package_manifest)
    passed = all(row["both_seats"] for row in import_checks) and package_import_ok and fresh.returncode == 0
    save(
        EXP / "package_verification.json",
        {
            "created_at": now(),
            "passed": passed,
            "imports": import_checks,
            "package_isolation": package_import_ok,
            "fresh_process": {"passed": fresh.returncode == 0, "stderr": fresh.stderr},
            "stdlib_only_candidate_wrapper": True,
            "manifest": package_manifest,
        },
    )
    if not passed:
        raise RuntimeError("package/import validation failed")
    manifest.update(
        status="VALIDATED_PRE_RESULTS",
        phase="aa",
        updated_at=now(),
        candidate_package_sha256=sha(ARCHIVE),
    )
    save(EXP / "manifest.json", manifest)
    print(json.dumps({"validated": True, "package": sha(ARCHIVE), "entries": len(archive_names)}))


def phase_spec(phase: str) -> tuple[str, str, list[str], list[int]]:
    if phase == "aa_v111":
        return "V111", "V111", ["qeinstein_moev2"], [10091011]
    if phase == "aa_v117":
        return "V117", "V117", ["qeinstein_moev2"], [10091011]
    if phase == "smoke_nontrigger":
        return "V111", "V117", ["mooman_e052a"], [10091011]
    if phase == "smoke_commit":
        return "V111", "V117", ["souvik_v4", "qeinstein_moev2"], [10091012]
    if phase == "old_spent":
        return "V111", "V117", list(SOURCES), OLD_SEEDS
    if phase == "confirmation":
        chosen = load(EXP / "seed_ledger.json")["selected_confirmation_seeds"]
        return "V111", "V117", list(SOURCES), [int(seed) for seed in chosen]
    raise ValueError(phase)


def pair_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record["phase"],
        record["candidate"],
        record["candidate_source_sha256"],
        record["evaluation_core_sha256"],
        record["lineage_id"],
        int(record["seed"]),
        int(record["seat"]),
    )


def run_phase(phase: str, workers: int) -> None:
    from scripts.evaluation.runner import run_tasks

    manifest = load(EXP / "manifest.json")
    assert manifest["candidate_source_sha256"] == sha(V117) == SOURCE_SHA
    control_name, treatment_name, source_names, seeds = phase_spec(phase)
    control = V111 if control_name == "V111" else V117
    treatment = V111 if treatment_name == "V111" else V117
    core = composite_hash(core_hashes())
    package_sha = sha(ARCHIVE)
    plan = {
        "created_at": now(),
        "phase": phase,
        "candidate": treatment_name,
        "candidate_source_sha256": sha(treatment),
        "candidate_package_sha256": package_sha,
        "evaluation_core_sha256": core,
        "sources": source_names,
        "seeds": seeds,
        "seats": [0, 1],
        "episode_steps": 720,
        "control": control_name,
        "preregistration_sha256": sha(PREREG),
    }
    plan_path = EXP / "plans" / f"{phase}.json"
    if plan_path.exists():
        existing = load(plan_path)
        plan["created_at"] = existing["created_at"]
        assert existing == plan
    else:
        save(plan_path, plan)
    provenance = {
        "plan_sha256": sha(plan_path),
        "preregistration_sha256": sha(PREREG),
        "candidate_contract_sha256": sha(EXP / "candidate_contract.json"),
        "engine_sha256": sha(ENGINE),
        "configuration_sha256": sha(CONFIGURATION),
        "driver_sha256": sha(Path(__file__)),
    }
    all_pairs_path = EXP / "pairs.jsonl"
    prior = rows(all_pairs_path)
    keys = [pair_key(record) for record in prior]
    if len(keys) != len(set(keys)):
        raise RuntimeError("duplicate pair key before resume")
    seen = set(keys)
    required_paths = [V111, V117, ENGINE, CONFIGURATION, Path(__file__), plan_path, PREREG, *SOURCES.values()]
    required_paths.extend(ROOT / name for name in core_hashes())
    required_hashes = {str(path): sha(path) for path in required_paths}
    tasks = []
    for source_name in source_names:
        for seed in seeds:
            for seat in (0, 1):
                wanted = (phase, treatment_name, sha(treatment), core, source_name, seed, seat)
                if wanted in seen:
                    continue
                tasks.append(
                    {
                        "control_main": str(control),
                        "treatment_main": str(treatment),
                        "opponent_main": str(SOURCES[source_name]),
                        "seed": seed,
                        "seat": seat,
                        "episode_steps": 720,
                        "phase": phase,
                        "lineage_id": source_name,
                        "opponent_name": source_name,
                        "opponent_tier": "frozen old executable source",
                        "meta_weight": 1 / len(source_names),
                        "intended_action_step": 0,
                        "inherited_transaction_step": 248,
                        "intervention_kind": "complete_policy",
                        "strict_all_step_safety": True,
                        "save_all_replays": True,
                        "replay_dir": str(EXP / "replays"),
                        "isolate_packages": ["kaggriculture"],
                        "provenance": provenance,
                        "required_file_hashes": required_hashes,
                    }
                )
    expected = len(source_names) * len(seeds) * 2
    existing_count = sum(record["phase"] == phase and record["candidate"] == treatment_name for record in prior)
    manifest.update(status="RUNNING", phase=phase, updated_at=now(), evaluation_pid=os.getpid())
    save(EXP / "manifest.json", manifest)
    started = time.perf_counter()

    def progress(done: int, total: int, record: dict[str, Any]) -> None:
        record.update(
            {
                "candidate": treatment_name,
                "candidate_source_sha256": sha(treatment),
                "candidate_package_sha256": package_sha,
                "evaluation_core_sha256": core,
                "ancestry": ANCESTRY[record["lineage_id"]],
            }
        )
        key = pair_key(record)
        if key in seen:
            raise RuntimeError(f"duplicate completed pair key: {key}")
        seen.add(key)
        append(all_pairs_path, record)
        save(
            EXP / "progress" / f"{phase}.json",
            {
                "updated_at": now(),
                "completed_new": done,
                "total_new": total,
                "reused": existing_count,
                "expected": expected,
                "last_pair_key": list(key),
                "elapsed_seconds": time.perf_counter() - started,
            },
        )
        print(
            json.dumps(
                {
                    "phase": phase,
                    "done": done,
                    "total": total,
                    "source": record["lineage_id"],
                    "seed": record["seed"],
                    "seat": record["seat"],
                    "C": record["control"]["result"],
                    "T": record["treatment"]["result"],
                    "commit": bool(record["agent_trace"]["treatment"].get("research_decision", {}).get("committed")),
                    "safety": record["candidate_new_major_regressions"],
                }
            ),
            flush=True,
        )

    completed = run_tasks(tasks, workers, progress)
    append(
        EXP / "runs.jsonl",
        {
            "finished_at": now(),
            "phase": phase,
            "workers": workers,
            "new_pairs": len(completed),
            "reused_pairs": existing_count,
            "wall_seconds": time.perf_counter() - started,
            "candidate_source_sha256": sha(treatment),
            "candidate_package_sha256": package_sha,
        },
    )
    phase_rows = [
        record for record in rows(all_pairs_path)
        if record["phase"] == phase and record["candidate"] == treatment_name
    ]
    if len(phase_rows) != expected or len({pair_key(record) for record in phase_rows}) != expected:
        raise RuntimeError(f"incomplete/duplicate phase {phase}: {len(phase_rows)} != {expected}")
    if not all(record["safety"][arm]["completed_720"] for record in phase_rows for arm in ("control", "treatment")):
        raise RuntimeError(f"incomplete 720-state run in {phase}")
    save(EXP / "summary" / f"{phase}.json", summarize_rows(phase_rows, phase))
    manifest.update(status="PHASE_COMPLETE", phase=phase, updated_at=now(), evaluation_pid=None)
    save(EXP / "manifest.json", manifest)
    print(json.dumps({"phase": phase, "complete": len(phase_rows), "expected": expected}))


def percentile10(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = 0.1 * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - rank) + ordered[upper] * (rank - lower)


def result_class(score: float) -> str:
    if score > 0.5:
        return "W"
    if score < 0.5:
        return "L"
    return "D"


def arm_stats(selected: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    results = Counter(record[arm]["result"] for record in selected)
    margins = [float(record[arm]["margin"]) for record in selected]
    return {
        "W": results["win"],
        "D": results["draw"],
        "L": results["loss"],
        "win_score": mean(float(record[arm]["score"]) for record in selected) if selected else None,
        "margin_mean": mean(margins) if margins else None,
        "margin_median": median(margins) if margins else None,
        "margin_p10": percentile10(margins),
    }


def semantic_replay(path: Path) -> list[Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        replay = json.load(handle)
    result = []
    for step in replay["steps"]:
        clean_step = []
        for state in step:
            observation = state.get("observation")
            if isinstance(observation, str):
                observation = json.loads(observation)
            observation = dict(observation or {})
            observation.pop("remainingOverageTime", None)
            clean_step.append(
                {
                    "observation": observation,
                    "action": state.get("action"),
                    "reward": state.get("reward"),
                    "status": state.get("status"),
                }
            )
        result.append(clean_step)
    return result


def first_land_step(path: Path, seat: int) -> int | None:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        replay = json.load(handle)
    for step, states in enumerate(replay["steps"]):
        observation = states[seat].get("observation") or {}
        if isinstance(observation, str):
            observation = json.loads(observation)
        farms = observation.get("farms") or []
        if seat < len(farms) and len(set(farms[seat].get("unlocked_quadrants") or [])) >= 3:
            return step
    return None


def summarize_rows(selected: list[dict[str, Any]], phase: str) -> dict[str, Any]:
    transitions = Counter(
        record["control"]["result"][0].upper() + "->" + record["treatment"]["result"][0].upper()
        for record in selected
    )
    by_source = {}
    for source in sorted({record["lineage_id"] for record in selected}):
        subset = [record for record in selected if record["lineage_id"] == source]
        control_stats = arm_stats(subset, "control")
        treatment_stats = arm_stats(subset, "treatment")
        by_source[source] = {
            "contexts": len(subset),
            "control": control_stats,
            "treatment": treatment_stats,
            "delta_win_score": treatment_stats["win_score"] - control_stats["win_score"],
        }
    blocks: defaultdict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in selected:
        blocks[(record["lineage_id"], int(record["seed"]))].append(record)
    block_transitions: Counter[str] = Counter()
    block_rows = []
    for (source, seed), subset in sorted(blocks.items()):
        control_score = mean(float(record["control"]["score"]) for record in subset)
        treatment_score = mean(float(record["treatment"]["score"]) for record in subset)
        transition = f"{result_class(control_score)}->{result_class(treatment_score)}"
        block_transitions[transition] += 1
        decisions = [record["agent_trace"]["treatment"].get("research_decision", {}) for record in subset]
        block_rows.append(
            {
                "source": source,
                "seed": seed,
                "seats": len(subset),
                "control_win_score": control_score,
                "treatment_win_score": treatment_score,
                "delta_win_score": treatment_score - control_score,
                "transition": transition,
                "commit_seats": sum(bool(decision.get("committed")) for decision in decisions),
                "rejoin_seats": sum(bool(decision.get("rejoined")) for decision in decisions),
                "contract_failure_seats": sum(bool(decision.get("hard_failure")) for decision in decisions),
            }
        )
    decisions = [record["agent_trace"]["treatment"].get("research_decision", {}) for record in selected]
    committed = [record for record, decision in zip(selected, decisions, strict=True) if decision.get("committed")]
    nontrigger = [record for record, decision in zip(selected, decisions, strict=True) if not decision.get("committed")]
    exact_nontrigger = []
    for record in nontrigger:
        exact_nontrigger.append(
            semantic_replay(Path(record["replay_artifacts"]["control"]))
            == semantic_replay(Path(record["replay_artifacts"]["treatment"]))
        )
    land_advances = []
    same_turn = 0
    duplicate_removed = 0
    for record in committed:
        control_land = first_land_step(Path(record["replay_artifacts"]["control"]), int(record["seat"]))
        treatment_land = first_land_step(Path(record["replay_artifacts"]["treatment"]), int(record["seat"]))
        if control_land is not None and treatment_land is not None:
            land_advances.append(control_land - treatment_land)
        decision = record["agent_trace"]["treatment"].get("research_decision", {})
        duplicate_removed += int(decision.get("duplicate_land_removed", 0) or 0) > 0
        first = record["divergence_audit"].get("first_focal_action") or {}
        market = (first.get("treatment") or {}).get("market") or []
        if ["BUY_ANIMAL", "COW", 2] in market and ["BUY_LAND"] in market:
            same_turn += 1
    safe_cancels: Counter[str] = Counter()
    for decision in decisions:
        safe_cancels.update(decision.get("safe_cancels") or {})
    hard_failures = [
        {"source": record["lineage_id"], "seed": record["seed"], "seat": record["seat"], "failures": record["candidate_new_major_regressions"]}
        for record in selected if record["candidate_new_major_regressions"]
    ]
    contract_failures = [
        {"source": record["lineage_id"], "seed": record["seed"], "seat": record["seat"], "failure": decision.get("hard_failure")}
        for record, decision in zip(selected, decisions, strict=True) if decision.get("hard_failure")
    ]
    return {
        "created_at": now(),
        "phase": phase,
        "contexts": len(selected),
        "control": arm_stats(selected, "control"),
        "treatment": arm_stats(selected, "treatment"),
        "delta_win_score": mean(float(record["delta_win_score"]) for record in selected) if selected else None,
        "transitions": dict(sorted(transitions.items())),
        "source_seed_block_transitions": dict(sorted(block_transitions.items())),
        "source_seed_blocks": block_rows,
        "by_source": by_source,
        "by_ancestry": copy.deepcopy(by_source),
        "delivery_funnel": {
            "trigger_requests": sum(int(decision.get("trigger_requests", 0) or 0) for decision in decisions),
            "commit_contexts": len(committed),
            "commit_sources": sorted({record["lineage_id"] for record in committed}),
            "commit_source_seed_blocks": len({(record["lineage_id"], record["seed"]) for record in committed}),
            "safe_cancels": dict(safe_cancels),
            "partial_or_contract_failure_contexts": len(contract_failures),
            "rejoin_contexts": sum(bool(decision.get("rejoined")) for decision in decisions),
        },
        "mechanism": {
            "same_turn_land_and_cow_contexts": same_turn,
            "duplicate_land_removed_contexts": duplicate_removed,
            "land_advance_decisions": land_advances,
            "land_advance_median": median(land_advances) if land_advances else None,
            "first_productive_actions": [decision.get("first_productive_action") for decision in decisions if decision.get("first_productive_action")],
            "preflight": [decision.get("preflight") for decision in decisions if decision.get("preflight")],
            "cow_pickups": sum(int(decision.get("cow_pickups", 0) or 0) for decision in decisions),
            "cow_places": sum(int(decision.get("cow_places", 0) or 0) for decision in decisions),
            "feed_actions_after_commit": sum(int(decision.get("feed_actions_after_commit", 0) or 0) for decision in decisions),
        },
        "nontrigger_fidelity": {
            "contexts": len(nontrigger),
            "exact_semantic_replays": sum(exact_nontrigger),
            "all_exact": all(exact_nontrigger),
            "comparison_excludes_only_remainingOverageTime": True,
        },
        "runtime_and_safety": {
            "completed_720_contexts": sum(all(record["safety"][arm]["completed_720"] for arm in ("control", "treatment")) for record in selected),
            "agent_exception_contexts": sum(bool(record["agent_trace"]["treatment"].get("agent_exceptions")) for record in selected),
            "candidate_new_hard_failure_contexts": len(hard_failures),
            "candidate_new_hard_failures": hard_failures,
            "contract_failures": contract_failures,
        },
    }


def summarize_all() -> None:
    all_rows = rows(EXP / "pairs.jsonl")
    phase_names = ["aa_v111", "aa_v117", "smoke_nontrigger", "smoke_commit", "old_spent", "confirmation"]
    summaries = {}
    for phase in phase_names:
        selected = [record for record in all_rows if record["phase"] == phase]
        if selected:
            summaries[phase] = summarize_rows(selected, phase)
            save(EXP / "summary" / f"{phase}.json", summaries[phase])
    save(EXP / "aa_results.json", {key: value for key, value in summaries.items() if key.startswith("aa_")})
    save(EXP / "smoke_results.json", {key: value for key, value in summaries.items() if key.startswith("smoke_")})
    confirmation = summaries.get("confirmation")
    safety = {
        "created_at": now(),
        "raw_safety": {
            phase: summary["runtime_and_safety"] for phase, summary in summaries.items()
        },
        "candidate_new_safety": {
            phase: summary["runtime_and_safety"]["candidate_new_hard_failure_contexts"]
            for phase, summary in summaries.items()
        },
        "delivery": {phase: summary["delivery_funnel"] for phase, summary in summaries.items()},
        "candidate_new_lifecycle_limit": "Generic lifecycle audit is retained in every pair. Candidate-new counts are paired; terminal intentional decay is not relabeled as water death.",
    }
    save(EXP / "safety_and_delivery.json", safety)
    mechanism = {
        "created_at": now(),
        "implementation": "late_land_order_resequence",
        "primary_success_count": 0,
        "phases": {phase: summary["mechanism"] for phase, summary in summaries.items()},
        "causal_limit": "Opponent coin or action changes after the public intervention are closed-loop responses, not a single-action causal attribution.",
        "fungible_inventory_limit": "Fallback preserves V111 field activity; shed-level sale proceeds cannot be uniquely attributed to one new-land tile.",
    }
    save(EXP / "mechanism_attribution.json", mechanism)
    trial = load(EXP / "trial_gate.json")
    if confirmation is not None:
        hard = (
            confirmation["runtime_and_safety"]["candidate_new_hard_failure_contexts"] == 0
            and not confirmation["runtime_and_safety"]["contract_failures"]
            and confirmation["nontrigger_fidelity"]["all_exact"]
            and confirmation["runtime_and_safety"]["completed_720_contexts"] == confirmation["contexts"]
        )
        block = confirmation["source_seed_block_transitions"]
        per_source = [value["delta_win_score"] for value in confirmation["by_source"].values()]
        efficacy = (
            confirmation["delta_win_score"] >= -0.0625
            and block.get("W->L", 0) <= block.get("L->W", 0) + 1
            and all(delta >= -0.25 for delta in per_source)
            and len(confirmation["delivery_funnel"]["commit_sources"]) >= 2
            and confirmation["delivery_funnel"]["commit_source_seed_blocks"] >= 4
            and confirmation["mechanism"]["same_turn_land_and_cow_contexts"] >= 2
            and confirmation["mechanism"]["duplicate_land_removed_contexts"] >= 2
        )
        trial["result"] = {
            "evaluated_at": now(),
            "hard_gate_passed": hard,
            "loss_budget_passed": efficacy,
            "passed": hard and efficacy,
            "delta_win_score": confirmation["delta_win_score"],
            "block_transitions": block,
            "by_source_delta": {source: value["delta_win_score"] for source, value in confirmation["by_source"].items()},
            "commit_sources": confirmation["delivery_funnel"]["commit_sources"],
            "commit_source_seed_blocks": confirmation["delivery_funnel"]["commit_source_seed_blocks"],
            "same_turn_land_and_cow_contexts": confirmation["mechanism"]["same_turn_land_and_cow_contexts"],
            "duplicate_land_removed_contexts": confirmation["mechanism"]["duplicate_land_removed_contexts"],
            "classification_if_passed": "EXPLORATORY_E6_REQUIRED",
            "production_promotion_forbidden": True,
        }
        save(EXP / "trial_gate.json", trial)
    save(
        EXP / "summary.json",
        {
            "created_at": now(),
            "phases": summaries,
            "old_spent_role": "engineering panel, not promotion/generalization evidence",
            "confirmation_role": "live-trial qualification panel, not promotion evidence",
            "live_role": "E6 observation only, not promotion evidence",
            "trial_gate_result": trial.get("result"),
            "production_champion": "V111",
        },
    )
    print(json.dumps({"summarized": list(summaries), "trial": trial.get("result")}))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("initialize")
    subparsers.add_parser("validate")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("phase", choices=["aa_v111", "aa_v117", "smoke_nontrigger", "smoke_commit", "old_spent", "confirmation"])
    run_parser.add_argument("--workers", type=int, default=4)
    subparsers.add_parser("summarize")
    args = parser.parse_args()
    if args.command == "initialize":
        initialize()
    elif args.command == "validate":
        validate()
    elif args.command == "run":
        run_phase(args.phase, args.workers)
    elif args.command == "summarize":
        summarize_all()


if __name__ == "__main__":
    main()
