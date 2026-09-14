# 次の5時間を、何の解明に使うべきか

2026年9月11日。対象repository: `pj-kaggriculture`。再調査開始時HEAD: `395362f`、working treeはclean。今回の目的は、前回の研究を再検証し、次回の実験の順序と判断基準を決めること。Agent変更、追加対戦、Champion昇格、Kaggle提出は行っていない。

**提案する最優先課題は「途中状態から正しく実行でき、V111の敗戦を勝ちへ変える代替行動が存在するか」の検証である。** 相手供給予測や経路選択器の高度化は、その存在を確かめた後に行う。V114の閾値調整から再開する根拠はない。

ただし、前回の「経路変更で維持作業が破綻した」という説明にも修正が必要だった。保存済みreplayの再集計では、強制切替による雑草化増加の大半は、既に残存収穫量がゼロになった作物の寿命終了である。一方、種不足のPLANTとSheep購入失敗は実際に起きている。**経済的に無害かもしれない寿命終了、実行不整合、相手への利益移転を分けて扱う必要がある。**

## 1. 現時点で確定していること

### 1.1 LeaderboardとChampion

Kaggle公開APIを再取得した。取得時刻は **2026-09-11 03:33:23 UTC / 12:33:23 JST**。首位はSpaTaro、**3137.6**、submission `56114097`。前回最終確認の3136.2を更新した。現時点で「3000を超えれば1位」という目標設定は正しくない。[取得したLeaderboard](../data/current_field_20260910/leaderboard_planning_20260911_033321.json)

| 順位 | Team | Rating | Submission |
| --- | --- | ---: | ---: |
| 1 | SpaTaro | 3137.6 | 56114097 |
| 2 | ymg_aq | 3042.4 | 56147428 |
| 3 | feel the agi | 3039.0 | 56132899 |
| 4 | Otter Vibe | 3033.0 | 56097405 |
| 5 | Majkel1337 | 3030.4 | 56148003 |
| 6 | binghua | 2999.0 | 56092906 |
| 7 | redblackbst | 2967.9 | 56148866 |
| 8 | c0nrad | 2964.1 | 56149454 |
| 9 | keiz | 2962.7 | 56141084 |
| 10 | Gleb Tumanov | 2958.7 | 56149996 |

凍結すべきproduction Championは引き続きV111。前回記録のsource SHA256は `699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660`、archive SHA256は `85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e`。次回開始時にも再照合する。最新の自分のremote submissionと、この凍結artifactの同一性は未確定である。近いaction列は同一artifactの証明にならない。[前回identity監査](current_state_20260910.md)、[提出action照合](../experiments/research_20260910/latest_submission_action_fidelity.json)

したがって、remoteの1347.3をV111の現在実力と断定することも、古い対戦成績から現在の2500級・3000級を推定することもできない。現状の適切な表現は「V111の現在の絶対実力は未同定、新たな強い公開policy群に対して大きな課題がある」。

### 1.2 前回結果の射程

| 対象 | 実際の結果 | 言えること | 言えないこと |
| --- | --- | --- | --- |
| V114 original | checkpoint実行時のconfig引数不整合 | 実装バグで不適格 | 戦略の良否 |
| V114r1 | 32組で発火0、V111と12W/20Lで一致 | treatment delivery failure | 適応戦略が効かない／有効 |
| V114probe | 24組発火、全32組で0W/32L、L→W=0、W→L=12 | この強制suffixは棄却 | すべてのstate-dependent continuationの否定 |
| H2終端への売却追加 | 小さな在庫しか残らず、勝敗反転の機会なし | この限定された介入の優先度は低い | 終盤数日を含む再投資・収穫・換金の最適化全体の否定 |
| 相手供給ridge | strict splitで供給量MAE改善 | E2の予測能力 | 対戦勝率改善 |

前回のREJECTは維持する。E4/E5は未実施であり、「効果がないと証明された一般仮説」と「まだ介入が成立していない仮説」を混同しない。[前回最終報告](v114_research_and_evaluation_report.md)

## 2. 今回の再分析で、新たに重要になったこと

