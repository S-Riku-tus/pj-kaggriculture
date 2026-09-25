"""Round9 A2: learned policy on accepted actor and market prefix states.

The learned token and quantity heads are unchanged in the F1/F2 arms.  This
module separates model requests, legality, the quantity ledger, the optional
livestock plan, the final engine-order resolver, and the next-observation
effect check.  Trace records own deep copies so a later step cannot mutate an
earlier record.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import spatial_policy as _policy

_plans: dict[int, dict[str, Any]] = {}
_trace: dict[int, list[dict[str, Any]]] = {}
_pending: dict[int, dict[str, Any]] = {}
_SHED_ACCESS = ((4, 4), (5, 4), (4, 5), (5, 5))
_ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
_CROP_FIRST_YIELD = {"WHEAT": 2, "CARROT": 2, "TOMATO": 8, "STRAWBERRY": 10, "MELON": 10}
_CROP_MAX_YIELD_DAY = {"WHEAT": 4, "CARROT": 3, "TOMATO": 8, "STRAWBERRY": 10, "MELON": 12}
_CROP_MAX_YIELD = {"WHEAT": 6, "CARROT": 4, "TOMATO": 4, "STRAWBERRY": 4, "MELON": 6}
_ONGOING_CROPS = {"TOMATO", "STRAWBERRY"}
_SCHEMA_SIMPLE = {
    "PASS",
    "NORTH",
    "SOUTH",
    "EAST",
    "WEST",
    "WATER",
    "HARVEST",
    "FERTILIZE",
    "CARE",
    "FEED",
    "COLLECT_FERTILIZER",
    "DIG",
    "DROP",
    "BUILD_COOP",
    "BUILD_PASTURE",
}


def reset_runtime_state() -> None:
    _policy.reset_runtime_state()
    _plans.clear()
    _trace.clear()
    _pending.clear()


def _number(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _step(observation: Mapping[str, Any]) -> int:
    return 24 * _number(observation.get("day")) + _number(observation.get("hour"))


def _target_identity(tile: Any, position: Sequence[int]) -> dict[str, Any]:
    value = _mapping(tile)
    return {
        "position": list(position),
        "kind": value.get("kind"),
        "resource": value.get("crop", value.get("animal")),
        "generation": value.get("planted_day", value.get("placed_day")),
        "yield_units": _number(value.get("yield_units")),
    }


def _actor_quantity(features: np.ndarray, token: str) -> int:
    if not token.startswith(("PICKUP:", "PLACE:")):
        return 1
    return _policy._predicted_quantity(
        _policy.ACTOR_QUANTITY_MODEL,
        np.concatenate((features, _policy._token_one_hot(token, _policy.ACTOR_TOKENS))),
    )


def _market_quantity(features: np.ndarray, token: str) -> int:
    if token in {"EOS", "HIRE", "BUY_LAND"}:
        return 1
    return _policy._predicted_quantity(
        _policy.MARKET_QUANTITY_MODEL,
        np.concatenate((features, _policy._token_one_hot(token, _policy.MARKET_TOKENS))),
    )


def _contract_legal_tokens(
    observation: Mapping[str, Any], actor_index: int, reserved: Mapping[str, int], *, full_contract: bool
) -> set[str]:
    """Return executable candidates, keeping economic priority out of legality."""
    legal = set(_policy.legal_actor_tokens(observation, actor_index, reserved))
    _farm, _position, _inventory, tile = _policy.actor_context(observation, actor_index)
    tile_map = _mapping(tile)
    if tile_map.get("kind") == "PLANT":
        age = _number(observation.get("day")) - _number(tile_map.get("planted_day"))
        crop = str(tile_map.get("crop", ""))
        mature = age >= _CROP_FIRST_YIELD.get(crop, 10**9)
        if not (mature and _number(tile_map.get("yield_units")) > 0):
            legal.discard("HARVEST")
    elif tile_map.get("animal"):
        if _number(tile_map.get("yield_units")) > 0:
            legal.add("HARVEST")
        else:
            legal.discard("HARVEST")
        # The fixed 1.32.7 engine permits CARE before FEED.  F1 deliberately
        # isolates the HARVEST repair; F2 enables the complete engine contract.
        if full_contract and not tile_map.get("cared_today"):
            legal.add("CARE")
    return legal


def _decode_actor(
    feature_observation: Mapping[str, Any],
    legality_observation: Mapping[str, Any],
    index: int,
    previous_token: str,
    history: Any,
    reserved: dict[str, int],
    current_tokens: list[Any],
    *,
    full_contract: bool,
) -> tuple[list[Any], dict[str, Any]]:
    # A2 was trained on the accepted same-turn prefix state.
    features = _policy._actor_features(feature_observation, index, previous_token, history, current_tokens)
    probabilities = _policy.ACTOR_MODEL.probabilities(features)
    _policy._stats["inference_calls"] += 1
    _policy._stats["actor_decisions"] += 1
    ranking = sorted(zip(_policy.ACTOR_MODEL.classes, probabilities, strict=True), key=lambda pair: -float(pair[1]))
    raw_token = str(ranking[0][0])
    raw_quantity = _actor_quantity(features, raw_token)
    # The prefix state has already consumed resources.  Passing reservations
    # here as well would double-subtract them.
    legal = _contract_legal_tokens(legality_observation, index, {}, full_contract=full_contract)
    _policy._stats["legality_masks"] += 1
    token = next((str(candidate) for candidate, _score in ranking if str(candidate) in legal), "PASS")
    requested_quantity = raw_quantity if token == raw_token else _actor_quantity(features, token)
    quantity = requested_quantity
    _farm, position, inventory, tile = _policy.actor_context(legality_observation, index)
    if token.startswith("PICKUP:"):
        item = token.split(":", 1)[1]
        available = _number(legality_observation["private"]["shed"].get(item))
        quantity = min(max(1, quantity), max(1, available))
    elif token.startswith("PLACE:"):
        item = token.split(":", 1)[1]
        tile_map = _mapping(tile)
        compatible = {"COOP": {"GOOSE"}, "PASTURE": {"COW", "SHEEP"}}
        animal_placement = not tile_map.get("animal") and item in compatible.get(str(tile_map.get("kind")), set())
        quantity = 1 if animal_placement else min(max(1, quantity), max(1, _number(inventory.get(item))))
    _policy.reserve_actor_token(reserved, token, quantity)
    if token == "DROP" or token.startswith("PLACE:"):
        tile_map = _mapping(tile)
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
    action = _policy.token_action(token, quantity)
    return action, {
        "actor_index": index,
        "position": list(position),
        "raw_model": {
            "token": raw_token,
            "quantity": raw_quantity,
            "top5": [[str(candidate), float(score)] for candidate, score in ranking[:5]],
        },
        "mask_candidates": sorted(legal),
        "mask": {"token": token, "quantity": requested_quantity},
        "ledger": copy.deepcopy(action),
        "target": _target_identity(tile, position),
    }


def _simulate_shed_after_actors(observation: Mapping[str, Any], units: list[list[Any]]) -> dict[str, int]:
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
        tile_map = _mapping(tile)
        compatible = {"COOP": {"GOOSE"}, "PASTURE": {"COW", "SHEEP"}}
        animal_placement = (
            op == "PLACE" and not tile_map.get("animal") and item in compatible.get(str(tile_map.get("kind")), set())
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


def _spawn_hand(farm: dict[str, Any]) -> list[int]:
    occupants = {tile: 0 for tile in _SHED_ACCESS}
    for position in [farm["farmer"], *farm.get("hands", [])]:
        value = tuple(position)
        if value in occupants:
            occupants[value] += 1
    order = list(_SHED_ACCESS)
    return list(min(occupants, key=lambda value: (occupants[value], order.index(value))))


def _refresh_market_prices(shadow: dict[str, Any]) -> None:
    market = shadow["market"]
    for item in market.get("prices", {}):
        market["prices"][item] = _policy.market_price(item, _number(market["inventory"].get(item)))


def _apply_market_prefix_order(
    shadow: dict[str, Any], requested: list[Any]
) -> tuple[list[Any] | None, dict[str, Any]]:
    """Apply one own order with fixed-engine partial-fill semantics.

    Opponent orders are intentionally unknown.  Quotes therefore use the
    observed market plus the learner's already accepted own prefix only.
    """
    seat = _number(shadow.get("player"))
    farm = shadow["farms"][seat]
    private = shadow["private"]
    before = {
        "money": float(farm.get("money", 0)),
        "shed": copy.deepcopy(private.get("shed", {})),
        "seeds": copy.deepcopy(private.get("seeds", {})),
    }
    if not isinstance(requested, list) or not requested:
        return None, {"requested": copy.deepcopy(requested), "reason": "schema_rejected", "accepted_quantity": 0}
    op = str(requested[0])
    if op == "HIRE":
        cost = _policy._fib(_number(farm.get("hires_today")))
        if cost > float(farm.get("money", 0)):
            return None, {"requested": copy.deepcopy(requested), "reason": "insufficient_funds", "accepted_quantity": 0}
        farm["money"] = float(farm.get("money", 0)) - cost
        farm["hires_today"] = _number(farm.get("hires_today")) + 1
        farm.setdefault("hands", []).append(_spawn_hand(farm))
        private.setdefault("inventories", []).append({})
        return ["HIRE"], {"requested": copy.deepcopy(requested), "reason": "accepted", "accepted_quantity": 1, "before": before}
    if op == "BUY_LAND":
        unlocked = farm.setdefault("unlocked_quadrants", ["NW"])
        extra = len(unlocked) - 1
        if extra >= len(_policy.LAND_COST) or _policy.LAND_COST[extra] > float(farm.get("money", 0)):
            return None, {"requested": copy.deepcopy(requested), "reason": "unavailable_or_insufficient_funds", "accepted_quantity": 0}
        farm["money"] = float(farm.get("money", 0)) - _policy.LAND_COST[extra]
        quadrant = ("NE", "SW", "SE")[extra]
        unlocked.append(quadrant)
        for y, row in enumerate(farm["tiles"]):
            for x, tile in enumerate(row):
                in_quadrant = ("N" if y < 5 else "S") + ("W" if x < 5 else "E")
                if in_quadrant == quadrant and tile == "LOCKED":
                    row[x] = None
        return ["BUY_LAND"], {"requested": copy.deepcopy(requested), "reason": "accepted", "accepted_quantity": 1, "before": before}
    if op not in {"SELL", "BUY_SEED", "BUY_PRODUCT", "BUY_ANIMAL"} or len(requested) < 3:
        return None, {"requested": copy.deepcopy(requested), "reason": "schema_rejected", "accepted_quantity": 0}
    item = str(requested[1])
    remaining = max(0, _number(requested[2]))
    accepted = 0
    shed = private["shed"]
    seeds = private["seeds"]
    market = shadow["market"]
    while remaining > 0:
        if op == "SELL":
            if _number(shed.get(item)) <= 0 or item not in market.get("inventory", {}):
                break
            price = _policy.market_price(item, _number(market["inventory"].get(item)))
            shed[item] = _number(shed.get(item)) - 1
            farm["money"] = float(farm.get("money", 0)) + price
            if price > 1:
                market["inventory"][item] = _number(market["inventory"].get(item)) + 1
        elif op == "BUY_SEED":
            cost = _policy.SEED_COST.get(item)
            if cost is None or float(farm.get("money", 0)) < cost:
                break
            farm["money"] = float(farm.get("money", 0)) - cost
            seeds[item] = _number(seeds.get(item)) + 1
        elif op == "BUY_ANIMAL":
            cost = _policy.ANIMAL_COST.get(item)
            if cost is None or float(farm.get("money", 0)) < cost or sum(_number(v) for v in shed.values()) >= 100:
                break
            farm["money"] = float(farm.get("money", 0)) - cost
            shed[item] = _number(shed.get(item)) + 1
        else:
            if item not in {"WHEAT", "FERTILIZER"} or _number(market["inventory"].get(item)) <= 0:
                break
            price = _policy.market_price(item, _number(market["inventory"].get(item)) - 1)
            if float(farm.get("money", 0)) < price or sum(_number(v) for v in shed.values()) >= 100:
                break
            farm["money"] = float(farm.get("money", 0)) - price
            shed[item] = _number(shed.get(item)) + 1
            market["inventory"][item] = _number(market["inventory"].get(item)) - 1
        accepted += 1
        remaining -= 1
    _refresh_market_prices(shadow)
    resolved = [op, item, accepted] if accepted else None
    return resolved, {
        "requested": copy.deepcopy(requested),
        "final": copy.deepcopy(resolved),
        "reason": "accepted" if accepted == _number(requested[2]) else "partial_fill" if accepted else "not_executable",
        "accepted_quantity": accepted,
        "before": before,
        "money_after": float(farm.get("money", 0)),
    }


def _decode_market(
    shadow: dict[str, Any], history: Any, units: list[list[Any]]
) -> tuple[list[list[Any]], list[dict[str, Any]]]:
    orders: list[list[Any]] = []
    traces: list[dict[str, Any]] = []
    previous = "EOS"
    del units
    for slot in range(10):
        features = _policy.market_features(shadow, slot, previous, history)
        probability = _policy.MARKET_MODEL.probabilities(features)
        _policy._stats["inference_calls"] += 1
        _policy._stats["market_decisions"] += 1
        ranking = sorted(zip(_policy.MARKET_MODEL.classes, probability, strict=True), key=lambda pair: -float(pair[1]))
        raw_token = str(ranking[0][0])
        raw_quantity = _market_quantity(features, raw_token)
        _policy._stats["legality_masks"] += 1
        token, quantity = "EOS", 1
        accepted_order: list[Any] | None = None
        rejected: list[dict[str, Any]] = []
        for candidate_value, _score in ranking:
            candidate = str(candidate_value)
            if candidate == "EOS":
                break
            candidate_quantity = _market_quantity(features, candidate)
            trial = copy.deepcopy(shadow)
            resolved, resolution = _apply_market_prefix_order(trial, _policy.token_order(candidate, candidate_quantity))
            if resolved is None:
                rejected.append({"token": candidate, "reason": resolution["reason"]})
                _policy._stats["blocked_market_orders"] += 1
                continue
            shadow.clear()
            shadow.update(trial)
            token, quantity, accepted_order = candidate, resolution["accepted_quantity"], resolved
            break
        traces.append(
            {
                "slot": slot,
                "raw_model": {"token": raw_token, "quantity": raw_quantity},
                "ledger": {"token": token, "quantity": quantity},
                "rejected": rejected,
            }
        )
        if token == "EOS":
            break
        _policy._stats["resource_reservations"] += 1
        orders.append(copy.deepcopy(accepted_order or _policy.token_order(token, quantity)))
        previous = token
    return orders, traces


def _decode_ledger(observation: Mapping[str, Any], *, full_contract: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    seat = _number(observation.get("player"))
    history = _policy._history.setdefault(seat, _policy.MarketHistory())
    history.update(observation, _policy._previous_market.get(seat))
    hand_count = len(observation["farms"][seat].get("hands", []))
    reserved: dict[str, int] = {}
    previous = _policy._previous_actor.get(seat, [])
    current_tokens: list[Any] = []
    units: list[list[Any]] = []
    actor_trace: list[dict[str, Any]] = []
    prefix_shadow = copy.deepcopy(dict(observation)) if hasattr(_policy, "make_prefix_entry") else None
    prefix_plant_remaining = (
        {
            str(crop): max(0, _number(value))
            for crop, value in prefix_shadow["private"].get("seeds", {}).items()
        }
        if prefix_shadow is not None
        else {}
    )
    for index in range(hand_count + 1):
        action, record = _decode_actor(
            prefix_shadow if prefix_shadow is not None else observation,
            prefix_shadow if prefix_shadow is not None else observation,
            index,
            previous[index] if index < len(previous) else "PASS",
            history,
            reserved,
            current_tokens,
            full_contract=full_contract,
        )
        units.append(action)
        actor_trace.append(record)
        if prefix_shadow is not None:
            resolved, effect = _resolve_actor(prefix_shadow, index, action, prefix_plant_remaining)
            current_tokens.append(
                _policy.make_prefix_entry(
                    record["mask"]["token"],
                    record["ledger"][2] if len(record["ledger"]) >= 3 else 1,
                    effect["target_before"],
                    bool(effect["expected_effect"]),
                    resolved,
                )
            )
        else:
            current_tokens.append(record["mask"]["token"])
    market, market_trace = _decode_market(prefix_shadow, history, units)
    action = {"farmer": units[0], "hands": units[1:], "market": market}
    return action, {"actors": actor_trace, "market": market_trace, "reservations": copy.deepcopy(reserved)}


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
            or unit[0] in {"HARVEST", "FEED", "CARE", "COLLECT_FERTILIZER"}
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
    before = copy.deepcopy(actions[index])
    actions[index] = copy.deepcopy(action)
    assigned.add(index)
    reasons.append({"actor_index": index, "reason": reason, "before": before, "after": copy.deepcopy(action)})


def _apply_plan(
    observation: Mapping[str, Any], base: dict[str, Any], *, repaired_endgame: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    seat = _number(observation.get("player"))
    step = _step(observation)
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
        return copy.deepcopy(base), {"active": False, "interventions": []}
    day = _number(observation.get("day"))
    if plan is None or (day >= 28 and not repaired_endgame):
        return copy.deepcopy(base), {"active": plan is not None, "interventions": [], "endgame_stopped": day >= 28}

    positions = _positions(observation, seat)
    inventories = observation["private"]["inventories"]
    actions = [copy.deepcopy(base["farmer"]), *(copy.deepcopy(value) for value in base.get("hands", []))]
    assigned: set[int] = set()
    reasons: list[dict[str, Any]] = []
    service_budget = len(positions) if len(positions) <= 2 else max(1, (len(positions) + 2) // 3)

    # Products already carried must reach the shed before a market sale can use them.
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

    # Day 28+ is liquidation only: harvest, deliver, sell.  Do not spend the
    # remaining horizon maintaining production that cannot be monetized.
    liquidation = day >= 28
    if not liquidation:
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
            _assign(
                actions,
                assigned,
                index,
                ["FEED"] if positions[index] == target else _move_toward(positions[index], target),
                reasons,
                "complete_learned_feed_job",
            )
            targets.pop(target, None)
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
                _assign(
                    actions,
                    assigned,
                    index,
                    ["PICKUP", "WHEAT", amount]
                    if positions[index] in _SHED_ACCESS
                    else _move_toward(positions[index], target),
                    reasons,
                    "acquire_wheat_for_learned_feed_job",
                )
        wheat_needed = max(0, len(targets) - sum(_number(inventory.get("WHEAT")) for inventory in inventories))
    else:
        unfed, shed_wheat, wheat_needed = [], _number(observation["private"]["shed"].get("WHEAT")), 0

    for animal in animals:
        if len(assigned) >= service_budget:
            break
        target = (animal["x"], animal["y"])
        desired: list[Any] | None = None
        reason = ""
        if _number(animal.get("yield_units")) > 0:
            desired, reason = ["HARVEST"], "collect_first_or_later_production"
        elif not liquidation and animal.get("fed_today") and not animal.get("cared_today"):
            desired, reason = ["CARE"], "care_after_feed"
        if desired is None:
            continue
        candidates = [index for index in range(len(positions)) if index not in assigned]
        if not candidates:
            break
        index = min(
            candidates, key=lambda value: abs(positions[value][0] - target[0]) + abs(positions[value][1] - target[1])
        )
        _assign(
            actions,
            assigned,
            index,
            desired if positions[index] == target else _move_toward(positions[index], target),
            reasons,
            reason,
        )

    market = [copy.deepcopy(value) for value in base.get("market", [])]
    if (
        not liquidation
        and wheat_needed > shed_wheat
        and not any(order[:2] == ["BUY_PRODUCT", "WHEAT"] for order in market)
    ):
        market.append(["BUY_PRODUCT", "WHEAT", min(10, wheat_needed - shed_wheat)])
    for product in _ANIMAL_PRODUCT.values():
        amount = _number(observation["private"]["shed"].get(product))
        if amount > 0 and not any(order[:2] == ["SELL", product] for order in market):
            market.insert(0, ["SELL", product, amount])
    result = {"farmer": actions[0], "hands": actions[1:], "market": market[:10]}
    if plan is not None:
        plan["last_day"] = day
        plan["stage"] = "liquidate" if liquidation else "feed" if unfed else "care_or_collect"
    return result, {
        "active": True,
        "service_budget": service_budget,
        "liquidation": liquidation,
        "interventions": copy.deepcopy(reasons),
        "plan_snapshot": {
            "created_step": plan.get("created_step") if plan else None,
            "source": plan.get("source") if plan else None,
            "last_day": plan.get("last_day") if plan else None,
            "stage": plan.get("stage") if plan else None,
            "signal_count": len(plan.get("signals", [])) if plan else 0,
            "signals": copy.deepcopy(plan.get("signals", [])[-4:]) if plan else [],
        },
    }


def _shadow_context(shadow: dict[str, Any], actor_index: int) -> tuple[dict[str, Any], list[int], dict[str, int], Any]:
    seat = _number(shadow.get("player"))
    farm = shadow["farms"][seat]
    positions = [farm["farmer"], *farm.get("hands", [])]
    position = positions[actor_index]
    inventory = shadow["private"]["inventories"][actor_index]
    tile = farm["tiles"][position[1]][position[0]]
    return farm, position, inventory, tile


def _take(inventory: dict[str, int], item: str, quantity: int = 1) -> bool:
    if _number(inventory.get(item)) < quantity:
        return False
    inventory[item] = _number(inventory.get(item)) - quantity
    if inventory[item] <= 0:
        inventory.pop(item, None)
    return True


def _add(inventory: dict[str, int], item: str, quantity: int) -> None:
    inventory[item] = _number(inventory.get(item)) + quantity


def _resolve_actor(
    shadow: dict[str, Any], actor_index: int, requested: list[Any], plant_remaining: dict[str, int]
) -> tuple[list[Any], dict[str, Any]]:
    farm, position, inventory, tile = _shadow_context(shadow, actor_index)
    before_inventory = copy.deepcopy(inventory)
    before_target = _target_identity(tile, position)
    before_shed = copy.deepcopy(shadow["private"]["shed"])
    op = str(requested[0]) if requested else "PASS"
    final: list[Any] = ["PASS"]
    reason = "not_executable"
    effect: dict[str, Any] = {}
    x, y = position
    tile_map = _mapping(tile)
    if op in {"NORTH", "SOUTH", "EAST", "WEST"}:
        delta = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}[op]
        nx, ny = x + delta[0], y + delta[1]
        if 0 <= nx < 10 and 0 <= ny < 10:
            position[:] = [nx, ny]
            final, reason, effect = [op], "executable", {"position": [nx, ny]}
    elif op == "PASS":
        final, reason = ["PASS"], "schema_pass"
    elif op == "PICKUP" and len(requested) >= 2 and tuple(position) in _SHED_ACCESS:
        item = str(requested[1])
        quantity = max(1, _number(requested[2], 1) if len(requested) >= 3 else 1)
        moved = min(quantity, max(0, _number(shadow["private"]["shed"].get(item))))
        if moved > 0:
            shadow["private"]["shed"][item] = _number(shadow["private"]["shed"].get(item)) - moved
            _add(inventory, item, moved)
            final, reason, effect = ["PICKUP", item, moved], "quantity_clipped_to_available", {"moved": moved}
    elif op == "DROP" and tuple(position) in _SHED_ACCESS and sum(_number(v) for v in inventory.values()) > 0:
        room = max(0, 100 - sum(_number(v) for v in shadow["private"]["shed"].values()))
        moved: dict[str, int] = {}
        for item in list(inventory):
            amount = min(max(0, _number(inventory[item])), room)
            if amount > 0:
                _add(shadow["private"]["shed"], item, amount)
                moved[item] = amount
                room -= amount
            inventory.pop(item, None)  # fixed engine discards overflow
        final, reason, effect = ["DROP"], "executable", {"deposited": moved}
    elif op == "PLACE" and len(requested) >= 2:
        item = str(requested[1])
        compatible = {"COOP": {"GOOSE"}, "PASTURE": {"COW", "SHEEP"}}
        if (
            item in compatible.get(str(tile_map.get("kind")), set())
            and not tile_map.get("animal")
            and _take(inventory, item)
        ):
            farm["tiles"][y][x] = {
                "kind": "COOP" if item == "GOOSE" else "PASTURE",
                "animal": item,
                "placed_day": _number(shadow.get("day")),
                "yield_units": 0,
                "fed_today": False,
                "consecutive_unfed": 0,
                "cared_today": False,
                "fertilizer_available": False,
                "pending_care_bonus": 0,
            }
            final, reason, effect = ["PLACE", item, 1], "animal_placement", {"placed": 1}
        elif tuple(position) in _SHED_ACCESS:
            quantity = max(1, _number(requested[2], 1) if len(requested) >= 3 else 1)
            room = max(0, 100 - sum(_number(v) for v in shadow["private"]["shed"].values()))
            moved = min(quantity, max(0, _number(inventory.get(item))), room)
            if moved > 0:
                _take(inventory, item, moved)
                _add(shadow["private"]["shed"], item, moved)
                final, reason, effect = ["PLACE", item, moved], "shed_deposit", {"moved": moved}
    elif tile != "LOCKED":
        day = _number(shadow.get("day"))
        if op == "PLANT" and len(requested) >= 2 and tile is None:
            crop = str(requested[1])
            if crop in _CROP_FIRST_YIELD and plant_remaining.get(crop, 0) > 0:
                plant_remaining[crop] -= 1
                shadow["private"]["seeds"][crop] = _number(shadow["private"]["seeds"].get(crop)) - 1
                farm["tiles"][y][x] = {
                    "kind": "PLANT",
                    "crop": crop,
                    "planted_day": day,
                    "watered_today": False,
                    "consecutive_unwatered": 1,
                    "yield_units": 0 if crop in _ONGOING_CROPS else 1,
                    "max_lifespan_step": (-1 if crop in _ONGOING_CROPS else (day + _CROP_MAX_YIELD_DAY[crop] + 1) * 24),
                    "fertilized_until_day": -1,
                }
                final, reason, effect = ["PLANT", crop], "reserved_seed", {"generation": day}
        elif op == "WATER" and tile_map.get("kind") == "PLANT" and not tile_map.get("watered_today"):
            tile_map["watered_today"] = True
            crop = str(tile_map.get("crop"))
            if crop not in _ONGOING_CROPS:
                age = day - _number(tile_map.get("planted_day"))
                window_start = (_CROP_MAX_YIELD_DAY[crop] + 1) // 2
                if window_start <= age <= _CROP_MAX_YIELD_DAY[crop]:
                    bonus = 2 if _number(tile_map.get("fertilized_until_day"), -1) >= day else 1
                    tile_map["yield_units"] = min(
                        _CROP_MAX_YIELD[crop], _number(tile_map.get("yield_units")) + bonus
                    )
            final, reason, effect = ["WATER"], "executable", {"watered_today": True}
        elif op == "HARVEST" and _number(tile_map.get("yield_units")) > 0:
            product = None
            if tile_map.get("kind") == "PLANT":
                crop = str(tile_map.get("crop"))
                if day - _number(tile_map.get("planted_day")) >= _CROP_FIRST_YIELD.get(crop, 10**9):
                    product = crop
            elif tile_map.get("animal") in _ANIMAL_PRODUCT:
                product = _ANIMAL_PRODUCT[str(tile_map.get("animal"))]
            if product:
                units = _number(tile_map.get("yield_units"))
                _add(inventory, product, units)
                if tile_map.get("kind") == "PLANT" and tile_map.get("crop") in {"WHEAT", "CARROT", "MELON"}:
                    farm["tiles"][y][x] = None
                else:
                    tile_map["yield_units"] = 0
                final, reason, effect = ["HARVEST"], "mature_or_animal_yield", {"product": product, "units": units}
        elif op == "FERTILIZE" and tile_map.get("kind") == "PLANT" and _take(inventory, "FERTILIZER"):
            tile_map["fertilized_until_day"] = max(_number(tile_map.get("fertilized_until_day"), -1), day + 2)
            final, reason, effect = ["FERTILIZE"], "executable", {"until_day": day + 2}
        elif op == "DIG" and tile is not None and not tile_map.get("animal"):
            farm["tiles"][y][x] = None
            final, reason, effect = ["DIG"], "executable", {"removed": True}
        elif op in {"BUILD_COOP", "BUILD_PASTURE"} and tile is None:
            farm["tiles"][y][x] = {"kind": "COOP" if op == "BUILD_COOP" else "PASTURE"}
            final, reason, effect = [op], "executable", {"built": True}
        elif op == "FEED" and tile_map.get("animal") and not tile_map.get("fed_today") and _take(inventory, "WHEAT"):
            tile_map["fed_today"] = True
            final, reason, effect = ["FEED"], "executable", {"fed_today": True}
        elif op == "CARE" and tile_map.get("animal") and not tile_map.get("cared_today"):
            tile_map["cared_today"] = True
            final, reason, effect = ["CARE"], "engine_allows_without_same_day_feed", {"cared_today": True}
        elif op == "COLLECT_FERTILIZER" and tile_map.get("animal") and tile_map.get("fertilizer_available"):
            tile_map["fertilizer_available"] = False
            _add(inventory, "FERTILIZER", 1)
            final, reason, effect = ["COLLECT_FERTILIZER"], "executable", {"FERTILIZER": 1}
    after_tile = farm["tiles"][position[1]][position[0]]
    return final, {
        "actor_index": actor_index,
        "requested": copy.deepcopy(requested),
        "final": copy.deepcopy(final),
        "reason": reason,
        "model_requested_quantity": _number(requested[2], 1) if len(requested) >= 3 else 1,
        "executable_quantity": _number(final[2], 1) if len(final) >= 3 else (0 if final == ["PASS"] else 1),
        "expected_effect": effect,
        "before_inventory": before_inventory,
        "after_inventory": copy.deepcopy(inventory),
        "before_shed": before_shed,
        "after_shed": copy.deepcopy(shadow["private"]["shed"]),
        "target_before": before_target,
        "target_after": _target_identity(after_tile, position),
    }


def _resolve_market(shadow: dict[str, Any], requested: list[list[Any]]) -> tuple[list[list[Any]], list[dict[str, Any]]]:
    final: list[list[Any]] = []
    trace: list[dict[str, Any]] = []
    for slot, order in enumerate(requested[:10]):
        resolved, record = _apply_market_prefix_order(shadow, copy.deepcopy(order))
        if resolved is not None:
            final.append(resolved)
        trace.append({"slot": slot, **record})
    return final, trace


def resolve_final_action(
    observation: Mapping[str, Any], proposed: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve the final proposal in fixed-engine actor then market order."""
    shadow = copy.deepcopy(dict(observation))
    seat = _number(shadow.get("player"))
    actor_count = 1 + len(shadow["farms"][seat].get("hands", []))
    requested_units = [copy.deepcopy(proposed.get("farmer") or ["PASS"])]
    requested_units.extend(copy.deepcopy(value or ["PASS"]) for value in proposed.get("hands", []))
    requested_units = (requested_units + [["PASS"]] * actor_count)[:actor_count]
    # Keep a per-crop reservation so the emitted joint action never triggers
    # the engine's all-or-nothing PLANT shortage cancellation.
    plant_remaining = {str(crop): max(0, _number(value)) for crop, value in shadow["private"].get("seeds", {}).items()}
    final_units: list[list[Any]] = []
    actor_trace: list[dict[str, Any]] = []
    for index, requested in enumerate(requested_units):
        final, record = _resolve_actor(shadow, index, requested, plant_remaining)
        final_units.append(final)
        actor_trace.append(record)
    market, market_trace = _resolve_market(shadow, [copy.deepcopy(value) for value in proposed.get("market", [])])
    action = {"farmer": final_units[0], "hands": final_units[1:], "market": market}
    return action, {
        "actors": actor_trace,
        "market": market_trace,
        "shadow_summary": {
            "money": shadow["farms"][seat].get("money"),
            "shed": copy.deepcopy(shadow["private"].get("shed", {})),
            "seeds": copy.deepcopy(shadow["private"].get("seeds", {})),
        },
    }


