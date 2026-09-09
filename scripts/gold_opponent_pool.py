"""Shared mechanics for executable-opponent discovery and V111 weakness mapping.

The important statistical unit in this module is an *executed action family*.
Source names, notebook names, and submission ids are provenance only.  Two
sources are the same exact family when their candidate-side cumulative action
hash vectors match on every registered probe seed, seat, and checkpoint.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import math
import os
import random
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from statistics import mean, median
from typing import Any

from kaggle_environments import make

from scripts.evaluation.divergence import portfolio
from scripts.evaluation.replay import (
    action,
    canonical_action,
    decision_count,
    lineage_hash,
    observation,
    resolved_seed,
    result_label,
    result_score,
)

ROOT = Path(__file__).resolve().parents[1]
ACTION_CHECKPOINTS = (24, 100, 200, 400, 719)
DAY_MARGIN_CHECKPOINTS = (288, 432, 480, 576)
MARKET_ITEMS = (
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
PREMIUM_ITEMS = ("STRAWBERRY", "MELON", "MILK", "WOOL")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dependency_closure_sha256(entrypoint: Path) -> str:
    """Hash the local immutable dependency directory, not only ``main.py``."""
    digest = hashlib.sha256()
    root = entrypoint.parent
    selected = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix.lower() in {".py", ".json", ".txt", ".md"}
    ]
    for path in sorted(selected, key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
        digest.update(b"\n")
    return digest.hexdigest()


def stable_json_hash(value: Any, length: int = 20) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def _import_module(path: Path, role: str) -> Any:
    name = f"_gold_pool_{role}_{os.getpid()}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import executable opponent: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if hasattr(module, "reset_runtime_state"):
        module.reset_runtime_state()
    if not callable(getattr(module, "agent", None)):
        raise TypeError(f"entrypoint has no callable agent: {path}")
    return module


def _call(function: Callable[..., Any], obs: Any, configuration: Any) -> Any:
    try:
        parameters = list(inspect.signature(function).parameters.values())
        accepts_configuration = len(parameters) >= 2 or any(
            parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}
            for parameter in parameters
        )
    except (TypeError, ValueError):
        accepts_configuration = True
    return function(obs, configuration) if accepts_configuration else function(obs)


def _entrypoint(candidate: dict[str, Any], role: str) -> tuple[Any, Any | None]:
    if candidate.get("kind") == "builtin":
        return str(candidate["entrypoint"]), None
    path = Path(str(candidate["entrypoint"])).resolve()
    module = _import_module(path, role)

    def wrapped(obs: Any, configuration: Any = None):
        return _call(module.agent, obs, configuration)

    return wrapped, module


def _farm(obs: dict[str, Any] | None, seat: int) -> dict[str, Any]:
    farms = list((obs or {}).get("farms") or [])
    value = farms[seat] if seat < len(farms) else {}
    return value if isinstance(value, dict) else {}


def _numeric_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {str(key): float(number or 0.0) for key, number in value.items()}


def _checkpoint_state(replay: dict[str, Any], focal_seat: int, step: int) -> dict[str, Any]:
    obs = observation(replay, min(step, decision_count(replay)), focal_seat) or {}
    own = _farm(obs, focal_seat)
    opposing = _farm(obs, 1 - focal_seat)
    market = obs.get("market") or {}
    town = obs.get("town") or {}
    own_money = float(own.get("money", 0.0) or 0.0)
    opponent_money = float(opposing.get("money", 0.0) or 0.0)
    return {
        "step": step,
        "own_money": own_money,
        "opponent_money": opponent_money,
        "cash_margin": own_money - opponent_money,
        "own_portfolio": portfolio(own),
        "opponent_portfolio": portfolio(opposing),
        "market_inventory": _numeric_map(market.get("inventory")),
        "market_prices": _numeric_map(market.get("prices")),
        "unlocked_shops": sorted(str(item) for item in (town.get("unlocked_shops") or [])),
        "own_hands": len(own.get("hands") or []),
        "opponent_hands": len(opposing.get("hands") or []),
    }


def _action_profile(replay: dict[str, Any], seat: int) -> dict[str, Any]:
    field_operations: Counter[str] = Counter()
    market_operations: Counter[str] = Counter()
    market_item_quantity: Counter[str] = Counter()
    active_actor_slots = 0
    actor_slots = 0
    unique_actions: set[str] = set()
    for step in range(decision_count(replay)):
        emitted = action(replay, step, seat)
        unique_actions.add(canonical_action(emitted))
        actors = [emitted.get("farmer") or ["PASS"], *(emitted.get("hands") or [])]
        actor_slots += len(actors)
        for row in actors:
            operation = str((row or ["PASS"])[0])
            field_operations[operation] += 1
            active_actor_slots += operation != "PASS"
        for row in emitted.get("market") or []:
            if not row:
                continue
            operation = str(row[0])
            item = str(row[1]) if len(row) >= 2 else ""
            quantity = row[-1] if len(row) >= 3 and isinstance(row[-1], int | float) else 1
            market_operations[f"{operation}:{item}"] += 1
            market_item_quantity[f"{operation}:{item}"] += float(quantity)
    return {
        "field_operations": dict(sorted(field_operations.items())),
        "market_operations": dict(sorted(market_operations.items())),
        "market_item_quantity": dict(sorted(market_item_quantity.items())),
        "active_actor_slots": active_actor_slots,
        "actor_slots": actor_slots,
        "action_utilization": active_actor_slots / max(1, actor_slots),
        "unique_canonical_actions": len(unique_actions),
    }


def _market_displacement(
    initial: dict[str, Any], checkpoint: dict[str, Any]
) -> dict[str, Any]:
    inventory = {
        item: float(checkpoint["market_inventory"].get(item, 0.0))
        - float(initial["market_inventory"].get(item, 0.0))
        for item in MARKET_ITEMS
    }
    prices = {
        item: float(checkpoint["market_prices"].get(item, 0.0))
        - float(initial["market_prices"].get(item, 0.0))
        for item in MARKET_ITEMS
    }
    return {
        "inventory_delta": inventory,
        "price_delta": prices,
        "inventory_l1": sum(abs(value) for value in inventory.values()),
        "price_l1": sum(abs(value) for value in prices.values()),
    }


def _premium_market_behavior(action_profile: dict[str, Any]) -> dict[str, Any]:
    """Reduce an action stream to descriptive premium-market exposure.

    This is deliberately a diagnostic, not a strength metric.  It records how
    much premium output was sold and how much premium-producing capacity was
    requested; it does not infer profitability or causal value from the orders.
    """
    quantities = action_profile.get("market_item_quantity") or {}
    sold = {
        item: float(quantities.get(f"SELL:{item}", 0.0) or 0.0)
        for item in PREMIUM_ITEMS
    }
    all_sell_quantity = sum(
        float(quantity or 0.0)
        for key, quantity in quantities.items()
        if str(key).startswith("SELL:")
    )
    capacity_orders = {
        "strawberry_seed": float(
            quantities.get("BUY_SEED:STRAWBERRY", 0.0) or 0.0
        ),
        "melon_seed": float(quantities.get("BUY_SEED:MELON", 0.0) or 0.0),
        "cow": float(quantities.get("BUY_ANIMAL:COW", 0.0) or 0.0),
        "sheep": float(quantities.get("BUY_ANIMAL:SHEEP", 0.0) or 0.0),
    }
    premium_sell_quantity = sum(sold.values())
    return {
        "sell_quantity": sold,
        "premium_sell_quantity": premium_sell_quantity,
        "all_sell_quantity": all_sell_quantity,
        "premium_share_of_sell_quantity": (
            premium_sell_quantity / all_sell_quantity
            if all_sell_quantity > 0.0
            else 0.0
        ),
        "capacity_purchase_quantity": capacity_orders,
    }


def replay_diagnostics(
    replay: dict[str, Any], focal_seat: int, episode_steps: int = 720
) -> dict[str, Any]:
    """Return common weakness-map diagnostics for one focal replay arm."""
    terminal_step = max(0, int(episode_steps) - 1)
    state_checkpoints = sorted(
        {0, *(step for step in DAY_MARGIN_CHECKPOINTS if step <= terminal_step), terminal_step}
    )
    states = {
        str(step): _checkpoint_state(replay, focal_seat, step)
        for step in state_checkpoints
    }
    initial = states["0"]
    terminal = states[str(terminal_step)]
    focal_actions = _action_profile(replay, focal_seat)
    opponent_actions = _action_profile(replay, 1 - focal_seat)
    return {
        "checkpoint_states": states,
        "terminal_market_displacement": _market_displacement(initial, terminal),
        "champion_action_profile": focal_actions,
        "opponent_action_profile": opponent_actions,
        "focal_premium_market_behavior": _premium_market_behavior(focal_actions),
        "opponent_premium_market_behavior": _premium_market_behavior(opponent_actions),
    }


def run_executable_game(task: dict[str, Any]) -> dict[str, Any]:
    """Run one isolated 720-turn game and return action/weakness diagnostics."""
    champion = dict(task["champion"])
    candidate = dict(task["candidate"])
    seed = int(task["seed"])
    champion_seat = int(task["champion_seat"])
    episode_steps = int(task.get("episode_steps", 720))
    champion_agent, _ = _entrypoint(champion, "champion")
    opponent_agent, _ = _entrypoint(candidate, "opponent")
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": episode_steps, "seed": seed},
        debug=True,
    )
    env.run(
        [champion_agent, opponent_agent]
        if champion_seat == 0
        else [opponent_agent, champion_agent]
    )
    replay = env.toJSON()
    final = env.steps[-1]
    rewards = [float(state.reward or 0.0) for state in final]
    ours = rewards[champion_seat]
    theirs = rewards[1 - champion_seat]
    score = result_score(ours, theirs)
    action_checkpoints = tuple(int(value) for value in task.get("action_checkpoints", ACTION_CHECKPOINTS))
    diagnostics = replay_diagnostics(replay, champion_seat, episode_steps)
    return {
        "candidate_id": candidate["candidate_id"],
        "requested_seed": seed,
        "resolved_seed": resolved_seed(replay, seed),
        "champion_seat": champion_seat,
        "opponent_seat": 1 - champion_seat,
        "episode_steps": episode_steps,
        "final_statuses": [str(state.status) for state in final],
        "champion_coin": ours,
        "opponent_coin": theirs,
        "relative_margin": ours - theirs,
        "win_score": score,
        "result": result_label(score),
        "champion_fingerprint": {
            str(step): lineage_hash(replay, champion_seat, step)
            for step in action_checkpoints
        },
        "opponent_fingerprint": {
            str(step): lineage_hash(replay, 1 - champion_seat, step)
            for step in action_checkpoints
        },
        "diagnostics": diagnostics,
    }


def source_fingerprint(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row["requested_seed"]),
            int(row["champion_seat"]),
        ),
    )
    vector = [
        {
            "seed": int(row["requested_seed"]),
            "champion_seat": int(row["champion_seat"]),
            "opponent": row["opponent_fingerprint"],
        }
        for row in ordered
    ]
    checkpoint_signatures = {
        str(checkpoint): stable_json_hash(
            [
                {
                    "seed": row["requested_seed"],
                    "champion_seat": row["champion_seat"],
                    "hash": row["opponent_fingerprint"][str(checkpoint)],
                }
                for row in ordered
            ]
        )
        for checkpoint in ACTION_CHECKPOINTS
    }
    return {
        "family_signature": stable_json_hash(vector, 32),
        "checkpoint_vector_signatures": checkpoint_signatures,
        "probe_vector": vector,
    }


def cluster_sources(
    candidates: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_candidate[str(row["candidate_id"])].append(row)
    candidate_by_id = {str(row["candidate_id"]): row for row in candidates}
    sources = []
    exact: dict[str, list[str]] = defaultdict(list)
    checkpoint_clusters: dict[str, dict[str, list[str]]] = {
        str(checkpoint): defaultdict(list) for checkpoint in ACTION_CHECKPOINTS
    }
    for candidate_id in sorted(candidate_by_id):
        selected = by_candidate.get(candidate_id, [])
        expected = int(candidate_by_id[candidate_id].get("expected_probe_games", len(selected)))
        if not selected or len(selected) != expected:
            sources.append(
                {
                    "candidate_id": candidate_id,
                    "probe_status": "INCOMPLETE",
                    "completed_games": len(selected),
                    "expected_games": expected,
                }
            )
            continue
        signature = source_fingerprint(selected)
        exact[signature["family_signature"]].append(candidate_id)
        for checkpoint, checkpoint_signature in signature["checkpoint_vector_signatures"].items():
            checkpoint_clusters[checkpoint][checkpoint_signature].append(candidate_id)
        sources.append(
            {
                "candidate_id": candidate_id,
                "probe_status": "COMPLETE",
                **signature,
                "strict_win_rate_of_v111": mean(
                    float(row["result"] == "win") for row in selected
                ),
                "win_score_of_v111": mean(float(row["win_score"]) for row in selected),
                "mean_margin_of_v111": mean(float(row["relative_margin"]) for row in selected),
            }
        )
    families = []
    for index, signature in enumerate(sorted(exact), start=1):
        members = sorted(exact[signature])
        ancestry = sorted(
            {
                str(candidate_by_id[member].get("source_ancestry_id") or member)
                for member in members
            }
        )
        families.append(
            {
                "behavior_family_id": f"gold_family_{index:02d}_{signature[:8]}",
                "family_signature": signature,
                "source_members": members,
                "representative_candidate_id": members[0],
                "source_ancestry_ids": ancestry,
                "independent_ancestry_votes": len(ancestry),
            }
        )
    return {
        "clustering_rule": (
            "exact equality of candidate cumulative canonical action-stream hashes "
            "for all common probe seeds, both seats, and checkpoints 24/100/200/400/719"
        ),
        "source_count": len(candidates),
        "complete_source_count": sum(row.get("probe_status") == "COMPLETE" for row in sources),
        "exact_behavior_family_count": len(families),
        "sources": sources,
        "exact_families": families,
        "checkpoint_clusters": {
            checkpoint: [
                {"signature": signature, "members": sorted(members)}
                for signature, members in sorted(groups.items())
            ]
            for checkpoint, groups in checkpoint_clusters.items()
        },
    }


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def seed_cluster_bootstrap(
    rows: list[dict[str, Any]],
    metric: Callable[[dict[str, Any]], float],
    *,
    repetitions: int = 2000,
    bootstrap_seed: int = 20260901,
) -> dict[str, Any]:
    by_seed: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_seed[int(row["requested_seed"])].append(row)
    seed_ids = sorted(by_seed)
    rng = random.Random(bootstrap_seed)
    estimates = []
    for _ in range(repetitions):
        sampled = rng.choices(seed_ids, k=len(seed_ids))
        values = [metric(row) for seed in sampled for row in by_seed[seed]]
        estimates.append(mean(values))
    point = mean(metric(row) for row in rows)
    return {
        "method": "cluster bootstrap by episode seed; both seats retained",
        "independent_seeds": len(seed_ids),
        "repetitions": repetitions,
        "estimate": point,
        "low_95": _quantile(estimates, 0.025),
        "high_95": _quantile(estimates, 0.975),
    }


def _mean_mapping(rows: list[dict[str, float]]) -> dict[str, float]:
    keys = sorted({key for row in rows for key in row})
    return {key: mean(float(row.get(key, 0.0)) for row in rows) for key in keys}


def summarize_v111_family(
    family: dict[str, Any], rows: list[dict[str, Any]], *, bootstrap_seed: int
) -> dict[str, Any]:
    losses = [row for row in rows if row["result"] == "loss"]
    wins = [row for row in rows if row["result"] == "win"]
    checkpoint_summary: dict[str, Any] = {}
    for checkpoint in DAY_MARGIN_CHECKPOINTS:
        values = [
            float(row["diagnostics"]["checkpoint_states"][str(checkpoint)]["cash_margin"])
            for row in rows
        ]
        lead_to_loss = sum(
            float(row["diagnostics"]["checkpoint_states"][str(checkpoint)]["cash_margin"])
            > 0
            and row["result"] == "loss"
            for row in rows
        )
        behind_to_win = sum(
            float(row["diagnostics"]["checkpoint_states"][str(checkpoint)]["cash_margin"])
            < 0
            and row["result"] == "win"
            for row in rows
        )
        checkpoint_summary[str(checkpoint)] = {
            "day": checkpoint // 24,
            "mean_visible_cash_margin": mean(values),
            "median_visible_cash_margin": median(values),
            "lead_to_loss": lead_to_loss,
            "behind_to_win": behind_to_win,
        }
    by_seat = {}
    for seat in (0, 1):
        selected = [row for row in rows if int(row["champion_seat"]) == seat]
        by_seat[str(seat)] = {
            "games": len(selected),
            "wins": sum(row["result"] == "win" for row in selected),
            "draws": sum(row["result"] == "draw" for row in selected),
            "losses": sum(row["result"] == "loss" for row in selected),
            "strict_win_rate": mean(float(row["result"] == "win") for row in selected),
            "win_score": mean(float(row["win_score"]) for row in selected),
            "mean_margin": mean(float(row["relative_margin"]) for row in selected),
        }
    terminal_shops = Counter(
        "+".join(
            row["diagnostics"]["checkpoint_states"][str(row["episode_steps"] - 1)][
                "unlocked_shops"
            ]
        )
        or "NONE"
        for row in rows
    )
    market_inventory = _mean_mapping(
        [row["diagnostics"]["terminal_market_displacement"]["inventory_delta"] for row in rows]
    )
    market_prices = _mean_mapping(
        [row["diagnostics"]["terminal_market_displacement"]["price_delta"] for row in rows]
    )
    return {
        "behavior_family_id": family["behavior_family_id"],
        "representative_candidate_id": family["representative_candidate_id"],
        "source_ancestry_ids": family.get("source_ancestry_ids", []),
        "panels": family.get("panels", []),
        "games": len(rows),
        "independent_seeds": len({int(row["requested_seed"]) for row in rows}),
        "wins": len(wins),
        "draws": sum(row["result"] == "draw" for row in rows),
        "losses": len(losses),
        "strict_win_rate": mean(float(row["result"] == "win") for row in rows),
        "win_score": mean(float(row["win_score"]) for row in rows),
        "strict_win_rate_ci": seed_cluster_bootstrap(
            rows,
            lambda row: float(row["result"] == "win"),
            bootstrap_seed=bootstrap_seed,
        ),
        "win_score_ci": seed_cluster_bootstrap(
            rows,
            lambda row: float(row["win_score"]),
            bootstrap_seed=bootstrap_seed + 1,
        ),
        "mean_champion_coin": mean(float(row["champion_coin"]) for row in rows),
        "mean_opponent_coin": mean(float(row["opponent_coin"]) for row in rows),
        "mean_relative_margin": mean(float(row["relative_margin"]) for row in rows),
        "minimum_margin": min(float(row["relative_margin"]) for row in rows),
        "p10_margin": _quantile([float(row["relative_margin"]) for row in rows], 0.10),
        "seat_breakdown": by_seat,
        "seat_win_score_gap_seat0_minus_seat1": (
            by_seat["0"]["win_score"] - by_seat["1"]["win_score"]
        ),
        "day_margin_and_reversal": checkpoint_summary,
        "lead_to_loss_any_major_checkpoint": sum(
            row["result"] == "loss"
            and any(
                float(row["diagnostics"]["checkpoint_states"][str(step)]["cash_margin"])
                > 0
                for step in DAY_MARGIN_CHECKPOINTS
            )
            for row in rows
        ),
        "behind_to_win_any_major_checkpoint": sum(
            row["result"] == "win"
            and any(
                float(row["diagnostics"]["checkpoint_states"][str(step)]["cash_margin"])
                < 0
                for step in DAY_MARGIN_CHECKPOINTS
            )
            for row in rows
        ),
        "terminal_shop_regimes": dict(sorted(terminal_shops.items())),
        "mean_terminal_market_inventory_delta": market_inventory,
        "mean_terminal_market_price_delta": market_prices,
        "mean_terminal_market_inventory_l1": mean(
            float(row["diagnostics"]["terminal_market_displacement"]["inventory_l1"])
            for row in rows
        ),
        "mean_terminal_market_price_l1": mean(
            float(row["diagnostics"]["terminal_market_displacement"]["price_l1"])
            for row in rows
        ),
        "mean_v111_action_utilization": mean(
            float(row["diagnostics"]["champion_action_profile"]["action_utilization"])
            for row in rows
        ),
        "mean_opponent_action_utilization": mean(
            float(row["diagnostics"]["opponent_action_profile"]["action_utilization"])
            for row in rows
        ),
        "mean_v111_market_quantity": _mean_mapping(
            [
                row["diagnostics"]["champion_action_profile"]["market_item_quantity"]
                for row in rows
            ]
        ),
        "mean_opponent_market_quantity": _mean_mapping(
            [
                row["diagnostics"]["opponent_action_profile"]["market_item_quantity"]
                for row in rows
            ]
        ),
        "loss_cases": [
            {
                "seed": row["requested_seed"],
                "champion_seat": row["champion_seat"],
                "margin": row["relative_margin"],
                "day_cash_margins": {
                    str(step): row["diagnostics"]["checkpoint_states"][str(step)]["cash_margin"]
                    for step in DAY_MARGIN_CHECKPOINTS
                },
            }
            for row in losses
        ],
    }


def validate_complete_games(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": row["candidate_id"],
            "seed": row["requested_seed"],
            "champion_seat": row["champion_seat"],
            "statuses": row["final_statuses"],
        }
        for row in rows
        if row["final_statuses"] != ["DONE", "DONE"]
    ]
