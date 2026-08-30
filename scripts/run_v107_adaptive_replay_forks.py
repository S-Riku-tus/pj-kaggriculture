"""Run V107 from frozen recent forks against adaptive submitted policies."""

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

from agents.v14 import main as adaptive_v14  # noqa: E402
from agents.v18 import main as adaptive_v18  # noqa: E402
from agents.v107 import main as v107  # noqa: E402
from scripts.run_v102_diagnostic import _mode_summary, _runtime_failures, _trace  # noqa: E402
from scripts.run_v102_replay_forks import (  # noqa: E402
    RECENT,
    _logged_action,
    _manifests,
    _replay_path,
)
from scripts.run_v105_replay_forks import _action_difference  # noqa: E402

V106_EVIDENCE = ROOT / "data/runs/v106_recent_adaptive_replay_forks.json"


def _reset(module: Any) -> None:
    module.v9._MISSION_LAST_STEP = -1
    module.v9._MISSION_PREVIOUS_ACTIONS = []


def _controlled(original: dict[str, Any], seat: int, fork_step: int):
    def policy(obs: Any) -> dict[str, Any]:
        step = int(obs.step)
        return _logged_action(original, step, seat) if step < fork_step else v107.agent(obs)

    return policy


def _adaptive(original: dict[str, Any], seat: int, fork_step: int, module: Any):
    def policy(obs: Any) -> dict[str, Any]:
        step = int(obs.step)
        return _logged_action(original, step, seat) if step < fork_step else module.agent(obs)

    return policy


def _run(
    source: str,
    episode_id: str,
    original: dict[str, Any],
    controlled_seat: int,
    fork_day: int,
    output: Path,
) -> dict[str, Any]:
    opponent = adaptive_v14 if source == "v14_recent_opponent" else adaptive_v18
    _reset(v107)
    _reset(opponent)
    v107.reset_runtime_state()
    v107.ENABLE_V107_RUNTIME_GATE = True
    if opponent is adaptive_v18:
        adaptive_v18.ENABLE_INTRADAY_HERD_GATE = True
    seed = int(original["info"]["seed"])
    fork_step = fork_day * 24
    policies = [
        _adaptive(original, 0, fork_step, opponent),
        _adaptive(original, 1, fork_step, opponent),
    ]
    policies[controlled_seat] = _controlled(original, controlled_seat, fork_step)
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    env.run(policies)
    replay = env.toJSON()
    rewards = [float(value or 0) for value in replay.get("rewards") or (0, 0)]
    trace = _trace(replay, controlled_seat)
    trace["active_steps"] = int(v107.v105._DAILY_ACTIVE_STEPS)
    trace["changed_steps"] = int(v107.v105._DAILY_ACTIVE_STEPS)
    trace["daily_activations"] = int(v107.v105._DAILY_ACTIVATIONS)
    trace["emergency_fallbacks"] = int(v107.v105._DAILY_EMERGENCY_FALLBACKS)
    if not trace["daily_activations"]:
        trace["mean_normalized_change"] = 0.0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    return {
        "source": source,
        "episode_id": episode_id,
        "seed": seed,
        "seat": controlled_seat,
        "fork_day": fork_day,
        "mode": "candidate",
        "adaptive_opponent": "v14" if opponent is adaptive_v14 else "v18-enabled",
        "ours": rewards[controlled_seat],
        "theirs": rewards[1 - controlled_seat],
        "margin": rewards[controlled_seat] - rewards[1 - controlled_seat],
        "statuses": [str(state["status"]) for state in replay["steps"][-1]],
        "runtime_failures": _runtime_failures(replay),
        "trace": trace,
        "replay": str(output.relative_to(ROOT)),
    }


def main() -> None:
    confirmation = json.loads(RECENT.read_text(encoding="utf-8"))
    first_trigger: dict[str, int] = {}
    for record in confirmation["triggered_records"]:
        episode_id = str(record["episode_id"])
        first_trigger[episode_id] = min(
            int(record["day"]), first_trigger.get(episode_id, int(record["day"]))
        )
    manifests = _manifests()
    prior = json.loads(V106_EVIDENCE.read_text(encoding="utf-8"))
    safe_games = [dict(game) for game in prior["games"] if game["mode"] == "safe-core"]
    replay_dir = ROOT / "data/replays/v107_recent_adaptive_replay_forks"
    candidate_games = []
    for episode_id, fork_day in sorted(first_trigger.items()):
        source, manifest = manifests[episode_id]
        original = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        controlled_seat = 1 - int(manifest["submission_seat"])
        candidate_games.append(
            _run(
                source,
                episode_id,
                original,
                controlled_seat,
                fork_day,
                replay_dir / f"candidate_episode_{episode_id}_day_{fork_day}.json",
            )
        )
    games = safe_games + candidate_games
    summary = {
        mode: _mode_summary([game for game in games if game["mode"] == mode])
        for mode in ("safe-core", "candidate")
    }
    paired = []
    for episode_id, fork_day in sorted(first_trigger.items()):
        safe = next(
            game for game in safe_games if game["episode_id"] == episode_id
        )
        candidate = next(
            game for game in candidate_games if game["episode_id"] == episode_id
        )
        safe_replay = json.loads((ROOT / safe["replay"]).read_text(encoding="utf-8"))
        candidate_replay = json.loads((ROOT / candidate["replay"]).read_text(encoding="utf-8"))
        paired.append(
            {
                "source": candidate["source"],
                "episode_id": episode_id,
                "fork_day": fork_day,
                "adaptive_opponent": candidate["adaptive_opponent"],
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
        "format": "kaggriculture-v107-adaptive-replay-forks-v1",
        "entry_source": str(RECENT.relative_to(ROOT)),
        "safe_core_source": str(V106_EVIDENCE.relative_to(ROOT)),
        "episodes": len(first_trigger),
        "fork_semantics": "both seats replay exact logged actions before trigger; both become adaptive thereafter",
        "opponent_semantics": "local source-equivalent submitted policy; mission memory starts cold at fork",
        "purpose": "frozen V107 path/resource diagnostic; not top-policy counterfactual or rating estimate",
        "summary": summary,
        "paired_diagnostics": paired,
        "games": games,
    }
    output = ROOT / "data/runs/v107_recent_adaptive_replay_forks.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "paired": paired}, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
