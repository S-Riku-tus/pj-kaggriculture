# Round3 reproduction commands

Run from the repository root with the checked environment:

```powershell
.\.venv\Scripts\python.exe scripts\learning_round3.py init
.\.venv\Scripts\python.exe scripts\learning_round3.py package-control
.\.venv\Scripts\python.exe scripts\learning_round3.py validate-loader
.\.venv\Scripts\python.exe scripts\learning_round3.py normalization-audit
.\.venv\Scripts\python.exe scripts\learning_round3.py executor-tests
.\.venv\Scripts\python.exe scripts\learning_round3.py p2-decomposition
.\.venv\Scripts\python.exe scripts\learning_round3.py p3-scan
.\.venv\Scripts\python.exe scripts\learning_round3.py p3-paired
.\.venv\Scripts\python.exe scripts\learning_round3.py validate-probe-loader
.\.venv\Scripts\python.exe scripts\learning_round3.py finalize
```

`p3-paired` reuses a replay only when the sidecar task digest, replay SHA-256,
seed, seat, terminal statuses, state count, engine, agent/archive, feature schema,
configuration, and opponent hashes match. Missing or stale evidence is rerun and
the prior files are quarantined, never treated as a measurement.
