# Kaggriculture V17

V17 adds one bounded strategic choice to V14. In a Day 6-19 recovery state,
it chooses between V11's Cow/Sheep goal and the herd already owned. It never
predicts an arbitrary herd size. The state must lie inside V14's winner
manifold and V17's tree disagreement must remain within its validation
threshold; otherwise the policy falls back to V14. The herd gate does not
depend on the separate V14 crop model being confident.

The model was trained on winning sides of the Rank 1-3 corpus with episode-level
train/validation/test splits (243/78/78 episodes). The threshold was selected
on validation recovery rows only. On untouched test recovery rows, 72-hour herd
MAE improved from 1.760 for V11 goals to 1.349, with 95.1% precision on freeze
decisions. These are offline trajectory metrics, not a rating guarantee.

Closed-loop diagnostics found only two effective target changes among 13,440
saved states. On the triggering seed, lowering the Day 9 Cow goal from 8 to 6
produced a trajectory exactly identical to V14 because purchasing occurred
later in the day after the day-start gate stopped firing. V17 is therefore
disabled by default and does not replace V14.
