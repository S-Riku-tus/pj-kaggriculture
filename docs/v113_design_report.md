# Kaggriculture V113: first-principles analysis and implementation report

Date: 2026-09-01 (JST)

> **Superseding status:** V113 is `PROMISING_UNPROVEN`, its formal promotion
> verdict is `REJECTED_SAFETY`, and it is not eligible as the V114 base. The
> Top-366 analysis below is Development predictive evidence, not causal policy
> value. The authoritative result is
> [the Champion/Challenger evaluation](v113_champion_challenger_evaluation_report.md).

## Executive conclusion

The replay corpus does not support the idea that the strongest agent is one
fixed route plus a few universal thresholds. Rank 1 had 66 distinct complete
action prefixes by turn 200 and 80 distinct day-20 portfolios in only 85
games. Its policy is strongly conditional on the realized shop schedule,
market, and opponent. Rank 2 and Rank 3 use progressively narrower policy
families, and V109-V111 are narrower again.

V113 therefore keeps V111's complete executor and tests one decision for which
there is E1/E2 replay-predictive evidence: the final two-animal continuation.
V111 allowed the final planned
Cow-to-Sheep substitution only after an exact third-Yarn event. V113 allows
the same already-implemented transaction whenever V111's 72-turn model is in
support and predicts a sufficiently strong Sheep-over-Cow continuation. No
new movement route, maintenance schedule, purchase quantity, or market
quantity was introduced.

This is a deliberately conservative V113. A price-priority market overlay was
implemented and causally ablated, but lost 71 coins per game on the paired
sample and was disabled. Several attractive replay correlations were also
rejected because they were already present in V111, varied by opponent
archetype, or could not be changed without breaking the complete route.

The result was initially treated as a mechanically conservative extension.
The later preregistered paired evaluation supersedes that interpretation: the
gate caused a candidate-only fallback, showed no win-probability uplift, and
is not approved for production.

## Scope and data

The analysis was rebuilt from the current engine, current executable agents,
and raw replays. The supplied historical analyses were used to identify
questions, not as proof of the answers.

The final corpus contains 580 complete games:

| Corpus | Games | Wins | Losses | Mean reward | Mean margin |
|---|---:|---:|---:|---:|---:|
| Rank 1, submission 55905066 | 85 | 82 | 2 | 105,926.8 | +24,165.0 |
| Rank 2, submission 55865730 | 147 | 82 | 65 | 94,133.3 | +3,190.5 |
| Rank 3, submission 55867591 | 134 | 89 | 44 | 86,583.9 | +3,957.8 |
| V109 | 52 | 37 | 14 | 91,104.6 | +9,340.5 |
| V110 | 55 | 36 | 18 | 91,910.1 | +6,465.8 |
| V111-A | 52 | 45 | 6 | 96,245.6 | +12,988.4 |
| V111-B | 55 | 38 | 16 | 92,450.9 | +10,876.9 |

The latest observed Rank-1 episode was 104492175, created at
2026-09-01T03:54:30Z, with an episode-result rating of 2942.85. That is a
trajectory observation from the public episode service, not a claim about the
leaderboard at the instant this report is read.

Replay actions were aligned carefully: action at logical turn `t` is stored
in replay state `t + 1`. The controlled seat was reconstructed from the full
EpisodeService response rather than the partially overwritten download
manifests. This prevents seat swaps and one-turn feature leakage.

## What the game engine implies

The installed official implementation is `kaggle-environments 1.32.7`. Its
mechanics produce several strategic invariants.

1. **Relative outcome dominates isolated production.** Goods share one
   market, so supplying one more unit changes both one's own revenue and the
   opponent's price. The correct value is residual demand after expected
   opponent supply, not a static product price.

2. **Water and feed are state-preservation controls, not symmetric production
   buttons.** A plant or animal is lost after two consecutive unserviced day
   refreshes. Crops still produce their base yield without water, and animals
   still produce their base yield without feed. Water/feed mainly gates bonus
   output and survival. Consequently the marginal value depends on death
   timer, fertilizer/care state, headroom, travel cost, and remaining horizon.

3. **The market is an ordered shared queue.** Orders are processed by slot,
   while each unit walks the price curve. Slot order therefore matters, but
   the value of moving an order cannot be inferred from its standalone quote;
   it also changes later orders and the opponent's realized price.

4. **Logistics is part of the economics.** End-of-day field inventories are
   automatically moved to the shed up to capacity, and hands/positions reset.
   Harvest timing, shed headroom, night transitions, and carrier constraints
   determine whether nominal output becomes sellable output.

