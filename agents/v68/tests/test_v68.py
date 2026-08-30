from agents.v68 import main as v68


def test_tolerance_is_two_mae_band() -> None:
    assert v68.MAX_PREDICTED_MONEY_GAP_DECLINE == 0.464
    assert v68.v67.MAX_PREDICTED_MONEY_GAP_DECLINE == 0.464


def test_relative_gate_and_late_days_remain_installed() -> None:
    assert v68.v58._predict is v68.v67._relative_predict
    assert v68.v58.ACTIVE_DAYS == (11, 12)
    assert v68.v58.ENABLE_ROLE_CONTINUITY is True
