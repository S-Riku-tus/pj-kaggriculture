"""Safety-test V112 against action streams from the current top-three corpus.

The recorded opponent is intentionally open loop after the new trajectory
diverges.  Results are therefore safety/state-generation diagnostics, not a
rating estimate and not evidence that V112 beat the live top agent.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kaggle_environments import make  # noqa: E402

from agents.v112 import main as v112  # noqa: E402

SOURCES = {
    "current_rank1": ROOT
    / "data/submissions/leaderboard_20260831_rank1_tetsuya_submission_55905066",
    "current_rank2": ROOT
    / "data/submissions/leaderboard_20260831_rank2_yusuke_hayashi_submission_55865730",
    "current_rank3": ROOT
    / "data/submissions/leaderboard_20260831_rank3_mtn_submission_55867591",
}


def _rows(directory: Path, sample: int) -> list[dict[str, str]]:
    with (directory / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        available = [
            row
            for row in csv.DictReader(handle)
            if row.get("replay_status") in {"downloaded", "skipped_existing"}
            and int(float(row.get("step_count") or 0)) >= 719
        ]
    ordered = sorted(available, key=lambda row: float(row.get("own_reward") or 0))
    if sample >= len(ordered):
        return ordered
    indexes = {round(i * (len(ordered) - 1) / max(1, sample - 1)) for i in range(sample)}
    return [ordered[index] for index in sorted(indexes)]


def _path(row: dict[str, str]) -> Path:
    direct = ROOT / str(row["replay_path"])
    return direct if direct.is_file() else ROOT / "data" / str(row["replay_path"])


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    getter = getattr(value, "get", None)
    if callable(getter):
        return getter(key, default)
    return getattr(value, key, default)


def _inventory_units(private: dict[str, Any]) -> int:
    inventories = [private.get("shed") or {}, *(private.get("inventories") or [])]
    return sum(
        max(0, int(quantity or 0))
        for inventory in inventories
        for quantity in inventory.values()
        if isinstance(quantity, int | float)
    )


def _animal_count(farm: Any) -> int:
    result = 0
    for row in _get(farm, "tiles", []) or []:
        for tile in row or []:
            result += _get(tile, "animal") in {"GOOSE", "COW", "SHEEP"}
    return result


def _weed_count(farm: Any) -> int:
    result = 0
    for row in _get(farm, "tiles", []) or []:
        for tile in row or []:
            result += tile == "WEED" or _get(tile, "kind") == "WEED"
    return result


def _run(label: str, row: dict[str, str]) -> dict[str, Any]:
    replay = json.loads(_path(row).read_text(encoding="utf-8"))
    seat = int(row["submission_seat"])
    opponent = 1 - seat
    seed = int(replay["info"]["seed"])
    v112._WEED_STATE = {0: {}, 1: {}}
    trace = {
        "minimum_cash": float("inf"),
        "maximum_weeds": 0,
        "previous_animals": None,
        "animal_losses": 0,
    }

    def candidate(obs: Any, configuration: Any = None):
        farm = _get(obs, "farms", [])[seat]
        money = float(_get(farm, "money", 0) or 0)
        animals = _animal_count(farm)
        previous = trace["previous_animals"]
        trace["minimum_cash"] = min(float(trace["minimum_cash"]), money)
        trace["maximum_weeds"] = max(int(trace["maximum_weeds"]), _weed_count(farm))
        if previous is not None and animals < int(previous):
            trace["animal_losses"] += int(previous) - animals
        trace["previous_animals"] = animals
        return v112.agent(obs, configuration)

    def scripted(obs: Any, _configuration: Any = None):
        step = int(_get(obs, "step", 0) or 0)
        stored = min(step + 1, len(replay["steps"]) - 1)
        return copy.deepcopy(replay["steps"][stored][opponent].get("action") or {})

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    env.run([candidate, scripted] if seat == 0 else [scripted, candidate])
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    observation = final[seat]["observation"]
    private = observation.get("private") or {}
    return {
        "source": label,
        "episode_id": row["episode_id"],
        "seed": seed,
        "seat": seat,
        "statuses": [str(state.status) for state in final],
        "candidate_reward": rewards[seat],
        "scripted_opponent_reward": rewards[opponent],
        "margin_debug_only": rewards[seat] - rewards[opponent],
        "original_teacher_reward": float(row.get("own_reward") or 0),
        "original_opponent_reward": float(row.get("opponent_reward") or 0),
        "minimum_cash": trace["minimum_cash"],
        "maximum_weeds": trace["maximum_weeds"],
        "animal_losses": trace["animal_losses"],
        "terminal_private_units": _inventory_units(private),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=2, help="quantile episodes per teacher")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/analysis/v112_teacher_fork_diagnostics.json"),
    )
    args = parser.parse_args()
    games = [
        _run(label, row)
        for label, directory in SOURCES.items()
        for row in _rows(directory, max(1, args.sample))
    ]
    payload = {
        "format": "kaggriculture-v112-teacher-fork-diagnostics-v1",
        "warning": (
            "recorded opponents are open loop after divergence; margins are debugging observations, "
            "not live top-agent win rates or rating estimates"
        ),
        "summary": {
            "games": len(games),
            "all_done": all(game["statuses"] == ["DONE", "DONE"] for game in games),
            "mean_candidate_reward": mean(game["candidate_reward"] for game in games),
            "minimum_candidate_reward": min(game["candidate_reward"] for game in games),
            "mean_margin_debug_only": mean(game["margin_debug_only"] for game in games),
            "maximum_terminal_private_units": max(game["terminal_private_units"] for game in games),
            "total_animal_losses": sum(game["animal_losses"] for game in games),
            "maximum_weeds": max(game["maximum_weeds"] for game in games),
        },
        "games": games,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"diagnostics: {output}")


if __name__ == "__main__":
    main()
