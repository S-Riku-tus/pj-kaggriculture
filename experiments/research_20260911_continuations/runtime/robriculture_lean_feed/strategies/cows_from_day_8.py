# strategies/cows_from_day_8.py
"""A clock, not a rival reader: every animal from day 8 on is a cow (#225).

`dense_farm` with one decision changed, through the same `herd_preference`
seam `rival_aware` uses (#181, #202, #219). Before day 8 the budget rule
stands -- sheep, whose wool is on the shelf by day 6 at base 200. From day 8
the herd goes to milk, whose three shops open on seeded days, so the town's
draw is per-seed (#228 measured 66-354 over eight seeds) -- against wool's
one shop and a floor past ~300 units (#146).

Why day 8 and why no tile-reading: #219's three recorded-not-gated arms.
The ablation, the cows-from-day-N timing arm and the 63-rival ghost bench are
recorded on #219 with their numbers; the short version is that the timing arm
found N=8 the first day that matches the champion, and that the tile-reading
turned out to be a brake rather than an engine -- it keeps the switch quiet in
the games where no rival herd appears. This contender takes the clock alone.

Declared before measurement: the switch day, and the criterion in
`harness/clock_bench.py` (posted to #225 before the criterion ran).
"""

from __future__ import annotations

from strategies.dense_farm import DenseFarmStrategy

#: The first day every animal we buy is a cow. Declared in #225, chosen from
#: the #219 timing arm rather than searched here.
SWITCH_DAY = 8


class CowsFromDay8Strategy(DenseFarmStrategy):
    """`dense_farm` that buys cows from `DAY` on, whatever the rival does."""

    name = "cows_from_day_8"
    benchmark = False

    #: Class attribute so a test can switch the mechanism off (a day past the
    #: season) and prove the identity with dense_farm to the value.
    DAY = SWITCH_DAY

    def herd_preference(self, obs):
        return "COW" if int(obs.get("day", 0)) >= self.DAY else None


STRATEGY = CowsFromDay8Strategy
