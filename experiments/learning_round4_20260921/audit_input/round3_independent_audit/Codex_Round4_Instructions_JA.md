# Codexへの実装依頼：Round4 — 実行・評価の修正と、独立した上位模倣学習

この文書全体を、これまでの会話を知らないCodexへの入力として使う。単なる提案書作成ではなく、リポジトリを調べ、下記の不具合を再現・修正し、実際に動く次の研究版を作ること。実行した作業と未実行の作業を区別すること。

## 0. 目的と開発上の方針転換

対象はKaggleのKaggriculture。ユーザーはこれまでv109〜v125、learning round1〜3を開発しており、最近の提出は1600前後で、まず2000、その後3000以上を目指している。ただしこの文書で新規のオンラインレートを確認したわけではない。目標値を達成済みと書いてはいけない。

今回のユーザーの問題意識は、少数のローカル対戦や狭いproxyによって、有望な学習・戦略が提出前に止められていないか、という点である。上位の判断を状態条件付きで言語化し、それを再現する能力の向上も評価したい。これは「見た目が似れば強さを証明できる」という意味ではない。

次の4つを別々に判定する。

1. 意図した行動が正しく実行されたか。
2. 教師の重要判断・一貫した手順を再現する技能が向上したか。
3. 局所介入または戦略全体の経済価値が向上したか。
4. オンラインの対戦分布で強くなったか。

「C0へ小さな介入をした平均利益が正でなければ、上位模倣の学習すら禁止する」という依存関係は廃止する。現在の壊れたprobeを無検証で提出することも禁止する。限定オンライン試験に進めることと、championへの昇格は別にする。

## 1. 最初に読むもの・保存するもの

まず既存README、AGENTS.md、実験ディレクトリ、提出パッケージ、学習スクリプト、テスト、環境固定情報を調べ、実際の構成へこの指示を対応付ける。

入力資料：
- `learning_round3_20260921.zip`
- `Kaggriculture_Round3_Independent_Audit_JA.md`
- `source_contract_audit.json`
- `replay_diff_summary.csv` / `first_divergence_traces.json`
- `report_literal_mutation_tests.json`
- 同梱の3つの監査スクリプト

ZIPの `handoff_evidence.zip` に以下の実ソースがある。
- `agents/learning_round3_20260921/a3_probe_agent.py`
- `agents/learning_round3_20260921/contracts.py`
- `scripts/learning_round3.py`
- `tests/test_learning_round3.py`

独立監査は、16本の保存リプレイ再集計、41manifest hash照合、添付関数の実観測への適用、報告関数への人工入力テストを行った。新しいシミュレータ対戦・学習・提出を実行したものではない。修正後の経済改善はあなたが新規に測定する必要がある。

C0、旧モデル、元リプレイ、旧判定書、既存holdout台帳を変更・削除しない。新しいbranchまたはディレクトリへ実装し、上書きではなく追記監査とする。既に見た条件を未使用holdoutへ戻さない。作業開始時のgit statusとdiffを保存し、ユーザーの未コミット変更を破壊しない。

既知の提出成功基準は `learning_next_20260921_b_learned_fixed_v3.tar.gz`、SHA-256 `f1aede2a9f4a8ad0b8f3b3cd41d1f49708b713ca1cbc4221df472dcba1201105`。これはユーザー報告に基づく提出互換性の参照であり、Round3のC0と同一戦略という意味ではない。より新しい正常版を禁止する意味でもない。元版・fixed・fixed_v2へ戻さない。

## 2. Round3で実際に分かったこと

新規Round3学習は0回、モデルロード・推論0回、提出なし。既存C0の内部に過去のモデル資産があることと混同しない。

各arm4試合＝qeinstein_moev2 × seed2026092421両seat、smart_farm × seed2026092422両seat。独立なfamily×seedは2つ。結果は以下。

| arm | 平均Δmargin対C0 | 勝敗 |
|---|---:|---|
| feed_refill | -1089 | 全arm共通で2勝2敗 |
| feed_once_replan | -87 | 同上 |
| harvest_deliver | 0 | 同上 |

