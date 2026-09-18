# Kaggriculture V120

V120 replaces V119's five long open-loop replay tapes with a turn-by-turn
case policy learned from the dominant live opponent family in the two supplied
V119 submissions.

At each turn it:

1. reads only the current observation;
2. builds a 558-value state description covering money, market, town demand,
   both visible farms, own private inventory, unit positions, and tile state;
3. restricts the 37 successful public-replay cases for that turn to the same
   worker count when possible;
4. emits the action belonging to the nearest current state.

The runtime model does not contain episode or submission ids, ratings, rewards,
outcomes, or future observations. The offline builder deliberately selected
the 37 games in which the source policy defeated V119; this is documented as
an overfitting risk, not hidden as independent evidence.

## Evidence

- V119 live sample: 148 games, 73W/69L/6D.
- Dominant new opening family: V119 went 6W/37L in 43 games.
- New-seed local V120 versus V119: 18W/2L, mean margin +8,880.65.
- Four older source families: 16W/0L.
- Three public candidates acquired on 2026-09-18: 12W/0L.
- Formal local total: 46W/2L across 48 games; every game completed.

These are local paired simulations, not a live rating measurement. Rating
3000 remains an objective, not a guarantee.

## Files

- `main.py`: observation features, nearest-case selector, output normalization.
- `model.json.gz`: deterministic runtime cases (SHA256 is recorded in
  `model_metadata.json`).
- `model_metadata.json`: replay provenance and exclusions.

Rebuild the model with:

```powershell
.\.venv\Scripts\python.exe scripts\build_v120_imitation.py
```

Build the deterministic submission archive with:

```powershell
.\.venv\Scripts\python.exe scripts\package_submission.py --agent agents\v120
```

