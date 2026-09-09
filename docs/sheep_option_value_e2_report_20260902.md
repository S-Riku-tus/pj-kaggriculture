# Sheep option value lineage-held-out test

Date: 2026-09-02  
Hypothesis: `H_OPTION_PRESERVING_SHEEP_EXPANSION_001`  
Dataset role: Development  
Result: `FAIL_E2_PREDICTION`

## Scope

The feature set, mechanical thresholds, model, and pass rule were frozen in
[`preregistration.json`](../experiments/sheep_option_value_e2_20260902/preregistration.json)
before feature extraction. The test asks only whether step216 option-state
features predict observed Top-policy Sheep expansion by step288 on a held-out
action lineage. It does not test whether option preservation improves wins.

The machine-readable result is
[`result.json`](../data/analysis/sheep_option_value_e2_20260902/result.json).

## Coverage and result

- 366 source episodes, 84 frozen trigger episodes.
- 25 exact h200 action lineages.
- 21 material Sheep-expansion lineages and four no-material lineages.
- Every material row retains `Cow delta = 0`; the label is Sheep expansion,
  not Cow replacement.

Balanced L2 logistic regression was fit on lineage means with
leave-one-lineage-out standardization and fitting.

| Metric | Frozen threshold | Observed | Pass |
|---|---:|---:|---:|
| Sensitivity | >= 70% | 76.19% | yes |
| Specificity | >= 75% | 50.00% | no |
| Balanced accuracy | >= 72.5% | 63.10% | no |
| Brier score | <= 0.25 | 0.1971 | yes |
| ROC AUC | diagnostic | 0.7143 | n/a |

The confusion matrix is 16 TP, two FP, two TN, and five FN. The positive class
dominates 21/25 lineages, so raw 72% accuracy is below the 84% accuracy of an
uninformative always-positive classifier and is not evidence of a useful
selector.

The independently frozen mechanical rule required two free pasture slots,
500 coins after paying for two Sheep, non-negative three-day feed surplus, and
at least eight prior slack actor-actions. It predicted no positive lineage:
zero TP, zero FP, four TN, and 21 FN.

## What the frozen features show

Values are lineage-weighted means at step216 or over the frozen prior window.

| Feature | Material 21 | No material 4 | Difference |
|---|---:|---:|---:|
| Free pasture slots | 0.524 | 1.000 | -0.476 |
| Cash after buying two Sheep | +84.9 | -84.8 | +169.7 |
| Three-day feed surplus after two Sheep | -24.20 | -12.09 | -12.10 |
| Prior worker slack rate | 23.82% | 17.06% | +6.77 pp |
| Prior mean hands | 9.19 | 8.43 | +0.76 |
| Wool-minus-Milk residual-demand proxy | 28.54 | 23.61 | +4.92 |
| Wool-minus-Milk price | 40.45 | 48.35 | -7.90 |
| Wool-minus-Milk market scarcity | 7.57 | 0.86 | +6.70 |

Static pasture and feed reserve move opposite the simple option-preservation
prediction. Most material lineages have zero or one free pasture at step216,
and their frozen three-day feed balance is substantially negative. Cash,
worker slack, hands, and public Wool scarcity move in the hypothesized
direction, but together they do not discriminate the four held-out
no-material lineages reliably enough.

## Interpretation

The broad economic idea of future flexibility is not disproved. The tested
version is: **reserve the resources statically at step216**. That version fails.
The observed Top policies often expand Sheep despite lacking two prebuilt free
pastures, immediately spendable cash plus reserve, or a static three-day Wheat
surplus. Their option appears to be implemented by a dynamic pipeline that can
build pasture, generate/release cash, acquire Wheat, hire labor, and place
Sheep over the following 72 turns.

This distinction matters for Agent design. “Keep two pasture slots and feed in
reserve” is not supported and should not be added to V111. A future study would
need trajectory-level option features such as time-to-build capacity,
cash-generation capacity, committed worker routes, reachable shed inventory,
and closed-loop feasibility under newly revealed shops. Those are new
hypotheses and require a new preregistration and unseen action lineages; the
failed thresholds here must not be retuned and relabeled as E2.

## Decision

- No V114 option-preservation branch.
- No Cow-to-Sheep replacement inference.
- Retain Sheep expansion / Wool continuation as an E1 research direction.
- Formal E2 support for the frozen static option-value hypothesis was not
  obtained.

