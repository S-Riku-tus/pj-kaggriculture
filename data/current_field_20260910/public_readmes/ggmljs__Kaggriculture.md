<div align="center">
  <img src="assets/logo.svg" width="100%" alt="Kaggriculture autonomous farming agent" />

  <br />

  [![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
  [![Kaggle Environment](https://img.shields.io/badge/Kaggle-Environment-20BEFF?logo=kaggle&logoColor=white)](https://www.kaggle.com/competitions/kaggriculture)
  [![Tests](https://img.shields.io/badge/tests-80%20passing-2ea44f?logo=pytest&logoColor=white)](#-verified-current-strategy)
  [![Submission status](https://img.shields.io/badge/V16%20submission-COMPLETE-2ea44f?logo=kaggle&logoColor=white)](#-submission)
  [![Policy](https://img.shields.io/badge/policy-V16%20leader--aware%20queue-7B61FF)](#-strategy)

  **A deterministic public-state farm agent for Kaggle's 720-state economic simulation.**
</div>

## 🌾 Overview

This repository contains the self-contained V16 agent for the
[Kaggriculture competition](https://www.kaggle.com/competitions/kaggriculture).
V16 retains the established public-shop routes and adds a fail-closed
leader-opening selector plus conservative market-queue ordering. It uses only
observable current-game state and never routes on identity, episode ID,
submission ID, random seed, opponent-private inventory, replay lookup, or
future actions.

```text
steps 24–96 public opening
  ├─ cow-heavy leader profile + no early Pizza → demote 10C/4S to 8C/6S
  └─ missing, malformed, or other               → unchanged route selector

all paths
  ├─ executable SELL orders move ahead of other market orders
  ├─ product restocking keeps its original relative position
  └─ step 718 projected-shed terminal liquidation
```

The Kaggle entrypoint is [`main.py`](main.py). It is self-contained, returns
JSON-safe actions, and has no runtime dependency on the rest of this
repository.

## 🧠 Strategy

- During steps 24–96, a seat-isolated sticky detector reads only the opponent's
  public tiles. At least four cows, at most two sheep, and at least twelve wheat
  tiles identify the cow-heavy leader opening.
- When that profile would otherwise enter the vulnerable 10C/4S milk route,
  V16 selects the 8C/6S route unless early Pizza demand supports milk. Missing
  or malformed farm data returns no match and leaves the established selector
  unchanged.
- Executable `SELL` orders are front-loaded while preserving their internal
  order. WHEAT/FERTILIZER restocking is not back-loaded, and unsupported
  `BUY_PRODUCT` orders are never inserted as padding.
- Zero-quantity executable market orders are removed. The input action is
  copied before queue edits, preserving retry safety.
- Existing seed and weed recovery, animal reconciliation, premium repayment,
  route isolation, action caching, and step-718 projected-shed liquidation
  remain active. Route provenance is documented in
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## ✅ Verified current strategy

The submitted V16 `main.py` SHA-256 is
`e3df9435cffe67a75ae908a1c888240b30546e4a1a86cba62904fe34e2cb4f2f`.
The repository has 80 passing tests. Starter and random matches each reached
720 states with `DONE/DONE` and a win.

A fixed four-seed, both-seat, five-opponent closed-loop panel completed all 40
games cleanly. V16 won 8/8 against V4, V5, and Wheat. The near-mirror V7 and
V10 rows each finished 4 wins, 2 ties, and 2 seat-order losses with mean margin
`+2.25`. Against the same candidate with queue control disabled, V4, V5, and
Wheat were identical while V7 and V10 each gained `+2.25` mean margin.

Six representative public replay tapes covered SpaTaro, Otter Vibe, Mengfei
Li, binghua, Matthew Huang, and Ad Space Available from both policy seats. All
12 final-hash comparisons were clean and reported zero margin regressions
against the frozen pre-queue candidate. These are open-loop action-tape
regression checks, not adaptive rematches or leaderboard forecasts.

The repository-local dependency installation encountered the Windows maximum
path limit inside an optional Orbax test fixture. Kaggriculture 1.32.7 still
imported and all applicable tests and matches ran, but `pip check` reports the
three uninstalled optional transitive packages. Exact scope and claim limits
are in [`docs/v16-strategy.md`](docs/v16-strategy.md).

## 🚜 Quick start

Prerequisites: Git, CPython 3.12.13, and a POSIX-like shell. The exact Python
version is recorded in [`.python-version`](.python-version).

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip check
python -m pytest -q
```

Run full matches and write ignored replays:

```bash
python scripts/run_local_match.py --opponent starter --seed 20260805
python scripts/run_local_match.py --opponent random --seed 20260805 --player 1
```

Build and inspect the minimal Kaggle archive:

```bash
python scripts/package_submission.py
tar -tzf dist/submission.tar.gz
```

## 📦 Submission

V16 submission `56103627`, message
`v16 leader-aware conservative queue 85aae5c`, reached `COMPLETE`. The uploaded
`main.py` maps to public Git commit
[`85aae5c`](https://github.com/ggmljs/Kaggriculture/commit/85aae5c042b23d9da45a0f5c4a57e6b2e24c2016),
which was pushed to `origin/main` before upload.

The deterministic reviewed archive is 125,637 bytes with SHA-256
`78ecfb3e3938117bdad1109eccc0a3f47f5666178c22889b2126b7cb2decc289`.
Kaggle recorded it at `2026-09-08T17:34:28.123Z`; validation was observed at
`2026-09-08T17:37:41Z` with initial dynamic public score **600.0**. A new
simulation submission begins its own rating trajectory, so this is a delivery
snapshot rather than a strength estimate.

The package contains only:

```text
submission.tar.gz
├── main.py
├── LICENSE-APACHE-2.0.txt
└── THIRD_PARTY_NOTICES.txt
```

## 🗂️ Project layout

```text
.
├── main.py                       # self-contained V16 Kaggle agent
├── scripts/                      # local evaluation and packaging utilities
├── docs/v16-strategy.md          # current strategy and evidence boundary
├── tests/                        # deterministic unit and smoke tests
├── THIRD_PARTY_NOTICES.md        # route provenance and modifications
├── AGENTS.md                     # chronological strategy history and rules
└── requirements*.txt             # portable dependency inputs and lockfile
```

## 🧭 Development gates

Before changing or submitting the agent:

1. Run `python -m pip check` and `python -m pytest -q`.
2. Complete 720-state starter and random matches from both seats.
3. Require zero per-game margin regression and preserve every known win.
4. Rebuild the archive and verify its exact contents, import, and hash.
5. Distinguish fixed tapes, closed-loop panels, remote validation, and dynamic
   leaderboard scoring.
6. Stage only explicit paths and keep secrets and generated artifacts out of
   every commit.

Repository-specific contribution and delivery rules live in
[`AGENTS.md`](AGENTS.md).

---

<div align="center">
  Fail closed, preserve every known win, then improve. 🌱
</div>
