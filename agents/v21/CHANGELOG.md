# V21 changelog

- Preserve V14 strategy goals, market planning, feasibility checks, survival
  priorities, and unknown-state fallback.
- Route only empty, residual `PASS` units on Days 11-12 after hour 14.
- Restrict preventive routes to three tiles and require completion before the
  day boundary.
- Disable the rule whenever a feed emergency exists.
- Leave the learned opponent-supply model disconnected pending price and
  closed-loop validation.
- Reject and disable the experiment after the paired holdout improved the mean
  by only 94.7 while reducing P10 by 1,086 and minimum reward by 10,860.
- Record that lower next-day water risk did not prevent path-dependent herd
  and portfolio regressions.
