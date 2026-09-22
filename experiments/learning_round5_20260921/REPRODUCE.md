# Round5 reproduction

前提: Windows PowerShell、repository root、既存 `.venv` の `kaggle-environments==1.32.7` と NumPy。

```powershell
.\.venv\Scripts\python.exe experiments\learning_round5_20260921\input_bundle\round4_independent_audit\audit_round4.py experiments\learning_round4_20260921.zip --out experiments\learning_round5_20260921\input_audit
.\.venv\Scripts\python.exe scripts\learning_round5.py inventory
.\.venv\Scripts\python.exe scripts\learning_round5.py representation
.\.venv\Scripts\python.exe scripts\learning_round5.py skills
.\.venv\Scripts\python.exe scripts\learning_round5.py train --epochs 18
.\.venv\Scripts\python.exe scripts\evaluate_round5_skills.py
.\.venv\Scripts\python.exe scripts\evaluate_round5_teacher_prefix.py
.\.venv\Scripts\python.exe scripts\evaluate_round5_comparison.py
.\.venv\Scripts\python.exe scripts\evaluate_round5_frozen_round4.py
.\.venv\Scripts\python.exe scripts\learning_round5.py package
```

Archive loader検査は `scripts/validate_round5_archive.py` を各arm/seatへ実行する。テスト:

```powershell
$env:PYTHONPATH=(Resolve-Path .).Path
.\.venv\Scripts\python.exe -m pytest -q tests\test_learning_round5.py tests\test_learning_round4.py tests\test_learning_round3.py
```

正式比較のseed/armは `COMPARISON_PROTOCOL.json` に結果生成前の状態で固定済み。Kaggleへの提出コマンドは再現手順に含めない。
