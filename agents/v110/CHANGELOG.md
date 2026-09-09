# Changelog

## 110.0.0 - 2026-08-31

- Preserve V109's full default/first-YARN/second-YARN routes and deterministic
  execution/fallback layers.
- Infer opponent premium supply from public market transitions, Town demand,
  and the candidate's effective sales.
- Add conservative public-state near-clone confidence rather than identity or
  submission-specific matching.
- Move an existing planned Strawberry/Melon/Milk/Wool sale at most four turns
  earlier only in the confirmed near-clone regime.
- Detect a matching opponent front-run before enabling the bounded
  second-order candidate.
- Keep uncertain states on the unchanged V109 trajectory.
- Reject and disable general sale-phase front-running after episode-split live
  playback produced negative future quote support.
- Add live-log analysis, lower-tail/state-coverage diagnostics, forced-fallback
  stress, purity tests, and self-contained archive verification.
- Keep the 3000 rating target explicitly unverified pending live evaluation.
