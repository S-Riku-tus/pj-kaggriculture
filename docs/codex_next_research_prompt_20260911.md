# 次回Codexへ入力するプロンプト

以下を、`C:\Users\shiba\Kaggle\pj-kaggriculture`を開いたCodexへ入力してください。本文は次回の実行指示です。

---

あなたはKaggricultureでLeaderboard #1と最終評価上位を目指すPrincipal Research Engineerです。最大5時間程度、repository、Kaggle、engine、既存データを調査し、仮説選定、実装、paired evaluation、最終判断まで自律的に進めてください。

今回の目的は、前回のV114を閾値調整で復活させることではありません。

**「現在の途中状態から、正しく実行でき、Championの敗戦を勝ちに変える代替行動があるか」を確かめ、その証拠が得られた場合だけ最小のstate-dependent policyを作ること**を主目的とします。

最適化対象は最終coinの大小による勝率です。平均self coin、margin、模倣精度、予測MAE、routeの多様性だけでpromotionしないでください。L→WとW→Lを必ず数えてください。3000という数字も固定された首位目標ではないので、現在のLeaderboardを再取得してください。

作業を実行する依頼です。計画だけで終了しないでください。簡単な確認で停止せず、資料から合理的に判断してください。重要な不確実性はEvidence / Assumption / Inferenceとして区別してください。Kaggleへの提出は今回の範囲に含めず、提出可能なartifactと提出判断まで作成してください。

## 1. 最初に読む資料と、既知の結果

まず次を読み、重要な数値は元JSONやsourceで確認してください。

- `docs/next_research_strategy_20260911.md`
- `docs/v114_research_and_evaluation_report.md`
- `docs/current_state_20260910.md`、`docs/current_state_20260911.md`
- `docs/current_meta_analysis_20260910.md`
- `docs/champion_weakness_map_20260910.md`
- `docs/opponent_supply_estimation_20260910.md`
- `data/analysis/next_research_20260911/postmortem_recheck.json`
- `experiments/research_20260910/`のsource registry、preregistration、holdout audit、decision記録
- `scripts/evaluation/`、`scripts/research_20260910.py`

以下は前回までの結果であり、現在も正しいか確認してください。

1. production ChampionはV111。source SHA256は `699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660`、archive SHA256は `85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e`。
2. 2026-09-11 12:33 JSTの首位はSpaTaro、3137.6、submission56114097。
3. V114 originalはcheckpointのconfig引数不整合で不適格。
4. V114r1は32pairsで発火0、V111と12W/20Lで完全一致。適応戦略の有効性は未検証。
5. 強制切替V114probeは24/32pairsで発火し、0W/32L。L→W=0、W→L=12。REJECTを維持する。
6. ただし失敗原因を一括して「維持作業崩壊」と呼ばない。発火24pairsのt153以降では、水切れ死120→75、寿命終了360→473。寿命終了時に残存yieldがゼロのものは288→425。自然寿命終了件数と、実際の収穫損失は別。
7. 強制切替には初期の種不足PLANTとSheep購入不成立がある。mooman/10091012/seat0ではt186にcash759、Strawberry seeds0でPLANT不成立。t192は先行注文後にSheep購入不成立。調達不整合と資金不足を分ける。
8. V114r1のQはraw SELL予定量を在庫検証なしで収益計上し、BUY_PRODUCTのWheatを25で計算する。engineの購入価格は動的。README/AGENTSのmechanics説明と矛盾した場合は、凍結engineの実装を検証根拠にする。
9. 強制切替でself coinが増えた9pairsのうち5pairsは相手がさらに増益し、すべてW→L。self coin改善を成功扱いしない。
10. 相手供給ridgeはstrict episode/lineage splitでE2の改善を示したが、売却phaseや勝率の追加価値は未証明。
11. 新たな4実行policyはGoldとして動くが、PSR/Kaito ancestryが重複し、保守的には2祖先群。4独立familyと数えない。source registryのvalidation状況に古い記述があれば、検証証拠を追記する。
12. 最新の自分のKaggle submissionと凍結V111のartifact identityは未確定。remote ratingをV111へ帰属させない。

