# Kaggriculture v125 実体監査と v126 候補評価

## 結論

**v125 より強い次版は、この調査では採用できなかった。** 実行不整合 E の7案は既知ケースを直せず、Service/Fertilizer/Joint は同一 opponent・seed・seat の開発比較で Control より悪化した。したがって作成した `v126_control_candidate.tar.gz` は、提出可能性を確認した **v125 行動同一の安全な Control** であり、勝率改善版ではない。Kaggle への提出・既存提出の取り下げは行っていない。

既知不具合Aは再現できたが、採用候補では未修正である。棄却コードは検証可能性のため独立スイッチと `rejected` アーカイブで残し、Control ではすべて無効にした。

## 1. 提出物から実戦までの対応

### 1.1 v124 / v125 の実体

| 項目 | 確認結果 |
|---|---|
| v124 source commit | `dd928e2590687461a03c1af59d37e3e597c25416` |
| v125_exec source commit / 監査時 HEAD | `fadd7e89bfe6612ecbe2020fb724bb9064014987` |
| v124 archive | `artifacts/submissions/v124.tar.gz`, SHA256 `cdc74eb6ae47c53e9c2edfeea45dc55603c67ebfdba48164081458f79c4f46fc` |
| v125 archive | `artifacts/submissions/v125_exec_candidate.tar.gz`, SHA256 `b900d0fd98f1e19a8fd0276d5a406bff63006e68d874670464a36d7e34628cd5` |
| 実際の入口 | `main.py::agent` |
| 呼出し列 | `v125_exec.agent` → `v124_base.agent` → `v121_market.agent` → `v125_exec.repair_action` |
| v125 main | `agents/v125_exec/main.py`, SHA256 `6d013b9410741a861841077bb31969c315530637d92190448db16d2cfe7f59e8` |
| v124 main | `agents/v124/main.py`, SHA256 `0f0c95d52e82840488078a2feecf9ca4d3c59e9337d3273bf7c64ca572c0e51f` |
| policy model | `agents/v124/policy_model.json.gz`, SHA256 `fbc51e4ca157e73aa8c55b65048b57b3d46d7e0d7a1f89e9d8be84c0d9fc5471` |
| engine | `kaggle-environments 1.32.7`; `kaggriculture.py` SHA256 `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e` |

提出 56384917 と 56384919 は、どちらもローカルの `agents/v125_exec` と判定した。根拠は各 validation episode 111138981 / 111138983 の両seatで、記録済み観測に対する全 2,876 action が完全一致したこと（2,876/2,876、差分0）である。これは監査観測上の**行動同一性**であり、Kaggle 上の遠隔 archive byte SHA256 の認証ではない。遠隔 archive SHA256 は取得不能だったため `UNAVAILABLE` と記録した。

詳細は `phase0_live_identity.json` に、archive全member・configuration・replay・action列のハッシュまで保存した。

### 1.2 runtime で有効だった変更

| 提案 / 機能 | 実装 | runtime条件 | 期待 | 今回の観測 | 判定 |
|---|---|---|---|---|---|
| 同一turnの種数を超える PLANT を数量制限 | `agents/v125_exec/main.py::repair_action` | v125で常時ON | 不成立PLANTの除去 | 一括PLANT取消が v124の11試合47要求から v125で0 | v125の実行上の改善として保持 |
| 倉庫容量を超える DROP を、入る量だけの PLACE に置換 | 同上 | v125で常時ON | 全量DROP失敗と廃棄の削減 | 平均廃棄18.10→12.56 | 実行上の変化として保持。ただし勝率改善の因果証明ではない |
| current-meta continuation library | `agents/v124/main.py` | `ENABLE_CURRENT_META_LIBRARY=True` | v124で採用済みの継続方策 | v125にも継承 | v125新規変更ではない |
| segment router | `agents/v124/main.py` | `False` | 局面別source切替 | 実戦では無効 | 有効だったと扱わない |
| SELL forecast | `agents/v124/main.py` | `False` | 市場売却順の予測 | 実戦では無効 | 以前の負結果を保持 |
| clone preemption | v121系をv124から制御 | `False` | route割込 | 実戦では無効 | 有効だったと扱わない |
| d2イチゴ・3区画・早期輪作の complete plan | `agents/v125_base/main.py`, `agents/v125_adaptive/main.py` | 別arm。v125_execからは呼ばれない | 早期作付け・輪作 | ローカルで両armとも4 proxyに0/8。実提出ではイチゴd5、トマトは既存d18分岐 | 棄却済み。勝手に復活させない |

