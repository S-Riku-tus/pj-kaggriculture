# Codexへの実装依頼：Kaggriculture Round3

このリポジトリのKaggricultureエージェントを改善してください。以下を新規スレッドの全前提として扱い、診断文書の作成だけで終わらず、修正・単体試験・必要な教師生成/学習・小規模閉ループ比較まで実行してください。ただし、合格していない版を強化版と称して提出してはいけません。

## 1. 目的と現状

ユーザーの最終目標はKaggleレート2000を越え、その後3000/上位を狙うことです。round1の学習Bを提出したオンライン成績はユーザー報告で1600弱でした。round2は既に実装・学習・ローカル評価済みですが、A2/B2はREJECTED、BC2はPARTIALです。現時点で新しい昇格候補はありません。

参照対象をリポジトリ内で特定してください。

- `experiments/learning_round2_20260921/`
- `agents/learning_round2_20260921/`
- `scripts/learning_round2.py`
- `agents/learning_next_20260921/`
- `artifacts/submissions/`
- 本依頼に添付した `Kaggriculture_Round2_Audit_20260921.md` と監査evidence ZIP。

ローカルの実パスが異なれば探索してください。旧実験、C0、モデル、manifest、未追跡の証拠、過去のverdictを上書きしないでください。Round3用ディレクトリ・study IDを新設してください。

今回の監査入力ZIPのSHA-256は `cd94e3ade1a7bd0072e7e7db688ee32685059d0fc66be62acb93fbe7d3a57220` です。

## 2. 提出互換性の絶対条件

過去に `learning_next_20260921_b_learned_fixed_v3.tar.gz` でようやくKaggle提出に成功しています。既知のSHA-256は `f1aede2a9f4a8ad0b8f3b3cd41d1f49708b713ca1cbc4221df472dcba1201105`。元版、fixed、fixed_v2を提出成功基準に戻さないでください。fixed_v3実体をローカルで見つけてhashを照合し、見つからなければ未確認と明記してください。

従来の問題は、Kaggleの空globals exec、`__file__`/`__name__`がない状態、最後のcallable選択、NumPy/.npzやリポジトリ相対importへの依存です。

Round2の6アーカイブではこれが再発しています。

- A2系列：空globalsでは `KeyError: '__name__' not in globals`。変数を与えて読み込めても最後のcallableは`policy_trace`。
- B2系列：空globalsでは `NameError: __file__ is not defined`。変数を与えて読み込めても最後のcallableは`policy_diagnostics`。
- 全6件：NumPyを利用不可とする隔離試験で依存性エラー。
- 現 `package_round2()` はimportlibでmoduleを作り、`m.agent`を直に呼んでいるため、実loader試験になっていません。

提出用wrapper/モデル形式は既知の成功版に合わせて共有化してください。アーカイブから単独展開し、リポジトリ外・任意cwd・空globals・NumPy不在でも検査してください。最後に選ばれるcallableを実際にassertし、必ず`agent`にしてください。補助関数を後ろに追加してこの条件を壊さないでください。

固定した実 `kaggle_environments.agent.get_last_callable` / 実ゲームrunnerを使用してください。importlib直接呼出しは補助検査に留めてください。モデル変換前後の出力誤差、閾値付近の候補選択、完全行動の一致も検証してください。学習済み重みの読み込みに失敗したのに学習版として合格することは禁止です。

## 3. 独立監査で確認済みの結果

32条件は4公開実行可能family×4seed×両seat。familyは `mooman_e052a`, `qeinstein_moev2`, `smart_farm`, `souvik_v4`。seedは `2026092421`〜`2026092424`。これらは日付でなく乱数入力です。

| 方式 | 勝敗 | C0比・最終資金差の平均変化 | 行動差分ターン合計 |
|---|---:|---:|---:|
| C0 / A2_KEEP | 30勝2敗 | 0 | 0 |
| B1 | 30勝2敗 | +0.90625 | 46 |
| B2 | 28勝4敗 | −309.8125 | 122 |
| B2_frequency / B_simple | 28勝4敗 | −308.59375 | 114 |
| A2 | 23勝9敗 | −3096.78125 | 850 |
| A2_nonlearned | 20勝12敗 | −6659.1875 | 3373 |

