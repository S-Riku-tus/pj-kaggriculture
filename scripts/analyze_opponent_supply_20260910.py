"""Offline public-only forecasting; labels are separated from live features."""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluation.replay import action, observation  # noqa: E402
from scripts.evaluation.safety import simulate_turn  # noqa: E402
from scripts.train_v111_strategy import _demand_per_day  # noqa: E402

OUT = ROOT / "data/analysis/research_20260910_supply"
PRODUCTS = ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "MILK", "WOOL", "EGG")
ASSET = {"MILK": "COW", "WOOL": "SHEEP", "EGG": "GOOSE"}
SCHEDULE = {"TOMATO": (8, 1), "STRAWBERRY": (10, 2), "MILK": (8, 2), "WOOL": (6, 3), "EGG": (4, 1)}
SCALE = {
    "WHEAT": 400,
    "CARROT": 450,
    "TOMATO": 200,
    "STRAWBERRY": 100,
    "MELON": 300,
    "MILK": 122,
    "WOOL": 105,
    "EGG": 420,
}


def read(path):
    with gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open(encoding="utf-8") as handle:
        return json.load(handle)


def tiles(farm, item):
    return [
        tile
        for row in farm["tiles"]
        for tile in row
        if isinstance(tile, dict) and (tile.get("animal") or tile.get("crop")) == ASSET.get(item, item)
    ]


def public_features(obs, opponent_seat, item, horizon):
    """No private observations, action tapes, IDs, or future fields accepted here."""
    day, hour = obs["day"], obs["hour"]
    farm, own = obs["farms"][opponent_seat], obs["farms"][1 - opponent_seat]
    selected = tiles(farm, item)
    future_days = (hour + horizon) // 24
    production = 0.0
    for tile in selected:
        if item in SCHEDULE:
            first, interval = SCHEDULE[item]
            age = day - tile.get("placed_day", tile.get("planted_day", day))
            pending = float(tile.get("pending_care_bonus", 0))
            for offset in range(1, future_days + 1):
                elapsed = age + offset - first
                if elapsed >= 0 and elapsed % interval == 0:
                    if item not in ASSET and elapsed // interval >= 4:
                        continue
                    production += min(6, 1 + pending) if item in ASSET else 1.5
                    pending = 0
                if item in ASSET:
                    pending += 1  # E0 optimistic maintained-and-cared scenario
        else:
            age = day - tile.get("planted_day", day)
            maturity = 10 if item == "MELON" else 2
            if age < maturity <= age + future_days:
                production += 3.0
    yield_now = sum(tile.get("yield_units", 0) for tile in selected)
    market = obs["market"]
    demand = _demand_per_day(obs["town"].get("unlocked_shops", []), item)
    values = [
        day / 30,
        hour / 24,
        horizon / 144,
        len(selected),
        len(tiles(own, item)),
        yield_now,
        sum(day - tile.get("placed_day", tile.get("planted_day", day)) for tile in selected),
        production,
        (market["inventory"][item] - 10000) / SCALE[item],
        market["prices"][item],
        demand,
        len(farm.get("hands", [])),
        farm["money"] / 10000,
        (farm["money"] - own["money"]) / 10000,
    ]
    return values, yield_now + production


