# Kaggriculture learning round 3: preregistered plan

Created before Round3 source changes on 2026-09-21 (Asia/Tokyo).

## Claims and stopping rule

Round3 is an audit-and-repair study, not a predeclared promotion.  A candidate is
`PROMOTABLE` only when serialization, the pinned Kaggle loader, actual model use,
state support, changed action, execution, economic benefit, and evaluation on
unseen conditions all pass separately.  A candidate that only falls back to C0
is `SAFE_NO_EFFECT`.  No Kaggle submission or rating claim is authorized.

The observed Round2 panel (families `mooman_e052a`, `qeinstein_moev2`,
`smart_farm`, `souvik_v4`; seeds 2026092421..2026092424; both seats) is a
development/regression set.  It will not be called an unseen holdout.

## Order of work

1. P0: reproduce the successful fixed_v3 submission contract; validate a real
   archive with pinned `kaggle_environments.agent.get_last_callable`, empty
   globals, arbitrary cwd, repository absent from `sys.path`, and NumPy blocked.
   Add content-addressed replay sidecars and reject every stale or incomplete
   replay instead of accepting a 720-state file alone.
2. P1: make candidate plans explicit contracts.  Enforce actor identity,
   materials, cash, shed capacity, time, postconditions, and safe rejoin or
   state-based replanning over the final joint action.  Add state/constraint
   fixtures for the six requested failure families.  Replace A2's untyped
   `max(std, .001)` normalization with typed support metadata.  With zero
   positive teachers, A3 remains disabled as
   `NO_POSITIVE_CANDIDATE_SUPPORT`.
3. P2: implement an engine-parity lockstep market evaluator and compare, on the
   same states/candidates, current prediction/current scorer, current prediction/
   repaired scorer, frequency/repaired scorer, unordered item oracle, and
   ordered-order oracle.  Opponent private/future actions are offline-oracle
   inputs only.
4. P3: generate bounded continuation candidates over several midgame windows,
   evaluate paired continuations against retained C0 rollouts, and train only a
   low-capacity selector if positive, executable candidates exist.  Otherwise
   record the exhausted candidate scope and expand one scope before stopping.
5. Package and run a small closed-loop comparison.  Promotion is forbidden if
   a required gate is false.

## Resources and evaluation

- Pinned engine: `kaggle-environments==1.32.7`; engine source SHA-256
  `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`.
- Measure one cold import, warm inference distribution, and one-game peak RSS
  before choosing workers.  Default to 2 workers; never silently use 16.
- Regression seeds: 2026092421..2026092424 (already observed).
- Small unseen gate: seeds 2026092501 and 2026092502, with at least one strategy
  family outside the four observed Round2 families when executable code is
  locally available.  The two seats form one family×seed cluster.
- Practical improvement threshold fixed before the unseen gate: no win-to-loss
  cluster, mean paired margin improvement at least +100, and at least one
  positive cluster.  With fewer than 8 family×seed clusters, results are
  exploratory and cannot establish promotion.
- Early stop: any invalid terminal status, loader/model failure, resource or
  continuation-contract violation, or one cluster losing more than 2,500 margin
  versus C0.  P2 is stopped if ordered oracle headroom is non-positive over the
  sampled actionable states.

## Preservation

Existing experiments, C0, models, manifests, verdicts, and submissions are
read-only inputs.  Round3 uses new study and artifact names.  Broken evidence is
quarantined by metadata; it is not deleted.  No `git reset`, `clean`, force push,
paid compute, or Kaggle submission is performed.
