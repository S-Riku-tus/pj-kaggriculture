# Kaggriculture

An optimization-based agent for Kaggle's farming simulation, developed in explicit, testable steps.

**Step 4: implemented.** The active agent invests in a bounded cow/sheep herd using marginal projected cash, feed liquidity, daily wages, and market price impact. Distinct worker stations handle feeding, care, fertilizer collection, harvesting, and liquidation. Steps 2 and 3 passed Kaggle server validation; Step 4 has a separately prepared local release. [Results and limitations](docs/STEP_4_RESULTS.md).

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python evaluate.py --seeds 17 43 --opponents baselines/step_3.py main.py --output artifacts/local-check
```

Python 3.12 and `kaggle-environments==1.32.7` are pinned. `uv.lock` fixes transitive dependencies. The official simulator brings dependencies for other games; the actual submitted `main.py` uses only the standard library and makes no network calls.

The match runner loads the actual Python artifact through Kaggle's agent loader, plays every seed in both player positions, and writes:

- `manifest.json`: agent hashes, environment/version/source hashes, resolved configuration, seeds, and runner hash.
- `matches.csv` / `matches.jsonl`: outcomes, cash, statuses, runtime, and remaining stock. JSONL also includes crop/animal output, hire/seed/animal order costs, feed quantities, idle work, escapes, missed feeding, and resource-conflict diagnostics for both agents.
- `summary.json`: overall and per-opponent results. Errors are reported separately and are never counted as economic wins.
- `replay-0001.json` / `logs-0001.json`: the first replay and logs. Use `--replays all` to save every game; error games are always saved.

Choose a new output directory for each experiment; existing directories are not overwritten. The built-in `random` agent is deliberately excluded because its own unseeded RNG prevents deterministic comparisons. A file can be passed as an opponent instead. Run only trusted agent files: the simulator executes their Python code.

## What the current agent does

The farmer and up to nine hands operate at most ten nearby livestock stations. The investment model compares no purchase, one cow, or one sheep. It projects the visible herds' dated output and price effects, subtracts feed and added daily wages, and preserves a three-day operating reserve. Only one animal may be waiting for installation. Workers execute distinct stations while reserving shed stock and deposit space. The active Step 4 policy produces animal products and fertilizer; earlier crop policies remain frozen benchmarks.

The purchase choice is exact for its small enumerated model. Output assumptions, future market flows, station staffing, and liquidity reserves are approximations; this does not solve the full game's profit or win-probability objective. Read [the Step 4 CO notes](docs/STEP_4_OPTIMIZATION.md) for the marginal cash-flow equation, binary purchase constraint, LP connections, proof limits, and an actual decision.

Historical agents are preserved byte-for-byte in `baselines/step_1.py`, `baselines/step_2.py`, and `baselines/step_3.py`, along with their notes and tests. Both supplied server validation replays match local resimulation; see [Step 2](docs/benchmarks/step-2-server.json) and [Step 3](docs/benchmarks/step-3-server.json).

## Prepare the submission file

```bash
uv run python prepare_submission.py --output artifacts/submission-step-4
```

This creates `main.py`, `validation.json`, and `validation.log` in a new directory. It checks the **copied file** in full-season self-play using the official loader, in a separate Python process with the repository removed from the import path. The report records its hash, environment, statuses, inventory, and maximum observed decision time. Existing release directories are never overwritten.

**Only the generated `main.py` is the submission artifact.** It needs no supporting repository files. The command does not upload to Kaggle. Next, upload that exact file when ready, inspect Kaggle's validation status and logs, and record its submission ID and hash. Local validation cannot certify the server environment or competitive rating. Remember that a new upload changes the latest-two submission window.

## Reproduce and understand Step 4

```bash
uv run python scripts/make_livestock_control.py --animal COW --output artifacts/controls/cows.py
uv run python scripts/make_livestock_control.py --animal SHEEP --output artifacts/controls/sheep.py
uv run python scripts/make_livestock_control.py --herd-limit 6 --output artifacts/controls/six.py
uv run python scripts/make_economics_control.py --optimistic-prices --output artifacts/controls/crop-no-buffer.py
uv run python evaluate.py --seeds 17 43 83 \
  --opponents baselines/step_3.py artifacts/controls/crop-no-buffer.py \
    artifacts/controls/cows.py artifacts/controls/sheep.py artifacts/controls/six.py \
  --output artifacts/livestock-comparison