def stock(obs, item):
    private = obs.get("private", {})
    return sum(int(bag.get(item, 0)) for bag in [private.get("shed", {}), *private.get("inventories", [])])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    prereg = {
        "horizons": [24, 72, 144],
        "ridge_lambda": 10,
        "selection": "24 newest Discovery episodes; both seats",
        "features": "public farm counts/ages/yields/care, market, Town, labor, money only",
        "labels": "current opponent private total; future engine-committed SELL units; any-sale hazard",
        "split": "connected components of same submission OR identical h48 field opening; leave component out",
        "promotion": "NONE: predictive diagnostic only, no strategy thresholds selected",
    }
    pre = OUT / "preregistration.json"
    if pre.exists():
        raise SystemExit("Refusing to overwrite frozen forecast experiment")
    pre.write_text(json.dumps(prereg, indent=2), encoding="utf-8")
    sources = [
        json.loads(line)
        for line in (ROOT / "data/current_field_20260910/discovery_manifest.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    sources = sorted(sources, key=lambda row: row["episode_id"], reverse=True)[:24]
    records = []
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        parent[find(x)] = find(y)

    for source in sources:
        replay = read(ROOT / source["path"])
        sales = np.zeros((2, 719, len(PRODUCTS)))
        for step in range(719):
            events = simulate_turn(replay, step)
            for seat in (0, 1):
                for event in events[seat]:
                    if (
                        event.get("kind") == "market_commit"
                        and event.get("op") == "SELL"
                        and event.get("item") in PRODUCTS
                    ):
                        sales[seat, step, PRODUCTS.index(event["item"])] += event["committed"]
        agents = source["episode_metadata"]["agents"]
        for seat in (0, 1):
            sid = str(agents[seat]["submissionId"])
            prefix = [[action(replay, t, seat).get("farmer"), action(replay, t, seat).get("hands")] for t in range(48)]
            family = hashlib.sha256(json.dumps(prefix).encode()).hexdigest()[:20]
            union("sid" + sid, "prefix" + family)
            for step in range(144, 577, 24):
                for horizon in (24, 72, 144):
                    if step + horizon > 719:
                        continue
                    public = observation(replay, step, 1 - seat)
                    private = observation(replay, step, seat)
                    for index, item in enumerate(PRODUCTS):
                        features, rule = public_features(public, seat, item, horizon)
                        target = float(sales[seat, step : step + horizon, index].sum())
                        records.append(
                            {
                                "episode": source["episode_id"],
                                "submission": sid,
                                "item": item,
                                "horizon": horizon,
                                "features": features,
                                "rule_supply": rule,
                                "stock": stock(private, item),
                                "supply": target,
                                "hazard": float(target > 0),
                            }
                        )
        print("forecast labels", source["episode_id"], len(records), flush=True)
    for row in records:
        row["family"] = find("sid" + row["submission"])
    results = []
    for item in PRODUCTS:
        for horizon in (24, 72, 144):
            selected = [row for row in records if row["item"] == item and row["horizon"] == horizon]
            families = sorted({row["family"] for row in selected})
            for target in ("stock", "supply", "hazard"):
                errors = defaultdict(list)
                for family in families:
                    train = [row for row in selected if row["family"] != family]
                    test = [row for row in selected if row["family"] == family]
                    if not train:
                        continue
                    x = np.array([row["features"] for row in train])
                    y = np.array([row[target] for row in train])
                    xt = np.array([row["features"] for row in test])
                    yt = np.array([row[target] for row in test])
                    center = x.mean(axis=0)
                    spread = np.maximum(x.std(axis=0), 1e-6)
                    x = np.column_stack([np.ones(len(x)), (x - center) / spread])
                    xt = np.column_stack([np.ones(len(xt)), (xt - center) / spread])
                    penalty = np.eye(x.shape[1]) * 10
                    penalty[0, 0] = 0
                    beta = np.linalg.solve(x.T @ x + penalty, x.T @ y)
                    pred = np.maximum(0, xt @ beta)
                    if target == "hazard":
                        pred = np.minimum(1, pred)
                    errors["ridge"].extend(abs(pred - yt).tolist())
                    errors["training_mean"].extend(abs(y.mean() - yt).tolist())
                    errors["zero"].extend(abs(yt).tolist())
                    if target == "supply":
                        errors["maintained_calendar"].extend([abs(row["rule_supply"] - row[target]) for row in test])
                results.append(
                    {
                        "item": item,
                        "horizon": horizon,
                        "target": target,
                        "components": len(families),
                        "n": len(selected),
                        "MAE": {key: float(np.mean(value)) for key, value in errors.items()},
                    }
                )
    (OUT / "rows.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    (OUT / "result.json").write_text(
        json.dumps(
            {
                "preregistration": prereg,
                "episodes": len(sources),
                "families": len({row["family"] for row in records}),
                "results": results,
                "limitations": [
                    "Opening/source union is a conservative observable grouping, "
                    "not proven independent source ancestry.",
                    "Price-floor SELL does not increase market inventory; "
                    "exact latent stock is not identifiable from market deltas alone.",
                    "Calendar predictor assumes future care/watering and collection; includes no new investment.",
                    "No Fresh Holdout or causal win evidence. No forecast installed in Agent.",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def strict_revalidation():
    """Keep parameters fixed; also exclude the held-out episodes' other seat."""
    records = [json.loads(line) for line in (OUT / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
    results = []
    for item in PRODUCTS:
        for horizon in (24, 72, 144):
            selected = [row for row in records if row["item"] == item and row["horizon"] == horizon]
            families = sorted({row["family"] for row in selected})
            for target in ("stock", "supply", "hazard"):
                errors = defaultdict(list)
                for family in families:
                    test = [row for row in selected if row["family"] == family]
                    excluded_episodes = {row["episode"] for row in test}
                    train = [
                        row for row in selected if row["family"] != family and row["episode"] not in excluded_episodes
                    ]
                    if not train:
                        raise ValueError("No training episodes remain in strict fold")
                    x = np.array([row["features"] for row in train])
                    y = np.array([row[target] for row in train])
                    xt = np.array([row["features"] for row in test])
                    yt = np.array([row[target] for row in test])
                    center, spread = x.mean(axis=0), np.maximum(x.std(axis=0), 1e-6)
                    x = np.column_stack([np.ones(len(x)), (x - center) / spread])
                    xt = np.column_stack([np.ones(len(xt)), (xt - center) / spread])
                    penalty = np.eye(x.shape[1]) * 10
                    penalty[0, 0] = 0
                    beta = np.linalg.solve(x.T @ x + penalty, x.T @ y)
                    pred = np.maximum(0, xt @ beta)
                    if target == "hazard":
                        pred = np.minimum(1, pred)
                    errors["ridge"].extend(abs(pred - yt).tolist())
                    errors["training_mean"].extend(abs(y.mean() - yt).tolist())
                    errors["zero"].extend(abs(yt).tolist())
                    if target == "supply":
                        errors["maintained_calendar"].extend([abs(row["rule_supply"] - row[target]) for row in test])
                results.append(
                    {
                        "item": item,
                        "horizon": horizon,
                        "target": target,
                        "components": len(families),
                        "n": len(selected),
                        "MAE": {key: float(np.mean(value)) for key, value in errors.items()},
                    }
                )
    payload = {
        "split": (
            "held-out connected submission/opening group; exclude every held-out episode from training, "
            "including the other player"
        ),
        "parameters": "unchanged ridge lambda10; no retuning",
        "evidence": "E2 predictive diagnostic with conservative observed groups; latent ancestry still unresolved",
        "results": results,
    }
    (OUT / "result_strict_episode_exclusion.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("Strict episode-exclusion revalidation complete", flush=True)


if __name__ == "__main__":
    if "--strict-split" in sys.argv:
        strict_revalidation()
    else:
        main()