5. **The game is partially observed and non-stationary.** Shop draws and
   visible opponent state reveal some future value, but hidden stock and the
   live opponent population remain uncertain. A single best response to one
   replay cluster is not a stable Nash solution.

6. **Randomness is coupled but not safely steerable from observations.** Weed
   placement and shop selection use the same RNG stream. This is analytically
   interesting, but a replay association is insufficient to justify actions
   intended to steer future shops when the hidden RNG state is not known.

## What the top agents actually do

### Conditional policies, not a universal tape

Action lineage diversity is the clearest structural difference.

| Corpus | Distinct full prefixes at turn 200 | Distinct day-20 portfolios |
|---|---:|---:|
| Rank 1 | 66 / 85 | 80 / 85 |
| Rank 2 | 17 / 147 | 42 / 147 |
| Rank 3 | 8 / 134 | 8 / 134 |
| V111-A | 14 / 52 | 12 / 52 |
| V111-B | 15 / 55 | 17 / 55 |

Rank 1 converts early observations into many different continuations. Rank 3
is closer to a small repertoire: its dominant lineage accounts for 84.3% of
games. This explains why cloning modal actions or comparing one aggregate
metric is inadequate. A useful model must predict opponent-conditioned future
supply and choose a compatible continuation, not just imitate a mean action.

### Delayed score is not weakness

Rank 1 was behind at the day-12 checkpoint in 84 evaluated games and converted
82 of those to wins. Early visible score therefore has poor causal value for
this policy family. Capital tied in fields, animals, fertilizer, future market
headroom, and route position is strategically meaningful. A controller that
panic-sells or abandons investment because of an early score deficit would
move in the wrong direction.

### Maintenance is duty-cycled, but not uniformly

Among ongoing watering actions, the share executed when survival was due was
88.1% for Rank 1, 80.7% for Rank 2, 79.4% for Rank 3, and 88.8% for V111.
This validates the first-principles duty-cycle idea, but also shows that V111
already implements the important part. Replacing its watering schedule would
not be a new source of edge.

Feed is more archetype-dependent: survival-due shares were 3.6%, 9.8%, and
20.1% for Rank 1-3, versus roughly 2.5-2.8% for V111. Rank 1 often feeds for
bonus production rather than only survival; Rank 3 economizes feed much more.
There is no single replay-supported feed threshold that safely dominates all
three policy families.

### Logistics remains a real opportunity, but not a safe overlay

Night harvest represented 21.0%, 18.5%, and 17.7% of harvested quantity for
Rank 1-3, compared with 11.9-12.4% for V111. Rank 1 also ended with exactly
zero terminal stock in all 85 games, whereas V111 averaged about two units.
This points to a genuine future route-planning objective: jointly optimize
night harvest, dawn market access, shed headroom, and terminal liquidation.

It does not, however, justify inserting isolated harvest or sell actions into
V111. Its movement and actor allocation form a complete schedule; a local
insertion changes later actor positions and can destroy the route. A robust
version needs an alternative complete continuation library or a planner, not
a one-line action override.

## Hypotheses tested and decisions

| Hypothesis | Evidence | Decision |
|---|---|---|
| Generalize the final animal mix with V111's future model | Development replay direction accuracy; later paired safety/uplift evaluation | **PROMISING_UNPROVEN; promotion rejected** |
| Water only when survival-due | V111 already matches Rank 1 at 88.8% vs 88.1% | No change |
| Globally reduce feed | Large variation across top archetypes; Rank 1 often values bonus output | Rejected as universal rule |
| Move premium SELL orders earlier | Same-seed paired ablation: -71 mean reward vs V111 | Implemented, rejected, disabled |
| Add night harvest actions locally | Strong correlation but route/actor state is coupled | Deferred to complete-route planner |
| Force terminal liquidation | Top-1 evidence is strong, but current residual stock is small and route-safe slot is unproved | Deferred |
| Use V112's fixed public route as base | Narrow open-loop behavior and poor teacher-fork diagnostics; raw-step fragility | Rejected; V111 retained |
| Steer shops through RNG consumption | Hidden RNG state and causal effect are not identified | Rejected |

The premium-order result is an important warning: a plausible local market
metric predicted the wrong intervention. Shared price curves make causal,
paired engine evaluation essential.

## Development predictive validation of the candidate gate

At turn 216, V111's existing model predicts the next 72 turns' shop/market
continuation. The audit froze features at turn 216 and compared the prediction
with the actual Rank-1-to-3 portfolio change through turn 288.

- Rows: 366; in-support rows (`max_z <= 4`): 360.
- Overall direction accuracy when Cow/Sheep composition materially changed:
  87.24% episode-weighted and 88.26% action-lineage-weighted.
