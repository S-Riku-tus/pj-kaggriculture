# 次スレッド用の研究実行プロンプト（改訂版）

対象repository:

`C:\Users\shiba\Kaggle\pj-kaggriculture`

最大5時間程度で、計画だけで終えず、開始時保全、既存artifactのhash verification、既存replayだけの資金・land・capacity再解析、条件を満たす場合だけのV111由来candidate実装、paired closed-loop評価、artifact検証、最終判断、日本語報告まで進めてください。Kaggleへの提出、kernel push、submission slot変更は行わないでください。公開Leaderboard、discussion、public replayのread-only取得は可能ですが、非公開sourceを推測・復元したり、取得不能なlicense/provenanceを推測で埋めたりしないでください。

このpromptは`docs/codex_next_prompt_20260916_v111_tomato_option.md`を置き換えます。旧Tomato案は実行しないでください。今回の主目的は作物追加ではなく、V111のstep 144–264における資金拘束と、第3農地を購入してから実現売上を作るまでのactivation contractを切り分けることです。

## 0. 最初に読むものと開始時保全

次の順序で読んでください。

1. `AGENTS.md`とゲーム処理順、market order逐次処理、land cost、crop/animal lifecycle、Town処理に必要な`README.md`
2. `docs/research_20260916_rethought_next_steps.md`
3. `docs/research_20260915_router_mechanism_report.md`
4. `experiments/research_20260915_router_mechanism/final_decision.json`、`mechanism_ranking.json`、`mechanism_attribution.json`
5. `docs/research_20260916_current_meta_and_next_strategy.md`。保存済み観測値は再利用してよいが、Tomatoを次の主仮説とした結論は失効済みと扱う。
6. `data/analysis/research_20260916_next_strategy/strategy_evidence.json`
7. `data/analysis/research_20260916_next_strategy/current_top_execution_audit.json`
8. `data/analysis/research_20260916_next_strategy/current_submission_fidelity.json`
9. `data/analysis/research_20260916_next_strategy/remote_market_order_audit.json`
10. `docs/v7_design_report.md`、`docs/v109_design_report.md`、`docs/research_20260912_continuation_report.md`のcrop、land、productive capacity、terminal sale、livestock、Safety節
11. `agents/v111/main.py`、`strategy_model.json`、`submission_manifest.json`、`metadata.json`、`README.md`
12. `scripts/evaluation/runner.py`、`safety.py`、`statistics.py`、`divergence.py`、`lifecycle.py`と、今回再利用するreplay loader/analysis code
13. repository全体のseed ledger、`experiments/independent_gold_pool/`、`artifacts/opponent_pool/candidates/`

新しいexperiment IDは実行日のUTC/JST日付を使い、原則`research_YYYYMMDD_v111_midgame_capacity`とします。開始時に次を新manifestへ保存してください。

- UTC/JST開始時刻と5時間後のdeadline。
- branch、HEAD、`git status --short --ignore-submodules=all`。既存dirty差分とユーザー作成fileを保全し、無関係な変更を戻さない。
- 本promptと必読file、runner/evaluator、engine/configuration、V111、再利用するcontrol/opponent/replayのSHA-256。
- 実行中のPython/Kaggle processとcommand line。
- binary、cache、vendorを除外したrepository全体のseed利用履歴。structured recordとfree-text mentionを分ける。
- 既存experimentの完了状態、今回再利用するartifactのhash verification、duplicate/partial JSONL監査。
- 今回のpreregistrationとmachine-readable planのhash。結果を見る前にfreezeする。

前回までのexperimentは完了済みです。P1/D1/R0/A0/A1/A2や既存independent screenを未完了と誤認して再実行せず、旧artifactを上書きしないでください。production ChampionはV111で固定します。

## 1. 固定する事実

次を都合よく再定義しないでください。

### 1.1 PSR/router

- P1 fullのV111比win-score差は`+0.375`、A0 route-lockedは`+0.3125`。A0はP1 total-policy upliftの83.33%を残した。
- router固有差P1−A0は`+0.0625`、qeinstein seed `10091013`の1 source-seed block、1 source、1 ancestryだけ。day 24 switchの勝敗寄与は0。
- P1/A0/A1/A2はraw Safety failure 32/32、W→L 2。P1由来route/blob/tree/threshold/action tableのtransitive provenance/licenseは未確認。
- 旧改善の大半が固定route/初期footprintを含むtotal policyで説明可能なことはEvidenceだが、step 0 WHEAT、資本温存、固定routeの個別因果量はUnknown。
- PSRのrepair、route移植、threshold抽出、action列再構築は今回の対象外。

