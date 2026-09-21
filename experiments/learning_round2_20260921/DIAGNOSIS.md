# Round-2 narrow diagnosis

## A: KEEP_C0 and the first shared break

- KEEP_C0 is exact on 719 saved observations and on two 720-state closed-loop games (both seats): structured joint actions, public/private states, status, and rewards all match C0. The wrapper calls C0 once, performs read-only shadow encoding, and returns the complete C0 action for KEEP.
- Both old learned A and old non-learned A first diverge at turn 4. C0 intended main-farmer `PICKUP WHEAT` and hand-4 `PLACE COW`; the old executor emitted `DROP` for both. At turn 5, C0 has shed WHEAT 4 after reserving one unit and has placed the cow, while the replacement has shed WHEAT 5, COW 1, and SHEEP 2. The first missing premise is therefore not model fit: primitive substitution discarded C0's actor plan, item reservation, and continuation/rejoin contract.
- The exact before/action/after records for learned and non-learned variants and both seats are in `first_failure_cases.json`.

## A: what 97.7% measured

- Old A optimized weighted cross-entropy for an 11-class selected operation. It did not score a runtime choice set as `Q(obs,candidate)`, did not optimize a job result, and did not reconstruct item/quantity/full joint action.
- The 275-wide row contains observation, self history, and actor state; it contains neither a candidate operation nor the selected teacher target. Thus there is no direct feature/label copy, but the objective is still a primitive classifier rather than the claimed higher-level selection problem.
- Test controls: learned 0.977091, candidate-generator priority 0.638229, time-only lookup 0.481138, majority 0.383135, shuffled-label time lookup 0.383135. These controls do not turn class accuracy into economic/job accuracy.
- CARE 18,837 and HARVEST 64,942 examples were excluded. Runtime only intervened at a C0 work boundary; an unavailable selected token became PASS/fallback except for the special FEED job.

## BC: representation/decoder ceiling

- Across 88 teacher test episodes, operation coverage is 1.0, but actor full-field exactness is 0.980817, market full-field exactness is 0.646795, and full joint-action exactness is 0.597863.
- The first failure is already turn 0: teacher `BUY_PRODUCT WHEAT 5` becomes quantity 3. `bc_quantities.json` supplies a train-token median and replaces the example-specific quantity at decode, so its presence does not make quantity recovery lossless.
- Actor order, market-slot order, and end-of-sequence are represented. A separate BC2 probe uses canonical full joint actions instead of this lossy decoder and is explicitly only a short teacher-forced capacity test until closed-loop integration exists.

## B: time and terminal handling

- The 850 replays contain 612,000 stored states but 611,150 decisions. Old B sampled 612,000 even-index/seat feature rows and silently shortened tail horizons with `min(last_state, step+horizon)`.
- B2 preserves the frozen feature rows for comparison but adds an item-by-horizon censoring mask; missing future decisions are excluded from loss and metrics instead of becoming ordinary zero-supply labels.
- Runtime history is updated from the focal agent's actually emitted prior market orders. Opponent private state and future teacher actions are used only to reconstruct offline labels, never as runtime inputs.

Machine-readable evidence: `keep_c0_identity.json`, `first_failure_cases.json`, `feature_target_audit.json`, `action_roundtrip.json`, and `terminal_audit.json`.
