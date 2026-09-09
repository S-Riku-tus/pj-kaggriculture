# Kaggriculture V113

Status: **PROMISING_UNPROVEN — do not promote and do not use as the V114 base.**

V113 preserves V111's complete route and deterministic executor. It broadens
the final Cow-to-Sheep substitution when V111's 72-turn model has a strong
(`tilt >= 1.5`) in-support signal. The latest 366 Rank1-3 replays support the
direction prediction at E1/E2 only; they do not establish causal policy value.

The preregistered executable-opponent evaluation found 0.0 percentage-point
paired win-rate uplift in every sampled action family, with no Loss→Win or
Win→Loss transition. Treatment also introduced an
`unexpected-late-purchase-action` fallback in 8/60 source-opponent pairs, so
the Safety hard gate failed. See
`docs/v113_champion_challenger_evaluation_report.md`.

An experimental change that moved price-sensitive SELL orders before
non-premium orders was rejected after a same-seed ablation lost 71 coins on
average. The code remains disabled for reproducibility; submitted V113 keeps
V111's market ordering.

The agent does not claim production promotion, a verified rating of 3000, or
E3/E4/E5 support. Champion remains V111.
