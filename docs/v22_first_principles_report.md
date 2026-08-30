# Kaggriculture 第一原理・上位ログ統合分析（V22〜V32）

作成日: 2026-08-27（Asia/Tokyo）

## 結論と主張範囲

目標はレート3000超だが、ローカル試験や公開ログ分析はその達成を保証しない。提出済みV10はレート933、V11は1014.6であり、現在の採用可能な安全版はV14のままである。V15〜V21の追加変更と、V26〜V30の市場接続案は、平均値以外の悪化、時間軸の不一致、または閉ループの経路依存性により不採用となった。V25価格予測とV29短期供給予測は分析上の予測精度を持つが、runtimeでは無効である。

今回の第一原理分析から最も重要だった結論は、Kaggricultureを「高単価資産を増やす農場ゲーム」ではなく、次の五つを同時に管理する有限期間の二人用経済ゲームとして扱う必要があることである。

1. 現金と最終時刻
2. 共有市場に対する両者の供給圧力
3. 公開農場から予測できる相手の生産時計
4. 作業員ターン、移動距離、日次締切
5. 相手との相対スコアと下方リスク

以下では、公式エンジンから確認した事実、ログから得た再現可能な事実、そこからの推論、未検証事項を分離する。

## 公式エンジンから確定した事実

### 勝敗とターン順序

- 720ターン、30日間であり、公式環境の最終rewardは自分の所持金である。
- 競技レートは対戦勝敗に依存するため、平均所持金だけを最大化しても十分ではない。
- 1ターンの処理順は、両者のフィールド行動、マーケット注文、Town消費、植物減衰、23時後の日次更新である。
- Town消費ターンに売ると消費前価格で約定する。一般には次の観測まで待てば消費後価格を使えるが、現金需要、在庫上限、相手の先行売却を無視できない。
- 両者が同じ商品の同じ単位番号を同時に売る場合、双方が同じcommit前在庫から価格提示を受ける。
- 価格1の売却は1コインを受け取るが、市場在庫を増加させない。このため公開市場差分だけではfloor売却数量を完全には復元できない。

### 作物の生産と作業量

単収型作物は植付時に1単位の収穫可能量を持つ。最大収量を得る最小タイル操作数は次のとおりである。移動、倉庫搬送、肥料入手、マーケット注文は含まない。

| 作物 | 無施肥収量 | 無施肥操作 | 施肥収量 | 施肥操作 | 第一原理上の意味 |
|---|---:|---:|---:|---:|---|
| Wheat | 4 | 6 | 6 | 7 | 需要耐性と飼料用途を持つ頑健資産 |
| Carrot | 3 | 5 | 4 | 6 | 短期回転向けだが価格下落はWheatより急 |
| Tomato | 4 | 8 | 8 | 13 | 長い立上りと高い作業拘束を持つ |
| Strawberry | 4 | 11 | 8 | 14 | 高収益だが共有供給への感度が極めて高い |
| Melon | 6 | 10 | 6 | 9 | 施肥は増収でなく作業締切の圧縮になる |

植付日は`consecutive_unwatered=1`から始まるので当日給水が必須である。2回連続の日次未給水で枯死し、動物も2回連続未給餌で失われる。継続作物の基礎生産は生産日に発生するが、肥料ボーナスには当日の給水が必要である。CAREの追加生産も、給餌済みの将来生産日に初めて回収される。

### 市場感度とTown需要

8回の店抽選を事前確率で平均した季節Town需要は、Wheat 525、Strawberry 426、Carrot/Milk 327、Tomato/Egg/Wool 228、Melon 30である。実戦では公開済みの店構成を用い、未解禁分だけを期待値として扱う必要がある。

Wheatは基準在庫から+1T供給されても価格20を維持する。一方、Strawberry、Milk、Woolはそれぞれ+1T付近で価格1まで崩れる。したがって次が導かれる。

- Wheatは販売商品、飼料、終盤流動性という複数の役割を持つ。
- MelonはTown店需要がなく、序盤資本化と相手供給の少なさが主な価値になる。
- Strawberry/Milk/Woolの固定増産は危険であり、現在価格だけでなく予測共同供給を評価すべきである。
- 資産価値は「単価×収量」ではなく、移動・日次締切・保管・相手価格影響を引いた値で比較する必要がある。

### 作業員費用

12人目のhandは当日限界費用144、12人までの累積日次費用376である。13人目は233、14人目は377へ急増する。よって「忙しいから雇う」のではなく、追加worker-turnが費用と経路混雑を超える場合だけ雇うべきである。

