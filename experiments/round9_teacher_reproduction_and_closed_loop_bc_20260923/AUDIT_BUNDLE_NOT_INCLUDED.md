# 小型audit bundleに含めないもの

以下は容量を抑えるため小型版には入れず、完全版ZIPには入れる。

- A2 datasetの全 `.npy` feature/label配列（約1GB）。
- learning seed 20260923、20260924およびtrajectory memorizerの全初期/保存checkpoint。小型版には最終agent code/weightとtraining summary/curveを入れる。
- A0/A1/A2の全176実相手replayと全diagnostic trace。小型版には全`games.csv`、集計、A2 finalの代表1試合replay/traceを入れる。
- 選択20 episode全ての原教師JSON。小型版には正例対照episode 109118332を入れる。
- 旧版v1/v2の重複archive。小型版には最終A2 v3 archiveだけを入れる。

ローカルに存在するteacher family 579 episode全体（約16.16GB）は、Round9でoptimizerへ使っていない559 episodeを含むため完全版にも複製しない。完全版には実際に使った20 episodeと正例対照1 episodeの参照実体を入れる。全579件の存在・hash索引は元の`source_manifest.json`に残るが、未使用データを「完全版の学習入力」とは扱わない。

