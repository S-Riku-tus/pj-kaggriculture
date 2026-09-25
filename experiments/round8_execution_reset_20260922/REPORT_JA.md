# Kaggriculture Round8 execution reset 実施報告

## 結論

今回の作業では、Round7の具体的な実行欠陥を固定engine 1.32.7に合わせて修正し、同一重みのF0/F1/F2対照、位置情報を持つ独立BCの実訓練、自由実行、通常開始の新規対戦まで実施した。

最終判定は次のとおりである。

| 判定 | 結果 | 根拠 |
|---|---:|---|
| 実装成功 | YES | 既知fixture 5件、unit test、公式path loader、archive単体実行が合格 |
| 学習更新を実施 | YES | 4 headを2 seedで実更新し、曲線、更新数、checkpoint hash、再ロード推論を保存 |
| 実行整合性が改善 | YES | F2とspatial armでは、最終resolver後の非PASS作業について固定engine再集計の効果率が100% |
| 研究上の経済改善 | PARTIAL / HYBRID ONLY | spatial hybridは同一重みのpureより平均cashが16,284.6高いが、手書きplan介入率77.7%を伴う。F0超えではない |
| 基準より強い | NO | F0/F1/F2、spatial pure/hybridはいずれも開発8戦で0勝8敗 |
| 提出可能 | NO | 32戦昇格条件を満たさず、新規Kaggle提出も行っていない |

実行契約の修復は成功したが、独立BCの経済はまだ成立していない。したがって、位置入力を追加したこと、学習更新を行ったこと、archiveが完走したことを「強くなった」「学習成功」とは報告しない。

## 凍結した入力と環境

- 添付ZIP SHA256: `9303a2e36ac65e44044827f5679ff64f05eb1a9f8ffcba898058410f10c4eb09`
- Round7 F0 archive SHA256: `fe3b5bd9b14ec64208fc9360c38b9aaf5cc1b44547dca2b6eee3d24d0aaf1fca`
- 固定engine `kaggriculture.py` SHA256: `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`
- 固定loader `agent.py` SHA256: `9b7682b4831135f8d7205d5051840a7d57199928db68a92f243632a5aa735b59`
- 固定config SHA256: `a82c89dc86b542a3dafd521d12c45b08cc11d2f199c166f5792d4bd116525d24`
- 開発seedは `2026102201, 2026102202`、両seat、相手はv122/v124。既存sealed `2026110701..2026110732` は未使用。
- 新規Kaggle提出は0件。既存archive/checkpoint/seedは上書きしていない。

## Phase A: engine実行契約

修正した内容は次のとおりである。

1. schema上のaction、actor順で実行可能なaction、期待した状態変化を生むactionをtrace上で分離した。
2. 作物HARVESTは成熟日とyieldを同時に確認し、家畜HARVESTはproduct yieldを候補へ戻した。CAREは固定engineどおり当日未給餌でも許可した。
3. plan後にactor 0から順にshadow stateを再構築し、PICKUP/PLACE/PLANT/HARVEST/FEED等の在庫、対象世代、yield、当日flagを更新した。
4. 同座標を一律禁止せず、成熟作物HARVEST→新世代PLANT→WATERを許可した。原子的PLANT不足は後続要求をPASSにして全取消を防いだ。
5. actor処理後のshedからmarketを開始し、未来のmarket購入を当turnの農作業に使わせず、SELL/BUY順と保証済み資金を追跡した。
6. raw model、mask、ledger、plan、final、次観測effectをdeep copyした。plan signalの未来step混入を修正した。
7. root `main.py`、空globals、最後のcallable規約を公式path loaderで検査した。archiveは追加`sys.path`や外部weightに依存しない。

`fixtures/engine_contracts_v2.json` の5件は全合格した。内容はready COW harvest、未成熟CARROT拒否、post-plan小麦予約、同座標新世代列、未給餌CAREである。これは契約検査でありゲーム強度評価ではない。

## Phase B: 同一Round7重みの対照

各armはv122/v124 × 2 seed × 両seatの8戦である。

| arm | 変更 | W-D-L | 平均cash | 平均margin | 固定engine再集計の作業効果率 |
|---|---|---:|---:|---:|---:|
| F0 | 提出Round7 original | 0-0-8 | 28,747.4 | -127,485.4 | 92.55% |
| F1 | HARVEST契約のみ | 0-0-8 | 12,180.5 | -130,892.8 | 93.61% |
| F2 | 契約＋最終action再解決 | 0-0-8 | 6,831.0 | -150,715.3 | 100.00% |
| F2 no-plan | F2から家畜planを無効化 | 0-0-8 | 7,138.9 | -130,529.8 | 100.00% |

F2は無効果要求を最終actionから除去できたが、cashと勝敗は改善しなかった。よって「実行整合性改善」と「経済改善」を分ける。F0がこの小標本では最も高cashであり、F1/F2を昇格しない。

## Phase C: 位置入力を持つ独立BC

### データ契約

- 一貫したteacher familyはsubmission `56216119` のみ。
- 既存episode split内からhash順でtrain 12 / validation 4 / test 4 episodeを選択した。同一episodeの混入はない。
- 全20 replayのhashを再検証し、各720保存状態/719意思決定を確認した。
- 対応は `observation[t] -> action[t+1]`。seat1で保存`step`がない7,909状態もday/hourから時計を再構成した。
- farmer/hands順、item、raw要求quantity、market順、EOSをround-trip検査した。失敗0。
- 相手private、未来shop、未来action、勝敗はruntime入力に含めていない。
- public反例3 episodeはdevelopment扱いで除外し、sealedへ戻していない。

