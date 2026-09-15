# Kaggriculture 現状診断と次の改善戦略（2026-09-16 JST）

## 結論

次に行うべき研究は、PSR routerの修理でも、上位replayの固定route模倣でもない。V111を親にした **公開Town需要に連動する中盤Tomato option** を、まずactionを変えないshadow feasibility auditとして定義し、完全な購入・植付・日次給水・収穫・運搬・販売・rejoin契約を証明できた場合だけ、一つのbounded interventionとしてpaired評価するのが最も合理的である。

理由は四つある。

1. 完了したPSR ablationでは、P1のV111比 +0.375 のうち +0.3125、すなわち **83.33%** がrouteをstep 0で固定したA0でも残った。router固有値は +0.0625、1 source-seed block、1 source/ancestryだけで、移植gateを通っていない。PSRの具体routeはさらにlicense/provenanceとSafetyの両面でproductionへ移せない。
2. 2026-09-16 00:33 JST時点のLeaderboard Top 5の直近公開ログでは、30 target seats中22がTomato seedを購入し、初回購入step中央値は320.5だった。現在Top 5は歴史的V111より平均Tomato +3.317、Carrot +1.959、Wheat +3.596、Strawberry -3.612である。一方V111のcrop portfolioは実質固定routeのままで、V111のpublic-state modelが予測するcrop goalにはactionへの因果経路がない。
3. ただしTomatoは万能解ではない。Top 5のうちSpaTaroの6観測はTomato 0、Goose 0で6勝だった。よって「上位がTomatoを使うからコピーする」のではなく、**需要があり、V111の既存Wheat taskを完全なscheduleごと安全に置換できる状態だけ**を検証する。
4. 終盤売却、Sheep、Gooseはすでにpaired評価で無効または悪化している。現在Top 5と歴史的V111のterminal stranded-price proxy差も約136 coinにすぎず、現行リモート提出の直近8観測の平均margin -12,418を説明できない。

現時点で新numeric agentを作る根拠はない。local production ChampionはV111のまま維持する。

## 1. 調査範囲と証拠の扱い

証拠を次の三段階に分けた。

- **E0（mechanics/code）**: official local engineとrepository sourceから直接確認できる処理。
- **E1（observational）**: 公開Leaderboard、公開replay、実際に観測されたaction/state/result。相手mixが選択された標本で、counterfactualではない。
- **E2（paired closed-loop）**: 同一opponent・seed・seatでcontrol/treatmentを完走させた比較。

Top submissionの公開replayは行動と公開状態を示すが、実行source、ancestry、licenseを示さない。今回の上位ログはaggregate diagnosticにだけ使い、action列・trajectory fingerprint・相手名をruntime selectorへ入れてはならない。Kaggleの公式Leaderboardページは順位確認の入口であり、正確な時点値は保存済みAPI responseを基準にした。[^1]

## 2. 現在のLeaderboardと取得ログ

保存済みsnapshotはUTC `2026-09-15T15:33:56.343605+00:00`、JST `2026-09-16 00:33:56`である。

| Rank | Team | Active submission | Rating |
|---:|---|---:|---:|
| 1 | Majkel1337 | 56216119 | 3150.8 |
| 2 | Artem The Farmer 🍅 | 56232364 | 3149.2 |
| 3 | SpaTaro | 56233892 | 3058.4 |
| 4 | Sida Zuo | 56251379 | 3048.7 |
| 5 | DSM | 56244297 | 3040.6 |
| 6 | Orbital Terraformer | 56212726 | 3020.7 |
| 7 | ymg_aq | 56246419 | 3009.9 |
| 8 | THIRD FARM CLUB | 56240472 | 3008.3 |
| 9 | leave you | 56231920 | 2991.6 |
| 10 | Mengfei Li | 56173067 | 2989.3 |

自チーム`rsraki`は同snapshotでrank 3038、rating 1244.9、active submission 56089444だった。Leaderboardは短期間でactive submissionと順位が大きく変わっているため、rating単独をteacher qualityやpolicy因果の指標に使わない。最終評価はKaggle staffの説明どおりactive agent間のBradley–Terry tournamentで行われ、team scoreは二つのactive submissionの良い方、tieは各0.5として扱われる。[^2][^3]

