"""Reproduce the V109 live diagnosis and screen V110's bounded market overlay.

The script keeps episodes intact, uses the repository's frozen hash split, and
reports train/validation/test plus lower-tail and failure cohorts.  Overlay
playback is observational: logged future prices come from the unchanged V109
episode and therefore measure support for timing, not causal reward.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v110 import main as v110  # noqa: E402
from scripts.train_v12_relative_policy import _split  # noqa: E402

FORMAT = "kaggriculture-v110-live-strategy-analysis-v1"
V109_DIR = ROOT / "data" / "submissions" / "v109_submission_55890113"
V109_DETAILS = ROOT / "data" / "analysis" / "v110_v109_episodes.csv"
TOP3_DETAILS = ROOT / "data" / "analysis" / "v8_top3_full_episodes.csv"
PREMIUM = ("STRAWBERRY", "MELON", "MILK", "WOOL")
CHECKPOINT_STEPS = (24, 72, 168, 264, 432, 480, 528, 576, 648, 696, 719)


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "mean": 0.0, "median": 0.0, "p10": 0.0, "minimum": 0.0}
    return {
        "count": len(values),
        "mean": mean(values),
        "median": median(values),
        "p10": _percentile(values, 0.10),
        "minimum": min(values),
    }


def _manifest() -> list[dict[str, str]]:
    with (V109_DIR / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row.get("replay_status") in {"downloaded", "skipped_existing"}
            and row.get("team_name") != row.get("opponent_team_name")
            and int(float(row.get("step_count") or 0)) >= 719
        ]


def _replay_path(row: dict[str, str]) -> Path:
    direct = ROOT / str(row["replay_path"])
    return direct if direct.is_file() else ROOT / "data" / str(row["replay_path"])


def _observation(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any] | None:
    steps = replay.get("steps") or []
    if not (0 <= step < len(steps)) or seat >= len(steps[step]):
        return None
    obs = steps[step][seat].get("observation") or {}
    if not isinstance(obs, dict) or not obs.get("farms"):
        return None
    return obs


def _action(replay: dict[str, Any], decision_step: int, seat: int) -> dict[str, Any]:
    recorded = decision_step + 1
    steps = replay.get("steps") or []
    if not (0 <= recorded < len(steps)) or seat >= len(steps[recorded]):
        return {}
    action = steps[recorded][seat].get("action") or {}
    return action if isinstance(action, dict) else {}


def _sell_quantity(action: dict[str, Any], item: str) -> int:
    return sum(
        max(0, int(order[2] or 0))
        for order in (action.get("market") or [])[:10]
        if isinstance(order, list)
        and len(order) >= 3
        and order[0] == "SELL"
        and str(order[1]) == item
    )


def _checkpoint_gaps(replay: dict[str, Any], seat: int) -> dict[str, float]:
    result = {}
    for step in CHECKPOINT_STEPS:
        obs = _observation(replay, min(step, len(replay.get("steps") or []) - 1), seat)
        if obs is None:
            continue
        farms = obs.get("farms") or []
        result[str(step)] = float(farms[seat].get("money", 0) or 0) - float(
            farms[1 - seat].get("money", 0) or 0
        )
    return result


def _market_phase(replay: dict[str, Any], seat: int) -> dict[str, dict[str, int]]:
    quantities: Counter[tuple[str, int]] = Counter()
    for step in range(len(replay.get("steps") or []) - 1):
        obs = _observation(replay, step, seat)
        if obs is None:
            continue
        private = obs.get("private") or {}
        available = {item: int((private.get("shed") or {}).get(item, 0) or 0) for item in PREMIUM}
        for item in PREMIUM:
            requested = _sell_quantity(_action(replay, step, seat), item)
            sold = min(available[item], requested)
            quantities[item, int(obs.get("hour", step % 24) or 0) % 4] += sold
    return {
        item: {str(phase): quantities[item, phase] for phase in range(4)}
        for item in PREMIUM
    }


def _playback_overlays(
    replay: dict[str, Any],
    seat: int,
) -> list[dict[str, Any]]:
    v110.reset_runtime_state()
    configuration = replay.get("configuration") or {}
    rows = []
    steps = replay.get("steps") or []
    for step in range(len(steps) - 1):
        obs = _observation(replay, step, seat)
        if obs is None:
            continue
        v110.agent(obs, configuration)
        diagnostic = v110.policy_diagnostics(obs)
        overlay = diagnostic.get("last_overlay")
        if not isinstance(overlay, dict):
            continue
        item = str(overlay["item"])
        target = int(overlay["target"])
        target_obs = _observation(replay, target, seat)
        current_price = float(((obs.get("market") or {}).get("prices") or {}).get(item, 0) or 0)
        target_price = (
            float(((target_obs.get("market") or {}).get("prices") or {}).get(item, 0) or 0)
            if target_obs is not None
            else current_price
        )
        opponent_requested = sum(
            _sell_quantity(_action(replay, future, 1 - seat), item)
            for future in range(step, min(target + 1, len(steps) - 1))
        )
        quantity = int(overlay["quantity"])
        rows.append(
            {
                **overlay,
                "step": step,
                "day": int(obs.get("day", step // 24) or 0),
                "hour": int(obs.get("hour", step % 24) or 0),
                "current_price": current_price,
                "logged_target_price": target_price,
                "quote_delta": current_price - target_price,
                "quote_advantage": quantity * (current_price - target_price),
                "opponent_requested_before_target": opponent_requested,
            }
        )
    return rows


def _episode_row(manifest: dict[str, str]) -> dict[str, Any]:
    episode_id = str(manifest["episode_id"])
    seat = int(manifest["submission_seat"])
    replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
    gaps = _checkpoint_gaps(replay, seat)
    final_margin = float(manifest.get("own_reward") or 0) - float(manifest.get("opponent_reward") or 0)
    overlays = _playback_overlays(replay, seat)
    return {
        "episode_id": episode_id,
        "split": _split(episode_id),
        "result": str(manifest.get("result") or "unknown"),
        "reward": float(manifest.get("own_reward") or 0),
        "margin": final_margin,
        "gaps": gaps,
        "day18_ahead_final_loss": float(gaps.get("432", 0)) > 0 and final_margin < 0,
        "day20_ahead_final_loss": float(gaps.get("480", 0)) > 0 and final_margin < 0,
        "own_sell_phase": _market_phase(replay, seat),
        "opponent_sell_phase": _market_phase(replay, 1 - seat),
        "overlays": overlays,
    }


def _overlay_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [overlay for episode in episodes for overlay in episode["overlays"]]
    quote_advantages = [float(row["quote_advantage"]) for row in rows]
    by_mode = defaultdict(list)
    by_item = defaultdict(list)
    for row in rows:
        by_mode[str(row["mode"])].append(row)
        by_item[str(row["item"])].append(row)

    def summarize(group: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "events": len(group),
            "episodes": len({row.get("episode_id") for row in group}),
            "quantity": sum(int(row["quantity"]) for row in group),
            "positive_quote_delta_rate": (
                sum(float(row["quote_delta"]) > 0 for row in group) / len(group) if group else 0.0
            ),
            "quote_advantage": _stats([float(row["quote_advantage"]) for row in group]),
            "opponent_requested_units": sum(
                int(row["opponent_requested_before_target"]) for row in group
            ),
        }

    return {
        **summarize(rows),
        "total_quote_advantage": sum(quote_advantages),
        "by_mode": {name: summarize(group) for name, group in sorted(by_mode.items())},
        "by_item": {name: summarize(group) for name, group in sorted(by_item.items())},
    }


def _phase_pool(episodes: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    result = {}
    for item in PREMIUM:
        quantities = Counter()
        for episode in episodes:
            quantities.update(
                {int(phase): int(value) for phase, value in episode[key][item].items()}
            )
        total = sum(quantities.values())
        result[item] = {
            "quantity": {str(phase): quantities[phase] for phase in range(4)},
            "share": {
                str(phase): quantities[phase] / total if total else 0.0 for phase in range(4)
            },
        }
    return result


def _episode_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    rewards = [float(row["reward"]) for row in episodes]
    margins = [float(row["margin"]) for row in episodes]
    gap_by_step = {
        str(step): _stats(
            [float(row["gaps"][str(step)]) for row in episodes if str(step) in row["gaps"]]
        )
        for step in CHECKPOINT_STEPS
    }
    return {
        "episodes": len(episodes),
        "results": dict(Counter(row["result"] for row in episodes)),
        "reward": _stats(rewards),
        "margin": _stats(margins),
        "gap_by_step": gap_by_step,
        "day18_ahead_final_losses": sum(bool(row["day18_ahead_final_loss"]) for row in episodes),
        "day20_ahead_final_losses": sum(bool(row["day20_ahead_final_loss"]) for row in episodes),
        "own_sell_phase": _phase_pool(episodes, "own_sell_phase"),
        "opponent_sell_phase": _phase_pool(episodes, "opponent_sell_phase"),
        "overlay_playback": _overlay_summary(episodes),
    }


def _load_metric_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = []
    for row in rows:
        parsed: dict[str, Any] = dict(row)
        parsed["day_snapshots"] = json.loads(row.get("day_snapshots") or "{}")
        for key, value in row.items():
            if key == "day_snapshots" or value in (None, ""):
                continue
            if str(value).lower() in {"true", "false"}:
                parsed[key] = str(value).lower() == "true"
                continue
            try:
                parsed[key] = float(value)
            except ValueError:
                pass
        result.append(parsed)
    return result


def _portfolio_at(row: dict[str, Any], day: int) -> tuple[int, ...]:
    snapshot = row["day_snapshots"].get(str(day), {})
    crops = snapshot.get("crops") or {}
    animals = snapshot.get("animals") or {}
    return tuple(
        int((animals if item in {"COW", "SHEEP"} else crops).get(item, 0) or 0)
        for item in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "COW", "SHEEP")
    )


def _portfolio_diversity() -> dict[str, Any]:
    v109_rows = [row for row in _load_metric_rows(V109_DETAILS) if not bool(row.get("is_self_play"))]
    top_rows = [row for row in _load_metric_rows(TOP3_DETAILS) if not bool(row.get("is_self_play"))]
    cohorts = {"v109": v109_rows}
    for label in ("rank1", "rank2", "rank3"):
        cohorts[label] = [row for row in top_rows if row.get("label") == label]
    result = {}
    for label, rows in cohorts.items():
        portfolios = [_portfolio_at(row, 20) for row in rows]
        result[label] = {
            "episodes": len(rows),
            "day20_distinct_portfolios": len(set(portfolios)),
            "day20_most_common": [
                {"portfolio": list(portfolio), "episodes": count}
                for portfolio, count in Counter(portfolios).most_common(5)
            ],
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v110_live_strategy_analysis.json")
    )
    parser.add_argument(
        "--screen-rejected-phase-gate",
        action="store_true",
        help="observationally replay the disabled phase-only candidate",
    )
    args = parser.parse_args()
    v110.ENABLE_PHASE_FRONT_RUN = bool(args.screen_rejected_phase_gate)
    manifests = _manifest()
    episodes = []
    for index, manifest in enumerate(manifests, start=1):
        print(f"[{index}/{len(manifests)}] episode {manifest['episode_id']}", flush=True)
        episode = _episode_row(manifest)
        for overlay in episode["overlays"]:
            overlay["episode_id"] = episode["episode_id"]
            overlay["split"] = episode["split"]
            overlay["result"] = episode["result"]
        episodes.append(episode)

    payload = {
        "format": FORMAT,
        "sources": {
            "v109_live_submission": "data/submissions/v109_submission_55890113",
            "v109_episode_metrics": str(V109_DETAILS.relative_to(ROOT)),
            "top3_episode_metrics": str(TOP3_DETAILS.relative_to(ROOT)),
        },
        "split_rule": "SHA1(v12-relative-holdout:episode_id), 60/20/20 buckets",
        "candidate_mode": (
            "rejected-phase-screen" if args.screen_rejected_phase_gate else "production-default"
        ),
        "overall": _episode_summary(episodes),
        "by_split": {
            split: _episode_summary([row for row in episodes if row["split"] == split])
            for split in ("train", "validation", "test")
        },
        "by_result": {
            result: _episode_summary([row for row in episodes if row["result"] == result])
            for result in ("win", "loss", "draw")
        },
        "portfolio_diversity": _portfolio_diversity(),
        "failure_episodes": [
            {
                "episode_id": row["episode_id"],
                "split": row["split"],
                "result": row["result"],
                "reward": row["reward"],
                "margin": row["margin"],
                "gaps": row["gaps"],
                "overlays": row["overlays"],
            }
            for row in episodes
            if row["result"] != "win"
        ],
        "interpretation": {
            "fact": "episode outcomes, public farm states, actions, and market observations are replay-derived",
            "screen": (
                "V110 thresholds were frozen before this playback run and are reported on all three episode splits"
            ),
            "limit": "quote advantage uses the logged unchanged future price; it is not a closed-loop reward estimate",
            "promotion": (
                "requires causal local safety diagnostics and then live rating uncertainty; "
                "playback alone cannot promote"
            ),
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"overall": payload["overall"], "by_split": payload["by_split"]}, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
