"""dawn_reserve: herd_first with the cash floor set to tomorrow's wages plus the herd's feed (#256).

#254's `herd_first` beat `third_herder` 14/16 and lost the field (madhur 5/16
against the champion's 11/16). The census said why: the sim clears
`farm["hands"]` every night and re-hires at dawn on the wage ladder (1, 1, 2,
3, 5, 8, 13, 21, 34, 55 -- 143 for ten hands), and with a zero reserve the herd
block, which runs on every hour, spends every coin before dawn: 2-20 in hand,
2-5 hands, the crop line stalled at 11 tiles for six days, no feed wheat
against a strong opponent and head placed 9 -> 3. The buy order was the right
knob; zero reserve is wrong under daily re-hiring -- it fires the crew at dusk.

One decision changes: the herd's cash floor is what dawn will need --
tomorrow's wage bill for the crew the ramp asks for, plus the wheat the feed
block keeps for the herd standing today -- through the `capital_reserve` seam
(#252, #256). The buy order, `field_pace`'s eight knobs and `third_herder`'s
rules are inherited unchanged.

Declared before measurement: `wage_bill`, `feed_cost`, and the controls and
criterion in `harness/reserve_bench.py` (posted to #256 before any code).
"""

from __future__ import annotations

from strategies import field_rival as fr
from strategies import hired_hands as hh
from strategies.herd_first import HerdFirstStrategy


def wage_bill(hands: int) -> int:
    """What dawn charges to hire `hands` in one day: the benchmark's own ladder
    (`hand_wage`, the sim's fib(hires_today) per hire), summed."""
    return sum(hh.hand_wage(k) for k in range(1, hands + 1))


def feed_cost(animals: int) -> int:
    """The wheat the feed block keeps for `animals` head, at the price it
    budgets with -- the same units and the same divisor, so the floor and the
    buy agree."""
    return fr.feed_buffer(animals) * fr.CROPS["WHEAT"]["seed"]


class DawnReserveStrategy(HerdFirstStrategy):
    """`herd_first` that keeps back what dawn will need."""

    name = "dawn_reserve"
    benchmark = False

    def capital_reserve(self, day=None, animals=None):
        """Tomorrow's wage bill plus today's feed; the herd buys from what is
        left. A bare call (no day, no head) answers for the season's opening
        crew and an empty pasture, so the hook's contract holds here too."""
        crew = self.hire_target(0 if day is None else day + 1)
        return wage_bill(crew) + feed_cost(0 if animals is None else animals)


STRATEGY = DawnReserveStrategy
