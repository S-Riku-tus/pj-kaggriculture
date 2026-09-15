# 次にCodexへ送る研究実行プロンプト

対象repository:

`C:\Users\shiba\Kaggle\pj-kaggriculture`

最大5時間程度で、計画だけで終えず、開始時保全、既存artifactのverification、zero-action-change shadow feasibility、条件付きのV111由来candidate実装、paired closed-loop評価、artifact検証、最終判断、日本語報告まで進めてください。Kaggleへの提出、kernel push、submission slot変更は行わないでください。公開Leaderboard・discussion・public replayのread-only取得は可能ですが、非公開sourceを推測・復元したり、取得不能なlicense/provenanceを推測で埋めたりしないでください。

今回の主目的は、V111の固定crop routeに欠けている一つの公開状態actuatorを検証することです。候補機構は、公開TownでTomato需要が実在し、現在のpublic marketと自分のprivate feasibilityから完全なmulti-day scheduleが成立する場合だけ、V111の予定済みWheat plantingを少量のTomatoへ置換する `demand_backed_tomato_option` です。上位replayのaction列やportfolioをコピーせず、V111とrepository-owned codeだけで独自実装してください。

## 0. 最初に読むもの

次の順に読んでください。

1. `AGENTS.md`とgame処理順に必要な`README.md`
2. `docs/research_20260916_current_meta_and_next_strategy.md`
3. `data/analysis/research_20260916_next_strategy/strategy_evidence.json`
4. `data/analysis/research_20260916_next_strategy/current_top_execution_audit.json`
5. `data/analysis/research_20260916_next_strategy/current_submission_fidelity.json`
6. `data/analysis/research_20260916_next_strategy/remote_market_order_audit.json`
7. `docs/research_20260915_router_mechanism_report.md`
8. `experiments/research_20260915_router_mechanism/final_decision.json`
9. `experiments/research_20260915_router_mechanism/mechanism_attribution.json`
10. `docs/research_20260912_continuation_report.md`
11. `docs/current_meta_analysis_20260910.md`
12. `docs/champion_weakness_map_20260910.md`
13. `agents/v111/main.py`、`agents/v110/main.py`、`agents/v109/main.py`と、それらがruntimeで使うrepository-owned dependency
14. `.venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py`のcrop、water、market、Town、日次refresh処理
15. `scripts/evaluation/runner.py`、`safety.py`、`statistics.py`、`divergence.py`、`lifecycle.py`

前回experimentは完了済みです。P1/A0/A1/A2、terminal sales、Sheep/Goose continuationを未完了と誤認して再実行せず、既存artifactを上書きしないでください。P1/D1/R0のsource、blob、tree、route、threshold、action tableをcandidateへ転記・変換・importしないでください。production ChampionはV111に固定してください。

新experiment IDは実行日のUTC/JST日付を使い、原則 `research_YYYYMMDD_v111_tomato_option` とします。

## 1. 開始時保全

新manifestへ最低限、次を保存してください。

- UTC/JST開始時刻、5時間後deadline。
- branch、HEAD、`git status --short`。未commit差分とユーザー作成fileを保全する。
- 本prompt、上記必読file、runner/evaluator/engine/configuration、V111/V110/V109のSHA-256。
- 実行中のPython/Kaggle processとcommand line。
- repository全体のstructured seed使用履歴とfree-text mentionを分離したseed audit。
- 既存experimentの完了状態と、再利用artifactのhash verification。
- current Top replay 30 target seats / 26 unique replayをDiscoveryに固定し、Development/Promotion/Freshへ数えないこと。
- active remote submission 56089444は`close behavioral relative; archive identity UNVERIFIED`とし、V111 exactと認証しないこと。

Leaderboardは開始時にread-onlyで1回だけrefreshして構いません。順位やsubmissionが変わっていれば新snapshotを保存しますが、新ログをcandidateのthreshold調整には使わないでください。

## 2. 固定する既知事実

次を再解釈して変更しないでください。

