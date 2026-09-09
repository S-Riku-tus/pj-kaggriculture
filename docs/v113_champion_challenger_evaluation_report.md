# V113 generalized Cow→Sheep Champion/Challenger evaluation

Date: 2026-09-01 (JST)

## Decision

- Promotion verdict: **REJECTED_SAFETY**
- Agent archive status: **PROMISING_UNPROVEN**
- Highest supported evidence: **E2 — lineage-held-out predictive validation**
- E3 causal uplift: **not passed**
- E4 diverse-meta improvement: **not passed / not sufficiently diverse**
- E5 Fresh Holdout: **not run**
- Eligible as the base of V114: **no**

V113 must not replace Champion V111. The Treatment produced a candidate-only
fallback in 8 of 60 formal source-opponent pairs. This fails the first hard
gate, before strength metrics are considered. Even if that safety failure were
ignored, Control and Treatment had exactly the same win/draw/loss result in all
60 pairs: observed paired win-rate uplift was 0.0 percentage points, Loss→Win
was 0, and Win→Loss was 0. There is therefore no positive E3/E4 win-probability
evidence with which to promote the gate.

No two-stage gate or other new Agent feature was implemented. The only Agent
artifacts used were frozen gate-off and gate-on archives.

## Registry and frozen inputs

The formal Promotion seeds were unused before this run. The known V14 anomaly,
Top-366 replay analyses, and archive smoke tests were explicitly classified as
Development and excluded from the formal estimate.

| Item | Frozen identity |
|---|---|
| Hypothesis | `H-V113-GENERALIZED-COW-SHEEP-001` |
| Preregistration SHA-256 | `f98a86c1becf2c38170ad59f499fe70ed64b6abf16d6adf38e6bf02e4dadeb54` |
| Control archive | `85337f8390094f162e3ab7476f8e8575310e0f16aa0a9a4a2659bc3648e73871` |
| Treatment archive | `8e70f27af32ff0b469cf60d7822faf9ccf7371ba4bc0fd293de61815a752221d` |
| Evaluator v1 bundle hash | `4f234c9d0d470f580ee639e53634f87f1081a2c7ddd57b97e4e5a15c450defcc` |
| Frozen evaluator snapshot SHA-256 | `a1f6c756f1e1d4514981fa0575254e838192cc0f583a51003bcf32767a099997` |
| Engine | `kaggle-environments 1.32.7` |
| Engine source SHA-256 | `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e` |
| Immutable result SHA-256 | `70f4e3ebd86b77686247f82ff253300d5374040cc70bc96ba6d3fbdc181597d5` |
| Conservative lineage assessment SHA-256 | `98dd47e2f6742be13e78f7a0e9127bba1d481908ccb896d13c6524a0ef75fde6` |

The repository was dirty and V111/V113 were untracked at experiment time, so
the Git commit alone was not used as identity. The registry verifies archive,
opponent source, evaluator, and engine content hashes.

## Evidence and dataset semantics

| Level | Meaning | V113 status |
|---|---|---|
| E0 | Engine mechanics and executable safety | Engine/archive identities verified, but Treatment safety gate failed |
| E1 | Replay descriptive correlation | Available; hypothesis generation only |
| E2 | Lineage-held-out predictive validation | Available for the 72-turn state model |
| E3 | Paired causal experiment against executable opponents | Executed, but did not pass safety or positive-uplift criteria |
| E4 | Diverse meta tournament | Not passed; only 3 observed action families and no uplift |
| E5 | Fresh Holdout | Not run |
| E6 | Live ladder | Not available |

The latest Top1–3 corpus of 366 replays is **Development**, not Fresh Holdout,
because thresholds 1.0/1.5/2.0 were compared on it and 1.5 was selected from
those results. Any future dataset inspected while changing the threshold,
features, route condition, or promotion rule also becomes Development.

