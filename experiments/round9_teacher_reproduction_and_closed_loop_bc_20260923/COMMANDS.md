# 主要再実行コマンド

作業ディレクトリは `C:\Users\shiba\Kaggle\pj-kaggriculture`、Python は `.venv\Scripts\python.exe` である。下記は成果物を再生成する中心コマンドであり、既存出力を上書きしない実装なので、再実行時は新しい出力名または退避先を使う。

```powershell
.\.venv\Scripts\python.exe scripts\run_round9_contract_controls.py
.\.venv\Scripts\python.exe scripts\train_round9_prefix_bc.py build
.\.venv\Scripts\python.exe scripts\train_round9_prefix_bc.py finalize-dataset
.\.venv\Scripts\python.exe scripts\train_round9_prefix_bc.py train --seed 20260923
.\.venv\Scripts\python.exe scripts\train_round9_prefix_bc.py train --seed 20260924
.\.venv\Scripts\python.exe scripts\train_round9_prefix_bc.py build-trajectory-control
.\.venv\Scripts\python.exe scripts\train_round9_prefix_bc.py train-trajectory-control --seed 20260925
.\.venv\Scripts\python.exe scripts\run_round9_engine_fixtures.py
.\.venv\Scripts\python.exe scripts\evaluate_round9_t1_t2_t3.py
.\.venv\Scripts\python.exe scripts\build_round9_recovery_states.py
```

主要8試合パネル（A0/A1/A2で `--candidate`、`--label`、`--output` を変更）:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_round7_pilot.py --workers 4 --candidate artifacts\submissions\round9_20260923_a2_prefix_bc_seed20260924_v3.tar.gz --label round9_a2_v3 --output experiments\round9_teacher_reproduction_and_closed_loop_bc_20260923\development_panel_a2_v3
```

64試合拡張は、preregistration追記後に `scripts/evaluate_round7_pilot.py` と同じ `_run_game` 契約を使い、seed `2026102301..2026102316`、相手 `v122/v124`、seat `0/1` で実行した。全task・hash・seedは `development_panel_a2_v2_expanded64/evaluation_manifest.json` に保存した。

```powershell
.\.venv\Scripts\python.exe scripts\audit_round9_economy.py development_panel_a0 development_panel_a1_v2 development_panel_a2_v2 development_panel_a2_v2_expanded64
.\.venv\Scripts\python.exe scripts\validate_round9_archive.py
```

最終archive検証はリポジトリ外の `C:\tmp\round9_a2_v3_loader_audit_20260923` に展開して実行した。結果は `final_archive_loader_validation.json` にある。

