# Changelog

- Added episode-level train/validation/test winner-conditioned expert routing.
- Kept Rank1, Rank2, Rank3, and winning opponents as separate candidates.
- Released only a branch improving both 24h and 72h validation fidelity with
  sufficient support; all other contexts fall back to V11.
- Disabled that relative branch after paired unseen closed-loop diagnostics
  showed future-state fidelity did not imply higher relative value.
- Added experimental Wheat pickup capping and local FEED-to-CARE completion,
  then disabled both by default after paired diagnostics exposed feed/harvest
  regressions despite better direct logistics metrics.
