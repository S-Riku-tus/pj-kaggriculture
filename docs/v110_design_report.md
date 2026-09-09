# V110 bounded market adaptation: analysis and validation

## Outcome

V110 is a conservative successor to V109.  It does not claim that the supplied
logs justify a general dynamic route library, nor that offline diagnostics map
to a rating of 3000.  It preserves V109's strong complete trajectory and
executor, adds public opponent-supply observation, and changes market timing
only in the narrow regime that has both an external strategic precedent and a
closed-loop safety check: an observed near-clone.

The initially proposed general sell-phase gate was implemented, screened, and
rejected.  This is important: the main live-log signal identifies the failure
area, but it does not by itself identify a safe intervention.

## Evidence hierarchy

1. V109 live submission 55890113: 52 downloaded episodes.  The 51 non-self
   completed episodes are the strategy corpus; the single self-play draw is
   excluded from outcome statistics.
2. Rank 1/2/3 corpus: 133 + 130 + 184 non-self episodes after the same exclusion
   rule.  These logs describe common future states and conditional diversity;
   they are not converted into independent per-turn action labels.
3. Recent public policy artifacts: V43's complete route family, the distinct
   V27 midgame continuation, and the public “Breaking the Tie” market-response
   design.
4. Episode-split observational playback, followed by both-seat closed-loop
   safety/state-coverage diagnostics.  Old versions are perturbation sources,
   not a strength-selection tournament.

## V109 live facts

The 51 non-self episodes produced 37 wins and 14 losses.  Mean reward was
91,624.67, median 92,880, P10 59,956, and minimum 36,107.  Mean final margin
was +9,523.65, but P10 was -7,330 and the minimum was -23,223.  The lower tail,
not the positive mean alone, is the relevant gap.

Mean money gap by future checkpoint was:

| Step | Approximate day | Mean gap | P10 gap |
| ---: | ---: | ---: | ---: |
| 24 | 1 | +121 | +91 |
| 72 | 3 | +209 | +127 |
| 168 | 7 | +653 | -471 |
| 264 | 11 | -1,938 | -8,042 |
| 432 | 18 | +4,999 | -3,191 |
| 480 | 20 | +5,062 | -3,395 |
| 528 | 22 | +5,946 | -5,700 |
| 648 | 27 | +6,230 | -6,972 |
| 719 | final | +9,524 | -7,330 |

Five losses were ahead at day 18; four were still ahead at day 20.  Therefore
late reversals are real, but they coexist with losses that were already behind.
A single late-risk rule cannot explain or fix the whole lower tail.

V109's execution remains strong: productive actions per hire averaged 11.65,
hand PASS was about 5.70%, Sheep loss was zero, and Cow loss averaged 0.098 per
episode.  The primary strategic limitation remains portfolio rigidity.  At day
20 the 51 non-self games contained only 10 portfolio vectors, and the dominant
`15 Wheat / 37 Strawberry / 4 Melon / 11 Cow / 4 Sheep` vector appeared 35
times.  In contrast, the non-self top corpus contained 126/133, 128/130, and
108/184 distinct day-20 vectors for ranks 1, 2, and 3.

This diversity is evidence for conditional continuations, not permission to
splice trajectories.  A route library needs complete executable continuations
and lineage-disjoint future-state support.  The current corpus contains many
different outcomes but does not provide that missing action-safe bridge from a
V109 state into each top continuation.

## Replay phase alignment correction

In a replay, an action chosen from state `t` is stored on state `t + 1`.
Associating the stored action with the later observation shifts every apparent
sale phase by one.  After aligning actions to their decision state, V109's
Strawberry sale quantity is concentrated at phase 1 (60.76%), not phase 2.
Melon is also phase 1-heavy (63.95%), Milk is 47.92% phase 1, and Wool is split
between phases 1 and 2.

Opponents in the 51-game live corpus are earlier: 71.96% of Strawberry, 71.63%
of Melon, and 61.54% of Milk sale quantity occurs at phase 0.  This confirms a
timing mismatch.  It does not prove that moving V109's sale earlier is valuable,
because a phase-0 Town purchase can restore price before the planned V109 sale.

## Hypotheses, tests, and decisions

| Hypothesis | Evidence/test | Result | Decision |
| --- | --- | --- | --- |
| general opponent phase predicts profitable preemption | frozen gate replayed over 51 whole episodes with SHA1 60/20/20 episode split | 27 events; mean logged future quote advantage -15.59; positive rate 0%; train/validation/test means all negative | rejected and disabled |
| a looser phase gate will find more useful cases | earlier screening variants | hundreds of events but broadly negative quote support | rejected |
| exact/repeated trajectory similarity can bound the externality | public farm signatures over time, no identity/private data | V109-like source reaches confidence; starter and public V27 remain at zero | adopted as the only production gate |
| moving a clone-planned premium sale earlier is execution-safe | four both-seat V109-state diagnostic games | all complete, zero animal loss, minimum margin +125 | adopted as diagnostic-supported, not rating-proven |
| second-order counter is always needed | require an inferred matching opponent sale after our H4 action | did not activate against unmodified V109 | conditional code retained; live benefit unverified |
| a six-route dynamic portfolio should be added immediately | top future-state diversity vs available complete compatible routes | strategic motivation is strong, but compatible continuation/counterfactual support is absent | deferred rather than guessed |

