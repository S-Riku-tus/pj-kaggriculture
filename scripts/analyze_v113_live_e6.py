"""Build an immutable E6 addendum for Kaggle submission 55933145.

The analyzer is deliberately post-hoc and descriptive.  It verifies and reuses
the already-downloaded EpisodeService snapshot and replays, reconstructs the
submitted V113 policy on those observations, and never mutates the
preregistered V111/V113 formal experiment result.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib.util
import json
import math
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluation.replay import (  # noqa: E402
    action,
    canonical_action,
    decision_count,
    lineage_hash,
    observation,
    result_label,
    result_score,
)

SUBMISSION_ID = 55933145
DEFAULT_SUBMISSION_DIR = ROOT / "data/submissions/v113_submission_55933145"
DEFAULT_REPLAY_DIR = ROOT / "data/replays/v113_submission_55933145"
DEFAULT_OUTPUT_DIR = ROOT / "data/evaluation/v113_live_e6_55933145"
DEFAULT_TREATMENT_ARCHIVE = ROOT / "artifacts/evaluation/v113_cow_sheep/treatment.tar.gz"
DEFAULT_CONTROL_ARCHIVE = ROOT / "artifacts/evaluation/v113_cow_sheep/control.tar.gz"
DEFAULT_COMMON_PROBE = ROOT / "data/evaluation/independent_gold_pool/common_probe.json"
FORMAL_RESULT = ROOT / "data/evaluation/v113_cow_sheep_gate_e3e4_20260901_2024/experiment_result.json"
CHECKPOINTS = (24, 100, 200, 400, 719)
MARGIN_CHECKPOINTS = {"day12": 288, "day18": 432, "day20": 480, "day24": 576}
PORTFOLIO_STEPS = tuple(sorted({*range(0, 720, 24), 216, 248, 249, 250, 719}))
PREMIUM_ITEMS = frozenset({"TOMATO", "STRAWBERRY", "MELON", "MILK", "WOOL"})
EMPTY_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_immutable_json(path: Path, value: object) -> None:
    """Create a deterministic snapshot manifest once, then only verify it."""
    encoded = json.dumps(value, ensure_ascii=False, indent=2)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != encoded:
            raise RuntimeError(f"immutable manifest differs from current snapshot: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _number(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _int(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _agent_index(agents: list[dict[str, Any]], submission_id: int) -> int | None:
    for position, agent in enumerate(agents[:2]):
        if _int(agent.get("submissionId")) == submission_id:
            raw_index = _int(agent.get("index"))
            return raw_index if raw_index in (0, 1) else position
    return None


def _raw_indexes(raw_response: dict[str, Any]) -> dict[str, Any]:
    episodes = {
        int(row["id"]): row
        for row in raw_response.get("episodes", [])
        if isinstance(row, dict) and _int(row.get("id")) is not None
    }
    submissions = {
        int(row["id"]): row
        for row in raw_response.get("submissions", [])
        if isinstance(row, dict) and _int(row.get("id")) is not None
    }
    teams = {
        int(row["id"]): row
        for row in raw_response.get("teams", [])
        if isinstance(row, dict) and _int(row.get("id")) is not None
    }
    return {"episodes": episodes, "submissions": submissions, "teams": teams}


def _team_name(team: dict[str, Any] | None) -> str:
    return str((team or {}).get("teamName") or "")


def build_raw_manifest(
    submission_dir: Path,
    replay_dir: Path,
    treatment_archive: Path,
    control_archive: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify the complete local snapshot and return its immutable manifest."""
    metadata_path = submission_dir / "metadata.json"
    response_path = submission_dir / "episode_service_response.json"
    episodes_path = submission_dir / "episodes.csv"
    fetch_manifest_path = submission_dir / "manifest.csv"
    archive_path = submission_dir / "v113_submission_55933145_battle_logs.zip"
    required = (
        metadata_path,
        response_path,
        episodes_path,
        fetch_manifest_path,
        archive_path,
        treatment_archive,
        control_archive,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing required existing snapshot files: {missing}")

    metadata = _json(metadata_path)
    raw_response = _json(response_path)
    indexes = _raw_indexes(raw_response)
    csv_rows = _read_csv(episodes_path)
    fetch_rows = _read_csv(fetch_manifest_path)
    episode_ids = sorted(indexes["episodes"])
    csv_ids = sorted(int(row["episode_id"]) for row in csv_rows)
    fetch_ids = sorted(int(row["episode_id"]) for row in fetch_rows)
    replay_files = sorted(replay_dir.glob("episode_*.json"))
    replay_ids = sorted(int(path.stem.removeprefix("episode_")) for path in replay_files)
    if not episode_ids or episode_ids != csv_ids or episode_ids != fetch_ids or episode_ids != replay_ids:
        raise RuntimeError(
            "EpisodeService, episodes.csv, fetch manifest, and replay IDs do not form one complete snapshot"
        )

    replay_rows = []
    integrity_errors: list[dict[str, object]] = []
    for episode_id in episode_ids:
        path = replay_dir / f"episode_{episode_id}.json"
        replay = _json(path)
        info = replay.get("info") if isinstance(replay.get("info"), dict) else {}
        stored_id = _int(info.get("EpisodeId"))
        steps = replay.get("steps")
        step_count = len(steps) if isinstance(steps, list) else 0
        if stored_id != episode_id or step_count != 720:
            integrity_errors.append(
                {
                    "episode_id": episode_id,
                    "replay_id": stored_id,
                    "step_count": step_count,
                }
            )
        replay_rows.append(
            {
                "episode_id": episode_id,
                "path": _relative(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "step_count": step_count,
            }
        )
    fetch_errors = [row for row in fetch_rows if row.get("error")]
    if integrity_errors or fetch_errors:
        raise RuntimeError(
            f"existing snapshot failed integrity audit: replay={integrity_errors}, fetch={fetch_errors}"
        )

    source_files = []
    for path in (
        metadata_path,
        response_path,
        episodes_path,
        fetch_manifest_path,
        archive_path,
        treatment_archive,
        control_archive,
    ):
        source_files.append(
            {
                "path": _relative(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    manifest = {
        "format": "kaggriculture-v113-live-e6-immutable-raw-manifest-v1",
        "submission_id": SUBMISSION_ID,
        "snapshot_fetched_at_utc": metadata.get("fetched_at_utc"),
        "episode_source": metadata.get("episode_source"),
        "replay_source_template": metadata.get("replay_source_template"),
        "reported_rating_at_fetch": metadata.get("reported_rating"),
        "coverage": {
            "episode_service_rows": len(episode_ids),
            "episode_csv_rows": len(csv_ids),
            "fetch_manifest_rows": len(fetch_ids),
            "replays": len(replay_ids),
            "replays_with_720_states": sum(row["step_count"] == 720 for row in replay_rows),
            "fetch_errors": len(fetch_errors),
        },
        "source_files": source_files,
        "replays": replay_rows,
        "immutability_note": (
            "This file hashes the already-complete 2026-09-01 snapshot. The analyzer does not call Kaggle "
            "or overwrite source replays. A later ladder refresh must use a new snapshot/addendum path."
        ),
    }
    return manifest, raw_response


def reuse_raw_manifest(
    path: Path,
    submission_dir: Path,
    *,
    verify_all_replay_hashes: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reuse the completed audit; always check sizes and optionally all 1.68 GB of hashes."""
    manifest = _json(path)
    if manifest.get("submission_id") != SUBMISSION_ID:
        raise RuntimeError(f"immutable manifest has wrong submission id: {path}")
    for row in manifest.get("source_files") or []:
        source = ROOT / str(row["path"])
        if not source.is_file() or source.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"immutable source file size changed: {source}")
        if _sha256(source) != row["sha256"]:
            raise RuntimeError(f"immutable source file hash changed: {source}")
    for row in manifest.get("replays") or []:
        replay = ROOT / str(row["path"])
        if not replay.is_file() or replay.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"immutable replay file size changed: {replay}")
        if verify_all_replay_hashes and _sha256(replay) != row["sha256"]:
            raise RuntimeError(f"immutable replay hash changed: {replay}")
    raw_response = _json(submission_dir / "episode_service_response.json")
    return manifest, raw_response


def _safe_extract(archive_path: Path, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root) or member.issym() or member.islnk():
                raise ValueError(f"unsafe archive member: {member.name}")
        archive.extractall(destination, members=members)  # noqa: S202 - paths validated above


def _load_agent(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import submitted agent: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _portfolio(farm: dict[str, Any]) -> dict[str, int]:
    result = Counter()
    for row in farm.get("tiles") or []:
        tiles = [row] if isinstance(row, dict) else row or []
        for tile in tiles:
            if not isinstance(tile, dict):
                continue
            for key in ("animal", "crop"):
                value = tile.get(key)
                if value:
                    result[str(value)] += 1
    return dict(result)


def _farms(replay: dict[str, Any], step: int, seat: int) -> tuple[dict[str, Any], dict[str, Any]]:
    obs = observation(replay, step, seat) or {}
    farms = obs.get("farms") or []
    own = farms[seat] if seat < len(farms) and isinstance(farms[seat], dict) else {}
    other = farms[1 - seat] if 1 - seat < len(farms) and isinstance(farms[1 - seat], dict) else {}
    return own, other


def _snapshot(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    obs = observation(replay, min(step, len(replay.get("steps") or []) - 1), seat) or {}
    own, other = _farms(replay, step, seat)
    town = obs.get("town") or {}
    own_portfolio = _portfolio(own)
    opponent_portfolio = _portfolio(other)
    return {
        "step": step,
        "own_money": float(own.get("money", 0.0) or 0.0),
        "opponent_money": float(other.get("money", 0.0) or 0.0),
        "money_margin": float(own.get("money", 0.0) or 0.0) - float(other.get("money", 0.0) or 0.0),
        "shops": [str(value) for value in town.get("unlocked_shops") or []],
        "own_cow": int(own_portfolio.get("COW", 0)),
        "own_sheep": int(own_portfolio.get("SHEEP", 0)),
        "opponent_cow": int(opponent_portfolio.get("COW", 0)),
        "opponent_sheep": int(opponent_portfolio.get("SHEEP", 0)),
    }


def _market_summary(replay: dict[str, Any], seat: int) -> dict[str, Any]:
    requested: Counter[tuple[str, str]] = Counter()
    sell_steps: defaultdict[str, list[int]] = defaultdict(list)
    sell_by_period: Counter[tuple[str, str]] = Counter()
    period_edges = (("day0_11", 0, 288), ("day12_17", 288, 432), ("day18_23", 432, 576), ("day24_29", 576, 720))
    for step in range(decision_count(replay)):
        emitted = action(replay, step, seat)
        for row in emitted.get("market") or []:
            if not isinstance(row, list) or not row:
                continue
            operation = str(row[0])
            item = str(row[1]) if len(row) >= 2 else ""
            if item not in PREMIUM_ITEMS:
                continue
            quantity_requested = (
                int(row[-1]) if len(row) >= 3 and isinstance(row[-1], int | float) else 1
            )
            requested[operation, item] += quantity_requested
            if operation == "SELL" and quantity_requested:
                sell_steps[item].append(step)
                for period, start, end in period_edges:
                    if start <= step < end:
                        sell_by_period[item, period] += quantity_requested
                        break

    operations = sorted({operation for operation, _ in requested})
    by_operation = {
        operation: {
            item: {"requested": requested[operation, item]}
            for item in sorted(PREMIUM_ITEMS)
            if requested[operation, item]
        }
        for operation in operations
    }
    return {
        "quantity_basis": (
            "Recorded requested orders. Engine-committed quantities are not inferred for generic premium orders."
        ),
        "by_operation": by_operation,
        "sell_timing": {
            item: {
                "first_step": min(steps),
                "last_step": max(steps),
                "order_turns": len(steps),
                "requested_by_period": {
                    period: sell_by_period[item, period] for period, _, _ in period_edges
                },
            }
            for item, steps in sorted(sell_steps.items())
        },
    }


def _single_cow_to_sheep_rewrite(control: dict[str, Any], treatment: dict[str, Any]) -> bool:
    if control.get("farmer") != treatment.get("farmer") or control.get("hands") != treatment.get("hands"):
        return False
    left = copy.deepcopy(control.get("market") or [])
    right = copy.deepcopy(treatment.get("market") or [])
    if len(left) != len(right):
        return False
    differences = [index for index, (a, b) in enumerate(zip(left, right, strict=True)) if a != b]
    if len(differences) != 1:
        return False
    index = differences[0]
    return left[index] == ["BUY_ANIMAL", "COW", 2] and right[index] == ["BUY_ANIMAL", "SHEEP", 2]


def _has_order(value: dict[str, Any], operation: str, item: str, quantity: int) -> bool:
    return any(
        isinstance(row, list)
        and len(row) >= 3
        and row[0] == operation
        and row[1] == item
        and _int(row[2]) == quantity
        for row in value.get("market") or []
    )


def _normalized_action_token(value: dict[str, Any], *, field_only: bool) -> str:
    """Remove numeric quantities while retaining ordered route/operation semantics."""

    def normalized(row: object) -> list[str]:
        if not isinstance(row, list | tuple) or not row:
            return ["PASS"]
        return [str(cell) for cell in row if not isinstance(cell, int | float)]

    actors = [value.get("farmer") or ["PASS"], *(value.get("hands") or [])]
    payload: dict[str, Any] = {"field": [normalized(row) for row in actors]}
    if not field_only:
        payload["market"] = [normalized(row) for row in value.get("market") or []]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalized_action_stream(replay: dict[str, Any], seat: int, *, field_only: bool) -> list[str]:
    return [
        _normalized_action_token(action(replay, step, seat), field_only=field_only)
        for step in range(decision_count(replay))
    ]


def _prefix_hashes(tokens: list[str]) -> dict[str, str]:
    result = {}
    for checkpoint in CHECKPOINTS:
        digest = hashlib.sha256()
        for token in tokens[:checkpoint]:
            digest.update(token.encode("utf-8"))
            digest.update(b"\n")
        result[str(checkpoint)] = digest.hexdigest()[:20]
    return result


def _gate_nonconversion_reason(
    treatment_action: dict[str, Any],
    control_action: dict[str, Any],
    treatment_diagnostics: dict[str, Any],
    replay: dict[str, Any],
    seat: int,
) -> str:
    if _has_order(control_action, "BUY_ANIMAL", "SHEEP", 2):
        return "already_satisfied_by_v111_route"
    fallback = str(treatment_diagnostics.get("strategy_fallback_reason") or "")
    if fallback == "late-sheep-cash-reserve":
        return "cash_reserve_revalidation_failed"
    if fallback == "unexpected-late-purchase-action":
        if not _has_order(control_action, "BUY_ANIMAL", "COW", 2):
            return "baseline_purchase_slot_absent"
        return "unexpected_purchase_action_shape"
    own, _ = _farms(replay, 248, seat)
    if float(own.get("money", 0.0) or 0.0) < 1500.0:
        return "cash_below_1500"
    if _has_order(treatment_action, "BUY_ANIMAL", "SHEEP", 2):
        return "not_incremental_against_control"
    return "other_no_incremental_conversion"


def _owned_animal_total(replay: dict[str, Any], step: int, seat: int, animal: str) -> int:
    obs = observation(replay, step, seat) or {}
    farms = obs.get("farms") or []
    farm = farms[seat] if seat < len(farms) and isinstance(farms[seat], dict) else {}
    total = int(_portfolio(farm).get(animal, 0))
    private = obs.get("private") or {}
    total += int((private.get("shed") or {}).get(animal, 0) or 0)
    total += sum(
        int(inventory.get(animal, 0) or 0)
        for inventory in private.get("inventories") or []
        if isinstance(inventory, dict)
    )
    return total


def _transaction_audit(
    replay: dict[str, Any],
    seat: int,
    strategy_counts: dict[str, Any],
) -> dict[str, Any]:
    emitted_purchase = int(strategy_counts.get("cow-to-sheep-purchase", 0) or 0) > 0
    sheep_before = _owned_animal_total(replay, 248, seat, "SHEEP")
    sheep_after = _owned_animal_total(replay, 249, seat, "SHEEP")
    purchase_units_committed = max(0, sheep_after - sheep_before)
    own_at_purchase, _ = _farms(replay, 248, seat)
    initial_field_sheep = int(_portfolio(own_at_purchase).get("SHEEP", 0))
    maximum_field_sheep = initial_field_sheep
    for step in range(249, 720):
        own, _ = _farms(replay, step, seat)
        maximum_field_sheep = max(maximum_field_sheep, int(_portfolio(own).get("SHEEP", 0)))
    observed_field_increase = max(0, maximum_field_sheep - initial_field_sheep)
    emitted_pickups = int(strategy_counts.get("cow-to-sheep-pickup", 0) or 0)
    emitted_placements = int(strategy_counts.get("cow-to-sheep-place", 0) or 0)
    complete = (
        not emitted_purchase
        or (
            purchase_units_committed >= 2
            and emitted_pickups >= 2
            and emitted_placements >= 2
            and observed_field_increase >= 2
        )
    )
    return {
        "emitted_purchase_rewrite": emitted_purchase,
        "purchase_units_committed": purchase_units_committed,
        "emitted_pickups": emitted_pickups,
        "emitted_placements": emitted_placements,
        "observed_maximum_field_sheep_increase": observed_field_increase,
        "complete": complete,
        "method": (
            "Purchase commit is the observed total-owned Sheep increase from obs248 to obs249; placement is "
            "confirmed by emitted diagnostics plus the subsequent public field portfolio."
        ),
    }


def reconstruct_gate(
    replay: dict[str, Any],
    seat: int,
    control: Any,
    treatment: Any,
) -> dict[str, Any]:
    control.reset_runtime_state()
    treatment.reset_runtime_state()
    configuration = replay.get("configuration") or {}
    replay_mismatches: list[int] = []
    control_treatment_divergences: list[int] = []
    treatment_error: str | None = None
    control_error: str | None = None
    diagnostics_216: dict[str, Any] = {}
    diagnostics_248: dict[str, Any] = {}
    final_diagnostics: dict[str, Any] = {}
    actions_248: dict[str, dict[str, Any]] = {}

    for step in range(decision_count(replay)):
        obs = observation(replay, step, seat)
        if obs is None:
            continue
        actual = action(replay, step, seat)
        try:
            treatment_action = treatment.agent(copy.deepcopy(obs), copy.deepcopy(configuration))
        except Exception as exc:  # Preserve a reconstruction failure without hiding other episodes.
            treatment_error = f"step {step}: {type(exc).__name__}: {exc}"
            break
        try:
            control_action = control.agent(copy.deepcopy(obs), copy.deepcopy(configuration))
        except Exception as exc:
            control_error = f"step {step}: {type(exc).__name__}: {exc}"
            break
        treatment_action = treatment_action if isinstance(treatment_action, dict) else EMPTY_ACTION
        control_action = control_action if isinstance(control_action, dict) else EMPTY_ACTION
        if canonical_action(actual) != canonical_action(treatment_action):
            replay_mismatches.append(step)
        if canonical_action(control_action) != canonical_action(treatment_action):
            control_treatment_divergences.append(step)
        diagnostics = treatment.policy_diagnostics(copy.deepcopy(obs))
        if step == 216:
            diagnostics_216 = copy.deepcopy(diagnostics)
        if step == 248:
            diagnostics_248 = copy.deepcopy(diagnostics)
            actions_248 = {
                "recorded_live": copy.deepcopy(actual),
                "reconstructed_treatment": copy.deepcopy(treatment_action),
                "same_observation_control": copy.deepcopy(control_action),
            }
        final_diagnostics = copy.deepcopy(diagnostics)

    generalized_goal = diagnostics_216.get("generalized_goal")
    model = diagnostics_216.get("last_v113_model")
    gate_condition = bool(
        isinstance(model, dict)
        and model.get("in_support")
        and _number(model.get("animal_tilt")) is not None
        and float(model["animal_tilt"]) >= 1.5
    )
    armed = isinstance(generalized_goal, dict)
    recorded_248 = actions_248.get("recorded_live", {})
    treatment_248 = actions_248.get("reconstructed_treatment", {})
    control_248 = actions_248.get("same_observation_control", {})
    incremental = (
        armed
        and _single_cow_to_sheep_rewrite(control_248, treatment_248)
        and canonical_action(recorded_248) == canonical_action(treatment_248)
    )
    strategy_counts = dict(final_diagnostics.get("strategy_decision_counts") or {})
    transaction = _transaction_audit(replay, seat, strategy_counts)

    if not armed:
        cohort = "A_gate_non_trigger"
        reason = str(diagnostics_216.get("model_rejections") or {})
    elif incremental:
        cohort = "C_actual_incremental_conversion"
        reason = "incremental_cow2_to_sheep2_rewrite"
    else:
        cohort = "B_trigger_but_no_incremental_conversion"
        reason = _gate_nonconversion_reason(
            treatment_248,
            control_248,
            diagnostics_248,
            replay,
            seat,
        )
    return {
        "cohort": cohort,
        "reason_code": reason,
        "gate_condition_step216": gate_condition,
        "armed_step216": armed,
        "model_step216": model,
        "generalized_goal": generalized_goal,
        "actions_step248": actions_248,
        "first_control_treatment_divergence": (
            min(control_treatment_divergences) if control_treatment_divergences else None
        ),
        "control_treatment_divergence_steps": control_treatment_divergences,
        "actual_incremental_conversion": incremental,
        "transaction": transaction,
        "strategy_counts": strategy_counts,
        "reconstruction": {
            "submitted_treatment_action_matches": decision_count(replay) - len(replay_mismatches),
            "decisions": decision_count(replay),
            "mismatch_count": len(replay_mismatches),
            "first_mismatch": min(replay_mismatches) if replay_mismatches else None,
            "mismatch_steps": replay_mismatches[:25],
            "treatment_error": treatment_error,
            "control_error": control_error,
            "method": (
                "Frozen submitted treatment/control archives replayed sequentially on recorded live observations; "
                "the control comparison is same-observation policy reconstruction, not a closed-loop counterfactual."
            ),
        },
    }


def _cohort_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "episodes": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "win_rate": None,
            "win_score": None,
            "mean_margin": None,
            "median_margin": None,
        }
    counts = Counter(str(row["result"]) for row in records)
    return {
        "episodes": len(records),
        "wins": counts["win"],
        "draws": counts["draw"],
        "losses": counts["loss"],
        "win_rate": counts["win"] / len(records),
        "win_score": (counts["win"] + 0.5 * counts["draw"]) / len(records),
        "mean_self_coin": mean(float(row["self_final_coin"]) for row in records),
        "mean_opponent_coin": mean(float(row["opponent_final_coin"]) for row in records),
        "mean_margin": mean(float(row["margin"]) for row in records),
        "median_margin": median(float(row["margin"]) for row in records),
    }


def _rating_band_summaries(records: list[dict[str, Any]]) -> dict[str, Any]:
    predicates: dict[str, Callable[[float], bool]] = {
        "absolute_gap_le_50": lambda gap: abs(gap) <= 50.0,
        "absolute_gap_le_100": lambda gap: abs(gap) <= 100.0,
        "opponent_plus_100_or_more": lambda gap: gap >= 100.0,
        "opponent_minus_100_or_less": lambda gap: gap <= -100.0,
    }
    result = {}
    for label, predicate in predicates.items():
        selected = [row for row in records if predicate(float(row["rating_gap_opponent_minus_self"]))]
        result[label] = _cohort_summary(selected)
    result["note"] = "Requested bands are intentionally overlapping; <=50 is a subset of <=100."
    return result


def _lineage_clusters(records: list[dict[str, Any]]) -> dict[str, Any]:
    primary: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    checkpoint_groups: dict[int, defaultdict[str, list[int]]] = {
        checkpoint: defaultdict(list) for checkpoint in CHECKPOINTS
    }
    for row in records:
        signature = [row["opponent_action_fingerprints"][str(step)] for step in CHECKPOINTS]
        family = f"live_action_family_{hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:12]}"
        row["live_action_family"] = family
        primary[family].append(row)
        for checkpoint in CHECKPOINTS:
            checkpoint_groups[checkpoint][row["opponent_action_fingerprints"][str(checkpoint)]].append(
                int(row["episode_id"])
            )
    families = []
    for family, selected in primary.items():
        summary = _cohort_summary(selected)
        families.append(
            {
                "family_id": family,
                "evidence_tier": "Bronze recorded live trajectory",
                **summary,
                "episode_ids": [int(row["episode_id"]) for row in selected],
                "opponent_submission_ids": sorted({int(row["opponent_submission_id"]) for row in selected}),
                "opponent_teams": sorted({str(row["opponent_team_name"]) for row in selected}),
                "fingerprint_vector": selected[0]["opponent_action_fingerprints"],
            }
        )
    families.sort(key=lambda row: (-int(row["episodes"]), float(row["mean_margin"]), str(row["family_id"])))
    progressive = {}
    for checkpoint, grouped in checkpoint_groups.items():
        groups = sorted(grouped.values(), key=lambda rows: (-len(rows), rows))
        progressive[str(checkpoint)] = {
            "unique_prefixes": len(groups),
            "duplicate_prefix_groups": [rows for rows in groups if len(rows) > 1],
        }
    return {
        "method": (
            "Exact equality of recorded ordered actor+market action-prefix hashes. A live fingerprint is a "
            "behavioral trajectory, not executable-code identity and not a policy counterfactual."
        ),
        "checkpoints": list(CHECKPOINTS),
        "families": families,
        "family_count": len(families),
        "progressive_prefix_clusters": progressive,
    }


def _positional_similarity(left: list[str], right: list[str], checkpoint: int) -> float:
    length = min(checkpoint, len(left), len(right))
    if length <= 0:
        return 0.0
    return sum(a == b for a, b in zip(left[:length], right[:length], strict=True)) / length


def _near_action_similarities(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Retain nearest trajectory neighbors without claiming executable-family identity."""
    horizons = (100, 200, 400, 719)
    nearest: dict[int, dict[str, Any]] = {}
    strong_pairs = []
    for left_index, left in enumerate(records):
        for right_index in range(left_index + 1, len(records)):
            right = records[right_index]
            field_scores = {
                str(horizon): _positional_similarity(
                    left["_opponent_field_tokens"],
                    right["_opponent_field_tokens"],
                    horizon,
                )
                for horizon in horizons
            }
            normalized_scores = {
                str(horizon): _positional_similarity(
                    left["_opponent_normalized_tokens"],
                    right["_opponent_normalized_tokens"],
                    horizon,
                )
                for horizon in horizons
            }
            pair = {
                "left_episode_id": left["episode_id"],
                "right_episode_id": right["episode_id"],
                "left_opponent_submission_id": left["opponent_submission_id"],
                "right_opponent_submission_id": right["opponent_submission_id"],
                "field_route_positional_similarity": field_scores,
                "field_and_market_positional_similarity": normalized_scores,
            }
            for index in (left_index, right_index):
                current = nearest.get(index)
                score = field_scores["200"]
                if current is None or score > float(current["field_route_positional_similarity"]["200"]):
                    nearest[index] = pair
            if field_scores["200"] >= 0.80 or normalized_scores["200"] >= 0.80:
                strong_pairs.append(pair)
    strong_pairs.sort(
        key=lambda row: (
            -float(row["field_route_positional_similarity"]["200"]),
            -float(row["field_and_market_positional_similarity"]["200"]),
            int(row["left_episode_id"]),
            int(row["right_episode_id"]),
        )
    )
    return {
        "method": (
            "Position-wise similarity of ordered action skeletons after removing numeric quantities. "
            "This is a seed-robust route similarity diagnostic, not proof of common code."
        ),
        "horizons": list(horizons),
        "strong_pair_threshold_h200": 0.80,
        "strong_pairs": strong_pairs,
        "nearest_neighbor_by_episode": {
            str(records[index]["episode_id"]): row for index, row in sorted(nearest.items())
        },
    }


def _common_probe_matches(records: list[dict[str, Any]], common_probe: Path) -> dict[str, Any]:
    if not common_probe.is_file():
        return {
            "status": "COMMON_PROBE_NOT_AVAILABLE_AT_ANALYSIS_TIME",
            "path": _relative(common_probe),
            "matches": [],
        }
    probe = _json(common_probe)
    candidate_to_family = {}
    for family in (probe.get("clustering") or {}).get("exact_families") or []:
        for member in family.get("source_members") or []:
            candidate_to_family[str(member)] = str(family.get("behavior_family_id") or "")
    games = [row for row in probe.get("games") or [] if isinstance(row, dict)]
    matches = []
    for live in records:
        by_candidate: defaultdict[str, set[int]] = defaultdict(set)
        matched_probe_games: defaultdict[str, set[tuple[int, int]]] = defaultdict(set)
        for game in games:
            candidate = str(game.get("candidate_id") or "")
            fingerprint = game.get("opponent_fingerprint") or {}
            for checkpoint in CHECKPOINTS:
                if fingerprint.get(str(checkpoint)) == live["opponent_action_fingerprints"][str(checkpoint)]:
                    by_candidate[candidate].add(checkpoint)
                    matched_probe_games[candidate].add(
                        (int(game.get("requested_seed", 0)), int(game.get("champion_seat", -1)))
                    )
        for candidate, checkpoints in sorted(by_candidate.items()):
            matches.append(
                {
                    "live_episode_id": live["episode_id"],
                    "live_opponent_submission_id": live["opponent_submission_id"],
                    "candidate_id": candidate,
                    "gold_behavior_family_id": candidate_to_family.get(candidate),
                    "exact_matching_checkpoints": sorted(checkpoints),
                    "matched_probe_seed_seats": [
                        {"seed": seed, "champion_seat": seat}
                        for seed, seat in sorted(matched_probe_games[candidate])
                    ],
                    "interpretation": (
                        "Exact recorded prefix match to an executable probe trajectory. The executable source "
                        "retains its Gold status; the single live trajectory remains Bronze correspondence evidence."
                    ),
                }
            )
    return {
        "status": "MATCHED" if matches else "NO_EXACT_PREFIX_MATCH",
        "path": _relative(common_probe),
        "sha256": _sha256(common_probe),
        "matches": matches,
    }


def _episode_record(
    episode: dict[str, Any],
    replay: dict[str, Any],
    indexes: dict[str, Any],
    control: Any,
    treatment: Any,
) -> dict[str, Any]:
    episode_id = int(episode["id"])
    agents = [row for row in episode.get("agents") or [] if isinstance(row, dict)]
    seat = _agent_index(agents, SUBMISSION_ID)
    if seat not in (0, 1):
        raise ValueError(f"cannot locate submission {SUBMISSION_ID} in episode {episode_id}")
    opponent_seat = 1 - seat
    indexed_agents: dict[int, dict[str, Any]] = {}
    for position, row in enumerate(agents[:2]):
        index = _int(row.get("index"))
        indexed_agents[index if index in (0, 1) else position] = row
    own_agent = indexed_agents[seat]
    opponent_agent = indexed_agents[opponent_seat]
    own_reward = float(own_agent.get("reward", 0.0) or 0.0)
    opponent_reward = float(opponent_agent.get("reward", 0.0) or 0.0)
    opponent_submission = int(opponent_agent["submissionId"])
    opponent_team_id = _int(opponent_agent.get("teamId"))
    opponent_team = indexes["teams"].get(opponent_team_id or -1, {})
    own_initial = float(own_agent.get("initialScore", 0.0) or 0.0)
    opponent_initial = float(opponent_agent.get("initialScore", 0.0) or 0.0)
    score = result_score(own_reward, opponent_reward)
    snapshots = {
        label: _snapshot(replay, step, seat) for label, step in MARGIN_CHECKPOINTS.items()
    }
    portfolio_trajectory = {
        str(step): _snapshot(replay, step, seat) for step in PORTFOLIO_STEPS
    }
    gate = reconstruct_gate(replay, seat, control, treatment)
    final_shops = list((_snapshot(replay, 719, seat)).get("shops") or [])
    margin = own_reward - opponent_reward
    opponent_tokens = _normalized_action_stream(replay, opponent_seat, field_only=False)
    opponent_field_tokens = _normalized_action_stream(replay, opponent_seat, field_only=True)
    return {
        "episode_id": episode_id,
        "create_time": str(episode.get("createTime") or ""),
        "end_time": str(episode.get("endTime") or ""),
        "episode_type": str(episode.get("type") or ""),
        "seat": seat,
        "opponent_submission_id": opponent_submission,
        "opponent_team_id": opponent_team_id,
        "opponent_team_name": _team_name(opponent_team),
        "self_initial_rating": own_initial,
        "self_updated_rating": _number(own_agent.get("updatedScore")),
        "opponent_initial_rating": opponent_initial,
        "opponent_updated_rating": _number(opponent_agent.get("updatedScore")),
        "rating_gap_opponent_minus_self": opponent_initial - own_initial,
        "rating_confidence": None,
        "result": result_label(score),
        "win_score": score,
        "self_final_coin": own_reward,
        "opponent_final_coin": opponent_reward,
        "margin": margin,
        "opponent_action_fingerprints": {
            str(checkpoint): lineage_hash(replay, opponent_seat, checkpoint) for checkpoint in CHECKPOINTS
        },
        "opponent_seed_robust_fingerprints": {
            "quantity_agnostic_field_and_market": _prefix_hashes(opponent_tokens),
            "quantity_agnostic_field_route": _prefix_hashes(opponent_field_tokens),
            "normalization": (
                "Ordered field and market operation/item tokens with numeric quantities removed; "
                "the field-route variant also removes market orders."
            ),
        },
        "town_regime": {
            "final_shop_sequence": final_shops,
            "signature": "|".join(final_shops),
            "checkpoints": {label: row["shops"] for label, row in snapshots.items()},
        },
        "checkpoint_money_margins": {label: row["money_margin"] for label, row in snapshots.items()},
        "lead_to_loss": {
            label: row["money_margin"] > 0 and margin < 0 for label, row in snapshots.items()
        },
        "behind_to_win": {
            label: row["money_margin"] < 0 and margin > 0 for label, row in snapshots.items()
        },
        "premium_market_behavior": {
            "self": _market_summary(replay, seat),
            "opponent": _market_summary(replay, opponent_seat),
        },
        "cow_sheep_portfolio_trajectory": portfolio_trajectory,
        "generalized_cow_sheep_gate": gate,
        "_opponent_normalized_tokens": opponent_tokens,
        "_opponent_field_tokens": opponent_field_tokens,
    }


def _rating_continuity(records: list[dict[str, Any]]) -> dict[str, Any]:
    discontinuities = []
    for previous, current in zip(records, records[1:], strict=False):
        previous_updated = _number(previous.get("self_updated_rating"))
        current_initial = _number(current.get("self_initial_rating"))
        if previous_updated is None or current_initial is None:
            continue
        if not math.isclose(previous_updated, current_initial, abs_tol=1e-8):
            discontinuities.append(
                {
                    "previous_episode_id": previous["episode_id"],
                    "previous_updated_rating": previous_updated,
                    "current_episode_id": current["episode_id"],
                    "current_initial_rating": current_initial,
                    "difference": current_initial - previous_updated,
                }
            )
    return {
        "ordered_by": "EpisodeService createTime, then episode id",
        "links": max(0, len(records) - 1),
        "continuous_links": max(0, len(records) - 1) - len(discontinuities),
        "discontinuities": discontinuities,
    }


def _report(summary: dict[str, Any]) -> str:
    overall = summary["live_public_performance"]
    gate = summary["gate_reconstruction"]
    lines = [
        "# V113 submission 55933145 — Live E6 addendum",
        "",
        "This addendum does not rewrite the preregistered formal result. It records post-hoc live-ladder evidence.",
        "",
        "## Separated status fields",
        "",
        f"- Preregistered experiment verdict: `{summary['status_fields']['preregistered_experiment_verdict']}`",
        f"- Current research interpretation: `{summary['status_fields']['current_research_interpretation']}`",
        f"- Live ladder evidence: `{summary['status_fields']['live_ladder_evidence']}`",
        "",
        "## Coverage and result",
        "",
        (
            f"- Raw snapshot: {summary['coverage']['raw_episodes']} episodes, all with 720 stored states "
            "and zero fetch errors."
        ),
        (
            "- Non-public/validation episodes excluded before live-field scoring: "
            f"{summary['coverage']['non_public_or_validation_episodes_excluded']}."
        ),
        (
            f"- Public live field: {overall['episodes']} episodes; "
            f"{overall['wins']}W/{overall['draws']}D/{overall['losses']}L."
        ),
        f"- Strict live win rate: {100 * overall['win_rate']:.1f}%.",
        f"- Final EpisodeService rating: {summary['rating_trajectory']['final_rating']:.3f}.",
        "- Rating confidence/uncertainty is not exposed by the saved EpisodeService response.",
        "",
        "## Performance by requested rating-gap cohort",
        "",
        "| Cohort | Games | W-D-L | WR | Mean margin |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, row in summary["rating_gap_bands"].items():
        if name == "note":
            continue
        win_rate = "n/a" if row["win_rate"] is None else f"{100 * row['win_rate']:.1f}%"
        mean_margin = "n/a" if row["mean_margin"] is None else f"{row['mean_margin']:.1f}"
        lines.append(
            f"| {name} | {row['episodes']} | {row['wins']}-{row['draws']}-{row['losses']} | "
            f"{win_rate} | {mean_margin} |"
        )
    lines.extend(
        [
            "",
            "The <=50 cohort is contained in <=100; these are intentionally overlapping diagnostics.",
            "",
            "## Generalized Cow→Sheep gate reconstruction",
            "",
            "| Cohort | Episodes | W-D-L |",
            "|---|---:|---:|",
        ]
    )
    for name, row in gate["cohorts"].items():
        lines.append(f"| {name} | {row['episodes']} | {row['wins']}-{row['draws']}-{row['losses']} |")
    lines.extend(
        [
            "",
            f"Frozen submitted-code replay fidelity: {gate['exact_policy_reproductions']}/"
            f"{overall['episodes']} episodes reproduced every recorded decision exactly.",
            "",
            "A/B/C outcome differences are descriptive and highly confounded by opponent and Town regime. "
            "They are not the causal effect of the gate.",
            "",
            "## Interpretation boundary",
            "",
            "The local formal panel and live ladder sample different opponent populations. A 58/60 easy-panel "
            "baseline and a viable live rating can therefore coexist. E6 shows that the whole submitted Agent was "
            "live-viable; it does not identify Cow→Sheep as the cause or establish V113 > V111.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    submission_dir = args.submission_dir.resolve()
    replay_dir = args.replay_dir.resolve()
    output_dir = args.output_dir.resolve()
    treatment_archive = args.treatment_archive.resolve()
    control_archive = args.control_archive.resolve()
    common_probe = args.common_probe.resolve()
    immutable_manifest_path = output_dir / "immutable_raw_manifest.json"
    if immutable_manifest_path.is_file():
        raw_manifest, raw_response = reuse_raw_manifest(
            immutable_manifest_path,
            submission_dir,
            verify_all_replay_hashes=args.verify_all_raw_hashes,
        )
    else:
        raw_manifest, raw_response = build_raw_manifest(
            submission_dir,
            replay_dir,
            treatment_archive,
            control_archive,
        )
        _write_immutable_json(immutable_manifest_path, raw_manifest)
    indexes = _raw_indexes(raw_response)
    all_episodes = sorted(
        indexes["episodes"].values(),
        key=lambda row: (str(row.get("createTime") or ""), int(row["id"])),
    )

    with ExitStack() as stack:
        treatment_tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="v113_live_treatment_")))
        control_tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="v113_live_control_")))
        _safe_extract(treatment_archive, treatment_tmp)
        _safe_extract(control_archive, control_tmp)
        treatment = _load_agent(treatment_tmp / "main.py", "_v113_live_submitted_treatment")
        control = _load_agent(control_tmp / "main.py", "_v113_live_submitted_control")
        records = []
        for index, episode in enumerate(all_episodes, start=1):
            if str(episode.get("type")) != "EPISODE_TYPE_PUBLIC":
                continue
            episode_id = int(episode["id"])
            print(f"[{index}/{len(all_episodes)}] analyze live episode {episode_id}")
            replay = _json(replay_dir / f"episode_{episode_id}.json")
            records.append(_episode_record(episode, replay, indexes, control, treatment))

    records.sort(key=lambda row: (str(row["create_time"]), int(row["episode_id"])))
    for record in records:
        is_self_play = int(record["opponent_submission_id"]) == SUBMISSION_ID
        record["analysis_role"] = (
            "self_play_validation_excluded_from_live_performance"
            if is_self_play
            else "live_field_opponent"
        )
    live_records = [
        record
        for record in records
        if record["analysis_role"] == "live_field_opponent"
    ]
    lineage = _lineage_clusters(live_records)
    near_similarities = _near_action_similarities(live_records)
    common_probe_correspondence = _common_probe_matches(live_records, common_probe)
    for record in records:
        record.pop("_opponent_normalized_tokens", None)
        record.pop("_opponent_field_tokens", None)
    rating_continuity = _rating_continuity(live_records)
    rating_rows = [
        {
            "sequence": index,
            "episode_id": row["episode_id"],
            "create_time": row["create_time"],
            "seat": row["seat"],
            "opponent_submission_id": row["opponent_submission_id"],
            "opponent_team_name": row["opponent_team_name"],
            "result": row["result"],
            "self_final_coin": row["self_final_coin"],
            "opponent_final_coin": row["opponent_final_coin"],
            "margin": row["margin"],
            "self_initial_rating": row["self_initial_rating"],
            "self_updated_rating": row["self_updated_rating"],
            "opponent_initial_rating": row["opponent_initial_rating"],
            "rating_gap_opponent_minus_self": row["rating_gap_opponent_minus_self"],
            "gate_cohort": row["generalized_cow_sheep_gate"]["cohort"],
            "gate_reason": row["generalized_cow_sheep_gate"]["reason_code"],
            "opponent_h200": row["opponent_action_fingerprints"]["200"],
            "opponent_h719": row["opponent_action_fingerprints"]["719"],
            "live_action_family": row["live_action_family"],
        }
        for index, row in enumerate(live_records, start=1)
    ]
    gate_groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    reason_groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in live_records:
        gate_row = row["generalized_cow_sheep_gate"]
        gate_groups[str(gate_row["cohort"])].append(row)
        reason_groups[str(gate_row["reason_code"])].append(row)
    gate_summary = {
        "method": (
            "Frozen submitted V113 and gate-disabled control archives replayed on recorded observations. "
            "This reconstructs branch use but is not a closed-loop causal comparison."
        ),
        "cohorts": {name: _cohort_summary(selected) for name, selected in sorted(gate_groups.items())},
        "reason_codes": {name: _cohort_summary(selected) for name, selected in sorted(reason_groups.items())},
        "exact_policy_reproductions": sum(
            row["generalized_cow_sheep_gate"]["reconstruction"]["mismatch_count"] == 0
            for row in live_records
        ),
        "episodes_with_reconstruction_error": [
            row["episode_id"]
            for row in live_records
            if row["generalized_cow_sheep_gate"]["reconstruction"]["treatment_error"]
            or row["generalized_cow_sheep_gate"]["reconstruction"]["control_error"]
        ],
        "transaction_complete_conversions": sum(
            row["generalized_cow_sheep_gate"]["actual_incremental_conversion"]
            and row["generalized_cow_sheep_gate"]["transaction"]["complete"]
            for row in live_records
        ),
    }
    final_rating = live_records[-1]["self_updated_rating"] if live_records else None
    formal = _json(FORMAL_RESULT)
    summary = {
        "format": "kaggriculture-v113-live-e6-analysis-v1",
        "submission_id": SUBMISSION_ID,
        "status_fields": {
            "preregistered_experiment_verdict": formal["evaluation"]["decision"],
            "preregistered_result_path": _relative(FORMAL_RESULT),
            "preregistered_result_sha256": _sha256(FORMAL_RESULT),
            "current_research_interpretation": "LIVE_VIABLE / CAUSAL_UNRESOLVED",
            "live_ladder_evidence": "E6_OBSERVATIONAL",
            "promotion_implication": "none_without_expanded_paired_E3_E4_and_fresh_E5",
        },
        "coverage": {
            "raw_episodes": len(all_episodes),
            "public_episode_service_rows": len(records),
            "non_public_or_validation_episodes_excluded": (
                len(all_episodes) - len(records)
            ),
            "public_live_opponent_episodes": len(live_records),
            "self_play_validation_episodes_excluded_from_live_performance": (
                len(records) - len(live_records)
            ),
            "replays_analyzed": len(records),
            "rating_confidence_available": False,
            "opponent_submission_available": all(
                row["opponent_submission_id"] for row in live_records
            ),
            "opponent_team_available": all(
                row["opponent_team_name"] for row in live_records
            ),
        },
        "public_episode_performance_before_self_play_exclusion": _cohort_summary(records),
        "live_public_performance": _cohort_summary(live_records),
        "rating_trajectory": {
            "initial_public_rating": (
                live_records[0]["self_initial_rating"] if live_records else None
            ),
            "final_rating": final_rating,
            "peak_updated_rating": max(
                float(row["self_updated_rating"]) for row in live_records
            ),
            "minimum_updated_rating": min(
                float(row["self_updated_rating"]) for row in live_records
            ),
            "continuity": rating_continuity,
            "confidence": {
                "available": False,
                "reason": "EpisodeService snapshot exposes initialScore/updatedScore but no confidence field.",
            },
        },
        "rating_gap_bands": _rating_band_summaries(live_records),
        "gate_reconstruction": gate_summary,
        "opponent_action_lineages": {
            "family_count": lineage["family_count"],
            "method": lineage["method"],
            "checkpoint_unique_prefixes": {
                step: row["unique_prefixes"] for step, row in lineage["progressive_prefix_clusters"].items()
            },
            "strong_near_similarity_pairs_h200": len(near_similarities["strong_pairs"]),
            "common_probe_correspondence_status": common_probe_correspondence["status"],
            "common_probe_exact_prefix_matches": len(common_probe_correspondence["matches"]),
            "unmatched_live_trajectories_remain": "Bronze until executable code correspondence is established",
        },
        "causal_limit": (
            "Live outcomes are Agent-level E6 observations under Kaggle matchmaking. Gate A/B/C comparisons "
            "are selected by state/opponent and cannot identify a gate treatment effect."
        ),
    }
    _write_json(output_dir / "episode_metrics.json", {"episodes": records})
    _write_json(
        output_dir / "opponent_action_lineages.json",
        {
            **lineage,
            "near_action_similarities": near_similarities,
            "common_probe_correspondence": common_probe_correspondence,
        },
    )
    _write_json(output_dir / "analysis.json", summary)
    _write_csv(output_dir / "rating_trajectory.csv", rating_rows, list(rating_rows[0]))
    (output_dir / "report.md").write_text(_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"output: {output_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission-dir", type=Path, default=DEFAULT_SUBMISSION_DIR)
    parser.add_argument("--replay-dir", type=Path, default=DEFAULT_REPLAY_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--treatment-archive", type=Path, default=DEFAULT_TREATMENT_ARCHIVE)
    parser.add_argument("--control-archive", type=Path, default=DEFAULT_CONTROL_ARCHIVE)
    parser.add_argument("--common-probe", type=Path, default=DEFAULT_COMMON_PROBE)
    parser.add_argument(
        "--verify-all-raw-hashes",
        action="store_true",
        help="Re-hash all 1.68 GB of replay JSON after the initial immutable audit.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
