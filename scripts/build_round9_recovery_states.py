"""Persist learner-state recovery examples without calling a tournament agent as oracle.

These examples are diagnostics only.  Labels are one-step local-search results checked
against the pinned engine helpers; they are not silently appended to A2 training data.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/round9_teacher_reproduction_and_closed_loop_bc_20260923"
REPLAY = EXP / "trajectory_t1_t2_t3_v2/a2_seed20260924_t3_replay.json.gz"
OUT = EXP / "recovery_states_v1"

from audit_round9_economy import apply_actors, process_market  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def focal_observation(step: list[dict], seat: int = 0) -> dict:
    value = copy.deepcopy(step[0]["observation"])
    value["player"] = seat
    value["private"] = copy.deepcopy(step[seat]["observation"]["private"])
    return value


def market_trial(step: list[dict], order: list) -> dict:
    obs = focal_observation(step)
    farms = copy.deepcopy(obs["farms"])
    privates = [copy.deepcopy(side["observation"]["private"]) for side in step]
    actions = [
        {"farmer": ["PASS"], "hands": [["PASS"] for _ in farms[0]["hands"]], "market": [order]},
        {"farmer": ["PASS"], "hands": [["PASS"] for _ in farms[1]["hands"]], "market": []},
    ]
    before = {"cash": farms[0]["money"], "private": copy.deepcopy(privates[0])}
    process_market(
        farms,
        privates,
        copy.deepcopy(obs["market"]),
        actions,
        {"maxMarketOrdersPerTurn": 10, "farmHandCostMult": 1, "shedCapacity": 100},
    )
    after = {"cash": farms[0]["money"], "private": copy.deepcopy(privates[0])}
    return {"before": before, "after": after, "changed": before != after}


def actor_move_trial(step: list[dict], operation: str) -> dict:
    obs = focal_observation(step)
    farms = copy.deepcopy(obs["farms"])
    privates = [copy.deepcopy(side["observation"]["private"]) for side in step]
    before = copy.deepcopy(farms[0]["farmer"])
    actions = [
        {"farmer": [operation], "hands": [["PASS"] for _ in farms[0]["hands"]], "market": []},
        {"farmer": ["PASS"], "hands": [["PASS"] for _ in farms[1]["hands"]], "market": []},
    ]
    apply_actors(farms, privates, actions, int(obs["step"]))
    after = copy.deepcopy(farms[0]["farmer"])
    shed_access = ((4, 4), (5, 4), (4, 5), (5, 5))

    def distance(pos: list[int]) -> int:
        return min(abs(pos[0] - row) + abs(pos[1] - col) for row, col in shed_access)

    return {
        "before_position": before,
        "after_position": after,
        "before_distance_to_shed_access": distance(before),
        "after_distance_to_shed_access": distance(after),
        "changed": before != after,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(REPLAY, "rt", encoding="utf-8") as stream:
        replay = json.load(stream)

    selected = {
        24: "day_boundary_actor_slot_change",
        61: "first_observed_work_failure_context",
        96: "seed_shortage_with_saleable_stock",
        192: "zero_cash_reinvestment_stall",
        319: "carried_goods_far_from_shed",
        718: "last_executable_liquidation_window",
    }
    snapshots = []
    for record, category in selected.items():
        obs = focal_observation(replay["steps"][record])
        snapshots.append(
            {
                "record_index": record,
                "category": category,
                "observation": obs,
                "learner_action": replay["steps"][record + 1][0].get("action") if record < 719 else None,
            }
        )

    state_path = OUT / "states.json.gz"
    with gzip.open(state_path, "wt", encoding="utf-8") as stream:
        json.dump(snapshots, stream, ensure_ascii=False, separators=(",", ":"))

    labels = [
        {
            "record_index": 192,
            "category": selected[192],
            "label": {"market": [["SELL", "WHEAT", 13]]},
            "source_label_kind": "search",
            "search_scope": "one-step, focal market order, opponent market empty, no future state/action",
            "validation": market_trial(replay["steps"][192], ["SELL", "WHEAT", 13]),
        },
        {
            "record_index": 319,
            "category": selected[319],
            "label": {"actor_index": 0, "action": ["EAST"]},
            "source_label_kind": "search",
            "search_scope": "one-step legal movement minimizing Manhattan distance to a shed access tile",
            "validation": actor_move_trial(replay["steps"][319], "EAST"),
        },
        {
            "record_index": 718,
            "category": selected[718],
            "label": {"market": [["SELL", "MELON", 5]]},
            "source_label_kind": "search",
            "search_scope": "last executable one-step liquidation, opponent market empty, no future state/action",
            "validation": market_trial(replay["steps"][718], ["SELL", "MELON", 5]),
        },
    ]
    for label in labels:
        label["validated_effect"] = bool(label["validation"]["changed"])

    manifest = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "classification": "RECOVERY_LABEL_DIAGNOSTIC_NOT_TRAINED_NOT_DAGGER",
        "source_replay": str(REPLAY.relative_to(ROOT)),
        "source_replay_sha256": sha256(REPLAY),
        "states": str(state_path.relative_to(ROOT)),
        "states_sha256": sha256(state_path),
        "snapshot_count": len(snapshots),
        "validated_local_labels": labels,
        "unlabeled_categories": [
            {
                "record_index": 24,
                "category": selected[24],
                "reason": (
                    "no trusted day-level objective label was established; "
                    "a stale original-teacher time label was not copied"
                ),
            },
            {
                "record_index": 61,
                "category": selected[61],
                "reason": (
                    "the failed work is documented, but a one-step alternative does not establish "
                    "task ownership/completion"
                ),
            },
            {
                "record_index": 96,
                "category": selected[96],
                "reason": (
                    "buy-versus-sell-versus-harvest requires a multi-step economic objective; "
                    "no unverified self-label was used"
                ),
            },
        ],
        "added_to_a2_training_rows": 0,
        "dagger_claim": False,
        "private_or_future_opponent_input_used": False,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot_count": len(snapshots), "labels": labels}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
