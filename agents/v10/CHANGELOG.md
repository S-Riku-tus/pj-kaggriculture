# Changelog

## 10.0.0

- Added a high-confidence productive-portfolio target for the common top-team
  Day-12 state and a 72-hour Wheat rotation target.
- Calibrated unowned Cow/Sheep slots to revealed Milk and Wool demand while
  preserving owned animals and feed reserves.
- Raised Strawberry expansion and under-utilized refill work without outranking
  routine or emergency feed.
- Suppressed Day 6-10 fertilizer work and converted collected fertilizer to
  working capital in that bounded window.
- Restricted later fertilizer work to Strawberry and Tomato; retained V9 sales
  outside the independently validated early override.
- Added safe local watering and idle-worker pre-positioning behind the V9 OOD
  gate.
- Raised purchased-animal pickup and placement above ordinary field work after
  a lower-tail replay exposed a Cow expiring in the shed.
- Added whole-episode Rank-1/2/3 counterfactual evaluation, lower-tail local
  diagnostics, regression tests, and standalone package checks.
- Rejected full sales replacement, forced fertilizer sale after Day 10, and
  mission continuity because held-out or closed-loop evidence did not support
  them.
