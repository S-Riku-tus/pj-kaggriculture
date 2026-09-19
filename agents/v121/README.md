# Kaggriculture V121

V121 keeps V120's opening unchanged through step 287 and replaces its
turn-by-turn global nearest-neighbour continuation with a sparse closed-loop
router.

From the two complete V120 live submissions, the offline builder selects the
winning seat in state-compatible games against opponents initially rated at
least 1500.  At runtime it contains no episode IDs, submission IDs, ratings,
teams, rewards, outcomes, or future observations.

At steps 288, 360, 432, 480, 576, and 648 the router selects a small beam of
complete winning continuations using the current public and private state.
Between gates it stays inside that beam.  The day-12 animal portfolio is
treated as a precondition rather than splicing an incompatible suffix.  A
fourth-land Tomato continuation additionally requires at least three active
Tomato-demand shop instances, 20,000 coins, three unlocked quadrants, and a
non-Wool route.

The design targets the observed V120 failure window: losses were approximately
even at day 12 but fell behind by day 20.  Rating 3000 remains an objective,
not a verified result or guarantee.

Rebuild with:

```powershell
.\.venv\Scripts\python.exe scripts\build_v121_sparse_continuation.py
```

Package with:

```powershell
.\.venv\Scripts\python.exe scripts\package_submission.py --agent agents\v121
```
