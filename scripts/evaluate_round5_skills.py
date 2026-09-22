"""Persist fixed-engine Round5 skill-completion and economic-realization evidence."""

from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "experiments/learning_round5_20260921/skill_scenarios"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_round5_20260921.executor import ExecutionCoordinator  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class AnimalLifecyclePolicy:
    """Small explicit scenario policy; this is not claimed as a competitive arm."""

    def __init__(self, animal: str) -> None:
        self.animal = animal
        self.product = {"COW": "MILK", "SHEEP": "WOOL"}[animal]
        self.coordinator = ExecutionCoordinator(f"scenario-{animal.lower()}")

    def __call__(self, observation: dict[str, Any], configuration: Any = None) -> dict[str, Any]:
        del configuration
        if int(observation.get("step", 0)) == 0:
            self.coordinator.reset()
        tile = observation["farms"][observation["player"]]["tiles"][4][4]
        private = observation["private"]
        inventory = private["inventories"][0]
        market: list[list[Any]] = []
        if tile is None:
            unit = ["BUILD_PASTURE"]
            market = [["BUY_ANIMAL", self.animal, 1], ["BUY_PRODUCT", "WHEAT", 20]]
        elif isinstance(tile, dict) and not tile.get("animal"):
            unit = ["PLACE", self.animal] if inventory.get(self.animal, 0) else ["PICKUP", self.animal, 1]
        elif inventory.get(self.product, 0):
            unit = ["DROP"]
        elif private["shed"].get(self.product, 0):
            unit = ["PASS"]
            market = [["SELL", self.product, int(private["shed"][self.product])]]
        elif int(tile.get("yield_units", 0)) > 0:
            unit = ["HARVEST"]
        elif not tile.get("fed_today"):
            unit = ["FEED"] if inventory.get("WHEAT", 0) else ["PICKUP", "WHEAT", 2]
        elif not tile.get("cared_today"):
            unit = ["CARE"]
        else:
            unit = ["PASS"]
        proposal = {"farmer": unit, "hands": [], "market": market}
        return self.coordinator.repair(observation, proposal, {"ANIMAL_LIFECYCLE_REALIZATION": 1.0})


def action_records(replay: dict[str, Any], seat: int, predicate: Any) -> list[int]:
    return [record for record in range(1, len(replay["steps"])) if predicate(replay["steps"][record][seat].get("action") or {})]


