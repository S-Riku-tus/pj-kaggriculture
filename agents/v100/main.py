"""Kaggriculture V100: conservative V14-consensus candidate ranker."""

from __future__ import annotations

from typing import Any

from agents.v92 import main as v92

# V99 held-out analysis: this gate switched 4.82% of test decisions at 90.44%
# teacher top-1 accuracy. Runtime paired tests remain the promotion criterion.
v92.ENABLE_CANDIDATE_RANKER = True
v92.MIN_SCORE_GAP = 0.16
v92.MAX_BASE_RANK = 3
v92.CANDIDATE_BONUS = 1_600


def reset_runtime_counts() -> None:
    v92.reset_runtime_counts()


def policy_diagnostics(obs: Any) -> dict[str, Any]:
    result = dict(v92.policy_diagnostics(obs))
    result["v100"] = {
        "base": "v14",
        "candidate_ranker": True,
        "minimum_score_gap": v92.MIN_SCORE_GAP,
        "maximum_base_rank": v92.MAX_BASE_RANK,
        "promotion_status": "rejected-after-new-seed-pairs",
    }
    return result


def agent(obs: Any) -> dict[str, Any]:
    return v92.agent(obs)
