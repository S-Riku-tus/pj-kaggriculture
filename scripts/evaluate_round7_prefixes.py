"""Multiple teacher-prefix diagnostics for the selected Round7 archive."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import shutil
import sys
import tarfile
import tempfile
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_round6_imitation import _selected_teacher_rows, restore_observation  # noqa: E402

ARCHIVE = ROOT / "artifacts/submissions/learning_round7_20260922_arm_b_plan_v3.tar.gz"
OUTPUT = ROOT / "experiments/learning_round7_20260922/prefix_diagnostics_arm_b_plan_v3"
CASES = (
    (0, 48, 24),
    (1, 192, 48),
    (2, 384, 96),
    (4, 96, 192),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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


def load_wrapper(path: Path):
    for name in ("policy", "runtime", "common", "model_compat", "round7_prefix_wrapper"):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location("round7_prefix_wrapper", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def make_env(replay: Mapping[str, Any]):
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


def warm_observation_history(module: Any, replay: Mapping[str, Any], seat: int, prefix: int) -> None:
    runtime = sys.modules.get("runtime")
    policy = sys.modules["policy"]
    if runtime is not None and hasattr(runtime, "reset_runtime_state"):
        runtime.reset_runtime_state()
    else:
        policy.reset_runtime_state()
    for decision in range(prefix):
        # Only observations available before the branch are supplied.  Emitted
        # actions are discarded because the prefix is the saved teacher path.
        module.agent(restore_observation(replay["steps"][decision], seat, decision), {})


def summarize(observation: Mapping[str, Any], seat: int) -> dict[str, Any]:
    farm = observation["farms"][seat]
    private = observation["private"]
    animals = Counter()
    crops = Counter()
    yield_units = 0
    for row in farm["tiles"]:
        for tile in row:
            if not isinstance(tile, Mapping):
                continue
            if tile.get("animal"):
                animals[str(tile["animal"])] += 1
                yield_units += int(tile.get("yield_units", 0))
            if tile.get("kind") == "PLANT":
                crops[str(tile.get("crop"))] += 1
    return {
        "money": float(farm["money"]),
        "land_quadrants": len(farm.get("unlocked_quadrants", [])),
        "shed": dict(private["shed"]),
        "animals": dict(animals),
        "animal_yield_units": yield_units,
        "crops": dict(crops),
    }


def run_case(module: Any, replay: dict[str, Any], row: Mapping[str, Any], prefix: int, horizon: int) -> dict[str, Any]:
    seat = int(row["seat"])
    opponent = 1 - seat
    env = make_env(replay)
    mismatch = replay_prefix(env, replay, prefix)
    if mismatch is not None:
        return {"episode_id": int(row["episode_id"]), "prefix": prefix, "horizon": horizon, "mismatch": mismatch}
    prefix_hash = canonical_hash([exact_fields(env.steps[-1][value]) for value in (0, 1)])
    teacher_hash = canonical_hash([exact_fields(replay["steps"][prefix][value]) for value in (0, 1)])
    warm_observation_history(module, replay, seat, prefix)
    first_difference = None
    for decision in range(prefix, prefix + horizon):
        learner_action = module.agent(env.state[seat].observation, env.configuration)
        teacher_action = replay["steps"][decision + 1][seat]["action"]
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
    end_record = prefix + horizon
    learner = summarize(counterfactual["steps"][-1][seat]["observation"], seat)
    teacher = summarize(restore_observation(replay["steps"][end_record], seat, end_record), seat)
    replay_path = OUTPUT / f"episode_{row['episode_id']}_p{prefix}_h{horizon}.json.gz"
    with gzip.open(replay_path, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(counterfactual, stream, ensure_ascii=False, separators=(",", ":"))
    return {
        "episode_id": int(row["episode_id"]),
        "seat": seat,
        "seed": int(replay["info"]["seed"]),
        "prefix": prefix,
        "horizon": horizon,
        "prefix_exact": prefix_hash == teacher_hash,
        "prefix_state_sha256": prefix_hash,
        "teacher_prefix_state_sha256": teacher_hash,
        "warmup": "candidate called on observations 0..prefix-1 only; emitted warmup actions discarded",
        "warmup_reachability_limit": (
            "candidate internal state is observation-warmed on a teacher trajectory and is not claimed reachable "
            "under the candidate's discarded warmup actions"
        ),
        "opponent_after_branch": "fixed saved action tape; non-reactive",
        "dagger_claimed": False,
        "first_action_difference": first_difference,
        "learner_end": learner,
        "teacher_end": teacher,
        "delta_self_money": learner["money"] - teacher["money"],
        "statuses": [str(value["status"]) for value in counterfactual["steps"][-1]],
        "counterfactual_replay": str(replay_path.relative_to(ROOT)),
        "counterfactual_replay_sha256": sha256(replay_path),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    temp_parent = ROOT.parent / ".round7_tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    extracted = Path(tempfile.mkdtemp(prefix="round7_prefix_", dir=temp_parent))
    try:
        with tarfile.open(ARCHIVE, "r:gz") as stream:
            stream.extractall(extracted, filter="data")
        module = load_wrapper(extracted / "main.py")
        selected = _selected_teacher_rows()
        results = []
        for case_number, (row_index, prefix, horizon) in enumerate(CASES, 1):
            row = selected[row_index]
            source_path = ROOT / row["path"]
            if sha256(source_path) != row["sha256"]:
                raise RuntimeError(source_path)
            replay = json.loads(source_path.read_text(encoding="utf-8"))
            results.append(run_case(module, replay, row, prefix, horizon))
            print(f"prefix case {case_number}/{len(CASES)} episode={row['episode_id']}", flush=True)
        payload = {
            "created_at_utc": datetime.now(UTC).isoformat(),
            "archive": str(ARCHIVE.relative_to(ROOT)),
            "archive_sha256": sha256(ARCHIVE),
            "source_split": "old test, now diagnostic_development",
            "independent_cases": len(results),
            "same_episode_multi_horizon_claimed": False,
            "reactive_opponent_claimed": False,
            "sealed_seeds_opened": False,
            "all_prefixes_exact": all(result.get("prefix_exact", False) for result in results),
            "results": results,
        }
        (OUTPUT / "summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        shutil.rmtree(extracted)


if __name__ == "__main__":
    main()
