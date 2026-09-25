from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_round6_anchors.py"
SPEC = importlib.util.spec_from_file_location("round6_anchor_eval", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_preregistered_development_and_final_seeds_are_disjoint() -> None:
    data = json.loads(MODULE.PREREGISTRATION.read_text(encoding="utf-8"))
    development = data["development"]["seeds"]
    final = data["final_confirmation"]["seeds"]
    assert len(development) == 8
    assert len(final) == 32
    assert not set(development) & set(final)
    assert data["final_confirmation"]["status"] == "SEALED_NOT_RUN"


def test_seed_block_summary_keeps_both_seats_together() -> None:
    rows = []
    for anchor in ("v122", "v123", "v124"):
        for seed, scores in ((1, (1.0, 0.0)), (2, (1.0, 1.0))):
            for seat, score in enumerate(scores):
                rows.append(
                    {
                        "arm": "candidate",
                        "anchor": anchor,
                        "seed": seed,
                        "seat": seat,
                        "score": score,
                        "margin": 1 if score else -1,
                        "our_cash": 10,
                        "opponent_cash": 9,
                        "statuses": "DONE/DONE",
                    }
                )
    prereg = json.loads(MODULE.PREREGISTRATION.read_text(encoding="utf-8"))
    prereg["statistics"]["bootstrap_draws"] = 100
    summary = MODULE._summary(rows, prereg)["arms"]["candidate"]
    assert summary["p_internal_equal_anchor_weight"] == 0.75
    for row in summary["by_anchor"].values():
        assert row["seed_blocks"] == 2
        assert row["seed_block_scores"] == {"1": 0.5, "2": 1.0}


def test_hoeffding_lower_is_conservative_and_nonnegative() -> None:
    assert MODULE._hoeffding_lower(1.0, 8) < 1.0
    assert MODULE._hoeffding_lower(0.2, 8) == 0.0


def test_degenerate_all_loss_interval_does_not_claim_zero_uncertainty() -> None:
    interval = MODULE._hoeffding_interval(0.0, 8)
    assert interval[0] == 0.0
    assert 0.4 < interval[1] < 0.5


def test_final_stage_requires_a_separate_freeze_action() -> None:
    try:
        MODULE.evaluate("final", "round6_full_action_bc", 1)
    except RuntimeError as exc:
        assert "sealed" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("sealed final seeds were opened")