Top 5それぞれについてEpisodeServiceの最新6行をread-only取得した。重複対戦を含むため、30 target-seat observations、26 unique replaysである。

| Rank | 直近6観測 W/D/L | 平均margin | Tomato平均 | Carrot平均 | h48 field variants |
|---:|---:|---:|---:|---:|---:|
| 1 | 5/0/1 | +5,738.7 | 2.45 | 4.75 | 6 |
| 2 | 3/0/3 | -141.5 | 5.12 | 2.23 | 1 |
| 3 | 6/0/0 | +3,737.5 | 0.00 | 1.60 | 6 |
| 4 | 5/0/1 | +6,922.3 | 5.49 | 1.58 | 3 |
| 5 | 3/0/3 | +1,040.7 | 3.52 | 4.27 | 6 |

集計全体は22/0/8、観測win-score 0.733、平均margin +3,459.5、median +3,151.5、P10 -2,906だった。これはrating estimateではなく、最新行という選択を受けたE1標本である。

## 3. 上位ログから分かること

### 3.1 現在の上位は一つの固定opening familyではない

30 target seatsのfield-state hashはstep 24で15種類、step 48で22種類、step 100で23種類、step 200で28種類、step 300以降は30/30種類だった。全30件でday 6–25 portfolio continuationも異なる。Rank 2だけは6件すべて同一h48 openingだが、その後は6 continuationへ分岐した。

2026-09-10 corpusでは巨大な共通h48 opening clusterが見えていたが、現在のTop 5はより早く多様化している。これは「上位routeを一つ復元する」方向より、V111の安定したopeningを残し、公開状態に応じて中盤の少数optionだけを選ぶ方向を支持する。ただしhashの違いはsource ancestryの証明ではない。

### 3.2 crop mixはV111より分散しているが、単一の必勝portfolioはない

現在Top 5のday 6–25平均portfolioは次のとおりだった。

| Asset | Current Top 5 mean | Current Top 5 − historical V111 |
|---|---:|---:|
| Wheat | 18.398 | +3.596 |
| Carrot | 2.885 | +1.959 |
| Tomato | 3.317 | +3.317 |
| Strawberry | 24.937 | -3.612 |
| Melon | 3.417 | -0.014 |
| Cow | 7.955 | -0.267 |
| Sheep | 3.937 | -1.418 |
| Goose | 1.782 | +1.782 |

Top 5の初回market order中央値はTomato seed step 320.5（22/30）、Carrot seed step 491（25/30）、Goose step 152（21/30）。third land unlockは中央値step 209だった。

ここから確認できるのは、V111の「Strawberry + Cow/Sheepに厚く、Tomato/Gooseを持たない」portfolioが現在上位の中心から外れていることまでである。TomatoやGooseの採用が勝因だとは言えない。実際、Top 5の8敗側は勝ち側より平均Tomatoが多く、SpaTaroはTomato/Gooseなしで6/6だった。

### 3.3 Tomatoは「一般採用」ではなく「公開需要option」として試す価値がある

official engineではTomato seedは50、初回yieldは植付から8日後、以後毎日最大4回yieldを増やすongoing cropで、連続2日水切れでweedになる。Pizza ShopとFarmers MarketだけがTomatoを定期消費する。したがってTomato追加はseed購入だけでは成立せず、少なくとも8–11日の給水、収穫、物流、販売と、既存routeへのstate-based rejoinを含む。

2026-09-10の別Top corpusでは、新しいshopがTomatoを需要するevent後72 stepsのTop側Tomato増加が平均+0.457、非需要eventで+0.116だった。一方V111はどちらも0だった。この差は因果効果ではないが、単なる時刻固定より「新たに観測されたTown需要」をtriggerにする根拠になる。

### 3.4 敗戦は中盤以降のrelative economyで決まっている

