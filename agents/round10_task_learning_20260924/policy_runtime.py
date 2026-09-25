"""Round10 scheduled-production fertilization task selector and executor.

The base policy is the acquired public Herd-safe agent.  A task replaces a
baseline WATER with FERTILIZE, verifies the engine effect on the next
observation, then issues the displaced WATER with the same actor and verifies
completion.  The base policy is still called at every step so its own runtime
continues from the executed closed-loop observations.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

CROPS: dict[str, dict[str, int | bool]] = {
    "WHEAT": {"first": 2, "max_day": 4, "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT": {"first": 2, "max_day": 3, "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO": {"first": 8, "max_day": 8, "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"first": 10, "max_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON": {"first": 10, "max_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}
FEATURE_NAMES = (
    "crop_WHEAT",
    "crop_CARROT",
    "crop_TOMATO",
    "crop_STRAWBERRY",
    "crop_MELON",
    "day_29",
    "hour_23",
    "crop_age_12",
    "yield_fraction",
    "consecutive_unwatered_2",
    "fertilizer_carried_5",
    "fertilizer_shed_20",
    "own_money_10000",
    "cash_lead_10000",
    "crop_price_300",
    "fertilizer_price_150",
    "price_advantage_300",
    "unlocked_quadrants_4",
    "actor_6",
    "x_9",
    "y_9",
    "remaining_steps_720",
    "crop_market_inventory_delta_400",
    "fert_market_inventory_delta_400",
    "unlocked_shops_4",
)
MODIFYING_OPS = frozenset({"WATER", "FERTILIZE", "HARVEST", "DIG"})


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _base_path() -> Path:
    here = Path(__file__).resolve().parent
    candidates = (
        here / "base_main.py",
        here.parents[1] / "experiments/round10_public_learning_20260924/public_agents/herd_safe/main.py",
        Path.cwd() / "base_main.py",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("Round10 base_main.py / acquired herd_safe main.py")


def _load_base() -> tuple[Callable[..., Any], str]:
    path = _base_path()
    source = path.read_bytes()
    namespace: dict[str, Any] = {"__file__": str(path), "__name__": "_round10_base"}
    exec(compile(source, str(path), "exec"), namespace)
    callables = [value for value in namespace.values() if callable(value)]
    if not callables:
        raise RuntimeError(f"no callable in {path}")
    return callables[-1], hashlib.sha256(source).hexdigest()


def own_state(
    observation: Mapping[str, Any],
) -> tuple[Mapping[str, Any], list[tuple[int, int]], list[Mapping[str, Any]]]:
    player = integer(observation.get("player"), -1)
    farms = list(observation.get("farms") or [])
    farm = farms[player] if 0 <= player < len(farms) else {}
    raw_positions = [farm.get("farmer") or (0, 0), *(farm.get("hands") or [])]
    positions = [(integer(value[0]), integer(value[1])) for value in raw_positions]
    raw_inventories = list((observation.get("private") or {}).get("inventories") or [])
    inventories = [value if isinstance(value, Mapping) else {} for value in raw_inventories]
    return farm, positions, inventories


def tile_at(farm: Mapping[str, Any], position: Sequence[int]) -> Mapping[str, Any] | None:
    x, y = integer(position[0], -1), integer(position[1], -1)
    rows = list(farm.get("tiles") or [])
    value = rows[y][x] if 0 <= y < len(rows) and 0 <= x < len(rows[y]) else None
    return value if isinstance(value, Mapping) else None


def action_units(action: Mapping[str, Any]) -> list[list[Any]]:
    return [list(action.get("farmer") or ["PASS"]), *[list(value or ["PASS"]) for value in action.get("hands") or []]]


def set_unit(action: dict[str, Any], actor: int, value: Sequence[Any]) -> None:
    if actor == 0:
        action["farmer"] = list(value)
    else:
        action["hands"][actor - 1] = list(value)


def production_due(tile: Mapping[str, Any], day: int) -> bool:
    rule = CROPS.get(str(tile.get("crop") or ""))
    if not rule or integer(tile.get("yield_units")) >= int(rule["max_yield"]):
        return False
    age = day - integer(tile.get("planted_day"))
    if not bool(rule["ongoing"]):
        window_start = (int(rule["max_day"]) + 1) // 2
        return window_start <= age <= int(rule["max_day"])
    since_first = day + 1 - integer(tile.get("planted_day")) - int(rule["first"])
    interval = int(rule["interval"])
    return since_first >= 0 and since_first % interval == 0 and (
        since_first // interval + 1 <= int(rule["max_yield"])
    )


def candidate_features(
    observation: Mapping[str, Any], actor: int, position: tuple[int, int], tile: Mapping[str, Any]
) -> list[float]:
    player = integer(observation.get("player"), -1)
    farms = list(observation.get("farms") or [])
    farm = farms[player] if 0 <= player < len(farms) else {}
    other = farms[1 - player] if len(farms) == 2 and player in (0, 1) else {}
    private = observation.get("private") or {}
    inventories = list(private.get("inventories") or [])
    inventory = inventories[actor] if 0 <= actor < len(inventories) else {}
    shed = private.get("shed") or {}
    market = observation.get("market") or {}
    prices = market.get("prices") or {}
    market_inventory = market.get("inventory") or {}
    crop = str(tile.get("crop") or "")
    rule = CROPS[crop]
    crop_price = float(prices.get(crop, 0) or 0)
    fert_price = float(prices.get("FERTILIZER", 0) or 0)
    day = integer(observation.get("day"))
    step = integer(observation.get("step"), day * 24 + integer(observation.get("hour")))
    return [
        *(float(crop == name) for name in CROPS),
        day / 29.0,
        integer(observation.get("hour")) / 23.0,
        (day - integer(tile.get("planted_day"))) / 12.0,
        integer(tile.get("yield_units")) / max(1.0, float(rule["max_yield"])),
        integer(tile.get("consecutive_unwatered")) / 2.0,
        integer(inventory.get("FERTILIZER")) / 5.0,
        integer(shed.get("FERTILIZER")) / 20.0,
        float(farm.get("money", 0) or 0) / 10000.0,
        (float(farm.get("money", 0) or 0) - float(other.get("money", 0) or 0)) / 10000.0,
        crop_price / 300.0,
        fert_price / 150.0,
        (crop_price - fert_price) / 300.0,
        len(farm.get("unlocked_quadrants") or []) / 4.0,
        actor / 6.0,
        position[0] / 9.0,
        position[1] / 9.0,
        (719 - step) / 720.0,
        (integer(market_inventory.get(crop)) - 10000) / 400.0,
        (integer(market_inventory.get("FERTILIZER")) - 10000) / 400.0,
        len((observation.get("town") or {}).get("unlocked_shops") or []) / 4.0,
    ]


def candidate_from_action(
    observation: Mapping[str, Any], action: Mapping[str, Any]
) -> list[dict[str, Any]]:
    day, hour = integer(observation.get("day")), integer(observation.get("hour"))
    if hour > 21:
        return []
    farm, positions, inventories = own_state(observation)
    units = action_units(action)
    result: list[dict[str, Any]] = []
    for actor, unit in enumerate(units):
        if actor >= len(positions) or actor >= len(inventories) or not unit or unit[0] != "WATER":
            continue
        position = positions[actor]
        tile = tile_at(farm, position)
        if not tile or tile.get("kind") != "PLANT" or integer(inventories[actor].get("FERTILIZER")) <= 0:
            continue
        if integer(tile.get("fertilized_until_day"), -1) >= day or not production_due(tile, day):
            continue
        conflicts = []
        later_water = False
        for other_actor, (other_position, other_action) in enumerate(zip(positions, units, strict=False)):
            if other_actor == actor or other_position != position or not other_action:
                continue
            other_op = str(other_action[0])
            if other_op in MODIFYING_OPS:
                conflicts.append((other_actor, other_op))
                later_water |= other_actor > actor and other_op == "WATER"
        if any(op != "WATER" or other_actor < actor for other_actor, op in conflicts):
            continue
        features = candidate_features(observation, actor, position, tile)
        result.append(
            {
                "candidate_id": (
                    f"fertilize_then_water:s{integer(observation.get('step'))}:"
                    f"a{actor}:x{position[0]}y{position[1]}"
                ),
                "created_step": integer(observation.get("step")),
                "deadline_step": integer(observation.get("step")) + 1,
                "day_epoch": day,
                "actor_index": actor,
                "target": list(position),
                "target_identity": {
                    "type": "crop",
                    "coordinate": list(position),
                    "resource": tile.get("crop"),
                    "generation_or_placement_day": integer(tile.get("planted_day")),
                },
                "required_carried": {"FERTILIZER": 1},
                "reserved_resources": {"actor": actor, "FERTILIZER": 1, "target": list(position)},
                "start_condition": (
                    "baseline WATER; production due; unfertilized; carried FERTILIZER; "
                    "no harmful same-target predecessor"
                ),
                "planned_actions": [["FERTILIZE"], ["WATER"]],
                "completion": "fertilized_until_day >= day+2 and watered_today true on the same crop generation",
                "failure": "actor/target/day changed or either engine effect was not observed",
                "recovery": "return to freshly computed base action after checking the real remaining WATER obligation",
                "later_baseline_water": later_water,
                "features": dict(zip(FEATURE_NAMES, features, strict=True)),
                "feature_vector": features,
                "crop": str(tile.get("crop")),
                "crop_price": integer((observation.get("market") or {}).get("prices", {}).get(str(tile.get("crop")))),
                "fertilizer_price": integer((observation.get("market") or {}).get("prices", {}).get("FERTILIZER")),
            }
        )
    return result


def candidate_signature(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: candidate[key]
        for key in ("created_step", "actor_index", "target", "crop")
    }


def target_matches(candidate: Mapping[str, Any], target: Mapping[str, Any] | None) -> bool:
    if not target:
        return False
    signature = candidate_signature(candidate)
    return all(signature.get(key) == target.get(key) for key in signature)


def load_model(path: Path | None = None) -> dict[str, Any]:
    model_path = path or Path(__file__).with_name("model.json")
    if not model_path.is_file():
        return {}
    return json.loads(model_path.read_text(encoding="utf-8"))


def model_probability(candidate: Mapping[str, Any], model: Mapping[str, Any]) -> float:
    vector = list(candidate["feature_vector"])
    means = list(model.get("means") or [])
    scales = list(model.get("scales") or [])
    weights = list(model.get("weights") or [])
    if not (len(vector) == len(means) == len(scales) == len(weights)):
        return 0.0
    score = float(model.get("bias", 0.0))
    score += sum(
        weight * ((value - mean) / scale)
        for value, mean, scale, weight in zip(vector, means, scales, weights, strict=True)
    )
    if score >= 0:
        return 1.0 / (1.0 + math.exp(-min(score, 60.0)))
    exp_score = math.exp(max(score, -60.0))
    return exp_score / (1.0 + exp_score)


def build_agent(
    mode: str,
    *,
    target: Mapping[str, Any] | None = None,
    model_path: Path | None = None,
    max_tasks: int = 6,
) -> Callable[..., dict[str, Any]]:
    base, base_sha = _load_base()
    model = load_model(model_path) if mode == "learned" else {}
    stats: dict[str, Any] = {
        "mode": mode,
        "base_sha256": base_sha,
        "model_loaded": bool(model),
        "model_calls": 0,
        "model_selected_tasks": 0,
        "model_changed_final_actions": 0,
        "rule_overrides": 0,
        "task_candidates": 0,
        "tasks_started": 0,
        "tasks_completed": 0,
        "contract_failures": 0,
        "events": [],
    }
    pending: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None

    def log(event: str, observation: Mapping[str, Any], **values: Any) -> None:
        if len(stats["events"]) < 200:
            stats["events"].append({"event": event, "step": integer(observation.get("step")), **values})

    def same_target(observation: Mapping[str, Any], plan: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, bool]:
        farm, positions, _inventories = own_state(observation)
        actor = integer(plan.get("actor_index"), -1)
        expected = tuple(plan.get("target") or (-1, -1))
        if not 0 <= actor < len(positions) or positions[actor] != expected:
            return None, False
        tile = tile_at(farm, expected)
        identity = plan.get("target_identity") or {}
        matches = bool(
            tile
            and tile.get("kind") == "PLANT"
            and tile.get("crop") == identity.get("resource")
            and integer(tile.get("planted_day"), -1) == integer(identity.get("generation_or_placement_day"), -2)
        )
        return tile, matches

    def agent(observation: dict[str, Any], configuration: dict[str, Any] | None = None) -> dict[str, Any]:
        nonlocal pending, verification
        raw = base(observation)
        action = {
            "farmer": list(raw.get("farmer") or ["PASS"]),
            "hands": [list(value or ["PASS"]) for value in (raw.get("hands") or [])],
            "market": [list(value) for value in (raw.get("market") or [])],
        }
        if verification is not None:
            tile, matches = same_target(observation, verification)
            if matches and bool((tile or {}).get("watered_today")):
                stats["tasks_completed"] += 1
                log("task_completed", observation, candidate_id=verification["candidate_id"])
            else:
                stats["contract_failures"] += 1
                log("water_effect_missing", observation, candidate_id=verification["candidate_id"])
            verification = None
        if pending is not None:
            tile, matches = same_target(observation, pending)
            effect = matches and integer((tile or {}).get("fertilized_until_day"), -1) >= (
                integer(pending["day_epoch"]) + 2
            )
            timely = integer(observation.get("step")) == integer(pending["deadline_step"])
            if not effect or not timely or integer(observation.get("day")) != integer(pending["day_epoch"]):
                stats["contract_failures"] += 1
                log("fertilize_effect_or_deadline_failed", observation, candidate_id=pending["candidate_id"])
                pending = None
                return action
            if bool((tile or {}).get("watered_today")):
                stats["tasks_completed"] += 1
                log("completed_by_later_actor", observation, candidate_id=pending["candidate_id"])
                pending = None
                return action
            actor = integer(pending["actor_index"])
            set_unit(action, actor, ["WATER"])
            stats["model_changed_final_actions"] += int(mode == "learned")
            log("water_committed", observation, candidate_id=pending["candidate_id"], actor=actor)
            verification = pending
            pending = None
            return action
        if mode == "baseline" or integer(stats["tasks_started"]) >= max_tasks:
            return action
        candidates = candidate_from_action(observation, action)
        stats["task_candidates"] += len(candidates)
        chosen: dict[str, Any] | None = None
        for candidate in candidates:
            if mode == "target":
                if target_matches(candidate, target):
                    chosen = candidate
                    break
            elif mode == "rule":
                high_value = candidate["crop"] in {"MELON", "STRAWBERRY"}
                if high_value and candidate["crop_price"] > candidate["fertilizer_price"]:
                    chosen = candidate
                    break
            elif mode == "learned":
                stats["model_calls"] += 1
                probability = model_probability(candidate, model)
                candidate["model_probability"] = probability
                if probability >= float(model.get("threshold", 0.5)):
                    chosen = candidate
                    break
        if chosen is None:
            return action
        actor = integer(chosen["actor_index"])
        set_unit(action, actor, ["FERTILIZE"])
        pending = chosen
        stats["tasks_started"] += 1
        stats["rule_overrides"] += int(mode == "rule")
        stats["model_selected_tasks"] += int(mode == "learned")
        stats["model_changed_final_actions"] += int(mode == "learned")
        log(
            "fertilize_committed",
            observation,
            candidate_id=chosen["candidate_id"],
            actor=actor,
            target=chosen["target"],
            features=chosen["features"],
            probability=chosen.get("model_probability"),
        )
        return action

    def get_diagnostics() -> dict[str, Any]:
        result = json.loads(json.dumps(stats))
        result["pending_obligations"] = (
            {"FERTILIZE_EFFECT": 1, "WATER": 1}
            if pending is not None
            else {"WATER_EFFECT": 1}
            if verification is not None
            else {}
        )
        return result

    agent.round10_diagnostics = get_diagnostics  # type: ignore[attr-defined]
    return agent