監査では外部比較の保存リプレイ256件を読み、最終資金、行動差分数、最初の差分時刻がCSVと全件一致することを確認しました。ただし、新しい閉ループ対戦を再実行したわけではありません。また、保存ログの生成時のコード・モデルhashが全件独立に証明されたわけでもありません。

### 3.1 B1

B1は主に同一ターン内の売却順を変えます。23,008意思決定のうち差分46、約0.20%。勝敗改善はゼロ。上位の生産方針そのものを実行するモデルではありません。

`b_opportunity_headroom.json` は過去40試合の特定2候補について、事後の即時売上改善上限が合計2224、平均55.6/試合、B1実績が平均7.075/試合でした。この数値をゲーム全体の上限へ一般化しないでください。

### 3.2 B2：step264の系統的な誤判断

全32試合の最初の差分がstep264です。直前観測はC0と同一です。

```
C0: SELL MELON 12 → SELL FERTILIZER 13 → HIRE×5
B2: SELL FERTILIZER 13 → SELL MELON 12 → HIRE×5
```

変更直後の平均は自分−170.375、相手+138.4375、資金差−308.8125。最終差分−309.8125にほぼ一致します。30/32試合で作業者行動列は全てC0と同じです。

smart_farm/2026092424/seat0では、B2のMELON:h1出力がp=0.764112、qty=0.495358、FERTILIZER:h1がp=0.977170、qty=4.644242。qty>=0.5の条件でMELONが丸ごと消え、相手がFERTILIZER5だけ売る架空シナリオになります。現scorerはC0順2382、逆順2385と計算し、+3で変更します。

実際の相手はMELON12→FERTILIZER13。次状態の資金はC0が[16721,15917]、B2が[16549,16057]、相対差−312です。このseedの両seatが+54勝ちから−258負けへ変化しています。

B2のテストBrierは、h1:0.102336（頻度0.042202）、h4:0.128781（頻度0.120868）、h24:0.103009（頻度0.182708）。全体平均の改善でh1の劣化を隠さないでください。

正例重み付きBCEのraw sigmoidは元の発生確率ではありません。MELON:h1の重み20、FERTILIZER:h1は約6.517。数量も全例のlog1p回帰をexpm1した値であり、条件付き平均数量や無条件の算術期待数量ではありません。現p×qtyの意味を定義し直してください。

### 3.3 A2：データと正規化

全56行：KEEP24、非KEEP32。round1の非KEEP16はstep242のCOLLECT_DROP、全て負。round2の非KEEP16はstep246のCARE_COLLECT/COLLECT_CARE、全て差分0。正の教師はありません。

実trainは26行・12prefix、530特徴、12,794パラメータ。std<0.001の特徴が245。`max(std,0.001)`の正規化で未出現の0/1特徴が約1000になります。

外部32試合の最初の採用候補は凍結モデルで再現済み。全件でmax|z|=920〜1080、risk約9.36e-14、value0.392〜44.360。

特にmooman_e052a/2026092424/seat0/step242では、`history:own_sell:24:WOOL` が平均0.08から1.0となりz920。value43.664でCOLLECT_DROPを選択し、最終差−12235。分散ほぼゼロの次元を入力からゼロ化する診断ではvalue−3.516/risk0.413になり不採用です。同種6件が不採用になりますが、他の26候補はまだ採用されます。単純clip10も完全な修正ではありません。これは入力診断であり新方策の実戦成績ではありません。

### 3.4 A2：実行後に元経路へ戻れていない

mooman_e052a/2026092424/seat0/actor8では、C0のstep242 PICKUP WHEAT5とstep243 FEEDが、A2のCOLLECT_FERTILIZER→DROPで消えています。その後step247、251などでWHEAT0のままFEEDします。step288ではC0が17頭、A2が15頭となり、牛(5,3),(5,4)が失われています。

FERTILIZE_WATERの例ではWATER→NORTHをFERTILIZE→WATERで上書きし、NORTHが消え、後続経路の座標がずれます。

