from agents.v74 import main as v74


def test_core_late_model_loaded() -> None:
    assert v74.CORE_LATE_MODEL is not None
    assert "future72_money_gap_ratio" in v74.CORE_LATE_MODEL["labels"]


def test_core_late_configuration() -> None:
    assert v74.v58.ACTIVE_DAYS == tuple(range(20, 25))
    assert v74.v58.ENABLE_ROLE_CONTINUITY is True
    assert v74.v67.MAX_PREDICTED_MONEY_GAP_DECLINE == 0.089
