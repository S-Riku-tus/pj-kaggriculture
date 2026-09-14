"""NW pasture block: the pasture opened before the head (#246).

#244 fronted the herd ramp on `third_herder` and was REJECTED 3/16. Its
census said why: the contender OWNED 10 head at day 9 against the champion's
4 -- the cash was there -- but PLACED 5 against 4 and spent 561 of 719 turns
with head in the shed. `field_rival.PASTURE_TILES` is five NW tiles followed
by seven NE tiles and `LAND_RAMP` buys NE on day 12, so pasture is
land-capped at five until then whatever the ramp asks.

Two facts make the layout the lever. `BUILD_PASTURE` is free and instant --
the sim op only sets the tile's kind -- so pasture is bounded by owned tiles,
not money. And the ceiling (#234, `lonespear_v21`) builds six pasture tiles
on day 0 and fourteen by day 7 inside NW alone.

One decision changes on top of `pasture_first`: the pasture block is the
twelve NW tiles nearest the shed after the shed-access tile, through the
`layout` seam on the frozen benchmark (#181, #202, #219, #237, #239, #246),
and the crop tiles follow the frozen rule with that block removed. Twelve is
`len(PASTURE_TILES)`, so the ramp's ceiling and every inherited rule reading
the block length are unchanged; the first five tiles are the frozen block's
own, so the herders' shed walk is unchanged. A layout change alone is inert
before day 12 -- the frozen ramp asks four head and five tiles hold it --
which is why #244's `FRONT_RAMP` rides along, inherited.

The visible cost: on days 0-7 the champion's five crop hands work all
twenty NW crop tiles; this layout leaves thirteen -- crop slot 3 is `(0, 0)`
plus three NE tiles and slot 4 is wholly NE, both locked until NE opens on
day 12, so one crop hand idles for eight days. From day 8 the gap is three
(the third herder takes a crop hand on both sides). The day-16 crop-line
control in `harness/layout_bench.py` cannot see that deficit -- by then both
layouts expose the same tiles -- so the bench records planted tiles at day 8
beside the controls.

Declared before measurement: `PASTURE_BLOCK`, and the controls and criterion
in `harness/layout_bench.py` (posted to #246 before any code).
"""

from __future__ import annotations

from strategies import field_rival as fr
from strategies.pasture_first import PastureFirstStrategy

#: The twelve NW tiles nearest the shed after the shed-access tile (4, 4), in
#: the frozen nearest-to-shed order. Its first five are `PASTURE_TILES`' own.
PASTURE_BLOCK = tuple(fr._quadrant_tiles("NW")[1:13])

#: Everything else we will ever own, nearest-to-shed first, NW before NE
#: before SW -- the frozen rule with this block removed instead of the frozen one.
CROP_TILES = tuple(
    t for q in fr.OWNED_QUADRANTS for t in fr._quadrant_tiles(q) if t not in PASTURE_BLOCK
)


class NwPastureStrategy(PastureFirstStrategy):
    """`pasture_first` with the pasture block inside NW."""

    name = "nw_pasture"
    benchmark = False

    #: Class attributes so a test can read the declared layout off the agent
    #: itself, in the shape LEAD_TILES, HERDER_DAY and FRONT_RAMP use.
    PASTURE_BLOCK = PASTURE_BLOCK
    CROP_TILES = CROP_TILES

    def layout(self):
        """This arm's block and crop tiles; the count rules are inherited."""
        return (self.PASTURE_BLOCK, self.CROP_TILES)


STRATEGY = NwPastureStrategy
