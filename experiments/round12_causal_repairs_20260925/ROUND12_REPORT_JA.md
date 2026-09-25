# Round12 因果分離・実装検証報告

## 結論

Champion は B1 のまま維持する。保存した `P0M0_B1/main.py` は元 B1 と byte-for-byte 同一で、SHA256 は `b6553c296c556aff5b5e2d12b75618e505fa4d852afb5338414ac6d6e039cb02` である。Kaggle 提出、Notebook 公開、Git push、課金は0件である。

入力台帳と価格下限の欠陥は、B1を改変せず別armへ実装した。固定回帰は通った。一方、WAITを選ぶ市場則と新生産経路は終局得点を改善せず、未来参照oracleにも改善余地がなかった。したがって新規holdoutは開かず、学習器も作らなかった。

## 実装した修正

`P0_ledger_only` は最終entrypointの返却直前に、最終actionからpost-field shedと実行可能な自己SELL量を純粋関数で再計算する。同ターンDROP/PLACE、shed capacity、先頭10注文、重複SELL、在庫不足、後段での削除・並べ替えを反映する。候補比較でB1本体を複数回呼ばず、live stateを更新するのは最終採用actionだけである。

`P0_censor_only` は市場在庫差を点推定へ強制せず、`exact`、`interval`、`censored`、`unknown` と、更新側で扱う `lower_bound` 区分を持つ。下限到達時は観測不能な数量を0売却とせず、実行時特徴は公開観測と自己最終actionだけから作る。相手の非公開在庫、controller状態、未来行動は使わない。

固定例の結果は次の通り。

- seed 612609264 / step 645: 最終SELLは STRAWBERRY 13、WOOL 7。自己実約定を13、7と確定し、相手WOOL売却は0として扱える。旧誤推定の7は除去された。
- seed 612609254 / step 456 / WOOL: 開始価格37、自己実約定12。相手数量は公開情報だけでは `censored [0,100]` とし、旧値 -6 を生成しない。テスト専用真値12は区間内にある。
- seed 532609243 / step 668: CW1のWOOL 3は既存 `_v92_predict` と同じ最終注文であり `REDUNDANT_WITH_BASELINE`。二重注文を追加しない。

## 回帰テスト

要求された7項目を `tests/test_round12_regressions.py` に実装し、7/7 passした。

1. `test_final_ledger_matches_final_action_and_fill`
2. `test_mid_order_price_floor_censoring`
3. `test_cw1_redundant_with_existing_predictor`
4. `test_candidate_evaluation_is_state_pure`
5. `test_branch_opponent_remains_reactive`
6. `test_new_route_feasibility_and_completion`
7. `test_loader_archive_and_episode_reset`

loaderテストは公式 `get_last_callable` の空exec名前空間、最後のcallable、tar同梱、両seat独立load、連続episode resetを確認する。診断関数は最後のcallableではない。

## 入力修正の終局比較

既知のRound11開発seed 612609254、612609264、相手B1/v57、両seatの8試合/armで比較した。新規holdoutではない。

| arm | B1比得点差 | 平均自資金差 | 平均相手資金差 | 平均margin差 | W→L | L→W | 片側90% seed-bootstrap下限 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 台帳のみ | +1.0 | -37.75 | -57.50 | +19.75 | 0 | 0 | 0.000 |
| 打切りのみ | 0.0 | 0.00 | 0.00 | 0.00 | 0 | 0 | 0.000 |
| 両方 | +1.0 | -37.75 | -57.50 | +19.75 | 0 | 0 | 0.000 |
| 市場WAIT則 | -6.0 | -1326.75 | +906.75 | -2233.50 | 4 | 0 | -0.750 |

台帳修正は正しさが確認でき、既知小パネルでは悪化しなかったが、2 seed・近縁2相手だけなのでchampion候補とはしない。打切り修正はこのパネルの最終結果を変えなかったが、曖昧な0を教師イベントへ入れないという入力の正しさは保持する。

## 市場候補の実行段階

既知入力パネルの8試合合計で、`proposal_generated=198`、`candidate_different_from_baseline_final=106`、`candidate_survived_finalization=192` だった。paired replay上では初回分岐後を含む最終action差392、次状態の自己資金またはshed差392、将来状態差392、終局自資金差が出た試合8/8であった。終局自資金差合計は -10,614。

分類は `selected_wait=106`、`selected_baseline=86`、`overwritten_during_finalization=6`、`guard_not_met=5554`。提案数198を最終変更数とは呼ばず、最終action差106をその後の反応による392差とも混同しない。

## 新生産経路

