"""Smoke an extracted multi-file Kaggriculture submission from its own path."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

from kaggle_environments import make


def _import_main(path: Path):
    spec = importlib.util.spec_from_file_location("_standalone_submission_smoke", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import submission: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_one(main_path: Path, seed: int, seat: int) -> dict[str, Any]:
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": seed},
        debug=True,
    )
    agents = [str(main_path), "starter"] if seat == 0 else ["starter", str(main_path)]
    env.run(agents)
    final = env.steps[-1]
    rewards = [float(state.reward or 0) for state in final]
    return {
        "seat": seat,
        "steps": len(env.steps),
        "statuses": [state.status for state in final],
        "ours": rewards[seat],
        "opponent": rewards[1 - seat],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", type=Path, help="extracted directory or main.py")
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    main_path = args.submission / "main.py" if args.submission.is_dir() else args.submission
    main_path = main_path.resolve()
    module = _import_main(main_path)
    route_core = module
    wrapper_depth = 0
    while not hasattr(route_core, "safe_rule") and hasattr(route_core, "base"):
        route_core = route_core.base
        wrapper_depth += 1
    if not hasattr(route_core, "safe_rule") or not hasattr(route_core, "public_v43"):
        raise RuntimeError("could not locate the packaged V109 route core")
    fallback_modules = (
        route_core.safe_rule,
        route_core.safe_rule.v10,
        route_core.safe_rule.v9,
        route_core.safe_rule.v8,
        route_core.safe_rule.v7,
        route_core.safe_rule.v6,
        route_core.safe_rule.v5,
        route_core.safe_rule.v4,
        route_core.safe_rule.v3,
        route_core.safe_rule.base,
    )
    checks = {
        "module_dir_is_submission": Path(
            getattr(module, "MODULE_DIR", getattr(module, "HERE", main_path.parent))
        ).resolve() == main_path.parent,
        "wrapper_depth": wrapper_depth,
        "all_runtime_modules_are_packaged": all(
            Path(child.__file__).resolve().parent == main_path.parent for child in fallback_modules
        ),
        "feature_schema_is_packaged": (
            Path(route_core.safe_rule.v3.schema.__file__).resolve().parent == main_path.parent
        ),
        "route_length": len(route_core.public_v43._V43_ROUTES["default"]),
        "fallback_top3_model_disabled": route_core.safe_rule.v3.MODEL is None,
        "fallback_future_model_disabled": route_core.safe_rule.v8.POLICY_MODEL is None,
        "fallback_action_model_disabled": route_core.safe_rule.v9.DECISION_MODEL is None,
        "fallback_imitation_opening_disabled": route_core.safe_rule.v8.EXPERT_OPENING == {},
        "strategy_model_packaged": (
            not hasattr(module, "MODEL") or (main_path.parent / "strategy_model.json").is_file()
        ),
    }
    games = [run_one(main_path, args.seed, seat) for seat in (0, 1)]
    payload = {
        "submission": str(main_path.parent),
        "seed": args.seed,
        "checks": checks,
        "games": games,
        "passed": (
            all(
                value is True
                for key, value in checks.items()
                if key not in {"route_length", "wrapper_depth"}
            )
            and checks["route_length"] == 719
            and all(game["steps"] == 720 and game["statuses"] == ["DONE", "DONE"] for game in games)
        ),
    }
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