Bronze trajectories were never used as a closed-loop counterfactual. Recorded
opponent actions cannot respond to a changed focal policy and therefore cannot
establish policy-value uplift in the shared market.

## Replay predictive evidence: what it does and does not show

The 72-turn model remains strong predictive evidence about a later Top
trajectory:

- 366 total rows; 360 were in model support.
- Material-direction accuracy over the full corpus was 87.24% episode-weighted
  and 88.26% action-lineage-weighted.
- The `tilt >= 1.5` rule triggered 84/366 episodes: 22.95% coverage.
- 56/84 triggers had a material Cow/Sheep change; 56/56 moved in the Sheep
  direction.
- 28/84 triggers had no material animal change; all 28 had exactly zero actual
  Cow/Sheep tilt.
- Mean actual tilt across all 84 triggers was +2.976.

Thus `56/56` is the conditional quantity
`P(Sheep direction | trigger and material animal change)`. It is not accuracy
over all 84 triggers and is not evidence that executing Cow2→Sheep2 increases
win probability.

### Trigger lineage coverage

| Bronze action lineage | All triggers | Material | No material |
|---|---:|---:|---:|
| `a10f229861f92b52` | 24 | 0 | 24 |
| `0dcd0318abd0f126` | 16 | 16 | 0 |
| `b13621ef200b88fd` | 7 | 7 | 0 |
| `cde9a0046659f731` | 6 | 6 | 0 |
| `f70f0e3965948511` | 5 | 5 | 0 |
| `cfe5223433f05204` | 3 | 3 | 0 |
| `98d2c9b3719bfd19` | 3 | 3 | 0 |
| `deebc606ff9a7b5b` | 2 | 2 | 0 |
| `2b5a31a7e5723ae3` | 2 | 0 | 2 |
| `ce62a4dd02d1fd68` | 1 | 1 | 0 |
| `4471707031a8c0d4` | 1 | 1 | 0 |
| `2c91844b1a9df634` | 1 | 1 | 0 |
| `1845b0029ec1456b` | 1 | 1 | 0 |
| `5bb48d0cfe48fe28` | 1 | 1 | 0 |
| `b9ed84b8e0c57068` | 1 | 1 | 0 |
| `95b8e5ef7d9a72b0` | 1 | 1 | 0 |
| `b126d6ceb682268b` | 1 | 1 | 0 |
| `901f00bdaf04ac7e` | 1 | 1 | 0 |
| `29ff568db091a593` | 1 | 1 | 0 |
| `d6706fcb101dfca4` | 1 | 1 | 0 |
| `c4420e53a7f6b753` | 1 | 1 | 0 |
| `773e11831924d7c4` | 1 | 1 | 0 |
| `861ad41ad3c8ffb8` | 1 | 1 | 0 |
| `b53aa9edbaebb1a6` | 1 | 0 | 1 |
| `28a5518ec42e0bcd` | 1 | 0 | 1 |

The no-material cohort is highly concentrated: Top2 contributed 2 episodes,
Top3 contributed 26, and only four lineages were present. Lineage
`a10f229861f92b52` alone contributed 24/28 (85.7%). This concentration is why
the no-material cohort cannot be hidden behind the 56/56 conditional result.

## Bronze continuation-package finding

The post-step216 replay analysis indicates that Top animal movement is often
part of a broader continuation, not an isolated conversion. Selected
lineage-weighted correlations with actual tilt were:

- step216→360 FEED actions: +0.638;
- step216→360 CARE actions: +0.592;
- step216→360 active hand actions: +0.628;
- step216→360 hand-active rate: +0.722;
- terminal FEED actions: +0.821;
- terminal Wool harvest: +0.721;
- terminal Wool sales: +0.709;
- terminal Milk sales: −0.376.

The material and no-material lineages also differed in continuation shape:

| Lineage-weighted diagnostic | Material | No material |
|---|---:|---:|
| 144-turn FEED actions | 83.65 | 75.42 |
| 144-turn CARE actions | 85.17 | 78.00 |
| 144-turn hand-active rate | 87.45% | 83.30% |
| 144-turn Wool sold | 33.94 | 30.50 |
| 144-turn Milk sold | 39.11 | 47.00 |
| 144-turn Wheat held delta | +6.57 | +22.73 |
| Terminal Wool harvested | 230.24 | 132.99 |
| Terminal Wool sold | 233.69 | 141.00 |
| Terminal Milk sold | 166.05 | 246.67 |

This is recorded as a future **Sheep Continuation** hypothesis involving
Wheat/feed capacity, CARE/FEED service, hand utilization, and Wool/Milk sales
timing. It is E1 descriptive evidence only. No continuation package or
two-stage ARM/CONFIRM gate was added to production.

## Paired executable-opponent design

Control and Treatment were extracted from standalone archives and run from
turn 0 for the same requested seed and focal seat. Control had only the
generalized gate disabled; Treatment had only that gate enabled. Both had the
premium-order experiment disabled.

- Fast negative screen: 5 executable sources × 1 seed × 2 seats = 10 pairs.
- Formal Promotion cohort: 5 executable sources × 6 unused seeds × 2 seats =
  60 pairs, or 120 complete games.
- First-divergence reproduction: V14, seed 20260901, focal seat1; excluded from
  Promotion estimates.
- All Control/Treatment games used 720 turns and a fresh opponent import.
- Both seats remained in the same seed cluster in the hierarchical bootstrap.

The five executable source variants were Gold, but source identity was not
equivalent to independent action-lineage identity. The formal turn200 Control
fingerprint vector was identical for `gold_v11`, `gold_v14`, and `gold_v18`
over every formal seed and both seats. The conservative assessment therefore
collapses the pool to three observed action families:

| Observed action family | Executable sources | Frozen proxy weight |
|---|---|---:|
| `action_family_227d04476287` | V11, V14, V18 | 0.60 |
| `action_family_ced7dd42bab8` | public V27 | 0.20 |
| `action_family_0013ef3496d9` | public V43 | 0.20 |

This collapse is a post-run conservative correction and cannot upgrade the
result. It reveals that the preregistered minimum of five independent action
lineages was not met. Future experiments now record the complete
pre-intervention action fingerprint and must freeze action families before
the Promotion cohort.

The 0.20-per-source weights were an explicitly frozen equal-Gold proxy. No
defensible mapping exists from current Bronze population frequencies to these
Gold sources, so this must not be called a measured current-meta distribution.

## Ordered gates

| Gate | Formal status | Diagnostic status before short-circuit |
|---|---|---|
| Engine Correctness / Safety | **FAIL** | FAIL |
| Behavioral Isolation | Blocked | PASS |
| Trigger Causal Uplift | Blocked | INSUFFICIENT_EVIDENCE |
| Diverse Meta Payoff Improvement | Blocked | INSUFFICIENT_EVIDENCE |
| Robustness | Blocked | INSUFFICIENT_EVIDENCE |
| Fresh Holdout | Blocked | NOT_RUN |

No downstream margin, coin, imitation, or tilt metric can rescue the failed
Safety gate.

## Safety audit

| Audit | Control | Treatment | Candidate-only regression |
|---|---:|---:|---:|
| 720-turn completion | 60/60 | 60/60 | 0 |
| Runtime failure/exception pairs | 0 | 0 | 0 |
| Animal losses | 0 | 0 | 0 |
| Plant→weed events | 1,273 | 1,273 | 0 |
| Negative-cash pairs | 0 | 0 | 0 |
| OOD pairs | 0 | 0 | 0 |
| Transaction-complete pairs | 60/60 | 60/60 | 0 |
| Fallback-affected pairs | 0 | **8** | **8** |
| Seat count | 30 / 30 | 30 / 30 | 0 |

