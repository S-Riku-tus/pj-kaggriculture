"""Capital-rush build (STUB).

Philosophy: bias hard toward compounding assets early — buy neighboring
quadrants and stand up animals (indefinite production + free fertilizer) as fast
as cash flow safely allows, betting that a bigger productive base wins the back
half of the 30-day season. Deliberately different risk profile from greedy, to
probe a different region of strategy space (ADR-0003).

Falls back to lean until implemented.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies.lean import LeanStrategy


class CapitalRushStrategy(Strategy):
    name = "capital_rush"

    def __init__(self):
        self._fallback = LeanStrategy()

    def act(self, obs) -> dict:
        # TODO: horizon-aware land/animal investment schedule.
        return self._fallback.act(obs)


STRATEGY = CapitalRushStrategy
