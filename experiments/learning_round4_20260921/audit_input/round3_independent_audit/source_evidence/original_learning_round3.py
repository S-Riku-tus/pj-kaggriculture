# ruff: noqa: E501
"""Reproducible Round3 audit, packaging, decomposition, and small evaluation."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_round3_20260921.market import PRODUCTS, simulate_market  # noqa: E402

STUDY_ID = "learning_round3_20260921"
EXPERIMENT = ROOT / "experiments" / STUDY_ID
AGENT = ROOT / "agents" / STUDY_ID
ARCHIVES = ROOT / "artifacts" / "submissions"
RUNTIME = EXPERIMENT / "runtime"
C0_ARCHIVE = ARCHIVES / "v126_control_candidate.tar.gz"
SUCCESS_ARCHIVE = ARCHIVES / "learning_next_20260921_b_learned_fixed_v3.tar.gz"
AUDIT_ZIP = Path("C:/Users/shiba/Downloads/Kaggriculture_Round2_Audit_Evidence_20260921.zip")
EXPECTED_AUDIT_SHA256 = "cd94e3ade1a7bd0072e7e7db688ee32685059d0fc66be62acb93fbe7d3a57220"
EXPECTED_SUCCESS_SHA256 = "f1aede2a9f4a8ad0b8f3b3cd41d1f49708b713ca1cbc4221df472dcba1201105"
ENGINE_SHA256 = "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e"
GAME_CONFIGURATION = {"episodeSteps": 720}
OPPONENTS = {
    "qeinstein_moev2": ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py",
    "mooman_e052a": ROOT / "experiments/research_20260910/runtime/mooman_e052a/main.py",
    "smart_farm": ROOT / "experiments/research_20260918_v120/acquisition/smart_farm/decoded_main_1.py",
    "souvik_v4": ROOT / "experiments/research_20260910/runtime/souvik_v4/main.py",
    "robriculture_lean_feed": ROOT / "experiments/research_20260911_continuations/runtime/robriculture_lean_feed/main.py",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def safe_extract_tar(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=False)
    root = target.resolve()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            if not (target / member.name).resolve().is_relative_to(root):
                raise ValueError(member.name)
        stream.extractall(target)


def safe_extract_zip(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=False)
    root = target.resolve()
    with zipfile.ZipFile(archive) as stream:
        for member in stream.infolist():
            if not (target / member.filename).resolve().is_relative_to(root):
                raise ValueError(member.filename)
        stream.extractall(target)


def tree_digest(files: Sequence[Path]) -> dict[str, Any]:
    rows = []
    combined = hashlib.sha256()
    for path in sorted({path.resolve() for path in files if path.is_file()}, key=lambda value: str(value).lower()):
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            relative = str(path)
        digest = sha256(path)
        size = path.stat().st_size
        rows.append({"path": relative, "bytes": size, "sha256": digest})
        combined.update(relative.encode())
        combined.update(b"\0")
        combined.update(digest.encode())
        combined.update(b"\n")
    return {"sha256": combined.hexdigest(), "file_count": len(rows), "bytes": sum(row["bytes"] for row in rows), "files": rows}


def git_source_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    include_roots = ("agents/", "scripts/", "tests/")
    include_names = {"pyproject.toml", "uv.lock", "README.md", "AGENTS.md"}
    return [ROOT / line for line in completed.stdout.splitlines() if line.startswith(include_roots) or line in include_names]


def make_source_and_model_manifest() -> dict[str, Any]:
    import kaggle_environments
    import kaggle_environments.agent as loader_module
    from kaggle_environments.envs.kaggriculture import kaggriculture as engine

    sources = tree_digest(git_source_files())
    model_files = []
    config_files = []
    for base in (ROOT / "agents", ROOT / "experiments/learning_next_20260921", ROOT / "experiments/learning_round2_20260921"):
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            lower = path.name.lower()
            if lower.endswith((".npz", ".pkl", ".json.gz")) or "model" in lower:
                model_files.append(path)
            if lower.endswith(".json") and any(token in lower for token in ("config", "schema", "manifest")):
                config_files.append(path)
    opponents = {}
    for name, path in OPPONENTS.items():
        opponents[name] = {
            "path": str(path.relative_to(ROOT)) if path.exists() else str(path),
            "exists": path.is_file(),
            "sha256": sha256(path) if path.is_file() else None,
            "public_identity_claim": "local executable proxy; not the private current top agent",
        }
    round3_archives = {
        path.name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
        for path in sorted(ARCHIVES.glob(f"{STUDY_ID}*.tar.gz"))
    }
    return {
        "created_at_utc": utc_now(),
        "study_id": STUDY_ID,
        "source_tree": sources,
        "models": tree_digest(model_files),
        "configs_and_feature_schemas": tree_digest(config_files),
        "engine": {
            "package": f"kaggle-environments=={kaggle_environments.__version__}",
            "path": str(Path(engine.__file__).resolve()),
            "sha256": sha256(Path(engine.__file__).resolve()),
            "expected_sha256": ENGINE_SHA256,
        },
        "loader": {
            "path": str(Path(loader_module.__file__).resolve()),
            "function": "kaggle_environments.agent.get_last_callable",
        },
        "opponents": opponents,
        "archives": {
            "c0": {"path": str(C0_ARCHIVE.relative_to(ROOT)), "sha256": sha256(C0_ARCHIVE)},
            "known_success_fixed_v3": {
                "path": str(SUCCESS_ARCHIVE.relative_to(ROOT)),
                "sha256": sha256(SUCCESS_ARCHIVE),
                "expected_sha256": EXPECTED_SUCCESS_SHA256,
                "matches": sha256(SUCCESS_ARCHIVE) == EXPECTED_SUCCESS_SHA256,
            },
            "round3": round3_archives,
        },
        "model_output_formats": {
            "A2": "NPZ float arrays; rejected for submission and OOD behavior",
            "B2": "NPZ MLP outputs weighted-BCE raw sigmoid plus all-row log1p regression; rejected",
            "Round3_runtime": "standard-library JSON only; no NumPy import",
        },
        "executor_version": "round3-contract-executor-v1",
        "round3_evidence_tree": tree_digest(
            [
                *AGENT.glob("*.py"),
                ROOT / "scripts/learning_round3.py",
                ROOT / "scripts/round3_loader_probe.py",
                ROOT / "tests/test_learning_round3.py",
                EXPERIMENT / "ROUND3_PLAN.md",
                *(EXPERIMENT / "REGRESSION_CASES").glob("*.json"),
            ]
        ),
    }


def command_init() -> None:
    EXPERIMENT.mkdir(parents=True, exist_ok=True)
    observed = sha256(AUDIT_ZIP)
    quarantine = EXPERIMENT / "quarantine" / f"audit_input_{observed[:12]}"
    if not quarantine.exists():
        safe_extract_zip(AUDIT_ZIP, quarantine)
    input_record = {
        "path": str(AUDIT_ZIP),
        "bytes": AUDIT_ZIP.stat().st_size,
        "expected_sha256": EXPECTED_AUDIT_SHA256,
        "observed_sha256": observed,
        "hash_matches": observed == EXPECTED_AUDIT_SHA256,
        "disposition": "ACCEPTED" if observed == EXPECTED_AUDIT_SHA256 else "QUARANTINED_INPUT_HASH_MISMATCH_READ_ONLY",
        "extracted_to": str(quarantine.relative_to(ROOT)),
    }
    write_json(EXPERIMENT / "audit_input_validation.json", input_record)
    write_json(EXPERIMENT / "SOURCE_AND_MODEL_MANIFEST.json", make_source_and_model_manifest())
    environment = {
        "created_at_utc": utc_now(),
        "python": sys.version,
        "logical_cpus": os.cpu_count(),
        "numpy": np.__version__,
        "worker_limit": 2,
        "worker_reason": "conservative after prior multi-worker slowdown; measured before expansion",
    }
    try:
        import psutil

        environment.update({"ram_total_bytes": psutil.virtual_memory().total, "ram_available_bytes": psutil.virtual_memory().available})
    except ImportError:
        pass
    write_json(EXPERIMENT / "environment.json", environment)
    print(json.dumps({"study_id": STUDY_ID, "audit_input": input_record, "manifest": "written"}, ensure_ascii=False))


def command_package_control() -> None:
    target = ARCHIVES / f"{STUDY_ID}_c0_identity.tar.gz"
    shutil.copy2(C0_ARCHIVE, target)
    result = {
        "created_at_utc": utc_now(),
        "source": str(C0_ARCHIVE.relative_to(ROOT)),
        "source_sha256": sha256(C0_ARCHIVE),
        "artifact": str(target.relative_to(ROOT)),
        "artifact_sha256": sha256(target),
        "byte_identical": sha256(target) == sha256(C0_ARCHIVE),
    }
    write_json(EXPERIMENT / "c0_identity_package.json", result)
    print(json.dumps(result))


def command_validate_loader() -> None:
    artifact = ARCHIVES / f"{STUDY_ID}_c0_identity.tar.gz"
    if not artifact.is_file():
        command_package_control()
    extraction_root = ROOT.parent / f"round3_loader_validation_{os.getpid()}"
    extracted = extraction_root / "archive"
    if extraction_root.exists():
        raise FileExistsError(extraction_root)
    extracted.mkdir(parents=True)
    subprocess.run(["tar", "-xf", str(artifact), "-C", str(extracted)], check=True, timeout=60)
    command = [
        sys.executable,
        str(ROOT / "scripts/round3_loader_probe.py"),
        str(artifact),
        "--full-game",
        "--extracted-dir",
        str(extracted),
    ]
    completed = subprocess.run(command, cwd=ROOT.parent, text=True, capture_output=True, timeout=300, check=False)
    stdout_lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    if completed.returncode or not stdout_lines:
        raise RuntimeError({"exit_code": completed.returncode, "stdout": completed.stdout[-4000:], "stderr": completed.stderr[-4000:]})
    probe = json.loads(stdout_lines[-1])
    probe.update({
        "source_c0_sha256": sha256(C0_ARCHIVE),
        "c0_identity_preserved": sha256(artifact) == sha256(C0_ARCHIVE),
        "known_success_fixed_v3_found": SUCCESS_ARCHIVE.is_file(),
        "known_success_fixed_v3_sha256": sha256(SUCCESS_ARCHIVE) if SUCCESS_ARCHIVE.is_file() else None,
        "known_success_fixed_v3_matches": SUCCESS_ARCHIVE.is_file() and sha256(SUCCESS_ARCHIVE) == EXPECTED_SUCCESS_SHA256,
        "model_conversion": {"applicable": False, "reason": "C0 identity artifact has no newly converted learned model"},
        "full_720_game_attempt": {
            "attempted": True,
            "result": "PASS" if probe.get("stored_states") == 720 and probe.get("passed") else "FAIL",
            "terminal_statuses_confirmed": probe.get("terminal_statuses") == ["DONE", "DONE"],
            "extraction_note": "an earlier attempt timed out inside Python tarfile.extractall before loader execution; the recorded run uses OS tar extraction of the same hash",
        },
        "stderr_tail": completed.stderr[-2000:],
    })
    write_json(EXPERIMENT / "LOADER_VALIDATION.json", probe)
    print(json.dumps(probe, ensure_ascii=False))


def command_validate_probe_loader() -> None:
    """Validate the most advanced rejected probe through the official loader."""

    archive = ARCHIVES / f"{STUDY_ID}_a3_feed_once_replan_probe.tar.gz"
    if not archive.is_file():
        _prepare_probe_runtimes()
    extraction_root = ROOT.parent / f"round3_probe_loader_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    extracted = extraction_root / "archive"
    extracted.mkdir(parents=True)
    subprocess.run(["tar", "-xf", str(archive), "-C", str(extracted)], check=True, timeout=60)
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/round3_loader_probe.py"),
            str(archive),
            "--extracted-dir",
            str(extracted),
        ],
        cwd=ROOT.parent,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    stdout_lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    if completed.returncode or not stdout_lines:
        raise RuntimeError({"exit_code": completed.returncode, "stdout": completed.stdout[-4000:], "stderr": completed.stderr[-4000:]})
    result = json.loads(stdout_lines[-1])
    result.update(
        {
            "candidate_verdict": "REJECTED_DEVELOPMENT_NEGATIVE",
            "not_a_submission_candidate": True,
            "closed_loop_evidence": str((EXPERIMENT / "p3_paired_development/paired_summary.json").relative_to(ROOT)),
            "full_game_via_direct_runner": True,
            "full_game_via_official_loader": False,
            "official_loader_scope": "archive execution, last-callable assertion, and real 4-state runner smoke test",
            "stderr_tail": completed.stderr[-2000:],
        }
    )
    write_json(EXPERIMENT / "P3_PROBE_LOADER_VALIDATION.json", result)
    print(json.dumps(result, ensure_ascii=False))


def replay_task_digest(task: Mapping[str, Any]) -> str:
    payload = {
        "version": "round3-task-digest-v1",
        "agent_archive_sha256": task["agent_archive_sha256"],
        "agent_source_tree_sha256": task["agent_source_tree_sha256"],
        "model_hashes": task.get("model_hashes", {}),
        "config_hash": json_hash(task["configuration"]),
        "feature_schema_sha256": task.get("feature_schema_sha256"),
        "executor_version": task["executor_version"],
        "engine_sha256": task["engine_sha256"],
        "opponent_tree_sha256": task["opponent_tree_sha256"],
        "seed": int(task["seed"]),
        "seat": int(task["seat"]),
    }
    return json_hash(payload)


def reusable_replay(task: Mapping[str, Any], replay_path: Path, sidecar_path: Path) -> tuple[bool, str]:
    if not replay_path.is_file():
        return False, "REPLAY_MISSING"
    if not sidecar_path.is_file():
        return False, "SIDECAR_MISSING"
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "SIDECAR_INVALID"
    if sidecar.get("task_digest") != replay_task_digest(task):
        return False, "TASK_DIGEST_MISMATCH"
    if sidecar.get("replay_sha256") != sha256(replay_path):
        return False, "REPLAY_HASH_MISMATCH"
    if int(sidecar.get("seed", -1)) != int(task["seed"]) or int(sidecar.get("seat", -1)) != int(task["seat"]):
        return False, "SEED_OR_SEAT_MISMATCH"
    if sidecar.get("terminal_statuses") != ["DONE", "DONE"]:
        return False, "TERMINAL_STATUS_INVALID"
    if int(sidecar.get("stored_states", 0)) != int(task["configuration"].get("episodeSteps", 720)):
        return False, "STATE_COUNT_INVALID"
    return True, "VALID"


def _read_replay(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _load_module(path: Path, label: str) -> Any:
    generic = ("common", "learning_common", "market")
    cached = {name: sys.modules.pop(name) for name in generic if name in sys.modules}
    parent = str(path.parent)
    sys.path.insert(0, parent)
    try:
        spec = importlib.util.spec_from_file_location(f"_r3_{label}_{uuid.uuid4().hex}", path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "reset_runtime_state"):
            module.reset_runtime_state()
        return module
    finally:
        if sys.path and sys.path[0] == parent:
            sys.path.pop(0)
        for name in generic:
            sys.modules.pop(name, None)
        sys.modules.update(cached)


def _player_state(observation: Mapping[str, Any], private: Mapping[str, Any], seat: int) -> dict[str, Any]:
    farm = observation["farms"][seat]
    return {
        "money": int(farm["money"]),
        "shed": dict(private.get("shed") or {}),
        "seeds": dict(private.get("seeds") or {}),
        "hires_today": int(farm.get("hires_today", 0)),
        "hands": len(farm.get("hands") or []),
        "unlocked_land": len(farm.get("unlocked_quadrants") or ["NW"]),
    }


def _old_predicted_orders(prediction: Mapping[tuple[str, int], tuple[float, float]]) -> list[list[Any]]:
    return [["SELL", item, max(1, int(round(prediction[(item, 1)][1])))] for item in PRODUCTS if prediction[(item, 1)][0] >= .25 and prediction[(item, 1)][1] >= .5]


def _fixed_product_oracle(orders: Sequence[Sequence[Any]]) -> list[list[Any]]:
    quantities: Counter[str] = Counter()
    tail = []
    for order in orders:
        if len(order) >= 3 and order[0] == "SELL":
            quantities[str(order[1])] += int(order[2])
        else:
            tail.append(list(order))
    return [["SELL", item, quantities[item]] for item in PRODUCTS if quantities[item] > 0] + tail


def _score_exact(observation: Mapping[str, Any], own_private: Mapping[str, Any], opponent_private: Mapping[str, Any], own_orders: Sequence[Sequence[Any]], opponent_orders: Sequence[Sequence[Any]]) -> tuple[int, int]:
    seat = int(observation["player"])
    own = _player_state(observation, own_private, seat)
    other = _player_state(observation, opponent_private, 1 - seat)
    result = simulate_market(observation["market"]["inventory"], [own, other], [own_orders, opponent_orders])
    cash = [int(row["money"]) for row in result["players"]]
    return cash[0], cash[0] - cash[1]


def command_p2_decomposition() -> None:
    base_dir = ROOT / "experiments/learning_round2_20260921/external_bank/replays"
    runtime_main = ROOT / "experiments/learning_round2_20260921/runtime/b2/main.py"
    rows: list[dict[str, Any]] = []
    for family in ("mooman_e052a", "qeinstein_moev2", "smart_farm", "souvik_v4"):
        for seed in range(2026092421, 2026092425):
            for seat in (0, 1):
                control_replay = _read_replay(base_dir / "c0" / family / f"seed_{seed}_seat_{seat}.json.gz")
                b2_replay = _read_replay(base_dir / "b2" / family / f"seed_{seed}_seat_{seat}.json.gz")
                first = next(index - 1 for index in range(1, 720) if control_replay["steps"][index][seat].get("action") != b2_replay["steps"][index][seat].get("action"))
                observation = dict(control_replay["steps"][first][seat]["observation"])
                observation["player"] = seat
                observation["step"] = first
                own_private = observation["private"]
                opponent_private = control_replay["steps"][first][1 - seat]["observation"]["private"]
                c0_orders = control_replay["steps"][first + 1][seat]["action"]["market"]
                b2_orders = b2_replay["steps"][first + 1][seat]["action"]["market"]
                actual_opponent = control_replay["steps"][first + 1][1 - seat]["action"]["market"]
                candidates = [c0_orders, b2_orders]

                module = _load_module(runtime_main, f"b2_{family}_{seed}_{seat}")
                for index in range(first + 1):
                    obs = dict(control_replay["steps"][index][seat]["observation"])
                    obs.update({"player": seat, "step": index})
                    module.agent(obs, None)
                prediction = module._predict(observation, module._history[seat])
                predicted_orders = _old_predicted_orders(prediction)
                opponent_predicted_private = {"shed": {item: sum(int(order[2]) for order in predicted_orders if order[1] == item) for item in PRODUCTS}, "seeds": {}}
                simple_prediction = {}
                hour = str(int(observation.get("hour", 0)))
                simple = module.SIMPLE["by_hour"].get(hour, module.SIMPLE["global"])
                for item in PRODUCTS:
                    for horizon in module.HORIZONS:
                        cell = simple[item][str(horizon)]
                        simple_prediction[(item, horizon)] = (float(cell["probability"]), float(cell["expected_quantity"]))
                simple_orders = _old_predicted_orders(simple_prediction)
                opponent_simple_private = {"shed": {item: sum(int(order[2]) for order in simple_orders if order[1] == item) for item in PRODUCTS}, "seeds": {}}
                unordered_oracle = _fixed_product_oracle(actual_opponent)

                old_scores = [module.score_sell_candidate(observation, candidate, prediction) for candidate in candidates]
                repaired_scores = [_score_exact(observation, own_private, opponent_predicted_private, candidate, predicted_orders)[0] for candidate in candidates]
                simple_scores = [_score_exact(observation, own_private, opponent_simple_private, candidate, simple_orders)[0] for candidate in candidates]
                unordered_scores = [_score_exact(observation, own_private, opponent_private, candidate, unordered_oracle)[0] for candidate in candidates]
                ordered_cash_margin = [_score_exact(observation, own_private, opponent_private, candidate, actual_opponent) for candidate in candidates]
                ordered_scores = [value[0] for value in ordered_cash_margin]
                def chooser(values: Sequence[float]) -> int:
                    return max(range(len(values)), key=lambda offset: (values[offset], -offset))
                choices = {
                    "current_prediction_current_evaluator": chooser(old_scores),
                    "current_prediction_repaired_evaluator": chooser(repaired_scores),
                    "simple_prediction_repaired_evaluator": chooser(simple_scores),
                    "exact_quantities_unordered_oracle": chooser(unordered_scores),
                    "exact_ordered_oracle_repaired_evaluator": chooser(ordered_scores),
                }
                oracle_choice = choices["exact_ordered_oracle_repaired_evaluator"]
                row: dict[str, Any] = {
                    "opponent_family": family, "seed": seed, "seat": seat, "step": first,
                    "candidate_count": len(candidates), "c0_equals_b2": c0_orders == b2_orders,
                    "ordered_oracle_cash_c0": ordered_scores[0], "ordered_oracle_cash_b2": ordered_scores[1],
                    "ordered_oracle_margin_c0": ordered_cash_margin[0][1], "ordered_oracle_margin_b2": ordered_cash_margin[1][1],
                    "ordered_oracle_headroom": ordered_scores[oracle_choice] - ordered_scores[0],
                }
                for name, choice in choices.items():
                    row[f"choice_{name}"] = choice
                    row[f"regret_{name}"] = ordered_scores[oracle_choice] - ordered_scores[choice]
                rows.append(row)
    write_csv(EXPERIMENT / "ORACLE_HEADROOM_AND_REGRET.csv", rows)
    methods = [key.removeprefix("choice_") for key in rows[0] if key.startswith("choice_")]
    summary = {
        "created_at_utc": utc_now(),
        "conditions": len(rows),
        "all_first_divergences_step264": all(row["step"] == 264 for row in rows),
        "candidate_scope": "the same two SELL-block orders used by C0/B2 at the first divergence",
        "methods": {
            method: {
                "changed": sum(row[f"choice_{method}"] != 0 for row in rows),
                "total_ordered_oracle_regret": sum(row[f"regret_{method}"] for row in rows),
                "mean_ordered_oracle_regret": mean(row[f"regret_{method}"] for row in rows),
            }
            for method in methods
        },
        "ordered_oracle_positive_headroom_conditions": sum(row["ordered_oracle_headroom"] > 0 for row in rows),
        "ordered_oracle_total_headroom": sum(row["ordered_oracle_headroom"] for row in rows),
        "runtime_input_boundary": "opponent private and current/future orders used only for offline oracle columns",
    }
    write_json(EXPERIMENT / "p2_decomposition_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


def _feature_kind(name: str, values: np.ndarray) -> str:
    finite = values[np.isfinite(values)]
    unique = set(float(value) for value in np.unique(finite))
    categorical_name = any(
        token in name
        for token in ("job:", "control_op:", "tile_kind:", "tile_crop:", "tile_animal:")
    ) or name in {"player", "candidate_actor:player"}
    return "binary" if categorical_name and unique.issubset({0.0, 1.0}) else "continuous"


def command_normalization_audit() -> None:
    dataset = ROOT / "experiments/learning_round2_20260921/datasets/a2"
    rows = []
    for path in (dataset / "round1_candidate_results.jsonl", dataset / "round2_candidate_results.jsonl"):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    names = json.loads((ROOT / "experiments/learning_round2_20260921/feature_schema.json").read_text(encoding="utf-8"))["a2"]
    matrix = np.asarray([row["feature"] for row in rows], dtype=np.float64)
    with np.load(ROOT / "experiments/learning_round2_20260921/models/a2_model.npz", allow_pickle=False) as data:
        old_scale = data["scale"].astype(np.float64)
        old_mean = data["mean"].astype(np.float64)
    schema = []
    for index, name in enumerate(names):
        values = matrix[:, index]
        kind = _feature_kind(name, values)
        minimum, maximum = float(np.nanmin(values)), float(np.nanmax(values))
        constant = minimum == maximum
        if kind == "binary":
            typed_scale = None
            policy = "raw_0_or_1; unseen constant value is OOD, never divide by tiny std"
        else:
            p05, p95 = np.nanpercentile(values, [5, 95])
            typed_scale = max(float((p95 - p05) / 2.0), 0.1)
            policy = "center by training mean and divide by robust semantic scale; reject outside recorded support"
        schema.append({
            "index": index,
            "name": name,
            "kind": kind,
            "mean": float(values.mean()),
            "minimum": minimum,
            "maximum": maximum,
            "constant": constant,
            "constant_value": minimum if constant else None,
            "old_mean": float(old_mean[index]),
            "old_scale": float(old_scale[index]),
            "typed_scale": typed_scale,
            "policy": policy,
        })
    nonkeep = [row for row in rows if row["candidate_id"] != "KEEP_C0"]
    positive = [row for row in nonkeep if float(row["delta_score"]) > 0 or float(row["delta_margin"]) > 0]
    supported_jobs = sorted({row["job_type"] for row in nonkeep})
    audit_probe = None
    probe_path = EXPERIMENT / "quarantine" / "audit_input_bd696d89d493" / "results/a2_normalization_ablation.csv"
    if probe_path.is_file():
        with probe_path.open(encoding="utf-8-sig", newline="") as stream:
            probe_rows = list(csv.DictReader(stream))
        audit_probe = {
            "rows": len(probe_rows),
            "source": str(probe_path.relative_to(ROOT)),
            "source_sha256": sha256(probe_path),
            "input_archive_hash_verified": False,
            "warning": "copied from quarantined mismatched-hash audit input; diagnostic only",
        }
    result = {
        "created_at_utc": utc_now(),
        "source_rows": len(rows),
        "feature_count": len(names),
        "old_scale_below_0_001_count": int((old_scale < .001).sum()),
        "old_scale_at_or_below_0_00101_count": int((old_scale <= .00101).sum()),
        "binary_feature_count": sum(row["kind"] == "binary" for row in schema),
        "constant_feature_count": sum(row["constant"] for row in schema),
        "supported_nonkeep_jobs": supported_jobs,
        "unseen_jobs": sorted(set(("CARE_COLLECT", "COLLECT_CARE", "FERTILIZE_WATER", "WATER_FERTILIZE", "HARVEST_DROP", "COLLECT_DROP")) - set(supported_jobs)),
        "nonkeep_rows": len(nonkeep),
        "positive_nonkeep_rows": len(positive),
        "training_verdict": "NO_POSITIVE_CANDIDATE_SUPPORT" if not positive else "POSITIVE_SUPPORT_PRESENT",
        "runtime_policy": {
            "unknown_job": "KEEP",
            "constant_binary_changed": "KEEP",
            "continuous_outside_training_range": "KEEP_OR_SAFE_STATE_BASED_REPLAN",
            "nonfinite": "KEEP",
            "model_missing": "KEEP_AND_MODEL_USED_FALSE",
        },
        "quarantined_audit_probe": audit_probe,
        "schema": schema,
    }
    write_json(EXPERIMENT / "NORMALIZATION_AND_SUPPORT_AUDIT.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "schema"}, ensure_ascii=False))


def _positions(farm: Mapping[str, Any]) -> list[list[int]]:
    return [list(farm.get("farmer") or [0, 0]), *[list(value) for value in farm.get("hands") or []]]


def _route_length(left: Sequence[int], right: Sequence[int]) -> int:
    return abs(int(left[0]) - int(right[0])) + abs(int(left[1]) - int(right[1]))


def _worker_plan_candidates(observation: Mapping[str, Any], action: Mapping[str, Any]) -> list[dict[str, Any]]:
    seat = int(observation["player"])
    farm = observation["farms"][seat]
    positions = _positions(farm)
    hands = list(action.get("hands") or [])
    shed = observation["private"].get("shed") or {}
    hour = int(observation.get("hour", 0))
    step = int(observation.get("step", int(observation.get("day", 0)) * 24 + hour))
    if not 192 <= step <= 600 or hour > 20:
        return []
    animals = []
    for y, row in enumerate(farm.get("tiles") or []):
        for x, tile in enumerate(row):
            if isinstance(tile, Mapping) and tile.get("animal") and not tile.get("fed_today"):
                animals.append((x, y))
    shed_tiles = ((4, 4), (5, 4), (4, 5), (5, 5))
    result = []
    for actor in range(1, len(positions)):
        control = list(hands[actor - 1]) if actor - 1 < len(hands) else ["PASS"]
        position = positions[actor]
        if control == ["PASS"] and tuple(position) in shed_tiles and int(shed.get("WHEAT", 0)) > 0 and animals:
            target = min(animals, key=lambda value: (_route_length(position, value), value))
            quantity = min(int(shed.get("WHEAT", 0)), max(1, len(animals)), 5)
            duration = 1 + _route_length(position, target) + 1
            if hour + duration <= 23:
                result.append({
                    "candidate_id": f"FEED_REFILL_DAY_BOUNDARY:a{actor}:s{step}",
                    "job_type": "FEED_REFILL_DAY_BOUNDARY",
                    "step": step,
                    "actor_index": actor,
                    "replaced_control": control,
                    "opportunity_cost": "one PASS plus actor ownership through explicit feed route until day boundary",
                    "preconditions": {"at_shed": True, "unfed_animals": len(animals), "remaining_turns": 24 - hour},
                    "reserved_materials": {"shed:WHEAT": quantity},
                    "reserved_cash": 0,
                    "reserved_shed_capacity": 0,
                    "deadline_step": step + (23 - hour),
                    "continuation": [["PICKUP", "WHEAT", quantity], "route_to_nearest_unfed", ["FEED"]],
                    "safe_rejoin_boundary": {"kind": "HAND_DAY_END_DISAPPEARANCE", "day": int(observation["day"])},
                    "expected_rejoin": {"actor_absent_next_day": True, "remaining_obligations": 0},
                    "primitive_postconditions": ["pickup observed", "target fed"],
                    "economic_postconditions": ["animal survives refresh", "paired terminal margin measured separately"],
                    "abort_policy": "SAFE_REPLAN",
                    "replanning_policy": "STATE_BASED_ACTOR_REPLAN",
                    "estimated_duration": duration,
                })
        tile = None
        if 0 <= position[1] < len(farm.get("tiles") or []) and 0 <= position[0] < len(farm["tiles"][position[1]]):
            tile = farm["tiles"][position[1]][position[0]]
        if control == ["PASS"] and isinstance(tile, Mapping) and tile.get("kind") == "PLANT" and int(tile.get("yield_units", 0)) > 0:
            nearest_shed = min(shed_tiles, key=lambda value: (_route_length(position, value), value))
            duration = 1 + _route_length(position, nearest_shed) + 1
            if hour + duration <= 23 and sum(int(value) for value in shed.values()) < 100:
                result.append({
                    "candidate_id": f"HARVEST_DELIVER_DAY_BOUNDARY:a{actor}:s{step}",
                    "job_type": "HARVEST_DELIVER_DAY_BOUNDARY",
                    "step": step,
                    "actor_index": actor,
                    "replaced_control": control,
                    "opportunity_cost": "one PASS plus actor ownership through harvest/deposit until day boundary",
                    "preconditions": {"harvestable": True, "remaining_turns": 24 - hour},
                    "reserved_materials": {},
                    "reserved_cash": 0,
                    "reserved_shed_capacity": int(tile.get("yield_units", 0)),
                    "deadline_step": step + (23 - hour),
                    "continuation": [["HARVEST"], "route_to_shed", ["DROP"]],
                    "safe_rejoin_boundary": {"kind": "HAND_DAY_END_DISAPPEARANCE", "day": int(observation["day"])},
                    "expected_rejoin": {"actor_absent_next_day": True, "remaining_obligations": 0},
                    "primitive_postconditions": ["yield carried", "yield deposited"],
                    "economic_postconditions": ["product retained", "paired terminal margin measured separately"],
                    "abort_policy": "SAFE_REPLAN",
                    "replanning_policy": "STATE_BASED_ACTOR_REPLAN",
                    "estimated_duration": duration,
                })
    return result


def command_p3_scan() -> None:
    base_dir = ROOT / "experiments/learning_round2_20260921/external_bank/replays/c0"
    candidates = []
    coverage = Counter()
    for family in ("mooman_e052a", "qeinstein_moev2", "smart_farm", "souvik_v4"):
        for seed in range(2026092421, 2026092425):
            for seat in (0, 1):
                replay = _read_replay(base_dir / family / f"seed_{seed}_seat_{seat}.json.gz")
                for step in range(192, 600):
                    observation = dict(replay["steps"][step][seat]["observation"])
                    observation.update({"player": seat, "step": step})
                    action = replay["steps"][step + 1][seat].get("action") or {}
                    rows = _worker_plan_candidates(observation, action)
                    for row in rows:
                        row.update({"opponent_family": family, "seed": seed, "seat": seat, "prefix_state_sha256": json_hash(observation)})
                        candidates.append(row)
                        coverage[(row["job_type"], step // 24, family)] += 1
    output = EXPERIMENT / "p3_candidate_scan.jsonl"
    output.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in candidates), encoding="utf-8")
    summary = {
        "created_at_utc": utc_now(),
        "observed_development_conditions": 32,
        "scanned_steps_per_condition": 408,
        "fixed_step_filter": False,
        "candidate_count": len(candidates),
        "by_job": dict(Counter(row["job_type"] for row in candidates)),
        "distinct_steps": len({row["step"] for row in candidates}),
        "distinct_days": len({row["step"] // 24 for row in candidates}),
        "distinct_families": len({row["opponent_family"] for row in candidates}),
        "coverage_cells": len(coverage),
        "paired_continuations_run": 0,
        "training_run": False,
        "training_verdict": "PENDING_PAIRED_CONTINUATIONS" if candidates else "NO_CANDIDATE_COVERAGE",
        "note": "scan establishes state/job/time coverage only; it is not economic evidence and does not enable runtime actions",
    }
    write_json(EXPERIMENT / "p3_candidate_scan_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


def command_executor_tests() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_learning_round3.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    fixtures = tree_digest(list((EXPERIMENT / "REGRESSION_CASES").glob("*.json")))
    result = {
        "created_at_utc": utc_now(),
        "command": f"{sys.executable} -m pytest -q tests/test_learning_round3.py",
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "fixtures": fixtures,
        "contracts_enforced": [
            "actor identity/day epoch",
            "required pickup and remaining feed obligations",
            "state-based replan after missing movement",
            "DROP future-material reservation",
            "cross-worker shed material and capacity",
            "market slot limit",
            "typed constant/unseen/nonfinite support",
            "pinned engine market parity",
        ],
    }
    write_json(EXPERIMENT / "EXECUTOR_CONTRACT_TESTS.json", result)
    print(json.dumps({key: value for key, value in result.items() if key not in {"stdout", "stderr", "fixtures"}}, ensure_ascii=False))


def _prepare_probe_runtimes() -> dict[str, dict[str, Any]]:
    result = {}
    for mode in ("c0", "feed_refill", "harvest_deliver", "feed_once_replan"):
        target = RUNTIME / f"a3_{mode}"
        if not target.exists():
            target.mkdir(parents=True)
            subprocess.run(["tar", "-xf", str(C0_ARCHIVE), "-C", str(target)], check=True, timeout=60)
            if mode != "c0":
                (target / "main.py").rename(target / "c0_main.py")
                shutil.copy2(AGENT / "a3_probe_agent.py", target / "main.py")
                shutil.copy2(AGENT / "contracts.py", target / "contracts.py")
                write_json(target / "arm_config.json", {"mode": mode, "max_jobs": 1, "promotion_candidate": False})
        archive = ARCHIVES / f"{STUDY_ID}_a3_{mode}_probe.tar.gz"
        if not archive.exists():
            subprocess.run(["tar", "-czf", str(archive), "-C", str(target), "."], check=True, timeout=120)
        result[mode] = {
            "main": target / "main.py",
            "archive": archive,
            "archive_sha256": sha256(archive),
            "source_tree": tree_digest(list(target.glob("*"))),
        }
    write_json(
        EXPERIMENT / "p3_probe_archives.json",
        {
            "created_at_utc": utc_now(),
            "archives": {
                mode: {
                    "path": str(row["archive"].relative_to(ROOT)),
                    "sha256": row["archive_sha256"],
                    "source_tree_sha256": row["source_tree"]["sha256"],
                }
                for mode, row in result.items()
            },
        },
    )
    return result


def _call_agent(function: Any, observation: Any, configuration: Any) -> Any:
    try:
        parameters = inspect.signature(function).parameters.values()
        accepts = any(value.kind in {value.VAR_POSITIONAL, value.VAR_KEYWORD} for value in parameters) or len(list(parameters)) >= 2
    except (TypeError, ValueError):
        accepts = True
    return function(observation, configuration) if accepts else function(observation)


def _run_closed_game(task: Mapping[str, Any]) -> dict[str, Any]:
    import random

    import psutil
    from kaggle_environments import make

    random.seed(int(task["seed"]))
    np.random.seed(int(task["seed"]) % (2**32 - 1))
    process = psutil.Process(os.getpid())
    before_rss = process.memory_info().rss
    started = time.perf_counter()
    focal_module = _load_module(Path(task["agent_main"]), f"{task['arm']}_focal")
    import_seconds = time.perf_counter() - started
    opponent_module = _load_module(Path(task["opponent_main"]), f"{task['family']}_opponent")
    timings = []

    def focal(observation: Any, configuration: Any = None) -> Any:
        tick = time.perf_counter()
        result = _call_agent(focal_module.agent, observation, configuration)
        timings.append(time.perf_counter() - tick)
        return result

    def opponent(observation: Any, configuration: Any = None) -> Any:
        return _call_agent(opponent_module.agent, observation, configuration)

    configuration = dict(task["configuration"])
    configuration["seed"] = int(task["seed"])
    env = make("kaggriculture", configuration=configuration, debug=True)
    env.run([focal, opponent] if int(task["seat"]) == 0 else [opponent, focal])
    replay = env.toJSON()
    replay_path = Path(task["replay_path"])
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(replay_path, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))
    seat = int(task["seat"])
    rewards = [float(row.get("reward") or 0) for row in replay["steps"][-1]]
    statuses = [str(row.get("status")) for row in replay["steps"][-1]]
    diagnostics = focal_module.policy_diagnostics() if hasattr(focal_module, "policy_diagnostics") else (
        focal_module.latest_diagnostics(seat) if hasattr(focal_module, "latest_diagnostics") else {}
    )
    trace = focal_module.policy_trace() if hasattr(focal_module, "policy_trace") else []
    timing = np.asarray(timings, dtype=np.float64)
    result = {
        "arm": task["arm"],
        "family": task["family"],
        "seed": int(task["seed"]),
        "seat": seat,
        "our_cash": rewards[seat],
        "opponent_cash": rewards[1 - seat],
        "margin": rewards[seat] - rewards[1 - seat],
        "score": 1.0 if rewards[seat] > rewards[1 - seat] else .5 if rewards[seat] == rewards[1 - seat] else 0.0,
        "terminal_statuses": statuses,
        "stored_states": len(replay["steps"]),
        "cold_import_seconds": import_seconds,
        "warm_mean_seconds": float(timing.mean()),
        "warm_p95_seconds": float(np.percentile(timing, 95)),
        "warm_max_seconds": float(timing.max()),
        "rss_before_bytes": before_rss,
        "rss_after_bytes": process.memory_info().rss,
        "diagnostics": diagnostics,
        "trace": trace,
        "replay_path": str(replay_path),
    }
    sidecar = {
        "created_at_utc": utc_now(),
        "task_digest": replay_task_digest(task),
        "replay_sha256": sha256(replay_path),
        "seed": int(task["seed"]),
        "seat": seat,
        "terminal_statuses": statuses,
        "stored_states": len(replay["steps"]),
        "agent_archive_sha256": task["agent_archive_sha256"],
        "agent_source_tree_sha256": task["agent_source_tree_sha256"],
        "opponent_tree_sha256": task["opponent_tree_sha256"],
        "engine_sha256": task["engine_sha256"],
        "configuration": configuration,
        "diagnostics": diagnostics,
        "timing_measured": True,
    }
    write_json(Path(task["sidecar_path"]), sidecar)
    return result


def _quarantine_stale(replay: Path, sidecar: Path, reason: str) -> None:
    quarantine = replay.parents[4] / "quarantine" / f"{replay.stem}_{reason}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    quarantine.mkdir(parents=True)
    if replay.exists():
        shutil.move(str(replay), str(quarantine / replay.name))
    if sidecar.exists():
        shutil.move(str(sidecar), str(quarantine / sidecar.name))


def command_p3_paired() -> None:
    runtimes = _prepare_probe_runtimes()
    output = EXPERIMENT / "p3_paired_development"
    feature_schema = EXPERIMENT / "NORMALIZATION_AND_SUPPORT_AUDIT.json"
    conditions = [
        ("qeinstein_moev2", 2026092421, 0),
        ("qeinstein_moev2", 2026092421, 1),
        ("smart_farm", 2026092422, 0),
        ("smart_farm", 2026092422, 1),
    ]
    tasks = []
    for arm, runtime in runtimes.items():
        for family, seed, seat in conditions:
            replay = output / "replays" / arm / family / f"seed_{seed}_seat_{seat}.json.gz"
            sidecar = replay.with_suffix(replay.suffix + ".sidecar.json")
            opponent_files = [path for path in OPPONENTS[family].parent.rglob("*") if path.is_file() and path.suffix in {".py", ".json", ".gz"}]
            tasks.append({
                "arm": arm,
                "family": family,
                "seed": seed,
                "seat": seat,
                "agent_main": str(runtime["main"]),
                "opponent_main": str(OPPONENTS[family]),
                "replay_path": str(replay),
                "sidecar_path": str(sidecar),
                "configuration": dict(GAME_CONFIGURATION),
                "agent_archive_sha256": runtime["archive_sha256"],
                "agent_source_tree_sha256": runtime["source_tree"]["sha256"],
                "model_hashes": {},
                "feature_schema_sha256": sha256(feature_schema),
                "executor_version": "round3-contract-executor-v1",
                "engine_sha256": ENGINE_SHA256,
                "opponent_tree_sha256": tree_digest(opponent_files)["sha256"],
            })
    results = []
    cache_events = []
    for index, task in enumerate(tasks, 1):
        replay, sidecar = Path(task["replay_path"]), Path(task["sidecar_path"])
        reusable, reason = reusable_replay(task, replay, sidecar)
        if reusable:
            stored = _read_replay(replay)
            rewards = [float(row.get("reward") or 0) for row in stored["steps"][-1]]
            seat = int(task["seat"])
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            results.append({
                "arm": task["arm"], "family": task["family"], "seed": int(task["seed"]), "seat": seat,
                "our_cash": rewards[seat], "opponent_cash": rewards[1 - seat], "margin": rewards[seat] - rewards[1 - seat],
                "score": 1.0 if rewards[seat] > rewards[1 - seat] else .5 if rewards[seat] == rewards[1 - seat] else 0.0,
                "terminal_statuses": metadata["terminal_statuses"], "stored_states": metadata["stored_states"],
                "cold_import_seconds": None, "warm_mean_seconds": None, "warm_p95_seconds": None, "warm_max_seconds": None,
                "rss_before_bytes": None, "rss_after_bytes": None, "diagnostics": metadata.get("diagnostics", {}), "trace": [],
                "replay_path": str(replay),
            })
            cache_events.append({"task_digest": replay_task_digest(task), "decision": "REUSED", "reason": reason})
        else:
            if replay.exists() or sidecar.exists():
                _quarantine_stale(replay, sidecar, reason)
            result = _run_closed_game(task)
            results.append(result)
            cache_events.append({"task_digest": replay_task_digest(task), "decision": "RERUN", "reason": reason})
        print(f"{index}/{len(tasks)} {task['arm']} {task['family']} {task['seed']} seat{task['seat']}", flush=True)
    lookup = {(row["arm"], row["family"], row["seed"], row["seat"]): row for row in results}
    flat = []
    for row in sorted(results, key=lambda value: (value["arm"], value["family"], value["seed"], value["seat"])):
        control = lookup[("c0", row["family"], row["seed"], row["seat"])]
        flat.append({
            "arm": row["arm"], "opponent_family": row["family"], "requested_seed": row["seed"], "seat": row["seat"],
            "score": row["score"], "our_cash": row["our_cash"], "opponent_cash": row["opponent_cash"], "margin": row["margin"],
            "paired_score_delta_vs_c0": row["score"] - control["score"], "paired_margin_delta_vs_c0": row["margin"] - control["margin"],
            "model_loads": row["diagnostics"].get("model_loads"), "inference_calls": row["diagnostics"].get("inference_calls"),
            "jobs_started": row["diagnostics"].get("jobs_started", 0), "jobs_completed": row["diagnostics"].get("jobs_completed", 0),
            "jobs_aborted": row["diagnostics"].get("jobs_aborted", 0), "action_changes": row["diagnostics"].get("action_changes", 0),
            "fallbacks": row["diagnostics"].get("fallbacks", 0), "statuses": "/".join(row["terminal_statuses"]),
            "replay_path": str(Path(row["replay_path"]).relative_to(ROOT)),
        })
    write_csv(output / "paired_results.csv", flat)
    write_json(output / "cache_decisions.json", cache_events)
    write_json(output / "traces.json", [{"arm": row["arm"], "family": row["family"], "seed": row["seed"], "seat": row["seat"], "trace": row["trace"]} for row in results if row["trace"]])
    summary = {}
    for arm in runtimes:
        selected = [row for row in flat if row["arm"] == arm]
        summary[arm] = {
            "games": len(selected),
            "mean_paired_margin_delta": mean(float(row["paired_margin_delta_vs_c0"]) for row in selected),
            "positive_games": sum(float(row["paired_margin_delta_vs_c0"]) > 0 for row in selected),
            "negative_games": sum(float(row["paired_margin_delta_vs_c0"]) < 0 for row in selected),
            "jobs_started": sum(int(row["jobs_started"] or 0) for row in selected),
            "jobs_completed": sum(int(row["jobs_completed"] or 0) for row in selected),
            "jobs_aborted": sum(int(row["jobs_aborted"] or 0) for row in selected),
            "action_changes": sum(int(row["action_changes"] or 0) for row in selected),
        }
    positives = [arm for arm in runtimes if arm != "c0" and summary[arm]["positive_games"] > 0 and summary[arm]["mean_paired_margin_delta"] > 0]
    verdict = {
        "created_at_utc": utc_now(),
        "development_only": True,
        "observed_round2_conditions_reused_as_holdout": False,
        "grouping": "family x seed; both seats are one cluster",
        "summary": summary,
        "positive_candidate_arms": positives,
        "training_run": False,
        "training_reason": "selector training requires positive completed paired candidates" if not positives else "positive candidates exist; run the explicit training stage next",
        "promotable": False,
    }
    write_json(output / "paired_summary.json", verdict)
    write_csv(EXPERIMENT / "paired_results.csv", flat)
    write_json(EXPERIMENT / "MODEL_USAGE.json", {
        "created_at_utc": utc_now(),
        "games": len(results),
        "arms": {
            arm: {
                "model_loads": sum(int(row["diagnostics"].get("model_loads", 0)) for row in results if row["arm"] == arm),
                "inference_calls": sum(int(row["diagnostics"].get("inference_calls", 0)) for row in results if row["arm"] == arm),
                "timing_measured_games": sum(row["cold_import_seconds"] is not None for row in results if row["arm"] == arm),
                "cold_import_max_seconds": max((row["cold_import_seconds"] for row in results if row["arm"] == arm and row["cold_import_seconds"] is not None), default=None),
                "warm_mean_seconds": mean(row["warm_mean_seconds"] for row in results if row["arm"] == arm and row["warm_mean_seconds"] is not None) if any(row["arm"] == arm and row["warm_mean_seconds"] is not None for row in results) else None,
                "rss_after_max_bytes": max((row["rss_after_bytes"] for row in results if row["arm"] == arm and row["rss_after_bytes"] is not None), default=None),
                "missing_measurements_are_not_imputed": True,
            }
            for arm in runtimes
        },
    })
    print(json.dumps(verdict, ensure_ascii=False))


def command_finalize() -> None:
    paired_path = EXPERIMENT / "paired_results.csv"
    with paired_path.open(encoding="utf-8-sig", newline="") as stream:
        paired = list(csv.DictReader(stream))
    paired_summary = json.loads((EXPERIMENT / "p3_paired_development/paired_summary.json").read_text(encoding="utf-8"))
    scan_summary = json.loads((EXPERIMENT / "p3_candidate_scan_summary.json").read_text(encoding="utf-8"))
    p2_summary = json.loads((EXPERIMENT / "p2_decomposition_summary.json").read_text(encoding="utf-8"))
    normalization = json.loads((EXPERIMENT / "NORMALIZATION_AND_SUPPORT_AUDIT.json").read_text(encoding="utf-8"))
    loader = json.loads((EXPERIMENT / "LOADER_VALIDATION.json").read_text(encoding="utf-8"))
    probe_loader = json.loads((EXPERIMENT / "P3_PROBE_LOADER_VALIDATION.json").read_text(encoding="utf-8"))
    executor_tests = json.loads((EXPERIMENT / "EXECUTOR_CONTRACT_TESTS.json").read_text(encoding="utf-8"))
    audit_input = json.loads((EXPERIMENT / "audit_input_validation.json").read_text(encoding="utf-8"))

    cluster_rows = []
    for arm in sorted({row["arm"] for row in paired}):
        keys = sorted({(row["opponent_family"], int(row["requested_seed"])) for row in paired if row["arm"] == arm})
        for family, seed in keys:
            selected = [row for row in paired if row["arm"] == arm and row["opponent_family"] == family and int(row["requested_seed"]) == seed]
            deltas = [float(row["paired_margin_delta_vs_c0"]) for row in selected]
            cluster_rows.append(
                {
                    "arm": arm,
                    "opponent_family": family,
                    "seed": seed,
                    "seats": [int(row["seat"]) for row in selected],
                    "seat_deltas": deltas,
                    "cluster_mean_delta": mean(deltas),
                    "cluster_min_delta": min(deltas),
                    "cluster_max_delta": max(deltas),
                }
            )
    p3_scope = {
        "created_at_utc": utc_now(),
        "development_only": True,
        "observed_round2_panel_not_used_as_unseen_holdout": True,
        "broad_scan": scan_summary,
        "paired_summary": paired_summary,
        "family_seed_clusters": cluster_rows,
        "candidate_expansion_executed": {
            "from": "whole-day FEED_REFILL_DAY_BOUNDARY",
            "to": "one-unit FEED_ONCE_STATE_REPLAN with an observed fed_today safe boundary",
            "reason": "reduce worker opportunity cost and prove a state-based return instead of waiting for actor disappearance",
            "result": "4/4 negative; mean paired margin delta -87",
        },
        "training_verdict": "NO_POSITIVE_CANDIDATE_SUPPORT",
        "training_run": False,
        "unseen_evaluation_run": False,
        "stop_reason": "all executable expanded-scope candidates were non-positive; training or holdout use would violate the preregistered gate",
    }
    write_json(EXPERIMENT / "P3_SCOPE_RESULTS.json", p3_scope)

    prior_usage = json.loads((EXPERIMENT / "MODEL_USAGE.json").read_text(encoding="utf-8"))
    prior_usage = prior_usage.get("closed_loop_latest_run", prior_usage)
    selection_counts = {
        arm: {
            "jobs_started": sum(int(row.get("jobs_started") or 0) for row in paired if row["arm"] == arm),
            "jobs_completed": sum(int(row.get("jobs_completed") or 0) for row in paired if row["arm"] == arm),
            "jobs_aborted": sum(int(row.get("jobs_aborted") or 0) for row in paired if row["arm"] == arm),
            "action_changes": sum(int(row.get("action_changes") or 0) for row in paired if row["arm"] == arm),
            "fallbacks": sum(int(row.get("fallbacks") or 0) for row in paired if row["arm"] == arm),
        }
        for arm in sorted({row["arm"] for row in paired})
    }
    model_usage = {
        "created_at_utc": utc_now(),
        "trained_model_present": False,
        "model_loads": 0,
        "inference_calls": 0,
        "reason": "NO_POSITIVE_CANDIDATE_SUPPORT; no learned artifact was created or silently bypassed",
        "closed_loop_latest_run": prior_usage,
        "candidate_selection_and_fallback": selection_counts,
        "official_loader_measurements": {
            "c0_identity": {
                "archive_sha256": loader["archive_sha256"],
                "cold_import_seconds": loader["cold_import_seconds"],
                "warm_calls": loader["warm_calls"],
                "warm_mean_seconds": loader["warm_mean_seconds"],
                "warm_max_seconds": loader["warm_max_seconds"],
                "one_game_states": loader["stored_states"],
                "one_game_peak_rss_bytes": None,
            },
            "feed_once_replan_rejected_probe": {
                "archive_sha256": probe_loader["archive_sha256"],
                "cold_import_seconds": probe_loader["cold_import_seconds"],
                "warm_calls": probe_loader["warm_calls"],
                "warm_mean_seconds": probe_loader["warm_mean_seconds"],
                "warm_max_seconds": probe_loader["warm_max_seconds"],
                "closed_loop_peak_rss_bytes": prior_usage["arms"]["feed_once_replan"]["rss_after_max_bytes"],
            },
        },
        "missing_measurements_are_not_imputed": True,
    }
    write_json(EXPERIMENT / "MODEL_USAGE.json", model_usage)

    final_status = {
        "created_at_utc": utc_now(),
        "verdict": "NO_PROMOTION_CANDIDATE",
        "candidate": "NONE",
        "required_gates": {
            "SERIALIZATION_VALID": {"value": True, "scope": "C0 identity and rejected feed_once probe"},
            "LOADER_VALID": {"value": True, "scope": "official get_last_callable, empty globals, arbitrary cwd, last callable agent"},
            "TRAINED": {"value": False, "reason": "NO_POSITIVE_CANDIDATE_SUPPORT"},
            "MODEL_USED": {"value": False, "reason": "no model was trained; loads and inferences are both zero"},
            "SUPPORTED_STATE": {"value": True, "scope": "executed bounded probes; A2 unsupported/OOD states still KEEP"},
            "ACTION_CHANGED": {"value": True, "scope": "research probes only"},
            "EXECUTION_VALID": {"value": True, "scope": "all 16 recorded development games DONE/DONE; contracts completed without abort"},
            "ECONOMICALLY_BENEFICIAL": {"value": False, "reason": "no positive P2 headroom and no positive P3 arm"},
            "EVALUATED_ON_UNSEEN_CONDITIONS": {"value": False, "reason": "stopped before holdout because economic gate failed"},
            "PROMOTABLE": {"value": False, "reason": "economic, trained/model-used, and unseen gates are false"},
        },
        "arm_verdicts": {
            "c0_identity": "BASELINE_ONLY",
            "B3_same_two_order_candidate_set": "STOP_NO_ORACLE_HEADROOM",
            "feed_refill": "REJECTED_NEGATIVE",
            "harvest_deliver": "SAFE_NO_EFFECT",
            "feed_once_replan": "REJECTED_NEGATIVE",
        },
        "kaggle_submission_performed": False,
        "rating_claim": None,
    }
    write_json(EXPERIMENT / "FINAL_STATUS.json", final_status)

    reproduce = """# Round3 reproduction commands

