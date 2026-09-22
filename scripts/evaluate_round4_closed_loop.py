"""Run the fixed Round4 learned-vs-rule local closed-loop protocol.

This command never submits to Kaggle.  It consumes the protocol written before
results and records both seats as one family/seed cluster.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import inspect
import json
import random
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPERIMENT = ROOT / "experiments/learning_round4_20260921"
PROTOCOL = EXPERIMENT / "CLOSED_LOOP_PROTOCOL.json"
OUTPUT = EXPERIMENT / "closed_loop"
ARMS = {
    "round4_learned": ROOT / "agents/learning_round4_20260921/learned_main.py",
    "round4_rule": ROOT / "agents/learning_round4_20260921/rule_main.py",
}
OPPONENTS = {
    "qeinstein_moev2": ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py",
    "smart_farm": ROOT / "experiments/research_20260918_v120/acquisition/smart_farm/decoded_main_1.py",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_module(path: Path, label: str) -> Any:
    generic = ("common", "learning_common", "market")
    cached = {name: sys.modules.pop(name) for name in generic if name in sys.modules}
    parent = str(path.parent)
    sys.path.insert(0, parent)
    try:
        spec = importlib.util.spec_from_file_location(f"_r4_{label}_{uuid.uuid4().hex}", path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if callable(getattr(module, "reset_runtime_state", None)):
            module.reset_runtime_state()
        return module
    finally:
        if sys.path and sys.path[0] == parent:
            sys.path.pop(0)
        for name in generic:
            sys.modules.pop(name, None)
        sys.modules.update(cached)


def _call(function: Any, observation: Any, configuration: Any) -> Any:
    try:
        parameters = list(inspect.signature(function).parameters.values())
        accepts_two = any(value.kind in {value.VAR_POSITIONAL, value.VAR_KEYWORD} for value in parameters)
        accepts_two = accepts_two or len(parameters) >= 2
    except (TypeError, ValueError):
        accepts_two = True
    return function(observation, configuration) if accepts_two else function(observation)


def _run_one(arm: str, condition: Mapping[str, Any], seat: int) -> dict[str, Any]:
    from kaggle_environments import make

    seed = int(condition["seed"])
    family = str(condition["family"])
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed % (2**32 - 1))
    except ImportError:
        pass
    focal_module = _load_module(ARMS[arm], f"{arm}_focal")
    opponent_module = _load_module(OPPONENTS[family], f"{family}_opponent")
    timings: list[float] = []

    def focal(observation: Any, configuration: Any = None) -> Any:
        started = time.perf_counter()
        try:
            return _call(focal_module.agent, observation, configuration)
        finally:
            timings.append(time.perf_counter() - started)

    def opponent(observation: Any, configuration: Any = None) -> Any:
        return _call(opponent_module.agent, observation, configuration)

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    env.run([focal, opponent] if seat == 0 else [opponent, focal])
    replay = env.toJSON()
    final = replay["steps"][-1]
    rewards = [float(row.get("reward") or 0.0) for row in final]
    statuses = [str(row.get("status")) for row in final]
    replay_path = OUTPUT / "replays" / arm / family / f"seed_{seed}_seat_{seat}.json.gz"
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(replay_path, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))
    diagnostics = focal_module.policy_diagnostics()
    trace = focal_module.policy_trace()
    our_money, opponent_money = rewards[seat], rewards[1 - seat]
    return {
        "arm": arm,
        "scope": condition["scope"],
        "family": family,
        "seed": seed,
        "seat": seat,
        "self_money": our_money,
        "opponent_money": opponent_money,
        "margin": our_money - opponent_money,
        "result": "WIN" if our_money > opponent_money else "DRAW" if our_money == opponent_money else "LOSS",
        "terminal_statuses": statuses,
        "stored_states": len(replay["steps"]),
        "mean_call_seconds": mean(timings),
        "max_call_seconds": max(timings),
        "diagnostics": diagnostics,
        "first_trace_events": trace[:30],
        "trace_event_count": len(trace),
        "replay": str(replay_path.relative_to(ROOT)),
        "replay_sha256": _sha256(replay_path),
    }


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if not protocol.get("fixed_before_results"):
        raise ValueError("protocol was not fixed before results")
    if list(protocol["arms"]) != list(ARMS):
        raise ValueError("protocol arms differ from runner")
    for path in [*ARMS.values(), *OPPONENTS.values()]:
        if not path.is_file():
            raise FileNotFoundError(path)

    rows: list[dict[str, Any]] = []
    total = len(ARMS) * sum(len(row["seats"]) for row in protocol["conditions"])
    index = 0
    for arm in ARMS:
        for condition in protocol["conditions"]:
            for seat in condition["seats"]:
                index += 1
                row = _run_one(arm, condition, int(seat))
                rows.append(row)
                print(f"{index}/{total} {arm} {row['family']} {row['seed']} seat{seat}", flush=True)

    lookup = {(row["arm"], row["family"], row["seed"], row["seat"]): row for row in rows}
    paired = []
    for condition in protocol["conditions"]:
        family, seed = str(condition["family"]), int(condition["seed"])
        for seat in condition["seats"]:
            learned = lookup[("round4_learned", family, seed, int(seat))]
            rule = lookup[("round4_rule", family, seed, int(seat))]
            paired.append(
                {
                    "scope": condition["scope"],
                    "family": family,
                    "seed": seed,
                    "seat": int(seat),
                    "learned_self_money": learned["self_money"],
                    "rule_self_money": rule["self_money"],
                    "learned_opponent_money": learned["opponent_money"],
                    "rule_opponent_money": rule["opponent_money"],
                    "learned_margin": learned["margin"],
                    "rule_margin": rule["margin"],
                    "paired_margin_delta_learned_minus_rule": learned["margin"] - rule["margin"],
                    "learned_result": learned["result"],
                    "rule_result": rule["result"],
                }
            )

    csv_path = OUTPUT / "paired_results.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(paired[0]))
        writer.writeheader()
        writer.writerows(paired)

    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in paired:
        grouped[(row["scope"], row["family"], row["seed"])].append(row)
    clusters = []
    for (scope, family, seed), selected in sorted(grouped.items()):
        clusters.append(
            {
                "scope": scope,
                "family": family,
                "seed": seed,
                "seats": len(selected),
                "mean_margin_delta_learned_minus_rule": mean(
                    row["paired_margin_delta_learned_minus_rule"] for row in selected
                ),
                "seat_deltas": [row["paired_margin_delta_learned_minus_rule"] for row in selected],
                "learned_wdl": {
                    value: sum(row["learned_result"] == value for row in selected)
                    for value in ("WIN", "DRAW", "LOSS")
                },
                "rule_wdl": {
                    value: sum(row["rule_result"] == value for row in selected)
                    for value in ("WIN", "DRAW", "LOSS")
                },
            }
        )
    scope_summary = {}
    for scope in sorted({row["scope"] for row in paired}):
        selected = [row for row in paired if row["scope"] == scope]
        selected_clusters = [row for row in clusters if row["scope"] == scope]
        scope_summary[scope] = {
            "games": len(selected),
            "clusters": len(selected_clusters),
            "mean_paired_margin_delta_learned_minus_rule": mean(
                row["paired_margin_delta_learned_minus_rule"] for row in selected
            ),
            "positive_games": sum(row["paired_margin_delta_learned_minus_rule"] > 0 for row in selected),
            "negative_games": sum(row["paired_margin_delta_learned_minus_rule"] < 0 for row in selected),
            "positive_clusters": sum(row["mean_margin_delta_learned_minus_rule"] > 0 for row in selected_clusters),
            "negative_clusters": sum(row["mean_margin_delta_learned_minus_rule"] < 0 for row in selected_clusters),
        }
    output = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol": str(PROTOCOL.relative_to(ROOT)),
        "protocol_sha256": _sha256(PROTOCOL),
        "local_only": True,
        "online_evidence": False,
        "cluster_unit": protocol["cluster_unit"],
        "games": len(rows),
        "paired_games": len(paired),
        "clusters": clusters,
        "scope_summary": scope_summary,
        "rows": rows,
    }
    _write_json(OUTPUT / "CLOSED_LOOP_RESULTS.json", output)
    print(json.dumps({"scope_summary": scope_summary, "clusters": clusters}, ensure_ascii=False))


if __name__ == "__main__":
    main()
