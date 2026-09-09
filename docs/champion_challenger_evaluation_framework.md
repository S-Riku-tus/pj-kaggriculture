# Kaggriculture Champion/Challenger evaluation framework

## Objective

The optimization target is paired win probability against current and future
opponent populations. Coin, margin, imitation accuracy, portfolio diversity,
animal tilt, and opponent-supply error remain diagnostics; none can promote an
Agent on its own.

Replay evidence is separated from causal policy evidence:

| Evidence | Permitted claim |
|---|---|
| E0 engine mechanics | The engine/executor behavior is understood and executable |
| E1 replay descriptive correlation | A hypothesis or state association exists |
| E2 lineage-held-out prediction | A frozen model predicts unseen lineages |
| E3 paired Gold experiment | A policy intervention changes closed-loop outcomes |
| E4 diverse meta tournament | The intervention improves a varied executable pool |
| E5 Fresh Holdout | The frozen candidate generalizes after all choices are fixed |
| E6 live ladder | The effect survives the live population |

Production promotion requires E4 and E5 by default.

E6 is observational unless the live platform itself supplies an identified
randomized or paired intervention. A rating, rating trajectory, or live W/D/L
record can establish that an entire submitted Agent is viable in the sampled
field. It cannot by itself identify which internal branch caused that result,
nor can it replace paired E3-E5 comparisons.

Opponent evidence tiers are:

- Gold: executable Agent code; valid for paired closed-loop causal evidence.
- Silver: a validated executable replay-derived surrogate; useful when its
  validation scope is explicit, but not equivalent to source Gold.
- Bronze: a recorded replay trajectory; descriptive/predictive evidence only.

## Fixed ordered decision gates

The evaluator applies these gates in order:

1. Engine Correctness / Safety
2. Behavioral Isolation
3. Trigger Causal Uplift
4. Diverse Meta Payoff Improvement
5. Robustness
6. Fresh Holdout

The first non-pass blocks all later gates. A downstream mean coin or margin
cannot rescue an earlier failure, and no single composite score is used.

Fast screening is negative-only. It may stop a clearly harmful candidate but
cannot establish strength. Formal evaluation uses unused seeds, both seats,
multiple Gold action families, and paired uncertainty.

## Pair construction

For each executable opponent action family, seed, and focal seat:

1. import fresh Control, Treatment, and opponent modules;
2. start both arms from turn 0 with the same requested seed and seat;
3. run all 720 turns from extracted standalone archives;
4. retain the engine-resolved seed and intermediate statuses;
5. save self coin, opponent coin, margin, W/D/L, Loss→Win, and Win→Loss;
6. retain both seats inside the same seed cluster.

Replay alignment is centralized: `observation[t]` produces the action stored at
`steps[t+1]`.

## First Divergence and Behavioral Isolation

Every pair stores a First Divergence Audit for focal action, opponent action,
money, portfolio, worker position, market inventory, prices, private inventory,
and town/shop history.

The stable feedback-channel fields are `first_self_divergence`,
`first_opponent_response`, `opponent_response_lag`,
`first_market_divergence`, `first_price_divergence`, and
`first_money_divergence`. This preserves the temporal chain from our policy
change, through an opponent response, into shared-market and money effects.

For the V113 gate, action/state must be identical before step248. The first
action difference, if any, must be the single Cow2→Sheep2 market rewrite.
Downstream closed-loop differences are causal descendants. Any earlier or
structurally different action divergence invalidates the pair.

The runner now records a complete pre-intervention action fingerprint. Source
versions with identical fingerprint vectors on the frozen calibration grid are
clustered into one observed action family for lineage→seed uncertainty. Source
variant payoff rows remain available as diagnostics.

## Safety hard gate and treatment delivery

Future evaluators report two incident classes separately:

- **Hard Safety Failure** means game integrity was damaged: runtime error,
  incomplete game, materially harmful illegal/no-op action, animal/weed loss,
  negative cash, or an emitted transaction that partially committed or became
  corrupt. A candidate-new event fails Engine Correctness / Safety.
- **Treatment Delivery Failure** means the experimental branch could not be
  delivered while the game stayed valid and the baseline continuation was
  preserved. It reduces the actual-treatment sample and remains visible in the
  trigger funnel, but it is not called a catastrophic safety failure.

