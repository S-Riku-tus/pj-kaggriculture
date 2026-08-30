from agents.v55 import main as v55


def test_fixed_buffer_is_one() -> None:
    assert v55.SAFETY_CARRIER_BUFFER == 1
    assert v55.v54.REDUNDANT_CARRIER_BUFFER == 1


def test_disabled_agent_propagates_safe_flag() -> None:
    v55.ENABLE_BUFFERED_SUPPRESSION = False
    result = v55.agent({})
    assert result == {"farmer": ["PASS"], "hands": [], "market": []}
    assert not v55.v54.ENABLE_REDUNDANT_PICKUP_SUPPRESSION
