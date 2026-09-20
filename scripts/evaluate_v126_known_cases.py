"""Closed-loop regression of V125/V126 against recorded opponent routes.

The opponent is a fixed action tape, so these games are execution regressions,
not reacting-opponent strength evidence.  Unlike the fixture verifier, the
candidate agent and the real kaggriculture engine are run from turn zero.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "experiments/research_20260920_v126/known_case_rollouts.json"
CASES = (
    {
        "episode_id": 111196878,
        "seat": 1,
        "path": ROOT / "data/replays/v125_submission_56384917/episode_111196878.json",
    },
    {
        "episode_id": 111203616,
        "seat": 1,
        "path": ROOT / "data/replays/v125_submission_56384917/episode_111203616.json",
    },
    {
        "episode_id": 110824511,
        "seat": 0,
        "path": ROOT
        / "data/submissions/v124_submission_56357320/episodes/110824511/replay/episode_110824511.json",
    },
    {
        "episode_id": 111007532,
        "seat": 0,
        "path": ROOT
        / "data/submissions/v124_submission_56360233/episodes/111007532/replay/episode_111007532.json",
    },
)
ARMS = {
    "v125_live": ROOT / "agents/v125_exec/main.py",
    "v126_exec": ROOT / "agents/v126_exec/main.py",
}
PASS = {"farmer": ["PASS"], "hands": [], "market": []}


def _load(path: Path, label: str) -> Any:
    name = f"_v126_known_{label}_{os.getpid()}_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: Any) -> str:
    return json.dumps(value or PASS, sort_keys=True, separators=(",", ":"))


def _actor_events(replay: dict[str, Any], seat: int) -> dict[str, int]:
    audit = _load(
        ROOT
        / "artifacts/v125_analysis_package_20260920/v125_analysis_package/scripts/audit_engine.py",
        "audit",
    )
    counts = {
        "failed_pickup": 0,
        "failed_place": 0,
        "failed_feed": 0,
        "successful_feed": 0,
        "animal_exits": 0,
    }
    steps = replay["steps"]
    for turn in range(min(719, len(steps) - 1)):
        previous = steps[turn]
        following = steps[turn + 1]
        farm = copy.deepcopy(previous[0]["observation"]["farms"][seat])
        private = copy.deepcopy(previous[seat]["observation"]["private"])
        action = following[seat].get("action") or PASS
        day = int(previous[seat]["observation"].get("day", turn // 24))
        events = audit.units(farm, private, action, day)
        for event in events:
            op = str(event.get("op") or "")
            effect = bool(event.get("effect"))
            if op == "PICKUP" and not effect:
                counts["failed_pickup"] += 1
            elif op in {"PLACE", "DROP"} and not effect:
                counts["failed_place"] += 1
            elif op == "FEED":
                counts["successful_feed" if effect else "failed_feed"] += 1

        before_tiles = previous[0]["observation"]["farms"][seat]["tiles"]
        after_tiles = following[0]["observation"]["farms"][seat]["tiles"]
        for y, row in enumerate(before_tiles):
            for x, raw in enumerate(row):
                if not isinstance(raw, dict) or "animal" not in raw:
                    continue
                after = after_tiles[y][x]
                if isinstance(after, dict) and "animal" not in after:
                    counts["animal_exits"] += 1
    return counts


def _run(
    source: dict[str, Any], source_path: Path, episode_id: int, seat: int, arm: str, path: Path
) -> dict[str, Any]:
    from kaggle_environments import make

    module = _load(path, f"{arm}_{episode_id}_{seat}")
    opponent_seat = 1 - seat
    tape = [
        (source["steps"][turn + 1][opponent_seat].get("action") or PASS)
        for turn in range(len(source["steps"]) - 1)
    ]

    def focal(observation: Any) -> dict[str, Any]:
        return module.agent(observation)

    def opponent(observation: Any) -> dict[str, Any]:
        step = int(observation.get("step", 24 * int(observation.get("day", 0)) + int(observation.get("hour", 0))))
        return copy.deepcopy(tape[step]) if step < len(tape) else copy.deepcopy(PASS)

    configuration = dict(source.get("configuration") or {})
    configuration["episodeSteps"] = 720
    configuration["seed"] = int((source.get("info") or {}).get("seed", 0))
    env = make("kaggriculture", configuration=configuration, debug=True)
    env.run([focal, opponent] if seat == 0 else [opponent, focal])
    replay = env.toJSON()
    recorded = [
        source["steps"][turn + 1][seat].get("action") or PASS
        for turn in range(min(719, len(source["steps"]) - 1))
    ]
    emitted = [
        replay["steps"][turn + 1][seat].get("action") or PASS
        for turn in range(min(719, len(replay["steps"]) - 1))
    ]
    changes = sum(_canonical(left) != _canonical(right) for left, right in zip(recorded, emitted, strict=True))
    change_examples = [
        {"step": step, "recorded": left, "emitted": right}
        for step, (left, right) in enumerate(zip(recorded, emitted, strict=True))
        if _canonical(left) != _canonical(right)
    ][:20]
    final = replay["steps"][-1]
    cash = [float(slot.get("reward") or 0) for slot in final]
    final_private = final[seat]["observation"]["private"]
    final_shed = final_private.get("shed") or {}
    shops = []
    for turn in range(0, min(720, len(replay["steps"])), 24):
        shops.append(list(replay["steps"][turn][0]["observation"]["town"].get("unlocked_shops") or []))
    replay_path = (
        DEFAULT_OUTPUT.parent
        / "known_case_replays"
        / arm
        / f"episode_{episode_id}_seat_{seat}.json.gz"
    )
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(replay_path, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))
    diagnostics = {}
    getter = getattr(module, "latest_diagnostics", None)
    if callable(getter):
        diagnostics = getter(seat)
    return {
        "episode_id": episode_id,
        "source_replay": str(source_path.relative_to(ROOT)),
        "arm": arm,
        "seat": seat,
        "seed": configuration["seed"],
        "recorded_action_differences": changes,
        "action_difference_examples": change_examples,
        "our_cash": cash[seat],
        "opponent_cash": cash[opponent_seat],
        "margin": cash[seat] - cash[opponent_seat],
        "win": cash[seat] > cash[opponent_seat],
        "final_shed_animals": {
            animal: int(final_shed.get(animal, 0))
            for animal in ("GOOSE", "COW", "SHEEP")
        },
        "events": _actor_events(replay, seat),
        "shop_sequence": shops,
        "diagnostics": diagnostics,
        "replay": str(replay_path.relative_to(ROOT)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--new-only", action="store_true")
    args = parser.parse_args()
    selected = CASES[:2] if args.new_only else CASES
    results: list[dict[str, Any]] = []
    for case in selected:
        source_path = Path(case["path"])
        source = json.loads(source_path.read_text(encoding="utf-8"))
        for arm, path in ARMS.items():
            result = _run(
                source,
                source_path,
                int(case["episode_id"]),
                int(case["seat"]),
                arm,
                path,
            )
            results.append(result)
            print(
                f"{arm} episode={case['episode_id']} seat={case['seat']} "
                f"margin={result['margin']:.0f} exits={result['events']['animal_exits']} "
                f"changes={result['recorded_action_differences']}",
                flush=True,
            )
    baseline_exact = all(
        row["recorded_action_differences"] == 0
        for row in results
        if row["arm"] == "v125_live" and row["episode_id"] in {111196878, 111203616}
    )
    payload = {
        "format": "v126-known-case-closed-loop-v1",
        "classification": "fixed recorded opponent; execution regression only",
        "baseline_new_case_actions_exact": baseline_exact,
        "results": results,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "baseline_exact": baseline_exact}, indent=2))
    return 0 if baseline_exact else 1


if __name__ == "__main__":
    raise SystemExit(main())
