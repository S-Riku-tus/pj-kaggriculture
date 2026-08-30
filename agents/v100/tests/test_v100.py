from agents.v100 import main as v100


def test_v100_uses_conservative_consensus_gate() -> None:
    assert v100.v92.ENABLE_CANDIDATE_RANKER is True
    assert v100.v92.MIN_SCORE_GAP == 0.16
    assert v100.v92.MAX_BASE_RANK == 3
    assert v100.v92.CANDIDATE_MODEL is not None
    assert v100.v92.OOD_MODEL is not None