## 2. 差分監査と実験の保全

最初にgit status、branch、log、dirty/untracked、現在のChampion/Challenger registry、engine version/hash、artifact/source対応、前回以降の変更を確認してください。既存の大規模監査を丸ごとやり直さず、差分を優先します。

既存の研究、失敗candidate、raw evaluation、未commit変更を上書きしないでください。今回固有のexperiment IDを使い、変更前のhashとmanifestを保存してください。必要なら隔離された作業場所を作ってください。

最新Leaderboard、取得可能な自分のsubmission情報、上位の新しいsource/lineageを調べてください。情報取得は既存scriptとcacheを再利用し、現在性が必要な取得ではtimestampを持つ新しい保存先を使ってください。取得できない情報はunknownとし、local研究を止める理由にしないでください。

Championとlatest remote artifactの同一性が不明でも、localの凍結Championを明示して評価は進められます。コードを取得できない相手はBronze、validated surrogateはSilver、実行可能で検証済みsourceだけGoldです。

## 3. Agentより先に、評価の正しさを確認

`scripts/evaluation/schema.py`、`replay.py`、`runner.py`、`divergence.py`、`safety.py`、`lineage.py`、`statistics.py`、`registry.py`、`report.py`などを再利用してください。別の独自evaluatorを乱立させないでください。

以下を必要な範囲で修正・検証してください。

- A/Aで両seat、複数Town regime、通常engine configurationとstandalone実行を確認する。
- route介入t153と、V111が継承するCow→Sheep取引t248を別の監査対象にする。単一transaction_stepの使い回しによる誤検出を防ぐ。
- requested action、emitted action、engine commit、private資源、worker位置、field変化を結び付ける。
- oversized SELLのpartial commitと、成立が必須な購入・種調達・配置失敗を区別する。
- 雑草化は水切れ、寿命終了時の残存yield、空き地random発生に分類し、raw件数も保持する。前回Safety基準を事後的に緩めて失敗candidateを救済しない。
- branch以前のaction/state一致、runtime/module stateのreset、requested/resolved seed、engine/archive hashを確認する。

前回の元結果は変更せず、補正や新監査は別記録にします。旧`research_20260910.py`のDevelopment以外を拒否するgateを、旧candidateのために解除しないでください。必要なqualificationは新しいpreregistrationとして既存framework上に設けてください。

## 4. 最初の研究判断：どの失敗機構を扱うか

既に使用済みのDevelopment replaysを使い、次を区別してください。

- 種・feed・運搬・配置の不整合
- 注文順による資金枯渇、market slot制約、shed容量
- 未収穫yieldの実損失と、収穫済み作物の自然寿命終了
- 自分の取引が相手の売却収益を改善する価格効果
- 相手policyのpublic farmへの反応
- 畑変更を通じたTown/RNG分岐
- 将来経済modelの誤差と、そもそもrouteが有効でないケース

単一のfirst divergenceを最終敗因と断定しないでください。t153でWool売却を1turn遅らせたこと、t186の種不足、t192の購入失敗、後続Town変化は別々の因果経路です。

engineは空き地weed抽選後にTown shopを引くため、同じseedでも行動変更後のTownは変わり得ます。主評価は元engineでの総policy効果です。Townが変わったpairsを除外しないでください。Town/RNGを固定した補助解析は、改変engineのdiagnosticとして分離し、promotion根拠にしないでください。

## 5. 仮説を順位付けしてから実装

5〜10仮説を、mechanism、supporting evidence、Evidence Level、upside、failure mode、complexity、Safety risk、evaluation feasibility、test timeで比較してください。

当初の優先順は次です。ただしデータで変更して構いません。

1. 実行contractを持つ小さなcontinuation。
2. 現在の強い公開complete policyとの比較による、研究baseの限界確認。
3. 限定したmarket sell phase・相対価格効果の制御。
4. 実行可能な少数routeに対するstate-dependent selector。
5. public opponent supply forecastの意思決定への追加。
6. 条件付きscarcity crop、delayed commitment、収穫・寿命管理。
7. 終盤数日のexact-horizon再投資・換金。
8. payoff cycleが確認された場合だけMixed opening/PSRO。