- Original V111 exact-third-Yarn gate: 13 active episodes, 7 material, 7/7
  correct, 9 distinct lineages.
- Model-only `Sheep delta - Cow delta >= 1.5`: 84 active episodes, 56
  material, 56/56 correct, 25 distinct lineages, mean actual tilt +2.976.
- A looser threshold of 1.0 produced two wrong-direction Rank-1 cases.

The 1.5 threshold was selected on this same corpus because it was the broadest
tested rule with no observed wrong-direction material cases. The corpus is
therefore Development, not external or Fresh Holdout. The replay check proves
direction prediction, not the value of the transaction; the later paired
experiment found no win-rate uplift and exposed an unexpected-action fallback.

## V113 policy

V113 wraps the complete V111 implementation.

1. Canonical time is always reconstructed as `day * 24 + hour`. This avoids
   seat-specific or missing raw `observation.step` behavior.
2. At turn 216, run V111's frozen 72-turn model.
3. Reject the proposal if the model is out of support (`max_z > 4`) or its
   predicted Sheep-over-Cow tilt is below 1.5.
4. Otherwise prime V111's late animal goal.
5. At turn 248, V111 may replace its final planned purchase of two Cows with
   two Sheep. All inherited checks still apply: exact planned order, cash
   reserve, shed and pickup state, carrier capacity, placement capacity, and
   deterministic fallback.
6. If any mechanical condition fails, the complete V111/V110 route is used.

The dormant premium-first function is retained only so the rejected experiment
is reproducible. `ENABLE_PREMIUM_FIRST = False` in both source and packaged
submission.

## Closed-loop diagnostics and ablations

All diagnostic games ran both seats. Reported wins are only local debug
outcomes, not leaderboard evidence.

The final V113 run used four seed pairs per opponent (24 games total):

| Opponent | Complete | Mean reward | Min reward | Mean margin | Animal losses | Fallback/OOD | Completed conversions |
|---|---:|---:|---:|---:|---:|---:|---:|
| starter | 8/8 | 166,781.5 | 134,192 | +163,261.5 | 0 | 0 / 0 | 0 |
| V14 | 8/8 | 95,552.5 | 57,374 | +19,547.4 | 0 | 0 / 0 | 2/2 |
| V111 | 8/8 | exact tie | exact tie | 0 | 0 | 0 / 0 | 2/2 |

Against starter, six generalized goals were safely rejected by inherited cash
mechanics. Against V14, one of the two completed conversions was newly enabled
without the old third-Yarn condition. Against V111, both conversions overlapped
the old gate and therefore tied exactly.

The same-seed V111 baseline averaged 94,199 reward and +20,857 margin against
V14. V113 averaged 95,552.5 reward but +19,547.4 margin. This small sample is
mixed: V113 increased its own revenue by 1,353.5 while also benefiting the
opponent through the shared market. It establishes execution safety and new
state coverage, not a statistically proven win-rate improvement.

A four-pair ablation isolated the rejected market overlay:

- generalized gate only: exact tie with V111 in the sampled matchup, with all
  requested conversions complete;
- premium ordering only: -71 mean reward;
- both overlays disabled: exact identity with V111.

## Limits and next research frontier

No finite offline replay analysis can establish that nothing remains to learn.
The current evidence supports these next investments, in order:

1. Build several **prefix-compatible complete continuations** covering crop
   mix, night harvesting, terminal liquidation, and Cow/Sheep allocation.
   Switching only at validated synchronization points avoids route corruption.
2. Train an **opponent hidden-stock and future-supply model** from public
   observations, then price each continuation against residual demand rather
   than predicting the top agent's action directly.
3. Evaluate policies on **lineage-held-out replays and a paired population
   matrix**, not only random seeds against one baseline. Use a small robust
   portfolio if the game remains materially non-transitive.
4. Submit controlled candidates live and update from rating confidence
   intervals. Offline rewards from the debug engine are necessary safety
   evidence, but the live population determines rating.

V113 is retained as research material for that architecture. Prediction is
separated from execution, but the current generalized gate did not pass the
ordered promotion gates and must not be used as the next production base.

## Verification and deliverable

- The complete repository test suite passed.
- Ruff passed for the V113 agent, tests, replay analyses, and evaluator.
- The packaged archive was extracted into a clean directory and completed a
  720-step game from both seats. Every runtime module and the frozen strategy
  model resolved from inside the archive.
- Submission artifact: `artifacts/submissions/v113.tar.gz`
- SHA-256:
  `3e78b1c464762b9a1b7f5bf86e8513f1d465215ea83bb93247d2e858f4a23ebc`
