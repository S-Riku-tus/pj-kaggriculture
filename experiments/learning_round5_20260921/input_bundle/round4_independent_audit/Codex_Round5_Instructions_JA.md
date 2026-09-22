# Codex実装依頼：Round5 — 収益回収までつながる独立学習policy

この文書全体を、以前の会話を知らないCodexへ渡す。提案書を増やすだけではなく、ローカルの実ソースを読み、下記の失敗を再現・修正し、技能と経済の実測結果および実物を含む引継ぎを作ること。

## 0. 目的・制約

対象はKaggle Kaggriculture。ユーザーはv109〜v125、learning Round1〜4を開発してきた。最近のオンライン提出はユーザー報告ではレート1600前後であり、目標はまず2000、その後3000以上である。今回Round4ではKaggle提出も新規オンラインレートも取得していない。ゲーム内資金3,000とレート3,000を混同しない。

学習研究を少数proxyの平均差分が負というだけで取りやめない。独立した一貫した上位模倣policyを主経路としてよい。C0のPASSへの差込みだけに戻す必要はない。ただし既知の実行不成立や提出不具合を残したまま提出してよいという意味ではない。

C0・旧model・旧replay・旧判定書・holdout台帳は上書きしない。開始時のgit status/diffを保存し、既存の未コミット変更を壊さない。Round5用の新しいディレクトリまたはbranchに実装する。既観測条件を未使用holdoutへ戻さない。

ユーザー許可なしにKaggleへ提出しない。新たな有料API・クラウド・大規模GPUを使わない。現マシンで動く小さな実験から始める。実行したことと未実行を区別し、コードを書いただけでTRAINED、helperを通しただけでskill completeとしない。

## 1. 最初に読む入力

- `learning_round4_20260921.zip`
- `Kaggriculture_Round4_Independent_Audit_JA.md`
- 同梱の`audit_round4.py`、`audit_summary.json`
- `round5_regression_fixtures.json`
- `duplicate_harvests.json`、`animal_lifecycle.json`、`animal_harvest_opportunities.json`
- `paired_decomposition.json`、`replay_summary.csv`
- Round4入力中のRound3独立監査と`Codex_Round4_Instructions_JA.md`

入力Round4 ZIPのSHA-256：`ae89c1fb503af470b3b670b810c3344f065cabd9587730316bd6d84998042572`。

## 2. P0：今回欠落した実物を回収し、版を固定する

独立監査で確認できたのは16保存リプレイと報告書である。Round4の新規agentソース、学習/評価スクリプト、テスト、旧BC heads、新checkpoint、両提出tar.gzはZIPに同梱されていなかった。

`EVIDENCE_HASHES.json`の23項目のうち存在18項目はhash一致、5項目は欠落。欠落5項目は最終tar.gz2本、`strategy_model.json`、`evaluation.py`、`test_learning_round4.py`。他の新ソースも名前だけのmanifestになっている。

ローカルに実物があるはずなので確認し、報告hashと照合する。新規ファイルがuntrackedで`git diff`に出ないことへ注意する。差分だけで済ませず、明示manifestで実ファイルを収集する。

Round4報告上の参照hash：
- learned archive：`664b71ef17764fcfd526fb7b2eae16b0651bec4bdb943e3c42c2ab97ea96b340`
- rule archive：`6cb324f496ca216a1bd309a8cc3ae1db6eac9c2e9a9973f0325c06dcef454b3e`
- new strategy checkpoint：`0276229affaf6e8b28ca374f19c926d9208b136ac108e60ea9af65f1cd5a65b2`
- environment report engine hash：`bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`
- package version reported：`kaggle-environments==1.32.7`

ユーザーが過去に実際に提出成功した参照は `learning_next_20260921_b_learned_fixed_v3.tar.gz`、SHA-256 `f1aede2a9f4a8ad0b8f3b3cd41d1f49708b713ca1cbc4221df472dcba1201105`。これは提出互換性の参照でありC0や今回の独立BCと同じ戦略ではない。元版/fixed/fixed_v2を再び提出互換基準にしない。新しい正常版は許容する。

過去のloader問題は、`get_last_callable`がagent以外の末尾関数を選ぶ、empty globalsに`__name__`や`__file__`がない、任意cwdから相対import/資産読込が失敗する、などである。最後の関数がagentかを実archiveで確認する。

