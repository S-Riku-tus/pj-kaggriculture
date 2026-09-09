"""Engine-aware safety audit, including silent no-op and partial orders."""

from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any

from kaggle_environments.envs.kaggriculture import kaggriculture as engine

from .replay import action, decision_count, observation

ANIMALS = ("GOOSE", "COW", "SHEEP")
FAILURE_STATUSES = {"ERROR", "INVALID", "TIMEOUT"}


def _fingerprint(*values: Any) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _field_fingerprint(
    farm: dict[str, Any], private: dict[str, Any], unit_index: int
) -> str:
    positions = [farm.get("farmer") or [], *(farm.get("hands") or [])]
    position = positions[unit_index] if unit_index < len(positions) else []
    tile: Any = None
    if len(position) == 2:
        x, y = int(position[0]), int(position[1])
        tiles = farm.get("tiles") or []
        if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]):
            tile = tiles[y][x]
    inventories = private.get("inventories") or []
    inventory = inventories[unit_index] if unit_index < len(inventories) else {}
    return _fingerprint(
        position,
        tile,
        inventory,
        private.get("shed") or {},
        private.get("seeds") or {},
    )


def _owned_animals(obs: dict[str, Any], seat: int) -> Counter[str]:
    result: Counter[str] = Counter()
    farms = list(obs.get("farms") or [])
    farm = farms[seat] if seat < len(farms) else {}
    for row in farm.get("tiles") or []:
        for tile in row or []:
            if isinstance(tile, dict) and tile.get("animal") in ANIMALS:
                result[str(tile["animal"])] += 1
    private = obs.get("private") or {}
    shed = private.get("shed") or {}
    inventories = private.get("inventories") or []
    for animal in ANIMALS:
        result[animal] += max(0, int(shed.get(animal, 0) or 0))
        result[animal] += sum(max(0, int(inv.get(animal, 0) or 0)) for inv in inventories)
    return result


def _weed_events(previous: dict[str, Any], current: dict[str, Any], seat: int) -> tuple[int, int]:
    farms_before = list(previous.get("farms") or [])
    farms_after = list(current.get("farms") or [])
    if seat >= len(farms_before) or seat >= len(farms_after):
        return 0, 0
    plant_to_weed = 0
    spawned = 0
    before_tiles = farms_before[seat].get("tiles") or []
    after_tiles = farms_after[seat].get("tiles") or []
    for y, (left_row, right_row) in enumerate(zip(before_tiles, after_tiles, strict=False)):
        for x, (left, right) in enumerate(zip(left_row or [], right_row or [], strict=False)):
            _ = (x, y)
            right_weed = isinstance(right, dict) and right.get("kind") == "WEED"
            if not right_weed:
                continue
            if isinstance(left, dict) and left.get("kind") == "PLANT":
                plant_to_weed += 1
            elif left is None:
                spawned += 1
    return plant_to_weed, spawned


def _apply_fields(
    farms: list[dict[str, Any]],
    privates: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    day: int,
    *,
    board_size: int = 10,
    turns_per_day: int = 24,
    shed_capacity: int = 100,
) -> list[list[dict[str, Any]]]:
    events: list[list[dict[str, Any]]] = [[], []]
    for player in (0, 1):
        current = actions[player] if isinstance(actions[player], dict) else {}
        farmer_action = current.get("farmer", ["PASS"])
        hand_actions = current.get("hands", [])
        hand_actions = hand_actions if isinstance(hand_actions, list) else []
        unit_actions = [farmer_action, *hand_actions]
        seeds = privates[player].get("seeds", {})
        demand: Counter[str] = Counter(
            str(row[1])
            for row in unit_actions
            if isinstance(row, list) and len(row) >= 2 and row[0] == "PLANT"
        )
        blocked = {crop for crop, count in demand.items() if count > int(seeds.get(crop, 0) or 0)}
        expected_units = 1 + len(farms[player].get("hands") or [])
        if len(unit_actions) < expected_units:
            events[player].append(
                {
                    "kind": "missing_hand_actions",
                    "count": expected_units - len(unit_actions),
                }
            )
        for index, requested in enumerate(unit_actions):
            effective = requested
            if (
                isinstance(requested, list)
                and len(requested) >= 2
                and requested[0] == "PLANT"
                and requested[1] in blocked
            ):
                effective = ["PASS"]
            before = _field_fingerprint(farms[player], privates[player], index)
            engine._apply_unit_action(
                farms[player],
                privates[player],
                index,
                effective,
                board_size,
                day,
                turns_per_day,
                shed_capacity,
            )
            after = _field_fingerprint(farms[player], privates[player], index)
            op = str(requested[0]) if isinstance(requested, list) and requested else "MALFORMED"
            if op != "PASS" and before == after:
                events[player].append(
                    {
                        "kind": "silent_field_noop",
                        "unit": index,
                        "action": requested,
                        "atomic_plant_block": effective == ["PASS"] and requested != ["PASS"],
                    }
                )
    return events


