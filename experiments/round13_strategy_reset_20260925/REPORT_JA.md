# Round13 Strategy Reset 実行報告

## 結論

最終ステータスは **KEEP_B1** である。M1市場、P-EARLY4、P-ROTATE2はいずれも完成した異なる最終行動を実行し、P案は実生産・収穫・売却まで到達した。しかし事前登録した開発gateをすべて不通過で、独立holdoutへ進める候補はなかった。研究候補をKaggleへ自動提出していない。

提出用には、実物を再ハッシュしたRound10 tarの完全コピー `submission/round10_20260924_b1_herd_safe.tar.gz` を保存した。SHA-256は `3fff94ec235566fff3416627d2691dec2e502bc80646a9016ee15e6fc2067986`、内包 `main.py` は `b6553c296c556aff5b5e2d12b75618e505fa4d852afb5338414ac6d6e039cb02` である。

## 入力・B1・engineの同一性

- 入力ZIPは76メンバー、SHA-256 `38fc4ddbbbd1a90da1b73937f6c1a29d388953eb3315059289613e6907c35492`。
- 内包Round12 ZIPは306メンバー、SHA-256 `47e61b8324d2724face858ff846a8770ca5cd5e51cb7c0802c0b00307b14f20d`。リポジトリの既存ZIPと一致した。
- B1は1,040,805 bytes、7,141物理行、最終top-level callableは `opening_liquidity_agent`。
- 実物のRound10 tarは指定ハッシュと一致し、内包mainもB1と一致した。異なるartifactをB1として扱っていない。
- ローカル `kaggle-environments==1.32.7`。公式 `kaggriculture.py` のGit blobは固定参照 `302d8e20c83822b8d4572975cdea1180b792b748` と一致した。
- 反応型評価は既存cppsimを再利用した。binary SHA-256は `0fe077cc65622d6f6828160d90b617595a4aa7ea188e4afc67bfee8e4d290c92`。Round12の公式対cppsim 2反例parity結果を再利用し、このサイクルでは新しいsimulatorを作っていない。
- 既存の未コミット変更は消去・上書きしていない。ブランチ切替は行わず、新規 `experiments/round13_strategy_reset_20260925/` に隔離した。

詳細は `analysis/INPUT_AUDIT.json` にある。

## 実装した実行契約

全変更agentは各turnでB1を一度だけ呼び、`baseline_final_action`を得る。候補生成はコピー上で行い、共有cash・容量・market slot・重複品目・BUY/SELL・HIRE・種・動物・土地をまとめて検査し、選択後だけ予約と所有権をcommitする。次観測で在庫・約定・価格をreconcileする。

台帳は9 PRODUCTSを対象とし、相手値を `EXACT_ZERO / EXACT_POSITIVE / INTERVAL / UNKNOWN` に分けた。価格1の販売は区間、同品目BUY/SELL等の曖昧例はUNKNOWNとして消費側まで伝える。負残差を相手売却0へ丸めない。市場候補のdue stepは作成時に固定し、毎turn延長しない。

提出loader条件として、`__file__` なし、NumPyなし、最終callable、1 parent call、全品目台帳、価格floor区間、日境界DROP、同日購入種の先行使用禁止、`_cxd_candidates` の固定価格注文前倒し反例を含む9回帰テストが通った。提案内のresource validatorで却下された候補はB1へ安全fallbackしており、engineへillegal actionを送った件数は0である。

## 候補と実現した経済

### M1_DEADLINE_MARKET

B1のMILK/WOOL/STRAWBERRY/EGG全量売却から半量を最大4turn予約し、固定due stepで残量を処理する。無根拠WAITは作らず、購入資金を必要とする同turnでは発動しない。48試合で最終行動2,774turnがB1と異なり、872予約を作成、833完了、39は在庫0等で明示expiryとなった。28試合は作成した全deadlineを完遂し、20試合は少なくとも1 expiryを含んだ。

### P_EARLY4

