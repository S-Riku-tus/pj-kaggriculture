# V12–V14 analysis and V14 release report

Generated: 2026-08-26 (Asia/Tokyo)

## Scope and claim boundary

The working objective is a rating above 3000, but no local or offline result
establishes that rating. V10's supplied rating is 933 and V11's is 1014.6.
V14 is an evidence-gated candidate, not a rating guarantee.

## Data and split

- Rank 1/2/3 public submissions: 55614463, 55623460, 55574890.
- 399 deduplicated complete episodes after removing self matches.
- Both seats were retained in the common cache: 17,556 day-level rows.
- Episode-hash split: 243 train, 78 validation, 78 untouched test episodes.
- All rows from one match stay in one split.
- Runtime inputs contain only observable state; opponent private inventory is
  not used.

## What was rejected

### V12 direct expert-profile routing

The selected Rank 2 Strawberry branch matched held-out winner trajectories,
but five paired seeds regressed mean reward from 142,798.0 to 137,140.5 and
P10 from 113,476.0 to 86,956.0. It was disabled. This showed that trajectory
fidelity alone is not a value estimate.

### V12 logistics shortcuts

Wheat pickup right-sizing reduced units per feed from about 2.27 to 1.13, but
also reduced feed completion and reward. Stateless FEED-to-CARE completion
reduced route breaks but displaced watering/harvest work. Both were disabled.

### V13 residual action critic

The residual critic improved validation MAE versus a state-only baseline at all
three horizons: 24h by 3.0%, 72h by 6.1%, and final by 7.2%. Untouched-test
improvements were 2.6%, 5.8%, and 4.8%. Nevertheless, paired closed-loop runs
regressed mean reward from 142,798.0 to 138,588.3 and P10 from 113,476.0 to
90,171.0. Full-hour audit found 247 interventions, not the three visible at
day boundaries. Logged action/outcome association was therefore rejected as a
counterfactual action value, and V13 was disabled.

### V14 direct herd control

The first V14 projection exchanged crops for one extra Cow on Days 6–7. In seed
20261404 this reduced reward by 12,965 in both seats even though there was no
animal loss. The cause is structural: a herd count hides purchase, pasture,
feed, and routing commitments. V14 therefore never changes V11's herd target.

## V14 selected hypothesis

Hypothesis: while observably behind, the crop mix reached 72 hours later by
eventual winners is a useful strategic goal, provided the short horizon, herd,
workers, land, market feasibility, and field execution remain deterministic.

The model is trained on winning sides only. Rank 1, Rank 2, Rank 3, and opponents
that beat them all contribute states; they are also reported separately. It
predicts absolute 24h/72h portfolios, but validation rejected use of the 24h
model. Only the 72h recovery crop branch is active.

On recovery rows, normalized 72h error was:

| Split | V14 crop model | V11 goal | Unchanged state |
|---|---:|---:|---:|
| Validation | 0.188049 | 0.244028 | 0.214873 |
| Untouched test | 0.196344 | 0.248133 | 0.226869 |

The test split was reporting-only and did not select the branch. Phase-level
results show that direct full-portfolio control is unsafe even when aggregate
fidelity improves; this is why crop and herd control are separated.

## Runtime safety and unknown-state behavior

V14 activates only when own observable money is below the opponent's, the day
is 6–27, the state is inside a robust winning-teacher phase profile, forest
uncertainty is no greater than the validation P90, and combined confidence is
at least 0.35. Otherwise it returns V11 targets exactly.

When active, the model is blended by at most 35%. Per-call crop changes are
bounded, live crops cannot be removed, Wheat must cover 1.2 times the herd,
total productive target is capacity-projected, and low-demand crops yield
first. Herd, hiring, land, worker assignment, legal inventory operations,
market budgets, survival, and liquidation remain V11 deterministic logic.

## Closed-loop diagnostics

These are resource/safety diagnostics, not win-rate selection.

- Known five seeds, both seats: the initial full-portfolio V14 mean regressed
  by 2,593; crop-only V14 restored the targeted failing seed to V11 exactly.
- Five unseen starter seeds, both seats: crop-only V14 and V11 were identical
  on reward mean 130,349.5, P10 109,696.1, minimum 109,157, every recorded
  action KPI, and zero animal loss.
- Two seeds, both seats, against V11: all games completed with zero animal loss;
  48 hourly target changes produced three exact outcomes and one +300 reward
  diagnostic difference. This is evidence of operational safety only.

## Facts, inferences, and unverified items

Facts:

- Offline selection uses complete-episode validation and an untouched test
  report.
- V12/V13 and direct herd control failed closed-loop gates and are disabled.
- V14 crop-only recovery passed its offline gate and the recorded local safety
  diagnostics.

Inferences:

- Future crop mix contains useful recovery information beyond V11's fixed goal.
- Herd composition requires a cost-aware transition model, not direct future
  state imitation.
- A policy can improve logged prediction metrics while worsening control due to
  confounding and repeated intervention.

Unverified:

- V14's live leaderboard rating and whether it improves on V11.
- Generalization to private opponent policies outside the downloaded corpus.
- A causal estimate of each crop substitution's value.
- Rating 3000; achieving it likely requires further closed-loop data or a
  simulator-trained cost-aware planner, especially for herd and logistics.