## 3. 独立監査をまず再現する

```bash
python audit_round4.py learning_round4_20260921.zip --out experiments/learning_round5_20260921/input_audit
```

この監査は標準ライブラリのみで動く保存リプレイ集計であり、新規対戦やモデル実行ではない。次の観測を再現すること。

- 保存リプレイ16本、各hash・終局資金・相手資金・info.seedが報告と一致。
- 全16本で保存状態720、DONE/DONE。
- learned/ruleとも外部相手に0勝8敗。
- learned平均終局資金2,458、rule平均3,253.25。
- learnedの全8試合で途中現金0、4試合で全期間FEED0。
- learnedのHARVEST722回中、576回はactor別在庫増加、144回は後続actorの同一作物への重複で在庫増加0、2回は日替わりのためこの監査では帰属未確定。
- 未成熟作物へのHARVEST発行は0。ここは改善しているので回帰させない。
- 家畜38配置、35消失。消失前は全て未給餌カウント1・fed false・日替わり。
- MILK/WOOL/EGGの家畜HARVEST0。これらのSELLもない。
- 終局で牛2頭が各yield6、羊1頭がyield6を持つ例がある。
- learned/ruleの店舗系列は全8pairで異なる。

すべての数を手でfinalizerへ埋めない。ソースデータから再計算して一致/不一致を残す。不一致があれば原因を調べ、独立監査へ反例として記録する。

## 4. P1-A：joint actionの資源競合を直す

最優先の直接的実行不成立は、同じターンの同じ作物へ複数actorがHARVESTすることである。

例1：qeinstein、seed2026092421、seat0、保存record297／意思決定step296、(0,4)。WHEAT yield2へactor3とactor4がHARVESTし、後続actor4の取得量は0。

例2：qeinstein、seed2026092821、seat1、保存record583／意思決定step582、(7,4)。同じWHEATへ6actorがHARVESTする。

fixtureにはこの2局面のbefore/joint_action/afterがある。観測だけのfixtureを完全engine checkpointと思い込まない。反実仮想を継続する場合は全状態を復元するか正しいprefix再生を使う。

修正要件：

1. 単なるサービス文字列の重複検査ではなく、対象資源の消費・変化を扱う。HARVEST yield、PICKUPのshed inventory、PLANTのseedとtile、COLLECT_FERTILIZERのavailability、FEED/WATER/CAREの状態、必要なcapacity等。
2. 固定engineが実際に使うfarmer→hand順に、作業用状態へ先行actorの効果を反映する。PLANTの原子的種不足判定等、engine特有のjoint semanticsも一致させる。
3. 後続actorが資源を失った場合、別の有効jobへ再割当てする。最後の安全策としてのPASSは許すが、全てPASSに変えて解決扱いにしない。
4. 同一座標の複数actorを一律禁止しない。禁止するのは意味のない重複消費や資源不足である。
5. 収穫帰属は「該当actorの当該product増加」を基本にし、他actorによるtile変化を後続actorへ帰属させない。日末回収・capacity・終局は別処理し、観測で不明ならUNKNOWN。
6. cropとanimalのHARVESTを共通のtyped targetで扱う。cropの成熟条件をanimalへ誤適用しない。animalが候補から落ちる、inventoryへ入らない、品目マッピングが誤る、といった箇所を実ソースで調べる。
7. 修正をagent entrypointと実archiveを経由して検証する。helperだけで終わらせない。

旧Round3の未成熟収穫、重複FEED、WHEAT1→2の必要量、復帰後の小麦不足も回帰テストとして残す。

## 5. P1-B：家畜投資を収益回収までつなぐ

現在は配置38頭のうち35頭が逃げ、収穫可能になった家畜もHARVEST0だった。家畜を維持する技能と、家畜投資を回収する技能は別である。

実装する計画は少なくとも次をつなぐ。

`購入 → 配置 → 次の維持期限までの給餌/必要なCARE → 生産物回収 → 倉庫反映 → 売却 → 次の維持または撤退`

ただし毎日全頭にCARE/FEEDを強制する固定ルールを正解にしない。engineの生産日、逃走条件、残り日数、費用と回収可能性、他actorの予定に沿って判断する。

対象の種類・配置日・生産予定・保有収量・餌不足猶予・担当者・必要資源・最終回収期限をplanへ持たせる。維持すると決めたなら必要な餌と現金を予約する。撤退するなら明示的なretirement planとして記録し、単なる給餌忘れと区別する。