### 2.1 雑草化増加を、水やり崩壊と解釈してはいけない

既存の`replay.py`、`safety.py`と、実際のengineのfield action・寿命減衰・日次refreshを使い、**既に使用済みのDevelopment、発火24組、t153〜718**を再集計した。新規対戦やholdout閲覧は含まない。

| 作物→雑草の直接原因 | V111 | 強制切替 | 差 |
| --- | ---: | ---: | ---: |
| 水切れ | 120 | 75 | -45 |
| 寿命終了 | 360 | 473 | +113 |
| 合計 | 480 | 548 | +68 |

全24組で水切れ死が減り、寿命終了が増えた。寿命終了直前の残存収穫量を見ると、ゼロのケースが **288→425**、1のケースが **72→48**。つまり寿命終了件数の増加を、そのまま追加の収穫損失と呼ぶこともできない。この表は雑草へ変わった瞬間の分類であり、それ以前の全減衰量、作物構成・栽培本数による露出差、清掃の機会費用を測ったものではない。

分類不能は0件。再分類した各組の雑草化差は、保存済みの元Safety集計の差と全組で一致した。これは**原因分類の修正**であり、前回のhard gateを事後的に緩める変更ではない。前回candidateは勝敗でも明確に悪化しているため、棄却を覆す理由にならない。[再計算JSON](../data/analysis/next_research_20260911/postmortem_recheck.json)、[再計算スクリプト](../scripts/analyze_next_research_20260911.py)

次回は、raw雑草件数に加えて、水切れ、残存収穫物の減衰、収穫済み作物の寿命終了、空き地へのrandom発生を別々に記録する。現行promotion基準は維持し、意味論を変更する場合は、古い失敗作の救済と切り離した新しい事前登録で扱うべきである。

### 2.2 cash feasibilityだけでは実行可能性を表せない

強制切替の発火24組すべてに、t153〜215内のatomic PLANT blockとSheepの購入不成立が存在した。ただし対照側にも同区間のPLANT blockが16組あり、「発生した」だけで新規障害と数えてはいけない。

具体例は`mooman_e052a / seed10091012 / seat0`。t186で所持金759がある一方、Strawberry seedsは0、actionはStrawberryのPLANTであり不成立となる。これはその時点の資金不足ではなく、必要な種が作業開始時にないという**調達と作業の不整合**である。t192では先行する注文の後、Sheep購入が不成立となり、次のstateのcashは365。二つは別の失敗機構である。[当該treatment replay](../data/evaluation/research_20260910/v114probe/replays/development/mooman_e052a/seed_10091012_seat_0/treatment.json.gz)

次回のcontractには、残高だけでなく、種・shed・運搬中在庫・worker位置・field action先行・market注文順・同時PLANTのatomic validation・shed容量・日次resetを含める必要がある。不可逆な変更後に、元の固定scheduleへ単に戻すことも安全とは限らない。

### 2.3 V114r1のQは、実行可能性を保証する収支計算ではない

[V114r1 source](../agents/v114r1/main.py)をengineと照合すると、以下の差がある。

| 近似の内容 | なぜ判断を誤り得るか |
| --- | --- |
| raw routeのSELL予定数量を収益へ計上 | 実際にshedへ届いた在庫や作業の成功を保証していない |
| BUY_PRODUCTのWheat=25、Fertilizer=100 | engineは`market_price(item, inventory-1)`で動的に価格を決め、market在庫も減らす |
| field・運搬・給餌・実約定を追わない | cashが正でもPLANT/PLACE/FEEDが成立しない |
| Town消費を連続流量として扱う | 4turn/24turnのphase、注文との先後関係を失う |
| 未公開shopを平均需要へ置換 | 価格関数が非線形なので、平均需要から得た価格は期待価格と一致しない |
| 現在の相手portfolioを長期間固定 | 相手の増資・作物変更・反応を表現しない |
| 相手供給を0.75/1/1.25倍して最悪値を採用 | これは選んだscenarioに対する頑健性であり、校正された信頼下限ではない |