B1を呼ばない独立controllerとして、day0 WHEATで資金を作り、day2にSTRAWBERRY 8株、day15以降16株へ拡張し、土地、種、人員、水やり、収穫、搬入、売却を終局まで制御する経路を実装した。P1の市場はP1自身の将来供給に合わせ、B1の予約売却を流用していない。

最終版の開発8試合では全試合が正の資金でDONE/DONEとなり、初植え日は全てday2、最大16株、STRAWBERRY収穫・売却は各63、搬入失敗0、終局資金は6,906〜17,358（平均12,834）だった。しかし各試合で継続作物9株分の損失・再購入があり、対B1は0勝8敗。これは「完走可能」だが「維持義務が健全」「強い」経路ではない。失敗した32/48株志向の版も開発履歴として残した。

## 2×2 因果比較

新しい開発seed 712609243〜244、4相手、両seat、16試合/armで実行した。これもholdoutではない。

| arm | W/L/T | 得点 | P0M0比 | 平均自資金差 | 平均margin差 |
|---|---:|---:|---:|---:|---:|
| P0M0 | 10/2/4 | 12.0 | 0.0 | 0.00 | 0.00 |
| P0M1 | 4/12/0 | 4.0 | -8.0 | -124.13 | -561.13 |
| P1M0 | 0/16/0 | 0.0 | -12.0 | -92609.63 | -166912.00 |
| P1M1 | 0/16/0 | 0.0 | -12.0 | -92606.25 | -166908.13 |

P1上でのM1−M0は得点差0、平均自資金 +3.375、平均margin +3.875に留まる。市場M1はP0で全4相手に得点 -2ずつであり、局所cash差を終局勝利へ結び付けられていない。

未来を見て4 armから毎試合最善を選ぶ診断oracleは16/16でP0M0を選び、得点差0だった。候補集合自体に上限改善がないため、価値推定器を学習しても選択器問題を切り分けられない。学習更新、weight保存、reload、新規model推論、学習選択はいずれも0である。

## parity と実行環境

P0M1がB1から実際に分岐する seed 612609254 / v57 / seat0 と、独立P1の seed 712609243 / B1 / seat1 で、公式PythonとC++を新規に完走した。両ケースとも719意思決定、720状態、DONE/DONE、終局資金が一致し、不一致0だった。これはこの2軌跡のparityであり、全状態空間の同値証明ではない。

使用中の `kaggriculture.py` は1.32.7、SHA256 `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e` で、固定commit 302d8e20...についてRound10台帳に記録された参照SHAと一致した。`agent.py` は `9b7682ce9921c8f34080a8be0f7b41598cc12ac7eb14d24e4b707883f25213b6`。

## 入力アーカイブの注意

Round10の3 tar、B1 main.py、M20 main.pyは指定hashと一致した。M20は実ファイルから `98d374f58f68c5b9f263eb3ed04f724e1e0b7a4fa562b581bdac90b276492c4a` を生成しており、誤記 `98d374ab...` は使っていない。

一方、現在見つかるRound11 Execution ZIPは `eaffe964...`、Research Revision ZIPは `00c3048e...` で、依頼に示された `60b04f07...`、`d42d1759...` と一致しない。展開済み資料、個別B1/M20、対戦相手のhashを別途固定して実行した。独立監査ZIPは `8e8434b2...`。詳細は `INPUT_HASHES.json` にある。

## 実行済み・再集計・静的確認・未検証

- 実行済み: 保存済み反応型C++ full-game 129、最終parityのC++ 2ケース、公式Python 2ケース、回帰7件。公式parityは比較器修正前後で同じ2設定を2回ずつ実行したため、公式の実invocationは4。
- 保存結果の再集計: 今回生成したpanel CSV/replayのみ。Round11既存876試合の再集計は0で、独立監査報告を読んだだけである。
- 静的に読んだだけ: Round11独立監査報告、公式ソースの固定台帳、公開対戦相手の出典情報。
- 未検証: 新規holdout、外部familyの独立性、公開レート、Kaggle提出性能、32/48株の健全な維持、学習selector。
- 除外: 最初の120秒中断で完走表示された17試合はpanel CSVが完成しなかったため、統計から除外した。

## 採用判断

`P0M1` と `P1*` は棄却。台帳・打切り修正は正しさの修正として保持するが、狭い既知パネルしか通っていないので未採用。新規holdout seedは0、holdout試合0。B1を維持する。

根拠データは `metrics/round12_paired_analysis.json`、`metrics/route_summary.json`、`metrics/input_ledger_regressions.json`、`metrics/official_cpp_parity.json` を参照すること。
