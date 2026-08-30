from agents.v67 import main as v67


def test_relative_model_loaded() -> None:
    assert v67.RELATIVE_MODEL is not None
    assert "future72_money_gap_ratio" in v67.RELATIVE_MODEL["labels"]


def test_late_role_configuration() -> None:
    assert v67.v58.ENABLE_ROLE_CONTINUITY is True
    assert v67.v58.ACTIVE_DAYS == (11, 12)
    assert v67.v58.ROLE_TYPES == {"ANIMAL", "CROP"}


def test_relative_predict_is_installed() -> None:
    assert v67.v58._predict is v67._relative_predict


def test_v67_uses_strict_relative_gate() -> None:
    assert v67.MAX_PREDICTED_MONEY_GAP_DECLINE == 0.0
