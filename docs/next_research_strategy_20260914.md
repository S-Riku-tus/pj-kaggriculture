# これまでの研究の再評価と、次に検証する問い

次の研究では、**V111の敗戦状態を実際に対象にできる介入を選び、その状態で必要な調達・作業・売却を成立させたときに勝敗が変わるか**を検証する。最初の調査対象は、既存の管理付き動物が開始できなかった低資金の8敗戦と、t216～360の収支・生産活動である。前回と同じ選択肢へselectorを追加する根拠はない。一方で、今回の0反転を適応戦略全体の不可能性とは解釈しない。

本書は2026-09-14の再評価である。開始時のrepositoryはmain、HEAD `851e970`、tracked変更なし。前回の結果はこのcommitに保存されている。新たな対戦、candidate作成、Kaggle提出は行わず、既存32 control replays、7版のpaired records、48試合のround robin、sourceを照合した。元ファイルは変更していない。再集計と入力SHA256は[evidence_v2.json](../data/analysis/research_reassessment_20260914/evidence_v2.json)に保存した。[1]

## 1. 目的と成果を分ける

競技上の目的は最終coinによる勝率改善である。評価器の精度、候補数、予測MAE、平均self coinはそれを支える手段である。前回は実行の正しさを調べる能力が改善したが、競技policyの改善は確認されなかった。この区別を保つ。

次の判断は次の順で行う。

1. 介入する状態がV111の敗戦にも存在するか。
2. その状態から別行動が正しく完了するか。
3. 元engine・反応する同じ相手に対して、最終勝敗を変えるか。
4. 複数の有効な選択肢がある場合、その違いをlive観測から選べるか。
5. 未使用seed、異なる相手、重み変更で再現するか。

今回不足している証拠は主に1～3である。4のselectorや供給forecastを先行させない。また、単一の固定改善や完成policyの全体比較が勝率を改善するなら、selectorを作る必要はない。

## 2. 前回の判断のうち維持するもの

V111をproduction Championとして維持し、V114probeと今回の新候補を提出しない判断は維持する。source、Champion archive、凍結engineのSHA256は今回も前回記録と一致した。[1][2]

| 対象 | sourceから確認した変更 | W/D/L | L→W / W→L | 限定された結論 |
| --- | --- | --- | --- | --- |
| V111 | production基準 | 12/0/20 | 基準 | 旧4 source・4 seedsに条件付けた成績 |
| V114r1 | 修正済みselector、発火0 | 12/0/20 | 0/0 | 適応行動の価値は未検証 |
| V114probe | t153の強制suffix | 0/0/32 | 0/12 | 実行不整合を伴い、提出棄却 |
| immediate / town | t361～431の追加売却、以後のSELL整合処理 | 各12/0/20 | 各0/0 | この販売方策に勝敗改善なし |
| unmanaged Sheep | t248の購入・運搬・配置置換 | 10/0/22 | 0/2 | 発火22件でSafety回帰、棄却 |
| retain Cow r1 | 既存late_goalを外してCow側へ戻す | 12/0/20 | 0/0 | 発火対象が勝ち試合だけ、敗戦救済は未検証 |
| managed Sheep / Goose | 2頭の置換＋継続管理＋販売 | 各10/0/22 | 各0/2 | 安全化しても、この対象状態で改善なし |

Cow初版は半開区間を空の`[248,248)`相当にした設定不正であり、r1とは別のinvalid記録として保持する。r1は`[248,249)`で再評価されている。全候補のdraw関連反転は0である。[2]

管理付きGooseは平均self coinが+128.2でもopponent coinが+1,220.6、marginが−1,092.4となった。Sheep/Goose双方のW→Lはqeinstein / seed10091012の両seatである。2件の反転を独立した2つの成功・失敗事例とは数えない。[1][2]

## 3. 前回の文章から修正すべき点

### 3.1 「6候補すべてで敗戦救済を十分検証した」わけではない