The rejected phase result is in
`data/analysis/v110_rejected_phase_gate.json`.  The final production playback,
with that gate disabled, records zero action changes across all 51 V109 live
episodes in `data/analysis/v110_live_strategy_analysis.json`; none of those
opponents met the near-clone confidence gate.  This verifies abstention, not
improvement.

## Architecture and safety boundary

The strategic/execution flow is:

1. V109 selects and executes a complete `default`, `yarn_first`, or
   `yarn_second` route.
2. V110 reconstructs `step` if necessary and observes only public farm, Town,
   and market state.
3. Market inventory delta plus visible Town demand minus V110's effective sale
   estimates the opponent's premium supply.  Actor `DROP`, `PICKUP`, and
   `PLACE` are projected before computing effective shed availability.
4. Repeated near-equality of public farm signatures raises clone confidence.
5. Only at sufficient confidence may one existing route-planned premium sale
   be moved at most four turns earlier.  The route's field actions, feeding,
   movement, purchases, resource checks, and action alignment remain V109's.
6. If confidence is absent or decays, V110 abstains.  Phase estimates remain
   diagnostics only.
7. If V109 detects a critical broken state, its latched model-disabled V11
   deterministic fallback owns the entire action; V110 never overlays it.

Runtime logic uses no opponent identity, team name, rating, hidden shed, or
submission metadata.  This limits opponent-specific overfitting to observable
behavioral similarity, though similarity false positives remain possible and
require live monitoring.

## Multi-metric closed-loop diagnostics

`data/analysis/v110_diagnostics.json` contains 12 games: three state sources,
two new seeds, and both seats.

| State source | Games | Completed | Reward min | Margin min | Utilization min | Animal loss | Normal fallback | Market intervention |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| starter | 4 | 4 | 122,616 | +119,016 | 94.70% | 0 | 0 | none |
| distinct public V27 | 4 | 4 | 56,443 | +2,966 | 94.70% | 0 | 0 | none |
| V109 state source | 4 | 4 | 75,823 | +125 | 94.67% | 0 | 0 | clone-H4 only |

Win counts are deliberately labelled diagnostic-only in the JSON.  The sample
is too small for a competitive win-rate conclusion.  Its purpose is to expose
invalid actions, resource accidents, seat dependence, inappropriate gate
activation, and lower-tail crashes.

The forced step-168 fallback stress in
`data/analysis/v110_forced_fallback.json` completed both seats, activated the
latched fallback in both games, and lost zero animals.  It verifies graceful
operation after an artificial switch, not optimal play in unknown states.

## Reproduction

```powershell
.\.venv\Scripts\python.exe scripts\analyze_replay_corpus.py --corpus v109=data\submissions\v109_submission_55890113 --output data\analysis\v110_v109_corpus.json --details data\analysis\v110_v109_episodes.csv
.\.venv\Scripts\python.exe scripts\analyze_v110_live_strategy.py
.\.venv\Scripts\python.exe scripts\analyze_v110_live_strategy.py --screen-rejected-phase-gate --output data\analysis\v110_rejected_phase_gate.json
.\.venv\Scripts\python.exe scripts\evaluate_v110_diagnostics.py --opponent starter --opponent C:\tmp\kaggriculture-public-v27\main.py --opponent agents\v109\main.py --pairs 2 --seed 20260910
.\.venv\Scripts\python.exe scripts\evaluate_v110_diagnostics.py --opponent starter --pairs 1 --seed 20260930 --force-fallback-step 168 --output data\analysis\v110_forced_fallback.json
.\.venv\Scripts\python.exe -m pytest -q tests\test_agent_v110.py
uv run ruff check agents\v110\main.py tests\test_agent_v110.py scripts\evaluate_v110_diagnostics.py scripts\analyze_v110_live_strategy.py
.\.venv\Scripts\python.exe scripts\package_submission.py --agent agents\v110 --output artifacts\submissions\v110.tar.gz
```

## Known, inferred, and unverified

### Known from code and data

- V109's live non-self corpus has strong mean output but a materially negative
  lower margin tail and late reversal cases.
- Its day-20 portfolio diversity is far lower than the top corpus.
- The replay action phase requires a one-step correction.
- Phase-only front-running failed the frozen observational screen in every
  episode split and is disabled in production.
- Normal and forced-fallback diagnostics completed without animal loss.
- The packaged agent is self-contained and executes from an extracted archive.

### Inference

- Much of the remaining gap is likely continuation selection and market
  interaction rather than basic actor throughput.
- A lineage-aware complete route selector remains the highest-value structural
  research direction.
- Abstaining outside a supported regime is safer than installing a route patch
  whose future farm state cannot be executed coherently.

### Unknown / unverified

- V110's live rating, rating variance, and whether it improves on 1515.
- Whether enough near-clone opponents remain in the live pool for H4 to matter.
- False-positive rate of public signature similarity against unseen current
  lineages.
- Competitive benefit of the second-order branch.
- A supported Milk/Strawberry/Carrot/Tomato continuation library from compatible
  V109 states.
- Whether either V109 or V110 can exceed 3000.  No such guarantee is made.

## Promotion and next research gate

V110 is ready as a bounded live candidate, not a proven replacement by rating.
If submitted, promotion should use a confidence interval over new live games,
P10/worst margin, failures, seats, demand groups, time slices, and intervention
cohorts.  The next structural version should first collect lineage-deduplicated
same-opening/different-continuation teachers, label 24/72-hour future-state
targets, and require episode-held-out gains before adding any complete route.
