# Router mechanism research report — 2026-09-15

## 最終判断

`REJECT_NO_UPLIFT`。ここでいうupliftは、V111へ合法かつ完全に移せる一般化機構のupliftである。P1由来ablation自体の勝率が高いことを否定する判断ではない。production ChampionはV111のまま維持し、numeric agent、C1/C2、Development確認は作成・実行しなかった。

## 実行範囲と保全

開始時HEADは`851e970d81db084a712097928a71feb9c0e2b09a`、branchは`main`。開始時dirty worktreeとユーザー作成fileをmanifestへ記録して保全した。旧P1/D1/R0の32 pairはhash検証後に再利用し、新規gameはA0/A1/A2だけをA/A 6、smoke 12、旧spent 96 contexts実行した。全ablationは独立load A/A、両seat smoke、720 states/719 decisions、schema、runtime/isolationを通過した。

Kaggle提出、kernel push、submission slot変更は0。promotion `10091101–10091112`、Fresh `10091901–10091912`、旧Development `10091421–10091436`、今回条件付きDevelopment `10091521–10091536`はいずれも未使用である。

## Router固有価値と固定route

| policy | W/D/L | V111比win-score差 | P1 fullとの差 | raw Safety | W→L |
|---|---:|---:|---:|---:|---:|
| P1 full（既存） | 24/0/8 | +0.3750 | — | 32/32 | 2 |
| A0 route0固定 | 22/0/10 | +0.3125 | +0.0625 | 32/32 | 2 |
| A1 day6 switch無効 | 22/0/10 | +0.3125 | +0.0625 | 32/32 | 2 |
| A2 day24 switch無効 | 24/0/8 | +0.3750 | 0.0000 | 32/32 | 2 |

robustnessは、A0/A1のwhole source+seed block bootstrap 95%下限が0.0000、A2が0.0625だった。equal-source差は順に+0.3125/+0.3125/+0.3750、equal-ancestry差は+0.2917/+0.2917/+0.4167、9 reweighting worst差は+0.2763/+0.2763/+0.3421。exclude-self、exclude-tape2-source、exclude-near-lineage差はいずれも負ではない。ただしこれはtrained old-spent panel内の感度で、router固有差の2-source gateや一般化証拠を置き換えない。candidate margin P10はA0/A1が-13,194.6、A2が-5,063.5だった。

P1 full−A0は+0.0625で、qeinstein seed 10091013の1 source-seed block（両seatを1 case）のみだった。2 sources以上という事前gateを満たさない。A1がA0と同じ、A2がP1 fullと同じなので、観測された追加分はday 6 Town分岐に局在し、day 24 CARROT price分岐の勝敗寄与は0だった。

A0はV111比+0.3125で、P1 total-policy uplift +0.375の5/6（83.33%）を、step 0で選ばれたroute0を固定したまま再現した。したがって、旧改善の大半はrouter変更ではなく、route選択前から共通する固定route0とstep 0 market/portfolio footprintを含むtotal policyで説明可能である。A0は固定route全体を残すablationなので、step 0 WHEAT購入単独とその後のportfolioを分離しておらず、初期footprint単独の因果量はUnknownである。

## Identity proxy監査

実traverse featureはTown（YARN_STORE構成、MILK需要）と現在CARROT価格だけで、rival public farm featureは0、明示identity/seed/private/future/tape照合も0だった。route sequenceからsourceを多数決予測するaccuracyは0.375。ggmljsだけに現れた局所sequenceはあるが、唯一のrouter勝敗差は複数sourceで共有されるqeinsteinのsequence上にある。従って既知source identity proxyだったという証拠は成立しない。ただし閾値距離0のday 6 decisionが多く近傍安定性が弱く、route expressionのprovenanceも未確認なので、exact selectorのdeploy転記は不可である。

## Evidence / Inference / Unknown

Evidence: P1/A0/A1/A2はいずれもstep 1に最初のpublic market divergenceを生じる。P1のopponent responseはその後0–624 steps、中央値70.5。A0の平均V111差はself coin -5605.2500、opponent coin -19273.4062、margin +13668.1562。固定route0だけでsouvik +1.0、qeinstein +0.25、mooman/ggmljs 0のsource別win-score差が得られた。daily coin、portfolio、market/Town、opponent actionの順序は`mediator_timeline.json`に保存した。

Inference: marginの一部はpublic market/price/Townを介した相手のclosed-loop応答と整合する。自己生産・回収と相手行動の双方がtotal policy差の後に変わっている。

Unknown: self生産寄与とopponent mediation寄与の識別、step 0 WHEAT購入単独効果、Town/priceを固定したcounterfactual、未使用seed・第3 ancestryへの一般化。相手coin低下を単一market actionの因果効果とは呼ばない。

## Safety・実行contract

A0/A1/A2はいずれもraw Safety 32/32、W→L 2。全contextのcrop-to-weedはstep 479のblock3 route0、animal lossはstep 695にroute0とroute3の双方で発生した。market no-op 8 contexts、partial commit 8、silent field no-op 7も維持された。時刻とactive routeの一致は因果ではない。order/step明細、successful harvest units、water/lifespan loss、t672/t719 shed/carry/unharvested proxyは各candidateの`summary/*_diagnostics.json`と`complete.json`に保存した。step 719在庫は残りdecision 0のproxyであり実現収入ではない。

## Transfer gateと一般化

router固有差は1/16 source-seed blocks、1/4 sources、1 ancestryだけで、2-source条件を満たさない。さらに固定route0の具体表現はP1のresearch-only tape/routeと未確認transitive provenanceに依存し、V111-ownedの調達から販売・rejoinまで完結するsuffix/contractは確立できなかった。よってC1/C2を作らず、raw Safety 0やW→L 0を主張するdeploy候補は存在しない。

診断panelは16 source-seed blocks、4 sources、検証済み2 ancestries。Deepesh/Lonespearは前回と同一hashのため再走せず、robriculture新HEAD `2077b0…`はCC-BY-4.0とnative callableを静的確認したが、前段gate停止のためbaseline gameを開かず第3 ancestryに数えない。Developmentは0 blocks。numeric agent作成は0、labelは`REJECT_NO_UPLIFT`であり、V111は権利明確・既存production Championとして維持する。

## 再現とartifact

正確な実行・resume commandは`experiments/research_20260915_router_mechanism/reproduction_commands.json`、全artifact hashは`final_artifact_manifest.json`、再検証結果は`final_artifact_verification.json`を参照。P1 blob/tape/tree/route/action tableはproduction agentへ転記していない。
