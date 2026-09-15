# Kaggriculture 2026-09-14 研究報告

## 最終判断

Local production ChampionはV111を維持する。新候補`v116_mooman_complete`は**REJECT**、Kaggleへ提出しない。候補は旧Development panelの勝敗を大きく改善したが、32 paired contexts中28件で事前登録したraw Safetyを満たさなかった。勝敗でSafety違反を救済せず、Fresh・promotion seedは開いていない。

今回の重要な発見は、V111の低資金8敗戦を「t248の動物購入資金不足」と説明できなかったことと、無改変の公開complete policyには大きな総policy価値があることの2点である。ただし後者は現packageの昇格を意味しない。

## 差分監査と実行条件

開始HEADは`851e970d81db084a712097928a71feb9c0e2b09a`、branchはmain。開始前から存在した未追跡3ファイルは変更せず保全した。既存研究は完了済みで、Python/Kaggle評価jobは動いていなかった。V111 source、Champion archive、kaggle-environments 1.32.7 engineは指定SHA256と一致した。[initial_audit.json](../experiments/research_20260914_lowcash/initial_audit.json)に開始時のtracked file hash、既存JSONL監査、seed利用状況を保存した。

2026-09-14 11:43 JST取得時点の公開Leaderboard #1はMajkel1337、3197.1、submission 56156662だった。自チームの取得可能な公開submissionは56089444（1279.5）と55941525（1275.7）。remote archiveとV111の同一性は不明であり、Ratingへ換算していない。取得原文は[remote/20260914_024331](../experiments/research_20260914_lowcash/remote/20260914_024331/)に保存した。

候補はMIT公開mooman e052aのnative `policy.agent_entry`を無改変で包装したcomplete policyである。初期観測から全719 decisionsを自身で担当し、V111への途中fallbackは持たない。source、license、runtime members、engine、configuration schema、評価coreをfreezeし、root `main.py`を持つresearch-only archiveを作った。candidate archive SHA256は`32d246b6ead176827b0b7691055c5f5d984adf791cce14455ab096390fbcf165`。[candidate_freeze.json](../experiments/research_20260914_lowcash/candidate_freeze.json)と[事前登録](research_20260914_preregistration.md)に条件を保存した。

qeinsteinが実行中に埋込packageを動的importするため、最初のA/A前にruntime isolationを修正した。修正前の確定結果は0件であり、この事実と時刻をfreeze amendmentに記録した。その後V111 A/A、candidate A/Aは各2 pair・両seatでaction/state/final coin一致、720状態完走、Safety差分0。新Controlは前回保存Controlと全32 context・720 stepsの観測（実行時間を除く）・action・reward・statusが一致した。[control_reproduction.json](../experiments/research_20260914_lowcash/control_reproduction.json)

## 低資金8敗戦の会計監査

全32 baseline contextsのt216–360について、元engineのfield actionとmarket lockstepを再実行した。32×144×2 player-stepで現金残差は全て0で、既存market helperのfarm/private/market終状態とも一致した。この照合は標準configuration・対象区間の会計に限定され、mechanics全体の証明ではない。

前回managed候補が非対象だった8件は、mooman/souvik×seed10091011/10091014×両seatである。8件全てがcash≥1500を満たさず、同時にt248のCow2注文そのものが存在しなかった。shed容量、標準configuration、fallback条件は成立していた。t216–360にV111自身のBUY/HIRE履行失敗は0件だった。このため、cash閾値を下げて既存Cow注文を成立させるという介入contractは実装根拠を失った。

mooman/10091011の代表例では、t248–288のself現金は+6,777、相手は+13,870、Melon売却収入は9,048対16,061だった。t216–360のMelon収穫は42対72。V111も資金を増やしており、途中cashの減少だけを過剰投資とは呼べない。収穫・構成・価格・相手応答が同時に異なるため、この差を単一行動へ帰属していない。元データと全context台帳は[economy_summary.json](../experiments/research_20260914_lowcash/economy_summary.json)および[economy/](../experiments/research_20260914_lowcash/economy/)に保存した。

## Full720 paired評価

旧4 source×使用済みDevelopment 4 seeds×両seatの32 paired contextsを、Control/Treatmentとも新規full rerunした。全64 gamesが720状態で完走し、candidateは全32件でstep 0から実行された。Town・市場・相手actionが分岐したpairも総policy効果として含めた。

