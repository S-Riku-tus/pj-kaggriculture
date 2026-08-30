"""Build public-history rows for 24/72-turn opponent sell prediction.

Each unique Top-3 replay contributes both runtime perspectives.  Features use
only public farms, Town, market, and their history.  The other player's private
state is used only indirectly to cap offline SELL labels and never enters a
feature.  Episode hashing keeps both perspectives in the same split.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from kaggle_environments.envs.kaggriculture import kaggriculture as game

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import farm_summary  # noqa: E402
from scripts.build_v18_intraday_herd_rows import _episode_sources  # noqa: E402
from scripts.train_v12_relative_policy import _observation, _split  # noqa: E402

FORMAT = "kaggriculture-v22-opponent-supply-rows-v1"
ITEMS = ("WHEAT", "STRAWBERRY", "MILK", "WOOL")
ASSETS = {"WHEAT": "WHEAT", "STRAWBERRY": "STRAWBERRY", "MILK": "COW", "WOOL": "SHEEP"}
HORIZONS = (24, 72)
DAYS = tuple(range(3, 27))
HOURS = (0, 6, 12, 18)


def _farm(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = obs.get("farms") or []
    return farms[seat] if 0 <= seat < len(farms) else {}


def _inventory(private: dict[str, Any], item: str) -> int:
    return int((private.get("shed") or {}).get(item, 0) or 0)


def _declared_sell_prefix(replay: dict[str, Any]) -> dict[int, dict[str, list[int]]]:
    """Cap declared SELL by the pre-action shed; same-turn round trips are ignored."""
    steps = replay.get("steps") or []
    result = {
        seat: {item: [0] * (len(steps) + 1) for item in ITEMS}
        for seat in range(2)
    }
    for decision_step in range(len(steps)):
        recorded_step = decision_step + 1
        for seat in range(2):
            for item in ITEMS:
                result[seat][item][decision_step + 1] = result[seat][item][decision_step]
            if recorded_step >= len(steps) or seat >= len(steps[recorded_step]):
                continue
            pre_obs = _observation(replay, decision_step, seat)
            if pre_obs is None:
                continue
            available = {item: _inventory(pre_obs.get("private") or {}, item) for item in ITEMS}
            action = steps[recorded_step][seat].get("action") or {}
            for order in (action.get("market") or [])[:10]:
                if not isinstance(order, list) or len(order) < 3 or order[0] != "SELL":
                    continue
                item = str(order[1])
                if item not in ITEMS:
                    continue
                amount = min(available[item], max(0, int(order[2] or 0)))
                available[item] -= amount
                result[seat][item][decision_step + 1] += amount
    return result


def _town_rate(obs: dict[str, Any]) -> Counter[str]:
    rate: Counter[str] = Counter({item: 0.25 for item in ITEMS})
    shops = (obs.get("town") or {}).get("unlocked_shops") or []
    for shop in shops:
        products = game.SHOPS.get(shop, [])
        multiplier = 2 if len(products) == 1 else 1
        for item in products:
            if item in ITEMS:
                rate[item] += multiplier
    return rate


def _town_units(replay: dict[str, Any], seat: int, start: int, stop: int) -> Counter[str]:
    units: Counter[str] = Counter()
    for step in range(max(0, start), min(stop, len(replay.get("steps") or []))):
        obs = _observation(replay, step, seat)
        if obs is None:
            continue
        if step % 4 == 0:
            shops = (obs.get("town") or {}).get("unlocked_shops") or []
            for shop in shops:
                products = game.SHOPS.get(shop, [])
                multiplier = 2 if len(products) == 1 else 1
                for item in products:
                    if item in ITEMS:
                        units[item] += multiplier
        if step % 24 == 0:
            units.update(ITEMS)
    return units


def _tile_signals(farm: dict[str, Any], day: int, horizon_days: int) -> dict[str, float]:
    ready: Counter[str] = Counter()
    scheduled: Counter[str] = Counter()
    risk: Counter[str] = Counter()
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if not isinstance(tile, dict):
                continue
            if tile.get("kind") == "PLANT":
                crop = str(tile.get("crop") or "")
                if crop not in {"WHEAT", "STRAWBERRY"}:
                    continue
                ready[crop] += int(tile.get("yield_units", 0) or 0)
                risk[crop] += int(tile.get("consecutive_unwatered", 0) or 0) >= 1
                spec = game.CROPS[crop]
                if spec["ongoing"]:
                    for future_day in range(day + 1, day + horizon_days + 1):
                        elapsed = future_day - int(tile.get("planted_day", day)) - int(spec["first_yield_day"])
                        if elapsed >= 0 and elapsed % int(spec["interval"]) == 0:
                            production_index = elapsed // int(spec["interval"]) + 1
                            scheduled[crop] += production_index <= int(spec["max_yield"])
                else:
                    age = day - int(tile.get("planted_day", day) or day)
                    scheduled[crop] += int(age < int(spec["max_yield_day"]))
            animal = str(tile.get("animal") or "")
            if animal not in {"COW", "SHEEP"}:
                continue
            product = str(game.ANIMALS[animal]["product"])
            ready[product] += int(tile.get("yield_units", 0) or 0)
            risk[product] += int(tile.get("consecutive_unfed", 0) or 0) >= 1
            spec = game.ANIMALS[animal]
            for future_day in range(day + 1, day + horizon_days + 1):
                elapsed = future_day - int(tile.get("placed_day", day)) - int(spec["first_yield_day"])
                if elapsed >= 0 and elapsed % int(spec["interval"]) == 0:
                    scheduled[product] += 1
    return {
        **{f"ready_{item}": float(ready[item]) for item in ITEMS},
        **{f"scheduled_{item}": float(scheduled[item]) for item in ITEMS},
        **{f"risk_{item}": float(risk[item]) for item in ITEMS},
    }


def _public_values(obs: dict[str, Any], own_seat: int) -> dict[str, float]:
    day = int(obs.get("day", 0) or 0)
    hour = int(obs.get("hour", 0) or 0)
    own = _farm(obs, own_seat)
    opponent = _farm(obs, 1 - own_seat)
    own_summary = farm_summary(own)
    opponent_summary = farm_summary(opponent)
    own_money = float(own.get("money", 0) or 0)
    opponent_money = float(opponent.get("money", 0) or 0)
    values: dict[str, float] = {
        "day": day / 29.0,
        "hour": hour / 23.0,
        "town_phase_sin": math.sin(2 * math.pi * hour / 4),
        "town_phase_cos": math.cos(2 * math.pi * hour / 4),
        "remaining_days": (29 - day) / 29.0,
        "own_money_log": math.log1p(max(0.0, own_money)) / 12.0,
        "opponent_money_log": math.log1p(max(0.0, opponent_money)) / 12.0,
        "money_gap_ratio": (own_money - opponent_money) / max(1.0, own_money + opponent_money),
        "own_unlocked": float(own_summary["unlocked"]) / 4.0,
        "opponent_unlocked": float(opponent_summary["unlocked"]) / 4.0,
        "own_hands": len(own.get("hands") or []) / 14.0,
        "opponent_hands": len(opponent.get("hands") or []) / 14.0,
    }
    town_rate = _town_rate(obs)
    market = obs.get("market") or {}
    inventories = market.get("inventory") or {}
    prices = market.get("prices") or {}
    for item in ITEMS:
        params = game.MARKET_PARAMS[item]
        values[f"town_rate_{item}"] = float(town_rate[item]) / 10.0
        values[f"market_inventory_{item}"] = (
            float(inventories.get(item, params["I0"]) or 0) - float(params["I0"])
        ) / float(params["T"])
        values[f"market_price_{item}"] = float(prices.get(item, params["base"]) or 0) / float(params["base"])
        asset = ASSETS[item]
        group = "animals" if asset in {"COW", "SHEEP"} else "crops"
        scale = 16.0 if group == "animals" else 75.0
        values[f"own_asset_{item}"] = float(own_summary[group][asset]) / scale
        values[f"opponent_asset_{item}"] = float(opponent_summary[group][asset]) / scale
    for prefix, farm in (("own", own), ("opponent", opponent)):
        for horizon_days in (1, 3):
            signals = _tile_signals(farm, day, horizon_days)
            for name, value in signals.items():
                values[f"{prefix}_{name}_d{horizon_days}"] = value / 75.0
    return values


def _history_values(
    replay: dict[str, Any],
    step: int,
    own_seat: int,
    current: dict[str, Any],
) -> dict[str, float]:
    values: dict[str, float] = {}
    current_market = (current.get("market") or {}).get("inventory") or {}
    current_own = _farm(current, own_seat)
    current_opponent = _farm(current, 1 - own_seat)
    current_opponent_summary = farm_summary(current_opponent)
    for lag in (6, 24):
        previous = _observation(replay, max(0, step - lag), own_seat)
        if previous is None:
            previous = current
        previous_market = (previous.get("market") or {}).get("inventory") or {}
        town = _town_units(replay, own_seat, max(0, step - lag), step)
        previous_own = _farm(previous, own_seat)
        previous_opponent = _farm(previous, 1 - own_seat)
        previous_opponent_summary = farm_summary(previous_opponent)
        values[f"own_money_delta_{lag}"] = (
            float(current_own.get("money", 0) or 0) - float(previous_own.get("money", 0) or 0)
        ) / 20_000.0
        values[f"opponent_money_delta_{lag}"] = (
            float(current_opponent.get("money", 0) or 0) - float(previous_opponent.get("money", 0) or 0)
        ) / 20_000.0
        for item in ITEMS:
            params = game.MARKET_PARAMS[item]
            delta = (
                float(current_market.get(item, params["I0"]) or 0)
                - float(previous_market.get(item, params["I0"]) or 0)
            )
            values[f"joint_market_flow_{item}_{lag}"] = (delta + town[item]) / float(params["T"])
            asset = ASSETS[item]
            group = "animals" if asset in {"COW", "SHEEP"} else "crops"
            scale = 16.0 if group == "animals" else 75.0
            values[f"opponent_asset_delta_{item}_{lag}"] = (
                float(current_opponent_summary[group][asset]) - float(previous_opponent_summary[group][asset])
            ) / scale
    return values


def _row(
    replay: dict[str, Any],
    prefix: dict[int, dict[str, list[int]]],
    episode_id: str,
    source_by_seat: dict[int, str],
    own_seat: int,
    step: int,
) -> dict[str, Any] | None:
    obs = _observation(replay, step, own_seat)
    if obs is None or len(obs.get("farms") or []) < 2:
        return None
    public = _public_values(obs, own_seat)
    public.update(_history_values(replay, step, own_seat, obs))
    target_seat = 1 - own_seat
    labels: dict[str, dict[str, float]] = {}
    for horizon in HORIZONS:
        stop = min(step + horizon, len(replay.get("steps") or []))
        labels[f"h{horizon}"] = {
            item: float(prefix[target_seat][item][stop] - prefix[target_seat][item][step])
            for item in ITEMS
        }
    final = _observation(replay, len(replay.get("steps") or []) - 1, own_seat)
    final_farms = (final or {}).get("farms") or []
    final_money = [float(farm.get("money", 0) or 0) for farm in final_farms]
    return {
        "episode_id": episode_id,
        "split": _split(episode_id),
        "own_seat": own_seat,
        "target_seat": target_seat,
        "target_source": source_by_seat.get(target_seat, "opponent"),
        "day": int(obs.get("day", 0) or 0),
        "hour": int(obs.get("hour", 0) or 0),
        "features_by_name": public,
        "labels": labels,
        "target_final_margin": (
            final_money[target_seat] - final_money[own_seat] if len(final_money) >= 2 else 0.0
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/training/v22_opponent_supply_rows.json"),
    )
    args = parser.parse_args()
    episode_paths, sources = _episode_sources()
    rows: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    split_episodes: dict[str, set[str]] = defaultdict(set)
    target_sources: Counter[str] = Counter()
    feature_names: list[str] | None = None
    for index, (episode_id, replay_path) in enumerate(sorted(episode_paths.items()), start=1):
        if index == 1 or index % 25 == 0:
            print(f"[{index}/{len(episode_paths)}] episode {episode_id}", flush=True)
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        if len(replay.get("steps") or []) < 719:
            skipped["short_replay"] += 1
            continue
        prefix = _declared_sell_prefix(replay)
        episode_split = _split(episode_id)
        split_episodes[episode_split].add(episode_id)
        for own_seat in (0, 1):
            target_sources[sources[episode_id].get(1 - own_seat, "opponent")] += 1
            for day in DAYS:
                for hour in HOURS:
                    row = _row(
                        replay,
                        prefix,
                        episode_id,
                        sources[episode_id],
                        own_seat,
                        day * 24 + hour,
                    )
                    if row is None:
                        skipped["missing_row"] += 1
                        continue
                    feature_map = row.pop("features_by_name")
                    names = list(feature_map)
                    if feature_names is None:
                        feature_names = names
                    elif names != feature_names:
                        raise ValueError("feature order changed while building rows")
                    row["features"] = [float(feature_map[name]) for name in feature_names]
                    rows.append(row)
    payload = {
        "format": FORMAT,
        "items": list(ITEMS),
        "horizons": list(HORIZONS),
        "sampling": {"days": [min(DAYS), max(DAYS)], "hours": list(HOURS)},
        "feature_names": feature_names or [],
        "episodes": len(episode_paths),
        "split_episodes": {split: len(values) for split, values in sorted(split_episodes.items())},
        "split_disjoint": all(
            split_episodes[left].isdisjoint(split_episodes[right])
            for index, left in enumerate(split_episodes)
            for right in list(split_episodes)[index + 1 :]
        ),
        "target_source_sides": dict(target_sources),
        "label_note": "declared SELL capped by pre-action shed; same-turn buy/sell round trips ignored",
        "feature_privacy": "public observations and public history only",
        "skipped": dict(skipped),
        "rows": rows,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        json.dumps(
            {
                "format": FORMAT,
                "episodes": len(episode_paths),
                "rows": len(rows),
                "features": len(payload["feature_names"]),
                "split_episodes": payload["split_episodes"],
                "split_disjoint": payload["split_disjoint"],
                "target_source_sides": payload["target_source_sides"],
                "skipped": payload["skipped"],
                "bytes": output.stat().st_size,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"result: {output}")


if __name__ == "__main__":
    main()
