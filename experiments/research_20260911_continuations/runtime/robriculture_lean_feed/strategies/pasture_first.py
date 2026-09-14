"""Pasture first: the herd fronted, with the pasture standing before the head.

#237 built pasture ahead of the herd and #239 added a third herder, and the
champion still runs `ANIMAL_RAMP`'s herd: 4 head asked for by day 8, 8 by day
12. The ceiling (#234, `lonespear_v21`) has 14 head placed by day 9 with the
pasture standing before each one arrives. #239's own arm B raised the ramp
with two herders and lost 6/16 -- labour-limited then; #239 removed that
limit, so the ramp question is open again.

One decision changes: `herd_target` reads `FRONT_RAMP` instead of the frozen
ramp, through the seam on the frozen benchmark (#181, #202, #219, #237, #239),
and `pasture_count` reads the *same* ramp for its floor, so pasture stands
for the target before the head is bought rather than for the frozen ramp's
smaller number (`pasture_ahead` reads `fr.animal_target`, which on this arm
would be the wrong ramp). Head is still bought only from surplus above
`CAPITAL_RESERVE`, after seed and the crew: the ramp decides what the farm
wants, cash decides the pace. The third herder from day 8, the pasture lead
of 3, #219's cow rule and the crop caps come from the bases unchanged.

`FRONT_RAMP` tops out at 12 because that is `len(PASTURE_TILES)`, the frozen
shed-adjacent block; a 14-tile herd would be a layout change, a different
decision. Day 6 is the last step so that a farm placing at the ceiling's pace
has every head standing by day 9.

Declared before measurement: `FRONT_RAMP`, and the controls and criterion in
`harness/front_bench.py` (posted to the issue before the criterion ran).
"""

from __future__ import annotations

from strategies import field_rival as fr
from strategies.third_herder import ThirdHerderStrategy

#: Head to be running by day: 4 from day 0, 8 from day 2, the whole block
#: from day 6. Read with the benchmark's own step-table rule (`fr._ramp`), so
#: it differs from `ANIMAL_RAMP` in its numbers and in nothing else.
FRONT_RAMP = ((0, 4), (2, 8), (6, 12))


class PastureFirstStrategy(ThirdHerderStrategy):
    """`third_herder` on `FRONT_RAMP`, with pasture standing for the target."""

    name = "pasture_first"
    benchmark = False

    #: Class attribute so a test can read the declared constant off the agent
    #: itself, in the shape #219's THRESHOLD and #239's HERDER_DAY use.
    FRONT_RAMP = FRONT_RAMP

    def herd_target(self, day):
        """The front ramp, never fewer head than the frozen ramp asks."""
        return max(fr._ramp(self.FRONT_RAMP, day), fr.animal_target(day))

    def pasture_count(self, day, animals):
        """Tiles to keep in play: the lead ahead of placed head, never fewer
        than *this arm's* ramp, never more than the pasture block."""
        return min(len(fr.PASTURE_TILES),
                   max(animals + self.LEAD_TILES, self.herd_target(day)))


STRATEGY = PastureFirstStrategy