Run from the repository root with the checked environment:

```powershell
.\\.venv\\Scripts\\python.exe scripts\\learning_round3.py init
.\\.venv\\Scripts\\python.exe scripts\\learning_round3.py package-control
.\\.venv\\Scripts\\python.exe scripts\\learning_round3.py validate-loader
.\\.venv\\Scripts\\python.exe scripts\\learning_round3.py normalization-audit
.\\.venv\\Scripts\\python.exe scripts\\learning_round3.py executor-tests
.\\.venv\\Scripts\\python.exe scripts\\learning_round3.py p2-decomposition
.\\.venv\\Scripts\\python.exe scripts\\learning_round3.py p3-scan
.\\.venv\\Scripts\\python.exe scripts\\learning_round3.py p3-paired
.\\.venv\\Scripts\\python.exe scripts\\learning_round3.py validate-probe-loader
.\\.venv\\Scripts\\python.exe scripts\\learning_round3.py finalize
```

`p3-paired` reuses a replay only when the sidecar task digest, replay SHA-256,
seed, seat, terminal statuses, state count, engine, agent/archive, feature schema,
configuration, and opponent hashes match. Missing or stale evidence is rerun and
the prior files are quarantined, never treated as a measurement.
"""
    (EXPERIMENT / "REPRODUCE.md").write_text(reproduce, encoding="utf-8")

    report = f"""# Kaggriculture Round3 実装・評価報告

