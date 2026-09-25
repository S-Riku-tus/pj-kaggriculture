"""Teacher-prefix continuations for the frozen full-action BC archive.

The focal learner runs closed loop after an exact saved prefix.  The other
seat continues its saved replay actions, so this is explicitly a fixed-replay
counterfactual and not DAgger or a reactive-teacher match.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_round6_anchors import prepare_archives, sha256, write_json  # noqa: E402
from scripts.evaluate_round6_imitation import (  # noqa: E402
    _action_token,
    _load_module,
    _selected_teacher_rows,
    _units,
    restore_observation,
)

EXPERIMENT = ROOT / "experiments" / "learning_round6_20260922"
PREFIX = 96


def exact_fields(state: Mapping[str, Any]) -> dict[str, Any]:
    observation = state["observation"]
    return {
        "farms": observation["farms"],
        "market": observation["market"],
        "town": observation["town"],
        "day": observation["day"],
        "hour": observation["hour"],
        "private": observation["private"],
    }


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def make_env(replay: Mapping[str, Any]) -> Any:
    from kaggle_environments import make

    configuration = dict(replay["configuration"])
    configuration.pop("seed", None)
    return make("kaggriculture", configuration=configuration, info={"seed": int(replay["info"]["seed"])}, debug=True)


def replay_prefix(env: Any, replay: Mapping[str, Any], prefix: int) -> int | None:
    for record in range(1, prefix + 1):
        env.step([replay["steps"][record][seat]["action"] for seat in (0, 1)])
        if any(exact_fields(env.steps[-1][seat]) != exact_fields(replay["steps"][record][seat]) for seat in (0, 1)):
            return record
    return None


def reconstruct_teacher_history(module: Any, replay: Mapping[str, Any], seat: int, prefix: int) -> None:
    module.reset_runtime_state()
    history = module._history.setdefault(seat, module.MarketHistory())
    for decision in range(prefix):
        observation = restore_observation(replay["steps"][decision], seat, decision)
        prior = replay["steps"][decision][seat].get("action") if decision > 0 else None
        history.update(observation, (prior or {}).get("market", []) if isinstance(prior, Mapping) else [])
        teacher = replay["steps"][decision + 1][seat].get("action") or {
            "farmer": ["PASS"],
            "hands": [],
            "market": [],
        }
        module._previous_actor[seat] = [_action_token(module, value) for value in _units(teacher)]
        module._previous_market[seat] = [list(value) for value in teacher.get("market") or []]
    module._probes[seat] = []


def summarize(observation: Mapping[str, Any], seat: int) -> dict[str, Any]:
    farm = observation["farms"][seat]
    private = observation["private"]
    animals = Counter()
    crops = Counter()
    for row in farm["tiles"]:
        for tile in row:
            if not isinstance(tile, Mapping):
                continue
            if tile.get("animal"):
                animals[str(tile["animal"])] += 1
            if tile.get("kind") == "PLANT":
                crops[str(tile.get("crop"))] += 1
    return {
        "money": float(farm["money"]),
        "shed": dict(private["shed"]),
        "seeds": dict(private["seeds"]),
        "animals": dict(animals),
        "crops": dict(crops),
    }


def run_case(
    module: Any,
    replay: dict[str, Any],
    row: Mapping[str, Any],
    horizon: int,
    output_dir: Path = EXPERIMENT / "closed_loop_continuations",
) -> dict[str, Any]:
    seat = int(row["seat"])
    opponent = 1 - seat
    env = make_env(replay)
    mismatch = replay_prefix(env, replay, PREFIX)
    if mismatch is not None:
        raise RuntimeError(f"prefix reconstruction mismatch at record {mismatch}")
    prefix_hash = canonical_hash([exact_fields(env.steps[-1][value]) for value in (0, 1)])
    teacher_prefix_hash = canonical_hash([exact_fields(replay["steps"][PREFIX][value]) for value in (0, 1)])
    reconstruct_teacher_history(module, replay, seat, PREFIX)
    first_difference = None
    legal_shapes = 0
    for decision in range(PREFIX, PREFIX + horizon):
        learner_action = module.agent(env.state[seat].observation, env.configuration)
        teacher_action = replay["steps"][decision + 1][seat]["action"]
        legal_shapes += int(
            isinstance(learner_action, dict)
            and isinstance(learner_action.get("farmer"), list)
            and isinstance(learner_action.get("hands"), list)
            and isinstance(learner_action.get("market"), list)
        )
        if first_difference is None and learner_action != teacher_action:
            first_difference = {
                "decision_step": decision,
                "learner": learner_action,
                "teacher": teacher_action,
            }
        actions = [None, None]
        actions[seat] = learner_action
        actions[opponent] = replay["steps"][decision + 1][opponent]["action"]
        env.step(actions)
    counterfactual = env.toJSON()
    end_record = PREFIX + horizon
    learner_observation = counterfactual["steps"][-1][seat]["observation"]
    teacher_observation = restore_observation(replay["steps"][end_record], seat, end_record)
    learner = summarize(learner_observation, seat)
    teacher = summarize(teacher_observation, seat)
    output = output_dir / f"episode_{row['episode_id']}_prefix_{PREFIX}_horizon_{horizon}.json.gz"
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(counterfactual, stream, ensure_ascii=False, separators=(",", ":"))
    statuses = [str(value["status"]) for value in counterfactual["steps"][-1]]
    return {
        "episode_id": int(row["episode_id"]),
        "seat": seat,
        "seed": int(replay["info"]["seed"]),
        "prefix_steps": PREFIX,
        "rollout_steps": horizon,
        "remaining_all": horizon == len(replay["steps"]) - 1 - PREFIX,
        "prefix_exact": prefix_hash == teacher_prefix_hash,
        "prefix_state_sha256": prefix_hash,
        "teacher_prefix_state_sha256": teacher_prefix_hash,
        "opponent_after_branch": "fixed saved replay actions; not reactive",
        "dagger_claimed": False,
        "first_action_difference": first_difference,
        "valid_action_shapes": legal_shapes,
        "learner_end": learner,
        "teacher_end": teacher,
        "delta_self_money": learner["money"] - teacher["money"],
        "learner_opponent_money": float(
            counterfactual["steps"][-1][opponent]["observation"]["farms"][opponent]["money"]
        ),
        "teacher_opponent_money": float(
            replay["steps"][end_record][opponent]["observation"]["farms"][opponent]["money"]
        ),
        "statuses": statuses,
        "stored_states": len(counterfactual["steps"]),
        "counterfactual_replay": str(output.relative_to(ROOT)),
        "counterfactual_replay_sha256": sha256(output),
    }


def planned_horizons(step_count: int, prefix: int = PREFIX) -> list[int]:
    remaining = step_count - prefix
    return list(dict.fromkeys([24, 48, 96, 192, remaining]))


def main(candidate: str = "round6_full_action_bc") -> None:
    preregistration = json.loads((EXPERIMENT / "preregistration.json").read_text(encoding="utf-8"))
    if candidate not in preregistration["arms"]:
        raise ValueError(f"unknown candidate: {candidate}")
    archive = ROOT / preregistration["arms"][candidate]["archive"]
    run_root, extracted = prepare_archives([candidate])
    module = _load_module(extracted[candidate])
    suffix = "" if candidate == "round6_full_action_bc" else f"_{candidate}"
    output_dir = EXPERIMENT / f"closed_loop_continuations{suffix}"
    row = _selected_teacher_rows()[0]
    path = ROOT / str(row["path"])
    if sha256(path) != row["sha256"]:
        raise RuntimeError(f"teacher replay hash mismatch: {path}")
    replay = json.loads(path.read_text(encoding="utf-8"))
    horizons = planned_horizons(len(replay["steps"]) - 1)
    results = []
    for index, horizon in enumerate(horizons, 1):
        results.append(run_case(module, replay, row, horizon, output_dir))
        print(f"continuation {index}/{len(horizons)} horizon={horizon}", flush=True)
    payload = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "candidate": candidate,
        "archive": str(archive.relative_to(ROOT)),
        "archive_sha256": sha256(archive),
        "teacher_submission": 56216119,
        "teacher_episode": int(row["episode_id"]),
        "source_split": "test",
        "extraction_root": str(run_root),
        "scope": "exact teacher prefix followed by learner closed loop against fixed saved opponent actions",
        "reactive_opponent_evidence": "separate normal-start v122/v123/v124 development evaluation",
        "all_prefixes_exact": all(value["prefix_exact"] for value in results),
        "results": results,
    }
    write_json(output_dir / "summary.json", payload)
    print(
        json.dumps(
            {"all_prefixes_exact": payload["all_prefixes_exact"], "results": results},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default="round6_full_action_bc")
    arguments = parser.parse_args()
    main(arguments.candidate)