上述のmooman例ではt188のWheat購入1個でcashが759→725となり、実費は34。固定費25と一致しない。README/AGENTSのゲーム説明に「fixed prices」と書かれていても、凍結engineの実装をmechanicsの根拠にする必要がある。[engineの購入・commit処理](../.venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py)

**推論:** Q誤差の一部を改善するだけでは足りない。まず近い将来の注文と資源移動をengine通りに扱い、その上で不確かな相手行動と未来需要をモデル化する順序が妥当である。t192の予測不足額だけを調整し、閾値を下げる研究は優先しない。

### 2.4 自分の経済が改善しても、対戦では悪化する

32組を再集計すると、自分の最終coinが増えたのは9組。そのうち5組はmarginが悪化し、すべてW→Lとなった。marginが改善した4組にもL→Wはない。

| 相手 / seed / seat | Δself coin | Δopponent coin | Δmargin | 勝敗 |
| --- | ---: | ---: | ---: | --- |
| ggmljs / 10091012 / 0 | +19,980 | +49,270 | -29,290 | W→L |
| ggmljs / 10091014 / 0 | +37,242 | +47,830 | -10,588 | W→L |
| qeinstein / 10091013 / 0 | +24,955 | -32,640 | +57,595 | L→L |

これは「相手との相対収益が重要」という直接の対戦証拠である。一方、この数字だけでは、どの商品の価格外部性、相手のpolicy反応、Town変化が何coinを説明したかまでは分からない。改善したseedだけをwhitelistする根拠にもならない。[元paired records](../data/evaluation/research_20260910/v114probe/development/pairs.jsonl)

### 2.5 same seedでも、Townを固定した比較にはならない

engineは日ごとのseedからRNGを初期化し、空き地のweed抽選を実行した後にTown shopを抽選する。自分の畑構成が変わるとRNGの消費数が変わり、同じseedでも将来Townが変わり得る。実際、前回にはt216などでTown divergenceがある。

対戦の主解析は**元engineのままのpolicy変更による総効果**とする。Town divergenceした組を除外したり、事後的に同じTownの組だけで勝率を比較したりすると、介入後の変数で選別してしまう。原因分解のためTownやRNGを固定した補助実験を行うなら、改変engineの診断として分離し、promotion根拠には使わない。[first divergence audit](../data/evaluation/research_20260910/v114probe/development/first_divergence_audits.json)

## 3. 次回の研究を決める依存関係

現在の課題は、おおむね次の四段階に分けられる。

1. **実行可能性:** 途中状態から代替行動を実行し、必要な資源・約定・作業・継続管理を成立させられるか。
2. **選択肢の価値:** 実行できる代替行動に、現実の相手へ勝てるものがあるか。
3. **選択能力:** その違いを、liveで見える情報から事前に識別できるか。
4. **一般化:** 未使用seed、未見policy family、metaの重み変更でも改善が残るか。

V114r1は第3段階のselectorを実装したが、発火しなかった。forced probeは第1段階に不整合があり、第2段階の勝敗でも悪化した。したがって、いきなりselectorを大きなmodelへ変更するのは、依存関係を逆にたどることになる。

相手供給予測のstrict E2結果自体には価値がある。H72供給MAEは、Strawberry 3.876、Milk 3.219、Wool 4.157で、全体平均baselineの27.090、9.940、9.532を下回る。しかし次回に必要なのは、既知のday・crop age・portfolioを使う強いbaselineに対する増分価値と、**選ぶ行動が変わり、その結果勝敗が改善するか**である。長いhorizonの「一度でも売る」hazardはほぼ常に真になりやすく、近い1〜4turnの売却phaseを直接説明しない。[相手供給報告](opponent_supply_estimation_20260910.md)

## 4. 研究仮説の優先順位

順位は期待uplift、証拠、検証容易性、実装・解釈リスクを合わせた定性的判断。効果量を数値で予測できるだけの証拠はない。評価基盤整備は競技上の直接改善仮説ではなく、以下の検証の前提である。