新versionを作る前にPrimary hypothesisと比較対象を記録してください。V114r1の閾値を下げること、Cow数やCarrot比率をTopからコピーすることをPrimaryにしないでください。

V111はproductionとして保全します。ただし強い公開complete policyを無改変の比較基準として走らせることは可能です。公開sourceの全体比較と、一部ロジックを取り込む介入は別実験にします。全体差の結果から特定componentの優位性を主張しないでください。source利用条件とprovenanceも確認してください。

## 6. 実行可能な代替行動を先に作る

最初はbaselineを含め2〜3選択肢で十分です。巨大plannerや多数routeを一度に作らないでください。

各route/optionについて、次を定義します。

- 開始条件：day/hour、cash、seeds、shed、carried inventory、位置、土地、作物・動物状態、public market/Town/opponent。
- 実行中policy：調達、移動、植付け、給餌、収穫、運搬、売却。
- 必要資金と作業手数：動的BUY_PRODUCT価格、注文順、field action先行、atomic PLANT、market slot、日次resetを含む。
- 終了・中断条件と、変更後に継続して必要になる管理。
- baselineへ戻れる状態条件。不可逆変更後に元scheduleへ戻すだけのfallbackを使わない。

近い24〜72turnの資源・約定をまずengine通りに検証し、その介入の最終効果は必ず720-state/full-horizonで測定してください。live policyに相手private state、未来shop、seedから復元した未来情報を使わないでください。offline ground truthの利用とは区別します。

checkpointから再開する高速化を使う場合は、両者のprivate state、history、module globals、RNG、configurationを含む状態複製が、最初からの実行と一致することを先に検証してください。一致を証明できなければfull rerunを使ってください。

## 7. selector開発に進む条件

使用済みDiscovery/Developmentで、同一相手・seed・seatに対しbaselineと各実行可能routeを最後まで走らせてください。

win=1、draw=.5、loss=0として、各組で安全な最良routeを結果を見て選んだ場合の改善を計算してください。これは当該標本のoffline oracle診断であり、deploy可能な勝率ではありません。

この楽観的診断にもL→Wがない場合は、そのlibraryのselectorやforecastを高度化せず、別のroute、別のdecision point、別のcomplete policy比較へ進んでください。少数例から一般的な不可能性を断定しないでください。

複数の状態・相手で安全な勝敗反転が見つかった場合だけ、live観測でそれを識別する小さなgateを作ります。新shop、scarcity、opponent portfolio、horizonなど、限定したeventで判断し、毎turn切り替えないでください。

相手供給予測を使う場合は、同じroute libraryで、予測なし／public calendar baseline／追加modelを段階的に比較します。予測MAEだけで入れないでください。same-episodeの両seat、同一submissionやopening family、seedの漏洩を防いでください。

## 8. 相手poolとpaired evaluation

既存4公開policyを、強いanchor・敏感なmatchup・regression用として使い分けてください。強さを比較するには30〜70%付近のmatchupが望ましいですが、0%/100%の相手を捨てる必要はありません。

source ancestryとaction/response familyを二軸で保存してください。共通祖先のある4実行ファイルを4独立familyと呼ばず、共通祖先だけで全て同一policyと決め付けないでください。追加の未取得・実行可能な強い系統を優先して探してください。

Control/Treatmentは必ずsame opponent、same requested/resolved seed、same seat、both seats、same engine、exact frozen archives、full720状態で実施します。介入前に意図しないdivergenceがあればinvalidです。

小さなpilotはruntime/deliveryの棄却専用です。4〜8ゲームの勝率からpromotionしないでください。throughputを実測し、独立seed数、lineage数、発火数、不確実性に見合う評価数をpreregisterしてください。

両seatをseed blockとして扱います。複数familyに同じseedを使う場合のfamily横断の依存も考慮してください。真のmeta頻度が不明ならequal weightやstress weightと明記し、実測頻度と呼ばないでください。