最初のdataset v1はmarketを偶数stepだけ保存しており、重要なrecord 2のHIRE列を学習していなかった。自由実行で初手購入を反復したため、このdataset/model/archiveは失敗として凍結した。dataset v2は全719 decisionのmarket列を保存する。

### 入力とモデル

- self/otherを分けた `2 x 26 x 10 x 10` grid channelを作成した。kind、crop/animal、配置日由来age/maturity、yield、当日flag、連続未作業、期限を含む。
- runtimeモデルには各channelの位置依存4x4 DCT係数を与えた。Round7で同一だった成熟WHEATの東西交換は異なるhashになった。ただし4x4圧縮は可逆ではなく、高周波の空間aliasは残る制約である。
- self actor最大32 slotの位置と全inventory、other public actorの位置を保持した。今回corpusの最大actor数は12。
- 同turn prefixはtokenだけでなく、raw quantity、対象座標/資源/世代、固定engineで確定した効果、resolved actionを保持した。
- actor入力1871、market入力1664。各headは `input-96-48-output` の2 hidden ReLU MLP。
- categorical/定数列を極小stdで割らず、encoderの意味的正規化とmean=0/scale=1を用いた。

### 実学習の証拠

単一trajectoryのstep 0..95、527 actor行による過学習probe v1は600更新で81.59%となり失敗した。重複入力の矛盾ラベルは0件だった。基準98%を変えず、batchと容量を増やしたv2は1,260更新、98.29%で合格した。これは記憶能力の検査だけであり汎化・強度の証拠ではない。

最終primary seed `20260922` のcheckpointは次のとおりである。

| head | shape | 総更新 | best epoch | validation acc | test acc | checkpoint SHA256 |
|---|---|---:|---:|---:|---:|---|
| actor token | 1871-96-48-44 | 1080 | 22 | 57.35% | 58.17% | `33b0df76cdca4773060874809b33de3ce7bc985295f79e302bc16a92144d9539` |
| market token | 1664-96-48-22 | 1392 | 24 | 70.45% | 69.54% | `b73b73447033d55237e6fad4f6e2fabc04787ce41d720cb40013598166b39f52` |
| actor quantity | 1915-96-48-12 | 80 | 39 | 66.67% | 69.02% | `579427032cfe480b5774a2d0588dd78b3193956e683df127235762451f76ebc3` |
| market quantity | 1686-96-48-37 | 512 | 27 | 62.21% | 60.94% | `2b2da5a754efc3eb73709dbd728b1eb3460083ecb5b2e6d615e6c7d4311dadb2` |

別seed `20260923` でも4 headを再学習した。test accuracyはactor token 58.25%、market token 68.23%、actor quantity 70.59%、market quantity 61.48%であり、更新と再ロード推論は全headで確認した。

### 閉ループと回復データ

初期モデルは24/96/192ターンを完走したがHIRE/作付けへ接続しなかった。全step market化後も連続HIRE境界を外した。そこで同一teacher familyのday 0行だけをtarget-taskとして8倍oversampleした。手書き初期routeは入れていない。

この回復で、最終v6はrecord 1の購入とrecord 2の4 HIRE・家畜購入を教師どおり再現した。pass相手への24ターン自由実行ではpureが最大4 hands、作物2、家畜4へ到達した。しかし教師episode 109118332の同時点は作物15、家畜5であり、96/192ターンでもpureの最大作物は2、土地拡張は0だった。長期の仕事継続は未解決である。

通常開始の8戦結果は次のとおりである。

| arm | 性質 | W-D-L | 平均cash | 平均margin | 家畜yield/harvest発生ゲーム | 実収穫の概要 | plan介入率 |
|---|---|---:|---:|---:|---:|---|---:|
| spatial pure v6 | 独立BC＋安全decoder、planなし | 0-0-8 | 1,411.9 | -137,263.4 | 0 / 0 | WHEAT 36, MELON 90 | 0% |
| spatial hybrid v6 | 同じBC＋手書き家畜plan | 0-0-8 | 17,696.5 | -114,612.1 | 8 / 8 | WHEAT 111, WOOL 534, MILK 612ほか | 77.73% |

hybridはpureより経済指標が改善したが、両方0勝であり、F0平均cash 28,747.4にも届かない。hybridの成果をpure BCの学習成功とは扱わない。開発8戦の昇格条件を満たさないため32戦は実施していない。

## 診断と独立再集計

- 全48新規対戦で、replay最終観測から再集計したcashがgames.csvと一致した。
- raw model→mask→ledger→plan→final→次観測effectの719 record/gameをdiagnosticsに保存した。
- F2、F2 no-plan、spatial pure/hybridでは最終actionの非PASS作業が固定engine再適用で全件効果ありとなった。
- 同座標複数作業は別指標として保存し、構文illegalとは数えていない。
- 売却は同turnに同item BUYが先行した場合を曖昧として除外し、反実仮想利益は計算していない。
- shared marketの実shop履歴を各runに保存した。相手action固定試験を実対戦効果とは呼んでいない。

## 未実施・UNKNOWN

- Round5独立BCや別の実在弱相手との追加段階試験: 0件。
- 32戦昇格評価: 0件（8戦基準未達）。
- 大規模holdout / sealed seed: 0件。
- Kaggle提出: 0件。
- レート2000/3000到達可能性: UNKNOWN。
- 高周波まで可逆なfull-grid encoder、target座標を直接予測するtask head、訪問失敗状態への正しいteacher recovery label: 未実施。
- 現在のpure BCがRound5/Round7より強いか: NO。今回の8戦とcashでは支持されない。

次の研究課題は、actor番号依存の逐次token模倣を続けることではなく、対象座標・対象世代・仕事type・必要資材・期限・完了条件を明示したtarget-task headと、到達可能な自分の失敗状態に対するteacher recoveryデータを作ることである。
