"""How large can the crop line grow before the herd stops standing up? (#202)

#196 established that the binding constraint on running both businesses is
**worker slack**, not job priority. Every animal placement and every feeding is
a round trip to the shed, and a big crop line eats the turns those trips need.
FEED count tracks tiles-per-worker almost exactly:

    neuropilot      62 planted   0 animals   6.9 tiles/worker     0 FEED
    splitbrain      56 planted   4 animals   5.6 tiles/worker    17 FEED
    balanced_farm   20 planted   8 animals   1.8 tiles/worker   153 FEED

So the field's 20-tile crop line is not a sacrifice made to fit animals in --
it is the room the animals need. Which turns the design question into a
one-parameter one, and nobody has looked at the middle.

This is `balanced_farm` with its own crop caps, scaled by a single factor. It
matters because `balanced_farm` is live and failed exactly one criterion in
#193: `meta_bot` at 56% where the champion is at 100%, on a margin of 3,000
inside a 6,000-11,200 noise floor. More crop revenue is precisely what that
matchup is short of, and our crop line is the strongest in the replay data
(55,958 against the winning field's 28,361, #157).

`field_rival` is not tuned by this experiment. Its helpers take `caps` with the
module default, so #202 left its crop decisions byte-identical -- pinned by
`tests/test_dense_farm.py::test_the_crop_caps_parameter_is_behaviour_preserving_at_its_default`.
It is the only anchor calibrated to the field that beats us, and *tuning* it
would move the measuring stick under the thing being measured.

It is no longer byte-frozen, though: #211 fixed a defect in its herd state
machine on 2026-09-05 (a weed on a pasture tile stranded the herd for the rest
of the game). That is a correctness fix, not a calibration change -- it makes
the anchor stronger and less noisy -- but it does mean the numbers in #181,
#184, #193 and #202 were measured against the pre-fix `field_rival`. See the
2026-09-05 amendment to ADR-0007.
"""

from __future__ import annotations

from strategies import balanced_farm as bf
from strategies import field_rival as fr

#: The sweep, declared in #202 before any measurement so it cannot grow to fit
#: a result. 1.0 is the control -- `balanced_farm` exactly as submitted.
GRID = (1.0, 1.25, 1.5, 2.0, 2.5)

#: The setting this experiment selected. Searched over GRID on seeds 100-115,
#: then confirmed unchanged on held-out seeds 200-215 -- because picking the
#: best of five settings on one seed set, at a 6,000-11,200 noise floor (#181),
#: is selecting noise rather than measuring a farm.
#:
#:                        search (100-115)   held out (200-215)
#:     vs meta_bot                    88%                  88%
#:     vs neuropilot                  94%                  81%
#:
#: `balanced_farm`, the control and the agent currently on the ladder, is 56%
#: and 69% on those two. The held-out drop against `neuropilot` is the search
#: arm's optimism showing, and it still clears the declared 60% bar comfortably.
CHOSEN_SCALE = 1.5

#: Above this the caps stop binding. `crop_cluster` assigns 36 tiles across the
#: full crew, and melon never stands beside strawberry (melon early, strawberry
#: after the pivot), so simultaneous demand is STRAWBERRY + WHEAT: 20 tiles at
#: 1.0, 31 at 1.5, and 40 at 2.0 -- past what the crew is given. The grid keeps
#: its declared top end, but 2.0 and 2.5 are the same farm and are reported that
#: way rather than as two distinct settings.
SATURATES_ABOVE = 1.5


def scaled_caps(scale: float) -> dict:
    """`field_rival`'s measured caps multiplied by `scale`, in whole tiles.

    Only grows: shrinking below 1.0 is #193's setting, which is already measured
    and live on the ladder, so a smaller scale is a mistake rather than a point
    on this curve.
    """
    if scale < 1.0:
        raise ValueError(f"scale {scale} < 1.0; the sweep only grows the crop line")
    return {crop: int(round(cap * scale)) for crop, cap in fr.CROP_CAP.items()}


class DenseFarmStrategy(bf.BalancedFarmStrategy):
    """`balanced_farm` at a chosen crop density."""

    name = "dense_farm"
    benchmark = False

    #: The scale the #202 sweep chose on seeds 100-115 and then confirmed,
    #: unchanged, on held-out seeds 200-215. 1.0 is the control -- exactly
    #: `balanced_farm`, which is live on the ladder.
    CAPS = scaled_caps(CHOSEN_SCALE)


STRATEGY = DenseFarmStrategy