少なくとも以下を実engineで通す小さなシナリオを作る。
- 牛が初回生産まで生存し、MILKがactor inventoryへ入り、shedへ反映され、SELLで現金化する。
- 羊のWOOLについて同じ終点まで通る。
- 同じ対象へ2actorがHARVESTを提案しても1つの収量を二重計上しない。
- yieldが正でも残り時間・回収経路によって収穫/保留が変わる。
- 現金・餌・倉庫capacityが厳しい局面で、維持と撤退のどちらかを一貫して実施する。

この試験は「その種がいつも最適」と証明するためではない。選んだ投資を物理的・経済的に完結できる最低限の技能を確認するためである。

## 6. P1-C：序盤の資源・現金予約

qeinstein seed2026092421 seat0では、record1〜8で牛4頭と土地へ投資し、給餌予定のないまま小麦をSELLし、record48で初期2頭が逃げ、record49で現金0に到達した。最初の96行動を優先的に診断する。

市場policyを作業planと同じ資源台帳へ接続する。最低限、引受済みplanに対して次を考える。

```text
unreserved_cash = current_cash - committed_near_term_cash_requirements
unreserved_wheat = accessible_wheat - committed_feed_requirements
```

ここでrequirementsは、機械的な全家畜数ではなく、維持方針・期限・移動・購入可能時点から計算する。入金見込みを使う場合は、実際の回収/販売が期限までに実行できるかを確認する。市場注文順・per-unit価格変化・注文上限も実engineに合わせる。

土地や追加家畜の購入には、資金だけでなく必要な作業と初回回収までの継続見通しを付ける。合法注文を個別に通すだけで、餌予約や次の雇用費を使い切らない。

## 7. P2：モデル表現と技能カードを直す

Round4は新しい19特徴・4クラスsoftmax selectorを216更新した記録がある。test accuracy0.6510、macro-F10.5914、多数派baseline0.5708/0.1817。これは前進であり否定しない。一方、連続planの再現証拠ではない。

### 7.1 入力の情報不足を実テストする

Round4の特徴名には、家畜のyield、種類、年齢、次生産日、担当actor位置、現plan、個別商品の市場状態が明示されていない。実feature関数へ、家畜yield0/6だけ異なる同条件の2観測を与え、同じ特徴になるか確認する。旧BCの特徴についても別に調べ、全agentの欠落と新selectorだけの欠落を混同しない。

候補・対象単位の特徴として、必要なものを追加する。単に全マスを大きなベクトルへ押し込むことより、候補planの資源・期限・対象・見込み効果を表現する小さな設計を優先する。

### 7.2 出力を行動の大まかな名前だけで終えない

1joint actionに維持・植付け・購入が同時にあるため、単一クラスの付け方を確認する。教師から次に何を学ぶのかを明確にする。

実行可能な候補の選択、対象割当て、数量、期限、継続を出力/保持する。上位モデルが経営選択を行い、下位の共通planner/executorが資源予約付きで手順を完了する形でよい。巨大な新フレームワークを先に作らない。

例えば次の情報をtyped planへ持たせる。名前は実装に合わせてよい。

```text
plan_id / strategy_mode / job_type
actor_identity(seat, actor_index, day_epoch)
target_identity(type, coordinate, generation_or_placement_day)
required_resources / resource_reservations
ordered_primitives / deadline / continuation
primitive_postconditions / completion_postconditions
abort_and_replan_conditions
```

teacherの意図を断定して捏造しない。観測行動、解析者が推定したplan、探索器・ルールが生成した訂正ラベルを別のoriginとして保存する。

### 7.3 action表現を実際のruntime経路で検証する

Round4の28,760件のaction codec roundtripは、新旧モデルがその数量・順序を出せる証拠ではない。

旧`bc_agent.py`、actor/market model metadata、`bc_quantities.json`、codec呼出し箇所を調べる。固定代表数量や中央値に潰れていないか、注文列や同時actor対象を出力できるかを確認する。存在するだけのcodecを合格証にしない。

教師action→学習target→モデル出力表現→decode→実行actionまでの同値/表現不能率を測る。表現不能は学習不良と区別する。初期教師カードのWHEAT5と実戦冒頭のWHEAT3の差も、その原因を入力差・数量圧縮・モデル誤差のどれかに分ける。差があるだけで数量圧縮と断定しない。

