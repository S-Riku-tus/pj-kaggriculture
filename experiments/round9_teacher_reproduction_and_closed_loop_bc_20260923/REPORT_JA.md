# Round9 教師再現・prefix整合BC・閉ループ評価

## 結論

今回の「100%」は教師模倣accuracyではなく、**実際に発行された非移動・非PASS作業のうち、固定engineで直後に効果が確認できた割合**である。A0では1,157/1,157、A2の64試合では35,683/35,683で100%だった。しかし、これは「教師と同じ作業を選んだ」「十分な仕事量を選んだ」「生産物を回収・販売した」「相手より稼いだ」のいずれも意味しない。

元教師試合は、双方の正解actionを正しいrecord対応で渡すと、固定engine上で1,440/1,440 state-seat、最終資金111,530/99,333まで完全再現した。codecも数量・順序・EOS込み8,824/8,824で可逆だった。したがって、原リプレイ、固定engine、基本的なobservation/action整列、codecは正例対照を通過した。

切断点は二つある。第一に旧decoderは、教師actionを直接入れても要求保持8,648/8,824、joint turn完全一致608/719であり、有効な状態効果も6 turn壊していた。A2では状態効果719/719へ修正した。第二に、学習器は教師actionそのものを十分再現できない。単一軌跡専用に実学習したmemorizerでもT1 joint turnは596/719、T2は460/719、自由実行T3は18/719、state完全一致は16/720まで崩れた。つまり、実行契約の破壊を直しても、actor/orderの小さな誤差が自分生成stateで累積する。

最終A2は独立学習方策のままA0 pureより経済を改善したが、競争優位には届かなかった。既存8条件では0-0-8、平均自資金10,787.75、平均margin −128,250.375。新規64試合でも0-0-64、平均自資金9,604.546875、平均margin −147,861.125だった。よって「学習更新」と「自律経済改善」は成立、「v122/v124超え」と「提出準備」は不成立である。

## 冒頭サマリー

| 項目 | 数値・判定 |
|---|---:|
| 教師actionのcodec raw再現 | 8,824/8,824 = 100%（command/order/EOS、数量込み） |
| A0 final要求保持 | 8,648/8,824 = 98.0054% |
| A0 final joint turn一致 | 608/719 = 84.5619% |
| A0 official state-effect同等 | 713/719 = 99.1655% |
| A2 final要求保持 | 8,659/8,824 = 98.1301% |
| A2 final joint turn一致 | 612/719 = 85.1182% |
| A2 official state-effect同等 | 719/719 = 100% |
| 元教師の正解再生 | 成立。1,440/1,440 state-seat、資金111,530/99,333 |
| 単一軌跡memorizer T1 joint | 596/719 = 82.8929% |
| 同T2 joint / state effect | 460/719 = 63.9777% / 485/719 = 67.4548% |
| 同T3 joint / state exact | 18/719 = 2.5035% / 16/720 = 2.2222% |
| A0 work effect | 1,157/1,157 = 100%、ただし平均資金1,411.875 |
| A2 64試合 work effect | 35,683/35,683 = 100%、day-boundary/terminal UNKNOWN 730 |
| A2 64試合回収 | WHEAT 4,478、MILK 861、MELON 924、WOOL 421 |
| A2 64試合実販売 | WHEAT 5,536、FERTILIZER 2,158、MILK 861、MELON 855、WOOL 421 |
| 独立A2 8試合 | 0-0-8、資金10,787.75、margin −128,250.375 |
| 独立A2 64試合 | 0-0-64、資金9,604.546875、margin −147,861.125 |
| hybrid参照8試合 | 0-0-8、資金17,696.5、margin −114,612.125。独立学習成功とは数えない |
| 実装成功 | 成立 |
| 学習更新 | 成立（3 run / 12 head fit） |
| 実行契約 | 正例対照と15 fixtureでは成立 |
| 自律経済改善 | A0比で成立、hybrid比では不成立 |
| 対戦優位 | 不成立 |
| 提出準備 | 不成立 |
| 新規実相手対戦 | 176試合、126,544 joint-action call |
| 新規Kaggle提出 | 0 |

## 1. 事実：元教師を完全再生できるか

