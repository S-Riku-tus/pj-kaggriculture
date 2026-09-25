"""Round7 execution contracts layered around the independent learned policy.

The token and quantity choices still come from the four learned full-action
heads.  The ledger makes quantities sequentially feasible.  The optional plan
executor only starts a livestock job after the learned policy emits a related
PICKUP/PLACE/BUY action, then tracks completion from observations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import policy as _policy

_plans: dict[int, dict[str, Any]] = {}
_trace: dict[int, list[dict[str, Any]]] = {}
_SHED_ACCESS = ((4, 4), (5, 4), (4, 5), (5, 5))
_ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}


def reset_runtime_state() -> None:
    _policy.reset_runtime_state()
    _plans.clear()
    _trace.clear()


def _number(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _actor_quantity(features: np.ndarray, token: str) -> int:
    if not token.startswith(("PICKUP:", "PLACE:")):
        return 1
    return _policy._predicted_quantity(
        _policy.ACTOR_QUANTITY_MODEL,
        np.concatenate((features, _policy._token_one_hot(token, _policy.ACTOR_TOKENS))),
    )


def _pick_actor(
    observation: Mapping[str, Any],
    index: int,
    previous_token: str,
    history: Any,
    reserved: dict[str, int],
    current_tokens: list[str],
) -> list[Any]:
    features = _policy._actor_features(observation, index, previous_token, history, current_tokens)
    probability = _policy.ACTOR_MODEL.probabilities(features)
    _policy._stats["inference_calls"] += 1
    _policy._stats["actor_decisions"] += 1
    ranking = sorted(
        zip(_policy.ACTOR_MODEL.classes, probability, strict=True),
        key=lambda pair: -float(pair[1]),
    )
    legal = _policy.legal_actor_tokens(observation, index, reserved)
    _policy._stats["legality_masks"] += 1
    token = next((str(candidate) for candidate, _score in ranking if candidate in legal), "PASS")
    quantity = _actor_quantity(features, token)
    _farm, position, inventory, tile = _policy.actor_context(observation, index)
    if token.startswith("PICKUP:"):
        item = token.split(":", 1)[1]
        available = _number(observation["private"]["shed"].get(item)) - _number(reserved.get(f"shed:{item}"))
        quantity = max(1, min(quantity, max(1, available)))
    elif token.startswith("PLACE:"):
        item = token.split(":", 1)[1]
        tile_map = tile if isinstance(tile, Mapping) else {}
        compatible = {"COOP": {"GOOSE"}, "PASTURE": {"COW", "SHEEP"}}
        animal_placement = not tile_map.get("animal") and item in compatible.get(str(tile_map.get("kind")), set())
        quantity = 1 if animal_placement else max(1, min(quantity, _number(inventory.get(item), 1)))
    _policy.reserve_actor_token(reserved, token, quantity)
    if token == "DROP" or token.startswith("PLACE:"):
        tile_map = tile if isinstance(tile, Mapping) else {}
        item = token.split(":", 1)[1] if ":" in token else None
        compatible = {"COOP": {"GOOSE"}, "PASTURE": {"COW", "SHEEP"}}
        animal_placement = bool(
            item and not tile_map.get("animal") and item in compatible.get(str(tile_map.get("kind")), set())
        )
        if _policy.shed_access(position) and not animal_placement:
            deposit = (
                sum(max(0, _number(value)) for value in inventory.values())
                if token == "DROP"
                else min(quantity, max(0, _number(inventory.get(item))))
            )
            reserved["shed:deposit"] = reserved.get("shed:deposit", 0) + deposit
    current_tokens.append(token)
    return _policy.token_action(token, quantity)


def _shed_after_actor(observation: Mapping[str, Any], units: list[list[Any]]) -> dict[str, int]:
    shed = {str(key): _number(value) for key, value in observation["private"]["shed"].items()}
    inventories = [
        {str(key): _number(value) for key, value in inventory.items()}
        for inventory in observation["private"]["inventories"]
    ]
    seat = _number(observation.get("player"))
    farm = observation["farms"][seat]
    positions = [farm["farmer"], *farm.get("hands", [])]
    for index, action in enumerate(units):
        if index >= len(inventories) or not action:
            continue
        op = str(action[0])
        item = str(action[1]) if len(action) > 1 else ""
        quantity = _number(action[2], 1) if len(action) > 2 else 1
        position = tuple(positions[index])
        inventory = inventories[index]
        x, y = position
        tile = farm["tiles"][y][x]
        tile_map = tile if isinstance(tile, Mapping) else {}
        compatible = {"COOP": {"GOOSE"}, "PASTURE": {"COW", "SHEEP"}}
        animal_placement = (
            op == "PLACE"
            and not tile_map.get("animal")
            and item in compatible.get(str(tile_map.get("kind")), set())
        )
        if op == "PICKUP" and position in _SHED_ACCESS:
            moved = min(quantity, max(0, shed.get(item, 0)))
            shed[item] = shed.get(item, 0) - moved
            inventory[item] = inventory.get(item, 0) + moved
        elif op == "PLACE" and position in _SHED_ACCESS and not animal_placement:
            room = max(0, 100 - sum(shed.values()))
            moved = min(quantity, max(0, inventory.get(item, 0)), room)
            shed[item] = shed.get(item, 0) + moved
            inventory[item] = inventory.get(item, 0) - moved
        elif op == "DROP" and position in _SHED_ACCESS:
            room = max(0, 100 - sum(shed.values()))
            for carried_item in list(inventory):
                moved = min(max(0, inventory[carried_item]), room)
                shed[carried_item] = shed.get(carried_item, 0) + moved
                room -= moved
            inventory.clear()
    return shed


def _market_quantity(features: np.ndarray, token: str) -> int:
    if token in {"EOS", "HIRE", "BUY_LAND"}:
        return 1
    return _policy._predicted_quantity(
        _policy.MARKET_QUANTITY_MODEL,
        np.concatenate((features, _policy._token_one_hot(token, _policy.MARKET_TOKENS))),
    )


def _decode_market(observation: Mapping[str, Any], history: Any, units: list[list[Any]]) -> list[list[Any]]:
    orders: list[list[Any]] = []
    previous = "EOS"
    bought: dict[str, int] = {}
    hired = lands = 0
    seat = _number(observation.get("player"))
    guaranteed_money = float(observation["farms"][seat].get("money", 0))
    shed = _shed_after_actor(observation, units)
    for slot in range(10):
        features = _policy.market_features(observation, slot, previous, history)
        probability = _policy.MARKET_MODEL.probabilities(features)
        _policy._stats["inference_calls"] += 1
        _policy._stats["market_decisions"] += 1
        ranking = sorted(
            zip(_policy.MARKET_MODEL.classes, probability, strict=True),
            key=lambda pair: -float(pair[1]),
        )
        _policy._stats["legality_masks"] += 1
        token = "EOS"
        quantity = 1
        cost = 0.0
        for candidate, _score in ranking:
            candidate = str(candidate)
            if candidate == "EOS":
                break
            candidate_quantity = _market_quantity(features, candidate)
            if candidate.startswith("SELL:"):
                item = candidate.split(":", 1)[1]
                available = max(0, shed.get(item, 0))
                if available <= 0:
                    _policy._stats["blocked_market_orders"] += 1
                    continue
                candidate_quantity = min(candidate_quantity, available)
            elif candidate.startswith(("BUY_PRODUCT:", "BUY_ANIMAL:")):
                if sum(shed.values()) + candidate_quantity > 100:
                    _policy._stats["blocked_market_orders"] += 1
                    continue
            candidate_cost = _policy._market_cost(observation, candidate, candidate_quantity, hired, lands, bought)
            if candidate_cost > guaranteed_money:
                _policy._stats["blocked_market_orders"] += 1
                continue
            token, quantity, cost = candidate, candidate_quantity, candidate_cost
            break
        if token == "EOS":
            break
        if token.startswith("SELL:"):
            item = token.split(":", 1)[1]
            shed[item] = max(0, shed.get(item, 0) - quantity)
            # Opponent orders can change the quote, but every successful sale is
            # guaranteed at least the engine's $1 floor.
            guaranteed_money += quantity
        else:
            guaranteed_money -= cost
            _policy._stats["resource_reservations"] += 1
            if token == "HIRE":
                hired += 1
            elif token == "BUY_LAND":
                lands += 1
            elif token.startswith("BUY_PRODUCT:"):
                item = token.split(":", 1)[1]
                bought[item] = bought.get(item, 0) + quantity
                shed[item] = shed.get(item, 0) + quantity
            elif token.startswith("BUY_ANIMAL:"):
                item = token.split(":", 1)[1]
                shed[item] = shed.get(item, 0) + quantity
        orders.append(_policy.token_order(token, quantity))
        previous = token
    return orders


def agent_ledger(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    seat = _number(observation.get("player"))
    prior_probes = _policy._probes.pop(seat, [])
    _policy._stats["model_action_checks"] += len(prior_probes)
    _policy._stats["model_action_successes"] += sum(
        _policy.actor_probe_succeeded(observation, probe) for probe in prior_probes
    )
    history = _policy._history.setdefault(seat, _policy.MarketHistory())
    history.update(observation, _policy._previous_market.get(seat))
    hand_count = len(observation["farms"][seat].get("hands", []))
    reserved: dict[str, int] = {}
    previous = _policy._previous_actor.get(seat, [])
    current_tokens: list[str] = []
    units = [
        _pick_actor(
            observation,
            index,
            previous[index] if index < len(previous) else "PASS",
            history,
            reserved,
            current_tokens,
        )
        for index in range(hand_count + 1)
    ]
    market = _decode_market(observation, history, units)
    _policy._probes[seat] = [
        _policy.make_actor_probe(observation, index, value)
        for index, value in enumerate(units)
        if value and value[0] != "PASS"
    ]
    _policy._previous_actor[seat] = [_policy.action_token(value) for value in units]
    _policy._previous_market[seat] = market
    return {"farmer": units[0], "hands": units[1:], "market": market}


def _animal_tiles(observation: Mapping[str, Any], seat: int) -> list[dict[str, Any]]:
    result = []
    for y, row in enumerate(observation["farms"][seat]["tiles"]):
        for x, tile in enumerate(row):
            if isinstance(tile, Mapping) and tile.get("animal"):
                result.append({"x": x, "y": y, **dict(tile)})
    return result


def _positions(observation: Mapping[str, Any], seat: int) -> list[tuple[int, int]]:
    farm = observation["farms"][seat]
    return [tuple(farm["farmer"]), *(tuple(value) for value in farm.get("hands", []))]


def _move_toward(source: tuple[int, int], target: tuple[int, int]) -> list[str]:
    if source[0] < target[0]:
        return ["EAST"]
    if source[0] > target[0]:
        return ["WEST"]
    if source[1] < target[1]:
        return ["SOUTH"]
    if source[1] > target[1]:
        return ["NORTH"]
    return ["PASS"]


def _nearest(source: tuple[int, int], targets: list[tuple[int, int]]) -> tuple[int, int]:
    return min(targets, key=lambda target: (abs(source[0] - target[0]) + abs(source[1] - target[1]), target))


def _learned_livestock_signal(action: Mapping[str, Any]) -> list[str]:
    signals = []
    units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
    for unit in units:
        if unit and (
            unit[:2] == ["PICKUP", "WHEAT"]
            or (unit[0] == "PLACE" and len(unit) > 1 and unit[1] in _ANIMAL_PRODUCT)
            or unit[0] in {"FEED", "CARE", "COLLECT_FERTILIZER"}
        ):
            signals.append(":".join(str(value) for value in unit[:2]))
    for order in action.get("market") or []:
        if order and order[0] == "BUY_ANIMAL":
            signals.append(":".join(str(value) for value in order[:2]))
    return signals


def _assign(
    actions: list[list[Any]],
    assigned: set[int],
    index: int,
    action: list[Any],
    reasons: list[dict[str, Any]],
    reason: str,
) -> None:
    if index in assigned:
        return
    before = actions[index]
    actions[index] = action
    assigned.add(index)
    reasons.append({"actor_index": index, "reason": reason, "before": before, "after": action})


def _apply_plan(observation: Mapping[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    seat = _number(observation.get("player"))
    step = 24 * _number(observation.get("day")) + _number(observation.get("hour"))
    signals = _learned_livestock_signal(base)
    animals = _animal_tiles(observation, seat)
    plan = _plans.get(seat)
    if signals and animals:
        if plan is None:
            plan = {
                "created_step": step,
                "source": "learned_full_action_output",
                "signals": [],
                "last_day": _number(observation.get("day")),
            }
            _plans[seat] = plan
        plan["signals"].extend({"step": step, "signal": signal} for signal in signals)
    if not animals:
        _plans.pop(seat, None)
        return base
    if plan is None or _number(observation.get("day")) >= 28:
        return base

    positions = _positions(observation, seat)
    inventories = observation["private"]["inventories"]
    actions = [list(base["farmer"]), *(list(value) for value in base.get("hands", []))]
    assigned: set[int] = set()
    reasons: list[dict[str, Any]] = []
    # Livestock completion must not consume the whole workforce and erase the
    # learned crop/land policy.  Tiny farms may use both available actors;
    # larger farms reserve roughly two thirds for non-livestock work.
    service_budget = len(positions) if len(positions) <= 2 else max(1, (len(positions) + 2) // 3)

    # Preserve products through the actual delivery stage before asking the
    # market to sell them.
    for index, inventory in enumerate(inventories):
        if len(assigned) >= service_budget:
            break
        products = [item for item in _ANIMAL_PRODUCT.values() if _number(inventory.get(item)) > 0]
        if not products:
            continue
        target = _nearest(positions[index], list(_SHED_ACCESS))
        action = (
            ["PLACE", products[0], _number(inventory.get(products[0]))]
            if positions[index] in _SHED_ACCESS
            else _move_toward(positions[index], target)
        )
        _assign(actions, assigned, index, action, reasons, "deliver_animal_product")

    unfed = [animal for animal in animals if not animal.get("fed_today")]
    targets = {(animal["x"], animal["y"]): animal for animal in unfed}
    carriers = sorted(
        (
            index
            for index, inventory in enumerate(inventories)
            if _number(inventory.get("WHEAT")) > 0 and index not in assigned
        ),
        key=lambda index: (-_number(inventories[index].get("WHEAT")), index),
    )
    for index in carriers:
        if not targets or len(assigned) >= service_budget:
            break
        target = _nearest(positions[index], list(targets))
        action = ["FEED"] if positions[index] == target else _move_toward(positions[index], target)
        _assign(actions, assigned, index, action, reasons, "complete_learned_feed_job")
        targets.pop(target, None)

    wheat_needed = max(0, len(targets) - sum(_number(inventory.get("WHEAT")) for inventory in inventories))
    shed_wheat = _number(observation["private"]["shed"].get("WHEAT"))
    if targets and not carriers and shed_wheat > 0 and len(assigned) < service_budget:
        candidates = [index for index in range(len(positions)) if index not in assigned]
        if candidates:
            index = min(
                candidates,
                key=lambda value: min(
                    abs(positions[value][0] - x) + abs(positions[value][1] - y) for x, y in _SHED_ACCESS
                ),
            )
            target = _nearest(positions[index], list(_SHED_ACCESS))
            amount = min(shed_wheat, max(1, len(targets)))
            action = (
                ["PICKUP", "WHEAT", amount]
                if positions[index] in _SHED_ACCESS
                else _move_toward(positions[index], target)
            )
            _assign(actions, assigned, index, action, reasons, "acquire_wheat_for_learned_feed_job")

    # After FEED has taken effect, CARE and initial collection are explicit
    # completion states rather than isolated classification labels.
    for animal in animals:
        if len(assigned) >= service_budget:
            break
        target = (animal["x"], animal["y"])
        desired = None
        reason = ""
        if animal.get("fed_today") and not animal.get("cared_today"):
            desired, reason = ["CARE"], "care_after_feed"
        elif _number(animal.get("yield_units")) > 0:
            desired, reason = ["HARVEST"], "collect_first_or_later_production"
        if desired is None:
            continue
        candidates = [index for index in range(len(positions)) if index not in assigned]
        if not candidates:
            break
        index = min(
            candidates, key=lambda value: abs(positions[value][0] - target[0]) + abs(positions[value][1] - target[1])
        )
        action = desired if positions[index] == target else _move_toward(positions[index], target)
        _assign(actions, assigned, index, action, reasons, reason)

    market = [list(value) for value in base.get("market", [])]
    if wheat_needed > shed_wheat and not any(order[:2] == ["BUY_PRODUCT", "WHEAT"] for order in market):
        market.append(["BUY_PRODUCT", "WHEAT", min(10, wheat_needed - shed_wheat)])
    for product in _ANIMAL_PRODUCT.values():
        amount = _number(observation["private"]["shed"].get(product))
        if amount > 0 and not any(order[:2] == ["SELL", product] for order in market):
            market.insert(0, ["SELL", product, amount])
    market = market[:10]
    result = {"farmer": actions[0], "hands": actions[1:], "market": market}

    # Quantity semantics: a learned pickup that starts a feed job requests the
    # actual remaining target count, not the unconditional modal quantity one.
    for action in actions:
        if action[:2] == ["PICKUP", "WHEAT"] and animals:
            available = _number(observation["private"]["shed"].get("WHEAT"))
            action[2] = min(max(1, len(unfed)), max(1, available))

    plan["last_day"] = _number(observation.get("day"))
    plan["stage"] = "feed" if unfed else "care_or_collect"
    _trace.setdefault(seat, []).append(
        {
            "step": step,
            "signals": signals,
            "plan": dict(plan),
            "service_budget": service_budget,
            "interventions": reasons,
            "base": base,
            "final": result,
        }
    )
    return result


def agent_plan(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    base = agent_ledger(observation, configuration)
    final = _apply_plan(observation, base)
    seat = _number(observation.get("player"))
    units = [final["farmer"], *final.get("hands", [])]
    _policy._previous_actor[seat] = [_policy.action_token(value) for value in units]
    _policy._previous_market[seat] = final["market"]
    _policy._probes[seat] = [
        _policy.make_actor_probe(observation, index, value)
        for index, value in enumerate(units)
        if value and value[0] != "PASS"
    ]
    return final


def diagnostics() -> dict[str, Any]:
    return {
        "arm": "round7_plan",
        "plans": _plans,
        "trace": _trace,
        "base": _policy.policy_diagnostics(),
    }
