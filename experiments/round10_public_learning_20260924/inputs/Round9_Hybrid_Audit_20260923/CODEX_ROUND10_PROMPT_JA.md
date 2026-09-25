# Codex入力用：Round10 — 強いbaselineを保持したタスク候補ランキング型ハイブリッド

あなたはこのリポジトリのKaggricultureエージェントを改善する。過去スレッドの知識がなくても、この依頼とリポジトリ内の実物を確認して進めること。目的は学習回数や模倣accuracyを増やすことではなく、**既存の強いv122/v124を、同条件の対戦で上回るエージェントを作ること**である。今回の作業中はKaggleへ提出しない。

まず既存ファイルと実装を読む。存在しないソースや実行結果を推測で補わない。現行コードを無差別に置き換えず、独立したRound10ディレクトリ・設定・成果物として作る。実装・学習・推論・評価の実行済み件数を別々に報告する。未実行の計画は結果として書かない。

## 0. 実物確認に使う情報

ユーザーが監査へ渡した入力は次の二つだった。

- `round9_teacher_reproduction_and_closed_loop_bc_20260923.zip`
  SHA256 `2640c30c38d5304b142a47b87d3b50e5fe030fbe0746d51be272840f40eaaf9f`
- `grimmsnarl_ml_vfinal_submission.tar.gz`
  SHA256 `95c8a0db9cb87b7820a4bd172088b82e57582261f51d4f9e3a56bc016d466acb`

Round9の添付は実験ディレクトリのexportで、同梱のcomplete_v2 manifestが記述する完全なrepo bundleではなかった。最終A2ソース、提出tar、固定engine、v122/v124等の一部が含まれていない。**ローカルリポジトリで実物を探して照合すること**。同名ファイルを勝手に同一物とみなさない。

ローカル参照パスと既知hash：

- A2 source予定位置：`agents/round9_teacher_reproduction_and_closed_loop_bc_20260923/a2/`
- A2 v3：`artifacts/submissions/round9_20260923_a2_prefix_bc_seed20260924_v3.tar.gz`
  SHA256 `f5ac17a3b7db2d1311f066f9e19b1c8aa0ccf577d0955b7e2a78e03b8246811a`
- A2 v2：SHA256 `02b83f3626c33914860ca2a542619d2aa4a1197cbe3176549979a761b029245c`
- v122 archive：SHA256 `edf5b32565f8c4530959b94df36858a6a64c651d4b42b7aa612ddaca02e9a88c`
- v124 archive：SHA256 `cdc74eb6ae47c53e9c2edfeea45dc55603c67ebfdba48164081458f79c4f46fc`
- 固定engine：kaggle_environments 1.32.7 のKaggriculture engine
  SHA256 `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`

これらは識別情報であり、現在インストールされている環境の版を推測する根拠ではない。現物が違えば差分と影響を報告する。欠落時は検証可能な工程まで進め、通過していないゲートをPASSとしない。

## 1. 既知の結果と、その正しい扱い

以下は今回の独立監査が保存対戦・重みから確認した事実である。こちらの監査では新規ゲームも再学習もしていない。

### 1.1 成績

- A0 pure、共通8条件：0勝0分8敗、平均自資金1,411.875、平均margin −137,263.375。
- A1、同8条件：0-0-8、648.25、−146,260.125。
- A2 v2、同8条件：0-0-8、10,787.75、−128,250.375。
- A2 v3、同8条件：v2と所要時間関係以外の全action/state/rewardが意味的に一致。同じ成績。
- A2 v2拡張64条件：0-0-64、9,604.546875、相手157,465.671875、margin −147,861.125。
- 拡張64条件は16 seed×v122/v124×両seat。64を独立試行とみなさない。
- 全176保存試合のhash/seed/状態数/DONE/DONE/終局資金は整合。ただし条件重複を含む。
- **64試合はv2。v3は8試合。v123は今回未評価。**
- A2がA0より改善した事実を、v122/v124超えと呼ばない。

### 1.2 モデル

選択seed20260924、旧testは既に設計判断に使われた開発診断でありfresh holdoutではない。

- actor token 13,899/16,692＝83.27%。
- 作業token 13,402/14,967＝89.54%。
- 移動方向490/1,697＝28.87%。
- market token4,617/6,714＝68.77%。
- EOS＋HIRE3,642/4,028＝90.42%。
- その他経済判断975/2,686＝36.30%。
- SELL477/1,615＝29.54%。
- 2 seed×4 headの初期/最終hashが整合し、重みは実際に変化。
- actor/market計23,406行の独立NumPy再推論は保存confusionと完全一致。
- training対象は20 episode＝train12/validation4/旧test4。全workを保持し、MOVE/PASSを1/8抽出。全体accuracyの分母に偏りがある。
- 現行normalizationはmean0/scale1。以前のtiny varianceの問題を現行の確定原因として再主張しない。