現在Top 5でもday 18時点のleadから6/30が最終敗戦へ反転し、8敗中7件は5,000 coin未満の僅差だった。8敗すべてでpremium congestionが観測され、7件で相手がTomato 3以上またはCarrot 10以上のunusual-crop条件を満たした。ただし同じ敗戦の7件はMilk-heavy、8件はStrawberry-heavyでもあり、どれか一つを原因とすることはできない。

相手coin、price、Town、market inventoryはclosed-loop mediatorである。自分のportfolioを変えれば相手actionと将来Town RNG経路も変わり得るため、相手coin低下を「market attackの効果」と解釈してはいけない。

### 3.5 absolute no-opは上位policyの欠陥指標として使えない

30件すべてが720 statesを完走し、runtime error、negative cash、missing hand、malformed actionは0だった。一方、absolute auditでは全30件にterminal animal lossとplant-to-weedがあり、oversized SELLやsilent no-opも多数あった。これは固定routeが存在し得ること、終端で意図的にmaintenanceを切ること、過大SELLをengineにcapさせる実装があることを示す。

従って上位のabsolute eventをそのままproduction品質基準にしてはいけない。candidate SafetyはV111比で新しく発生したfirst-event class、runtime/delivery、complete lifecycleをpairedに評価する。

## 4. 自エージェントV111の明確な弱点

### 4.1 crop strategic outputがactionへ接続されていない

V111はpublic stateから7-component farm changeを予測するが、実際にそのgoalを消費できるのはthird-shop YARN時のlate Cow→Sheep conversionだけである。Tomato、Carrot、Wheat、Strawberry、Melonの予測はfield actionを変えない。V110の追加適応もnear-clone時に既存premium saleを最大4 steps前倒しするだけで、phase予測介入は無効化されている。

つまりV111は情報を見ているが、現在metaで重要に見えるcrop trade-offを動かす安全なactuatorを持たない。最優先の修正点はmodelを大きくすることではなく、**一つのcrop decisionを完全な実行optionとしてactionへ接続すること**である。

### 4.2 固定routeとadaptive overlayの責任境界が狭すぎる

V111の安定性はV109/public-v43のcoherent 719-step routeに依存する。これは強みだが、crop構成変更にはstate compatibility問題がある。購入だけ置換すると、植えるtile、毎日の水、収穫時刻、worker位置、carry capacity、販売slotが全てずれる。

P1はこの問題を実証した。強いtotal-policy resultがあっても、animal loss、crop-to-weed、field/market no-op、partial commitが同時に発生した。従って次candidateはaction patchではなくpersistent option contractでなければならない。

### 4.3 current remote submissionとlocal Championのidentity管理が不十分

active submission 56089444の直近8 replayを、local V109/V110/V111/V113へfactual observation playbackした。全versionで5,725/5,752 actions（99.5306%）が一致したが、8/8 episodeで完全一致しなかった。27 mismatchはすべてfarmer/handsとmarket-order multisetが同じで、SELL列の順序だけが異なった。

official engineはmarket listをslot順に処理する。27 turnを一手だけ再計算するとlocal V111順序はremote順序に対し、自分cash +12合計、相手cash -29合計、非zero self effect 6 turnsだった。効果は小さく、直近8観測のremote平均margin -12,418を直接説明できないが、market inventoryが常に同一にはならず、closed-loop影響は未確認である。

これは戦略改善より先に、package source/hash、archive manifest、Python/runtime、market list順序を再現可能にする必要があることを示す。ただし今回の結果だけでactive archiveをV111と認証してはならない。

### 4.4 historical weaknessはterminalだけではない

歴史的V111 public corpusでは147 seat observations中、day 18 lead→lossが17件、day 24 lead→lossが4件だった。terminal stranded-price proxyは平均264.7 coinで、現在Top 5は128.8 coinだった。差は改善可能だが、数千から数万coinの敗戦を説明する規模ではない。

さらに旧paired panelで即時売却とTown同期売却はいずれもL→W 0、margin悪化だった。terminal liquidationを次の主仮説に戻す理由はない。

## 5. 完了済み研究から除外すべき方向