### 1.2 現上位の公開ログ

- 保存済みLeaderboard snapshotはUTC `2026-09-15T15:33:56.343605+00:00`、JST `2026-09-16 00:33:56`。
- 当時のTop 5はMajkel1337 3150.8、Artem The Farmer 3149.2、SpaTaro 3058.4、Sida Zuo 3048.7、DSM 3040.6。
- Top 5の各active submissionから先頭6 EpisodeService rowsを固定して取得し、30 target-seat観測、26 unique replayを解析済み。22W/0D/8L、mean margin `+3459.5`、P10 `-2906`だが、選択済みopponent mix上のE1観測でありrating推定やpaired効果ではない。
- step 48 field hashは22種類、step 300は30/30、portfolio continuationも30/30が異なる。単一の上位routeは存在しない。
- Tomato seed購入は22/30、初回中央値step 320.5。しかし上位8敗の平均Tomatoは4.25、22勝では2.98で、SpaTaroはTomato 0・Goose 0の6観測で6勝。Tomatoを直接の勝因としない。
- 上位第2区画unlock中央値はstep 150、第3区画はstep 209。勝ちの第3区画中央値208.5、負け210であり、早期landは上位内の勝敗を説明しない。
- productive tile差は主にstep 216–264で、Tomato初回購入中央値より前。step 600では歴史的V111が上位平均を上回る。問題候補は最終面積でなく、中盤の資本回収・activation timingである。
- public replayから得たaction、public state、aggregate portfolioは研究診断に使えるが、source code、private state、将来state、exact routeの復元物ではない。

Leaderboard snapshotが開始時に24時間以上古い場合だけ、同じ固定規則で一度だけread-only refreshして構いません。refreshする場合、candidate結果を見る前に対象順位・各submissionから取るrow数・取得時刻をfreezeし、旧corpusと新corpusを混ぜず、両方のhashを保存してください。24時間未満なら再取得しません。順位や観測勝敗を見て対象teamやrow数を変えないでください。

### 1.3 V111のlandとcash

- 歴史的V111の第2区画unlockは概ねstep 161、第3区画はstep 253–266。
- 旧spent V111 controls 32 contextsではstep 192/198/209/216/222のcash≥2000は0/32。cash中央値は順に482、77、55、216、103.5。
- step 240はcash中央値1403で8/32だけが2000以上、step 248は1788.5で2/32だけが2000以上。
- step 253は全32が2000以上、24/32がすでに第3区画をunlock。step 264でも24/32で、残りrouteは後でunlockする。
- 上位中央値step 209にV111が第3区画を買えない主因は、単なる発火thresholdではなく、先行支出による流動性不足である。

### 1.4 既存の負の証拠

- V7 broad OOD/recovery/crop controllerはday 20 productive tilesを約66.4から70.5へ増やしても20戦0勝、平均差`-8356`。
- bounded Carrot rotationは3W/2D/5L、平均差`-1112`。Tomato diversificationもreplacement cost/timingを補えず棄却済み。
- V109のmissing-third-land broad fallbackは土地を買ったがmean rewardを97,961から85,395へ低下させた。
- immediate/Town sale、retain Cow、managed Sheep、managed Goose、unmanaged Sheepはpaired評価で無効または悪化した。
- `BUY_LAND`単独、汎用rule fallback、crop/animalの横滑り、terminal sellの再探索はしない。

### 1.5 remote fidelity

- active remote submission `56089444`の直近8 public replayに対し、V109/V110/V111/V113はいずれも5725/5752 actions、99.53%一致したがexact episode一致はない。
- 27差分は同じmarket order multisetのorder差で、一手監査のself cash効果合計は`+12`、opponentは`-29`。closed-loop全体の効果とremote package identityはUnknown。
- exact archiveを取得物のhashで確定できない限り、active remoteをV111 exactと断定しない。package parityはhygieneであり今回の主strategy仮説ではない。

## 2. 今回の問い

Primary diagnostic question:

