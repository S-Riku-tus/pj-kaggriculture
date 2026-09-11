"""Current Discovery replay audit; E1 only, using canonical evaluator accessors.

No replay is an executable opponent. Exact hashes distinguish action trajectories,
not latent policies. This command rejects holdout-labelled manifest entries.
"""

from __future__ import annotations

import argparse
import csv
import gzip
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

from scripts.evaluation.replay import action, canonical_action, decision_count, observation  # noqa: E402
from scripts.train_v111_strategy import BASE_PRICE, SHOP_PRODUCTS, _demand_per_day  # noqa: E402

HORIZONS = (24, 48, 100, 200, 300, 400, 600, 719)
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMALS = ("COW", "SHEEP", "GOOSE")
ASSETS = (*CROPS, *ANIMALS)
PRODUCTS = (*CROPS, "MILK", "WOOL", "EGG", "FERTILIZER")
PREMIUM = ("STRAWBERRY", "MELON", "MILK", "WOOL")
ANIMAL_PRODUCT = {"COW": "MILK", "SHEEP": "WOOL", "GOOSE": "EGG"}
CHECKPOINTS = {"day12": 288, "day18": 432, "day20": 480, "day24": 576}


def read_json(path: Path) -> Any:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False) if isinstance(value, list | dict) else value
                    for key, value in row.items()
                }
            )


