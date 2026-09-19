# V122 data and code notice

V122 combines locally written sparse-routing and execution-repair code. Its
continuation model is derived from public Kaggle episode replays; offline
provenance is recorded in `model_metadata.json`.

The runtime model excludes episode and submission identities, ratings, rewards,
outcomes, and future observations. Public-replay selection can overfit, and the
3000 rating is a target rather than a measured or guaranteed result.

SELL price-impact reordering was evaluated but deliberately disabled after it
changed two independent smart-farm wins into losses on a close held-out seed.
