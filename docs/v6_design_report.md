# Kaggriculture V6 replay analysis and design report

## Executive conclusion

V5 is materially stronger and more stable than V4 even though their public
ratings were close. In the like-for-like 29-game corpus, mean reward increased
from 85,510 to 92,079 and P10 increased from 60,162 to 71,342. The remaining
gap to the top agents is therefore not a general V5 failure; it is concentrated
in the timing of early premium-crop investment, board utilization, and a small
number of high-scoring losses.

V6 makes the smallest change that remained robust over three independent
paired seed blocks: it forms the Strawberry capital engine earlier while
retaining V5's herd scale, conservative portfolio, and feasible task executor.
Against V5 it won 18 of 30 local games (60%). Mean margin was -547 and median
margin was +235, so this is evidence of improved win conversion rather than a
claim that V6 has already matched the leaderboard leaders. A leaderboard
submission is still the necessary out-of-sample test.

## Data and method

- V5 submission: ID `55685688`, displayed rating `851`.
- Downloaded replay count: 35; public distinct opponents used for V5 KPI
  analysis: 34 (one self-play game excluded).
- Top comparison: the existing Rank 1, Rank 2, and Rank 3 replay corpora, using
  30, 29, and 30 sampled episodes respectively.
- Local selection: paired games, the same seed in both seats, 720 turns per
  game. Three disjoint five-seed blocks supplied 30 V6-versus-V5 games.
- Metrics: reward distribution, paired margin, action/transition counts,
  movement rate, productive work per hire, crop/animal portfolio, unlocked
  land, utilization, and empty/unproductive tiles at fixed daily checkpoints.

The attachment's HARVEST average (about 274) differs from the direct replay
recount (317.9) because the counting pipelines used different event scopes.
All comparisons in this report use one pipeline per table; the strategic
conclusion is unchanged.

## What changed from V4 to V5

| Metric (29-game comparable sample) | V4 | V5 | Change |
|---|---:|---:|---:|
| Mean reward | 85,510 | 92,079 | +6,569 |
| P10 reward | 60,162 | 71,342 | +11,180 |
| Mean margin | +3,369 | +3,744 | +375 |
| Productive actions / hire | 9.66 | 9.82 | +0.16 |
| Day-24 utilization | 83.1% | 81.3% | -1.8 pp |

V5's main gain is downside protection: the lower tail improved much more than
the mean margin. Its observation-derived strategy model, safer portfolio
selection, and sequential animal-service logic improved operational stability.
The cost is that V5 still carries unused land late in the match, so rating can
remain flat when opponents also score highly.

## V5 versus the top replay corpora

| Corpus | Mean reward | Mean margin | Day-24 utilization | Day-24 nonproductive cells | Max Carrot | Max Tomato | Productive actions / hire |
|---|---:|---:|---:|---:|---:|---:|---:|
| V5 | 92,079 | +3,744 | 81.3% | 14.0 | 0.0 | 0.0 | 9.82 |
| Rank 1 | 96,395 | +8,186 | 92.3% | 5.8 | 8.2 | 3.1 | 10.88 |
| Rank 2 | 101,342 | +14,712 | 92.2% | 5.9 | 10.1 | 4.6 | 10.32 |
| Rank 3 | 91,136 | +10,411 | 92.5% | 5.6 | 1.8 | 0.8 | 9.73 |

The shared top-agent signature is high utilization, not one mandatory crop
mix. Rank 3 uses little Carrot/Tomato yet achieves the same utilization band,
so blindly copying Rank 1/2's crops would confuse correlation with causation.
V5's direct 34-public-game profile also shows the early timing gap:

| Checkpoint | V5 Strawberry | Typical top range | V5 empty cells |
|---|---:|---:|---:|
| Day 7 | 1.9 | 5.9–12.5 | 20.6 |
| Day 12 | 17.0 | 28.2–34.4 | 10.6 |
| Day 24 | 21.5 | portfolio-dependent | 13.4 |