## 上位ログとの照合

### データと分割

- Rank 1: submission 55614463、133 sides
- Rank 2: submission 55623460、130 sides
- Rank 3: submission 55574890、184 sides
- 重複除去後399試合
- episode単位でtrain 243、validation 78、untouched test 78へ分割
- 一試合の両seatと全時点は同じ分割に固定

### 人数差ではなく作業変換率

V11とRank 1はいずれも11〜12日目に概ね12 handsへ到達しており、V11の主問題は過少雇用ではなかった。差は同じ作業ターンを実作業へ変換する率にある。

- 11日目のhand PASS率: V11 15.8%、Rank 1 1.7%
- 12日目のhand PASS率: V11 24.5%、Rank 1 4.8%
- 11日目のproductive hand actions: V11 102.2、Rank 1 134.4
- 12日目のproductive hand actions: V11 97.3、Rank 1 116.6
- 翌日開始時の未給水植物: 11日目V11 18.0対Rank 1 1.2、12日目V11 27.5対Rank 1 4.6

この差はtrain/validation/testで再現した。ただしRank 3は大量の予防給水を行わないため、予防給水そのものは上位共通戦略ではない。

### 売却タイミングには複数の強い分岐がある

replay state `t+1`のactionをdecision observation `t`へ対応させ直すと、Rank 2はTown消費後のphase 1へ売却を集中させていた。

- Rank 2の18〜26日Wheatは全分割でphase 1比率100%
- 同期間のRank 2はStrawberry 87.0%、Milk 72.0%、Wool 77.6%がphase 1
- Rank 1とRank 3は主に消費前phase 0
- V11も主にphase 0で、Rank 1/3型に近い

よって「Town消費後に必ず売る」という単一規則は上位模倣にならない。Rank 2型は在庫余裕と資金待機を使い、Rank 1/3型は相手より先に供給する価値や資本回転を取っている可能性がある。これは推論であり、因果効果は未検証である。

### 相手供給は予測可能だが、上位の即時反応は確認できない

公開履歴100特徴だけから、相手のWheat/Strawberry/Milk/Woolの24/72時間SELLを予測した。相手private inventoryは特徴に含めず、offline label作成にだけ利用した。

未使用78試合の結果:

- macro event AP 0.9417
- macro event F1 0.9005
- quantity MAE 14.045のゼロ予測から6.804へ改善
- 下位margin四分位でもAP 0.9585、F1 0.9146、MAE 17.423から8.376

ただし24時間Wheat/Woolの予測総量比は0.441/0.461であり、数量を過小評価する。モデルは分析専用、runtime無効である。

さらに上位側の未来供給を予測する際、上位自身の公開農場・市場・Townに対戦相手の公開農場と資金を加えるアブレーションを行った。42,912時点の未使用試合ではevent APが+0.00084改善しただけで、quantity MAEは5.248から5.321へ1.38%悪化した。したがって次を分ける必要がある。

- 確認済み: 相手の既存農場から近未来供給を予測できる。
- 未確認: 上位が相手農場に応じて24/72時間供給量を大きく変更する。
- なお可能: 相手反応は、より長期の新規資産選択、売却時刻、リスク管理に現れる。

相手以外の将来市場在庫をoracleで与え、相手の実効売却分だけを予測で戻す有利な必要条件テストでは、定数供給基準に対する正規化価格MAEをvalidationで51.9%、untouched testで52.2%削減した。したがって相手供給予測は市場価格へ変換できる情報を持つ。ただしoracleは自分の将来供給、Town処理、その他の実現フローを既知としており、実運用可能な価格精度ではない。

### 公開状態の24時間価格予測は成立したが、相手供給特徴の追加価値はなかった

現在価格を基準に24時間後の残差を予測するV25を作った。元のV22 test試合を価格validation 38試合と価格test 40試合へ再分割し、森林seedを揃えて公開状態だけのモデルとV22相手供給特徴追加モデルを比較した。

- 価格validation正規化MAE: 現在価格0.1142、公開状態0.07475、公開状態+供給0.07444
- 価格test正規化MAE: 現在価格0.1161、公開状態0.07465、公開状態+供給0.07474
- 供給特徴の追加効果: validationで0.42%改善、testで0.13%悪化
- 学習に使っていないV11全38試合: MAE 0.09741から0.06969へ28.45%改善、P90も29.83%改善