前回の表に加え、baselineが負ける組における発火と安全性を数え直した。[1]

| Option | 発火総数 | 発火したV111勝ち / 負け | 安全に介入したV111敗戦 | 意味 |
| --- | --- | --- | --- | --- |
| immediate | 32 | 12 / 20 | 20 | この売却案は全敗戦を試した |
| town | 32 | 12 / 20 | 20 | 同上 |
| unmanaged Sheep | 22 | 10 / 12 | 0 | 安全な別routeの証拠に使えない |
| retain Cow r1 | 2 | 2 / 0 | 0 | 敗戦状態で効果を試していない |
| managed Sheep | 22 | 10 / 12 | 12 | 8敗戦は非対象 |
| managed Goose | 22 | 10 / 12 | 12 | 同じ8敗戦は非対象 |

Cow保持の発火はggmljsへの勝ち試合だけだった。したがって全体のL→W=0は正しいが、「Cow保持が敗戦で無効」という機構の反証にはならない。動物選択を最優先に戻す理由にもならず、試していない状態を明記する理由になる。

managedの未発火8敗戦はmoomanとsouvikのseed10091011/10091014、両seat。t248の現金はmooman899、souvik945で、開始条件のcash≥1500を満たさない。他の開始条件が同時に不成立である可能性もあるため、cashだけを唯一の原因と断定しない。moomanの4敗戦は最終差3,175または3,846coinだった。**比較的近い敗戦の一部ほど、前回の動物介入の対象外だった**。[1][3]

次回は開始条件の不成立理由を条件別に記録する。cash閾値の引下げだけを試すのではなく、先行SELLの確実に実行できる量、動的価格、注文順、必要seed/feed/雇用、翌日の作業まで含めて、低資金状態を扱える別の契約を考える。

### 3.2 売却案は、終盤経済全体の反証ではない

設定はstart=361、end=432、minimum_cash=4000。対象はおよそday15～17であり、終端直前の一括換金でも、最終数日の再投資停止でもない。既存売却のcap処理は介入後も継続する。即時案とTown同期案の無改善から言えるのは、この方策・窓・在庫制約・相手集合に関する否定的結果である。[3]

ただし現在の20敗戦の不足額は最小3,069、中央値9,219、最大67,976coin。2,000以内は0、5,000以内は6、10,000以内は14だった。前回の終端在庫proxyは平均46.4coinで、平均値同士だけで個別反転は否定できないものの、単純な残品売却を主戦略にする根拠は弱い。再投資・生産・運搬を含む数日単位の変更は未検証として残す。[1][2]

### 3.3 「非推移性を確認した」は取り下げる

旧4公開policy間の48試合を再集計した。moomanはqeinstein/souvikに各6勝2敗、3者はいずれもggmljsに8勝0敗、qeinsteinとsouvikは4勝4敗。勝ち越しを有向辺としたグラフに循環は存在しない。これは有限標本での確認であり、母集団が推移的である証明でもない。[1][4]

相手ごとの成績差や4勝4敗は、循環の証拠ではない。Mixed opening/PSROを今導入する実証的根拠は得られていない。PSRO自体が循環を必須とするという意味ではなく、現在の限られた研究時間で優先する理由がないという判断である。原著は、policy混合に対する応答とempirical gameを扱い、固定相手への過適応も問題にしている。[11]

### 3.4 寿命減衰192と、終端残存yieldを区別する

`lifecycle.py`の`lost_current_units.lifespan_decay`は、各stepで実際に減衰したyieldの累積量である。192→192はこの量を指す。一方、最終的にWEEDへ遷移する直前の残存yieldを度数から合計すると72→48になる。前回文章の「寿命終了時の未収穫yield合計192→192」は指標名が不正確だった。[1][5]