> V111が上位中央値より約36–55 decisions遅れて第3農地を開ける原因のうち、同じ一種類の既存支出familyを延期・順序変更するだけで解消できる資金拘束はあるか。また、早く買った土地を同じgame day内に実働化し、既存maintenanceを壊さず、terminalまでに実現売上へ変えられるV111-owned contractが存在するか。

Primary transfer question:

> その機構が2 sources以上の複数blockで成立する場合、上位/P1のrouteやportfolioをコピーせず、V111自身の予定済みasset familyだけをresequenceする一つの`midgame_third_land_capital_and_activation_commitment`として独自実装し、raw Safety 0、W→L 0、paired upliftを保てるか。

Secondary causal question:

> margin変化を、土地購入時刻、新規区画の実働化、自己生産・回収、market/Town mediator、相手のclosed-loop応答へ時間順にどこまで限定できるか。

相手coin低下や上位の高いproductive tileはtotal-policy相関です。単独の`BUY_LAND`や特定作物の因果効果と呼ばないでください。

## 3. 情報境界、license境界、禁止事項

deploy可能candidateが使えるのは、自分のprivate state、現在および過去のpublic observation、configurationの公開値、自分自身のrepository-owned固定model/routeだけです。次をcandidateへ含めないでください。

- opponent名、source/team/submission/episode ID、seed、seed由来情報。
- opponent private state、未公開shop、未来RNG、offline replayの未来state。
- 上位/P1の位置、portfolio、行動列、時刻列、離散signatureから固定future routeへ飛ぶselector。
- P1のblob、tree、node、threshold、route index、action sequenceの転記または機械変換。
- 新しいopponent prediction model、供給forecast、未来price/shop推定。
- source/seed別勝敗で発火条件、reserve、購入step、asset数を最適化する処理。
- `BUY_LAND`だけを早めるvariant、invalid actionをPASSへ変えるsanitizer、汎用rule-policy fallback。
- Tomato/Carrot/Goose/Sheep、terminal saleなど別仮説の同時追加。

current public market/price/inventory/Town、自分のcash・shed・seed・unit・tile・urgent task、configuration上のland cost/lifecycleを使う一般則は許容します。ただし既知sourceをほぼ一意に識別する離散signatureは使えません。

上位public replayはaggregate timing、action category、public-state transitionのE1比較に限ります。exact action route、hidden source、package、licenseを復元しません。candidateはV111とrepository-owned codeだけを親にし、external research moduleをimportしません。source/package diff、hash、license inventoryを保存してください。

## 4. gameを始める前の資金・land・activation監査

新しいgameを始める前に、旧spent V111 controls 32 contextsと保存済みTop corpusだけから次を作成してください。

### 4.1 cashflow ledger

V111のstep 144から第3農地unlock後48 decisionsまで、contextごと・stepごとに次を記録します。

- pre/post cash、cash delta、successful sales、Town income、market price/inventory delta。
- market orderの順序、要求量、実成立量、cost/revenue、silent no-op、partial commit。
- `HIRE`、`BUY_SEED` crop別、`BUY_ANIMAL` species別、`BUY_PRODUCT` item別、`BUY_LAND`の実支出。
- そのstepで必要なWATER/FEED/HARVEST/carry/shed作業、hands数、unit position。
- 支出を`urgent maintenance`、`existing production continuation`、`deferrable irreversible investment`、`land/activation`へ分類した根拠。
- 第3農地を買うまでの最大cash shortfallと、それを生む支出family。

分類は勝敗を見て変えず、日本語preregistrationで定義します。cashが後で戻るというだけでmaintenanceを延期可能と扱わず、asset loss、missed harvest、market slot、worker travelを含むopportunity costを記録してください。

### 4.2 unlock-relative activation timeline

各contextの第3農地unlockを相対時刻`t=0`として`t=-96..+96`を整列し、次を保存します。

- unlock quadrant、最初のunit entry、最初の合法field action、最初のplant/build/place。
- 新規区画と全farmのproductive tiles、空tile、weed、crop/animal portfolio。
- 最初のWATER/FEED、最初のHARVEST、実収穫units、carry/drop、実成立SELL。
- land cost以外のseed/animal/structure/hire/worker-turn cost。
- 既存区画で失われたmaintenance、生産、収穫、sale。
- 最初の自己coin回収と、public market/price/Town divergence、最初のopponent action divergence、そのlag。

