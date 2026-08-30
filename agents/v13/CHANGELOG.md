# Changelog

- Replaced winner-trajectory imitation with action-only residual value learning.
- Added separate Rank1/Rank2/Rank3/winning-opponent candidate scoring.
- Required positive 24h, 72h, final, composite, atlas-confidence, and uncertainty gates.
- Preserved V11's deterministic executor, market policy, opening, and feasibility rules.
- Disabled the critic after paired closed-loop reward and lower-tail regressions.