### 1.3 実戦の崩壊

- A2 actor306,692件中MOVE269,847件＝87.99%。相手は42.35%。
- 非MOVE/nonPASS workはA2 11.63%、相手50.54%。
- 直前の移動の逆戻りはA2平均164.25回/試合、相手12.53回。正常な往復もあり、全件を不具合扱いしない。
- day=8/record192：A2平均土地1、作物9.47、家畜2.22。相手は土地2、作物37、家畜10。現金はA2 1,452.53、相手650.81でA2の方が多い。
- day=20/record480：A2作物0.625、家畜0.15625。48/64試合が作物・家畜ともゼロ。相手は作物58.94、家畜16.81。
- 終局：A2は62/64試合が作物・家畜ともゼロ、家畜は全64試合ゼロ、48/64試合で土地1区画。
- A2は空の牧草地がday20平均24.48、終局26.36。BUILD_PASTURE2,537回、相手934回。
- 終局作物ゼロ自体は正常清算の可能性がある。今回はday20から生産能力が失われ、資金成長が止まっていることが問題。

### 1.4 A2のハイブリッド度

- 64試合46,016 turnで `plan.disabled=true` 全件、plan active0、interventions0。
- `final_action == ledger_action` 全件。
- raw actor top1が合法候補外となりtokenが変わった例103,922/306,692＝33.89%。
- raw→mask変更のうち98,555件はMOVE。うち65,180件はrawが作業だった。
- よってA2は生モデル出力を無加工で使ってはいないが、主に合法化/共有資源処理であり、戦略的task管理とは違う。

### 1.5 100%と再現検査

Round9 REPORTのwork effect100%は、発行済みworkに直後の効果があるという条件付き指標。教師模倣accuracyではない。作業量、必要性、仕事の完了、最終利益を測っていない。

元教師完全再生1440/1440、codec8824/8824、A2教師state-effect719/719、15 fixture、loader/reset修正は保存報告にある。今回の監査はengineがないため再実行していない。あなたはローカルの実物で必要範囲を再確認すること。

単一軌跡memorizerはactor98.51%でもT1 joint596/719、teacher physical state＋自己prefixのT2 joint460/719、自己stateのT3 joint18/719、state16/720、最終cash4,658対教師111,530に崩れた。T3は記録相手action固定の再現診断であり、本当の応答相手との勝率ではない。

Round9には6失敗状態と検証済み回復ラベル3件があるが、まだ再学習していない。既にDAgger完了とは扱わない。

## 2. ポケモン側から移すこと／移さないこと

次を実際の添付コードで確認すること。

- `ml_runtime.py` のrankerはengine提供の合法 `select.option` を状態＋候補特徴で順位付けし、意味的重複を除く。
- 保存モデルはLightGBM形式、2000 trees、823 features。ただしモデル種類自体の優位は未証明。
- `Ranker.is_scorable` はrouted contexts、単一選択、候補数などでMLの権限を限定。context最低support400/top1 0.6はexport側の選定設定で、各判断の勝率信頼度ではない。
- `main._choose` は非対応/失敗時にrule、対応時にranker、さらに `Planner.adjust` の狭い補正を使う。
- 最終的に実行した候補を `commit` / `observe_external` / `note` に反映する。
- **`turn_search.py:53` は `ENABLED=False`。buildはNoneを返す。探索は最終版既定OFF。**
- コードコメントでは、即時prize最大化の探索を忠実に完遂しても成績が悪化したと記録。コメントの勝率を生ログで独立確認済みとは書かない。

移すべきものは候補化・権限分離・履歴整合・限定補正・悪化機能の無効化である。ポケモンのゲームロジックや即時利益探索をそのまま移植しない。未確認の因果関係を「成功理由」と断定しない。

## 3. 今回の基本方針：二つの系列を分ける

### Competition track

強いbaselineを壊さないwrapperを出発点として、**タスク候補の選び方をMLで改善する**。弱いA2を救う大規模ルールを先に作るのではない。baselineより強いかを主目的とする。

ただし、baselineを呼ぶだけでML成功とはしない。baseline由来の選択、新規ルール由来の選択、MLによる変更、補正による変更をtraceで区別する。新しい候補を全く持たなければbaselineを超えられないので、上位ログ由来の新タスク・投資プランへ拡張できる構造を作る。

### Research track