All 8 fallback cases used seed `19135103`, both seats, across source variants
V11, V14, V18, and public V27. Treatment primed the generalized goal at
step216, but the expected Cow2 purchase did not exist at step248. The inherited
executor recorded `unexpected-late-purchase-action`. Its diagnostic reason then
remained visible for 471 later observations in each affected game; this is one
failed gate attempt per pair, not 471 separate action failures. Control did not
record the fallback.

The emitted Cow→Sheep transaction was complete whenever it occurred. There
were 21 Treatment purchase rewrites in total, but 8 overlapped V111's original
third-Yarn conversion and therefore were not incremental. The generalized gate
caused 13 incremental transactions.

## Behavioral Isolation

All 60 formal pairs passed Behavioral Isolation:

- 31 inactive pairs were exact Control/Treatment identities;
- 29 pairs requested the generalized goal;
- 13 pairs emitted the intended incremental Cow2→Sheep2 rewrite;
- 16 requested pairs had no incremental action difference;
- no pair diverged before the allowed step248 intervention;
- whenever a first action difference existed, it was the expected single
  market-order rewrite with field and other market actions unchanged.

Subsequent opponent, market, portfolio, and money changes were treated as
causal descendants, not as unintended wrapper drift.

## Pairwise payoff matrix

The primary matrix below uses the three observed action families. Win rate is
strict win rate; draws would contribute 0.5 to the separate win-score metric.

| Gold action family | Pairs | Baseline WR | Candidate WR | ΔWR | L→W | W→L | Δself | Δopp | Δmargin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| public V43 family | 12 | 83.3% | 83.3% | +0.0 pp | 0 | 0 | +0.0 | +0.0 | +0.0 |
| V11/V14/V18 family | 36 | 100.0% | 100.0% | +0.0 pp | 0 | 0 | +3,174.3 | +2,154.8 | +1,019.4 |
| public V27 family | 12 | 100.0% | 100.0% | +0.0 pp | 0 | 0 | −1,535.5 | +253.3 | −1,788.8 |

For traceability, the original source-variant rows were:

| Gold executable source | Pairs | Baseline WR | Candidate WR | ΔWR | L→W | W→L | Δself | Δopp | Δmargin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| public V27 | 12 | 100.0% | 100.0% | +0.0 pp | 0 | 0 | −1,535.5 | +253.3 | −1,788.8 |
| public V43 | 12 | 83.3% | 83.3% | +0.0 pp | 0 | 0 | +0.0 | +0.0 | +0.0 |
| V11 | 12 | 100.0% | 100.0% | +0.0 pp | 0 | 0 | +3,171.8 | +2,188.8 | +983.0 |
| V14 | 12 | 100.0% | 100.0% | +0.0 pp | 0 | 0 | +3,175.5 | +2,137.8 | +1,037.7 |
| V18 | 12 | 100.0% | 100.0% | +0.0 pp | 0 | 0 | +3,175.5 | +2,137.8 | +1,037.7 |

The outcome ceiling was severe: Control and Treatment both finished 58 wins,
0 draws, and 2 losses. The paired source-proxy Meta-weighted delta and the
Macro-action-family delta were both 0.0 percentage points. The hierarchical
lineage→seed percentile bootstrap was also `[0.0, 0.0]` because every observed
paired W/D/L difference was exactly zero. This degenerate empirical interval
does **not** prove population equivalence; it means the sample contained no
discordant outcome from which a nonzero bootstrap effect could be learned.

Robust reweighting by ±0.10 around each frozen proxy weight also produced a
worst-scenario delta of 0.0 percentage points. The Bradley–Terry diagnostic
estimated Candidate-minus-Baseline ability at approximately `+0.00004`, with
an approximate 95% interval of `[-1.518, +1.518]`; this is diagnostic only and
does not override the payoff matrix or matchup non-transitivity.

## Trigger-conditional and global effects