A delayed transaction uses `ARM -> REVALIDATE -> COMMIT / SAFE_CANCEL`. The
revalidation step must verify the intended purchase/action slot, cash reserve,
capacity, inventory, workers, route ownership, and remaining horizon. If any
precondition changed, `SAFE_CANCEL` clears the intent and emits the baseline
action exactly. A cancel is recorded once with a reason code; it must not latch
one diagnostic over every later turn. Once `COMMIT` emits an intervention,
incomplete purchase/pickup/place execution is a Hard Safety Failure.

The engine-aware audit covers:

- 720-turn completion and intermediate ERROR/INVALID/TIMEOUT states;
- Agent runtime exceptions;
- animal loss and plant→weed transitions;
- cash floor;
- fallback and OOD diagnostics;
- silent field/market no-ops and partial commits;
- conversion purchase/pickup/place completeness;
- equal seat coverage;
- archive/source/engine hash verification.

Only candidate-new regressions fail a comparative check when the same baseline
mechanical event already exists. Absolute treatment failures such as runtime
exceptions and incomplete games always fail.

## Strength and uncertainty

The primary result is a Pairwise Payoff Matrix at the independent executable
action-family level. It reports baseline/candidate win rates, paired win-score
delta, Loss→Win, Win→Loss, draws, Δself coin, Δopponent coin, and Δmargin.

Uncertainty uses a hierarchical cluster bootstrap:

`executable action family → requested seed cluster (both seats retained)`

The report includes:

- Meta-weighted paired win-score delta;
- Macro-action-family paired delta;
- major-family pairwise deltas;
- robust reweighting scenarios around the frozen meta weights;
- a diagnostic Bradley–Terry ability difference.

Bradley–Terry never replaces the matrix because Kaggriculture matchups may be
non-transitive. If all paired outcome deltas are zero, the empirical bootstrap
can be degenerate; this is reported as absence of observed discordance, not as
proof of population equivalence.

Trigger-request and emitted-transaction cohorts are reported separately. The
preregistered pre-action request cohort is the main trigger analysis. The
emitted cohort is a complier diagnostic. The all-game estimate remains the
global policy effect.

## Dataset lifecycle and registry

Each experiment has four explicit data roles: Discovery, Development,
Promotion, and Fresh Holdout. Inspecting a holdout while changing thresholds,
features, routing, or evaluation rules contaminates it permanently into
Development.

The immutable preregistration records:

- hypothesis ID;
- baseline/candidate archive and source hashes;
- evaluator and engine hashes;
- Gold opponent pool and weights;
- fast/formal seed manifests and seats;
- ordered promotion criteria;
- dataset roles and evidence policy.

The result records verified provenance, every paired audit, all ordered-gate
statuses, the payoff matrix, uncertainty, and report paths. Result files are
write-once. Any later evidence is stored in a separate posthoc assessment and
never overwrites the preregistered record. Posthoc records keep three explicit
fields: `preregistered_experiment_verdict`,
`current_research_interpretation`, and `live_ladder_evidence`. Later evidence
may change the research interpretation in either direction, but it cannot
retroactively alter the registered verdict or promotion thresholds.

## Implementation map

- `scripts/evaluation/schema.py`: evidence/tier/data enums and fixed gate order
- `scripts/evaluation/replay.py`: replay alignment and versioned action hashes
- `scripts/evaluation/runner.py`: archive-only paired Gold runner
- `scripts/evaluation/divergence.py`: First Divergence Audit
- `scripts/evaluation/safety.py`: engine-aware safety and transaction audit
- `scripts/evaluation/lineage.py`: executable action-family validation/collapse
- `scripts/evaluation/statistics.py`: payoff, hierarchical bootstrap, robust
  meta, and Bradley–Terry diagnostics
- `scripts/evaluation/registry.py`: hash verification and immutable records
- `scripts/evaluation/report.py`: ordered gates and human-readable report
- `scripts/evaluate_v113_champion_challenger.py`: frozen V113 experiment CLI

The V113 record is under
`data/evaluation/v113_cow_sheep_gate_e3e4_20260901_2024/`. Its frozen evaluator
v1 source is archived there because the general framework was conservatively
extended after the run to collapse duplicate source/action families.

See `v113_champion_challenger_evaluation_report.md` for the result and
`experiments/v113_cow_sheep_gate_e3e4/dataset_manifest.json` for the role
manifest.

The later V113 E6 observation, complete trigger-funnel reclassification, and
V14 opponent-response mediation audit are in
`docs/v113_live_e6_posthoc_addendum.md`. They are stored separately and do not
alter the preregistered result.