## 結論

Round3では比較・提出基盤、実行契約、正規化/support拒否、step264市場評価器、限定的な複数ターン候補を実装し、単体試験と実ゲーム閉ループまで実行した。しかし、新しい昇格候補は得られなかった。`PROMOTABLE=false` であり、Round3のprobe archiveを強化版として提出してはいけない。Kaggle提出は実施していない。

## 入力と基準版

- 指定された監査ZIPの実SHA-256は `{audit_input['observed_sha256']}` で、指定値 `{audit_input['expected_sha256']}` と一致しなかった。内容はread-only quarantineへ展開し、診断補助にのみ使った。
- 既知の提出成功版 fixed_v3 は発見され、SHA-256 `{loader['known_success_fixed_v3_sha256']}` が既知値と一致した。
- C0 identity artifactは元C0とbyte-identical（`{loader['archive_sha256']}`）。公式 `get_last_callable`、空globals、repo外cwd、archive実行時NumPy遮断で最後のcallableが `agent` になり、720状態を `DONE/DONE` で完走した。
- 棄却した最終probeも実archiveから公式loaderで `agent` が選択され、4状態smoke testを完走した。これは提出適格性ではなくserialization/loaderだけの証拠である。

## P1: 壊さない実行契約

- actor identity/day epoch、必要資材・現金・shed容量・期限、完全continuation、安全なrejoin境界、postcondition、abort/replanを明示する契約を追加した。
- 最終joint actionに対し、他作業者を含むPICKUP/PLACE/DROP、予約二重使用、shed容量、market slotを検査する。
- 小麦PICKUP消失、給餌予約、NORTH消失後の古い経路復帰、将来資材DROP、複数作業者競合、日付境界/index再利用を汎用fixtureで検査した。試験結果は `EXECUTOR_CONTRACT_TESTS.json` のとおり `{executor_tests['passed']}`。
- A2の56行/530特徴を型付き監査し、定数次元 {normalization['constant_feature_count']}、旧scale≦0.00101の次元 {normalization['old_scale_at_or_below_0_00101_count']}、正の非KEEP教師 {normalization['positive_nonkeep_rows']} を確認した。結論は `NO_POSITIVE_CANDIDATE_SUPPORT`。二値特徴を微小stdで割らず、未知job・定数binary変化・範囲外・nonfinite・model欠損はKEEPまたは安全replanにする。

