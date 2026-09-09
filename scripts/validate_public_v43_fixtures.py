"""Reproducible smoke probe for the hash-pinned public V43 route fixtures."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from kaggle_environments import make

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = (
    "public_v43_forced_default",
    "public_v43_forced_yarn_first",
    "public_v43_forced_yarn_second",
)
CHECKPOINTS = (24, 100, 200, 400, 719)


def _load(path: Path):
    name = f"_public_v43_validation_{path.parent.name}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import agent: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "reset_runtime_state"):
        module.reset_runtime_state()
    return module


def _canonical_action(action: Any) -> bytes:
    action = action if isinstance(action, dict) else {}
    payload = {
        "farmer": list(action.get("farmer") or ["PASS"]),
        "hands": [list(row or ["PASS"]) for row in (action.get("hands") or [])],
        "market": [list(row) for row in (action.get("market") or [])],
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _prefix_hash(actions: list[Any], count: int) -> str:
    digest = hashlib.sha256()
    for action in actions[:count]:
        digest.update(_canonical_action(action))
        digest.update(b"\n")
    return digest.hexdigest()[:20]


def _run(task: tuple[str, int, int]) -> dict[str, Any]:
    fixture, seed, champion_seat = task
    champion = _load(ROOT / "agents" / "v111" / "main.py")
    opponent_main = (
        ROOT / "artifacts" / "opponent_pool" / "sources" / fixture / "main.py"
    )
    opponent = _load(opponent_main)
    actions: list[Any] = []

    def champion_agent(obs, configuration=None):
        return champion.agent(obs, configuration)

    def opponent_agent(obs, configuration=None):
        action = opponent.agent(obs, configuration)
        actions.append(action)
        return action

    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": seed},
        debug=True,
    )
    ordered = (
        [champion_agent, opponent_agent]
        if champion_seat == 0
        else [opponent_agent, champion_agent]
    )
    env.run(ordered)
    final = env.steps[-1]
    rewards = [float(state.reward or 0.0) for state in final]
    checkpoint_actions = {
        str(turn): actions[min(turn, len(actions) - 1)] for turn in CHECKPOINTS
    }
    return {
        "fixture": fixture,
        "fixture_main_sha256": hashlib.sha256(opponent_main.read_bytes()).hexdigest(),
        "shared_ancestry_id": opponent.FIXTURE_METADATA["shared_ancestry_id"],
        "source_sha256": opponent.FIXTURE_METADATA["source_sha256"],
        "seed": seed,
        "champion_seat": champion_seat,
        "statuses": [str(state.status) for state in final],
        "rewards": rewards,
        "champion_margin": rewards[champion_seat] - rewards[1 - champion_seat],
        "decision_count": len(actions),
        "last_decision_step": len(actions) - 1,
        "fixture_fallback_count": int(
            opponent.FIXTURE_TELEMETRY.get("fallback_count", 0)
        ),
        "checkpoint_prefix_hashes": {
            str(turn): _prefix_hash(actions, min(turn, len(actions)))
            for turn in CHECKPOINTS
        },
        "checkpoint_actions": checkpoint_actions,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=29114343)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    tasks = [
        (fixture, int(args.seed), seat) for fixture in FIXTURES for seat in (0, 1)
    ]
    with ProcessPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
        rows = list(executor.map(_run, tasks))
    if args.compact:
        rows = [
            {
                key: row[key]
                for key in (
                    "fixture",
                    "fixture_main_sha256",
                    "shared_ancestry_id",
                    "source_sha256",
                    "seed",
                    "champion_seat",
                    "statuses",
                    "rewards",
                    "champion_margin",
                    "decision_count",
                    "last_decision_step",
                    "fixture_fallback_count",
                    "checkpoint_prefix_hashes",
                )
            }
            for row in rows
        ]
    print(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
