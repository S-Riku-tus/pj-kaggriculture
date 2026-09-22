"""Exact teacher-prefix reconstruction followed by bounded learner rollouts.

The private teacher cannot be queried on learner states.  After the exact
prefix, the focal Round5 policy is closed-loop while the other seat replays its
saved action sequence.  This is counterfactual replay evidence, not DAgger.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "experiments/learning_round5_20260921/teacher_prefix"
MANIFEST = ROOT / "experiments/learning_round4_20260921/EPISODE_SPLIT_MANIFEST.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_round5_20260921 import learned_main  # noqa: E402
from agents.learning_round5_20260921.action_codec import normalize_action  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def restored_observation(replay: dict[str, Any], record: int, seat: int) -> dict[str, Any]:
    observation = copy.deepcopy(replay["steps"][record][0]["observation"])
    private = replay["steps"][record][seat]["observation"]
    observation["player"] = seat
    observation["private"] = copy.deepcopy(private["private"])
    observation["remainingOverageTime"] = private.get("remainingOverageTime", 60)
    observation["step"] = record
    return observation


def exact_fields(state: dict[str, Any]) -> dict[str, Any]:
    observation = state["observation"]
    return {
        "farms": observation["farms"],
        "market": observation["market"],
        "town": observation["town"],
        "day": observation["day"],
        "hour": observation["hour"],
        "private": observation["private"],
    }


def summarize(observation: dict[str, Any], seat: int) -> dict[str, Any]:
    farm = observation["farms"][seat]
    private = observation["private"]
    animals = []
    positive_yield = []
    for y, row in enumerate(farm["tiles"]):
        for x, tile in enumerate(row):
            if isinstance(tile, dict) and tile.get("animal"):
                value = {"position": [x, y], "animal": tile["animal"], "yield_units": int(tile.get("yield_units", 0)), "consecutive_unfed": int(tile.get("consecutive_unfed", 0))}
                animals.append(value)
                if value["yield_units"] > 0:
                    positive_yield.append(value)
    return {
        "money": int(farm["money"]),
        "shed": dict(private["shed"]),
        "seeds": dict(private["seeds"]),
        "carried": [dict(value) for value in private["inventories"]],
        "animals": animals,
        "positive_animal_yield": positive_yield,
    }


def make_env(replay: dict[str, Any]) -> Any:
    from kaggle_environments import make

    configuration = dict(replay["configuration"])
    configuration.pop("seed", None)
    return make("kaggriculture", configuration=configuration, info={"seed": int(replay["info"]["seed"])}, debug=True)


def replay_prefix(env: Any, replay: dict[str, Any], prefix: int) -> tuple[bool, int | None]:
    first_mismatch = None
    for record in range(1, prefix + 1):
        env.step([replay["steps"][record][seat]["action"] for seat in (0, 1)])
        if first_mismatch is None and any(
            exact_fields(env.steps[-1][seat]) != exact_fields(replay["steps"][record][seat]) for seat in (0, 1)
        ):
            first_mismatch = record
    return first_mismatch is None, first_mismatch


def reconstruct_policy_state(replay: dict[str, Any], seat: int, prefix: int, configuration: Any) -> None:
    learned_main.reset_runtime_state()
    runtime = learned_main._runtime
    for record in range(prefix):
        observation = restored_observation(replay, record, seat)
        runtime.base.agent(observation, configuration)
        runtime._commit_actual(observation, replay["steps"][record + 1][seat]["action"])
    # No Round5 plan was accepted during the observed teacher prefix.  Keep the
    # reconstructed BC history but begin executor contracts at the branch.
    runtime.coordinator.reset()
    runtime.stats["strategy_inference_calls"] = 0
    if runtime.selector is not None:
        runtime.selector.inference_calls = 0


def run_case(row: dict[str, Any], prefix: int, horizon: int) -> dict[str, Any]:
    replay_path = ROOT / str(row["path"]).replace("\\", "/")
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    if sha256(replay_path) != row["sha256"]:
        raise RuntimeError(f"teacher hash mismatch: {replay_path}")
    seat = int(row["seat"])
    opponent = 1 - seat
    env = make_env(replay)
    prefix_exact, mismatch = replay_prefix(env, replay, prefix)
    if not prefix_exact:
        raise RuntimeError(f"prefix mismatch episode={row['episode']} record={mismatch}")
    prefix_hash = canonical_hash([exact_fields(env.steps[-1][value]) for value in (0, 1)])
    teacher_prefix_hash = canonical_hash([exact_fields(replay["steps"][prefix][value]) for value in (0, 1)])
    reconstruct_policy_state(replay, seat, prefix, env.configuration)
    first_difference = None
    focal_actions = []
    animal_product_sales = 0
    for decision in range(prefix, prefix + horizon):
        observation = env.state[seat].observation
        learner_action = learned_main.agent(observation, env.configuration)
        teacher_action = replay["steps"][decision + 1][seat]["action"]
        if first_difference is None and normalize_action(learner_action) != normalize_action(teacher_action):
            first_difference = {
                "decision_step": decision,
                "record": decision + 1,
                "learner_action": learner_action,
                "teacher_action": teacher_action,
            }
        animal_product_sales += sum(
            1 for order in learner_action.get("market", []) if order and order[0] == "SELL" and len(order) > 1 and order[1] in {"EGG", "MILK", "WOOL"}
        )
        focal_actions.append({"decision_step": decision, "action": learner_action})
        actions = [None, None]
        actions[seat] = learner_action
        actions[opponent] = replay["steps"][decision + 1][opponent]["action"]
        env.step(actions)
    end_record = prefix + horizon
    counterfactual = env.toJSON()
    replay_output = OUTPUT / f"episode_{row['episode']}_prefix_{prefix}_horizon_{horizon}.json.gz"
    replay_output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(replay_output, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(counterfactual, stream, ensure_ascii=False, separators=(",", ":"))
    learner_end = counterfactual["steps"][-1][seat]["observation"]
    learner_end["private"] = counterfactual["steps"][-1][seat]["observation"]["private"]
    teacher_end = restored_observation(replay, end_record, seat)
    learner_summary = summarize(learner_end, seat)
    teacher_summary = summarize(teacher_end, seat)
    diagnostics = learned_main.policy_diagnostics()
    trace = learned_main.policy_trace()
    trace_output = OUTPUT / f"episode_{row['episode']}_prefix_{prefix}_horizon_{horizon}.trace.jsonl"
    trace_output.write_text(
        "".join(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n" for value in trace),
        encoding="utf-8",
    )
    failures = [
        value for value in trace
        if value.get("event") in {"primitive_result", "cash_realization_result"} and value.get("status") in {"FAILED", "UNKNOWN"}
    ]
    failure_steps = {int(value["step"]) for value in failures}
    windows = [value for value in trace if any(abs(int(value.get("step", -999)) - step) <= 1 for step in failure_steps)]
    failure_output = OUTPUT / f"episode_{row['episode']}_prefix_{prefix}_horizon_{horizon}.failure_windows.json"
    write_json(failure_output, windows)
    return {
        "episode": int(row["episode"]),
        "teacher_submission": 56216119,
        "source_split": row["split"],
        "seat": seat,
        "seed": int(replay["info"]["seed"]),
        "prefix_steps": prefix,
        "rollout_steps": horizon,
        "prefix_exact_all_states": prefix_exact,
        "first_prefix_mismatch": mismatch,
        "prefix_state_hash": prefix_hash,
        "teacher_prefix_state_hash": teacher_prefix_hash,
        "policy_state_reconstruction": "BC history advanced with observed prefix states and actual teacher actions; Round5 executor begins with no invented accepted plan",
        "post_prefix_opponent_origin": "saved replay action sequence; no private-teacher query on learner states",
        "dagger_claimed": False,
        "first_action_difference": first_difference,
        "learner_end": learner_summary,
        "teacher_end": teacher_summary,
        "delta_self_money": learner_summary["money"] - teacher_summary["money"],
        "learner_opponent_money": int(counterfactual["steps"][-1][opponent]["observation"]["farms"][opponent]["money"]),
        "teacher_opponent_money": int(replay["steps"][end_record][opponent]["observation"]["farms"][opponent]["money"]),
        "animal_product_sales": animal_product_sales,
        "selector_inference_calls": diagnostics["strategy_inference_calls"],
        "silent_fallbacks": diagnostics["silent_fallbacks"],
        "executor": diagnostics["executor"],
        "failure_reasons": dict(Counter(str(value.get("reason") or "MARKET_NET_DELTA_AMBIGUOUS") for value in failures)),
        "trace": str(trace_output.relative_to(ROOT)),
        "trace_sha256": sha256(trace_output),
        "failure_windows": str(failure_output.relative_to(ROOT)),
        "failure_windows_sha256": sha256(failure_output),
        "focal_actions": focal_actions,
        "counterfactual_replay": str(replay_output.relative_to(ROOT)),
        "counterfactual_replay_sha256": sha256(replay_output),
    }


def main() -> None:
    selected = [row for row in json.loads(MANIFEST.read_text(encoding="utf-8"))["selected"] if row["split"] == "train"]
    cases = [(selected[0], 24, 24), (selected[1], 48, 48), (selected[2], 96, 96)]
    results = [run_case(row, prefix, horizon) for row, prefix, horizon in cases]
    output = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scope": "three train/development teacher-prefix counterfactuals; not an unused holdout and not DAgger",
        "teacher_submission": 56216119,
        "teacher_current_rank": "UNKNOWN",
        "teacher_private_version": "UNKNOWN",
        "engine_sha256": sha256(ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"),
        "all_prefixes_exact": all(row["prefix_exact_all_states"] and row["prefix_state_hash"] == row["teacher_prefix_state_hash"] for row in results),
        "results": results,
    }
    write_json(OUTPUT / "TEACHER_PREFIX_RESULTS.json", output)
    print(json.dumps({"all_prefixes_exact": output["all_prefixes_exact"], "cases": [{key: row[key] for key in ("episode", "prefix_steps", "rollout_steps", "delta_self_money", "animal_product_sales", "selector_inference_calls")} for row in results]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