## P2: step264の分解

固定エンジンと同じlockstep市場処理を実装し、価格floor、SELL/BUY_PRODUCT、資金依存注文、slot順を試験した。32条件の同一状態・同一2候補で、現予測は修正評価器でも32/32逆順を選び、ordered oracle regretは合計 {p2_summary['methods']['current_prediction_repaired_evaluator']['total_ordered_oracle_regret']}、平均 {p2_summary['methods']['current_prediction_repaired_evaluator']['mean_ordered_oracle_regret']}。正確な数量・順序oracleは32/32でC0順を維持し、正のoracle headroomは {p2_summary['ordered_oracle_positive_headroom_conditions']} 条件だった。従って評価器だけの修正では足りず、この2順序候補集合の大型化は停止した。

## P3: 候補生成と閉ループ

固定時刻2点ではなくstep 192〜599を走査し、{scan_summary['observed_development_conditions'] * scan_summary['scanned_steps_per_condition']}状態、{scan_summary['candidate_count']}候補、{scan_summary['distinct_steps']}時刻、{scan_summary['distinct_days']}日、{scan_summary['distinct_families']} familyを得た。経済評価は観察済みRound2条件の一部をdevelopmentとして使い、holdoutとは呼んでいない。

- `FEED_REFILL_DAY_BOUNDARY`: 4ゲームすべて悪化、平均margin差 -1089。作業者を日末まで所有する機会費用が大きく棄却。
- `HARVEST_DELIVER_DAY_BOUNDARY`: 4ゲームで差0、`SAFE_NO_EFFECT`。実行成功を経済改善とは数えていない。
- 次の候補生成として `FEED_ONCE_STATE_REPLAN` を実装。小麦1個→最寄り給餌→`fed_today`確認で状態ベース復帰に狭めたが、4ゲームすべて悪化、平均margin差 -87（qeinstein -136/-136、smart_farm -32/-44）。

