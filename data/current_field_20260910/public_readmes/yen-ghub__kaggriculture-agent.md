# Kaggriculture Agent

A local Python project for developing and testing an agent for the
[Kaggriculture Kaggle competition](https://www.kaggle.com/competitions/kaggriculture).

The current candidate is a rule-based, market-aware agent operating across two
quadrants with seven farm hands, four cows, and four delayed sheep.

## Requirements

- Python 3.12
- Git
- `kaggle-environments==1.32.6`

## Setup

Create and activate a virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Install the required packages:

```powershell
python -m pip install -r requirements.txt
```

## Running the project

Run one local match with detailed tracing:

```powershell
python run_local.py
```

Run the multi-seed evaluation:

```powershell
python evaluate.py
```

Some OpenSpiel warnings may appear when importing `kaggle_environments`.
They are unrelated to Kaggriculture if the match still runs successfully.

## Project structure

- `main.py` — current candidate agent
- `run_local.py` — detailed single-match tracing
- `evaluate.py` — multi-seed, both-position evaluation
- `sweep_*.py` — parameter sweeps
- `baselines/` — frozen agents used for regression testing
- `docs/mechanics.md` — observed game mechanics
- `docs/experiment-log.md` — strategy history and evaluation results
- `requirements.txt` — Python dependencies


## Current agent

The agent preserves an opening Melon wave, expands into the northeast quadrant,
and uses hands for planting, watering, harvesting, and Sheep care. It adapts
crop selection and Strawberry sales to visible opponent production and town
demand. Four cows provide Milk, while a compact four-Sheep block is introduced
after its opening crops are cleared. Final-day liquidation sells remaining
crops and animal products before the season ends.

The latest focused validation won 37 of 40 matches against its immediate frozen
predecessor. Detailed results and configuration history are maintained in the
[experiment log](docs/experiment-log.md).
