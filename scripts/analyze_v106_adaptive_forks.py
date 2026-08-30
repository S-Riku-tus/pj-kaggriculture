"""Diagnose positive and negative V106 adaptive replay-fork paths."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v106 import main as v106  # noqa: E402

RUN = ROOT / "data/runs/v106_recent_adaptive_replay_forks.json"
OUTPUT = ROOT / "data/analysis/v106_adaptive_fork_diagnosis.json"


def _first_divergence(
    safe: dict[str, Any], candidate: dict[str, Any], seat: int
) -> dict[str, Any] | None:
    for index, (safe_states, candidate_states) in enumerate(
        zip(safe.get("steps") or [], candidate.get("steps") or [], strict=True)
    ):
        safe_action = safe_states[seat].get("action")
        candidate_action = candidate_states[seat].get("action")
        if safe_action != candidate_action:
            obs = candidate_states[seat].get("observation") or {}
            return {
                "state_index": index,
                "day": int(obs.get("day", 0) or 0),
                "hour": int(obs.get("hour", 0) or 0),
                "safe_action": safe_action,
                "candidate_action": candidate_action,
            }
    return None


def _context(obs: dict[str, Any]) -> dict[str, Any]:
    safe = v106.base._safe_observation(obs)
    if safe is None:
        return {}
    farm, opponent_farm, private = safe
    summary = v106.base._farm_summary(farm)
    opponent = v106.base._farm_summary(opponent_farm)
    shed = v106.base._get(private, "shed", {}) or {}
    seeds = v106.base._get(private, "seeds", {}) or {}
    inventories = v106.base._get(private, "inventories", []) or []
    carried_wheat = sum(v106.base._inventory_count(value, "WHEAT") for value in inventories)
    decision = v106.v102._gate_decision(obs, farm, opponent_farm, private)
    baseline = decision["baseline"]
    candidate_crops = decision.get("candidate_crops", baseline[1])
    return {
        "money": float(v106.base._get(farm, "money", 0) or 0),
        "opponent_money": float(v106.base._get(opponent_farm, "money", 0) or 0),
        "productive": int(summary["productive"]),
        "opponent_productive": int(opponent["productive"]),
        "crops": {crop: int(summary["crops"].get(crop, 0)) for crop in v106.v14.CROPS},
        "animals": {
            animal: int(summary["animals"].get(animal, 0))
            for animal in ("COW", "SHEEP", "GOOSE")
        },
        "shed_wheat": v106.base._inventory_count(shed, "WHEAT"),
        "carried_wheat": carried_wheat,
        "wheat_seeds": v106.base._inventory_count(seeds, "WHEAT"),
        "strawberry_seeds": v106.base._inventory_count(seeds, "STRAWBERRY"),
        "demand": v106.base._demand_profile(obs),
        "gate": {
            "confidence": decision.get("confidence"),
            "uncertainty_ratio": decision.get("uncertainty_ratio"),
            "money_gap_ratio": (decision.get("prediction") or {}).get("money_gap_ratio"),
            "normalized_change": decision.get("normalized_change"),
            "crop_delta": {
                crop: int(candidate_crops[crop]) - int(baseline[1][crop])
                for crop in v106.v14.CROPS
            },
        },
    }


def main() -> None:
    payload = json.loads(RUN.read_text(encoding="utf-8"))
    records = []
    for pair in payload["paired_diagnostics"]:
        episode_id = str(pair["episode_id"])
        safe_game = next(
            game
            for game in payload["games"]
            if str(game["episode_id"]) == episode_id and game["mode"] == "safe-core"
        )
        candidate_game = next(
            game
            for game in payload["games"]
            if str(game["episode_id"]) == episode_id and game["mode"] == "candidate"
        )
        safe_replay = json.loads((ROOT / safe_game["replay"]).read_text(encoding="utf-8"))
        candidate_replay = json.loads((ROOT / candidate_game["replay"]).read_text(encoding="utf-8"))
        seat = int(candidate_game["seat"])
        fork_step = int(pair["fork_day"]) * 24
        obs = candidate_replay["steps"][fork_step][seat].get("observation") or {}
        records.append(
            {
                "source": pair["source"],
                "episode_id": episode_id,
                "fork_day": pair["fork_day"],
                "reward_delta_context": pair["reward_delta_context"],
                "margin_delta_context": pair["margin_delta_context"],
                "day15_productive_delta": pair["day15_productive_delta"],
                "day20_productive_delta": pair["day20_productive_delta"],
                "entry": _context(obs),
                "first_divergence": _first_divergence(safe_replay, candidate_replay, seat),
            }
        )
    result = {
        "format": "kaggriculture-v106-adaptive-fork-diagnosis-v1",
        "input": str(RUN.relative_to(ROOT)),
        "records": records,
        "limits": [
            "the eight recent states were already used in V102-V106 development",
            "the adaptive opponent starts with cold mission memory at the fork",
            "associations in this report are hypotheses, not causal gate proof",
        ],
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = [
        {
            "episode_id": record["episode_id"],
            "reward_delta": record["reward_delta_context"],
            "margin_delta": record["margin_delta_context"],
            "money": record["entry"]["money"],
            "opponent_money": record["entry"]["opponent_money"],
            "productive": record["entry"]["productive"],
            "animals": record["entry"]["animals"],
            "shed_wheat": record["entry"]["shed_wheat"],
            "carried_wheat": record["entry"]["carried_wheat"],
            "crop_delta": record["entry"]["gate"]["crop_delta"],
            "first_divergence": record["first_divergence"],
        }
        for record in records
    ]
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    print(f"result: {OUTPUT}")


if __name__ == "__main__":
    main()
