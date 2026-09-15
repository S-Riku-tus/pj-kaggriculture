# V111 midgame capacity 研究報告 — 2026-09-16

## 最終判断

`REJECT_NO_FEASIBLE_CONTRACT`。

旧 spent V111 control 32 contexts と保存済み current Top 30 target seatsだけを再解析した。新しいgame、candidate、numeric agentは作成していない。production ChampionはV111のまま維持する。

同一支出familyとして最も強かったのは `BUY_ANIMAL:COW` だった。COW購入費を一時的に戻す算術上界では、4 sources・16/16 source-seed blocks・32/32 seat contextsで、第3農地代2,000と固定activation reserve 11へ到達し、actual V111より24 decisions以上前倒しできた。算術上の前倒しはmedian 91、mean 94.75、range 91–106 decisionsである。

しかし、これは実現可能なcoinやpaired upliftではない。第3農地前までにV111は32 contexts合計で新しいCOWを232頭配置し、COWを対象とするPICKUP 174、PLACE 232、FEED 848、CARE 856、COLLECT_FERTILIZER 616 actionsを既に実行していた。COW購入だけを抜くとこれらのfield scheduleが欠品/no-op/別stateになり、そのtask debtを回収しながら新規SW区画のWHEATを同日PLANT/WATERし、HARVEST、carry/drop、committed SELL、明示的rejoinまで閉じる一意なcontractを旧replayから定義できなかった。

従って実装gate 1（同一familyの2 sources/4 blocks）・5（V111既存familyだけ）・8（P1/Top依存なし）は成立したが、2（maintenanceを保つ24-step activation schedule）・3（調達からsaleまでの一意なstate machine）・4（state-compatible suffix/general executor）・6（全resource preflight）・7（V109 broad fallbackと区別できる限定executor）が不成立だった。C1を捏造せず、A/A、smoke、旧spent paired、Developmentへ進まなかった。

## 開始時保全と入力監査

開始時はbranch `main`、HEAD `21e91ece0039ed6bd74add48e0c2e46f8ba385ef`、既存dirty差分なしだった。UTC開始 `2026-09-15T22:12:12.2952552+00:00`、JST開始 `2026-09-16T07:12:12.2952552+09:00`、deadlineはJST `12:12:12.2952552` と固定した。開始時のPython/Kaggle processは0だった。

必読資料、engine/configuration、V111、評価core、control replay、Top replay、user prompt、preregistrationをSHA-256固定した。A0 spentから再利用したV111 controlは32/32が固有body、720 states / 719 decisionsで、既存pair JSONLのduplicate/partialは0だった。repository全体のstructured seed recordとfree-text mentionを分離し、promotion、Fresh、旧Development、今回条件付きDevelopmentの4範囲はいずれもruntime使用0を確認した。

保存済みLeaderboard snapshotは開始時点で約30.64時間前だった。24時間超のためread-only refreshは許容されたが任意規定であり、今回のgateは保存済みreplayだけで完結するためrefreshしなかった。旧corpusとの混在、対象team/row数の結果後変更はない。

## cash shortageと支出family

V111のcash不足は再現した。step 192/198/209/216/222のcash中央値は482/77/55/216/103.5で、cash≥2,000は全て0/32。step 240は中央値1,403で8/32、step 248は1,788.5で2/32、step 253は3,379で32/32だった。第3農地unlock stateは24 contextsがstep 253、8 contextsが266で、中央値253、mean 256.25である。Top 30 target seatsは中央値209、mean 210.1だった。

step 144からactual unlock前までのengine-committed COW購入費はcontext当たりmin 2,000、median 4,000、mean 3,450、max 4,000だった。これを同じfamilyとして一時延期するshadowでは、2区画目unlock後のdecision 159または161で2,011へ届く。全16 source-seed blocks・4 sourcesが24 decisions以上のcapital-only条件を満たした。