teacher submission 56216119のepisode 109118332、seed 338650874を選んだ。リプレイ形式を実データで一手ずつ校正した結果、対応は `steps[t]のobservation → steps[t+1]に保存されたaction → steps[t+1]のobservation` だった。

双方の完全actionを初期状態から固定engine 1.32.7へ渡すと、720 records × 2 seats = 1,440/1,440でpublic stateと各seat private stateが一致した。最初の不一致はなく、最終statusは双方DONE、報酬も記録と同じ111,530/99,333だった。「同じ初期状態・相手行動・乱数・設定・完全actionなら元教師の状態と資金が再現される」という正例対照は成立した。

この結果は再生系の校正であり、新しいagentの勝率ではない。

## 2. 事実：表現とdecoderのどこで壊れたか

原actionからoperation、item、quantity、actor identity、market順序、EOSへ変換し、actionへ戻した。actor 7,196/7,196、market order 909/909、EOS 719/719、数量932/932、合計8,824/8,824で完全一致し、UNKNOWN labelは0だった。数量語彙外を分母から除外して100%にした結果ではない。

同じ教師state cloneへ正解joint actionを注入し、raw→mask→ledger→final→official engineを比較した。

| 版 | 要求保持 | joint turn完全一致 | official state-effect同等 |
|---|---:|---:|---:|
| A0 frozen | 8,648/8,824 | 608/719 | 713/719 |
| A1 frozen重み＋prefix合法化 | 8,648/8,824 | 608/719 | 713/719 |
| A2 unified prefix | 8,659/8,824 | 612/719 | 719/719 |

A0/A1の最初の有害差は旧market ledgerの「保証された資金」判定が合法な注文を消すことだった。A2は部分約定とaccepted prefixを固定engineへ合わせ、有効状態効果を全turn保持した。要求完全一致が100%でないのは、engine効果を変えないno-op/正規化された要求も数えるためであり、state-effect 100%と区別した。

負例対照はall-PASS、移動だけ、作業削除、全数量1置換、教師action 1-stepずらしの全てで該当指標が悪化した。all-PASSのwork effectは0/0を100%とせず、`ratio=null, NOT_APPLICABLE` とした。

## 3. 事実：データ利用と実学習

ローカルには全source appearance 864、重複除去後850 episode、対象teacher family 579 episodeが存在した。既存splitはtrain 403 / validation 88 / 旧test 88。最初の制御学習ではfamilyを1つに固定し、実在確認した20 episodeだけを決定論的に選び、train 12 / validation 4 / 旧test 4とした。旧testは既に設計判断に使われているため、新規holdoutとは呼ばない。

20 episodeは14,380意思決定、正規化前actor command 144,015件だった。全workと数量2以上を保持し、movement/PASSだけをepisode/day/hour/actor/tokenのhashで1/8層別抽出した。固定strideは使っていない。actor rowsはtrain 50,461 / validation 16,691 / 旧test 16,692、marketは20,038 / 6,650 / 6,714で、market orderとEOSは全件保持した。各行のepisode、record、step、actor/order slot、day/hour、operation/item/quantity、teacher、label由来、partitionはgzip CSVに保存した。

入力はmean=0、scale=1である。Round8以前の極小分散問題を現行へ流用していない。相手private、未来Shop、未来action、最終勝敗は入力していない。

A2はlearning seed 20260923と20260924で4 headずつ実学習した。初期/最終checkpoint hash、loss curve、best epoch、checkpoint optimizer step、total optimizer stepを保存した。validationだけでseed 20260924を選んだ。

| head | validation | 旧test（開発診断） |
|---|---:|---:|
| actor token | 13,933/16,691 = 83.4761% | 13,899/16,692 = 83.2674% |
| market token incl. EOS | 4,691/6,650 = 70.5414% | 4,617/6,714 = 68.7668% |
| actor quantity・既知行 | 935/1,284 = 72.8193% | 850/1,205 = 70.5394% |
| market quantity・既知行 | 1,641/2,608 = 62.9218% | 1,641/2,669 = 61.4837% |

これはRound8の58.17%/69.54%よりactor tokenを改善したが、異なるsampling・特徴・行集合なので、単純な同一分母比較ではない。100%でもない。

## 4. 事実：単一軌跡のT1/T2/T3

