"""Run the preregistered Round5 NONE/RULE/LEARNED local comparison."""

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
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments/learning_round5_20260921"
PROTOCOL = EXPERIMENT / "COMPARISON_PROTOCOL.json"
OUTPUT = EXPERIMENT / "comparison"
ARMS = {
    "round5_none": ROOT / "agents/learning_round5_20260921/base_main.py",
    "round5_rule": ROOT / "agents/learning_round5_20260921/rule_main.py",
    "round5_learned": ROOT / "agents/learning_round5_20260921/learned_main.py",
}
OPPONENTS = {
    "qeinstein_moev2": ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py",
    "smart_farm": ROOT / "experiments/research_20260918_v120/acquisition/smart_farm/decoded_main_1.py",
}
GENERIC_MODULES = (
    "agents", "action_codec", "base_main", "bc_agent", "common", "contracts", "executor", "features",
    "learned_main", "market", "policy_runtime", "rule_main", "selector",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_module(path: Path, label: str) -> Any:
    cached = {name: sys.modules.pop(name) for name in GENERIC_MODULES if name in sys.modules}
    parent = str(path.parent)
    sys.path.insert(0, parent)
    try:
        spec = importlib.util.spec_from_file_location(f"_r5_{label}_{uuid.uuid4().hex}", path)
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
        for name in GENERIC_MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(cached)


def call(function: Any, observation: Any, configuration: Any) -> Any:
    try:
        parameters = list(inspect.signature(function).parameters.values())
        accepts_two = any(value.kind in {value.VAR_POSITIONAL, value.VAR_KEYWORD} for value in parameters) or len(parameters) >= 2
    except (TypeError, ValueError):
        accepts_two = True
    return function(observation, configuration) if accepts_two else function(observation)


def emitted_action_audit(replay: dict[str, Any], seat: int) -> dict[str, int]:
    immature = duplicate = animal_harvest = harvest = 0
    first_yield = {"WHEAT": 2, "CARROT": 2, "TOMATO": 8, "STRAWBERRY": 10, "MELON": 10}
    for record in range(1, len(replay["steps"])):
        before = replay["steps"][record - 1][seat]["observation"]
        action = replay["steps"][record][seat].get("action") or {}
        farm = before["farms"][seat]
        positions = [farm["farmer"], *farm["hands"]]
        units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        targets = Counter()
        for actor, unit in enumerate(units):
            if not unit or unit[0] != "HARVEST" or actor >= len(positions):
                continue
            harvest += 1
            x, y = positions[actor]
            tile = farm["tiles"][y][x]
            targets[(x, y)] += 1
            if isinstance(tile, dict) and tile.get("animal"):
                animal_harvest += 1
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                immature += int(before["day"] - tile["planted_day"] < first_yield[tile["crop"]])
        duplicate += sum(max(0, count - 1) for count in targets.values())
    return {"harvest_issued": harvest, "duplicate_harvest_issued": duplicate, "immature_harvest_issued": immature, "animal_harvest_issued": animal_harvest}


def run_one(arm: str, condition: Mapping[str, Any], seat: int) -> dict[str, Any]:
    from kaggle_environments import make

    seed = int(condition["seed"])
    family = str(condition["family"])
    random.seed(seed)
    np = __import__("numpy")
    np.random.seed(seed % (2**32 - 1))
    focal_module = load_module(ARMS[arm], f"{arm}_focal")
    opponent_module = load_module(OPPONENTS[family], f"{family}_opponent")
    timings: list[float] = []

    def focal(observation: Any, configuration: Any = None) -> Any:
        started = time.perf_counter()
        try:
            return call(focal_module.agent, observation, configuration)
        finally:
            timings.append(time.perf_counter() - started)

    def opponent(observation: Any, configuration: Any = None) -> Any:
        return call(opponent_module.agent, observation, configuration)

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    env.run([focal, opponent] if seat == 0 else [opponent, focal])
    replay = env.toJSON()
    final = replay["steps"][-1]
    rewards = [float(value.get("reward") or 0.0) for value in final]
    statuses = [str(value.get("status")) for value in final]
    replay_path = OUTPUT / "replays" / arm / family / f"seed_{seed}_seat_{seat}.json.gz"
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(replay_path, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))
    trace = focal_module.policy_trace()
    trace_path = OUTPUT / "traces" / arm / family / f"seed_{seed}_seat_{seat}.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("".join(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n" for value in trace), encoding="utf-8")
    failure_steps = {int(value["step"]) for value in trace if value.get("event") in {"primitive_result", "cash_realization_result"} and value.get("status") in {"FAILED", "UNKNOWN"}}
    failure_windows = [value for value in trace if any(abs(int(value.get("step", -999)) - step) <= 1 for step in failure_steps)]
    failure_path = OUTPUT / "failure_windows" / arm / family / f"seed_{seed}_seat_{seat}.json"
    write_json(failure_path, failure_windows)
    audit = emitted_action_audit(replay, seat)
    self_money, opponent_money = rewards[seat], rewards[1 - seat]
    return {
        "arm": arm,
        "scope": condition["scope"],
        "family": family,
        "seed": seed,
        "seat": seat,
        "self_money": self_money,
        "opponent_money": opponent_money,
        "margin": self_money - opponent_money,
        "result": "WIN" if self_money > opponent_money else "DRAW" if self_money == opponent_money else "LOSS",
        "terminal_statuses": statuses,
        "stored_states": len(replay["steps"]),
        "mean_call_seconds": mean(timings),
        "max_call_seconds": max(timings),
        "diagnostics": focal_module.policy_diagnostics(),
        "emitted_action_audit": audit,
        "trace_event_count": len(trace),
        "failure_result_count": len(failure_steps),
        "trace": str(trace_path.relative_to(ROOT)),
        "trace_sha256": sha256(trace_path),
        "failure_windows": str(failure_path.relative_to(ROOT)),
        "replay": str(replay_path.relative_to(ROOT)),
        "replay_sha256": sha256(replay_path),
        "town_unlock_sequence": replay["steps"][-1][seat]["observation"]["town"]["unlocked_shops"],
    }


