# Kaggriculture V16

V16 is a one-change experiment on V14. During Days 6-10 it raises routine
Melon WATER tasks to priority 12,000: below routine FEED (12,100), Strawberry
planting (13,500), animal placement (13,400-13,500), and emergency FEED
(15,400), but above the original 10,600 priority.

The hypothesis comes from public replays rather than old-agent win rate. V11
waters about 82% of initial Melon opportunities in Days 6-10 and delays much
of the first Melon sale, while Rank 1 is near complete watering and converts
the same 11-tile opening into substantially more Day-11 cash.

An initial broad all-crop WATER variant improved one seed and the lower tail,
but reduced Day-7 Strawberry placement and regressed the five-seed mean. It is
therefore not the selected implementation; the current rule is Melon-only.
The first Melon-only priority of 12,800 then produced two animal-loss games on
its untouched holdout, so it was also rejected. The current 12,000 priority
preserved V14's routine-FEED ordering but still regressed mean, P10, and
minimum reward and produced one animal-loss game on a new holdout. The entire
V16 experiment is therefore disabled by default and retained only as a
reproducible rejected checkpoint.