| 指標 | Control | V114probe |
| --- | --- | --- |
| 寿命終了件数 | 360 | 473 |
| 残存yield=0での寿命終了 | 288 | 425 |
| 全stepの寿命減衰による累積消失units | 192 | 192 |
| 最終WEED遷移直前の残存yield合計 | 72 | 48 |
| 水切れ死件数 | 120 | 75 |
| 水切れ時のcurrent yield消失 | 96 | 48 |

実HARVEST差は別に保持する。Wheat−232、Carrot−792、Strawberry−1683、Melon±0、Milk−2960、Wool+2666である。作付け・生産構成自体が変わっているので、収穫量差の全量を「取り損ね」とは呼ばない。寿命、水切れ、作付け減少、作業不成立、実売却量、販売単価を別々に見る。元engineでの総policy効果と、各機構が最終coin差に占める割合の同定も区別する。[5]

## 4. 次の調査区間を選ぶ根拠

同じ20敗戦について、元control replayの現金差を確認した。day12/18/20/24でlead→lossが0だったのは集計ミスではなく、この観測時点ではすでに全件劣勢だった。[1]

| decision step | V111現金リード / 劣勢件数 | 敗戦群の現金差中央値 |
| --- | --- | --- |
| 72 | 20 / 0 | +169 |
| 144 | 0 / 20 | −34 |
| 216 | 0 / 20 | −587 |
| 248 | 20 / 0 | +618 |
| 288 | 0 / 20 | −9,854 |
| 361 | 0 / 20 | −12,925.5 |
| 432 | 0 / 20 | −10,865 |
| 576 | 0 / 20 | −8,676.5 |

**Evidence:** 現金差の大きな変化がt248～288にある。**Inference:** t216～360の収支・稼働資産を調べる情報価値が高い。**未証明:** この区間のV111支出が悪い投資なのか、相手が先に換金しただけなのか、収穫・市場・雇用のどれを変えれば勝てるか。現金残高をそのまま経済的優位や最初の不可逆的敗因に置き換えない。

調査では次の会計を一致させる。

`現金変化 = 約定SELL収入 − seed/product/animal購入 − 雇用 − 土地/建設等の支出 + 残差`

併せて、稼働作物・動物、実収穫units、carry/shed、未収穫yield、必要給餌・水やり、worker日次更新を追う。購入された資産を最終スコアへ足さず、将来の稼働・換金で確認する。相手のprivateはoffline検証だけに使い、liveに渡さない。

低資金8敗戦を含め、近い敗戦、遠い敗戦、既存の勝ちを共通基準で選ぶ。都合のよい一組だけで仮説を採用せず、最終評価は凍結した全panelで行う。元の4 sourceは残し、同じ4 seedへの反復だけを増やさない。

## 5. 仮説の順位と判断を変える証拠

| 優先 | 仮説 | 根拠 / 証拠段階 | 次に必要な証拠 | 棄却・転換条件 |
| --- | --- | --- | --- | --- |
| 1 | 低資金状態に届く調達・投資・売却の小さな契約 | 未発火8敗戦、t248～288の現金差。E1＋source | 資金制約と作業の因果的つながり、24～72turnの履行、full720のL→W | 契約成立不能、またはsafe oracle改善なしで別decisionへ |
| 2 | 強い既存complete policyを研究baseの比較対象にする | mooman等へV111低勝率、moomanの旧pool内優位。E3限定 | V111と同じ凍結panelに対する全体比較、自己対戦除外の感度 | 特定相手だけ改善、Safety/多様性不足なら未昇格 |
| 3 | 必要seed/feed/worker確保と注文順を局所修正 | 既存no-op、V114の買付不成立。E0/E1 | 必須作業が失敗した実体と後続効果。エラー数減少だけでは不可 | PASS置換で数だけ減少、または勝敗価値なし |
| 4 | 需要と相手供給を踏まえた生産規模・再投資変更 | 20敗戦のgapは微小換金より大きい。仮説 | 全管理契約、元engineの最終相対利益 | 単なる動物種置換の再試行なら低優先 |
| 5 | 最終数日の再投資停止・収穫・換金 | t361～431の否定結果では未検証 | 戻らない支出と回収可能量の具体例 | 近い敗戦を動かす規模がなければ打切り |
| 条件付き | 最小selector | 現libraryの安全oracle改善0 | 状態による最良route差、安全な反転が複数seed/相手に再現 | 固定routeで十分なら作らない |
| 保留 | opponent forecastの高度化 | strict E2はあるが勝敗価値未証明 | 同じ有効library上の予測なし/calendar/model ablation | MAE改善だけなら入れない |
| 保留 | Mixed opening/PSRO | 確認されたcycleなし | 複数policyの相補的payoffが再現 | 候補数や多様性自体を目的にしない |