def load_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def first_difference(left: dict[str, Any], right: dict[str, Any], seat: int, kind: str) -> int | None:
    opponent = 1 - seat
    for record, (a, b) in enumerate(zip(left["steps"], right["steps"], strict=True)):
        if kind == "town" and a[seat]["observation"]["town"] != b[seat]["observation"]["town"]:
            return record
        if kind == "opponent_action" and record > 0 and a[opponent].get("action") != b[opponent].get("action"):
            return record
    return None


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if not protocol.get("created_before_results") or list(protocol["arms"]) != list(ARMS):
        raise ValueError("protocol was not fixed for this runner")
    rows = []
    total = len(ARMS) * sum(len(condition["seats"]) for condition in protocol["conditions"])
    index = 0
    for arm in ARMS:
        for condition in protocol["conditions"]:
            for seat in condition["seats"]:
                index += 1
                row = run_one(arm, condition, int(seat))
                rows.append(row)
                print(f"{index}/{total} {arm} {row['family']} {row['seed']} seat{seat}", flush=True)
    lookup = {(row["arm"], row["family"], row["seed"], row["seat"]): row for row in rows}
    paired = []
    for arm in ("round5_rule", "round5_learned"):
        for condition in protocol["conditions"]:
            family, seed = str(condition["family"]), int(condition["seed"])
            for seat in condition["seats"]:
                base = lookup[("round5_none", family, seed, int(seat))]
                candidate = lookup[(arm, family, seed, int(seat))]
                base_replay = load_gzip_json(ROOT / base["replay"])
                candidate_replay = load_gzip_json(ROOT / candidate["replay"])
                paired.append({
                    "arm": arm,
                    "scope": condition["scope"],
                    "family": family,
                    "seed": seed,
                    "seat": int(seat),
                    "delta_self": candidate["self_money"] - base["self_money"],
                    "delta_opponent": candidate["opponent_money"] - base["opponent_money"],
                    "delta_margin": candidate["margin"] - base["margin"],
                    "base_result": base["result"],
                    "candidate_result": candidate["result"],
                    "first_town_difference_record": first_difference(candidate_replay, base_replay, int(seat), "town"),
                    "first_opponent_action_difference_record": first_difference(candidate_replay, base_replay, int(seat), "opponent_action"),
                })
    csv_path = OUTPUT / "paired_results.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(paired[0]))
        writer.writeheader()
        writer.writerows(paired)
    clusters = []
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in paired:
        grouped[(row["arm"], row["family"], row["seed"])].append(row)
    for (arm, family, seed), selected in sorted(grouped.items()):
        clusters.append({"arm": arm, "family": family, "seed": seed, "seats": 2, "mean_delta_self": mean(row["delta_self"] for row in selected), "mean_delta_opponent": mean(row["delta_opponent"] for row in selected), "mean_delta_margin": mean(row["delta_margin"] for row in selected), "seat_margin_deltas": [row["delta_margin"] for row in selected]})
    summary = {}
    for arm in ("round5_rule", "round5_learned"):
        selected = [row for row in paired if row["arm"] == arm]
        selected_clusters = [row for row in clusters if row["arm"] == arm]
        summary[arm] = {
            "games": len(selected),
            "clusters": len(selected_clusters),
            "mean_delta_self": mean(row["delta_self"] for row in selected),
            "mean_delta_opponent": mean(row["delta_opponent"] for row in selected),
            "mean_delta_margin": mean(row["delta_margin"] for row in selected),
            "positive_clusters": sum(row["mean_delta_margin"] > 0 for row in selected_clusters),
            "negative_clusters": sum(row["mean_delta_margin"] < 0 for row in selected_clusters),
        }
    output = {"created_at_utc": datetime.now(UTC).isoformat(), "protocol": str(PROTOCOL.relative_to(ROOT)), "protocol_sha256": sha256(PROTOCOL), "engine_sha256_verified": protocol["engine_sha256"] == sha256(ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"), "local_only": True, "online_evidence": False, "cluster_unit": protocol["cluster_unit"], "games": len(rows), "paired_rows": paired, "clusters": clusters, "summary_vs_none": summary, "rows": rows}
    write_json(OUTPUT / "COMPARISON_RESULTS.json", output)
    print(json.dumps({"summary_vs_none": summary, "clusters": clusters}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
