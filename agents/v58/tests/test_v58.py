from agents.v58 import main as v58


def test_model_is_available_and_schema_matches() -> None:
    assert v58.MODEL is not None
    assert v58.MODEL["format"] == v58.MODEL_FORMAT
    assert "same_role_transition_rate" in v58.MODEL["labels"]


def test_role_classification() -> None:
    assert v58._task_role({"label": "feed", "action": ["FEED"]}) == "ANIMAL"
    assert v58._task_role({"label": "plant-WHEAT", "action": ["PLANT", "WHEAT"]}) == "CROP"
    assert v58._task_role({"label": "pickup-wheat", "action": ["PICKUP", "WHEAT", 2]}) is None


def test_role_scope_can_exclude_crop() -> None:
    old_types = v58.ROLE_TYPES
    v58.ROLE_TYPES = {"ANIMAL"}
    try:
        assert "CROP" not in v58.ROLE_TYPES
        assert "ANIMAL" in v58.ROLE_TYPES
    finally:
        v58.ROLE_TYPES = old_types


def test_disabled_invalid_observation_falls_back() -> None:
    v58.ENABLE_ROLE_CONTINUITY = False
    assert v58.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}
