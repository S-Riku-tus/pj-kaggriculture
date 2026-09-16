# V117限定live-trial qualification報告 — 2026-09-16

## 結論

V111だけを親とするnumeric agent `V117`（version `117.0.0`）を実装し、package、A/A、smoke、old-spent、frozen confirmationまで完了した。最終labelは`LIVE_TRIAL_CANDIDATE_NOT_SUBMITTED_SLOT_APPROVAL_REQUIRED`である。V117はTrial Gateのhard gateとloss budgetを通過したが、これは`EXPLORATORY_E6_REQUIRED`なlive-trial資格であり、production promotion証拠ではない。production ChampionはV111のまま維持する。

- V117 source SHA-256: `2772e5fa31476db3dc4f015d4a8cf11bf7c48d75ab617a9bd782bb4c7aa696a8`
- deterministic final archive: `artifacts/submissions/v117.tar.gz`
- final archive SHA-256: `8f2c7e8446ce1295fe519cf9f29b87b01a0816863b952d94f1db80ed1432dbfa`
- archive entry-content SHA-256: `f907d9343d0940ff4e839a8cae771cff9c19f2c99b9fb325676dab3b64a7231c`
- production Champion: V111 (`699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660`)

Kaggle uploadは0回、submission IDはなし、slot変更なし、kernel pushなしである。CLIが認証を要求しcurrent slot一覧を取得できず、prior-known active submission `56089444`を含む既存slotの自動置換を否定できない。したがって、archive hashとlocal結果を固定した上で、upload command実行前の一度のユーザー確認待ちとした。

## 開始時保全

開始時刻はUTC `2026-09-16T00:42:12.3388529Z`、JST `2026-09-16T09:42:12.4710851+09:00`、5時間deadlineはUTC `05:42:12.3388529Z`／JST `14:42:12.4710851+09:00`。branch `main`、HEAD `ab349ef5dd815ed54a314ef0591bca28502be134`、`git status --short --ignore-submodules=all`はcleanだった。既存dirty fileはなく、その後も無関係な既存fileを復元・削除・上書きしていない。

開始時のPython/Kaggle processは0件。必読input、prompt、V111/V112、engine/configuration、evaluation core、4 executable opponentsをSHA-256で固定した。remote queryはread-onlyだけを試み、authentication requiredで終了した。remote package identityはhash証明がないため`UNVERIFIED`のままとした。

repository全体のseed ledgerではstructured execution useとfree-text mentionを分離した。`10091521–10091524`は実行未使用だったため、結果を見る前に4 blocksを一括固定した。

## Primaryからfallbackへの事前縮退

W/D/Lを見る前にPrimaryを不採用とし、一度だけ許可されたfallback `late_land_order_resequence`を選んだ。Primary Cow-debt案は、既存auditでmaintenance-to-sale/rejoinのcomplete contractが0、land前Cow配置232、関連PICKUP 174、PLACE 232、FEED 848、CARE 856、COLLECT_FERTILIZER 616であり、static preflight時点でcomplete catch-up/rejoinを固定できなかったためである。W/D/Lを使った選択ではない。

Fallbackはstep/seed/source/opponent identityを見ない。current V111 actionが`SELL MELON 6`の後に`BUY_ANIMAL COW 2`を含み、exactly 2 quadrants、standard configuration、order slot、same-turn shed、逐次価格、cash、Wheat maintenanceをpreflightでき、Cow2＋land2000＋maintenance＋V111由来500 coin reserveを払える場合だけ、Cow order直後へ`BUY_LAND`を追加する。land unlockをstateで確認した後だけ、後のV111 duplicate `BUY_LAND`を1件除く。Cow order、field action、hands、pickup、pasture build、place、feedは保持する。

このfallbackはCowを延期しないのでCow debtは作られない。従ってdebtのsilent cancelもない。Primary mechanism成功件数は0であり、4 decisionsの小さなordering/identity trialとしてのみ扱う。

## Packageとruntime

archiveはroot `main.py`とV111-owned runtime chainを含む18 files。V117 wrapperはstdlibだけを使い、source/license/notice inventoryを保存した。package import isolation、最後のcallable `agent`、両seat、step 0 reset、independent import、fresh processに合格した。

最終deterministic archiveについて、両seatそれぞれ同一module objectで2 episode連続実行し、各720 states／719 decisions、final status `DONE/DONE`、negative cashなし、hands shape一致、repeat間のaction/state/final coin一致を確認した。package runtimeのminimum cashは2。評価core既存test `tests/test_champion_challenger_evaluation.py`は10件全合格。新規・変更Pythonは`py_compile`とruffに合格した。