def _effect_check(observation: Mapping[str, Any], pending: dict[str, Any]) -> dict[str, Any]:
    if _step(observation) != pending["step"] + 1:
        return {"status": "UNKNOWN_NONCONSECUTIVE"}
    if _number(observation.get("day")) != pending["day"]:
        return {"status": "UNKNOWN_DAY_BOUNDARY", "reason": "hands and inventories reset after engine effects"}
    seat = _number(observation.get("player"))
    farm = observation["farms"][seat]
    positions = [farm["farmer"], *farm.get("hands", [])]
    inventories = observation["private"]["inventories"]
    actor_effects = []
    for record in pending["actors"]:
        index = record["actor_index"]
        final = record["final"]
        if index >= len(positions) or index >= len(inventories):
            actor_effects.append({"actor_index": index, "status": "UNKNOWN_ACTOR_MISSING"})
            continue
        op = final[0] if final else "PASS"
        before_inventory = record["before_inventory"]
        after_inventory = inventories[index]
        success = None
        if op in {"NORTH", "SOUTH", "EAST", "WEST"}:
            success = list(positions[index]) != record["target_before"]["position"]
        elif op == "PICKUP" and len(final) >= 2:
            success = _number(after_inventory.get(final[1])) > _number(before_inventory.get(final[1]))
        elif op in {"PLACE", "DROP"}:
            success = sum(_number(v) for v in after_inventory.values()) < sum(
                _number(v) for v in before_inventory.values()
            )
        elif op == "HARVEST":
            product = record["expected_effect"].get("product")
            success = bool(product) and _number(after_inventory.get(product)) > _number(before_inventory.get(product))
        elif op in {"FEED", "FERTILIZE"}:
            item = "WHEAT" if op == "FEED" else "FERTILIZER"
            success = _number(after_inventory.get(item)) < _number(before_inventory.get(item))
        elif op == "COLLECT_FERTILIZER":
            success = _number(after_inventory.get("FERTILIZER")) > _number(before_inventory.get("FERTILIZER"))
        elif op == "PASS":
            success = False
        else:
            target = record["target_before"]["position"]
            tile = farm["tiles"][target[1]][target[0]] if len(target) == 2 else None
            tile_map = _mapping(tile)
            if op == "PLANT":
                success = tile_map.get("crop") == (final[1] if len(final) > 1 else None)
            elif op == "WATER":
                success = bool(tile_map.get("watered_today"))
            elif op == "CARE":
                success = bool(tile_map.get("cared_today"))
            elif op.startswith("BUILD_"):
                success = tile_map.get("kind") == ("COOP" if op == "BUILD_COOP" else "PASTURE")
            elif op == "DIG":
                success = tile is None
        actor_effects.append({"actor_index": index, "action": copy.deepcopy(final), "success": success})
    return {"status": "OBSERVED", "actors": actor_effects}


