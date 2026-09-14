"""herd_first: field_pace with the herd funded before land and seed (#254).

#252 put the field's schedule on the benchmark's buy order and stood 6 head by
day 8 with 15 in cash: `market_orders` funds land and the whole strawberry seed
bill before the herd. The field funds its herd first, and the sim says why that
is self-funding -- every placed animal makes one fertilizer a day, fertilizer
sells from 100 and falls 0.2 a unit with no shop draining it, sheep add wool
from day 6. Four head from day 0 earn ~380 a day before any melon pays; thirteen
~1,200; lonespear takes 51% of its revenue from livestock and fertilizer (#234).

One decision changes: `buy_order` runs the herd block before land and seed,
through the seam on the frozen benchmark (#181, #202, #237, #246, #252, #254).
Every `field_pace` knob and every `third_herder` rule beneath it is inherited.

Declared before measurement: `ORDER_H`, and the controls and criterion in
`harness/order_bench.py` (posted to #254 before any code).
"""

from __future__ import annotations

from strategies.field_pace import FieldPaceStrategy

#: The herd ahead of land and seed; sells first and feed last as ever.
ORDER_H = ("hires", "herd", "land", "seed")


class HerdFirstStrategy(FieldPaceStrategy):
    """`field_pace` with the herd funded first."""

    name = "herd_first"
    benchmark = False

    ORDER_H = ORDER_H

    def buy_order(self):
        return self.ORDER_H


STRATEGY = HerdFirstStrategy
