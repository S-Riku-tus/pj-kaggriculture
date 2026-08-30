"""Compare V9/V10 with a top-team teacher on complete episodes.

This is an off-policy diagnostic, not a rollout or a rating estimate.  It uses
whole-episode filtering and samples the same six observations per day used by
the V9 decision-policy evaluation.  The default remains V9's untouched Rank-1
test bucket; another submission can be supplied for external evaluation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v9 import main as v9  # noqa: E402
from agents.v10 import main as v10  # noqa: E402
from scripts import train_v9_decision_policy as training  # noqa: E402

POLICIES = {"teacher": None, "v9": v9.agent, "v10": v10.agent}
FIELD_KEYS = (
    "PLANT_WHEAT",
    "PLANT_STRAWBERRY",
    "FERTILIZE",
    "WATER",
    "FEED",
    "CARE",
    "COLLECT_FERTILIZER",
    "HARVEST",
    "PASS",
    "MOVE",
)
MARKET_KEYS = (
    "SELL_WHEAT",
    "SELL_STRAWBERRY",
    "SELL_MELON",
    "SELL_MILK",
    "SELL_WOOL",
    "SELL_FERTILIZER",
    "BUY_SEED_WHEAT",
    "BUY_SEED_STRAWBERRY",
    "BUY_ANIMAL_COW",
    "BUY_ANIMAL_SHEEP",
    "BUY_LAND",
    "HIRE",
)
MOVE = {"NORTH", "SOUTH", "EAST", "WEST"}


def _field_key(action: Any) -> str:
    if not isinstance(action, list) or not action:
        return "PASS"
    verb = str(action[0])
    if verb in MOVE:
        return "MOVE"
    if verb == "PLANT" and len(action) >= 2:
        return f"PLANT_{action[1]}"
    return verb


def _field_actions(action: dict[str, Any]) -> list[Any]:
    return [action.get("farmer", ["PASS"]), *(action.get("hands", []) or [])]


def _market_counts(action: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for order in action.get("market", []) or []:
        if not isinstance(order, list) or not order:
            continue
        verb = str(order[0])
        key = verb
        if verb in {"SELL", "BUY_SEED", "BUY_ANIMAL"} and len(order) >= 2:
            key = f"{verb}_{order[1]}"
        quantity = 1 if verb in {"BUY_LAND", "HIRE"} else max(
            0, v9.base._as_int(order[2] if len(order) >= 3 else 0)
        )
        counts[key] += quantity
    return counts


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)

    def percentile(probability: float) -> float:
        if not ordered:
            return 0.0
        position = (len(ordered) - 1) * probability
        lower = math.floor(position)
        upper = math.ceil(position)
        fraction = position - lower
        return ordered[lower] * (1 - fraction) + ordered[upper] * fraction

    return {
        "p10": round(percentile(0.10), 5),
        "median": round(percentile(0.50), 5),
        "mean": round(sum(ordered) / max(1, len(ordered)), 5),
        "p90": round(percentile(0.90), 5),
    }


def _source_rows(source: Path, split: str) -> list[dict[str, str]]:
    with (source / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows = [
        row
        for row in rows
        if row.get("replay_status") in {"downloaded", "skipped_existing"}
        and row.get("opponent_team_name") != row.get("team_name")
    ]
    if split != "all":
        rows = [row for row in rows if training._split(row["episode_id"]) == split]
    return rows


def analyze(
    start_day: int = 6,
    end_day: int = 10,
    source: Path = training.SOURCE,
    split: str = "test",
    teacher_label: str = "Rank-1",
) -> dict[str, Any]:
    rows = _source_rows(source, split)
    totals = {
        name: {"field": Counter(), "market": Counter(), "fertilize_crop": Counter()}
        for name in POLICIES
    }
    exact = {name: Counter() for name in ("v9", "v10")}
    field_confusion = {name: Counter() for name in ("v9", "v10")}
    sale_confusion = {
        name: {item: Counter() for item in v9.MARKET_ITEMS}
        for name in ("v9", "v10")
    }
    episode_l1: dict[str, list[float]] = defaultdict(list)
    recovery = Counter()
    worst: dict[str, list[dict[str, Any]]] = defaultdict(list)
    observations = 0

    for row in rows:
        replay = json.loads(training._replay_path(row).read_text(encoding="utf-8"))
        seat = int(row["submission_seat"])
        episode_counts = {
            name: {"field": Counter(), "market": Counter()}
            for name in POLICIES
        }
        for step in range(
            start_day * 24,
            min((end_day + 1) * 24, len(replay.get("steps", [])) - 1),
            4,
        ):
            obs = training._observation(replay, step, seat)
            if obs is None:
                continue
            teacher = training._action(replay, step, seat)
            actions = {"teacher": teacher, "v9": v9.agent(obs), "v10": v10.agent(obs)}
            observations += 1

            diagnostic = v10.policy_diagnostics(obs).get("capital_recovery", {})
            recovery["active"] += int(bool(diagnostic.get("active")))
            recovery[str(diagnostic.get("reason", "unknown"))] += 1

            teacher_units = _field_actions(teacher)
            shed = (obs.get("private", {}) or {}).get("shed", {}) or {}
            farms = obs.get("farms", []) or []
            player = int(obs.get("player", seat))
            farm = farms[player] if 0 <= player < len(farms) else {}
            positions = [farm.get("farmer") or [0, 0], *(farm.get("hands") or [])]
            tiles = farm.get("tiles") or []
            for name, action in actions.items():
                unit_actions = _field_actions(action)
                unit_keys = [_field_key(unit) for unit in unit_actions]
                field_counts = Counter(unit_keys)
                market_counts = _market_counts(action)
                totals[name]["field"].update(field_counts)
                totals[name]["market"].update(market_counts)
                for unit, unit_action in enumerate(unit_actions):
                    if _field_key(unit_action) != "FERTILIZE" or unit >= len(positions):
                        continue
                    x, y = positions[unit]
                    tile = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]) else None
                    crop = str(tile.get("crop", "UNKNOWN")) if isinstance(tile, dict) else "INVALID"
                    totals[name]["fertilize_crop"][crop] += 1
                episode_counts[name]["field"].update(field_counts)
                episode_counts[name]["market"].update(market_counts)
                if name == "teacher":
                    continue
                predicted_units = _field_actions(action)
                for index, teacher_unit in enumerate(teacher_units):
                    teacher_key = _field_key(teacher_unit)
                    predicted_key = _field_key(
                        predicted_units[index] if index < len(predicted_units) else ["PASS"]
                    )
                    exact[name]["units"] += 1
                    exact[name]["verb"] += int(predicted_key == teacher_key)
                    exact[name]["productive_units"] += int(teacher_key not in {"PASS", "MOVE"})
                    exact[name]["productive_verb"] += int(
                        teacher_key not in {"PASS", "MOVE"} and predicted_key == teacher_key
                    )
                    field_confusion[name][f"{predicted_key}->{teacher_key}"] += 1
                predicted_market = _market_counts(action)
                teacher_market = _market_counts(teacher)
                for item in v9.MARKET_ITEMS:
                    if v9.base._inventory_count(shed, item) <= 0:
                        continue
                    truth = teacher_market[f"SELL_{item}"] > 0
                    predicted = predicted_market[f"SELL_{item}"] > 0
                    sale_confusion[name][item][
                        "tp" if truth and predicted else (
                            "fn" if truth else ("fp" if predicted else "tn")
                        )
                    ] += 1

        for name in ("v9", "v10"):
            l1 = sum(
                abs(episode_counts[name]["field"][key] - episode_counts["teacher"]["field"][key])
                for key in FIELD_KEYS
            ) + sum(
                abs(episode_counts[name]["market"][key] - episode_counts["teacher"]["market"][key])
                for key in MARKET_KEYS
            )
            episode_l1[name].append(float(l1))
            worst[name].append({"episode_id": row["episode_id"], "l1": l1})

    episode_count = len(rows)

    def per_episode(counter: Counter[str], keys: tuple[str, ...]) -> dict[str, float]:
        return {key: round(counter[key] / max(1, episode_count), 5) for key in keys}

    def confusion_metrics(values: Counter[str]) -> dict[str, Any]:
        tp, fp, fn, tn = (values[key] for key in ("tp", "fp", "fn", "tn"))
        return {
            "examples": tp + fp + fn + tn,
            "precision": round(tp / max(1, tp + fp), 5),
            "recall": round(tp / max(1, tp + fn), 5),
            "f1": round(2 * tp / max(1, 2 * tp + fp + fn), 5),
            "false_positives": fp,
            "false_negatives": fn,
        }

    return {
        "objective": (
            f"off-policy phase diagnostic against {teacher_label} on whole episodes; "
            "not a rollout or rating estimate"
        ),
        "source": str(source.relative_to(ROOT) if source.is_relative_to(ROOT) else source),
        "episode_filter": split,
        "episodes": episode_count,
        "observations": observations,
        "sampling": f"Days {start_day}-{end_day} inclusive, every 4 hours",
        "recovery": {
            "active_rate": round(recovery["active"] / max(1, observations), 5),
            "reasons": dict(recovery),
        },
        "policies": {
            name: {
                "field_per_episode": per_episode(totals[name]["field"], FIELD_KEYS),
                "market_quantity_per_episode": per_episode(totals[name]["market"], MARKET_KEYS),
                "fertilize_target_crop_per_episode": {
                    crop: round(count / max(1, episode_count), 5)
                    for crop, count in sorted(totals[name]["fertilize_crop"].items())
                },
                **(
                    {}
                    if name == "teacher"
                    else {
                        "field_verb_agreement": round(
                            exact[name]["verb"] / max(1, exact[name]["units"]), 5
                        ),
                        "productive_field_verb_recall": round(
                            exact[name]["productive_verb"]
                            / max(1, exact[name]["productive_units"]),
                            5,
                        ),
                        "episode_action_l1": _distribution(episode_l1[name]),
                        "field_confusion": dict(field_confusion[name].most_common()),
                        "sell_decision": {
                            item: confusion_metrics(sale_confusion[name][item])
                            for item in v9.MARKET_ITEMS
                        },
                        "worst_episode_l1": sorted(
                            worst[name], key=lambda value: value["l1"], reverse=True
                        )[:5],
                    }
                ),
            }
            for name in POLICIES
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v10_counterfactual_untouched.json")
    )
    parser.add_argument("--start-day", type=int, default=6)
    parser.add_argument("--end-day", type=int, default=10)
    parser.add_argument("--source", type=Path, default=training.SOURCE)
    parser.add_argument(
        "--split", choices=("all", "train", "validation", "test"), default="test"
    )
    parser.add_argument("--teacher-label", default="Rank-1")
    args = parser.parse_args()
    if args.end_day < args.start_day:
        parser.error("--end-day must be >= --start-day")
    source = args.source if args.source.is_absolute() else ROOT / args.source
    report = analyze(args.start_day, args.end_day, source, args.split, args.teacher_label)
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
