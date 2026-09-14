"""Read-only postmortem of spent development replays; no games or holdout access."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.evaluation.replay import action, observation
from scripts.evaluation.safety import _apply_fields, engine, simulate_turn

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/evaluation/research_20260910/v114probe/development/pairs.jsonl"
OUT = ROOT / "data/analysis/next_research_20260911"


def weed_causes(replay, seat):
    counts = Counter()
    lifespan_remaining = Counter()
    first = {}
    for step in range(153, len(replay["steps"]) - 1):
        before = observation(replay, step, seat)["farms"][seat]["tiles"]
        after = observation(replay, step + 1, seat)["farms"][seat]["tiles"]
        changes = [
            (x, y)
            for y, row in enumerate(before)
            for x, tile in enumerate(row)
            if isinstance(tile, dict)
            and tile.get("kind") == "PLANT"
            and isinstance(after[y][x], dict)
            and after[y][x].get("kind") == "WEED"
        ]
        if not changes:
            continue
        obs = [observation(replay, step, player) for player in (0, 1)]
        farms = copy.deepcopy(obs[0]["farms"])
        privates = [copy.deepcopy(o["private"]) for o in obs]
        _apply_fields(farms, privates, [action(replay, step, p) for p in (0, 1)], step // 24)
        after_fields = copy.deepcopy(farms[seat]["tiles"])
        engine._decay_plants(farms[seat], step)
        after_decay = copy.deepcopy(farms[seat]["tiles"])
        if (step + 1) % 24 == 0:
            engine._daily_refresh_plants(farms[seat], step // 24, 24)
        for x, y in changes:
            def is_weed(tiles, x=x, y=y):
                tile = tiles[y][x]
                return isinstance(tile, dict) and tile.get("kind") == "WEED"

            cause = (
                "field_action"
                if is_weed(after_fields)
                else "lifespan_decay"
                if is_weed(after_decay)
                else "missed_watering"
                if is_weed(farms[seat]["tiles"])
                else "unresolved"
            )
            counts[cause] += 1
            if cause == "lifespan_decay":
                lifespan_remaining[str(after_fields[y][x].get("yield_units", 0))] += 1
            first.setdefault(cause, {"action_step": step, "tile": [x, y], "before": before[y][x]})
    return {
        "counts": dict(counts),
        "first": first,
        "lifespan_terminal_remaining_yield_before_decay": dict(lifespan_remaining),
    }


def early_events(replay, seat):
    events = []
    wheat_quotes = []
    for step in range(153, 216):
        obs = observation(replay, step, seat)
        for event in simulate_turn(replay, step)[seat]:
            if event["kind"] == "silent_field_noop" or (
                event["kind"] == "market_commit" and event["committed"] < event["requested"]
            ):
                events.append({"step": step, **event})
        if any(order[:2] == ["BUY_PRODUCT", "WHEAT"] for order in action(replay, step, seat).get("market", [])):
            wheat_quotes.append({
                "step": step,
                "pre_turn_first_unit_quote": engine.market_price(
                    "WHEAT", obs["market"]["inventory"]["WHEAT"] - 1, obs["market"].get("params")
                ),
                "projection_fixed_cost": 25,
            })
    return {"events": events, "wheat_quotes_not_realized_cost": wheat_quotes}


def main():
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines()]
    records = []
    for row in rows:
        record = {key: row[key] for key in (
            "opponent_name", "seed", "seat", "control", "treatment", "delta_self_coin",
            "delta_opponent_coin", "delta_margin", "delta_win_score", "loss_to_win", "win_to_loss",
            "incremental_treatment",
        )}
        if row["incremental_treatment"]:
            for arm in ("control", "treatment"):
                path = Path(row["replay_artifacts"][arm])
                with gzip.open(path, "rt", encoding="utf-8") as stream:
                    replay = json.load(stream)
                record[arm + "_audit"] = {
                    "replay": str(path.relative_to(ROOT)),
                    "replay_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "weed_causes": weed_causes(replay, row["seat"]),
                    "early_events": early_events(replay, row["seat"]),
                }
            measured_delta = sum(record["treatment_audit"]["weed_causes"]["counts"].values()) - sum(
                record["control_audit"]["weed_causes"]["counts"].values()
            )
            frozen_delta = row["safety"]["treatment"]["plant_to_weed"] - row["safety"]["control"]["plant_to_weed"]
            assert measured_delta == frozen_delta, (row["opponent_name"], row["seed"], row["seat"])
            assert all(
                record[arm + "_audit"]["weed_causes"]["counts"].get("unresolved", 0) == 0
                for arm in ("control", "treatment")
            )
        records.append(record)
    counts = Counter()
    for record in records:
        if not record["incremental_treatment"]:
            continue
        for arm in ("control", "treatment"):
            for cause, count in record[arm + "_audit"]["weed_causes"]["counts"].items():
                counts[arm + "_" + cause] += count
    summary = {
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "scope": "32 spent development pairs, 24 activated; causal outcome unchanged; no holdout read",
        "weed_scope": "activated pairs only, action steps 153..718; engine stage attribution, not mediation effect",
        "weed_events": dict(counts),
        "self_coin_up_pairs": sum(record["delta_self_coin"] > 0 for record in records),
        "self_coin_up_margin_down_pairs": sum(
            record["delta_self_coin"] > 0 and record["delta_margin"] < 0 for record in records
        ),
        "margin_up_pairs": sum(record["delta_margin"] > 0 for record in records),
        "loss_to_win": sum(record["loss_to_win"] for record in records),
        "win_to_loss": sum(record["win_to_loss"] for record in records),
        "records": records,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "postmortem_recheck.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "records"}, indent=2))


if __name__ == "__main__":
    main()
