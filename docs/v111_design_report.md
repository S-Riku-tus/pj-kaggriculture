# V111 design and validation report

## Outcome

V111 is a conservative, testable successor to V110.  It does not replace the
strong complete V110/V109 trajectory or its deterministic mechanics.  It adds
one public-state strategic gate learned from Rank 1–3 replays: when Yarn first
appears as the third shop and a lineage-held-out model predicts a sufficiently
strong Sheep direction 72 turns ahead, the final planned two-Cow transaction
is converted to two Sheep.

This is a candidate for live evaluation, not evidence that rating 3000 has
been reached.  V110's observed 1681.5 rating remains the latest verified live
rating supplied with this work.

## Evidence used

### V110 live submission

The local submission corpus for submission `55903573` contains 55 complete
replays and no download errors:

- result: 36 wins, 18 losses, 1 draw;
- rating metadata: 1681.5;
- mean final margin: +6,465.76;
- p10 final margin: -11,257;
- near-clone public-state cohort: 15 games, 3 wins, 11 losses, 1 draw,
  mean margin -4,159.6;
- non-clone cohort: 40 games, 33 wins, 7 losses, mean margin +10,450.28.

Near-clone status uses only public farm-state similarity.  It is not proof of
shared code.  Thirteen of the 15 near-clones first reached confidence at step
24 and two at step 48.

Action-lineage hashing found one opponent h200 lineage repeated in three
near-clone games; V110 lost all three with mean margin -5,187.  At h400 those
games separate into different lineages.  This argues against a fixed
opponent-code counter and supports public demand/future-state branching.

The live corpus also confirms the main structural limitation described in the
attachments: V110 is highly productive but remains concentrated in a small
portfolio family and almost never changes animal direction after day 12.

### V110 market overlay

Replaying V110's existing near-clone early-sale decisions against recorded
public market states produced 262 planned-sale timing observations across 11
episodes.  The logged current-minus-target quote was positive in 196, equal in
38, and negative in 28; quantity times quote difference summed to +13,903.

This is observational price support, not causal reward attribution.  It is
enough to retain V110's bounded market controller, but not to infer a rating
effect.

### Top-three teacher corpus

Training uses only complete Rank 1–3 replay states:

| Source | Episodes | Training rows | Distinct h200 lineages |
|---|---:|---:|---:|
| Rank 1 | 134 | 804 | 71 |
| Rank 2 | 131 | 786 | 113 |
| Rank 3 | 185 | 1,110 | 105 |
| Total | 450 | 2,700 | — |

Rows are observations at steps 88, 153, 216, 288, 360, and 432.  Targets are
changes in Wheat, Carrot, Tomato, Strawberry, Melon, Cow, and Sheep at 24 and
72 turns in the future.  No private opponent inventory, team identity, rating,
or submission metadata is a runtime feature.

Two independent split protocols are reported:

1. whole-episode hash split, so a game never crosses train/validation/test;
2. h200 action-lineage hash split, so a behavioral opening lineage never
   crosses train/validation/test.

The lineage protocol is the production model.  The separate episode protocol
is retained as a robustness check.

## Model results

The 72-turn model beats a zero-change predictor on both held-out protocols:

| Protocol | Test rows | Model normalized MAE | Zero-change MAE | Improvement | Material animal-direction accuracy |
|---|---:|---:|---:|---:|---:|
| Episode | 648 | 0.16038 | 0.19618 | +0.03580 | 84.46% |
| h200 lineage | 534 | 0.16030 | 0.19550 | +0.03519 | 86.15% |

The 24-turn model is disabled.  It is worse than zero-change on held-out data:

| Protocol | Model normalized MAE | Zero-change MAE | Difference |
|---|---:|---:|---:|
| Episode test | 0.07814 | 0.07670 | -0.00144 |
| h200 lineage test | 0.07843 | 0.07610 | -0.00233 |

This negative result matters: V111 does not combine a weak short-term target
with the stronger 72-turn target merely to increase action responsiveness.

## Hypotheses and decisions

### Retained: third-shop Yarn, final two-animal conversion

Hypothesis: when Yarn first becomes known as shop three, top trajectories often
move toward Sheep within 72 turns.  V110 cannot switch to its Yarn continuation
at step 216 because that route diverged earlier.  The final default-route Cow
purchase at step 248 is still mechanically substitutable.

The gate requires all of the following:

- shops 1–2 are not Yarn and shop 3 is Yarn;
- predicted `(delta Sheep - delta Cow) >= 2.0` at step 216;
- maximum standardized feature deviation is at most 4.0;
- V109's critical fallback is not latched;
- at step 248, the exact planned order is `BUY_ANIMAL COW 2`;
- current cash is at least 1,500, preserving 500 after the Sheep cost;
- the Sheep purchase appears in the shed before pickup is rewritten;
- the carrying actor visibly owns Sheep before each placement is rewritten.

Teacher direction precision is:

| Split | Active | Correct | Precision | Mean actual animal tilt |
|---|---:|---:|---:|---:|
| Episode validation | 5 | 4 | 80% | +2.80 |
| Episode test | 6 | 6 | 100% | +3.83 |
| Lineage validation | 3 | 3 | 100% | +3.33 |
| Lineage test | 5 | 4 | 80% | +2.40 |

The cohort is small, so the operation is capped at two animals.  It does not
retarget the whole farm.

### Rejected: second-shop Yarn milk veto

A prefix-compatible veto at step 153 was tested.  It looked correct on two
lineage-validation activations but failed the episode-validation activation
(0/1 correct), and lineage test had no activation.  Because the result did not
reproduce across both split protocols, `ENABLE_SECOND_YARN_VETO` is false.

### Rejected: 24-turn runtime target

