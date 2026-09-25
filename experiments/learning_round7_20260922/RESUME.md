# Round7からの再開点

最終開発候補は `artifacts/submissions/learning_round7_20260922_arm_b_plan_v3.tar.gz`、SHA-256は `fe3b5bd9b14ec64208fc9360c38b9aaf5cc1b44547dca2b6eee3d24d0aaf1fca` である。これは提出候補ではなく、Round8の診断baselineとして凍結する。

現状は「実装完了、研究改善あり、昇格不可」。48開発戦は0-0-48だが、Round6の無給餌を解消し、全48戦で初回生産・回収、42/48戦で土地拡張に到達した。改善はtask-completion executor込みであり、独立全行動BC単体の成功ではない。

次回はsealed seed `2026110701..2026110732` を開かず、次の順に進める。

1. V3が学習方策を上書きした12,510 actor変更と9,564 market変更を、利益を生んだ介入・crop/landを壊した介入に分解する。
2. V3の固定executorを教師として盲目的に蒸留せず、feed/care/collect/deliver/sellの完了状態、期限、中断条件を観測可能なtask labelとして構成する。派生traceは元episode family単位で分割する。
3. actor/marketの10以上・15以上数量を、独立argmaxではなく残量・目標量・全量・reserveを残す等の最小の構造表現で一つずつ比較する。
4. 家畜serviceとcrop/landの人員・現金・小麦競合を短い回復状態で評価し、fixture→複数prefix→同じ8戦pilotの順に進む。
5. pilotで少なくとも生産基盤を維持し、開発anchorに勝つ兆候が出るまで48戦を反射的に再実行しない。48戦で昇格条件を満たした候補だけについて、候補・補正・指標・試合数を凍結してからsealed評価を検討する。

重要な既知反例は次の通り。

- `phase0/day1_unfed_round6_trace.json`: raw FEEDは小麦を持たないhand、mask後は消失。数量1だけの問題ではない。
- `day1_candidate_comparison_v2.json`: Arm B/ledgerだけではWHEAT 2取得後にWESTへ進み、plan armだけがFEED完了。
- `prefix_diagnostics_arm_b_plan_v3/summary.json`: 短期2例は現金増、長期2例は-12,775/-6,740で作物・土地が劣化。
- `arm_b_plan_v3_stage_audit.json`: final joint 2.90%で、executorの上書きが強い。
- `development_evaluation_arm_b_plan_v3/summary.json`: 0-0-48。昇格不可の決定根拠。

再現コマンドは `REPRODUCE.md` にある。最終状態の健全性確認は次で行う。

```powershell
.\.venv\Scripts\pytest.exe -q tests\test_round7_contracts.py
.\.venv\Scripts\python.exe scripts\validate_round7_candidates.py --output experiments\learning_round7_20260922\arm_b_plan_v3_runtime_validation.json artifacts\submissions\learning_round7_20260922_arm_b_plan_v3.tar.gz
```

validatorは出力を上書きするので、凍結後の再実行では新しい出力名を使うこと。archive、既存replay、`ARTIFACT_SHA256.json`、sealed集合を上書きしない。

