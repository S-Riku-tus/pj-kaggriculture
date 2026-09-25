# Round13 Strategy Reset 2026-09-25

結論は `KEEP_B1`。最初に `REPORT_JA.md`、次に `NEXT_ACTIONS.md` と `EXECUTION_SCOPE.md` を読む。

主要artifact:

- `submission/round10_20260924_b1_herd_safe.tar.gz`: 提出可能な完全一致B1
- `agents/`: frozen B1、市場1案、生産2案、未評価composition
- `analysis/diffs/`: 各candidateのB1からのunified diff
- `configs/candidate_specs.json`: 依存資源・期限・所有権を含む計画仕様
- `metrics/development/`: 192反応型試合、pair集計、生replay
- `models/sale_forecast.json`: reload検証済みoffline売却予測
- `metrics/sale_forecast/report.json`: horizon別test指標・誤認例
- `analysis/CAUSAL_TRACES.json`: 改善・悪化・無効果の最初の差分から終局
- `REGISTRY.json`: candidate/source/engine/config/hash/seed台帳
- `MANIFEST.json`: ZIP対象全ファイルのhash台帳

再現コマンド（repo rootから）:

```powershell
.\.venv\Scripts\python.exe experiments\round13_strategy_reset_20260925\scripts\build_agents.py
.\.venv\Scripts\python.exe -m pytest -q experiments\round13_strategy_reset_20260925\tests\test_round13_contracts.py
.\.venv\Scripts\python.exe experiments\round13_strategy_reset_20260925\scripts\run_panel.py experiments\round13_strategy_reset_20260925\configs\development.json
.\.venv\Scripts\python.exe experiments\round13_strategy_reset_20260925\scripts\analyze_results.py experiments\round13_strategy_reset_20260925\metrics\development\games.csv --output experiments\round13_strategy_reset_20260925\metrics\development\paired_summary.json
.\.venv\Scripts\python.exe experiments\round13_strategy_reset_20260925\scripts\train_sale_forecast.py --stride 4
```

`run_panel.py` は既存 `games.csv` があれば混在防止のため停止する。再実行時は別output configを作り、既存の生結果を消さない。
