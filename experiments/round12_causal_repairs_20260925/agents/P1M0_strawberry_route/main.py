"""Round12 independent early-strawberry production controller.

This is a complete route, not a B1 prefix patch. It targets nine day-0 wheat
plots, eight early strawberries from day 2, annual-crop financing in spare
cells, and expansion to sixteen strawberries from day 15. It controls land,
seed, daily labor, watering, harvest, transport and market liquidation through
the terminal turn. The builder replaces R12_ROUTE_MARKET_MODE with M0 or M1.
"""

import math

R12_ROUTE_MARKET_MODE = "M0"
_R12_ROUTE = {}
_R12_PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")
_R12_BASE_PRICE = {"WHEAT": 25, "STRAWBERRY": 120}
_R12_PARAMS = {
    "WHEAT": {"base": 25, "I0": 10000, "T": 400, "above_func": "log", "above_target": 0.20},
    "STRAWBERRY": {"base": 120, "I0": 10000, "T": 100, "above_func": "linear", "above_target": 1.60},
}
_R12_SHOPS = {
    "BAKERY": ("EGG", "WHEAT"),
    "PIZZA_SHOP": ("MILK", "TOMATO", "WHEAT"),
    "BRUNCH_SPOT": ("EGG", "WHEAT", "STRAWBERRY"),
    "YARN_STORE": ("WOOL",),
    "ICE_CREAM_SHOP": ("STRAWBERRY", "MILK", "WHEAT"),
    "PET_CAFE": ("CARROT",),
    "SMOOTHIE_SHOP": ("STRAWBERRY", "MILK"),
    "FARMERS_MARKET": ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"),
}
_R12_ROUTE_REPORT = {
    "controller": "early8_day15_to16",
    "market_mode": R12_ROUTE_MARKET_MODE,
    "calls": 0,
    "land_requests": 0,
    "hire_requests": 0,
    "seed_requests": {"WHEAT": 0, "STRAWBERRY": 0},
    "water_requests": 0,
    "harvest_requests": 0,
    "drop_requests": 0,
    "plant_requests": {"WHEAT": 0, "STRAWBERRY": 0},
    "sell_requests": {"WHEAT": 0, "STRAWBERRY": 0},
    "wait_decisions": 0,
    "sell_decisions": 0,
    "maintenance_failures_observed": 0,
}


def _r12_route_price(item, inventory):
    p = _R12_PARAMS[item]
    x = max(0, int(inventory) - p["I0"])
    if p["above_func"] == "linear":
        shape, scale = x, p["T"]
    else:
        shape, scale = math.log1p(x), math.log1p(p["T"])
    value = p["base"] - p["above_target"] * p["base"] * shape / scale
    return max(1, int(round(value)))


def _r12_route_revenue(item, inventory, quantity):
    revenue = 0
    inventory = int(inventory)
    for _ in range(max(0, int(quantity))):
        quote = _r12_route_price(item, inventory)
        revenue += quote
        if quote > 1:
            inventory += 1
    return revenue


def _r12_route_town_draw(observation, item):
    step = int(observation["step"])
    draw = int(step % 24 == 0)
    if step % 4 == 0:
        for shop in observation["town"]["unlocked_shops"]:
            products = _R12_SHOPS.get(shop, ())
            if item in products:
                draw += 2 if len(products) == 1 else 1
    return draw


def _r12_home(position):
    homes = ((4, 4), (5, 4), (4, 5), (5, 5))
    return min(homes, key=lambda target: (abs(position[0] - target[0]) + abs(position[1] - target[1]), target))


def _r12_walk(position, target):
    x, y = position
    tx, ty = target
    if x != tx:
        return ["EAST" if x < tx else "WEST"]
    if y != ty:
        return ["SOUTH" if y < ty else "NORTH"]
    return None


def _r12_route_cells(farm):
    cells = []
    for y in range(5):
        for x in range(10):
            if farm["tiles"][y][x] != "LOCKED":
                cells.append((x, y))
    return cells


def _r12_crop_counts(farm):
    counts = {"WHEAT": 0, "STRAWBERRY": 0}
    for row in farm["tiles"]:
        for tile in row:
            if isinstance(tile, dict) and tile.get("kind") == "PLANT" and tile.get("crop") in counts:
                counts[tile["crop"]] += 1
    return counts


