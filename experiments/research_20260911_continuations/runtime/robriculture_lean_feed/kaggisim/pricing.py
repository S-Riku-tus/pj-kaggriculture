"""Market pricing model — so strategies sell and produce PRICE-AWARE.

The realized unit price of a product *falls* as its market inventory rises (you
selling into it) and *rises* as town demand drains it. Every strategy already
receives the live market state in ``obs["market"]`` ({"inventory", "prices"};
see ``kaggisim.state.prices``) — yet our agents historically dumped their whole
shed every turn regardless of price, flooding shallow markets (notably melon,
which floors after ~158 units) to $1.

This module reproduces the sim's ``market_price`` **exactly** — verified against
the installed simulator in ``tests/test_pricing_matches_sim.py`` (the ADR-0002
claim-check pattern) so it can't silently drift — and adds the marginal helpers a
strategy needs to answer "how many should I sell before the price sinks?" and
"which market is worth producing for right now?".

Constants (``PRICE_FLOOR``, the ``_shape`` curves) and the price formula mirror
``kaggle_environments/envs/kaggriculture/kaggriculture.py``.
"""

from __future__ import annotations

import math

from kaggisim import economy
from kaggisim.economy import MARKET_PARAMS, PRICE_FLOOR


#: The curve itself lives in `kaggisim.economy` and is re-exported here, not
#: reimplemented. This module used to carry its own copy of `_shape` and
#: `market_price`; when 1.32.7 added the `hinge` scarcity curve (#195) only one
#: of the two was updated, and the duplicate silently kept pricing carrot,
#: tomato and egg on the old formula. A second source of truth for a value is a
#: drift generator -- one source, cited from both places.
_shape = economy._shape
market_price = economy.market_price


def marginal_revenue(item: str, inventory: float, units: int) -> int:
    """Total coins from selling ``units`` of ``item`` now.

    Per-unit lockstep like the sim: each unit sold raises the inventory by one, so
    later units in the same batch clear lower. ``units <= 0`` yields 0.
    """
    inv = int(inventory)
    return sum(market_price(item, inv + j) for j in range(max(0, int(units))))


def sell_quantity(item: str, inventory: float, have: int, min_price: int) -> int:
    """How many of ``have`` units to sell now while each still clears ``min_price``.

    Price discipline: sell into the market only down to ``min_price`` (e.g. 55–60%
    of base), then hold the rest / move volume elsewhere so a shallow market isn't
    dumped to the floor. Bounded by ``have`` (never searches unbounded), so it is
    cheap to call every turn.
    """
    have = max(0, int(have))
    n = 0
    while n < have and market_price(item, int(inventory) + n) >= min_price:
        n += 1
    return n


def best_market(items, market_inventory, base_frac: float = 0.0):
    """Of ``items``, the one whose *next* unit clears the highest price now, or
    ``None`` if none clears at least ``base_frac`` of its base. Lets a strategy
    steer the next unit of production/sale toward the currently richest market."""
    best, best_price = None, 0
    for item in items:
        inv = market_inventory.get(item, MARKET_PARAMS[item]["I0"])
        price = market_price(item, inv)
        if price >= base_frac * MARKET_PARAMS[item]["base"] and price > best_price:
            best, best_price = item, price
    return best
