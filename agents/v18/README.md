# Kaggriculture V18

V18 repairs V17's day-start-only training mismatch. The Top-3 winner corpus is
sampled every three hours from Day 6 through Day 19. The model chooses only
between V11's Cow/Sheep target and the herd already owned; it cannot invent an
arbitrary target. Intraday winner-profile and model-disagreement checks fall
back to V14 on unfamiliar states.

The 399 episodes remain split 243/78/78 by episode, producing 44,688 rows. On
untouched test recovery rows, 72-hour herd MAE improved from 1.537 to 1.158,
with improvement at every sampled hour and 97.3% precision for freeze choices.
The bottom final-margin quartile improved from 1.273 to 1.030. These are offline
future-state metrics, not a rating estimate or guarantee.

Closed-loop tests produced real changes, but the joint Cow/Sheep gate was
unstable across seats: the same Day 10 branch yielded +15,409 as seat 1 and
-12,801 as seat 0. Offline Sheep error also increased slightly while Cow error
improved. V18 omits seat ordering and cannot gate animal species separately,
so it is disabled by default and does not replace V14.
