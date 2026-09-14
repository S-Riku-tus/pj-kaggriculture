"""lean_feed: herd_first with feed sized to the herd (#262).

#260 measured the cash flow of the three schedule contenders on seed 944.
Every one ends day 0 at 15: 12 on hires, 800-880 on seed, 1,900 on three
sheep and a cow, and 395-664 on feed -- three herders filling eight-wheat
pockets (`FEED_CARRY`) plus a sixteen-wheat shed buffer (`feed_buffer`, max
of 8 and twice the head) for four head that eat four a day. Days 1-5 the
herd's fertilizer and wheat sales go on refilling them -- wheat bought at
30-33, harvested wheat sold at 25-30 the same day -- and the champion's
melon payday on day 10 is 9,808 from eighteen tiles against 2,505-4,589 from
twelve. The pre-payday economy is break-even and the feed churn is its
largest controllable outflow.

One decision changes: feed is sized to the herd. A herder's shed trip takes
one day's feed for its own tiles (`carry_for`), and the shed keeps one
feeding (`stock_for`), through the two feed seams on the frozen benchmark
(#262). The buy order (#254), `field_pace`'s knobs (#252) and `third_herder`'s
rules are inherited unchanged; the herd's reserve stays 0 and there is no
spend floor.

Declared before measurement: `carry_for`, `stock_for`, and the controls and
criterion in `harness/feed_bench.py` (posted to #262 before any code).
"""

from __future__ import annotations

import math

from strategies import field_rival as fr
from strategies.herd_first import HerdFirstStrategy


def carry_for(animals: int, herders: int) -> int:
    """Wheat one shed trip should take: the herder's share of the head, so one
    trip feeds its own tiles for a day. Never zero -- an empty-handed herder
    walks to the shed and back for nothing."""
    return max(1, math.ceil(animals / max(1, herders)))


def stock_for(animals: int) -> int:
    """Wheat the shed keeps: one feeding for the herd standing today."""
    return max(1, animals)


class LeanFeedStrategy(HerdFirstStrategy):
    """`herd_first` with the feed sized to the herd."""

    name = "lean_feed"
    benchmark = False

    def feed_carry(self, animals=None, herders=None):
        return carry_for(animals or 0, herders or len(fr.LIVESTOCK_WORKERS))

    def feed_stock(self, animals=None):
        return stock_for(animals or 0)


STRATEGY = LeanFeedStrategy
