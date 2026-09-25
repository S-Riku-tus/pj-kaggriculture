# RESUME

## 現在地

Round9 A2は完成・凍結済み。最終archiveは `artifacts/submissions/round9_20260923_a2_prefix_bc_seed20260924_v3.tar.gz`、SHA256 `f5ac17a3b7db2d1311f066f9e19b1c8aa0ccf577d0955b7e2a78e03b8246811a`。公式loader、外部展開、依存元、2 episode連続resetを検証済み。

A2はA0 pureより経済改善したが、v122/v124には8試合0勝、追加64試合0勝。提出準備は不成立。sealed holdoutは未開封、Kaggle提出0。

## 再開時に最初に読むもの

1. `REPORT_JA.md`
2. `METRIC_CONTRACT.json` と `METRIC_RESULTS.json`
3. `DATA_USAGE_FUNNEL.json`
4. `trajectory_t1_t2_t3_v2/summary.json`
5. `recovery_states_v1/manifest.json`
6. `IMPLEMENTATION_DIFF.md`

## 次の一変更比較

現在の20 episode、split、A2 decoder、seed 20260923/20260924を固定する。raw-grid CNNへの変更やデータ増量を同時に行わず、まずtask/target/continue-or-completeと短期因果履歴だけを追加する。目的地と担当継続は学習出力とし、手書き畜産planへ戻さない。

優先評価はT1/T2/T3のjoint turnとofficial state-effect、cash reconciliation、実売上、平均自資金、margin。work_effect単独では昇格しない。回復例は`original_teacher`と`search`を分離し、未検証self-labelを入れない。

## 既知の注意

- observation/action対応は`steps[t] -> action steps[t+1]`。
- `model_compat`をruntimeより先にimportしないと3層checkpointを誤読し得る。
- WATERのshadowは固定engineのyield増加を含める。
- step 0でruntimeをresetする。
- 旧test4は開発診断でありfresh holdoutではない。
- T3固定相手は`REPRODUCTION_DIAGNOSTIC`であって勝率ではない。
- A2 v3の8試合はv2と完全同一。64試合はv2で実施され、v3差分はstep 0 resetのみ。
- Round8 hybridは救済対照であり、独立学習方策の成果へ数えない。

## まだしていないこと

48 episode以上への拡張、CNN/entity encoder、正式recovery再学習、fresh final holdout、Kaggle提出、rating推定。存在しない結果を補わないこと。

