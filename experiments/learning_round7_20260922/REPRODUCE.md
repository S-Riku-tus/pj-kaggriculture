# Round7 reproduction commands

Run from the repository root with the checked local environment. None of these commands submits to Kaggle.

```powershell
.\.venv\Scripts\python.exe scripts\audit_round7_phase0.py
.\.venv\Scripts\python.exe scripts\audit_round7_data_contract.py
.\.venv\Scripts\python.exe scripts\run_round7_minimal_fixtures.py
.\.venv\Scripts\pytest.exe -q tests\test_round7_contracts.py
```

The compliant Arm A and preregistered Arm B training runs are:

```powershell
.\.venv\Scripts\python.exe scripts\train_round7_arms.py arm_a_extended_v1
.\.venv\Scripts\python.exe scripts\train_round7_arms.py arm_b_capacity
```

`models/arm_a_extended` is retained as an excluded failed-reproduction attempt. Its batch RNG restarted after initialization; `arm_a_extended_v1` fixes that and reproduces every Round6 epoch-10 array exactly.

Package and validate the selected candidate under a new archive name:

```powershell
.\.venv\Scripts\python.exe scripts\package_round7_candidates.py arm_b_plan_v3
.\.venv\Scripts\python.exe scripts\validate_round7_candidates.py --output experiments\learning_round7_20260922\arm_b_plan_v3_runtime_validation.json artifacts\submissions\learning_round7_20260922_arm_b_plan_v3.tar.gz
.\.venv\Scripts\python.exe scripts\benchmark_round7_agent.py --archive artifacts\submissions\learning_round7_20260922_arm_b_plan_v3.tar.gz --output experiments\learning_round7_20260922\arm_b_plan_v3_agent_subprocess_benchmark.json
.\.venv\Scripts\python.exe scripts\audit_round7_candidate_stages.py --archive artifacts\submissions\learning_round7_20260922_arm_b_plan_v3.tar.gz --output experiments\learning_round7_20260922\arm_b_plan_v3_stage_audit.json
```

The two pilots and the 48-game development evaluation use only development seeds:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_round7_pilot.py --workers 4 --candidate artifacts\submissions\learning_round7_20260922_arm_b_plan_v2.tar.gz --label arm_b_plan_v2 --output experiments\learning_round7_20260922\pilot
.\.venv\Scripts\python.exe scripts\evaluate_round7_pilot.py --workers 4 --candidate artifacts\submissions\learning_round7_20260922_arm_b_plan_v3.tar.gz --label arm_b_plan_v3 --output experiments\learning_round7_20260922\pilot_arm_b_plan_v3
.\.venv\Scripts\python.exe scripts\evaluate_round7_pilot.py --workers 4 --full-development --candidate artifacts\submissions\learning_round7_20260922_arm_b_plan_v3.tar.gz --label arm_b_plan_v3 --output experiments\learning_round7_20260922\development_evaluation_arm_b_plan_v3
```

Do not run seeds `2026110701..2026110732`: they remain unopened because no candidate met the development promotion condition.

After `REPORT_JA.md`, `FINAL_STATUS.json`, and `RESUME.md` are finalized, create the hash inventory and evidence archive once:

```powershell
.\.venv\Scripts\python.exe scripts\finalize_round7_artifacts.py
```