- local production ChampionはV111。
- 旧spent 32 contextsでV111は12/0/20、win-score 0.375。
- P1 fullは24/0/8、V111比 +0.375だがraw Safety 32/32 failureでresearch-only。
- A0 route-lockedはV111比 +0.3125。P1 upliftの83.33%が固定route0+initial footprintでも残る。
- router固有値はP1−A0 = +0.0625、1 source-seed block、1 source/ancestryだけでtransfer gate不成立。
- A1 no-day6はA0と同じ。A2 no-day24はP1と同じ。day24 Carrot routerのincremental valueは0。
- PSRにknown-source identity proxyは確立しなかったが、route provenance/licenseは不十分で、全ablationにanimal/crop/no-op/partial-commit Safety failureがある。
- terminal即時売却とTown同期売却はL→W 0でmargin悪化。
- managed Sheep/GooseはともにW→L 2。managed Gooseはself coin +128.2でもopponent coin +1220.6、margin -1092.4。
- 2026-09-16 00:33 JST snapshotのTop 5は30 target seatsで22/0/8。これはselected observational sampleでrating estimateではない。
- Current Top 5 minus historical V111 mean portfolioはWheat +3.596、Carrot +1.959、Tomato +3.317、Strawberry -3.612、Melon -0.014、Cow -0.267、Sheep -1.418、Goose +1.782。cross-corpus記述差でありpaired効果ではない。
- Current Top 5ではTomato seed購入22/30、初回step中央値320.5。ただしSpaTaroの6観測はTomato 0、Goose 0で6/6。Tomatoは必要条件でも単独勝因でもない。
- Current Top 5の8敗中7件はmargin 5,000未満。terminal stranded-price proxyはCurrent Top 5 128.8、historical V111 264.7で、この差だけでは主要敗戦を説明できない。
- active remote 56089444とlocal V111は最新8 replayで5,725/5,752 actions一致。27差はfield/hands 0、market-order multiset 0、ordered marketだけ27。一手再計算でlocal順序のself cash差合計+12、opponent -29だがclosed-loop効果は未確認。

## 3. 情報・license・候補境界

deploy可能candidateが使えるのは、自分のprivate state、現在および過去のpublic observation、configuration公開値、自分自身の固定model/routeだけです。

次をcandidateへ含めないでください。

- opponent名、team/submission/episode/source ID、seed、rating。
- opponent private state、未公開shop、future RNG、offline replayの未来状態。
- known opponentのposition、portfolio、action列を識別するfingerprintと対応route。
- 新しいopponent prediction model、future supply/price/shop forecast。
- Top replay、PSR、P1/D1/R0のexact action sequence、route、tree、threshold、blob。
- source別勝敗を使うruntime selector。
- unsafe actionをPASSへ変えるだけのsanitizer。

C1 triggerではrival public farmも使わないでください。今回許可する外生情報は、現在までに公開されたTown shops、現在のpublic market price/inventory、configurationだけです。feasibilityには自分のmoney、seed、shed/carry、worker数と位置、tile、crop lifecycle、既存V111 taskを使えます。

親はV111とrepository-owned codeだけとし、source/package diff、license inventory、runtime import treeを保存してください。これは法的clean-room認定ではありません。不明点は`UNVERIFIED`のままにします。

## 4. Primary questionとpreregistration

Primary question:

> 公開TownでTomato需要が確認された中盤stateに限り、V111の予定Wheat plantingをcomplete schedule付きTomato optionへ置換すると、V111の既存勝ちを落とさず、raw Safety 0のまま、旧spent panelの2 sources以上でsafe deliveryまたはwin-scoreを改善できるか。

Secondary diagnostics:

- upliftがself production/realized saleから来るのか、public market/Townを介した相手closed-loop応答と整合するのか。
- どのcash、worker、tile、remaining-day条件がoption completionに必要か。
- current TopのTomato採用はTown需要と時間順に整合するか。これはE1で、candidate因果効果には数えない。

評価前に日本語preregistrationとmachine-readable planをfreezeしてください。旧pair結果を最大化するthreshold search、複数crop/animalの同時変更、結果を見た発火条件修理は禁止です。

## 5. Phase A: zero-action-change shadow feasibility

新candidateを作る前に、既存V111 control replayだけからshadow loggerを作ってください。shadow loggerはV111 actionを一切変更してはいけません。

