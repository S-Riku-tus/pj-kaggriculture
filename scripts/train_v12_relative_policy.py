"""Build an episode-held-out, winner-conditioned portfolio router for V12.

The model intentionally predicts macro portfolio goals, not worker actions.
Rank 1/2/3 and opponents that defeated them remain separate candidate experts.
Candidates are fitted on train episodes, selected on validation episodes, and
reported once on an untouched test split.  Runtime features are observation
only; opponent private inventories never enter the model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import (  # noqa: E402
    BASE_PRICE,
    demand_profile,
    encode_observation,
    farm_summary,
)
from agents.v11 import main as v11  # noqa: E402

FORMAT = "kaggriculture-v12-relative-policy-v1"
CACHE_FORMAT = "kaggriculture-v12-relative-rows-v2"
TEACHERS = {
    "rank1": ROOT / "data/submissions/leaderboard_rank1_submission_55614463",
    "rank2": ROOT / "data/submissions/leaderboard_rank2_submission_55623460",
    "rank3": ROOT / "data/submissions/leaderboard_rank3_submission_55574890",
}
PORTFOLIO = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "COW", "SHEEP")
FOCUS = ("MILK", "WOOL", "STRAWBERRY", "WHEAT")
FOCUS_ASSET = {"MILK": "COW", "WOOL": "SHEEP", "STRAWBERRY": "STRAWBERRY", "WHEAT": "WHEAT"}
PHASES = ((6, 9), (10, 11), (12, 13), (14, 17), (18, 21), (22, 24), (25, 27))


def _split(episode_id: str) -> str:
    digest = hashlib.sha1(f"v12-relative-holdout:{episode_id}".encode()).digest()
    bucket = int.from_bytes(digest[:2], "big") % 5
    return "validation" if bucket == 0 else ("test" if bucket == 1 else "train")


def _manifest(directory: Path) -> list[dict[str, str]]:
    with (directory / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row.get("replay_status") in {"downloaded", "skipped_existing"}
            and row.get("team_name") != row.get("opponent_team_name")
            and int(float(row.get("step_count") or 0)) >= 719
        ]


def _replay_path(row: dict[str, str]) -> Path:
    direct = ROOT / row["replay_path"]
    return direct if direct.is_file() else ROOT / "data" / row["replay_path"]


def _phase(day: int) -> str:
    for lower, upper in PHASES:
        if lower <= day <= upper:
            return f"{lower}-{upper}"
    return "outside"


def _portfolio(farm: dict[str, Any]) -> dict[str, float]:
    summary = farm_summary(farm)
    return {
        **{crop: float(summary["crops"][crop]) for crop in PORTFOLIO[:5]},
        "COW": float(summary["animals"]["COW"]),
        "SHEEP": float(summary["animals"]["SHEEP"]),
    }


def _focus(obs: dict[str, Any], own: dict[str, Any], opponent: dict[str, Any]) -> tuple[str, dict[str, float]]:
    demand = demand_profile(obs)
    prices = (obs.get("market") or {}).get("prices") or {}
    opponent_portfolio = _portfolio(opponent)
    scores: dict[str, float] = {}
    for product in FOCUS:
        asset = FOCUS_ASSET[product]
        crowding = opponent_portfolio[asset]
        scale = 16.0 if asset in {"COW", "SHEEP"} else 50.0
        scores[product] = (
            float(demand.get(product, 0))
            + float(prices.get(product, BASE_PRICE[product]) or 0) / BASE_PRICE[product]
            - 0.35 * crowding / scale
        )
    selected = max(FOCUS, key=lambda product: (scores[product], -FOCUS.index(product)))
    own_portfolio = _portfolio(own)
    asset = FOCUS_ASSET[selected]
    crowded = own_portfolio[asset] + opponent_portfolio[asset] >= (15.0 if asset in {"COW", "SHEEP"} else 48.0)
    return selected, {
        "focus_margin": sorted(scores.values(), reverse=True)[0] - sorted(scores.values(), reverse=True)[1],
        "own_focus": own_portfolio[asset],
        "opponent_focus": opponent_portfolio[asset],
        "crowded": float(crowded),
    }


def context(obs: dict[str, Any], seat: int) -> dict[str, Any] | None:
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    if len(farms) < 2 or not 0 <= player < len(farms):
        return None
    own, opponent = farms[player], farms[1 - player]
    focus, details = _focus(obs, own, opponent)
    own_money = float(own.get("money", 0) or 0)
    opponent_money = float(opponent.get("money", 0) or 0)
    money_gap_ratio = (own_money - opponent_money) / max(1.0, own_money + opponent_money)
    crowded = "crowded" if details["crowded"] else "open"
    return {
        "key": f"{_phase(int(obs.get('day', 0) or 0))}|{focus}|{crowded}",
        "phase": _phase(int(obs.get("day", 0) or 0)),
        "focus": focus,
        "crowded": crowded,
        "money_gap_ratio": money_gap_ratio,
        **details,
    }


def _observation(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any] | None:
    steps = replay.get("steps") or []
    if not 0 <= step < len(steps) or not 0 <= seat < len(steps[step]):
        return None
    value = steps[step][seat].get("observation")
    return value if isinstance(value, dict) else None


def _gap(obs: dict[str, Any], seat: int) -> float:
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    if len(farms) < 2:
        return 0.0
    return float(farms[player].get("money", 0) or 0) - float(farms[1 - player].get("money", 0) or 0)


def _baseline(obs: dict[str, Any], seat: int) -> dict[str, float] | None:
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    if len(farms) < 2:
        return None
    private = obs.get("private") or {}
    animals, crops, *_rest = v11._strategy_targets(obs, farms[player], farms[1 - player], private)
    return {
        **{crop: float(crops[crop]) for crop in PORTFOLIO[:5]},
        "COW": float(animals["COW"]),
        "SHEEP": float(animals["SHEEP"]),
    }


def collect() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    episodes: dict[str, dict[str, Any]] = {}
    teacher_seats: dict[str, dict[int, str]] = defaultdict(dict)
    for label, directory in TEACHERS.items():
        for row in _manifest(directory):
            episode_id = str(row["episode_id"])
            teacher_seats[episode_id][int(row["submission_seat"])] = label
            episodes.setdefault(episode_id, row)

    rows: list[dict[str, Any]] = []
    source_counts: dict[str, int] = defaultdict(int)
    for episode_index, (episode_id, manifest) in enumerate(sorted(episodes.items()), start=1):
        print(f"[{episode_index}/{len(episodes)}] episode {episode_id}", flush=True)
        replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        final_obs = _observation(replay, len(replay.get("steps") or []) - 1, 0)
        if final_obs is None or len(final_obs.get("farms") or []) < 2:
            continue
        final_money = [float(farm.get("money", 0) or 0) for farm in final_obs["farms"]]
        if final_money[0] == final_money[1]:
            continue
        winner = 0 if final_money[0] > final_money[1] else 1
        for seat in (0, 1):
            source = teacher_seats[episode_id].get(seat, "opponent")
            source_counts[source] += 1
            for day in range(6, 28):
                step = day * 24
                current = _observation(replay, step, seat)
                h24 = _observation(replay, min(step + 24, 719), seat)
                h72 = _observation(replay, min(step + 72, 719), seat)
                if current is None or h24 is None or h72 is None:
                    continue
                player = int(current.get("player", seat))
                farms = current.get("farms") or []
                future24 = h24.get("farms") or []
                future72 = h72.get("farms") or []
                if len(farms) < 2 or len(future24) < 2 or len(future72) < 2:
                    continue
                state = context(current, seat)
                baseline = _baseline(current, seat)
                if state is None or baseline is None:
                    continue
                current_gap = _gap(current, seat)
                rows.append(
                    {
                        "episode_id": episode_id,
                        "split": _split(episode_id),
                        "seat": seat,
                        "source": source,
                        "winner": seat == winner,
                        "day": day,
                        **state,
                        "features": encode_observation(current),
                        "current": _portfolio(farms[player]),
                        "h24": _portfolio(future24[player]),
                        "h72": _portfolio(future72[player]),
                        "baseline": baseline,
                        "relative_delta_24": _gap(h24, seat) - current_gap,
                        "relative_delta_72": _gap(h72, seat) - current_gap,
                        "final_margin": final_money[seat] - final_money[1 - seat],
                    }
                )
    return rows, {"episodes": len(episodes), "source_episode_sides": dict(source_counts)}


def _profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        horizon: {item: round(median(row[horizon][item] for row in rows), 4) for item in PORTFOLIO}
        for horizon in ("h24", "h72")
    }


def _mae(rows: list[dict[str, Any]], prediction: dict[str, Any] | None) -> dict[str, float]:
    if not rows or prediction is None:
        return {"h24": math.inf, "h72": math.inf, "combined": math.inf}
    result: dict[str, float] = {}
    for horizon in ("h24", "h72"):
        target = prediction[horizon]
        result[horizon] = mean(mean(abs(row[horizon][item] - target[item]) for item in PORTFOLIO) for row in rows)
    result["combined"] = mean(result.values())
    return result


def _baseline_mae(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"h24": math.inf, "h72": math.inf, "combined": math.inf}
    result = {
        horizon: mean(mean(abs(row[horizon][item] - row["baseline"][item]) for item in PORTFOLIO) for row in rows)
        for horizon in ("h24", "h72")
    }
    result["combined"] = mean(result.values())
    return result


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"p10": 0.0, "median": 0.0, "mean": 0.0}
    return {
        "p10": round(ordered[max(0, math.ceil(0.1 * len(ordered)) - 1)], 4),
        "median": round(median(ordered), 4),
        "mean": round(mean(ordered), 4),
    }


def train(rows: list[dict[str, Any]], source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    keys = sorted({row["key"] for row in rows})
    selected: dict[str, Any] = {}
    report_branches: dict[str, Any] = {}
    for key in keys:
        buckets = {
            split: [row for row in rows if row["key"] == key and row["split"] == split]
            for split in ("train", "validation", "test")
        }
        train_winners = [row for row in buckets["train"] if row["winner"]]
        validation_winners = [row for row in buckets["validation"] if row["winner"]]
        test_winners = [row for row in buckets["test"] if row["winner"]]
        candidates: dict[str, Any] = {}
        for expert in (*TEACHERS, "opponent"):
            fitting = [row for row in train_winners if row["source"] == expert]
            if len(fitting) < 8:
                continue
            profile = _profile(fitting)
            candidates[expert] = {
                "support": len(fitting),
                "profile": profile,
                "validation_mae": _mae(validation_winners, profile),
                "test_mae": _mae(test_winners, profile),
                "relative_value": {
                    metric: _distribution([float(row[metric]) for row in fitting])
                    for metric in ("relative_delta_24", "relative_delta_72", "final_margin")
                },
            }
        baseline_validation = _baseline_mae(validation_winners)
        baseline_test = _baseline_mae(test_winners)
        # Do not let a large 72-hour gain hide a worse immediate transition.
        # Sparse validation branches were the main false positive in the first
        # audit, so release requires independent improvement at both horizons.
        viable = [
            expert
            for expert, candidate in candidates.items()
            if candidate["support"] >= 12
            and len(validation_winners) >= 20
            and candidate["validation_mae"]["h24"] <= 0.95 * baseline_validation["h24"]
            and candidate["validation_mae"]["h72"] <= 0.95 * baseline_validation["h72"]
        ]
        chosen = min(viable, key=lambda expert: candidates[expert]["validation_mae"]["combined"], default=None)
        train_context = [row for row in buckets["train"] if row["winner"]]
        if chosen is not None:
            ranges = {
                feature: [
                    round(min(float(row[feature]) for row in train_context), 6),
                    round(max(float(row[feature]) for row in train_context), 6),
                ]
                for feature in ("money_gap_ratio", "focus_margin", "own_focus", "opponent_focus")
            }
            selected[key] = {
                "expert": chosen,
                "train_support": candidates[chosen]["support"],
                "validation_examples": len(validation_winners),
                "profile": candidates[chosen]["profile"],
                "ranges": ranges,
            }
        report_branches[key] = {
            "counts": {split: len(values) for split, values in buckets.items()},
            "winner_counts": {
                "train": len(train_winners),
                "validation": len(validation_winners),
                "test": len(test_winners),
            },
            "baseline": {"validation_mae": baseline_validation, "test_mae": baseline_test},
            "candidates": candidates,
            "selected": chosen,
        }
    model = {
        "format": FORMAT,
        "created_at": datetime.now().astimezone().isoformat(),
        "portfolio": list(PORTFOLIO),
        "selection": selected,
        "ood_features": ["money_gap_ratio", "focus_margin", "own_focus", "opponent_focus"],
        "source": source,
    }
    report = {
        "objective": "Winner-conditioned expert routing for 24h/72h public portfolio targets",
        "selection_uses": "train profiles and validation selection only; test is untouched reporting",
        "source": source,
        "rows": len(rows),
        "episode_split": {
            split: len({row["episode_id"] for row in rows if row["split"] == split})
            for split in ("train", "validation", "test")
        },
        "selected_branches": len(selected),
        "branches": report_branches,
    }
    return model, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("agents/v12/relative_policy_model.json"))
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=Path("data/analysis/v12_relative_policy_validation.json"),
    )
    parser.add_argument(
        "--dataset-cache",
        type=Path,
        default=Path("data/training/v12_relative_rows.json"),
    )
    args = parser.parse_args()
    cache = args.dataset_cache if args.dataset_cache.is_absolute() else ROOT / args.dataset_cache
    if cache.is_file() and json.loads(cache.read_text(encoding="utf-8")).get("format") == CACHE_FORMAT:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        rows, source = cached["rows"], cached["source"]
        for row in rows:
            _old_phase, focus, crowded = row["key"].split("|")
            row["phase"] = _phase(int(row["day"]))
            row["key"] = f"{row['phase']}|{focus}|{crowded}"
    else:
        rows, source = collect()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps(
                {"format": CACHE_FORMAT, "source": source, "rows": rows},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    model, report = train(rows, source)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    validation = args.validation_output if args.validation_output.is_absolute() else ROOT / args.validation_output
    output.parent.mkdir(parents=True, exist_ok=True)
    validation.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    validation.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "selected_branches": len(model["selection"]), **source}, indent=2))
    print(f"model: {output}")
    print(f"validation: {validation}")


if __name__ == "__main__":
    main()
