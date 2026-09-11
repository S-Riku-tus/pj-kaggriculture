# Kaggriculture agent lab

This repository contains agents, evaluation tools, replay analysis, and an autonomous search loop for Kaggle's **Kaggriculture** environment. The active workflow uses a vendored copy of the ladder engine, so ordinary local head-to-head evaluation needs only Python and does not depend on the full `kaggle-environments` package.

## Current status

- `main.py` is the original heuristic baseline, not the current research frontier.
- `candidates/E1.py` is the current promoted own-code baseline documented by the latest checked-in experiments.
- `candidates/C1.py`, `candidates/V3_12.py`, and the tape agents in `Opponents/` are evaluation yardsticks.
- `candidates/P.py` is an experimental day-planner. It failed its promotion gates and should not be treated as the current agent; see [`docs/planner-results.md`](docs/planner-results.md).
- Historical agents, rejected candidates, notebooks, experiments, and reports are retained under `archive/` for provenance. They are not supported entry points.

Candidate status can change as the evolution loop produces and validates new results. The authoritative automated report lives on the `results` branch:

```bash
git fetch origin results
git show origin/results:evolve/reports/latest.md
```

## Quick start

Python 3.10+ is recommended. The fastest local evaluator uses only the Python standard library and the vendored engine:

```bash
python3 mini_engine.py candidates/E1.py candidates/V3_12.py \
  --seeds 1 2 3 4 5 6 7 8 9 10 \
  --both-seats --jobs 4
```

Always use `--both-seats` for decisions. Kaggriculture has a deterministic seat-by-seed weed-layout effect; playing every seed in both seats cancels that bias. `seeded_h2h.py --swap-half` is retained only for reproducing historical results.

Useful `mini_engine.py` options:

```text
--engine master|1.32   choose the vendored engine version
--config JSON          override environment configuration
--both-seats           play every seed from both seats
--jobs N               parallel worker count
--no-cache             bypass the evaluation cache
--trace FILE           write per-day traces for single-seat runs
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `candidates/` | Small, curated set of active baselines and current experiments |
| `Opponents/` | Frontier, scenario, and replay-tape opponents |
| `vendor/` | Pinned Kaggriculture engine versions used by `mini_engine.py` |
| `evolve/` | Autonomous candidate generation, cascade evaluation, traces, and reports |
| `docs/` | Current specifications, findings, and reports |
| `submissions/` | Packaged Kaggle submission artifacts |
| `tools/` | Supporting analysis utilities |
| `archive/` | Historical and rejected work kept for provenance |

Generated candidates, replay dumps, caches, databases, credentials, and evolution outputs are intentionally ignored by Git.

## Local Kaggle environment

Most development should use `mini_engine.py`. To run tools that import `kaggle_environments`, create and activate a virtual environment, then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
bash setup_local_env.sh
```

The setup script installs a lightweight environment and adds the vendored Kaggriculture definition if the installed PyPI release does not yet include it.

## Replay workflow

Replay downloads require Kaggle credentials. Follow the token setup documented at the top of `sync_replays.py`; credentials must never be committed.

```bash
# Download and ingest recent games from the latest submission
python3 sync_replays.py mine --latest

# Pull ladder episodes and classify opponents
python3 pull_ladder.py

# Ingest local replay files into the SQLite analysis database
python3 harness.py ingest Replays/Auto/mine/*.json

# Print aggregate reports
python3 harness.py report

# Verify that a replay reproduces on the vendored ladder engine
python3 replay_verify.py Replays/Auto/mine/episode-REPLAY_ID-replay.json \
  --engine master

# Convert one replay seat into a deterministic tape opponent
python3 make_tape_agent.py replay.json 1 \
  -o Opponents/tape_example.py
```

`Replays/` and `kaggriculture.db` are local, regenerable data and are excluded from version control.

## Evolution loop

The autonomous search system renders candidates from the frozen chassis, evaluates them through a paired-seed cascade, and publishes reports to the `results` branch.

```bash
# Short local check
python3 evolve/loop.py --minutes 5

# Generate the latest report from the local population
python3 evolve/report.py

# Run an eight-hour search
bash evolve/run_nightly.sh 8
```

Read [`evolve/README.md`](evolve/README.md) for architecture and operations, and [`evolve/RULES.md`](evolve/RULES.md) before proposing or adding mutation blocks. Only held-out results should drive promotion; development-set leaders are expected to be seed-fit.

## Development rules

1. Evaluate meaningful comparisons on paired seeds with `--both-seats`.
2. Keep the ladder engine pinned with the candidate result; engine versions are not interchangeable.
3. Do not promote a candidate based only on development margins. Run the documented held-out and opponent-tape gates.
4. Preserve rejected work under `archive/` only when it adds useful provenance; do not repopulate the active candidate directory with generated variants.
5. Never commit Kaggle tokens, replay dumps, local databases, caches, or generated candidate batches.

## Further reading

- [`evolve/README.md`](evolve/README.md) — search architecture, cascade, Air workflow, and reporting
- [`evolve/RULES.md`](evolve/RULES.md) — measured engine facts and closed/open research directions
- [`docs/candidates-C1-H10-sep03.md`](docs/candidates-C1-H10-sep03.md) — recent candidate lineage and results
- [`docs/SPEC-day-planner-executor.md`](docs/SPEC-day-planner-executor.md) — planner design and acceptance gates
- [`docs/planner-results.md`](docs/planner-results.md) — why the current planner experiment was rejected
