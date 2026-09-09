# Manual Kaggle opponent acquisition

## Why this exists

The local Kaggle CLI has no authenticated session. Anonymous `GetKernel` and
`ListKernelSessionOutput` calls return HTTP 403 even for public notebooks.
Browser-visible scores and indexed code snippets are Discovery leads only;
they are not executable Gold evidence.

The current immutable acquisition queue is
`experiments/independent_gold_pool/public_kaggle_acquisition_queue_20260902.json`.
Start with the lowest numeric priority.

## Browser download

1. Open the exact queued URL while signed into Kaggle.
2. Select the queued notebook version when one is specified.
3. Prefer **Download notebook output**. This should preserve `main.py` or the
   exact `submission.tar.gz` produced by that run. Use **Download code** only
   when no output exists, and do not claim output identity for a code download.
4. Do not unpack, rename, or edit the downloaded file before ingestion.
5. Keep credentials and browser cookies outside this repository.

## Safe ingest

From the repository root, run (replace the three values):

```powershell
.\.venv\Scripts\python.exe scripts\ingest_kaggle_opponent_artifact.py `
  --artifact "C:\path\from\browser\download.zip" `
  --candidate-id "kaggle_rayk_rank_your_agent_v11" `
  --source-url "https://www.kaggle.com/code/raykkretzschmar/kaggriculture-rank-your-agent/output" `
  --exact-public-output
```

Add `--script-version-id ID` when the queue provides one. If the notebook page
publishes a file hash, add `--expected-sha256 HASH`. The ingest tool:

- preserves the raw bytes and SHA-256;
- rejects archive traversal, links/devices, duplicate targets, excessive
  archive depth, and oversized expansion;
- safely expands nested `submission.tar.gz` files;
- recovers files from notebook `%%writefile` cells;
- parses Python without importing or executing it;
- selects a unique `main.py` containing top-level `agent` when possible;
- emits `acquisition_manifest.json` and a common-probe-compatible
  `candidate_sources.json`.

If multiple valid `main.py` files exist, the status is
`NEEDS_ENTRYPOINT_SELECTION`. Review their provenance and rerun with a new
immutable candidate id plus `--entrypoint relative/path/main.py`. Never delete
or overwrite the earlier ingest record.

## Closed-loop probe and family collapse

The ingest command prints the exact common-probe command. It uses already-spent
Development seeds `29114001` and `29114002`, both seats, and a fresh process per
game. Run it only after reviewing the selected source. A completed four-game
probe upgrades the artifact from an acquisition lead to executable Gold for
the behavior actually run locally; it does not prove the public notebook's
displayed score or exact live-submission identity.

The resulting source must then be collapsed by its executed fingerprint. To
build a dual V111/V113 Development panel from one or more new probe files:

```powershell
.\.venv\Scripts\python.exe scripts\build_public_gold_addendum_panel.py `
  --probe "artifacts\opponent_pool\manual_kaggle_downloads\CANDIDATE\common_probe.json" `
  --output "experiments\independent_gold_pool\manual_addendum_panel.json" `
  --report "docs\independent_gold_manual_addendum_manifest.md"

.\.venv\Scripts\python.exe scripts\evaluate_v111_v113_expanded.py `
  --manifest "experiments\independent_gold_pool\manual_addendum_panel.json" `
  --panel sensitivity `
  --output "data\evaluation\v111_v113_manual_addendum_YYYYMMDD" `
  --workers 4
```

Do not append new rows to an old immutable result. Use a new addendum output
directory and record source, evaluator, engine, seeds, seats, hashes, W/D/L,
Loss-to-Win, Win-to-Loss, and family ancestry.

## Evidence boundary

- Downloaded bytes before execution: acquisition lead, not Gold.
- Completed local executable probe: Gold for local closed-loop behavior.
- Matching source name or displayed score: not an independent family.
- Replay-prefix similarity to live c03: still Bronze correspondence.
- Every artifact inspected here is Development and is excluded from Fresh
  Holdout.
