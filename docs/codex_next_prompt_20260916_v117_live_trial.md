# 次スレッド用実行prompt: V117作成と限定live trial

対象repository:

`C:\Users\shiba\Kaggle\pj-kaggriculture`

最大5時間程度で、調査だけで終えず、V111を親にした新しいnumeric agent `V117`を実際に作成し、package、local closed-loop評価、trial判断まで進めてください。V117をproduction Championへ自動昇格させてはいけません。目的は「厳格なpromotion証明」ではなく、「identityが確定しhard Safetyを満たす新agentを固定し、限定live trialから現在fieldの情報を得られる状態を作ること」です。

Trial Gateを通った場合、Kaggleへのsubmission uploadは最大1回まで許可します。ただしkernel pushは禁止です。既存active submission slotの置換は自動実行せず、必要になった時点で現在のslot、置換案、archive hash、local結果を提示してユーザーへ一度確認してください。Kaggleの仕組み上upload自体が既存slotを自動的に置換する場合も、command実行前に確認してください。

このpromptは、完了済みの`docs/codex_next_prompt_20260916_v111_midgame_capacity.md`の後続です。旧Tomato案、PSR repair、P1 route移植、v116/P1提出は行わないでください。

## 0. 今回の重要な変更

以前は、candidate作成、live trial、Champion promotionのgateが同じでした。今回は分離します。

- numeric version作成にpositive upliftや3 ancestryを要求しない。
- live trialにbootstrap 95%下限>0、全source非悪化、Fresh完了を要求しない。
- production Champion昇格には従来の厳格基準を維持する。
- hard Safety、package identity、license、runtime correctnessは緩めない。
- localで小さい不確実な悪化があっても、事前固定したbounded loss budget内ならexploratory live trialを許容する。

最終statusは次を別々に記録してください。

- `RESEARCH_ARTIFACT`
- `LIVE_TRIAL_CANDIDATE`
- `LIVE_TRIAL_SUBMITTED`
- `PRODUCTION_CHAMPION`

V117を作ったことはV111をChampionから外すことを意味しません。

## 1. 最初に読むもの

次の順序で読んでください。

1. `AGENTS.md`とgame処理順、market逐次commit、land、crop/animal lifecycle、Town、handsに必要な`README.md`。
2. `docs/research_20260916_program_status_and_live_trial_strategy.md`。
3. `docs/agent_status_registry_20260916.json`。
4. `docs/research_20260916_v111_midgame_capacity_report.md`とpreregistration。
5. `experiments/research_20260916_v111_midgame_capacity/final_decision.json`、`shadow_capital_counterfactual.json`、`opportunity_cost_by_spend_family.json`、`mechanism_ranking.json`、`mechanism_attribution.json`、`current_top_capacity_comparison.json`。
6. 必要な範囲の`midgame_cashflow_ledger.json`と`land_relative_activation_timeline.json`。巨大なので最初から全文をcontextへ展開せず、scriptまたはqueryで対象context/stepだけ読む。
7. `docs/research_20260916_rethought_next_steps.md`、`docs/research_20260915_router_mechanism_report.md`、`docs/research_20260914_clean_psr_report.md`、`docs/research_20260914_report.md`、`docs/research_20260912_continuation_report.md`。
8. `agents/v111/`の全runtime file、manifest、metadata、READMEと、呼び出されるV110/V109 executor。
9. `agents/v112/`、`docs/v112_design_report.md`、`artifacts/submissions/v112.tar.gz`が存在する場合のhash。V112はfallback calibrationでありV117の親ではない。
10. `agents/v113/`、`docs/v113_live_e6_posthoc_addendum.md`、`docs/v111_v113_live_and_expanded_final_assessment.md`。
11. `scripts/evaluation/runner.py`、`safety.py`、`statistics.py`、`divergence.py`、`lifecycle.py`、package script、submission関連script。
12. repository全体のseed ledger、opponent/source manifest、`experiments/independent_gold_pool/`、`artifacts/opponent_pool/candidates/`。

## 2. 開始時保全

experiment IDは実行日のJST/UTC日付を使い、原則`research_YYYYMMDD_v117_live_trial`とします。開始直後に次を保存してください。

- UTC/JST開始時刻、5時間後のdeadline。
- branch、HEAD、`git status --short --ignore-submodules=all`。
- 既存dirty差分とユーザー作成fileを保全し、無関係な変更を戻さない。
- 本prompt、上記必読file、V111、V112、runner/evaluator、engine/configuration、control/opponent/replayのSHA-256。
- 実行中のPython/Kaggle processとcommand line。
- repository全体のseed履歴。structured useとfree-text mentionを分ける。
- active remote submissionと既知submissionのread-only一覧、可能な範囲の提出時刻、rating、active状態。remote package identityはhashで証明できない限り`UNVERIFIED`。
- preregistration、candidate contract、Trial Gate、fallback ruleのhash。W/D/Lを見る前にfreezeする。

