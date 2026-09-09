# Kaggriculture V111

V111 keeps V110's complete route family, deterministic executor, critical
fallback, and supported near-clone market timing.  Its new strategic layer is
a public-state ridge model trained on Rank 1–3 complete replays to predict the
farm portfolio change 72 turns ahead.

The model is isolated from mechanics.  It can request one bounded goal:

- convert the final planned two-Cow transaction to Sheep when Yarn first
  appears as shop three and the future-goal signal is supported.

A second-shop Yarn veto was tested and rejected because its result did not
reproduce across both episode and action-lineage validation splits.  Its
diagnostic code stays explicitly disabled.

The second operation rewrites the purchase, pickup, and two placements only
when cash and private inventory checks succeed.  Feeding, movement, pasture
placement, market limits, and V109's emergency fallback stay deterministic.
An unknown or out-of-support state executes unchanged V110.

The 24-turn model is retained in the research artifact but disabled at
runtime because it did not beat a zero-change baseline on held-out games.  The
72-turn model did on both whole-episode and h200-action-lineage test splits.

V110's recorded rating of 1681.5 is evidence about V110, not V111.  Rating
3000 remains an objective; it is not a verified or guaranteed consequence of
these offline tests.
