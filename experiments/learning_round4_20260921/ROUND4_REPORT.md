# Kaggriculture Round4 report

## 1. What was fixed

Round4 is implemented in `agents/learning_round4_20260921/` without modifying C0 or the saved
Round3 evidence.

- Harvestability is a shared engine-pinned precondition over crop type, age, positive yield,
  ownership, actor, and coordinate. The step205 immature WHEAT action is blocked.
- `TypedPlan` is the single source for contract and executable primitives. A harvest contract can
  no longer describe PICKUP/FEED while executing HARVEST.
- Primitive attribution inspects the named actor's inventory/tile transition. A target flag changed
  by another actor is not credited to the later actor.
- FEED/WATER/CARE reservations follow engine actor order. Duplicate target service is blocked and
  recomputed from current state.
- Observable remaining wheat duty raises the reproduced actor5 pickup from 1 to 2. Rejoin proof
  includes identity/day, position, time, inventory, reservations, and policy state.
- Trigger, generation, applicability, scheduling, start, primitive issue/effect/failure/unknown,
  job completion, and economic evaluation are separate counters.
- The report finalizer was replaced by a pure evidence-driven evaluator with independent axes.
- During archive testing, an additional real loader defect was found and fixed: empty globals do
  not contain `__name__`, so the entrypoint now handles the resulting relative-import `KeyError`.

The before/after evidence is in `BEFORE_AFTER_TRACES.json`. Round4 tests passed 12/12; the
existing Round3 and `learning_next` tests passed 84/84.

## 2. What was actually learned

The fixed teacher key is submission `56216119`. Its current rank and private source version were
not re-verified and remain `UNKNOWN`. The local ledger contains 579 public replay episodes and
uses no opponent hidden inventory.

The existing episode-ID 70/15/15 split was preserved. Round4 selected 24 train, 8 validation,
and 8 test episodes, producing 5,760/1,920/1,920 rows with stride 3 and 19 shared train/runtime
features. It trained a four-class softmax selector for `NONE`, animal service with continuation,
harvest/land conversion, and sell/reinvest. The three skill cards have real teacher episode/seat/
step evidence and explicitly label intent as inferred.

This run performed 216 optimizer updates. Checkpoint SHA-256 is
`0276229affaf6e8b28ca374f19c926d9208b136ac108e60ea9af65f1cd5a65b2`; reload inference was
finite. Test accuracy was 0.6510 versus the majority baseline 0.5708. Test macro-F1 was 0.5914
versus 0.1817, a +0.4097 delta. These are teacher-state decision metrics, not proof of stronger
closed-loop play.

The learned runtime combines this newly trained strategy selector with the prior independently
trained, same-single-teacher BC actor/market heads from `learning_next_20260921`. Those BC heads
were reused, not retrained in Round4. The explicit-rule comparison has no model. Both share the
new deterministic executor. Action encode/decode checked 28,760 full actions with zero failures;
quantities and market order were preserved.

## 3. Did the intended actions execute?

For the two mandatory failure modes, yes: step205 is blocked before HARVEST, actor4 receives the
old FEED effect, actor5 does not, the duplicate is reserved away, and the lost pickup obligation
is detected. These assertions go through the real Round4 entrypoint as well as helpers.

The final learned archive was loaded with the pinned public `get_last_callable` from empty globals,
without `__file__`, from an arbitrary cwd, with the repository removed from `sys.path`. It completed
720 stored states as `DONE/DONE` in both seats. Each archive run made 719 strategy inferences and
had zero silent fallbacks. The rule archive passed the same two-seat checks with NumPy deliberately
blocked. The learned artifact depends on NumPy because the reused BC heads do.

Across the eight learned external-family games, the selector was called 5,752 times and changed
runtime actions. Full-policy completion does not establish coherent reproduction of the teacher's
multi-step plans, so `BEHAVIORAL_FIDELITY` remains `UNKNOWN` despite the better held-out decision
metrics.

## 4. Where did results improve or worsen?

The comparison scope was frozen before results in `CLOSED_LOOP_PROTOCOL.json`. Each family×seed
pair is one cluster; its two seats are not presented as independent samples.

| Scope / cluster | Mean margin delta, learned − rule | Seat deltas | Interpretation |
|---|---:|---|---|
| seen regression / qeinstein 2026092421 | +32,485.5 | +15,351, +49,620 | improved relative to rule |
| seen regression / smart_farm 2026092422 | −24,189.5 | −42,271, −6,108 | worsened |
| prospective local / qeinstein 2026092821 | +2,167 | −5,035, +9,369 | mixed seats |
| prospective local / smart_farm 2026092822 | −21,126 | −18,307, −23,945 | materially worsened |

The seen-regression mean over four games was +4,148. The limited prospective mean over four games
was −9,479.5. Both learned and rule agents lost all eight of their external-family games. These
opponents are local public proxies, not verified representatives of the current top field, and the
sample contains only two prospective clusters. Nevertheless, this is direct negative evidence for
this artifact relative to its rule comparison on the fixed prospective scope.

## 5. What remains unverified

- No Kaggle submission, online match, contemporaneous control, or new rating was obtained.
- No teacher-prefix 24/48/96-step state-restored plan-fidelity evaluation was completed.
- No DAgger query to the original teacher was possible.
- No per-candidate continuation-vs-KEEP economics were run for the preserved 384 scan candidates
  or the Round4 runtime candidates; full-policy terminal margin must not be assigned to each one.
- Current teacher rank/version, broader external families, cluster confidence bounds, and GPU-scale
  training were not evaluated.
- The full repository test suite was not run; only the 96 relevant tests and linted Round4 paths
  were run.

## 6. Submission and promotion decision

Two mechanically valid artifacts exist:

- learned: `artifacts/submissions/learning_round4_20260921_learned.tar.gz`, SHA-256
  `664b71ef17764fcfd526fb7b2eae16b0651bec4bdb943e3c42c2ab97ea96b340`
- rule comparison: `artifacts/submissions/learning_round4_20260921_rule.tar.gz`, SHA-256
  `6cb324f496ca216a1bd309a8cc3ae1db6eac9c2e9a9973f0325c06dcef454b3e`

They are reproducible research artifacts, not recommended submissions. The learned artifact is
`ECONOMIC_EFFECT=FAIL`, `READY_FOR_DIAGNOSTIC_SUBMISSION=FAIL`, and
`CHAMPION_PROMOTION=FAIL`. Online evidence is `UNKNOWN`. No Kaggle submission was made.

Research should continue, but this candidate should be redesigned around teacher-prefix plan
completion and the smart_farm failure trace before another bounded local panel. The negative local
result does not prohibit imitation learning as a research path and is not a permanent claim of no
headroom.
