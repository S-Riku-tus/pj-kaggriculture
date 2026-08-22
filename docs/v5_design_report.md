# V5 design and validation report

## Scope

V5 was developed from the submitted V4 artifact, submission `55681293`
(reported rating `868.1`), its 36 public replays, and the existing Rank 1–3
replay corpora.  One V4 replay had the same team name on both seats and no
distinct opponent submission ID, so opponent-comparison statistics use the 35
distinct-team games.  Raw action analysis also corrects an important replay
detail: the action selected from `steps[t].observation` is stored in
`steps[t + 1].action`.

## Independent V4 findings

V4 was already much stronger than V3 at field execution, but four remaining
effects were measurable:

| Signal | V4 public games | Rank 1 public games |
| --- | ---: | ---: |
| Day-20 Cow / Sheep profile | 26/35 games at exactly 9 / 6 | adaptive |
| Milk-demand / Cow correlation | 0.511 | 0.688 |
| Wool-demand / Sheep correlation | 0.662 | 0.780 |
| Strawberry-demand / Strawberry correlation | -0.224 | 0.641 |
| `FEED -> CARE` per game | 61.5 | 250.5 |
| `CARE -> COLLECT_FERTILIZER` per game | 4.9 | 159.8 |
| `FEED -> movement` per game | 147.4 | 5.6 |
| Hour-23 `PLANT` per game | 11.83 | not used as a target |

The hour-23 behavior is mechanically unsafe: a newly planted crop begins with
one consecutive unwatered day, while no later action remains before the daily
refresh.  V4 also took an average of 92.7 turns to fill the second unlocked
quadrant and 79.4 turns to fill the third; Rank 1 took 45.3 and 36.1 turns.

## Implemented V5 changes

V5 retains the submitted V4 executor and V3 model, then applies four bounded
changes:

1. Cow and Sheep are projected through a shared animal-total budget and an
   adaptive ratio.  The model remains the dominant signal, demand/price logic
   is a smaller correction, and already owned animals are hard lower bounds.
2. Strawberry targets blend learned and economic signals.  Wheat fills only
   the remaining shared tile budget, including the feed reserve.
3. `PLANT` tasks are forbidden at hour 23, and land purchases require both
   sufficient current utilization and enough planned productive tiles.
4. Animal work at an occupied tile is exposed as a sequence—harvest, feed,
   care, fertilizer collection—rather than competing simultaneous tasks.
   Same-tile continuation receives an assignment bonus.  This is derived from
   each observation and uses no mutable episode state.

The total-animal and Strawberry schedules are deliberately conservative.  An
initial variant that removed nearly all floors allocated too much space to
low-value Wheat and lost to V4 despite higher utilization.

## Ablation and holdout results

All local comparisons are paired by seed: each market sequence is played once
from each seat.

| Variant | Games | W-L | Mean margin vs V4 | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Unconstrained adaptive portfolio | 10 | 1-9 | -3,985.7 | Rejected; too few premium assets |
| Conservative portfolio, old task assignment | 10 | 7-3 | +4,562.8 | Portfolio fix retained |
| Conservative portfolio + animal missions | 10 | 6-4 | +3,247.0 | Large execution-KPI gain |
| Same final V5, new seed holdout | 20 | 17-3 | +7,465.3 | Passed independent holdout |
| Final V5 vs V3, new seeds | 10 | 10-0 | +37,106.5 | No detected old-version regression |

Across the two V4 test batches, final V5 was 23-7 with mean scores 91,755.4 vs
85,696.2 and mean margin +6,059.2.  Treating the two seat-swapped games for
each of 15 seeds as one paired observation gives an approximate 95% interval
of +2,238 to +9,881.  Mean margin remained positive from both seats (+6,825.7
as seat 0, +5,292.7 as seat 1).

The new-seed action KPIs confirm that the intended mechanism survived the
holdout:

| KPI per game | V4 public | Final V5 holdout |
| --- | ---: | ---: |
| Hour-23 `PLANT` | 11.83 | 0.00 |
| `FEED -> CARE` | 61.5 | 232.4 |
| `CARE -> COLLECT_FERTILIZER` | 4.9 | 233.7 |
| `FEED -> movement` | 147.4 | 45.8 |
| Harvest | 306.0 | 323.1 |

## Delta-learning experiment

`scripts/train_v5_delta_strategy.py` creates an explicit short-horizon
dataset from Rank 1 replays.  It samples every six turns from days 3–22 and
labels the next 24 turns with seven portfolio deltas plus seven high-level
intents (animal/land purchases, planting, pasture construction, and digging).
The split is by episode, not by row.

Training on 134 episodes produced 10,720 examples.  On 1,600 held-out examples,
the forest's macro MAE was 0.6222 versus 0.5175 for a training-only day/hour
median (ratio 1.202).  It also lost on the strategically important Cow, Sheep,
Land, and Hands targets.  The learned delta model is therefore retained as a
research artifact but is intentionally not loaded by V5.  The negative result
suggests that Rank 1's expansion decisions are dominated by a stable temporal
choreography; the current schedule plus bounded economic correction is the
safer deployment choice.

Generated research artifacts:

- `data/training/v5_delta_strategy.npz`
- `data/models/v5_delta_strategy.json`
- `data/analysis/v5_baseline_comparison.json`
- `data/analysis/v5_v4_opportunities_corrected.json`

## Limitations

Local V5-versus-V4 games share the same simulator and are stronger evidence
than unpaired score comparisons, but 15 independent market seeds are still a
modest sample.  Public Rank 1–3 replays come from different market and opponent
distributions, so their raw rewards are diagnostic rather than causal.  The
next highest-value evidence is a real V5 submission followed by the same
distinct-opponent replay analysis used here.
