"""Round5 ordered joint-action executor and resource-reserving planner."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

try:
    from .contracts import (
        ANIMAL_RULES,
        CROP_RULES,
        SHED_TILES,
        TypedPlan,
        actor_inventory,
        actor_positions,
        animal_product,
        attribute_primitive,
        canonical_step,
        harvestability,
        make_feed_plan,
        make_harvest_plan,
        next_animal_production_day,
        observation_digest,
        target_identity,
        tile_at,
    )
except ImportError:
    from contracts import (  # type: ignore
        ANIMAL_RULES,
        CROP_RULES,
        SHED_TILES,
        TypedPlan,
        actor_inventory,
        actor_positions,
        animal_product,
        attribute_primitive,
        canonical_step,
        harvestability,
        make_feed_plan,
        make_harvest_plan,
        next_animal_production_day,
        observation_digest,
        target_identity,
        tile_at,
    )

MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}
TRACKED = frozenset(
    {
        "PICKUP",
        "HARVEST",
        "FEED",
        "WATER",
        "CARE",
        "COLLECT_FERTILIZER",
        "PLANT",
        "FERTILIZE",
        "DROP",
        "PLACE",
        "DIG",
        "BUILD_COOP",
        "BUILD_PASTURE",
        *MOVES,
    }
)
SEED_COST = {"WHEAT": 10, "CARROT": 20, "TOMATO": 50, "STRAWBERRY": 100, "MELON": 80}
ANIMAL_COST = {"GOOSE": 300, "COW": 400, "SHEEP": 500}
LAND_COST = (1000, 2000, 4000)
PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
MARKET_PARAMS: dict[str, dict[str, Any]] = {
    "WHEAT": {"base": 25, "I0": 10000, "T": 400, "below_func": "sqrt", "below_target": 0.80, "above_func": "log", "above_target": 0.20},
    "CARROT": {"base": 35, "I0": 10000, "T": 450, "below_func": "hinge", "below_target": 1.00, "above_func": "sqrt", "above_target": 0.70},
    "TOMATO": {"base": 60, "I0": 10000, "T": 200, "below_func": "hinge", "below_target": 0.40, "above_func": "sqrt", "above_target": 0.60},
    "STRAWBERRY": {"base": 120, "I0": 10000, "T": 100, "below_func": "sqrt", "below_target": 0.70, "above_func": "linear", "above_target": 1.60},
    "MELON": {"base": 250, "I0": 10000, "T": 300, "below_func": "log", "below_target": 0.20, "above_func": "sq", "above_target": 3.60},
    "EGG": {"base": 50, "I0": 10000, "T": 332, "below_func": "hinge", "below_target": 0.40, "above_func": "log", "above_target": 0.20},
    "MILK": {"base": 160, "I0": 10000, "T": 122, "below_func": "sqrt", "below_target": 0.60, "above_func": "linear", "above_target": 1.60},
    "WOOL": {"base": 200, "I0": 10000, "T": 105, "below_func": "log", "below_target": 0.20, "above_func": "sq", "above_target": 3.20},
    "FERTILIZER": {"base": 100, "I0": 10000, "T": 200, "below_func": "linear", "below_target": 0.40, "above_func": "linear", "above_target": 0.40},
}


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1])


def _move_toward(left: tuple[int, int], right: tuple[int, int]) -> list[str]:
    if left[0] < right[0]:
        return ["EAST"]
    if left[0] > right[0]:
        return ["WEST"]
    if left[1] < right[1]:
        return ["SOUTH"]
    if left[1] > right[1]:
        return ["NORTH"]
    return ["PASS"]


def _shape(action: Mapping[str, Any], hands: int) -> dict[str, Any]:
    result = {
        "farmer": list(action.get("farmer") or ["PASS"]),
        "hands": [list(value or ["PASS"]) for value in action.get("hands") or []],
        "market": [list(value) for value in action.get("market") or [] if isinstance(value, Sequence)][:10],
    }
    result["hands"] = (result["hands"] + [["PASS"]] * hands)[:hands]
    return result


def _units(action: Mapping[str, Any]) -> list[list[Any]]:
    return [list(action.get("farmer") or ["PASS"]), *[list(value or ["PASS"]) for value in action.get("hands") or []]]


def _set_unit(action: dict[str, Any], actor: int, value: Sequence[Any]) -> None:
    if actor == 0:
        action["farmer"] = list(value)
    else:
        action["hands"][actor - 1] = list(value)


def _shed_access(position: tuple[int, int]) -> bool:
    return position in SHED_TILES


def _fib(index: int) -> int:
    left, right = 1, 1
    for _ in range(index):
        left, right = right, left + right
    return left


def _market_shape(name: str, value: float, scale: float) -> float:
    value = max(0.0, value)
    if name == "linear":
        return value
    if name == "sq":
        return value * value
    if name == "sqrt":
        return math.sqrt(value)
    if name == "log":
        return math.log(1.0 + value)
    if name == "log10":
        return math.log10(1.0 + value)
    if name == "hinge":
        if scale <= 0:
            return value
        ratio = value / scale
        return ratio + 8.0 * max(0.0, ratio - 1.0) ** 2
    return value


def _market_price(item: str, inventory: int, overrides: Mapping[str, Any] | None = None) -> int:
    params = dict(MARKET_PARAMS[item])
    patch = (overrides or {}).get(item)
    if isinstance(patch, Mapping):
        params.update(patch)
    base, initial, scale = float(params["base"]), float(params["I0"]), float(params["T"])
    if inventory < initial:
        shape = str(params["below_func"])
        amplitude = float(params["below_target"]) * base / _market_shape(shape, scale, scale)
        value = base + amplitude * _market_shape(shape, initial - inventory, scale)
    else:
        shape = str(params["above_func"])
        amplitude = float(params["above_target"]) * base / _market_shape(shape, scale, scale)
        value = base - amplitude * _market_shape(shape, inventory - initial, scale)
    return max(1, int(round(value)))


class WorkingState:
    """A minimal copy of engine state, updated in farmer->hand order."""

    def __init__(self, observation: Mapping[str, Any]) -> None:
        seat = _integer(observation.get("player"))
        farm = observation["farms"][seat]
        private = observation.get("private") or {}
        self.day = _integer(observation.get("day"))
        self.board_size = len(farm.get("tiles") or [])
        self.positions = actor_positions(observation)
        self.tiles = deepcopy(farm.get("tiles") or [])
        self.inventories = deepcopy(list(private.get("inventories") or []))
        self.inventories = (self.inventories + [{} for _ in self.positions])[: len(self.positions)]
        self.shed = deepcopy(dict(private.get("shed") or {}))
        self.seeds = deepcopy(dict(private.get("seeds") or {}))
        self.capacity = 100

    def tile(self, position: tuple[int, int]) -> Any:
        x, y = position
        if not (0 <= x < self.board_size and 0 <= y < self.board_size):
            return "LOCKED"
        return self.tiles[y][x]

    def _harvest_product(self, tile: Mapping[str, Any]) -> str | None:
        if tile.get("kind") == "PLANT":
            crop = str(tile.get("crop") or "")
            rule = CROP_RULES.get(crop)
            if not rule or self.day - _integer(tile.get("planted_day")) < _integer(rule["first_yield_day"]):
                return None
            return crop
        return animal_product(tile)

    def apply(self, actor: int, action: Sequence[Any], blocked_plants: set[str]) -> tuple[list[Any] | None, str]:
        if not 0 <= actor < len(self.positions):
            return None, "ACTOR_MISSING"
        unit = list(action or ["PASS"])
        op = str(unit[0]) if unit else "PASS"
        position = self.positions[actor]
        x, y = position
        inventory = self.inventories[actor]
        if op == "PASS":
            return ["PASS"], "PASS"
        if op in MOVES:
            dx, dy = MOVES[op]
            target = (x + dx, y + dy)
            if not (0 <= target[0] < self.board_size and 0 <= target[1] < self.board_size):
                return None, "MOVE_OUT_OF_BOUNDS"
            self.positions[actor] = target
            return [op], "MOVE"
        tile = self.tile(position)
        if op == "PICKUP":
            if not _shed_access(position) or len(unit) < 2:
                return None, "PICKUP_PRECONDITION_FAILED"
            item = str(unit[1])
            wanted = max(1, _integer(unit[2], 1) if len(unit) > 2 else 1)
            quantity = min(wanted, _integer(self.shed.get(item)))
            if quantity <= 0:
                return None, f"PICKUP_RESOURCE_EMPTY:{item}"
            self.shed[item] = _integer(self.shed.get(item)) - quantity
            inventory[item] = _integer(inventory.get(item)) + quantity
            return ["PICKUP", item, quantity], "PICKUP_RESERVED"
        if op == "DROP":
            if not _shed_access(position) or not any(_integer(value) > 0 for value in inventory.values()):
                return None, "DROP_PRECONDITION_FAILED"
            room = max(0, self.capacity - sum(_integer(value) for value in self.shed.values()))
            if room <= 0:
                return None, "SHED_CAPACITY_EXHAUSTED"
            for item, raw in list(inventory.items()):
                quantity = min(_integer(raw), room)
                if quantity > 0:
                    self.shed[item] = _integer(self.shed.get(item)) + quantity
                    room -= quantity
                inventory.pop(item, None)
            return ["DROP"], "DROP_RESERVED"
        if op == "PLACE" and len(unit) >= 2:
            item = str(unit[1])
            if item in ANIMAL_RULES and isinstance(tile, Mapping) and not tile.get("animal"):
                expected = "COOP" if item == "GOOSE" else "PASTURE"
                if tile.get("kind") != expected or _integer(inventory.get(item)) <= 0:
                    return None, "ANIMAL_PLACE_PRECONDITION_FAILED"
                inventory[item] = _integer(inventory.get(item)) - 1
                self.tiles[y][x] = {
                    "kind": expected,
                    "animal": item,
                    "placed_day": self.day,
                    "yield_units": 0,
                    "fed_today": False,
                    "consecutive_unfed": 0,
                    "cared_today": False,
                    "fertilizer_available": False,
                    "pending_care_bonus": 0,
                }
                return ["PLACE", item], "ANIMAL_PLACED"
            if not _shed_access(position) or _integer(inventory.get(item)) <= 0:
                return None, "PLACE_PRECONDITION_FAILED"
            room = max(0, self.capacity - sum(_integer(value) for value in self.shed.values()))
            wanted = max(1, _integer(unit[2], 1) if len(unit) > 2 else 1)
            quantity = min(wanted, _integer(inventory.get(item)), room)
            if quantity <= 0:
                return None, "PLACE_CAPACITY_OR_RESOURCE_FAILED"
            inventory[item] = _integer(inventory.get(item)) - quantity
            self.shed[item] = _integer(self.shed.get(item)) + quantity
            return ["PLACE", item, quantity], "PLACE_RESERVED"
        if tile == "LOCKED":
            return None, "TARGET_LOCKED"
        if op == "PLANT":
            crop = str(unit[1]) if len(unit) > 1 else ""
            if crop in blocked_plants:
                return None, f"PLANT_ATOMIC_SEED_SHORTAGE:{crop}"
            if tile is not None or crop not in CROP_RULES or _integer(self.seeds.get(crop)) <= 0:
                return None, "PLANT_PRECONDITION_FAILED"
            self.seeds[crop] = _integer(self.seeds.get(crop)) - 1
            self.tiles[y][x] = {
                "kind": "PLANT",
                "crop": crop,
                "planted_day": self.day,
                "watered_today": False,
                # The fixed engine counts planting day as already unwatered.
                # A plant placed at hour 23 therefore dies unless a later actor
                # waters the same coordinate in this joint action.
                "consecutive_unwatered": 1,
                "yield_units": 0 if bool(CROP_RULES[crop]["ongoing"]) else 1,
                "fertilized_until_day": -1,
            }
            return ["PLANT", crop], "PLANT_RESERVED"
        if op == "DIG":
            if tile is None or (isinstance(tile, Mapping) and tile.get("animal")):
                return None, "DIG_PRECONDITION_FAILED"
            self.tiles[y][x] = None
            return ["DIG"], "DIG_RESERVED"
        if op in {"BUILD_COOP", "BUILD_PASTURE"}:
            if tile is not None:
                return None, "BUILD_PRECONDITION_FAILED"
            self.tiles[y][x] = {"kind": "COOP" if op == "BUILD_COOP" else "PASTURE"}
            return [op], "BUILD_RESERVED"
        if op == "HARVEST":
            if not isinstance(tile, Mapping) or _integer(tile.get("yield_units")) <= 0:
                return None, "HARVEST_RESOURCE_EMPTY"
            product = self._harvest_product(tile)
            if not product:
                return None, "HARVEST_PRECONDITION_FAILED"
            quantity = _integer(tile.get("yield_units"))
            inventory[product] = _integer(inventory.get(product)) + quantity
            if tile.get("kind") == "PLANT" and not bool(CROP_RULES[str(tile["crop"])]["ongoing"]):
                self.tiles[y][x] = None
            else:
                tile["yield_units"] = 0
            return ["HARVEST"], f"HARVEST_RESERVED:{product}:{quantity}"
        if op == "WATER":
            if not isinstance(tile, Mapping) or tile.get("kind") != "PLANT" or bool(tile.get("watered_today")):
                return None, "WATER_PRECONDITION_FAILED"
            tile["watered_today"] = True
            return ["WATER"], "WATER_RESERVED"
        if op == "FEED":
            if not isinstance(tile, Mapping) or not tile.get("animal") or bool(tile.get("fed_today")):
                return None, "FEED_PRECONDITION_FAILED"
            if _integer(inventory.get("WHEAT")) <= 0:
                return None, "FEED_WHEAT_SHORTAGE"
            inventory["WHEAT"] = _integer(inventory.get("WHEAT")) - 1
            tile["fed_today"] = True
            return ["FEED"], "FEED_RESERVED"
        if op == "CARE":
            if not isinstance(tile, Mapping) or not tile.get("animal") or bool(tile.get("cared_today")):
                return None, "CARE_PRECONDITION_FAILED"
            tile["cared_today"] = True
            return ["CARE"], "CARE_RESERVED"
        if op == "COLLECT_FERTILIZER":
            if not isinstance(tile, Mapping) or not tile.get("animal") or not bool(tile.get("fertilizer_available")):
                return None, "FERTILIZER_PRECONDITION_FAILED"
            tile["fertilizer_available"] = False
            inventory["FERTILIZER"] = _integer(inventory.get("FERTILIZER")) + 1
            return ["COLLECT_FERTILIZER"], "FERTILIZER_RESERVED"
        if op == "FERTILIZE":
            if not isinstance(tile, Mapping) or tile.get("kind") != "PLANT" or _integer(inventory.get("FERTILIZER")) <= 0:
                return None, "FERTILIZE_PRECONDITION_FAILED"
            inventory["FERTILIZER"] = _integer(inventory.get("FERTILIZER")) - 1
            tile["fertilized_until_day"] = max(_integer(tile.get("fertilized_until_day"), -1), self.day + 2)
            return ["FERTILIZE"], "FERTILIZE_RESERVED"
        # BUILD/DIG and unknown legal-looking primitives do not consume a shared
        # item represented here; leave their final legality to the fixed engine.
        return unit, "PASSTHROUGH"


class ExecutionCoordinator:
    """Repair proposals with ordered resource consumption and economic reserves."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.reset()

    def reset(self) -> None:
        self.pending: dict[int, list[dict[str, Any]]] = {}
        self.completed_plan_ids: set[str] = set()
        self.trace: list[dict[str, Any]] = []
        self.animal_plan_ledger: dict[str, dict[str, Any]] = {}
        self.stats: dict[str, int] = {
            "base_primitive_issued": 0,
            "override_primitive_issued": 0,
            "primitive_effect_observed": 0,
            "primitive_failed": 0,
            "primitive_unknown": 0,
            "terminal_pending": 0,
            "plan_started": 0,
            "plan_completed": 0,
            "cash_realization_started": 0,
            "cash_realization_completed": 0,
            "resource_conflicts_blocked": 0,
            "duplicate_harvests_blocked": 0,
            "duplicate_services_blocked": 0,
            "atomic_plants_blocked": 0,
            "actors_reassigned": 0,
            "fallback_passes": 0,
            "animal_harvest_overrides": 0,
            "retirement_plans_enforced": 0,
            "market_orders_changed": 0,
            "wheat_sell_units_blocked": 0,
            "investment_orders_blocked": 0,
        }

    def _event(self, observation: Mapping[str, Any], event: str, **fields: Any) -> None:
        if len(self.trace) < 20_000:
            self.trace.append({"step": canonical_step(observation), "seat": _integer(observation.get("player")), "event": event, **fields})

    def _verify_pending(self, observation: Mapping[str, Any]) -> None:
        seat = _integer(observation.get("player"))
        rows = self.pending.pop(seat, [])
        for row in rows:
            if row.get("kind") == "market_sell":
                before = row["before"]
                item = row["item"]
                old_shed = _integer(row.get("pre_market_shed"), _integer((before.get("private") or {}).get("shed", {}).get(item)))
                new_shed = _integer((observation.get("private") or {}).get("shed", {}).get(item))
                old_money = _integer(before["farms"][seat].get("money"))
                new_money = _integer(observation["farms"][seat].get("money"))
                status = "ESTABLISHED" if new_shed < old_shed else "UNKNOWN"
                if status == "ESTABLISHED":
                    self.stats["cash_realization_completed"] += 1
                reason = "SOLD_INVENTORY_CONSUMED_CASH_MAY_BE_RESPENT" if status == "ESTABLISHED" else "MARKET_OR_DAY_BOUNDARY_NET_DELTA_AMBIGUOUS"
                self._event(observation, "cash_realization_result", status=status, reason=reason, item=item, gross_cash_observation=new_money - old_money, plan_id=row["plan_id"])
                continue
            status, reason = attribute_primitive(row["before"], observation, row["actor"], row["action"], row.get("target"))
            if status == "ESTABLISHED":
                self.stats["primitive_effect_observed"] += 1
                plan_id = row.get("plan_id")
                if plan_id and row.get("terminal") and plan_id not in self.completed_plan_ids:
                    self.completed_plan_ids.add(plan_id)
                    self.stats["plan_completed"] += 1
            elif status == "FAILED":
                self.stats["primitive_failed"] += 1
            elif status == "UNKNOWN":
                self.stats["primitive_unknown"] += 1
            self._event(observation, "primitive_result", actor=row["actor"], action=row["action"], status=status, reason=reason, plan_id=row.get("plan_id"))

    def _animal_portfolio(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        seat = _integer(observation.get("player"))
        farm = observation["farms"][seat]
        day = _integer(observation.get("day"))
        prices = (observation.get("market") or {}).get("prices") or {}
        wheat_price = max(1, _integer(prices.get("WHEAT"), 1))
        private = observation.get("private") or {}
        shed_used = sum(_integer(value) for value in (private.get("shed") or {}).values())
        shed_free = max(0, 100 - shed_used)
        terminal_drop = day >= 29 and _integer(observation.get("hour")) >= 23
        plans: list[dict[str, Any]] = []
        committed_feed = 0
        for y, row in enumerate(farm.get("tiles") or []):
            for x, tile in enumerate(row):
                if not isinstance(tile, Mapping) or not tile.get("animal"):
                    continue
                animal = str(tile.get("animal"))
                product = str(ANIMAL_RULES[animal]["product"])
                next_day = next_animal_production_day(tile, day)
                days = 99 if next_day is None else max(1, next_day - day)
                expected_units = max(1, 1 + _integer(tile.get("pending_care_bonus")))
                expected_value = expected_units * max(1, _integer(prices.get(product), 1))
                feed_cost = days * wheat_price
                harvestable = _integer(tile.get("yield_units")) > 0
                recovery_route = not terminal_drop or shed_free >= _integer(tile.get("yield_units"))
                urgent_survival = _integer(tile.get("consecutive_unfed")) >= 1
                recoverable_in_season = next_day is not None and next_day <= 29
                maintain = (harvestable and recovery_route) or (recoverable_in_season and (urgent_survival or expected_value >= 0.5 * feed_cost))
                state = "MAINTAIN" if maintain else "RETIRE"
                if harvestable and recovery_route:
                    state = "HARVEST_PENDING"
                if maintain and not bool(tile.get("fed_today")):
                    committed_feed += 1
                plan_id = f"ANIMAL:{animal}:{x},{y}:placed{tile.get('placed_day')}:day{day}"
                record = {
                    "plan_id": plan_id,
                    "target_identity": target_identity(tile, (x, y)),
                    "state": state,
                    "next_production_day": next_day,
                    "yield_units": _integer(tile.get("yield_units")),
                    "feed_cost_to_production": feed_cost,
                    "expected_product_value": expected_value,
                    "shed_free_capacity": shed_free,
                    "recovery_route_available": recovery_route,
                    "maintenance_deadline_step": day * 24 + 23,
                    "retirement_reason": None if maintain else (
                        "TERMINAL_SHED_CAPACITY_BLOCKS_REALIZATION"
                        if harvestable and not recovery_route
                        else "NO_RECOVERABLE_PRODUCTION_WITHIN_SEASON_OR_COST_BOUND"
                    ),
                }
                plans.append(record)
                self.animal_plan_ledger[plan_id] = record
        carried = sum(_integer(inv.get("WHEAT")) for inv in private.get("inventories") or [])
        shed_wheat = _integer((private.get("shed") or {}).get("WHEAT"))
        accessible = carried + shed_wheat
        if _integer(observation.get("hour")) >= 20 and day < 29:
            committed_feed += sum(1 for row in plans if row["state"] in {"MAINTAIN", "HARVEST_PENDING"})
        reserve_from_shed = max(0, committed_feed - carried)
        cash_required = max(0, committed_feed - accessible) * wheat_price
        return {
            "plans": plans,
            "committed_feed_requirements": committed_feed,
            "accessible_wheat": accessible,
            "carried_wheat": carried,
            "shed_wheat": shed_wheat,
            "reserved_shed_wheat": reserve_from_shed,
            "unreserved_wheat": max(0, accessible - committed_feed),
            "committed_near_term_cash_requirements": cash_required,
            "unreserved_cash": max(0, _integer(farm.get("money")) - cash_required),
        }

    def _repair_market(
        self,
        observation: Mapping[str, Any],
        orders: list[list[Any]],
        portfolio: Mapping[str, Any],
        working: WorkingState,
    ) -> list[list[Any]]:
        """Simulate this seat's ordered market queue one unit at a time.

        The fixed engine interleaves the opponent at each order slot.  That
        action is unavailable at decision time, so this ledger exactly models
        our own queue and records the remaining concurrent-price uncertainty.
        """
        seat = _integer(observation.get("player"))
        farm = observation["farms"][seat]
        money = _integer(farm.get("money"))
        shed = deepcopy(working.shed)
        seeds = deepcopy(working.seeds)
        room = max(0, working.capacity - sum(_integer(value) for value in shed.values()))
        market = observation.get("market") or {}
        market_inventory = {item: _integer((market.get("inventory") or {}).get(item), 10000) for item in PRODUCTS}
        params = market.get("params") if isinstance(market.get("params"), Mapping) else None
        hires = _integer(farm.get("hires_today"))
        lands = max(0, len(farm.get("unlocked_quadrants") or []) - 1)
        accessible_wheat = _integer(shed.get("WHEAT")) + sum(_integer(value.get("WHEAT")) for value in working.inventories)
        feed_shortage = max(0, _integer(portfolio.get("committed_feed_requirements")) - accessible_wheat)
        raw_orders = [list(value) for value in orders[:10] if value]
        requested_feed = sum(max(1, _integer(value[2], 1)) for value in raw_orders if value[:2] == ["BUY_PRODUCT", "WHEAT"])
        if requested_feed < feed_shortage and len(raw_orders) < 10:
            raw_orders.insert(0, ["BUY_PRODUCT", "WHEAT", feed_shortage - requested_feed])
        result: list[list[Any]] = []
        structure_capacity = sum(
            1
            for row in working.tiles
            for tile in row
            if isinstance(tile, Mapping) and tile.get("kind") in {"COOP", "PASTURE"} and not tile.get("animal")
        )

        def feed_reserve_cost() -> int:
            inventory = market_inventory["WHEAT"]
            return sum(_market_price("WHEAT", inventory - offset - 1, params) for offset in range(feed_shortage))

        for raw in raw_orders[:10]:
            order = list(raw)
            op = str(order[0])
            item = str(order[1]) if len(order) > 1 else ""
            quantity = max(1, _integer(order[2], 1) if len(order) > 2 else 1)
            emitted = 0
            if op == "HIRE":
                cost = _fib(hires)
                if money - cost >= feed_reserve_cost():
                    money -= cost
                    hires += 1
                    result.append(["HIRE"])
                else:
                    self.stats["investment_orders_blocked"] += 1
                continue
            if op == "BUY_LAND":
                cost = LAND_COST[lands] if lands < len(LAND_COST) else 10**9
                labor_buffer = max(1, len(actor_positions(observation))) * 10
                if money - cost < feed_reserve_cost() + labor_buffer:
                    self.stats["investment_orders_blocked"] += 1
                    continue
                money -= cost
                lands += 1
                result.append(["BUY_LAND"])
                continue
            for _ in range(quantity):
                reserve_after = feed_reserve_cost()
                if op == "SELL" and item in PRODUCTS:
                    if _integer(shed.get(item)) <= 0:
                        break
                    if item == "WHEAT" and accessible_wheat - 1 < _integer(portfolio.get("committed_feed_requirements")):
                        self.stats["wheat_sell_units_blocked"] += quantity - emitted
                        break
                    price = _market_price(item, market_inventory[item], params)
                    shed[item] = _integer(shed.get(item)) - 1
                    accessible_wheat -= int(item == "WHEAT")
                    money += price
                    if price > 1:
                        market_inventory[item] += 1
                    room += 1
                elif op == "BUY_PRODUCT" and item in {"WHEAT", "FERTILIZER"}:
                    price = _market_price(item, market_inventory[item] - 1, params)
                    required_feed_unit = item == "WHEAT" and feed_shortage > 0
                    if room <= 0 or money < price or (not required_feed_unit and money - price < reserve_after):
                        break
                    money -= price
                    market_inventory[item] -= 1
                    shed[item] = _integer(shed.get(item)) + 1
                    room -= 1
                    if item == "WHEAT":
                        accessible_wheat += 1
                        feed_shortage = max(0, feed_shortage - 1)
                elif op == "BUY_SEED" and item in SEED_COST:
                    price = SEED_COST[item]
                    if money - price < reserve_after:
                        break
                    money -= price
                    seeds[item] = _integer(seeds.get(item)) + 1
                elif op == "BUY_ANIMAL" and item in ANIMAL_COST:
                    price = ANIMAL_COST[item]
                    continuation_days = _integer(ANIMAL_RULES[item].get("first_yield_day"), 8)
                    continuation = sum(
                        _market_price("WHEAT", market_inventory["WHEAT"] - offset - 1, params)
                        for offset in range(continuation_days)
                    )
                    if structure_capacity <= 0 or room <= 0 or money - price - continuation < reserve_after:
                        break
                    money -= price
                    shed[item] = _integer(shed.get(item)) + 1
                    room -= 1
                    structure_capacity -= 1
                else:
                    break
                emitted += 1
            if emitted > 0:
                result.append([op, item, emitted])
            if emitted < quantity and op in {"BUY_SEED", "BUY_PRODUCT", "BUY_ANIMAL"}:
                self.stats["investment_orders_blocked"] += 1
        return result[:10]

    def _urgent_targets(
        self,
        observation: Mapping[str, Any],
        working: WorkingState,
        excluded: set[tuple[int, int]],
        retiring: set[tuple[int, int]],
    ) -> list[tuple[int, tuple[int, int], str]]:
        result: list[tuple[int, tuple[int, int], str]] = []
        for y, row in enumerate(working.tiles):
            for x, tile in enumerate(row):
                position = (x, y)
                if position in excluded or not isinstance(tile, Mapping):
                    continue
                if tile.get("animal"):
                    if position in retiring:
                        continue
                    if _integer(tile.get("yield_units")) > 0:
                        result.append((0, position, "HARVEST"))
                    elif not bool(tile.get("fed_today")):
                        result.append((1 if _integer(tile.get("consecutive_unfed")) else 3, position, "FEED"))
                    elif bool(tile.get("fertilizer_available")):
                        result.append((4, position, "COLLECT_FERTILIZER"))
                    elif not bool(tile.get("cared_today")):
                        result.append((5, position, "CARE"))
                elif tile.get("kind") == "PLANT":
                    crop = str(tile.get("crop") or "")
                    rule = CROP_RULES.get(crop, {})
                    mature = working.day - _integer(tile.get("planted_day")) >= _integer(rule.get("first_yield_day"), 999)
                    if mature and _integer(tile.get("yield_units")) > 0:
                        result.append((2, position, "HARVEST"))
                    elif not bool(tile.get("watered_today")):
                        result.append((6, position, "WATER"))
        return result

    def _alternate(
        self,
        observation: Mapping[str, Any],
        working: WorkingState,
        actor: int,
        excluded: set[tuple[int, int]],
        retiring: set[tuple[int, int]],
    ) -> tuple[list[Any], tuple[int, int] | None]:
        position = working.positions[actor]
        tile = working.tile(position)
        inventory = working.inventories[actor]
        if isinstance(tile, Mapping) and tile.get("animal"):
            if position in retiring:
                pass
            elif _integer(tile.get("yield_units")) > 0:
                return ["HARVEST"], position
            elif not bool(tile.get("fed_today")) and _integer(inventory.get("WHEAT")) > 0:
                return ["FEED"], position
            elif bool(tile.get("fertilizer_available")):
                return ["COLLECT_FERTILIZER"], position
            elif bool(tile.get("fed_today")) and not bool(tile.get("cared_today")):
                future = next_animal_production_day(tile, working.day, strictly_after=True)
                if future is not None and future <= 29:
                    return ["CARE"], position
        if isinstance(tile, Mapping) and tile.get("kind") == "PLANT":
            crop = str(tile.get("crop") or "")
            mature = working.day - _integer(tile.get("planted_day")) >= _integer(CROP_RULES.get(crop, {}).get("first_yield_day"), 999)
            if mature and _integer(tile.get("yield_units")) > 0:
                return ["HARVEST"], position
            if not bool(tile.get("watered_today")):
                return ["WATER"], position
        if _shed_access(position) and any(
            _integer(value) > 0 for key, value in inventory.items() if key not in {*ANIMAL_RULES, "WHEAT", "FERTILIZER"}
        ):
            return ["DROP"], position
        targets = self._urgent_targets(observation, working, excluded, retiring)
        if targets:
            _priority, target, _op = min(targets, key=lambda row: (row[0], _distance(position, row[1]), row[1]))
            return _move_toward(position, target), target
        return ["PASS"], None

    def repair(self, observation: Mapping[str, Any], proposal: Mapping[str, Any], skill_scores: Mapping[str, float] | None = None) -> dict[str, Any]:
        self._verify_pending(observation)
        positions = actor_positions(observation)
        result = _shape(proposal, max(0, len(positions) - 1))
        original = deepcopy(result)
        scores = skill_scores or {}
        portfolio = self._animal_portfolio(observation)
        retiring = {
            tuple(int(value) for value in row["target_identity"]["coordinate"])
            for row in portfolio["plans"]
            if row["state"] == "RETIRE"
        }
        candidates = _units(result)
        # A newly planted crop starts with consecutive_unwatered=1 in the
        # fixed engine.  On hour 23 it survives only if a later actor at the
        # same coordinate waters it in this same ordered joint action.
        doomed_last_hour_plants: set[int] = set()
        if _integer(observation.get("hour")) == 23:
            for actor, unit in enumerate(candidates):
                if not unit or unit[0] != "PLANT":
                    continue
                position = positions[actor]
                if not any(
                    later < len(positions)
                    and positions[later] == position
                    and bool(candidates[later])
                    and candidates[later][0] == "WATER"
                    for later in range(actor + 1, len(candidates))
                ):
                    doomed_last_hour_plants.add(actor)
        # A pickup must preserve this actor's observable fair share of the
        # already accepted daily feed commitments.  This keeps the Round3
        # WHEAT1->2 continuation regression from returning.
        active = max(1, len(positions))
        fair_feed_share = math.ceil(_integer(portfolio.get("committed_feed_requirements")) / active)
        available_shed_wheat = _integer((observation.get("private") or {}).get("shed", {}).get("WHEAT"))
        for actor, unit in enumerate(candidates):
            if unit[:2] == ["PICKUP", "WHEAT"]:
                requested = max(1, _integer(unit[2], 1) if len(unit) > 2 else 1)
                required = min(available_shed_wheat, max(requested, fair_feed_share))
                if required > requested:
                    candidates[actor] = ["PICKUP", "WHEAT", required]
        # Harvest a full animal product buffer before movement can abandon it.
        for actor, unit in enumerate(candidates):
            tile = tile_at(observation, positions[actor])
            if not isinstance(tile, Mapping) or not tile.get("animal"):
                continue
            rule = ANIMAL_RULES.get(str(tile.get("animal")), {})
            full = _integer(tile.get("yield_units")) >= _integer(rule.get("max_held"), 10**9)
            selected = float(scores.get("ANIMAL_LIFECYCLE_REALIZATION", 0.0)) >= 0.45
            if positions[actor] not in retiring and _integer(tile.get("yield_units")) > 0 and (full or _integer(observation.get("day")) >= 28 or selected):
                if unit != ["HARVEST"]:
                    candidates[actor] = ["HARVEST"]
                    self.stats["animal_harvest_overrides"] += 1

        working = WorkingState(observation)
        demand: dict[str, int] = {}
        for unit in candidates:
            if unit and unit[0] == "PLANT" and len(unit) > 1:
                crop = str(unit[1])
                demand[crop] = demand.get(crop, 0) + 1
        blocked_plants = {crop for crop, count in demand.items() if count > _integer(working.seeds.get(crop))}
        self.stats["atomic_plants_blocked"] += sum(demand[crop] for crop in blocked_plants)
        claimed_targets: set[tuple[int, int]] = set()
        emitted_units: list[list[Any]] = []
        plan_by_actor: dict[int, TypedPlan] = {}
        for actor, proposed in enumerate(candidates):
            original_unit = _units(original)[actor]
            unit = proposed
            if unit == ["PASS"] and max(float(scores.get("ANIMAL_LIFECYCLE_REALIZATION", 0.0)), float(scores.get("HARVEST_AND_LAND_CONVERSION", 0.0))) >= 0.45:
                unit, _target = self._alternate(observation, working, actor, claimed_targets, retiring)
            retirement_service = positions[actor] in retiring and unit and unit[0] in {"HARVEST", "FEED", "CARE", "COLLECT_FERTILIZER"}
            if retirement_service:
                emitted, reason = None, "ANIMAL_RETIREMENT_PLAN"
                self.stats["retirement_plans_enforced"] += 1
            elif actor in doomed_last_hour_plants and unit and unit[0] == "PLANT":
                emitted, reason = None, "PLANT_WOULD_DIE_AT_DAY_BOUNDARY"
            else:
                emitted, reason = working.apply(actor, unit, blocked_plants)
            target_before = positions[actor]
            if emitted is None:
                self.stats["resource_conflicts_blocked"] += 1
                if unit and unit[0] == "HARVEST" and reason == "HARVEST_RESOURCE_EMPTY":
                    self.stats["duplicate_harvests_blocked"] += 1
                if unit and unit[0] in {"FEED", "WATER", "CARE", "COLLECT_FERTILIZER"}:
                    self.stats["duplicate_services_blocked"] += 1
                replacement, target = self._alternate(observation, working, actor, claimed_targets, retiring)
                emitted, replacement_reason = working.apply(actor, replacement, blocked_plants)
                if emitted is None:
                    emitted, replacement_reason = ["PASS"], "NO_VALID_ALTERNATE"
                    self.stats["fallback_passes"] += 1
                else:
                    self.stats["actors_reassigned"] += 1
                    if target is not None:
                        claimed_targets.add(target)
                self._event(observation, "resource_conflict_replan", actor=actor, rejected=list(unit), reason=reason, emitted=emitted, replacement_reason=replacement_reason)
            op = str(emitted[0]) if emitted else "PASS"
            if op in {"HARVEST", "FEED", "WATER", "CARE", "COLLECT_FERTILIZER"}:
                claimed_targets.add(target_before)
            if op == "HARVEST":
                plan, _precondition = make_harvest_plan(observation, actor, strategy_mode=self.label, origin="base_observed_action" if original_unit == emitted else "executor_correction")
                if plan is not None:
                    plan_by_actor[actor] = plan
            elif op == "FEED":
                plan_by_actor[actor] = make_feed_plan(observation, actor, target_before, 1, observation_digest(observation, actor), strategy_mode=self.label, origin="base_observed_action" if original_unit == emitted else "executor_correction")
            emitted_units.append(emitted)
        for actor, emitted in enumerate(emitted_units):
            _set_unit(result, actor, emitted)
        result["market"] = self._repair_market(observation, result["market"], portfolio, working)
        if result["market"] != original["market"]:
            self.stats["market_orders_changed"] += 1
            self._event(
                observation,
                "market_reservation_repair",
                before=original["market"],
                after=result["market"],
                portfolio=portfolio,
                price_model="fixed-engine own-queue per-unit; concurrent opponent order unknown",
            )

        before_snapshot = deepcopy(dict(observation))
        pending: list[dict[str, Any]] = []
        for actor, emitted in enumerate(emitted_units):
            op = str(emitted[0]) if emitted else "PASS"
            changed = emitted != _units(original)[actor]
            if op in TRACKED:
                self.stats["override_primitive_issued" if changed else "base_primitive_issued"] += 1
                plan = plan_by_actor.get(actor)
                if plan is not None:
                    self.stats["plan_started"] += 1
                    self._event(observation, "plan_started", plan=plan.contract())
                pending.append({
                    "kind": "primitive",
                    "before": before_snapshot,
                    "actor": actor,
                    "action": list(emitted),
                    "target": positions[actor],
                    "plan_id": plan.plan_id if plan else None,
                    "terminal": op in {"HARVEST", "FEED", "WATER", "CARE", "COLLECT_FERTILIZER", "PLANT", "DROP", "PLACE"},
                })
        for index, order in enumerate(result["market"]):
            if order and order[0] == "SELL" and len(order) >= 3 and _integer(order[2]) > 0:
                plan_id = f"CASH_REALIZATION:{order[1]}:s{canonical_step(observation)}:slot{index}"
                self.stats["cash_realization_started"] += 1
                pending.append({
                    "kind": "market_sell",
                    "before": before_snapshot,
                    "item": str(order[1]),
                    "quantity": _integer(order[2]),
                    "pre_market_shed": _integer(working.shed.get(str(order[1]))),
                    "plan_id": plan_id,
                })
        seat = _integer(observation.get("player"))
        self.pending[seat] = pending
        self.stats["terminal_pending"] = sum(len(value) for value in self.pending.values())
        return result

    def diagnostics(self) -> dict[str, Any]:
        return {
            "executor": "round5-ordered-resource-ledger-v1",
            "policy": self.label,
            **self.stats,
            "terminal_pending": sum(len(value) for value in self.pending.values()),
            "animal_plan_count": len(self.animal_plan_ledger),
            "completed_plan_ids": len(self.completed_plan_ids),
        }

    def policy_trace(self) -> list[dict[str, Any]]:
        return deepcopy(self.trace)

    def animal_plans(self) -> list[dict[str, Any]]:
        return deepcopy(list(self.animal_plan_ledger.values()))


__all__ = ["ExecutionCoordinator", "WorkingState"]
