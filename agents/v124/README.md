# Kaggriculture V124

V124 keeps V123's V120 opening, executor, weed repair, dead-SELL removal, and
terminal liquidation. It changes the decision layer in three places:

1. `step` is always reconstructed as `24 * day + hour`, so both seats use the
   same clock even when the framework omits `observation.step` for seat 1.
2. The continuation library is rebuilt from state-compatible winners in the
   two V123 live submissions, restricted to current opponents initially rated
   at least 1600. A three-day source latch was tested, but fresh paired seeds
   favored the adaptive per-turn router, so `ENABLE_SEGMENT_ROUTER` is disabled.
3. Farm-clone detection is removed. A direct premium-sale predictor was also
   implemented from public farm/market/Town state and past opponent sales
   inferred from shared-market inventory changes. Under the actual safe
   intervention conditions, however, cross-submission holdout had insufficient
   precision and coverage. The predictor remains packaged for reproducible
   research, but `ENABLE_SELL_FORECAST` is deliberately disabled in the
   promoted policy.

The promoted library-only policy beat V123 14-6 with mean margin +535.5 on a
fresh 20-game paired holdout. The rejected segment latch scored 10-10 and
-146.3 on exactly the same seeds. On the same-seed seven-family panel it kept
V123's 26-2 record and raised the unweighted family mean margin from +9,371.2
to +9,425.3. Full results are retained in
`experiments/research_20260919_v124`; these are local challenger results, not
evidence of a guaranteed public-ladder gain.

The runtime artifacts contain no episode IDs, submission IDs, team names,
exact ratings, rewards, outcomes, or future observations.

Build the models with:

```powershell
.\.venv\Scripts\python.exe scripts\build_v124_current_meta.py
```

Package with:

```powershell
.\.venv\Scripts\python.exe scripts\package_submission.py --agent agents\v124
```
