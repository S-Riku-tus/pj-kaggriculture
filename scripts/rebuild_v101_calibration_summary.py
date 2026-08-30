"""Replace a runtime-contaminated V101 replay and rebuild its diagnostics.

The original calibration batch contains one local TIMEOUT after the host was
paused for longer than Kaggle's wall-clock allowance.  This script keeps the
other deterministic seed/seat replays, substitutes the clean rerun, and
recomputes the aggregate without silently treating a final DONE as success.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v101 import main as v101  # noqa: E402
from scripts.run_v101_diagnostic import _mode_summary, _trace  # noqa: E402

ORIGINAL = ROOT / "data/runs/v101_calibration_20261101.json"
CORRECTED_REPLAY = (
    ROOT
    / "data/replays/v101_calibration_corrected/candidate_seed_20261102_seat_0.json"
)
OUTPUT = ROOT / "data/runs/v101_calibration_corrected.json"


def _runtime_failures(replay: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "step": step,
            "player": player,
            "status": str(state.get("status")),
            "remaining_overage_time": (state.get("observation") or {}).get(
                "remainingOverageTime"
            ),
        }
        for step, states in enumerate(replay.get("steps") or [])
        for player, state in enumerate(states)
        if state.get("status") not in {"ACTIVE", "DONE"}
    ]


def main() -> None:
    payload = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    games = payload["games"]
    clean_replay = json.loads(CORRECTED_REPLAY.read_text(encoding="utf-8"))
    final = clean_replay["steps"][-1]
    rewards = [float(value or 0) for value in clean_replay["rewards"]]

    v101.ENABLE_EARLY_OPTIONALITY = True
    replacement = {
        "seed": int(clean_replay["info"]["seed"]),
        "resolved_seed": int(clean_replay["info"]["seed"]),
        "seat": 0,
        "mode": "candidate",
        "ours": rewards[0],
        "theirs": rewards[1],
        "margin": rewards[0] - rewards[1],
        "statuses": [str(state["status"]) for state in final],
        "runtime_failures": _runtime_failures(clean_replay),
        "trace": _trace(clean_replay, 0),
        "replay": str(CORRECTED_REPLAY.relative_to(ROOT)),
    }
    index = next(
        index
        for index, game in enumerate(games)
        if game["seed"] == 20261102 and game["seat"] == 0 and game["mode"] == "candidate"
    )
    games[index] = replacement

    for game in games:
        if "runtime_failures" in game:
            continue
        replay = json.loads((ROOT / game["replay"]).read_text(encoding="utf-8"))
        game["resolved_seed"] = int(replay["info"]["seed"])
        game["runtime_failures"] = _runtime_failures(replay)

    payload["correction"] = {
        "reason": "host-pause wall-clock TIMEOUT contamination",
        "replaced": "candidate seed=20261102 seat=0",
        "original_result_retained_at": str(ORIGINAL.relative_to(ROOT)),
        "clean_replay": str(CORRECTED_REPLAY.relative_to(ROOT)),
    }
    payload["summary"] = {
        mode: _mode_summary([game for game in games if game["mode"] == mode])
        for mode in ("safe-core", "candidate")
    }
    paired = []
    for seed in sorted({int(game["seed"]) for game in games}):
        for seat in (0, 1):
            safe = next(
                game
                for game in games
                if game["seed"] == seed and game["seat"] == seat and game["mode"] == "safe-core"
            )
            candidate = next(
                game
                for game in games
                if game["seed"] == seed and game["seat"] == seat and game["mode"] == "candidate"
            )
            paired.append(
                {
                    "seed": seed,
                    "seat": seat,
                    "reward_delta_context": candidate["ours"] - safe["ours"],
                    "margin_delta_context": candidate["margin"] - safe["margin"],
                    "day15_strawberry_delta": (
                        candidate["trace"]["checkpoints"]["15"]["crops"]["STRAWBERRY"]
                        - safe["trace"]["checkpoints"]["15"]["crops"]["STRAWBERRY"]
                    ),
                    "day20_productive_delta": (
                        candidate["trace"]["checkpoints"]["20"]["productive"]
                        - safe["trace"]["checkpoints"]["20"]["productive"]
                    ),
                    "changed_steps": candidate["trace"]["changed_steps"],
                }
            )
    payload["paired_diagnostics"] = paired
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": payload["summary"], "paired": paired}, ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