最初のqualification archive SHAは`3f77d4860a773852a77b2e0c1ae4f023bcf08f91e6590ad6eb303e6243a8e76b`だった。Trial Gate後の指定された再packageで、既存packagerのgzip header timestampだけにより外側hashが変わることを検出した。entry names/contentとV117 sourceは不変である。packagerをgzip `mtime=0`へ修正し、final hash `8f2c7e...2dbfa`を2回連続でbyte-for-byte再現した。qualification/finalの区別とcanonical entry-content hashは`package_verification.json`へ保存した。

## A/Aとsmoke

V111 A/A、V117 A/Aはいずれも固定contextの両seatを独立loadし、720 statesを完走してaction/state/final coin一致、candidate-new Safety 0だった。

non-trigger smokeの2/2 contextsは、`remainingOverageTime`だけを除いた全action/stateでV111と完全一致した。commit smokeは2 sources×両seatの4/4 contextsで以下を確認した。

- step 248にMelon売却＋Cow2＋landを逐次commit
- step 249にCowとthird landをstate確認
- V111 controlのland step 253に対して4 decisions前倒し
- step 252で後続duplicate landを除去し、V111へrejoin
- step 255にnew quadrantでV111既存の`BUILD_PASTURE`
- Cow pickup/place/feed continuation完了
- runtime/timeout/incomplete/negative cash/schema/missing hands/delivery/contract failure 0

## old-spent engineering panel

旧4 sources×`10091011–10091014`×両seat、32 paired contextsをfull720で全件実行した。

| arm | W/D/L | win-score | margin mean | median | P10 |
|---|---:|---:|---:|---:|---:|
| V111 | 12/0/20 | 0.375 | -5784.594 | -3510.5 | -23091.3 |
| V117 | 12/0/20 | 0.375 | -5784.594 | -3510.5 | -23091.3 |

差は0.000。context transitionは12 W→W、20 L→Lで、L→W/W→L/D→W/W→D/L→D/D→Lは全て0。source-seed blockは6 W→W、10 L→L。各sourceのwin-score差も0だった。これはengineering panelでありpromotion/generalization証拠ではない。

22 contexts、11 source-seed blocks、全4 sourcesでcommitした。全22でsame-turn land+COW、land 4 decisions前倒し、duplicate land除去、Cow継続、rejoinを完了。残る10 non-triggerは完全一致した。candidate-new hard Safety、contract failure、partial transaction、runtime failureは全て0。

## frozen confirmation panel

未使用だった`10091521–10091524`を4 seeds一括で開き、旧4 sources×両seat、32 paired contextsをfull720で完了した。途中修正、subset報告、partial row、duplicate pair keyはない。

| arm | W/D/L | win-score | margin mean | median | P10 |
|---|---:|---:|---:|---:|---:|
| V111 | 12/0/20 | 0.375 | -7717.375 | -11644.5 | -26450.5 |
| V117 | 12/0/20 | 0.375 | -7717.375 | -11644.5 | -26450.5 |

差は0.000。context transitionは12 W→W、20 L→Lだけで、指定された6方向transitionは全て0。source-seed blockは6 W→W、10 L→L、W→L 0、L→W 0。source別はggmljs 8/0/0、mooman 0/0/8、qeinstein 0/0/8、souvik 4/0/4で、V117−V111差は全source 0.000。ancestry別も同一source groupingで差0.000だった。

12 contexts、6 source-seed blocks、全4 sourcesでcommitした。全12でsame-turn land+COW、duplicate land除去、rejoinを確認。20 non-triggerは完全一致した。従ってoverall `>= -0.0625`、W→L block excess `<=1`、各source `>=-0.25`、2 sources／4 blocks以上、fallback mediatorの全条件を満たした。

## Mechanism、Safety、delivery

confirmation commit時のpre-cashは1777–2457、projected post land+COW cashは535–1215。activation reserveは0、maintenance reserveは0で、current Wheatがurgent unfed animalsを満たした。V111由来500 coin reserveは保持した。market orderは逐次simulateし、未実現SELL incomeを先に自由cashとして扱っていない。

land unlockはcontrol step 253、V117 step 249で中央値4 decisions前倒し。ただしfirst productive actionは両armとも絶対step 255であり、landからのlagはcontrol 2、V117 6。first new-land harvestも同じ絶対stepで、land-relative lagはcontrol 92、V117 96。これはactivation自体の前倒しではなく、小さいordering/identity差である。shed-wide saleはfungibleでnew land由来に厳密帰属できない。この限界をartifactへ明記した。

