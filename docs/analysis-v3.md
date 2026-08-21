# V3 Expert-Distilled Hybrid 分析・設計・検証

## 結論

今回のデータでは、学習を導入する価値はあります。ただし有効だったのは、720 turnの低レベルactionを直接学習することではなく、**上位agentが1日後にどの資産構成へ向かうかを学習すること**でした。

V3は次のhybrid構造です。

```text
Day 0       Rank1由来の固定24-turn opening
Day 1-2     安全なopening completion
Day 3-23    Top3別の学習済みportfolio expert + direct-match gate
全期間      決定論的task planner + global worker assignment
Day 24-29   horizon-aware harvest / liquidation
```

上位agent内部が機械学習かルールベースかはreplayから断定できません。一方、全Top3が「序盤は固定、情報が出た後は状態依存」という挙動を示すため、こちら側の再現方法としてはこのhybridが最も自然です。

## なぜEnd-to-End RLにしなかったか

Kaggricultureでは最大13 unit前後のfield actionと最大10 market orderを同時に720 turn選びます。PPOなどをゼロから適用すると探索空間が大きく、feed忘れやroute逸脱のような1回の誤りが長く残ります。

一方、手元にはTop3合計450 episodeがあります。そこでV3では、既知の安全なexecutionを残し、学習対象を次へ限定しました。

```text
Observation(t)
    -> [Wheat, Strawberry, Melon, Cow, Sheep, Hands, Land](t + 1 day)
```

モデルが多少外しても、違法actionを直接出さず、動物数・作物数・土地数などのmacro targetが少しずれるだけです。これがBehavior Cloningのcovariate shiftを抑える主な設計です。

## 教師データ

| Expert | Submission | Episode | 教師例 |
| --- | ---: | ---: | ---: |
| Rank1 | 55614463 | 134 | 2,814 |
| Rank2 | 55623460 | 131 | 2,751 |
| Rank3 | 55574890 | 185 | 3,885 |
| 合計 | - | 450 | 9,450 |

1 episodeにつきDay 3-23の21 snapshotを使用し、1日先のportfolioをlabelにしました。勝利trajectoryと大きな正marginを少し重くしますが、Rank1の敗戦を含め全試合を保持しています。

特徴量は77個です。主な内容は次の通りです。

- Day、残り日数、phase
- Cash、土地、利用率、Hands
- 自分の作物・動物・構造物・weed・未処理care
- Shed、carry inventory、seed
- Townの商品別需要
- 商品別priceとmarket inventory
- 相手の公開portfolioと土地利用率

train/validationはturn単位ではなくepisode単位で分割しました。同じ試合の隣接状態が両側へ入る情報漏洩を防いでいます。

## 学習モデル

Rank1/2/3を混ぜた単一モデルにはしていません。各expertについて24本、最大深さ7のweighted multi-output extremely randomized regression treeを学習しました。学習時はNumPyを使いますが、推論はJSON化したtreeをPython標準ライブラリだけで辿ります。

### Episode holdout MAE

`model / 同じexpert・同じdayの中央値baseline`です。値が小さいほど良い結果です。

| Expert | Wheat | Strawberry | Melon | Cow | Sheep | Hands | Land |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Rank1 model | 3.58 | 2.34 | 0.62 | 0.64 | 0.38 | 0.10 | 0.04 |
| Rank1 baseline | 4.85 | 3.91 | 0.86 | 1.54 | 1.48 | 0.01 | 0.03 |
| Rank2 model | 3.44 | 3.35 | 1.51 | 0.78 | 0.68 | 0.13 | 0.04 |
| Rank2 baseline | 5.43 | 7.42 | 1.31 | 1.56 | 2.05 | 0.06 | 0.01 |
| Rank3 model | 2.08 | 2.18 | 0.89 | 0.41 | 0.40 | 0.34 | 0.05 |
| Rank3 baseline | 2.28 | 2.84 | 1.11 | 1.47 | 1.44 | 0.31 | 0.03 |

HandsとLandは元々ほぼ日付だけで決まるため、中央値baselineが一部で上回りました。Town適応の中心であるCow、Sheep、Strawberryは全expertで大きく改善しています。V3ではHands/Land予測にも範囲制限と既存状態下限を付け、誤差を安全側へ閉じています。

## Mixture-of-Experts gate

Top3同士の重複episodeを除いた直接対戦49試合からpairwise logistic gateを学習しました。

| Pair | 試合数 | 学習内accuracy |
| --- | ---: | ---: |
| Rank1 vs Rank2 | 3 | 100.0% |
| Rank1 vs Rank3 | 35 | 71.4% |
| Rank2 vs Rank3 | 11 | 72.7% |

Rank1 vs Rank3モデルでは、Milk需要はRank1側、Wool需要はRank3側へ寄せる係数になりました。これは添付分析の直接対戦結果と整合します。

