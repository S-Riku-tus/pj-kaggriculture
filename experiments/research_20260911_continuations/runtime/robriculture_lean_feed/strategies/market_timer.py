"""Market-timing specialist (STUB).

Philosophy: treat the price curve as the primary battlefield. Premium goods
(strawberry, melon, milk, wool) crash to the $1 floor on modest gluts, so this
strategy deliberately paces production and bundles/times sales into town-demand
windows to keep realized prices high — potentially underproducing on purpose.
A different lens from raw ROI (ADR-0003).

Falls back to lean until implemented.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies.lean import LeanStrategy


class MarketTimerStrategy(Strategy):
    name = "market_timer"

    def __init__(self):
        self._fallback = LeanStrategy()

    def act(self, obs) -> dict:
        # TODO: model price impact of our own sells; time sales to demand ticks.
        return self._fallback.act(obs)


STRATEGY = MarketTimerStrategy