FallbackはCow debtを作らず、元Cow2 orderを保持した。confirmationのpickup/placeは各24、Cow由来milk harvest／fertilizer collect／requested sale proxyのpaired deltaは全て0。candidate-new lost milk/fertilizer proxyは0。worker/hands、travel/action utilization、productive/empty/weed tilesはrejoin後に一致した。

raw SafetyはV111から継承したno-op/oversized order/crop lifecycleを隠していない。confirmation rawでは両armともanimal loss 0、water-death events 118、lifespan-end 648、empty random weed 12、water-death current yield 86、lifespan decay current units 200だった。candidate-new deltaはこれら全て0で、candidate-new first eventは`null`。raw silent field/market no-op、partial order、failed purchase、oversized sellも両armで同数、candidate-new delta 0である。

t672/t719ではcash、productive/empty/weed tiles、workers/hands、shed、carry、unharvested-current-units proxyのpaired deltaが全commit contextで0。t719 stockは残りdecisionがないため実現収入と数えていない。market inventory、price、Townのfirst differenceは0 contexts。opponent first action responseも0 contextsだった。opponent coin低下を単一actionの因果効果とは呼ばない。

delivery funnelはold-spentでrequest/commit/rejoin 22/22/22、confirmationで12/12/12、safe cancel 0、post-commit partial/failure 0。全評価でruntime error、timeout、incomplete、negative cash、malformed action、missing hands、candidate-new non-terminal animal escape、required maintenance loss、candidate-new water death、broken partial transaction、land/debt/rejoin failureは0。

## Trial Gateとsubmission

hard gate合格、confirmation loss budget合格。labelは`EXPLORATORY_E6_REQUIRED`で、bootstrap 95%下限、全source非悪化、3 ancestry、Freshは要求も実行もしていない。V117をproduction Championへ昇格していない。

uploadは行っていない。prior-known active slotはsubmission `56089444`だがcurrent slot listingは認証不足で取得不能、exact package identityも`UNVERIFIED`。slot replacementを否定できないため、次の1回だけのV117 exploratory upload案はユーザー確認待ちである。確認なしにcommandを実行しない。submission receiptとlive episodeは存在しない。live evidenceは0 episodesで、因果主張もない。

V112 fallbackはV117がgateを通ったため使っていない。V112 main hash `f48c21166eac68d1b05a401f04f94a2eb6154e65415af64893672365ff33c7b8`とApache-2.0 noticeを監査したが、同hashの自team提出帰属は`UNKNOWN`。V112 uploadも0回である。

## Seeds

実行したpaired evaluation seedはold-spent `10091011–10091014`とconfirmation `10091521–10091524`。A/A/smoke/package validationは旧seedを再利用し、新しい証拠seedとして数えていない。以下は開いていない。

- confirmation残り `10091525–10091536`
- promotion `10091101–10091112`
- Fresh `10091901–10091912`
- prior reserved `10091421–10091436`

## GitHub保存対象とLFS

保存対象のexact file-by-file list、size、SHA-256、LFS attributeは`final_artifact_manifest.json`を正本とする。論理的な保存範囲は次である。

- `agents/v117/`全file
- 本preregistration/reportと`docs/agent_status_registry_20260916.json`
- `scripts/research_20260916_v117_live_trial.py`、`scripts/analyze_20260916_v117_live_trial.py`、`scripts/validate_v117_package_runtime.py`、deterministic化した`scripts/package_submission.py`
- `experiments/research_20260916_v117_live_trial/`全file（plans、progress、pairs、runs、summaries、Safety、mechanism、replays、final verificationを含む）
- `.gitattributes`のV117 replay LFS rule

experiment directoryは約92.3 MB、replayは個別最大約0.60 MBだが総量が大きい。そのため`experiments/research_20260916_v117_live_trial/replays/**/*.json.gz`をLFS対象に設定した。現時点ではuntrackedで未stageなので、`git add`時にLFS pointerへ変換される。既存V111の2巨大JSONも従来どおりLFS管理である。

final archive `artifacts/submissions/v117.tar.gz`は119,759 bytesで、repositoryの`.gitignore`対象である。GitHubへ厳密archiveを残す場合はrelease assetまたは明示的force-addが必要であり、通常commit対象の再現commandとexpected hashは`reproduction_commands.json`に保存した。ignored `data/submissions/builds/`のtimestamped build receiptsは再現に必須ではない。

Tomato/Carrot/Goose/Sheep、terminal saleの追加、PSR/P1/v116 route・threshold・blob・tree・action列の移植、v116/P1提出は行っていない。
