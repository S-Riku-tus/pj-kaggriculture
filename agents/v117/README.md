# Kaggriculture V117

V117 is a frozen numeric research artifact derived only from V111.  V111
remains the production Champion.

The primary Cow-deferral design was rejected before any W/D/L result because
its Cow debt, maintenance, sale attribution, and state-compatible catch-up
could not be closed without replacing the field executor.  V117 therefore
uses the preregistered one-time fallback `late_land_order_resequence`.

When current state has exactly two unlocked quadrants and V111 itself emits a
late `SELL MELON` followed by `BUY_ANIMAL COW 2`, a standard-configuration,
hands, shed, market-slot, feed-reserve, and sequential-cash preflight may append
`BUY_LAND` to the same transaction.  The original Cow purchase and all V111
field actions are retained.  After the third quadrant is confirmed in state,
the later duplicate V111 `BUY_LAND` is removed exactly once.

The implementation never keys on step, seed, source, opponent identity,
episode/submission ID, replay signatures, future RNG, or opponent private
state.  It adds no Tomato, Carrot, Goose, Sheep, terminal sale, PSR route, or
v116/P1 expression.

See the experiment preregistration and report under `docs/` for the frozen
gate, package hash, local results, and submission decision.
