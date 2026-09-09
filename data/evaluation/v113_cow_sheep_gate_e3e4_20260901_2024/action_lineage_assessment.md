# Post-run independent action-lineage correction

> This is a conservative posthoc downgrade audit. The immutable preregistered result remains the experiment record, and this assessment cannot promote V113.

# V113 generalized Cow→Sheep Champion/Challenger evaluation

- Decision: **REJECTED_SAFETY**
- Highest supported evidence: **E2_lineage_held_out_predictive_validation**
- Formal pairs: 60
- Independent action families: 3 from 5 declared executable sources
- Champion/Control: v113 wrapper with generalized gate disabled (v111-equivalent)
- Challenger/Treatment: identical archive except generalized gate enabled at tilt >= 1.5

## Ordered promotion gates

| Gate | Status |
|---|---|
| engine_correctness | FAIL |
| behavioral_isolation | BLOCKED_BY_EARLIER_GATE |
| trigger_causal_uplift | BLOCKED_BY_EARLIER_GATE |
| diverse_meta_payoff_improvement | BLOCKED_BY_EARLIER_GATE |
| robustness | BLOCKED_BY_EARLIER_GATE |
| fresh_holdout | BLOCKED_BY_EARLIER_GATE |

## Pairwise payoff matrix

| Gold executable lineage | Pairs | Baseline WR | Candidate WR | ΔWR | L→W | W→L | Δself | Δopp | Δmargin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| action_family_0013ef3496d9 (gold_public_v43) | 12 | 83.3% | 83.3% | +0.0% | 0 | 0 | +0.0 | +0.0 | +0.0 |
| action_family_227d04476287 (gold_v11, gold_v14, gold_v18) | 36 | 100.0% | 100.0% | +0.0% | 0 | 0 | +3174.3 | +2154.8 | +1019.4 |
| action_family_ced7dd42bab8 (gold_public_v27) | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | -1535.5 | +253.3 | -1788.8 |

## Primary strength estimates

- Meta-weighted Δ win score: +0.000% (95% hierarchical CI +0.000% to +0.000%)
- Macro-lineage Δ win score: +0.000% (95% hierarchical CI +0.000% to +0.000%)
- Robust worst-scenario Δ: +0.000%

Diagnostics such as coin, margin, Top imitation, and actual tilt do not override an earlier failed or insufficient gate.
