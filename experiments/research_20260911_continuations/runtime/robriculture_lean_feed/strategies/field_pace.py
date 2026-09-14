"""field_pace: the field's schedule on third_herder, as one package (#252).

A census of `third_herder` vs `pilkwang_structured_economic_policy` on spent
seeds 864-867 read the field's schedule straight off both boards (medians):
5 hands, 4 head and no cash reserve from day 0; strawberry from day 5; NE on
day 6 with 8 hands; 10 hands, 37 planted and 13 head by day 8; SW on day 11;
62 planted (38 strawberry, 24 wheat) by day 12; 14 pasture tiles inside NW;
12 hands by day 15. Closing money 128,904 to our 46,228 on seed 864.

#244 fronted the herd alone and #246 opened the pasture alone; both were
cash-limited before the melon payday on day 10. The field's edge is that it
spends every coin on growth from day 0, on every knob at once. This arm moves
them together -- hands, land, crop pivot, crop caps, tiles per hand, herd,
pasture block and cash reserve -- through the seams on the frozen benchmark
(#181, #202, #237, #246, #252), every value the median above and none tuned.
Inherited unchanged: the third herder from day 8, the lead of 3, #219's cow
rule, the benchmark's sell and feed rules.

Declared before measurement: every constant below, and the controls and
criterion in `harness/pace_bench.py` (posted to #252 before any code).

Measured after the fact: the `(15, 12)` hand step never fires (hires are dawn-only
under the ten-order cap), and the frozen slot layout works 11/36/30/48 crop tiles
by window, not the 60 the numbers name (#252 review).
"""

from __future__ import annotations

from strategies import field_rival as fr
from strategies.third_herder import ThirdHerderStrategy

HAND_RAMP_F = ((0, 5), (6, 8), (8, 10), (15, 12))
LAND_RAMP_F = ((0, 1), (6, 2), (11, 3))
PIVOT_F = 5
CAPS_F = {"MELON": 12, "STRAWBERRY": 38, "WHEAT": 24}
CLUSTER_F = 6
HERD_RAMP_F = ((0, 4), (6, 8), (8, 13))
RESERVE_F = 0

#: Fourteen NW tiles nearest the shed after the shed-access tile (4, 4); the
#: first five are the frozen block's own, so the herders' shed walk is unchanged.
PASTURE_BLOCK_F = tuple(fr._quadrant_tiles("NW")[1:15])

#: The frozen crop rule with this block removed: NW first, then NE, then SW.
CROP_TILES_F = tuple(
    t for q in fr.OWNED_QUADRANTS for t in fr._quadrant_tiles(q) if t not in PASTURE_BLOCK_F
)


class FieldPaceStrategy(ThirdHerderStrategy):
    """`third_herder` on the field's measured schedule."""

    name = "field_pace"
    benchmark = False

    CAPS = CAPS_F
    HAND_RAMP_F = HAND_RAMP_F
    LAND_RAMP_F = LAND_RAMP_F
    PIVOT_F = PIVOT_F
    CLUSTER_F = CLUSTER_F
    HERD_RAMP_F = HERD_RAMP_F
    PASTURE_BLOCK_F = PASTURE_BLOCK_F
    CROP_TILES_F = CROP_TILES_F
    RESERVE_F = RESERVE_F

    def hire_target(self, day):
        return fr._ramp(self.HAND_RAMP_F, day)

    def land_target(self, day):
        return fr._ramp(self.LAND_RAMP_F, day)

    def pivot_day(self):
        return self.PIVOT_F

    def cluster_size(self):
        return self.CLUSTER_F

    def capital_reserve(self, day=None, animals=None):
        return self.RESERVE_F

    def herd_target(self, day):
        """The field's herd ramp, never fewer head than the frozen ramp asks."""
        return max(fr._ramp(self.HERD_RAMP_F, day), fr.animal_target(day))

    def layout(self):
        return (self.PASTURE_BLOCK_F, self.CROP_TILES_F)

    def pasture_count(self, day, animals):
        """Tiles to keep in play: the lead ahead of placed head, never fewer
        than this arm's ramp, never more than this arm's own block."""
        return min(len(self.PASTURE_BLOCK_F),
                   max(animals + self.LEAD_TILES, self.herd_target(day)))


STRATEGY = FieldPaceStrategy