元方策を毎ターン一回呼ぶことと、元の計画へ復帰できることは別です。現在の位置だけのrejoin判定、メタデータだけのreservationsでは不足です。

初回job別の結果：COLLECT_CARE14試合は差分0、COLLECT_DROP6試合は合計−73508、FERTILIZE_WATER12試合は合計−25589。FERTILIZE_WATERは学習候補に一件もありません。

### 3.5 BC2

BC2はteacher56216119/episode111063979/seat0、step240〜311の72行で、完全joint actionを72クラスへ分類し同じ72行上で100%。runtime未統合、閉ループ0回です。未知状態に対する構造化行動生成の成功と呼ばないでください。

## 4. 作業段階P0：信頼できる比較・提出基盤

最初に変更前のgit状態と主要ファイルhashを保存してください。既存C0の設定フラグを確認し、基準版の挙動が変わっていないことを確認してください。C0のファイルサイズがB1内部baseと異なるだけで別方策だと誤判定しないでください。

新しいtask digestに以下を含めてください。

- ソースツリー全体、全モデル、設定、特徴schema、engine、opponentコードのhash
- seed、seat、ゲームconfiguration、変換済み提出artifactのhash
- モデル出力形式と実行器のバージョン

既存の `_result_from_completed_replay` のような「720状態あれば再利用」を廃止してください。sidecarがない、hashが合わない、seed/seatが不一致、終端status不正なら再利用不可です。壊れた旧証拠は削除せず隔離してください。

汎用名`common`などのimport衝突が再発しないよう、相手・方式ごとに隔離プロセスまたはユニークnamespaceを使用してください。モデルロード回数、hash、推論回数、選択候補、fallback理由、cold/warm時間を実際に記録し、resumeで欠損した値を実測扱いにしないでください。

P0終了条件：実アーカイブが固定実loaderでagentとして選択され、C0恒等性が保たれ、モデル/コードとリプレイの由来がhashで結び付いていること。

## 5. 作業段階P1：A3の学習前に、行動を壊さない仕組みを作る

### 5.1 固定回帰テスト

少なくとも次の事例を、seed/相手/時刻へのハードコードではなく、状態と制約を入力する一般テストにしてください。

- 必要なWHEATのPICKUPを消す候補を検出する。
- FEED前の所持WHEATと残り給餌数の予約が成立する。
- WATER→NORTHを上書きしてNORTHを失った後に、古い経路へ戻らない。
- DROPで将来使用する資材を全て降ろさない。
- 同一ターンの他作業者のPICKUP/PLACE/納品を含め、倉庫容量と資材予約が二重使用されない。
- 日付境界、作業者消滅/再雇用、actor index再利用でもjobを取り違えない。

### 5.2 継続計画の契約

候補に少なくとも次を持たせてください。

```
preconditions
actor ownership / identity
reserved materials / cash / shed capacity / time
complete continuation or explicit safe rejoin boundary
expected position + inventory + remaining obligations at rejoin
primitive success + economic postconditions
abort policy and replanning policy
```

`reservations`を表示するだけでなく、全体のexecutorで強制してください。候補実行後の最終joint actionにも修復・合法性・資源検査を掛けてください。

固定時刻に依存するC0を裏で進め続け、候補終了時にそのまま返す設計は不可です。短い差替えでC0への復帰を証明できる場合だけ復帰し、できない場合は当該作業者の残り経路を現在の観測状態から再計画してください。全体方策を巻き戻して他作業者を壊さないでください。

最初から自由な全方策を生成せず、限定した作業者/区間の安全な継続計画で始めてください。作業成功を金銭改善と混同しないでください。

### 5.3 正規化・サポート判定

二値/one-hotと連続特徴を分け、二値特徴へ学習std=0.001を適用しないでください。連続特徴は意味のあるスケールを持たせ、定数次元や未学習カテゴリを明示してください。平均・scale・範囲・学習サポートをschemaと共に保存します。

