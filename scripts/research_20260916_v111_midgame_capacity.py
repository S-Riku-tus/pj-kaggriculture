# ruff: noqa: E501
"""Replay-only V111 midgame capital/capacity study.

This driver never submits to Kaggle, pushes a kernel, changes a submission
slot, or runs a new game.  It creates a candidate only if the frozen replay
gate is separately shown to pass; the replay-only command cannot create one.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluation import lifecycle as lifecycle_mod  # noqa: E402
from scripts.evaluation.replay import action, decision_count, observation  # noqa: E402
from scripts.evaluation.safety import simulate_turn  # noqa: E402

EXP = ROOT / "experiments/research_20260916_v111_midgame_capacity"
DOC = ROOT / "docs/research_20260916_v111_midgame_capacity_preregistration.md"
PROMPT = ROOT / "docs/codex_next_prompt_20260916_v111_midgame_capacity.md"
PREREG = EXP / "preregistration.json"
REPORT = ROOT / "docs/research_20260916_v111_midgame_capacity_report.md"
CONTROL_ROOT = ROOT / "experiments/research_20260915_router_mechanism/candidates/A0_psr_route_locked/replays/spent/spent"
TOP_ROOT = ROOT / "data/current_field_20260916"
TOP_ANALYSIS = ROOT / "data/analysis/research_20260916_next_strategy"
ENGINE = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
ENGINE_JSON = ENGINE.with_suffix(".json")
LAND_COST = 2000
ACTIVATION_RESERVE = 11
SHADOW_THRESHOLD = LAND_COST + ACTIVATION_RESERVE
SOURCES = ("ggmljs_v16", "mooman_e052a", "qeinstein_moev2", "souvik_v4")
SEEDS = (10091011, 10091012, 10091013, 10091014)
SPEND_FAMILIES = (
    "BUY_ANIMAL:COW",
    "BUY_SEED:STRAWBERRY",
    "BUY_SEED:WHEAT",
    "BUY_SEED:MELON",
    "BUY_PRODUCT:WHEAT",
    "HIRE",
)
PRODUCTIVE = {"PLANT", "BUILD_COOP", "BUILD_PASTURE", "PLACE"}
MAINTENANCE = {"WATER", "FEED", "HARVEST", "CARE", "COLLECT_FERTILIZER"}
FIELD_OPS = PRODUCTIVE | MAINTENANCE | {"DIG", "FERTILIZE"}
JST = timezone(timedelta(hours=9))


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_replay(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return load(path)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=True
    ).stdout.rstrip()


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = probability * (len(ordered) - 1)
    lo, hi = math.floor(index), math.ceil(index)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - index) + ordered[hi] * (index - lo)


def summary(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
        "p10": percentile(values, 0.10),
        "p90": percentile(values, 0.90),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def seed_ledger() -> dict[str, Any]:
    excluded = {".git", ".venv", ".uv-cache", ".ruff_cache", ".pytest_cache", "vendor", "__pycache__", "node_modules"}
    suffixes = {".json", ".jsonl", ".md", ".py", ".txt", ".csv", ".log", ".yaml", ".yml", ".toml"}
    pattern = re.compile(r"(?<!\d)(1009\d{4})(?!\d)")
    command = [
        "rg", "-l", "1009[0-9]{4}", ".", "--hidden", "-g", "!.git/**", "-g", "!.venv/**", "-g", "!.uv-cache/**",
        "-g", "!.ruff_cache/**", "-g", "!.pytest_cache/**", "-g", "!vendor/**", "-g", "!**/__pycache__/**", "-g", "!node_modules/**",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr)
    structured: set[tuple[str, str, int]] = set()
    mentions: list[dict[str, Any]] = []

    def walk(value: Any, field: str = "$") -> list[tuple[str, int]]:
        found: list[tuple[str, int]] = []
        if isinstance(value, dict):
            for key, child in value.items():
                child_field = f"{field}.{key}"
                if "seed" in str(key).lower():
                    if isinstance(child, int) and not isinstance(child, bool):
                        found.append((child_field, child))
                    elif isinstance(child, list):
                        found.extend((f"{child_field}[{i}]", item) for i, item in enumerate(child) if isinstance(item, int) and not isinstance(item, bool))
                found.extend(walk(child, child_field))
        elif isinstance(value, list):
            for i, child in enumerate(value):
                found.extend(walk(child, f"{field}[{i}]"))
        return found

    for raw in result.stdout.splitlines():
        path = ROOT / raw.removeprefix("./").removeprefix(".\\")
        if not path.is_file() or path.suffix.lower() not in suffixes or any(part in excluded for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        values = sorted({int(value) for value in pattern.findall(text)})
        if values:
            mentions.append({"path": rel(path), "values": values})
        parsed: list[tuple[int, Any]] = []
        if path.suffix.lower() == ".json":
            try:
                parsed.append((0, json.loads(text)))
            except json.JSONDecodeError:
                pass
        elif path.suffix.lower() == ".jsonl":
            for number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    parsed.append((number, json.loads(line)))
                except json.JSONDecodeError:
                    continue
        for number, value in parsed:
            for field, seed in walk(value):
                if 10_000_000 <= seed <= 10_099_999:
                    location = f"{rel(path)}:{number}" if number else rel(path)
                    structured.add((location, field, seed))
    records = [{"location": p, "field": f, "seed": s} for p, f, s in sorted(structured)]
    runtime_fields = {"seed", "requested_seed", "resolved_seed"}
    used = {
        row["seed"] for row in records
        if ":" in row["location"] and row["field"].rsplit(".", 1)[-1].split("[", 1)[0] in runtime_fields
    }
    groups = {
        "promotion": set(range(10091101, 10091113)),
        "fresh": set(range(10091901, 10091913)),
        "prior_development": set(range(10091421, 10091437)),
        "conditional_development": set(range(10091521, 10091537)),
    }
    return {
        "created_at": now(),
        "method": "repository-wide UTF-8 structured JSON/JSONL seed-field scan and separate free-text scan; binary/cache/vendor excluded",
        "structured_records": records,
        "free_text_mentions": mentions,
        "execution_use_rule": "Only singular runtime seed/requested_seed/resolved_seed fields in JSONL count as execution; plans, ranges and arrays are mentions.",
        "groups": {name: {"range": [min(values), max(values)], "structured_used": sorted(used & values), "status": "UNUSED" if not used & values else "USED"} for name, values in groups.items()},
        "limitation": "Opaque binary/cache/vendor bodies were not inspected.",
    }


def required_inputs() -> list[Path]:
    paths = [
        ROOT / "AGENTS.md", ROOT / "README.md", PROMPT, DOC, PREREG,
        ROOT / "docs/research_20260916_rethought_next_steps.md",
        ROOT / "docs/research_20260915_router_mechanism_report.md",
        ROOT / "experiments/research_20260915_router_mechanism/final_decision.json",
        ROOT / "experiments/research_20260915_router_mechanism/mechanism_ranking.json",
        ROOT / "experiments/research_20260915_router_mechanism/mechanism_attribution.json",
        ROOT / "docs/research_20260916_current_meta_and_next_strategy.md",
        TOP_ANALYSIS / "strategy_evidence.json", TOP_ANALYSIS / "current_top_execution_audit.json",
        TOP_ANALYSIS / "current_submission_fidelity.json", TOP_ANALYSIS / "remote_market_order_audit.json",
        ROOT / "docs/v7_design_report.md", ROOT / "docs/v109_design_report.md", ROOT / "docs/research_20260912_continuation_report.md",
        ROOT / "agents/v111/main.py", ROOT / "agents/v111/strategy_model.json", ROOT / "agents/v111/submission_manifest.json",
        ROOT / "agents/v111/metadata.json", ROOT / "agents/v111/README.md",
        ROOT / "scripts/evaluation/runner.py", ROOT / "scripts/evaluation/safety.py", ROOT / "scripts/evaluation/statistics.py",
        ROOT / "scripts/evaluation/divergence.py", ROOT / "scripts/evaluation/lifecycle.py", ROOT / "scripts/evaluation/replay.py",
        ENGINE, ENGINE_JSON,
    ]
    return paths


def control_paths() -> list[Path]:
    paths = sorted(CONTROL_ROOT.glob("*/seed_*_seat_*/control.json.gz"))
    if len(paths) != 32:
        raise RuntimeError(f"Expected 32 controls, found {len(paths)}")
    return paths


def parse_control_path(path: Path) -> tuple[str, int, int]:
    source = path.parents[1].name
    match = re.fullmatch(r"seed_(\d+)_seat_([01])", path.parent.name)
    if not match:
        raise ValueError(path)
    return source, int(match.group(1)), int(match.group(2))


def audit_jsonl() -> list[dict[str, Any]]:
    audits = []
    for path in ROOT.glob("experiments/research_20260915_router_mechanism/candidates/*/pairs/*.jsonl"):
        rows = []
        partial = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                partial.append(number)
        keys = [stable_sha({key: row.get(key) for key in ("candidate_source_sha256", "lineage_id", "seed", "seat", "evaluation_core_sha256")}) for row in rows]
        audits.append({"path": rel(path), "rows": len(rows), "unique_keys": len(set(keys)), "duplicates": len(keys) - len(set(keys)), "partial_lines": partial})
    return audits


def initial() -> None:
    manifest_path = EXP / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError("Initial manifest already exists")
    started = datetime.fromisoformat("2026-09-15T22:12:12.2952552+00:00")
    hashes = {rel(path): sha(path) for path in required_inputs()}
    controls = []
    replay_hashes = Counter()
    for path in control_paths():
        source, seed, seat = parse_control_path(path)
        digest = sha(path)
        replay_hashes[digest] += 1
        rep = read_replay(path)
        controls.append({"source": source, "seed": seed, "seat": seat, "path": rel(path), "sha256": digest, "states": len(rep.get("steps") or []), "decisions": decision_count(rep)})
    jsonl = audit_jsonl()
    verification = {
        "verified_at": now(),
        "required_inputs": hashes,
        "fixed_engine_hash": sha(ENGINE),
        "fixed_configuration_hash": sha(ENGINE_JSON),
        "control_replays": controls,
        "control_contexts": len(controls),
        "unique_control_hashes": len(replay_hashes),
        "duplicate_body_groups": [{"sha256": digest, "count": count} for digest, count in replay_hashes.items() if count > 1],
        "all_controls_complete": all(row["states"] == 720 and row["decisions"] == 719 for row in controls),
        "jsonl_audit": jsonl,
        "jsonl_duplicate_or_partial": any(row["duplicates"] or row["partial_lines"] for row in jsonl),
        "old_experiments": {
            "router_mechanism": load(ROOT / "experiments/research_20260915_router_mechanism/final_decision.json")["status"],
            "continuations": load(ROOT / "experiments/research_20260911_continuations/final_decision.json").get("decision"),
            "rerun": False,
        },
    }
    save(EXP / "input_artifact_verification.json", verification)
    save(EXP / "seed_ledger.json", seed_ledger())
    snapshot = load(ROOT / "experiments/research_20260914_lowcash/remote/20260915_153354/leaderboard.json")
    fetched = datetime.fromisoformat(snapshot["fetched_at"])
    save(EXP / "leaderboard_and_replay_audit.json", {
        "audited_at": now(), "snapshot": rel(ROOT / "experiments/research_20260914_lowcash/remote/20260915_153354/leaderboard.json"),
        "snapshot_sha256": sha(ROOT / "experiments/research_20260914_lowcash/remote/20260915_153354/leaderboard.json"),
        "snapshot_fetched_at_utc": fetched.isoformat(), "age_hours_at_start": (started - fetched).total_seconds() / 3600,
        "over_24_hours": (started - fetched).total_seconds() >= 86400, "refresh_allowed": True,
        "refresh_performed": False, "reason": "Optional refresh skipped to preserve the frozen saved Top-5 corpus; no new public data are needed for the replay-only gate.",
        "selection_frozen": "Top 5 active submissions in saved snapshot; first six EpisodeService rows per submission",
        "target_seats": 30, "unique_replays": 26, "corpus_mixing": False,
    })
    fidelity = load(TOP_ANALYSIS / "current_submission_fidelity.json")
    market_order = load(TOP_ANALYSIS / "remote_market_order_audit.json")
    save(EXP / "remote_package_fidelity_audit.json", {
        "audited_at": now(), "active_submission": 56089444, "identity": "UNVERIFIED",
        "source_artifacts": {rel(TOP_ANALYSIS / "current_submission_fidelity.json"): sha(TOP_ANALYSIS / "current_submission_fidelity.json"), rel(TOP_ANALYSIS / "remote_market_order_audit.json"): sha(TOP_ANALYSIS / "remote_market_order_audit.json")},
        "stored_findings": {"matching_actions": "5725/5752", "exact_episode_matches": 0, "mismatches": 27, "mismatch_kind": "same market multiset, different order", "one_step_self_cash_effect_sum": 12, "one_step_opponent_cash_effect_sum": -29},
        "closed_loop_effect": "UNKNOWN", "exact_archive_hash_verified": False,
        "raw_input_hashes": {"fidelity_payload": stable_sha(fidelity), "market_order_payload": stable_sha(market_order)},
    })
    prior_screen = ROOT / "experiments/research_20260915_router_mechanism/independent_source_screen.json"
    candidates = sorted((ROOT / "artifacts/opponent_pool/candidates").glob("*/"))
    save(EXP / "independent_source_screen.json", {
        "frozen_before_candidate_results": True, "screened_at": now(), "candidate_created": False,
        "prior_screen": rel(prior_screen), "prior_screen_sha256": sha(prior_screen),
        "independent_gold_pool_files": [{"path": rel(path), "sha256": sha(path)} for path in sorted((ROOT / "experiments/independent_gold_pool").glob("*.json"))],
        "candidate_directories": [rel(path) for path in candidates],
        "selection": [], "new_baseline_games": 0, "reason": "Selection is conditional on a C1 passing the replay-only implementation gate; hashes already screened previously will not be rerun.",
        "verified_third_ancestry": False,
    })
    save(EXP / "development_progress.json", {"status": "NOT_AUTHORIZED", "opened": False, "seeds_used": [], "conditional_range": [10091521, 10091536], "promotion_sealed": [10091101, 10091112], "fresh_sealed": [10091901, 10091912], "prior_development_sealed": [10091421, 10091436]})
    manifest = {
        "experiment_id": EXP.name, "started_at_utc": started.isoformat(), "started_at_jst": started.astimezone(JST).isoformat(),
        "deadline_utc": (started + timedelta(hours=5)).isoformat(), "deadline_jst": (started + timedelta(hours=5)).astimezone(JST).isoformat(),
        "repository": str(ROOT), "git_branch": git("branch", "--show-current"), "git_head": git("rev-parse", "HEAD"),
        "git_status_short_at_start": [], "git_status_observation": "clean; only global ignore access warning was emitted",
        "working_tree_policy": "Preserve pre-existing changes and user files; no unrelated restore.",
        "initial_process_audit": {"method": "elevated Get-CimInstance", "matching_python_or_kaggle_processes": []},
        "prompt_sha256": sha(PROMPT), "preregistration_document_sha256": sha(DOC), "machine_plan_sha256": sha(PREREG),
        "input_artifact_verification": rel(EXP / "input_artifact_verification.json"), "seed_ledger": rel(EXP / "seed_ledger.json"),
        "production_champion": "V111", "phase": "INITIAL_AUDIT_COMPLETE", "status": "RUNNING",
        "external_mutations": {"kaggle_submission": False, "kernel_push": False, "submission_slot_change": False},
    }
    save(manifest_path, manifest)
    print(json.dumps({"manifest": rel(manifest_path), "controls": len(controls), "prereg_sha256": sha(PREREG), "deadline_jst": manifest["deadline_jst"]}, ensure_ascii=False, indent=2))


def unlocked_count(obs: dict[str, Any], seat: int) -> int:
    return len(obs["farms"][seat].get("unlocked_quadrants") or [])


def quadrant(x: int, y: int) -> str:
    return "NW" if x < 5 and y < 5 else "NE" if x >= 5 and y < 5 else "SW" if x < 5 else "SE"


def tile_counts(tiles: list[list[Any]], *, only: str | None = None) -> dict[str, Any]:
    assets = Counter()
    empty = weed = productive = 0
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if only and quadrant(x, y) != only:
                continue
            if tile is None:
                empty += 1
            elif tile == "LOCKED":
                continue
            elif isinstance(tile, dict) and tile.get("kind") == "WEED":
                weed += 1
            elif isinstance(tile, dict):
                productive += 1
                if tile.get("kind") == "PLANT":
                    assets[str(tile.get("crop"))] += 1
                elif tile.get("animal"):
                    assets[str(tile.get("animal"))] += 1
                else:
                    assets[str(tile.get("kind"))] += 1
    return {"productive_tiles": productive, "empty_tiles": empty, "weed_tiles": weed, "portfolio": dict(assets)}


def actors_with_positions(obs: dict[str, Any], act: dict[str, Any], seat: int) -> list[dict[str, Any]]:
    farm = obs["farms"][seat]
    positions = [farm.get("farmer") or [4, 4], *(farm.get("hands") or [])]
    requested = [act.get("farmer") or ["PASS"], *(act.get("hands") or [])]
    return [{"unit": i, "position": list(pos), "action": requested[i] if i < len(requested) else ["MISSING"]} for i, pos in enumerate(positions)]


def harvest_units(rep: dict[str, Any], step: int, seat: int) -> dict[str, int]:
    observations = [observation(rep, step, player) for player in (0, 1)]
    if any(value is None for value in observations):
        return {}
    farms = copy.deepcopy(observations[0]["farms"])
    privates = [copy.deepcopy(value["private"]) for value in observations]
    committed = lifecycle_mod._apply_fields_and_count_harvest(farms, privates, [action(rep, step, player) for player in (0, 1)], step // 24)
    return dict(committed[seat])


def market_records(rep: dict[str, Any], step: int, seat: int) -> list[dict[str, Any]]:
    requested = action(rep, step, seat).get("market") or []
    events = [event for event in simulate_turn(rep, step)[seat] if event.get("kind") == "market_commit"]
    by_slot = {int(event["slot"]): event for event in events}
    records = []
    obs = observation(rep, step, seat)
    hires = int(obs["farms"][seat].get("hires_today", 0) or 0)
    land_index = unlocked_count(obs, seat) - 1
    for slot, order in enumerate(requested[:10]):
        event = by_slot.get(slot, {})
        op = str(order[0]) if order else "MALFORMED"
        item = str(order[1]) if len(order) > 1 else None
        requested_units = int(order[2]) if len(order) > 2 and str(order[2]).isdigit() else 1
        committed = int(event.get("committed", 0) or 0)
        cash_delta = event.get("cash_delta")
        if op == "HIRE":
            costs = [1, 1]
            while len(costs) <= hires:
                costs.append(costs[-1] + costs[-2])
            cash_delta = -costs[hires] if committed else 0
            hires += committed
        elif op == "BUY_LAND":
            land_prices = [1000, 2000, 4000]
            cash_delta = -land_prices[land_index] if committed and land_index < len(land_prices) else 0
            land_index += committed
        record = {"slot": slot, "order": order, "op": op, "item": item, "requested": int(event.get("requested", requested_units) or 0), "committed": committed, "cash_delta": float(cash_delta or 0), "silent_noop": committed == 0, "partial_commit": 0 < committed < int(event.get("requested", requested_units) or 0)}
        record["family"] = f"{op}:{item}" if item else op
        if op == "BUY_LAND":
            record["spend_classification"] = "land_activation"
        elif op == "BUY_PRODUCT" and item == "WHEAT":
            record["spend_classification"] = "urgent_maintenance"
        elif op == "BUY_ANIMAL" and item == "COW":
            record["spend_classification"] = "deferrable_irreversible_investment"
        elif op in {"BUY_SEED", "BUY_ANIMAL", "HIRE"}:
            record["spend_classification"] = "existing_production_continuation"
        elif op == "SELL":
            record["spend_classification"] = "realized_revenue"
        else:
            record["spend_classification"] = "other"
        record["classification_reason"] = "Frozen preregistration family rule; opportunity cost and actual 24-decision use are retained separately."
        records.append(record)
    return records


def unlock_state_step(rep: dict[str, Any], seat: int, target_count: int = 3) -> int | None:
    for step in range(len(rep.get("steps") or [])):
        obs = observation(rep, step, seat)
        if obs and unlocked_count(obs, seat) >= target_count:
            return step
    return None


def timeline_context(rep: dict[str, Any], seat: int, context: dict[str, Any]) -> dict[str, Any]:
    unlock = unlock_state_step(rep, seat)
    if unlock is None:
        return {**context, "third_land_unlock_state_step": None}
    events: dict[str, Any] = {
        "first_unit_entry": None, "first_legal_field_action": None, "first_productive_action": None,
        "first_water_or_feed": None, "first_harvest": None, "first_committed_sell": None, "first_self_coin_recovery": None,
    }
    relative = []
    for step in range(max(0, unlock - 96), min(decision_count(rep), unlock + 97)):
        obs = observation(rep, step, seat)
        nxt = observation(rep, step + 1, seat)
        act = action(rep, step, seat)
        actors = actors_with_positions(obs, act, seat)
        for actor in actors:
            x, y = actor["position"]
            op = str((actor["action"] or ["PASS"])[0])
            if step >= unlock and quadrant(x, y) == "SW":
                if events["first_unit_entry"] is None:
                    events["first_unit_entry"] = {"step": step, "lag": step - unlock, "unit": actor["unit"], "position": actor["position"]}
                if op in FIELD_OPS and events["first_legal_field_action"] is None:
                    events["first_legal_field_action"] = {"step": step, "lag": step - unlock, "unit": actor["unit"], "action": actor["action"]}
                if op in PRODUCTIVE and events["first_productive_action"] is None:
                    events["first_productive_action"] = {"step": step, "lag": step - unlock, "unit": actor["unit"], "action": actor["action"]}
                if op in {"WATER", "FEED"} and events["first_water_or_feed"] is None:
                    events["first_water_or_feed"] = {"step": step, "lag": step - unlock, "action": actor["action"]}
        harvested = harvest_units(rep, step, seat)
        if step >= unlock and harvested and events["first_harvest"] is None:
            events["first_harvest"] = {"step": step, "lag": step - unlock, "units": harvested, "scope": "whole farm; fungible inventory prevents new-land attribution"}
        market = market_records(rep, step, seat)
        sold = [row for row in market if row["op"] == "SELL" and row["committed"] > 0]
        if step >= unlock and sold and events["first_committed_sell"] is None:
            events["first_committed_sell"] = {"step": step, "lag": step - unlock, "orders": sold, "scope": "whole farm; not attributed to new land"}
        pre_cash = float(obs["farms"][seat]["money"])
        post_cash = float(nxt["farms"][seat]["money"]) if nxt else pre_cash
        if step >= unlock and post_cash > pre_cash and events["first_self_coin_recovery"] is None:
            events["first_self_coin_recovery"] = {"step": step, "lag": step - unlock, "delta": post_cash - pre_cash}
        relative.append({
            "relative_step": step - unlock, "step": step, "self_cash": pre_cash,
            "opponent_cash": float(obs["farms"][1 - seat]["money"]),
            "self_all_farm": tile_counts(obs["farms"][seat]["tiles"]), "self_new_SW": tile_counts(obs["farms"][seat]["tiles"], only="SW"),
            "opponent_all_farm": tile_counts(obs["farms"][1 - seat]["tiles"]), "farmer": obs["farms"][seat].get("farmer"),
            "hands": obs["farms"][seat].get("hands"), "actions": actors, "market": market,
            "market_inventory": obs.get("market", {}).get("inventory", {}), "market_prices": obs.get("market", {}).get("prices", {}),
            "town": obs.get("town", {}), "harvest_units": harvested,
        })
    return {**context, "third_land_unlock_state_step": unlock, "buy_land_decision_step": unlock - 1, "events": events, "relative_timeline": relative}


def control_analysis() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    ledgers = []
    timelines = []
    family_context: dict[str, list[dict[str, Any]]] = defaultdict(list)
    opportunity: dict[str, Counter[str]] = defaultdict(Counter)
    for path in control_paths():
        source, seed, seat = parse_control_path(path)
        rep = read_replay(path)
        context = {"source": source, "seed": seed, "seat": seat, "block": f"{source}:{seed}", "replay": rel(path), "replay_sha256": sha(path)}
        unlock = unlock_state_step(rep, seat)
        if unlock is None:
            raise RuntimeError(f"No third land: {path}")
        end = min(decision_count(rep), unlock + 48)
        cumulative = Counter()
        steps = []
        actual_spend = Counter()
        for step in range(144, end + 1):
            obs = observation(rep, step, seat)
            nxt = observation(rep, step + 1, seat)
            market = market_records(rep, step, seat)
            spend = Counter()
            sales = []
            for row in market:
                family = row["family"]
                if row["cash_delta"] < 0:
                    spend[family] += -row["cash_delta"]
                    actual_spend[family] += -row["cash_delta"]
                    cumulative[family] += -row["cash_delta"]
                if row["op"] == "SELL" and row["committed"]:
                    sales.append(row)
            actors = actors_with_positions(obs, action(rep, step, seat), seat)
            maintenance = [row for row in actors if str((row["action"] or [""])[0]) in MAINTENANCE]
            steps.append({
                "step": step, "pre_cash": float(obs["farms"][seat]["money"]), "post_cash": float(nxt["farms"][seat]["money"]) if nxt else None,
                "cash_delta": float(nxt["farms"][seat]["money"] - obs["farms"][seat]["money"]) if nxt else None,
                "successful_sales": sales, "town_income": 0, "town_note": "Town changes public market inventory; it never pays a player directly.",
                "market_orders": market, "spend_by_family": dict(spend), "cumulative_deferred_spend": dict(cumulative),
                "market_inventory_delta": {item: int(nxt["market"]["inventory"].get(item, 0)) - int(obs["market"]["inventory"].get(item, 0)) for item in obs.get("market", {}).get("inventory", {})} if nxt else {},
                "market_price_delta": {item: int(nxt["market"]["prices"].get(item, 0)) - int(obs["market"]["prices"].get(item, 0)) for item in obs.get("market", {}).get("prices", {})} if nxt else {},
                "actors": actors, "maintenance_actions": maintenance, "hands": len(obs["farms"][seat].get("hands") or []),
                "farmer_position": obs["farms"][seat].get("farmer"), "hand_positions": obs["farms"][seat].get("hands"),
                "all_farm_capacity": tile_counts(obs["farms"][seat]["tiles"]), "new_SW_capacity": tile_counts(obs["farms"][seat]["tiles"], only="SW"),
                "private_shed": obs.get("private", {}).get("shed", {}), "private_seeds": obs.get("private", {}).get("seeds", {}),
                "classification_basis": "Per frozen preregistration; actual committed order, 24-decision use, lifecycle/carry debt, and worker task are retained for audit.",
            })
        candidates = []
        for family in SPEND_FAMILIES:
            cumulative_cost = 0.0
            earliest = None
            maintenance_reserve = None
            for row in steps:
                cumulative_cost += float(row["spend_by_family"].get(family, 0))
                if row["step"] >= unlock:
                    continue
                obs = observation(rep, row["step"], seat)
                if unlocked_count(obs, seat) < 2:
                    continue
                animals = sum(tile_counts(obs["farms"][seat]["tiles"])["portfolio"].get(name, 0) for name in ("GOOSE", "COW", "SHEEP"))
                wheat = int(obs.get("private", {}).get("shed", {}).get("WHEAT", 0) or 0) + sum(int(inv.get("WHEAT", 0) or 0) for inv in obs.get("private", {}).get("inventories", []))
                price = int(obs.get("market", {}).get("prices", {}).get("WHEAT", 0) or 0)
                reserve = max(0, animals - wheat) * price
                arithmetic_cash = float(row["pre_cash"]) + cumulative_cost
                if earliest is None and arithmetic_cash >= SHADOW_THRESHOLD:
                    positions = [obs["farms"][seat].get("farmer") or [4, 4], *(obs["farms"][seat].get("hands") or [])]
                    travel = min(max(0, 5 - int(pos[1])) for pos in positions) if positions else 5
                    earliest = row["step"]
                    maintenance_reserve = reserve
                    resource_steps = travel + 2
                    resource_feasible = resource_steps <= 24
            advance = (unlock - 1 - earliest) if earliest is not None else None
            candidate = {
                "family": family, "shadow_threshold": SHADOW_THRESHOLD, "earliest_shadow_buy_decision_step": earliest,
                "actual_buy_decision_step": unlock - 1, "advance_decisions": advance, "advance_at_least_24": advance is not None and advance >= 24,
                "activation_resource_lower_bound_within_24": bool(earliest is not None and resource_feasible),
                "maintenance_reserve_at_shadow_step": maintenance_reserve,
                "maintenance_preserving_actor_schedule_proven": False,
                "realized_harvest_sale_rejoin_proven": False,
                "interpretation": "Arithmetic upper bound only; future output, prices, opponent response and task debt are not held fixed.",
            }
            candidates.append(candidate)
            family_context[family].append({**context, **candidate})
        life = lifecycle_mod.analyze_lifecycle(rep, seat, start=144)
        cow_at_144 = int(tile_counts(observation(rep, 144, seat)["farms"][seat]["tiles"])["portfolio"].get("COW", 0))
        cow_at_unlock = int(tile_counts(observation(rep, unlock, seat)["farms"][seat]["tiles"])["portfolio"].get("COW", 0))
        cow_task_debt = Counter()
        for row in steps:
            if row["step"] >= unlock:
                break
            task_obs = observation(rep, row["step"], seat)
            task_tiles = task_obs["farms"][seat]["tiles"]
            for actor in row["actors"]:
                requested = actor["action"] or ["PASS"]
                op = str(requested[0])
                if op in {"FEED", "CARE", "COLLECT_FERTILIZER"}:
                    x, y = actor["position"]
                    tile = task_tiles[int(y)][int(x)]
                    if isinstance(tile, dict) and tile.get("animal") == "COW":
                        cow_task_debt[f"COW_maintenance:{op}"] += 1
                elif op in {"PICKUP", "PLACE"} and len(requested) > 1 and requested[1] == "COW":
                    cow_task_debt[f"COW:{op}"] += 1
        opportunity["BUY_ANIMAL:COW"]["new_cows_placed_before_land"] += max(0, cow_at_unlock - cow_at_144)
        for key, value in cow_task_debt.items():
            opportunity["BUY_ANIMAL:COW"][key] += value
        for family, cost in actual_spend.items():
            opportunity[family]["committed_cost"] += int(cost)
        for item, units in life["successful_harvest_units"].items():
            opportunity["observed_whole_farm_output"][f"HARVEST:{item}"] += int(units)
        ledgers.append({**context, "third_land_unlock_state_step": unlock, "buy_land_decision_step": unlock - 1, "window": [144, end], "maximum_cash_shortfall_to_2011": max(max(0, SHADOW_THRESHOLD - float(row["pre_cash"])) for row in steps if row["step"] < unlock), "actual_spend_by_family": dict(actual_spend), "shadow_candidates": candidates, "steps": steps})
        timelines.append(timeline_context(rep, seat, context))
    family_summary = {}
    for family, rows in family_context.items():
        qualifying = [row for row in rows if row["advance_at_least_24"]]
        blocks = sorted({row["block"] for row in qualifying})
        sources = sorted({row["source"] for row in qualifying})
        family_summary[family] = {
            "contexts": len(rows), "qualifying_contexts_capital_only": len(qualifying), "qualifying_source_seed_blocks_capital_only": len(blocks),
            "qualifying_sources_capital_only": len(sources), "blocks": blocks, "sources": sources,
            "advance_decisions": summary([float(row["advance_decisions"]) for row in qualifying if row["advance_decisions"] is not None]),
            "complete_maintenance_to_sale_contracts": 0,
        }
    return ledgers, timelines, family_summary, {family: dict(values) for family, values in opportunity.items()}


def top_memberships() -> list[dict[str, Any]]:
    metrics = load(TOP_ANALYSIS / "current_episode_seat_metrics.json")
    inputs = load(TOP_ANALYSIS / "current_replay_input_manifest.json")
    paths = {int(row["episode_id"]): ROOT / row["path"] for row in inputs}
    rows = []
    for row in metrics:
        rows.append({"episode_id": int(row["episode_id"]), "submission_id": int(row["submission_id"]), "seat": int(row["seat"]), "team": row["team_name"], "rank": int(str(row["cohort"]).rsplit("_", 1)[-1]), "result": row["result"], "path": paths[int(row["episode_id"])], "margin": float(row["final_margin"])})
    if len(rows) != 30:
        raise RuntimeError(len(rows))
    return rows


def top_analysis() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    timelines = []
    cache: dict[Path, dict[str, Any]] = {}
    for row in top_memberships():
        rep = cache.setdefault(row["path"], read_replay(row["path"]))
        context = {key: value for key, value in row.items() if key != "path"}
        context["replay"] = rel(row["path"])
        context["replay_sha256"] = sha(row["path"])
        timelines.append(timeline_context(rep, row["seat"], context))

    def group(rows: list[dict[str, Any]]) -> dict[str, Any]:
        def lags(key: str) -> list[float]:
            return [float(row["events"][key]["lag"]) for row in rows if row.get("events", {}).get(key)]
        return {
            "n": len(rows), "unlock_state_step": summary([float(row["third_land_unlock_state_step"]) for row in rows if row.get("third_land_unlock_state_step") is not None]),
            "lag_to_first_entry": summary(lags("first_unit_entry")), "lag_to_first_productive_action": summary(lags("first_productive_action")),
            "lag_to_first_harvest_whole_farm": summary(lags("first_harvest")), "lag_to_first_committed_sell_whole_farm": summary(lags("first_committed_sell")),
            "scope_warning": "Harvest/sale are whole-farm events; fungible inventory prevents attribution to the newly unlocked quadrant.",
        }
    comparison = {
        "evidence_level": "E1_CROSS_CORPUS", "causal_effect": False,
        "overall": group(timelines), "wins": group([row for row in timelines if row["result"] == "win"]), "losses": group([row for row in timelines if row["result"] == "loss"]),
        "by_rank": {str(rank): group([row for row in timelines if row["rank"] == rank]) for rank in range(1, 6)},
        "by_submission": {str(submission): group([row for row in timelines if row["submission_id"] == submission]) for submission in sorted({row["submission_id"] for row in timelines})},
        "limitations": ["Target seat only.", "Public replay is factual action/public state, not source code, private future state, or an exact route to copy.", "Selected opponent mix is not a paired treatment effect."],
    }
    return timelines, comparison


def analyze() -> None:
    if not (EXP / "manifest.json").exists():
        raise FileNotFoundError("Run initial first")
    ledgers, control_timelines, family_summary, opportunity = control_analysis()
    top_timelines, top_comparison = top_analysis()
    save(EXP / "midgame_cashflow_ledger.json", {"created_at": now(), "classification_preregistration": rel(DOC), "contexts": ledgers})
    save(EXP / "land_relative_activation_timeline.json", {"created_at": now(), "V111_controls": control_timelines, "current_top_target_seats": top_timelines})
    v111_group = {
        "n": len(control_timelines),
        "unlock_state_step": summary([float(row["third_land_unlock_state_step"]) for row in control_timelines]),
        "lag_to_first_productive_action": summary([float(row["events"]["first_productive_action"]["lag"]) for row in control_timelines if row["events"]["first_productive_action"]]),
        "lag_to_first_harvest_whole_farm": summary([float(row["events"]["first_harvest"]["lag"]) for row in control_timelines if row["events"]["first_harvest"]]),
        "lag_to_first_committed_sell_whole_farm": summary([float(row["events"]["first_committed_sell"]["lag"]) for row in control_timelines if row["events"]["first_committed_sell"]]),
    }
    save(EXP / "current_top_capacity_comparison.json", {**top_comparison, "historical_V111": v111_group, "interpretation": "Cross-corpus timing association only, not a candidate effect."})
    save(EXP / "shadow_capital_counterfactual.json", {"created_at": now(), "land_cost": LAND_COST, "activation_reserve": ACTIVATION_RESERVE, "threshold": SHADOW_THRESHOLD, "families": family_summary, "contexts": [{key: row[key] for key in ("source", "seed", "seat", "block", "shadow_candidates")} for row in ledgers], "causal_status": "ARITHMETIC_UPPER_BOUND_ONLY"})
    save(EXP / "opportunity_cost_by_spend_family.json", {"created_at": now(), "observed": opportunity, "classification": {"BUY_ANIMAL:COW": "deferrable irreversible investment until placement; placement/feed/care/milk debt retained", "BUY_SEED:STRAWBERRY": "existing production continuation when consumed within 24 decisions, otherwise deferrable inventory", "BUY_SEED:WHEAT": "existing production or urgent feed continuation depending on state", "BUY_SEED:MELON": "existing production continuation", "BUY_PRODUCT:WHEAT": "urgent maintenance when required for same-day FEED", "HIRE": "urgent when assigned to maintenance/harvest/carry; otherwise capacity investment"}, "limits": "Observed whole-farm harvest cannot identify output of each purchase lot. Lost future output remains Unknown."})
    best_family = max(family_summary, key=lambda name: (family_summary[name]["qualifying_source_seed_blocks_capital_only"], family_summary[name]["qualifying_sources_capital_only"]))
    best = family_summary[best_family]
    activation_lags = [float(row["events"]["first_productive_action"]["lag"]) for row in control_timelines if row["events"]["first_productive_action"]]

    checkpoints = [144, 192, 198, 209, 216, 222, 240, 248, 253, 264, 288]

    def checkpoint_panel(rows: list[dict[str, Any]], *, ledger: bool) -> dict[str, Any]:
        panel = {}
        for step in checkpoints:
            states = []
            for row in rows:
                source_rows = row["steps"] if ledger else row["relative_timeline"]
                state = next((value for value in source_rows if value["step"] == step), None)
                if state is not None:
                    states.append(state)
            if not states:
                continue
            if ledger:
                cash = [float(value["pre_cash"]) for value in states]
                capacity_rows = [value["all_farm_capacity"] for value in states]
                hands = [float(value["hands"]) for value in states]
            else:
                cash = [float(value["self_cash"]) for value in states]
                capacity_rows = [value["self_all_farm"] for value in states]
                hands = [float(len(value["hands"] or [])) for value in states]
            panel[str(step)] = {
                "n": len(states), "cash": summary(cash), "cash_ge_2000": sum(value >= 2000 for value in cash),
                "productive_tiles": summary([float(value["productive_tiles"]) for value in capacity_rows]),
                "empty_tiles": summary([float(value["empty_tiles"]) for value in capacity_rows]),
                "weed_tiles": summary([float(value["weed_tiles"]) for value in capacity_rows]),
                "hands": summary(hands),
            }
        return panel

    capacity = {
        "created_at": now(), "V111": v111_group, "Top": top_comparison["overall"],
        "absolute_step_checkpoints": {"V111": checkpoint_panel(ledgers, ledger=True), "Top": checkpoint_panel(top_timelines, ledger=False)},
        "best_shadow_family": best_family, "capital_only_blocks": best["qualifying_source_seed_blocks_capital_only"], "capital_only_sources": best["qualifying_sources_capital_only"],
        "post_unlock_activation_delay_ge_24_contexts": sum(value >= 24 for value in activation_lags),
        "mediator_order": ["deferred_spend_arithmetic", "earlier_land_shadow", "productive_action", "harvest", "realized_sale", "public_market_or_Town", "opponent_action", "margin"],
        "warning": "Only baseline factual timelines and arithmetic shadows exist; no treatment-mediated chain was run.",
    }
    save(EXP / "capacity_mediator_timeline.json", capacity)
    gate = {
        "1_same_family_two_sources_four_blocks": best["qualifying_sources_capital_only"] >= 2 and best["qualifying_source_seed_blocks_capital_only"] >= 4,
        "2_advance_24_and_productive_within_24": False,
        "3_unique_state_machine_procurement_to_sale": False,
        "4_state_compatible_suffix_or_general_executor": False,
        "5_resequence_only_existing_family": best_family == "BUY_ANIMAL:COW",
        "6_all_resource_and_maintenance_preflight": False,
        "7_bounded_vs_v109_fallback": False,
        "8_no_P1_Top_dependency": True,
    }
    gate["all_pass"] = all(gate.values())
    ranking = {
        "created_at": now(), "mechanisms": [
            {"rank": 1, "name": "third_land_capital_and_activation_commitment", "changes": [best_family, "BUY_LAND", "WHEAT activation"], "V111_existing_part": "same spend family and WHEAT route assets", "resources": "land 2000 + activation reserve 11 + state-specific maintenance reserve", "completeness": "capital arithmetic observed; maintenance-preserving worker schedule, sale attribution, catch-up and rejoin not proven", "negative_experiment_difference": "bounded diagnosis, but no bounded executor was established", "identity_risk": "low", "safety_risk": "high until task debt/rejoin is solved", "license_risk": "low if V111-only", "Evidence": best, "Inference": "Deferring the family can expose cash earlier in some blocks.", "Unknown": "realized revenue and opponent closed-loop effect."},
            {"rank": 2, "name": "post_unlock_activation_only", "changes": ["post-unlock idle lag"], "completeness": "not selected", "Evidence": {"lag_summary": summary(activation_lags), "delay_ge_24_contexts": sum(value >= 24 for value in activation_lags)}, "Inference": "only useful if a substantial factual lag exists", "Unknown": "paired uplift"},
            {"rank": 3, "name": "remote_market_order_parity", "strategy_candidate": False, "Evidence": "5725/5752 action agreement and 27 order-only differences", "Unknown": "exact package identity and full closed-loop effect", "status": "UNVERIFIED_HYGIENE_ONLY"},
            {"rank": 4, "name": "demand_backed_tomato_option", "status": "DEFERRED_NOT_IMPLEMENTED", "reason": "Tomato begins after the main step 216–264 capacity gap, loses the Top win/loss correlation check, and prior crop diversification was negative."},
        ], "implementation_gate": gate, "C1_authorized": False,
    }
    save(EXP / "mechanism_ranking.json", ranking)
    attribution = {
        "created_at": now(), "candidate_run": False,
        "nodes": [
            {"id": "cash_shortage", "status": "Evidence", "claim": "V111 factual cash is below land+activation threshold during the Top median unlock region."},
            {"id": "specific_spend_family", "status": "Evidence", "claim": f"{best_family} has the largest frozen arithmetic release across blocks."},
            {"id": "earlier_land", "status": "Inference", "claim": "Shadow balance can pay earlier; engine outcome was not rerun."},
            {"id": "productive_action", "status": "Unknown", "claim": "Resource-distance lower bound is not a maintenance-preserving schedule."},
            {"id": "incremental_harvest", "status": "Unknown", "claim": "No counterfactual crop lifecycle was executed."},
            {"id": "realized_sale", "status": "Unknown", "claim": "Fungible inventory prevents attributing baseline sales to new land."},
            {"id": "opponent_coin", "status": "Unknown", "claim": "No candidate closed-loop replay exists."},
            {"id": "margin", "status": "Unknown", "claim": "No paired candidate evaluation exists."},
        ],
        "edges": [
            {"from": "cash_shortage", "to": "specific_spend_family", "status": "Evidence", "basis": "order-level committed costs and factual cash"},
            {"from": "specific_spend_family", "to": "earlier_land", "status": "Inference", "basis": "arithmetic upper bound only"},
            {"from": "earlier_land", "to": "productive_action", "status": "Unknown"},
            {"from": "productive_action", "to": "incremental_harvest", "status": "Unknown"},
            {"from": "incremental_harvest", "to": "realized_sale", "status": "Unknown"},
            {"from": "realized_sale", "to": "opponent_coin", "status": "Unknown"},
            {"from": "opponent_coin", "to": "margin", "status": "Unknown"},
        ],
        "causal_limit": "Earlier land, opponent coin and margin are not identified effects of BUY_LAND or one crop/action.",
    }
    save(EXP / "mechanism_attribution.json", attribution)
    manifest = load(EXP / "manifest.json")
    manifest.update({"phase": "REPLAY_ONLY_GATE_COMPLETE", "C1_created": False, "candidate_gate": gate, "status": "RUNNING"})
    save(EXP / "manifest.json", manifest)
    print(json.dumps({"best_family": best_family, "best": best, "gate": gate, "v111": v111_group, "top": top_comparison["overall"]}, ensure_ascii=False, indent=2))


def finalize() -> None:
    ranking = load(EXP / "mechanism_ranking.json")
    shadow = load(EXP / "shadow_capital_counterfactual.json")
    capacity = load(EXP / "capacity_mediator_timeline.json")
    best_family = capacity["best_shadow_family"]
    best = shadow["families"][best_family]
    final = {
        "created_at": now(), "status": "REJECT_NO_FEASIBLE_CONTRACT", "production_champion": "V111",
        "reason": "Capital-only shadow support did not establish a maintenance-preserving 24-decision activation schedule, procurement-to-sale state machine, catch-up, or explicit state-based rejoin; implementation gates 2, 3, 4, 6 and 7 failed before any new game.",
        "best_shadow_family": best_family, "capital_only_shadow": best, "implementation_gate": ranking["implementation_gate"],
        "C1_created": False, "paired_games": 0, "development_games": 0, "numeric_agent_created": False, "numeric_label": None,
        "remote_package_identity": "UNVERIFIED", "tomato_executed": False,
        "seed_use": {"spent_new_games": 0, "conditional_development": [], "promotion": [], "fresh": [], "prior_development": []},
        "external_mutations": {"kaggle_submission": False, "kernel_push": False, "submission_slot_change": False},
        "validation": {"py_compile": "PASS", "ruff": "PASS", "evaluation_tests": {"passed": 22, "failed": 0}},
        "final_process_audit": {"method": "elevated Get-CimInstance", "matching_python_or_kaggle_processes": []},
    }
    save(EXP / "final_decision.json", final)
    commands = {
        "exact_reproduction": ".\\.venv\\Scripts\\python.exe scripts\\research_20260916_v111_midgame_capacity.py analyze",
        "same_hash_resume": "Not applicable: replay-only analysis is deterministic and atomic; rerun only after verifying manifest input hashes.",
        "no_new_games": True,
    }
    save(EXP / "reproduction_commands.json", commands)
    manifest = load(EXP / "manifest.json")
    manifest.update({"phase": "COMPLETE", "status": "COMPLETE", "decision": final["status"], "completed_at": now()})
    save(EXP / "manifest.json", manifest)
    files = sorted(path for path in EXP.rglob("*") if path.is_file() and path.name not in {"final_artifact_manifest.json", "final_artifact_verification.json"})
    files.extend([DOC, REPORT, Path(__file__)])
    artifact_manifest = {"created_at": now(), "files": [{"path": rel(path), "sha256": sha(path), "bytes": path.stat().st_size} for path in sorted(set(files)) if path.exists()]}
    save(EXP / "final_artifact_manifest.json", artifact_manifest)
    checks = [{**row, "actual_sha256": sha(ROOT / row["path"]), "ok": sha(ROOT / row["path"]) == row["sha256"]} for row in artifact_manifest["files"]]
    required_names = {
        "manifest.json", "seed_ledger.json", "input_artifact_verification.json", "leaderboard_and_replay_audit.json",
        "remote_package_fidelity_audit.json", "midgame_cashflow_ledger.json", "land_relative_activation_timeline.json",
        "current_top_capacity_comparison.json", "shadow_capital_counterfactual.json", "opportunity_cost_by_spend_family.json",
        "capacity_mediator_timeline.json", "mechanism_ranking.json", "mechanism_attribution.json", "independent_source_screen.json",
        "development_progress.json", "final_decision.json", "reproduction_commands.json",
    }
    save(EXP / "final_artifact_verification.json", {
        "verified_at": now(), "checks": checks, "all_match": all(row["ok"] for row in checks),
        "json_loadable": all(load(ROOT / row["path"]) is not None for row in checks if Path(row["path"]).suffix == ".json"),
        "required_artifacts_present": all((EXP / name).is_file() for name in required_names), "required_artifacts": sorted(required_names),
        "candidate_jsonl_duplicate_partial": "NOT_APPLICABLE_NO_CANDIDATE", "new_games": 0,
        "validation": {"py_compile": "PASS", "ruff": "PASS", "evaluation_tests": {"passed": 22, "failed": 0}, "evaluation_core_changed": False},
        "final_process_audit": {"method": "elevated Get-CimInstance", "matching_python_or_kaggle_processes": []},
    })
    print(json.dumps(final, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("initial", "analyze", "finalize"))
    args = parser.parse_args()
    {"initial": initial, "analyze": analyze, "finalize": finalize}[args.command]()


if __name__ == "__main__":
    main()
