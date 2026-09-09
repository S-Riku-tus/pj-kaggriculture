# Expanded V111/V113 paired benchmark

V111 is the clean causal control; V113 is the live-validated field benchmark. This report does not modify the immutable prior 60-pair verdict and does not treat live rating as causal gate evidence.

## sensitivity

- Independent executable families: 15
- Validity/Safety gate: pairing+isolation `PASS`, hard safety `FAIL`; causal-valid pairs `180/180`
- Meta-weighted V113−V111 strict win-probability delta: +1.1% (family→seed 95% interval +0.0% to +4.4%)
- Macro-lineage V113−V111 strict win-probability delta: +1.1% (family→seed 95% interval +0.0% to +4.4%)
- Pre-registered Meta-weighted V113−V111 win-score delta: +0.6% (95% interval +0.0% to +2.2%)
- Pre-registered Macro-family V113−V111 win-score delta: +0.6% (95% interval +0.0% to +2.2%)

| Family | Pairs | V111 WR | V113 WR | ΔWR | L→W | W→L | Trigger | Actual | Δ margin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gold_family_02_01651da9 | 12 | 91.7% | 91.7% | +0.0% | 0 | 0 | 2 | 0 | +0.0 |
| gold_family_06_2e4e06f7 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | -442.8 |
| gold_family_07_35af8bcc | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 2 | -692.5 |
| gold_family_08_4fcc1724 | 12 | 91.7% | 91.7% | +0.0% | 0 | 0 | 2 | 2 | -92.3 |
| gold_family_09_55d707fe | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 4 | 0 | +0.0 |
| gold_family_10_595361e4 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +690.0 |
| gold_family_11_63b5d789 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 2 | 0 | +0.0 |
| gold_family_13_87cc7b78 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +690.0 |
| gold_family_14_9aa44dd2 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +904.4 |
| gold_family_15_af440239 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 4 | 0 | +0.0 |
| gold_family_16_b0b3c33c | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | -128.2 |
| gold_family_19_d4e09ee0 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +359.4 |
| gold_family_20_db8eac65 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +359.4 |
| gold_family_21_e9b175a2 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 4 | 0 | +0.0 |
| gold_family_22_f835f763 | 12 | 8.3% | 25.0% | +16.7% | 0 | 0 | 2 | 2 | +520.3 |

`Actual` counts pairs where the intended incremental Cow→Sheep action was emitted. Total pairs, triggers, actual treatments, and discordant outcomes remain separate statistical quantities.

## meta

- Independent executable families: 7
- Validity/Safety gate: pairing+isolation `PASS`, hard safety `FAIL`; causal-valid pairs `84/84`
- Meta-weighted V113−V111 strict win-probability delta: +2.4% (family→seed 95% interval +0.0% to +9.5%)
- Macro-lineage V113−V111 strict win-probability delta: +2.4% (family→seed 95% interval +0.0% to +11.9%)
- Pre-registered Meta-weighted V113−V111 win-score delta: +1.2% (95% interval +0.0% to +4.8%)
- Pre-registered Macro-family V113−V111 win-score delta: +1.2% (95% interval +0.0% to +6.0%)

| Family | Pairs | V111 WR | V113 WR | ΔWR | L→W | W→L | Trigger | Actual | Δ margin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gold_family_06_2e4e06f7 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | -442.8 |
| gold_family_09_55d707fe | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 4 | 0 | +0.0 |
| gold_family_15_af440239 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 4 | 0 | +0.0 |
| gold_family_19_d4e09ee0 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +359.4 |
| gold_family_20_db8eac65 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +359.4 |
| gold_family_21_e9b175a2 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 4 | 0 | +0.0 |
| gold_family_22_f835f763 | 12 | 8.3% | 25.0% | +16.7% | 0 | 0 | 2 | 2 | +520.3 |

`Actual` counts pairs where the intended incremental Cow→Sheep action was emitted. Total pairs, triggers, actual treatments, and discordant outcomes remain separate statistical quantities.

## regression

- Independent executable families: 14
- Validity/Safety gate: pairing+isolation `PASS`, hard safety `FAIL`; causal-valid pairs `168/168`
- Meta-weighted V113−V111 strict win-probability delta: +0.0% (family→seed 95% interval +0.0% to +0.0%)
- Macro-lineage V113−V111 strict win-probability delta: +0.0% (family→seed 95% interval +0.0% to +0.0%)
- Pre-registered Meta-weighted V113−V111 win-score delta: +0.0% (95% interval +0.0% to +0.0%)
- Pre-registered Macro-family V113−V111 win-score delta: +0.0% (95% interval +0.0% to +0.0%)

| Family | Pairs | V111 WR | V113 WR | ΔWR | L→W | W→L | Trigger | Actual | Δ margin |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gold_family_02_01651da9 | 12 | 91.7% | 91.7% | +0.0% | 0 | 0 | 2 | 0 | +0.0 |
| gold_family_06_2e4e06f7 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | -442.8 |
| gold_family_07_35af8bcc | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 2 | -692.5 |
| gold_family_08_4fcc1724 | 12 | 91.7% | 91.7% | +0.0% | 0 | 0 | 2 | 2 | -92.3 |
| gold_family_09_55d707fe | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 4 | 0 | +0.0 |
| gold_family_10_595361e4 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +690.0 |
| gold_family_11_63b5d789 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 2 | 0 | +0.0 |
| gold_family_13_87cc7b78 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +690.0 |
| gold_family_14_9aa44dd2 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +904.4 |
| gold_family_15_af440239 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 4 | 0 | +0.0 |
| gold_family_16_b0b3c33c | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | -128.2 |
| gold_family_19_d4e09ee0 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +359.4 |
| gold_family_20_db8eac65 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 3 | 3 | +359.4 |
| gold_family_21_e9b175a2 | 12 | 100.0% | 100.0% | +0.0% | 0 | 0 | 4 | 0 | +0.0 |

`Actual` counts pairs where the intended incremental Cow→Sheep action was emitted. Total pairs, triggers, actual treatments, and discordant outcomes remain separate statistical quantities.