ただしRank1 vs Rank2は3試合しかなく、その100%は一般化性能を意味しません。runtimeでは試合数が少ないpairのevidenceを弱くし、Rank1 50%、Rank2 30%、Rank3 20%のpriorと混ぜています。またDay 3から7は情報がまだ少ないため、gateの影響を段階的に増やします。最終的には最大weightのexpertを82%使用し、残り18%だけsoft blendします。これは異なるpolicyを単純平均して弱くすることを避けるためです。

## Openingとexecution

Rank1 replayではsample内のDay 0 actionが完全一致していました。V3の24 actionは実replayのindex shiftを補正して抽出し、canonical replayとの完全一致もtestで確認しました。

Day 1-2ではV2の「早すぎるWheat 10」を使わず、Rank1の時間軸に近いWheat 6、6、7を使います。Day 3以降に学習モデルへ切り替えます。

field executionではV2のfeed reserve、water、harvest、fertilizer、terminal inventory safetyを維持しました。同じpriorityのtaskは1件ずつgreedyに取らず、Hungarian assignmentで全workerとtaskの総移動距離を小さくします。

市場売却はTop3のexpert weightから商品別batch sizeを補間します。Milk、Wool、Strawberry、Melonを同じthreshold・同じbatchで扱いません。Rank2 weightが高い場合はFertilizerをより多く再投資用に残します。

## ローカル対戦結果

### V3 vs V2

未調整seed 20260830-20260832を両席で実行しました。

| 指標 | V3 | V2 |
| --- | ---: | ---: |
| 勝敗 | **6勝0敗** | 0勝6敗 |
| 平均coin | **60,148** | 55,150 |
| 平均margin | **+4,998** | -4,998 |
| 最小margin | **+2,285** | - |

V3は全seed・両席で勝ち、席依存の逆転もありませんでした。

### V3 vs V1

V2評価と同じseed 20260822-20260824を両席で実行しました。

| 指標 | V3 | V1 |
| --- | ---: | ---: |
| 勝敗 | **6勝0敗** | 0勝6敗 |
| 平均coin | **66,202** | 27,379 |
| 平均margin | **+38,823** | -38,823 |
| 最小margin | **+27,478** | - |

同じseedで以前のV2は平均70,684 coin、対V1 margin +34,522でした。V3は自分の絶対coinが約4,482低い一方、相手を含む市場への作用によりmarginは約4,301大きくなりました。Ratingの目的は絶対coin最大化ではなく勝率最大化なので、この差は今回狙ったrelative optimizationと整合します。

### 学習model ablation

seed 20260830の両席だけで、opening・plannerを同じまま学習modelを無効化しました。

| 構成 | 自分平均 | V2平均 | margin |
| --- | ---: | ---: | ---: |
| Full V3 | **55,675** | 47,675 | **+8,000** |
| 学習modelなし | 51,038 | 49,052 | +1,986 |

2試合だけなので統計的な結論ではありませんが、このseedでは改善がopeningだけではなく学習strategyからも来ていることを示すsanity checkになっています。

### 運用安全性

保存したseed 20260830の両席では、V3は次の結果でした。

- Hand PASS率: 6.21%
- Productive action / Hire: 6.76
- Fertilizer collect: 85、Fertilize: 49
- Cow/Sheep loss: 0
- Terminal inventory value: 0

V2の同試合はPASS率約2.6%、productive/hire約7.14で、純粋なaction密度はV2が上でした。それでもV3が勝ったため、「PASSを減らすこと」より「高ROI taskを選ぶこと」が重要というTop3分析とも一致します。

## 現時点の限界

1. 上位agent本体とはローカル対戦できないため、Top3との差が埋まったとはまだ言えません。
2. 9,450例はportfolio imitationには十分有用ですが、gateの直接対戦は49試合、特にRank1対Rank2は3試合だけです。
3. 教師状態から外れた場合の安全策はありますが、offline imitation固有のdistribution shiftは残ります。
4. ローカル12試合の結果だけからleaderboard ratingは推定できません。
5. 公開replayを学習に使うことについて、提出前にcompetition固有Rulesを利用者自身でも確認する必要があります。

今回、V2の新規対戦ログは取得していません。既に手元にあったTop3 replayとローカルsimulationだけを使用しています。

## 再現手順

```powershell
# 全450 replayで再学習
.\.venv\Scripts\python.exe scripts\train_v3_strategy.py

# test / lint
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .

# package
.\.venv\Scripts\python.exe scripts\package_submission.py --agent agents/v3
```

提出物は`artifacts/submissions/v3.tar.gz`です。`main.py`、`feature_schema.py`、`strategy_model.json`、`v2_base.py`の4ファイルを含みます。展開したartifactだけを使うofficial environment smoke testも完了しています。
