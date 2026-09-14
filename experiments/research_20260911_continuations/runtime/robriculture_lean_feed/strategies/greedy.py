"""Greedy economic maximizer (STUB).

Philosophy: at every decision, do the thing with the best immediate
profit-per-tile-per-day, subject to survival (everything watered/fed first).
Plant the highest-ROI crop we can afford; sell into the best available price;
expand land/labor only when payback fits the remaining horizon.

This is the first "real" strategy to flesh out (ADR-0002). For now it falls back
to the lean baseline so it is submittable and non-crashing from day one.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies.lean import LeanStrategy


class GreedyStrategy(Strategy):
    name = "greedy"

    def __init__(self):
        self._fallback = LeanStrategy()

    def act(self, obs) -> dict:
        # TODO: ROI-ranked planting, market-aware selling, land/labor logic.
        return self._fallback.act(obs)


STRATEGY = GreedyStrategy
