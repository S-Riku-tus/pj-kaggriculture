# 🌾 Kaggriculture — Upgraded AI Agent (V4)

Top-tier hybrid agent for the **[Kaggle Kaggriculture Simulation Competition](https://www.kaggle.com/competitions/kaggriculture)**.

Building upon the 2644.2 ladder baseline, this upgraded agent preserves the proven foundation while eliminating strategic failure points and incorporating an action safety layer.

---

## 🚀 Key Improvements & Benchmarks

Across a 20-seed validation benchmark against the competition baseline:
* **Baseline (2644.2) Average Score**: **148,391**
* **Upgraded V4 Average Score**: **160,599**
* **Performance Delta**: **+12,208 points** (+8.2% mean revenue gain)
* **Execution Speed**: **~252 turns/second** (full 720-step episode completes in ~2.85 seconds)

---

## 🧠 Architecture Overview

The agent is built on four key pillars:

1. **Prefix-Guarded Route Replay**:
   * Uses recorded master tapes from high-ranking ladder games compressed into a compact binary blob.
   * `_switch_ok` guarantees 100% prefix consistency before any continuation branch.

2. **Calibrated Public State Router**:
   * **t=226**: Switches to `YARN` route if `YARN_STORE` unlocks (boosting wool demand by 2x).
   * **t=360**: Switches to `YARN_CARROT` route if carrot price `>= 42` under Yarn.
   * Eliminates premature branch abandonment of the top-performing `MAIN` wool/wheat route.

3. **Four Online Repairs**:
   * **Weed Dig**: Transforms idle turns on weed tiles into productive `DIG` actions.
   * **Clamp Sells**: Removes unfillable sell orders that exceed shed inventory to preserve market order slots.
   * **Dead Stock Liquidation**: Sweeps surplus inventory across all 30 days based on descending market value (`price * qty`).
   * **Preserved Cash-Flow Order**: Strictly preserves the route tape's market order sequences (`market + extra`), ensuring early-turn buys and hires are funded by prior sells.

4. **Action Safety Layer**:
   * Dynamically validates farmer and hands counts, padding missing hands with legal `PASS` actions.
   * Wraps turn logic in resilient exception handling to guarantee legal degradation under edge-case observations.

---

## 📁 Repository Structure

```
.
├── my/
│   ├── Kaggriculture(2644.2).ipynb  # Primary competition notebook
│   ├── main.py                      # Standalone upgraded V4 agent
│   ├── baseline_main.py             # Original 2644.2 baseline agent
│   ├── eval_suite.py                # Multiprocessing evaluation suite
│   ├── benchmark.py                 # Benchmark runner
│   └── submission.tar.gz            # Kaggle submission archive
├── data/
│   └── kaggriculture/               # Competition rules and documentation
├── strter/                          # Starter notebook
├── try__1/                          # Fieldbook reference exploration
├── tyr__2/                          # ShopForge pasture reference exploration
├── submission.tar.gz                # Direct submission archive
└── README.md
```

---

## 🛠️ Quick Start & Local Testing

### Prerequisites
```bash
pip install -U kaggle-environments
```

### Run Local Match (720 turns)
```python
from kaggle_environments import make

env = make("kaggriculture", configuration={"episodeSteps": 720})
env.run(["my/main.py", "random"])

print("Agent Reward:", env.steps[-1][0]["reward"])
print("Opponent Reward:", env.steps[-1][1]["reward"])
```

### Run Benchmark Suite
```bash
# Run 10-seed parallel benchmark against random
python3 my/eval_suite.py --agent1 my/main.py --n 10

# Head-to-head match alternating seats
python3 my/eval_suite.py --agent1 my/main.py --agent2 my/baseline_main.py --h2h --n 20
```

---

## 📦 Submission

The submission package is ready at [`submission.tar.gz`](submission.tar.gz). It contains the self-contained `main.py` entrypoint.
