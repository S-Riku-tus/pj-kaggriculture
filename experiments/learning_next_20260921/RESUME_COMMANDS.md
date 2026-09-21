# 再開・再現コマンド

作業ディレクトリは `C:\Users\shiba\Kaggle\pj-kaggriculture`。Kaggle への submit は行わない。実行済みコマンドの開始・終了・exit code・device は `commands.jsonl`、epoch 履歴は `training_logs/*.jsonl` に保存した。

## データ索引

```powershell
.\.venv\Scripts\python.exe scripts\learning_next_pipeline.py inventory
```

## B

```powershell
.\.venv\Scripts\python.exe scripts\learning_next_pipeline.py build --task b
.\.venv\Scripts\python.exe scripts\learning_next_pipeline.py train --task b
.\.venv\Scripts\python.exe scripts\learning_next_pipeline.py verify --task b
```

## A

```powershell
.\.venv\Scripts\python.exe scripts\learning_next_pipeline.py build --task a
.\.venv\Scripts\python.exe scripts\learning_next_pipeline.py train --task a
.\.venv\Scripts\python.exe scripts\learning_next_pipeline.py verify --task a
```

## 独立 BC

```powershell
.\.venv\Scripts\python.exe scripts\learning_next_pipeline.py build --task bc
.\.venv\Scripts\python.exe scripts\learning_next_pipeline.py train --task bc
.\.venv\Scripts\python.exe scripts\learning_next_pipeline.py verify --task bc
```

## archive・別process検証・closed-loop評価

```powershell
.\.venv\Scripts\python.exe scripts\learning_next_evaluate.py package
.\.venv\Scripts\python.exe scripts\learning_next_evaluate.py validate
.\.venv\Scripts\python.exe scripts\learning_next_evaluate.py evaluate --stage smoke --output-id smoke_repair1_evaluation
.\.venv\Scripts\python.exe scripts\learning_next_evaluate.py evaluate --stage calibration --output-id challenge_calibration
.\.venv\Scripts\python.exe scripts\learning_next_evaluate.py evaluate --stage development --arms b_simple,b_learned --opponents qeinstein_moev2,mooman_e052a,smart_farm,souvik_v4 --output-id b_development_evaluation
```

## 回帰検証・集約

```powershell
uv run pytest -q
uv run ruff check agents\learning_next_20260921 scripts\learning_next_pipeline.py scripts\learning_next_evaluate.py scripts\learning_next_finalize.py tests\test_learning_next.py
.\.venv\Scripts\python.exe artifacts\v125_followup_evidence\scripts\verify_fixtures.py
.\.venv\Scripts\python.exe scripts\learning_next_finalize.py
```

`datasets/**/*.npy` と各 evaluation の replay は大容量再生成物なので git ignore 対象。source/split manifest、checkpoint、metrics、CSV/JSON、archive、report は保持する。モデル欠損時は明示エラーになり、C0へ黙って戻らない。
