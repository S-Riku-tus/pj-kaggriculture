# V9 design and validation report

## Outcome

V9 adds a Rank-1 macro-decision and opponent-aware market layer to V8's
Rank-1 opening, Top-3 24/72-hour portfolio atlas, OOD fallback, deterministic
executor, and endgame liquidation.  The submitted defaults activate only
controls that remained safe after episode-held-out evaluation and causal local
diagnostics.  No result here guarantees a Kaggle rating, including 3000.

## Facts rechecked

- Market orders are resolved in lockstep, followed by Town consumption.
- A replay action stored at step `t+1` was chosen from the observation at step
  `t`; training uses that alignment.
- Animals are irreversible productive-capital commitments.  Cow and Sheep
  controls therefore cannot be selected independently.
- The existing V8 executor already guarantees action shape, transaction
  feasibility, feed reserves, land/pasture constraints, OOD fallback, and
  late liquidation.  V9 retains these guarantees.

## Teacher data and leakage controls

The main teacher is 133 non-self Rank-1 episodes from submission 55614463.
Complete episodes are deterministically hashed into 69 train, 25 validation,
and 39 untouched test episodes.  Thresholds and branch activation use only the
validation split; test is report-only.  The resulting datasets contain 19,152
macro-intent states and 148,751 stock-bearing market states.

V8's Top-3 data remains useful for a different purpose: it supplies the
trajectory manifold and safe recovery envelope.  Rank 1 supplies the coherent
primary policy; Rank 2/3 describe robust progress ranges rather than mixed
action labels.  This separates common strategy from situation-dependent
branches.

## Learned objectives

The macro forest predicts actions within 12 turns and 24 turns: Cow/Sheep
purchase, explicit animal WAIT, land, pasture, Strawberry/Wheat planting, and
their quantities.  V8 continues to predict absolute portfolio anchors 24 and
72 hours ahead.  The market forest predicts SELL/WAIT plus sale fraction for
Wheat, Strawberry, Melon, Milk, Wool, and Fertilizer.  Features include current
price and displacement, Town demand/consumption phase, future shop uncertainty,
public opponent production, and a conservative hidden-supply pressure belief.

Forest disagreement is combined with the Top-3 trajectory distance.  Low
confidence falls back gradually to V8; malformed observations fail closed.
The learned layer proposes strategic targets, while V8's deterministic layer
remains responsible for executable movement, feeding, purchasing, inventory,
land, and cash constraints.

## Untouched-test results

The principal binary results below are F1 scores on 39 never-selected episodes.

| Decision | V9 | V8 rule |
|---|---:|---:|
| Buy Cow within 12 turns | 0.745 | 0.250 |
| Buy Sheep within 12 turns | 0.519 | 0.270 |
| Wait on animals for 12 turns | 0.949 | 0.630 |
| Buy land within 24 turns | 0.886 | 0.833 |
| Build pasture within 12 turns | 0.730 | 0.304 |
| Plant Strawberry within 12 turns | 0.882 | 0.584 |
| Plant Wheat within 12 turns | 0.891 | 0.737 |

Sheep did not satisfy the validation selection rule despite its test result.
Therefore Cow and Sheep direct learned controls are both inactive, preventing
one-sided herd distortion.  Quantity MAE improved from V8 to V9 for Cow
0.546→0.135, Sheep 0.177→0.098, Strawberry 1.667→0.316, and Wheat
4.108→1.545.

| Market SELL/WAIT | V9 F1 | V8 rule F1 |
|---|---:|---:|
| Wheat | 0.814 | 0.166 |
| Strawberry | 0.848 | 0.352 |
| Milk | 0.788 | 0.205 |
| Wool | 0.670 | 0.138 |
| Fertilizer | 0.546 | 0.270 |

Melon had only four stock-bearing test examples and is disabled regardless of
its nominal score.  Demand stratification still favors V9: for zero-demand
states, F1 is 0.897 Wheat, 0.837 Milk, 0.453 Wool, and 0.546 Fertilizer; for
positive-demand states it is 0.811 Wheat, 0.847 Strawberry, 0.781 Milk, and
0.805 Wool.  By time, Wheat F1 is 0.905/0.817/0.790 for days 5–11/12–19/20–26;
Milk is 1.000/0.816/0.763 where examples exist.  The late decline is recorded
instead of hidden by an overall mean.

