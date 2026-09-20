"""Paired, seat-swapped evaluation of the four preregistered V125 arms.

This is a local proxy experiment.  The public reference agents are regression
families, not authenticated current leaderboard binaries, and win rates from
this script must not be converted into a Kaggle rating.
"""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import importlib.util
import json
import os
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "experiments" / "research_20260920_v125" / "paired_eval"

ARMS = {
    "v124_frozen": ROOT / "agents/v124/main.py",
    "v125_exec_only": ROOT / "agents/v125_exec/main.py",
    "v125_base_plan": ROOT / "agents/v125_base/main.py",
    "v125_adaptive": ROOT / "agents/v125_adaptive/main.py",
}
OPPONENTS = {
    "mooman_e052a": ROOT / "experiments/research_20260910/runtime/mooman_e052a/main.py",
    "qeinstein_moev2": ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py",
    "smart_farm": ROOT / "experiments/research_20260918_v120/acquisition/smart_farm/decoded_main_1.py",
    "souvik_v4": ROOT / "experiments/research_20260910/runtime/souvik_v4/main.py",
}
DEFAULT_SEEDS = (2026092101,)
EMPTY_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_module(path: Path, label: str) -> Any:
    name = f"_v125_eval_{label}_{os.getpid()}_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _audit_module() -> Any:
    path = (
        ROOT
        / "artifacts/v125_analysis_package_20260920/v125_analysis_package/scripts/audit_engine.py"
    )
    return _load_module(path, "audit")


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=lambda item: dict(item)))


