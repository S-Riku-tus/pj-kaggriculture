# Round10 再現手順

PowerShell、リポジトリ root `C:\Users\shiba\Kaggle\pj-kaggriculture`、既存 `.venv` を前提とする。コマンドは Kaggle submit/publish を含まない。各評価 config に seed、seat、arm、相手、出力先が固定されている。

## 1. 入力と公開コード

入力 ZIP の実 hash は `artifact_manifest.json` に記録済み。fresh 作業先へ展開する場合だけ次を使う。

```powershell
Expand-Archive -LiteralPath 'C:\Users\shiba\Downloads\Kaggriculture_Public_Research_20260924.zip' -DestinationPath 'experiments\round10_public_learning_20260924\inputs\Kaggriculture_Public_Research_20260924'
Expand-Archive -LiteralPath 'C:\Users\shiba\Downloads\Round9_Hybrid_Audit_20260923.zip' -DestinationPath 'experiments\round10_public_learning_20260924\inputs\Round9_Hybrid_Audit_20260923'
```

保存済み public response が再現の基準である。現行版を別ディレクトリへ再取得する場合は次を使う。この処理は Notebook を実行しない。

```powershell
.\.venv\Scripts\python.exe scripts\acquire_round10_public_sources.py --output-root C:\tmp\round10-public-refresh
.\.venv\Scripts\kaggle.exe --version
.\.venv\Scripts\kaggle.exe competitions leaderboard --help
.\.venv\Scripts\kaggle.exe competitions leaderboard kaggriculture --show --format json
```

最後のコマンドは今回、認証未設定で return code 1 になった。認証情報をこの手順へ書かない。取得済み Notebook の静的抽出例:

```powershell
.\.venv\Scripts\python.exe scripts\extract_round10_public_agents.py experiments\round10_public_learning_20260924\public_sources\ahmedberatozer__kaggriculture-v57-funding-order-invariant\payload_1.ipynb C:\tmp\round10-v57-extract
.\.venv\Scripts\python.exe scripts\build_round10_source_registry.py --output experiments\round10_public_learning_20260924\source_registry.json
```

## 2. 公式比較と C++ L1

市場 microcheck と公式比較:

```powershell
.\.venv\Scripts\python.exe experiments\round10_public_learning_20260924\inputs\Kaggriculture_Public_Research_20260924\scripts\market_microcheck.py
.\.venv\Scripts\python.exe experiments\round10_public_learning_20260924\inputs\Kaggriculture_Public_Research_20260924\scripts\verify_micro_with_official.py
```

C++ source は `experiments/round10_public_learning_20260924/engines/kaggriculture-cppsim` に commit `f0084b916343c37bbcbdc7de9d833dc96caff78f` で保存済み。Windows MinGW build は記録済み `setup.py` patch を使う。

```powershell
Push-Location experiments\round10_public_learning_20260924\engines\kaggriculture-cppsim
$env:KAGSIM_MINGW='1'
..\..\..\..\.venv\Scripts\python.exe setup.py build_ext --inplace --compiler=mingw32
g++ -O3 -std=c++17 -o validate.exe tools\validate.cpp
Pop-Location
.\.venv\Scripts\python.exe scripts\record_round10_engine_validation.py --output experiments\round10_public_learning_20260924\validation\engine_validation.json
```

