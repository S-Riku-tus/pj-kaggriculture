"""Recheck spent original replays with source-backed mechanics and exact trade accounting."""

# ruff: noqa: E402, E501

from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.analyze_next_research_20260911 import early_events, weed_causes
from scripts.evaluation.lifecycle import analyze_lifecycle
from scripts.evaluation.replay import action, observation
from scripts.evaluation.safety import simulate_turn
from scripts.research_20260911 import OUT, digest, save


def read_replay(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def trade_ledger(replay, seat):
    revenue, quantity, costs = Counter(), Counter(), Counter()
    rows = []
    for step in range(153, 719):
        obs = observation(replay, step, seat)
        events = simulate_turn(replay, step)[seat]
        for e in events:
            if e["kind"] != "market_commit":
                continue
            if e.get("op") == "SELL":
                revenue[e["item"]] += e["cash_delta"]
                quantity[e["item"]] += e["committed"]
            elif e.get("op", "").startswith("BUY_") and "item" in e:
                costs[e["item"]] -= e["cash_delta"]
            if 153 <= step <= 215:
                rows.append({"step": step, "cash": obs["farms"][seat]["money"], **e})
    return {"revenue": dict(revenue), "quantity": dict(quantity), "costs": dict(costs), "early": rows}


def main():
    source = ROOT / "data/evaluation/research_20260910/v114probe/development/pairs.jsonl"
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    records, totals = [], Counter()
    for row in rows:
        if not row["incremental_treatment"]:
            continue
        record = {k: row[k] for k in ("opponent_name", "seed", "seat", "delta_self_coin", "delta_opponent_coin", "delta_margin", "loss_to_win", "win_to_loss")}
        for arm in ("control", "treatment"):
            path = Path(row["replay_artifacts"][arm])
            replay = read_replay(path)
            lifecycle = analyze_lifecycle(replay, row["seat"], 153)
            old = weed_causes(replay, row["seat"])
            assert lifecycle["counts"].get("lifespan_end", 0) == old["counts"].get("lifespan_decay", 0)
            assert lifecycle["counts"].get("water_death", 0) == old["counts"].get("missed_watering", 0)
            record[arm] = {
                "replay": str(path.relative_to(ROOT)), "sha256": digest(path),
                "lifecycle": lifecycle, "early_execution": early_events(replay, row["seat"]),
                "self_trade": trade_ledger(replay, row["seat"]),
                "opponent_trade": trade_ledger(replay, 1 - row["seat"]),
                "t186": {"observation": observation(replay, 186, row["seat"]), "action": action(replay, 186, row["seat"])},
            }
            for group in ("counts", "lost_current_units", "lifespan_end_remaining_yield", "successful_harvest_units"):
                for key, value in lifecycle[group].items():
                    totals[f"{arm}.{group}.{key}"] += value
        record["divergence"] = row["divergence_audit"]
        observed_delta = sum(
            record["treatment"]["lifecycle"]["counts"].get(k, 0) - record["control"]["lifecycle"]["counts"].get(k, 0)
            for k in ("lifespan_end", "water_death", "field_action", "unresolved")
        )
        assert observed_delta == row["safety"]["treatment"]["plant_to_weed"] - row["safety"]["control"]["plant_to_weed"]
        records.append(record)
        print(len(records), row["opponent_name"], row["seed"], row["seat"], flush=True)
    save(OUT / "postmortem_recomputed.json", {
        "source": str(source.relative_to(ROOT)), "sha256": digest(source), "records": records,
        "totals": dict(totals), "original_outcomes_unchanged": True,
        "same_town_filter": False, "counterfactual_town_engine": "not used",
        "price_attribution_limit": "Exact revenue and quantity accounting. Final price/quantity differences include policy and Town feedback; not identified mediated causal effects.",
    })
    print(json.dumps(dict(totals)), flush=True)


if __name__ == "__main__":
    main()
