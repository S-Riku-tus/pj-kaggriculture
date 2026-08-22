# Changelog

## 3.0.1 - 2026-08-21

- Kaggleが`main.py`を`__file__`なし・別作業ディレクトリから実行する場合も、展開済みsubmission directoryを`sys.path`から検出するよう修正。
- 3つの補助ファイルが揃ったディレクトリだけをruntime directoryとして採用。

## 3.0.0 - 2026-08-21

- Rank1/2/3の全450 public replayから、Day 3-23の1日先portfolioを教師化。
- expertを混ぜずに3つのmulti-output regression forestとして学習。
- Top3直接対戦からTown需要依存のpairwise expert gateを学習。
- Rank1のDay 0 choreographyを24-turn deterministic openingとして追加。
- 同一priorityのworker tasksをHungarian assignmentで全体最適化。
- V2のfeed reserve、animal safety、crop care、final harvest、liquidationを再利用。
- 商品別のTop3平均batch sizeをexpert weightで補間。
- 再現可能なtraining script、episode-level validation、multi-file packagingを追加。