未学習job、学習範囲外の重大状態、nonfinite入力、モデル欠損ではKEEPまたは安全な再計画へ移行し、理由を記録してください。単純なclipだけを修正完了としてはいけません。

正の有効候補がないデータでは、モデルを強引に昇格させず `NO_POSITIVE_CANDIDATE_SUPPORT` としてください。この場合は候補生成へ戻り、正の利益候補を得るまで行動拡張を有効化しないでください。

## 6. 作業段階P2：B3を小さく正しく比較する

B3を主たるレート突破策と決めつけず、既知の誤判断を修正できるかの限定研究として扱います。

### 6.1 まず評価器の正しさ

固定エンジンと比較し、同一turnのworker処理後在庫、両者のordered market slots、SELL、BUY_PRODUCT、資金で実行可否が変わる注文、price floor、同時単位処理の価格見積りが一致することをテストしてください。

実相手のprivateや将来注文を与える試験はオフラインoracle診断限定です。agentの入力へ混入させてはいけません。

次の分解を同じ候補集合・同じ状態で行ってください。

1. 現予測＋現評価器
2. 現予測＋修正評価器
3. 単純予測＋修正評価器
4. 正確な品目別量だが順序を落としたoracle
5. 正確な順序付き注文oracle＋修正評価器

これで量、順序、評価器、候補集合のどこが利益を失っているかを測ってください。step264だけを禁止する修正、相手ID/seedによる分岐は禁止です。

### 6.2 予測の定義

イベントのraw sigmoidに重み付きBCEを使う場合、その値を未校正の確率として使わないでください。非重み付き確率学習、または適切な補正＋未使用校正集合を比較してください。

数量は、発生時の条件付き数量分布とイベント確率、または無条件の数量分布として定義してください。全例log回帰のexpm1を条件付き平均と呼ばないでください。

品目集計から固定PRODUCTS順の架空注文列へ落とすのではなく、順序とslotを持つ相手シナリオを使ってください。pが高いqty0.495を丸ごと消すような不連続処理を避け、数量不確実性をシナリオ/分布で扱ってください。

### 6.3 評価と使い道

h1/h4/h24、品目、price floor、actionable状態別にBrier/校正/数量誤差を出してください。採用の主目的は経済regretと対戦成績です。全27target平均だけでモデル選択しないでください。

現候補集合でoracle改善が小さければ、その結果を明記し、Bの大型化を止めて次節の生産・販売時期を含む継続計画へ資源を移してください。これは研究失敗ではなく、改善余地の小さい部分を切り分けた成功です。

## 7. 作業段階P3：1600帯を越えるため、候補集合を広げて価値を学ぶ

P0/P1を合格した後に、実行可能な複数ターンの計画を用意してください。まずは中盤の限定範囲でよいですが、step242と246だけを繰り返すデータ取得は禁止です。

候補例は、給餌→回収→配達をまとめた作業者経路、肥料配分と水やりの同時再設計、回収時期・販売時期・再投資の整合した計画です。特定作物や家畜を無条件に増やすだけのルールにせず、固定エンジンと価格・資金・作業時間で評価してください。

候補ごとに以下を測ります。

- 既存のどの作業を置き換え、その機会費用がいくらか。
- 資材、倉庫容量、雇用、土地、将来給餌の義務が成立するか。
- 計画実行後に本当に予定した状態へ到達するか。
- 即時売上だけでなく、終了時の勝敗と自分/相手それぞれの資金がどう変わるか。

C0、非学習スコア、学習選択、有限候補oracleを同じprefixで比較してください。oracleでも改善候補がなければ候補生成を直し、oracleは良いのに学習が選べない場合だけ教師・特徴・モデルを改善します。

教師は同じ完全状態と対戦相手方策からのpaired continuationで作り、元C0 rolloutも保持してください。prefixを独立サンプルのように水増しせず、episode/family/version/day帯/jobで分割・集計してください。候補取得は最初の一件だけで打ち切らず、局面・時刻・jobのカバレッジを確認してください。

最初はデータ規模に合う単純な価値/順位モデルも比較し、530入力に26行のMLPのような状況を繰り返さないでください。高次元化より、正の教師・実行の整合性・分布外拒否を優先します。

