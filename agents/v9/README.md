# V9 Decision-Distilled Agent

V9 keeps V8's Rank-1 opening, Top-3 24/72-hour trajectory atlas, OOD
envelope, feasibility checks, and deterministic endgame.  It adds two compact
Rank-1 forests trained on complete-episode splits:

- a 12/24-turn macro-intent model for BUY, WAIT, LAND, PASTURE, and planting;
- an immediate SELL/WAIT and sale-fraction model conditioned on the market,
  Town demand, public opponent production, and a stateless hidden-supply
  pressure estimate.

Sixty-nine episodes train the model, 25 calibrate thresholds and decide which
outputs may replace V8 rules, and 39 remain an untouched report-only test set.
The Sheep-purchase model did not pass the validation selection rule, and the
Melon market branch had insufficient held-out support, so both fail closed to
V8.  Every other learned override is also gated by the Top-3 manifold and
forest disagreement.

The field layer remains V8's deterministic safe executor.  A stateful animal
mission continuation prototype is retained behind a disabled switch for
reproducible ablation: both tested variants reduced operational quality, so
neither is active in the submission.  Likewise, the accurate WAIT classifier
is deployed only as a soft one-slot option-value cap; treating a 12-hour label
as an hourly purchase freeze caused a large trajectory regression.

The active V9 controls are learned SELL/WAIT timing, bounded land/crop intent,
and the soft herd-slot guard.  The Cow and Sheep purchase controls are coupled:
because Sheep failed validation, neither may independently alter the herd mix.

Reproduce the model and validation report with:

```powershell
.\.venv\Scripts\python.exe scripts\train_v9_decision_policy.py
```

Build the submission with:

```powershell
.\.venv\Scripts\python.exe scripts\package_submission.py --agent agents\v9
```

The full evidence and rejected hypotheses are in `docs/v9_design_report.md`.
These tests establish held-out decision fidelity and executable safety, not a
Kaggle rating and not a guarantee of the 3000-rating target.