各実在stateについて次を保存します。

- Tomato需要shopの種類、unlockを初めて観測したstep、現在のdemand rate。
- 現在のTomato/Wheat priceとinventory。
- V111が次に行う予定のeligible Wheat seed購入・plant taskとtile。
- Tomato seedの必要cash、購入slot、pickup/plant可否。
- 植付日からfirst yieldまでの全日給水task、各worker route長、他のurgent WATER/FEEDとの競合。
- harvest可能日、実収穫想定units、carry/shed容量、dropと次state以降の合法SELL slot。
- latest safe plant day、terminal前に実現可能なcash conversion。
- option完了後にV111へ戻れる明示的state。時刻だけのrejoinは禁止。
- Wheatを置換するopportunity cost。未来相手行動や未来priceを予測せず、official mechanicsと現在stateから計算できる範囲をEvidence/Inferenceに分ける。

Tomatoはseed 50、first yield day 8、daily interval 1、max yield count 4のongoing cropで、連続2日水切れでweedになることをengine hash付きで確認してください。現在shopが将来も存在することとTown consumption scheduleはofficial mechanicsからのみ扱います。

shadow feasibility gateは次を全て満たす場合だけ通過とします。

1. 実在する旧spent control stateでeligible eventが2 sources以上のsource-seed blocksに存在する。
2. V111の予定済みWheat taskとの置換点が一意で、tileとworker scheduleを未来のreplay actionに依存せず生成できる。
3. seed購入、plant、全日water、harvest、carry/drop、sell、rejoinまで一意に定義できる。
4. urgent crop/animal maintenanceと衝突せず、worker/cash/shed/market slot reserveがある。
5. current Top replayのaction列、既知source trajectory、PSR routeを使わない。
6. fixed parameterはofficial mechanicsとresource boundから導出し、旧勝敗を見て選ばない。

一つでも不成立ならC1を作らず、`REJECT_NO_FEASIBLE_CONTRACT`または`PROMISING_UNPROVEN`で終了してください。Carrot、Goose、Sheep、terminal sellへ横滑りしないでください。

最低限、`shadow_feasibility.json`、`option_economic_contract.json`、`eligibility_by_source_seed_block.json`を作成してください。

## 6. Phase B: 条件付きC1実装contract

Phase Aを通った場合だけ `C1_v111_demand_backed_tomato_option` を作成します。実装前に`candidate_contract.json`とpreregistration amendmentをfreezeしてください。

最低限、次を一意に定義します。

- 発火: 新しく公開された`PIZZA_SHOP`または`FARMERS_MARKET`のTomato需要、現在market price/inventory、own feasibilityのみ。
- 発火phase: shop unlockという自然eventとengine-derived latest safe plant day。known seed/sourceを再現する固定step列にしない。
- replacement対象: V111が実際に予定していたeligible Wheat plantだけ。既存Tomato/other cropを上書きしない。
- max tiles/quantity: remaining deterministic Town absorption、worker water capacity、carry/shed capacityから事前導出。結果を見て増減しない。
- preflight: cash、seed、market order slots、tile、unit position、worker、日次WATER/FEED reserve、harvest/carry/sell deadline。
- persistent task: buy seed、pickup、plant、当日water、以後全日water、harvest、carry/drop、合法quantityのSELL。
- SELL: pre-action shed以下、逐次commit、max order slots、partial/no-op時の扱い。oversized SELL禁止。
- rejoin: V111が期待するtile crop/state、全unit position、inventory/carry、urgent tasksが明示条件を満たしたときだけ。単にstepが来たら戻さない。
- abstain: 全条件を満たさない場合はV111 actionをbyte-equivalentに維持。
- log: 元action、置換action、public trigger、private feasibility、resource差、worker schedule、water/harvest/sell completion、rejoin成功。

option開始後にcontractを完了できないと実装中に分かった場合は、勝敗を見る前に中止して理由を保存してください。

## 7. import、A/A、smoke

C1を作った場合、次の順に行います。

