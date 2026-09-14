"""Price discipline as a wrapper: never sell a unit below `min_frac` of its base
price; hold the rest in the shed (#172 Stage 1).

The wrapper is the knob the rollout objective is asked to rank. It edits SELL
quantities only, using the sim's own price curve through
`kaggisim.pricing.sell_quantity`, so it works on any strategy and leaves the
frozen benchmark (`field_rival`, #181) and the champion byte-for-byte alone.
`min_frac = 0.0` is the identity — the positive control.

Deliberately NOT registered: no module-level ``STRATEGY``, so the
auto-discovery in ``strategies/__init__.py`` skips this file (the same choice
as ``strategies/ghost.py``). It has no behaviour without an inner strategy.
"""

from __future__ import annotations

from kaggisim.economy import MARKET_PARAMS
from kaggisim.pricing import sell_quantity
from kaggisim.strategy import Strategy


def cap_sells(orders: list, market_inventory: dict, min_frac: float) -> list:
    """`orders` with every SELL capped to the units that still clear
    `min_frac * base`; a SELL capped to zero is dropped (a dead order burns one
    of the ten slots). Non-SELL orders and order positions are untouched.
    Two SELLs of one item in the same turn share the cap: the second is priced
    at the inventory the first will have pushed up."""
    sold: dict = {}
    out = []
    for order in orders:
        if not (order and order[0] == "SELL" and len(order) >= 3 and order[1] in MARKET_PARAMS):
            out.append(order)
            continue
        item, have = order[1], int(order[2])
        params = MARKET_PARAMS[item]
        inventory = market_inventory.get(item, params["I0"]) + sold.get(item, 0)
        n = sell_quantity(item, inventory, have, min_frac * params["base"])
        if n > 0:
            out.append(["SELL", item, n])
            sold[item] = sold.get(item, 0) + n
    return out


class SellDiscipline(Strategy):
    """`inner` with its SELL orders capped by `min_frac` (see `cap_sells`)."""

    benchmark = False

    def __init__(self, inner: Strategy, min_frac: float):
        self.inner = inner
        self.min_frac = float(min_frac)
        self.name = f"{inner.name}@{self.min_frac:.1f}"

    def act(self, obs) -> dict:
        action = self.inner.act(obs)
        inventory = obs.get("market", {}).get("inventory", {})
        return {
            "farmer": action.get("farmer"),
            "hands": action.get("hands", []),
            "market": cap_sells(action.get("market", []), inventory, self.min_frac),
        }

    def reset(self) -> None:
        self.inner.reset()