Top corpusにも同じaggregate指標を計算しますが、target seatだけを使い、勝ち/負け、team/submission別を併記します。Topのexact routeをreportやcandidateへ複製しません。V111とTopの差はcross-corpus Evidenceであり、candidate効果ではありません。

### 4.3 shadow capital counterfactual

actionを変えず、V111 ledger上で「一種類の支出familyだけを一時延期した場合に、算術上いつland cost 2,000とactivation reserveへ到達できるか」を計算します。

- これはfuture price、相手応答、延期assetのcounterfactual outputを固定できない算術上界です。paired性能や実現可能なcoinと呼ばないでください。
- familyはcontextごとに別物へ切り替えず、candidate全体で一種類に固定できるものだけを候補にします。
- activation reserveは土地代とは別に、事前に固定したseed/animal/structure/hire/market-slot/worker/maintenance/carry/sell costの合計として定義します。
- 旧pairの勝敗を最大化するためにfamily、reserve、開始step、tile数を探索しません。
- V111が元々そのfamilyから得た実収穫・売上と、延期による最悪のtask debtを併記します。
- 24 decisions未満の前倒しは、一日単位のproduction/maintenance cycleを新たに確保しないため、実装gateの前倒し件数に数えません。

### 4.4 必須artifact

最低限、次を作ります。

- `midgame_cashflow_ledger.json`
- `land_relative_activation_timeline.json`
- `current_top_capacity_comparison.json`
- `shadow_capital_counterfactual.json`
- `opportunity_cost_by_spend_family.json`
- `capacity_mediator_timeline.json`
- `mechanism_ranking.json`
- `mechanism_attribution.json`

`mechanism_attribution.json`では、landが早い、productive actionが早い、収穫が増える、実現saleが増える、opponent coinが変わる、marginが変わる、を別nodeにし、各edgeを`Evidence`、`Inference`、`Unknown`へ分離してください。

## 5. 機構rankingと実装へ進むgate

既存replay監査後、最大4件を次の順序で比較します。

1. `third_land_capital_and_activation_commitment`: 一種類のV111既存支出をresequenceし、土地購入から実現saleまで閉じる。
2. `post_unlock_activation_only`: V111自身の購入時刻は変えず、購入後の空き時間だけを縮める。十分な遅延が既存replayにある場合だけ候補。
3. `remote_market_order_parity`: exact packageがhashで確定できた場合だけの再現性hygiene。strategy uplift候補にしない。
4. `demand_backed_tomato_option`: 今回はdeferred。実装・評価せず、なぜ優先度が低いかだけ記録する。

各機構について、変えるstate/action、V111に既にある部分、必要resource、worker/route/lifecycle/sale完全性、既存負の実験との差、identity risk、Safety risk、license risk、Evidence/Inference/Unknownを保存してください。

`C1_v111_midgame_capital_commitment`へ進めるのは次を全て満たす場合だけです。

1. 同じ一種類の延期可能支出familyで、2 sources以上かつ4 source-seed blocks以上において、land cost 2,000と固定activation reserveを作れる。
2. 第3農地unlockをV111より24 decisions以上早め、その同じ24 decisions内に新規区画で合法なproductive actionを開始できるshadow scheduleがある。
3. 支出延期からland、調達、market order、worker、移動、配置、WATER/FEED、HARVEST、carry/drop、SELLまで、一つのstate-machineとして一意に定義できる。
4. 変更後もterminalまで完了するV111-ownedのstate-compatible suffixがあるか、毎step current stateから契約を再検証する一般executorを定義できる。
5. V111の既存asset familyをresequenceするだけで、crop/animal portfolio仮説を追加しない。
6. urgent maintenance、shed capacity、market order上限、worker position、daily hire reset、land順序を全てpreflightできる。
7. V109 broad fallbackと異なり、開始条件、変更action family、task debt、終了/rejoin状態が限定されている。
8. P1/Topのroute、threshold、exact action timing、source/seed情報を一切必要としない。

満たさなければ候補を捏造せず、`REJECT_NO_FEASIBLE_CONTRACT`または`PROMISING_UNPROVEN`で診断完了としてください。Tomato、Carrot、livestock、terminal saleへ横滑りせず、新seedを開かないでください。

## 6. 条件付きC1の実装contract

C1を作る場合、親はV111だけです。実装前に`candidate_contract.json`とpreregistration amendmentをfreezeし、次を一意にします。

