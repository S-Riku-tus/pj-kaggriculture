"""The field's shape, put forward as a candidate instead of an opponent (#193).

#157 decomposed 63 real ladder matches: the winning field draws **62% of its
revenue from livestock and fertilizer**, we draw none, and our crop revenue is
actually the strongest in that data. #187 then established that the herd cannot
simply be bolted on — the two businesses compete for one crew, and our crop line
is three times the field's:

                         planted  animals  crew   WATER   FEED
    neuropilot (ours)         62        0     8   1,074     13
    the field                 20        8    11     506    153

So the hypothesis under test is not "keep animals". It is that the **shape** is
wrong: 62 tiles of one business against 20 tiles plus a herd.

`field_rival` is our own code, calibrated in #181 to the archetype measured from
those replays. Over 8 seeds it beats the submitted champion **5 games to 3**
while earning slightly less per game — and the ladder scores wins and ties only,
margin discarded (ADR-0003). It has been sitting in this repository since #181
labelled as an opponent.

This module is deliberately a **behavioural copy** of it. That is the control the
question needs: it isolates "is the field's shape better than ours" from "can we
out-tune the field", which are different experiments and would confound each
other if run together.

Two constraints this respects:

- `field_rival` stays `benchmark = True` and frozen. It is the only anchor
  calibrated to the field that beats us; editing it, or flipping its flag, moves
  the measuring stick under the thing being measured.
- If this promotes, the anchor pool loses its discriminating opponent — the
  benchmark becomes a mirror of the champion. Filing a replacement benchmark is
  part of that outcome, not an afterthought (#193).
"""

from __future__ import annotations

from strategies import field_rival as fr


class BalancedFarmStrategy(fr.FieldRivalStrategy):
    """`field_rival`'s calibrated shape, eligible for promotion."""

    name = "balanced_farm"

    #: A contender, not a sparring partner. `scripts/submit.py` and
    #: `harness.promotion.top_contender` both gate on this flag (ADR-0005).
    benchmark = False

    #: The planted-tile band this shape is claimed to run, from the replay
    #: medians (#157: the field holds 20-27 planted tiles from day 12 on). The
    #: necessary condition in #193 checks the agent actually lands inside it,
    #: so a null result cannot be a mechanism that never fired — which is
    #: exactly how #187 failed.
    TARGET_PLANTED_RANGE = (15, 30)


STRATEGY = BalancedFarmStrategy
