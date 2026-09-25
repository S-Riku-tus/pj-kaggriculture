# Round11 reproduction

Working directory is repository root `pj-kaggriculture`. Commands below use the existing Windows virtual environment and do not submit or publish anything.

## 1. Verify the supplied revision

```powershell
.\.venv\Scripts\python.exe experiments\Kaggriculture_Round11_Research_Revision_20260924\scripts\verify_package.py
```

Expected: package PASS, 215 files, 128 complete games, 357343 ledger checks.

## 2. Public source acquisition and static extraction

The already acquired raw files are under `experiments/round11_execution_20260924/sources/raw/kaggle`. Re-fetch is optional, requires network approval, and may return a newer Kaggle version:

```powershell
.\.venv\Scripts\python.exe scripts\acquire_round11_public_sources.py --output-root experiments\round11_execution_20260924\sources\raw\kaggle
```

Static extraction takes one saved payload/response and an output directory; it never executes the notebook:

```powershell
.\.venv\Scripts\python.exe scripts\extract_round11_public_agents.py <saved-payload-or-response> <output-directory>
```

Audit the six emitted execution files:

```powershell
.\.venv\Scripts\python.exe scripts\audit_round11_agents.py `
  experiments\round11_execution_20260924\sources\extracted_static\more_wheat\extracted_agent_1.py `
  experiments\round11_execution_20260924\sources\extracted_static\order_book_v3\extracted_agent_1.py `
  experiments\round11_execution_20260924\sources\extracted_static\moon\extracted_agent_1.py `
  experiments\round11_execution_20260924\sources\extracted_static\v15stack\extracted_agent_1.py `
  experiments\round11_execution_20260924\sources\extracted_static\wonderful\extracted_agent_1.py `
  experiments\round11_execution_20260924\sources\extracted_static\master_hybrid\extracted_agent_1.py `
  --output experiments\round11_execution_20260924\sources\STATIC_AUDIT.json
```

The scanner deliberately reports false for the common disabled `open(path)` branch. Review `SOURCE_REGISTRY.json` before execution; it records the inspected `path=None` guard and literal-exec hashes.

## 3. Build B1-based arms

```powershell
.\.venv\Scripts\python.exe scripts\build_round11_variants.py
```

This must reproduce `arms/generated_manifest.json`. M20 SHA256 must be `98d374f58f68c5b9f263eb3ed04f724e1e0b7a4fa562b581bdac90b276492c4a`.

## 4. Phase 0

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round11_execution_20260924\configs\phase0_no_change_official.json
.\.venv\Scripts\python.exe scripts\verify_round11_no_change.py
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round11_execution_20260924\configs\phase0_m20_official_parity.json
.\.venv\Scripts\python.exe scripts\verify_round11_engine_parity.py `
  experiments\round11_execution_20260924\phase0\m20_official_parity `
  experiments\round11_execution_20260924\track_b\market_kagsim `
  --output experiments\round11_execution_20260924\phase0\m20_official_cppsim_parity.json
```

Expected: NO_CHANGE all identical; M20 parity 4/4 exact with 720 states and 719 decisions.

## 5. Development panels

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round11_execution_20260924\configs\track_a_screen_kagsim.json --workers 4
.\.venv\Scripts\python.exe scripts\summarize_round11_panel.py experiments\round11_execution_20260924\track_a\screen_kagsim
.\.venv\Scripts\python.exe scripts\analyze_round11_production_routes.py experiments\round11_execution_20260924\track_a\screen_kagsim

.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round11_execution_20260924\configs\track_b_market_kagsim.json --workers 4
.\.venv\Scripts\python.exe scripts\summarize_round11_panel.py experiments\round11_execution_20260924\track_b\market_kagsim
.\.venv\Scripts\python.exe scripts\summarize_round11_telemetry.py experiments\round11_execution_20260924\track_b\market_kagsim

.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round11_execution_20260924\configs\track_b_conditional_wool_kagsim.json --workers 4
.\.venv\Scripts\python.exe scripts\summarize_round11_panel.py experiments\round11_execution_20260924\track_b\conditional_wool_kagsim
.\.venv\Scripts\python.exe scripts\summarize_round11_telemetry.py experiments\round11_execution_20260924\track_b\conditional_wool_kagsim
```

These commands create 224 + 160 + 96 cppsim games. Existing output directories should be moved aside before an intentional full rerun; do not mix old and new rows.

## 6. Frozen holdout

Read `holdout/ACCEPTANCE_PROTOCOL.json` before executing:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round11_execution_20260924\configs\holdout_m20_kagsim.json --workers 4
.\.venv\Scripts\python.exe scripts\summarize_round11_panel.py experiments\round11_execution_20260924\holdout\m20_kagsim
.\.venv\Scripts\python.exe scripts\summarize_round11_telemetry.py experiments\round11_execution_20260924\holdout\m20_kagsim
.\.venv\Scripts\python.exe scripts\decide_round11_holdout.py `
  experiments\round11_execution_20260924\holdout\m20_kagsim `
  --protocol experiments\round11_execution_20260924\holdout\ACCEPTANCE_PROTOCOL.json `
  --parity experiments\round11_execution_20260924\phase0\m20_official_cppsim_parity.json `
  --output experiments\round11_execution_20260924\holdout\HOLDOUT_DECISION.json
```

The decision command intentionally exits nonzero for the recorded REJECT. The as-run protocol has a transcribed candidate-hash typo; do not silently edit it. `HASH_AUDIT.json` demonstrates that development, official parity, holdout and current M20 source all used the same actual hash.

## 7. Registries and final research bundle

```powershell
.\.venv\Scripts\python.exe scripts\build_round11_registries.py
.\.venv\Scripts\python.exe scripts\build_round11_final_bundle.py
.\.venv\Scripts\python.exe scripts\verify_round11_final_bundle.py
```

If and only if refreshing the already generated Round11 artifact after an in-scope script/document correction, pass `--refresh`; it overwrites the enumerated bundle members and ZIP but does not recursively delete a directory.

No new candidate tar is expected because no arm passed the holdout. The bundle includes the already successful immutable B1 archive as the retained baseline, not as a newly claimed Round11 improvement.
