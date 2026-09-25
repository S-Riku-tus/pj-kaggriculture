"""Held-out full-action imitation audit for the frozen Round6 BC archive."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_round6_anchors import prepare_archives, sha256, write_json  # noqa: E402

EXPERIMENT = ROOT / "experiments" / "learning_round6_20260922"
SOURCE_EXPERIMENT = ROOT / "experiments" / "learning_next_20260921"
TEACHER_SUBMISSION = 56216119


def restore_observation(states: list[dict[str, Any]], seat: int, step: int) -> dict[str, Any]:
    public = dict(states[0].get("observation") or {})
    private = states[seat].get("observation") or {}
    public["player"] = seat
    public["private"] = private.get("private", {})
    public["remainingOverageTime"] = private.get("remainingOverageTime", public.get("remainingOverageTime", 60))
    public["step"] = step
    return public


def _load_module(path: Path) -> Any:
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("round6_imitation_archive", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str | bytes) else ()


def _action_token(module: Any, action: Any) -> str:
    return str(module.action_token(action))


def _market_token(module: Any, order: Any) -> str:
    helper = getattr(module, "market_token", None)
    if callable(helper):
        return str(helper(order))
    values = list(order) if isinstance(order, list | tuple) else []
    if not values:
        return "EOS"
    operation = str(values[0])
    if operation in {"HIRE", "BUY_LAND"}:
        return operation
    return f"{operation}:{values[1]}" if len(values) >= 2 else "EOS"


def _units(action: Mapping[str, Any]) -> list[list[Any]]:
    return [list(action.get("farmer") or ["PASS"]), *[list(value) for value in action.get("hands") or []]]


def _quantity(value: Sequence[Any]) -> int:
    return int(value[2]) if len(value) >= 3 else 1


def _raw_prediction(module: Any, observation: Mapping[str, Any], seat: int) -> dict[str, Any]:
    helper = getattr(module, "predict_raw_action", None)
    if callable(helper):
        return {"action": helper(observation, None), "actor_probabilities": [], "market_probabilities": []}
    history = module._history.setdefault(seat, module.MarketHistory())
    previous_market = module._previous_market.get(seat, [])
    history.update(observation, previous_market)
    previous_actor = module._previous_actor.get(seat, [])
    actor_count = 1 + len(observation["farms"][seat].get("hands", []))
    units: list[list[Any]] = []
    actor_probabilities: list[float] = []
    for index in range(actor_count):
        previous = previous_actor[index] if index < len(previous_actor) else "PASS"
        probability = module.ACTOR_MODEL.probabilities(module.bc_actor_features(observation, index, previous, history))
        best = int(probability.argmax())
        token = str(module.ACTOR_MODEL.classes[best])
        quantity = module._quantity("actor", token)
        units.append(module.token_action(token, quantity))
        actor_probabilities.append(float(probability[best]))
    orders: list[list[Any]] = []
    market_probabilities: list[float] = []
    previous = "EOS"
    for slot in range(10):
        probability = module.MARKET_MODEL.probabilities(module.market_features(observation, slot, previous, history))
        best = int(probability.argmax())
        token = str(module.MARKET_MODEL.classes[best])
        market_probabilities.append(float(probability[best]))
        if token == "EOS":
            break
        quantity = module._quantity("market", token)
        orders.append(module.token_order(token, quantity))
        previous = token
    return {
        "action": {"farmer": units[0], "hands": units[1:], "market": orders},
        "actor_probabilities": actor_probabilities,
        "market_probabilities": market_probabilities,
    }


def _prime_teacher_history(module: Any, seat: int, teacher_previous: Mapping[str, Any] | None) -> None:
    if teacher_previous is None:
        module._previous_actor.pop(seat, None)
        module._previous_market.pop(seat, None)
        return
    units = _units(teacher_previous)
    module._previous_actor[seat] = [_action_token(module, value) for value in units]
    module._previous_market[seat] = [list(value) for value in teacher_previous.get("market") or []]
    module._probes[seat] = []


def _context_labels(observation: Mapping[str, Any], previous_shops: list[str]) -> list[str]:
    seat = int(observation["player"])
    step = 24 * int(observation.get("day", 0)) + int(observation.get("hour", 0))
    phase = "early" if step < 240 else "mid" if step < 480 else "late"
    labels = [f"phase:{phase}"]
    shops = list(observation.get("town", {}).get("unlocked_shops", []))
    labels.append("shop:before_first" if not shops else "shop:after_first")
    if len(shops) > len(previous_shops):
        labels.append("shop:addition_turn")
    money = float(observation["farms"][seat].get("money", 0))
    labels.append("cash:pressured" if money < 1000 else "cash:not_pressured")
    shed_count = sum(max(0, int(value)) for value in observation["private"].get("shed", {}).values())
    labels.append("inventory:pressured" if shed_count >= 80 else "inventory:not_pressured")
    return labels


def _importance(action: Mapping[str, Any]) -> set[str]:
    categories: set[str] = set()
    values = [*_units(action), *[list(value) for value in action.get("market") or []]]
    for value in values:
        if not value:
            continue
        op = str(value[0])
        item = str(value[1]) if len(value) >= 2 else ""
        if op == "HIRE":
            categories.add("hire")
        if op == "BUY_PRODUCT" and item == "WHEAT":
            categories.add("feed_procurement")
        if op in {"NORTH", "SOUTH", "EAST", "WEST", "PICKUP", "PLACE", "DROP"}:
            categories.add("transport")
        if op in {"HARVEST", "COLLECT_FERTILIZER"}:
            categories.add("collection")
        if op == "SELL":
            categories.add("sale")
        if op in {"BUY_SEED", "BUY_ANIMAL", "BUY_LAND", "BUILD_COOP", "BUILD_PASTURE"}:
            categories.add("reinvestment")
        if op == "DIG":
            categories.add("exit_or_conversion")
    return categories or {"routine_or_pass"}


def _update(counter: dict[str, Counter[str]], key: str, exact: bool) -> None:
    counter[key]["total"] += 1
    counter[key]["exact"] += int(exact)


def _rates(counter: dict[str, Counter[str]]) -> dict[str, Any]:
    result = {}
    for key, values in sorted(counter.items()):
        total = int(values["total"])
        result[key] = {"total": total, "exact": int(values["exact"]), "accuracy": values["exact"] / max(1, total)}
    return result


def _selected_teacher_rows() -> list[dict[str, Any]]:
    source = json.loads((SOURCE_EXPERIMENT / "source_manifest.json").read_text(encoding="utf-8"))
    split = json.loads((SOURCE_EXPERIMENT / "split_manifest.json").read_text(encoding="utf-8"))["assignments"]
    rows = [
        row
        for row in source["files"]
        if int(row["submission_id"]) == TEACHER_SUBMISSION and split[str(row["episode_id"])] == "test"
    ]
    rows.sort(key=lambda row: hashlib.sha256(f"round6-imitation:{row['episode_id']}".encode()).hexdigest())
    return rows[:8]


def main(candidate: str = "round6_full_action_bc") -> None:
    preregistration = json.loads((EXPERIMENT / "preregistration.json").read_text(encoding="utf-8"))
    if candidate not in preregistration["arms"]:
        raise ValueError(f"unknown candidate: {candidate}")
    archive = ROOT / preregistration["arms"][candidate]["archive"]
    run_root, extracted = prepare_archives([candidate])
    module = _load_module(extracted[candidate])
    selected = _selected_teacher_rows()
    exact: dict[str, Counter[str]] = defaultdict(Counter)
    actor_class: dict[str, Counter[str]] = defaultdict(Counter)
    market_class: dict[str, Counter[str]] = defaultdict(Counter)
    per_episode: list[dict[str, Any]] = []
    for episode_number, row in enumerate(selected, 1):
        path = ROOT / str(row["path"])
        if sha256(path) != row["sha256"]:
            raise RuntimeError(f"teacher replay hash mismatch: {path}")
        replay = json.loads(path.read_text(encoding="utf-8"))
        seat = int(row["seat"])
        module.reset_runtime_state()
        episode_counter: dict[str, Counter[str]] = defaultdict(Counter)
        previous_teacher: Mapping[str, Any] | None = None
        previous_shops: list[str] = []
        corrections = Counter()
        for step in range(len(replay["steps"]) - 1):
            observation = restore_observation(replay["steps"][step], seat, step)
            teacher = replay["steps"][step + 1][seat].get("action") or {
                "farmer": ["PASS"],
                "hands": [],
                "market": [],
            }
            _prime_teacher_history(module, seat, previous_teacher)
            runtime_snapshot = {
                "history": copy.deepcopy(module._history),
                "previous_market": copy.deepcopy(module._previous_market),
                "previous_actor": copy.deepcopy(module._previous_actor),
                "probes": copy.deepcopy(module._probes),
                "stats": copy.deepcopy(module._stats),
            }
            raw = _raw_prediction(module, observation, seat)["action"]
            module._history = runtime_snapshot["history"]
            module._previous_market = runtime_snapshot["previous_market"]
            module._previous_actor = runtime_snapshot["previous_actor"]
            module._probes = runtime_snapshot["probes"]
            module._stats = runtime_snapshot["stats"]
            final = module.agent(observation, None)
            contexts = _context_labels(observation, previous_shops)
            importance = _importance(teacher)
            for stage, prediction in (("raw_decode", raw), ("final_archive", final)):
                joint = prediction == teacher
                _update(exact, f"stage:{stage}:joint_action", joint)
                _update(episode_counter, f"stage:{stage}:joint_action", joint)
                for label in contexts:
                    _update(exact, f"stage:{stage}:{label}", joint)
                for label in importance:
                    _update(exact, f"stage:{stage}:importance:{label}", joint)
            corrections["turns"] += 1
            corrections["any_raw_to_final_change"] += int(raw != final)
            raw_units, final_units, teacher_units = _units(raw), _units(final), _units(teacher)
            actor_count = max(len(raw_units), len(final_units), len(teacher_units))
            for index in range(actor_count):
                teacher_action = teacher_units[index] if index < len(teacher_units) else ["PASS"]
                teacher_token = _action_token(module, teacher_action)
                for stage, units in (("raw", raw_units), ("final", final_units)):
                    predicted = units[index] if index < len(units) else ["PASS"]
                    token = _action_token(module, predicted)
                    actor_class[f"{stage}:{teacher_token}"]["total"] += 1
                    actor_class[f"{stage}:{teacher_token}"]["token_exact"] += int(token == teacher_token)
                    actor_class[f"{stage}:{teacher_token}"]["action_exact"] += int(predicted == teacher_action)
                    if len(teacher_action) >= 3:
                        actor_class[f"{stage}:{teacher_token}"]["quantity_total"] += 1
                        actor_class[f"{stage}:{teacher_token}"]["quantity_and_token_exact"] += int(
                            token == teacher_token and _quantity(predicted) == _quantity(teacher_action)
                        )
                        if token == teacher_token:
                            actor_class[f"{stage}:{teacher_token}"]["quantity_token_correct_total"] += 1
                            actor_class[f"{stage}:{teacher_token}"]["quantity_exact_given_token"] += int(
                                _quantity(predicted) == _quantity(teacher_action)
                            )
            teacher_orders = [list(value) for value in teacher.get("market") or []]
            for stage, orders in (("raw", raw.get("market") or []), ("final", final.get("market") or [])):
                orders = [list(value) for value in orders]
                _update(exact, f"stage:{stage}:market_order_sequence", orders == teacher_orders)
                slot_count = max(len(orders), len(teacher_orders)) + 1
                for slot in range(slot_count):
                    teacher_order = teacher_orders[slot] if slot < len(teacher_orders) else []
                    predicted_order = orders[slot] if slot < len(orders) else []
                    teacher_token = _market_token(module, teacher_order)
                    token = _market_token(module, predicted_order)
                    market_class[f"{stage}:{teacher_token}"]["total"] += 1
                    market_class[f"{stage}:{teacher_token}"]["token_exact"] += int(token == teacher_token)
                    market_class[f"{stage}:{teacher_token}"]["order_exact"] += int(predicted_order == teacher_order)
                    if len(teacher_order) >= 3:
                        market_class[f"{stage}:{teacher_token}"]["quantity_total"] += 1
                        market_class[f"{stage}:{teacher_token}"]["quantity_and_token_exact"] += int(
                            token == teacher_token and _quantity(predicted_order) == _quantity(teacher_order)
                        )
                        if token == teacher_token:
                            market_class[f"{stage}:{teacher_token}"]["quantity_token_correct_total"] += 1
                            market_class[f"{stage}:{teacher_token}"]["quantity_exact_given_token"] += int(
                                _quantity(predicted_order) == _quantity(teacher_order)
                            )
            previous_teacher = teacher
            previous_shops = list(observation.get("town", {}).get("unlocked_shops", []))
        per_episode.append(
            {
                "episode_id": int(row["episode_id"]),
                "seat": seat,
                "source_path": str(path.relative_to(ROOT)),
                "source_sha256": row["sha256"],
                "decisions": len(replay["steps"]) - 1,
                "raw_joint_accuracy": episode_counter["stage:raw_decode:joint_action"]["exact"]
                / max(1, episode_counter["stage:raw_decode:joint_action"]["total"]),
                "final_joint_accuracy": episode_counter["stage:final_archive:joint_action"]["exact"]
                / max(1, episode_counter["stage:final_archive:joint_action"]["total"]),
                "raw_to_final_changed_turns": int(corrections["any_raw_to_final_change"]),
            }
        )
        print(f"episode {episode_number}/{len(selected)} id={row['episode_id']}", flush=True)
    actor_rates = {}
    for key, values in sorted(actor_class.items()):
        total = int(values["total"])
        actor_rates[key] = {
            "total": total,
            "token_accuracy": values["token_exact"] / max(1, total),
            "full_action_accuracy": values["action_exact"] / max(1, total),
            "quantity_applicable": int(values["quantity_total"]),
            "quantity_and_token_accuracy": values["quantity_and_token_exact"]
            / max(1, values["quantity_total"]),
            "quantity_accuracy_given_token_correct": values["quantity_exact_given_token"]
            / max(1, values["quantity_token_correct_total"]),
        }
    market_rates = {}
    for key, values in sorted(market_class.items()):
        total = int(values["total"])
        market_rates[key] = {
            "total": total,
            "token_accuracy": values["token_exact"] / max(1, total),
            "full_order_accuracy": values["order_exact"] / max(1, total),
            "quantity_applicable": int(values["quantity_total"]),
            "quantity_and_token_accuracy": values["quantity_and_token_exact"]
            / max(1, values["quantity_total"]),
            "quantity_accuracy_given_token_correct": values["quantity_exact_given_token"]
            / max(1, values["quantity_token_correct_total"]),
        }
    actor_macro = {}
    for stage in ("raw", "final"):
        rows = [value for key, value in actor_rates.items() if key.startswith(f"{stage}:") and value["total"]]
        actor_macro[stage] = {
            "token_macro_accuracy": sum(row["token_accuracy"] for row in rows) / max(1, len(rows)),
            "full_action_macro_accuracy": sum(row["full_action_accuracy"] for row in rows) / max(1, len(rows)),
            "classes": len(rows),
        }
    actor_micro = {}
    market_micro = {}
    for stage in ("raw", "final"):
        actor_values = [values for key, values in actor_class.items() if key.startswith(f"{stage}:")]
        market_values = [values for key, values in market_class.items() if key.startswith(f"{stage}:")]
        actor_total = sum(values["total"] for values in actor_values)
        actor_quantity_total = sum(values["quantity_total"] for values in actor_values)
        market_total = sum(values["total"] for values in market_values)
        market_quantity_total = sum(values["quantity_total"] for values in market_values)
        actor_micro[stage] = {
            "total": int(actor_total),
            "token_accuracy": sum(values["token_exact"] for values in actor_values) / max(1, actor_total),
            "full_action_accuracy": sum(values["action_exact"] for values in actor_values)
            / max(1, actor_total),
            "quantity_applicable": int(actor_quantity_total),
            "quantity_and_token_accuracy": sum(
                values["quantity_and_token_exact"] for values in actor_values
            )
            / max(1, actor_quantity_total),
        }
        market_micro[stage] = {
            "total": int(market_total),
            "token_accuracy": sum(values["token_exact"] for values in market_values) / max(1, market_total),
            "full_order_accuracy": sum(values["order_exact"] for values in market_values)
            / max(1, market_total),
            "quantity_applicable": int(market_quantity_total),
            "quantity_and_token_accuracy": sum(
                values["quantity_and_token_exact"] for values in market_values
            )
            / max(1, market_quantity_total),
        }
    payload = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "candidate": candidate,
        "archive": str(archive.relative_to(ROOT)),
        "archive_sha256": sha256(archive),
        "extraction_root": str(run_root),
        "teacher_submission": TEACHER_SUBMISSION,
        "split": "test",
        "selection_rule": "eight teacher episodes with lowest SHA-256 of round6-imitation:<episode_id>",
        "teacher_forced_history": True,
        "future_or_identity_runtime_inputs": False,
        "episodes": per_episode,
        "stratified_exact_match": _rates(exact),
        "actor_by_teacher_class": actor_rates,
        "actor_macro": actor_macro,
        "actor_micro": actor_micro,
        "market_by_teacher_class": market_rates,
        "market_micro": market_micro,
        "stage_limit": (
            "raw argmax and raw quantity decode are separately measured; the frozen archive combines legality and "
            "economic corrections internally, so those two correction sub-stages cannot be disaggregated without "
            "creating a different artifact"
        ),
        "representation_oracle_is_not_model_accuracy": True,
    }
    suffix = "" if candidate == "round6_full_action_bc" else f"_{candidate}"
    write_json(EXPERIMENT / f"imitation_metrics{suffix}.json", payload)
    with (EXPERIMENT / f"imitation_episodes{suffix}.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(per_episode[0]))
        writer.writeheader()
        writer.writerows(per_episode)
    print(
        json.dumps(
            {
                "episodes": len(per_episode),
                "raw_joint": payload["stratified_exact_match"]["stage:raw_decode:joint_action"],
                "final_joint": payload["stratified_exact_match"]["stage:final_archive:joint_action"],
                "actor_macro": actor_macro,
                "actor_micro": actor_micro,
                "market_micro": market_micro,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default="round6_full_action_bc")
    arguments = parser.parse_args()
    main(arguments.candidate)
