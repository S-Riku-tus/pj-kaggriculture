# Kaggriculture AI Agent

Autonomous agent for the [Kaggriculture](https://www.kaggle.com/competitions/kaggriculture) farming-simulation competition — an agent earns coins by managing crops, animals, land and market trades across a 30-day (720-step) season, **against a live opponent in the same shared market**.

- **Prize pool**: $50,000 · **Entry deadline**: Sep 23, 2026
- **Platform**: Kaggle `kaggle-environments` (ELO ladder, 5 submissions/day, only latest 2 active)
- **Repo**: [github.com/zansued/kaggriculture-ai-agent](https://github.com/zansued/kaggriculture-ai-agent)

---

## 🏆 Current status

| Item | Value |
|---|---|
| **Best agent** | `mix_agent` (purearch base + clone & maturity-aware front-run) — beats purearch h2h |
| **Ladder ELO** | mix_single fresh/climbing · purearch ~1067 · c27-tuned ~1057 · 10c4s ~987 (Aug 20) |
| **Field top** | ~3100-3150 (adaptive agents) |
| **Hard truth** | fixed traces **depreciate ~30-40 ELO/day**; the field improves faster than any precomputed schedule |

**The breakthrough (Aug 20):** opponent-aware **front-running** works. When the opponent's farm signature is clone-like (or their premium production is near-mature), sell that premium product ~2 turns before the joint glut — capturing the higher price before the crash. This is the first opponent-aware technique that genuinely beats purearch h2h. **`mix_agent` is strictly ≥ purearch** (never worse, better vs clones and near-mature opponents).

---

## 🤖 The agents (ranked)

| Agent | File | vs starter | h2h vs purearch | Role |
|---|---|---|---|---|
| **mix_agent v2** ⭐ | `mix_agent.py` | ~175-181k | **+2605 (10-2)** seeds 1-12 | **Best agent.** purearch base trace + c27's clone-detection front-run (hz=2) + maturity-aware opponent front-run. Strictly ≥ purearch; = purearch vs non-clones (front-run off). |
| **c27_agent** | `c27_agent.py` | ~172k | **+1186 P0 / +2346 P1** (hz=2) | Gui's home work: c27 trace + clone-detection front-run. First purearch-beater; trace is ~2-5k weaker than purearch vs non-clones. |
| **purearch trace** | `reference/opponents/purearch_opponent.py` | ~181k | baseline | Precomputed 8 COW + 6 SHEEP; NE d7 + SW d10; 39 strawberry + 32 wheat; aggressive price-timed selling. Tight local optimum for overlays. |
| **trace_10c4s** | `data/kawasagi/trace_10c4s.json` | ~183k | 8-12 loss | purearch with 10 COW + 4 SHEEP. Loses h2h (market interaction). |
| **reactive (FarmBrain)** | `src/kaggriculture_real.py` | ~88k | 0-8 | Hand-coded greedy coordinator, 25 tiles, 9 COW + 4 SHEEP. |
| **cronograma** | `cronograma_agent.py` | 25-29k | — | Zone-based scaling agent, WIP. |
| **dispatcher v2** | `dispatcher_v2.py` | ~32k | — | Learned classifier coordinator, crop-only. v3 (animals) negative. |

> **Dead-ends kept for reference** (all tested, all lose): `market_agent.py`, `market_agent10.py`, `hybrid_agent.py`, `hybrid_switch.py`, `opponent_aware_trace.py`, `hold_wheat_late.py`, `lns_sell.py`, `convert_wheat_to_strawberry.py`, `dispatcher_v3.py`, `top_trace_oracle.py`.

---

## 📊 Performance & head-to-head (paired seeds)

| Matchup | Result |
|---|---|
| purearch vs starter | ~181k mean |
| purearch vs trace_10c4s (20 seeds) | **12-8** |
| top agent vs purearch (10 replays) | **8-10** (top wins) — its *coherent schedule* beats purearch, but it's adaptive & unreplicable as a trace |
| reactive vs purearch | 0/5 (every reactive variant) |
| any sell overlay / cap / re-calibration on purearch | loses |

---

## 🛠️ Usage

### Requirements
```bash
pip install -r requirements.txt   # kaggle-environments, numpy, joblib (dispatcher only)
```

### Benchmark vs starter / random
```bash
python benchmark.py                        # FarmBrain variants vs starter, 3 seeds
python benchmark.py --opponent random --seeds 5
```

### Head-to-head (the metric that matters)
```bash
python h2h_bench.py purearch trace_10c4s --seeds 1-20
python h2h_bench.py purearch reactive --seeds 1-20
python h2h_bench.py dispatcher_v2 purearch --seeds 1-10
```

### ⚠️ Submission format (CRITICAL)
**Multi-file tar.gz (main.py + helper modules) ERRORS on Kaggle** for this competition. **Always submit a SINGLE self-contained `main.py`** (embed helper modules via `exec`/`repr`). The mix bundle in `submissions/mix_single/main.py` shows the pattern (purearch + c27 sources embedded as strings, exec'd into namespaces).

### Submit to Kaggle
```bash
./kaggle_cli.sh competitions submit -c kaggriculture -f submissions/mix_single.tar.gz -m "mix_agent v2"
./kaggle_cli.sh competitions list -c kaggriculture   # check leaderboard
python check_submissions.py                          # your submission status/ELO
```

### Push to GitHub (token via Windows Credential Manager)
```powershell
powershell -ExecutionPolicy Bypass -File push_gh.ps1
```

---

## 🧠 Research findings (16+ sessions of hard-won facts)

1. **⭐ The front-run breakthrough (Aug 20):** opponent-aware selling WORKS. When the opponent is a clone-like build (or has near-mature premium production), sell that premium product ~2 turns before the joint glut — capture the higher price before the crash. This is the FIRST technique that beats purearch h2h. `_FRONT_RUN_HORIZON=2` is the sweet spot; selling feed-WHEAT in the front-run is catastrophic (starves animals).
2. **mix_agent = purearch base + front-run overlays** is strictly ≥ purearch (never worse, better vs clones and near-mature opponents). The clone front-run uses your own trace's future sells as the glut proxy; the maturity-aware front-run reads the opponent's visible near-mature production.
3. **Holding raises prices for BOTH players** — the opponent (selling freely) captures more of the benefit. Raw reward is a misleading h2h objective; ALWAYS measure the margin.
4. **Aggressive selling IS the production engine.** Sell overlays/caps/gates on traces destroy value (CEM/LNS confirmed). Front-running is a timing shift, not a hold.
5. **Animals are ~3× the labor ROI of crops** — COW +$19k, SHEEP +$17k, GOOSE +$11k marginal. Reactive 9+4 = 88k ceiling.
6. **Hands re-hired daily** (fib cost). 8 hands ≈ 54g/day; 12 ≈ 376g/day. 8 is optimal.
7. **Land is net loss for every greedy coordinator**; only traces scale 75 tiles.
8. **The top agent's coherent schedule is unreplicable** (state-coupled trace, tight-optimum config, coordinator ceilings). Its edge is adaptivity.
9. **Price dynamics**: fertilizer decays, milk peaks d13, wool dips then recovers, strawberry crashes after d21, melon crashes after d10, wheat rises late.

---

## 🗂️ Project structure

```
kaggriculture-ai-agent/
├── main.py                       # submission entrypoint → src/kaggriculture_real.agent (reactive)
├── mix_agent.py                  # ⭐ NEW BEST: purearch base + clone & maturity-aware front-run
├── c27_agent.py                  # Gui's c27 trace + clone-detection front-run (hz=2 tuned)
├── benchmark.py                  # vs-starter harness (named FarmBrain variants)
├── h2h_bench.py                  # head-to-head between any two agents over N seeds
├── psro_meta.py                  # Stage-5 meta-game matrix + Nash (incl. c27)
├── rhea_schedule.py              # Stage-3 CEM sell-timing search (+ --targeted)
├── top_trace_oracle.py           # oracle attempt: repair top-agent trace (NEGATIVE)
├── dispatcher_agent.py / v2 / v3 # learned dispatcher (v2 ~32k crop-only)
├── cronograma_agent.py           # zone-based scaling agent (WIP)
├── kaggle_cli.sh                 # kaggle CLI wrapper (kaggle.exe broken on Py3.14)
├── push_gh.ps1                   # push via Windows Credential Manager token
├── check_submissions.py          # ladder status checker
├── src/
│   └── kaggriculture_real.py     # FarmBrain reactive agent (88k ceiling)
├── reference/opponents/
│   ├── purearch_opponent.py      # purearch trace (181k, tight optimum)
│   └── trace_agent.py            # generic trace loader + robustness layer
├── data/kawasagi/                # trace_*.json versioned; replays/models local
│   ├── trace_purearch.json       # purearch trace
│   └── dispatcher_model.joblib   # 323MB RandomForest (dispatcher, local only)
├── submissions/                  # ⚠️ gitignored build artifacts; mix_single/main.py = the single-file pattern
├── tests/test_agent.py           # 28 unit tests
└── README.md
```

> **Note on `data/`**: gitignored (replays are 29MB each, model is 323MB). The dispatcher runtime needs `data/kawasagi/dispatcher_model.joblib` + `dispatch_extract.py` from a previous session — not reproducible from a fresh clone.

---

## 🔬 Research scripts (in `data/kawasagi/`, gitignored)

- `build_trace.py` / `decode_purearch.py` — trace extraction
- `fork_trace.py` — counterfactual regret forks
- `hand_alloc.py` — Stage-1 hand allocation analysis
- `microbench_animal.py` — animal ROI benchmark
- `mutate_*.py` — animal/sell-mix/trace mutation sweeps
- `dispatch_extract.py` — dispatcher feature extraction + training data builder
- `pure_daily.py` / `reactive_daily.py` / `trace_econ.py` — per-day economy probes

---

## 📝 License

MIT — see [LICENSE](LICENSE).

---
*Built for Kaggriculture — the field moves fast; fixed traces depreciate; adapt or lose ELO.*
