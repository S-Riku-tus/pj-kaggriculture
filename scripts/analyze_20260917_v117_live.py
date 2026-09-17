"""Forensic comparison of the two 2026-09-16 V117 live submissions.

The analysis is descriptive.  It uses only public replay state plus each
seat's own private observation as recorded by Kaggle.  No replay identity,
team identity, score, or future state is intended for agent runtime use.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = (
    ROOT / "data/submissions/v117_submission_56267292",
    ROOT / "data/submissions/v117_submission_56267296",
)
DEFAULT_OUTPUT = ROOT / "experiments/research_20260917_v118/live_forensics.json"
CHECKPOINTS = (24, 96, 168, 240, 288, 360, 480, 576, 648, 696, 719)
CROPS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")
ANIMALS = ("GOOSE", "COW", "SHEEP")
PRODUCTS = (*CROPS, "EGG", "MILK", "WOOL", "FERTILIZER")
MOVES = frozenset({"NORTH", "SOUTH", "EAST", "WEST", "PASS"})


def number(value: object) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def integer(value: object) -> int:
    return int(number(value))


def quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = probability * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    x_bar = mean(xs)
    y_bar = mean(ys)
    numerator = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys, strict=True))
    x_ss = sum((x - x_bar) ** 2 for x in xs)
    y_ss = sum((y - y_bar) ** 2 for y in ys)
    if not x_ss or not y_ss:
        return None
    return numerator / math.sqrt(x_ss * y_ss)


def canonical_action(state: dict[str, Any]) -> str:
    action = state.get("action") or {}
    return json.dumps(action, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def tiles(farm: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        tile
        for row in farm.get("tiles") or []
        for tile in (row or [])
        if isinstance(tile, dict)
    ]


def portfolio(farm: dict[str, Any]) -> Counter[str]:
    result: Counter[str] = Counter()
    for tile in tiles(farm):
        crop = tile.get("crop")
        animal = tile.get("animal")
        if crop in CROPS:
            result[str(crop)] += 1
        if animal in ANIMALS:
            result[str(animal)] += 1
    return result


def private_total(private: dict[str, Any], item: str) -> int:
    total = integer((private.get("shed") or {}).get(item))
    total += sum(integer((inventory or {}).get(item)) for inventory in private.get("inventories") or [])
    return max(0, total)


def snapshot(state: dict[str, Any], seat: int) -> dict[str, Any]:
    obs = state.get("observation") or {}
    farms = obs.get("farms") or []
    farm = farms[seat] if seat < len(farms) else {}
    private = obs.get("private") or {}
    counts = portfolio(farm)
    prices = (obs.get("market") or {}).get("prices") or {}
    inventory_value = sum(private_total(private, item) * integer(prices.get(item)) for item in PRODUCTS)
    productive = sum(counts.values())
    unlocked = len(set(farm.get("unlocked_quadrants") or []))
    return {
        "money": number(farm.get("money")),
        "land": unlocked,
        "hands": len(farm.get("hands") or []),
        "productive": productive,
        "utilization": productive / max(1, 25 * unlocked),
        "inventory_value": inventory_value,
        "portfolio": {item: counts[item] for item in (*CROPS, *ANIMALS)},
    }


def action_counts(states: list[list[dict[str, Any]]], seat: int) -> dict[str, dict[str, int]]:
    field: Counter[str] = Counter()
    market: Counter[str] = Counter()
    market_items: Counter[str] = Counter()
    for step in states:
        if seat >= len(step):
            continue
        action = step[seat].get("action") or {}
        unit_actions = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        for actor_action in unit_actions:
            if actor_action:
                field[str(actor_action[0])] += 1
        for order in action.get("market") or []:
            if not order:
                continue
            operation = str(order[0])
            market[operation] += 1
            if len(order) >= 2:
                market_items[f"{operation}:{order[1]}"] += integer(order[2]) if len(order) >= 3 else 1
    return {"field": dict(field), "market": dict(market), "market_items": dict(market_items)}


def transition_steps(states: list[list[dict[str, Any]]], seat: int) -> dict[str, int | None]:
    result: dict[str, int | None] = {f"land_{count}": None for count in (2, 3, 4)}
    result.update({f"first_{item.lower()}": None for item in (*CROPS, *ANIMALS)})
    for step_index, step in enumerate(states):
        if seat >= len(step):
            continue
        obs = step[seat].get("observation") or {}
        farms = obs.get("farms") or []
        if seat >= len(farms):
            continue
        farm = farms[seat]
        land = len(set(farm.get("unlocked_quadrants") or []))
        counts = portfolio(farm)
        for count in (2, 3, 4):
            key = f"land_{count}"
            if land >= count and result[key] is None:
                result[key] = step_index
        for item in (*CROPS, *ANIMALS):
            key = f"first_{item.lower()}"
            if counts[item] and result[key] is None:
                result[key] = step_index
    return result


def maxima(states: list[list[dict[str, Any]]], seat: int) -> dict[str, int]:
    result: Counter[str] = Counter()
    for step in states:
        if seat >= len(step):
            continue
        obs = step[seat].get("observation") or {}
        farms = obs.get("farms") or []
        if seat >= len(farms):
            continue
        counts = portfolio(farms[seat])
        for item in (*CROPS, *ANIMALS):
            result[item] = max(result[item], counts[item])
    return {item: result[item] for item in (*CROPS, *ANIMALS)}


def first_market_step(states: list[list[dict[str, Any]]], seat: int, operation: str, item: str = "") -> int | None:
    for step_index, step in enumerate(states):
        if seat >= len(step):
            continue
        action = step[seat].get("action") or {}
        for order in action.get("market") or []:
            if not order or str(order[0]) != operation:
                continue
            if not item or (len(order) >= 2 and str(order[1]) == item):
                return step_index
    return None


def live_family(maximum: dict[str, int], field_h48: str) -> str:
    if maximum["TOMATO"] and maximum["GOOSE"]:
        route = "tomato_goose"
    elif maximum["TOMATO"]:
        route = "tomato"
    elif maximum["GOOSE"]:
        route = "goose"
    elif maximum["CARROT"] >= 8:
        route = "carrot_strawberry"
    else:
        route = "strawberry_livestock"
    return f"{route}:{field_h48}"


def action_hash(states: list[list[dict[str, Any]]], seat: int, horizon: int, *, field_only: bool) -> str:
    actions = []
    for step in states[:horizon]:
        state = step[seat] if seat < len(step) else {}
        action = state.get("action") or {}
        if field_only:
            action = {"farmer": action.get("farmer"), "hands": action.get("hands")}
        actions.append(action)
    encoded = json.dumps(actions, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def episode_score_row(raw_episode: dict[str, Any], submission_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    indexed = {}
    for position, agent in enumerate((raw_episode.get("agents") or [])[:2]):
        index = integer(agent.get("index")) if agent.get("index") is not None else position
        indexed[index] = agent
    own_seat = next(
        (seat for seat, agent in indexed.items() if integer(agent.get("submissionId")) == submission_id),
        0,
    )
    return indexed.get(own_seat, {}), indexed.get(1 - own_seat, {})


def analyze_source(source: Path) -> list[dict[str, Any]]:
    metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    submission_id = integer(metadata["submission_id"])
    raw = json.loads((source / "episode_service_response.json").read_text(encoding="utf-8"))
    raw_episodes = {integer(row.get("id")): row for row in raw.get("episodes") or []}
    teams = {integer(row.get("id")): row for row in raw.get("teams") or []}
    with (source / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        manifest_rows = list(csv.DictReader(handle))
    records = []
    for manifest in manifest_rows:
        episode_id = integer(manifest["episode_id"])
        seat = integer(manifest["submission_seat"])
        replay_path = ROOT / "data" / manifest["replay_path"]
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        states = replay.get("steps") or []
        opponent_seat = 1 - seat
        raw_episode = raw_episodes[episode_id]
        own_score, opponent_score = episode_score_row(raw_episode, submission_id)
        own_checkpoints = {}
        opponent_checkpoints = {}
        for step in CHECKPOINTS:
            selected = states[min(step, len(states) - 1)]
            own_checkpoints[str(step)] = snapshot(selected[seat], seat)
            opponent_checkpoints[str(step)] = snapshot(selected[opponent_seat], opponent_seat)
        own_max = maxima(states, seat)
        opponent_max = maxima(states, opponent_seat)
        own_hash = action_hash(states, seat, 48, field_only=True)
        opponent_hash = action_hash(states, opponent_seat, 48, field_only=True)
        match_h48 = sum(
            canonical_action(step[seat]) == canonical_action(step[opponent_seat])
            for step in states[:48]
            if len(step) >= 2
        ) / max(1, min(48, len(states)))
        opponent_team = teams.get(integer(opponent_score.get("teamId")), {})
        own_reward = number(manifest.get("own_reward"))
        opponent_reward = number(manifest.get("opponent_reward"))
        records.append(
            {
                "submission_id": submission_id,
                "reported_rating": metadata.get("reported_rating"),
                "episode_id": episode_id,
                "seat": seat,
                "result": manifest.get("result"),
                "is_self_play": submission_id == integer(manifest.get("opponent_submission_id")),
                "reward": own_reward,
                "opponent_reward": opponent_reward,
                "margin": own_reward - opponent_reward,
                "initial_rating": number(own_score.get("initialScore")),
                "updated_rating": number(own_score.get("updatedScore")),
                "opponent_initial_rating": number(opponent_score.get("initialScore")),
                "opponent_updated_rating": number(opponent_score.get("updatedScore")),
                "opponent_submission_id": integer(opponent_score.get("submissionId")),
                "opponent_team": str(opponent_team.get("teamName") or manifest.get("opponent_team_name") or ""),
                "shops": list(
                    ((states[-1][seat].get("observation") or {}).get("town") or {}).get("unlocked_shops") or []
                ),
                "own_checkpoints": own_checkpoints,
                "opponent_checkpoints": opponent_checkpoints,
                "own_max": own_max,
                "opponent_max": opponent_max,
                "own_transitions": transition_steps(states, seat),
                "opponent_transitions": transition_steps(states, opponent_seat),
                "own_actions": action_counts(states, seat),
                "opponent_actions": action_counts(states, opponent_seat),
                "own_field_h48": own_hash,
                "opponent_field_h48": opponent_hash,
                "opening_action_match_rate": match_h48,
                "opponent_family": live_family(opponent_max, opponent_hash),
                "opponent_first_sell": first_market_step(states, opponent_seat, "SELL"),
                "own_first_sell": first_market_step(states, seat, "SELL"),
            }
        )
    return records


def summarize(selected: list[dict[str, Any]]) -> dict[str, Any]:
    if not selected:
        return {"episodes": 0}
    margins = [row["margin"] for row in selected]
    return {
        "episodes": len(selected),
        "wins": sum(row["result"] == "win" for row in selected),
        "losses": sum(row["result"] == "loss" for row in selected),
        "draws": sum(row["result"] == "draw" for row in selected),
        "win_score": mean(
            1.0 if row["result"] == "win" else 0.5 if row["result"] == "draw" else 0.0
            for row in selected
        ),
        "reward_mean": mean(row["reward"] for row in selected),
        "margin_mean": mean(margins),
        "margin_median": median(margins),
        "margin_p10": quantile(margins, 0.10),
        "opponent_initial_rating_mean": mean(row["opponent_initial_rating"] for row in selected),
    }


def checkpoint_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    margins = [row["margin"] for row in records]
    for step in CHECKPOINTS:
        key = str(step)
        metrics = {}
        for metric in ("money", "land", "hands", "productive", "inventory_value"):
            differences = [
                row["own_checkpoints"][key][metric] - row["opponent_checkpoints"][key][metric]
                for row in records
            ]
            metrics[metric] = {
                "own_mean": mean(row["own_checkpoints"][key][metric] for row in records),
                "opponent_mean": mean(row["opponent_checkpoints"][key][metric] for row in records),
                "difference_mean": mean(differences),
                "margin_correlation": correlation(differences, margins),
            }
        result[key] = metrics
    return result


def family_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        groups[row["opponent_family"]].append(row)
    rows = []
    for family, selected in groups.items():
        summary = summarize(selected)
        summary.update(
            {
                "family": family,
                "opening_hash": family.rsplit(":", 1)[-1],
                "opponent_max_mean": {
                    item: mean(row["opponent_max"][item] for row in selected)
                    for item in (*CROPS, *ANIMALS)
                },
                "episode_ids": [row["episode_id"] for row in selected],
            }
        )
        rows.append(summary)
    return sorted(rows, key=lambda row: (-row["episodes"], row["win_score"], row["family"]))


def paired_opponents(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        groups[row["opponent_submission_id"]].append(row)
    result = []
    for submission_id, selected in groups.items():
        if len(selected) < 2:
            continue
        summary = summarize(selected)
        summary.update(
            {
                "opponent_submission_id": submission_id,
                "opponent_team": selected[0]["opponent_team"],
                "families": dict(Counter(row["opponent_family"] for row in selected)),
                "episode_ids": [row["episode_id"] for row in selected],
            }
        )
        result.append(summary)
    return sorted(result, key=lambda row: (row["win_score"], row["margin_mean"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, action="append")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    sources = [path if path.is_absolute() else ROOT / path for path in (args.source or DEFAULT_SOURCES)]
    records = [row for source in sources for row in analyze_source(source)]
    public = [row for row in records if not row["is_self_play"]]
    cohorts = {
        "all": summarize(public),
        "win": summarize([row for row in public if row["result"] == "win"]),
        "loss": summarize([row for row in public if row["result"] == "loss"]),
        "opponent_below_1150": summarize([row for row in public if row["opponent_initial_rating"] < 1150]),
        "opponent_1150_1250": summarize(
            [row for row in public if 1150 <= row["opponent_initial_rating"] < 1250]
        ),
        "opponent_1250_plus": summarize([row for row in public if row["opponent_initial_rating"] >= 1250]),
    }
    per_submission = {
        str(submission_id): summarize([row for row in public if row["submission_id"] == submission_id])
        for submission_id in sorted({row["submission_id"] for row in public})
    }
    worst = sorted(public, key=lambda row: row["margin"])[:20]
    output = {
        "format": "kaggriculture-v117-live-forensics-v1",
        "sources": [str(path.relative_to(ROOT)).replace("\\", "/") for path in sources],
        "cohorts": cohorts,
        "per_submission": per_submission,
        "checkpoints": checkpoint_summary(public),
        "opponent_families": family_summary(public),
        "paired_opponents": paired_opponents(public),
        "worst_losses": [
            {
                key: row[key]
                for key in (
                    "submission_id",
                    "episode_id",
                    "margin",
                    "reward",
                    "opponent_reward",
                    "opponent_initial_rating",
                    "opponent_submission_id",
                    "opponent_team",
                    "opponent_family",
                    "shops",
                    "own_max",
                    "opponent_max",
                    "own_transitions",
                    "opponent_transitions",
                )
            }
            for row in worst
        ],
        "records": records,
        "interpretation": {
            "evidence": "descriptive complete public snapshot of both supplied V117 submissions",
            "causal_limit": "win/loss associations do not identify counterfactual gains from changing one action",
            "runtime_exclusion": "ratings, identities, replay hashes, and future state are analysis-only",
        },
    }
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compact = {key: value for key, value in output.items() if key not in {"records", "worst_losses"}}
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    print(f"output: {output_path}")


if __name__ == "__main__":
    main()
