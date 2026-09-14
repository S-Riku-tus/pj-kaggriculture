"""Short-horizon rollout planner (STUB).

Philosophy: the dynamics are largely deterministic (weeds + shop unlocks are the
main randomness), so simulate a few days forward and choose actions by rollout.
Includes a daily labor/route assignment sub-problem (which hand does what where)
and a market-timing sub-model (how much to sell now vs later against the price
curve). This is where most of the strategic edge is expected to live.

Falls back to lean until implemented.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies.lean import LeanStrategy


class PlannerStrategy(Strategy):
    name = "planner"

    def __init__(self):
        self._fallback = LeanStrategy()

    def act(self, obs) -> dict:
        # TODO: forward-simulate, score rollouts, pick best action set.
        return self._fallback.act(obs)


STRATEGY = PlannerStrategy
