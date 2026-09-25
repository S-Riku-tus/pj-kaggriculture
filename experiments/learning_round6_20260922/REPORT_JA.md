# Kaggriculture Round6 追補実行報告

分析日: 2026-09-22（日本時間）

## 結論

追補に従い、v122/v123/v124 の凍結提出用 archive を主比較基準へ変更した。旧学習版、既存の全行動BC、新規の系列対応全行動BCを、同じ8 seed・両seat・3 anchorで比較した。

新規 `round6_sequence_bc_v1` は、保留教師上の最終 joint action 完全一致を 2.14% から 7.01% へ、既存全行動BC比の平均終局資金を 1,571 から 8,402 へ改善した。しかし、v122/v123/v124 の各16試合にすべて敗れ、長期自由継続も崩壊した。したがって、模倣学習研究は継続するが、この archive は提出候補へ昇格させない。最終確認用32 seedは開封していない。

Kaggleへの新規提出、外部アカウント操作、有料計算資源の利用は行っていない。

## 基準成果物の実体

| anchor | archive SHA-256 | 過去submission情報 | ローカルmanifest |
|---|---|---|---|
| v122 | `edf5b32565f8c4530959b94df36858a6a64c651d4b42b7aa612ddaca02e9a88c` | 56330890, 56330893 | 全内部ファイル一致 |
| v123 | `0d5296587b1ba6f68cbd7bd5943f164269071b03b852ee3982ce22958edc33f6` | 56346060, 56346090 | 全内部ファイル一致 |
| v124 | `cdc74eb6ae47c53e9c2edfeea45dc55603c67ebfdba48164081458f79c4f46fc` | 56357320, 56360233 | 全内部ファイル一致 |

engineは `kaggle-environments==1.32.7`、source SHA-256は `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`。全archiveを公式ローダー相当のroot `main.py` 経路から別プロセスで読み込み、各試合もfresh processで実行した。

過去submission IDとratingは保存済みローカル分析に基づく。実際にKaggleへアップロードされたbytesの再取得、現在rating、ユーザー報告のqeinstein約1250、ローカル `qeinstein_moev2` との同一性は今回独立確認していない。

## 実行した新しい全行動学習

`round6_sequence_bc_v1` は4クラスselectorではない。以下を全て学習対象にした。

- farmerと可変長handsの操作・対象token
- 同一turnで先にdecodeしたactor tokenの頻度と直前token
- 市場注文の可変長・順序・EOS
- actorと市場の数量を、token固定中央値ではなく状態条件付き分類headで予測
- モデルraw出力と合法性・経済補正を分離

episode単位の既存splitを変更せず、両seatを含む教師replayから学習した。学習行数はactor 579,777、市場359,837。testはcheckpoint選択後にのみ開き、token正解率はactor 78.91%、市場77.16%、数量完全一致はactor 78.81%、市場67.17%だった。archiveは次の通り。

`artifacts/submissions/learning_round6_20260922_sequence_bc_v1.tar.gz`

SHA-256: `f8d1bc6ea5d69ef8777013995c63aa88e83f8a5c1402b184f356153d2d372434`

最終archiveをfresh processで両seatから720状態完走させた。719回/seatの推論で最大0.2551秒、最大p99 0.0132秒となり、`actTimeout=1` 秒を満たした。48試合の主評価でもruntime errorは0だった。

## 主開発評価

事前固定した `2026102201..2026102208`、両seat、3 anchorを使用した。勝ち=1、引分=0.5、負け=0とし、同anchor・同seedの両seatを1 blockとして扱った。

### 新候補

| anchor | W-D-L | seat 0勝点率 | seat 1勝点率 | 勝点率 | 平均終局資金 | 平均資金差 |
|---|---:|---:|---:|---:|---:|---:|
| v122 | 0-0-16 | 0.000 | 0.000 | 0.000 | 8,866.94 | -143,314.13 |
| v123 | 0-0-16 | 0.000 | 0.000 | 0.000 | 8,866.94 | -143,314.13 |
| v124 | 0-0-16 | 0.000 | 0.000 | 0.000 | 7,471.56 | -143,931.31 |

`p_internal=0.000`。各anchorの初期目標60%も、片側95%下限が50%超という優位基準も満たさない。

8 seed blockがすべて0のため、percentile bootstrapは `[0,0]` に退化する。これは確実性の証拠として扱わない。bounded seed scoreに対する保守的Hoeffding両側95%区間は各anchorで `[0, 0.4802]`。観測した48全敗は明確に昇格を否定するが、真の勝点率を厳密に0と断定するものではない。

### 同じ新基準上の比較

| arm | p_internal | 3 anchor平均の自資金 | 3 anchor平均の資金差 | runtime error |
|---|---:|---:|---:|---:|
| 旧Round5学習版 | 0.000 | 8,640.65 | -141,562.92 | 0 |
| 既存全行動BC | 0.000 | 1,570.83 | -150,261.38 | 0 |
| 新系列BC v1 | 0.000 | 8,401.81 | -143,519.85 | 0 |

新系列BCは既存全行動BCに対し平均自資金を約6,831改善した。一方、旧Round5学習版に対して平均自資金は約239低く、資金差も各anchorで約1,692〜2,089悪い。勝点率は3 armとも0なので、資金改善を勝率改善とは呼ばない。

同seedでも方策分岐後の乱数消費が変わり、比較arm間のShop履歴hashは48/48で異なった。これらの試合は除外していない。

