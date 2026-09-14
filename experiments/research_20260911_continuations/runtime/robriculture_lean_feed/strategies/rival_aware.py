# strategies/rival_aware.py
"""Read the rival's herd off the board and keep ours out of their market (#219).

`dense_farm` with one decision changed: once the other farm has placed
SHEEP_THRESHOLD sheep, every animal we buy is a cow. Wool has one shop and
floors past ~300 units between the two farms (#146); milk has three shops
whose opening days are seeded, so the town's draw is per-seed (#228 measured
66-354 over eight seeds) and MILK floors 76 units above its anchor. Everything
else -- crop caps, ramps, sells, land, feed -- is `dense_farm`'s, through the
`herd_preference` seam on the frozen benchmark (#181, #202).

Declared before measurement: the threshold, and the criterion in
docs/superpowers/specs/2026-09-06-rival-aware-herd-design.md.
"""

from __future__ import annotations

from strategies import field_rival as fr
from strategies.dense_farm import DenseFarmStrategy

#: One sheep can be a stray placement; two is a herd. Declared in #219.
SHEEP_THRESHOLD = 2


class RivalAwareStrategy(DenseFarmStrategy):
    """`dense_farm` that buys cows once the rival is running sheep."""

    name = "rival_aware"
    benchmark = False

    #: Class attribute so a test can switch the mechanism off (threshold
    #: unreachable) and prove the identity with dense_farm to the value.
    THRESHOLD = SHEEP_THRESHOLD

    def herd_preference(self, obs):
        return "COW" if fr.rival_sheep(obs) >= self.THRESHOLD else None


STRATEGY = RivalAwareStrategy
