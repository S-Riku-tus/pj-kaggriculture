"""Diagnose relative-score externalities from V63's late role tie-break."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.train_v12_relative_policy import _observation  # noqa: E402

PRODUCTS = (
    "WHEAT",
    "CARROT",
    "TOMATO",
    "STRAWBERRY",
    "MELON",
    "EGG",
    "MILK",
    "WOOL",
    "FERTILIZER",
)
COMPARISONS = {
    "v14_calibration": (
        ROOT / "data/runs/v58_interaction_safe_v14_20265821.json",
        ROOT / "data/runs/v62_phase_late_v14_20265821.json",
    ),
    "v14_holdout": (
        ROOT / "data/runs/v58_interaction_safe_v14_holdout_20265831.json",
        ROOT / "data/runs/v63_phase_late_v14_holdout_20265831.json",
    ),
    "v18_diagnostic": (
        ROOT / "data/runs/v58_interaction_safe_v18_20265841.json",
        ROOT / "data/runs/v63_phase_late_v18_20265841.json",
    ),
    "v18_holdout": (
        ROOT / "data/runs/v63_safe_v18_holdout_20265851.json",
        ROOT / "data/runs/v63_phase_late_v18_holdout_20265851.json",
    ),
}
OUTPUT = ROOT / "data/analysis/v64_v63_market_externality.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _replay(game: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(game["replay"]))
    if not path.is_absolute():
        path = ROOT / path
    return _load(path)


def _action(replay: dict[str, Any], decision_step: int, seat: int) -> dict[str, Any]:
    steps = replay.get("steps") or []
    if decision_step + 1 >= len(steps) or seat >= len(steps[decision_step + 1]):
        return {}
    return steps[decision_step + 1][seat].get("action") or {}


def _farm_counts(farm: dict[str, Any]) -> tuple[int, int]:
    crops = 0
    animals = 0
    for row in farm.get("tiles", []):
        for tile in row:
            if not isinstance(tile, dict):
                continue
            crops += tile.get("kind") == "PLANT"
            animals += bool(tile.get("animal"))
    return crops, animals


def _terminal(replay: dict[str, Any], seat: int) -> dict[str, float]:
    obs = None
    for step in range(len(replay.get("steps") or []) - 1, -1, -1):
        obs = _observation(replay, step, seat)
        if obs is not None:
            break
    if obs is None:
        return {}
    farm = (obs.get("farms") or [{}, {}])[seat]
    private = obs.get("private") or {}
    prices = (obs.get("market") or {}).get("prices") or {}
    shed = private.get("shed") or {}
    inventories = private.get("inventories") or []
    crops, animals = _farm_counts(farm)
    inventory_value = sum(
        max(0, int(shed.get(item, 0) or 0)) * max(1, int(prices.get(item, 1) or 1))
        for item in PRODUCTS
    ) + sum(
        max(0, int(inventory.get(item, 0) or 0))
        * max(1, int(prices.get(item, 1) or 1))
        for inventory in inventories
        for item in PRODUCTS
    )
    return {
        "money": float(farm.get("money", 0) or 0),
        "crops": float(crops),
        "animals": float(animals),
        "productive": float(crops + animals),
        "inventory_quote_value": float(inventory_value),
    }


def _side(replay: dict[str, Any], seat: int) -> dict[str, Any]:
    sale_units: Counter[str] = Counter()
    sale_quote: Counter[str] = Counter()
    late_sale_units: Counter[str] = Counter()
    late_sale_quote: Counter[str] = Counter()
    market_orders: Counter[str] = Counter()
    steps = replay.get("steps") or []
    for decision_step in range(len(steps) - 1):
        obs = _observation(replay, decision_step, seat)
        if obs is None:
            continue
        day = int(obs.get("day", 0) or 0)
        private = obs.get("private") or {}
        available = Counter(
            {
                item: max(0, int((private.get("shed") or {}).get(item, 0) or 0))
                for item in PRODUCTS
            }
        )
        prices = (obs.get("market") or {}).get("prices") or {}
        for order in (_action(replay, decision_step, seat).get("market") or [])[:10]:
            if not isinstance(order, list) or not order:
                continue
            op = str(order[0])
            market_orders[op] += 1
            if op != "SELL" or len(order) < 3:
                continue
            item = str(order[1])
            if item not in PRODUCTS:
                continue
            quantity = min(available[item], max(0, int(order[2] or 0)))
            available[item] -= quantity
            quote = quantity * max(1, int(prices.get(item, 1) or 1))
            sale_units[item] += quantity
            sale_quote[item] += quote
            if day >= 11:
                late_sale_units[item] += quantity
                late_sale_quote[item] += quote
    return {
        "sale_units": dict(sale_units),
        "sale_quote": dict(sale_quote),
        "late_sale_units": dict(late_sale_units),
        "late_sale_quote": dict(late_sale_quote),
        "sale_units_total": float(sum(sale_units.values())),
        "sale_quote_total": float(sum(sale_quote.values())),
        "late_sale_units_total": float(sum(late_sale_units.values())),
        "late_sale_quote_total": float(sum(late_sale_quote.values())),
        "market_orders": dict(market_orders),
        "terminal": _terminal(replay, seat),
    }


def _first_divergence(
    safe: dict[str, Any], candidate: dict[str, Any], seat: int
) -> dict[str, Any] | None:
    limit = min(len(safe.get("steps") or []), len(candidate.get("steps") or [])) - 1
    for step in range(limit):
        left = _action(safe, step, seat)
        right = _action(candidate, step, seat)
        if left != right:
            obs = _observation(safe, step, seat) or {}
            return {
                "step": step,
                "day": int(obs.get("day", 0) or 0),
                "hour": int(obs.get("hour", 0) or 0),
                "safe": left,
                "candidate": right,
            }
    return None


def _numeric_delta(candidate: dict[str, Any], safe: dict[str, Any]) -> dict[str, float]:
    keys = sorted(
        key
        for key in set(candidate) & set(safe)
        if isinstance(candidate[key], int | float)
        and isinstance(safe[key], int | float)
    )
    return {key: float(candidate[key]) - float(safe[key]) for key in keys}


def _item_delta(candidate: dict[str, float], safe: dict[str, float]) -> dict[str, float]:
    return {
        item: float(candidate.get(item, 0)) - float(safe.get(item, 0))
        for item in PRODUCTS
        if candidate.get(item, 0) or safe.get(item, 0)
    }


def _game_row(
    safe_game: dict[str, Any], candidate_game: dict[str, Any]
) -> dict[str, Any]:
    safe_replay = _replay(safe_game)
    candidate_replay = _replay(candidate_game)
    focal = int(safe_game["seat"])
    sides = {}
    for label, seat in (("focal", focal), ("opponent", 1 - focal)):
        safe_side = _side(safe_replay, seat)
        candidate_side = _side(candidate_replay, seat)
        sides[label] = {
            "summary_delta": _numeric_delta(candidate_side, safe_side),
            "terminal_delta": _numeric_delta(
                candidate_side["terminal"], safe_side["terminal"]
            ),
            "sale_units_delta": _item_delta(
                candidate_side["sale_units"], safe_side["sale_units"]
            ),
            "sale_quote_delta": _item_delta(
                candidate_side["sale_quote"], safe_side["sale_quote"]
            ),
            "late_sale_units_delta": _item_delta(
                candidate_side["late_sale_units"], safe_side["late_sale_units"]
            ),
            "late_sale_quote_delta": _item_delta(
                candidate_side["late_sale_quote"], safe_side["late_sale_quote"]
            ),
            "first_action_divergence": _first_divergence(
                safe_replay, candidate_replay, seat
            ),
        }
    return {
        "seed": int(safe_game["seed"]),
        "seat": focal,
        "reward_delta": float(candidate_game["ours"]) - float(safe_game["ours"]),
        "opponent_reward_delta": float(candidate_game["theirs"])
        - float(safe_game["theirs"]),
        "margin_delta": float(candidate_game["margin"]) - float(safe_game["margin"]),
        "sides": sides,
    }


def _mean(values: list[float]) -> float:
    return mean(values) if values else 0.0


def _comparison(safe_path: Path, candidate_path: Path) -> dict[str, Any]:
    safe = _load(safe_path)
    candidate = _load(candidate_path)
    safe_games = {(int(g["seed"]), int(g["seat"])): g for g in safe["games"]}
    candidate_games = {
        (int(g["seed"]), int(g["seat"])): g for g in candidate["games"]
    }
    if set(safe_games) != set(candidate_games):
        raise ValueError(f"paired game mismatch: {safe_path} vs {candidate_path}")
    rows = [
        _game_row(safe_games[key], candidate_games[key])
        for key in sorted(safe_games)
    ]
    return {
        "games": len(rows),
        "mean_reward_delta": _mean([row["reward_delta"] for row in rows]),
        "mean_opponent_reward_delta": _mean(
            [row["opponent_reward_delta"] for row in rows]
        ),
        "mean_margin_delta": _mean([row["margin_delta"] for row in rows]),
        "changed_games": sum(
            row["sides"]["focal"]["first_action_divergence"] is not None
            for row in rows
        ),
        "rows": rows,
    }


def main() -> None:
    comparisons = {name: _comparison(*paths) for name, paths in COMPARISONS.items()}
    payload = {
        "format": "kaggriculture-v64-v63-market-externality-v1",
        "runtime_policy_enabled": False,
        "objective": (
            "separate V63 focal production gains from opponent and shared-market effects"
        ),
        "comparisons": comparisons,
        "limits": [
            "sale quote is quantity times the decision-time public price, not net profit",
            "downstream opponent action changes are closed-loop effects, not isolated causal components",
            "local V14/V18 opponents do not estimate hidden leaderboard rating",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        name: {
            key: value[key]
            for key in (
                "games",
                "changed_games",
                "mean_reward_delta",
                "mean_opponent_reward_delta",
                "mean_margin_delta",
            )
        }
        for name, value in comparisons.items()
    }
    worst = min(
        (
            {"group": name, **row}
            for name, value in comparisons.items()
            for row in value["rows"]
        ),
        key=lambda row: row["margin_delta"],
    )
    print(json.dumps({"comparisons": compact, "worst_margin": worst}, ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