| 方向 | 既存結果 | 判断 |
|---|---|---|
| PSR router/tree/route移植 | router固有 +0.0625、1 block/1 source。Safety 32/32 failure、provenance不十分 | 終了。research-only |
| PSR固定route移植 | P1 upliftの83.33%を説明するが、具体routeはunsafeかつlicense境界不明 | コピー禁止 |
| terminal即時/Town売却 | 32/32安全、L→W 0、平均margin悪化 | 主仮説から除外 |
| unmanaged Sheep | W→L 2、22/22発火で新silent no-op | Safety reject |
| managed Sheep | W→L 2、平均margin -2,057.8 | reject |
| managed Goose | W→L 2、self coin +128.2だがopponent +1,220.6、margin -1,092.4 | reject |
| late Carrot router | P1−A2 = 0 | late固定switchは除外 |
| opponent future-supply予測 | V110 phase interventionは正のsupportを示さずdisabled | 新予測modelを増やさない |
| primitive-action RL/BC | 長期task、rare event、free-running driftを同時に解く必要 | 今すぐの主路線にしない |

Kaggle communityでも、高水準optionをmodel/ruleが選びdeterministic executorが合法性・routing・deadlineを担当する分離が議論されているが、これは他参加者の経験談であり性能証拠ではない。[^4] 本repositoryではP1失敗と既存continuation実験が同じ設計要件を独立に支持している。

## 6. 次の改善候補ランキング

### 1位: `demand_backed_tomato_option`

変更familyは一つだけとする。新たに確認したPizza ShopまたはFarmers MarketのTomato需要があり、現在price/inventoryがengine-derived break-evenを満たし、自分のcash・seed・tile・worker・position・remaining daysで完全scheduleが成立するときだけ、V111の予定済みWheat plantingを少量Tomatoへ置換する。

これはまだ有望仮説であって、勝率改善の結論ではない。parameterはold-pairの勝敗最適化で選ばず、engine cost、yield horizon、Town consumption、shed/worker capacityから一意に凍結する。最初はactionを変えないshadow loggerでeligible stateとschedule completionを検証する。

### 2位: `persistent_option_executor`（必要基盤、単独昇格候補ではない）

Option開始後に`buy seed → pickup → plant → water daily → harvest → carry/drop → sell → rejoin`を状態で追跡する。毎step legality、cash、inventory、tile、worker位置、deadlineを再確認し、失敗時は時刻ではなく明示的rejoin stateへ戻る。

executorだけでwin upliftを主張しない。Tomato optionを安全に試すためのcontractであり、戦略と同時に複数仮説を混ぜない。

### 3位: `demand_backed_carrot_option`（Tomatoが機構として不成立の場合だけ）

Carrotは短cycleでTomatoよりstate compatibilityを作りやすく、現在Top 5で25/30に購入がある。ただしV111は既に少量保有し、P1 late-Carrot switchはincremental value 0だった。Tomatoの結果を見て同じseedで横滑りしてはならず、別のpreregistrationと新しいdata splitが必要である。

### 4位: `exact_package_and_market_order_parity`

これは性能仮説ではなくdeployment hygieneである。source hash、archive hash、dependency、runtime、ordered market listを固定し、local A/Aとfresh-process parityを通す。+12 coinの一手auditをcandidate upliftとして数えない。

## 7. 推奨する段階的実行

### Phase 0: 保全と役割固定

- V111をproduction Championのまま固定する。
- current Top replayとLeaderboardはDiscoveryとしてhash固定する。
- active remote 56089444を`V111 exact`と呼ばず、`close behavioral relative; archive identity UNVERIFIED`とする。
- promotion `10091101–10091112`、Fresh `10091901–10091912`、旧Development `10091421–10091436`を開かない。

### Phase 1: zero-action-change shadow feasibility

- V111の旧spent 32 contextsを再利用し、新規gameを始める前にTomato需要eventとV111予定Wheat plantを列挙する。
- 各eventでcash、seed、empty/replaceable tile、worker positions、water visits、harvest/carry/sell deadline、market slotsを計算する。
- 実在stateで2 sources以上にeligible eventがなく、またはcomplete scheduleを一意に作れなければ実装せず`PROMISING_UNPROVEN`で止める。

