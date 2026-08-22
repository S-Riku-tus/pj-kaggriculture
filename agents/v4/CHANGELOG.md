# Changelog

## 4.0.0 - 2026-08-22

- v3のRank1 openingとTop-3 learned strategyを継承。
- PastureをAnimalより先に用意し、配置可能容量を超える購入を禁止。
- Melon/Strawberryのpayback horizon guardとSeed JIT batchを追加。
- 終了済みongoing cropとweedをDIGして即時再利用するlifecycle管理を追加。
- 毎日全作物をWaterせず、生存・収量上必要な日だけWaterするよう修正。
- 距離だけでなく同一tileの複合作業密度を評価するglobal assignmentへ刷新。
- Fertilizerを1個ずつ運ぶ経路を廃止し、最大4個のroute loadへ変更。