既存の未追跡midgame研究や他のdirty fileを上書きしないでください。

## 3. 固定する事実

都合よく再定義しないでください。

### 3.1 agent/live履歴

- production Championとclean controlはV111。
- known V111 submissions 55909167/55912910の保存ratingは1688.6/1730.7。
- V113はsubmission 55933145でlive約1675、58 public episodes 44W/0D/14Lだった。ただしgateの因果効果は未解決で、paired Safety regressionがある。
- V112は公開Kaito v27 Apache-2.0 exact artifactで、main SHA-256は`f48c21166eac68d1b05a401f04f94a2eb6154e65415af64893672365ff33c7b8`、upstream表示scoreは3090.1。自チームによる同hashのcurrent-field ratingは未検証。
- active remote 56089444はlocal V109/V110/V111/V113と99.53%近いがexact package identityは`UNVERIFIED`。
- V114/V114r1、V115p群、v116_mooman_complete、P1はresearch-only。v116/P1を提出しない。

### 3.2 PSR/router

- P1 fullはV111比+0.375、A0 fixed-routeは+0.3125。P1 upliftの83.33%がfixed total policyに残った。
- router固有差は+0.0625、1 block/1 source/1 ancestry。
- P1/A0/A1/A2はraw Safety 32/32、P1系はW→L 2。transitive route provenance/licenseも未確認。
- P1/v116の高い局所成績は「異なるtotal policyのupside」を示すが、具体routeをV117へコピーする許可ではない。

### 3.3 land/cash

- current Top第3区画中央値はstep 209、歴史的V111は概ね253–266。
- V111 spent 32 contextsはstep 209のcash中央値55、cash>=2000は0/32。
- post-unlock最初のproductive action lagはV111中央値2、Top中央値2.5。購入後の長い放置がprimary gapではない。
- COW購入だけを算術上延期すると32/32 contexts、16/16 blocks、4/4 sourcesで2011へ到達し、shadow前倒し中央値91 decisions。
- これは算術上界であり、paired upliftではない。
- land前に配置されたCowは合計232、関連PICKUP 174、PLACE 232、FEED 848、CARE 856、COLLECT_FERTILIZER 616。lost milk/fertilizer、worker debt、catch-upはUnknown。

### 3.4 除外する方向

- Tomato/Carrot/Goose/Sheep、terminal saleをV117へ同時追加しない。
- `BUY_LAND`だけを無条件に早めない。
- opponent/source/seed/name/episode/submission IDや離散identity signatureを使わない。
- Top/P1/v116のroute、position、portfolio、action列、threshold、blob/treeを転記しない。
- future RNG、future shop/price、opponent private stateを使わない。
- invalid actionを単にPASSへ隠すsanitizer、汎用rule fallbackを作らない。
- outcomeを見てreserve、開始step、cow数、tile数、thresholdを探索しない。

## 4. 必須deliverable

今回、前段の診断だけを理由にnumeric agentを作らない終了は禁止します。最低限、`agents/v117/`を作り、以下を含めてください。

- `main.py`
- `metadata.json`
- `README.md`
- `CHANGELOG.md`
- `submission_manifest.json`
- 必要なV111-owned runtime file
- `RESEARCH_STATUS.json`
- source/package SHA-256とlicense/notice

V117がhard Safetyを通らない場合もdirectoryは`RESEARCH_ARTIFACT_UNSAFE_DO_NOT_SUBMIT`として残し、first failureとexact diffを保存してください。通った場合は`LIVE_TRIAL_CANDIDATE`とします。どちらの場合もproduction ChampionはV111です。

## 5. V117 primary contract

名称は`midgame_land_cash_reserve_live_trial`とします。親はV111だけです。

### 5.1 発火境界

runtime inputはcurrent own/private state、current/past public observation、configuration、V111のcurrent proposed actionだけです。次を全てcurrent stateから確認します。

- 標準configuration。
- 自分はちょうど2 quadrantsをunlock済みで、次のland costが2,000。
- V111 current actionに実際の`BUY_ANIMAL COW` orderが存在する。
- same-day urgent FEED/WATER/HARVEST、Wheat feed在庫、shed capacity、market order slots、worker/handsをpreflightできる。
- candidate固有のcommit前はbaseline action/stateと一致する。

