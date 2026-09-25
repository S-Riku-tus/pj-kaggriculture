# Round10 結果報告（2026-09-24）

## 結論

競技用の新しいローカル基準として、公開 Notebook から取得した herd-safe 方策を B1 として保存した。B1 は Apache-2.0 の原著者表示を保ち、今回取得・実行した `main.py` の SHA256 は
`b6553c296c556aff5b5e2d12b75618e505fa4d852afb5338414ac6d6e039cb02` である。これはタイトルのレート表記ではなく、実際の対話型対戦結果で選んだ。

評価相手 family は学習・選別中にも見ているが、seed は新しい 2026092425〜2026092427 とした最終比較（4 family × 3 seed × 両 seat）では、B0=v124 が 6W18L、B1 が 23W1L だった。同一 seed の両 seat と派生 arm は独立標本として水増ししていない。この結果は Kaggle レートへの換算ではなく、現在の rated field や「2500以下」に対する勝率の証明でもない。

採用成果物は `round10_20260924_b1_herd_safe.tar.gz`。Kaggle への submit、Notebook publish、既存 Champion の置換は行っていない。

## 取得と基準方策

公開 `kernels/pull` 応答から 7 方策を保存した。指定された Harvest Ledger は HTTP 404 で、代替として Barnyard を取得した。各 Notebook の kernel ID、current version number、取得時刻、最終実行時刻、Notebook/API/agent hash、ライセンス、タイトルスコアと未確認スコアを `source_registry.json` に分離して記録した。unauthenticated 応答に `scriptVersionId` はなく、現行提出物との同一性も未確認である。

Kaggle CLI 2.2.4 の現行 help を確認後、leaderboard を正しい構文で取得しようとしたが認証未設定で停止した。したがって current leaderboard、episodes、対戦時 submission ID、現在表示レートは保存できていない。認証情報は記録していない。

B0 の実体は `agents/v124/main.py` であり、SHA256 は `0f0c95d52e82840488078a2feecf9ca4d3c59e9337d3273bf7c64ca572c0e51f`。リポジトリ内の v124 tar も実在し、SHA256 は `cdc74eb6ae47c53e9c2edfeea45dc55603c67ebfdba48164081458f79c4f46fc`。v122 tar も実在し、SHA256 は `edf5b32565f8c4530959b94df36858a6a64c651d4b42b7aa612ddaca02e9a88c`。これは「前回の Round9 export ZIP に同梱されていなかった」という監査結果と矛盾しない。今回、リポジトリ本体で別に現物確認したものである。

4 新規 seed × 両 seat の予備比較では、B0 は V56/V57/OrderBook/MetaV4/Herd/Melon の各 8 試合をすべて失い、Barnyard にだけ 8W0L。候補同士の選別後、Herd は V57/MetaV4/Melon/OrderBook に確認 16W0L。旧評価相手 mooman/qeinstein/smart_farm/souvik に対する 32 試合では、B1 は 32W0L、B0 は 30W2L だった。この予備試験と回帰試験を fresh holdout とは呼ばない。

## 初日資金耐性と B2

B0/B1 を BUY70→SELL70、BUY10→SELL10、BUY90→SELL90→小麦5、より小さい往復、売却先行、無取引と対話させた。B0 は強い BUY90 と売却先行に各 0W4L。B1 は BUY90 に 2W2L、売却先行に 4W0L だった。

B1 の初手だけを固定し、5 完全候補を比較した。強い BUY90 ストレスでは BUY10→SELL5 が 4W0L、平均 margin +24066.5。B1 の BUY8→SELL3 は 4W0L、+145。BUY10→SELL5 は step 1 後の小麦5・hands 5、day 1 の作物20タイル・動物4頭を維持した。SELL3→BUY8 は 0W4L、作物18タイルまで落ちたため不採用。

BUY10→SELL5 を B2 として実装し、別 seed 96 試合で B1 と比較した。V57/MetaV4/OrderBook では paired margin がそれぞれ +4、+4、+4、qeinstein では平均 +814.25、Melon では -2。B1 mirror では B1 の 6 引分を B2 が strict loss に変え、平均 -2 だった。したがって B2 は資金攻撃用の実験 arm であり、B1 の無条件置換にはしていない。

## タスク契約、教師データ、実学習

