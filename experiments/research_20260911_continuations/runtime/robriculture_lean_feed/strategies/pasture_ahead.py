# strategies/pasture_ahead.py
"""Keep pasture standing ahead of the herd, from day 0 (#237).

#234 decomposed `lonespear_kaggriculture_v21` against our champion and found
the livestock line capped by **head-days, not prices**: we realise the same
%-of-base as it does on milk, wool and fertilizer and earn 41,285 to its
88,888 on units alone. The measured cause is placement -- our 5th pasture
tile arrives on day 12 against its day 0, we never exceed 8 tiles for 12 head
bought, and bought head sits unplaced in the shed on 482 of 719 turns (67%)
against its 30 (4%). Two thirds of our waiting turns have no free pasture at
all, so the shortage is tiles, not herders.

One decision changes: `pasture_count` keeps ``placed head + LEAD`` tiles in
play instead of the ramp-derived count, from day 0, through the seam on the
frozen benchmark (#181, #202, #219). The rule only ever ADDS pasture -- it is
a `max` against the benchmark's own count, never a cap on it -- and the
shed-adjacent tile order is untouched. Crop caps, ramps, sells, land, feed,
the hire schedule and #219's cow rule are `rival_aware`'s, unchanged.

The base is `rival_aware`, the champion, not `dense_farm`: the head-to-head
that gates this experiment is against `rival_aware`, so building on anything
else would confound the pasture rule with #219's cow rule.

Declared before measurement: `LEAD`, and the criterion in
`harness/pasture_bench.py` (posted to #237 before the criterion ran).
"""

from __future__ import annotations

from strategies import field_rival as fr
from strategies.rival_aware import RivalAwareStrategy

#: How many empty pastures to keep standing ahead of the head already placed.
#: `lonespear_v21`'s own rule, read off its board in #234: it holds 14 tiles
#: for 14 head and never waits more than a pickup. Three is the smallest lead
#: that covers a herder's round trip to the shed on both livestock workers at
#: once. Declared in #237 before any measurement.
LEAD = 3


class PastureAheadStrategy(RivalAwareStrategy):
    """`rival_aware` that builds pasture to placed head + `LEAD_TILES`."""

    name = "pasture_ahead"
    benchmark = False

    #: Class attribute so a test can read the declared constant off the agent
    #: itself, in the shape #219's THRESHOLD and #225's DAY already use.
    LEAD_TILES = LEAD

    def pasture_count(self, day, animals):
        """Tiles to keep in play: the lead ahead of placed head, never fewer
        than the benchmark's own ramp and never more than the pasture block.

        `animals` is the placed count, so `animals + LEAD_TILES` already
        dominates the benchmark's "never fewer than the head standing" term --
        the `max` against `animal_target(day)` is what keeps the rule from
        ever building LESS than the frozen ramp would.
        """
        return min(len(fr.PASTURE_TILES),
                   max(animals + self.LEAD_TILES, fr.animal_target(day)))


STRATEGY = PastureAheadStrategy