source、seed、opponent identity、固定replay step表を発火条件にしません。stepはlogとdeadlineに使ってよいですが、既知contextを識別するlookup tableにしてはいけません。

### 5.2 capital debt

- 変更する支出familyは`BUY_ANIMAL:COW`だけ。
- V111が現在要求したCOW orderだけを延期できる。将来orderを予測して先に操作しない。
- 延期した数量、cost、元order index、expected pickup/place taskをFIFO debtとして保存する。
- land 2,000、activation reserve、maintenance reserveの内訳をengine/configurationとcurrent stateからfreezeする。
- land purchaseは逐次market orderとしてcashとslotを再確認し、前段SELLを未実現incomeとして無条件に数えない。

### 5.3 activation

- `BUY_LAND`成功とunlock quadrantをstateで確認するまでfield activationへ進まない。
- 新landで使うasset familyはV111自身にあるもの一つに固定し、新portfolio仮説を足さない。
- tile、actor、移動、seed/structure、WATER/FEED、HARVEST、carry/drop、SELLをstate machineで追う。
- 既存farmのurgent maintenanceを新land taskより優先する。
- option actorを追加HIREする場合、V111へ渡すhands/inventory mappingとengineへ返すaction lengthを明示し、actor index driftをtestする。
- new-land harvestとsaleをfungible shed全体のsaleから区別できるtrackingを持つ。厳密に区別不能ならその限界を記録する。

### 5.4 catch-up/rejoin

- 延期Cowはcash、pasture、shed、worker、remaining horizonが揃った時だけ再購入・配置する。
- commit後にCow debtをsilent cancelしない。再購入できない場合の明示的cancel conditionとlost-production accountingをcontractへ事前登録する。
- V111へのrejoinはfixed stepではなく、land、option tile、inventory/carry、Cow debt、actor ownership、urgent tasksが定めるstateで行う。
- candidateが一部だけcommitして壊れた場合はhard failureであり、勝敗で救済しない。

## 6. 事前fallback contract

Primaryのstatic preflightまたは発火smokeで、W/D/Lを見る前にcomplete catch-up/rejoinが構築不能と分かった場合だけ、`late_land_order_resequence`へ一度だけ縮退できます。結果を見てPrimaryとfallbackを選んではいけません。

Fallbackは次だけを行います。

- V111 current actionが元々`SELL MELON`と`BUY_ANIMAL COW 2`を含むlate transactionである。
- current sequential order simulationで、実現可能な前段order後にland 2,000と元COW order、必要maintenance reserveを全て支払える。
- market slot上限内で`BUY_LAND`を同turnへ追加または移動する。
- 元COW order、pickup、pasture build、place、feedを保持する。
- 後でV111が出す重複`BUY_LAND`だけを、実際にlandが既unlockであることを確認して除く。
- land purchaseからpasture build/place/FEEDまたはV111既存productive actionまでをcontract logへ残す。

これは36–55 decisions gapの解決とは呼ばず、小さなordering/identity live trialとします。4 decisions程度の前倒しでもnumeric artifactにはできますが、Primary mechanismの成功件数へ数えません。

Primaryもfallbackもhard Safetyを満たさない場合、V117はunsafe research artifactとして終了し、提出対象をV112 fallbackへ切り替えます。

## 7. package/import/A/A/smoke

W/D/L集計前に次を行います。

1. package import isolation、最後のcallable、両seat、step 0 reset、same-process連続episode、fresh process。
2. V111 A/AとV117 A/Aを同じ固定contextで独立load反復し、action/state/final coin一致。
3. non-trigger contextを最低1つ両seatで確認し、V111と全action/state一致。
4. commit contextを最低2 sourceで両seatsmokeし、720 states/719 decisionsを完走。
5. runtime/timeout/incomplete/negative cash/schema/missing hands/delivery、market order逐次commitを勝敗より先に集計。
6. animal loss、crop-to-weedをwater death/lifespan/terminal intentional decayに分離し、candidate-new first eventを表示。
7. all-step silent field/market no-op、partial commit、oversized SELL、failed BUY/HIREを表示。
8. land、activation、harvest/carry/sale、Cow debt、rejoinをtraceで確認。

commit前safe cancelはdelivery funnelとして数え、hard Safetyとは分けます。commit後のpartial execution、動植物喪失、maintenance欠落はhard Safetyです。

## 8. old-spent engineering panel

smoke合格後、旧spent 4 sources × seeds `10091011–10091014` × 両seatの32 paired contextsでV111と比較します。

これはtraining/engineering panelであり、promotion/generalization証拠ではありません。目的は次です。