B1 の 32 対戦ログには、予定 WATER の直前に FERTILIZE を追加できる候補が 1,421 件あった。このうち `FERTILIZE -> WATER` を一つの仕事束として実装した。契約には target の世代、actor、所持 fertilizer、予約資源、開始条件、期限、予定行動、実 engine effect による完了・失敗、残った WATER 義務を再確認して B1 へ戻る復帰条件を含む。先行 actor 実行後の状態で後続 actor を判定し、実際に commit された行動だけを履歴へ入れる。

null wrapper は 4 対戦で全状態・全行動・報酬・telemetry が B1 と完全一致した。教師収集は snapshot/clone を仮定せず、各 baseline/treatment を step 0 から両 agent とも再実行した。72 fork すべてで prefix hash 一致、仕事の engine effect と完了を確認し、contract failure は 0。terminal margin が正の fork は 10/72（13.9%）だった。

標準ライブラリだけで推論できる logistic ranker を 600 update 実訓練した。group は opponent:seed 単位でまとめ、両 seat と関連候補を同じ split に置いた。初期 weight hash は `d58e691914f89d3470077d819aa83190ee3b246529bfbcb404ca544c73127437`、最終 weight hash は `0c7e853157792bfc32e7b11bf82f211a5042b6c3cb070d04996e75b0091591f2`、export model hash は `4629a2137737ee6982e2f8a0ebf1e639e415e83aadd977a1b5263d326ad0ad5f`。

ただし、validation で選ばれた threshold 0.95 は全候補に abstain した。fresh seed 24 対話試合で model は全試合ロードされ、合計 1,344 回推論したが、選択タスク0、変更行動0。結果は B1 と完全一致したため、学習寄与は未証明である。rule selector は 77 回発火し contract failure 0 だったが、V57 1W5L、MetaV4 2W4Lまで退化した。よって rule/learned を採用しない。未来の terminal label を使う oracle は候補集合の診断に限定し、agent には搭載していない。

## Engine と包装

公式側はローカル `kaggle-environments==1.32.7`。市場 microcheck は公式比較 9/9 pass。C++ は commit `f0084b916343c37bbcbdc7de9d833dc96caff78f` を固定し、Windows MinGW 用の `setup.py` 差分を記録した。bundled 6 trace は各 719 step exact、Python golden 6/6、L1 observation lockstep 6/6（各 10,066 field-block）を通過した。B1 対 V57 seed 2026092401 の両 seat では、公式/L1 の終局 cash、勝敗、Shop sequence hash が一致した。これは未試験状態までの同等性証明ではない。L2 は未実装で、Game clone/snapshot は使用していない。

3 archive は独立プロセスで実展開・実ロードし、719 判断の full episode を完走した。learned archive では model load、61 calls、contract failure 0 も確認したが、ここでも選択0である。

## 成果物と未確定事項

- B1（採用ローカル基準）: `artifacts/submissions/round10_20260924_b1_herd_safe.tar.gz`, SHA256 `3fff94ec235566fff3416627d2691dec2e502bc80646a9016ee15e6fc2067986`
- B2（初手耐性 arm、混合回帰）: `artifacts/submissions/round10_20260924_b2_buy10_sell5.tar.gz`, SHA256 `70ede751deac2688a2e822f65f10069e3b98d9db9d6dd0278d7574e13acb651a`
- learned diagnostic（寄与未証明）: `artifacts/submissions/round10_20260924_learned_diagnostic.tar.gz`, SHA256 `f0e1d9012b1cf2e9556302a299c8ac459990466cd3d0a3b6cd26fa45e95c636e`
- 全対戦 CSV と gzip raw replay: `evaluations/`
- 特徴・候補・label、実学習、model、予測: `training/` と `agents/round10_task_learning_20260924/`
- 観測→候補→model score→補正→実行→完了例: `analysis/task_diagnostic_examples.json`
- source/code/engine/model/opponent/package/replay hash: `artifact_manifest.json`

未確定なのは、current leaderboard/episodes、公開タイトルスコアと取得コード・提出物の対応、現在の rated 中上位・上位への強さ、2500以下への95%勝率、3000到達である。ローカル結果をレートへ換算していない。

次の一実験は、B1 上で「既存3区画の最初の収穫後から、後作の購入・播種・水やり・収穫・販売まで」を一つの原子的経済計画として実装し、今回未使用の seed と別 family の反応型相手で B1 と比較すること。初手 B2 は同時に混ぜず、局所施肥より大きな oracle 余地を持つ完成計画かを先に測る。