v122とv123はこの集合で全結果・資金差が一致した。別々に表示はしたが、これを独立した2戦略familyの証拠とは扱わない。

## 保留教師の全行動模倣

教師submission 56216119のtest splitから、事前固定hash規則で8 episode（両seat、5,752判断）を選んだ。teacher-forced履歴を使い、未来情報・episode ID・相手名はruntime入力にしていない。

| 指標 | 既存全行動BC | 新系列BC v1 |
|---|---:|---:|
| raw joint action完全一致 | 2.14% | 8.22% |
| 最終archive joint action完全一致 | 2.14% | 7.01% |
| 最終actor token micro | 69.87% | 75.92% |
| 最終actor token macro | 77.82% | 82.15% |
| 最終actor 数量+token | 47.14% | 68.20% |
| 最終市場token micro | 61.38% | 64.18% |
| 最終市場 数量+token | 28.41% | 34.38% |
| 最終市場注文列完全一致 | 36.49% | 42.25% |
| rawから最終補正で変化したturn | 43.52% | 35.34% |

新候補は全軸で改善したが、joint action 7.01%は依然低い。時期別の最終joint一致は序盤16.35%、中盤3.65%、終盤0.99%。重要判断別では餌調達15.71%、再投資7.46%、搬送6.58%、売却3.54%、退出・転用2.41%であり、長期戦略の系列保持が不足している。

raw joint 8.22%から最終7.01%へ低下しているため、合法性・経済補正も残る誤差源である。ただし補正はruntime安全性に必要であり、単に外すのではなく、補正後出力を学習時に整合させる必要がある。

## 教師prefixからの自由継続

episode 109590135、seat 1で最初の96 stepをengine上で完全再生し、その後を候補のclosed loopとした。相手は保存replay行動を再生しただけで反応型ではなく、DAggerとも呼ばない。

| 継続step | 教師に対する自資金差: 既存BC | 教師に対する自資金差: 新v1 |
|---:|---:|---:|
| 24 | -241 | -164 |
| 48 | -511 | -105 |
| 96 | +114 | +156 |
| 192 | -7,318 | -6,990 |
| 残り623 | -106,403 | -104,789 |

最初の相違は両候補ともdecision step 97。新候補はWHEAT搬送を教師の `[4,3,3]` に対して `[3,3,2]` とし、操作系列は近づいたが資源割当量を再現できなかった。短期差は改善したものの、192 step以降の崩壊は解消していない。

## 工程別判定

| 工程 | 状態 | 判定 |
|---|---|---|
| `full_action_training_executed` | EXECUTED | 新系列BCを実学習・archive化 |
| `teacher_imitation_result` | MEASURED_IMPROVED_BUT_INSUFFICIENT | 全模倣指標は改善、jointと終盤は不足 |
| `closed_loop_execution_result` | MEASURED_LONG_HORIZON_COLLAPSE | 起動・合法形状・完走は成功、長期戦略は崩壊 |
| `internal_anchor_comparison` | FAIL_TARGET_NOT_MET | 3版すべて0-16 |
| `external_generalization_check` | NOT_RUN | qeinstein/smart_farm補助比較は未実施 |
| `online_validation` | NOT_RUN | Kaggle提出なし |
| `research_continuation` | CONTINUE | 学習全体は停止しない |
| `candidate_promotion` | REJECTED | 最終確認seedを開く条件に未到達 |

## 次段階の学習仮説

1. 個別handの数量分類ではなく、turn全体で必要な資源総量を予測し、handsへ制約付きで配分するjoint allocation headを導入する。step 97の `[4,3,3]` 対 `[3,3,2]` を直接対象にする。
2. actor token列と市場注文列に、同一turnだけでなく24/48/96 stepの目的・作業phaseを表す潜在optionを持たせる。未来教師情報はruntime入力にせず、訓練labelとしてのみ使う。
3. 補正前raw出力と補正後実行出力の双方へlossを置き、補正が35%のturnを書き換える状態分布を縮める。モデルと補正の測定は引き続き分離する。
4. 自由継続で生成した未知状態に教師を問い合わせられない限り、DAggerとは報告しない。まずengineで作れる合法性・資源保存・系列完遂の自己教師信号と、3 anchorへの多相手最適化を追加する。
5. 次候補も同じ開発48試合で比較し、模倣改善だけでは昇格させない。開発条件を満たす候補が凍結されるまで、最終192試合は実行しない。

## 主な成果物

- `preregistration.json`: anchor、開発seed、封印した最終seed、判定規則
- `anchor_identity.json`: archive/member/engine hash
- `development_evaluation/games.csv`: 144試合の全結果
- `development_evaluation/summary.json`: seed-block集計と保守区間
- `imitation_metrics.json`: 既存全行動BCの保留模倣
- `imitation_metrics_round6_sequence_bc_v1.json`: 新候補の保留模倣
- `closed_loop_continuations*/summary.json`: 24/48/96/192/残期間の自由継続
- `candidate_v1_preregistration.json`: 新候補仕様の結果前固定
- `candidate_v1_offline_metrics.json`: 学習・validation・test指標
- `candidate_v1_archive_manifest.json`: 最終archive内部hash
- `candidate_v1_runtime_validation/summary.json`: 最終archiveの両seat時計検証
- `FINAL_STATUS.json`: 工程別状態

`Codex_Round6_Instructions_JA.md` はworkspaceと添付領域で見つからなかったため、その本文との機械的diffは未実施。ユーザーが本会話で提示した追補を最新仕様として適用した。
