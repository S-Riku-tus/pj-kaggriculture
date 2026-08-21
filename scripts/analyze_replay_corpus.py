"""Aggregate economic and operational KPIs from Kaggriculture replay corpora.

The replay downloader stores one submission manifest beside a directory of full
episode JSON files.  This script joins the manifest to the replay observations,
extracts one row per submission/episode, and writes both detailed CSV and a
compact JSON summary.  It intentionally uses only the standard library so the
analysis is reproducible from a clean checkout.
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMALS = ("GOOSE", "COW", "SHEEP")
MOVEMENT = {"NORTH", "SOUTH", "EAST", "WEST"}
SNAPSHOT_DAYS = (1, 4, 7, 10, 12, 15, 20, 24, 27, 29)
SHOP_DEMAND = {
    "BAKERY": {"EGG": 1, "WHEAT": 1},
    "PIZZA_SHOP": {"MILK": 1, "TOMATO": 1, "WHEAT": 1},
    "BRUNCH_SPOT": {"EGG": 1, "WHEAT": 1, "STRAWBERRY": 1},
    "YARN_STORE": {"WOOL": 2},
    "ICE_CREAM_SHOP": {"STRAWBERRY": 1, "MILK": 1, "WHEAT": 1},
    "PET_CAFE": {"CARROT": 2},
    "SMOOTHIE_SHOP": {"STRAWBERRY": 1, "MILK": 1},
    "FARMERS_MARKET": {"WHEAT": 1, "CARROT": 1, "TOMATO": 1, "STRAWBERRY": 1},
}


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _inventory_count(inventory: dict[str, Any], item: str) -> int:
    return max(0, _as_int(inventory.get(item, 0)))


def _farm_counts(farm: dict[str, Any]) -> tuple[Counter[str], Counter[str], int, int]:
    crops: Counter[str] = Counter()
    animals: Counter[str] = Counter()
    structures = 0
    weeds = 0
    for row in farm.get("tiles", []):
        for tile in row:
            if not isinstance(tile, dict):
                continue
            kind = tile.get("kind")
            if kind == "PLANT" and tile.get("crop") in CROPS:
                crops[tile["crop"]] += 1
            elif tile.get("animal") in ANIMALS:
                animals[tile["animal"]] += 1
            elif kind in {"COOP", "PASTURE"}:
                structures += 1
            elif kind == "WEED":
                weeds += 1
    return crops, animals, structures, weeds


def _all_owned_animals(farm: dict[str, Any], private: dict[str, Any]) -> Counter[str]:
    _crops, placed, _structures, _weeds = _farm_counts(farm)
    result = Counter(placed)
    shed = private.get("shed", {})
    inventories = private.get("inventories", [])
    for animal in ANIMALS:
        result[animal] += _inventory_count(shed, animal)
        result[animal] += sum(_inventory_count(inv, animal) for inv in inventories)
    return result


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = probability * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    x_mean = mean(xs)
    y_mean = mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    x_ss = sum((x - x_mean) ** 2 for x in xs)
    y_ss = sum((y - y_mean) ** 2 for y in ys)
    if x_ss == 0 or y_ss == 0:
        return None
    return numerator / math.sqrt(x_ss * y_ss)


def _load_manifest(submission_dir: Path) -> list[dict[str, str]]:
    with (submission_dir / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _select_rows(rows: list[dict[str, str]], sample: int | None) -> list[dict[str, str]]:
    available = [row for row in rows if row.get("replay_status") in {"downloaded", "skipped_existing"}]
    if sample is None or sample >= len(available):
        return available
    # Deterministic quantile coverage preserves low, middle, and high outcomes.
    ordered = sorted(available, key=lambda row: float(row.get("own_reward") or 0))
    indexes = {round(i * (len(ordered) - 1) / max(1, sample - 1)) for i in range(sample)}
    return [ordered[index] for index in sorted(indexes)]


def _demand_scores(shops: list[str]) -> Counter[str]:
    scores: Counter[str] = Counter()
    for shop in shops:
        scores.update(SHOP_DEMAND.get(shop, {}))
    return scores


def analyze_episode(path: Path, manifest: dict[str, str]) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        replay = json.load(handle)

    seat = _as_int(manifest.get("submission_seat"))
    submission_id = str(manifest.get("submission_id", ""))
    episode_id = str(manifest.get("episode_id", path.stem.removeprefix("episode_")))
    field_actions: Counter[str] = Counter()
    market_actions: Counter[str] = Counter()
    sell_volume: Counter[str] = Counter()
    sell_quote_value: Counter[str] = Counter()
    hand_actions = 0
    hand_passes = 0
    productive_actions = 0
    day_snapshots: dict[int, dict[str, Any]] = {}
    maximum_crops: Counter[str] = Counter()
    maximum_animals: Counter[str] = Counter()
    first_unlocked: dict[int, int] = {}
    previous_owned: Counter[str] | None = None
    animal_losses: Counter[str] = Counter()
    previous_day = -1
    final_obs: dict[str, Any] = {}
    final_state: dict[str, Any] = {}

    for states in replay.get("steps", []):
        if seat >= len(states):
            continue
        state = states[seat]
        obs = state.get("observation") or {}
        farms = obs.get("farms") or []
        if seat >= len(farms):
            continue
        farm = farms[seat]
        private = obs.get("private") or {}
        day = _as_int(obs.get("day"))
        crops, animals, structures, weeds = _farm_counts(farm)
        owned = _all_owned_animals(farm, private)
        for item in CROPS:
            maximum_crops[item] = max(maximum_crops[item], crops[item])
        for item in ANIMALS:
            maximum_animals[item] = max(maximum_animals[item], animals[item])
        unlocked = len(farm.get("unlocked_quadrants", []))
        first_unlocked.setdefault(unlocked, day)

        if previous_owned is not None:
            for animal in ANIMALS:
                if owned[animal] < previous_owned[animal]:
                    animal_losses[animal] += previous_owned[animal] - owned[animal]
        previous_owned = owned

        if day != previous_day:
            previous_day = day
            available = max(1, 25 * unlocked)
            productive_tiles = sum(crops.values()) + sum(animals.values())
            day_snapshots[day] = {
                "money": float(farm.get("money") or 0),
                "unlocked": unlocked,
                "productive_tiles": productive_tiles,
                "utilization": productive_tiles / available,
                "structures": structures,
                "weeds": weeds,
                "crops": dict(crops),
                "animals": dict(animals),
            }

        action = state.get("action") or {}
        unit_actions = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        for unit_index, unit_action in enumerate(unit_actions):
            op = unit_action[0] if unit_action else "PASS"
            field_actions[op] += 1
            if unit_index > 0:
                hand_actions += 1
                hand_passes += op == "PASS"
            if op != "PASS" and op not in MOVEMENT:
                productive_actions += 1

        prices = (obs.get("market") or {}).get("prices") or {}
        for order in action.get("market") or []:
            if not order:
                continue
            op = order[0]
            market_actions[op] += 1
            if op == "SELL" and len(order) >= 3:
                item = str(order[1])
                amount = max(0, _as_int(order[2]))
                sell_volume[item] += amount
                sell_quote_value[item] += amount * _as_int(prices.get(item))

        final_obs = obs
        final_state = state

    farms = final_obs.get("farms") or []
    farm = farms[seat] if seat < len(farms) else {}
    private = final_obs.get("private") or {}
    final_prices = (final_obs.get("market") or {}).get("prices") or {}
    shed = private.get("shed") or {}
    inventories = private.get("inventories") or []
    terminal_shed_value = sum(_inventory_count(shed, item) * _as_int(final_prices.get(item)) for item in PRODUCTS)
    terminal_carried_value = sum(
        _inventory_count(inv, item) * _as_int(final_prices.get(item)) for inv in inventories for item in PRODUCTS
    )
    shops = list((final_obs.get("town") or {}).get("unlocked_shops") or [])
    demand = _demand_scores(shops)
    own_reward = float(manifest.get("own_reward") or farm.get("money") or final_state.get("reward") or 0)
    opponent_reward = float(manifest.get("opponent_reward") or 0)
    is_self_play = bool(
        (
            submission_id
            and manifest.get("opponent_submission_id")
            and submission_id == str(manifest.get("opponent_submission_id"))
        )
        or (
            manifest.get("team_name")
            and manifest.get("team_name") == manifest.get("opponent_team_name")
        )
    )
    result: dict[str, Any] = {
        "submission_id": submission_id,
        "episode_id": episode_id,
        "seat": seat,
        "result": manifest.get("result", "unknown"),
        "is_self_play": is_self_play,
        "own_reward": own_reward,
        "opponent_reward": opponent_reward,
        "margin": own_reward - opponent_reward,
        "steps": len(replay.get("steps", [])),
        "terminal_shed_value": terminal_shed_value,
        "terminal_carried_value": terminal_carried_value,
        "terminal_inventory_value": terminal_shed_value + terminal_carried_value,
        "hand_actions": hand_actions,
        "hand_passes": hand_passes,
        "hand_pass_rate": hand_passes / hand_actions if hand_actions else 0.0,
        "productive_actions": productive_actions,
        "hires": market_actions["HIRE"],
        "productive_actions_per_hire": productive_actions / market_actions["HIRE"] if market_actions["HIRE"] else 0.0,
        "final_shops": shops,
        "day_snapshots": day_snapshots,
    }
    for item in CROPS:
        result[f"max_{item.lower()}"] = maximum_crops[item]
        result[f"demand_{item.lower()}"] = demand[item]
    for item in ANIMALS:
        result[f"max_{item.lower()}"] = maximum_animals[item]
        result[f"lost_{item.lower()}"] = animal_losses[item]
    result["demand_milk"] = demand["MILK"]
    result["demand_wool"] = demand["WOOL"]
    for count in (2, 3, 4):
        result[f"unlock_{count}_day"] = first_unlocked.get(count)
    for op, count in field_actions.items():
        result[f"field_{op.lower()}"] = count
    for op, count in market_actions.items():
        result[f"market_{op.lower()}"] = count
    for item in PRODUCTS:
        volume = sell_volume[item]
        result[f"sell_{item.lower()}_volume"] = volume
        result[f"sell_{item.lower()}_mean_quote"] = sell_quote_value[item] / volume if volume else None

    del replay
    gc.collect()
    return result


def _summarize(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    public = [row for row in rows if not row["is_self_play"]]
    rewards = [float(row["own_reward"]) for row in public]
    margins = [float(row["margin"]) for row in public]
    wins = sum(row["result"] == "win" for row in public)
    losses = sum(row["result"] == "loss" for row in public)
    summary: dict[str, Any] = {
        "label": label,
        "episodes": len(public),
        "wins": wins,
        "losses": losses,
        "draws": len(public) - wins - losses,
        "win_rate": wins / len(public) if public else 0.0,
        "coins": {
            "minimum": min(rewards, default=0),
            "p10": _percentile(rewards, 0.10),
            "median": median(rewards) if rewards else 0,
            "mean": mean(rewards) if rewards else 0,
            "maximum": max(rewards, default=0),
        },
        "margin": {
            "p10": _percentile(margins, 0.10),
            "median": median(margins) if margins else 0,
            "mean": mean(margins) if margins else 0,
        },
        "operations": {},
        "daily": {},
        "portfolio": {},
        "demand_correlations": {},
    }
    scalar_metrics = (
        "hires",
        "hand_pass_rate",
        "productive_actions_per_hire",
        "field_collect_fertilizer",
        "field_fertilize",
        "terminal_inventory_value",
        "lost_goose",
        "lost_cow",
        "lost_sheep",
    )
    for metric in scalar_metrics:
        summary["operations"][metric] = mean(float(row.get(metric) or 0) for row in public) if public else 0.0
    for day in SNAPSHOT_DAYS:
        snapshots = [row["day_snapshots"].get(day) for row in public]
        snapshots = [snapshot for snapshot in snapshots if snapshot is not None]
        if snapshots:
            summary["daily"][str(day)] = {
                "money": mean(snapshot["money"] for snapshot in snapshots),
                "utilization": mean(snapshot["utilization"] for snapshot in snapshots),
                "productive_tiles": mean(snapshot["productive_tiles"] for snapshot in snapshots),
                "unlocked": mean(snapshot["unlocked"] for snapshot in snapshots),
            }
    for item in (*CROPS, *ANIMALS):
        metric = f"max_{item.lower()}"
        summary["portfolio"][metric] = mean(float(row.get(metric) or 0) for row in public) if public else 0.0
    correlation_pairs = {
        "milk_to_cow": ("demand_milk", "max_cow"),
        "wool_to_sheep": ("demand_wool", "max_sheep"),
        "strawberry_to_strawberry": ("demand_strawberry", "max_strawberry"),
    }
    for name, (demand_metric, capacity_metric) in correlation_pairs.items():
        summary["demand_correlations"][name] = _pearson(
            [float(row.get(demand_metric) or 0) for row in public],
            [float(row.get(capacity_metric) or 0) for row in public],
        )
    for item in PRODUCTS:
        volume_metric = f"sell_{item.lower()}_volume"
        quote_metric = f"sell_{item.lower()}_mean_quote"
        volume = sum(float(row.get(volume_metric) or 0) for row in public)
        quote_value = sum(
            float(row.get(volume_metric) or 0) * float(row.get(quote_metric) or 0) for row in public
        )
        summary["portfolio"][volume_metric] = volume / len(public) if public else 0.0
        summary["portfolio"][quote_metric] = quote_value / volume if volume else None
    return summary


def _json_cell(value: Any) -> Any:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, dict | list) else value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        action="append",
        required=True,
        metavar="LABEL=SUBMISSION_DIR",
        help="repeatable corpus; replay paths are read from manifest.csv",
    )
    parser.add_argument("--sample", type=int, help="deterministic reward-quantile sample per corpus")
    parser.add_argument("--output", type=Path, default=Path("data/analysis/replay_corpus_comparison.json"))
    parser.add_argument("--details", type=Path, default=Path("data/analysis/replay_episode_metrics.csv"))
    args = parser.parse_args()

    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for corpus in args.corpus:
        if "=" not in corpus:
            raise ValueError(f"invalid --corpus {corpus!r}; expected LABEL=SUBMISSION_DIR")
        label, directory = corpus.split("=", 1)
        submission_dir = Path(directory)
        submission_dir = submission_dir if submission_dir.is_absolute() else ROOT / submission_dir
        manifest_rows = _select_rows(_load_manifest(submission_dir), args.sample)
        corpus_rows: list[dict[str, Any]] = []
        for index, manifest in enumerate(manifest_rows, start=1):
            replay_path = ROOT / manifest["replay_path"]
            if not replay_path.is_file():
                replay_path = ROOT / "data" / manifest["replay_path"]
            print(f"[{label}] {index}/{len(manifest_rows)} episode {manifest['episode_id']}", flush=True)
            row = analyze_episode(replay_path, manifest)
            row["label"] = label
            corpus_rows.append(row)
        all_rows.extend(corpus_rows)
        summaries.append(_summarize(label, corpus_rows))

    output = args.output if args.output.is_absolute() else ROOT / args.output
    details = args.details if args.details.is_absolute() else ROOT / args.details
    output.parent.mkdir(parents=True, exist_ok=True)
    details.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"corpora": summaries}, ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = sorted({key for row in all_rows for key in row})
    with details.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: _json_cell(row.get(key)) for key in fieldnames} for row in all_rows)
    print(f"summary: {output}")
    print(f"details: {details}")


if __name__ == "__main__":
    main()
