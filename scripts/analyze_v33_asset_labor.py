"""Attribute productive actions and preceding movement to farm assets."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v3.feature_schema import farm_summary  # noqa: E402
from scripts.train_v12_relative_policy import _manifest, _observation, _replay_path, _split  # noqa: E402

FORMAT = "kaggriculture-v33-asset-labor-v1"
SOURCES = {
    "v11": ROOT / "data/submissions/v11_submission_55787906",
    "rank1": ROOT / "data/submissions/leaderboard_rank1_submission_55614463",
}
ASSETS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "COW", "SHEEP")
DAYS = tuple(range(11, 21))
MOVEMENT = {"NORTH", "SOUTH", "EAST", "WEST"}


def _farm(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = obs.get("farms") or []
    player = int(obs.get("player", seat))
    return farms[player] if 0 <= player < len(farms) else {}


def _positions(farm: dict[str, Any]) -> list[tuple[int, int]]:
    result = [tuple(farm.get("farmer") or [0, 0])]
    result.extend(tuple(value) for value in (farm.get("hands") or []))
    return result


def _actions(replay: dict[str, Any], decision_step: int, seat: int) -> list[list[Any]]:
    steps = replay.get("steps") or []
    stored = decision_step + 1
    if not 0 <= stored < len(steps):
        return []
    action = steps[stored][seat].get("action") or {}
    result = [list(action.get("farmer") or ["PASS"])]
    result.extend(list(value or ["PASS"]) for value in (action.get("hands") or []))
    return result


def _tile(farm: dict[str, Any], position: tuple[int, int]) -> Any:
    x, y = position
    tiles = farm.get("tiles") or []
    return tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]) else None


def _asset(action: list[Any], farm: dict[str, Any], position: tuple[int, int]) -> str | None:
    op = str(action[0]) if action else "PASS"
    if op in {"PASS", *MOVEMENT}:
        return None
    # Shed operations resolve before tile operations in the engine.  A shed
    # access tile may itself contain a crop or animal, but PICKUP/DROP still do
    # not service that asset and must not inherit its tile label.
    if op in {"PICKUP", "DROP"}:
        return None
    if op == "PLANT" and len(action) >= 2 and str(action[1]) in ASSETS:
        return str(action[1])
    tile = _tile(farm, position)
    if op == "PLACE" and len(action) >= 2:
        item = str(action[1])
        expected_structure = {"COW": "PASTURE", "SHEEP": "PASTURE"}.get(item)
        if (
            expected_structure is not None
            and isinstance(tile, dict)
            and tile.get("kind") == expected_structure
            and "animal" not in tile
        ):
            return item
        return None
    crop = str((tile or {}).get("crop") or "") if isinstance(tile, dict) else ""
    animal = str((tile or {}).get("animal") or "") if isinstance(tile, dict) else ""
    if crop in ASSETS:
        return crop
    if animal in ASSETS:
        return animal
    return None


def _future_asset(
    replay: dict[str, Any], seat: int, step: int, unit: int, lookahead: int = 6
) -> str | None:
    for future in range(step + 1, min(step + lookahead + 1, len(replay.get("steps") or []) - 1)):
        obs = _observation(replay, future, seat)
        if obs is None:
            return None
        farm = _farm(obs, seat)
        positions = _positions(farm)
        actions = _actions(replay, future, seat)
        if unit >= len(positions) or unit >= len(actions):
            return None
        op = str(actions[unit][0]) if actions[unit] else "PASS"
        if op == "PASS":
            return None
        if op in MOVEMENT:
            continue
        return _asset(actions[unit], farm, positions[unit])
    return None


def _side(replay: dict[str, Any], seat: int, episode_id: str, source: str) -> dict[str, Any]:
    productive: Counter[str] = Counter()
    movement: Counter[str] = Counter()
    asset_days: Counter[str] = Counter()
    unattributed = Counter()
    for day in DAYS:
        start = _observation(replay, day * 24, seat)
        if start is None:
            continue
        summary = farm_summary(_farm(start, seat))
        for asset in ASSETS:
            group = "animals" if asset in {"COW", "SHEEP"} else "crops"
            asset_days[asset] += int(summary[group][asset])
        for hour in range(24):
            step = day * 24 + hour
            obs = _observation(replay, step, seat)
            if obs is None:
                continue
            farm = _farm(obs, seat)
            positions = _positions(farm)
            actions = _actions(replay, step, seat)
            for unit, action in enumerate(actions):
                op = str(action[0]) if action else "PASS"
                if op == "PASS":
                    unattributed["pass"] += 1
                    continue
                if op in MOVEMENT:
                    target = _future_asset(replay, seat, step, unit)
                    if target is None:
                        unattributed["movement"] += 1
                    else:
                        movement[target] += 1
                    continue
                if unit >= len(positions):
                    unattributed["productive"] += 1
                    continue
                target = _asset(action, farm, positions[unit])
                if target is None:
                    unattributed["productive"] += 1
                else:
                    productive[target] += 1
    return {
        "source": source,
        "episode_id": episode_id,
        "split": _split(episode_id),
        "productive": dict(productive),
        "movement": dict(movement),
        "asset_days": dict(asset_days),
        "unattributed": dict(unattributed),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    productive: Counter[str] = Counter()
    movement: Counter[str] = Counter()
    asset_days: Counter[str] = Counter()
    unattributed: Counter[str] = Counter()
    for row in rows:
        productive.update(row["productive"])
        movement.update(row["movement"])
        asset_days.update(row["asset_days"])
        unattributed.update(row["unattributed"])
    games = max(1, len(rows))
    return {
        "games": len(rows),
        "per_game_10_days": {
            "productive": {asset: productive[asset] / games for asset in ASSETS},
            "movement": {asset: movement[asset] / games for asset in ASSETS},
            "asset_days": {asset: asset_days[asset] / games for asset in ASSETS},
            "unattributed": {name: value / games for name, value in unattributed.items()},
        },
        "turns_per_asset_day": {
            asset: {
                "productive": productive[asset] / max(1, asset_days[asset]),
                "movement": movement[asset] / max(1, asset_days[asset]),
                "total": (productive[asset] + movement[asset]) / max(1, asset_days[asset]),
            }
            for asset in ASSETS
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("data/analysis/v33_asset_labor.json")
    )
    args = parser.parse_args()
    rows = []
    for source, directory in SOURCES.items():
        manifests = _manifest(directory)
        for index, manifest in enumerate(manifests, start=1):
            if index == 1 or index % 25 == 0:
                print(f"[{source} {index}/{len(manifests)}]", flush=True)
            replay = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
            rows.append(
                _side(
                    replay,
                    int(manifest["submission_seat"]),
                    str(manifest["episode_id"]),
                    source,
                )
            )
    payload = {
        "format": FORMAT,
        "objective": "attribute Day-11..20 worker turns to the next realized asset action",
        "source_summary": {
            source: _summary([row for row in rows if row["source"] == source])
            for source in SOURCES
        },
        "v11_split_summary": {
            split: _summary(
                [row for row in rows if row["source"] == "v11" and row["split"] == split]
            )
            for split in ("train", "validation", "test")
        },
        "interpretation": {
            "fact": (
                "movement is attributed only when the same worker reaches a productive "
                "asset action within six turns"
            ),
            "limit": "turns per asset-day are descriptive and do not measure marginal profit or causal efficiency",
        },
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"result: {output}")


if __name__ == "__main__":
    main()