- interventionが複数sourceで実際にcommitするか。
- hard Safetyが0か。
- task debt、land、activation、sale、rejoinが完走するか。
- catastrophic regressionがないか。

この結果を見てthreshold、reserve、Cow数、tile数を調整しません。一つのfixed implementationだけを評価します。hard Safetyが1件でもあればV117を提出しません。

## 9. frozen confirmation panel

old-spentでhard Safety 0だった場合だけ、新しいconfirmationを一つ開きます。以前の16-block promotion型Developmentとは目的が違うlive-trial qualification panelです。

- repository全体で未使用なら`10091521–10091524`の4 seed blocksを一括登録する。
- 一つでも使用済みなら、結果を見る前に次の未使用連続4 blocksを機械的に選ぶ。
- 旧4 executable sources、全4 seeds、両seat、full720を全件実行する。
- candidate source/package hashをfreezeし、途中修正した場合は全件無効にして新hashを別experimentとする。
- 4 blocksをsubset報告せず、全32 paired contexts完了を要求する。
- `10091525–10091536`、promotion `10091101–10091112`、Fresh `10091901–10091912`、旧予約`10091421–10091436`は開かない。

control再利用はengine/configuration/opponent/seed/seat/control/evaluator hash一致と、`remainingOverageTime`以外のstate再現がある場合だけです。pair key、JSONL flush、duplicate/partial監査を行います。

## 10. Trial Gate

V117を`LIVE_TRIAL_CANDIDATE`にできる条件は次です。

### 10.1 hard gate

- source/license/package/manifest/hash監査合格。
- forbidden feature/identity proxyなし。
- runtime error、timeout、incomplete、negative cash、malformed action、missing hands 0。
- candidate-new non-terminal animal escape、水切れcrop death、required maintenance loss、broken partial transaction 0。
- commit後のland/activation/debt/rejoin contract failure 0。
- non-trigger contextはV111と完全一致。

### 10.2 efficacy loss budget

confirmation panelで次を満たします。

- V117−V111 win-score差`>= -0.0625`。
- W→L source-seed blocksはL→W blocksより最大1 block多いまで。
- 各sourceのwin-score差`>= -0.25`。
- intervention commitが2 sources以上、4 source-seed blocks以上。
- Primaryの場合はearlier land、productive action、harvest/saleまたは明示的debt resolutionが複数blockで実測される。
- Fallbackの場合は同turn land+COW transactionと重複land除去が複数blockで実測される。

Trial Gateではbootstrap 95%下限>0、全source非悪化、W→L 0、3 ancestry、Freshを要求しません。代わりに結果を`EXPLORATORY_E6_REQUIRED`と明示し、Champion昇格を禁止します。

## 11. V112 fallback

V117がhard gateまたはloss budgetを通らない場合、unsafe/strongly-regressive V117を提出してはいけません。最大1回のupload枠をV112 exact calibrationに使えるか監査します。

次を全て確認してください。

- `agents/v112/main.py` SHA-256が`f48c21166eac68d1b05a401f04f94a2eb6154e65415af64893672365ff33c7b8`。
- Apache-2.0 source/noticeが保存済み取得物と一致。
- archive root、entrypoint、stdlib dependency、両seat、same/fresh process、720 statesが合格。
- current self submission historyに同hashを確実に帰属できる提出がない。推測だけなら`UNKNOWN`として重複riskを報告する。
- V112をV117やV111-derived improvementと呼ばず、external exact live calibrationとする。

V112のupstream 3090.1は現在自チームratingの保証ではありません。提出する場合もproduction ChampionはV111です。

## 12. submission手順

Trial Gate通過後、次を行います。

1. exact archiveを再生成し、SHA-256、file list、source hash、license、smoke resultをfreeze。
2. current submission slotsをread-only取得。
3. uploadがslotを置換しないことが確認できる場合、最大1回だけKaggle competition submissionを実行してよい。
4. uploadまたはactivationが既存slotを置換する場合、実行前にユーザー確認を求める。確認なしに変更しない。
5. kernel pushはしない。
6. command、message、UTC/JST時刻、CLI raw response、submission ID、archive SHA-256を保存。
7. upload失敗時、archiveを変更して繰り返し提出しない。原因を診断し、同一hashの安全なretryだけを提案する。

live matchが開始した場合、最大5時間内で取れる範囲をread-only監視し、episode数、W/D/L、rating trajectory、first failuresを保存します。少数matchを因果効果やfinal strengthと呼びません。時間内に十分なmatchがなければmonitor/resume commandを残します。

## 13. 必須集計

V117について最低限次を保存・報告してください。