| Cohort | Pairs | Trigger rate | Baseline WR | Candidate WR | Δ win score | L→W | W→L | Mean Δmargin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| All formal games | 60 | 48.3% | 96.7% | 96.7% | +0.0 pp | 0 | 0 | +253.9 |
| Pre-action gate requested | 29 | 100% | 100.0% | 100.0% | +0.0 pp | 0 | 0 | +525.3 |
| Incremental transaction emitted | 13 | 100% | 100.0% | 100.0% | +0.0 pp | 0 | 0 | +1,171.8 |

In the 13 incremental games, mean self coin increased by 7,372.9, but mean
opponent coin also increased by 6,201.1. This is a useful shared-market
diagnostic, not a promotion result. Multiplying a zero conditional W/D/L
effect by trigger frequency still gives a zero observed global policy effect.

Seat0 and seat1 each contained 30 formal pairs and both had exactly 0.0
percentage-point outcome uplift. Diagnostic mean Δmargin was +158.0 from seat0
and +349.8 from seat1; no outcome-level seat asymmetry was observed.

## First Divergence Audit of the historical V14 anomaly

The known V14 case was exactly reproduced and excluded from the formal
Promotion estimate:

| Arm | Self coin | Opponent coin | Relative margin | Result |
|---|---:|---:|---:|---|
| Control | 109,082 | 90,741 | +18,341 | Win |
| Treatment | 119,910 | 112,046 | +7,864 | Win |
| Treatment − Control | +10,828 | +21,305 | −10,477 | Win→Win |

The earlier eight-pair averages of `Δself = +1,353.5` and
`Δmargin = −1,309.6` came entirely from this one pair; the other seven were
exact identities. The implied average opponent gain was approximately
`+2,663.1`, also entirely from this pair.

Turn-level first differences were:

| Category | First turn | Finding |
|---|---:|---|
| Candidate action | 248 | One `BUY_ANIMAL COW 2` order became `BUY_ANIMAL SHEEP 2` |
| Self money/private stock | 249 | Treatment paid 200 more; Cow/Sheep shed stock differed |
| Self field portfolio | 257 | Control COW8/SHEEP4; Treatment COW7/SHEEP5 |
| Opponent action | 270 | V14 bought 2 Strawberry seed units in Control and 1 in Treatment |
| Opponent money benefit | 271 | Treatment-world opponent had 100 more coin |
| Opponent worker positions | 281 | First position divergence |
| Opponent portfolio | 282 | Wheat/Strawberry field mix diverged |
| Market inventory | 302 | Wheat inventory differed by one unit |
| Price | 312 | Fertilizer price was 71 vs 72 |
| Shared RNG/shop history | 432 | Final shop draw diverged: Yarn vs Ice Cream |

No focal-worker position divergence occurred. The causal chain starts with the
intended transaction, changes money and animal inventory, induces a closed-loop
opponent response, then propagates through shared inventory, prices, and the
coupled engine trajectory. This is a shared-market/executor-state externality,
not pre-trigger worker drift. It explains why increasing self coin alone was
not sufficient evidence: opponent coin increased almost twice as much in the
same case.

## Final interpretation

The strongest defensible statement is:

> Across the sampled Gold executable pool, V113 improved observed paired win
> probability by **0.0 percentage points** in every observed action family and
> harmed it by **0.0 percentage points** in every family. The sample had no
> Loss→Win or Win→Loss transition, so it provides no positive causal uplift.
> Treatment additionally introduced an `unexpected-late-purchase-action`
> fallback in 8/60 source pairs. After accounting for the fact that five source
> variants represented only three observed action families, there is no basis
> to replace Champion V111.

V113 is retained only as `PROMISING_UNPROVEN` research material. It is not a
V114 foundation. The current Promotion seeds are now spent and can never be
called Fresh Holdout. Before any related candidate returns to strength
evaluation, it must eliminate the unexpected-action fallback, pass the Safety
and Behavioral Isolation gates, use a preregistered set of genuinely distinct
and more challenging Gold action families, and then pass a truly fresh E5
holdout without changing thresholds after inspection.