def _simulate_market(
    farms: list[dict[str, Any]],
    privates: list[dict[str, Any]],
    market: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    board_size: int = 10,
    max_orders: int = 10,
    hire_mult: int = 1,
    shed_capacity: int = 100,
) -> list[list[dict[str, Any]]]:
    events: list[list[dict[str, Any]]] = [[], []]
    queues: list[list[Any]] = []
    for player, current in enumerate(actions):
        orders = current.get("market", []) if isinstance(current, dict) else []
        orders = list(orders) if isinstance(orders, list) else []
        if len(orders) > max_orders:
            events[player].append(
                {"kind": "market_orders_truncated", "count": len(orders) - max_orders}
            )
        queues.append(orders[:max_orders])
    for slot in range(max((len(queue) for queue in queues), default=0)):
        states = []
        requested: list[Any] = []
        committed = [0, 0]
        for player, queue in enumerate(queues):
            raw = queue[slot] if slot < len(queue) else None
            requested.append(raw)
            parsed = engine._parse_order(raw) if raw is not None else None
            if raw is not None and parsed is None:
                events[player].append(
                    {"kind": "malformed_market_order", "slot": slot, "order": raw}
                )
            states.append(parsed)
        for player, state in enumerate(states):
            if state is None:
                continue
            op = state["type"]
            if op == "HIRE":
                before = _fingerprint(farms[player], privates[player])
                engine._do_hire(farms[player], privates[player], board_size, hire_mult)
                accepted = before != _fingerprint(farms[player], privates[player])
                committed[player] = int(accepted)
                events[player].append(
                    {"kind": "market_commit", "slot": slot, "op": op, "requested": 1, "committed": int(accepted)}
                )
                states[player] = None
            elif op == "BUY_LAND":
                before = _fingerprint(farms[player])
                engine._do_buy_land(farms[player], board_size)
                accepted = before != _fingerprint(farms[player])
                committed[player] = int(accepted)
                events[player].append(
                    {"kind": "market_commit", "slot": slot, "op": op, "requested": 1, "committed": int(accepted)}
                )
                states[player] = None
        while True:
            quoted: list[tuple[str, str, int, dict[str, Any]] | None] = [None, None]
            for player, state in enumerate(states):
                if state is None or state["remaining"] <= 0:
                    continue
                op = state["type"]
                item = state["item"]
                if op == "SELL" and item in engine.PRODUCTS:
                    price = engine.market_price(item, market["inventory"][item], market.get("params"))
                elif op == "BUY_PRODUCT" and item in ("WHEAT", "FERTILIZER"):
                    price = engine.market_price(item, market["inventory"][item] - 1, market.get("params"))
                elif op == "BUY_SEED" and item in engine.CROPS:
                    price = engine.CROPS[item]["seed"]
                elif op == "BUY_ANIMAL" and item in engine.ANIMALS:
                    price = engine.ANIMALS[item]["cost"]
                else:
                    states[player] = None
                    continue
                quoted[player] = (op, item, price, state)
            if all(value is None for value in quoted):
                break
            committed_any = False
            for player, quote in enumerate(quoted):
                if quote is None:
                    continue
                op, item, price, state = quote
                ok = engine._commit_unit(
                    op,
                    item,
                    price,
                    farms[player],
                    privates[player],
                    market,
                    shed_capacity,
                )
                if ok:
                    state["remaining"] -= 1
                    committed[player] += 1
                    committed_any = True
                else:
                    states[player] = None
            if not committed_any:
                break
        engine._refresh_prices(market)
        for player, raw in enumerate(requested):
            parsed = engine._parse_order(raw) if raw is not None else None
            if parsed is None or parsed["type"] in {"HIRE", "BUY_LAND"}:
                continue
            requested_units = int(parsed["remaining"])
            events[player].append(
                {
                    "kind": "market_commit",
                    "slot": slot,
                    "op": parsed["type"],
                    "item": parsed.get("item"),
                    "requested": requested_units,
                    "committed": committed[player],
                }
            )
    return events


