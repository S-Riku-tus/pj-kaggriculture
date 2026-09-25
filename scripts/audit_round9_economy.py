"""Independent fixed-engine work/economy accounting for Round9 replay panels."""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kaggle_environments.envs.kaggriculture import kaggriculture as engine

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "round9_teacher_reproduction_and_closed_loop_bc_20260923"
DEFAULT_PANELS = (
    "development_panel_a0",
    "development_panel_a1",
    "development_panel_a2",
    "development_panel_a2_expanded64",
)
MOVE = {"NORTH", "SOUTH", "EAST", "WEST"}
PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def units(action: dict[str, Any]) -> list[list[Any]]:
    return [list(action.get("farmer") or ["PASS"]), *[list(value or ["PASS"]) for value in action.get("hands") or []]]


def private_for(states: list[dict[str, Any]], seat: int) -> dict[str, Any]:
    return copy.deepcopy((states[seat].get("observation") or {}).get("private") or {})


def state_fingerprint(farm: dict[str, Any], private: dict[str, Any], actor: int) -> str:
    positions = [farm["farmer"], *farm.get("hands", [])]
    position = positions[actor]
    x, y = int(position[0]), int(position[1])
    value = {
        "position": position,
        "tile": farm["tiles"][y][x],
        "inventory": private["inventories"][actor],
        "shed": private["shed"],
        "seeds": private["seeds"],
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def item_deltas(after: dict[str, Any], before: dict[str, Any]) -> Counter[str]:
    keys = set(before) | set(after)
    return Counter({str(key): int(after.get(key, 0)) - int(before.get(key, 0)) for key in keys})


def apply_actors(
    farms: list[dict[str, Any]], privates: list[dict[str, Any]], actions: list[dict[str, Any]], step: int
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "issued": Counter(),
        "effective": Counter(),
        "pickup": Counter(),
        "harvest": Counter(),
        "deposit": Counter(),
        "placed_assets": Counter(),
    }
    day = step // 24
    for seat in range(2):
        requested = units(actions[seat])
        plant_demand = Counter(str(value[1]) for value in requested if len(value) >= 2 and value[0] == "PLANT")
        blocked = {
            crop for crop, demand in plant_demand.items() if demand > int(privates[seat].get("seeds", {}).get(crop, 0))
        }
        for index, raw in enumerate(requested):
            if index >= len(privates[seat].get("inventories", [])):
                continue
            action = ["PASS"] if len(raw) >= 2 and raw[0] == "PLANT" and raw[1] in blocked else raw
            op = str(action[0]) if action else "PASS"
            before_fp = state_fingerprint(farms[seat], privates[seat], index)
            before_inv = copy.deepcopy(privates[seat]["inventories"][index])
            before_shed = copy.deepcopy(privates[seat]["shed"])
            positions = [farms[seat]["farmer"], *farms[seat].get("hands", [])]
            x, y = positions[index]
            before_tile = copy.deepcopy(farms[seat]["tiles"][y][x])
            engine._apply_unit_action(farms[seat], privates[seat], index, action, 10, day, 24, 100)
            after_fp = state_fingerprint(farms[seat], privates[seat], index)
            if seat == 0:
                result["issued"][op] += 1
                result["effective"][op] += int(before_fp != after_fp)
                inv_delta = item_deltas(privates[seat]["inventories"][index], before_inv)
                shed_delta = item_deltas(privates[seat]["shed"], before_shed)
                if op == "PICKUP":
                    for item, value in inv_delta.items():
                        if value > 0:
                            result["pickup"][item] += value
                if op == "HARVEST":
                    for item, value in inv_delta.items():
                        if value > 0:
                            result["harvest"][item] += value
                if op in {"DROP", "PLACE"}:
                    for item, value in shed_delta.items():
                        if value > 0:
                            result["deposit"][item] += value
                after_tile = farms[seat]["tiles"][y][x]
                if op == "PLANT" and before_tile is None and isinstance(after_tile, dict):
                    result["placed_assets"][f"PLANT:{after_tile.get('crop')}"] += 1
                elif op.startswith("BUILD_") and before_tile is None and isinstance(after_tile, dict):
                    result["placed_assets"][op] += 1
                elif op == "PLACE" and isinstance(after_tile, dict) and after_tile.get("animal"):
                    result["placed_assets"][f"ANIMAL:{after_tile.get('animal')}"] += 1
    return result


def process_market(
    farms: list[dict[str, Any]],
    privates: list[dict[str, Any]],
    market: dict[str, Any],
    actions: list[dict[str, Any]],
    configuration: dict[str, Any],
) -> dict[str, Any]:
    max_orders = max(1, int(configuration.get("maxMarketOrdersPerTurn", 10)))
    hire_mult = int(configuration.get("farmHandCostMult", 1))
    capacity = int(configuration.get("shedCapacity", 100))
    queues = [list(action.get("market") or [])[:max_orders] for action in actions]
    parsed = [[engine._parse_order(value) for value in queue] for queue in queues]
    totals = {
        "requested": Counter(),
        "sold": Counter(),
        "bought_seed": Counter(),
        "bought_product": Counter(),
        "bought_animal": Counter(),
        "sales_revenue": 0,
        "seed_cost": 0,
        "product_cost": 0,
        "animal_cost": 0,
        "hire_cost": 0,
        "land_cost": 0,
        "hires": 0,
        "lands": 0,
    }
    for order in queues[0]:
        if len(order) >= 3:
            totals["requested"][f"{order[0]}:{order[1]}"] += int(order[2])
        elif order:
            totals["requested"][str(order[0])] += 1
    for slot in range(max((len(value) for value in queues), default=0)):
        order_states = [parsed[seat][slot] if slot < len(parsed[seat]) else None for seat in range(2)]
        for seat, order in enumerate(order_states):
            if order is None:
                continue
            op = order["type"]
            before_money = int(farms[seat]["money"])
            before_hands = len(farms[seat].get("hands", []))
            before_land = len(farms[seat].get("unlocked_quadrants", []))
            if op == "HIRE":
                engine._do_hire(farms[seat], privates[seat], 10, hire_mult)
                if seat == 0 and len(farms[seat].get("hands", [])) > before_hands:
                    totals["hires"] += 1
                    totals["hire_cost"] += before_money - int(farms[seat]["money"])
                order_states[seat] = None
            elif op == "BUY_LAND":
                engine._do_buy_land(farms[seat], 10)
                if seat == 0 and len(farms[seat].get("unlocked_quadrants", [])) > before_land:
                    totals["lands"] += 1
                    totals["land_cost"] += before_money - int(farms[seat]["money"])
                order_states[seat] = None
        while True:
            quoted: list[Any] = [None, None]
            for seat, order in enumerate(order_states):
                if order is None or order["remaining"] <= 0:
                    continue
                op, item = order["type"], order["item"]
                if op == "SELL" and item in PRODUCTS:
                    quoted[seat] = (
                        op,
                        item,
                        engine.market_price(item, market["inventory"][item], market.get("params")),
                        order,
                    )
                elif op == "BUY_PRODUCT" and item in {"WHEAT", "FERTILIZER"}:
                    quoted[seat] = (
                        op,
                        item,
                        engine.market_price(item, market["inventory"][item] - 1, market.get("params")),
                        order,
                    )
                elif op == "BUY_SEED" and item in engine.CROPS:
                    quoted[seat] = (op, item, engine.CROPS[item]["seed"], order)
                elif op == "BUY_ANIMAL" and item in engine.ANIMALS:
                    quoted[seat] = (op, item, engine.ANIMALS[item]["cost"], order)
                else:
                    order_states[seat] = None
            if all(value is None for value in quoted):
                break
            committed = False
            for seat, quote in enumerate(quoted):
                if quote is None:
                    continue
                op, item, price, order = quote
                ok = engine._commit_unit(op, item, price, farms[seat], privates[seat], market, capacity)
                if ok:
                    order["remaining"] -= 1
                    committed = True
                    if seat == 0:
                        if op == "SELL":
                            totals["sold"][item] += 1
                            totals["sales_revenue"] += price
                        elif op == "BUY_SEED":
                            totals["bought_seed"][item] += 1
                            totals["seed_cost"] += price
                        elif op == "BUY_PRODUCT":
                            totals["bought_product"][item] += 1
                            totals["product_cost"] += price
                        elif op == "BUY_ANIMAL":
                            totals["bought_animal"][item] += 1
                            totals["animal_cost"] += price
                else:
                    order_states[seat] = None
            if not committed:
                break
        engine._refresh_prices(market)
    return totals


def tile_yields(farm: dict[str, Any]) -> Counter[str]:
    values: Counter[str] = Counter()
    product = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
    for row in farm["tiles"]:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            item = tile.get("crop") or product.get(tile.get("animal"))
            if item:
                values[str(item)] += int(tile.get("yield_units", 0))
    return values


def animal_count(farm: dict[str, Any]) -> int:
    return sum(isinstance(tile, dict) and bool(tile.get("animal")) for row in farm["tiles"] for tile in row)


def audit_game(replay_path: Path, seat: int) -> dict[str, Any]:
    with gzip.open(replay_path, "rt", encoding="utf-8") as stream:
        replay = json.load(stream)
    steps = replay["steps"]
    total = {
        "issued": Counter(),
        "effective": Counter(),
        "pickup": Counter(),
        "harvest": Counter(),
        "deposit": Counter(),
        "placed_assets": Counter(),
        "production": Counter(),
        "requested": Counter(),
        "sold": Counter(),
        "bought_seed": Counter(),
        "bought_product": Counter(),
        "bought_animal": Counter(),
    }
    scalar = Counter()
    day_boundary_unknown = 0
    animal_exits = 0
    for step in range(len(steps) - 1):
        public = copy.deepcopy(steps[step][0]["observation"])
        farms = copy.deepcopy(public["farms"])
        privates = [private_for(steps[step], index) for index in range(2)]
        market = copy.deepcopy(public["market"])
        actions = [copy.deepcopy(steps[step + 1][index].get("action") or {}) for index in range(2)]
        # Normalize analysis so focal learner is index 0, while preserving market player order.
        actor_result = apply_actors(farms, privates, actions, step)
        focal_actor_result = actor_result if seat == 0 else None
        if seat == 1:
            swapped = apply_actors(
                [copy.deepcopy(public["farms"][1]), copy.deepcopy(public["farms"][0])],
                [private_for(steps[step], 1), private_for(steps[step], 0)],
                [actions[1], actions[0]],
                step,
            )
            focal_actor_result = swapped
        assert focal_actor_result is not None
        for key in ("issued", "effective", "pickup", "harvest", "deposit", "placed_assets"):
            total[key].update(focal_actor_result[key])
        if step % 24 == 23:
            day_boundary_unknown += sum(
                count for op, count in focal_actor_result["issued"].items() if op not in MOVE | {"PASS"}
            )
        before_yield = tile_yields(farms[seat])
        market_result = process_market(farms, privates, market, actions, replay["configuration"])
        # process_market reports player 0; run a player-swapped accounting copy for seat 1.
        if seat == 1:
            farms2 = [copy.deepcopy(public["farms"][1]), copy.deepcopy(public["farms"][0])]
            privates2 = [private_for(steps[step], 1), private_for(steps[step], 0)]
            market2 = copy.deepcopy(public["market"])
            actions2 = [actions[1], actions[0]]
            apply_actors(farms2, privates2, actions2, step)
            market_result = process_market(farms2, privates2, market2, actions2, replay["configuration"])
        for key in ("requested", "sold", "bought_seed", "bought_product", "bought_animal"):
            total[key].update(market_result[key])
        for key in (
            "sales_revenue",
            "seed_cost",
            "product_cost",
            "animal_cost",
            "hire_cost",
            "land_cost",
            "hires",
            "lands",
        ):
            scalar[key] += int(market_result[key])
        if step % 24 == 23:
            next_farm = steps[step + 1][0]["observation"]["farms"][seat]
            after_yield = tile_yields(next_farm)
            for item, value in (after_yield - before_yield).items():
                if value > 0:
                    total["production"][item] += value
            animal_exits += max(0, animal_count(farms[seat]) - animal_count(next_farm))
    start_cash = int(steps[0][0]["observation"]["farms"][seat]["money"])
    final_cash = int(steps[-1][0]["observation"]["farms"][seat]["money"])
    costs = sum(scalar[key] for key in ("seed_cost", "product_cost", "animal_cost", "hire_cost", "land_cost"))
    reconciled = start_cash + scalar["sales_revenue"] - costs
    work_ops = {op for op in total["issued"] if op not in MOVE | {"PASS"}}
    work_denominator = sum(total["issued"][op] for op in work_ops)
    work_numerator = sum(total["effective"][op] for op in work_ops)
    return {
        "replay": str(replay_path.relative_to(ROOT)),
        "replay_sha256": sha256(replay_path),
        "seat": seat,
        "start_cash": start_cash,
        "final_cash": final_cash,
        "sales_revenue": scalar["sales_revenue"],
        "purchase_cost": scalar["seed_cost"] + scalar["product_cost"] + scalar["animal_cost"],
        "seed_cost": scalar["seed_cost"],
        "product_cost": scalar["product_cost"],
        "animal_cost": scalar["animal_cost"],
        "hire_cost": scalar["hire_cost"],
        "land_cost": scalar["land_cost"],
        "reconciled_cash": reconciled,
        "cash_reconciliation_error": abs(final_cash - reconciled),
        "requested_orders": dict(total["requested"]),
        "actual_sold": dict(total["sold"]),
        "actual_bought_seed": dict(total["bought_seed"]),
        "actual_bought_product": dict(total["bought_product"]),
        "actual_bought_animal": dict(total["bought_animal"]),
        "actor_pickup": dict(total["pickup"]),
        "placed_assets": dict(total["placed_assets"]),
        "produced_units_day_boundary_lower_bound": dict(total["production"]),
        "harvested_units": dict(total["harvest"]),
        "deposited_to_shed": dict(total["deposit"]),
        "animal_exits": animal_exits,
        "work_effect": {
            "numerator": work_numerator,
            "denominator": work_denominator,
            "ratio": work_numerator / work_denominator if work_denominator else None,
            "unit": "issued non-move non-PASS actor command",
            "day_boundary_terminal_unknown_count": day_boundary_unknown,
            "method": "independent fixed-engine immediate transition, not teacher imitation",
        },
        "actor_issued": dict(total["issued"]),
        "actor_effective": dict(total["effective"]),
    }


def audit_panel(panel: Path, output: Path) -> dict[str, Any]:
    games = list(csv.DictReader((panel / "games.csv").open(encoding="utf-8-sig", newline="")))
    records = []
    for row in games:
        record = audit_game(ROOT / row["replay"], int(row["seat"]))
        record.update(
            {key: row[key] for key in ("candidate", "anchor", "seed", "score", "our_cash", "opponent_cash", "margin")}
        )
        records.append(record)
    output.mkdir(parents=True, exist_ok=False)
    for index, record in enumerate(records):
        write = output / f"game_{index:03d}_{record['anchor']}_seed_{record['seed']}_seat_{record['seat']}.json"
        write.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    work_num = sum(value["work_effect"]["numerator"] for value in records)
    work_den = sum(value["work_effect"]["denominator"] for value in records)
    aggregate = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "panel": str(panel.relative_to(ROOT)),
        "games": len(records),
        "cash_reconciliation": {
            "games_exact": sum(value["cash_reconciliation_error"] == 0 for value in records),
            "games": len(records),
            "total_absolute_error": sum(value["cash_reconciliation_error"] for value in records),
        },
        "work_effect": {
            "numerator": work_num,
            "denominator": work_den,
            "ratio": work_num / work_den if work_den else None,
            "day_boundary_terminal_unknown_count": sum(
                value["work_effect"]["day_boundary_terminal_unknown_count"] for value in records
            ),
        },
        "totals": {
            key: sum(value[key] for value in records)
            for key in (
                "sales_revenue",
                "purchase_cost",
                "seed_cost",
                "product_cost",
                "animal_cost",
                "hire_cost",
                "land_cost",
                "animal_exits",
            )
        },
        "item_totals": {
            key: dict(sum((Counter(value[key]) for value in records), Counter()))
            for key in (
                "actual_sold",
                "actual_bought_seed",
                "actual_bought_product",
                "actual_bought_animal",
                "actor_pickup",
                "placed_assets",
                "produced_units_day_boundary_lower_bound",
                "harvested_units",
                "deposited_to_shed",
            )
        },
        "records": [
            {
                key: value[key]
                for key in (
                    "anchor",
                    "seed",
                    "seat",
                    "final_cash",
                    "sales_revenue",
                    "purchase_cost",
                    "hire_cost",
                    "land_cost",
                    "cash_reconciliation_error",
                    "work_effect",
                    "animal_exits",
                    "replay",
                )
            }
            for value in records
        ],
    }
    (output / "summary.json").write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("panels", nargs="*", default=list(DEFAULT_PANELS))
    args = parser.parse_args()
    summaries = {}
    for name in args.panels:
        panel = EXPERIMENT / name
        output = EXPERIMENT / "economy_audit_v1" / name
        summaries[name] = audit_panel(panel, output)
        print(
            name,
            json.dumps(
                {key: summaries[name][key] for key in ("games", "cash_reconciliation", "work_effect", "totals")}
            ),
        )
    master = EXPERIMENT / "economy_audit_v1" / "summary.json"
    if master.exists():
        suffix = hashlib.sha256("|".join(args.panels).encode()).hexdigest()[:12]
        master = master.with_name(f"summary_{suffix}.json")
        if master.exists():
            raise FileExistsError(f"refusing to overwrite {master}")
    master.write_text(json.dumps({"panels": summaries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