384候補のscanがあるが、候補ごとのcontinuation評価は行っていない。probeは `MAX_JOBS=1` で最初の候補を使う。384件は356給餌・28収穫。IDは36種類だが同じIDでも局面は異なる。収穫候補にはstep543/544が20件あり、step205の失敗だけでそれらを棄却できない。

この負の終局結果は捏造ではない。問題は、意図した戦術の完遂になっていないことと、そこから一般化した判定である。過去に有望な完成agentが実際に誤棄却された、と断定してはいけない。

## 3. 必須再現A：未成熟収穫と誤った成功判定

qeinstein_moev2、seed2026092421、両seat、step205、actor4、座標(0,1)。day8、WHEAT planted_day7、yield_units1。小麦の初回収穫年齢は2日だが、候補生成はyield_unitsだけで収穫を選ぶ。HARVEST前後のinventoryは空、タイルも不変。空荷で倉庫へ行き、日替わりでjobs_completedになる。

同じ実候補のcontractは、実行がHARVESTなのに `PICKUP WHEAT1 → FEED` となっている。reserve>0を給餌契約へ結び付ける `_contract()` の誤りを含む。

修正：
- 固定した実engineに沿うharvestability判定を共通化する。作物種、年齢、収量、所有・座標を扱う。
- job種別でtyped planを作り、契約と実際のprimitive列を同じ構造から生成する。
- 実在庫増分・タイル変化・対象actorの処理順を検査する。
- 発火、primitive発行、primitive成立、job完遂、経済効果を別カウンタにする。
- 空荷、未成熟、他actorの収穫、容量超過、日替わりだけで成功としない。
- 日末自動回収と倉庫容量を考慮し、無条件の「収穫後に倉庫へ移動」を正解にしない。

旧 `SAFE_NO_EFFECT` には監査追記として `HARVEST_PRECONDITION_FAILED / ECONOMIC_HYPOTHESIS_UNTESTED` を付す。元の履歴は残す。

## 4. 必須再現B：他actorの給餌を成功とみなす・復帰後に小麦が不足

同じqeinstein条件、actor5。
- step434：C0はPASS、probeはWHEAT1をPICKUP。
- step435：C0はWHEAT2をPICKUP、probeはFEED。
- 同step、actor4も同じ牛へ先にFEED。actor4小麦5→4、actor5小麦1→1。actor5のFEEDは無効。
- 次obsのfed_today=Trueでprobeは完遂を誤認。
- step436：元経路へ復帰。C0は小麦2、probeは小麦1。
- step437：一頭へ給餌してprobeは小麦0。
- step441：次の羊へのFEEDが失敗。

実 `validate_joint_action()` はこの重複へ[]、実 `rejoin_status()` はstep436でPROVEN_REJOINを返す。契約がminimum_inventory={}、remaining_obligations=0と嘘の前提になっている。本番probeはrejoin_statusやplan_preserves_obligationsを呼んでもいない。

修正：
- 同一対象・同一日のFEED/WATER/CARE等にサービス予約を置き、実engineのactor順に沿って重複を検出する。
- 給餌の成立は対象変化だけでなく、どのactorの小麦が消費されたかで帰属させる。成立条件を正確に満たすが観測だけで帰属できない場合はUNKNOWNとする。
- 元計画が失うPICKUPを検知し、今のjobだけでなく残り義務の小麦を計算する。
- 復帰証明は座標だけでは不足。actor identity/day epoch、残りinventory、時刻、他actorとの資材予約、元方策の内部進行状態を含める。
- 戻せない場合は実状態から残り経路を作り直す。文字列STATE_BASED_ACTOR_REPLANを付けるだけで実装済みとしない。
- C0を先に呼ぶことで内部ポインタが進む場合、介入後に同じポインタへ戻すだけでは安全でない。状態のcommit/rollbackまたは明示的な別executorを実装する。
- helperテストだけでなく、提出用agent entrypointを経由する再現試験を作る。

同一座標を禁止する必要はない。禁止するのは、無意味な二重サービスや資源競合である。

## 5. 必須修正C：評価器を証拠に従う純粋関数へ

`command_finalize()` に、ECONOMICALLY_BENEFICIAL=false、EXECUTION_VALID=true、NO_PROMOTION_CANDIDATE、4/4 negative / -87等が固定されている。人工データでpaired marginを正にしても、statusをERRORにしても判定は変わらない。これは元試合で正の利益やERRORがあったという意味ではない。また固定finalizerだけから、上流で有望候補が実際に除外された証拠とはしない。