- 発火に使うcurrent own/public feature。source、seed、opponent identity、fixed replay step tableは使わない。
- 延期するV111既存支出family、そのorderを延期する条件、task debt、catch-upまたは明示的cancel条件。
- land cost 2,000、activation reserve、maintenance reserveのengine-derived内訳。paired結果を見て変更しない。
- 第3農地だけを対象とし、第4農地や追加portfolio familyを同時に扱わない。
- `BUY_LAND`のorder位置、pre-order cash、maxMarketOrdersPerTurn、前段order失敗、逐次commit後のstate確認。
- unlock quadrantの確認前にfield activationへ進まないこと。
- 新規区画で使うasset type/countはV111自身の既存予定から事前固定し、Top/P1 portfolioから選ばない。
- unit選択、移動、tile、seed/animal/structure、日次WATER/FEED、HARVEST、carry/drop、SELLのcomplete schedule。
- oversized SELL、partial commit、silent BUY/HIRE、missing handsを起こさない逐次成立条件。
- 既存tile/animalのurgent maintenanceを新規land taskより優先する規則。
- explicit state-based rejoin。単に元routeの時刻が来たら戻るfallbackは禁止。
- 発火しないcontextでV111とaction/stateが最後まで一致すること。
- 全発火log。元action、置換action、cash/resource差、延期task、新規land task、maintenance、harvest/sale、rejoin成功を含める。

`BUY_LAND`だけを早め、新しい区画を後で放置するものはC1ではありません。contractを実装途中で満たせないと分かったら勝敗を見る前に中止し、理由とpartial artifactを保存してください。C2、Safety repair、reserve/step/tile数の再探索は今回は行いません。

## 7. independent sourceを結果前に固定

C1のsource別resultを見る前に、`experiments/independent_gold_pool/`、`artifacts/opponent_pool/candidates/`、取得可能な新しいpublic standalone sourceをread-only監査します。

- 前回screen済みの同一hashは再走せず、結果を再利用する。新revisionだけを別sourceとして扱う。
- local mainline、V111、PSR/Kaito派生ではないこと。
- source URL、revision、取得時刻、hash、license、native callable、dependency、runtime、import ancestryを確認する。
- source/artifact取得不能、license不明、native実行不能なら選ばない。Leaderboard scoreやpublic replayからcodeを推測しない。
- baseline V111だけを旧spent seedsで評価し、win-score 0.25–0.75のsourceを最大2つ選ぶ。
- 複数ならancestry、opening、land timing、crop/animal portfolio、market order timingの差を優先し、C1との相性を見て選ばない。
- selection rule、全screen結果、source package hashをC1 paired結果より前にfreezeする。

適切なsourceがなければ、第3 independent ancestryを確認したと扱わず、最終status上限を`PROMISING_UNPROVEN`にします。現在Top public replayはnative callable/source/licenseがないため、この独立source数に含めません。

## 8. import、A/A、smoke、旧spent paired評価

C1を作った場合だけ次の順に進めます。

1. package import isolation、最後のcallable、両seat、step 0 reset、同一process連続episode、fresh processをunit testする。
2. V111 A/AとC1 A/Aを同じ固定contextで独立load反復し、action/state/final coin一致を確認する。
3. 発火contextと非発火contextを最低1つずつ両seatでsmokeする。
4. 全smokeで720 states/719 decisions、schema、runtime/timeout/incomplete/negative cash/delivery failure、trace、raw Safetyを勝敗集計より先に確認する。
5. 非発火contextはV111と全action/state一致。発火contextはland購入、activation、maintenance、harvest/carry/sell、rejoinを完走する。
6. smoke合格後だけ旧spent 4 sources × seeds `10091011–10091014` × 両seatの32 contextsでV111とpaired closed-loop評価する。

control再利用はengine/configuration/opponent/seed/seat/control/evaluator hashが一致し、`remainingOverageTime`以外のstateがmachine checkで再現できる場合だけ許可します。pair keyにはcandidate source/package hash、engine、configuration、opponent、seed、seat、control/evaluator hashを含め、pair完了ごとにJSONL flushします。異なるcandidate hashのresume混入、duplicate key、partial recordを検査してください。

旧spentはtraining/development dataであり、今回の新規一般化証拠やpromotion証拠と呼びません。gateは次で固定します。

