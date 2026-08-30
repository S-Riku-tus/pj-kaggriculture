# V10 Future-State Recovery Agent

V10 is an evidence-driven successor to V9. It uses the 55 non-self public V9
episodes and the public logs of the top three submissions as its primary
evidence. Matches against older local agents are diagnostic only.

The agent retains V9's learned Rank-1 strategy atlas, OOD confidence gate,
opening scripts, budget checks, inventory constraints, feed safety, legal
movement, and liquidation. V10 adds bounded corrections for gaps measured in
closed-loop replays:

- demand-conditioned Cow/Sheep allocation without selling or removing owned
  animals;
- a Day 10-18 productive-portfolio target of 72 cells, filling only residual
  capacity with Wheat while preserving demand-specific crop targets;
- late Wheat rotation targets that represent the desired 72-hour farm state;
- immediate Day 6-8 Strawberry execution and Day 13-26 refill recovery;
- no expansion fertilizer work and early fertilizer sale for working capital;
- premium-only fertilizer work on Days 11-26;
- safe local watering and pre-positioning of otherwise idle empty workers.
- expiry-safe pickup and placement of purchased animals below emergency feed
  but above ordinary field work.

Learned corrections turn off when atlas confidence is below 0.35. Feed
emergencies remain above watering, fertilizing, and planting priorities.

Evidence, rejected experiments, limitations, and reproduction commands are in
`docs/v10_design_report.md`. No local or replay result guarantees a leaderboard
rating, including the research target of 3000.
