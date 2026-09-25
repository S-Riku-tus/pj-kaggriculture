"""Run reactive Round12 panels with terminal observations and route accounting."""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROUND12 = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "experiments/round10_public_learning_20260924/engines/kaggriculture-cppsim"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
_DLL_HANDLE = None


def init_kagsim():
    global _DLL_HANDLE
    mingw = Path(r"C:\msys64\ucrt64\bin")
    if os.name == "nt" and hasattr(os, "add_dll_directory") and mingw.is_dir():
        _DLL_HANDLE = _DLL_HANDLE or os.add_dll_directory(str(mingw))
    import kagsim

    return kagsim


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_last(path: Path):
    from kaggle_environments.agent import get_last_callable

    # path=None intentionally reproduces the official empty exec namespace.
    return get_last_callable(path.read_text(encoding="utf-8")), path.read_text(encoding="utf-8")


def invoke(function, observation, configuration):
    argc = getattr(getattr(function, "__code__", None), "co_argcount", 1)
    result = function(observation, configuration) if argc >= 2 else function(observation)
    if not isinstance(result, dict):
        return {"farmer": ["PASS"], "hands": [], "market": []}
    return {
        "farmer": list(result.get("farmer") or ["PASS"]),
        "hands": [list(value) for value in result.get("hands") or []],
        "market": [list(value) for value in result.get("market") or []],
    }


def jsonable(value):
    return json.loads(json.dumps(value, default=lambda item: dict(item)))


def post_field_states(observations, actions):
    from kaggle_environments.envs.kaggriculture import kaggriculture as official

    farms = copy.deepcopy(observations[0]["farms"])
    privates = [copy.deepcopy(observations[player]["private"]) for player in (0, 1)]
    day = int(observations[0]["day"])
    for player in (0, 1):
        action = actions[player]
        unit_actions = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        demand = Counter(
            command[1]
            for command in unit_actions
            if isinstance(command, list) and len(command) >= 2 and command[0] == "PLANT"
        )
        blocked = {crop for crop, amount in demand.items() if amount > privates[player]["seeds"].get(crop, 0)}
        for actor, command in enumerate(unit_actions):
            if isinstance(command, list) and len(command) >= 2 and command[0] == "PLANT" and command[1] in blocked:
                command = ["PASS"]
            official._apply_unit_action(farms[player], privates[player], actor, command, 10, day, 24, 100)
    return farms, privates


def market_events(observations, actions):
    from kaggle_environments.envs.kaggriculture import kaggriculture as official

    revision_scripts = ROOT / "experiments/Kaggriculture_Round11_Research_Revision_20260924/scripts"
    if str(revision_scripts) not in sys.path:
        sys.path.insert(0, str(revision_scripts))
    from market_reconstruction import market_execute

    farms, privates = post_field_states(observations, actions)
    inventory = copy.deepcopy(observations[0]["market"]["inventory"])
    params = {key: dict(value) for key, value in official.MARKET_PARAMS.items()}
    for key, patch in (observations[0]["market"].get("params") or {}).items():
        params[key].update(patch)
    cfg = {"maxMarketOrdersPerTurn": 10, "shedCapacity": 100, "farmHandCostMult": 1, "boardSize": 10}
    return market_execute(farms, privates, inventory, [actions[0]["market"], actions[1]["market"]], params, cfg)


def crop_counts(observation, player):
    counts = Counter()
    animals = Counter()
    weeds = 0
    for row in observation["farms"][player]["tiles"]:
        for tile in row:
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                counts[tile.get("crop")] += 1
            elif isinstance(tile, dict) and tile.get("animal"):
                animals[tile.get("animal")] += 1
            elif isinstance(tile, dict) and tile.get("kind") == "WEED":
                weeds += 1
    return counts, animals, weeds


def route_metrics(decisions, terminal, seat):
    planted = Counter()
    first_day = {}
    peak = Counter()
    harvest = Counter()
    sold = Counter()
    revenue = Counter()
    expense = Counter()
    idle = 0
    drop_failures = 0
    previous_counts = Counter()
    crop_loss_units = Counter()
    daily_counts = {}
    for record in decisions:
        observation = record["observations"][seat]
        action = record["actions"][seat]
        counts, animals, weeds = crop_counts(observation, seat)
        day = int(observation["day"])
        daily_counts[str(day)] = {"crops": dict(counts), "animals": dict(animals), "weeds": weeds}
        for crop, amount in counts.items():
            peak[crop] = max(peak[crop], amount)
            if crop not in first_day and amount:
                first_day[crop] = day
            if amount > previous_counts[crop]:
                planted[crop] += amount - previous_counts[crop]
        # A drop in a continuing crop is a maintenance loss. Annual crops are
        # intentionally removed by harvest and are therefore not counted here.
        for crop in ("TOMATO", "STRAWBERRY"):
            if counts[crop] < previous_counts[crop]:
                crop_loss_units[crop] += previous_counts[crop] - counts[crop]
        previous_counts = counts
        commands = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        idle += sum(command == ["PASS"] for command in commands)
        positions = [observation["farms"][seat]["farmer"], *observation["farms"][seat]["hands"]]
        for actor, command in enumerate(commands):
            if command == ["HARVEST"] and actor < len(positions):
                x, y = positions[actor]
                tile = observation["farms"][seat]["tiles"][y][x]
                if isinstance(tile, dict) and tile.get("yield_units", 0) > 0:
                    item = tile.get("crop")
                    if not item and tile.get("animal"):
                        item = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}.get(tile["animal"])
                    if item:
                        harvest[item] += int(tile["yield_units"])
            if command == ["DROP"] and actor < len(positions):
                inventory = observation["private"]["inventories"][actor]
                if tuple(positions[actor]) not in {(4, 4), (5, 4), (4, 5), (5, 5)} or not any(inventory.values()):
                    drop_failures += 1
        for event in market_events(record["observations"], record["actions"]):
            if int(event["seat"]) != seat or int(event.get("units", 0)) <= 0:
                continue
            operation = event["op"]
            item = event.get("item") or operation
            if operation == "SELL":
                sold[item] += int(event["units"])
                revenue[item] += int(event["cash"])
            else:
                expense[operation if not event.get("item") else f"{operation}:{item}"] += -int(event["cash"])
    end_counts, end_animals, end_weeds = crop_counts(terminal["observations"][seat], seat)
    return {
        "first_plant_day": first_day,
        "plants_created": dict(planted),
        "peak_crop_count": dict(peak),
        "daily_terminal_predecision_counts": daily_counts,
        "harvest_units": dict(harvest),
        "sold_units": dict(sold),
        "sales_revenue": dict(revenue),
        "expenses": dict(expense),
        "idle_worker_actions": idle,
        "drop_failures": drop_failures,
        "continuing_crop_loss_units": dict(crop_loss_units),
        "terminal_crops": dict(end_counts),
        "terminal_animals": dict(end_animals),
        "terminal_weeds": end_weeds,
        "terminal_cash": terminal["rewards"][seat],
        "opponent_terminal_cash": terminal["rewards"][1 - seat],
    }