def _r12_assign_targets(observation):
    player = int(observation["player"])
    farm = observation["farms"][player]
    private = observation["private"]
    day = int(observation["day"])
    positions = [list(farm["farmer"])] + [list(value) for value in farm["hands"]]
    inventories = private["inventories"]
    cells = _r12_route_cells(farm)
    desired_strawberries = 0 if day < 2 else 8 if day < 15 else 16
    counts = _r12_crop_counts(farm)
    assigned = set()
    commands = []
    reserved_seed = {"WHEAT": 0, "STRAWBERRY": 0}

    def nearest(position, options):
        available = [target for target in options if target not in assigned]
        if not available:
            return None
        return min(available, key=lambda target: (abs(position[0] - target[0]) + abs(position[1] - target[1]), target[1], target[0]))

    urgent_water = []
    unwatered = []
    harvestable = []
    weeds = []
    empty = []
    for x, y in cells:
        tile = farm["tiles"][y][x]
        if tile is None:
            empty.append((x, y))
        elif isinstance(tile, dict) and tile.get("kind") == "WEED":
            weeds.append((x, y))
        elif isinstance(tile, dict) and tile.get("kind") == "PLANT":
            if not tile.get("watered_today", False):
                if int(tile.get("consecutive_unwatered", 0)) >= 1:
                    urgent_water.append((x, y))
                else:
                    unwatered.append((x, y))
            crop = tile.get("crop")
            age = day - int(tile.get("planted_day", day))
            if tile.get("yield_units", 0) > 0 and (crop == "STRAWBERRY" or (crop == "WHEAT" and (age >= 4 or day >= 14))):
                harvestable.append((x, y))
            if int(tile.get("consecutive_unwatered", 0)) >= 1:
                _R12_ROUTE_REPORT["maintenance_failures_observed"] += 1

    for actor, position in enumerate(positions):
        inventory = inventories[actor] if actor < len(inventories) else {}
        if any(int(value) > 0 for value in inventory.values()):
            home = _r12_home(position)
            command = _r12_walk(position, home)
            if command is None:
                command = ["DROP"]
                _R12_ROUTE_REPORT["drop_requests"] += 1
            commands.append(command)
            continue
        target = nearest(position, urgent_water)
        if target is None:
            target = nearest(position, unwatered)
        if target is not None:
            assigned.add(target)
            command = _r12_walk(position, target)
            if command is None:
                command = ["WATER"]
                _R12_ROUTE_REPORT["water_requests"] += 1
            commands.append(command)
            continue
        target = nearest(position, harvestable)
        if target is not None:
            assigned.add(target)
            command = _r12_walk(position, target)
            if command is None:
                command = ["HARVEST"]
                _R12_ROUTE_REPORT["harvest_requests"] += 1
            commands.append(command)
            continue
        target = nearest(position, weeds)
        if target is not None:
            assigned.add(target)
            command = _r12_walk(position, target)
            commands.append(command if command is not None else ["DIG"])
            continue
        strawberry_need = max(0, desired_strawberries - counts["STRAWBERRY"] - reserved_seed["STRAWBERRY"])
        wheat_allowed = day <= 10
        crop = None
        if strawberry_need and private["seeds"].get("STRAWBERRY", 0) > reserved_seed["STRAWBERRY"]:
            crop = "STRAWBERRY"
        elif wheat_allowed and private["seeds"].get("WHEAT", 0) > reserved_seed["WHEAT"]:
            crop = "WHEAT"
        # A newly planted crop starts with one unwatered day.  Do not start a
        # distant late-day planting that cannot be reached and watered before
        # the daily maintenance transition.
        target = nearest(position, empty) if crop and int(observation["hour"]) <= 16 else None
        if target is not None:
            assigned.add(target)
            command = _r12_walk(position, target)
            if command is None:
                command = ["PLANT", crop]
                reserved_seed[crop] += 1
                _R12_ROUTE_REPORT["plant_requests"][crop] += 1
            commands.append(command)
            continue
        commands.append(["PASS"])
    return commands


def _r12_route_projected_shed(observation, commands):
    shed = dict(observation["private"]["shed"])
    total = sum(int(value) for value in shed.values())
    positions = [observation["farms"][int(observation["player"])]["farmer"]] + list(observation["farms"][int(observation["player"])]["hands"])
    inventories = observation["private"]["inventories"]
    homes = {(4, 4), (5, 4), (4, 5), (5, 5)}
    for index, command in enumerate(commands):
        if index >= len(positions) or tuple(positions[index]) not in homes or not command:
            continue
        if command[0] == "DROP" and index < len(inventories):
            for item, value in inventories[index].items():
                take = min(max(0, int(value)), max(0, 100 - total))
                shed[item] = shed.get(item, 0) + take
                total += take
    return shed


