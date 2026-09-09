# Late-premium reversal: Day 12-20 post-hoc accounting

Date: 2026-09-02  
Hypothesis: `H_WEAK_LATE_PREMIUM_REVERSAL_001`  
Dataset role: Development post-hoc  
Evidence: E1 mechanistic replay accounting, not a Best Response estimate

## Result

The dominant explanation in the frozen loss regime is **H1, more precisely a
pre-Day12 plus Day12-20 premium production/portfolio-mix deficit**. V111 has
more Strawberry and Milk throughput, but the opponents enter Day12 with more
premium stock and subsequently produce much more Melon and Wool. H2 is not
supported as the primary mechanism, H3 is a small secondary effect, H4 is not
supported, and H5 is not causally identified by these observations.

This result does not authorize a V114 implementation. All six seat-level
conditions use seed `29117001`, one Town regime, and three continuations with
one opponent action prefix through step 200. V111 and V113 execute identical
actions in these six paired conditions.

## Reproduction and accounting integrity

Only the six frozen V111 conditions were rerun: three continuations times both
seats. The duplicate V113 arms were not rerun. Every terminal outcome and every
stored focal/opponent action fingerprint reproduced exactly. The accounting
simulation matched the replay after every Day12-20 transition for money,
private product holdings, on-farm yield, and shared-market inventory: 192
transitions times two players per game, across six games.

The machine-readable result is
[`late_premium_accounting.json`](../data/analysis/late_premium_accounting_20260902/late_premium_accounting.json).
It contains all nine products, both players, exact engine-committed sells,
per-unit realized sale value, market buys, field and overflow loss, shared
market inventory, and Town consumption.

## Premium flow, Day 12 inclusive to Day 20 exclusive

Values below are descriptive means over six dependent seat-level conditions.
They are not six IID samples.

| Flow | V111 | Opponent | V111 - Opponent |
|---|---:|---:|---:|
| Initial private + on-farm premium | 14.00 | 36.00 | -22.00 |
| Production | 252.00 | 264.00 | -12.00 |
| Harvest | 211.00 | 217.00 | -6.00 |
| Sell units | 180.00 | 198.67 | -18.67 |
| Realized sale value | 38,947.67 | 43,077.67 | -4,130.00 |
| Ending private | 31.00 | 27.33 | +3.67 |
| Ending on-farm | 55.00 | 73.00 | -18.00 |

The initial 22-unit gap plus the 12-unit production gap yields a 34-unit
available-premium disadvantage. That is the upstream source of the 18.67-unit
sell gap. The opponent's extra realized premium revenue is 4,130 coins during
the window, while V111's visible-cash margin moves from +1,308 on Day12 to
-1,043 through -1,461 on Day20, a swing of -2,351 through -2,769. Purchases and
other product cash flows offset part of the premium-sale difference.

## Product decomposition

| Product | Initial owned Δ | Production Δ | Harvest Δ | Sell-units Δ | Sale-value Δ | Ending owned Δ |
|---|---:|---:|---:|---:|---:|---:|
| Strawberry | 0 | +39 | +35 | +26.00 | +5,139.67 | +13.00 |
| Melon | -11 | -22 | -24 | -22.67 | -4,219.67 | -9.33 |
| Milk | -9 | +16 | +1 | +2.00 | +306.67 | -4.00 |
| Wool | +7 | -45 | -18 | -24.00 | -5,356.67 | -14.00 |

The label “premium deficit” is therefore too coarse. V111 overproduces and
outsells Strawberry, and slightly outsells Milk. It loses the window on the
Melon/Wool side of the product mix. This is consistent with the opponent's
larger Sheep exposure, but it is not evidence that literal Cow replacement is
the right intervention.

## H1-H5 diagnosis

### H1 Production deficit: primary, regime-specific

Supported for this dependent regime. The problem begins before the accounting
window: the opponent owns 36 premium units at Day12 versus V111's 14. Within
the window the opponent also creates 12 more net premium units, driven by +45
Wool and +22 Melon production relative to V111, partly offset by V111's +39
Strawberry and +16 Milk production. The actionable concept is a route/product-
mix mismatch, not a blanket instruction to sell more.

### H2 Harvest/collect deficit: not primary

Raw premium harvest is only six units lower. Relative to initial on-farm stock
plus new production, V111 harvests 79.3% versus the opponents' 72.3%. V111 is
therefore not leaving a larger fraction of available output uncollected.
Fertilizer collection is recorded separately in the artifact (99 versus 112
units) but does not explain the premium conservation equation.

### H3 Private inventory release deficit: small secondary contribution

V111 sells 85.3% of initial-private-plus-harvested premium versus 87.9% for the
opponents and ends with 3.67 more private premium units. A small release gap is
present, but it cannot explain the upstream 34-unit availability gap and is
not the dominant mechanism.

### H4 Market timing / realized-price deficit: not supported

The volume-weighted realized premium price is 216.38 for V111 and 216.83 for
the opponents. The 0.46-coin difference per unit is negligible relative to the
18.67-unit volume gap. No premium sale in this window occurs at the engine's
one-coin floor. V111's loss is not caused primarily by selling an equivalent
volume at worse prices.

### H5 Opponent response / shared-market externality: not identified

The opponent's extra committed sales mechanically enter the shared market and
the artifact exactly reconciles market inventory with both players' sales and
Town withdrawals. That establishes the market externality, not a policy
response. Two continuations (`frontier_moon` and `high_score`) are explicitly
fixed step-indexed routes and cannot react to V111's public farm. The third is
observation-dependent, but this analysis contains no controlled own-policy
intervention. A second-order response is therefore unnecessary to produce the
observed reversal and remains unestimated here.

## Decision

Do not implement “sell more premium” or create V114 from this result. The next
valid test is a pre-registered, independent-seed/continuation targeted panel
that separates:

1. earlier Melon/Wool productive capacity or option preservation;
2. a small inventory-release intervention with production held fixed; and
3. a reaction-aware intervention against genuinely closed-loop opponents.

Only an intervention that produces actual treatments and net Loss-to-Win
without compensating Win-to-Loss can become the single V114 Best Response.

