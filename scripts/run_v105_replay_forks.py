"""Run V105 on frozen forks, reusing V104's action-identical safe replays."""

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

from agents.v105 import main as v105  # noqa: E402
from scripts.run_v102_diagnostic import (  # noqa: E402
    _mode_summary,
    _runtime_failures,
    _trace,
)
from scripts.run_v102_replay_forks import (  # noqa: E402
    _logged_action,
    _manifests,
    _replay_path,
    _scripted,
)

SAFE_RUN = ROOT / "data/runs/v104_recent_replay_forks.json"


def _reset() -> None:
    v105.v9._MISSION_LAST_STEP = -1
    v105.v9._MISSION_PREVIOUS_ACTIONS = []
    v105.reset_runtime_state()


def _forked(original: dict[str, Any], seat: int, fork_step: int):
    def policy(obs: Any) -> dict[str, Any]:
        step = int(obs.step)
        return _logged_action(original, step, seat) if step < fork_step else v105.agent(obs)

    return policy


def _run(
    source: str,
    episode_id: str,
    original: dict[str, Any],
    controlled_seat: int,
    fork_day: int,
    output: Path,
) -> dict[str, Any]:
    _reset()
    v105.ENABLE_DAILY_RECOVERY = True
    seed = int(original["info"]["seed"])
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    policies = [_scripted(original, 0), _scripted(original, 1)]
    policies[controlled_seat] = _forked(original, controlled_seat, fork_day * 24)
    env.run(policies)
    replay = env.toJSON()
    rewards = [float(value or 0) for value in replay.get("rewards") or (0, 0)]
    trace = _trace(replay, controlled_seat)
    trace["active_steps"] = int(v105._DAILY_ACTIVE_STEPS)
    trace["changed_steps"] = int(v105._DAILY_ACTIVE_STEPS)
    trace["daily_activations"] = int(v105._DAILY_ACTIVATIONS)
    trace["emergency_fallbacks"] = int(v105._DAILY_EMERGENCY_FALLBACKS)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    return {
        "source": source,
        "episode_id": episode_id,
        "seed": seed,
        "seat": controlled_seat,
        "fork_day": fork_day,
        "mode": "candidate",
        "ours": rewards[controlled_seat],
        "theirs": rewards[1 - controlled_seat],
        "margin": rewards[controlled_seat] - rewards[1 - controlled_seat],
        "statuses": [str(state["status"]) for state in replay["steps"][-1]],
        "runtime_failures": _runtime_failures(replay),
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
    safe_payload = json.loads(SAFE_RUN.read_text(encoding="utf-8"))
    safe_games = [game for game in safe_payload["games"] if game["mode"] == "safe-core"]
    manifests = _manifests()
    replay_dir = ROOT / "data/replays/v105_recent_replay_forks"
    candidates = []
    for safe in safe_games:
        source, manifest = manifests[str(safe["episode_id"])]
        original = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        candidates.append(
            _run(
                source,
                str(safe["episode_id"]),
                original,
                int(safe["seat"]),
                int(safe["fork_day"]),
                replay_dir
                / f"candidate_episode_{safe['episode_id']}_day_{safe['fork_day']}.json",
            )
        )
    summary = {
        "safe-core": _mode_summary(safe_games),
        "candidate": _mode_summary(candidates),
    }
    paired = []
    for safe, candidate in zip(safe_games, candidates, strict=True):
        safe_replay = json.loads((ROOT / safe["replay"]).read_text(encoding="utf-8"))
        candidate_replay = json.loads((ROOT / candidate["replay"]).read_text(encoding="utf-8"))
        paired.append(
            {
                "source": candidate["source"],
                "episode_id": candidate["episode_id"],
                "fork_day": candidate["fork_day"],
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
                "daily_activations": candidate["trace"]["daily_activations"],
                "active_steps": candidate["trace"]["active_steps"],
                "emergency_fallbacks": candidate["trace"]["emergency_fallbacks"],
                "action_differences": _action_difference(
                    safe_replay, candidate_replay, candidate["seat"]
                ),
                "candidate_runtime_failures": candidate["runtime_failures"],
            }
        )
    result = {
        "created_at": datetime.now().astimezone().isoformat(),
        "format": "kaggriculture-v105-recent-replay-forks-v1",
        "safe_run_reused": str(SAFE_RUN.relative_to(ROOT)),
        "episodes": len(candidates),
        "fork_semantics": "exact logged actions before first trigger; evaluated seat policy thereafter",
        "opponent_semantics": "open-loop logged actions throughout; invalid as causal value after divergence",
        "purpose": "day-goal action-effect, path, and resource diagnostic; not rating estimation",
        "summary": summary,
        "paired_diagnostics": paired,
        "games": [*safe_games, *candidates],
    }
    output = ROOT / "data/runs/v105_recent_replay_forks.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "paired": paired}, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