def _r12_should_sell(observation, item, quantity, projected_total):
    if quantity <= 0:
        return False
    if R12_ROUTE_MARKET_MODE == "M0" or int(observation["step"]) >= 712:
        return True
    inventory = int(observation["market"]["inventory"][item])
    draw = _r12_route_town_draw(observation, item)
    now = _r12_route_revenue(item, inventory, quantity)
    wait = _r12_route_revenue(item, inventory - draw, quantity)
    # Capacity pressure and a non-improving one-turn wait both force liquidation.
    return projected_total >= 80 or now >= wait


def _r12_route_market(observation, commands):
    player = int(observation["player"])
    farm = observation["farms"][player]
    private = observation["private"]
    day, hour = int(observation["day"]), int(observation["hour"])
    counts = _r12_crop_counts(farm)
    projected = _r12_route_projected_shed(observation, commands)
    total = sum(int(value) for value in projected.values())
    orders = []
    for item in ("STRAWBERRY", "WHEAT"):
        quantity = int(projected.get(item, 0))
        if _r12_should_sell(observation, item, quantity, total):
            orders.append(["SELL", item, quantity])
            _R12_ROUTE_REPORT["sell_requests"][item] += quantity
            _R12_ROUTE_REPORT["sell_decisions"] += 1
        elif quantity:
            _R12_ROUTE_REPORT["wait_decisions"] += 1
    money = float(farm["money"])
    if "NE" not in farm["unlocked_quadrants"] and money >= 1000:
        orders.append(["BUY_LAND"])
        money -= 1000
        _R12_ROUTE_REPORT["land_requests"] += 1
    strawberry_target = 0 if day < 2 else 8 if day < 15 else 16
    strawberry_need = max(0, strawberry_target - counts["STRAWBERRY"] - int(private["seeds"].get("STRAWBERRY", 0)))
    if strawberry_need and money >= 100:
        quantity = min(strawberry_need, int(max(0, money - 100) // 100))
        if quantity:
            orders.append(["BUY_SEED", "STRAWBERRY", quantity])
            money -= 100 * quantity
            _R12_ROUTE_REPORT["seed_requests"]["STRAWBERRY"] += quantity
    if day <= 10:
        # The opening financing crop is capped at nine plants so day-2
        # strawberry space and same-day watering capacity remain available.
        # Annual filler resumes only after the opening wheat can be harvested.
        desired_wheat = 9 if day == 0 else (12 if day >= 4 else 0)
        wheat_need = max(
            0,
            desired_wheat
            - counts["WHEAT"]
            - int(private["seeds"].get("WHEAT", 0)),
        )
        if wheat_need and money >= 10:
            quantity = min(wheat_need, int(max(0, money - 50) // 10))
            if quantity:
                orders.append(["BUY_SEED", "WHEAT", quantity])
                money -= 10 * quantity
                _R12_ROUTE_REPORT["seed_requests"]["WHEAT"] += quantity
    if hour == 0:
        for _ in range(7):
            if len(orders) >= 10:
                break
            orders.append(["HIRE"])
            _R12_ROUTE_REPORT["hire_requests"] += 1
    return orders[:10]


def strawberry_route_agent(observation, configuration=None):
    player, step = int(observation["player"]), int(observation["step"])
    state = _R12_ROUTE.get(player)
    if state is None or step <= state.get("step", -1):
        _R12_ROUTE[player] = {"step": -1}
        if step == 0:
            for key in ("calls", "land_requests", "hire_requests", "water_requests", "harvest_requests", "drop_requests", "wait_decisions", "sell_decisions", "maintenance_failures_observed"):
                _R12_ROUTE_REPORT[key] = 0
            for key in ("seed_requests", "plant_requests", "sell_requests"):
                for item in _R12_ROUTE_REPORT[key]:
                    _R12_ROUTE_REPORT[key][item] = 0
    _R12_ROUTE[player]["step"] = step
    _R12_ROUTE_REPORT["calls"] += 1
    commands = _r12_assign_targets(observation)
    market = _r12_route_market(observation, commands)
    return {"farmer": commands[0], "hands": commands[1:], "market": market}


strawberry_route_agent.telemetry = _R12_ROUTE_REPORT
