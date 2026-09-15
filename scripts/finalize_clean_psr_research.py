"""Finalize the preregistered clean-PSR study without opening sealed seeds."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import random
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXP = ROOT / "experiments" / "research_20260914_clean_psr"
OLD_EXP = ROOT / "experiments" / "research_20260914_lowcash"
OLD_PAIRS = ROOT / "data" / "evaluation" / "research_20260914_lowcash" / "discovery" / "pairs.jsonl"
DOC = ROOT / "docs" / "research_20260914_clean_psr_report.md"
SOURCES = ["mooman_e052a", "souvik_v4", "ggmljs_v16", "qeinstein_moev2"]
ANCESTRY = {
    "psr_kaito_near": ["mooman_e052a", "souvik_v4", "ggmljs_v16"],
    "qeinstein_independent": ["qeinstein_moev2"],
}
CANDIDATES = {
    "R0_v116_frozen_reference": OLD_PAIRS,
    "D1_e052a_no_opponent_tape": EXP / "candidates" / "D1_e052a_no_opponent_tape" / "pairs" / "spent.jsonl",
    "P1_psr_clean": EXP / "candidates" / "P1_psr_clean" / "pairs" / "spent.jsonl",
}
BOOTSTRAP_REPETITIONS = 100_000
BOOTSTRAP_SEED = 20_260_914


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path: Path | str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def save(path: Path | str, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_replay(path: Path | str) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def observation(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    value = replay["steps"][step][seat]["observation"]
    return json.loads(value) if isinstance(value, str) else value


def clean_steps(replay: dict[str, Any]) -> list[list[dict[str, Any]]]:
    result = []
    for states in replay["steps"]:
        clean_states = []
        for state in states:
            obs = state.get("observation")
            obs = json.loads(obs) if isinstance(obs, str) else dict(obs or {})
            obs.pop("remainingOverageTime", None)
            clean_states.append(
                {
                    "observation": obs,
                    "action": state.get("action"),
                    "reward": state.get("reward"),
                    "status": state.get("status"),
                }
            )
        result.append(clean_states)
    return result


def quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction)


def distribution(values: list[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "min": min(values) if values else None,
        "p10": quantile(values, 0.10),
        "median": statistics.median(values) if values else None,
        "mean": statistics.mean(values) if values else None,
        "p90": quantile(values, 0.90),
        "max": max(values) if values else None,
    }


def wdl(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    counts = Counter(row[arm]["result"] for row in rows)
    return {
        "wins": counts["win"],
        "draws": counts["draw"],
        "losses": counts["loss"],
        "win_score": statistics.mean(float(row[arm]["score"]) for row in rows) if rows else 0.0,
    }


def transition_name(row: dict[str, Any]) -> str:
    return f"{row['control']['result']}->{row['treatment']['result']}"


def summarize_subset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    control = wdl(rows, "control")
    candidate = wdl(rows, "treatment")
    return {
        "contexts": len(rows),
        "source_seed_blocks": len({(row["lineage_id"], int(row["seed"])) for row in rows}),
        "seed_values": sorted({int(row["seed"]) for row in rows}),
        "control": control,
        "candidate": candidate,
        "delta_win_score": candidate["win_score"] - control["win_score"],
        "transitions": dict(sorted(Counter(transition_name(row) for row in rows).items())),
        "mean_delta_self_coin": statistics.mean(float(row["delta_self_coin"]) for row in rows) if rows else 0.0,
        "mean_delta_opponent_coin": statistics.mean(float(row["delta_opponent_coin"]) for row in rows) if rows else 0.0,
        "mean_delta_margin": statistics.mean(float(row["delta_margin"]) for row in rows) if rows else 0.0,
    }


def source_seed_blocks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["lineage_id"]), int(row["seed"]))].append(row)
    result = []
    for (source, seed), selected in sorted(grouped.items()):
        if {int(row["seat"]) for row in selected} != {0, 1}:
            raise RuntimeError(f"incomplete seat block: {source} {seed}")
        item = summarize_subset(selected)
        item.update(
            {
                "source": source,
                "seed": seed,
                "case_count": 1,
                "seat_contexts": 2,
                "has_loss_to_win": any(transition_name(row) == "loss->win" for row in selected),
                "has_win_to_loss": any(transition_name(row) == "win->loss" for row in selected),
            }
        )
        result.append(item)
    return result


def block_bootstrap(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(block["delta_win_score"]) for block in blocks]
    rng = random.Random(BOOTSTRAP_SEED)
    estimates = []
    for _ in range(BOOTSTRAP_REPETITIONS):
        sample = rng.choices(values, k=len(values))
        estimates.append(statistics.mean(sample))
    return {
        "method": "whole source+seed block bootstrap; both seats retained as one case",
        "blocks": len(blocks),
        "replicates": BOOTSTRAP_REPETITIONS,
        "rng_seed": BOOTSTRAP_SEED,
        "estimate": statistics.mean(values),
        "low_95": quantile(estimates, 0.025),
        "high_95": quantile(estimates, 0.975),
    }


def weighted_delta(rows: list[dict[str, Any]], raw_weights: dict[str, float]) -> float:
    by_source = {
        source: summarize_subset([row for row in rows if row["lineage_id"] == source])["delta_win_score"]
        for source in SOURCES
    }
    total = sum(raw_weights.values())
    return sum(raw_weights[source] * by_source[source] for source in SOURCES) / total


def weighting_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = [{"name": "equal_source", "raw_weights": {source: 1.0 for source in SOURCES}}]
    for source in SOURCES:
        for factor in (1.2, 0.8):
            weights = {item: 1.0 for item in SOURCES}
            weights[source] = factor
            scenarios.append(
                {
                    "name": f"{source}_x{factor:.1f}",
                    "raw_weights": weights,
                }
            )
    for scenario in scenarios:
        scenario["delta"] = weighted_delta(rows, scenario["raw_weights"])
    ancestry_delta = {}
    for ancestry, sources in ANCESTRY.items():
        ancestry_delta[ancestry] = summarize_subset([row for row in rows if row["lineage_id"] in sources])[
            "delta_win_score"
        ]
    return {
        "equal_source_delta": scenarios[0]["delta"],
        "ancestry_delta": ancestry_delta,
        "equal_ancestry_delta": statistics.mean(ancestry_delta.values()),
        "nine_scenarios": scenarios,
        "nine_scenario_worst_delta": min(float(row["delta"]) for row in scenarios),
    }


def exclusion_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    definitions = {
        "exclude_self_mooman": [source for source in SOURCES if source != "mooman_e052a"],
        "exclude_tape2_firing_sources": ["ggmljs_v16", "qeinstein_moev2"],
        "exclude_psr_kaito_near_lineage": ["qeinstein_moev2"],
    }
    return {
        name: {
            "included_sources": sources,
            **summarize_subset([row for row in rows if row["lineage_id"] in sources]),
        }
        for name, sources in definitions.items()
    }


def terminal_proxy(replay: dict[str, Any], seat: int, step: int) -> dict[str, Any]:
    obs = observation(replay, step, seat)
    private = obs["private"]
    products = list(obs["market"]["prices"])
    shed = Counter(private.get("shed") or {})
    carried: Counter[str] = Counter()
    for inventory in private.get("inventories") or []:
        carried.update(inventory)
    prices = obs["market"]["prices"]
    unharvested: Counter[str] = Counter()
    for tile_row in obs["farms"][seat]["tiles"]:
        for tile in tile_row:
            if isinstance(tile, dict) and tile.get("crop") in products:
                unharvested[str(tile["crop"])] += max(0, int(tile.get("yield_units", 0) or 0))
    return {
        "step": step,
        "decisions_remaining": 719 - step,
        "shed_product_units": sum(shed[item] for item in products),
        "carried_product_units": sum(carried[item] for item in products),
        "unharvested_current_units": sum(unharvested.values()),
        "gross_quote_shed": sum(shed[item] * float(prices[item]) for item in products),
        "gross_quote_carried": sum(carried[item] * float(prices[item]) for item in products),
        "gross_quote_field_current_yield": sum(unharvested[item] * float(prices[item]) for item in products),
        "limit": (
            "Proxy only: ignores price impact, opponent orders, order slots, travel, readiness and labor; "
            "at step719 no decisions remain."
        ),
    }


def aggregate_numeric_rows(rows: list[dict[str, Any]], points: list[str], fields: list[str]) -> dict[str, Any]:
    return {
        point: {field: statistics.mean(float(row[point][field]) for row in rows) for field in fields}
        for point in points
    }


def first_action_divergence(left: dict[str, Any], right: dict[str, Any], seat: int) -> int | None:
    decisions = min(len(left["steps"]), len(right["steps"])) - 1
    for step in range(decisions):
        left_action = left["steps"][step + 1][seat].get("action")
        right_action = right["steps"][step + 1][seat].get("action")
        if left_action != right_action:
            return step
    return None


def lifecycle_and_engine(
    candidate_id: str, rows: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from scripts.evaluation.lifecycle import analyze_lifecycle
    from scripts.evaluation.safety import simulate_turn

    lifecycle_rows = []
    terminal_rows = []
    engine_rows = []
    for row in sorted(rows, key=lambda item: (item["lineage_id"], item["seed"], item["seat"])):
        key = [row["lineage_id"], row["seed"], row["seat"]]
        for arm in ("control", "treatment"):
            replay = read_replay(row["replay_artifacts"][arm])
            lifecycle_rows.append({"key": key, "arm": arm, **analyze_lifecycle(replay, int(row["seat"]), 0)})
            terminal_rows.append(
                {
                    "key": key,
                    "arm": arm,
                    "at672": terminal_proxy(replay, int(row["seat"]), 672),
                    "at719": terminal_proxy(replay, int(row["seat"]), 719),
                }
            )
            if arm != "treatment":
                continue
            incidents = []
            counts: Counter[str] = Counter()
            for step in range(len(replay["steps"]) - 1):
                for event in simulate_turn(replay, step)[int(row["seat"])]:
                    kind = str(event["kind"])
                    if kind == "market_commit":
                        requested = int(event.get("requested", 0) or 0)
                        committed = int(event.get("committed", 0) or 0)
                        if committed >= requested:
                            continue
                        category = "market_noop" if committed == 0 else "partial_market_commit"
                        counts[category] += 1
                        if event.get("op") == "SELL":
                            counts["oversized_sell"] += 1
                        elif event.get("op") in {"BUY_PRODUCT", "BUY_SEED", "BUY_ANIMAL", "HIRE"}:
                            counts["failed_buy_or_hire"] += 1
                        incidents.append({"step": step, "category": category, **event})
                    elif kind in {"silent_field_noop", "missing_hand_action"}:
                        counts[kind] += int(event.get("count", 1) or 1)
                        incidents.append({"step": step, "category": kind, **event})
            engine_rows.append({"key": key, "counts": dict(counts), "orders": incidents})

    lifecycle_path = EXP / "candidates" / candidate_id / "summary" / "lifecycle_diagnostics.json"
    terminal_path = EXP / "candidates" / candidate_id / "summary" / "terminal_inventory_diagnostics.json"
    engine_path = EXP / "candidates" / candidate_id / "summary" / "engine_action_diagnostics.json"
    save(lifecycle_path, {"created_at": now(), "candidate": candidate_id, "rows": lifecycle_rows})
    save(terminal_path, {"created_at": now(), "candidate": candidate_id, "rows": terminal_rows})
    save(engine_path, {"created_at": now(), "candidate": candidate_id, "rows": engine_rows})

    lifecycle_aggregate = {}
    terminal_aggregate = {}
    for arm in ("control", "treatment"):
        selected_life = [row for row in lifecycle_rows if row["arm"] == arm]
        counts: Counter[str] = Counter()
        lost_units: Counter[str] = Counter()
        harvest_units: Counter[str] = Counter()
        for item in selected_life:
            counts.update(item["counts"])
            lost_units.update(item["lost_current_units"])
            harvest_units.update(item["successful_harvest_units"])
        lifecycle_aggregate[arm] = {
            "counts": dict(counts),
            "lost_current_units": dict(lost_units),
            "successful_harvest_units": dict(harvest_units),
        }
        selected_terminal = [row for row in terminal_rows if row["arm"] == arm]
        terminal_aggregate[arm] = aggregate_numeric_rows(
            selected_terminal,
            ["at672", "at719"],
            [
                "shed_product_units",
                "carried_product_units",
                "unharvested_current_units",
                "gross_quote_shed",
                "gross_quote_carried",
                "gross_quote_field_current_yield",
            ],
        )
    action_counts: Counter[str] = Counter()
    for item in engine_rows:
        action_counts.update(item["counts"])
    return (
        lifecycle_aggregate,
        terminal_aggregate,
        {
            "counts": dict(action_counts),
            "per_order_step_file": str(engine_path.relative_to(ROOT)).replace("\\", "/"),
        },
    )


def safety_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    absolute = {"control": Counter(), "treatment": Counter()}
    for row in rows:
        reasons.update(row["candidate_new_major_regressions"])
        for arm in ("control", "treatment"):
            safety = row["safety"][arm]
            absolute[arm].update(
                {
                    "animal_loss": int(safety.get("animal_loss_total", 0) or 0),
                    "crop_to_weed": int(safety.get("plant_to_weed", 0) or 0),
                    "spawned_weed": int(safety.get("spawned_weeds", 0) or 0),
                }
            )
    return {
        "raw_failure_contexts": sum(bool(row["candidate_new_major_regressions"]) for row in rows),
        "raw_reason_context_counts": dict(reasons),
        "absolute_event_totals": {arm: dict(value) for arm, value in absolute.items()},
        "runtime_or_delivery_failures": sum(
            bool(row["candidate_incident_classification"]["treatment_delivery_failure"]) for row in rows
        ),
        "minimum_treatment_cash": min(float(row["safety"]["treatment"]["minimum_cash"]) for row in rows),
        "all_completed_720": all(
            row["safety"]["control"]["completed_720"] and row["safety"]["treatment"]["completed_720"] for row in rows
        ),
    }


def divergence_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pair_rows = []
    for row in sorted(rows, key=lambda item: (item["lineage_id"], item["seed"], item["seat"])):
        audit = row["divergence_audit"]
        state = audit.get("first_state_divergence") or {}
        lag = audit.get("opponent_response_lag") or {}
        pair_rows.append(
            {
                "key": [row["lineage_id"], row["seed"], row["seat"]],
                "transition": transition_name(row),
                "first_action": audit.get("first_focal_action"),
                "first_state_divergence": state,
                "first_public_observation_divergence_step": audit.get("first_public_observation_divergence_step"),
                "first_market_step": (audit.get("first_market_divergence") or {}).get("step"),
                "first_price_step": (audit.get("first_price_divergence") or {}).get("step"),
                "first_town_step": (state.get("town") or {}).get("step"),
                "first_opponent_response_step": audit.get("first_opponent_response_step"),
                "opponent_response_lag": lag,
                "delta_self_coin": row["delta_self_coin"],
                "delta_opponent_coin": row["delta_opponent_coin"],
                "delta_margin": row["delta_margin"],
            }
        )
    public_steps = [
        int(row["first_public_observation_divergence_step"])
        for row in pair_rows
        if row["first_public_observation_divergence_step"] is not None
    ]
    response_lags = [
        int(row["opponent_response_lag"]["from_first_public_signal"])
        for row in pair_rows
        if row["opponent_response_lag"] and row["opponent_response_lag"].get("from_first_public_signal") is not None
    ]
    return {
        "pairs": pair_rows,
        "first_public_step_distribution": distribution(public_steps),
        "opponent_response_lag_from_public_distribution": distribution(response_lags),
        "causal_limit": (
            "Opponent-coin changes follow a closed-loop policy divergence; they are not attributed "
            "to one action without a mediator counterfactual."
        ),
    }


def candidate_summary(candidate_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) != 32:
        raise RuntimeError(f"{candidate_id}: expected 32 rows, got {len(rows)}")
    keys = {(row["lineage_id"], int(row["seed"]), int(row["seat"])) for row in rows}
    if len(keys) != 32:
        raise RuntimeError(f"{candidate_id}: duplicate context keys")
    blocks = source_seed_blocks(rows)
    by_source = {source: summarize_subset([row for row in rows if row["lineage_id"] == source]) for source in SOURCES}
    by_ancestry = {
        name: summarize_subset([row for row in rows if row["lineage_id"] in sources])
        for name, sources in ANCESTRY.items()
    }
    lifecycle, terminal, engine = lifecycle_and_engine(candidate_id, rows)
    margins = {
        "control": distribution([float(row["control"]["margin"]) for row in rows]),
        "candidate": distribution([float(row["treatment"]["margin"]) for row in rows]),
        "delta": distribution([float(row["delta_margin"]) for row in rows]),
    }
    transitions = {
        name: [[row["lineage_id"], row["seed"], row["seat"]] for row in rows if transition_name(row) == name]
        for name in ("loss->win", "win->loss", "draw->win", "win->draw", "loss->draw", "draw->loss")
    }
    overall = summarize_subset(rows)
    return {
        "created_at": now(),
        "candidate": candidate_id,
        "overall": overall,
        "by_source": by_source,
        "ancestry_mapping": ANCESTRY,
        "by_ancestry": by_ancestry,
        "margins": margins,
        "p10_candidate_margin": margins["candidate"]["p10"],
        "transition_table": transitions,
        "source_seed_blocks": blocks,
        "independent_loss_to_win_blocks": sum(block["has_loss_to_win"] for block in blocks),
        "independent_loss_to_win_sources": sorted({block["source"] for block in blocks if block["has_loss_to_win"]}),
        "whole_source_seed_block_bootstrap": block_bootstrap(blocks),
        "weighting": weighting_summary(rows),
        "exclusions": exclusion_summary(rows),
        "safety": safety_summary(rows),
        "lifecycle": lifecycle,
        "terminal_inventory_proxy": terminal,
        "engine_action": engine,
        "divergence": divergence_summary(rows),
        "coin_causal_limit": (
            "Self/opponent coin differences are total-policy paired outcomes; opponent coin decline "
            "is not a single-action causal effect."
        ),
    }


def reuse_r0_artifacts(r0_summary: dict[str, Any]) -> None:
    target = EXP / "candidates" / "R0_v116_frozen_reference"
    save(
        target / "freeze.json",
        {
            "created_at": now(),
            "candidate": "R0_v116_frozen_reference",
            "role": "frozen reference only",
            "new_execution": False,
            "source_pairs": str(OLD_PAIRS.relative_to(ROOT)).replace("\\", "/"),
            "source_pairs_sha256": sha256(OLD_PAIRS),
            "package": "experiments/research_20260914_lowcash/v116_mooman_complete.tar.gz",
            "package_sha256": sha256(OLD_EXP / "v116_mooman_complete.tar.gz"),
        },
    )
    save(
        target / "plan.json",
        {
            "candidate": "R0_v116_frozen_reference",
            "action": "reuse only; no game, promotion, or new replay",
            "contexts": 32,
        },
    )
    save(
        target / "pairs" / "reused.json",
        {"path": str(OLD_PAIRS.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(OLD_PAIRS)},
    )
    save(target / "runs" / "reused.json", {"new_runs": 0, "status": "FROZEN_REUSE"})
    replay_paths = sorted(
        {
            str(Path(row["replay_artifacts"][arm]).resolve().relative_to(ROOT)).replace("\\", "/")
            for row in load_jsonl(OLD_PAIRS)
            for arm in ("control", "treatment")
        }
    )
    save(
        target / "replay" / "reused.json",
        {"new_replays": 0, "reused_count": len(replay_paths), "paths": replay_paths},
    )
    save(target / "summary" / "complete.json", r0_summary)


def comparison_summary(
    left_id: str,
    left_rows: list[dict[str, Any]],
    right_id: str,
    right_rows: list[dict[str, Any]],
    note: str,
) -> dict[str, Any]:
    def key(row: dict[str, Any]) -> tuple[str, int, int]:
        return str(row["lineage_id"]), int(row["seed"]), int(row["seat"])

    left = {key(row): row for row in left_rows}
    right = {key(row): row for row in right_rows}
    pairs = []
    for item in sorted(left):
        left_row, right_row = left[item], right[item]
        left_replay = read_replay(left_row["replay_artifacts"]["treatment"])
        right_replay = read_replay(right_row["replay_artifacts"]["treatment"])
        pairs.append(
            {
                "key": list(item),
                "result_transition": (f"{left_row['treatment']['result']}->{right_row['treatment']['result']}"),
                "delta_win_score": float(right_row["treatment"]["score"]) - float(left_row["treatment"]["score"]),
                "delta_self_coin": float(right_row["treatment"]["ours"]) - float(left_row["treatment"]["ours"]),
                "delta_opponent_coin": float(right_row["treatment"]["theirs"]) - float(left_row["treatment"]["theirs"]),
                "first_action_divergence_step": first_action_divergence(left_replay, right_replay, item[2]),
            }
        )
    by_source = {}
    for source in SOURCES:
        selected = [row for row in pairs if row["key"][0] == source]
        by_source[source] = {
            "delta_win_score": statistics.mean(row["delta_win_score"] for row in selected),
            "result_transitions": dict(Counter(row["result_transition"] for row in selected)),
            "action_diverged_contexts": sum(row["first_action_divergence_step"] is not None for row in selected),
        }
    return {
        "left": left_id,
        "right": right_id,
        "note": note,
        "overall_delta_win_score": statistics.mean(row["delta_win_score"] for row in pairs),
        "by_source": by_source,
        "pairs": pairs,
    }


def safe_oracle(all_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    by_candidate = {
        candidate: {(row["lineage_id"], int(row["seed"]), int(row["seat"])): row for row in rows}
        for candidate, rows in all_rows.items()
    }
    keys = sorted(next(iter(by_candidate.values())))
    selected_rows = []
    for key in keys:
        control = by_candidate["R0_v116_frozen_reference"][key]["control"]
        routes = []
        for candidate, mapping in by_candidate.items():
            row = mapping[key]
            if not row["candidate_new_major_regressions"]:
                routes.append(
                    {
                        "candidate": candidate,
                        "score": float(row["treatment"]["score"]),
                        "result": row["treatment"]["result"],
                    }
                )
        best = max(routes, key=lambda item: item["score"]) if routes else None
        selected_rows.append(
            {
                "key": list(key),
                "safe_routes": routes,
                "selected": best,
                "gain_over_v111": 0.0 if best is None else best["score"] - float(control["score"]),
            }
        )
    return {
        "scope": "sample-in offline upper bound over raw-safe routes only",
        "not_a_deployable_selector": True,
        "contexts_with_any_safe_route": sum(row["selected"] is not None for row in selected_rows),
        "mean_gain_treating_no_safe_route_as_zero": statistics.mean(row["gain_over_v111"] for row in selected_rows),
        "rows": selected_rows,
    }


def control_reproduction(new_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    old_rows = {(row["lineage_id"], int(row["seed"]), int(row["seat"])): row for row in load_jsonl(OLD_PAIRS)}
    old_freeze = load(OLD_EXP / "candidate_freeze.json")
    prereg = load(EXP / "preregistration.json")
    current_core = prereg["environment"]["evaluation_core_sha256"]
    old_core = old_freeze["identity"]["evaluation_core"]
    component_match = {name: old_core.get(name) == digest for name, digest in current_core.items()}
    component_match["runner.py"] = old_core.get("runner.py") == current_core["runner.py"]
    metadata = {
        "engine": old_freeze["identity"]["engine"] == prereg["environment"]["engine_sha256"],
        "configuration": old_freeze["identity"]["engine_json"] == prereg["environment"]["configuration_sha256"],
        "control": old_freeze["identity"]["source"] == prereg["candidate_hashes"]["V111"],
        "evaluation_core_components": component_match,
        "evaluation_core_all_match": all(component_match.values()),
    }
    comparisons = []
    for candidate, rows in new_rows.items():
        for row in rows:
            key = (row["lineage_id"], int(row["seed"]), int(row["seat"]))
            old = old_rows[key]
            old_replay = read_replay(old["replay_artifacts"]["control"])
            new_replay = read_replay(row["replay_artifacts"]["control"])
            comparisons.append(
                {
                    "candidate_run": candidate,
                    "key": list(key),
                    "public_result_equal": old["control"] == row["control"],
                    "semantic_720_equal_excluding_remainingOverageTime": clean_steps(old_replay)
                    == clean_steps(new_replay),
                }
            )
    return {
        "created_at": now(),
        "old_replay_reuse_eligible": all(metadata.values()),
        "reuse_decision": "NOT_REUSED; V111 control was independently rerun",
        "metadata_hash_match": metadata,
        "note": (
            "The old freeze's evaluator identity and required-file section disagree on runner.py; "
            "the conservative path was independent control execution."
        ),
        "comparisons": comparisons,
        "all_public_results_equal": all(row["public_result_equal"] for row in comparisons),
        "all_semantic_720_equal": all(row["semantic_720_equal_excluding_remainingOverageTime"] for row in comparisons),
    }


def forbidden_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    integrity = load(EXP / "candidate_integrity.json")["candidates"]
    p1 = rows[0]
    replay = read_replay(p1["replay_artifacts"]["treatment"])
    obs = observation(replay, 0, int(p1["seat"]))
    forbidden_keys = {
        "seed",
        "opponent_name",
        "source_id",
        "team_id",
        "submission_id",
        "episode_id",
    }
    return {
        "created_at": now(),
        "P1_static": integrity["P1_psr_clean"]["feature_audit"],
        "D1_static": integrity["D1_e052a_no_opponent_tape"]["feature_audit"],
        "runtime": {
            "observation_top_level_keys": sorted(obs),
            "forbidden_identity_keys_present": sorted(forbidden_keys & set(obs)),
            "agent_exceptions": sum(
                len((row.get("agent_trace", {}).get("treatment") or {}).get("agent_exceptions") or []) for row in rows
            ),
            "fallback_steps": sum(
                int((row.get("agent_trace", {}).get("treatment") or {}).get("fallback_steps", 0) or 0) for row in rows
            ),
            "isolation": "fresh package load per game; kaggriculture module isolated; step-0 reset tested",
        },
        "passed": integrity["P1_psr_clean"]["feature_audit"]["passed"] and not (forbidden_keys & set(obs)),
        "scope_limit": (
            "Runtime observation contains public state and own private state only; static audit establishes "
            "that P1 has no opponent identity/seed/tape lookup path."
        ),
    }


def update_safety_first_events(all_rows: dict[str, list[dict[str, Any]]]) -> None:
    from scripts.audit_clean_psr_prerun import first_event_map

    path = EXP / "safety_first_event_map.json"
    original = load(path)
    original["candidate_maps"] = {}
    for candidate in ("D1_e052a_no_opponent_tape", "P1_psr_clean"):
        value = first_event_map(all_rows[candidate])
        value["scope"] = f"{candidate} spent treatment replays; first-event diagnostics"
        original["candidate_maps"][candidate] = value
    original["updated_after_spent_at"] = now()
    original["causal_limit"] = "Temporal order is diagnostic and is not treated as proof of the win mechanism."
    save(path, original)


def gate(summary: dict[str, Any], forbidden: dict[str, Any]) -> dict[str, Any]:
    overall = summary["overall"]
    transitions = overall["transitions"]
    checks = {
        "runtime_delivery_zero": summary["safety"]["runtime_or_delivery_failures"] == 0,
        "raw_safety_zero": summary["safety"]["raw_failure_contexts"] == 0,
        "positive_delta": overall["delta_win_score"] > 0,
        "loss_to_win_two_blocks": summary["independent_loss_to_win_blocks"] >= 2,
        "loss_to_win_two_sources": len(summary["independent_loss_to_win_sources"]) >= 2,
        "win_to_loss_zero": transitions.get("win->loss", 0) == 0,
        "win_to_draw_zero": transitions.get("win->draw", 0) == 0,
        "each_source_nonnegative": all(value["delta_win_score"] >= 0 for value in summary["by_source"].values()),
        "exclusions_nonnegative": all(value["delta_win_score"] >= 0 for value in summary["exclusions"].values()),
        "equal_source_positive": summary["weighting"]["equal_source_delta"] > 0,
        "equal_ancestry_positive": summary["weighting"]["equal_ancestry_delta"] > 0,
        "nine_scenario_worst_positive": summary["weighting"]["nine_scenario_worst_delta"] > 0,
        "bootstrap_lower_positive": summary["whole_source_seed_block_bootstrap"]["low_95"] > 0,
        "forbidden_feature_audit": forbidden["passed"],
    }
    return {"checks": checks, "passed": all(checks.values())}


def seed_ledger() -> dict[str, Any]:
    ranges = {
        "promotion": set(range(10091101, 10091113)),
        "fresh": set(range(10091901, 10091913)),
        "new_development": set(range(10091421, 10091437)),
    }
    records = []
    excluded = {".git", ".venv", "vendor", "node_modules", "__pycache__"}
    wanted = set().union(*ranges.values())
    for path in ROOT.rglob("*.jsonl"):
        if any(part in excluded for part in path.parts):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            found = {
                int(value[name])
                for name in ("seed", "requested_seed", "resolved_seed")
                if isinstance(value.get(name), int) and int(value[name]) in wanted
            }
            records.extend(
                {
                    "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "line": number,
                    "seed": item,
                }
                for item in sorted(found)
            )
    used = {row["seed"] for row in records}
    result = {
        "created_at": now(),
        "method": "repository-wide structured *.jsonl seed-field audit; binary/cache/vendor excluded",
        "structured_usage_records": records,
    }
    for name, values in ranges.items():
        hits = sorted(used & values)
        result[name] = {
            "range": [min(values), max(values)],
            "used": hits,
            "status": "UNUSED" if not hits else "USED",
        }
    return result


def relevant_processes() -> list[dict[str, Any]]:
    command = (
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|kaggle' } | "
        "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Depth 3"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode or not completed.stdout.strip():
        return []
    value = json.loads(completed.stdout)
    return value if isinstance(value, list) else [value]


def report_text(
    summaries: dict[str, dict[str, Any]],
    comparison: dict[str, Any],
    discovery_gate: dict[str, Any],
    screen: dict[str, Any],
) -> str:
    r0 = summaries["R0_v116_frozen_reference"]
    d1 = summaries["D1_e052a_no_opponent_tape"]
    p1 = summaries["P1_psr_clean"]
    p1_sources = p1["by_source"]

    def result_row(label: str, value: dict[str, Any]) -> str:
        overall = value["overall"]
        candidate = overall["candidate"]
        return (
            f"| {label} | {candidate['wins']}/{candidate['draws']}/{candidate['losses']} | "
            f"{overall['delta_win_score']:+.4f} | {value['safety']['raw_failure_contexts']}/32 | "
            f"{value['independent_loss_to_win_blocks']} | "
            f"{overall['transitions'].get('win->loss', 0)} |"
        )

    r0_row = result_row("R0 v116 frozen", r0)
    d1_row = result_row("D1 no tape", d1)
    p1_row = result_row("P1 clean PSR", p1)
    return f"""# 公開状態routerのclean-room評価（2026-09-14/15）