def simulate_turn(replay: dict[str, Any], step: int) -> list[list[dict[str, Any]]]:
    obs0 = observation(replay, step, 0) or {}
    obs1 = observation(replay, step, 1) or {}
    farms = copy.deepcopy(list(obs0.get("farms") or [{}, {}]))
    privates = [
        copy.deepcopy(obs0.get("private") or {}),
        copy.deepcopy(obs1.get("private") or {}),
    ]
    market = copy.deepcopy(obs0.get("market") or {})
    actions = [action(replay, step, 0), action(replay, step, 1)]
    day = int(obs0.get("day", step // 24) or 0)
    field_events = _apply_fields(farms, privates, actions, day)
    market_events = _simulate_market(farms, privates, market, actions)
    return [[*field_events[player], *market_events[player]] for player in (0, 1)]


def analyze_safety(
    replay: dict[str, Any],
    seat: int,
    agent_trace: dict[str, Any],
    *,
    transaction_step: int = 248,
) -> dict[str, Any]:
    statuses: list[dict[str, Any]] = []
    minimum_cash = float("inf")
    animal_losses: Counter[str] = Counter()
    plant_to_weed = 0
    spawned_weeds = 0
    previous_obs: dict[str, Any] | None = None
    previous_animals: Counter[str] | None = None
    event_counts: Counter[str] = Counter()
    event_examples: list[dict[str, Any]] = []
    purchase_committed = 0
    sheep_pickup_noops = 0
    sheep_place_noops = 0
    steps = replay.get("steps") or []
    for index, states in enumerate(steps):
        if seat < len(states):
            status = str((states[seat] or {}).get("status") or "")
            if status in FAILURE_STATUSES:
                statuses.append({"state_index": index, "status": status})
        obs = observation(replay, index, seat)
        if obs is None:
            continue
        farms = list(obs.get("farms") or [])
        farm = farms[seat] if seat < len(farms) else {}
        minimum_cash = min(minimum_cash, float(farm.get("money", 0.0) or 0.0))
        current_animals = _owned_animals(obs, seat)
        if previous_animals is not None:
            for animal in ANIMALS:
                animal_losses[animal] += max(0, previous_animals[animal] - current_animals[animal])
        if previous_obs is not None:
            lost_crops, new_weeds = _weed_events(previous_obs, obs, seat)
            plant_to_weed += lost_crops
            spawned_weeds += new_weeds
        previous_obs = obs
        previous_animals = current_animals
    for step in range(decision_count(replay)):
        for event in simulate_turn(replay, step)[seat]:
            kind = str(event["kind"])
            if kind == "market_commit":
                requested = int(event.get("requested", 0) or 0)
                committed = int(event.get("committed", 0) or 0)
                if committed == 0 and requested:
                    event_counts["silent_market_noop"] += 1
                    event_counts[
                        f"{'pre' if step < transaction_step else 'post'}_intervention_silent_market_noop"
                    ] += 1
                elif committed < requested:
                    event_counts["partial_market_commit"] += 1
                    event_counts[
                        f"{'pre' if step < transaction_step else 'post'}_intervention_partial_market_commit"
                    ] += 1
                if (
                    step == transaction_step
                    and event.get("op") == "BUY_ANIMAL"
                    and event.get("item") == "SHEEP"
                ):
                    purchase_committed += committed
            else:
                event_counts[kind] += int(event.get("count", 1) or 1)
                event_counts[
                    f"{'pre' if step < transaction_step else 'post'}_intervention_{kind}"
                ] += int(event.get("count", 1) or 1)
            if kind == "silent_field_noop":
                row = event.get("action") or []
                if len(row) >= 2 and row[:2] == ["PICKUP", "SHEEP"] and step >= transaction_step:
                    sheep_pickup_noops += 1
                if len(row) >= 2 and row[:2] == ["PLACE", "SHEEP"] and step >= transaction_step:
                    sheep_place_noops += 1
            if len(event_examples) < 100 and (
                kind != "market_commit"
                or int(event.get("committed", 0) or 0) < int(event.get("requested", 0) or 0)
            ):
                event_examples.append({"step": step, **event})
    counts = Counter(agent_trace.get("strategy_counts") or {})
    emitted_purchase = int(counts.get("cow-to-sheep-purchase", 0)) > 0
    transaction_complete = (
        not emitted_purchase
        or (
            purchase_committed >= 2
            and int(counts.get("cow-to-sheep-pickup", 0)) >= 2
            and int(counts.get("cow-to-sheep-place", 0)) >= 2
            and sheep_pickup_noops == 0
            and sheep_place_noops == 0
        )
    )
    final_statuses = [str((state or {}).get("status") or "") for state in (steps[-1] if steps else [])]
    return {
        "stored_steps": len(steps),
        "decisions": decision_count(replay),
        "final_statuses": final_statuses,
        "runtime_failures": statuses,
        "completed_720": len(steps) == 720 and final_statuses == ["DONE", "DONE"],
        "minimum_cash": 0.0 if minimum_cash == float("inf") else minimum_cash,
        "animal_losses": dict(animal_losses),
        "animal_loss_total": sum(animal_losses.values()),
        "plant_to_weed": plant_to_weed,
        "spawned_weeds": spawned_weeds,
        "fallback_steps": int(agent_trace.get("fallback_steps", 0) or 0),
        "ood_steps": int(agent_trace.get("ood_steps", 0) or 0),
        "engine_action_audit": dict(event_counts),
        "engine_action_examples": event_examples,
        "transaction": {
            "emitted_purchase_rewrite": emitted_purchase,
            "purchase_units_committed": purchase_committed,
            "emitted_pickups": int(counts.get("cow-to-sheep-pickup", 0)),
            "emitted_placements": int(counts.get("cow-to-sheep-place", 0)),
            "pickup_noops": sheep_pickup_noops,
            "placement_noops": sheep_place_noops,
            "complete": transaction_complete,
        },
    }


def candidate_new_major_regressions(control: dict[str, Any], treatment: dict[str, Any]) -> list[str]:
    """Return candidate-new *hard* safety failures.

    This compatibility entry point intentionally excludes a safe inability to
    deliver the treatment.  Call :func:`classify_candidate_incidents` when the
    delivery-failure diagnostics are also required.
    """

    return classify_candidate_incidents(control, treatment)["hard_safety_failures"]


def classify_candidate_incidents(
    control: dict[str, Any], treatment: dict[str, Any]
) -> dict[str, Any]:
    """Separate game-integrity failures from treatment-delivery failures.

    Fallback/OOD means that the requested branch was not delivered.  In the
    absence of an integrity regression it is reported as treatment delivery,
    not promoted to a catastrophic safety claim.  Runtime failure, incomplete
    games, animal/weed/cash corruption, incomplete emitted transactions, and
    candidate-new pre-intervention illegal/no-op behavior remain hard safety
    failures.
    """

    hard: list[str] = []
    delivery: list[str] = []
    absolute_checks = {
        "runtime_failure": bool(treatment.get("runtime_failures")),
        "incomplete_720": not bool(treatment.get("completed_720")),
        "new_animal_loss": int(treatment.get("animal_loss_total", 0))
        > int(control.get("animal_loss_total", 0)),
        "new_crop_to_weed": int(treatment.get("plant_to_weed", 0))
        > int(control.get("plant_to_weed", 0)),
        "new_spawned_weed": int(treatment.get("spawned_weeds", 0))
        > int(control.get("spawned_weeds", 0)),
        "negative_cash": float(treatment.get("minimum_cash", 0.0)) < 0.0,
        "transaction_incomplete": not bool(
            (treatment.get("transaction") or {}).get("complete")
        ),
    }
    hard.extend(name for name, failed in absolute_checks.items() if failed)
    for key in ("fallback_steps", "ood_steps"):
        if int(treatment.get(key, 0)) > int(control.get(key, 0)):
            delivery.append(f"new_{key}")
    for key in (
        "pre_intervention_silent_field_noop",
        "pre_intervention_silent_market_noop",
        "pre_intervention_partial_market_commit",
        "pre_intervention_missing_hand_actions",
    ):
        left = int((control.get("engine_action_audit") or {}).get(key, 0))
        right = int((treatment.get("engine_action_audit") or {}).get(key, 0))
        if right > left:
            hard.append(f"new_{key}")
    hard = sorted(set(hard))
    delivery = sorted(set(delivery))
    return {
        "hard_safety_failures": hard,
        "treatment_delivery_failures": delivery,
        "hard_safety_failure": bool(hard),
        "treatment_delivery_failure": bool(delivery),
    }