次のような純粋関数を作る。名前は既存構成に合わせてよい。

```python
def evaluate_artifact(metrics, provenance, purpose, thresholds):
    # IOや暗黙のグローバル結論を持たない。
    # 各判定はPASS / FAIL / UNKNOWN / NOT_APPLICABLE。
    # evidence_idsと理由を必ず返す。
    ...
```

最低限の独立軸：
- PACKAGE_VALID：最終archiveそのもののロード・完走。
- EXECUTION_CORRECT：対象skillが意味的に成功したか。DONEだけではPASSにしない。
- TRAINING_EXECUTED / MODEL_USED：学習版のみ。ルール版はNOT_APPLICABLE。
- BEHAVIORAL_FIDELITY：未使用教師条件での技能再現。
- ECONOMIC_EFFECT：対象scopeでの効果と不確実性。未実行はUNKNOWN。
- ONLINE_EVIDENCE：オンライン結果があるか。
- READY_FOR_DIAGNOSTIC_SUBMISSION：試験に進めるか。
- CHAMPION_PROMOTION：本命を置き換えるだけの証拠があるか。

自動テスト：正利益、負利益、無発動、実行失敗、データ欠損、古いhashの証拠、ルール版、モデルをロードしただけで推論0、推論したが無効fallback、技能改善あり/経済未評価、win-loss tradeoff。各ケースでどの軸が変わるべきか検証する。

同じ固定version・同じmetricsからJSON/Markdownを生成する。試合件数、平均、reason、scopeを二重管理しない。runtime証拠のないrequired fieldをtrueへ埋めない。既知の実装破綻はhard failだが、局面依存のトレードオフを「勝ちが1件でも負けに変わるなら永久棄却」にしない。

## 6. 次の主経路：一貫した上位模倣policyを独立して作る

C0のPASSへの差込みだけを唯一の研究経路にしない。主経路として、1つの確認可能な教師提出versionから一貫した戦略を学習する独立版を作る。残差selectorは補助研究でよい。

最初にリポジトリ内の教師リプレイを調べ、episode/seat、教師submission/version、取得日、game engine/config、公開情報の範囲、由来と利用可能性を台帳化する。現在の上位であることが確認できない教師は、その不確実性をラベル化する。公開notebookの名前・説明だけで、現在上位本人の提出コードと同じとみなさない。

必要ならユーザーの既存Kaggle CLI・公開公式配布データを用い、利用条件とアクセス制限を守って取得する。非公開コードや相手の隠れinventoryを学習時だけ入力へ混ぜない。認証が未設定なら既存データで進め、未取得を明記する。データ不足を架空の教師で埋めない。

まず単一教師versionで因果を分ける。複数教師を使うなら自分の戦略modeで条件付けする。相手の秘密submission IDを実戦入力へ使わない。複数教師の混合自体を一律禁止しない。

## 7. 「上位の判断を言語化」を実行可能な技能カードにする

自由作文をLLMに採点させるだけで終えない。各カードは実例と反例を持ち、例えば以下を含む。

```json
{
  "skill_id": "animal_service_with_continuation",
  "teacher_submission": "実際に確認したIDまたはUNKNOWN",
  "evidence": [{"episode": "実ID", "seat": 0, "step_range": [434, 441]}],
  "observable_preconditions": [],
  "observed_plan": [],
  "inferred_intent": "観測事実ではなく推定であると明記",
  "alternative_plans": [],
  "required_resources_and_deadlines": {},
  "success_postconditions": [],
  "abort_and_replan_conditions": [],
  "counterexamples": []
}
```

上のstep値は今回の自作失敗例の説明用であり、上位教師の実例として流用しない。上位のカードには本当にその教師のepisodeを付す。

初期対象は2〜3種類に絞る。経営判断と、それを支える作業計画をセットで選ぶ。例は、動物群の維持・回収・小麦補充、収穫と土地転用、販売と次投資。優先順位は教師データでの頻度・利益への影響・現コードの失敗頻度から決める。

