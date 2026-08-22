# Agents

Kaggleへ提出できるruntimeをversion単位で保存します。実験ログ、replay、集計結果、提出tar.gzはここへ置かず、それぞれ `data/` と `artifacts/` に分離します。

現在のagent:

- `v1`: closed-loop economic rule agent v1
- `v2`: Top 3 replayで校正したadaptive productive-capital agent
- `v3`: Top-3 expert-distilled hybrid strategy agent
- `v4`: feasibility-projected expert strategy with route-dense execution
