"""Detailed post-hoc accounting for the frozen V117 paired panels."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluation.lifecycle import analyze_lifecycle  # noqa: E402
from scripts.evaluation.replay import action, observation  # noqa: E402

EXP = ROOT / "experiments/research_20260916_v117_live_trial"
PHASES = ("old_spent", "confirmation")
PRODUCTS = (
    "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
    "EGG", "MILK", "WOOL", "FERTILIZER",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"partial JSONL record {path}:{line_number}") from exc
    return result


def load_replay(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def save(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def private_total(private: dict[str, Any], item: str) -> int:
    return int((private.get("shed") or {}).get(item, 0) or 0) + sum(
        int((inventory or {}).get(item, 0) or 0)
        for inventory in (private.get("inventories") or [])
    )


def quadrant(position: list[int], board_size: int = 10) -> str | None:
    if len(position) != 2:
        return None
    x, y = int(position[0]), int(position[1])
    if not (0 <= x < board_size and 0 <= y < board_size):
        return None
    half = board_size // 2
    return ("N" if y < half else "S") + ("W" if x < half else "E")


def tile_snapshot(replay: dict[str, Any], seat: int, step: int) -> dict[str, Any]:
    obs = observation(replay, step, seat) or {}
    farms = obs.get("farms") or []
    farm = farms[seat]
    private = obs.get("private") or {}
    unlocked = set(farm.get("unlocked_quadrants") or [])
    productive = empty = weeds = unharvested = 0
    crop_tiles = Counter()
    animal_tiles = Counter()
    for y, row in enumerate(farm.get("tiles") or []):
        for x, tile in enumerate(row or []):
            if quadrant([x, y]) not in unlocked:
                continue
            if tile is None:
                empty += 1
                continue
            kind = str(tile.get("kind") or "")
            weeds += kind == "WEED"
            if kind not in {"", "WEED"}:
                productive += 1
            if tile.get("crop"):
                crop_tiles[str(tile["crop"])] += 1
                unharvested += max(0, int(tile.get("yield_units", 0) or 0))
            if tile.get("animal"):
                animal_tiles[str(tile["animal"])] += 1
                unharvested += max(0, int(tile.get("stored_yield", 0) or 0))
    inventories = private.get("inventories") or []
    shed = private.get("shed") or {}
    return {
        "step": step,
        "cash": float(farm.get("money", 0.0) or 0.0),
        "unlocked_quadrants": sorted(unlocked),
        "productive_tiles": productive,
        "empty_tiles": empty,
        "weed_tiles": weeds,
        "crop_tiles": dict(crop_tiles),
        "animal_tiles": dict(animal_tiles),
        "workers": 1 + len(farm.get("hands") or []),
        "hands": len(farm.get("hands") or []),
        "shed_units": sum(int(quantity or 0) for quantity in shed.values()),
        "carry_units": sum(
            int(quantity or 0)
            for inventory in inventories
            for quantity in (inventory or {}).values()
        ),
        "unharvested_current_units_proxy": unharvested,
        "products": {item: private_total(private, item) for item in PRODUCTS},
    }


def unit_actions(current: dict[str, Any]) -> list[list[Any]]:
    farmer = current.get("farmer") if isinstance(current, dict) else None
    hands = current.get("hands") if isinstance(current, dict) else None
    return [farmer if isinstance(farmer, list) else ["PASS"], *(hands or [])]


def successful_product_events(
    replay: dict[str, Any], seat: int, start: int
) -> dict[str, int]:
    harvested_milk = collected_fertilizer = sold_milk = sold_fertilizer = 0
    for step in range(start, min(719, len(replay.get("steps") or []) - 1)):
        before = observation(replay, step, seat) or {}
        after = observation(replay, step + 1, seat) or {}
        before_private = before.get("private") or {}
        after_private = after.get("private") or {}
        current = action(replay, step, seat) or {}
        actor_actions = unit_actions(current)
        if any(row and row[0] == "HARVEST" for row in actor_actions):
            harvested_milk += max(
                0,
                private_total(after_private, "MILK")
                - private_total(before_private, "MILK")
                + sum(
                    int(order[2])
                    for order in (current.get("market") or [])
                    if isinstance(order, list) and len(order) >= 3 and order[:2] == ["SELL", "MILK"]
                ),
            )
        if any(row and row[0] == "COLLECT_FERTILIZER" for row in actor_actions):
            collected_fertilizer += max(
                0,
                private_total(after_private, "FERTILIZER")
                - private_total(before_private, "FERTILIZER")
                + sum(
                    int(order[2])
                    for order in (current.get("market") or [])
                    if isinstance(order, list)
                    and len(order) >= 3
                    and order[:2] == ["SELL", "FERTILIZER"]
                ),
            )
        sold_milk += sum(
            int(order[2])
            for order in (current.get("market") or [])
            if isinstance(order, list) and len(order) >= 3 and order[:2] == ["SELL", "MILK"]
        )
        sold_fertilizer += sum(
            int(order[2])
            for order in (current.get("market") or [])
            if isinstance(order, list)
            and len(order) >= 3
            and order[:2] == ["SELL", "FERTILIZER"]
        )
    return {
        "harvested_milk_proxy": harvested_milk,
        "collected_fertilizer_proxy": collected_fertilizer,
        "requested_sell_milk": sold_milk,
        "requested_sell_fertilizer": sold_fertilizer,
    }


def new_land_timeline(
    replay: dict[str, Any], seat: int, commit: int, new_quadrant: str | None
) -> dict[str, Any]:
    first: dict[str, int | None] = {
        "productive": None,
        "harvest": None,
        "carry_or_drop": None,
        "shed_wide_sale": None,
    }
    utilization = Counter()
    for step in range(commit, min(719, len(replay.get("steps") or []) - 1)):
        obs = observation(replay, step, seat) or {}
        farm = (obs.get("farms") or [])[seat]
        positions = [farm.get("farmer") or [], *(farm.get("hands") or [])]
        current = action(replay, step, seat) or {}
        actors = unit_actions(current)
        for index, row in enumerate(actors):
            operation = str(row[0]) if row else "PASS"
            utilization["actor_slots"] += 1
            utilization["pass"] += operation == "PASS"
            utilization["travel"] += operation in {"NORTH", "SOUTH", "EAST", "WEST"}
            utilization["nonpass"] += operation != "PASS"
            on_new_land = index < len(positions) and quadrant(positions[index]) == new_quadrant
            if on_new_land and operation in {
                "PLANT", "WATER", "HARVEST", "BUILD_COOP", "BUILD_PASTURE",
                "FEED", "CARE", "COLLECT_FERTILIZER",
            }:
                first["productive"] = step if first["productive"] is None else first["productive"]
            if on_new_land and operation == "HARVEST":
                first["harvest"] = step if first["harvest"] is None else first["harvest"]
            if on_new_land and operation in {"PICKUP", "DROP"}:
                first["carry_or_drop"] = step if first["carry_or_drop"] is None else first["carry_or_drop"]
        if first["shed_wide_sale"] is None and any(
            isinstance(order, list) and order and order[0] == "SELL"
            for order in (current.get("market") or [])
        ):
            first["shed_wide_sale"] = step
    return {
        "first_steps": first,
        "lags_from_land_commit": {
            name: (value - commit if value is not None else None) for name, value in first.items()
        },
        "action_utilization": dict(utilization),
        "sale_attribution_limit": (
            "Shed inventory is fungible; the first post-land SELL cannot be strictly attributed "
            "to the newly unlocked quadrant."
        ),
    }


def add_nested(counter: Counter[str], values: dict[str, Any]) -> None:
    for key, value in values.items():
        if isinstance(value, int | float):
            counter[str(key)] += value


def phase_details(records: list[dict[str, Any]], phase: str) -> dict[str, Any]:
    selected = [record for record in records if record["phase"] == phase]
    raw_audits = {arm: Counter() for arm in ("control", "treatment")}
    raw_lifecycle = {arm: Counter() for arm in ("control", "treatment")}
    raw_lost_units = {arm: Counter() for arm in ("control", "treatment")}
    raw_harvest = {arm: Counter() for arm in ("control", "treatment")}
    raw_animals = {arm: Counter() for arm in ("control", "treatment")}
    minimum_cash = {arm: [] for arm in ("control", "treatment")}
    committed_contexts = []
    first_event = None
    for record in selected:
        for arm in ("control", "treatment"):
            safety = record["safety"][arm]
            add_nested(raw_audits[arm], safety.get("engine_action_audit") or {})
            add_nested(raw_animals[arm], safety.get("animal_losses") or {})
            minimum_cash[arm].append(float(safety.get("minimum_cash", 0.0)))
            replay = load_replay(Path(record["replay_artifacts"][arm]))
            lifecycle = analyze_lifecycle(replay, int(record["seat"]), 0)
            add_nested(raw_lifecycle[arm], lifecycle["counts"])
            add_nested(raw_lost_units[arm], lifecycle["lost_current_units"])
            add_nested(raw_harvest[arm], lifecycle["successful_harvest_units"])
        decision = record["agent_trace"]["treatment"].get("research_decision", {})
        if not decision.get("committed"):
            continue
        control = load_replay(Path(record["replay_artifacts"]["control"]))
        treatment = load_replay(Path(record["replay_artifacts"]["treatment"]))
        seat = int(record["seat"])
        commit = int(decision["commit_step"])
        land_confirmed = int(decision["land_confirmed_step"])
        control_land = next(
            step
            for step in range(commit, 720)
            if len(set((observation(control, step, seat) or {})["farms"][seat].get("unlocked_quadrants") or [])) >= 3
        )
        product_control = successful_product_events(control, seat, commit)
        product_treatment = successful_product_events(treatment, seat, commit)
        timeline_control = new_land_timeline(control, seat, control_land, decision.get("new_quadrant"))
        timeline_treatment = new_land_timeline(
            treatment, seat, land_confirmed, decision.get("new_quadrant")
        )
        divergence = record["divergence_audit"]
        context = {
            "source": record["lineage_id"],
            "seed": record["seed"],
            "seat": seat,
            "commit_step": commit,
            "control_land_step": control_land,
            "treatment_land_step": land_confirmed,
            "land_advance": control_land - land_confirmed,
            "preflight": decision.get("preflight"),
            "cow_contract": {
                "debt_created": False,
                "original_order_preserved": True,
                "cow_confirmed_step": decision.get("cow_confirmed_step"),
                "pickup_actions": decision.get("cow_pickups"),
                "place_actions": decision.get("cow_places"),
                "rejoined": decision.get("rejoined"),
                "rejoin_step": decision.get("rejoin_step"),
                "product_proxy_control": product_control,
                "product_proxy_treatment": product_treatment,
                "product_proxy_delta": {
                    key: product_treatment[key] - product_control[key] for key in product_control
                },
            },
            "activation_control": timeline_control,
            "activation_treatment": timeline_treatment,
            "snapshots": {
                str(step): {
                    "control": tile_snapshot(control, seat, step),
                    "treatment": tile_snapshot(treatment, seat, step),
                }
                for step in (commit, commit + 1, control_land, 255, 672, 719)
            },
            "opponent_response": {
                "first_action": divergence.get("first_opponent_action"),
                "lag": divergence.get("opponent_response_lag"),
                "first_money_benefit": divergence.get("first_opponent_money_benefit"),
            },
            "market_price_town_first_differences": {
                key: divergence.get("first_state_divergence", {}).get(key)
                for key in ("market_inventory", "prices", "town")
            },
        }
        committed_contexts.append(context)
        if first_event is None:
            candidate_new = record.get("candidate_incident_classification") or {}
            failures = candidate_new.get("hard_safety_failures") or []
            if failures:
                first_event = {
                    "source": record["lineage_id"],
                    "seed": record["seed"],
                    "seat": seat,
                    "failures": failures,
                }
    candidate_new = {
        "engine_action_audit_delta": {
            key: raw_audits["treatment"][key] - raw_audits["control"][key]
            for key in sorted(raw_audits["control"] | raw_audits["treatment"])
        },
        "animal_loss_delta": {
            key: raw_animals["treatment"][key] - raw_animals["control"][key]
            for key in sorted(raw_animals["control"] | raw_animals["treatment"])
        },
        "lifecycle_count_delta": {
            key: raw_lifecycle["treatment"][key] - raw_lifecycle["control"][key]
            for key in sorted(raw_lifecycle["control"] | raw_lifecycle["treatment"])
        },
        "lost_current_units_delta": {
            key: raw_lost_units["treatment"][key] - raw_lost_units["control"][key]
            for key in sorted(raw_lost_units["control"] | raw_lost_units["treatment"])
        },
        "successful_harvest_units_delta": {
            key: raw_harvest["treatment"][key] - raw_harvest["control"][key]
            for key in sorted(raw_harvest["control"] | raw_harvest["treatment"])
        },
        "first_event": first_event,
    }
    return {
        "phase": phase,
        "contexts": len(selected),
        "committed_contexts": len(committed_contexts),
        "raw_safety": {
            arm: {
                "engine_action_audit": dict(raw_audits[arm]),
                "animal_losses": dict(raw_animals[arm]),
                "lifecycle_causes": dict(raw_lifecycle[arm]),
                "lost_current_units": dict(raw_lost_units[arm]),
                "successful_harvest_units": dict(raw_harvest[arm]),
                "minimum_cash": min(minimum_cash[arm]) if minimum_cash[arm] else None,
            }
            for arm in ("control", "treatment")
        },
        "candidate_new_safety": candidate_new,
        "committed_details": committed_contexts,
        "aggregate": aggregate_committed(committed_contexts),
    }


def aggregate_committed(contexts: list[dict[str, Any]]) -> dict[str, Any]:
    if not contexts:
        return {}
    activation_lags = {
        arm: {
            key: [
                context[f"activation_{arm}"]["lags_from_land_commit"][key]
                for context in contexts
                if context[f"activation_{arm}"]["lags_from_land_commit"][key] is not None
            ]
            for key in ("productive", "harvest", "carry_or_drop", "shed_wide_sale")
        }
        for arm in ("control", "treatment")
    }
    first_difference_counts = Counter()
    opponent_response = 0
    product_delta = Counter()
    for context in contexts:
        opponent_response += context["opponent_response"]["first_action"] is not None
        for category, value in context["market_price_town_first_differences"].items():
            first_difference_counts[category] += value is not None
        product_delta.update(context["cow_contract"]["product_proxy_delta"])
    final_deltas = {}
    for step in (672, 719):
        final_deltas[str(step)] = {
            field: [
                context["snapshots"][str(step)]["treatment"][field]
                - context["snapshots"][str(step)]["control"][field]
                for context in contexts
            ]
            for field in (
                "cash", "productive_tiles", "empty_tiles", "weed_tiles",
                "workers", "hands", "shed_units", "carry_units",
                "unharvested_current_units_proxy",
            )
        }
    return {
        "land_advance": [context["land_advance"] for context in contexts],
        "land_advance_median": median(context["land_advance"] for context in contexts),
        "pre_cash": [context["preflight"]["cash_before"] for context in contexts],
        "projected_post_cash": [
            context["preflight"]["projected_cash_after_land_and_cows"] for context in contexts
        ],
        "activation_reserve": sorted({context["preflight"]["activation_reserve"] for context in contexts}),
        "maintenance_reserve": sorted({context["preflight"]["maintenance_reserve"]["coin"] for context in contexts}),
        "cow_debt": "NOT_CREATED_BY_FALLBACK; original COW2 order remained in the same transaction",
        "cow_product_proxy_delta": dict(product_delta),
        "activation_lag_median": {
            arm: {
                key: median(values) if values else None for key, values in mapping.items()
            }
            for arm, mapping in activation_lags.items()
        },
        "opponent_first_action_response_contexts": opponent_response,
        "market_price_town_first_difference_contexts": dict(first_difference_counts),
        "t672_t719_deltas": final_deltas,
        "terminal_stock_rule": (
            "t719 has no remaining decision. Shed, carry, and unharvested stock are reported as stock, "
            "not realized future income."
        ),
    }


def main() -> None:
    pairs_path = EXP / "pairs.jsonl"
    records = read_jsonl(pairs_path)
    result = {
        "created_from": {"pairs": str(pairs_path.relative_to(ROOT)), "sha256": sha(pairs_path)},
        "method": (
            "Replay-derived field/private/action accounting. Raw inherited incidents and paired "
            "candidate-new deltas are kept separate."
        ),
        "phases": {phase: phase_details(records, phase) for phase in PHASES},
        "limits": [
            "Fungible shed sales cannot be assigned uniquely to new-land output.",
            (
                "Fertilizer and milk figures are conservative observed inventory/action proxies, "
                "not a counterfactual production model."
            ),
            (
                "Opponent money/action changes are observations after a public intervention, "
                "not single-action causal effects."
            ),
        ],
    }
    save(EXP / "mechanism_details.json", result)
    print(json.dumps({phase: result["phases"][phase]["aggregate"] for phase in PHASES}))


if __name__ == "__main__":
    main()
