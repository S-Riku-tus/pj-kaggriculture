# robriculture

An agent for the [Kaggriculture](https://www.kaggle.com/competitions/kaggriculture)
Kaggle × Google simulation competition — a 1v1 turn-based farming-economy game
where you maximize profit over a 30-day (720-turn) season.

## Approach

Heuristic economic engine + short-horizon planner first, reinforcement learning
held in reserve (see [ADR-0002](docs/adr/0002-heuristic-planner-before-rl.md)).
We develop several genuinely different strategies, let them fight in a local
tournament, and promote the best to the ladder
([ADR-0003](docs/adr/0003-multi-strategy-portfolio.md)).

## Layout

```
kaggisim/      shared library bundled into every submission (state, economy, actions)
strategies/    swappable agents behind one interface (lean, greedy, planner, ...)
harness/       local round-robin tournament — our fitness signal
build/         package.py: turn one strategy into a submittable tarball
tests/         no-crash regression guard (a crash = auto-loss)
docs/adr/      architecture decision records
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Develop

```bash
# Run the local tournament (all strategies + built-in bots)
python -m harness.tournament --games 20

# Regression tests (must stay green — a crash on the ladder is an auto-loss)
pytest -q
```

## Submit

```bash
# Build a self-contained tarball for one strategy (runs a smoke test)
python -m build.package greedy

# Submit from your machine with your own Kaggle CLI credentials
kaggle competitions submit kaggriculture -f dist/greedy.tar.gz -m "greedy v1"
```

Or do both in one command with `scripts/submit.py` (defaults to the recorded
`submit_default` from `harness/champion.json`; message defaults to `"<strategy> <sha>"`):

```bash
python scripts/submit.py                 # build + submit the recorded submit_default
python scripts/submit.py dairy_hands      # a specific strategy
python scripts/submit.py --dry-run        # build + smoke test only, no submit
```

Only your **latest 2** submissions are active on the ladder — treat them as
submit_default + challenger and promote deliberately.

## License

CC-BY 4.0 (see [`LICENSE`](LICENSE) and
[ADR-0005](docs/adr/0005-cc-by-4.0-and-open-development.md)) — required for prize
eligibility. Competition data is provided separately under Apache 2.0.