第1仮説は「資金不足を直せば勝てる」という結論ではない。次回の最初の約1時間で調査し、行動契約へ落とせなければ第2仮説をPrimaryへ変更する。公開source取得は初期25～30分を上限の目安とし、入手できるまでローカル検証を待たない。30～60%程度の相手は感度の目安であり、30%未満や100%の相手を除く条件ではない。

mooman等をcomplete candidateとして比較する場合、archive全体の効果とcomponent移植を分ける。自分自身や近縁sourceとの対戦が平均を押し上げていないか示す。ライセンスとnative入口を確認し、V111へ直接上書きしない。robriculture/lean_feedの0勝4敗は低感度の独立anchorとして扱い、新しい強い相手や別設定が全て無価値だとは結論しない。[4]

## 6. 評価系は再利用し、次回の誤判定だけを防ぐ

前回のA/Aは8 pairs完全一致、両seat standaloneと720状態完走の記録があり、検証の出発点として使える。変更がなければ全監査を最初からやり直さない。A/Aは再現性を示すが、両armに共通する実装誤りを否定しない。新しい資源会計に依存する箇所だけ、凍結engineの実処理と照合する。[6]

次の補修は小さく限定する。

- **履行:** requested/emitted/engine commitを区別する。Cow保持の`committed`はsourceでは注文の存在確認なので、全種類の新契約で実在庫・配置まで確認する。
- **開始範囲:** 全体のeligible/activeに加え、敗戦上のeligible/active/安全履行、除外理由、独立seed数を出す。
- **Safety:** 旧hard判定を保持する。その上で、raw weed/partial SELL/空HARVESTを原因別に診断する。PASS置換やraw件数の相殺だけで必須作業の欠落を隠さない。旧敗戦候補を判定緩和で救済しない。
- **seedとidentity:** 旧`paired()`は既存キーをlineage/seed/seatでskipし、engine provenanceに固定文字列を入れる。次のrunでは実体のengine・configuration・control/opponent/candidate runtime・評価core・manifestを開始時に照合し、同じ内容の結果だけresumeする。現結果が混入した証拠があるという指摘ではなく、再利用時の境界条件である。
- **共通prefix:** 動的な実発火時刻まで両者のaction/stateとmodule状態を検証する。固定t248の購入監査と任意の介入時刻を混同しない。
- **resumeと時間:** 新規計算とcache再利用の件数、累積wall time、pair当たり実測throughputを残す。0.2秒の再集計を32pairsの実行速度と呼ばない。

`safety.py`は標準設定の数値を使う箇所があるので、異なるconfigurationを使う際は未検証のまま流用しない。`simulate_turn`のHIRE/BUY_LANDイベントには他の売買と同じcash_deltaが記録されないため、単純なイベント合計だけで完全収支と主張しない。位置で決まる建設支出も含め、残差を確認する。[7]

## 7. データを増やす順序と統計の限界

6候補×32pairsを192個の独立した敗戦状態とは数えない。共通のbaseline contextは32件、baseline敗戦は20件、共有seed blockは4である。同一seedの両seatと全sourceをまとめて扱う。source ancestryも保守的には2群で、実行policyの数と独立性は別である。[1]