agent-specific official/L1 crosscheck:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round10_public_learning_20260924\configs\official_agent_crosscheck.json --workers 1
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round10_public_learning_20260924\configs\kagsim_agent_crosscheck.json --workers 1
.\.venv\Scripts\python.exe scripts\compare_round10_engine_runs.py experiments\round10_public_learning_20260924\validation\official_agent_crosscheck\games.csv experiments\round10_public_learning_20260924\validation\kagsim_agent_crosscheck\games.csv --output experiments\round10_public_learning_20260924\validation\official_vs_kagsim_agent.json
```

## 3. B0/B1 と初日資金

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round10_public_learning_20260924\configs\public_preliminary.json --workers 4
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round10_public_learning_20260924\configs\public_candidate_selection.json --workers 4
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round10_public_learning_20260924\configs\herd_safe_confirmation.json --workers 4
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round10_public_learning_20260924\configs\b1_regression.json --workers 4
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round10_public_learning_20260924\configs\opening_funding_stress.json --workers 4
.\.venv\Scripts\python.exe scripts\analyze_round10_opening_funding.py experiments\round10_public_learning_20260924\evaluations\opening_funding_stress\games.csv --output-csv experiments\round10_public_learning_20260924\analysis\opening_funding_stress_games.csv --summary experiments\round10_public_learning_20260924\analysis\opening_funding_stress_summary.json
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round10_public_learning_20260924\configs\opening_candidate_isolation.json --workers 4
.\.venv\Scripts\python.exe scripts\analyze_round10_opening_funding.py experiments\round10_public_learning_20260924\evaluations\opening_candidate_isolation\games.csv --output-csv experiments\round10_public_learning_20260924\analysis\opening_candidate_isolation_games.csv --summary experiments\round10_public_learning_20260924\analysis\opening_candidate_isolation_summary.json
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round10_public_learning_20260924\configs\opening_b2_confirmation.json --workers 4
.\.venv\Scripts\python.exe scripts\summarize_round10_panel.py experiments\round10_public_learning_20260924\evaluations\opening_b2_confirmation\games.csv --reference B1_buy8_sell3 --output experiments\round10_public_learning_20260924\analysis\opening_b2_confirmation_summary.json --paired-csv experiments\round10_public_learning_20260924\analysis\opening_b2_confirmation_paired.csv
```

## 4. タスク教師、実学習、fresh seed 評価

候補機会の監査、null-control、step 0 からの paired fork、実学習を順に行う。

```powershell
.\.venv\Scripts\python.exe scripts\analyze_round10_task_opportunities.py experiments\round10_public_learning_20260924\evaluations\b1_regression\games.csv --arm B1_herd_safe --output experiments\round10_public_learning_20260924\analysis\b1_task_opportunities.json
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round10_public_learning_20260924\configs\task_null_control.json --workers 2
.\.venv\Scripts\python.exe scripts\verify_round10_null_control.py experiments\round10_public_learning_20260924\evaluations\task_null_control\games.csv --output experiments\round10_public_learning_20260924\validation\task_null_control_exact.json
.\.venv\Scripts\python.exe scripts\collect_round10_task_labels.py experiments\round10_public_learning_20260924\configs\task_label_collection.json --workers 4
.\.venv\Scripts\python.exe scripts\train_round10_task_ranker.py experiments\round10_public_learning_20260924\training\task_labels\task_labels.csv --model agents\round10_task_learning_20260924\model.json --report experiments\round10_public_learning_20260924\training\ranker_training_report.json --predictions experiments\round10_public_learning_20260924\training\ranker_predictions.csv --epochs 600 --learning-rate 0.08 --l2 0.02
.\.venv\Scripts\python.exe scripts\evaluate_round10_panel.py experiments\round10_public_learning_20260924\configs\task_selector_seed_holdout.json --workers 4
.\.venv\Scripts\python.exe scripts\summarize_round10_panel.py experiments\round10_public_learning_20260924\evaluations\task_selector_seed_holdout\games.csv --reference B1_herd_safe --output experiments\round10_public_learning_20260924\analysis\task_selector_seed_holdout_summary.json --paired-csv experiments\round10_public_learning_20260924\analysis\task_selector_seed_holdout_paired.csv
.\.venv\Scripts\python.exe scripts\build_round10_task_diagnostics.py
```

`task_selector_seed_holdout` の seed は教師収集と重ならないが、opponent family は既知なので、結果ファイル自身も fresh seed とだけ記載している。

## 5. 包装と完全性検査

```powershell
.\.venv\Scripts\python.exe scripts\package_round10_candidates.py --output-dir artifacts\submissions --manifest experiments\round10_public_learning_20260924\package_manifest.json
.\.venv\Scripts\python.exe scripts\validate_round10_archives.py experiments\round10_public_learning_20260924\package_manifest.json --output experiments\round10_public_learning_20260924\package_validation\archive_loader_results.json --seed 2026092428
.\.venv\Scripts\python.exe scripts\build_round10_artifact_manifest.py
.\.venv\Scripts\ruff.exe check scripts\acquire_round10_public_sources.py scripts\*round10*.py agents\round10_opening_b2_20260924 agents\round10_task_learning_20260924
```

最終成功条件は `artifact_manifest.json` の `integrity_passed=true` と、`package_validation/archive_loader_results.json` の `all_passed=true`。これはローカル再現・包装の成功条件であり、Kaggle 提出成功や競技レートを意味しない。