| 順位 | 仮説 | mechanismと根拠 | 証拠段階 | 上振れ / 主な失敗 | 実装・評価 |
| --- | --- | --- | --- | --- | --- |
| 1 | 実行contractを持つ小さな継続行動 | 種・cash・運搬・約定を一体で成立させ、別の経済へ移る。現行suffixに具体的な不整合 | E0＋失敗E3 | 中〜大 / 実行できても勝てない | 中。局所windowでdelivery確認後、全期間paired |
| 2 | 現在の強い公開policyを全体の比較基準にする | V111への局所修正で残る上限と、強いcomplete packageとの差を測る | E3の対戦材料あり | 大の可能性 / sourceへの過適応、独立性不足 | 低〜中。まず無改変round-robin、移植は別実験 |
| 3 | 限定的な売却phase・価格外部性制御 | 自分の利益増が相手の利益増に負けた5組を起点に、特定market介入を比較 | E3の総効果、機構未同定 | 中 / 自分の運転資金を壊す | 中。既存market executorを使った単一介入 |
| 4 | 少数routeのstate-dependent selector | 経路別の実際の勝敗差を学び、十分な差がある時だけ選ぶ | 有効なselectorのE3なし | 大 / library自体に勝ち筋がない | 中。順位1・選択肢価値の確認後 |
| 5 | 相手供給予測を意思決定へ追加 | 需要と両者供給の差から将来混雑を見積もる | strict E2 | 中 / MAEだけ改善、変更後stateへ外挿 | 中。forecast有無のpaired ablation |
| 6 | Carrot等の希少需要への限定移行 | Top replayの差を、小面積・短い契約で検証 | E0/E1 | 中〜大 / 作業・収穫期限・種費の増加 | 中〜高。作物だけ置換しない |
| 7 | commitmentを遅らせる行動 | 次shopを待つ情報価値と増産遅延を比較 | 主にE0の仮説 | 中 / 複利的な成長を失う | 中。保留期間と回復経路を固定 |
| 8 | 収穫・寿命・清掃の局所調整 | 実際の未回収yieldや手数を減らす | 今回E0/E1再分類 | 小〜中 / 空作物の自然終了を誤って最適化 | 低〜中。失われたunitsの算定が先 |
| 9 | 終盤数日のhorizon最適化 | 末尾の売却追加でなく、再投資停止と収穫・換金を合わせる | 限定H2は否定的 | 不明 / 元scheduleの換金を妨げる | 中。末尾1turn調整は低優先度 |
| 10 | Mixed opening / PSRO | 相手群への対抗関係を混合する | cycle未確認 | 条件付きで大 / 無根拠な複雑化 | 高。payoff matrixで循環が再現した場合のみ |

次回のPrimaryは1を基本とする。ただし、短い監査で「現在の強い公開policyの全体比較の方が、改善可能性を明らかにしやすい」と分かった場合は2へ変更し、その理由を実験前に記録する。Primaryを名前だけ固定し、証拠に反して続ける必要はない。

## 5. 経路libraryは、行動列から実行条件を持つpolicyへ

少数の継続行動を作るなら、最初はbaselineを含めて2〜3個でよい。各行動を次の組で定義する。

`開始可能な状態 / 実行中のpolicy / 終了・中断条件 / 終了後に必要な管理`

