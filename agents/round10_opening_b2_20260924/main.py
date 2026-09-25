"""Round10 B2: Herd-safe B1 with an isolated step-0 10->5 Wheat round trip."""

from base_main import opening_liquidity_agent as _base_agent

OPENING = (
    ("BUY_PRODUCT", "WHEAT", 10),
    ("SELL", "WHEAT", 5),
    ("BUY_SEED", "WHEAT", 1),
)


def agent(observation):
    action = _base_agent(observation)
    if int(observation.get("step", 0) or 0) == 0:
        action = {
            "farmer": list(action.get("farmer") or ["PASS"]),
            "hands": [list(value) for value in (action.get("hands") or [])],
            "market": [list(value) for value in OPENING],
        }
    return action