- overall/source/ancestry別W/D/L、win-score、margin mean/median/P10。
- L→W、W→L、D→W、W→D、L→D、D→Lとsource-seed block数。
- trigger/request/commit/safe-cancel/partial/failure funnel。
- land unlock stepと前倒し、first productive action/harvest/sale lag。
- pre/post cash、延期COW数量/cost、activation/maintenance reserve。
- Cow debtの再購入、pickup/place、feed/care、lost milk/fertilizer proxy。
- productive/empty/weed tiles、worker/hands、travel/action utilization。
- self/opponent coin差、market inventory/price/Town、first opponent responseとlag。
- opponent coin低下を単一actionの因果効果と呼ばない。
- raw Safetyとcandidate-new Safetyを分離。
- t672/t719 shed/carry/unharvested proxy。残りdecisionがないstockを実現収入にしない。
- old-spentはengineering、confirmationはlive-trial qualification、liveはE6 observationであり、promotion evidenceではないこと。

## 14. 必須artifact

最低限、次を作成してください。

- `docs/research_YYYYMMDD_v117_live_trial_preregistration.md`
- `docs/research_YYYYMMDD_v117_live_trial_report.md`
- `experiments/research_YYYYMMDD_v117_live_trial/manifest.json`
- `initial_audit.json`
- `seed_ledger.json`
- `input_artifact_verification.json`
- `candidate_contract.json`
- `candidate_integrity.json`
- `trial_gate.json`
- `fallback_decision.json`
- `source_and_license_inventory.json`
- `package_manifest.json`
- `package_verification.json`
- `aa_results.json`
- `smoke_results.json`
- `pairs.jsonl`、`runs.jsonl`、`summary.json`、replays、progress
- `safety_and_delivery.json`
- `mechanism_attribution.json`
- `remote_identity_and_slots.json`
- `submission_decision.json`
- submission時の`submission_receipt.json`
- `final_decision.json`
- `final_artifact_manifest.json`
- `final_artifact_verification.json`
- exact reproduction、same-hash resume、monitor command
- 更新したmachine-readable agent registry

新規・変更Pythonには`py_compile`とruffを実行します。evaluation coreの既存test、candidate import/reset/isolation、A/A、manifest hash、JSONL duplicate/partialを検証してください。evaluation coreを変更した場合は前後互換性とV111 control reproductionを明記します。

## 15. 最終判断label

V117について次のいずれかを使います。

- `RESEARCH_ARTIFACT_UNSAFE_DO_NOT_SUBMIT`
- `RESEARCH_ARTIFACT_STRONGLY_REGRESSIVE`
- `LIVE_TRIAL_CANDIDATE_NOT_SUBMITTED_SLOT_APPROVAL_REQUIRED`
- `LIVE_TRIAL_SUBMITTED_EXPLORATORY`
- `LIVE_TRIAL_CANDIDATE_UPLOAD_FAILED`

V112 fallbackについて必要なら次を使います。

- `V112_EXACT_CALIBRATION_READY`
- `V112_EXACT_CALIBRATION_SUBMITTED`
- `V112_IDENTITY_OR_LICENSE_BLOCKED`

今回`PROMOTE`や`PRODUCTION_CHAMPION_V117`は使いません。V111はclean Championとして維持します。

## 16. 最終回答

日本語で、少なくとも次を明記してください。

- Git開始状態と既存dirty fileを保全したこと。
- V117を実際に作成したか、version/status/hash。
- PrimaryとfallbackのどちらをW/D/Lを見る前に選んだか、その理由。
- landだけでなくactivation、maintenance、harvest/sale、Cow debt、rejoinが完了したか。
- hard Safety、delivery、runtime、A/A、non-trigger fidelity。
- old-spentとconfirmationのW/D/L、transition、loss budget判定。
- V117を提出したか。していない場合はSafety、regression、slot approvalのどれが理由か。
- V112 fallbackを使ったか、exact hash/license、提出有無。
- submission ID、archive hash、slot変更有無、kernel pushなし。
- live evidenceがあればepisode数と観測結果。ただし因果主張しない。
- production Champion V111を維持したこと。
- Tomato/Carrot/livestock追加、PSR/v116移植を行っていないこと。
- 使用seedと未使用のpromotion/Fresh/reserved ranges。
- GitHubへ保存すべきexact file一覧と、巨大artifactのLFS状態。

時間配分の目安は、0–25分を開始時保全・identity/hash/seed監査、25–100分をV111 routeとactor mappingの実装調査、100–190分をV117実装・unit/import/A/A、190–235分をsmoke・old-spent、235–270分を条件付きconfirmation、270–285分をpackage/Trial Gate/条件付きupload、285–300分をartifact verificationと日本語報告に使います。