これは時間をまたぐ閉ループpolicyを扱うoptionsの考え方に沿う。ただし、optionsという形式だけでこの競技での有効性が保証されるわけではない。[Sutton, Precup, Singh, 1999, 著者掲載論文](https://incompleteideas.net/609%20dropbox/other%20readings%20and%20resources/Options.pdf)

初期案は、既存の配置と運搬を大きく変えない、1回の注文・1区画・1収穫cycle程度の境界を持つ行動。Carrot、追加Sheep、待機などの名称を先に決めず、live lossesに対して実行可能性と勝敗感度のあるものを選ぶ。24〜72turnで直接必要な資源と作業を厳密に追い、影響する管理は最終turnまで担当させる。

重要なのは、開始できない状態を明示的に除外することと、変更後にbaselineへ戻れる条件を検証すること。現金だけを見て開始し、後から通常scheduleへ戻せば安全、という設計を避ける。

不確実な領域ではbaselineへ留まる考え方は、SPIBBなどのsafe policy improvementにも見られる。ただし同論文は特定のBatch RL/MDP条件の下での保証であり、部分観測・相手反応・少数lineageを持つ本件へ保証を移せない。ここでは設計原則として参考にする。[Laroche et al., ICML 2019](https://proceedings.mlr.press/v97/laroche19a.html)

## 6. selectorを作る前に、選択肢の上限を調べる

使用済みDiscovery/Development上で、同じ相手・seed・seatから、baselineと各実行可能routeを最後まで実行する。`U_j(r)`をwin=1、draw=.5、loss=0とする。

`当該標本での楽観的上限 = mean_j[max_{r ∈ feasible library, baseline含む} U_j(r) - U_j(baseline)]`

これは各組の結果を見てから最良routeを選ぶ**offline oracle診断**であり、実装可能なpolicyの勝率でも、母集団に対する厳密な上界でもない。安全性を満たさないrouteは候補集合から除外する。

この限定された診断ですらL→Wが見つからないなら、そのlibraryに対してselectorや供給予測を複雑化する期待値は低い。別のroute、別の意思決定時点、あるいはcomplete packageの比較に研究予算を振る。少数例のゼロを一般的な不可能性の証明とはしない。

逆に、複数の状態・相手で安全なL→Wがあり、どのrouteがよいかが状態で変わるなら、初めてselectorが必要になる。その学習には相手・seed・episodeの分離を維持し、未来の結果やprivate stateをlive特徴量に混ぜない。最初は小さなgateで十分。marginは機構診断や補助学習に使えても、promotionはpairwise outcomeで決める。

供給予測を使う場合は、同じlibraryと同じ他のロジックで、予測なし／public farmの単純なcalendar推定／strictに検証したmodelの追加価値を段階的に比較する。一度にroute、forecast、selector、売却phaseを変更しない。

## 7. 評価poolは、強さと独立性を別々に改善する

新しい公開policy群は旧Gold poolより有用だが、そのまま現在metaの独立サンプルではない。前回Developmentは次の通り。

| 実行可能policy | V111 W/L | 強制切替 W/L | 用途 |
| --- | ---: | ---: | --- |
| mooman_e052a | 2/6 | 0/8 | 強いanchor、近い勝敗もある |
| souvik_v4 | 0/8 | 0/8 | 強いanchor、改善感度の確認が必要 |
| ggmljs_v16 | 8/0 | 0/8 | regression検出に有効 |
| qeinstein_moev2 | 2/6 | 0/8 | 異なる構造の強いanchor |

Discoveryと合わせた8seedでは、ggmljs以外のV111勝率はいずれも2/16=12.5%。したがって、30〜70%程度の感度のよいpoolを十分確保したとはいえない。ただし0%や100%の相手を捨てるのでもなく、強いanchorとregression用として残す。

mooman、souvik、ggmljsにはPSR/Kaitoのsource ancestry重複がある。四つの実行ファイルを四独立familyと数えない。同時に、共通祖先があるからすべて同一行動policy、と断定するのも誤りである。次回は**source ancestry graphと、観測された行動・反応・payoffの分類を二軸で保存する**。保守的な祖先mergeでは二群にとどまることを明記する。

追加取得は、同じopeningのepisode数を増やすことより、未取得の実行可能で異なるpolicyを優先する。完成した720-state実行とnative entrypoint確認を、source registryのvalidation追記に結びつける。既存manifestの「validation pending」を黙って書き換えて履歴を失わせない。replayだけの相手はBronzeのままである。

V111を含む5policy、8seed、両seatの全round-robinは、10対戦組合せ×8×2=160ゲームである。最初に実測throughputを測り、重要な未測定matchupから実行する。complete packageが強い場合でも、V111を直接上書きせず、全体比較は全体効果として扱う。そこから一部だけ取り込む変更は、別の介入として評価する。

## 8. 評価系で先に修正・固定すべきこと

**A/Aとtransaction checkpoint。** V114r1の2件のtransaction failureは、route介入t153を、継承されたCow→Sheep取引t248の監査時刻として渡したための誤判定だった。次回は単一の`transaction_step`を使い回さず、介入と継承取引を別々に定義する。generic frameworkを再利用し、旧実験のraw結果と補正記録は保持する。[補正記録](../data/evaluation/research_20260910/v114r1/development/transaction_checkpoint_adjudication.json)

**要求・発行・約定・状態変化。** 予定した注文、実際にAgentが返したaction、engineのcommit、種や持ち物や配置の変化をつなぐ。SELL99に対し在庫5を売ったpartial commitと、必要なSheepを買えなかった失敗を、同じ意味の障害として数えない。新しいSafety定義を後から結果に合わせて変更しない。

**不確実性。** 両seatは同じseedのblockとして扱う。複数policyに同じseedを使うならseedはpolicyを横断する依存要因であり、family内だけ独立bootstrapして精密なCIを主張しない。対戦差分を維持したseed blockと、source ancestryへの感度を示す。少数二祖先からcurrent Top全体への一般化CIは作れない。RL評価文献のstratified bootstrapや分布表示は参考になるが、独立性が増える方法ではない。[Agarwal et al.の公式rliable repository](https://github.com/google-research/rliable)

**数と判断。** 2family×2seed×両seat×2arm=16ゲーム程度のpilotは、runtimeとdeliveryの早期棄却に使う。4policy×8seed×両seatなら64pairs=128ゲームのDevelopmentになるが、それだけでE4達成とはしない。E4では独立性と感度を満たすpool、事前に固定したseed数・gate・重み、十分な発火を必要とし、予算不足はPROMISING_UNPROVENと報告する。

勝率のpoint estimateに加え、L→W、W→L、D→W、W→D、lineage別結果、worst major lineage、source/ancestry重み変更、seed blockによる不確実性を出す。真のmeta頻度が不明ならequal weightやstress weightと明記する。Bradley–Terry値は診断であり、Kaggle Ratingへ換算しない。

PSROは相手混合へのbest responseとempirical gameを扱う方法である。現在は再現する非推移cycleが未確認なので、まずpayoff matrixを取得することに価値があり、PSRO自体の実装は後順位となる。[Lanctot et al., NeurIPS 2017](https://proceedings.neurips.cc/paper/2017/hash/3323fe11e9595c09af38fe67567a9394-Abstract.html)

## 9. Fresh Holdoutと、次の5時間の分岐

前回のpromotion seeds `10091101–10091112`、fresh seeds `10091901–10091912`は未使用として記録されている。使用履歴を確認してから割り当てる。8個のreplay予約はbody未見でも公開metadataにoutcomeを含み、完全blindなholdoutではない。現在の分析に用いたDevelopmentや、本報告の再分析対象はすべて使用済みである。

旧`research_20260910.py`はDevelopment以外を拒否する。次回は新しいexperimentを事前登録し、既存framework上でqualificationを実装する。旧失敗実験の封印を外して「続き」として昇格を通してはいけない。

| 時間目安 | 作業 | 次へ進む条件／打切り |
| --- | --- | --- |
| 0–25分 | 差分監査、hash・engine・remote identity・holdout状況、A/A設計 | 既存の全監査を再実行しない。remote identity不明はlocal実験と分けて記録 |
| 25–60分 | 本報告のpostmortem確認、transaction監査整備、source分類・追加取得を絞る | 種・約定・自然寿命の分類ができる。新データ取得だけで時間を使い切らない |
| 60–150分 | 1つのcontract付き継続行動とbaselineを比較。必要時に第2候補へ | deliveryが成立しない候補は修正か棄却。勝敗上限がないlibraryにselectorを追加しない |
| 150–225分 | 勝ち筋があれば最小gateを作り、使用済みdataでE3評価 | 実発火、Safety、L→W/W→Lを確認。0発火なら競技改善を主張しない |
| 225–280分 | 資格を満たす場合のみE4と一度限りのE5 | source不足、統計不足、Safety失敗ならholdoutを開かない |
| 280–300分 | 完成artifact、再現手順、判断、次の具体的課題 | PROMOTE/REJECT/PROMISING_UNPROVENを証拠に合わせる |

5時間で3000級を証明できるとは約束できない。次回の望ましい到達点は、優先順に、(1) 多様な相手とfresh dataで確認できた勝率改善、(2) 未昇格でも安全なL→Wを持つ再現可能な候補、(3) 代替libraryの限界と、より有望な研究baseを具体的に示した否定的結果である。

## 10. 次回Codexへ渡す文脈

次回プロンプトは、目標、読むべき具体的artifact、変更範囲、完了条件を分けて書いた。これはOpenAIのCodex向け推奨構成に沿う。一般論の禁止事項を増やすより、今回分かった失敗条件と、次の実験で通すべきgateを明示する。[OpenAI: Codex best practices](https://learn.chatgpt.com/guides/best-practices)

[次回実行用の完全なプロンプト](codex_next_research_prompt_20260911.md)を用意した。ユーザーが次に求める実行タスクであり、この分析タスク中にその実装を先行させていない。

## 参照資料と証拠の限界

| 資料 | 種別 | 本報告で支える判断 | 限界 |
| --- | --- | --- | --- |
| [最新Leaderboard JSON](../data/current_field_20260910/leaderboard_planning_20260911_033321.json) | Kaggle一次取得 | 首位3137.6、Top10 | 取得時点のみ、policyの実力因果証拠ではない |
| [前回最終report](v114_research_and_evaluation_report.md) | 研究記録 | Champion、実験経緯、E3とholdout状況 | 原因説明を本報告で再評価 |
| [paired JSONL](../data/evaluation/research_20260910/v114probe/development/pairs.jsonl) | 一次実験出力 | W/L、相対coin、介入発火 | 4seed、source重複、Development |
| [postmortem JSON](../data/analysis/next_research_20260911/postmortem_recheck.json) | 使用済みreplayのengine再集計 | weed原因、初期不成立注文 | 機構別の最終coin効果は未分離 |
| [V114r1 source](../agents/v114r1/main.py) | 一次実装 | Qの在庫・価格・Town近似 | 修正による勝率改善は未検証 |
| [engine source](../.venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py) | 実行mechanics | 動的購入価格、処理順、寿命、RNG | 次回version更新の再確認が必要 |
| [current meta分析](current_meta_analysis_20260910.md) | replay記述分析 | 共通openingと異なるcontinuation | 9月10日cohort。最新順位と混同しない |
| [strict supply研究](opponent_supply_estimation_20260910.md) | E2 | 公開情報からの予測可能性 | 意思決定の追加価値は未確認 |
| [Sutton et al., AIJ 112:181–211, 1999](https://incompleteideas.net/609%20dropbox/other%20readings%20and%20resources/Options.pdf) | 原著 | 時間をまたぐclosed-loop policyという設計 | 本競技での効果保証なし |
| [Laroche et al., ICML 2019](https://proceedings.mlr.press/v97/laroche19a.html) | 原著 | 不確実な領域でbaselineを保持する原則 | SPIBBの保証条件は本件で未充足 |
| [Agarwal et al., NeurIPS 2021 / rliable](https://github.com/google-research/rliable) | 著者の公式実装 | 分布と不確実性を示す評価 | seed/source独立性を代替しない |
| [Lanctot et al., NeurIPS 2017](https://proceedings.neurips.cc/paper/2017/hash/3323fe11e9595c09af38fe67567a9394-Abstract.html) | 原著 | empirical payoffと混合相手への応答 | 現時点でPSROの導入根拠は不足 |
| [OpenAI Codex best practices](https://learn.chatgpt.com/guides/best-practices) | 公式documentation | 次回promptの目標・文脈・制約・完了条件 | 研究結果を保証するものではない |

本報告の最重要な修正点は、**「不適格なsuffixを棄却した」ことと「適応の方向性を棄却した」ことを分け、さらに「雑草化した」ことと「収穫・維持に失敗した」ことも分けた**点にある。次の判断を変える証拠は、実行可能な選択肢のpaired outcomeと、それを事前に識別できるかどうかである。