V5's first expansion is bought only after cash becomes available late on day
6 in many games. Its inherited market planner reserves seed room in Wheat-first
order, while the field task builder also creates Wheat tasks before Strawberry
tasks. Higher Strawberry task priority cannot recover cells that Wheat has
already reserved. This is the concrete early-game bottleneck addressed by V6.

V5 still averages 48.9 `FEED -> MOVE` transitions per episode. A residual
inspection found that almost all examined cases left that worker on a fed,
uncared animal tile, confirming mission fragmentation. However, a stronger
assignment lock changed global matching and market outcomes enough to fail the
last holdout. It remains a research target, not a safe V6 change.

## Ablations and selection

| Variant | Games | Wins | Mean margin | Decision |
|---|---:|---:|---:|---|
| Force first land purchase | 6 | 2 | -2,634 | Reject: spends cash too early and can improve the shared market for the opponent |
| Adaptive herd + crop rotation | 20 | 9 | -2,110 | Reject: herd fell from about 15 to 13.4 and lost Milk/Wool revenue |
| V5 herd + crop rotation, two blocks | 20 | 7 | -1,289 | Reject: second block regressed to 2–8 |
| Early Strawberry only, three blocks | 30 | 18 | -547 | Select: best win robustness across all blocks |
| Early Strawberry + strong mission lock | 30 | 16 | +2,687 | Reject: last block regressed to 2–8 despite positive mean margin |

The selected blocks were 6–4, 5–5, and 7–3. The final block's negative mean
margin came from several large losses even though it won seven games; across
all blocks V6 had five losses with reward at least 90,000. This explains why
win rate and mean margin disagree and is the largest remaining risk.

## Final V6 behavior

1. Advance the Strawberry target floor to 8 on day 5, 12 on day 6, 18 on day
   8, 26 on day 11, and 30 on day 12.
2. During the early Strawberry deficit, stop discretionary Wheat seeds from
   consuming the day's free seed capacity. Product Wheat purchases used for
   animal feed are unchanged.
3. Replace discretionary Wheat plant tasks with Strawberry tasks when seeds
   and target deficit exist.
4. Accept the first land expansion at 58% utilization during the opening
   Wheat-recycle dip; retain the stricter 72% gate thereafter.
5. Preserve V5's animal totals, crop fallback, mission construction, Hungarian
   assignment, endgame liquidation, and stateless observation handling.

Across the 30 paired games, V6 reached 6.0 Strawberry tiles by day 7 and 20.6
by day 12, versus V5 public means of 1.9 and 17.0. Day-24 empty cells fell from
13.4 to 10.0. The operational averages remained close to V5: 313.1 harvests,
302.3 feeds, 290.2 cares, 288.9 fertilizer collections, 54.0% movement, and
49.5 `FEED -> MOVE` transitions. This is intentional: V6 changes capital
timing without destabilizing the proven V5 executor.

A separate six-game regression block against V3 finished 6–0 with mean reward
90,653 and mean margin +33,237; all episodes reached `DONE` in both seats.

## Remaining work after leaderboard evaluation

The next changes should be gated by larger paired samples and leaderboard
evidence:

- Reduce high-score losses with opponent-aware risk control rather than a
  fixed global aggressiveness increase.
- Raise day-24 utilization toward 90% using horizon/value estimates, without
  assuming Carrot/Tomato are always optimal.
- Repair animal mission continuity with explicit worker reservations or a
  short-horizon assignment objective, then verify it across several market
  regimes.
- Calibrate early land timing from projected cash and opponent demand instead
  of unconditional forced buying.

## Reproducibility artifacts

- Public V5 replay analysis: `data/analysis/v6_v5_opportunities.json`
- Cross-corpus comparison: `data/analysis/v6_baseline_comparison.json`
- Selected local runs: `data/runs/v6f_vs_v5_seed_20261201.json`,
  `data/runs/v6f_holdout2_vs_v5_seed_20261206.json`, and
  `data/runs/v6f_final_holdout_vs_v5_seed_20261301.json`
- Per-turn selected-run KPIs: matching `_kpis.json` files under
  `data/analysis/`
- Backward-regression run: `data/runs/v6_final_vs_v3_seed_20261401.json`
