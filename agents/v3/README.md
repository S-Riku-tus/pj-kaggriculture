# V3 Expert-Distilled Hybrid

V3は、上位3submissionの公開replayから戦略を教師あり学習したhybrid agentです。全workerの移動を直接模倣するBehavior Cloningや、720 turn全体を探索するPPOではありません。

構成は4段階です。

1. Day 0はRank1の安定した24-turn opening choreographyを実行します。
2. Day 1-2はopeningの完成を安全な固定目標で管理します。
3. Day 3-23はRank1/2/3を別expertとして学習したmodelが、1日先のCow、Sheep、Wheat、Strawberry、Melon、Hands、Landを予測します。直接対戦から学習したpairwise gateがTown regimeに応じてexpertを選びます。
4. Day 24-29はV2由来のhorizon-aware harvest/liquidationへ戻します。

低レベルのFeed、Water、Harvest、Fertilize、Pickup、Drop、market safetyは決定論的plannerが担当します。モデルの予測値は作物・動物・土地・workerごとに範囲制限され、後半の動物新規投資も停止されます。

## 再学習

```powershell
.\.venv\Scripts\python.exe scripts\train_v3_strategy.py
```

`agents/v3/strategy_model.json`が再生成されます。学習時だけNumPyを使い、提出時の推論はPython標準ライブラリだけで動きます。

短いpipeline確認には次を使えます。

```powershell
.\.venv\Scripts\python.exe scripts\train_v3_strategy.py --max-episodes 2 --trees 2 --depth 3 --min-leaf 4 --output data\analysis\v3_smoke_model.json
```

## 検証とpackage

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_match.py --agent agents/v3 --opponent agents/v2/main.py --pairs 3 --seed 20260830
.\.venv\Scripts\python.exe scripts\package_submission.py --agent agents/v3
```

V3は複数ファイル提出です。`submission_manifest.json`に従い、`main.py`、feature schema、学習済みmodel、V2 planner baseをtar.gzへ格納します。

## 注意点

- 上位agent内部が機械学習かルールベースかは、replayだけからは断定できません。
- model validationは教師のportfolio再現精度であり、leaderboard ratingの保証ではありません。
- 公開replayからの学習利用については、提出前にcompetition固有Rulesを利用者自身でも確認してください。
