"""Run the generic future-portfolio confirmation on V108's sealed stage 2."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.v108 import main as v108  # noqa: E402
from scripts import evaluate_v107_untouched_top_logs as evaluation  # noqa: E402


def main() -> None:
    evaluation.v107 = v108
    evaluation.OUTPUT = (
        evaluation.ROOT / "data/analysis/v108_untouched_stage2_confirmation.json"
    )
    evaluation.FORMAT = "kaggriculture-v108-untouched-stage2-confirmation-v1"
    evaluation.SOURCES = {
        "untouched_top_1_stage2_55832857": evaluation.ROOT
        / "data/submissions/untouched_top_1_stage2_submission_55832857",
        "untouched_top_2_stage2_55815118": evaluation.ROOT
        / "data/submissions/untouched_top_2_stage2_submission_55815118",
    }
    evaluation.PORTFOLIO = tuple(v108.v14.PORTFOLIO)
    evaluation.BASE_GATE_ATTRIBUTE = "_SAFE_V107_GATE_DECISION"
    evaluation.BASE_ACTIVE_LABEL = "v107_base_active_rows"
    evaluation.REJECTION_LABEL = "v108_rejection_reasons"
    evaluation.SELECTION_PROVENANCE = {
        "rule": "EpisodeService rows 25--40 for the two previously selected strong submissions",
        "selected_before_v108_trigger_inspection": True,
        "skip_episodes": 24,
        "episodes_per_source": 16,
        "disjoint_from_v107_stage1": True,
    }
    evaluation.INTERPRETATION = {
        "fact": "V108 code and its 5000 cash ceiling were frozen before these 32 trajectories were fetched",
        "scope": "future-portfolio fidelity to two strong submitted policies on a second episode-disjoint slice",
        "limit": "this is observational teacher agreement, not a counterfactual reward or rating estimate",
    }
    evaluation.main()


if __name__ == "__main__":
    main()
