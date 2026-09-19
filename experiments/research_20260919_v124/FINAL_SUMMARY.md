# V124 integrated decision record

## Outcome

V124 is the new **local challenger**, built from the attached V109-V123
analysis and the two V123 live-submission log sets. Its promoted behavior is
deliberately narrower than the initial design:

- keep V123's V120 opening, executor, weed repair, dead-SELL removal, and
  terminal liquidation;
- reconstruct the canonical turn as `24 * day + hour` for both seats;
- replace V121's broad historical continuation pool with 44 current-meta,
  day-12-compatible winning continuations;
- remove V123's farm-clone sale preemption;
- keep the tested three-day source latch and direct sale predictor in code for
  reproducibility, but disable both in the promoted configuration.

This is the strongest candidate supported by the local evidence in this run.
It is not yet a claim of a guaranteed public-ladder improvement.

## From finding to implementation

1. **V123's failure mode was after the shared opening.** The five losses to
   initially 1700+ opponents were all compatible with the day-12 portfolio,
   so a new opening or forced route splice was not justified.
2. **The old library was stale and too broad.** Across 130 completed,
   non-draw V123 live games, the builder selected winner continuations only
   when opponent initial rating was at least 1600 and day-12 portfolio L1
   distance from V123 was at most 5. This produced 44 continuations: 15 V123
   wins and 29 opponent wins.
3. **Runtime identity leakage was excluded.** The policy artifact contains
   only the existing six-field continuation rows. Episode/submission IDs,
   names, exact ratings, outcomes, rewards, and future observations are not
   runtime features.
4. **Three-day coherence was a plausible but rejected hypothesis.** It won
   the first 12-game screen, then lost the decisive same-seed fresh comparison
   to adaptive per-turn routing.
5. **Direct sale forecasting was also rejected.** Once training examples were
   restricted to turns on which the overlay could safely intervene, the
   cross-submission holdout had essentially no useful coverage: Strawberry
   and Wool selected no events; Milk selected four events and only one was
   correct. `ENABLE_SELL_FORECAST=False` prevents this weak model from changing
   promoted actions.

## Ablation results against V123

| Policy | Seeds | W-L | Mean margin |
|---|---:|---:|---:|
| Current library, adaptive router | initial 12 games | 8-4 | -125.8 |
| Current library, 3-day latch | initial 12 games | 10-2 | +762.7 |
| Current library, adaptive router | fresh 20 games | **14-6** | **+535.5** |
| Current library, 3-day latch | fresh 20 games | 10-10 | -146.3 |

The fresh same-seed result is the promotion gate: current library enabled,
segment latch disabled. Across both screens, adaptive routing was 22-10 with
weighted mean margin +287.5, but the initial screen is not treated as an
independent confirmation set.

## External-family regression panel

All rows use exactly the prior V123 seeds and four games per family.

| Opponent family | V124 W-L | V124 margin | V123 margin | Delta |
|---|---:|---:|---:|---:|
| farming_score_v3 | 4-0 | +16,226.5 | +16,566.0 | -339.5 |
| ggmljs_v16 | 4-0 | +20,067.0 | +20,307.0 | -240.0 |
| mooman_e052a | 4-0 | +6,123.0 | +6,017.5 | +105.5 |
| qeinstein_moev2 | 4-0 | +6,779.0 | +6,116.0 | +663.0 |
| shape_tetsutani | 4-0 | +6,514.5 | +5,441.5 | +1,073.0 |
| smart_farm | 2-2 | +1,724.0 | +2,765.5 | -1,041.5 |
| souvik_v4 | 4-0 | +8,543.0 | +8,385.0 | +158.0 |
| **Total / family mean** | **26-2** | **+9,425.3** | **+9,371.2** | **+54.1** |

There is no family-level win/loss regression, although Smart Farm remains a
meaningful weakness and its margin declined.

## Verification and delivery

- Ruff lint and format checks pass.
- V121/V123/V124 regression suites pass: 15 tests.
- V124-specific tests pass: 5 tests, covering the canonical clock, feature
  gates, anonymous 44-source artifact, optional segment behavior, and package
  manifest.
- The submission archive was extracted outside the source tree and imported;
  at seat 1 / canonical step 319 it returned valid `farmer`, `hands`, and
  `market` output without repository-relative files.
- Final archive: `artifacts/submissions/v124.tar.gz`
- SHA-256: `cdc74eb6ae47c53e9c2edfeea45dc55603c67ebfdba48164081458f79c4f46fc`

## Honest next gate

The direct fresh holdout is only 20 games, the external panel is four games per
family, and the continuation source data come from the same two V123 live
submissions. V124 should therefore be submitted as a challenger and retained
only if the live rating trajectory improves without repeating V123's 1700+
failure pattern. V123 remains the rollback artifact.