## 9. Dashboardとpromotion

gateの順序を、実行妥当性 → treatment delivery → Safety → 対戦改善 → 多様性・頑健性 → Fresh Holdout、としてください。Safety failureをcoinやwin rateで救済しないでください。

必須出力：

- runtime、incomplete、invalid/new no-op、failed transaction、animal loss、weed分類、negative cash、unexpected divergence。
- eligible件数、actual activation件数、実約定を伴ったtreatment件数。0発火は改善ではない。
- Baseline/Candidate W/D/L、L→W、W→L、D→W、W→D。
- source/lineage別payoff、weighted Δwin score、worst major lineage、robust reweighting、不確実性、Bradley–Terry diagnostic。
- Δself coin、Δopponent coin、Δmargin、P10、lead→loss、terminal stranded inventory。
- first self action/money/portfolio/position、opponent responseとlag、opponent money、market、price、Town/RNG divergence。

E0 mechanics、E1 replay記述、E2 held-out prediction、E3 executable opponentへのpaired causal、E4 diverse tournament、E5 fresh holdout、E6 liveを区別します。PROMOTEには原則E4+E5が必要です。lineage不足や効果不確実ならPROMISING_UNPROVENとしてください。

## 10. Holdout保護

前回のpromotion seeds `10091101–10091112`、fresh seeds `10091901–10091912`は未使用として予約されています。今回の使用履歴を確認し、新しいmanifestで用途を明示してください。8個のreplay-body予約はmetadataにoutcomeがあるので、完全blindなholdoutとは呼ばないでください。

Candidateのsource・threshold・特徴・gateとpromotion条件をfreezeし、先行gateを満たした後だけFresh Holdoutを一度開きます。悪い結果を見て調整したら、そのdataはDevelopmentへ降格させ、Freshとして再利用しないでください。E4へ進めない候補のためにholdoutを消費しないでください。

## 11. 時間配分と中間判断

目安は、0〜25分：差分監査、25〜60分：失敗分類と評価整備、60〜150分：実行可能な代替行動とその対戦価値、150〜225分：最小gateとE3、225〜280分：資格がある場合のみE4/E5、280〜300分：artifactと最終報告です。

既に答えが出ている分析を延々繰り返さず、次の判断を変える証拠に時間を使ってください。Primaryがimplementation bug、delivery failure、mechanism disproved、Safety regression、no causal uplift、insufficient sensitivity/diversity、meta tradeoffのどれで失敗したかを分類し、必要なら第2候補へ進んでください。

Candidateを作ったことを成果にせず、無効な研究方向を正しく棄却することも成果として記録します。ただし、まだ検証可能な有望仮説があり予算が残るのに、報告書だけ作って早期終了しないでください。

## 12. 成果物と最終回答

今回固有の名前で、少なくとも以下を残してください。

- 差分audit、最新Leaderboard、Champion/source/engine identity。
- postmortemと仮説ranking、事前登録した評価・Safety・holdout条件。
- route開始条件・必要資源・完了条件、実約定trace。
- causal route-value tableとoffline oracle診断。
- 新candidateがある場合の`agents/<version>/`、source hash、再現可能なstandalone archive。
- `data/evaluation/<experiment_id>/`のpaired records、全divergence監査、Safety、payoff matrix、統計。
- 適切なtests、lint、両seatのstandalone/full-horizon検証結果。
- 日本語の最終研究報告と、次回再現に必要なcommand。

最終回答では、現在の首位Rating、真のChampion、何が分かったか、何を棄却したか、Primary選定理由、何を実装したか、W/D/LとL→W/W→L、lineage別結果、Safety、holdout、PROMOTE/REJECT/PROMISING_UNPROVEN、提出すべきか、推定実力の根拠、次の5時間の最優先課題を明記してください。

最終目的は、**安全に実行できる勝ち筋を作り、それを選ぶことで相手に勝ちやすくなったと示すこと**です。前回の文章や私の仮説に合わせるのではなく、現在のsource、engine、pairwise outcomeを根拠に判断してください。
