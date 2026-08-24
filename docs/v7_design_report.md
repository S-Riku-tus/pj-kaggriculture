# Kaggriculture repository V7 design report

## Result and evidence boundary

The source of public submission `55693615` (external V7, reported rating
822.1) and submission `55694351` (external V7-2, reported rating 786.2) is not
present in this repository. `agents/v7` is a new implementation built from the
repository V6; it is not claimed to reconstruct either submitted policy.

The investigation used:

- all 47 external-V7 and 44 external-V7-2 full replays downloaded on
  2026-08-23;
- the V1-V6 source, design notes, tests, and local match history;
- the existing sampled Rank 1-3 replay corpora; and
- ten isolated local ablations followed by an independent selected-policy
  holdout.

One self-play episode from each external submission is excluded from public
opponent statistics. A local V6 match is an engineering regression test, not a
leaderboard-rating estimator. Consequently this report does not claim that the
new policy has reached, or is statistically proven to approach, rating 3000.

## What the public replays establish

| Metric | External V7 | External V7-2 | Rank 1 sample | Rank 2 sample | Rank 3 sample |
| --- | ---: | ---: | ---: | ---: | ---: |
| Public games | 46 | 43 | 30 | 29 | 30 |
| Win rate | 50.0% | 51.2% | 93.3% | 79.3% | 86.7% |
| Mean coin | 86,135 | 82,860 | 96,395 | 101,342 | 91,136 |
| P10 coin | 58,112 | 53,266 | 65,206 | 75,212 | 63,328 |
| Hand PASS rate | 8.18% | 14.63% | 3.47% | 4.68% | 18.89% |
| Productive actions / hire | 9.42 | 8.59 | 10.88 | 10.32 | 9.73 |
| Day-12 productive tiles | 49.1 | 52.1 | 70.0 | 67.4 | 69.3 |
| Day-24 productive tiles | 61.2 | 56.7 | 69.2 | 69.1 | 69.4 |
| Max Cow vs Milk-demand correlation | -0.02 | 0.31 | 0.71 | 0.76 | 0.62 |

The attachment's central warning is supported: closer action imitation did not
turn into head-to-head strength. The full replays also separate two causes.

First, V7-2 has a real execution/expansion regression. It fills at least 80%
of the farm after its third land purchase in only 20 of 43 public games; V7
does so in 46 of 46. Its lower productive-work rate is therefore not merely a
side effect of finishing with fewer coins.

Second, executor collapse is not a complete explanation for V7. Its bottom and
top coin-share quartiles have nearly identical hire, harvest, animal-service,
and herd totals. More work alone cannot repair those losses. The near-zero
Milk-demand/Cow response and the roughly 20-tile Day-12 gap to the top samples
instead identify portfolio response and capital timing as missing information.

## Existing V6 as the control

V6 is a small, already tested extension of V5. V5 supplies the route-dense task
assignment and sequential Feed-Care-Collect missions; V6 advances Strawberry
capital formation while retaining conservative feed reserves, sales, and
liquidation. Previous repository comparisons found V5 materially stronger than
V4, while V6's advantage over V5 was much narrower and included high-score
losses. That made V6 the safest control, not a policy to rewrite wholesale.

The investigation therefore treated each proposed idea as an isolated causal
change. Every match used paired seeds with both player seats. Variants were not
stacked after a negative test.

## Ablation results

| Variant and immediate control | Games | W-T-L | Mean margin | Decision |
| --- | ---: | ---: | ---: | --- |
| Broad OOD/recovery/crop controller vs V6 | 20 | 0-0-20 | -8,356 | Reject |
| Full first-quadrant opening vs V6 | 10 | 3-0-7 | -2,065 | Reject |
| Bounded herd, max 1 slot vs V6 | 10 | 6-0-4 | +1,023 | Retain |
| Bounded herd holdout vs V6 | 10 | 5-0-5 | +1,735 | Retain |
| Market residual vs bounded herd | 10 | 5-0-5 | -78 | Reject |
| Strawberry/Wheat rotation vs bounded herd | 10 | 5-0-5 | +211 | Reject as neutral |
| Max 2 herd slots vs max 1 | 10 | 6-0-4 | +820 | Re-test |
| Max 2 herd holdout vs max 1 | 10 | 5-0-5 | 0 | Reject as neutral |
| Max 2 herd slots vs V6 | 20 | 8-4-8 | +70 | Reject as neutral |
| Bounded Carrot rotation vs max 2 herd | 10 | 3-2-5 | -1,112 | Reject |
| Selected max 1 policy, new V6 holdout | 20 | 11-0-9 | -201 | Keep selected policy |

The broad controller is especially informative. It reached about 70.5
productive tiles on Day 20 versus V6's 66.4, yet lost all 20 games. The shared
market makes farm utilization endogenous: extra supply can depress the
producer's own price and transfer value to the opponent. Productive tiles,
action count, and imitation accuracy are diagnostics rather than objectives.

## Selected repository V7

The deployed policy changes only the target Cow/Sheep composition on Days 8-20:

1. obtain the complete V6 target tuple;
2. compute an economic Cow/Sheep ratio from observable Town demand, current
   prices, opponent portfolio, and the existing V2 economic function;
3. blend 55% of V6's safe ratio with 45% of that economic ratio;
4. clamp the result to at most one not-yet-owned slot away from V6;
5. preserve total herd size and never set a target below an already-owned
   animal count.

Every other target and executor path remains V6: crop counts, land, hands,
field task construction, task assignment, feed reserve, purchases, sales, and
endgame liquidation. The policy is deterministic and has no cross-turn mutable
state.

Across the three V6 comparison blocks used for the selected max-one policy (40
games, 20 paired seeds), the result was 22 wins and 18 losses, mean reward
96,374, and mean margin +589. Median margin was +258. The approximate 95%
interval for mean margin was -941 to +2,119, so the result is directionally
positive but statistically inconclusive. The newest independent 20-game block
was 11-9 with mean margin -201; it prevents overclaiming based on the two
earlier, smaller blocks.

## Why the rejected features are absent

- **Recovery/OOD mode:** the thresholded policy changed capital allocation too
  aggressively and amplified shared-market effects.
- **100% opening utilization:** filling five additional Wheat tiles delayed
  higher-value capital and lost locally.
- **Carrot/Tomato diversification:** visible demand did not compensate for
  replacement cost and timing in the tested controller. Tomato was rejected
  with the broader controller; bounded Carrot was then rejected independently.
- **Market residual:** apparent price timing did not survive its immediate
  control.
- **Two-slot herd response:** its first block was positive but the holdout was
  exactly neutral and the direct V6 comparison contained four ties.

These remain research hypotheses, not dormant code paths in the submitted
agent.

## Validation and next leaderboard experiment

Unit tests cover observation purity, fail-closed behavior, exact preservation
of non-herd V6 targets, owned-animal lower bounds, the one-slot clamp, the
Day-21 freeze, and dependency resolution from a packaged runtime. Paired local
matches completed with both agents in `DONE` state.

The next valid measurement is a Kaggle submission followed by at least 30
distinct public opponents. Select on P25 coin share, P10 margin, and win rate
against 800+ opponents; use mean coin only as a secondary diagnostic. If the
demand response fails there, revert the single herd-ratio function without
touching the validated V6 executor. Reaching rating 3000 will require repeated
public-distribution experiments; the available 89 external public games and a
single V6 control cannot support that claim by themselves.
