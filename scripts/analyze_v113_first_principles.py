"""Replay-grounded first-principles audit for Kaggriculture V113.

The report deliberately separates engine facts from observed policy choices.
It reads replay files directly and reconstructs the target seat from the saved
EpisodeService response, so it does not depend on a partially rewritten fetch
manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CORPORA = {
    "top1_20260901": (55905066, "leaderboard_20260831_rank1_tetsuya_submission_55905066"),
    "top2_20260901": (55865730, "leaderboard_20260831_rank2_yusuke_hayashi_submission_55865730"),
    "top3_20260901": (55867591, "leaderboard_20260831_rank3_mtn_submission_55867591"),
    "v109": (55890113, "v109_submission_55890113"),
    "v110": (55903573, "v110_submission_55903573"),
    "v111_a": (55909167, "v111_submission_55909167"),
    "v111_b": (55912910, "v111_submission_55912910"),
}

ONGOING_CROPS = {"TOMATO", "STRAWBERRY"}
ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
BASE_PRICE = {
    "WHEAT": 25,
    "CARROT": 35,
    "TOMATO": 60,
    "STRAWBERRY": 120,
    "MELON": 250,
    "EGG": 50,
    "MILK": 160,
    "WOOL": 200,
    "FERTILIZER": 100,
}
MAX_HELD = {"GOOSE": 4, "COW": 6, "SHEEP": 6}
PORTFOLIO_ITEMS = (
    "WHEAT",
    "CARROT",
    "TOMATO",
    "STRAWBERRY",
    "MELON",
    "GOOSE",
    "COW",
    "SHEEP",
)
CHECKPOINTS = (100, 200, 400)


def _episode_rows(directory: Path) -> dict[int, dict[str, Any]]:
    path = directory / "episode_service_response.json"
    response = json.loads(path.read_text(encoding="utf-8"))
    return {
        int(row["id"]): row
        for row in response.get("episodes", [])
        if isinstance(row, dict) and str(row.get("id", "")).isdigit()
    }


def _target_seat(row: dict[str, Any], submission_id: int) -> int | None:
    for position, agent in enumerate((row.get("agents") or [])[:2]):
        if not isinstance(agent, dict):
            continue
        if int(agent.get("submissionId") or -1) == submission_id:
            return int(agent.get("index", position) or 0)
    return None


def _agent_score(row: dict[str, Any], submission_id: int, key: str) -> float | None:
    for agent in row.get("agents") or []:
        if isinstance(agent, dict) and int(agent.get("submissionId") or -1) == submission_id:
            value = agent.get(key)
            return float(value) if isinstance(value, int | float) else None
    return None


def _obs(replay: dict[str, Any], stored_step: int, seat: int) -> dict[str, Any]:
    try:
        value = replay["steps"][stored_step][seat].get("observation") or {}
    except (IndexError, KeyError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _action(replay: dict[str, Any], logical_step: int, seat: int) -> dict[str, Any]:
    # Kaggle stores the action chosen from observation t on recorded state t+1.
    try:
        value = replay["steps"][logical_step + 1][seat].get("action") or {}
    except (IndexError, KeyError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _farm(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = obs.get("farms") or []
    if seat >= len(farms) or not isinstance(farms[seat], dict):
        return {}
    return farms[seat]


def _tile(farm: dict[str, Any], position: Any) -> dict[str, Any] | None:
    try:
        x, y = int(position[0]), int(position[1])
        value = farm["tiles"][y][x]
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _actor_rows(obs: dict[str, Any], seat: int, action: dict[str, Any]):
    farm = _farm(obs, seat)
    positions = [farm.get("farmer"), *(farm.get("hands") or [])]
    actions = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
    for index, position in enumerate(positions):
        actor_action = actions[index] if index < len(actions) else ["PASS"]
        if not isinstance(actor_action, list) or not actor_action:
            actor_action = ["PASS"]
        yield actor_action, _tile(farm, position)


def _canonical(action: dict[str, Any], component: str) -> str:
    field = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
    market = action.get("market") or []
    if component == "field":
        payload: Any = field
    elif component == "market":
        payload = market
    else:
        payload = {"field": field, "market": market}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _lineages(replay: dict[str, Any], seat: int) -> dict[str, dict[int, str]]:
    digests = {name: hashlib.sha1() for name in ("field", "market", "full")}
    result = {name: {} for name in digests}
    for step in range(CHECKPOINTS[-1]):
        action = _action(replay, step, seat)
        for name, digest in digests.items():
            digest.update(_canonical(action, name).encode())
            digest.update(b"\n")
            if step + 1 in CHECKPOINTS:
                result[name][step + 1] = digest.hexdigest()[:16]
    return result


def _portfolio(farm: dict[str, Any]) -> tuple[int, ...]:
    counts: Counter[str] = Counter()
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if not isinstance(tile, dict):
                continue
            crop = tile.get("crop")
            animal = tile.get("animal")
            if crop in PORTFOLIO_ITEMS:
                counts[str(crop)] += 1
            if animal in PORTFOLIO_ITEMS:
                counts[str(animal)] += 1
    return tuple(counts[item] for item in PORTFOLIO_ITEMS)


def _sum_private_stock(obs: dict[str, Any], item: str) -> int:
    private = obs.get("private") or {}
    total = int((private.get("shed") or {}).get(item, 0) or 0)
    for inventory in private.get("inventories") or []:
        total += int((inventory or {}).get(item, 0) or 0)
    return total


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _episode_metrics(
    replay: dict[str, Any],
    row: dict[str, Any],
    seat: int,
    submission_id: int,
) -> dict[str, Any]:
    opponent = 1 - seat
    rewards = replay.get("rewards") or [0, 0]
    own_reward = float(rewards[seat] or 0)
    opponent_reward = float(rewards[opponent] or 0)
    lineages = _lineages(replay, seat)
    counters: Counter[str] = Counter()
    water_by_crop: Counter[str] = Counter()
    feed_by_animal: Counter[str] = Counter()
    harvest_hours: Counter[str] = Counter()
    sell_phase: dict[str, Counter[str]] = defaultdict(Counter)
    sell_slots: dict[str, list[int]] = defaultdict(list)
    day20_portfolio: tuple[int, ...] = ()
    day12_margin: float | None = None
    terminal_stock = 0

    steps = min(719, max(0, len(replay.get("steps") or []) - 1))
    for logical_step in range(steps):
        obs = _obs(replay, logical_step, seat)
        action = _action(replay, logical_step, seat)
        day = int(obs.get("day", logical_step // 24) or 0)
        hour = int(obs.get("hour", logical_step % 24) or 0)
        if logical_step == 12 * 24:
            farms = obs.get("farms") or []
            if len(farms) >= 2:
                day12_margin = float(farms[seat].get("money") or 0) - float(
                    farms[opponent].get("money") or 0
                )
        if logical_step == 20 * 24:
            day20_portfolio = _portfolio(_farm(obs, seat))

        for actor_action, tile in _actor_rows(obs, seat, action):
            op = str(actor_action[0])
            counters["actor_actions"] += 1
            counters[f"op:{op}"] += 1
            if op == "PASS":
                counters["passes"] += 1
                continue
            counters["nonpass"] += 1
            if not tile:
                continue
            if op == "WATER" and tile.get("kind") == "PLANT":
                crop = str(tile.get("crop"))
                water_by_crop[crop] += 1
                counters["water"] += 1
                if int(tile.get("consecutive_unwatered", 0) or 0) >= 1:
                    counters["water_survival_due"] += 1
                if crop in ONGOING_CROPS:
                    counters["water_ongoing"] += 1
                    if int(tile.get("consecutive_unwatered", 0) or 0) >= 1:
                        counters["water_ongoing_survival_due"] += 1
                    if int(tile.get("fertilized_until_day", -1) or -1) >= day:
                        counters["water_ongoing_fertilized"] += 1
            elif op == "FEED" and tile.get("animal") in ANIMAL_PRODUCT:
                animal = str(tile["animal"])
                product = ANIMAL_PRODUCT[animal]
                feed_by_animal[animal] += 1
                counters["feed"] += 1
                if int(tile.get("consecutive_unfed", 0) or 0) >= 1:
                    counters["feed_survival_due"] += 1
                price = float(((obs.get("market") or {}).get("prices") or {}).get(product, 0) or 0)
                if price <= 0.5 * BASE_PRICE[product]:
                    counters["feed_low_price"] += 1
                    if int(tile.get("consecutive_unfed", 0) or 0) >= 1:
                        counters["feed_low_price_survival_due"] += 1
            elif op == "CARE" and tile.get("animal") in ANIMAL_PRODUCT:
                animal = str(tile["animal"])
                counters["care"] += 1
                expected = 1 + int(tile.get("pending_care_bonus", 0) or 0)
                if int(tile.get("yield_units", 0) or 0) + expected >= MAX_HELD[animal]:
                    counters["care_low_headroom"] += 1
            elif op == "HARVEST":
                quantity = max(0, int(tile.get("yield_units", 0) or 0))
                counters["harvest"] += 1
                counters["harvest_quantity"] += quantity
                harvest_hours[str(hour)] += 1
                if hour >= 18:
                    counters["night_harvest"] += 1
                    counters["night_harvest_quantity"] += quantity

        for slot, order in enumerate((action.get("market") or [])[:10]):
            if not isinstance(order, list) or len(order) < 3 or order[0] != "SELL":
                continue
            item = str(order[1])
            try:
                quantity = max(0, int(order[2]))
            except (TypeError, ValueError):
                continue
            counters["sell_orders"] += 1
            counters["sell_quantity"] += quantity
            counters[f"sell_hour:{hour}"] += quantity
            if hour == 1:
                counters["dawn_sell_quantity"] += quantity
            sell_phase[item][str(logical_step % 4)] += quantity
            sell_slots[item].append(slot)

    final_obs = _obs(replay, len(replay.get("steps") or []) - 1, seat)
    for item in BASE_PRICE:
        terminal_stock += _sum_private_stock(final_obs, item)

    return {
        "episode_id": int(row.get("id") or 0),
        "create_time": str(row.get("createTime") or ""),
        "seat": seat,
        "initial_score": _agent_score(row, submission_id, "initialScore"),
        "updated_score": _agent_score(row, submission_id, "updatedScore"),
        "own_reward": own_reward,
        "opponent_reward": opponent_reward,
        "margin": own_reward - opponent_reward,
        "result": "win" if own_reward > opponent_reward else "loss" if own_reward < opponent_reward else "draw",
        "day12_margin": day12_margin,
        "lead_to_loss": bool(day12_margin is not None and day12_margin > 0 and own_reward < opponent_reward),
        "behind_to_win": bool(day12_margin is not None and day12_margin < 0 and own_reward > opponent_reward),
        "lineages": {name: {str(k): v for k, v in values.items()} for name, values in lineages.items()},
        "day20_portfolio": list(day20_portfolio),
        "counters": dict(counters),
        "water_by_crop": dict(water_by_crop),
        "feed_by_animal": dict(feed_by_animal),
        "harvest_hours": dict(harvest_hours),
        "sell_phase": {item: dict(values) for item, values in sell_phase.items()},
        "mean_sell_slot": {
            item: mean(values) for item, values in sell_slots.items() if values
        },
        "terminal_stock": terminal_stock,
    }


def _distribution(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"minimum": None, "p10": None, "median": None, "mean": None, "maximum": None}
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(0.1 * len(ordered)) - 1))
    return {
        "minimum": ordered[0],
        "p10": ordered[index],
        "median": median(ordered),
        "mean": mean(ordered),
        "maximum": ordered[-1],
    }


def _sum_counters(episodes: list[dict[str, Any]]) -> Counter[str]:
    total: Counter[str] = Counter()
    for episode in episodes:
        total.update(episode["counters"])
    return total


def _lineage_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for component in ("field", "market", "full"):
        result[component] = {}
        for checkpoint in CHECKPOINTS:
            counts = Counter(
                episode["lineages"][component].get(str(checkpoint), "missing")
                for episode in episodes
            )
            result[component][str(checkpoint)] = {
                "distinct": len(counts),
                "largest_count": counts.most_common(1)[0][1] if counts else 0,
                "largest_share": _ratio(counts.most_common(1)[0][1], len(episodes)) if counts else None,
            }
    return result


def _lineage_weighted(episodes: list[dict[str, Any]], metric) -> float | None:
    groups: dict[str, list[float]] = defaultdict(list)
    for episode in episodes:
        value = metric(episode)
        if value is None:
            continue
        lineage = episode["lineages"]["full"].get("200", "missing")
        groups[lineage].append(float(value))
    return mean(mean(values) for values in groups.values()) if groups else None


def _aggregate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    total = _sum_counters(episodes)

    def water_risk(episode: dict[str, Any]) -> float | None:
        return _ratio(
            episode["counters"].get("water_ongoing_survival_due", 0),
            episode["counters"].get("water_ongoing", 0),
        )

    def feed_risk(episode: dict[str, Any]) -> float | None:
        return _ratio(
            episode["counters"].get("feed_survival_due", 0),
            episode["counters"].get("feed", 0),
        )

    def night_share(episode: dict[str, Any]) -> float | None:
        return _ratio(
            episode["counters"].get("night_harvest_quantity", 0),
            episode["counters"].get("harvest_quantity", 0),
        )

    def dawn_share(episode: dict[str, Any]) -> float | None:
        return _ratio(
            episode["counters"].get("dawn_sell_quantity", 0),
            episode["counters"].get("sell_quantity", 0),
        )
    sell_phase: dict[str, Counter[str]] = defaultdict(Counter)
    slots: dict[str, list[float]] = defaultdict(list)
    for episode in episodes:
        for item, values in episode["sell_phase"].items():
            sell_phase[item].update(values)
        for item, value in episode["mean_sell_slot"].items():
            slots[item].append(float(value))
    unique_portfolios = {
        tuple(episode["day20_portfolio"])
        for episode in episodes
        if episode["day20_portfolio"]
    }
    latest = max(episodes, key=lambda episode: episode["create_time"], default=None)
    return {
        "episodes": len(episodes),
        "latest_episode": (
            {
                "episode_id": latest["episode_id"],
                "create_time": latest["create_time"],
                "updated_score": latest["updated_score"],
            }
            if latest
            else None
        ),
        "outcomes": dict(Counter(episode["result"] for episode in episodes)),
        "reward": _distribution([episode["own_reward"] for episode in episodes]),
        "margin": _distribution([episode["margin"] for episode in episodes]),
        "day12_transitions": {
            "ahead": sum((episode["day12_margin"] or 0) > 0 for episode in episodes),
            "lead_to_loss": sum(episode["lead_to_loss"] for episode in episodes),
            "behind": sum((episode["day12_margin"] or 0) < 0 for episode in episodes),
            "behind_to_win": sum(episode["behind_to_win"] for episode in episodes),
        },
        "lineages": _lineage_summary(episodes),
        "day20_portfolios": {
            "distinct": len(unique_portfolios),
            "distinct_share": _ratio(len(unique_portfolios), len(episodes)),
        },
        "service": {
            "water_actions": total["water"],
            "ongoing_water_actions": total["water_ongoing"],
            "ongoing_water_survival_due_share": _ratio(
                total["water_ongoing_survival_due"], total["water_ongoing"]
            ),
            "ongoing_water_fertilized_share": _ratio(
                total["water_ongoing_fertilized"], total["water_ongoing"]
            ),
            "ongoing_water_survival_due_lineage_weighted": _lineage_weighted(
                episodes, water_risk
            ),
            "feed_actions": total["feed"],
            "feed_survival_due_share": _ratio(total["feed_survival_due"], total["feed"]),
            "feed_survival_due_lineage_weighted": _lineage_weighted(episodes, feed_risk),
            "low_price_feed_actions": total["feed_low_price"],
            "low_price_feed_survival_due_share": _ratio(
                total["feed_low_price_survival_due"], total["feed_low_price"]
            ),
            "care_actions": total["care"],
            "care_low_headroom_share": _ratio(total["care_low_headroom"], total["care"]),
        },
        "logistics": {
            "harvest_actions": total["harvest"],
            "night_harvest_action_share": _ratio(total["night_harvest"], total["harvest"]),
            "night_harvest_quantity_share": _ratio(
                total["night_harvest_quantity"], total["harvest_quantity"]
            ),
            "night_harvest_quantity_lineage_weighted": _lineage_weighted(
                episodes, night_share
            ),
            "dawn_sell_quantity_share": _ratio(
                total["dawn_sell_quantity"], total["sell_quantity"]
            ),
            "dawn_sell_quantity_lineage_weighted": _lineage_weighted(episodes, dawn_share),
            "terminal_stock": _distribution([episode["terminal_stock"] for episode in episodes]),
        },
        "market": {
            "sell_phase_quantity": {item: dict(values) for item, values in sell_phase.items()},
            "mean_sell_slot": {item: mean(values) for item, values in slots.items() if values},
        },
    }


def _load_corpus(label: str, submission_id: int, name: str) -> list[dict[str, Any]]:
    submission_dir = DATA / "submissions" / name
    replay_dir = DATA / "replays" / name
    rows = _episode_rows(submission_dir)
    episodes: list[dict[str, Any]] = []
    for replay_path in sorted(replay_dir.glob("episode_*.json")):
        episode_id = int(replay_path.stem.removeprefix("episode_"))
        row = rows.get(episode_id)
        if row is None:
            continue
        seat = _target_seat(row, submission_id)
        if seat not in (0, 1):
            continue
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        if len(replay.get("steps") or []) < 719:
            continue
        episodes.append(_episode_metrics(replay, row, seat, submission_id))
    print(f"{label}: {len(episodes)} complete mapped replays")
    return episodes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v113_first_principles.json"),
    )
    parser.add_argument(
        "--details",
        type=Path,
        default=Path("data/analysis/v113_episode_metrics.jsonl"),
    )
    args = parser.parse_args()

    corpora = {
        label: _load_corpus(label, submission_id, name)
        for label, (submission_id, name) in CORPORA.items()
    }
    top = [episode for label in ("top1_20260901", "top2_20260901", "top3_20260901") for episode in corpora[label]]
    own = [episode for label in ("v109", "v110", "v111_a", "v111_b") for episode in corpora[label]]
    report = {
        "format": "kaggriculture-v113-first-principles-v1",
        "engine": "kaggle-environments 1.32.7",
        "observation_clock": "day*24+hour; replay action t is stored at state t+1",
        "corpora": {label: _aggregate(episodes) for label, episodes in corpora.items()},
        "combined": {"current_top3": _aggregate(top), "v109_to_v111": _aggregate(own)},
        "interpretation_contract": {
            "engine_facts": [
                "plants and animals are lost after two consecutive unserviced day refreshes",
                "ongoing crops produce base yield without daily water",
                "animals produce base yield without feed; feed gates banked care bonus",
                "field inventory auto-drops at midnight up to shed capacity",
                "market orders are processed by slot with per-unit lockstep quotes",
            ],
            "observational_limits": [
                "replay behavior is association, not a causal ablation",
                "episode outcomes span the submissions' rating trajectories",
                "action-lineage hashes describe behavior and do not prove common source code",
            ],
        },
    }

    output = args.output if args.output.is_absolute() else ROOT / args.output
    details = args.details if args.details.is_absolute() else ROOT / args.details
    output.parent.mkdir(parents=True, exist_ok=True)
    details.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with details.open("w", encoding="utf-8") as handle:
        for label, episodes in corpora.items():
            for episode in episodes:
                handle.write(json.dumps({"label": label, **episode}, ensure_ascii=False) + "\n")
    print(f"report: {output}")
    print(f"details: {details}")


if __name__ == "__main__":
    main()
