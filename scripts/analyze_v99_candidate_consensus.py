"""Run the V99 V14-consensus gate analysis without replacing the V91 artifact."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import analyze_v91_full_candidate_holdout as analysis


if __name__ == "__main__":
    analysis.OUTPUT = analysis.ROOT / "data/analysis/v99_candidate_consensus.json"
    analysis.ANALYSIS_FORMAT = "kaggriculture-v99-candidate-consensus-v1"
    analysis.main()