### 7.4 技能カードを実際の連続系列へ

Round4の3カードの正例は全てepisode109741171、各observed_planは4個のjoint actionスナップショットで、実行条件は一般文だった。

複数のtrain episodeから、始点状態・連続action・終点状態・必要資源・期限・完了条件を保存する。実行可能な条件式を定義し、正例/反例を通す。test/validationの結果を見ながらカードを最適化して新規holdout扱いにしない。

単一teacher submission56216119の由来を保ち、現在上位であることや非公開ソースversionは未確認ならUNKNOWNにする。他教師・自作探索訂正を使う場合は由来を混ぜない。

## 8. P3：教師状態上の学習から自律動作へ

学習は実際に実行する。新checkpoint、parameter change、optimizer updates、loss、split別metric、再ロード推論を保存する。既存BCを再利用しただけの部分を今回再学習したと書かない。

少数の一貫したepisode/技能を再現できるか確認し、できなければfeature alias、ラベル競合、出力表現、モデル容量、最適化を分けて調べる。低容量モデルへ表現不能な100%一致を一律に要求しない。

teacher-prefixから24/48/96step等の閉ループを行い、最初の重要な分岐、その後の資材・期限・投資回収を記録する。家畜初回収穫など窓が足りない技能は完了まで延長する。

復元は全engine state、seed/RNG、設定、policy stateを考慮する。復元できない場合、同じengineの正しい初期化から両者の保存actionをprefixまで再生し、元状態へ一致することをまず確認する。fixtureの観測を直接差し込むだけで本物の反実仮想と主張しない。

非公開教師のreplayしかない場合、learner状態への教師queryはできない。DAggerを実施したと書かず、実際に利用可能なルール/探索/人手訂正は別originとして記録する。

## 9. 比較実験を公平にする

Round4のruleは、1区画のニンジン、動物0、雇用0、移動0、660/719 PASSの別方策だった。共通executorでもこれとの比較だけでは新selectorの効果を分離できない。

最初は同じ基盤と候補集合で以下を比較する。

| arm | base | executor/planner | selector |
|---|---|---|---|
| NONE | 同じBCまたは同じ独立base | 同一の修正版 | 新selectorなし |
| RULE | 同じbase | 同一の修正版 | 明示ルール |
| LEARNED | 同じbase | 同一の修正版 | 学習版 |

元のRound4 artifactは凍結し、同条件の回帰比較でexecutor修正の前後も測る。完全に別の独立policyを作る場合はその差を明示し、「selectorだけの効果」と呼ばない。

C0を並べる場合は同じ外部相手での参考水準として使い、旧agentへの直接勝利を主目的にしない。C0差分正でなければ学習研究停止というゲートを復活させない。

現時点で既に見た条件：
- qeinstein_moev2 seed2026092421、両seat
- smart_farm seed2026092422、両seat
- qeinstein_moev2 seed2026092821、両seat
- smart_farm seed2026092822、両seat

これらは全て開発済み。修正後の正式確認は新しいseedで事前固定する。必要な家族数・seed数は実行予算から決め、両seatを独立標本として数えない。元の新規scopeは2clusterだけなので、狭い信頼区間やレート推定を作らない。

## 10. 市場・店舗の差を記録する

Round4では全8pairで店舗系列が変わり、marginが改善した3試合は全て自分の資金が減っていた。

既使用4試合の平均：Δself−1,905.5、Δopponent−6,053.5、Δmargin+4,148。
新規ローカル4試合：Δself+315、Δopponent+9,794.5、Δmargin−9,479.5。

公開engineは同じ日内乱数ストリームを雑草配置と店舗選択に使う。ローカルの固定engine実体で確認する。空きマスの違いにより乱数消費回数が変わり、同じseedでも店舗系列が変わり得る。

paired比較は無効ではない。方策全体の効果にこの経路も含まれる。しかし、相手資金差を意図的な妨害戦略の学習と断定しない。self/opponent/marginに加え、店舗解放系列、最初の市場差、相手actionの最初の差を保存する。

正式比較のengineは変えない。店舗系列を固定する補助実験を作る場合は非公式なデバッグ用として完全に分離する。

## 11. 成功カウンタと評価器