確認できたのは、公開農場、市場、Town、公開履歴から24時間価格を現在価格より正確に予測できることまでである。V22相手供給モデルを別特徴として接続する根拠はなく、価格精度は売却方策の因果価値を意味しない。

### Town直前売却の延期案は時間軸と相手売却リスクで不採用

V26は24時間後のV25価格を1ターン延期へ誤接続していた。V11の1,830売却中6件しか選ばず、次ターン価格上昇は0/6だった。これはV25の否定ではなく、24時間目的を1ターン判断へ使った設計誤りである。

公式市場曲線から現在売却を楽観、Town後売却を相手の次ターン注文込みで悲観評価したV27では、V11の480件で正の利益下限が残り、train/validation/testは255/93/132件だった。しかし実行時に相手の同時注文は見えない。公開Town効果だけの実行可能ゲートは外部V11 testで正率54.5%、利益下限P10 -242となった。

V22の24時間相手供給を使うV28は上位validation正率40.7%、P10 -576で失敗した。危険に時間軸を合わせたV29は399試合、53,640行、243/78/78試合分割で現在+次ターン売却を学習し、untouched testのevent APはStrawberry 0.845、Milk 0.788、Wool 0.577だった。それでも難しい延期候補だけに限定したV30では次の結果となった。

- 上位validation: 正率54.9%、利益下限P10 -279
- 上位test: 正率66.3%、P10 -94.9
- 外部V11: 6件、正率66.7%、P10 -187

一般状態の予測精度が高くても、方策変更を必要とする境界状態では安全なゲートにならない。V26〜V30はすべてruntime無効とし、V14の売却層を変更しない。

### floor売却の単純禁止は成立しない

V11には価格1のpremium商品売却が1,375単位あった。しかし「24日以前、翌日入庫込み在庫70以下、購入後現金100以上、該当する解禁済みTown店あり」を同時に満たす明確な保留候補は0件だった。安値売却は見た目だけで判断できず、在庫圧迫または資金制約と結び付いている。単純なfloor売却禁止は実装しない。

## V21予防給水の反証

第一原理とRank 1/2ログから、11〜12日目の残余PASS作業員だけを3マス以内の予防給水へ向かわせるV21を作った。通常タスク、空荷条件、日末到達可能性、給餌緊急停止を決定論的に保証した。

同一の未使用5 seed、両seat、対starterの結果:

| 指標 | V14安全核 | V21 |
|---|---:|---:|
| 平均reward | 137,619.8 | 137,714.5 |
| P10 | 123,458.5 | 122,372.5 |
| 最小 | 97,156 | 86,296 |
| 動物損失 | 0 | 0 |

平均は+94.7だがP10と最小が悪化し、最悪試合は-10,860だった。最初の差は11日18時の`PASS -> SOUTH`で、12日開始時の給水リスクを5枚減らしたにもかかわらず、作業員位置とassignment identityが変わり、15日にはCowが2頭少ないポートフォリオへ分岐した。

これは「局所目標を達成した」「上位ログに近づいた」「動物を直接失わなかった」の三条件だけでは採用できない例である。V21は既定無効とし、V14を維持する。

22時以降、距離1だけに狭めた追加診断も行った。既知10試合では平均+2,399、2改善・7同一・1悪化、最悪差-687だった。しかし条件選択に未使用の別10試合では平均が137,540.9から135,050.5へ-2,490.4、P10/最小は103,800から94,245へ-9,555となった。未給水は微改善し、動物損失0でも最終価値は悪化したため、狭い版も不採用である。

## V31〜V32 作業実行層の構造診断

V11 plannerを提出V11状態とRank 1状態の双方へ載せ、PASSを原因別に分解した。V11提出ログではplannerの最終PASSが実際の提出行動と一致し、再現性を確認した。

- V11 Day 11: raw PASS 2.29人/時。実行可能タスクなし0.44、正タスクへの競合1.85、距離込み非正0
- V11 Day 12: raw PASS 3.11人/時。実行可能タスクなし1.19、正タスクへの競合1.92、距離込み非正0
- Rank 1の実PASS: Day 11 0.182、Day 12 0.605
- 同じRank 1状態でV11 plannerを使った最終PASS: 1.839、1.805

したがって主因はV11農場だけではなく、一手タスク表現と将来工程への移動変換にもある。単純な距離ペナルティ調整ではない。

