# v1

添付資料で推奨された `Economic Core + Closed-loop Scheduling + Market Timing + Opponent Adaptation` を、公式 `kaggle-environments==1.32.7` 向けに実装した最初の自作agentです。

## Runtime files

- `main.py`: Kaggle entrypoint。top-levelの `agent(obs)` を公開する標準ライブラリのみの単一ファイル。
- `metadata.json`: version、方針、検証結果、提出状態。
- `CHANGELOG.md`: このversion内で行った修正。

## Policy summary

- Day 0–3はWheat/Carrotでcash flowを作る
- Day 4以降にCow/Sheep/Strawberryへ段階移行する
- `FEED`、`WATER`、期限付き `HARVEST` を損失リスク順に処理する
- worker inventoryを考慮してWheat、動物、Fertilizerをshedから配送する
- premium商品をTown消費後に小口売却し、Day 28以降は清算する
- 相手の公開farmがCow/Sheep/Strawberryへ偏った場合に自分のtargetを軽くずらす

詳細設計は [../../docs/strategy-v1.md](../../docs/strategy-v1.md)、paired benchmarkは [../../docs/benchmark-v1.md](../../docs/benchmark-v1.md) を参照してください。

## Validate from repository root

```powershell
uv run pytest
uv run python scripts/run_match.py `
  --agent agents/v1 `
  --opponent starter `
  --pairs 3
```

## Build

```powershell
uv run python scripts/package_submission.py `
  --agent agents/v1
```
