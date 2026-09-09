"""Post-hoc Day 12->20 product-flow accounting for the frozen late-premium losses.

This script deliberately replays only the six already-spent Development
conditions behind ``H_WEAK_LATE_PREMIUM_REVERSAL_001``.  It does not create a
candidate policy, select a best response, or reinterpret the conditions as
independent evidence.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from kaggle_environments.envs.kaggriculture import kaggriculture as engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluation.replay import action, lineage_hash, observation  # noqa: E402
from scripts.evaluation.runner import _run_game  # noqa: E402

PRODUCTS = tuple(engine.PRODUCTS)
PREMIUM = ("STRAWBERRY", "MELON", "MILK", "WOOL")
TARGET_FAMILIES = (
    "gold_public_0b7f92b9",
    "gold_public_46d78f69",
    "gold_public_a6f1291b",
)
SEED = 29117001
WINDOW_START = 288
WINDOW_END = 480


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count(mapping: dict[str, Any], item: str) -> int:
    return max(0, int(mapping.get(item, 0) or 0))


def _private_products(private: dict[str, Any]) -> Counter[str]:
    result: Counter[str] = Counter()
    sources = [private.get("shed") or {}, *(private.get("inventories") or [])]
    for source in sources:
        for item in PRODUCTS:
            result[item] += _count(source, item)
    return result


def _tile_product(tile: Any) -> str | None:
    if not isinstance(tile, dict):
        return None
    crop = tile.get("crop")
    if crop in PRODUCTS:
        return str(crop)
    animal = tile.get("animal")
    if animal in engine.ANIMALS:
        return str(engine.ANIMALS[animal]["product"])
    return None


def _on_farm_products(farm: dict[str, Any]) -> Counter[str]:
    result: Counter[str] = Counter()
    for row in farm.get("tiles") or []:
        for tile in row or []:
            product = _tile_product(tile)
            if product is not None:
                result[product] += max(0, int(tile.get("yield_units", 0) or 0))
    return result


def _positions(farm: dict[str, Any]) -> list[list[int]]:
    return [list(farm.get("farmer") or []), *(list(row) for row in (farm.get("hands") or []))]


def _tile_at(farm: dict[str, Any], position: list[int]) -> Any:
    if len(position) != 2:
        return None
    x, y = (int(position[0]), int(position[1]))
    tiles = farm.get("tiles") or []
    return tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]) else None


def _positive_delta(after: Counter[str], before: Counter[str]) -> Counter[str]:
    return Counter({item: max(0, after[item] - before[item]) for item in PRODUCTS})


def _negative_delta(after: Counter[str], before: Counter[str]) -> Counter[str]:
    return Counter({item: max(0, before[item] - after[item]) for item in PRODUCTS})


def _apply_fields(
    farms: list[dict[str, Any]],
    privates: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    day: int,
    board_size: int,
    turns_per_day: int,
    shed_capacity: int,
) -> list[dict[str, Counter[str]]]:
    ledgers = [
        {
            "production": Counter(),
            "harvest": Counter(),
            "collect": Counter(),
            "input_consumption": Counter(),
        }
        for _ in (0, 1)
    ]
    for player in (0, 1):
        current = actions[player] if isinstance(actions[player], dict) else {}
        rows = [current.get("farmer") or ["PASS"], *(current.get("hands") or [])]
        seeds = privates[player].get("seeds") or {}
        demand = Counter(
            str(row[1])
            for row in rows
            if isinstance(row, list) and len(row) >= 2 and row[0] == "PLANT"
        )
        blocked = {crop for crop, quantity in demand.items() if quantity > _count(seeds, crop)}
        for unit, requested in enumerate(rows):
            effective = requested
            if (
                isinstance(requested, list)
                and len(requested) >= 2
                and requested[0] == "PLANT"
                and requested[1] in blocked
            ):
                effective = ["PASS"]
            positions = _positions(farms[player])
            position = positions[unit] if unit < len(positions) else []
            tile = copy.deepcopy(_tile_at(farms[player], position))
            tile_product = _tile_product(tile)
            before_private = _private_products(privates[player])
            before_farm = _on_farm_products(farms[player])
            engine._apply_unit_action(
                farms[player],
                privates[player],
                unit,
                effective,
                board_size,
                day,
                turns_per_day,
                shed_capacity,
            )
            after_private = _private_products(privates[player])
            after_farm = _on_farm_products(farms[player])
            op = str(requested[0]) if isinstance(requested, list) and requested else ""
            if op == "HARVEST" and tile_product is not None:
                ledgers[player]["harvest"][tile_product] += max(
                    0, after_private[tile_product] - before_private[tile_product]
                )
            if op == "COLLECT_FERTILIZER":
                ledgers[player]["collect"]["FERTILIZER"] += max(
                    0, after_private["FERTILIZER"] - before_private["FERTILIZER"]
                )
            if op in {"PLANT", "WATER"}:
                ledgers[player]["production"].update(_positive_delta(after_farm, before_farm))
            if op in {"FEED", "FERTILIZE"}:
                ledgers[player]["input_consumption"].update(
                    _negative_delta(after_private, before_private)
                )
    return ledgers


def _process_market(
    farms: list[dict[str, Any]],
    privates: list[dict[str, Any]],
    market: dict[str, Any],
    actions: list[dict[str, Any]],
    board_size: int,
    max_orders: int,
    hire_mult: int,
    shed_capacity: int,
) -> list[dict[str, Any]]:
    ledgers = [
        {
            "sell_units": Counter(),
            "sell_value": Counter(),
            "sell_market_supply": Counter(),
            "sell_at_floor": Counter(),
            "market_buy_units": Counter(),
            "market_buy_value": Counter(),
        }
        for _ in (0, 1)
    ]
    queues = []
    for current in actions:
        orders = current.get("market") or [] if isinstance(current, dict) else []
        queues.append(list(orders)[:max_orders] if isinstance(orders, list) else [])
    for slot in range(max((len(queue) for queue in queues), default=0)):
        states = []
        for queue in queues:
            raw = queue[slot] if slot < len(queue) else None
            states.append(engine._parse_order(raw) if raw is not None else None)
        for player, state in enumerate(states):
            if state is None:
                continue
            if state["type"] == "HIRE":
                engine._do_hire(farms[player], privates[player], board_size, hire_mult)
                states[player] = None
            elif state["type"] == "BUY_LAND":
                engine._do_buy_land(farms[player], board_size)
                states[player] = None
        while True:
            quoted: list[tuple[str, str, int, dict[str, Any]] | None] = [None, None]
            for player, state in enumerate(states):
                if state is None or state["remaining"] <= 0:
                    continue
                op, item = state["type"], state["item"]
                if op == "SELL" and item in engine.PRODUCTS:
                    price = engine.market_price(item, market["inventory"][item], market.get("params"))
                elif op == "BUY_PRODUCT" and item in ("WHEAT", "FERTILIZER"):
                    price = engine.market_price(
                        item, market["inventory"][item] - 1, market.get("params")
                    )
                elif op == "BUY_SEED" and item in engine.CROPS:
                    price = engine.CROPS[item]["seed"]
                elif op == "BUY_ANIMAL" and item in engine.ANIMALS:
                    price = engine.ANIMALS[item]["cost"]
                else:
                    states[player] = None
                    continue
                quoted[player] = (op, item, int(price), state)
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
                if not ok:
                    states[player] = None
                    continue
                state["remaining"] -= 1
                committed_any = True
                if op == "SELL":
                    ledgers[player]["sell_units"][item] += 1
                    ledgers[player]["sell_value"][item] += price
                    if price > 1:
                        ledgers[player]["sell_market_supply"][item] += 1
                    else:
                        ledgers[player]["sell_at_floor"][item] += 1
                elif op == "BUY_PRODUCT":
                    ledgers[player]["market_buy_units"][item] += 1
                    ledgers[player]["market_buy_value"][item] += price
            if not committed_any:
                break
        engine._refresh_prices(market)
    return ledgers


def _town_consume(market: dict[str, Any], town: dict[str, Any], step: int, cfg: dict[str, Any]) -> Counter[str]:
    result: Counter[str] = Counter()
    shop_interval = max(1, int(cfg.get("townShopSellInterval", 4) or 4))
    center_interval = max(1, int(cfg.get("townCenterSellInterval", 24) or 24))
    if step % shop_interval == 0:
        for shop_name in town.get("unlocked_shops") or []:
            products = engine.SHOPS[shop_name]
            multiplier = 2 if len(products) == 1 else 1
            for item in products:
                market["inventory"][item] -= multiplier
                result[item] += multiplier
    if step % center_interval == 0:
        for item in engine.TOWN_CENTER_PRODUCTS:
            market["inventory"][item] -= 1
            result[item] += 1
    engine._refresh_prices(market)
    return result


def _refresh_and_losses(
    farms: list[dict[str, Any]],
    privates: list[dict[str, Any]],
    step: int,
    day: int,
    turns_per_day: int,
    shed_capacity: int,
) -> list[dict[str, Counter[str]]]:
    result = [
        {"production": Counter(), "field_loss": Counter(), "overflow_loss": Counter()}
        for _ in (0, 1)
    ]
    for player, farm in enumerate(farms):
        before = _on_farm_products(farm)
        engine._decay_plants(farm, step)
        after = _on_farm_products(farm)
        result[player]["field_loss"].update(_negative_delta(after, before))
    if (step + 1) % turns_per_day:
        return result
    for player, farm in enumerate(farms):
        before = _on_farm_products(farm)
        engine._daily_refresh_plants(farm, day, turns_per_day)
        after_plants = _on_farm_products(farm)
        result[player]["production"].update(_positive_delta(after_plants, before))
        result[player]["field_loss"].update(_negative_delta(after_plants, before))
        before_animals = after_plants
        engine._daily_refresh_animals(farm, day)
        after_animals = _on_farm_products(farm)
        result[player]["production"].update(_positive_delta(after_animals, before_animals))
        result[player]["field_loss"].update(_negative_delta(after_animals, before_animals))
        private_before = _private_products(privates[player])
        engine._drop_inventories_to_shed(privates[player], shed_capacity)
        private_after = _private_products(privates[player])
        result[player]["overflow_loss"].update(_negative_delta(private_after, private_before))
    return result


def _counter_dict(value: Counter[str]) -> dict[str, int]:
    return {item: int(value[item]) for item in PRODUCTS}


def _simulate_step(replay: dict[str, Any], step: int) -> dict[str, Any]:
    observations = [observation(replay, step, seat) or {} for seat in (0, 1)]
    base = observations[0]
    farms = copy.deepcopy(list(base.get("farms") or [{}, {}]))
    privates = [copy.deepcopy(obs.get("private") or {}) for obs in observations]
    market = copy.deepcopy(base.get("market") or {})
    town = copy.deepcopy(base.get("town") or {})
    actions = [action(replay, step, seat) for seat in (0, 1)]
    cfg = dict(replay.get("configuration") or {})
    board_size = int(cfg.get("boardSize", 10) or 10)
    turns_per_day = max(1, int(cfg.get("turnsPerDay", 24) or 24))
    shed_capacity = int(cfg.get("shedCapacity", 100) or 100)
    max_orders = max(1, int(cfg.get("maxMarketOrdersPerTurn", 10) or 10))
    hire_mult = int(cfg.get("farmHandCostMult", engine.FARM_HAND_COST_MULT) or 1)
    day = int(base.get("day", step // turns_per_day) or 0)
    field = _apply_fields(
        farms,
        privates,
        actions,
        day,
        board_size,
        turns_per_day,
        shed_capacity,
    )
    market_ledgers = _process_market(
        farms,
        privates,
        market,
        actions,
        board_size,
        max_orders,
        hire_mult,
        shed_capacity,
    )
    town_units = _town_consume(market, town, step, cfg)
    refresh = _refresh_and_losses(
        farms, privates, step, day, turns_per_day, shed_capacity
    )
    next_obs = [observation(replay, step + 1, seat) or {} for seat in (0, 1)]
    checks: list[dict[str, bool]] = []
    for player in (0, 1):
        expected_farm = (next_obs[player].get("farms") or [{}, {}])[player]
        expected_market = next_obs[player].get("market") or {}
        checks.append(
            {
                "money": float(farms[player].get("money", 0) or 0)
                == float(expected_farm.get("money", 0) or 0),
                "private_products": _private_products(privates[player])
                == _private_products(next_obs[player].get("private") or {}),
                "on_farm_products": _on_farm_products(farms[player])
                == _on_farm_products(expected_farm),
                "market_inventory": market.get("inventory")
                == expected_market.get("inventory"),
            }
        )
    return {
        "players": [
            {
                "production": _counter_dict(field[player]["production"] + refresh[player]["production"]),
                "harvest": _counter_dict(field[player]["harvest"]),
                "collect": _counter_dict(field[player]["collect"]),
                "input_consumption": _counter_dict(field[player]["input_consumption"]),
                "sell_units": _counter_dict(market_ledgers[player]["sell_units"]),
                "sell_value": _counter_dict(market_ledgers[player]["sell_value"]),
                "sell_market_supply": _counter_dict(
                    market_ledgers[player]["sell_market_supply"]
                ),
                "sell_at_floor": _counter_dict(market_ledgers[player]["sell_at_floor"]),
                "market_buy_units": _counter_dict(
                    market_ledgers[player]["market_buy_units"]
                ),
                "market_buy_value": _counter_dict(
                    market_ledgers[player]["market_buy_value"]
                ),
                "field_loss": _counter_dict(refresh[player]["field_loss"]),
                "overflow_loss": _counter_dict(refresh[player]["overflow_loss"]),
            }
            for player in (0, 1)
        ],
        "town_consumption": _counter_dict(town_units),
        "validation": checks,
    }


def _sum_product_maps(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return {
        item: sum(int(row[key].get(item, 0) or 0) for row in rows)
        for item in PRODUCTS
    }


def _state_products(replay: dict[str, Any], step: int, seat: int) -> dict[str, dict[str, int]]:
    obs = observation(replay, step, seat) or {}
    farm = (obs.get("farms") or [{}, {}])[seat]
    private = _private_products(obs.get("private") or {})
    on_farm = _on_farm_products(farm)
    return {
        "private": _counter_dict(private),
        "on_farm": _counter_dict(on_farm),
        "total_owned": _counter_dict(private + on_farm),
    }


def _window_accounting(replay: dict[str, Any], focal_seat: int) -> dict[str, Any]:
    per_step = [_simulate_step(replay, step) for step in range(WINDOW_START, WINDOW_END)]
    invalid = [
        {"step": WINDOW_START + offset, "player": player, "checks": checks}
        for offset, row in enumerate(per_step)
        for player, checks in enumerate(row["validation"])
        if not all(checks.values())
    ]
    if invalid:
        raise RuntimeError(f"engine accounting failed replay validation: {invalid[:3]}")
    players = []
    for seat in (focal_seat, 1 - focal_seat):
        ledgers = [row["players"][seat] for row in per_step]
        sell_units = _sum_product_maps(ledgers, "sell_units")
        sell_value = _sum_product_maps(ledgers, "sell_value")
        players.append(
            {
                "seat": seat,
                "initial": _state_products(replay, WINDOW_START, seat),
                "production": _sum_product_maps(ledgers, "production"),
                "harvest": _sum_product_maps(ledgers, "harvest"),
                "collect": _sum_product_maps(ledgers, "collect"),
                "input_consumption": _sum_product_maps(ledgers, "input_consumption"),
                "market_buy_units": _sum_product_maps(ledgers, "market_buy_units"),
                "market_buy_value": _sum_product_maps(ledgers, "market_buy_value"),
                "sell_units": sell_units,
                "realized_sale_value": sell_value,
                "realized_average_price": {
                    item: sell_value[item] / sell_units[item] if sell_units[item] else None
                    for item in PRODUCTS
                },
                "sell_market_supply": _sum_product_maps(ledgers, "sell_market_supply"),
                "sell_at_floor": _sum_product_maps(ledgers, "sell_at_floor"),
                "field_loss": _sum_product_maps(ledgers, "field_loss"),
                "overflow_loss": _sum_product_maps(ledgers, "overflow_loss"),
                "ending": _state_products(replay, WINDOW_END, seat),
                "premium_totals": {
                    "initial_private": sum(
                        _state_products(replay, WINDOW_START, seat)["private"][item]
                        for item in PREMIUM
                    ),
                    "initial_on_farm": sum(
                        _state_products(replay, WINDOW_START, seat)["on_farm"][item]
                        for item in PREMIUM
                    ),
                    "production": sum(
                        _sum_product_maps(ledgers, "production")[item] for item in PREMIUM
                    ),
                    "harvest": sum(
                        _sum_product_maps(ledgers, "harvest")[item] for item in PREMIUM
                    ),
                    "sell_units": sum(sell_units[item] for item in PREMIUM),
                    "realized_sale_value": sum(sell_value[item] for item in PREMIUM),
                    "ending_private": sum(
                        _state_products(replay, WINDOW_END, seat)["private"][item]
                        for item in PREMIUM
                    ),
                    "ending_on_farm": sum(
                        _state_products(replay, WINDOW_END, seat)["on_farm"][item]
                        for item in PREMIUM
                    ),
                },
            }
        )
    first_obs = observation(replay, WINDOW_START, 0) or {}
    last_obs = observation(replay, WINDOW_END, 0) or {}
    first_market = (first_obs.get("market") or {}).get("inventory") or {}
    last_market = (last_obs.get("market") or {}).get("inventory") or {}
    town_rows = [row["town_consumption"] for row in per_step]
    return {
        "focal": players[0],
        "opponent": players[1],
        "market": {
            "initial_inventory": {item: int(first_market.get(item, 0) or 0) for item in PRODUCTS},
            "ending_inventory": {item: int(last_market.get(item, 0) or 0) for item in PRODUCTS},
            "inventory_delta": {
                item: int(last_market.get(item, 0) or 0) - int(first_market.get(item, 0) or 0)
                for item in PRODUCTS
            },
            "town_consumption": {
                item: sum(int(row.get(item, 0) or 0) for row in town_rows)
                for item in PRODUCTS
            },
        },
        "validated_steps": len(per_step) * 2,
    }


def _expected_rows(paths: list[Path]) -> dict[tuple[str, int], dict[str, Any]]:
    result = {}
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                family = str(row.get("behavior_family_id"))
                if family in TARGET_FAMILIES and int(row.get("seed", -1)) == SEED:
                    result[(family, int(row["seat"]))] = row
    return result


def _families(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(row["behavior_family_id"]): row
        for row in payload.get("families") or []
        if row.get("behavior_family_id") in TARGET_FAMILIES
    }


def _aggregate_games(games: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = (
        "production",
        "harvest",
        "sell_units",
        "realized_sale_value",
        "ending_private",
        "ending_on_farm",
    )
    result: dict[str, Any] = {}
    for role in ("focal", "opponent"):
        result[role] = {
            metric: mean(game["accounting"][role]["premium_totals"][metric] for game in games)
            for metric in metrics
        }
    result["focal_minus_opponent"] = {
        metric: result["focal"][metric] - result["opponent"][metric] for metric in metrics
    }
    result["descriptive_unit"] = (
        "six seat-level conditions; one seed/Town regime and three dependent continuations"
    )
    return result


def run(output: Path) -> dict[str, Any]:
    champion = ROOT / "agents" / "v111" / "main.py"
    panel_path = ROOT / "experiments" / "independent_gold_pool" / "public_gold_addendum_panel_manifest.json"
    pairs_paths = [
        ROOT
        / "data"
        / "evaluation"
        / "v111_v113_public_gold_addendum_20260902"
        / "pairs.jsonl",
        ROOT / "data" / "evaluation" / "v111_v113_expanded_20260902" / "pairs.jsonl",
    ]
    family_rows = _families(panel_path)
    expected = _expected_rows(pairs_paths)
    games = []
    for family_id in TARGET_FAMILIES:
        family = family_rows[family_id]
        opponent = Path(family["entrypoint"])
        for seat in (0, 1):
            game = _run_game(champion, opponent, SEED, seat, 720, f"late_premium_{family_id}_{seat}")
            expected_row = expected[(family_id, seat)]
            expected_arm = expected_row["v111"]
            expected_fingerprints = expected_row["executed_action_fingerprints"]["v111_arm"]
            reproduced = {
                "outcome": all(
                    game[key] == expected_arm[key]
                    for key in (
                        "requested_seed",
                        "resolved_seed",
                        "seat",
                        "ours",
                        "theirs",
                        "margin",
                        "score",
                        "result",
                    )
                ),
                "focal_action_fingerprints": {
                    step: lineage_hash(game["replay"], seat, int(step))
                    for step in expected_fingerprints["focal"]
                }
                == expected_fingerprints["focal"],
                "opponent_action_fingerprints": {
                    step: lineage_hash(game["replay"], 1 - seat, int(step))
                    for step in expected_fingerprints["opponent"]
                }
                == expected_fingerprints["opponent"],
            }
            if not all(reproduced.values()):
                raise RuntimeError(f"frozen condition did not reproduce: {family_id} seat {seat}: {reproduced}")
            games.append(
                {
                    "behavior_family_id": family_id,
                    "representative_candidate_id": family["representative_candidate_id"],
                    "opponent_policy_scope": family.get("artifact_scope"),
                    "opponent_entrypoint_sha256": _sha256(opponent),
                    "seed": SEED,
                    "focal_seat": seat,
                    "terminal": {
                        key: game[key]
                        for key in ("ours", "theirs", "margin", "score", "result")
                    },
                    "deterministic_reproduction": reproduced,
                    "accounting": _window_accounting(game["replay"], seat),
                }
            )
    payload = {
        "format": "kaggriculture-late-premium-causal-accounting-v1",
        "created_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
        "dataset_role": "Development post-hoc accounting",
        "hypothesis_id": "H_WEAK_LATE_PREMIUM_REVERSAL_001",
        "evidence_level": "E1 mechanistic replay accounting; not a causal best-response estimate",
        "window": {
            "start_step_inclusive": WINDOW_START,
            "end_step_exclusive": WINDOW_END,
            "start_day": 12,
            "end_day": 20,
        },
        "independence_guardrail": {
            "seat_level_conditions": 6,
            "independent_seeds": 1,
            "town_regimes": 1,
            "continuations": 3,
            "shared_opponent_action_prefix_through_step": 200,
            "v111_v113_execution_identity": (
                "V111 and V113 actions are identical in all six frozen pairs; only V111 was rerun"
            ),
        },
        "provenance": {
            "champion": str(champion),
            "champion_sha256": _sha256(champion),
            "source_pairs": [str(path) for path in pairs_paths],
            "source_pairs_sha256": {str(path): _sha256(path) for path in pairs_paths},
            "source_panel": str(panel_path),
            "source_panel_sha256": _sha256(panel_path),
            "analyzer": str(Path(__file__).resolve()),
            "analyzer_sha256": _sha256(Path(__file__).resolve()),
            "engine": str(Path(engine.__file__).resolve()),
            "engine_sha256": _sha256(Path(engine.__file__).resolve()),
        },
        "accounting_semantics": {
            "production": (
                "new yield_units created by PLANT/WATER/daily refresh; annual-crop PLANT "
                "books the engine's initial biological unit"
            ),
            "harvest": "successful transfer of crop/animal yield from a farm tile to private carried inventory",
            "private": "shed plus all carried inventories",
            "sell": "engine-committed units only; realized value sums the exact per-unit lockstep quote",
            "market_supply": "committed sale units with price > 1; engine floor-price sales do not add inventory",
            "town_consumption": "engine-scheduled shared-market withdrawals from unlocked shops and Town center",
        },
        "games": games,
        "descriptive_aggregate": _aggregate_games(games),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    target = output / "late_premium_accounting.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "analysis" / "late_premium_accounting_20260902",
    )
    args = parser.parse_args()
    payload = run(args.output.resolve())
    print(json.dumps(payload["descriptive_aggregate"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
