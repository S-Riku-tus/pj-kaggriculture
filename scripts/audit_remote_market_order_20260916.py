"""Measure the immediate effect of active-submission market-order reordering.

The active public replay and local V111 emit the same farmer/hand actions and
the same market-order multiset in the audited mismatches.  Because the engine
processes market slots sequentially, this script replays each differing turn
twice from the same factual pre-action state: once with the factual remote
order and once with V111's order.  Opponent actions are held factual, so the
result is a one-turn mechanism audit, not a closed-loop score estimate.
"""

from __future__ import annotations

import copy
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluation import safety  # noqa: E402
from scripts.evaluation.replay import action, canonical_action, observation  # noqa: E402
from scripts.evaluation.runner import _call, _import_module  # noqa: E402

DATA = ROOT / "data/current_field_20260915"
SUBMISSION = DATA / "submissions/current_our_20260915_submission_56089444"
OUT = ROOT / "data/analysis/research_20260916_next_strategy/remote_market_order_audit.json"


def _market_multiset(value: dict[str, Any]) -> Counter[tuple[Any, ...]]:
    return Counter(tuple(row) for row in (value.get("market") or []))


def _simulate(
    replay: dict[str, Any], step: int, actions: list[dict[str, Any]]
) -> dict[str, Any]:
    observations = [observation(replay, step, seat) or {} for seat in (0, 1)]
    farms = copy.deepcopy(list(observations[0].get("farms") or [{}, {}]))
    privates = [copy.deepcopy(obs.get("private") or {}) for obs in observations]
    market = copy.deepcopy(observations[0].get("market") or {})
    day = int(observations[0].get("day", step // 24) or 0)
    field_events = safety._apply_fields(farms, privates, actions, day)
    market_events = safety._simulate_market(farms, privates, market, actions)
    return {
        "money": [float(farm.get("money", 0.0) or 0.0) for farm in farms],
        "market_inventory": dict(market.get("inventory") or {}),
        "private_shed": [dict(private.get("shed") or {}) for private in privates],
        "field_events": field_events,
        "market_events": market_events,
    }


def main() -> None:
    with (SUBMISSION / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        manifest = list(csv.DictReader(handle))
    rows: list[dict[str, Any]] = []
    for index, source in enumerate(manifest):
        replay_path = DATA / source["replay_path"]
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        seat = int(source["submission_seat"])
        module = _import_module(ROOT / "agents/v111/main.py", f"order_audit_v111_{index}")
        for step in range(719):
            remote = action(replay, step, seat)
            local = _call(module.agent, observation(replay, step, seat), None)
            if canonical_action(remote) == canonical_action(local):
                continue
            if remote.get("farmer") != local.get("farmer") or remote.get("hands") != local.get("hands"):
                raise AssertionError((source["episode_id"], step, "non-market mismatch"))
            if _market_multiset(remote) != _market_multiset(local):
                raise AssertionError((source["episode_id"], step, "market multiset mismatch"))
            factual_actions = [action(replay, step, player) for player in (0, 1)]
            local_actions = copy.deepcopy(factual_actions)
            local_actions[seat] = local
            factual = _simulate(replay, step, factual_actions)
            altered = _simulate(replay, step, local_actions)
            rows.append(
                {
                    "episode_id": int(source["episode_id"]),
                    "seat": seat,
                    "step": step,
                    "remote_market": remote.get("market") or [],
                    "local_v111_market": local.get("market") or [],
                    "opponent_market": factual_actions[1 - seat].get("market") or [],
                    "money_delta_local_minus_remote": [
                        altered["money"][player] - factual["money"][player]
                        for player in (0, 1)
                    ],
                    "market_inventory_equal": (
                        altered["market_inventory"] == factual["market_inventory"]
                    ),
                    "private_shed_equal": altered["private_shed"] == factual["private_shed"],
                    "factual_market_events": factual["market_events"],
                    "local_market_events": altered["market_events"],
                }
            )
    focal_deltas = [row["money_delta_local_minus_remote"][row["seat"]] for row in rows]
    opponent_deltas = [row["money_delta_local_minus_remote"][1 - row["seat"]] for row in rows]
    summary = {
        "mismatch_turns": len(rows),
        "nonzero_focal_cash_effect_turns": sum(delta != 0 for delta in focal_deltas),
        "focal_cash_delta_sum": sum(focal_deltas),
        "focal_cash_delta_min": min(focal_deltas, default=0),
        "focal_cash_delta_max": max(focal_deltas, default=0),
        "nonzero_opponent_cash_effect_turns": sum(delta != 0 for delta in opponent_deltas),
        "opponent_cash_delta_sum": sum(opponent_deltas),
        "all_market_inventory_equal": all(row["market_inventory_equal"] for row in rows),
        "all_private_shed_equal": all(row["private_shed_equal"] for row in rows),
        "scope": (
            "One-turn intervention with the factual opponent action held fixed; not a closed-loop "
            "counterfactual, rating estimate, or remote archive authentication."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