A2純粋BCは対照として残す。最初の安い比較は、同じ20episode/特徴/model/decoderでMOVE/PASSの抽出率・損失重みだけを変更すること。実験としてsampling補正と、後続のtask/target/history変更を同時に混ぜない。

research trackの改善待ちでcompetition trackを止めない。時間・資源不足時はcompetition trackのPhase Aと一つのtask実験を優先し、未実施分を明記する。

## 4. Phase A：基準とnull controlを先に通す

1. リポジトリ・engine・各archive・現行agentを識別し、SHA、commit、依存、公式loader挙動を記録する。
2. v122/v124を未改変で固定条件評価し、基準方策を事前規則で固定する。版番号だけでv124最強とみなさない。同じ結果になる系列を独立family数に水増ししない。
3. wrapperに `force_baseline` を作り、元baselineと全action、state、rewardが同じになるnull controlを実行する。所要時間等の非意味フィールド除外は明記する。
4. proposal生成は副作用を持たせない。baseline呼び出しが内部カウンタ、task、RNG、資源予約を進めるなら、隔離・複製・最終commitを設計する。
5. 他候補実行後にbaselineへ復帰できるかを、実状態・在庫・土地・actor位置・日付・計画進捗の契約として定める。途中の固定ルートへ無条件で戻さない。
6. 復帰が安全に定義できない領域ではinterventionを許可しない。ただし永久に全領域をbaseline固定にして成功扱いしない。
7. 新タスクに介入しない限り、baselineの動作をA2のresolverで勝手に変更しない。baseline own contractと新タスクcontractの整合を確認し、wrapperだけで性能差を出さない。

**Phase Aの停止条件**：null control不一致、公式loader誤選択、episode状態漏れ、モデル未読込の隠蔽、復帰契約不明、実行時間超過。原因を直すまで後段の大規模学習へ進まない。

## 5. Phase B：最初のtask系統を実測で一つ選ぶ

A2が苦手というだけでv124に改善余地があるとは限らない。まずbaseline対戦の損失・未回収・維持失敗・過剰投資・将来資源欠乏を調べ、上位教師ログと照合する。そのうえで、最初のtask系統を一つだけ事前選択し、理由を記録する。

候補例は給餌の完了、成熟作物の収穫＋倉庫搬入、種/餌の補充、再植付け、予約済み資源を除いた販売など。これは選択候補であり、今回すべて実装せよという意味ではない。土地・家畜・販売・全crop mixを同時に変更しない。

タスク表現の必須項目：

```
task_id, family, actor_id, target_id/coordinate,
preconditions, required_items/quantity, reserved_resources,
start_step, deadline, expected_work_steps,
completion_predicate, failure_predicate,
abort/replan_conditions, baseline_rejoin_contract,
proposal_source, features_version
```

現在のobsを根拠に候補を生成する。教師の未来を見て候補を生成しない。teacher未来行動を教師ラベルの構成に使う場合は、観測特徴へ漏らさない。

候補集合には少なくとも「baseline案」と「継続中task」を残し、仕様上必要ならPASS/待機を残す。新しい候補をrankerに選ばせる前に、実行可能性と対象物の同一性を確認する。

候補生成・選択・実行の失敗を別に集計する。

- 良いtaskが候補にない：candidate coverageの問題。
- 候補にあるが選ばない：rankingの問題。
- 選んだが途中で止まる/別対象になる：executionの問題。
- 正しく完了しても最終成績が悪い：目標/戦略価値の問題。

## 6. 実行器：一手の合法化ではなく仕事の完了を扱う

目標を毎手の方角へ解体して忘れない。選ばれたtaskの目的地、必要品、移動、作業、回収、搬入、完了を追う。ただし悪いtaskに無期限に固執しない。価格・対象消失・期限・資源・生産状態が変わった場合のabort/replanを定義する。

同turnの複数actorとmarketは共通のaccepted-prefix/resource ledgerを使う。種/餌/倉庫容量/現金/土地/収穫対象の競合を予約し、拒否や部分実行時に解放・再計算する。最終action後、次の実観測からtask成否を更新する。「命令を発行した」だけで完了としない。

ruleへ切り替えた場合も、モデル履歴、task履歴、baseline内部状態には**実際に採用されたfinal action**を一度だけ反映する。candidate採点のための仮のactionで履歴を進めない。

必要fixtureは既存Round9の正例を保存したうえで、task開始/継続/中断、他actorとの対象衝突、給餌資源の売却防止、収穫→搬入、日替わりreset、episode reset、倉庫満杯、baseline復帰などを追加する。コード固有の動作は固定engineで確認する。

## 7. Rankerの学習