1. package import isolation、最後のcallable、両seat、step 0 reset、同一process連続episode、fresh process。
2. V111 A/AとC1 A/A。独立load反復でaction/state/final coin一致。
3. 発火contextと非発火contextを最低1つずつ両seatでsmoke。
4. 全smokeで720 states/719 decisions、runtime/timeout/incomplete/negative cash/delivery failure 0。
5. 発火しないcontextではV111と最初から最後までaction/state一致。
6. 発火contextでは全Tomatoのplant/water/harvest/carry/sell/rejoinをtraceし、未収穫/未販売見込みを実現収入に数えない。

新規・変更Pythonに`py_compile`と`ruff`を実行してください。external sourceの既存style errorはown codeと分離します。

## 8. 旧spent paired compatibility

smoke合格後だけ、旧4 sources × seeds `10091011–10091014` × 両seatの32 contextsでV111対C1をclosed-loop paired評価します。

control再利用はengine/configuration/opponent/seed/seat/control/evaluator hashが一致し、`remainingOverageTime`以外のstate再現をmachine checkできる場合だけ許可します。pair keyにはcandidate source/package hash、engine、configuration、opponent、seed、seat、evaluator hashを含め、pairごとにJSONL flushし、duplicate/partial/hash混入を検査します。

これはtrained/development panel上のcompatibilityであり、新規発見、promotion、一般化証拠と呼ばないでください。

gateは次で固定します。

- runtime error、timeout、incomplete、negative cash、delivery failure 0。
- V111比の新raw Safety failure 0。
- 新animal loss、crop-to-weed、水切れ、lifespan decay、silent field/market no-op、partial commit、oversized extra SELL、missing hands 0。
- V111比win-score差 > 0。
- safe L→Wが2 source-seed blocks以上かつ2 sources以上。
- W→L=0、W→D=0、全source別win-score非悪化。
- whole source+seed block bootstrap 95%下限 > 0。
- equal-source、equal-ancestry、source重み±0.2の9 scenarioでworst delta > 0。
- exclude-self、exclude-near-lineage、exclude-tape-matchedで差が負にならない。
- forbidden feature、identity proxy、license、runtime import監査合格。

1項目でも不合格なら新seedを開かず、repair、max-tile変更、price threshold変更、shop subset変更を打ち切ります。SafetyだけのC2 repairも今回は作らないでください。complete option自体が今回のSafety contractだからです。

## 9. 独立sourceとDevelopment

C1 resultを見る前に、既存`experiments/independent_gold_pool/`と`artifacts/opponent_pool/candidates/`をread-only監査し、同一hashの前回screenは再利用してください。current Topの非公開sourceをreplayから復元しないでください。

source選択条件:

- V111、local mainline、PSR/Kaito派生でない。
- source URL/revision/hash/license/native callable/dependency/runtime/import ancestryが確認できる。
- V111だけを旧spent seedsでscreenし、win-score 0.25–0.75のsourceを最大2つ、C1結果を見る前に固定する。
- 弱すぎるanchorだけなら第3 ancestry一般化と数えない。

旧spent gateを全て通った場合だけ、`10091521–10091536`がrepository全体で未使用か確認し、未使用なら16 blocksを一括登録してDevelopmentを開始してください。1つでも使用済みなら、結果を見る前に同じ命名規則で次の連続16 blocksを機械的に選びます。

Development条件:

- 凍結16 blocksを旧4 sourcesと事前固定した独立source、両seatで全件完了。
- active contexts 64以上。
- safe L→W 4 blocks以上かつ2 independent ancestries以上。
- W→L=0、W→D=0、全source非悪化。
- raw/追加Safety、runtime、timeout、incomplete、negative cash、delivery違反0。
- bootstrap 95%下限 > 0、equal-source/equal-ancestry/9 reweighting/全除外差 > 0。
- verified independent ancestries 3以上。

promotion `10091101–10091112`、Fresh `10091901–10091912`、旧Development `10091421–10091436`は今回も開かないでください。全Development gateを通ってもFreshはsealedなのでlabel上限は`E4_QUALIFIED_FRESH_SEALED`、production ChampionはV111のままです。license/ancestryが不明ならnumeric agentを作らないでください。

## 10. 必須集計

C1を作った場合、次を保存・報告してください。