「v125に関数が存在したが発動しなかった」のではなく、早期 complete plan は**別の棄却armであり、実提出の入口に含まれていなかった**。実提出に入った新規差分は seed PLANT cap と shed overflow bound の2点である。

## 2. 実戦結果の位置づけ

提出56384917は公開66戦37勝29敗、最終1579.08、最高1634.94。56384919は公開64戦42勝22敗、最終1531.45。合計130戦79勝51敗だが、対戦時レート1600以上には4勝24敗だった。v124の同帯25勝35敗とは相手・seed・seatを揃えた比較ではないので、v125差分が劣化原因だとは断定しない。

実ログで確認済みの到達点は次の通り。

- イチゴ初植えは v124 全157戦、v125 全130戦とも d5。早期化なし。
- v125のトマトは14/130戦で、すべて d18・4区画目・10株。v124と同じ分岐。
- 家畜退出後の同座標作物転用は v125 0/130、v124 0/157。
- 成功した小麦施肥は平均10.76→11.39、イチゴ59.99→60.19。ただしv125の64/130戦は小麦施肥0。
- 成功FEEDは350.16→349.43、CAREは384.23→384.48で、維持強度の増加は見られない。
- 上位行動への見た目の接近や平均現金だけでは採用根拠にしない。これら130戦は開発データであり、最終holdoutには再利用していない。

## 3. 既知不具合Aの再現

### 3.1 engine契約

公式engineソースと実観測の双方から次を固定した。

- 倉庫アクセス位置は `(4,4),(5,4),(4,5),(5,5)` のみ。
- `PICKUP/PLACE/DROP` は、そのactionを出すactor自身がアクセス位置にいる必要がある。
- `FEED` は同じworkerのinventoryに WHEAT が必要で、倉庫在庫だけでは成立しない。
- unit actions が先、market/HIRE が後。新規handはその後にアクセス4マスの占有が少ない位置へ生成される。
- day境界ではhand/inventoryの更新・dropがあり、route想定位置を次日にそのまま持ち越せない。
- 記録tのactionは観測t−1へ適用される。dayはd0始まり。`actor0=farmer`, `actor1以降=hands`。

### 3.2 具体的な失敗

episode 111196878 / 111203616 で、記録243の actor8 `(4,3)` からの `PICKUP WHEAT 5` は、倉庫に小麦7があっても非アクセス位置なので失敗した。記録251の actor2 `(3,5)` からの `PLACE MELON 6` も同様に失敗した。actor8は小麦を持たないまま記録252/256で `FEED` を出し、その後も失敗が連鎖した。記録288（d12開始）で `(5,2)=羊,(5,3)=牛,(5,4)=牛,(6,4)=羊` の4頭が退出し、羊3頭が倉庫に未配置で残り、後作転用はなかった。

同じ位置・記録の失敗を旧v124の episode 110824511 / 111007532（seat0）でも再現した。新例はseat1である。したがって、新しい退出機能だけを原因とはしない。

実engineをturn0から動かし、相手だけを記録action tapeに固定した回帰結果は次の通り。これは強さ評価ではない。

| episode | seat | v125/control最終差 | 退出 | v126 Controlの対v125 action差 |
|---:|---:|---:|---:|---:|
| 111196878 | 1 | -41,578 | 4 | 0 |
| 111203616 | 1 | -28,406 | 4 | 0 |
| 110824511 | 0 | -49,512 | 4 | 0 |
| 111007532 | 0 | -46,970 | 4 | 0 |

