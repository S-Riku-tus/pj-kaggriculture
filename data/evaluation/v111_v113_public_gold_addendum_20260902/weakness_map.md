# V111/V113 executable-family Weakness Map

This map treats V111 as the clean causal control and V113 as the live-validated benchmark. Aggregate loss signals are diagnostics, not causal Best-Response proof.

- Independent executable families: 14
- Close-matchup families (either arm 30–70% WR): `[]`
- Below-50% families: `[]`

| Family | Panels | V111 WR | V113 WR | ΔWR | V111 margin | V113 margin | L→W | W→L | Priority |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| gold_public_0b7f92b9 | regression, sensitivity | 83.3% | 83.3% | +0.0% | +18987.2 | +18987.2 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_46d78f69 | regression, sensitivity | 83.3% | 83.3% | +0.0% | +18669.8 | +18669.8 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_a6f1291b | meta, regression, sensitivity | 83.3% | 83.3% | +0.0% | +19198.0 | +19198.0 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_1f13714f | meta, regression, sensitivity | 100.0% | 100.0% | +0.0% | +9274.5 | +9274.5 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_30c5a82e | regression, sensitivity | 100.0% | 100.0% | +0.0% | +28992.0 | +28992.0 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_3ddfa626 | meta, regression, sensitivity | 100.0% | 100.0% | +0.0% | +50997.5 | +50997.5 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_552d0330 | regression, sensitivity | 100.0% | 100.0% | +0.0% | +43688.3 | +43688.3 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_728728d6 | meta, regression, sensitivity | 100.0% | 100.0% | +0.0% | +38586.4 | +38989.1 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_9ddbfb07 | regression, sensitivity | 100.0% | 100.0% | +0.0% | +19490.9 | +19350.0 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_aa5d5586 | regression, sensitivity | 100.0% | 100.0% | +0.0% | +23143.6 | +23143.6 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_acfb3cab | regression, sensitivity | 100.0% | 100.0% | +0.0% | +41716.7 | +41642.8 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_b6f3732a | regression, sensitivity | 100.0% | 100.0% | +0.0% | +24693.2 | +24693.2 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_d3edb8ec | regression, sensitivity | 100.0% | 100.0% | +0.0% | +19680.8 | +19680.8 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_public_fcc926c5 | regression, sensitivity | 100.0% | 100.0% | +0.0% | +11923.2 | +11923.2 | 0 | 0 | REGRESSION_OR_CALIBRATION |

## Family diagnostics

### gold_public_0b7f92b9

- V111 loss signals: `['late_cash_reversal_after_major_checkpoint_lead']`
- V113 loss signals: `['late_cash_reversal_after_major_checkpoint_lead']`
- Lead→loss (major checkpoints): V111 `2`, V113 `2`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_46d78f69

- V111 loss signals: `['late_cash_reversal_after_major_checkpoint_lead']`
- V113 loss signals: `['late_cash_reversal_after_major_checkpoint_lead']`
- Lead→loss (major checkpoints): V111 `2`, V113 `2`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_a6f1291b

- V111 loss signals: `['late_cash_reversal_after_major_checkpoint_lead']`
- V113 loss signals: `['late_cash_reversal_after_major_checkpoint_lead']`
- Lead→loss (major checkpoints): V111 `2`, V113 `2`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_1f13714f

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_30c5a82e

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_3ddfa626

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_552d0330

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_728728d6

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `275.0`; response lag median: `27.0`
- Opponent response components: `{'market': 1}`

### gold_public_9ddbfb07

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_aa5d5586

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_acfb3cab

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_b6f3732a

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_d3edb8ec

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_public_fcc926c5

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

## Selection guardrail

Select one large, repeated, experimentally targetable loss regime only after loss-case review; do not infer a V114 rule from aggregate labels alone.

Every family or seed used in common probes or this benchmark remains Discovery/Development and cannot later be relabeled Fresh Holdout.