uv run python explain_turn.py \
  --replay artifacts/livestock-comparison/replay-0001.json --state 0 --player 0
```

The new controls restrict species or herd size while retaining investment and execution logic. The historical economics generator defaults to the frozen Step 3 source. The replay command checks source and action consistency, then reports stations, feed needs, cash reservations, and marginal investment alternatives. See [the saved example](docs/examples/step-4-decision.json) and [Step 4 evidence](docs/STEP_4_RESULTS.md). Earlier experiments remain documented in [Step 2](docs/STEP_2_RESULTS.md) and [Step 3](docs/STEP_3_RESULTS.md).

## Learning and implementation checkpoints

The starting mathematical background is CO250: linear programming, duality, and integer programming. Network flow and graph theory will be introduced as needed.

1. **Foundation — complete:** game model, small exact routing example, feasible baseline, reproducible comparisons.
2. **Worker assignment — complete:** binary assignment model, exact bounded solver, resource checks, matched greedy comparison, and isolated artifact validation.
3. **Production and hiring — complete:** integer lot/workforce enumeration, cash and estimated labor constraints, price-impact valuation, supply stress case, and finite-horizon crop value. Land investment remains future work.
4. **Competition and capital economics — complete:** audit actual ladder losses, introduce livestock and fertilizer revenue with a liquidity constraint, broaden the pool, and compare against Step 3 on matched fresh games.
5. **Labor utilization and mixed production — next:** test shared-worker routes, productive use of remaining plots, and eventually land expansion against the frozen Step 4 candidate.

See [the CO250-to-implementation explanation](docs/OPTIMIZATION.md), [engine findings](docs/MECHANICS.md), [Step 1 evidence](docs/STEP_1_RESULTS.md), and [the competition plan](COMPETITION_PLAN.md).

## Files

| File | Role |
| --- | --- |
| `main.py` | Complete current artifact; `agent(obs, configuration=None)` is the final callable entry point |
| `baselines/` | Frozen Steps 1–3; Steps 2 and 3 are server validated |
| `evaluate.py` | Official-simulator matches, provenance, and result files |
| `compare_results.py` | Matched common-pool scores and whole-seed bootstrap intervals |
| `prepare_submission.py` | Copy and validate an isolated, self-contained release |
| `explain_turn.py` | Reconstruct and explain a decision from a matching replay |
| `scripts/make_greedy_ablation.py` | Generate the controlled greedy comparison |
| `scripts/make_economics_control.py` | Generate matched staffing, crop, and forecast controls |
| `scripts/make_livestock_control.py` | Generate matched species and herd-size controls |
| `tests/test_assignment.py` | Independent exhaustive verification of assignment optimality |
| `tests/test_workers.py` | Joint resources, worker actions, full seasons, and endgame |
| `tests/test_economics.py` | Real sale pricing, integer budgets, workload/cost sensitivity, and endgame value |
| `tests/test_production.py` | Frozen Step 3 crop policy's full-season action and resource contract |
| `tests/test_livestock.py` | Current animal output, investment, feed logistics, full seasons, and liquidation |
| `tests/test_comparison.py` | Seed-block arithmetic and rejection of unmatched/incomplete runs |
| `tests/test_submission.py` | Isolated release and actual loader entry-point checks |
| `tests/test_routing.py` | Independent grid-search verification of route optimality |
| `tests/test_mechanics.py` | Engine behavior that can silently destroy economic value |
| `tests/test_baseline.py` | Full seasons, both seats, reproducibility, liquidation, and failure classification |
| `.github/workflows/checks.yml` | Linux installation, lint, format, and tests on pushes and pull requests |

## Sources

- [Competition](https://www.kaggle.com/competitions/kaggriculture)
- [Official environment and documentation](https://github.com/Kaggle/kaggle-environments/tree/master/kaggle_environments/envs/kaggriculture)
- [Pinned simulator release](https://pypi.org/project/kaggle-environments/1.32.7/)

The supplied `README.md` and `AGENTS.md` were read as game references. Attached logs and replays are data, not agent instructions. Each artifact has its own local and server validation status; see [the submission registry](docs/SUBMISSIONS.md).