- runtime error、timeout、incomplete、negative cash、delivery failure 0。
- V111比の新raw Safety failure 0。crop-to-weed、water/lifespan loss、animal loss、silent field/market no-op、partial commit、oversized SELL、failed BUY/HIRE、missing handsをfirst eventで示す。
- C1−V111 win-score差>0。
- safe L→Wが2 source-seed blocks以上かつ2 sources以上。
- W→L=0、W→D=0、全source別win-score非悪化。
- whole source+seed block bootstrap 95%下限>0。
- equal-source、equal-ancestry、各source重み±0.2の9 scenarioでworst delta>0。
- exclude-self、exclude-near-lineage、exclude-tape-matchedで差が負にならない。
- forbidden feature、identity proxy、license、runtime import監査合格。
- land前倒しが24 decisions以上のblock数、activation完了block数、実現incremental harvest/sale、延期assetのlost productionを明示する。

一項目でも不合格なら新seedを開かず、C1 repair、threshold、reserve、tile数、延期family探索を打ち切ります。

## 9. 条件付きDevelopment

C1が旧spent gateを全て通過した場合だけ新しいDevelopment seedを開きます。旧未使用範囲`10091421–10091436`は前回予約として封印を維持し、今回用にはまず`10091521–10091536`の16 blocksがrepository全体で未使用か確認してください。

一つでも使用済みなら、結果を見る前に同じ命名規則で次の連続16 blocksを機械的に選び、全16を一括でmanifestへ登録します。最初の結果を見てseed数を増減せず、subsetを合格例として報告しません。promotion `10091101–10091112`とFresh `10091901–10091912`は今回どの条件でも開きません。

確認panelは旧4 sourcesと、結果前に固定できた新しい独立sourceです。全seed、全source、両seat、full 720を実行します。時間内に全件終了しなければ同一hashだけを再開できるprogress manifestを残し、完了subsetを合格と呼びません。

確認合格条件:

- freezeした16 independent seed blocksが全件完了。
- 全体active contexts 64以上。
- safe L→Wが4 source-seed blocks以上かつ2 independent ancestries以上。
- W→L=0、W→D=0。
- raw/追加Safety、runtime、timeout、incomplete、negative cash、delivery違反0。
- 全source別win-score非悪化。
- whole source+seed block bootstrap 95%下限>0。
- equal-source、equal-ancestry、9 reweighting、exclude-self、exclude-near-lineage、exclude-tape-matchedの全差>0。
- forbidden feature、identity proxy、source/license監査合格。
- 検証済みindependent ancestry 3以上。弱いanchorだけなら強いmetaへの一般化未証明とする。
- candidate interventionが実際に発火し、land前倒し、activation、harvest/sale完了を複数ancestryで再現する。

全条件を通り、candidateがV111/repository-owned codeだけから構成され、license/noticeが明確な場合だけ、`agents/`を走査して次の未使用numeric versionを作成できます。Freshはsealedのためlabelは`E4_QUALIFIED_FRESH_SEALED`で、production Champion V111は変更しません。license/independenceが曖昧ならnumeric agentを作らずresearch-only archiveに留めます。

## 10. 必須集計

C1を作らなくてもreplay-only診断を保存します。C1を作った場合はさらに次を保存・報告してください。

- overall/source/ancestry別W/D/L、win-score、margin分布、P10。
- L→W、W→L、D→W、W→D、L→D、D→Lとsource-seed block数。両seatを独立seed事例として数えない。
- whole-block bootstrap、equal-source、equal-ancestry、9 reweighting、全除外感度。
- step 144–288のcashflow、market order、cash shortfall、延期支出、activation reserve。
- land unlock step、unlockから最初のproductive action/harvest/saleまでのlag。
- productive/empty/weed tile、asset portfolio、worker/hands、travel/action utilization。
- self/opponent coin差と日別increment、market inventory/price/Town、opponent response lag。
- 相手coin低下を単一actionや土地購入の因果効果と呼ばない。
- crop lifecycle、実収穫units、water death、lifespan decay、crop-to-weed、spawned weed、animal loss。
- t672/t719 shed/carry/unharvested proxy。残りdecisionがないinventoryを実現収入にしない。
- market no-op、partial commit、oversized SELL、failed BUY/HIRE、missing handsをorder/step単位で表示。
- V111→C1の差と、land→activation→harvest→saleのmediator chain。
- shadow counterfactualは算術上界、Top比較はE1 cross-corpus、paired C1差だけがE2 closed-loop evidenceであること。
- Evidence、Inference、Unknownを分離した`mechanism_attribution.json`。