実行されたworker遷移では、移動の次手を生産行動へ変換する率がDay 11でV11 37.1%対Rank 1 47.0%、Day 12で41.2%対44.0%だった。動物セルで生産行動を連続する率もV11 53.9/52.5%対Rank 1 59.2/57.2%だった。Rank 1は動物セルへ単純に人を積んでおらず、Day 12の移動をV11約4.91人/時から約6.39人/時へ増やしながら、PASS→PASSを2.28から0.44へ抑えている。

この事実はmulti-turn schedulerの必要性を支持するが、任意のPASSを局所目標へ動かすV21は反証済みである。次の候補は、将来タスク列、worker identity、資産サービス工程、日次締切を同時に評価し、資源購入を含む閉ループで検証する必要がある。

## 設計への反映

現在支持される責務分離は次のとおりである。

```text
Public state
  -> Opponent supply predictor（24h/2turnとも分析済み、runtime無効）
  -> Public price forecaster（24h精度を外部V11で確認、runtime無効）
  -> Relative portfolio objective（未実装）
  -> Multi-turn scheduler（将来タスク列、位置、identity、締切を同時評価する必要）
  -> Deterministic executor（合法性、給餌、給水、在庫、資金を保証）
```

学習器を次の一手へ直接接続してはならない。V13ではoffline action criticの24/72/final誤差が改善しても閉ループで悪化し、V17〜V20では将来herd誤差が改善しても購入・pasture・給餌・経路の結合を壊した。V21でも同じ経路依存性が再確認された。

公開状態による価格予測の必要条件は通過したが、限定売却方策の下方リスク条件は通過しなかった。市場実行へは接続しない。次の主要課題は、V31/V32で確認した将来タスク列を扱うschedulerと、家畜サービス負荷・作物構成・資本回転の結合価値を分離することである。

## 再現可能な成果物

- `scripts/analyze_v22_game_economics.py`
- `data/analysis/v22_game_economics.json`
- `scripts/build_v22_opponent_supply_rows.py`
- `data/training/v22_opponent_supply_rows.json`
- `scripts/train_v22_opponent_supply.py`
- `data/models/v22_opponent_supply_model.json`
- `data/analysis/v22_opponent_supply_validation.json`
- `scripts/analyze_v22_market_timing.py`
- `data/analysis/v22_market_timing.json`
- `scripts/analyze_v22_top_response_ablation.py`
- `data/analysis/v22_top_response_ablation.json`
- `scripts/analyze_v23_floor_sales.py`
- `data/analysis/v23_floor_sales.json`
- `scripts/analyze_v24_opponent_price_value.py`
- `data/analysis/v24_opponent_price_value.json`
- `scripts/train_v25_public_price_forecast.py`
- `data/models/v25_public_price_model.json`
- `data/analysis/v25_public_price_forecast_residual.json`
- `scripts/evaluate_v25_on_v11.py`
- `data/analysis/v25_v11_external_price_evaluation.json`
- `scripts/analyze_v26_sale_deferral.py`
- `data/analysis/v26_sale_deferral_screen.json`
- `scripts/analyze_v27_town_deferral_counterfactual.py`
- `data/analysis/v27_town_deferral_counterfactual.json`
- `scripts/analyze_v28_deferral_supply_gate.py`
- `data/analysis/v28_deferral_supply_gate.json`
- `scripts/build_v29_two_turn_supply_rows.py`
- `data/training/v29_two_turn_supply_rows.json`
- `scripts/train_v29_two_turn_supply.py`
- `data/models/v29_two_turn_supply_model.json`
- `data/analysis/v29_two_turn_supply_validation.json`
- `scripts/analyze_v30_deferral_two_turn_gate.py`
- `data/analysis/v30_deferral_two_turn_gate.json`
- `scripts/analyze_v31_task_supply_gap.py`
- `data/analysis/v31_task_supply_gap.json`
- `scripts/analyze_v32_worker_pipeline.py`
- `data/analysis/v32_worker_pipeline.json`
- `agents/v21/main.py`（rejected-disabled）
- `scripts/run_v21_ablation.py`
- `scripts/analyze_v21_closed_loop.py`
- `data/analysis/v21_closed_loop_diagnosis.json`

## 未検証事項

- 公開ログだけから推定した相手供給が、実際の自エージェント対上位エージェント分布でも同精度か。
- 将来タスク列を扱うschedulerが、worker identityの経路依存性を悪化させず未使用試合の下位分位を改善できるか。
- 家畜サービス負荷を含むportfolio価値を予測し、購入・pasture・給餌を壊さずに上位構成へ近づけられるか。
- leaderboard ratingが改善するか、または3000を超えるか。

これらは未確認であり、達成済みとして表現しない。
