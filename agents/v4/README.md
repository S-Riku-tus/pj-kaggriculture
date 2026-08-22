# V4 Feasible Expert Executor

V4は、V3の上位3チーム学習モデルを戦略目標として残しつつ、実行可能性と作業密度を独立に保証するhybrid agentです。

処理は次の順です。

1. Day 0はV3と同じRank1 openingを再生します。
2. Learned portfolioにTopの成長下限とTown需要補正を加えます。
3. Pasture、土地、残り日数、空きtileから実行可能な投資量へ射影します。
4. Animal購入は、空きPastureまたは同turnに建設するPastureの容量内に限定します。
5. Seedは直近で植えられる少量だけを購入し、MelonはDay10、StrawberryはDay18以降追加しません。
6. Worker割当は同じtileでのHARVEST・FEED・CARE・COLLECT連続完了を優遇します。

検証とpackage:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_match.py --agent agents/v4 --opponent agents/v3/main.py --pairs 3 --seed 20260830
.\.venv\Scripts\python.exe scripts\package_submission.py --agent agents/v4
```

V4はV3の学習済みmodelをそのまま利用します。今回の再解析ではportfolio prediction誤差よりexecutor wasteの影響が大きかったため、4.0.0では教師labelを増やさず、モデル出力を安全に実行する層を優先しています。

5 seedを両席で実行したローカルpaired validationでは、V2に10/10勝、package版V3に10/10勝でした。20戦合計の平均はV4が99,713 coin、相手が58,720 coinです。詳細と制約は `docs/v4_design_report.md` を参照してください。この結果はLeaderboard ratingを保証するものではありません。