### Phase 2: 一つのC1だけ実装

- 親はV111とrepository-owned codeだけ。
- Top replay action、PSR route/blob/tree/threshold、opponent identity/seed/future stateを使わない。
- 発火しないcontextではV111とaction/stateを完全一致させる。
- trigger、max tiles、break-even、plant deadline、rejoin stateは勝敗を見る前に固定する。

### Phase 3: execution gate

- import/reset/isolation、same-process連続episode、fresh-process、両seat。
- V111 A/A、C1 A/A。
- 発火/非発火を両seatでsmokeし720 states、719 decisionsを確認。
- runtime/timeout/incomplete/negative cash/delivery failure 0。
- V111比の新animal loss、crop-to-weed、水切れ、未回収Tomato、silent no-op、partial commit、oversized extra SELLを0。

### Phase 4: 旧spent compatibility

- 4 sources × 4 spent seeds × 両seatの32 contextsでpaired closed-loop評価。
- これは発見・一般化証拠ではなくtrained-panel compatibilityと明記する。
- 必須gateはdelta > 0、safe L→Wが2 source-seed blocks以上かつ2 sources以上、W→L=0、W→D=0、全source非悪化、raw Safety 0。
- failureならthreshold・tile数・発火条件を結果に合わせて修理せず終了する。

### Phase 5: 条件付きDevelopment

- Phase 4を全て通った場合だけ、repository全体で未使用確認後に`10091521–10091536`の16 blocksを一括登録する。
- 旧4 sourcesと、candidate結果を見る前に固定した合法・native実行可能な独立sourceで全件を走らせる。
- promotion/Freshは封印したままにし、new Development完了前にnumeric agentを作らない。

## 8. 現時点の判断

- PSR router研究: `REJECT_NO_UPLIFT`（deploy-transfer gate不成立）。
- current-meta Tomato機構: `PROMISING_UNPROVEN`。
- V111由来新candidate: 未作成。
- raw Safety 0 / W→L 0: candidate未作成のため未評価。
- numeric agent: 未作成。
- production Champion: V111維持。
- Kaggle submission、kernel push、submission slot変更: 実施していない。

## Sources

[^1]: Kaggle, [Kaggriculture Leaderboard](https://www.kaggle.com/competitions/kaggriculture/leaderboard). Exact local snapshot: [`leaderboard.json`](../experiments/research_20260914_lowcash/remote/20260915_153354/leaderboard.json).
[^2]: María Cruz (Kaggle Staff), [Comment on the final evaluation for this competition](https://www.kaggle.com/competitions/kaggriculture/discussion/731587).
[^3]: Addison Howard (Kaggle Staff comment), [Final Bradley-Terry scoring: three clarifications](https://www.kaggle.com/competitions/kaggriculture/discussion/739410).
[^4]: Zhenyu Zhang, [If I’m Going to Write Rules Anyway, Why Train a Model?](https://www.kaggle.com/competitions/kaggriculture/discussion/738079). Community experience only, not evidence for V111.

Local evidence:

- [`strategy_evidence.json`](../data/analysis/research_20260916_next_strategy/strategy_evidence.json)
- [`current_top_execution_audit.json`](../data/analysis/research_20260916_next_strategy/current_top_execution_audit.json)
- [`current_submission_fidelity.json`](../data/analysis/research_20260916_next_strategy/current_submission_fidelity.json)
- [`remote_market_order_audit.json`](../data/analysis/research_20260916_next_strategy/remote_market_order_audit.json)
- [`research_20260915_router_mechanism_report.md`](research_20260915_router_mechanism_report.md)
- [`research_20260912_continuation_report.md`](research_20260912_continuation_report.md)
- [`current_meta_analysis_20260910.md`](current_meta_analysis_20260910.md)
- [`champion_weakness_map_20260910.md`](champion_weakness_map_20260910.md)
