# Round-2 resume commands

```powershell
.\.venv\Scripts\python.exe scripts\learning_round2.py --help
.\.venv\Scripts\python.exe scripts\learning_round2.py diagnose
.\.venv\Scripts\python.exe scripts\learning_round2.py collect-a2 --round 1
.\.venv\Scripts\python.exe scripts\learning_round2.py train-a2 --rounds 1
.\.venv\Scripts\python.exe scripts\learning_round2.py collect-a2 --round 2
.\.venv\Scripts\python.exe scripts\learning_round2.py train-a2 --rounds 2
.\.venv\Scripts\python.exe scripts\learning_round2.py build-b2
.\.venv\Scripts\python.exe scripts\learning_round2.py train-b2
.\.venv\Scripts\python.exe scripts\learning_round2.py b-headroom
.\.venv\Scripts\python.exe scripts\learning_round2.py train-bc2
.\.venv\Scripts\python.exe scripts\learning_round2.py evaluate --bank all
.\.venv\Scripts\python.exe scripts\learning_round2.py finalize
```

各commandはexclusive lock、開始/終了/exit codeを`commands.jsonl`へ記録する。既存の完了artifactがある場合も上書き対象はこのstudy内だけで、旧studyは変更しない。