def _agent(
    observation: Mapping[str, Any], *, plan_enabled: bool, final_consistency: bool, full_contract: bool
) -> dict[str, Any]:
    if _step(observation) == 0:
        reset_runtime_state()
    seat = _number(observation.get("player"))
    if seat in _pending:
        prior = _pending.pop(seat)
        prior["record"]["effect"] = _effect_check(observation, prior)
    ledger, decoder_trace = _decode_ledger(observation, full_contract=full_contract)
    if plan_enabled:
        planned, plan_trace = _apply_plan(observation, ledger, repaired_endgame=final_consistency)
    else:
        planned, plan_trace = copy.deepcopy(ledger), {"active": False, "interventions": [], "disabled": True}
    if final_consistency:
        final, final_trace = resolve_final_action(observation, planned)
    else:
        final, final_trace = copy.deepcopy(planned), {"actors": [], "market": [], "not_resolved": True}
    record = {
        "step": _step(observation),
        "day": _number(observation.get("day")),
        "hour": _number(observation.get("hour")),
        "decoder": copy.deepcopy(decoder_trace),
        "ledger_action": copy.deepcopy(ledger),
        "plan": copy.deepcopy(plan_trace),
        "plan_action": copy.deepcopy(planned),
        "final_resolution": copy.deepcopy(final_trace),
        "final_action": copy.deepcopy(final),
        "effect": {"status": "PENDING_NEXT_OBSERVATION"},
    }
    _trace.setdefault(seat, []).append(record)
    pending_actors = (
        final_trace.get("actors", [])
        if final_consistency
        else [
            {
                "actor_index": index,
                "final": copy.deepcopy(action),
                "before_inventory": copy.deepcopy(observation["private"]["inventories"][index]),
                "target_before": _target_identity(
                    _policy.actor_context(observation, index)[3], _policy.actor_context(observation, index)[1]
                ),
                "expected_effect": {},
            }
            for index, action in enumerate([final["farmer"], *final.get("hands", [])])
        ]
    )
    _pending[seat] = {
        "step": record["step"],
        "day": record["day"],
        "actors": copy.deepcopy(pending_actors),
        "record": record,
    }
    units = [final["farmer"], *final.get("hands", [])]
    _policy._previous_actor[seat] = [_policy.action_token(value) for value in units]
    _policy._previous_market[seat] = copy.deepcopy(final["market"])
    return final


def agent_f1(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    return _agent(observation, plan_enabled=True, final_consistency=False, full_contract=False)


def agent_f2(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    return _agent(observation, plan_enabled=True, final_consistency=True, full_contract=True)


def agent_f2_no_plan(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    return _agent(observation, plan_enabled=False, final_consistency=True, full_contract=True)


def diagnostics() -> dict[str, Any]:
    return {
        "arm": "round9_trajectory_memorizer_seed20260925_diagnostic",
        "plans": _plans,
        "trace": _trace,
        "base": _policy.policy_diagnostics(),
    }