def run_game(arm_path: Path, opponent_path: Path, seed: int, seat: int, collect_route_metrics: bool = True):
    kagsim = init_kagsim()

    arm, _ = load_last(arm_path)
    opponent, _ = load_last(opponent_path)
    game = kagsim.Game(int(seed))
    configuration = {"episodeSteps": 720, "seed": int(seed)}
    decisions = []
    while not game.done:
        observations = [jsonable(game.observe(0)), jsonable(game.observe(1))]
        functions = [arm, opponent] if seat == 0 else [opponent, arm]
        actions = [invoke(functions[player], observations[player], configuration) for player in (0, 1)]
        decisions.append({"step": int(game.step_count), "observations": observations, "actions": actions})
        game.step(actions[0], actions[1])
    terminal_observations = [jsonable(game.observe(0)), jsonable(game.observe(1))]
    rewards = [float(game.reward(0)), float(game.reward(1))]
    terminal = {
        "step": int(game.step_count),
        "observations": terminal_observations,
        "statuses": ["DONE", "DONE"],
        "rewards": rewards,
    }
    replay = {
        "format": "round12-kagsim-reactive-v1",
        "engine_version": kagsim.ENGINE_VERSION,
        "seed": int(seed),
        "decisions": decisions,
        "terminal": terminal,
        "agent_telemetry": jsonable(getattr(arm, "telemetry", {})),
    }
    metrics = route_metrics(decisions, terminal, seat) if collect_route_metrics else {
        "terminal_cash": rewards[seat],
        "opponent_terminal_cash": rewards[1 - seat],
        "collection_skipped": True,
    }
    return replay, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    output = ROUND12 / config["output"]
    if (output / "games.csv").exists():
        raise FileExistsError(f"refusing to mix results in {output}")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for arm_name, arm_rel in config["arms"].items():
        arm_path = ROUND12 / arm_rel
        for opponent_name, opponent_rel in config["opponents"].items():
            opponent_path = ROOT / opponent_rel
            for seed in config["seeds"]:
                for seat in config.get("seats", [0, 1]):
                    collect_route = arm_name in set(config.get("route_metric_arms", config["arms"]))
                    replay, metrics = run_game(
                        arm_path,
                        opponent_path,
                        int(seed),
                        int(seat),
                        collect_route_metrics=collect_route,
                    )
                    replay_path = output / "replays" / arm_name / opponent_name / f"seed_{seed}_seat_{seat}.json.gz"
                    replay_path.parent.mkdir(parents=True, exist_ok=True)
                    with gzip.open(replay_path, "wt", encoding="utf-8") as stream:
                        json.dump(replay, stream, separators=(",", ":"))
                    own = replay["terminal"]["rewards"][seat]
                    other = replay["terminal"]["rewards"][1 - seat]
                    rows.append({
                        "arm": arm_name,
                        "opponent": opponent_name,
                        "seed": seed,
                        "seat": seat,
                        "result": "W" if own > other else "L" if own < other else "T",
                        "score": 1.0 if own > other else 0.0 if own < other else 0.5,
                        "self_cash": own,
                        "opponent_cash": other,
                        "margin": own - other,
                        "agent_sha256": sha256(arm_path),
                        "opponent_sha256": sha256(opponent_path),
                        "replay": replay_path.relative_to(ROUND12).as_posix(),
                        "replay_sha256": sha256(replay_path),
                        "route_metrics_json": json.dumps(metrics, separators=(",", ":")),
                        "agent_telemetry_json": json.dumps(replay["agent_telemetry"], separators=(",", ":")),
                    })
                    print(arm_name, opponent_name, seed, seat, rows[-1]["result"], own, other, flush=True)
    with (output / "games.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = []
    for arm in config["arms"]:
        selected = [row for row in rows if row["arm"] == arm]
        summary.append({
            "arm": arm,
            "games": len(selected),
            "wins": sum(row["result"] == "W" for row in selected),
            "losses": sum(row["result"] == "L" for row in selected),
            "ties": sum(row["result"] == "T" for row in selected),
            "score": sum(row["score"] for row in selected),
            "mean_self_cash": sum(row["self_cash"] for row in selected) / len(selected),
            "mean_opponent_cash": sum(row["opponent_cash"] for row in selected) / len(selected),
            "mean_margin": sum(row["margin"] for row in selected) / len(selected),
        })
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
