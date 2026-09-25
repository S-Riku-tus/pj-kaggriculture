"""Summarize a paired Round11 panel against its B1 arm."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]


def point(result: str) -> float:
    return 1.0 if result == "W" else 0.5 if result == "T" else 0.0


def read_replay(path: str) -> dict:
    with gzip.open(ROOT / path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def action_diff(baseline: dict, candidate: dict, seat: int) -> dict:
    if baseline.get("format") != "round10-kagsim-l1-trace-v1":
        return {
            "own_action_changed_decisions": None,
            "own_field_changed_decisions": None,
            "own_market_changed_decisions": None,
            "opponent_action_changed_decisions": None,
            "full_trajectory_identical": None,
        }
    left = baseline["decisions"]
    right = candidate["decisions"]
    count = min(len(left), len(right))
    own = field = market = opponent = 0
    for index in range(count):
        left_actions = left[index]["actions"]
        right_actions = right[index]["actions"]
        la, ra = left_actions[seat], right_actions[seat]
        own += la != ra
        field += (la.get("farmer"), la.get("hands")) != (
            ra.get("farmer"),
            ra.get("hands"),
        )
        market += la.get("market") != ra.get("market")
        opponent += left_actions[1 - seat] != right_actions[1 - seat]
    return {
        "own_action_changed_decisions": own + abs(len(left) - len(right)),
        "own_field_changed_decisions": field,
        "own_market_changed_decisions": market,
        "opponent_action_changed_decisions": opponent,
        "full_trajectory_identical": left == right
        and baseline.get("rewards") == candidate.get("rewards"),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panel", type=Path)
    parser.add_argument("--baseline", default="B1")
    args = parser.parse_args()
    panel = args.panel if args.panel.is_absolute() else ROOT / args.panel
    with (panel / "games.csv").open(encoding="utf-8-sig", newline="") as stream:
        games = list(csv.DictReader(stream))
    key = lambda row: (row["opponent_id"], row["seed"], row["seat"])
    baseline = {key(row): row for row in games if row["arm"] == args.baseline}
    pairs: list[dict] = []
    replay_cache: dict[str, dict] = {}
    for row in games:
        if row["arm"] == args.baseline:
            continue
        left = baseline[key(row)]
        if left["replay"] not in replay_cache:
            replay_cache[left["replay"]] = read_replay(left["replay"])
        candidate_replay = read_replay(row["replay"])
        diffs = action_diff(
            replay_cache[left["replay"]], candidate_replay, int(row["seat"])
        )
        pairs.append(
            {
                "arm": row["arm"],
                "opponent_id": row["opponent_id"],
                "opponent_family": row["opponent_family"],
                "seed": int(row["seed"]),
                "seat": int(row["seat"]),
                "baseline_result": left["result"],
                "candidate_result": row["result"],
                "transition": f"{left['result']}->{row['result']}",
                "delta_points": point(row["result"]) - point(left["result"]),
                "delta_self_cash": float(row["self_final_cash"])
                - float(left["self_final_cash"]),
                "delta_opp_cash": float(row["opp_final_cash"])
                - float(left["opp_final_cash"]),
                "delta_margin": float(row["margin"]) - float(left["margin"]),
                **diffs,
            }
        )
    write_csv(panel / "paired_results.csv", pairs)

    arms = list(dict.fromkeys(row["arm"] for row in games))
    summaries = []
    for arm in arms:
        selected = [row for row in games if row["arm"] == arm]
        paired = [row for row in pairs if row["arm"] == arm]
        transitions = Counter(row["transition"] for row in paired)
        summaries.append(
            {
                "arm": arm,
                "games": len(selected),
                "wins": sum(row["result"] == "W" for row in selected),
                "losses": sum(row["result"] == "L" for row in selected),
                "ties": sum(row["result"] == "T" for row in selected),
                "score_rate": mean(point(row["result"]) for row in selected),
                "mean_self_cash": mean(float(row["self_final_cash"]) for row in selected),
                "mean_opp_cash": mean(float(row["opp_final_cash"]) for row in selected),
                "mean_margin": mean(float(row["margin"]) for row in selected),
                "mean_delta_points_vs_b1": mean(row["delta_points"] for row in paired)
                if paired
                else 0.0,
                "mean_delta_margin_vs_b1": mean(row["delta_margin"] for row in paired)
                if paired
                else 0.0,
                "loss_to_win": transitions["L->W"],
                "win_to_loss": transitions["W->L"],
                "tie_to_win": transitions["T->W"],
                "tie_to_loss": transitions["T->L"],
                "changed_games_vs_b1": sum(
                    (row["own_action_changed_decisions"] or 0) > 0 for row in paired
                ),
                "changed_decisions_vs_b1": sum(
                    row["own_action_changed_decisions"] or 0 for row in paired
                ),
                "changed_field_decisions_vs_b1": sum(
                    row["own_field_changed_decisions"] or 0 for row in paired
                ),
                "changed_market_decisions_vs_b1": sum(
                    row["own_market_changed_decisions"] or 0 for row in paired
                ),
                "opponent_changed_decisions_vs_b1": sum(
                    row["opponent_action_changed_decisions"] or 0 for row in paired
                ),
                "trajectory_identical_games": sum(
                    row["full_trajectory_identical"] is True for row in paired
                ),
            }
        )
    write_csv(panel / "panel_summary.csv", summaries)

    blocks: list[dict] = []
    by_arm_seed: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in pairs:
        by_arm_seed[(row["arm"], row["seed"])].append(row)
    for (arm, seed), selected in sorted(by_arm_seed.items()):
        blocks.append(
            {
                "arm": arm,
                "seed": seed,
                "pairs": len(selected),
                "mean_delta_points": mean(row["delta_points"] for row in selected),
                "mean_delta_self_cash": mean(row["delta_self_cash"] for row in selected),
                "mean_delta_opp_cash": mean(row["delta_opp_cash"] for row in selected),
                "mean_delta_margin": mean(row["delta_margin"] for row in selected),
            }
        )
    write_csv(panel / "seed_block_summary.csv", blocks)
    print(json.dumps({"games": len(games), "pairs": len(pairs), "summaries": summaries}, indent=2))


if __name__ == "__main__":
    main()