安全libraryの標本内oracleを再計算するとwin-score増分は0だった。これは観測済みの選択肢と状態に関する結果で、母集団の上界ではない。0差だけをbootstrapしたCI `[0,0]`は無効果の精密な証明ではない。さらに旧robust reweightingは、4 sourceの各1つを上下させる9個のシナリオであり、任意のmeta分布に対する最悪値ではない。[2][8]

探索で反転を見つけたら、最終candidateまたはgateを凍結し、予約Freshとは異なる未使用の**Development確認用seed**で再確認する。確認結果を見て修正したcandidateには、その確認setは以後Developmentである。poolやseedを良い結果が出るまで選び続けない。seed追加は母集団効果の確認に使い、単に既存の全候補を再走する用途には使わない。

E3の反転は次へ進む資格であり、PROMOTEではない。E4ではsourceの多様性、十分な発火、pairwise結果、重み変更を確認し、資格を満たした凍結candidateだけE5を一度開く。前登録の独立ancestry要件は弱い3群目を加えただけでは、現在の強いmetaへの一般化を意味しない。BTをKaggle Ratingに変換しない。少数試行での不確実性を重視する方針はRL評価の原著とも整合するが、特定の統計手法が本件の独立性を保証するわけではない。[10]

[旧preregistration](research_20260911_preregistration.md)のE4最低条件は、検証済み独立ancestryが3群以上、正のrobust payoff、source別非悪化である。これを保持し、「十分」の発火・seed数、不確実性の扱い、E5合否を次runの確認結果を見る前に具体化する。必要な検証量が5時間を超える場合は、Fresh消費を急がず、未証明の範囲と追加計算量を残す。

## 8. 次の5時間の実行順序

| 時間 | 作業 | 終了時に必要な判断 |
| --- | --- | --- |
| 0～20分 | 差分・hash・未完了job・holdoutを確認、必要なら最新Leaderboardを取得 | 何を再利用でき、何がunknownか |
| 20～60分 | 低資金8敗戦とt216～360を中心に収支・資源・作業を調べる。公開source探索はこの段階内で時間制限 | 介入点とPrimary、具体的な比較対象 |
| 60～90分 | baseline＋最大2optionを事前登録、局所実行・不発火・残差の検証 | 対象敗戦で履行可能か |
| 90～180分 | 元engineのfull720 paired、same source/seed/seat、両seat、baseline勝ちも含む | L→W/W→L、Safety、oracle、failure class |
| 180～235分 | 反転ありなら最小固定改善かselectorを凍結し別Developmentで確認。なければ一度だけ第2仮説へ | 多重探索を増やすより次の有益な証拠があるか |
| 235～270分 | 資格を満たす場合のみE4/E5。資格不足なら範囲を限定して未証明とする | PROMOTE / REJECT / PROMISING_UNPROVEN |
| 270～300分 | artifact・検証記録・日本語報告・再開地点を保存 | 何が強くなり、次に何を調べるか |

時間は上限の目安で、各phaseを埋めるための作業はしない。広い候補探索とE4/E5を一度に完遂できなければ、証拠のない昇格をしない。中断対策としてrun開始直後にdeadlineとmanifestを保存し、各pair完了時に追記する。次スレッドが現在の完了済み研究を「未完了」と誤認して再実行しないよう、完了済み・実行中・次の一手を分けて残す。

## 9. Holdout、記録、再現

前回記録ではpromotion `10091101–10091112`、Fresh `10091901–10091912`は未使用。今回アクセスしたreplayは既使用Development `10091011–10091014`のcontrolのみである。元の予約8 replayはmetadataにoutcomeが含まれるので完全blindとは呼ばない。9月14日時点の別実験まで含む全利用履歴の監査は次runの差分確認で行い、前回の局所manifestだけをrepository全体の証明にしない。[9]

首位3198.2、Majkel1337という値は2026-09-12 13:33 JSTの取得記録で、9月14日の最新値ではない。今回の意思決定はその値へ依存させていない。次回開始時に最新Leaderboardを取得し、local V111とremote submissionの同一性が不明ならunknownを維持する。[2]