同梱fixture検証はPASSしたが、元ログに不具合があることの検証にすぎない。上表の別rolloutでも Control は不具合をそのまま再現しており、修正成功ではない。

### 3.3 E修復案の結果

actor別の所持品・位置・source・日境界・成功確認を持つ作業単位、HIRE生成位置の照合、動物購入guardを `agents/v126_exec/main.py` に実装した。しかし、既知新2例の固定相手closed-loopで7案すべてを棄却した。

| E案 | 最終差（111196878 / 111203616） | 退出 | v125 action差 | 棄却理由 |
|---|---:|---:|---:|---|
| broad actor-local jobs | -65,082 / -60,102 | 4 / 2 | 479 / 499 | routeを広く壊し両方悪化 |
| narrow generic jobs | -56,061 / -17,686 | 9 / 3 | 388 / 402 | 一方改善でも他方が追加5頭退出 |
| atomic, sourceなし | -112,952 / -162,305 | 4 / 3 | 426 / 507 | nearest-route切替が破局的 |
| continuation sourceのみ | -41,578 / -28,406 | 4 / 4 | 8 / 9 | d10 openingはsource=-1で既知失敗に未発動 |
| opening source full-farm latch | -52,479 / -35,777 | 4 / 4 | 52 / 243 | 退出を防げず両方悪化 |
| opening source actor-only | -54,692 / -41,868 | 5 / 6 | 49 / 294 | 退出増、両方悪化 |
| counterfactual day view | -54,692 / -38,578 | 5 / 5 | 51 / 233 | 日境界まで差分を隠しても悪化 |

よって `ENABLE_EXECUTION_TRANSACTIONS`, `ENABLE_GENERAL_JOB_RECOVERY`, `ENABLE_ANIMAL_PURCHASE_GUARD` は Control でOFF。既知不具合は残る。`opening_routes.json.gz`（SHA256 `93e0ef61cfc78ba8d381ec46e451110cb9a9bb22890d80d783c11475f3863530`）は棄却案を再現するためだけに同梱し、Control runtimeでは読まない。

## 4. S/F 四条件比較

Eで採用できる修正がなかったため、全armで同じ v125実行器をControlとして使い、ServiceとFertilizerだけを独立スイッチにした。相手は反応する公開proxy 4種（`mooman_e052a`, `qeinstein_moev2`, `smart_farm`, `souvik_v4`）、seedは2026092201/2026092202、両seat、各arm16戦・計64戦。

同じseedでもarmの行動により実際のShop列は同一にならなかった。Shop列は各replayと21.8MBの `decision_log.jsonl` に保存しており、同一世界とは扱っていない。このpanelは開発用で、現在の上位相手であることを認証した最終holdoutではない。

| arm | 勝敗 | 平均差 | 最悪差 | 平均FEED | 平均CARE | 平均退出 | 小麦施肥 | 平均廃棄 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Control | 16-0 | +6,201.81 | +1,580 | 343.38 | 384.94 | 0.00 | 10.25 | 7.00 |
| Service | 10-6 | -2,538.50 | -23,824 | 260.75 | 236.88 | 4.25 | 22.81 | 55.75 |
| Fertilizer | 14-2 | +4,038.44 | -2,122 | 342.00 | 384.44 | 0.38 | 14.00 | 51.06 |
| Joint | 10-6 | -2,970.75 | -23,783 | 260.31 | 236.31 | 4.19 | 24.06 | 65.63 |

Controlとの同一条件pairでは、Serviceは Loss→Win 0、Win→Loss 6、平均margin差 -8,740.31。Fertilizerは0/2、-2,163.38で、16/16すべてのmarginが悪化。Jointは0/6、-9,172.56だった。

相手別勝数（各4戦）は次の通り。

| arm | mooman | qeinstein | smart_farm | souvik |
|---|---:|---:|---:|---:|
| Control | 4 | 4 | 4 | 4 |
| Service | 2 | 4 | 2 | 2 |
| Fertilizer | 4 | 4 | 2 | 4 |
| Joint | 2 | 4 | 2 | 2 |

