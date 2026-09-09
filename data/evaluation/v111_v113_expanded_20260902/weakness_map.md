# V111/V113 executable-family Weakness Map

This map treats V111 as the clean causal control and V113 as the live-validated benchmark. Aggregate loss signals are diagnostics, not causal Best-Response proof.

- Independent executable families: 15
- Close-matchup families (either arm 30–70% WR): `[]`
- Below-50% families: `['gold_family_22_f835f763']`

| Family | Panels | V111 WR | V113 WR | ΔWR | V111 margin | V113 margin | L→W | W→L | Priority |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| gold_family_22_f835f763 | meta, sensitivity | 8.3% | 25.0% | +16.7% | +0.0 | +520.3 | 0 | 0 | BOTH_CONTROLS_WEAK |
| gold_family_02_01651da9 | regression, sensitivity | 91.7% | 91.7% | +0.0% | +15779.7 | +15779.7 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_08_4fcc1724 | regression, sensitivity | 91.7% | 91.7% | +0.0% | +2552.5 | +2460.2 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_06_2e4e06f7 | meta, regression, sensitivity | 100.0% | 100.0% | +0.0% | +22250.2 | +21807.3 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_07_35af8bcc | regression, sensitivity | 100.0% | 100.0% | +0.0% | +21565.4 | +20872.9 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_09_55d707fe | meta, regression, sensitivity | 100.0% | 100.0% | +0.0% | +26164.7 | +26164.7 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_10_595361e4 | regression, sensitivity | 100.0% | 100.0% | +0.0% | +18542.5 | +19232.5 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_11_63b5d789 | regression, sensitivity | 100.0% | 100.0% | +0.0% | +23447.3 | +23447.3 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_13_87cc7b78 | regression, sensitivity | 100.0% | 100.0% | +0.0% | +19708.5 | +20398.5 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_14_9aa44dd2 | regression, sensitivity | 100.0% | 100.0% | +0.0% | +17678.4 | +18582.8 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_15_af440239 | meta, regression, sensitivity | 100.0% | 100.0% | +0.0% | +26143.2 | +26143.2 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_16_b0b3c33c | regression, sensitivity | 100.0% | 100.0% | +0.0% | +18399.8 | +18271.7 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_19_d4e09ee0 | meta, regression, sensitivity | 100.0% | 100.0% | +0.0% | +17461.2 | +17820.7 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_20_db8eac65 | meta, regression, sensitivity | 100.0% | 100.0% | +0.0% | +17461.2 | +17820.7 | 0 | 0 | REGRESSION_OR_CALIBRATION |
| gold_family_21_e9b175a2 | meta, regression, sensitivity | 100.0% | 100.0% | +0.0% | +10727.8 | +10727.8 | 0 | 0 | REGRESSION_OR_CALIBRATION |

## Family diagnostics

### gold_family_22_f835f763

- V111 loss signals: `['terminal_animal_portfolio_deficit']`
- V113 loss signals: `['terminal_animal_portfolio_deficit', 'losses_have_higher_terminal_market_price_displacement']`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `360.0`; response lag median: `112.0`
- Opponent response components: `{'market': 2}`

### gold_family_02_01651da9

- V111 loss signals: `['late_cash_reversal_after_major_checkpoint_lead']`
- V113 loss signals: `['late_cash_reversal_after_major_checkpoint_lead']`
- Lead→loss (major checkpoints): V111 `1`, V113 `1`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_family_08_4fcc1724

- V111 loss signals: `['terminal_animal_portfolio_deficit', 'losses_have_higher_terminal_market_price_displacement']`
- V113 loss signals: `['terminal_animal_portfolio_deficit']`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `479.0`; response lag median: `231.0`
- Opponent response components: `{'market': 2}`

### gold_family_06_2e4e06f7

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `319.0`; response lag median: `71.0`
- Opponent response components: `{'hands': 1, 'market': 2}`

### gold_family_07_35af8bcc

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `319.0`; response lag median: `71.0`
- Opponent response components: `{'hands': 2, 'market': 2}`

### gold_family_09_55d707fe

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_family_10_595361e4

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `270.0`; response lag median: `22.0`
- Opponent response components: `{'market': 3}`

### gold_family_11_63b5d789

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_family_13_87cc7b78

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `270.0`; response lag median: `22.0`
- Opponent response components: `{'market': 3}`

### gold_family_14_9aa44dd2

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `270.0`; response lag median: `22.0`
- Opponent response components: `{'market': 3}`

### gold_family_15_af440239

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

### gold_family_16_b0b3c33c

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `270.0`; response lag median: `22.0`
- Opponent response components: `{'market': 3}`

### gold_family_19_d4e09ee0

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `270.0`; response lag median: `22.0`
- Opponent response components: `{'market': 3}`

### gold_family_20_db8eac65

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `248.0`; opponent response median: `270.0`; response lag median: `22.0`
- Opponent response components: `{'market': 3}`

### gold_family_21_e9b175a2

- V111 loss signals: `[]`
- V113 loss signals: `[]`
- Lead→loss (major checkpoints): V111 `0`, V113 `0`
- First self divergence median: `None`; opponent response median: `None`; response lag median: `None`
- Opponent response components: `{}`

## Selection guardrail

Select one large, repeated, experimentally targetable loss regime only after loss-case review; do not infer a V114 rule from aggregate labels alone.

Every family or seed used in common probes or this benchmark remains Discovery/Development and cannot later be relabeled Fresh Holdout.
