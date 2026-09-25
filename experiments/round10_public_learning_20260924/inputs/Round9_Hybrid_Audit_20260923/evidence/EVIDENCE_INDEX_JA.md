# 証拠索引と独立検証の範囲

## 読み方

「独立再計算」は今回の監査スクリプトが保存物から計算した内容。「ソース確認」は添付コードの制御フロー・定数・モデルmetadataの確認。「保存報告」はCodexが残した実行報告で、今回engineで再実行していない内容である。

本監査では新規学習0、新規ゲーム実行0、Kaggle提出0、ポケモン実行0。保存されたA2 actor/marketモデルの23,406行の推論は実施した。native binaryやユーザーの提出agentコードを動かして対戦したものではない。

## 1. 成績・保存対戦の整合

- `replay_checks.csv`：全176保存試合の再確認。各行のall_checksはreplay SHA、diagnostic SHA、seed、状態数、status、資金、差額と元games.csvの一致を合成したもの。
- `panel_summary.csv` / `panel_summary.json`：全保存パネルの勝分敗・平均資金・平均差額。
- `small/v2_v3_independent_equivalence.json`：A2 v2/v3の共通8試合について、duration/remainingOverageTime以外のstepsとrewards/statusesの一致。

入力元はRound9各 `development_panel_*/games.csv` と、そのCSVが指すreplay/diagnostic。64試合の最終統計は `development_panel_a2_v2_expanded64` に限る。v3の64試合再検証、v123との対戦、176独立条件は主張しない。

## 2. 学習とraw推論

- `checkpoint_identities.json`：main2 seed×4 headの初期/最終hash、宣言hashとの一致、保存済みoptimizer step。
- `independent_model_inference.json`：保存配列を独立NumPy MLPで推論した結果。actor16,692行、market6,714行。
- `independent_model_class_metrics.csv`：各classのsupport/正解数/recall。marketはEOS予測件数も記録。
- `provenance_counts.json`：保存row provenanceの行数とpartition、episode数。

inputは `a2_prefix_bc/models_v1/seed_20260924/{actor_token,market_token}.npz` と `a2_prefix_bc/dataset_v1/` のtest配列。旧testは開発診断用で、新規holdoutではない。再推論はraw argmaxであり、game-state mask後の実戦成功率ではない。

actor全体83.27%、work89.54%、MOVE28.87%。market全体68.77%、EOS/HIRE90.42%、その他36.30%、SELL29.54%。全体値の分母はMOVE/PASSが1/8抽出されたwork-heavy集合であり、元の自然頻度のaccuracyとは違う。

## 3. 実戦の行動と農場状態

- `state_snapshots.csv`：最終64試合・両者の指定recordにおけるmoney、land、crops、animals、empty_pasture等。
- `mean_state_snapshots.csv`：上記の平均。
- `final64/behavior_counts.json`：試合別・両者の発行command、market、日別行動、即時逆戻り、終局在庫。
- `behavior_summary.json`：最終64試合集計。
- `key_summary.json`：主要比率と学習metricsの控え。

作物はtile.kind==`PLANT`、家畜はtileのanimalの存在、空牧草地はkind==`PASTURE`かつanimalなしで数える。土地はunlocked_quadrantsの数。dayはゼロ始まり。record192=day8、record480=day20。終局はrecord719。

行動は `steps[t] observation → steps[t+1] action → steps[t+1] observation` の対応で数えた。通常の移動往復もあり、immediate_backtracksを全件失敗とはみなさない。終局cropゼロも単独では不具合ではなく、day20の稼働作物・家畜と資金の成長停止を重視する。

A2:MOVE269,847/306,692=87.99%。相手42.35%。day20に48/64試合が作物・家畜ともゼロ。終局62/64で両方ゼロ、全64で家畜ゼロ。day20に空牧草地平均24.48マス。

## 4. モデルとruleの実際の役割

- `diagnostic_recount.json`：最終64試合46,016判断のplan、raw/mask/final、resolver理由、旧inline effect集計。
- `late_state_trace_examples.json`：保存traceから抽出した後半の判断例。

46,016/46,016判断でplan.disabled、active0/interventions0、final_actionとledger_action一致。103,922/306,692のactorでraw top1がmask候補外かつtoken変更。変更98,555件がMOVEで、65,180件はrawが作業。これはtrace上の集計であり、今回存在しない最終A2 source全行の不在証明ではない。

## 5. Pokémon source

- `POKEMON_CODE_EVIDENCE.md`：添付tarから読んだ該当ソースの行番号付き抜粋とモデルmetadata。

主な箇所：

- `main.py:89–154`：rule代替、is_scorable、ranker、planner補正、search条件、final commit。
- `main.py:157–167`：外部決定の履歴反映。
- `ml_runtime.py:276–297`：MLを使うcontext/単一選択/候補数の条件。
- `ml_runtime.py:319–353`：engine候補からのfeatures作成と候補処理。
- `ml_planner.py:116–143`：局面を限定した補正。
- **`turn_search.py:53`：ENABLED=False。** 末尾buildの早期returnにより既定のSEARCHはNone。
- `turn_search.py:39–52`：OFFにした理由についての開発者コメント。書かれた勝率の対戦生ログはこの添付にないため再検証済み成績とは扱わない。

ソース中に探索や手順commitの実装があることと、最終版でONになっていることは違う。上位docstringでなく実際のbuild/constantを優先した。

## 6. 保存報告として引用する内容

`SOURCE_ROUND9_REPORT_NUMBERED.md` は入力ZIPの `REPORT_JA.md` に行番号を付けたコピーである。

教師完全再生1440/1440、codec8824/8824、A2教師state-effect719/719、15fixture、T1/T2/T3、3件の回復ラベル、専用work effect100%は、この保存報告および関連保存結果で確認した。固定engineや元教師の完全リプレイが今回のZIPにないため、今回engineで再実行した検証ではない。

専用work effectと古いinline traceのeffectには計測方法・単位の違いがある。後者のwork34,951/success34,466を専用指標の直接反証として扱わない。次回はchecked/success/failure/unknownをaction ID単位で対応させる必要がある。

## 7. 添付の範囲

`attachment_scope.json` にZIP SHA、ファイル数、完全版manifestとの相対パス比較、今回含まれていないsource/archive等を記録した。実験ディレクトリexportに完全版manifestが入っていることが相違の原因であり、ファイル破損と断定していない。

## 8. 理論参考

外部論文は一般的な設計背景だけに使った。本ゲームでの勝率や改善保証には使っていない。

- Ross et al. (2011), PMLR15, A Reduction of Imitation Learning and Structured Prediction to No-Regret Online Learning.
- Laroche et al. (2019), PMLR97, Safe Policy Improvement with Baseline Bootstrapping.
- Silver et al. (2018/2019), arXiv:1812.06298, Residual Policy Learning.