step 1で初期COW 2頭のうち1頭を4イチゴ種へ等価置換し、B1のday2牛再購入を利用する。新土地は買わず、day2〜3の小麦再植え4マスをイチゴへ置換し、day5の種4単位を抑制して二重投資を避ける。所有マス上に既にいるactorだけを水やり・収穫へ使い、配送はB1へ任せる。

48/48試合でday2初植え、計192株、day5種抑制192単位、収穫・売却まで完遂した。したがってこれは「命令が失敗したP案」ではない。初版は移動中actorを奪って家畜経済を崩したため、(1) on-site/PASS限定、(2) on-site限定かつ配送をB1へ返す、の2回改良を行ってから凍結した。労働最適化P-LABORは独立の別経済として水増しせず、この所有権・締切schedulerとして両P案へ組み込んだ。

### P_ROTATE2

day18〜21、hour 18以降、WOOL価格30以下で、収穫・肥料を回収済みの隣接羊2頭を対象にする。FEED/CAREを止め、退出を待ち、2施設をDIGし、公開需要・相手作物・納品時価格からWHEAT/CARROT/TOMATOを選び、種購入・植付け・水やり・収穫・配送・販売まで所有する。

48試合中24試合でtriggerし、24試合すべてで2施設変換を完了した。実現した置換はTOMATOで、初植えはday18〜21、計200単位を収穫・販売した。残る24試合はtrigger条件が成立せず、B1と同一だった。

全candidate specificationは `configs/candidate_specs.json`、反復記録は `analysis/CANDIDATE_GENERATION_LOG.json`、実現物量は `analysis/candidate_realization_summary.json` にある。

## 反応型開発パネル

4 fresh development seeds × 6 opponents × 両seat = 48条件/arm、4 armsで192新規fullgameを実行した。相手はB1/v57/order_book/metav4に加え、生産構造が異なるbarnyardとmelon_thresholdを含む。相手は変更後観測を毎turn受けて再判断した。fixed tape、部分市場、固定shop改造環境の結果は0件である。

事前gateはpaired score +0.03以上、主要familyの最低差 −0.05以上、crash/illegal 0とした。結果は次のとおり。

| candidate | W/D/L | mean score | paired score差 | self cash差 | opponent cash差 | margin差 | status |
|---|---:|---:|---:|---:|---:|---:|---|
| B1 | 37/6/5 | 0.8333 | — | — | — | — | KEEP_B1 |
| M1 | 23/0/25 | 0.4792 | -0.3542 | -166.1 | +482.4 | -648.5 | RESEARCH_ONLY |
| P-EARLY4 | 8/0/40 | 0.1667 | -0.6667 | -3,797.0 | +13,293.7 | -17,090.6 | RESEARCH_ONLY |
| P-ROTATE2 | 17/2/29 | 0.3750 | -0.4583 | -5,776.4 | +3,446.6 | -9,223.0 | RESEARCH_ONLY |

勝敗遷移はM1が `D→L 6, W→L 14`、P-EARLY4が `D→L 6, W→L 29`、P-ROTATE2が `D→L 4, W→L 20`。L→WとD→Wは0だった。P-ROTATE2のtrigger 24件だけではpaired score差 −0.9167、self −11,552.8、opponent +6,893.3であり、未発動例が平均を薄めている。

family別score差は、M1がnear-lineage −0.5313 / barnyard 0 / melon 0、P-EARLY4が −0.7813 / 0 / −0.875、P-ROTATE2が −0.4375 / −0.5 / −0.5。条件数重みは2/3, 1/6, 1/6で、family等重みでもそれぞれ −0.1771, −0.5521, −0.4792。大勝marginで得点悪化を隠していない。seed bootstrapは4seedだけなので参考値に留める。

公式RNG結合により、同seedでもshop列がB1と異なった条件はM1 0/48、P-EARLY4 48/48、P-ROTATE2 14/48だった。これは公式総効果に含め、候補結果を見てshop条件を選別していない。全shop列はgames.csvに保存した。

生結果は `metrics/development/games.csv`、pairは `paired_rows.csv`、集計は `paired_summary.json`、192 replayはgzip JSONで保存した。engine failureは0。

