# Agents

Kaggleへ提出できるruntimeをversion単位で保存します。実験ログ、replay、集計結果、提出tar.gzはここへ置かず、それぞれ `data/` と `artifacts/` に分離します。

現在のagent:

- `v1`: closed-loop economic rule agent v1
- `v2`: Top 3 replayで校正したadaptive productive-capital agent
- `v3`: Top-3 expert-distilled hybrid strategy agent
- `v4`: feasibility-projected expert strategy with route-dense execution
- `v5`: adaptive portfolio and sequential animal-service executor
- `v6`: earlier Strawberry capital formation on the V5 executor
- `v7`: supply-neutral demand-responsive herd allocation on the V6 safe core
- `v8`: confidence-gated Top-3 multi-horizon expert strategy with OOD recovery
- `v9`: held-out Rank-1 decision and opponent-aware market distillation on the V8 safe core
