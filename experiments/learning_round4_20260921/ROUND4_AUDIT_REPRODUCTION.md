# Round4 audit reproduction

## Scope and preservation

The supplied audit archive was extracted under `audit_input/` and run against the preserved
`experiments/learning_round3_20260921.zip`. The audited input SHA-256 was
`51f5625762895a782f34989dd2db32f1d09343ff6ff49704695254e4f1d8e870`.

The starting commit was `688a9d28782af1b1a416b98f2267325dc0011398` on `main`. The starting status and diff are saved
as `INITIAL_GIT_STATUS.txt` and `INITIAL_GIT_DIFF.patch`. Existing Round3, C0, old models,
replays, decisions, and holdout ledgers were not overwritten. All Round4 implementation and
evidence were added in new Round4 paths.

The final tracked diff differs from the initial capture by one added WHEAT market-parameter line
in the already modified Round3 `market.py`. Round4 does not write that path and its provenance is
unknown, so it was not reverted. Both snapshots and `WORKTREE_PRESERVATION.json` retain this fact.

## Reproduced findings

| Finding | Result | Evidence |
|---|---|---|
| 16 saved replay integrity checks | reproduced | `audit_reproduction/replay_integrity.json` |
| 41 manifest hash checks | reproduced | `audit_reproduction/replay_integrity.json` |
| step205 immature WHEAT harvest | reproduced | `audit_reproduction/source_contract_audit.json` |
| step435 duplicate FEED missed by old validator | reproduced | same |
| step436 false `PROVEN_REJOIN` | reproduced | same |
| positive synthetic margins ignored by fixed finalizer | reproduced | `audit_reproduction/report_literal_mutation_tests.json` |
| synthetic ERROR status ignored by fixed finalizer | reproduced | same |

The bundled audit itself did not run a new simulator game, train a model, or submit anything.
Those activities are not retroactively attributed to it.

## A: immature harvest before and after

The saved qeinstein replay at seed 2026092421, seat 0, step205 has actor4 on WHEAT planted on
day7 while the observation is day8. `yield_units=1`, but the crop age is one day and WHEAT first
harvest maturity is two days. The old action was `HARVEST`; inventory and tile were unchanged.

Round4 derives both the typed contract and primitive from the same harvest plan. The common
precondition returns `HARVEST_PRECONDITION_FAILED:IMMATURE`, emits `PASS`, and appends
`HARVEST_PRECONDITION_FAILED` plus `ECONOMIC_HYPOTHESIS_UNTESTED`. It does not schedule a trip
to the shed. The exact before/after trace is in `BEFORE_AFTER_TRACES.json` and is exercised
through the submission-style rule entrypoint in `tests/test_learning_round4.py`.

## B: duplicate service and lost continuation before and after

The saved step435 action sends actors4 and 5 to FEED the same animal. The observed inventory
transition attributes the effect to actor4 (WHEAT 5→4); actor5 stays at WHEAT 1, so the target
flag alone cannot establish actor5's primitive. Round4 reports actor5 as
`FEED_TARGET_CHANGED_BY_OTHER_ACTOR` rather than completed.

At step434, the repaired continuation changes actor5's `PICKUP WHEAT 1` to `PICKUP WHEAT 2`
from observable remaining duties. At step435, engine-order target reservation keeps the first
effective FEED and replaces the duplicate with a state-derived continuation. Rejoin proof now
requires actor/day identity, time, inventory, material reservations, and policy-state digest.
There is no hidden source-policy cursor restore.

The exact-state repair assertions were run, but an engine fork from step434 with full hidden RNG
was not available; therefore the repaired branch's terminal economic value is not claimed from
this regression alone.

## C: evaluator reproduction and replacement

The audit's artificial positive-margin and ERROR-status mutations both left the old report
unchanged, confirming that its conclusion was literal-driven. Round4 replaces it with the pure
`evaluate_artifact(metrics, provenance, purpose, thresholds)` function. JSON and Markdown are
rendered from the same returned object. Tests cover positive/negative economics, no activation,
execution failure, missing data, stale hashes, rules, load-only models, invalid fallback,
skill-only evidence, win/loss tradeoff, missing plan completion, and an explicit bounded
diagnostic block.

## Reproduction limits

- The audit did not prove that a previously strong completed agent was rejected.
- Round3's 384 generated candidates still lack individual continuation-vs-KEEP economic runs.
- The Round4 exact A/B traces repair the observed bugs; they are not claims of positive profit.
- No online match or rating was obtained.
