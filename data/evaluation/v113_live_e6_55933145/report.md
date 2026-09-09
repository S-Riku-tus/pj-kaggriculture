# V113 submission 55933145 — Live E6 addendum

This addendum does not rewrite the preregistered formal result. It records post-hoc live-ladder evidence.

## Separated status fields

- Preregistered experiment verdict: `REJECTED_SAFETY`
- Current research interpretation: `LIVE_VIABLE / CAUSAL_UNRESOLVED`
- Live ladder evidence: `E6_OBSERVATIONAL`

## Coverage and result

- Raw snapshot: 59 episodes, all with 720 stored states and zero fetch errors.
- Non-public/validation episodes excluded before live-field scoring: 1.
- Public live field: 58 episodes; 44W/0D/14L.
- Strict live win rate: 75.9%.
- Final EpisodeService rating: 1676.026.
- Rating confidence/uncertainty is not exposed by the saved EpisodeService response.

## Performance by requested rating-gap cohort

| Cohort | Games | W-D-L | WR | Mean margin |
|---|---:|---:|---:|---:|
| absolute_gap_le_50 | 37 | 26-0-11 | 70.3% | 5249.4 |
| absolute_gap_le_100 | 53 | 41-0-12 | 77.4% | 7662.0 |
| opponent_plus_100_or_more | 3 | 2-0-1 | 66.7% | 5748.7 |
| opponent_minus_100_or_less | 2 | 1-0-1 | 50.0% | 6935.5 |

The <=50 cohort is contained in <=100; these are intentionally overlapping diagnostics.

## Generalized Cow→Sheep gate reconstruction

| Cohort | Episodes | W-D-L |
|---|---:|---:|
| A_gate_non_trigger | 44 | 34-0-10 |
| B_trigger_but_no_incremental_conversion | 11 | 8-0-3 |
| C_actual_incremental_conversion | 3 | 2-0-1 |

Frozen submitted-code replay fidelity: 58/58 episodes reproduced every recorded decision exactly.

A/B/C outcome differences are descriptive and highly confounded by opponent and Town regime. They are not the causal effect of the gate.

## Interpretation boundary

The local formal panel and live ladder sample different opponent populations. A 58/60 easy-panel baseline and a viable live rating can therefore coexist. E6 shows that the whole submitted Agent was live-viable; it does not identify Cow→Sheep as the cause or establish V113 > V111.