## 11. 必須artifactと検証

最低限、次を作成してください。

- `docs/research_YYYYMMDD_v111_midgame_capacity_preregistration.md`
- `docs/research_YYYYMMDD_v111_midgame_capacity_report.md`
- `experiments/research_YYYYMMDD_v111_midgame_capacity/manifest.json`
- `seed_ledger.json`
- `input_artifact_verification.json`
- `leaderboard_and_replay_audit.json`
- `remote_package_fidelity_audit.json`
- `midgame_cashflow_ledger.json`
- `land_relative_activation_timeline.json`
- `current_top_capacity_comparison.json`
- `shadow_capital_counterfactual.json`
- `opportunity_cost_by_spend_family.json`
- `capacity_mediator_timeline.json`
- `mechanism_ranking.json`
- `mechanism_attribution.json`
- `independent_source_screen.json`
- C1を作った場合の`candidate_contract.json`、`candidate_integrity.json`、freeze、source/package hash、exact diff、license/import inventory、plan、pairs、runs、summary、replays
- `development_progress.json`
- `final_decision.json`
- `final_artifact_manifest.json`
- `final_artifact_verification.json`
- exact reproduction commandと同一hash限定resume command

新規・変更Pythonには`py_compile`と`ruff`を実行します。external exact sourceの既存style errorは改変して隠さず、own codeと分離して記録してください。evaluation coreの既存test、candidate import/reset/isolation、A/A、manifest hash、JSONL duplicate/partialを検証します。evaluation coreを変更した場合は、変更前確定結果、旧結果との互換性、control再現を明記してください。

## 12. 終了条件と最終回答

最終判断は次のいずれかです。

- `REJECT_NO_FEASIBLE_CONTRACT`
- `REJECT_PROHIBITED_DEPENDENCY`
- `REJECT_SAFETY`
- `REJECT_NO_UPLIFT`
- `PROMISING_UNPROVEN`
- `E4_QUALIFIED_FRESH_SEALED`

replay-only監査で完全contractが作れなければ、game数を増やさず`REJECT_NO_FEASIBLE_CONTRACT`で終えて構いません。旧spent合格でも独立source不足、license不明、Development未完了、identity-proxy判定不能なら上限は`PROMISING_UNPROVEN`です。Safety違反やW→Lが残るcandidateはrejectです。Freshを開かないため`PROMOTE`は使いません。

実行終了時に関連Python/Kaggle processが残っていないことを確認してください。最終回答には少なくとも次を明記します。

- これまでのPSR/router、Top public replay、過去crop/land/livestock研究から何が確定し、何が未証明か。
- V111の第3農地遅延のうち、cash shortage、特定支出family、購入後activationの各寄与。
- shadow上、何source-seed blocks・何sourcesで24 decisions以上前倒し可能だったか。
- `BUY_LAND`だけでなく実働化・maintenance・harvest・sale・rejoinまで完全だったか。
- C1を作ったか。作らなければどのgateが不成立だったか。
- 作った場合、raw Safety 0、W→L 0、safe L→W、source/ancestry一般化、実現self revenue、opponent closed-loopのEvidence/Unknown。
- Tomato案を実行しなかったことと、その理由。
- numeric agent作成有無とlabel。production Champion V111を維持または変更しない理由。
- active remote package identityがverifiedか`UNVERIFIED`か。
- Kaggle未提出、kernel未push、slot未変更。
- promotion/Fresh/旧Development seed未使用、今回Development seedの使用状況。

時間配分の目安は、0–30分を開始時保全・hash・seed・source監査、30–100分をcashflow/land-relative activation/Top比較、100–140分をshadow counterfactual・mechanism ranking・gate判断、140–210分を条件付きC1 contract/実装/import/A/A/smoke、210–260分を条件付き旧spent paired評価、260–285分を資格がある場合だけDevelopment開始、285–300分をartifact verificationと日本語報告に使います。前段gate不合格なら後段へ進まず、閾値探索、作物/家畜への横滑り、PSR repair、同じ結果の再集計で時間を埋めないでください。
