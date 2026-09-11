# Kaggriculture Agent

A competition agent for the Kaggle simulation
[**Kaggriculture**](https://www.kaggle.com/competitions/kaggriculture) — a
turn-based, 2-player farming simulator: 30 days × 24 turns, highest bank
balance when the season ends (step 718 = day 29, hour 22) wins. Unsold
inventory is worth $0.

**Measured against the real engine: ~$80,000 mean over 10 seeds**, up from
$12,712 for the first version. Wins every match against the built-in
`random` and `starter` agents, with zero plant deaths, zero animal escapes
and a fully liquidated shed at the bell.

## Files

| File | Purpose |
|------|---------|
| `agent.py` | **The submission.** Self-contained, stdlib-only `agent(obs)` — paste into a Kaggle notebook and run. |
| `test_agent.py` | Real-engine test suite: full 720-step matches vs `random`, `starter` and itself, checking survival, liquidation and validity. |
| `bench.py` | Multi-seed benchmark (mean / median / min / max). |
| `tune.py` | Parameter sweeps — the portfolio caps were chosen with this, not by intuition. |
| `diag.py` | Single-match diagnostics: revenue by product, farm layout, share of turns spent walking. |
| `analyze_market.py` | Price-curve analysis: what each product's market can actually absorb. |
| `fuzz_test.py` | Degenerate/malformed observations must never crash the agent. |
| `STRATEGY.md` | The full reasoning, the measurements behind it, and every sweep. |
| `docs/` | Competition reference documents. |

## Local setup

`pygame` (an optional `kaggle-environments` dependency) fails to build on
Python 3.14, so install without it — the kaggriculture engine doesn't need it:

```bash
pip install kaggle-environments --no-deps
pip install jsonschema requests numpy
```

## Running

```bash
python test_agent.py          # correctness: 6 real-engine matches
python bench.py starter 10    # performance: 10 seeds
python bench.py self 5        # mirror match (shared, saturating market)
python diag.py 42             # where the money came from
python tune.py MAX_COWS 4 6 8 # sweep any constant
```

## The short version of the strategy

Three findings reversed the obvious plan:

1. **`CARE` rewards slow animals.** It banks +1 product per day and pays the
   whole bank out on the next production day, so a sheep (produces every 3
   days) gets a 3× multiplier and a goose only 1×. A sheep placed on day 2 is
   worth **$6,073** on a single tile; a goose is worth $2,244.
2. **Geese are a trap.** They have the best headline stat in the rulebook
   (1.00 yield/tile/day) but eat a wheat a day, and 400 wheat costs $15,340.
   Sweeping the flock from 0 to 20 birds, *every* goose made the farm poorer.
   The final portfolio keeps none.
3. **Labour, not land, is the constraint.** About two thirds of unit-turns are
   spent walking. Hiring eight hands costs $54/day and was the single most
   valuable change in the whole project (+$12k).

So: buy sheep and cows on day 0 (placement day drives their entire lifetime
value), ring the shed with pastures, run a rolling melon program on the outer
tiles, grow wheat for feed, take exactly one extra quadrant, hire hard, sell
in batches sized to each price curve, and liquidate everything from day 28.
Fertilizer is the quiet third engine — every animal drops one free per night
and 200 of them are worth $16k.

Full reasoning and all measurements are in `STRATEGY.md`.

## Using it on Kaggle

```python
from kaggle_environments import make

# Paste the entire contents of agent.py here (or %load agent.py).

env = make("kaggriculture", configuration={"episodeSteps": 720})
env.run([agent, "random"])
env.render(mode="ipython", width=800, height=800)
```

No external packages are needed. Persistent state lives on `agent._states`,
keyed by player id, so a single process can safely run both sides.

## A note on the leaderboard

Kaggle simulation competitions score with a skill rating, not with in-game
money: submissions start near **600** and climb only as they play and win
matches. A fresh submission sitting at 600 has usually just not played enough
games yet. What this agent can control is winning its matches, which it does
against every opponent available locally.