両seatは独立試行として水増しせず、family×seedクラスタ内の感度として `P3_SCOPE_RESULTS.json` に併記した。正の完遂候補が0なので、selector学習は実施していない。学習済みと称するmodelも作成していない。未使用条件による最終評価は経済gate不合格のため未実施である。

## 悪化・未確認・次の一手

給餌候補は安全に完遂してもC0より悪かった。収穫納品候補は無効果だった。新しい学習モデル、変換前後誤差、閾値付近選択、未使用holdout、Kaggleレート効果は未確認（学習を開始する正例がなかったため非該当または未実施）。

次は、単発の追加サービスではなく、同一prefixから「給餌→産物回収→倉庫/販売→再投資」まで終端価値を持つ有限候補を生成し、C0 rolloutを保持したpaired continuationでoracle headroomを先に測る。正のoracle候補が得られた場合だけ、episode/family/version/day帯/jobで分割した低容量順位モデルを学習する。既知32条件と今回の4開発ゲームを未使用holdoutへ戻してはならない。
"""
    (EXPERIMENT / "REPORT_JA.md").write_text(report, encoding="utf-8")

    write_json(EXPERIMENT / "SOURCE_AND_MODEL_MANIFEST.json", make_source_and_model_manifest())
    handoff_files = [
        AGENT / "__init__.py",
        AGENT / "contracts.py",
        AGENT / "market.py",
        AGENT / "a3_probe_agent.py",
        ROOT / "scripts/learning_round3.py",
        ROOT / "scripts/round3_loader_probe.py",
        ROOT / "tests/test_learning_round3.py",
        EXPERIMENT / "ROUND3_PLAN.md",
        EXPERIMENT / "REPRODUCE.md",
        EXPERIMENT / "REPORT_JA.md",
        EXPERIMENT / "SOURCE_AND_MODEL_MANIFEST.json",
        EXPERIMENT / "LOADER_VALIDATION.json",
        EXPERIMENT / "P3_PROBE_LOADER_VALIDATION.json",
        EXPERIMENT / "NORMALIZATION_AND_SUPPORT_AUDIT.json",
        EXPERIMENT / "EXECUTOR_CONTRACT_TESTS.json",
        EXPERIMENT / "ORACLE_HEADROOM_AND_REGRET.csv",
        EXPERIMENT / "p2_decomposition_summary.json",
        EXPERIMENT / "p3_candidate_scan_summary.json",
        EXPERIMENT / "P3_SCOPE_RESULTS.json",
        EXPERIMENT / "paired_results.csv",
        EXPERIMENT / "MODEL_USAGE.json",
        EXPERIMENT / "FINAL_STATUS.json",
        EXPERIMENT / "audit_input_validation.json",
        EXPERIMENT / "initial_workspace_state.json",
        EXPERIMENT / "environment.json",
        EXPERIMENT / "p3_paired_development/traces.json",
        ARCHIVES / f"{STUDY_ID}_c0_identity.tar.gz",
        ARCHIVES / f"{STUDY_ID}_a3_feed_once_replan_probe.tar.gz",
        *(EXPERIMENT / "REGRESSION_CASES").glob("*.json"),
    ]
    representative = [
        EXPERIMENT / f"p3_paired_development/replays/{arm}/qeinstein_moev2/seed_2026092421_seat_0.json.gz"
        for arm in ("c0", "feed_refill", "harvest_deliver", "feed_once_replan")
    ]
    handoff_files.extend(representative)
    handoff_files.extend(path.with_suffix(path.suffix + ".sidecar.json") for path in representative)
    handoff_files = sorted({path.resolve() for path in handoff_files if path.is_file()}, key=lambda path: str(path).lower())
    handoff_manifest = {
        "created_at_utc": utc_now(),
        "study_id": STUDY_ID,
        "verdict": final_status["verdict"],
        "files": [
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in handoff_files
        ],
    }
    write_json(EXPERIMENT / "HANDOFF_MANIFEST.json", handoff_manifest)
    handoff_files.append((EXPERIMENT / "HANDOFF_MANIFEST.json").resolve())
    handoff_zip = EXPERIMENT / "handoff_evidence.zip"
    with zipfile.ZipFile(handoff_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as stream:
        for path in handoff_files:
            stream.write(path, path.relative_to(ROOT).as_posix())
    handoff_record = {
        "created_at_utc": utc_now(),
        "path": str(handoff_zip.relative_to(ROOT)),
        "bytes": handoff_zip.stat().st_size,
        "sha256": sha256(handoff_zip),
        "member_count": len(handoff_files),
        "contains_models": False,
        "contains_rejected_probe_archive": True,
        "promotion_candidate": False,
    }
    write_json(EXPERIMENT / "handoff_evidence.json", handoff_record)
    print(json.dumps(handoff_record, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "package-control", "validate-loader", "validate-probe-loader", "p2-decomposition", "normalization-audit", "p3-scan", "executor-tests", "p3-paired", "finalize"):
        sub.add_parser(name)
    args = parser.parse_args()
    functions = {
        "init": command_init,
        "package-control": command_package_control,
        "validate-loader": command_validate_loader,
        "validate-probe-loader": command_validate_probe_loader,
        "p2-decomposition": command_p2_decomposition,
        "normalization-audit": command_normalization_audit,
        "p3-scan": command_p3_scan,
        "executor-tests": command_executor_tests,
        "p3-paired": command_p3_paired,
        "finalize": command_finalize,
    }
    functions[args.command]()


if __name__ == "__main__":
    main()