Round4報告の合計はstarted730、job_completed4,297、primitive_issued29,092、effect28,205、failed10、unknown818。差59が残る。base primitiveとplanが混在している可能性があるので、実ソースで定義を確認して修正する。

- base primitive、override primitive、plan start、plan completion、cash realizationを別母集団で数える。
- 全イベントをplan_idとactor/day/target versionに関連付ける。
- 同じplanのcompletedを二重計上しない。
- 最後の未観測結果はterminal pending/unknownへ。無条件成功にしない。
- 重複収穫144件が旧runtimeでどのstatusになったかを調べる。failed10だけから誤帰属を断定しない。
- 全traceを保存するか、各失敗の前後窓を保存する。Round4のfirst_trace_events30件だけでは後半の重複収穫を監査できなかった。

`EXECUTION_CORRECT`は「何かのprimitiveが成功した」ではなく、明示したscopeの必須契約が成立したかで判断する。全体DONEと別軸にする。

`evaluate_artifact(metrics, provenance, purpose, thresholds)`のような純粋関数を使い、PASS/FAIL/UNKNOWN/NOT_APPLICABLEと理由・scope・evidence hashを出す。正負の経済結果、無発動、unknown、古いhash、重複完了、model loadのみ、推論なし、fallback、ルール版などの人工入力で判定が正しく変化することをテストする。

学習・モデル使用・実行・技能再現・局所経済・外部経済・online・限定提出・champion promotionを分ける。全てを1つの合否に押し込めない。

## 12. 研究継続、提出候補、昇格を別にする

今回の重複HARVESTと家畜回収欠落は明確な修正対象であり、現在のRound4をそのまま提出する理由はない。しかし、模倣学習一般を棄却する理由でもない。

修正後に意味的な技能が実戦で成立し、実装重大欠陥がなく、明確な仮説があるなら、少数proxyでchampion昇格未達でも限定オンライン試験を提案できる。人為的な恣意的ゲートで有望研究を止めない。実際の提出は許可がある場合のみ。

Round3の384 scan候補は個別continuation未評価のまま保存する。今回の主優先は新たに確認した序盤・重複収穫・家畜回収であり、全384候補への大規模評価を先に完遂する必要はない。未評価をNO_HEADROOMへ書き換えない。

## 13. 最終archiveと引継ぎbundle

最終tar.gzそのものを実loaderで検証する。empty globals、`__file__`なし、任意cwd、リポジトリをsys.pathから外す条件、末尾callable agent、seat0/1、完全episode、実model推論、silent fallbackなしを確認する。不要な外部通信を要求しない。NumPy依存を許容するかは実提出環境で確認し、ルール版だけNumPy不要の結果を学習版へ転用しない。

次の引継ぎはレポートだけのZIPにしない。少なくとも以下を実物で同梱する。

1. 変更したRound5ソース、参照するbase/BCソース、全modelとmetadata、学習/評価/packagingスクリプト、テスト。
2. 最終learned/rule/比較archiveとmanifest。作らないarmは未作成と明記する。
3. 固定engineと依存version情報、engine hash。可能なら合法に同梱、不可なら正確な取得・検証手順。
4. 再現fixture、最初の失敗の前後trace、保存replay、比較CSV、技能完遂・経済回収台帳。
5. データ/教師/split/label provenance、学習記録、再ロード推論、提出loader検査。
6. `ROUND5_REPORT.md`、`FINAL_STATUS.json`、`REPRODUCE.md`。

bundleに含む全manifestパスが実在し、hashが一致することを機械検証する。通常のgit diffがuntrackedを含まないことを忘れない。巨大な教師原本を全て同梱する必要はないが、独立再現できる最小データsubsetとその由来、全データの取得情報・hash台帳を用意する。

## 14. 最終報告の順序

何を再現したか → 実ソースのどこが原因だったか → 何を修正したか → 実際に何を学習したか → 同条件でどの技能が完遂されたか → 資金/相手資金/marginのどこが変わったか → 未実行事項 → 限定提出候補の有無、の順に書く。

性能改善やレート2000/3000達成を約束しない。改善が見つからなくても、どの仮説をどの条件で反証し、何が未解決かを実測に基づいて残す。監査文書の量やテスト件数を成果の中心にせず、一つの投資・一つの仕事が収益回収まで完結する実証を重視する。