本再集計の再現commandは以下。出力済みファイルへの上書きは拒否する。

```powershell
./.venv/Scripts/python.exe scripts/reassess_research_20260914.py --output data/analysis/research_reassessment_20260914/reproduced.json
./.venv/Scripts/ruff.exe check scripts/reassess_research_20260914.py
```

古い報告書の一括再現commandをそのまま実行しない。`research_20260911.py audit`は保存済み初期auditがあると停止する。旧`aa`は結果を追記し、旧`paired`はcacheを再利用してsummary時間を書き換える。`postmortem_20260911.py`にはargparseによる`--help`がなく、渡しても解析を開始する。旧finalizerも結果と報告書を再生成する。今回は新しい出力先を持つ再集計だけを使った。[7]

## 参照

1. [今回の再集計evidence_v2.json](../data/analysis/research_reassessment_20260914/evidence_v2.json)、[再集計source](../scripts/reassess_research_20260914.py)。2026-09-14、ローカル既使用データ。各入力のSHA256、coverage、checkpoint、cycle、指標定義を保存。
2. [前回final_decision.json](../experiments/research_20260911_continuations/final_decision.json)、[9月12日報告](research_20260912_continuation_report.md)。勝敗・Safety・identityの一次実験集計。本文の過大な解釈は本書で補正。
3. [売却option](../agents/v115p_immediate/option.json)、[売却source](../scripts/continuation_option_template.py)、[managed source](../scripts/managed_animal_template.py)、[Cow保持source](../scripts/retain_cow_option_template.py)。対象範囲と開始・継続契約の根拠。
4. [round_robin.jsonl](../data/evaluation/research_20260911_continuations/complete_policy/round_robin.jsonl)、[独立source pilot](../data/evaluation/research_20260911_continuations/complete_policy/new_source_pilot.jsonl)。旧4 seedsに限定。
5. [V114 postmortem](../experiments/research_20260911_continuations/postmortem_recomputed.json)、[lifecycle source](../scripts/evaluation/lifecycle.py)、[凍結engine](../.venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py)。E0/E1と総policy効果、機構別coin寄与は未同定。
6. [A/A summary](../data/evaluation/research_20260911_continuations/aa/summary.json)、[Champion standalone](../experiments/research_20260911_continuations/champion_standalone.json)、[artifact verification](../experiments/research_20260911_continuations/final_artifact_verification.json)。実行の検証であり競技勝率の証明ではない。
7. [研究runner](../scripts/research_20260911.py)、[共通runner](../scripts/evaluation/runner.py)、[Safety](../scripts/evaluation/safety.py)、[postmortem command](../scripts/postmortem_20260911.py)。2026-09-14時点のsource確認。
8. [statistics](../scripts/evaluation/statistics.py)、[finalizer](../scripts/finalize_research_20260912.py)、[oracle集計](../scripts/analyze_continuations_20260911.py)。seed block、stress scenario、履行判定の範囲。
9. [前回Holdout記録](../experiments/research_20260911_continuations/final_holdout_audit.json)、[source registry](../experiments/research_20260910/source_registry.json)。局所的な過去利用記録。
10. Agarwal et al., [Deep Reinforcement Learning at the Edge of the Statistical Precipice](https://proceedings.neurips.cc/paper/2021/hash/f514cec81cb148559cf475e7426eed5e-Abstract.html), NeurIPS 2021。少数試行・点推定だけでの比較の危うさ。2026-09-14参照。
11. Lanctot et al., [A Unified Game-Theoretic Approach to Multiagent Reinforcement Learning](https://proceedings.neurips.cc/paper/2017/hash/3323fe11e9595c09af38fe67567a9394-Abstract.html), NeurIPS 2017。policy混合とempirical game。2026-09-14参照。

[次スレッドで使う実行プロンプト](codex_next_research_prompt_20260914.md)
