"""dusk_floor: herd_first with a turn-wide spend floor on land, seed and herd (#258).

#254's `herd_first` beat `third_herder` 14/16 and lost the field because a zero
reserve fires the crew at dusk: the sim clears the hands every night and
re-hires at dawn on the wage ladder, and the herd block, which runs on every
hour, spent every coin before dawn. #256 put dawn's wages and the herd's feed
behind `capital_reserve` and VOIDed on the same crew bar -- that reserve is a
floor inside the herd block only, and under herd_first's order the land and
seed blocks run after the herd and spend it.

One decision changes: the same quantity -- tomorrow's wage bill plus the feed
the herd is short of, at the price the feed block will pay -- goes behind the
`spend_floor` seam (#258), which land, seed and the herd all respect and hires
and the feed block are exempt from. The buy order, `field_pace`'s eight knobs
and `third_herder`'s rules are inherited unchanged; the herd's own reserve
stays 0.

Declared before measurement: `feed_shortfall_cost`, the floor, and the controls
and criterion in `harness/floor_bench.py` (posted to #258 before any code).
"""

from __future__ import annotations

from kaggisim import economy
from strategies import field_rival as fr
from strategies.dawn_reserve import wage_bill
from strategies.herd_first import HerdFirstStrategy

#: Wheat's anchor price: what the feed leg is priced at before the market is read.
WHEAT_BASE = economy.MARKET_PARAMS["WHEAT"]["base"]


def feed_shortfall_cost(animals: int, shed: dict, prices: dict) -> int:
    """What the feed block will spend to top the shed up to `feed_buffer` for
    `animals` head, at today's wheat price: the shortfall, not the buffer --
    the sell sweep already keeps the buffer, so most days this is 0."""
    short = max(0, fr.feed_buffer(animals) - int(shed.get("WHEAT", 0)))
    return short * int(prices.get("WHEAT", WHEAT_BASE))


class DuskFloorStrategy(HerdFirstStrategy):
    """`herd_first` that leaves dawn's needs unspent, whatever block is spending."""

    name = "dusk_floor"
    benchmark = False

    def spend_floor(self, day=None, animals=None, shed=None, prices=None):
        """Tomorrow's wage bill plus today's feed shortfall. A bare call (no day,
        no head, no shed, no prices) answers for the season's opening crew."""
        crew = self.hire_target(0 if day is None else day + 1)
        return wage_bill(crew) + feed_shortfall_cost(animals or 0, shed or {}, prices or {})


STRATEGY = DuskFloorStrategy