「未給餌だからFEED」「PASSが多いから悪い」「yieldが正だからHARVEST」等の単一条件は技能カードの完成形ではない。他actorの予定、期限、費用、残り経路、収穫可能年齢、終了までの回収可能性を含める。

## 8. 学習表現・段階的な訓練

既存の出力圧縮で行動の数量や市場注文順が失われていないか調べる。完全なactionをencode→decodeして同値に戻せるroundtripを先に通す。数量を種類ごとの中央値に置き換えるなど、教師の重要判断を出力不能にする表現を使わない。

推奨分離：
- strategy/plan selector：経営上の選択、維持/拡張/転用/売却など。
- multi-step planner：対象actor、対象tile、必要資材、期限、次の仕事を選ぶ。
- deterministic executor：公開ルール、移動、資材競合、同一ターンの処理順、完了検知。

小さく実装できる形を選び、巨大な新フレームワークを先に作らない。入力に必要なage、時刻、資材、資産、公開相手盤面、市場履歴、現在planを含める。学習時と提出時の特徴生成を共通にする。

訓練は、少数エピソードfitのsanity check → 教師version/episode単位の未使用分割 → learnerが自ら動くclosed-loop、の順で実際に行う。時間隣接frameをtrain/testへランダム混在させて高精度を演出しない。データ量が少なければその限界を明示する。

模倣学習を実行するためにC0残差候補の正利益を要求しない。checkpoint hash、optimizer更新回数、training/validation loss、重要判断別metric、再ロード推論、実際に変わった行動数を保存する。trainコマンドを用意しただけをTRAINEDとしない。

同じ技能を学習なしの明示ルールで実装した比較版を用意する。最初から学習が必ず勝つとは仮定しない。共通executorでルール版と学習版を比べ、改善がモデルか実行器かを分ける。

## 9. 教師状態だけで正解する問題を避ける

教師の状態へ1step予測を当てるだけでは不十分。自分がずれた後も動く必要がある。

実施可能な方式を証拠に合わせて選ぶ。
- 全状態復元が可能なら、teacher prefixから24/48/96step等の短いclosed-loopを行う。
- 復元できなければ、engineを初期化し当該prefixまで正しく再生する。隠れengine state/RNGを無視して観測だけを突っ込まない。
- 終局まで自律動作した結果を保存する。
- 最初の教師との重要分岐と、その後の資材・期限・行動不成立を追う。

窓長は初期候補であり、技能の完了に必要な長さへ変更してよい。

DAggerは実行可能で許可された教師へ、learnerが訪れた局面のラベルを問い合わせられる場合に使う。非公開上位のreplayだけでは任意の新状態の正解を得られない。探索器、ルール、人手で作った訂正ラベルは由来を別に記録し、上位本人の正解と偽らない。

## 10. 残差候補評価の改善

全384件を無条件に重い終局評価することを要求しているわけではない。まず状態×job family×期限帯の層化サンプルと予算を決め、各状態の複数候補とKEEPを比較する。結果を見てから都合よくscopeを変更しない。

台帳の状態：generated / applicable / scheduled / started / primitive_effect_observed / job_completed / economically_evaluated / skipped_reason。生成数を評価数に数えない。

候補の完遂に必要な資材確保、他actorの予約、継続・復帰を含めて反実仮想を比較する。失敗候補の収益は「現コードの実現収益」として残すが、成功した戦術の経済ラベルとして混ぜない。実行失敗例はexecutor改善用の負例へ回す。

常時介入arm平均が負であっても、状態条件で正の完遂候補が選べるならselector学習を検討する。すべての有効候補を評価したわけでない場合にNO_ORACLE_HEADROOMと書かない。

Round3のB3、step264の同じ2SELL順序は、32条件でC0側に利益があった。ここを同じ設定のまま拡大する優先度は下げてよい。ただし別の時刻・数量・販売待機・再投資の研究へ一般化して禁止しない。

## 11. 評価は「技能」「経済」「オンライン」を別々に出す

技能：重要判断別の精度、対象・数量・注文順、一貫したplanの完遂、未成熟収穫、重複サービス、資材不足、復帰失敗。単純なPASS一致率やactor順序だけの差を強さと混同しない。

状態：技能完了時の資材、稼働資産、期限残量、倉庫余裕、現金、将来義務。教師と同じ状態条件で比較する。人手で作った重み付き総合点だけで合否を決めない。