最初は既存教師20episodeから状態＋task候補のrankerを作る。MLPか木モデルかは実装容易性・候補表現との相性・提出依存・推論時間で選び、選択理由を残す。モデル種類比較を行う場合は候補・特徴・データ・目的を固定する。

特徴は現在の公開状態、自己private、既知の過去、task/target/移動距離/期限/資源予約/実行進捗とする。相手private、未来shop、未来action、最終勝敗を入力しない。

教師を写すだけのscoreと、baseline案に対する経済的優位の推定は別名・別指標にする。top1確率やentropyをそのまま利益差の信頼度とみなさない。

候補に教師taskが含まれない行を黙って除外しない。coverageとその分母を報告する。分割はepisode/family/時期を尊重し、同軌跡の隣接行をtrain/testへランダム分配しない。旧testは開発用のまま扱う。

初期/最終weights、model schema、feature order、候補集合version、乱数seed、hash、loss、selected epoch、optimizer stepを保存する。決定に実際に使われたモデルがそのweightであることをarchive展開先から確認する。

## 8. ルールとモデルの権限を分ける

- 契約違反：違法、資源超過、二重予約など。常に棄却するが、これを戦略優位と呼ばない。
- 狭い条件での比較：同じtaskを満たす経路など。前提と比較理由を記録する。
- 中長期の経済判断：原則としてpairedな終局評価と検証済みcontext別の増分を使う。

ゲートは、対象contextのデータ量、未経験状態、学習候補とbaseline候補の差、検証済み改善域などを明示する。閾値はvalidation/developmentで固定する。不確実ならbaselineに戻す設計は可能だが、任意のfallbackが安全性の理論保証を持つとは書かない。

**禁止**：単に今のcashを増やせるから上書き、売れるものを全部売る、給餌/種/再投資資源を無視、短期rollout利益だけで大規模に上書き、探索を増やせば強いと決める。

A2はday8に相手より現金が多くても生産投資が不足して負けた。この観測を回帰テストの説明例として使う。中間の生産能力指標も無条件最大化せず、最終資金差への整合性を確認する。

## 9. 自分生成状態・回復学習

初期のranker/executorが動いた後、その方策自身のrolloutから、task中断、空農場、必要資源欠乏、目的地振動、在庫運搬未完了などの状態を採取する。

その**現在状態**で実行できるbaseline/planner/探索を教師にし、元の上位教師の同じstep actionを貼らない。元教師コードが呼べない場合は、代理教師であることをlabel provenanceに記録する。

ラベル源は original_teacher / executable_baseline / bounded_search / human_rule / unknown 等で分ける。収集しただけでなく再学習し、on-policy結果を再評価して初めて回復学習の効果を述べる。現存の3ラベルだけでDAgger済みとしない。

offline分岐評価では評価器のfull engine stateとagentのobservationを分離する。相手はその分岐に応答する固定方策を動かす。未来の記録相手actionをそのまま使う場合は再現診断に限定し、実相手勝率や本番行動の根拠にしない。初期state・乱数・相手・seatを対応付け、因果的に比較できないrolloutをpairedと呼ばない。

この段階まで到達できない場合、未実施として残す。工程を埋めるための偽の回復ラベルを作らない。

## 10. 評価アームと因果的な比較

最小構成を次とする。全アームを一度に大規模評価する必要はなく、ゲート順に進める。

- C0：改変しない強いbaseline。
- C0-wrap：force_baseline wrapper。C0とのnull control。
- H-rule：新candidate generator＋新executor＋ルールranker。
- H-learned：**H-ruleと同じ候補と実行器**＋学習ranker。
- H-gated：必要になった場合のみH-learned＋経済/適用領域ゲート。
- A2-v3：旧学習対照。優越主張の基準にしない。

新タスク実行器だけで強くなったのか、学習によってさらに強くなったのかを分ける。MLがほぼ使われないのにML版と称すること、model inferenceだけして選択を常にruleに戻すことを成功扱いしない。固定状態上のscore shuffle/weight差し替え等は経路確認診断に利用できるが、無意味に大量のランダム対戦を増やさない。

全ての判断に、baseline proposal、候補一覧、選択score、モデル選択、rule補正、採用元、final action、task遷移、effect、復帰理由を対応付ける。ログ量が大きい場合は集計と監査用抜粋を残し、監査対象は決定的に再抽出可能にする。

## 11. 事前登録と採用条件