- overall/source/ancestry別W/D/L、win-score、margin、P10。
- L→W、W→L、D→W、W→D、L→D、D→Lとsource-seed block数。
- self/opponent coin差と日別increment。
- first action/state/market/price/Town/opponent-action divergenceとresponse lag。
- optionのtrigger/abstain数、Tomato tiles、seed purchased/committed、water scheduled/completed、actual harvest units、carry/drop/sell units、realized sale、rejoin成功。
- opportunity-costとして置換されたWheat unitsと実現sale。future inventoryをcashにしない。
- crop-to-weed、spawned weed、water death、lifespan decay、animal loss。
- silent no-op、partial market commit、oversized SELL、failed BUY/HIRE、missing hands。
- whole-block bootstrap、equal-source/equal-ancestry、9 reweighting、全除外感度。
- public triggerがsourceをどれだけ予測するか、leave-one-source、近傍price/inventory摂動。source identity proxyならreject。
- Evidence、Inference、Unknownを分離したmechanism attribution。相手coin低下を単一actionの因果効果と呼ばない。

## 11. 必須artifact

最低限、次を作成してください。

- `docs/research_YYYYMMDD_v111_tomato_option_preregistration.md`
- `docs/research_YYYYMMDD_v111_tomato_option_report.md`
- `experiments/research_YYYYMMDD_v111_tomato_option/manifest.json`
- `seed_ledger.json`
- `input_artifact_verification.json`
- `leaderboard_and_replay_audit.json`
- `remote_package_fidelity_audit.json`
- `shadow_feasibility.json`
- `option_economic_contract.json`
- `eligibility_by_source_seed_block.json`
- C1を作る場合の`candidate_contract.json`、`candidate_integrity.json`、freeze、exact diff、license/import inventory、plan、pairs.jsonl、runs、summary、replays
- `mechanism_attribution.json`
- `independent_source_screen.json`
- `development_progress.json`
- `final_decision.json`
- `final_artifact_manifest.json`
- `final_artifact_verification.json`
- exact再現commandと同一hash resume command

## 12. 最終statusと終了条件

最終判断は次のいずれかにしてください。

- `REJECT_NO_FEASIBLE_CONTRACT`
- `REJECT_PROHIBITED_DEPENDENCY`
- `REJECT_SAFETY`
- `REJECT_NO_UPLIFT`
- `PROMISING_UNPROVEN`
- `E4_QUALIFIED_FRESH_SEALED`

Tomatoを作っただけ、Topのportfolioへ近づいただけ、self coinが増えただけでは合格にしません。確認未完了、independent source不足、license不明、identity-proxy判定不能なら上限は`PROMISING_UNPROVEN`です。Safety違反またはW→Lが残るcandidateはrejectです。

終了時に関連Python/Kaggle processが残っていないことを確認してください。最終回答では少なくとも次を明記してください。

- shadow feasibilityが何source-seed blocks、何sourcesで成立したか。
- C1を作ったか。作らなければどのresource/schedule/rejoin条件が不成立だったか。
- 実発火数、complete Tomato lifecycle、realized self revenue、opponent closed-loop差のEvidence/Unknown。
- raw Safetyを0、W→Lを0にできたか。
- 旧spentと条件付きDevelopmentで何blocks、sources、independent ancestriesへ一般化したか。
- numeric agent作成有無とlabel。V111をChampionとして維持または変更しない理由。
- active remote package identityが依然UNVERIFIEDか。
- Kaggle未提出、kernel未push、slot未変更。
- promotion/Fresh/旧Development seed未使用、今回Development seedの使用状況。

時間配分の目安は、0–30分を開始時保全・hash・remote parity・seed/source監査、30–90分をshadow feasibilityとeconomic contract、90–150分をpreregistrationと条件付きC1実装、150–210分をimport/A/A/smoke、210–270分を条件付き旧spent paired評価、270–290分を資格がある場合だけDevelopment開始、290–300分をartifact verificationと日本語報告に充てます。前段gate不合格なら後段へ進まず、閾値探索、PSR修理、別crop/animalへの横滑り、同じ結果の再集計で時間を埋めないでください。