def run_lifecycle(animal: str, seed: int) -> dict[str, Any]:
    from kaggle_environments import make

    product = {"COW": "MILK", "SHEEP": "WOOL"}[animal]
    policy = AnimalLifecyclePolicy(animal)
    env = make("kaggriculture", configuration={"episodeSteps": 360, "seed": seed}, debug=True)
    env.run([policy, "pass"])
    replay = env.toJSON()
    path = OUTPUT / animal.lower() / "replay.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))
    trace_path = OUTPUT / animal.lower() / "trace.jsonl"
    trace_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in policy.coordinator.policy_trace()),
        encoding="utf-8",
    )
    buy = action_records(replay, 0, lambda action: any(order[:2] == ["BUY_ANIMAL", animal] for order in action.get("market", [])))
    place = action_records(replay, 0, lambda action: action.get("farmer") == ["PLACE", animal])
    feed = action_records(replay, 0, lambda action: action.get("farmer") == ["FEED"])
    care = action_records(replay, 0, lambda action: action.get("farmer") == ["CARE"])
    harvest = action_records(replay, 0, lambda action: action.get("farmer") == ["HARVEST"])
    drop = action_records(replay, 0, lambda action: action.get("farmer") == ["DROP"])
    sell = action_records(replay, 0, lambda action: any(order[:2] == ["SELL", product] for order in action.get("market", [])))
    milestones = {"buy": buy[0], "place": place[0], "first_feed": feed[0], "first_care": care[0], "harvest": harvest[0], "drop": drop[0], "sell": sell[0]}
    harvest_before = replay["steps"][harvest[0] - 1][0]["observation"]
    harvest_after = replay["steps"][harvest[0]][0]["observation"]
    sell_before = replay["steps"][sell[0] - 1][0]["observation"]
    sell_after = replay["steps"][sell[0]][0]["observation"]
    product_delta = int(harvest_after["private"]["inventories"][0].get(product, 0)) - int(harvest_before["private"]["inventories"][0].get(product, 0))
    cash_delta = int(sell_after["farms"][0]["money"]) - int(sell_before["farms"][0]["money"])
    initial_money = int(replay["steps"][0][0]["observation"]["farms"][0]["money"])
    after_purchase_money = int(replay["steps"][buy[0]][0]["observation"]["farms"][0]["money"])
    after_sale_money = int(sell_after["farms"][0]["money"])
    ordered = list(milestones.values()) == sorted(milestones.values())
    return {
        "animal": animal,
        "product": product,
        "seed": seed,
        "engine_episode": True,
        "stored_states": len(replay["steps"]),
        "terminal_statuses": [replay["steps"][-1][seat]["status"] for seat in (0, 1)],
        "milestones": milestones,
        "ordered_end_to_end": ordered,
        "actor_product_delta_at_harvest": product_delta,
        "cash_delta_at_sale_step": cash_delta,
        "initial_money": initial_money,
        "purchase_cash_outlay": initial_money - after_purchase_money,
        "money_after_first_sale": after_sale_money,
        "cycle_cash_delta_through_first_sale": after_sale_money - initial_money,
        "cash_realization_completed": policy.coordinator.diagnostics()["cash_realization_completed"],
        "animal_plan_count": policy.coordinator.diagnostics()["animal_plan_count"],
        "replay": str(path.relative_to(ROOT)),
        "replay_sha256": sha256(path),
        "trace": str(trace_path.relative_to(ROOT)),
        "trace_sha256": sha256(trace_path),
        "contract": "PASS" if ordered and product_delta > 0 and cash_delta > 0 else "FAIL",
    }


def duplicate_animal_harvest_probe() -> dict[str, Any]:
    module_path = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
    spec = importlib.util.spec_from_file_location("round5_fixed_engine_probe", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tile = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0, "yield_units": 1,
        "fed_today": True, "consecutive_unfed": 0, "cared_today": False,
        "fertilizer_available": False, "pending_care_bonus": 0,
    }
    farm = {"farmer": [4, 4], "hands": [[4, 4]], "tiles": [[None for _ in range(10)] for _ in range(10)]}
    farm["tiles"][4][4] = copy.deepcopy(tile)
    private = {"shed": {}, "seeds": {}, "inventories": [{}, {}]}
    module._apply_unit_action(farm, private, 0, ["HARVEST"], 10, 10, 24)
    module._apply_unit_action(farm, private, 1, ["HARVEST"], 10, 10, 24)
    received = [int(value.get("MILK", 0)) for value in private["inventories"]]
    return {
        "scope": "fixed engine primitive order, two actors same typed animal target",
        "issued_harvests": 2,
        "per_actor_milk": received,
        "total_milk": sum(received),
        "remaining_yield": int(farm["tiles"][4][4]["yield_units"]),
        "contract": "PASS" if received == [1, 0] and farm["tiles"][4][4]["yield_units"] == 0 else "FAIL",
    }


def main() -> None:
    lifecycle = [run_lifecycle("COW", 2026100601), run_lifecycle("SHEEP", 2026100602)]
    output = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "engine_sha256": sha256(ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"),
        "package_version": "kaggle-environments==1.32.7",
        "purpose": "minimum physical/economic completion of a selected investment; not proof that animals are universally optimal",
        "lifecycle_scenarios": lifecycle,
        "duplicate_animal_harvest": duplicate_animal_harvest_probe(),
        "all_required_contracts_pass": all(row["contract"] == "PASS" for row in lifecycle),
    }
    write_json(OUTPUT / "SKILL_SCENARIO_RESULTS.json", output)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