経済：self money、opponent money、margin、win/draw/lossを全て残す。局所と終局を区別する。介入の直接override回数とC0別軌跡に対する全action差分回数を分ける。

外部対戦：ローカルC0や旧自作版への勝ち越しを主目的にしない。使用可能な外部familyを種類別に分ける。公開代理コードが現在上位を代表するという未確認の前提を置かない。各family×seedの両seatは独立2標本に見せず、clusterとして扱う。小標本では不確実性を出し、統計的未達を能力ゼロと表現しない。

開発データと固定した未使用条件を分ける。ただし、広い研究継続・限定提出の可否を、小さなholdoutの単一閾値だけへ依存させない。結果を見たholdoutは以後開発済みとして記録する。

## 12. 最終archiveと提出の扱い

学習版は以下を実物で確認する。
- 最終tar.gzを展開し、実Kaggle loader/get_last_callableで最後のcallableがagentである。
- empty globals、__file__なし、任意cwd、提出環境にない外部sitepackagesなしで動く。
- NumPy不要の推論が必要な構成なら、実際にその条件で動作確認する。
- day/hourからのstep復元とseat1の観測差を扱う。
- archiveからの完全episode、両seat、モデルload/inferenceの証跡、silent fallbackがないこと。
- 性能・メモリ・時間制限、外部通信不要を検査する。

ルール版はMODEL_USEDをNOT_APPLICABLEとするが、同じロード・完全episode検査は行う。

重大既知不具合がなく、意図した技能が実際に発動し、明確な仮説があれば、ローカル昇格未達でもREADY_FOR_DIAGNOSTIC_SUBMISSIONという別状態を許可する。現在の壊れたRound3probeはその対象ではない。

Kaggle提出は勝手に行わない。ユーザーの明示許可がない限り、提出候補・hash・検査結果・未確定点・比較計画を渡すところまで。提出後の評価は同時期のcontrol、相手帯/戦略別、実発動、最初の失敗を重視する。初期レートの単一値を最終判定にしない。

## 13. 実行順序とリソース

A. 入力・環境・履歴を確認して独立監査を再現する。
B. 判定器と共通executorを修正し、実entrypointの回帰試験を通す。
C. 並行可能なら教師データ・技能カードを整備する。Bの修正待ちでもデータ整備や教師状態での学習は進めてよい。
D. 一貫した独立ルール版と模倣学習版を実装し、学習を実行する。
E. 閉ループで重要分岐を診断し、限定した候補評価と外部比較を実施する。
F. 最終archiveを検査し、状態表と実物をまとめる。

初期並列度は2程度を上限目安にし、既存マシンの空き・メモリから調整する。大規模GPU、有料API、クラウド計算を新たに使う前にユーザー許可を得る。性能不足なら実行可能な小さい実験へ落とし、未実行範囲を記録する。無限の全候補探索や、文書だけを増やす作業を優先しない。

## 14. 必須成果物と最終報告の形

最低限、以下を残す。
- `ROUND4_AUDIT_REPRODUCTION.md`：再現できた/できない監査所見と理由。
- 実行器の修正コード、実entrypointを通るテスト、変更前後の同条件trace。
- 純粋な判定関数、人工入力テスト、証拠hashを伴う判定JSON。
- 教師台帳、技能カード、episode単位の分割manifest、action roundtrip検査。
- 学習コード、実checkpoint、更新数/loss/validation/再読込推論の記録。
- 共通executor上のルール版と学習版のclosed-loop比較結果。
- candidate coverage ledgerと未評価の範囲。
- 提出候補が成立した場合のみ最終archiveとその完全episode検査。
- 現状態を軸ごとに示す最終表。研究継続、技能改善、経済効果、限定提出、本命昇格を分ける。

最終文章の順序：何を直したか → 実際に何を学習したか → 意図した行動が実現したか → どの条件で何が改善/悪化したか → 未検証は何か → 限定提出候補があるか。

途中で経済的正例が見つからなくても、模倣学習の実行を自動的に取りやめない。ただし教師データが無い、loaderが壊れている等の本当の阻害要因は隠さない。勝率や3000到達を約束しない。以前の不適切な門番を外すことと、実装品質を下げることを混同しない。