## 結論

最終判断は **REJECT_SAFETY** である。P1_psr_clean は旧spent panelで 24/0/8、V111比
win-score差 {p1["overall"]["delta_win_score"]:+.4f} を得たが、raw Safetyは
{p1["safety"]["raw_failure_contexts"]}/32 contextで不合格となり、V111の既存勝ちも
{p1["overall"]["transitions"].get("win->loss", 0)}件失った。production ChampionはV111のまま維持する。

Kaggle提出、kernel push、submission slot変更は実施していない。promotion seeds
10091101–10091112、Fresh seeds 10091901–10091912、新規Development seeds
10091421–10091436はいずれも未使用である。

## Sourceとintegrity

公開notebook [Kaggriculture: 93.8% Win Rate Public State Router](https://www.kaggle.com/code/thomastschinkel/kaggriculture-93-8-win-rate-public-state-router)
のVersion 3をread-only APIで取得した。main.py SHA-256は
`91772fda544e2d5768afff819e2de75ecb7a12db8acb40a48ee9edcf76aca434`である。
表示licenseはApache-2.0だが、本文が言及するroute-data provenance.jsonを取得物内で確認できず、
transitive provenance/licenseは未確認である。そのためP1は結果にかかわらずresearch-onlyとした。

静的・runtime監査ではP1にopponent名/source/seed/ID、既知相手position signature、将来SELL表、
private opponent state、future RNGへの依存は見つからなかった。P1はstep 0から単独で動き、
外側のv56 opening、E030、tape/oracle、step216 hybrid等を混ぜていない。

## Paired結果

| candidate | W/D/L | V111比 win-score差 | raw Safety | L→W blocks | W→L |
|---|---:|---:|---:|---:|---:|
{r0_row}
{d1_row}
{p1_row}

P1のsource別差は、mooman {p1_sources["mooman_e052a"]["delta_win_score"]:+.4f}、
souvik {p1_sources["souvik_v4"]["delta_win_score"]:+.4f}、ggmljs
{p1_sources["ggmljs_v16"]["delta_win_score"]:+.4f}、qeinstein
{p1_sources["qeinstein_moev2"]["delta_win_score"]:+.4f}だった。whole source+seed block bootstrap
95%区間は [{p1["whole_source_seed_block_bootstrap"]["low_95"]:+.4f},
{p1["whole_source_seed_block_bootstrap"]["high_95"]:+.4f}] である。両seatは各source+seedの1事例として保持した。

## Tape交絡とablation

既存32 replayの独立再計算は、tape2がmoomanとsouvikで各8/8、qeinsteinとggmljsで0/8
という既報と一致した。sidecar tracerは32×719 decisionの実actionと完全一致した。

D1ではqeinsteinのL→W 4件とsouvikのL→W 6件が残り、souvik改善は件数上は縮まなかった。
ただしR0→D1の全体差は {comparison["r0_to_d1"]["overall_delta_win_score"]:+.4f} で、D1は
raw Safety 28/32かつW→L 2件の診断候補である。この同一context結果は、tapeが無因果であることや
別panelへの一般化を証明しない。D1→P1は複数層が同時に変わるため単一component効果とは呼ばない。

## Safetyとrepair判断

P1では新規animal lossとcrop-to-weedがともに32/32で発生した。first-event監査は、animal lossを
2日連続未給餌によるescape（必須FEED欠落）として、crop-to-weedをwater deathまたはlifespan decay/
収穫欠落として区別した。さらにsource依存でsilent market no-op、partial commit、field no-opもある。
これは1個のinvalid actionをPASSへ置換するだけでは隠せない複数contract failureである。

P1は既にW→L=2でPrimary efficacy条件も外しているため、Safety専用repairで救済するP2の作成条件を
満たさない。勝敗を見てrepairを選ぶこと、複数repair探索は行わなかった。

## 独立sourceと一般化

Primary結果を見る前のV111-only screenでは、Deepesh、Lonespear、robriculture_lean_feedの3 source
すべてにV111が8/8勝ち、win-score 1.0だった。事前登録の0.25–0.75を満たすsourceは0件で、
追加sourceは選択されなかった。したがって検証済みancestryは既存2群のままで、強い第3 ancestryへの
一般化は未証明である。最終status上限は`PROMISING_UNPROVEN`だったが、P1自身はSafety不合格のため
`REJECT_SAFETY`となる。

## Gateと終了状態

Primary discovery gateは `{str(discovery_gate["passed"]).lower()}`。失敗項目は
{", ".join(name for name, passed in discovery_gate["checks"].items() if not passed)} である。
このため新規Development確認は開始せず、numeric production agentも作成していない。
experiment内のP1/D1 archiveはresearch-onlyであり、V111を変更しない。

全gameは720 states（通常719 decisions）を完走し、runtime error、timeout、negative cash、delivery failureは0。
A/AはV111、D1、P1のすべてで独立ロード間のaction/state/final coinが一致した。旧V111 controlは
evaluator metadataの不整合を保守的に扱って再利用せず独立再実行し、旧replayと
`remainingOverageTime`を除く全720 stateが一致した。

詳細なsource/ancestry集計、9 reweighting、除外感度、bootstrap、divergence、coin、lifecycle、
terminal proxy、order/step監査、sample-in safe oracleはcandidate summaryと
`performance_attribution.json`に保存した。相手coin低下はclosed-loopのtotal-policy差であり、
単一actionの因果効果とは解釈しない。
"""


def main() -> None:
    all_rows = {candidate: load_jsonl(path) for candidate, path in CANDIDATES.items()}
    update_safety_first_events(all_rows)
    summaries = {candidate: candidate_summary(candidate, rows) for candidate, rows in all_rows.items()}
    reuse_r0_artifacts(summaries["R0_v116_frozen_reference"])
    for candidate in ("D1_e052a_no_opponent_tape", "P1_psr_clean"):
        save(EXP / "candidates" / candidate / "summary" / "complete.json", summaries[candidate])

    comparison = {
        "created_at": now(),
        "r0_to_d1": comparison_summary(
            "R0_v116_frozen_reference",
            all_rows["R0_v116_frozen_reference"],
            "D1_e052a_no_opponent_tape",
            all_rows["D1_e052a_no_opponent_tape"],
            "Minimal known-opponent position gate and future SELL-table ablation.",
        ),
        "d1_to_p1": comparison_summary(
            "D1_e052a_no_opponent_tape",
            all_rows["D1_e052a_no_opponent_tape"],
            "P1_psr_clean",
            all_rows["P1_psr_clean"],
            "Multiple layers change; this is not a single-component effect.",
        ),
        "safe_route_offline_oracle": safe_oracle(all_rows),
        "causal_limit": "Temporal order and coin mediation do not identify a single-action causal effect.",
    }
    save(EXP / "performance_attribution.json", comparison)

    reproduction = control_reproduction(
        {candidate: all_rows[candidate] for candidate in ("D1_e052a_no_opponent_tape", "P1_psr_clean")}
    )
    save(EXP / "control_reproduction.json", reproduction)
    forbidden = forbidden_audit(all_rows["P1_psr_clean"])
    save(EXP / "forbidden_feature_audit.json", forbidden)
    primary_gate = gate(summaries["P1_psr_clean"], forbidden)
    save(EXP / "primary_discovery_gate.json", primary_gate)
    p2 = {
        "created_at": now(),
        "created": False,
        "authorized": False,
        "reasons": [
            "P1 has two W->L regressions, so it does not retain all primary efficacy conditions",
            "first events span animal escape/required FEED omission and crop water/lifespan/harvest contracts",
            "market and field no-op classes also occur; no single unique repair covers the failures",
        ],
        "repair_searches": 0,
        "outcome_based_repair_selection": False,
    }
    save(EXP / "p2_decision.json", p2)

    ledger = seed_ledger()
    save(EXP / "seed_ledger.json", ledger)
    screen = load(EXP / "independent_screen" / "selection.json")
    final = {
        "created_at": now(),
        "experiment": "research_20260914_clean_psr",
        "decision": "REJECT_SAFETY",
        "production_champion": {"version": "V111", "status": "RETAIN"},
        "primary_candidate": {
            "id": "P1_psr_clean",
            "status": "REJECT",
            "numeric_agent_created": False,
            "archive_status": "research-only",
            "reasons": [
                "raw Safety failures in 32/32 spent contexts",
                "two V111 wins regressed to losses",
                "no qualifying independent source; only two verified ancestry groups",
                "transitive route-data provenance/license unverified",
            ],
        },
        "diagnostic_candidate": {
            "id": "D1_e052a_no_opponent_tape",
            "promotion_eligible": False,
            "status": "diagnostic only",
        },
        "headline": summaries["P1_psr_clean"]["overall"],
        "safety": summaries["P1_psr_clean"]["safety"],
        "primary_discovery_gate": primary_gate,
        "p2": p2,
        "development_confirmation": "NOT_OPENED",
        "verified_ancestry_groups": 2,
        "independent_source_selection": screen,
        "submission": "NOT_PERFORMED",
        "kernel_push": "NOT_PERFORMED",
        "submission_slot_change": "NOT_PERFORMED",
        "promotion_seeds": ledger["promotion"],
        "fresh_seeds": ledger["fresh"],
        "new_development_seeds": ledger["new_development"],
    }
    save(EXP / "final_decision.json", final)

    DOC.write_text(report_text(summaries, comparison, primary_gate, screen), encoding="utf-8")
    processes = relevant_processes()
    evaluation_processes = [
        row
        for row in processes
        if "run_clean_psr_research.py" in str(row.get("CommandLine") or "")
        or "finalize_clean_psr_research.py" in str(row.get("CommandLine") or "")
    ]
    # The current finalizer process may appear in the PowerShell command line; only runner workers matter.
    runner_processes = [
        row for row in evaluation_processes if "run_clean_psr_research.py" in str(row.get("CommandLine") or "")
    ]
    manifest = load(EXP / "manifest.json")
    manifest["current_phase"] = "FINALIZED"
    manifest["finalized_at"] = now()
    manifest["final_decision"] = "REJECT_SAFETY"
    manifest["relevant_processes_at_end"] = processes
    manifest["evaluation_runner_processes_at_end"] = runner_processes
    manifest["git_status_short_at_end"] = subprocess.run(
        ["git", "status", "--short"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    save(EXP / "manifest.json", manifest)

    expected_hashes = {
        "engine": load(EXP / "preregistration.json")["environment"]["engine_sha256"],
        "configuration": load(EXP / "preregistration.json")["environment"]["configuration_sha256"],
    }
    engine = ROOT / ".venv" / "Lib" / "site-packages" / "kaggle_environments" / "envs" / "kaggriculture"
    actual_hashes = {
        "engine": sha256(engine / "kaggriculture.py"),
        "configuration": sha256(engine / "kaggriculture.json"),
    }
    replay_paths = sorted(
        {
            Path(row["replay_artifacts"][arm]).resolve()
            for rows in all_rows.values()
            for row in rows
            for arm in ("control", "treatment")
        }
    )
    verification = {
        "created_at": now(),
        "expected_hashes": expected_hashes,
        "actual_hashes": actual_hashes,
        "engine_configuration_hashes_ok": expected_hashes == actual_hashes,
        "candidate_rows": {
            candidate: {
                "rows": len(rows),
                "unique_keys": len({(row["lineage_id"], row["seed"], row["seat"]) for row in rows}),
                "all_completed_720": summaries[candidate]["safety"]["all_completed_720"],
            }
            for candidate, rows in all_rows.items()
        },
        "replay_count": len(replay_paths),
        "replay_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in replay_paths},
        "aa": {
            candidate: load(EXP / "candidates" / candidate / "summary" / "aa.json")
            for candidate in ("V111", "D1_e052a_no_opponent_tape", "P1_psr_clean")
        },
        "control_reproduction": {
            "all_public_results_equal": reproduction["all_public_results_equal"],
            "all_semantic_720_equal": reproduction["all_semantic_720_equal"],
        },
        "duplicate_reconciliation": load(EXP / "duplicate_pair_reconciliation.json"),
        "reserved_seeds_all_unused": all(
            ledger[name]["status"] == "UNUSED" for name in ("promotion", "fresh", "new_development")
        ),
        "evaluation_runner_processes_at_end": runner_processes,
        "submission": "NOT_PERFORMED",
        "fresh": "SEALED_UNOPENED",
        "promotion": "SEALED_UNOPENED",
        "final_artifact_manifest_excluded": "avoids a circular self-reference",
    }
    save(EXP / "final_artifact_verification.json", verification)

    mandatory = [
        ROOT / "docs" / "research_20260914_clean_psr_preregistration.md",
        DOC,
        EXP / "manifest.json",
        EXP / "source_acquisition.json",
        EXP / "source_layer_map.json",
        EXP / "tape_confounding_audit.json",
        EXP / "safety_first_event_map.json",
        EXP / "candidate_integrity.json",
        EXP / "performance_attribution.json",
        EXP / "seed_ledger.json",
        EXP / "final_decision.json",
        EXP / "final_artifact_verification.json",
        EXP / "control_reproduction.json",
        EXP / "forbidden_feature_audit.json",
        EXP / "primary_discovery_gate.json",
        EXP / "p2_decision.json",
        ROOT / "scripts" / "acquire_clean_psr_source.py",
        ROOT / "scripts" / "prepare_clean_psr_candidates.py",
        ROOT / "scripts" / "audit_clean_psr_prerun.py",
        ROOT / "scripts" / "finalize_clean_psr_prerun.py",
        ROOT / "scripts" / "run_clean_psr_research.py",
        ROOT / "scripts" / "reconcile_clean_psr_duplicates.py",
        Path(__file__),
    ]
    for candidate in CANDIDATES:
        mandatory.append(EXP / "candidates" / candidate / "summary" / "complete.json")
    artifact_manifest = {
        "created_at": now(),
        "files": {
            str(path.relative_to(ROOT)).replace("\\", "/"): {
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in mandatory
        },
        "candidate_directories": {
            candidate: str((EXP / "candidates" / candidate).relative_to(ROOT)).replace("\\", "/")
            for candidate in CANDIDATES
        },
        "replay_hashes_stored_in": ("experiments/research_20260914_clean_psr/final_artifact_verification.json"),
        "reproduce_commands": [
            ".\\.venv\\Scripts\\python.exe scripts\\run_clean_psr_research.py validate",
            ".\\.venv\\Scripts\\python.exe scripts\\run_clean_psr_research.py aa --candidate V111 --workers 2",
            (
                ".\\.venv\\Scripts\\python.exe scripts\\run_clean_psr_research.py aa "
                "--candidate D1_e052a_no_opponent_tape --workers 2"
            ),
            ".\\.venv\\Scripts\\python.exe scripts\\run_clean_psr_research.py aa --candidate P1_psr_clean --workers 2",
            ".\\.venv\\Scripts\\python.exe scripts\\run_clean_psr_research.py screen --workers 4",
            (
                ".\\.venv\\Scripts\\python.exe scripts\\run_clean_psr_research.py smoke "
                "--candidate D1_e052a_no_opponent_tape --workers 4"
            ),
            (
                ".\\.venv\\Scripts\\python.exe scripts\\run_clean_psr_research.py smoke "
                "--candidate P1_psr_clean --workers 4"
            ),
            (
                ".\\.venv\\Scripts\\python.exe scripts\\run_clean_psr_research.py spent "
                "--candidate D1_e052a_no_opponent_tape --workers 4"
            ),
            (
                ".\\.venv\\Scripts\\python.exe scripts\\run_clean_psr_research.py spent "
                "--candidate P1_psr_clean --workers 4"
            ),
            ".\\.venv\\Scripts\\python.exe scripts\\finalize_clean_psr_research.py",
        ],
        "resume_command": (
            ".\\.venv\\Scripts\\python.exe scripts\\run_clean_psr_research.py spent "
            "--candidate <frozen-candidate-id> --workers 4"
        ),
        "submission": "NOT_PERFORMED",
        "fresh": "SEALED_UNOPENED",
        "promotion": "SEALED_UNOPENED",
        "self_excluded": "final_artifact_manifest.json",
    }
    save(EXP / "final_artifact_manifest.json", artifact_manifest)
    print(
        json.dumps(
            {
                "decision": final["decision"],
                "P1": summaries["P1_psr_clean"]["overall"],
                "safety": summaries["P1_psr_clean"]["safety"],
                "gate": primary_gate,
                "manifest_files": len(artifact_manifest["files"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
