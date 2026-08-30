"""Run V103's bounded commitment from the eight frozen recent replay forks."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kaggle_environments import make  # noqa: E402

from agents.v103 import main as v103  # noqa: E402
from scripts.run_v102_diagnostic import (  # noqa: E402
    _mode_summary,
    _runtime_failures,
    _trace,
)
from scripts.run_v102_replay_forks import (  # noqa: E402
    RECENT,
    _logged_action,
    _manifests,
    _replay_path,
    _scripted,
)


def _reset() -> None:
    v103.v9._MISSION_LAST_STEP = -1
    v103.v9._MISSION_PREVIOUS_ACTIONS = []
    v103._COMMIT_LAST_STEP = -1
    v103._COMMIT_ACTIVATIONS = 0
    v103._COMMIT_CONTINUATION_STEPS = 0
    v103._reset_commitment()


def _forked(original: dict[str, Any], seat: int, fork_step: int):
    def policy(obs: Any) -> dict[str, Any]:
        step = int(obs.step)
        return _logged_action(original, step, seat) if step < fork_step else v103.agent(obs)

    return policy


def _run(
    source: str,
    episode_id: str,
    original: dict[str, Any],
    controlled_seat: int,
    fork_day: int,
    enabled: bool,
    output: Path,
) -> dict[str, Any]:
    _reset()
    v103.ENABLE_RECOVERY_COMMITMENT = enabled
    seed = int(original["info"]["seed"])
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    policies = [_scripted(original, 0), _scripted(original, 1)]
    policies[controlled_seat] = _forked(original, controlled_seat, fork_day * 24)
    env.run(policies)
    replay = env.toJSON()
    rewards = [float(value or 0) for value in replay.get("rewards") or (0, 0)]
    failures = _runtime_failures(replay)
    activations = int(v103._COMMIT_ACTIVATIONS)
    continuation_steps = int(v103._COMMIT_CONTINUATION_STEPS)
    trace = _trace(replay, controlled_seat)
    # _trace also sees V102's diagnostic-only gate while V103 is disabled.
    # Do not count that observation as a V103 strategic intervention.
    if not enabled:
        trace["mean_normalized_change"] = 0.0
    trace["active_steps"] = activations + continuation_steps
    trace["changed_steps"] = activations + continuation_steps
    trace["commitment_activations"] = activations
    trace["continuation_steps"] = continuation_steps
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    return {
        "source": source,
        "episode_id": episode_id,
        "seed": seed,
        "seat": controlled_seat,
        "fork_day": fork_day,
        "mode": "candidate" if enabled else "safe-core",
        "ours": rewards[controlled_seat],
        "theirs": rewards[1 - controlled_seat],
        "margin": rewards[controlled_seat] - rewards[1 - controlled_seat],
        "statuses": [str(state["status"]) for state in replay["steps"][-1]],
        "runtime_failures": failures,
        "trace": trace,
        "replay": str(output.relative_to(ROOT)),
    }


def _action_difference(safe: dict[str, Any], candidate: dict[str, Any], seat: int) -> int:
    return sum(
        safe_states[seat].get("action") != candidate_states[seat].get("action")
        for safe_states, candidate_states in zip(
            safe.get("steps") or [], candidate.get("steps") or [], strict=True
        )
    )


def main() -> None:
    confirmation = json.loads(RECENT.read_text(encoding="utf-8"))
    first_trigger: dict[str, int] = {}
    for record in confirmation["triggered_records"]:
        episode_id = str(record["episode_id"])
        first_trigger[episode_id] = min(
            int(record["day"]), first_trigger.get(episode_id, int(record["day"]))
        )
    manifests = _manifests()
    replay_dir = ROOT / "data/replays/v103_recent_replay_forks"
    games: list[dict[str, Any]] = []
    for episode_id, fork_day in sorted(first_trigger.items()):
        source, manifest = manifests[episode_id]
        original = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        controlled_seat = 1 - int(manifest["submission_seat"])
        for enabled in (False, True):
            games.append(
                _run(
                    source,
                    episode_id,
                    original,
                    controlled_seat,
                    fork_day,
                    enabled,
                    replay_dir
                    / f"{'candidate' if enabled else 'safe'}_episode_{episode_id}_day_{fork_day}.json",
                )
            )
    summary = {
        mode: _mode_summary([game for game in games if game["mode"] == mode])
        for mode in ("safe-core", "candidate")
    }
    paired = []
    for episode_id, fork_day in sorted(first_trigger.items()):
        safe = next(
            game for game in games if game["episode_id"] == episode_id and game["mode"] == "safe-core"
        )
        candidate = next(
            game for game in games if game["episode_id"] == episode_id and game["mode"] == "candidate"
        )
        safe_replay = json.loads((ROOT / safe["replay"]).read_text(encoding="utf-8"))
        candidate_replay = json.loads((ROOT / candidate["replay"]).read_text(encoding="utf-8"))
        paired.append(
            {
                "source": candidate["source"],
                "episode_id": episode_id,
                "fork_day": fork_day,
                "reward_delta_context": candidate["ours"] - safe["ours"],
                "margin_delta_context": candidate["margin"] - safe["margin"],
                "day15_productive_delta": (
                    candidate["trace"]["checkpoints"]["15"]["productive"]
                    - safe["trace"]["checkpoints"]["15"]["productive"]
                ),
                "day20_productive_delta": (
                    candidate["trace"]["checkpoints"]["20"]["productive"]
                    - safe["trace"]["checkpoints"]["20"]["productive"]
                ),
                "commitment_activations": candidate["trace"]["commitment_activations"],
                "continuation_steps": candidate["trace"]["continuation_steps"],
                "action_differences": _action_difference(
                    safe_replay, candidate_replay, candidate["seat"]
                ),
                "candidate_runtime_failures": candidate["runtime_failures"],
            }
        )
    result = {
        "created_at": datetime.now().astimezone().isoformat(),
        "format": "kaggriculture-v103-recent-replay-forks-v1",
        "entry_selection_source": str(RECENT.relative_to(ROOT)),
        "episodes": len(first_trigger),
        "fork_semantics": "exact logged actions before first trigger; evaluated seat policy thereafter",
        "opponent_semantics": "open-loop logged actions throughout; may be invalid after divergence",
        "purpose": "bounded goal-commitment path and resource diagnostic, not rating estimation",
        "summary": summary,
        "paired_diagnostics": paired,
        "games": games,
    }
    output = ROOT / "data/runs/v103_recent_replay_forks.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "paired": paired}, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