Serviceは低価格時の追加FEED/CARE抑制を2,683回発動したが、退出と廃棄を増やした。Fertilizerは530回変更し小麦施肥を増やしたが、勝率も全pairのmarginも悪化した。高価格羊毛を一律削減する条件にはしていないが、それでも採用条件を満たさない。したがって3候補とも棄却し、Controlの `ENABLE_SERVICE_POLICY` / `ENABLE_FERTILIZER_POLICY` はOFF。

## 5. 市場Mと早期作付けR

Mは独立に扱った。episode 111189071 の既存SELL枠をMILK-firstへ入れ替えた単一遷移実験は、記録618で相対+96、668で-37、708で-31だった。固定MILK-firstは一貫せず棄却した。既存 `ENABLE_SELL_FORECAST=False` も過去の負結果を維持し、今回勝手にONへ戻していない。反応相手で勝率を確認できる新M候補は作れなかったため、Controlは市場無変更。

RもS/F/Mと混ぜなかった。d2イチゴ・3区画・早期輪作を含む `v125_base` / `v125_adaptive` は以前の開発panelでともに0/8で、実提出にも含まれない。既存4区画目を無条件に消す変更もしていない。完全な種・労働・土地・水・動物・現金化計画と未使用panelがないため、R候補は昇格させなかった。

## 6. 採用物・棄却物・検証

### 採用可能なControl（強化版ではない）

- archive: `artifacts/submissions/v126_control_candidate.tar.gz`
- SHA256: `472eb013183d4d7bc320fb25532ace0d6ab6d2af46d914e0ae158486f39e8452`
- 12 memberをstandaloneロードし、seed 2026092101 / seat0 / 720 statesでsourceとのaction差0、reward一致。`package_validation.json` はPASS。
- v125既知ケースでもaction差0。したがって回帰安全性はあるが、強さ改善は0。

### 棄却アーカイブ（提出非推奨）

| arm | archive | SHA256 | 理由 |
|---|---|---|---|
| E | `v126_e_rejected.tar.gz` | `55adcb64db79706a5568308a487660f2911b8f0c8829519cbf9ebcdac2cf9102` | 既知不具合を解消せず悪化 |
| Service | `v126_service_rejected.tar.gz` | `b7ccfd426ea3d240f22c7dc0b8b487044583d3dd64955087850aacacfc7ebaa3` | 10-6、Controlから6敗増 |
| Fertilizer | `v126_fertilizer_rejected.tar.gz` | `613a60811d597c48d3692d3897a2408c922b6f98790f4303b57bd253798b78d5` | 14-2、全16pairでmargin悪化 |
| Joint | `v126_joint_rejected.tar.gz` | `72d56d69b5bf4be2525c614247f66fe033b0fdf2a9404c6a537c11adebf9d27a` | 10-6、Controlから6敗増 |

Python regressionは `test_v125_exec.py`, `test_v125_engine_contract.py`, `test_v126_exec.py` の21件がPASS。変更Python一式の Ruff もPASSした。

## 7. 残る不確実性

1. 遠隔Kaggle archiveのbyte hashは取得できず、v125同定はvalidation観測での完全action一致に限る。
2. E修復は既知ケースへ過適応しない条件を優先した結果、採用可能な修正に到達しなかった。作業単位を元route生成時に持たせる設計変更が必要で、出力actionだけから安全に復元する方式は不十分。
3. 四条件は64戦の開発panelで、相手は反応するが現在の上位実体とは限らない。勝率改善の最終判定には未使用seed・別系統相手・seat swapを事前固定した新panelが必要。
4. 同じseedでもShop列はarm間で変化した。pair比較は opponent/seed/seat を揃えているが、同一Shop世界の反実仮想ではない。
5. v125実戦130戦は分析・開発に使ったため、今後の最終holdoutとして再利用できない。

現時点で実提出する合理的な新候補はない。提出する場合でも、`v126_control_candidate` はv125の再包装であって「v126で改善した」とは扱わない。
