"""Build a timestamped, discovery-only view of the current Kaggriculture Top 5.

The script joins read-only public EpisodeService metadata to the downloaded
replays, reuses the canonical replay analyzers, and contrasts the result with
the frozen September 10 discovery corpus.  It never submits to Kaggle and it
refuses holdout-labelled inputs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import analyze_current_meta_20260909 as meta  # noqa: E402
from scripts.evaluation.lifecycle import analyze_lifecycle  # noqa: E402
from scripts.evaluation.replay import decision_count  # noqa: E402
from scripts.evaluation.safety import analyze_safety  # noqa: E402

SNAPSHOT = ROOT / "experiments/research_20260914_lowcash/remote/20260915_153354/leaderboard.json"
CURRENT = ROOT / "data/current_field_20260916"
OLD = ROOT / "data/analysis/research_20260910_final/current_episode_seat_metrics.json"
OUT = ROOT / "data/analysis/research_20260916_next_strategy"
BATCH_LABEL = "current_top_20260916"
TOP_N = 5


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = probability * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def median_or_none(values: list[float]) -> float | None:
    return median(values) if values else None


def compact_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    base = meta.summary(rows)
    base["source_warning"] = (
        "Latest six EpisodeService rows per target submission; observational, "
        "opponent-mix selected, not a rating estimate or a paired comparison."
    )
    return base


def order_step(row: dict[str, Any], prefix: str) -> int | None:
    values = [int(step) for key, step in row["first_market_order"].items() if key.startswith(prefix)]
    return min(values, default=None)


def timing_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "land_unlock_steps": {},
        "first_market_order_steps": {},
        "last_irreversible_investment": median_or_none(
            [
                float(row["last_irreversible_investment"])
                for row in rows
                if row["last_irreversible_investment"] is not None
            ]
        ),
    }
    for index in range(3):
        values = [float(row["land_timing"][index]) for row in rows if len(row["land_timing"]) > index]
        result["land_unlock_steps"][str(index + 2)] = {
            "n": len(values),
            "median": median_or_none(values),
            "p10": percentile(values, 0.10),
            "p90": percentile(values, 0.90),
        }
    prefixes = [
        "HIRE_",
        "BUY_LAND_",
        "BUY_ANIMAL_COW",
        "BUY_ANIMAL_SHEEP",
        "BUY_ANIMAL_GOOSE",
        "BUY_SEED_WHEAT",
        "BUY_SEED_CARROT",
        "BUY_SEED_TOMATO",
        "BUY_SEED_STRAWBERRY",
        "BUY_SEED_MELON",
    ]
    for prefix in prefixes:
        values = [float(value) for row in rows if (value := order_step(row, prefix)) is not None]
        result["first_market_order_steps"][prefix.rstrip("_")] = {
            "n": len(values),
            "median": median_or_none(values),
            "p10": percentile(values, 0.10),
            "p90": percentile(values, 0.90),
        }
    return result


def mean_dict(rows: list[dict[str, Any]], key: str, labels: tuple[str, ...]) -> dict[str, float]:
    return {label: mean(float(row[key].get(label, 0)) for row in rows) if rows else 0.0 for label in labels}


def current_corpus() -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    snapshot = read_json(SNAPSHOT)
    board = snapshot["data"]["publicLeaderboard"]
    leaders = board[:TOP_N]
    target_ids = {int(row["submissionId"]) for row in leaders}
    ranks = {int(row["submissionId"]): int(row["rank"]) for row in leaders}
    names = {
        int(team["teamId"]): str(team.get("teamName", ""))
        for team in snapshot["data"].get("teams", [])
    }
    episodes: dict[int, dict[str, Any]] = {}
    paths: dict[int, Path] = {}
    downloaded_memberships: list[dict[str, Any]] = []

    for submission_id in sorted(target_ids, key=ranks.get):
        directory = CURRENT / "submissions" / f"{BATCH_LABEL}_submission_{submission_id}"
        response = read_json(directory / "episode_service_response.json")
        for team in response.get("teams", []):
            names[int(team["id"])] = str(team.get("teamName", ""))
        for episode in response.get("episodes", []):
            episodes[int(episode["id"])] = episode
        with (directory / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("replay_status") not in {"downloaded", "skipped_existing"}:
                    continue
                episode_id = int(row["episode_id"])
                path = CURRENT / row["replay_path"]
                if not path.is_file():
                    raise FileNotFoundError(path)
                paths.setdefault(episode_id, path)
                downloaded_memberships.append(
                    {
                        "submission_id": submission_id,
                        "rank": ranks[submission_id],
                        "episode_id": episode_id,
                        "seat": int(row["submission_seat"]),
                        "path": str(path.relative_to(ROOT)),
                    }
                )

    if any("holdout" in json.dumps(row).lower() for row in downloaded_memberships):
        raise ValueError("Refusing a holdout-labelled input")

    cohorts = {submission_id: f"current_top_rank_{rank}" for submission_id, rank in ranks.items()}
    inputs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    sales: list[dict[str, Any]] = []
    for episode_id, path in sorted(paths.items()):
        replay = meta.read_json(path)
        if decision_count(replay) != 719:
            raise ValueError(f"Episode {episode_id} is not a complete 719-decision replay")
        episode = episodes[episode_id]
        inputs.append(
            {
                "episode_id": episode_id,
                "path": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "dataset_role": "current_top_discovery",
            }
        )
        for seat in (0, 1):
            record, day_rows, event_rows, sale_rows = meta.analyze_seat(replay, episode, seat, names, cohorts)
            rows.append(record)
            daily.extend(day_rows)
            events.extend(event_rows)
            sales.extend(sale_rows)

    membership_keys = {
        (int(item["submission_id"]), int(item["episode_id"])) for item in downloaded_memberships
    }
    selected = [
        row
        for row in rows
        if (int(row["submission_id"]), int(row["episode_id"])) in membership_keys
    ]
    if len(selected) != len(downloaded_memberships):
        raise ValueError(
            f"Expected {len(downloaded_memberships)} selected seats, found {len(selected)}; "
            "download membership may contain an unaccounted duplicate"
        )
    return snapshot, inputs, downloaded_memberships, selected, daily, events, sales


def build_execution_audit(
    inputs: list[dict[str, Any]], memberships: list[dict[str, Any]]
) -> dict[str, Any]:
    paths = {int(row["episode_id"]): ROOT / row["path"] for row in inputs}
    replay_cache: dict[int, dict[str, Any]] = {}
    contexts: list[dict[str, Any]] = []
    for membership in memberships:
        episode_id = int(membership["episode_id"])
        replay = replay_cache.setdefault(episode_id, meta.read_json(paths[episode_id]))
        seat = int(membership["seat"])
        safety = analyze_safety(replay, seat, {})
        lifecycle = analyze_lifecycle(replay, seat)
        contexts.append(
            {
                **membership,
                "completed_720": safety["completed_720"],
                "runtime_failures": safety["runtime_failures"],
                "minimum_cash": safety["minimum_cash"],
                "animal_losses": safety["animal_losses"],
                "animal_loss_total": safety["animal_loss_total"],
                "plant_to_weed": safety["plant_to_weed"],
                "spawned_weeds": safety["spawned_weeds"],
                "engine_action_audit": safety["engine_action_audit"],
                "lifecycle_counts": lifecycle["counts"],
                "lost_current_units": lifecycle["lost_current_units"],
                "successful_harvest_units": lifecycle["successful_harvest_units"],
            }
        )

    keys = (
        "silent_field_noop",
        "silent_market_noop",
        "partial_market_commit",
        "oversized_sell",
        "failed_required_purchase",
        "missing_hand_actions",
        "market_orders_truncated",
        "malformed_market_order",
    )

    def aggregate(values: list[dict[str, Any]]) -> dict[str, Any]:
        action_totals = {
            key: sum(int(row["engine_action_audit"].get(key, 0)) for row in values) for key in keys
        }
        return {
            "contexts": len(values),
            "all_completed_720": all(row["completed_720"] for row in values),
            "runtime_failure_contexts": sum(bool(row["runtime_failures"]) for row in values),
            "minimum_cash": min((float(row["minimum_cash"]) for row in values), default=None),
            "animal_loss_contexts": sum(int(row["animal_loss_total"]) > 0 for row in values),
            "animal_loss_units": sum(int(row["animal_loss_total"]) for row in values),
            "plant_to_weed_contexts": sum(int(row["plant_to_weed"]) > 0 for row in values),
            "plant_to_weed_events": sum(int(row["plant_to_weed"]) for row in values),
            "spawned_weeds": sum(int(row["spawned_weeds"]) for row in values),
            "engine_action_totals": action_totals,
            "engine_action_contexts": {
                key: sum(int(row["engine_action_audit"].get(key, 0)) > 0 for row in values) for key in keys
            },
            "successful_harvest_units": dict(
                sum((Counter(row["successful_harvest_units"]) for row in values), Counter())
            ),
            "lost_current_units": dict(
                sum((Counter(row["lost_current_units"]) for row in values), Counter())
            ),
        }

    return {
        "evidence_level": "E0_ENGINE_REPLAY_AUDIT",
        "scope": "Absolute execution diagnostics for 30 current Top-5 target seats; no V111 counterfactual.",
        "overall": aggregate(contexts),
        "by_rank": {
            str(rank): aggregate([row for row in contexts if int(row["rank"]) == rank])
            for rank in range(1, TOP_N + 1)
        },
        "contexts": contexts,
        "interpretation_limit": (
            "An absolute no-op or lifecycle event is not automatically harmful; only paired candidate-new "
            "events can define a promotion Safety regression."
        ),
    }


def build_evidence(
    snapshot: dict[str, Any],
    inputs: list[dict[str, Any]],
    memberships: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    sales: list[dict[str, Any]],
) -> dict[str, Any]:
    board = snapshot["data"]["publicLeaderboard"]
    teams = {int(row["teamId"]): row for row in snapshot["data"].get("teams", [])}
    leaders = board[:TOP_N]
    ranks = {int(row["submissionId"]): int(row["rank"]) for row in leaders}
    old_rows = read_json(OLD)
    historical_v111 = [row for row in old_rows if row["cohort"] == "champion_v111"]
    prior_top = [row for row in old_rows if str(row["cohort"]).startswith("top_rank_")]

    old_snapshot = read_json(ROOT / "data/current_field_20260910/leaderboard.json")
    prior_board = old_snapshot["data"]["publicLeaderboard"][:30]
    current_board = board[:30]
    prior_submissions = {int(row["submissionId"]) for row in prior_board}
    current_submissions = {int(row["submissionId"]) for row in current_board}
    prior_teams = {int(row["teamId"]) for row in prior_board}
    current_teams = {int(row["teamId"]) for row in current_board}

    by_rank: dict[str, Any] = {}
    for leader in leaders:
        submission_id = int(leader["submissionId"])
        subset = [row for row in rows if int(row["submission_id"]) == submission_id]
        by_rank[str(leader["rank"])] = {
            "team": teams.get(int(leader["teamId"]), {}).get("teamName", ""),
            "submission_id": submission_id,
            "leaderboard_rating": float(leader["displayScore"]),
            "sample": compact_summary(subset),
            "timing": timing_summary(subset),
            "opening_field_h48_counts": dict(Counter(row["field_hashes"].get("48") for row in subset)),
        }

    opening_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        opening_groups[str(row["field_hashes"].get("48"))].append(row)
    opening = [
        {
            "field_h48": digest,
            "seat_records": len(values),
            "submissions": sorted({int(row["submission_id"]) for row in values}),
            "ranks": sorted({ranks[int(row["submission_id"])] for row in values}),
            "continuation_action_hashes": len({row["continuation_action_hash_144_600"] for row in values}),
            "portfolio_continuations": len({row["daily_portfolio_hash_144_600"] for row in values}),
        }
        for digest, values in sorted(opening_groups.items(), key=lambda item: -len(item[1]))
    ]

    membership_keys = {
        (int(item["submission_id"]), int(item["episode_id"])) for item in memberships
    }
    target_sales = [
        row
        for row in sales
        if (int(row["submission_id"]), int(row["episode_id"])) in membership_keys
    ]
    sale_phase: dict[str, Any] = {}
    for product in meta.PRODUCTS:
        subset = [row for row in target_sales if row["product"] == product]
        requested = Counter(int(row["phase4"]) for row in subset)
        units = Counter()
        for row in subset:
            units[int(row["phase4"])] += int(row["availability_capped_qty"])
        sale_phase[product] = {
            "orders": {str(phase): requested[phase] for phase in range(4)},
            "availability_capped_units": {str(phase): units[phase] for phase in range(4)},
            "warning": "requested sales capped by pre-action shed, not engine-committed revenue",
        }

    assets = tuple(meta.ASSETS)
    current_summary = compact_summary(rows)
    v111_summary = compact_summary(historical_v111)
    prior_top_summary = compact_summary(prior_top)
    comparisons = {
        "warning": (
            "These are cross-corpus descriptive differences, not paired effects. "
            "Current Top 5 rows are September 16 JST latest-public samples; V111 rows end September 1."
        ),
        "current_top5_minus_historical_v111_mean_portfolio": {
            asset: current_summary["mean_portfolio"][asset] - v111_summary["mean_portfolio"][asset]
            for asset in assets
        },
        "current_top5_minus_prior_top_mean_portfolio": {
            asset: current_summary["mean_portfolio"][asset] - prior_top_summary["mean_portfolio"][asset]
            for asset in assets
        },
        "mean_stranded_price_proxy": {
            "current_top5": current_summary["mean_stranded_price_proxy"],
            "historical_v111": v111_summary["mean_stranded_price_proxy"],
            "september10_top": prior_top_summary["mean_stranded_price_proxy"],
        },
        "day18_lead_to_loss_rate": {
            "current_top5": current_summary["lead_to_loss"]["day18"] / max(1, current_summary["n"]),
            "historical_v111": v111_summary["lead_to_loss"]["day18"] / max(1, v111_summary["n"]),
            "september10_top": prior_top_summary["lead_to_loss"]["day18"] / max(1, prior_top_summary["n"]),
        },
    }

    result_split = {}
    for outcome in ("win", "loss"):
        subset = [row for row in rows if row["result"] == outcome]
        result_split[outcome] = {
            "n": len(subset),
            "mean_self_coin": mean(float(row["self_final_coin"]) for row in subset) if subset else None,
            "mean_margin": mean(float(row["final_margin"]) for row in subset) if subset else None,
            "mean_portfolio": mean_dict(subset, "continuation_mean_portfolio", assets),
            "mean_opponent_portfolio": mean_dict(subset, "opponent_mean_portfolio", assets),
            "mean_stranded_price_proxy": (
                mean(float(row["final_stranded_observed_price_proxy"]) for row in subset) if subset else None
            ),
        }

    return {
        "evidence_level": "E1_DISCOVERY",
        "created_from": {
            "leaderboard_snapshot": str(SNAPSHOT.relative_to(ROOT)),
            "leaderboard_fetched_at_utc": snapshot["fetched_at"],
            "public_replays": len(inputs),
            "target_submission_episode_seats": len(memberships),
            "target_submissions": TOP_N,
            "selection": "first six EpisodeService rows per current Top 5 submission",
        },
        "leaderboard": {
            "top5": [
                {
                    "rank": int(row["rank"]),
                    "team": teams.get(int(row["teamId"]), {}).get("teamName", ""),
                    "team_id": int(row["teamId"]),
                    "submission_id": int(row["submissionId"]),
                    "rating": float(row["displayScore"]),
                    "team_last_submission_utc": teams.get(int(row["teamId"]), {}).get("lastSubmissionDate"),
                }
                for row in leaders
            ],
            "drift_from_20260910": {
                "top30_submission_overlap": len(prior_submissions & current_submissions),
                "top30_team_overlap": len(prior_teams & current_teams),
                "current_top30_count": len(current_board),
                "warning": "rank and rating are a timestamped public snapshot, not final strength",
            },
        },
        "current_top5_aggregate": current_summary,
        "by_rank": by_rank,
        "timing": timing_summary(rows),
        "opening_groups": opening,
        "same_field_h48_against_opponent": sum(
            row["field_hashes"].get("48") == row["opponent_field_hashes"].get("48") for row in rows
        ),
        "result_split": result_split,
        "sale_phase4": sale_phase,
        "historical_comparison": comparisons,
        "historical_reference": {
            "v111": v111_summary,
            "september10_top": prior_top_summary,
        },
        "limitations": [
            "The sample is recent and strong-opponent selected, not random.",
            "A public replay reveals factual trajectories but not source ancestry or counterfactual causality.",
            "Opponent private state is available offline in public replays but is prohibited for deployable features.",
            "Opening/action hashes are trajectory fingerprints, not proof of shared code.",
            "Requested sale quantities are not exact committed quantities unless separately engine-audited.",
        ],
    }


def main() -> None:
    snapshot, inputs, memberships, rows, daily, events, sales = current_corpus()
    OUT.mkdir(parents=True, exist_ok=True)
    meta.write_json(OUT / "current_replay_input_manifest.json", inputs)
    meta.write_json(OUT / "current_episode_seat_metrics.json", rows)
    meta.write_csv(OUT / "current_daily_trajectories.csv", daily)
    meta.write_csv(OUT / "current_shop_event_study_rows.csv", events)
    meta.write_csv(OUT / "current_sell_microstructure.csv", sales)
    evidence = build_evidence(snapshot, inputs, memberships, rows, sales)
    execution = build_execution_audit(inputs, memberships)
    meta.write_json(OUT / "strategy_evidence.json", evidence)
    meta.write_json(OUT / "current_top_execution_audit.json", execution)
    print(
        json.dumps(
            {
                "leader": evidence["leaderboard"]["top5"][0],
                "unique_replays": len(inputs),
                "target_seats": len(rows),
                "aggregate": evidence["current_top5_aggregate"],
                "opening_groups": evidence["opening_groups"][:5],
                "execution": execution["overall"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