- 相手と版/hashを固定し、同seed・同seatでpaired評価する。
- v122/v124の近さを踏まえ、family数を水増ししない。後段で可能なら戦略の違う相手を加えるが、現在の基準を黙って変更しない。
- 開発では2 seed×2相手×2seatなどの小パネルを最初に使い、実装不具合と大きな退行を検出する。小パネルだけで提出可としない。
- 既存16seedは開発用。候補固定後に未使用の最終確認範囲を開く。使用済みseedをfreshと呼ばない。
- 主指標は事前に固定する。例：対固定相手群のpaired終局margin改善を開発主指標とし、確認段階では勝敗scoreの改善・退行制約も事前定義する。結果を見てcashかmarginか勝率かを選び直さない。
- 同seed内の相手/seatをまとめたblock bootstrap等を使う。64ゲームを完全独立とみなした過小なCIを避ける。
- 絶対資金、勝分敗、相手別、seat別、下位tail、農場崩壊頻度、task完了、計算時間p50/p95/p99/maxを併記する。
- runtime exception、未完走、loader誤選択、データ漏洩は失格。ゲーム仕様上の許容された資産退出等は、baselineにも起きるかと経済影響を確認し、機械的に全件失格としない。
- 「H-learnedがA2を上回った」だけでは採用不可。C0に対する改善と、H-ruleに対するML増分を分けて評価する。
- この段階でレート2000/3000を予測しない。対戦相手・条件が限定されたローカル証拠として報告する。

## 12. 提出互換性と実行予算

今回の作業では提出しないが、検証は実際の公式loader規則に合わせる。`get_last_callable`がagentを選ぶか、空exec環境、展開先import、同名moduleの混線、w3を含む保存重み読込、複数episodeのstep0 resetを検査する。

runtime制限は現在の固定engine/configの実値から取得する。ポケモンの探索budget3.5秒等をKaggricultureへ流用しない。平均時間だけでなくtailと最悪ケースを測る。

research_strictとdeployment_fallbackを分離する。research_strictではモデル読込失敗を明示的失敗にし、fallback対戦をML実験として集計しない。deployment_fallbackを用意する場合も、発動をtraceに残して別集計する。

## 13. 必須成果物

1. `ROUND10_DECISION_JA.md`：事実、推定、提案、未実施を区別した結論。
2. `preregistered_evaluation.json`：目的、比較、primary metric、seed/相手/seat、失格条件、確認用範囲の扱い。
3. `artifact_identity.json`：入力/出力archive・engine・models・features・scriptsのhashと実体パス。
4. `baseline_null_control.json`：C0/C0-wrapの全action/state一致と最初の不一致。
5. `task_contracts.md`：最初に選んだ一系統の前提、継続、完了、abort、復帰契約。
6. `dataset_manifest.json`：episode単位分割、候補coverage、ラベル源、除外数、漏洩点検。
7. `learning_evidence.json`：実学習/保存/推論/採用の証拠を区別。
8. `games.csv`、各試合replay、診断、paired比較、seed block単位集計。
9. `authority_audit.json`：ML/rule/baseline/安全層の採用数、変更数、fallback数、各層の役割。
10. `economy_and_task_audit.json`：day8/12/20/終局の資金・稼働作物・家畜・土地、運搬・維持・再投資、task完了と中断。
11. `effect_denominator_audit.csv`：Round9の専用effectと旧inline effectの定義、action ID、checked/success/failure/unknownの対応。UNKNOWNを分母からどう扱ったかを説明。
12. `reproduce_audit.py`または同等スクリプト、実行コマンド、依存版。

返却するZIPには、一覧だけでなく実際の最終source、最終archive、必要なmodel weights、features schema、実行・学習・評価scripts、固定engineの識別情報と利用条件上同梱可能な実物、比較baselineの同定情報、必要replayを含める。容量で分割するならmanifestと全partを実際に作り、何がどのpartにあるかを検査する。権利・機密等で同梱しない物は理由と再取得方法を明記し、「complete」と誤表示しない。API key等の秘密は絶対に同梱しない。

## 14. 実行の優先順位

最優先はPhase Aの実物確認とnull control、次にbaselineにも実際の改善余地がある一つのtask、次にH-rule/H-learnedの同候補比較である。契約・候補・実行器が未成立のまま、データ数を増やしたり大型modelを長時間学習したりしない。

途中で性能が悪化したら、悪化した変更を切り分けて戻す。ポケモン最終版が短期探索をOFFにした点を参考にする。追加した機能を残すことを目的にしない。

最終報告は「何を実装したか」からではなく、**既存baselineに対する成績、MLが実際に改善した判断、まだ改善していない点、次に採用/却下するもの**から始める。未達なら未達と書き、提出推奨しない。競争力改善と、独立BC研究の進展を別々の結論にする。
