"""Read-only engine and frozen-route probes; no agent-policy modification."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from kaggle_environments import make
        from kaggle_environments.envs.kaggriculture import kaggriculture as engine

    runs = []
    for _ in range(2):
        seen = []

        def passive(obs, configuration):
            seen.append([obs.step, obs.day, obs.hour, configuration.seed])
            return {"farmer": ["PASS"], "hands": [], "market": []}

        start = time.perf_counter()
        env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 20260901}, debug=True)
        env.run([passive, passive])
        replay = env.toJSON()
        public = [[s["observation"] for s in pair] for pair in replay["steps"]]
        encoded = json.dumps(public, sort_keys=True, separators=(",", ":")).encode()
        runs.append({
            "wall_seconds": time.perf_counter() - start,
            "stored_steps": len(replay["steps"]),
            "decisions_per_player": len(seen) // 2,
            "first_call": seen[0], "last_call": seen[-1],
            "final_day_hour": [replay["steps"][-1][0]["observation"][key] for key in ("day", "hour")],
            "resolved_seed": replay["info"]["seed"],
            "all_agent_seed_hidden": all(x[3] is None for x in seen),
            "observation_sha256": hashlib.sha256(encoded).hexdigest(),
            "town": replay["steps"][-1][0]["observation"]["town"],
            "statuses": [s["status"] for s in replay["steps"][-1]],
        })

    price_probes = {}
    for item in engine.PRODUCTS:
        inventory = engine.MARKET_PARAMS[item]["I0"]
        floor_inventory = inventory
        while engine.market_price(item, floor_inventory) > 1 and floor_inventory < inventory + 200000:
            floor_inventory += 1
        price_probes[item] = {
            "base": engine.market_price(item, inventory),
            "inventory_100_below": engine.market_price(item, inventory - 100),
            "inventory_100_above": engine.market_price(item, inventory + 100),
            "first_floor_above_I0": floor_inventory - inventory if floor_inventory < inventory + 200000 else None,
        }
    floor_market = engine._new_market()
    floor_market["inventory"]["STRAWBERRY"] = 10100
    floor_private = engine._new_private()
    floor_private["shed"]["STRAWBERRY"] = 2
    floor_farm = engine._new_farm(10, 3000)
    before = copy.deepcopy(floor_market["inventory"])
    assert engine.market_price("STRAWBERRY", 10100) == 1
    committed = engine._commit_unit("SELL", "STRAWBERRY", 1, floor_farm, floor_private, floor_market)

    spec = importlib.util.spec_from_file_location("audit_v109", ROOT / "agents/v109/main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    public_v43 = module.public_v43
    routes = public_v43._V43_ROUTES
    route_summaries = {}
    for name, actions in routes.items():
        purchases = Counter()
        plant_by_phase = {phase: Counter() for phase in ("day0_5", "day6_14", "day15_24", "day25_29")}
        for step, action in enumerate(actions):
            phase = "day0_5" if step < 144 else "day6_14" if step < 360 else "day15_24" if step < 600 else "day25_29"
            for order in action.get("market", []):
                if order and order[0] in ("BUY_SEED", "BUY_ANIMAL"):
                    purchases[f"{order[0]}:{order[1]}"] += int(order[2])
            for actor in [action.get("farmer", []), *action.get("hands", [])]:
                if len(actor) > 1 and actor[0] == "PLANT":
                    plant_by_phase[phase][actor[1]] += 1
        route_summaries[name] = {
            "planned_decisions": len(actions),
            "action_sha256": hashlib.sha256(json.dumps(actions, sort_keys=True).encode()).hexdigest(),
            "planned_purchases": dict(purchases),
            "planned_plant_counts_by_phase": {k: dict(v) for k, v in plant_by_phase.items()},
        }
    pairwise = {}
    names = sorted(routes)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            different = [t for t, (a, b) in enumerate(zip(routes[left], routes[right], strict=True)) if a != b]
            pairwise[f"{left}:{right}"] = {"first_difference": min(different), "different_planned_decisions": len(different)}
    payload = {
        "evidence_level": "E0_engine_mechanics_and_source_inspection",
        "engine_version": importlib.metadata.version("kaggle-environments"),
        "engine_source_sha256": hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
        "engine_schema_sha256": hashlib.sha256(Path(engine.__file__).with_suffix(".json").read_bytes()).hexdigest(),
        "passive_repeatability": runs,
        "identical_public_trajectories": runs[0]["observation_sha256"] == runs[1]["observation_sha256"],
        "price_probes": price_probes,
        "floor_sell_probe": {"committed": committed, "inventory_unchanged": floor_market["inventory"] == before, "money": floor_farm["money"]},
        "route_config": vars(public_v43._V43_CONFIG),
        "route_summaries": route_summaries,
        "route_pairwise": pairwise,
        "planned_action_limitation": "Route tables are intended actions, not executed quantities or a closed-loop strength result.",
    }
    output = Path(__file__).with_name("mechanics_probes.json")
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
