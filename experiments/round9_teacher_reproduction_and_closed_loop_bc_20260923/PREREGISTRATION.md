# Round9 preregistration

- Registered: 2026-09-23 JST, before new training or games.
- Scope: diagnose and repair independent learned BC. Teacher tapes, fixed-state resets, and oracle actions are diagnostic controls only.
- Teacher family: submission `56216119` only for the first controlled experiments.
- Positive-control episode: `109118332` (teacher seat 0, original seed `338650874`).
- Engine: `kaggle-environments==1.32.7`; the copied and installed `kaggriculture.py` must hash to `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`.
- A0: frozen `round8_spatial_bc_20260922_seed20260922_pure_v6` archive and weights.
- A1: A0 weights and feature semantics, with only legality/quantity/final resolution driven by the accepted same-turn prefix state. No plan.
- A2: retrained independent policy whose actor and market features are generated and inferred from the same accepted prefix state and causal history. No plan or teacher call at inference.
- Hybrid remains a rescue/control column, not evidence for independent learning.

## Data and splits

- Preserve the existing episode assignment from `experiments/learning_next_20260921/split_manifest.json`.
- First trajectory-overfit control uses all decisions in episode `109118332`.
- Main A2 target is 48 available train episodes and 8 validation episodes from the same teacher family, selected deterministically before training. If runtime/storage makes that impossible, retain the largest completed prefix and report the actual counts.
- Actor sampling must retain every non-movement work action and every quantity-bearing action; any movement reduction must be deterministic and stratified by day/hour rather than fixed stride.
- Market rows retain every order token, quantity, order position, and EOS.
- The four Round8 test episodes have already influenced design and are development diagnostics, not a new final holdout.
- Previously sealed ranges will not be opened. A final untouched holdout is `NOT_RUN` unless an already-authorized unused split is identified without opening labels during selection.

## Seeds and comparisons

- Learning seeds: `20260923`, `20260924`.
- Eight-game development panel per arm: opponents `v122`, `v124`; environment seeds `2026102201`, `2026102202`; both seats.
- Expansion gate: only a candidate with reproducible economic improvement on the eight-game panel advances to 16 new environment seeds per opponent and both seats (64 games).
- A0, A1, and A2 are compared separately. Archived Round8 hybrid is reported separately.

## Fixed metrics and gates

1. Exact teacher-tape replay: first divergent record and complete public/self-private state diff; final money must match before using the replay harness as a positive control.
2. Lossless codec: requested operation/item/quantity/order/EOS round-trip, with unknown and excluded rows explicit.
3. Teacher-through-decoder: request retention and engine state-effect equivalence, measured at raw, masked, ledger, plan, final command, and observed-effect stages.
4. T1/T2/T3: token, quantity, complete command, ordered market list, joint turn, and engine state-effect metrics kept separate.
5. Economy: actual purchases, pickup/place/production/harvest/deposit/sales, and cash reconciliation. Work-effect rate is never called imitation accuracy.
6. Game panel: wins/draws/losses, self money, opponent money, and margin, grouped by opponent, seat, and environment seed.
7. Promotion requires measured economic improvement; submission readiness additionally requires loader/archive isolation and an untouched holdout. No Kaggle submission is authorized.

## Negative controls

The evaluator must make the relevant reproduction, quantity, work, and/or economy metrics worse for: all-PASS, movement-only, work deletion, all quantities replaced by one, and one-step-shifted teacher actions. A denominator of zero is `null`/`NOT_APPLICABLE`, never success.

## Non-goals and prohibitions

- No Kaggle submission, no paid API, no sealed-seed access.
- No v124 inference, fixed teacher tape, or handwritten livestock plan inside the claimed independent policy.
- No overwrite of Round8 artifacts, checkpoints, raw replays, or previous results.
- No private opponent inventory, future shop/action, or final outcome in runtime inputs.

## Preregistered expansion amendment (before expanded games)

- Trigger observed on the original eight conditions: A2 mean self cash `10302.625` versus A0 `1411.875`, with the same `v122`/`v124`, seeds, and seats. This is an economic-improvement trigger, not a promotion or win claim.
- Expanded environment seeds are fixed now as `2026102301` through `2026102316`, before any expanded game is run.
- Expanded panel: those 16 seeds × `v122`/`v124` × both seats = 64 games. `v123` remains excluded.
- Primary expanded metrics remain mean self cash, mean margin, and W-D-L; opponent and seat breakdowns are mandatory. No change of metric is permitted after results are observed.
