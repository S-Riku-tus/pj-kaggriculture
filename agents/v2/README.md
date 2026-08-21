# v2

V1と上位3提出の完全replayを同じKPIで再解析し、上位に共通した経済状態をclosed-loop policyへ移したagentです。Kaggle提出時は標準ライブラリだけを使う単一の `main.py` として動作します。

主な変更:

- Day 0を `6 Wheat + 11 Melon + 2 Cow + 2 Sheep` のproductive-capital openingへ変更
- 既存区画を90%前後まで使ってから土地を購入し、第3区画で停止
- Town需要、現在価格、相手供給からCow・Sheep・Strawberry目標を再計算
- Animal → Fertilizer → Cropの循環と、Day 21以降のWheat回転を強化
- worker数を作業密度に合わせて2–12人へ段階化
- Day 27から清算を開始し、Day 29は現金化可能な距離の作業だけを実行

解析根拠は [../../docs/analysis-v2.md](../../docs/analysis-v2.md) を参照してください。

```powershell
uv run pytest
uv run python scripts/run_match.py --agent agents/v2 --opponent agents/v1/main.py --pairs 5
uv run python scripts/package_submission.py --agent agents/v2
```