## 最初の差分と因果追跡

`analysis/CAUSAL_TRACES.json` は最初の異なる最終action、その直前の位置・資金・shed・seed・actor inventory・市場、次状態、終局を保存する。

- 局所margin改善例: M1対v57、seed 812609254、seat 1。step257から126turnで差があり、B1は86,325対84,198（margin 2,127）、M1は85,778対82,673（margin 3,105）。両方Wでselfは547減っており、得点改善ではない。
- 明確な悪化例: P-ROTATE2対barnyard、seed 812609252、seat 0。step465から220turnで差があり、B1の113,797対85,282（W）が78,241対109,299（L）へ転落した。
- 無効果例: P-ROTATE2対B1、seed 812609253、seat 0。triggerせず差分action 0、両branch 109,255対109,255（D）で完全一致した。

## 売却予測学習

129保存episodeを丸ごと分割し、train 81 / validation 16 / test 32とした。同一試合の隣接rowは分割していない。testはorder_book/metav4 family、validationはfactorial v57、残りをtrainとした。前処理・時刻頻度・数量表・標準化はtrainだけでfitした。公開9特徴だけを入力し、private stateは約定売却の事後正解ラベルに限った。同品目売買等で不明なラベルは1/4/12 horizonで129 / 1,859 / 5,319件を除外し、0にしていない。

| horizon | frequency Brier | model Brier | frequency quantity MAE | model quantity MAE | q90被覆 | frequency価格影響MAE | model価格影響MAE |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.035775 | 0.034988 | 0.505068 | 0.497961 | 0.970584 | 0.274784 | 0.239345 |
| 4 | 0.096696 | 0.090926 | 1.362386 | 1.154516 | 0.940118 | 1.115091 | 0.746885 |
| 12 | 0.151775 | 0.120374 | 3.176854 | 2.570652 | 0.921130 | 2.583267 | 1.690936 |

27小型logistic modelを各5 epoch、計135 model-epoch更新した。最終modelは28,740 bytes、SHA-256 `29f94111c3c92e3de9bcc74ef975672e066c841957e1f1fab2a961c355d78138`、保存後reload一致。test 153,664推論は約19.4 microseconds/件だった。最大誤認例はreportへ保存した。

ただし方策には接続していないため、使用された意思決定0件、B1との差は未測定である。offline予測改善を方策強化と呼ばない。計画selectorも、正のcandidateが0だったため学習0件で、候補生成へ戻す。

## 公開完成方策の確認

既存台帳・opponent poolから12候補を登録し、新規downloadは行っていない。author/version/license/hash/entrypoint/評価有無は `REGISTRY.json` に保存した。実行パネルは6系統で停止した。barnyardは本パネルでday7 strawberry、carrotなし、B1の2倍のmelon植付けを実行し、生産差を確認した。タイトルやratingだけでは採用していない。license不明のartifactは `UNKNOWN_NOT_FOUND`、barnyardは `NOT_ESTABLISHED` と明記した。

## 昇格判定と提出順

候補は全て development gateを明確に不通過なので、独立32seed評価は実施しない。これによりdevelopment選択バイアスを「holdout結果」と誤表示しない。最終結果は **KEEP_B1**、候補は **RESEARCH_ONLY**。B1のhashは維持した。

提出直前に公式deadlineと「最新2提出」の規定、および現在のsubmission履歴を再確認する。このサイクルの公開ページ確認はHTTP 200までで、未認証shellから規定本文を再取得できず、Kaggle CLIにも認証がなかった。過去確認値は2026-09-30 23:59 UTC（JST 10月1日08:59）である。

最新2枠が有効なら、安全な手順は次である。

1. 今回の研究候補は提出しない。
2. B1が既に最新2枠の外なら、保存済みの完全一致tarを手動で再提出する。
3. 将来holdoutを通ったchallengerを1本だけ試す場合は、challengerを先、B1を最後に提出し、B1を最新枠へ残す。B1の後へ2本提出しない。

ローカル得点から2500/3000等のratingを保証しない。
