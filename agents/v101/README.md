# Kaggriculture V101

V101 is a rejected, disabled experiment on V14. On Days 8-15, when Strawberry
demand is at most one, the opponent already exposes at least 16 Strawberry
tiles, and V3's existing expert gate is not Rank-3-like, it may stop increasing
the future Strawberry target. It never digs a live crop, changes an animal
target, or forces an immediate replacement. The branch expires on Day 16, so
later Town information returns control to V14 automatically.

The structural rule was selected on episode-disjoint train/validation Top-3
winner trajectories. Validation changed 26/68 episodes and improved the
weighted Wheat/Strawberry 72-hour target error and P90. The historical
confirmation split improved in aggregate and separately for Rank 1, Rank 2,
and Rank 3, but it was no longer pristine after an earlier distinct screen.
These are imitation diagnostics, not causal reward or rating estimates.

Closed-loop calibration rejected the branch. Four of six games changed. One
original replay was invalid because a host pause was charged to the local
agent as a wall-clock TIMEOUT; it was rerun with the same resolved seed and
seat. In the corrected six-game diagnostic all games completed without animal
loss, but mean contextual reward fell from 104,568 to 87,999, mean margin fell
from 0 to -483, margin P10 fell from -1,769 to -3,455, and one paired absolute
reward fell by 50,498. Those rewards are diagnostic context rather than a
selection KPI, but the lower-tail and trajectory evidence is insufficient for
promotion. The feature is disabled by default and must not replace V14 or V11.

V14 retains ownership of OOD fallback, herd growth, feed/water survival,
movement, assignment, cash, land, market feasibility, and liquidation. A
rating above 3000 remains an unverified goal.
