"""Lean baseline: a robust wheat loop.

Purpose: the floor of the portfolio. Its only jobs are to (a) never crash and
(b) reliably turn a small profit, so every other strategy has something to beat
and we always have a safe agent to hold a ladder slot. It is intentionally
simple — do NOT grow this into the smart agent; that belongs in greedy/planner.

Loop: keep one wheat plant going next to the shed, water it, harvest it, sell
the wheat. That's it.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy


class LeanStrategy(Strategy):
    name = "lean"

    def act(self, obs) -> dict:
        player = obs["player"]
        me = obs["farms"][player]
        private = obs["private"]
        fx, fy = me["farmer"]
        tile = me["tiles"][fy][fx]
        money = me["money"]

        market = []
        # Buy a wheat seed if we have none and can afford it.
        if private["seeds"].get("WHEAT", 0) == 0 and money >= 10:
            market.append(["BUY_SEED", "WHEAT", 1])
        # Sell any wheat sitting in the shed.
        wheat_in_shed = private["shed"].get("WHEAT", 0)
        if wheat_in_shed > 0:
            market.append(["SELL", "WHEAT", wheat_in_shed])

        # On an empty tile with a seed in hand -> plant.
        if tile is None and private["seeds"].get("WHEAT", 0) > 0:
            return {"farmer": ["PLANT", "WHEAT"], "hands": [], "market": market}

        # On our plant -> harvest when ready, else keep it watered.
        if isinstance(tile, dict) and tile.get("kind") == "PLANT":
            age = obs["day"] - tile["planted_day"]
            if tile.get("yield_units", 0) > 0 and age >= 2:
                return {"farmer": ["HARVEST"], "hands": [], "market": market}
            if not tile.get("watered_today", False):
                return {"farmer": ["WATER"], "hands": [], "market": market}

        return {"farmer": ["PASS"], "hands": [], "market": market}


STRATEGY = LeanStrategy
