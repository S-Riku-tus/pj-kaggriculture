from agents.v63 import main as v63


def test_late_gate_configuration() -> None:
    assert v63.v58.ENABLE_ROLE_CONTINUITY is True
    assert v63.v58.ACTIVE_DAYS == (11, 12)
    assert v63.v58.ROLE_TYPES == {"ANIMAL", "CROP"}


def test_model_is_packaged_source_compatible() -> None:
    assert v63.v58.MODEL is not None
    assert v63.v58.MODEL["format"] == v63.v58.MODEL_FORMAT


def test_outside_late_days_falls_back() -> None:
    assert 10 not in v63.v58.ACTIVE_DAYS
    assert 13 not in v63.v58.ACTIVE_DAYS