The 24-turn model loses to zero-change on both held-out tests and is not read by
the runtime policy.

### Not implemented: blind anti-mirror route reversal

The near-clone failure cohort is real, but selecting the opposite animal solely
because the opponent looks similar would overfit the current pool and can
contradict residual demand.  V111 uses public demand and a top-teacher future
goal instead of opponent identity or a hard-coded inverse.

## Runtime architecture

V111 has three strategic/mechanical tiers:

1. supported third-Yarn state: the 72-turn model may request a two-animal goal;
2. uncertain, out-of-support, or mechanically unexpected state: unchanged V110;
3. critical trajectory failure: inherited V109 model-disabled deterministic
   rule fallback.

The model emits only a portfolio delta.  It cannot issue movement, feeding,
market, pickup, or placement actions.  Deterministic code performs the exact
transaction rewrite and checks private own inventory after every stage.

Changing Cow to Sheep preserves pasture type and feed cost.  Existing route
sales deliberately over-request both Milk and Wool relative to typical
availability, so the additional Wool still has executable sale slots.  The
conversion also breaks near-clone farm similarity naturally, causing V110's
clone-only market intervention to decay instead of pretending the farms remain
identical.

## Closed-loop diagnostics

Twenty-four games were run across starter, the distinct V14 lineage, and V110,
four seeds, and both seats.  Opponents are state generators; win counts are
debug-only.

- completed: 24/24;
- animal losses: 0;
- critical fallback games: 0;
- strategy OOD games: 0;
- mean action utilization by opponent group: 94.88%–94.95%;
- conversion games: 4;
- complete purchase/pickup/two-placement conversions: 4/4;
- incomplete conversions: 0;
- converted final portfolio: 9 Cow / 6 Sheep instead of 11 Cow / 4 Sheep.

The minimum cash over all V110-generated diagnostic states reached zero later
in a route.  No purchase or placement failed and no animal was lost.  This is
not described as a cash optimum; it is retained as a lower-tail warning.

V110 replay coverage says the gate would have activated in three recorded
V110 episodes: one recorded win and two recorded losses.  Those outcomes did
not select the threshold and are not counterfactual V111 scores.

## Tests and standalone artifact

- V109/V110/V111 targeted tests: 21 passed;
- full repository test suite: 211 passed;
- Ruff checks on all changed Python files: passed;
- archive layout: 17 packaged files, including the strategy model and complete
  V110/V109/fallback dependency chain;
- extracted standalone smoke: both seats completed all 720 steps with `DONE`;
- package module-path checks: passed;
- archive SHA-256:
  `85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e`.

## Reproduction

```powershell
.\.venv\Scripts\python.exe scripts\train_v111_strategy.py
.\.venv\Scripts\python.exe scripts\analyze_v111_live_opponents.py
.\.venv\Scripts\python.exe scripts\evaluate_v111_strategy_gates.py
.\.venv\Scripts\python.exe scripts\evaluate_v111_diagnostics.py --pairs 4 --seed 20261110
.\.venv\Scripts\python.exe -m pytest
uv run ruff check agents\v111\main.py tests\test_agent_v111.py scripts\train_v111_strategy.py scripts\analyze_v111_live_opponents.py scripts\evaluate_v111_strategy_gates.py scripts\evaluate_v111_diagnostics.py scripts\smoke_standalone_agent.py
.\.venv\Scripts\python.exe scripts\package_submission.py --agent agents\v111 --output artifacts\submissions\v111.tar.gz
```

After extracting the archive to a directory outside the repository:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_standalone_agent.py <extracted-directory> --seed 20261111 --output data\analysis\v111_archive_smoke.json
```

## Known, inferred, and unverified

### Known from code and recorded data

- V110's supplied live rating is 1681.5 and its 55-game replay corpus is
  materially stronger than V109's earlier rating evidence.
- V110 performs well outside the near-clone cohort and poorly inside it.
- Top-team future portfolio changes are predictable better than zero-change at
  72 turns under both episode and action-lineage held-out protocols.
- The 24-turn model is not good enough for runtime use.
- The retained third-Yarn direction reproduces on both validation/test
  protocols, with small cohorts.
- The deterministic transaction completed in all four closed-loop activation
  games without animal loss.
- The standalone artifact imports all dependencies from its extracted
  directory and completes both seats.

### Inference

- Part of V110's remaining gap is caused by continuation rigidity rather than
  basic execution throughput.
- A small demand-triggered animal change is more defensible than a blind
  anti-clone inversion.
- Future gains likely require a library of mechanically compatible crop and
  animal continuations, not a larger unconstrained action predictor.

### Unverified

- V111's live rating and variance;
- whether the two-animal third-Yarn change improves reward against the current
  leaderboard distribution;
- causal value of V110's market overlay despite positive logged quote support;
- robustness to unseen post-submission strategy lineages;
- rating 3000 or a top-three finish.

## Highest-value next work toward 3000

1. Build complete, prefix-compatible continuations for third/fourth-shop Yarn,
   Pet Cafe/Carrot, Bakery/Wheat, and Ice Cream/Smoothie demand.  Each route
   needs its own exact feed, sale, and horizon cleanup schedule.
2. Train a residual-demand goal that predicts opponent future Milk/Wool and
   crop supply, then validate it by action lineage.  Do not use team identity.
3. Extend the deterministic transaction layer from animals to seed
   purchase/pickup/plant cycles so crop goals can be executed without breaking
   actor alignment.
4. Add exact remaining-yield and final-liquidation value at each late decision,
   including lower-tail cash and unsold-inventory penalties.
5. Collect a new untouched top-log snapshot before selecting the next route;
   keep the current 450 games frozen as development data and use new games only
   as a final external test.

V111 deliberately solves one supported branch rather than claiming the much
larger continuation library is already complete.