## 8. BC3は独立した後続課題

BC2の72クラス記憶を大量化するのではなく、farmer、ordered hands、op、item、quantity、market slot、STOPの構造化デコーダへ移行してください。数量を中央値へ置き換えず、完全な行動と停止を復元してください。

最初に完全action roundtrip、未使用episode上の完全行動一致、短いclosed loop、最後に全episodeと段階を分けてください。teacher-forced accuracy100%だけで方策として合格しないでください。

A3/B3の基盤検証が終わる前に全てを並行大型化しないでください。計算量と候補利益に基づき主経路を一つ選び、その理由を残してください。

## 9. 評価・資源・昇格

今回観察済みの外部32条件は次回からdevelopment/regression扱いです。次の最終判定に同じ条件を未使用holdoutとして再利用しないでください。

未使用seedと異なる戦略familyを分けて評価してください。公開実行可能コードと非公開上位本人を同一視せず、取得時点・コードhash・証拠強度を記録します。リポジトリの許可済みCLIで取得可能な公開情報は使ってよいですが、アクセス不能な相手を評価済みと記載しないでください。

評価前に、実用上必要な改善幅、検証件数、比較方式、途中打切り条件を固定してください。family×seedでpairedに扱い、両seatを独立試行として水増しせず、seed単位の感度分析とfamily別結果を併記してください。

最初にcold import、warm推論、1gameメモリを実測し、CPU/RAMに合うworker数にします。以前の多worker化で遅くなった経緯を踏まえ、無条件に16並列等にしないでください。

必須判定は次を分離してください。

```
SERIALIZATION_VALID
LOADER_VALID
TRAINED
MODEL_USED
SUPPORTED_STATE
ACTION_CHANGED
EXECUTION_VALID
ECONOMICALLY_BENEFICIAL
EVALUATED_ON_UNSEEN_CONDITIONS
PROMOTABLE
```

無介入へ戻して安全になっただけなら `SAFE_NO_EFFECT` であり、強化ではありません。弱い過去自作版への勝ち越しだけでも昇格させません。Kaggleレートへの数値換算や2000/3000達成の保証はしないでください。

## 10. 成果物と禁止事項

以下をRound3の成果物に含めてください。

- `ROUND3_PLAN.md`：変更前の事前計画、資源計画、評価条件。
- `REGRESSION_CASES/`：step264の市場事例、小麦受取消失、移動消失、未知job/定数特徴などの汎用テストfixture。
- `SOURCE_AND_MODEL_MANIFEST.json`：全hashと依存性、提出成功基準との照合。
- `LOADER_VALIDATION.json`：実アーカイブ・実loader・任意cwd・空globals・モデル変換前後一致の証拠。
- `NORMALIZATION_AND_SUPPORT_AUDIT.json`：型、定数次元、OOD理由、採用/拒否例。
- `EXECUTOR_CONTRACT_TESTS.json`：資源予約と再計画、復帰の検査。
- `ORACLE_HEADROOM_AND_REGRET.csv`：候補別、局面別、horizon別の分解。
- `paired_results.csv` とhash付きreplay sidecar。
- `MODEL_USAGE.json` と欠損を隠さないruntime測定。
- `REPORT_JA.md`：改善した点、悪化した点、未確認、次の一手。
- `handoff_evidence.zip`：必要なソース、schema、モデル、代表trace、テスト、再現コマンド。報告文だけのZIPにしない。

既存提出の撤回、Kaggleへの無断提出、無断課金、git reset/clean/force push、旧artifactの削除は禁止です。学習/評価を実施したと言う場合は実更新、model hash、実行ログを示してください。実施していない段階は未実施と明記してください。

まずP0→P1を実装して回帰事例を解消し、次にP2を限定的に比較してください。その結果からP3の利益候補生成へ進み、可能な範囲で学習と閉ループ検証まで完了してください。候補に利益がなければ、安全にC0へ戻すだけで終わらず、何の候補範囲に利益余地がなかったかを示し、次の候補生成を実行してください。