def portfolio(farm: dict[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if isinstance(tile, dict):
                for key in ("crop", "animal"):
                    if tile.get(key):
                        counts[tile[key]] += 1
    return {key: counts[key] for key in ASSETS}


def field_yield(farm: dict[str, Any]) -> dict[str, int]:
    result: Counter[str] = Counter()
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if isinstance(tile, dict):
                product = tile.get("crop") or ANIMAL_PRODUCT.get(tile.get("animal"))
                if product:
                    result[product] += int(tile.get("yield_units", 0))
    return {key: result[key] for key in PRODUCTS}


def private_units(obs: dict[str, Any]) -> dict[str, int]:
    private = obs.get("private") or {}
    bags = [private.get("shed") or {}, *(private.get("inventories") or [])]
    return {item: sum(max(0, int(bag.get(item, 0) or 0)) for bag in bags) for item in PRODUCTS}


def normalized_field(emitted: dict[str, Any]) -> str:
    actors = [emitted.get("farmer") or ["PASS"], *(emitted.get("hands") or [])]
    return json.dumps([[value for value in actor if isinstance(value, str)] for actor in actors], separators=(",", ":"))


def hashes(tokens: list[str]) -> dict[str, str]:
    hasher = hashlib.sha256()
    result = {}
    for index, token in enumerate(tokens, 1):
        hasher.update(token.encode())
        hasher.update(b"\n")
        if index in HORIZONS:
            result[str(index)] = hasher.hexdigest()[:20]
    return result


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def analyze_seat(
    replay: dict[str, Any], episode: dict[str, Any], seat: int, names: dict[int, str], cohorts: dict[int, str]
) -> tuple[dict, list, list, list]:
    n = decision_count(replay)
    eid = int(episode["id"])
    agents = episode.get("agents") or [{}, {}]
    indexed = {int(agent.get("index", index)): agent for index, agent in enumerate(agents)}
    own_meta, opp_meta = indexed.get(seat, {}), indexed.get(1 - seat, {})
    sid = int(own_meta.get("submissionId", 0))
    opp_sid = int(opp_meta.get("submissionId", 0))
    obs = [observation(replay, step, seat) or {} for step in range(n + 1)]
    opp_obs = [observation(replay, step, 1 - seat) or {} for step in range(n + 1)]
    farms = [(item.get("farms") or [{}, {}])[seat] for item in obs]
    opp_farms = [(item.get("farms") or [{}, {}])[1 - seat] for item in obs]
    ports = [portfolio(farm) for farm in farms]
    opp_ports = [portfolio(farm) for farm in opp_farms]
    emitted = [action(replay, step, seat) for step in range(n)]
    opp_emitted = [action(replay, step, 1 - seat) for step in range(n)]
    tokens = [canonical_action(value) for value in emitted]
    field_tokens = [normalized_field(value) for value in emitted]
    opp_tokens = [canonical_action(value) for value in opp_emitted]
    opp_fields = [normalized_field(value) for value in opp_emitted]
    final_money = float(farms[-1].get("money", 0))
    opponent_money = float(opp_farms[-1].get("money", 0))
    margin = final_money - opponent_money
    result = "win" if margin > 0 else "loss" if margin < 0 else "draw"
    base = {
        "episode_id": eid,
        "seat": seat,
        "submission_id": sid,
        "cohort": cohorts.get(sid, "opponent"),
        "team_name": names.get(int(own_meta.get("teamId", 0)), ""),
        "opponent_submission_id": opp_sid,
        "opponent_team": names.get(int(opp_meta.get("teamId", 0)), ""),
    }
    daily = []
    for step in sorted({*range(0, n + 1, 24), n}):
        item, farm = obs[step], farms[step]
        market = item.get("market") or {}
        shops = (item.get("town") or {}).get("unlocked_shops") or []
        record = {
            **base,
            "step": step,
            "day": step / 24,
            "cash": farm.get("money", 0),
            "opponent_cash": opp_farms[step].get("money", 0),
            "margin": farm.get("money", 0) - opp_farms[step].get("money", 0),
            "hands": len(farm.get("hands") or []),
            "quadrants": len(farm.get("unlocked_quadrants") or []),
            "shops": shops,
            "private": private_units(item),
            "opponent_private_offline_ground_truth": private_units(opp_obs[step]),
            "field_yield": field_yield(farm),
            "opponent_field_yield": field_yield(opp_farms[step]),
        }
        record.update({f"own_{key}": ports[step][key] for key in ASSETS})
        record.update({f"opp_{key}": opp_ports[step][key] for key in ASSETS})
        for product in PRODUCTS:
            record[f"inventory_{product}"] = (market.get("inventory") or {}).get(product)
            record[f"price_{product}"] = (market.get("prices") or {}).get(product)
            record[f"demand_day_{product}"] = 0 if product == "FERTILIZER" else _demand_per_day(shops, product)
        daily.append(record)
    events = []
    for step in range(1, n):
        shops = (obs[step].get("town") or {}).get("unlocked_shops") or []
        prior = (obs[step - 1].get("town") or {}).get("unlocked_shops") or []
        if len(shops) <= len(prior):
            continue
        new_shops = list((Counter(shops) - Counter(prior)).elements())
        if not 144 <= step <= 600:
            continue
        pre = max(0, step - 24)
        for horizon in (24, 72, 144):
            if step + horizon > n:
                continue
            end = step + horizon
            record = {
                **base,
                "step": step,
                "day": step / 24,
                "horizon": horizon,
                "new_shops": new_shops,
                "prior_shops": prior,
                "opening_family": hashes(field_tokens).get("48"),
                "pre_margin": farms[step].get("money", 0) - opp_farms[step].get("money", 0),
                "delta_margin": (farms[end].get("money", 0) - opp_farms[end].get("money", 0))
                - (farms[step].get("money", 0) - opp_farms[step].get("money", 0)),
                "delta_hands": len(farms[end].get("hands") or []) - len(farms[step].get("hands") or []),
            }
            for asset in ASSETS:
                record[f"delta_{asset}"] = ports[end][asset] - ports[step][asset]
                record[f"pre24_delta_{asset}"] = ports[step][asset] - ports[pre][asset]
                record[f"start_{asset}"] = ports[step][asset]
                record[f"opponent_{asset}"] = opp_ports[step][asset]
            for product in PRODUCTS:
                record[f"new_demand_{product}"] = sum(
                    (12 if len(SHOP_PRODUCTS.get(shop, [])) == 1 else 6)
                    for shop in new_shops
                    if product in SHOP_PRODUCTS.get(shop, [])
                )
            events.append(record)
    sales = []
    ops: Counter[str] = Counter()
    late_ops: Counter[str] = Counter()
    first_order: dict[str, int] = {}
    last_order: dict[str, int] = {}
    last_plant: dict[str, int] = {}
    investment_steps: list[int] = []
    total_slots = active_slots = 0
    congestion_exposure: Counter[str] = Counter()
    sold_units: Counter[str] = Counter()
    sold_value: Counter[str] = Counter()
    total_exposure: Counter[str] = Counter()
    clone_distances = []
    for step, act in enumerate(emitted):
        item = obs[step]
        market = item.get("market") or {}
        prices = market.get("prices") or {}
        inventories = market.get("inventory") or {}
        held = private_units(item)
        for product in PREMIUM:
            total_exposure[product] += held[product]
            if float(prices.get(product, 0)) <= 0.25 * BASE_PRICE[product]:
                congestion_exposure[product] += held[product]
        if 144 <= step <= 600:
            clone_distances.append(sum(abs(ports[step][key] - opp_ports[step][key]) for key in ASSETS))
        actors = [act.get("farmer") or ["PASS"], *(act.get("hands") or [])]
        for actor in actors:
            op = actor[0] if actor else "PASS"
            ops[op] += 1
            if step >= 600:
                late_ops[op] += 1
            if 144 <= step < 600:
                total_slots += 1
                active_slots += int(op != "PASS")
            if op == "PLANT" and len(actor) > 1:
                last_plant[actor[1]] = step
        for order in act.get("market") or []:
            if not order:
                continue
            op = order[0]
            product = order[1] if len(order) > 1 else ""
            key = f"{op}_{product}"
            first_order.setdefault(key, step)
            last_order[key] = step
            if op in {"BUY_LAND", "BUY_ANIMAL"}:
                investment_steps.append(step)
            if op != "SELL" or product not in PRODUCTS or len(order) < 3:
                continue
            qty = max(0, int(order[2]))
            own_shed = (item.get("private") or {}).get("shed") or {}
            # These are availability-capped requested quantities, NOT engine-committed audit.
            available_qty = min(qty, max(0, int(own_shed.get(product, 0))))
            price = float(prices.get(product, 0))
            sold_units[product] += available_qty
            sold_value[product] += available_qty * price
            next_market = obs[step + 1].get("market") or {}
            opp_sell = sum(
                max(0, int(order[2]))
                for order in opp_emitted[step].get("market") or []
                if len(order) >= 3 and order[0] == "SELL" and order[1] == product
            )
            sales.append(
                {
                    **base,
                    "step": step,
                    "product": product,
                    "requested_qty": qty,
                    "availability_capped_qty": available_qty,
                    "hour": step % 24,
                    "phase4": step % 4,
                    "price_before": price,
                    "price_after": (next_market.get("prices") or {}).get(product),
                    "market_before": inventories.get(product),
                    "market_after": (next_market.get("inventory") or {}).get(product),
                    "own_exposure": held[product],
                    "opponent_exposure_offline_ground_truth": private_units(opp_obs[step])[product],
                    "opponent_requested_sell_same_turn": opp_sell,
                    "final_margin": margin,
                    "result": result,
                }
            )
    checkpoints = {
        label: float(farms[min(step, n)].get("money", 0)) - float(opp_farms[min(step, n)].get("money", 0))
        for label, step in CHECKPOINTS.items()
    }
    daily_ports = [ports[step] for step in range(144, min(601, n), 24)]
    mean_port = {key: mean(row[key] for row in daily_ports) for key in ASSETS}
    opponent_mean = {key: mean(opp_ports[step][key] for step in range(144, min(601, n), 24)) for key in ASSETS}
    final_held = private_units(obs[-1])
    record = {
        **base,
        "create_time": episode.get("createTime"),
        "end_time": episode.get("endTime"),
        "states": n + 1,
        "decisions": n,
        "result": result,
        "score": 1 if margin > 0 else 0.5 if margin == 0 else 0,
        "self_final_coin": final_money,
        "opponent_final_coin": opponent_money,
        "final_margin": margin,
        "self_initial_rating": number(own_meta.get("initialScore")),
        "opponent_initial_rating": number(opp_meta.get("initialScore")),
        "hashes": hashes(tokens),
        "field_hashes": hashes(field_tokens),
        "opponent_hashes": hashes(opp_tokens),
        "opponent_field_hashes": hashes(opp_fields),
        "continuation_action_hash_144_600": digest(tokens[144:600]),
        "continuation_field_hash_144_600": digest(field_tokens[144:600]),
        "daily_portfolio_hash_144_600": digest(daily_ports),
        "continuation_mean_portfolio": mean_port,
        "opponent_mean_portfolio": opponent_mean,
        "opening_actions24": emitted[:24],
        "land_timing": [
            step
            for step in range(n + 1)
            if step > 0
            and len(farms[step].get("unlocked_quadrants") or []) > len(farms[step - 1].get("unlocked_quadrants") or [])
        ],
        "first_market_order": first_order,
        "last_market_order": last_order,
        "last_plant": last_plant,
        "last_irreversible_investment": max(investment_steps, default=None),
        "midgame_nonpass_rate": active_slots / max(1, total_slots),
        "operations": dict(ops),
        "late_operations": dict(late_ops),
        "checkpoint_margins": checkpoints,
        "lead_to_loss": {key: value > 0 and margin < 0 for key, value in checkpoints.items()},
        "final_shops": (obs[-1].get("town") or {}).get("unlocked_shops") or [],
        "sell_units_availability_capped": dict(sold_units),
        "sell_value_observation_price_proxy": dict(sold_value),
        "premium_congestion_unit_steps": dict(congestion_exposure),
        "premium_total_unit_steps": dict(total_exposure),
        "final_private_stranded": final_held,
        "final_field_yield": field_yield(farms[-1]),
        "final_stranded_observed_price_proxy": sum(
            final_held[key] * float(((obs[-1].get("market") or {}).get("prices") or {}).get(key, 0)) for key in PRODUCTS
        ),
        "mean_clone_portfolio_l1": mean(clone_distances) if clone_distances else None,
    }
    own_rating, opp_rating = record["self_initial_rating"], record["opponent_initial_rating"]
    record["loss_flags"] = {
        "close_loss_5000": -5000 <= margin < 0,
        "upset_loss_rating_gap_200": margin < 0
        and own_rating is not None
        and opp_rating is not None
        and own_rating - opp_rating >= 200,
        "premium_congestion": margin < 0 and sum(congestion_exposure.values()) > 0,
        "wool_heavy_opponent_ge5": margin < 0 and opponent_mean["SHEEP"] >= 5,
        "milk_heavy_opponent_ge5": margin < 0 and opponent_mean["COW"] >= 5,
        "strawberry_heavy_opponent_ge15": margin < 0 and opponent_mean["STRAWBERRY"] >= 15,
        "near_clone_mean_portfolio_l1_le5": margin < 0 and record["mean_clone_portfolio_l1"] <= 5,
        "same_field_opening_h48": margin < 0
        and record["field_hashes"].get("48") == record["opponent_field_hashes"].get("48"),
        "unusual_crop_opponent_tomato_ge3_or_carrot_ge10": margin < 0
        and (opponent_mean["TOMATO"] >= 3 or opponent_mean["CARROT"] >= 10),
        "market_timing_causality": "unidentified_from_single_replay",
    }
    return record, daily, events, sales


def summary(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    margins = sorted(row["final_margin"] for row in rows)
    return {
        "n": len(rows),
        "wdl": dict(Counter(row["result"] for row in rows)),
        "win_score": mean(row["score"] for row in rows),
        "mean_margin": mean(margins),
        "median_margin": median(margins),
        "p10_margin": margins[int(0.1 * (len(margins) - 1))],
        "mean_self_coin": mean(row["self_final_coin"] for row in rows),
        "mean_stranded_price_proxy": mean(row["final_stranded_observed_price_proxy"] for row in rows),
        "lead_to_loss": {key: sum(row["lead_to_loss"][key] for row in rows) for key in CHECKPOINTS},
        "loss_flags": {
            key: sum(row["loss_flags"][key] is True for row in rows)
            for key in rows[0]["loss_flags"]
            if key != "market_timing_causality"
        },
        "mean_portfolio": {key: mean(row["continuation_mean_portfolio"][key] for row in rows) for key in ASSETS},
        "unique_hashes": {str(h): len({row["hashes"].get(str(h)) for row in rows}) for h in HORIZONS},
        "unique_field_hashes": {str(h): len({row["field_hashes"].get(str(h)) for row in rows}) for h in HORIZONS},
        "unique_portfolio_continuations": len({row["daily_portfolio_hash_144_600"] for row in rows}),
    }


def group_summary(rows: list[dict], key) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[str(key(row))].append(row)
    return {label: summary(values) for label, values in sorted(groups.items(), key=lambda pair: -len(pair[1]))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, nargs="*", default=[])
    parser.add_argument("--champion-submissions", type=int, nargs="*", default=[55909167, 55912910])
    parser.add_argument("--top-submissions", type=int, nargs="*", default=[])
    parser.add_argument("--output", type=Path, default=ROOT / "data/analysis/research_20260909")
    args = parser.parse_args()
    manifest = [json.loads(line) for line in args.manifest.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if any("holdout" in str(row.get("dataset_role", "")).lower() for row in manifest):
        raise ValueError("Refusing to read a holdout-labelled manifest")
    episodes, names = {}, {}
    for path in args.metadata:
        raw = read_json(path)
        if isinstance(raw, list):
            raw = {"episodes": raw}
        for row in raw.get("episodes") or []:
            episodes[int(row["id"])] = row
        for row in raw.get("teams") or []:
            names[int(row["id"])] = str(row.get("teamName", ""))
    cohorts = {sid: "champion_v111" for sid in args.champion_submissions}
    cohorts.update({sid: f"top_rank_{rank}" for rank, sid in enumerate(args.top_submissions, 1)})
    cohorts.update({55933145: "benchmark_v113", 56089444: "latest_unmapped", 55941525: "previous_unmapped"})
    rows, daily, events, sales, inputs = [], [], [], [], []
    seen = set()
    for source in manifest:
        eid = int(source["episode_id"])
        if eid in seen:
            continue
        seen.add(eid)
        path = Path(source.get("path") or source.get("replay_path"))
        if not path.is_absolute():
            candidates = [ROOT / path, args.manifest.parent / path]
            path = next((value for value in candidates if value.is_file()), candidates[0])
        replay = read_json(path)
        episode = episodes.get(eid) or source.get("episode_metadata")
        if not episode:
            raise ValueError(f"Missing metadata for episode {eid}")
        if decision_count(replay) != 719:
            print(f"Skipping incomplete episode {eid}: {decision_count(replay)} decisions", flush=True)
            continue
        inputs.append(
            {
                "episode_id": eid,
                "path": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "dataset_role": "discovery",
            }
        )
        for seat in range(2):
            record, ds, es, ss = analyze_seat(replay, episode, seat, names, cohorts)
            rows.append(record)
            daily.extend(ds)
            events.extend(es)
            sales.extend(ss)
        print(f"Analyzed {len(inputs)} episodes; latest {eid}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "current_replay_input_manifest.json", inputs)
    write_json(args.output / "current_episode_seat_metrics.json", rows)
    write_csv(args.output / "current_daily_trajectories.csv", daily)
    write_csv(args.output / "current_shop_event_study_rows.csv", events)
    write_csv(args.output / "current_sell_microstructure.csv", sales)
    champion = [row for row in rows if row["cohort"] == "champion_v111"]
    top = [row for row in rows if row["cohort"].startswith("top_rank_")]
    family_counts = defaultdict(list)
    for row in top:
        family_counts[row["field_hashes"].get("48")].append(row)
    opening = [
        {
            "field_h48": family,
            "episode_seats": len(values),
            "submissions": sorted({row["submission_id"] for row in values}),
            "exact_continuations": len({row["continuation_action_hash_144_600"] for row in values}),
            "portfolio_continuations": len({row["daily_portfolio_hash_144_600"] for row in values}),
        }
        for family, values in sorted(family_counts.items(), key=lambda pair: -len(pair[1]))
    ]
    event_groups = defaultdict(list)
    for event in events:
        if (event["cohort"] != "champion_v111" and not event["cohort"].startswith("top_rank_")) or event[
            "horizon"
        ] != 72:
            continue
        cohort = "champion_v111" if event["cohort"] == "champion_v111" else "top"
        for product in ("MILK", "WOOL", "STRAWBERRY", "CARROT", "TOMATO"):
            event_groups[(cohort, product, bool(event[f"new_demand_{product}"]))].append(event)
    event_summary = []
    for (cohort, product, demanded), values in sorted(event_groups.items()):
        asset = {"MILK": "COW", "WOOL": "SHEEP"}.get(product, product)
        event_summary.append(
            {
                "cohort": cohort,
                "product": product,
                "new_shop_demands_product": demanded,
                "n_event_rows": len(values),
                "unique_episodes": len({row["episode_id"] for row in values}),
                "mean_delta_asset72": mean(row[f"delta_{asset}"] for row in values),
                "mean_pre24_delta_asset": mean(row[f"pre24_delta_{asset}"] for row in values),
                "mean_delta_margin72": mean(row["delta_margin"] for row in values),
                "evidence": "E1 descriptive; day/route/opponent confounding unresolved",
            }
        )

    def rating_bin(row):
        return (
            "unknown"
            if row["opponent_initial_rating"] is None
            else str(int(row["opponent_initial_rating"] // 250) * 250)
        )

    def town_regime(row):
        return "|".join(f"{key}:{Counter(row['final_shops'])[key]}" for key in sorted(set(row["final_shops"])))

    result = {
        "evidence_level": "E1",
        "dataset_role": "Discovery; consumed for hypothesis formation; never Fresh Holdout",
        "unique_replays": len(inputs),
        "seat_records": len(rows),
        "quantity_warning": (
            "Sales are requested capped to pre-action shed; not audited committed revenue. Final bank outcome is exact."
        ),
        "lineage_warning": (
            "Action hashes are state-dependent trajectory fingerprints. "
            "Counts are not independent executable policy families."
        ),
        "cohorts": group_summary(rows, lambda row: row["cohort"]),
        "champion": summary(champion),
        "champion_by_rating": group_summary(champion, rating_bin),
        "champion_by_opponent_field_h48": group_summary(champion, lambda row: row["opponent_field_hashes"].get("48")),
        "champion_by_opponent_h100": group_summary(champion, lambda row: row["opponent_hashes"].get("100")),
        "champion_by_opponent_h200": group_summary(champion, lambda row: row["opponent_hashes"].get("200")),
        "champion_by_town": group_summary(champion, town_regime),
        "top_opening_continuation_groups": opening,
        "shop_events72": event_summary,
    }
    write_json(args.output / "current_meta_weakness_summary.json", result)
    print(
        json.dumps(
            {
                "unique_replays": len(inputs),
                "champion": result["champion"],
                "cohorts": {
                    key: {"n": value["n"], "wdl": value.get("wdl")} for key, value in result["cohorts"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