他familyのcapital-only成立数は、STRAWBERRY seedが12 blocks・3 sources、WHEAT seed/MELON seed/BUY_PRODUCT WHEAT/HIREが各4 blocks・2 sourcesだった。ただしWHEAT productはFEED maintenance、HIREはmaintenance/harvest/carry capacityを直接損なうためdeploy候補にしなかった。STRAWBERRY等も既存生産を止めるopportunity costがある。結果に応じてfamilyをcontext別に切り替えていない。

shadowは各pre-cashへ同一familyの実成立費だけを足した算術上界である。future price、Town、相手応答、延期COWのmilk/fertilizer、worker位置、RNGを固定したcounterfactualではない。実現可能なcoin、performance、E2 evidenceとは呼ばない。

## land購入後activation

購入後のactivation遅延は弱点ではなかった。第3農地unlockから最初の新SW区画productive actionまで、V111はmean 1.75、median 2、range 1–2 decisions。Topはmean 2.17、median 2.5、range 0–5だった。従って `post_unlock_activation_only` を作る根拠はない。

V111のunlock後、最初のwhole-farm HARVESTはmedian 4、最初のcommitted SELLもmedian 4だった。Topはそれぞれ8と1。ただしreplay inventoryはfungibleであり、これらを新規区画由来harvest/saleへ帰属できない。baseline factual eventを `land → incremental harvest → realized sale` の因果chainとは呼ばない。

V111のproductive tilesはstep 144/192/216/240/264/288でmean 24.44/45.47/46.72/47.72/52.47/69.97だった。Topはstep 144で24.67、192で49.23であり、保存済み既知結果どおり差は主に216–264に現れる。全checkpointのcash、productive/empty/weed、handsは `capacity_mediator_timeline.json`、context-stepのportfolio、worker位置、shed/seed、market/Townはcashflow/timeline artifactに保存した。

## COW延期contractが閉じなかった理由

COW購入延期自体はV111既存familyのresequenceであり、Top/P1 portfolioのコピーではない。しかし実際のV111 routeでは、購入直後からPICKUP、複数PASTUREへのPLACE、その後の日次FEED/CARE/COLLECT_FERTILIZERがhard scheduleへ織り込まれている。購入orderだけを止めると、次のいずれかが必要になる。

- missing COWに向かうPICKUP/PLACEを別taskへ置換する。
- 既存animal/cropのurgent maintenanceを保ちながらSWへunitを移動する。
- WHEAT seed購入、PLANT、同日WATERをmarket-order上限とdaily hire reset内で成立させる。
- 2–4日後のHARVEST、carry/drop、oversizedでないSELLをfungible inventoryから追跡する。
- 延期COWをcatch-upするか明示cancelし、その後のFEED/CARE scheduleと元routeへstateでrejoinする。

これらは単なるCOW order延期ではなく、広いfield routeの再構成になる。どのactionを置換し、どのmaintenanceを残し、いつCOW debtを回収するかをcurrent stateだけから一意に決めるexecutorは旧replayから証明できなかった。固定step表へ戻るのも禁止されている。V109のmissing-third-land broad fallbackは土地を買ってもmean rewardを97,961から85,395へ悪化させており、同じ不完全contractを再試行する理由はない。

resource距離だけなら24 decisions以内のSW到達・PLANT/WATERは可能だが、これはmaintenance-preserving scheduleではないためgate 2を合格にしなかった。完全contract数は0である。

## mechanism attribution

Evidence:

- step 192–222では32/32が2,000未満であり、V111のTop中央値step 209における直接制約はcash shortageである。
- actual COW支出を戻す算術では全16 blocks・4 sourcesで大幅なcapital headroomが現れる。
- V111のactual unlock後productive actionは1–2 decisionsで、post-unlock idlenessは小さい。
- Topの勝ち/負けにおける第3農地中央値は208.5/210でほぼ同じであり、早期land単独はTop内勝敗を説明しない。

Inference:

- COW familyはV111の第3農地遅延を生む主要な資金拘束候補である。
- ただしCOW scheduleのproductionとmaintenanceを失わずにland revenueへ転換できる可能性は、完全executorがあれば初めて検証できる。

Unknown:

- COW延期後に実際に得られるself coin、new-land incremental harvest/sale、lost milk/fertilizer、market/Town mediator。
- opponent action/coinのclosed-loop応答とmargin。
- maintenanceを保つstate-compatible catch-up/rejoin。

従って相手coin低下やTop productive tileを`BUY_LAND`または特定cropの因果効果とは扱っていない。`mechanism_attribution.json`ではcash shortage、family、earlier land、productive action、harvest、sale、opponent coin、marginを別nodeにした。

## 既存研究との整合

PSR/router研究の結論は変更しない。P1 fullのV111比は+0.375、A0 fixed-routeは+0.3125で83.33%を残したが、router固有差は+0.0625、1 block・1 source・1 ancestryだけ。P1/A0/A1/A2はraw Safety 32/32 failure、W→L 2で、transitive provenance/licenseも未確認である。今回PSR repair、route/blob/tree/threshold/action列の移植は行っていない。

Top public replayは30 target seats、22W/0D/8L、mean margin +3,459.5、P10 -2,906というE1観測を維持した。field/continuationは多様で、単一routeではない。Tomatoは22/30で初回中央値320.5とcapacity gap後であり、敗戦側の平均保有が勝利側より多く、SpaTaroはTomato/Gooseなしで6/6だった。旧V7 crop controller、bounded Carrot、Tomato diversificationもnegative evidenceである。

過去land/livestock研究とも整合する。単独`BUY_LAND`、V109 broad fallback、即時/Town sale、retain Cow、managed/unmanaged Sheep、managed Gooseを再実装しなかった。今回得たCOW資金拘束は算術上の診断であり、「COWを削れば強くなる」というpaired結論ではない。

## 候補・独立source・seed・deployment

C1は作成していない。従ってcandidate contract/integrity、import/reset/isolation、A/A、smoke、旧spent paired、bootstrap/reweighting、Safety差、L→W/W→Lはnot applicableである。raw Safety 0やW→L 0をcandidate実績として主張しない。

既存independent gold poolとopponent candidate directoryは結果前にhash監査したが、C1不成立のため新baseline gameもsource selectionも0。第3 independent ancestryを確認したとは扱わない。Development `10091521–10091536`は0使用、promotion/Fresh/旧Developmentも0使用で封印を維持した。

active remote submission 56089444はlocal V109/V110/V111/V113と99.53%近いがexact episode一致0で、27差分は同じmarket multisetの順序差だった。取得archive hashでidentityを確定できていないため、remote package identityは `UNVERIFIED` のままである。

Tomato案は実行していない。今回のprimary gapより時期が遅く、Top内勝敗との単純対応もなく、既存crop diversificationがnegativeだからである。Tomato/Carrot/livestock/terminal saleへ横滑りしなかった。

numeric agentは作成していない。labelは付与なし。production Champion V111を維持する。Kaggle提出、kernel push、submission slot変更は全て0である。

## 再現とartifact

再現command:

```powershell
.\.venv\Scripts\python.exe scripts\research_20260916_v111_midgame_capacity.py analyze
```

同じmanifest input hashを確認した場合だけ再実行する。新gameやresume JSONLは存在しない。主要artifactは `experiments/research_20260916_v111_midgame_capacity/` の `midgame_cashflow_ledger.json`、`land_relative_activation_timeline.json`、`current_top_capacity_comparison.json`、`shadow_capital_counterfactual.json`、`opportunity_cost_by_spend_family.json`、`capacity_mediator_timeline.json`、`mechanism_ranking.json`、`mechanism_attribution.json`、`final_decision.json` である。

検証では新規Pythonの`py_compile`とruffが合格し、既存evaluation/continuation関連testは22/22合格した。evaluation core自体は変更していない。JSON load、artifact hash、終了時processはfinal verificationで別途machine-readableに保存する。
