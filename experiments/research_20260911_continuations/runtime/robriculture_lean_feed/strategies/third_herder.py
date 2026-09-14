"""A third herder from day 8, on top of #237's pasture lead (#239).

#237 built pasture ahead of the herd and VOIDed on its own mechanism control,
but it recorded the shape of the problem exactly: contender and champion both
finished the season on **8 pasture tiles, 8 head placed and 4 head stuck in
the shed**, and the contender spent 437 of 719 turns with head waiting. Three
quarters of that waiting had no free pasture standing, so the rule that
decides how much pasture to *want* is not what binds -- eight tiles is what
two herders have the turns to build and tend. `LIVESTOCK_WORKERS` is two
hard-coded indices, and #234's ceiling places 14 head by day 9 with eleven
hands.

One decision changes: from `HERDER_DAY`, `livestock_workers` names a third
worker on the livestock line, through the seam on the frozen benchmark (#181,
#202, #219, #237). The pasture lead of 3 comes from `pasture_ahead`, #219's
cow rule and the crop caps from `rival_aware`, and the crop, hire, land, feed
and sell rules from the benchmark -- all unchanged.

**Which worker, and what it costs.** `THIRD_HERDER` is worker index 6. Under
the frozen `HAND_RAMP` the farm runs six hands from day 0 (worker indices 0-6)
and seven from day 8, so worker 6 is an *existing crop hand*, not the day-8
hire -- measured on seed 816, six hands on days 0-7 and seven from day 8. It
therefore abandons the cluster it has been tending since day 0
(``CROP_TILES[16:20]``), and whatever is standing there dies unwatered. That
is the declared, visible cost of the arm and is exactly what #239's third
control -- planted tiles at day 16 within 5 of the champion's -- exists to
measure. `HERDER_DAY` is 8 because that is the day `ANIMAL_RAMP` first asks
for 4 head and the day the crew grows to seven.

No other worker's cluster moves: `field_rival._crop_slot` derives the slot
layout from `LIVESTOCK_WORKERS` rather than from who is herding, so the third
herder gives up its own tiles and nobody else's change hands.

Declared before measurement: `HERDER_DAY`, `THIRD_HERDER`, and the controls
and criterion in `harness/herder_bench.py` (posted to #239 before the
criterion ran).
"""

from __future__ import annotations

from strategies import field_rival as fr
from strategies.pasture_ahead import PastureAheadStrategy

#: The day the third herder joins the livestock line. `ANIMAL_RAMP` steps to
#: 4 head on day 8 and `HAND_RAMP` to 7 hands on the same day, so it is the
#: first day the herd asks for more than the opening pair can place. Declared
#: in #239 before any measurement.
HERDER_DAY = 8

#: The worker that herds. Index 6 -- the sixth hand, present from day 0 (see
#: the module docstring): it gives up its own crop cluster and keeps every
#: other worker's where it was.
THIRD_HERDER = 6


class ThirdHerderStrategy(PastureAheadStrategy):
    """`pasture_ahead` that runs three herders from `HERDER_DAY`."""

    name = "third_herder"
    benchmark = False

    #: Class attributes so a test can read the declared constants off the
    #: agent itself, in the shape #219's THRESHOLD and #237's LEAD_TILES use.
    HERDER_DAY = HERDER_DAY
    THIRD_HERDER = THIRD_HERDER

    def livestock_workers(self, day):
        """The benchmark's pair plus `THIRD_HERDER` from `HERDER_DAY` on.

        ``None`` before that day is the frozen split, not a rebuilt copy of
        it: the arm must be off for the first eight days in exactly the way
        the benchmark is off.
        """
        if day < self.HERDER_DAY:
            return None
        return tuple(fr.LIVESTOCK_WORKERS) + (self.THIRD_HERDER,)


STRATEGY = ThirdHerderStrategy
