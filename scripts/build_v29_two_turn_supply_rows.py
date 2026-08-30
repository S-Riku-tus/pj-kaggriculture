"""Build Top-3 rows for opponent sales over the current and next turn.

Rows are sampled at every pre-Town phase from the perspective of each Top-3
submission present in a replay.  Features are public only.  Private sheds are
used solely to cap declared SELL labels and never enter the feature vector.
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

from scripts.build_v18_intraday_herd_rows import _episode_sources  # noqa: E402
from scripts.build_v22_opponent_supply_rows import (  # noqa: E402
    _declared_sell_prefix,
    _history_values,
    _public_values,
)
from scripts.train_v12_relative_policy import _observation, _split  # noqa: E402

FORMAT = "kaggriculture-v29-two-turn-supply-rows-v1"
ITEMS = ("STRAWBERRY", "MILK", "WOOL")
DAYS = tuple(range(5, 25))
HOURS = tuple(range(0, 24, 4))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("data/training/v29_two_turn_supply_rows.json")
    )
    args = parser.parse_args()
    episode_paths, sources = _episode_sources()
    rows: list[dict[str, Any]] = []
    feature_names: list[str] | None = None
    split_episodes: dict[str, set[str]] = defaultdict(set)
    source_sides: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    for index, (episode_id, replay_path) in enumerate(sorted(episode_paths.items()), start=1):
        if index == 1 or index % 25 == 0:
            print(f"[{index}/{len(episode_paths)}] {episode_id}", flush=True)
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        steps = replay.get("steps") or []
        if len(steps) < 719:
            skipped["short_replay"] += 1
            continue
        prefix = _declared_sell_prefix(replay)
        episode_split = _split(episode_id)
        split_episodes[episode_split].add(episode_id)
        for own_seat, source in sorted(sources[episode_id].items()):
            source_sides[source] += 1
            target_seat = 1 - own_seat
            for day in DAYS:
                for hour in HOURS:
                    step = day * 24 + hour
                    obs = _observation(replay, step, own_seat)
                    if obs is None or len(obs.get("farms") or []) < 2:
                        skipped["missing_observation"] += 1
                        continue
                    features = _public_values(obs, own_seat)
                    features.update(_history_values(replay, step, own_seat, obs))
                    names = list(features)
                    if feature_names is None:
                        feature_names = names
                    elif names != feature_names:
                        raise ValueError("feature order changed while building rows")
                    stop = min(step + 2, len(steps))
                    labels = {
                        item: float(
                            prefix[target_seat][item][stop]
                            - prefix[target_seat][item][step]
                        )
                        for item in ITEMS
                    }
                    rows.append(
                        {
                            "episode_id": episode_id,
                            "split": episode_split,
                            "source": source,
                            "own_seat": own_seat,
                            "day": day,
                            "hour": hour,
                            "features": [float(features[name]) for name in feature_names],
                            "labels": labels,
                        }
                    )
    payload = {
        "format": FORMAT,
        "items": list(ITEMS),
        "horizon_turns": 2,
        "sampling": {"days": [min(DAYS), max(DAYS)], "hours": list(HOURS)},
        "feature_names": feature_names or [],
        "episodes": len(episode_paths),
        "source_sides": dict(source_sides),
        "split_episodes": {name: len(value) for name, value in sorted(split_episodes.items())},
        "split_disjoint": all(
            split_episodes[left].isdisjoint(split_episodes[right])
            for index, left in enumerate(split_episodes)
            for right in list(split_episodes)[index + 1 :]
        ),
        "feature_privacy": "public current observation and public 6/24-turn history only",
        "label_note": "declared opponent SELL over current+next turn capped by pre-action private shed",
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
                "episodes": payload["episodes"],
                "rows": len(rows),
                "features": len(payload["feature_names"]),
                "source_sides": payload["source_sides"],
                "split_episodes": payload["split_episodes"],
                "split_disjoint": payload["split_disjoint"],
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