episode 109118332の全719意思決定、actor 7,196 rows、market 1,628 rowsを間引かず使い、別のtrajectory memorizerを180 epoch上限で実学習した。byte-exact入力ごとのlabel衝突はなく、経験的上限はactor/marketとも100%だった。

それでもT1はactor token 7,089/7,196、market token 1,601/1,628、joint turn 596/719だった。100%に届かなかった残差はcodec衝突ではなく、有限容量・最適化の残差である。

teacher physical stateのまま先行prefixを自己生成するT2では、最初のtoken差がstep 15に現れ、joint 460/719、official state effect 485/719へ低下した。初期状態からphysical stateも履歴も自己生成するT3では、最初のstate差record 16、cash差record 17、売却差step 16、最初の失敗work step 319。joint 18/719、state exact 16/720、最終資金4,658対教師111,530だった。

main A2は、このepisodeに対するT1 jointが14/719、T2 state effectが24/719、T3 jointが3/719、state exactが2/720、最終資金1,353だった。単一軌跡memorizerよりさらに一般化誤差が大きい。

T3は記録相手actionを固定再生した`REPRODUCTION_DIAGNOSTIC`であり、未知相手への勝率ではない。結果は「高いhead accuracyや一手効果が、閉ループの完全軌跡を保証しない」ことを直接示す。

## 5. 事実：固定engine fixtureとloader

15 fixture全てが通過した。対象はPLANT→WATER、HARVEST→PLANT、BUILD→PLACE、PLACE→PICKUP、重複FEED後CARE、WATER→HARVEST、FERTILIZE→WATER→HARVEST、同turn種不足、部分PICKUP、倉庫満杯DROP、部分BUY、SELL→BUY、DROP→SELL、日替わりactor再生成＋market、終局直前の最終意思決定である。

この過程で三つの実装欠陥を修正した。

- 3層checkpoint loaderのimport順により`w3`が読まれない問題。
- WATER後のcrop yield更新がshadowにない問題。
- 同一callableで連続episodeを実行したときのstep 0 reset不足。

最終archiveを`C:\tmp\round9_a2_v3_loader_audit_20260923`へ展開し、公式`get_last_callable`で`agent`が選ばれること、runtime/spatial/model/commonと4重みが全て展開先由来であること、2 episode連続で各3 decisions・trace step 0開始になることを確認した。

## 6. 事実：実相手と経済会計

同じv122/v124 × seed 2026102201/2026102202 × 両seatの8条件では次の通りだった。

| arm | 勝-分-負 | 平均自資金 | 平均margin | 動物生産/回収がある試合 |
|---|---:|---:|---:|---:|
| A0 frozen pure | 0-0-8 | 1,411.875 | −137,263.375 | 0/8 |
| A1 frozen重み | 0-0-8 | 648.25 | −146,260.125 | 0/8 |
| A2 final v3 | 0-0-8 | 10,787.75 | −128,250.375 | 8/8 |
| Round8 hybrid参照 | 0-0-8 | 17,696.5 | −114,612.125 | 別契約 |

A2はA0に対し平均自資金+9,375.875、margin +9,013.0。ただしhybridより資金−6,908.75、margin −13,638.25である。A1の悪化は「decoderだけ直せば旧checkpointが強くなる」という仮説を否定した。

事前追記した新規seed 16個 × v122/v124 × 両seatの64試合では0-0-64、平均自資金9,604.546875、margin −147,861.125。v122別は資金9,593.78125、margin −148,411、v124別は9,615.3125、−147,311.25。seat 0は10,227.09375、seat 1は8,982.0だった。同seed内相関があるため64試合を完全独立とは扱わない。

64試合のcashは全64件で誤差0に再計算できた。

`開始192,000 + 実売上790,105 − 購入301,715 − 雇用49,699 − 土地16,000 = 終了614,691`

平均終了資金は614,691/64 = 9,604.546875。購入内訳はseed 59,000、product 83,015、animal 159,700。実販売はWHEAT 5,536、FERTILIZER 2,158、MILK 861、MELON 855、WOOL 421。回収はWHEAT 4,478、MILK 861、MELON 924、WOOL 421だった。animal exitは317であり、全てを一律errorとは判定していない。

