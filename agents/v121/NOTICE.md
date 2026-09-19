# V121 data and code notice

The V121 runtime wrapper and sparse-routing logic are local additions.  Its
opening feature implementation is packaged from the repository's V120 code.
The continuation model is derived from public Kaggle episode replays and its
offline provenance is recorded in `model_metadata.json`.

The runtime model intentionally excludes replay identity, submission identity,
team names, ratings, rewards, outcomes, and future observations.  Public replay
selection is an overfitting risk and does not establish a live rating.
