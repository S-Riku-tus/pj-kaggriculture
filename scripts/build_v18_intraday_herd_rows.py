"""Build episode-split intraday herd-goal rows from Top-3 match winners.

V12 sampled only hour 0. V18 samples every three hours so a herd-purchase gate
can remain valid when sale proceeds become available later in the day. Labels
remain 72-hour future states; no logged worker action becomes a direct target.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import FEATURE_NAMES, encode_observation, farm_summary  # noqa: E402
from agents.v11 import main as v11  # noqa: E402
from scripts.train_v12_relative_policy import (  # noqa: E402
    TEACHERS,
    _manifest,
    _observation,
    _replay_path,
    _split,
)

FORMAT = "kaggriculture-v18-intraday-herd-rows-v2"
ANIMALS = ("COW", "SHEEP")
HOURS = tuple(range(0, 24, 3))


def _field_herd(farm: dict[str, Any]) -> dict[str, float]:
    animals = farm_summary(farm)["animals"]
    return {animal: float(animals[animal]) for animal in ANIMALS}


def _episode_sources() -> tuple[dict[str, Path], dict[str, dict[int, str]]]:
    paths: dict[str, Path] = {}
    sources: dict[str, dict[int, str]] = defaultdict(dict)
    for label, directory in TEACHERS.items():
        for row in _manifest(directory):
            episode_id = str(row["episode_id"])
            paths.setdefault(episode_id, _replay_path(row))
            sources[episode_id][int(row["submission_seat"])] = label
    return paths, sources


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/training/v18_intraday_herd_rows.json"),
    )
    args = parser.parse_args()
    episode_paths, sources = _episode_sources()
    rows: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    split_episodes: dict[str, set[str]] = defaultdict(set)
    source_sides: Counter[str] = Counter()
    for episode_index, (episode_id, replay_path) in enumerate(sorted(episode_paths.items()), start=1):
        if episode_index == 1 or episode_index % 25 == 0:
            print(f"[{episode_index}/{len(episode_paths)}] episode {episode_id}", flush=True)
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        step_count = len(replay.get("steps") or [])
        final = _observation(replay, step_count - 1, 0)
        if final is None or len(final.get("farms") or []) < 2:
            skipped["missing_final"] += 1
            continue
        final_money = [float(farm.get("money", 0) or 0) for farm in final["farms"]]
        if final_money[0] == final_money[1]:
            skipped["tie"] += 1
            continue
        winner = 0 if final_money[0] > final_money[1] else 1
        source = sources[episode_id].get(winner, "opponent")
        source_sides[source] += 1
        episode_split = _split(episode_id)
        split_episodes[episode_split].add(episode_id)
        for day in range(6, 20):
            for hour in HOURS:
                step = day * 24 + hour
                current = _observation(replay, step, winner)
                future24 = _observation(replay, min(step + 24, step_count - 1), winner)
                future72 = _observation(replay, min(step + 72, step_count - 1), winner)
                if current is None or future24 is None or future72 is None:
                    skipped["missing_step"] += 1
                    continue
                player = int(current.get("player", winner))
                future24_player = int(future24.get("player", winner))
                future72_player = int(future72.get("player", winner))
                farms = current.get("farms") or []
                future24_farms = future24.get("farms") or []
                future72_farms = future72.get("farms") or []
                if (
                    not 0 <= player < len(farms)
                    or not 0 <= future24_player < len(future24_farms)
                    or not 0 <= future72_player < len(future72_farms)
                ):
                    skipped["missing_farm"] += 1
                    continue
                farm = farms[player]
                opponent = farms[1 - player]
                private = current.get("private") or {}
                baseline_animals, *_rest = v11._strategy_targets(current, farm, opponent, private)
                owned = {animal: float(v11.v4._owned_animals(farm, private, animal)) for animal in ANIMALS}
                own_money = float(farm.get("money", 0) or 0)
                opponent_money = float(opponent.get("money", 0) or 0)
                money_gap_ratio = (own_money - opponent_money) / max(1.0, own_money + opponent_money)
                rows.append(
                    {
                        "episode_id": episode_id,
                        "split": episode_split,
                        "seat": winner,
                        "source": source,
                        "day": day,
                        "hour": hour,
                        "money_gap_ratio": money_gap_ratio,
                        "features": [*encode_observation(current), hour / 23.0],
                        "current_owned": owned,
                        "current_placed": _field_herd(farm),
                        "baseline": {animal: float(baseline_animals[animal]) for animal in ANIMALS},
                        "h24": _field_herd(future24_farms[future24_player]),
                        "h72": _field_herd(future72_farms[future72_player]),
                        "final_margin": final_money[winner] - final_money[1 - winner],
                    }
                )
    payload = {
        "format": FORMAT,
        "feature_names": [*FEATURE_NAMES, "hour"],
        "sampling": {
            "days": [6, 19],
            "hours": list(HOURS),
            "horizon_hours": [24, 72],
        },
        "episodes": len(episode_paths),
        "split_episodes": {split: len(episode_ids) for split, episode_ids in sorted(split_episodes.items())},
        "source_winner_sides": dict(source_sides),
        "skipped": dict(skipped),
        "rows": rows,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "format": FORMAT,
                "episodes": len(episode_paths),
                "rows": len(rows),
                "split_episodes": payload["split_episodes"],
                "source_winner_sides": payload["source_winner_sides"],
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
