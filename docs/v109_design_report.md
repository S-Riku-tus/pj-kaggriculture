# V109 current-meta reset: analysis and validation

## Outcome

V109 replaces the V108 strategic lineage. The user-reported live result for
V108 is approximately 885, far below both the 3000 objective and the local
offline interpretation of V108. That result invalidates V108 as the main
strategy prior; V108 is not retained as an opponent-specific countermeasure.

V109 instead uses one coherent, recent public top trajectory family as its
strategic policy and adds only a narrow out-of-distribution recovery layer.
There is no claim that V109 will score 3000. Its live rating is unknown until a
real submission accumulates enough matches.

## Evidence hierarchy

1. **Primary teacher evidence:** the public notebook
   [103/128 Fresh Public V43 Sparse Shop Hybrid](https://www.kaggle.com/code/kaitofukami/103-128-fresh-public-v43-sparse-shop-hybrid?scriptVersionId=344404785).
   It documents 174 public source seat-games, chronological episode holdouts,
   actor-lineage-group holdouts, same-seed ablations, and a final untouched
   executable holdout.
2. **Game-wide teacher evidence:** the supplied analysis of Rank 1/2/3 logs:
   134 + 131 + 185 = 450 episodes, approximately 320,000 analyzed turns.
3. **Current-meta cross-check:** public leaderboard artifacts and action-lineage
   analysis, including the distinct public V27 lineage with a reported public
   score of 3090.1.
4. **Local diagnostics:** both-seat closed-loop tests across unseen seeds and
   opponent state sources. These are used for execution safety and failure
   discovery, not for promotion by old-agent win rate.

The exact V43 source is vendored at
`agents/v109/public_v43_base.py` with SHA-256
`69f06a802b62aa08f28705dab5728eb924bb6a7c23ffe0164f65b104cc3dadf3`.
Its provenance and source episode IDs are recorded in `agents/v109/NOTICE.md`.

## What is common and what is conditional

The 450-episode analysis supports these common strategic invariants:

- a highly optimized fixed opening before broad adaptation;
- three land quadrants rather than buying the fourth (450/450 in that corpus);
- convergence near 12 hands in the middle game;
- high productive-cell utilization;
- long-lived premium assets followed by late Wheat rotation;
- price-impact-aware ordering of simultaneous market orders;
- exact-horizon shutdown where CARE loses value before FEED.

The farm mix is not a universal constant. It branches with Town demand,
opponent pressure, current market inventory, and asset age. The 450-game
analysis found especially clear YARN -> Sheep, ICE_CREAM/SMOOTHIE ->
Cow+Strawberry, and PET_CAFE -> Carrot relationships, while also showing that
opponent congestion can reverse a naive demand response.

V43 implements only branches with outcome support:

| Route | Common prefix | Trigger | Status |
| --- | ---: | --- | --- |
| `default` | 719 when no branch occurs | no supported YARN event | enabled |
| `yarn_first` | 88 steps with default | first YARN event from step 88 | enabled |
| `yarn_second` | 153 steps with default | later second YARN event from step 153 | enabled |
| EGG market maker | n/a | BAKERY | disabled; no outcome-changing cases |
| separate BAKERY route | n/a | BAKERY | rejected; weak holdout support |

The route arrays differ on hundreds of later actions once selected. V109 never
splices the opening of one complete route into the middle of another.

## Future-state learning instead of action matching

The policy is a complete 719-step route family selected by sparse public events,
not a per-turn action classifier. Consequently, its object is a future farm and
market trajectory. The source notebook reports:

- chronological source holdout: default 32/38, first-YARN 4/4,
  second-YARN 3/4; first-BAKERY was only 2/7 and was not promoted;
- same-seed ablation: V43 30/32 versus fixed default 20/32 and V42 22/32;
- actor-lineage-group holdout: V43 108/116 versus fixed 90/116 and V42 45/116;
- final untouched executable holdout: 103/128, worst seat 79.7%, worst
  opponent 50%, mean margin +23,441, and no failures.

Those figures are evidence from the public notebook, not rerun measurements in
this repository and not a leaderboard guarantee.

Local diagnostics preserve checkpoints at 24, 72, 168, 264, 480, and 648
hours. Across the 34 final normal diagnostic games:

| Step | Productive tiles min/median/max | Land min/median/max | Main farm-state interpretation |
| ---: | ---: | ---: | --- |
| 24 | 16 / 16 / 16 | 1 / 1 / 1 | common opening: 7 Melon, 5 Wheat, 4 Sheep |
| 72 | 21 / 23 / 23 | 1 / 1 / 1 | 2 Strawberry added; Wheat 8--10 |
| 168 | 30 / 30 / 34 | 2 / 2 / 2 | 2 Cow + 4 Sheep; first expansion complete |
| 264 | 48 / 55 / 56 | 2 / 3 / 3 | demand branch visible; one delayed third land |
| 480 | 69 / 71 / 72 | 3 / 3 / 3 | dense premium portfolio |
| 648 | 75 / 75 / 75 | 3 / 3 / 3 | full utilization; 38--40 Wheat and 12 Carrot |

The checkpoint data are in `data/analysis/v109_diagnostics.json`,
`data/analysis/v109_vs_public_v27_diagnostic.json`, and
`data/analysis/v109_third_land_observe_only_same_seed.json`.

## Strategic layer and deterministic executor

The V43 strategic layer chooses a complete default or YARN trajectory. Its
deterministic layer then:

- aligns the action list to the currently available hands;
- repairs weed collisions without changing actor-local route progress;
- reorders only existing SELL slots using the official price-impact model;
- preserves market-order feasibility and the 10-order cap.

The unknown-state fallback loads the mature V11 executor but explicitly sets
every `MODEL`, `POLICY_MODEL`, and `DECISION_MODEL` to `None` and clears the
imitation opening. Thus its strategic targets are observation-only rules while
feeding, movement, task assignment, sales, budget reserves, and resource
constraints use the later deterministic executor.

Fallback is latched only for:

- a malformed route action;
- `consecutive_unfed >= 2` before the terminal no-value day;
- fewer than two unlocked quadrants after step 168 for two observations.

A missing third land after step 264 is observable in diagnostics but does not
switch policy.

## Hypotheses and decisions

| Hypothesis | Test | Result | Decision |
| --- | --- | --- | --- |
| V108's learned recovery can anchor the new agent | live rating | approximately 885 | rejected as strategic base |
| a recent complete route is a stronger prior than local target patches | public episode/lineage holdouts plus local closed loop | strong holdout evidence; all normal diagnostics complete | adopted |
| opponent future supply should directly gate sales | existing V22/V25/V28/V30 studies | no deployable price improvement; lower-tail failures | not integrated |
| one missed feed at hour 20 means route failure | new unseen seed | route subsequently recovered | rejected |
| any missing third land should switch to a rule policy | same-seed base/fallback comparison | fallback bought land but mean reward fell 97,961 -> 85,395 | rejected; observe only |
| model-disabled later executor is safer than V2 in foreign mature farms | forced step-480 switch, both seats | V2 lost one animal per seat; model-disabled executor lost zero | adopted |
| terminal feeding must always be forced | exact remaining-horizon analysis | no future day exists from step 696 | rejected after cutoff |

The failed V2 and third-land interventions remain in
`data/analysis/v109_forced_fallback_480.json` and
`artifacts/v109/rule_fallback_normal_smoke.json`; they are negative evidence,
not selected results.

## Multi-metric diagnostics

The final normal-policy evidence contains 34 both-seat games over distinct seed
groups and four state sources. All 34 completed; animal losses were zero and
fallback activation was zero. The 24-game repository-only diagnostic had:

- action utilization minimum approximately 94.70%;
- zero animal losses and zero fallback steps;
- reward lower tail varying strongly by demand group (minimum 54,120 against
  starter, 85,573 against V14/V108 state sources);
- minimum observed cash between 2 and 5 depending on opponent group.

Against the distinct public V27 lineage, the eight-game minimum margin was only
+49 despite a positive mean. This near-tie is retained as the relevant lower
tail rather than hidden by the 8/8 diagnostic win count.

At an intentionally forced step-480 switch, the final model-disabled rule
fallback completed both seats with zero animal loss; it produced one small win
and one small loss against the V27 state source. This verifies damage-limited
operation, not competitive strength after arbitrary policy switching.

Reproduce with:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_v109_diagnostics.py --pairs 4 --seed 20260830
```

Use `--force-fallback-step 480` only for fallback stress testing.

## Known facts, inference, and unknowns

### Known from data/code

- V108's reported live rating is approximately 885.
- The public V43 source and its documented holdouts are reproducible and the
  vendored source hash matches exactly.
- V109's final normal local diagnostics completed without fallback or animal
  loss in 34 games.
- The public V27 and V43 routes differ from step 0; they are not safe to splice.
- A third-land fallback hurt the measured same-seed score despite restoring
  the land.

### Inference

- V108 failed mainly because a narrow learned correction over a weak complete
  strategy cannot close the gap to the current route meta.
- Current leaderboard separation is more likely in continuation selection,
  opponent externalities, and rare lower-tail states than in another fixed
  opening tweak.
- V109 should be materially stronger than V108, but local matches cannot map
  that difference reliably to a rating.

### Unknown / unverified

- V109's live rating and whether it exceeds 3000.
- How much the public V43 lineage is now duplicated or countered in the live
  pool.
- Whether PET_CAFE and non-YARN lower-tail regimes need a new supported route.
- Whether an opponent-supply estimator can improve outcomes when trained on a
  newer, lineage-disjoint corpus; the existing estimator studies did not.
- Rating uncertainty and the number of matches needed for stable comparison.

## Promotion rule

Package and smoke tests are required, but live promotion should wait for a
rating interval rather than a single point estimate. Compare completion,
lower-tail reward/margin, failure logs, demand groups, seats, and time slices.
Do not select the next version solely because it beats V108.

## Final package verification

- Full repository test suite: 200/200 passed.
- Ruff checks on the V109 agent, diagnostics, smoke runner, match runner, and
  V109 tests: passed.
- `git diff --check`: passed.
- Final extracted archive smoke: both seats reached 720 steps with
  `DONE/DONE`; all runtime modules and `feature_schema.py` resolved from the
  extracted archive itself.
- Archive: `artifacts/submissions/v109.tar.gz`, 95,274 bytes.
- SHA-256:
  `d5f9211da5b14e0006800c75c7818469879b393df403419d007318b5c84357c6`.
- Build manifest:
  `data/submissions/builds/20260830_205405_+0900_v109.json`.
- Standalone result: `data/analysis/v109_standalone_smoke.json`.