A0の8試合も会計誤差0で、開始24,000 + 売上29,183 − 購入38,535 − 雇用1,353 − 土地2,000 = 終了11,295、平均1,411.875。作業が1,157/1,157成功しても、売上より購入・雇用・土地支出が大きく、十分な生産・回収・再投資ループになっていなかった。

A2の64試合でもwork effectは35,683/35,683で100%なのに全敗である。従って100%が弱さと矛盾しない理由は抽象論ではなく、**条件付き一手効果の分母が、教師一致、機会に対する処理率、販売、cash-flow、相対marginを測っていないから**である。

## 7. 自分の失敗状態と回復例

A2 T3からday boundary、最初のwork失敗、seed不足、資金0、手持ち品を倉庫へ運べない状態、最終清算窓の6状態を`recovery_states_v1/states.json.gz`へ保存した。教師の同じ時刻のactionは貼っていない。

固定engineを使う短期局所searchで3ラベルだけを検証した。

- record 192: 資金0、shed WHEAT 13をSELLし、cash 0→417。
- record 319: WHEAT 2を持つactor 0がEASTへ移動し、shed accessまでのManhattan距離5→4。
- record 718: 最後に実行可能な判断でshed MELON 5をSELLし、cash 1,353→2,507。

残り3状態は一手の効果だけではtask所有・中期収益を正当化できないため未ラベルとした。この3例はA2へ再学習しておらず、DAggerとは呼ばない。相手未来行動も使っていない。

## 8. 判定

| 判定軸 | 判定 | 根拠 |
|---|---|---|
| 実装成功 | PASS | 正例再生、codec、A2 state-effect、15 fixture、公式loader、reset |
| 学習更新 | PASS | 2 main seed + 1 trajectory seed、合計12 head fit、初期/保存hash差あり |
| 実行契約 | PASS（検証範囲） | 教師正解を通したA2 state-effect 719/719 |
| 自律経済改善 | PASS（A0比） | 8条件で資金+9,375.875、64試合でも平均9,604.55、動物生産/回収62/64 |
| hybrid超え | FAIL | 同じ8条件で資金・marginともhybrid未満 |
| 対戦優位 | FAIL | 8試合0勝、拡張64試合0勝 |
| 提出準備 | FAIL | fresh final holdout未実施、競争ゲート未達、Kaggle提出0 |

## 9. 合成・仮説・未確認

合成fixtureで確認したことは、代表的な同turn連鎖と部分約定にA2 shadowが固定engineと一致することだけである。実対戦における各fixture頻度や寄与率ではない。

現在もっとも支持される仮説は、単純なDCT＋独立token headが短期の作業分類は学べても、目的地・対象・task継続/完了・回収/販売/再投資という因果履歴を十分に保持できず、T1→T2→T3の分布ずれで崩れるというものだ。ただし、encoderと履歴を同時に変更した比較はまだ行っておらず、確定原因とはしない。

未実施・未確認は次の通り。

- train 12から48以上への段階的データ拡張。
- raw-grid CNNまたはentity encoderの比較。
- task/target/継続・完了headと短期履歴の追加。
- 回復3ラベルを含む正式なrecovery dataset学習。
- 候補固定後の未使用fresh holdout。既存sealed rangeは開けていない。
- Kaggle実提出、rating推定、3000到達予測。

これらを行っていないため、精度からratingへ換算せず、提出推奨もしない。

## 10. 次の決定

次はA2のデータ量とencoderを同時に変えない。まず現在の20 episode・同一decoderを固定し、B3相当の`task/target/continue-or-complete + 短期因果履歴`を追加した一変更比較を行う。通過条件は、単一軌跡T2 state-effect 67.45%を上回ること、別episode T1/T2 jointを改善すること、回復ラベルをoriginal/searchで分けること、8試合でA2 v3の資金10,787.75またはmargin −128,250.375の少なくとも事前指定した主指標を改善することとする。その後にepisode数だけを12→利用可能な実数へ拡張する。

最終archiveは `artifacts/submissions/round9_20260923_a2_prefix_bc_seed20260924_v3.tar.gz`、SHA256 `f5ac17a3b7db2d1311f066f9e19b1c8aa0ccf577d0955b7e2a78e03b8246811a`。これは再現・研究用の最良独立A2であり、提出推奨archiveではない。