def _action_metrics(replay: dict[str, Any], focal_seat: int) -> dict[str, Any]:
    audit = _audit_module()
    operations: Counter[str] = Counter()
    harvest: Counter[str] = Counter()
    sales: Counter[str] = Counter()
    revenue: Counter[str] = Counter()
    floor_sales: Counter[str] = Counter()
    planted: Counter[str] = Counter()
    fertilizer_uses: Counter[str] = Counter()
    discarded: Counter[str] = Counter()
    atomic_cancellations = 0
    effective = 0
    total_unit_actions = 0

    steps = replay["steps"]
    for turn in range(min(719, len(steps) - 1)):
        previous = steps[turn]
        following = steps[turn + 1]
        farms = copy.deepcopy(previous[0]["observation"]["farms"])
        privates = [copy.deepcopy(previous[seat]["observation"]["private"]) for seat in (0, 1)]
        actions = [following[seat].get("action") or EMPTY_ACTION for seat in (0, 1)]
        day = int(previous[0]["observation"].get("day", turn // 24))

        unit_events: list[list[dict[str, Any]]] = []
        for seat in (0, 1):
            events = audit.units(farms[seat], privates[seat], actions[seat], day)
            unit_events.append(events)
        for event in unit_events[focal_seat]:
            operation = str(event.get("op", "INVALID"))
            operations[operation] += 1
            total_unit_actions += 1
            effective += int(bool(event.get("effect")))
            atomic_cancellations += int(event.get("reason") == "atomic_seed_shortage")
            for item, quantity in (event.get("harvest") or {}).items():
                harvest[str(item)] += int(quantity)
            if event.get("planted"):
                planted[str(event["planted"])] += 1
            if event.get("fertilized"):
                fertilizer_uses[str(event["fertilized"])] += 1
            for item, quantity in (event.get("overflow") or {}).items():
                discarded[str(item)] += int(quantity)

        market_inventory = copy.deepcopy(previous[0]["observation"]["market"]["inventory"])
        market_events = audit.market(farms, privates, actions, market_inventory)
        for seat, _slot, operation, item, quantity, price in market_events:
            if int(seat) != focal_seat or operation != "SELL":
                continue
            sales[str(item)] += int(quantity)
            revenue[str(item)] += int(quantity) * int(price)
            if int(price) == 1:
                floor_sales[str(item)] += int(quantity)

        # Exact automatic end-of-day overflow from the audited post-market
        # private state. Inventories enter the shed in actor order.
        if turn % 24 == 23:
            private = privates[focal_seat]
            room = max(0, 100 - sum(int(value) for value in private["shed"].values()))
            for inventory in private["inventories"]:
                for item, quantity in list(inventory.items()):
                    take = min(int(quantity), room)
                    room -= take
                    if int(quantity) > take:
                        discarded[str(item)] += int(quantity) - take

    floor_total = sum(floor_sales.values())
    sold_total = sum(sales.values())
    return {
        "unit_actions": total_unit_actions,
        "effective_unit_actions": effective,
        "passes": operations["PASS"],
        "atomic_plant_cancellations": atomic_cancellations,
        "harvest": dict(harvest),
        "planted": dict(planted),
        "fertilizer_uses": dict(fertilizer_uses),
        "sales": dict(sales),
        "sale_revenue": dict(revenue),
        "floor_sales": dict(floor_sales),
        "floor_sale_units": floor_total,
        "sold_units": sold_total,
        "floor_sale_share": floor_total / sold_total if sold_total else 0.0,
        "discarded": dict(discarded),
        "discarded_units": sum(discarded.values()),
    }


def _run_task(task: dict[str, Any]) -> dict[str, Any]:
    from kaggle_environments import make

    arm_path = Path(task["arm_path"])
    opponent_path = Path(task["opponent_path"])
    focal_module = _load_module(arm_path, f"focal_{task['arm']}_{task['seed']}_{task['seat']}")
    opponent_module = _load_module(
        opponent_path, f"opponent_{task['opponent']}_{task['seed']}_{task['seat']}"
    )
    diagnostic_rows: list[dict[str, Any]] = []
    previous_trigger_counts: dict[str, Any] = {}

    def focal(observation: Any) -> dict[str, Any]:
        nonlocal previous_trigger_counts
        action = focal_module.agent(observation)
        getter = getattr(focal_module, "latest_diagnostics", None)
        if callable(getter):
            seat = int(observation.get("player", task["seat"]))
            diagnostic = _jsonable(getter(seat))
            triggers = diagnostic.get("trigger_counts") or {}
            changed = triggers != previous_trigger_counts
            if int(observation.get("hour", 0)) == 0 or diagnostic.get("rejected") or changed:
                diagnostic_rows.append(
                    {
                        "arm": task["arm"],
                        "opponent": task["opponent"],
                        "seed": task["seed"],
                        "seat": task["seat"],
                        "action": _jsonable(action),
                        **diagnostic,
                    }
                )
            previous_trigger_counts = dict(triggers)
        return action

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": task["seed"]}, debug=True)
    agents = [focal, opponent_module.agent] if task["seat"] == 0 else [opponent_module.agent, focal]
    started = time.perf_counter()
    env.run(agents)
    elapsed = time.perf_counter() - started
    replay = env.toJSON()
    final = replay["steps"][-1]
    rewards = [float(state.get("reward") or 0) for state in final]
    statuses = [str(state.get("status")) for state in final]
    metrics = _action_metrics(replay, int(task["seat"]))

    replay_path = Path(task["replay_path"])
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(replay_path, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))

    final_cash = rewards[int(task["seat"])]
    predicted = None
    if diagnostic_rows:
        predicted = (diagnostic_rows[-1].get("candidate_values") or {}).get("continue_base_plan")
    return {
        **task,
        "our_cash": final_cash,
        "opponent_cash": rewards[1 - int(task["seat"])],
        "margin": final_cash - rewards[1 - int(task["seat"])],
        "win": final_cash > rewards[1 - int(task["seat"])],
        "tie": final_cash == rewards[1 - int(task["seat"])],
        "statuses": statuses,
        "elapsed_seconds": elapsed,
        "prediction_terminal_cash": predicted,
        "prediction_error": final_cash - float(predicted) if predicted is not None else None,
        "metrics": metrics,
        "diagnostics": diagnostic_rows,
    }


def _recover_task(task: dict[str, Any]) -> dict[str, Any]:
    """Rebuild metrics/diagnostics from a completed immutable replay."""
    replay_path = Path(task["replay_path"])
    with gzip.open(replay_path, "rt", encoding="utf-8") as stream:
        replay = json.load(stream)
    focal_module = _load_module(
        Path(task["arm_path"]), f"recover_{task['arm']}_{task['seed']}_{task['seat']}"
    )
    diagnostic_rows: list[dict[str, Any]] = []
    getter = getattr(focal_module, "latest_diagnostics", None)
    previous_trigger_counts: dict[str, Any] = {}
    action_mismatches = 0
    if callable(getter):
        for turn in range(min(719, len(replay["steps"]) - 1)):
            observation = copy.deepcopy(replay["steps"][turn][int(task["seat"])]["observation"])
            # Kaggle's serialized non-zero-seat state omits the framework
            # `step` field even though the callable receives the game clock.
            observation["step"] = 24 * int(observation.get("day", turn // 24)) + int(
                observation.get("hour", turn % 24)
            )
            action = focal_module.agent(observation)
            recorded = replay["steps"][turn + 1][int(task["seat"])].get("action") or EMPTY_ACTION
            action_mismatches += int(_jsonable(action) != _jsonable(recorded))
            diagnostic = _jsonable(getter(int(task["seat"])))
            triggers = diagnostic.get("trigger_counts") or {}
            changed = triggers != previous_trigger_counts
            if int(observation.get("hour", 0)) == 0 or diagnostic.get("rejected") or changed:
                diagnostic_rows.append(
                    {
                        "arm": task["arm"],
                        "opponent": task["opponent"],
                        "seed": task["seed"],
                        "seat": task["seat"],
                        "action": _jsonable(action),
                        **diagnostic,
                    }
                )
            previous_trigger_counts = dict(triggers)
    final = replay["steps"][-1]
    rewards = [float(state.get("reward") or 0) for state in final]
    statuses = [str(state.get("status")) for state in final]
    metrics = _action_metrics(replay, int(task["seat"]))
    final_cash = rewards[int(task["seat"])]
    predicted = None
    if diagnostic_rows:
        predicted = (diagnostic_rows[-1].get("candidate_values") or {}).get("continue_base_plan")
    return {
        **task,
        "our_cash": final_cash,
        "opponent_cash": rewards[1 - int(task["seat"])],
        "margin": final_cash - rewards[1 - int(task["seat"])],
        "win": final_cash > rewards[1 - int(task["seat"])],
        "tie": final_cash == rewards[1 - int(task["seat"])],
        "statuses": statuses,
        "elapsed_seconds": float(task.get("elapsed_seconds") or 0),
        "prediction_terminal_cash": predicted,
        "prediction_error": final_cash - float(predicted) if predicted is not None else None,
        "metrics": metrics,
        "diagnostics": diagnostic_rows,
        "reconstructed_action_mismatches": action_mismatches,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _flat_result(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row["metrics"]
    return {
        "arm": row["arm"],
        "opponent_family": row["opponent"],
        "seed": row["seed"],
        "seat": row["seat"],
        "our_cash": row["our_cash"],
        "opponent_cash": row["opponent_cash"],
        "margin": row["margin"],
        "win": int(row["win"]),
        "tie": int(row["tie"]),
        "passes": metrics["passes"],
        "discarded_units": metrics["discarded_units"],
        "floor_sale_units": metrics["floor_sale_units"],
        "sold_units": metrics["sold_units"],
        "floor_sale_share": round(metrics["floor_sale_share"], 6),
        "atomic_plant_cancellations": metrics["atomic_plant_cancellations"],
        "fertilize_wheat": metrics["fertilizer_uses"].get("WHEAT", 0),
        "elapsed_seconds": round(row["elapsed_seconds"], 4),
        "prediction_terminal_cash": row["prediction_terminal_cash"],
        "prediction_error": row["prediction_error"],
        "replay": str(Path(row["replay_path"]).relative_to(ROOT)),
    }


def _summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    groups = sorted({(row["arm"], row["opponent_family"]) for row in rows})
    for arm, family in groups:
        selected = [row for row in rows if row["arm"] == arm and row["opponent_family"] == family]
        margins = [float(row["margin"]) for row in selected]
        output.append(
            {
                "arm": arm,
                "opponent_family": family,
                "games": len(selected),
                "wins": sum(int(row["win"]) for row in selected),
                "ties": sum(int(row["tie"]) for row in selected),
                "win_rate": sum(int(row["win"]) for row in selected) / len(selected),
                "mean_margin": mean(margins),
                "median_margin": median(margins),
                "lower_margin": min(margins),
                "mean_cash": mean(float(row["our_cash"]) for row in selected),
                "mean_discarded": mean(float(row["discarded_units"]) for row in selected),
                "mean_floor_share": mean(float(row["floor_sale_share"]) for row in selected),
                "mean_elapsed_seconds": mean(float(row["elapsed_seconds"]) for row in selected),
            }
        )
    return output


def _contributions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chain = ["v124_frozen", "v125_exec_only", "v125_base_plan", "v125_adaptive"]
    by_key = {(row["arm"], row["opponent_family"], row["seed"], row["seat"]): row for row in rows}
    output: list[dict[str, Any]] = []
    for left, right in zip(chain[:-1], chain[1:], strict=True):
        differences = []
        wins = []
        for row in rows:
            if row["arm"] != left:
                continue
            other = by_key[(right, row["opponent_family"], row["seed"], row["seat"])]
            differences.append(float(other["margin"]) - float(row["margin"]))
            wins.append(int(other["win"]) - int(row["win"]))
        output.append(
            {
                "from_arm": left,
                "to_arm": right,
                "paired_games": len(differences),
                "mean_margin_contribution": mean(differences),
                "median_margin_contribution": median(differences),
                "lower_margin_contribution": min(differences),
                "win_count_contribution": sum(wins),
            }
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seeds", type=int, nargs="*", default=list(DEFAULT_SEEDS))
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse completed .json.gz replays and reconstruct diagnostics without rerunning games",
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)

    for path in [*ARMS.values(), *OPPONENTS.values()]:
        if not path.is_file():
            raise FileNotFoundError(path)
    hashes = {str(path.relative_to(ROOT)): _sha256(path) for path in [*ARMS.values(), *OPPONENTS.values()]}
    preregistration = {
        "format": "v125-paired-evaluation-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "git_commit": os.popen("git rev-parse HEAD").read().strip(),
        "arms": {name: str(path.relative_to(ROOT)) for name, path in ARMS.items()},
        "opponents": {name: str(path.relative_to(ROOT)) for name, path in OPPONENTS.items()},
        "seeds": list(args.seeds),
        "seats": [0, 1],
        "file_sha256": hashes,
        "primary_metric": "win rate by opponent family",
        "secondary_metrics": [
            "margin", "lower margin", "discarded units", "floor-price sale share",
            "atomic plant cancellations", "wheat fertilizer uses", "runtime",
        ],
        "limitations": [
            "public proxy opponents are not authenticated current Top1/2/3 binaries",
            "one or two adjacent seeds do not justify an independence-based narrow confidence interval",
            (
                "these seeds are fresh for this V125 implementation but this run is development evidence, "
                "not final holdout"
            ),
        ],
    }
    preregistration_path = output / "preregistration.json"
    if not (args.resume and preregistration_path.is_file()):
        preregistration_path.write_text(
            json.dumps(preregistration, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    tasks: list[dict[str, Any]] = []
    for arm, arm_path in ARMS.items():
        for opponent, opponent_path in OPPONENTS.items():
            for seed in args.seeds:
                for seat in (0, 1):
                    replay = output / "replays" / arm / opponent / f"seed_{seed}_seat_{seat}.json.gz"
                    tasks.append(
                        {
                            "arm": arm,
                            "arm_path": str(arm_path),
                            "opponent": opponent,
                            "opponent_path": str(opponent_path),
                            "seed": int(seed),
                            "seat": seat,
                            "replay_path": str(replay),
                        }
                    )

    elapsed_lookup: dict[tuple[str, str, int, int], float] = {}
    existing_games = output / "games.csv"
    if args.resume and existing_games.is_file():
        with existing_games.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                elapsed_lookup[(row["arm"], row["opponent_family"], int(row["seed"]), int(row["seat"]))] = float(
                    row.get("elapsed_seconds") or 0
                )
        for task in tasks:
            task["elapsed_seconds"] = elapsed_lookup.get(
                (task["arm"], task["opponent"], task["seed"], task["seat"]), 0
            )

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        worker = _recover_task if args.resume else _run_task
        futures = {pool.submit(worker, task): task for task in tasks}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(
                f"{result['arm']} vs {result['opponent']} seed={result['seed']} "
                f"seat={result['seat']} margin={result['margin']:.0f}",
                flush=True,
            )
    results.sort(key=lambda row: (row["arm"], row["opponent"], row["seed"], row["seat"]))
    flat = [_flat_result(row) for row in results]
    fields = list(flat[0])
    _write_csv(output / "games.csv", flat, fields)
    summaries = _summaries(flat)
    _write_csv(output / "opponent_family_summary.csv", summaries, list(summaries[0]))
    contributions = _contributions(flat)
    _write_csv(output / "contributions.csv", contributions, list(contributions[0]))

    with (output / "decision_log.jsonl").open("w", encoding="utf-8") as stream:
        for result in results:
            for diagnostic in result["diagnostics"]:
                stream.write(json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.write(
                json.dumps(
                    {
                        "record_type": "realized_game",
                        "arm": result["arm"],
                        "opponent": result["opponent"],
                        "seed": result["seed"],
                        "seat": result["seat"],
                        "realized_cash": result["our_cash"],
                        "prediction_terminal_cash": result["prediction_terminal_cash"],
                        "prediction_error": result["prediction_error"],
                        "realized_yield": result["metrics"]["harvest"],
                        "inventory_discard": result["metrics"]["discarded"],
                        "reconstructed_action_mismatches": result.get(
                            "reconstructed_action_mismatches", 0
                        ),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )

    paired = {(row["opponent_family"], row["seed"], row["seat"]): row for row in flat if row["arm"] == "v124_frozen"}
    deltas = []
    for row in flat:
        if row["arm"] == "v124_frozen":
            continue
        control = paired[(row["opponent_family"], row["seed"], row["seat"])]
        deltas.append({**row, "margin_delta_vs_v124": row["margin"] - control["margin"]})
    representatives = {
        "largest_improvement": max(deltas, key=lambda row: row["margin_delta_vs_v124"]),
        "largest_worsening": min(deltas, key=lambda row: row["margin_delta_vs_v124"]),
    }
    (output / "representative_games.json").write_text(
        json.dumps(representatives, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"games": len(flat), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
