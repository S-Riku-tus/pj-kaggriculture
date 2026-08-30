"""Fork V11/V102 from recent replay states where the V102 gate fires.

Both agents replay the exact logged actions up to the frozen gate's first
trigger.  Thereafter the evaluated seat switches to either V11-safe V102 or
enabled V102 while the other seat remains an open-loop logged-action driver.
This is a deterministic safety/path diagnostic, not a counterfactual rating
estimate because the scripted opponent cannot adapt after divergence.
"""

from __future__ import annotations

import copy
import csv
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kaggle_environments import make  # noqa: E402

from agents.v102 import main as v102  # noqa: E402
from scripts.run_v102_diagnostic import _mode_summary, _runtime_failures, _trace  # noqa: E402

RECENT = ROOT / "data/analysis/v102_recent_opponent_confirmation.json"
SOURCES = {
    "v14_recent_opponent": ROOT / "data/submissions/rank1_v14_submission_55815097",
    "v18_recent_opponent": ROOT
    / "data/submissions/rank2_v18_intraday_gate_submission_55815102",
}
PASS = {"farmer": ["PASS"], "hands": [], "market": []}


def _manifests() -> dict[str, tuple[str, dict[str, str]]]:
    result: dict[str, tuple[str, dict[str, str]]] = {}
    for source, directory in SOURCES.items():
        with (directory / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                result[str(row["episode_id"])] = (source, row)
    return result


def _replay_path(row: dict[str, str]) -> Path:
    direct = ROOT / row["replay_path"]
    return direct if direct.is_file() else ROOT / "data" / row["replay_path"]


def _logged_action(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    action_step = min(step + 1, len(replay["steps"]) - 1)
    action = replay["steps"][action_step][seat].get("action")
    return copy.deepcopy(action) if isinstance(action, dict) else copy.deepcopy(PASS)


def _scripted(replay: dict[str, Any], seat: int) -> Callable[[Any], dict[str, Any]]:
    return lambda obs: _logged_action(replay, int(obs.step), seat)


def _forked(
    replay: dict[str, Any], seat: int, fork_step: int
) -> Callable[[Any], dict[str, Any]]:
    def policy(obs: Any) -> dict[str, Any]:
        step = int(obs.step)
        return _logged_action(replay, step, seat) if step < fork_step else v102.agent(obs)

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
    v102.v9._MISSION_LAST_STEP = -1
    v102.v9._MISSION_PREVIOUS_ACTIONS = []
    v102.ENABLE_RECOVERY_META_GATE = enabled
    seed = int(original["info"]["seed"])
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    policies = [_scripted(original, 0), _scripted(original, 1)]
    policies[controlled_seat] = _forked(original, controlled_seat, fork_day * 24)
    env.run(policies)
    replay = env.toJSON()
    rewards = [float(value or 0) for value in replay.get("rewards") or (0, 0)]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    final = replay["steps"][-1]
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
        "statuses": [str(state["status"]) for state in final],
        "runtime_failures": _runtime_failures(replay),
        "trace": _trace(replay, controlled_seat),
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
    replay_dir = ROOT / "data/replays/v102_recent_replay_forks"
    games: list[dict[str, Any]] = []
    original_rewards: dict[str, list[float]] = {}
    for episode_id, fork_day in sorted(first_trigger.items()):
        source, manifest = manifests[episode_id]
        original = json.loads(_replay_path(manifest).read_text(encoding="utf-8"))
        original_rewards[episode_id] = [float(value or 0) for value in original["rewards"]]
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
        paired.append(
            {
                "source": candidate["source"],
                "episode_id": episode_id,
                "fork_day": fork_day,
                "original_rewards": original_rewards[episode_id],
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
                "changed_steps": candidate["trace"]["changed_steps"],
                "candidate_runtime_failures": candidate["runtime_failures"],
            }
        )
    result = {
        "created_at": datetime.now().astimezone().isoformat(),
        "format": "kaggriculture-v102-recent-replay-forks-v1",
        "selection_source": str(RECENT.relative_to(ROOT)),
        "episodes": len(first_trigger),
        "fork_semantics": "exact logged actions before first trigger; evaluated seat policy thereafter",
        "opponent_semantics": "open-loop logged actions throughout; may be invalid after divergence",
        "purpose": "targeted path and resource diagnostic, not counterfactual score or rating",
        "summary": summary,
        "paired_diagnostics": paired,
        "games": games,
    }
    output = ROOT / "data/runs/v102_recent_replay_forks.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "paired": paired}, ensure_ascii=False, indent=2))
    print(f"result: {output}")
    print(f"replays: {replay_dir}")


if __name__ == "__main__":
    main()