The worst untouched intent episode has model binary Brier 0.073 versus V8
0.156; the worst market episode has 0.082 versus V8 0.370.  Episode IDs and all
per-stratum metrics are preserved in
`data/analysis/v9_decision_policy_validation.json`.

## Hypotheses tested and decisions

1. **Direct intent imitation improves macro decisions.** Supported on held-out
   episodes.  Deployment is bounded because isolated classifier quality does
   not prove safe closed-loop coupling.
2. **Cow and Sheep can be applied independently.** Rejected.  It produced an
   unintended C11/S4-style mix because both share irreversible pasture slots.
   The controls are now coupled and fail closed because Sheep failed validation.
3. **A 12-hour WAIT label can freeze hourly purchases.** Rejected.  It delayed
   growth severely.  WAIT now only preserves one herd slot while shops are
   uncertain.
4. **Same-tile and stateful mission pinning reduces waste.** Rejected for the
   submitted version.  Both variants worsened the causal diagnostics and did
   not reliably reduce FEED→MOVE, so V8's safe global assignment remains active.
5. **Opponent-aware learned market timing improves behavior.** Supported by
   held-out SELL/WAIT results and a diagnostic-only component ablation.  Hard
   financing, shed-pressure, early Fertilizer, low-confidence, and endgame
   rules still override the model.

## Closed-loop safety diagnostics

Old-agent and starter matches were used only to expose interaction failures,
not as the policy-selection objective.  On four fixed seeds in both seats, the
final V9 default completed 8/8 games.  Reward distribution was minimum 120,544,
P25 122,685, median 138,062, mean 138,839, P75 155,483, maximum 157,713.  The
same V8 diagnostic mean was 131,777.  These numbers are environment diagnostics,
not rating estimates.

Across the eight V9 replays there were zero animal-loss events, minimum
day-start cash was 17, maximum consecutive unfed and unwatered streaks were one
day, and all statuses were DONE.  Mean movement rate was 0.543 and core work
per hire 5.667.  The lower-tail seed 20269002 finished at 120,544 in both seats
without animal loss; it remains a recorded failure-analysis case rather than
being excluded.

## Reproducibility and artifacts

- Training: `scripts/train_v9_decision_policy.py`
- Component diagnostics: `scripts/run_v9_ablation.py`
- Operational/safety analysis: `scripts/analyze_local_match.py`
- Held-out report: `data/analysis/v9_decision_policy_validation.json`
- Final safety KPIs: `data/analysis/v9_final_safety_starter_seed_20269001_kpis.json`
- Final run: `data/runs/v9_final_safety_starter_seed_20269001.json`

The model training seed is 20260824.  The generated model SHA-256 is
`f82f3438b8da660c790a80dc46d2ecfafe8cfc8b6ef0c1a6fd254768818c28f2`.
On a real midgame observation, 100 warm calls measured median 5.795 ms, p95
9.126 ms, and maximum 11.327 ms on this machine.

The final submission is `artifacts/submissions/v9.tar.gz` (576,314 bytes,
SHA-256 `55a7a085b6647edc67f032678149acc5607942fa427e3894f75079fcc2d47063`).
After extraction outside the repository, the archive alone completed all 720
official-environment steps with statuses `DONE/DONE` and V9 reward 142,922 for
the smoke-test seed.

## Known limits and unverified claims

- A 3000+ rating is a goal, not a verified or guaranteed outcome.
- The untouched replay test measures expert decision fidelity, not counterfactual
  causal value or live leaderboard generalization.
- The local opponent is deliberately weak and does not reproduce top-team
  market pressure; its win rate is not a selection metric.
- Opponent hidden inventory is a public-state belief, not access to hidden data.
- Mission-level execution remains an open weakness: FEED→MOVE is still much
  higher than top trajectories.  The attempted fixes were worse, so this is
  reported rather than concealed.
- Late-period Fertilizer and Wool classification are weaker than early/midgame;
  deterministic liquidation and financing guards limit the exposure.