| Source | V111 W/D/L | v116 W/D/L | L→W | W→L | Δ win-score | 主な限定 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| ggmljs_v16 | 8/0/0 | 8/0/0 | 0 | 0 | 0.00 | marginは改善、2/8のみraw safe |
| mooman_e052a | 2/0/6 | 0/8/0 | 0 | 0 | +0.25 | 自己対戦。V111勝ち2件はW→D |
| qeinstein_moev2 | 2/0/6 | 6/0/2 | 4 | 0 | +0.50 | safe L→Wはseed10091014両seatだけ |
| souvik_v4 | 0/0/8 | 6/0/2 | 6 | 0 | +0.75 | 8/8がraw unsafe |
| 全体 | 12/0/20 | 20/8/4 | 10 | 0 | +0.375 | 4 seed blocks、2 ancestry群 |

自己対戦を除く24 contextsではV111 10/0/14、候補20/0/4、L→W 10、W→L 0、win-score差+0.4167。全体のwhole-seed bootstrap 95%区間は+0.1875～+0.5625、9つのsource±0.2 reweightingで最悪差は+0.275、equal-ancestry差は+0.4167。source別最悪はggmljsの0で悪化はなかった。P10 Δmarginは+1,546、平均Δmarginは+15,253.8だった。

候補は全体平均self coinを7,491.1減らした一方、opponent coinを22,744.9減らした。自己対戦を除くとself +2,212.7、opponent −17,563.1、margin +19,775.8である。主要な価値は単純な自分の増産だけではなく、初期市場と閉ループの相手経済の変化を含む。最初のpublic差から相手action差までのlag中央値は70.5 turns、範囲0～624だった。この総効果を特定のopening注文の因果効果とは呼ばない。

全体の作物診断では、候補はwater deathを146→32、water-death時の残存yieldを113→10、lifespan decay unitsを256→20へ減らした。収穫はWheat、Wool、Melon、Carrot、Eggで増え、MilkとStrawberryで減った。t719の平均shed売却quote proxyはV111 46.4 coin、候補0、未収穫current-yield quote proxyはV111 1,134、候補0。ただしt719にはdecisionが残らないため、V111の未回収分を実現可能な収入として加算していない。[paired_diagnostics.json](../experiments/research_20260914_lowcash/paired_diagnostics.json)、[lifecycle_diagnostics.json](../experiments/research_20260914_lowcash/lifecycle_diagnostics.json)、[inventory_recoverability.json](../experiments/research_20260914_lowcash/inventory_recoverability.json)

## Safetyとoracle

事前登録したraw Safetyで28/32 pairが不合格だった。

| 原因 | pair数 |
| --- | ---: |
| candidate-new all-step field no-op | 18 |
| candidate-new all-step market no-op | 8 |
| candidate-new all-step partial market commit | 4 |
| crop→weed増加 | 10 |
| spawned weed増加 | 3 |
| animal loss増加 | 4 |

候補にはV111よりno-opが少ないcontextも多いが、別contextの削減で新規回帰を相殺しなかった。自然寿命、未収穫yield、水切れも別に記録し、raw判定を緩和していない。runtime/incomplete/negative cashは0だった。

baselineを含むsafe routeだけのoffline oracle改善は2/32 score、平均+0.0625。どちらもqeinstein/seed10091014の両seatで、独立した成功例は1 seed blockである。invalid・Safety違反を除くとselectorを学ぶlibraryとして不足する。従ってselector、供給forecast、新規Development seed、E4、E5へ進まなかった。

## 結論と次の研究

V111敗戦に届くcomplete policyには、このspent panelで強い勝敗価値がある。これは「適応戦略全体が無効」という解釈を明確に否定する。一方、現packageは28/32 Safety不合格で、検証済み相手ancestryは2群、使用seedは4 blocksにすぎない。`v116_mooman_complete`を提出またはproduction化する根拠はない。

次の最優先課題は、complete policyの価値を安全な部品へ分解するか、具体的なno-op・部分約定・作物/動物管理違反を修正した新candidateを事前登録することである。勝敗差の大きさだけを使ったselectorは作らない。安全な複数seed・複数相手の反転が得られた後にだけlive gateを検討する。

最終機械可読判断は[final_decision.json](../experiments/research_20260914_lowcash/final_decision.json)、paired集計は[summary.json](../data/evaluation/research_20260914_lowcash/discovery/summary.json)、artifact検証は[final_artifact_verification.json](../experiments/research_20260914_lowcash/final_artifact_verification.json)に保存した。
