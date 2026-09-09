# Top366 Cow/Sheep continuation-package analysis

## Evidence status

This is Development-set Bronze replay analysis at **E1**. It is useful for
hypothesis generation and for specifying a later lineage-held-out E2 test. It
is not closed-loop evidence, does not authorize an Agent change, and cannot
promote V113 or any future continuation policy.

The machine-readable result is
`data/analysis/v113_continuation_package_bronze_v2.json`. It retains every
episode, lineage profile, cohort mean, and metric definition.

## Coverage and archetypes

- Triggered: 84/366 episodes (22.95%), across 25 action lineages.
- Material 72-turn animal movement: 56 episodes across 21 lineages.
- No material animal movement: 28 episodes across four lineages.
- Dominant no-material archetype: lineage `a10f229861f92b52`, 24/28 episodes
  (85.71%). It is reported separately rather than counted as 24 independent
  confirmations.
- Remaining no-material archetypes: four episodes across three lineages.

The most important correction is that all 56 material episodes had
`Cow delta = 0`; their Sheep delta was +2 to +6. Thus the observed 72-turn Top
movement is **Sheep expansion**, not replay evidence of literal Cow removal or
of a causal `Cow2 -> Sheep2` transaction. The old “Cow-to-Sheep” shorthand
must not erase these component deltas.

## Lineage-weighted continuation comparison

The table reports lineage-weighted means. Market orders are recorded requests,
not audited committed transactions.

| Metric | Material 56 / 21 lineages | Dominant no-material 24 / 1 lineage | Other no-material 4 / 3 lineages |
|---|---:|---:|---:|
| H72 Sheep delta | +3.95 | 0.00 | 0.00 |
| H72 Wheat tile delta | +11.62 | +15.21 | +15.33 |
| H72 FEED / CARE | 36.93 / 38.39 | 39.00 / 39.00 | 38.00 / 38.00 |
| H72 HARVEST actions | 16.29 | 25.00 | 25.00 |
| H72 hand active rate | 87.05% | 79.83% | 81.34% |
| H72 other-crop plant actions | 10.76 | 18.00 | 18.00 |
| H72 Wool / Milk sells | 10.43 / 15.75 | 8.00 / 18.00 | 8.00 / 17.67 |
| H144 FEED / CARE | 83.65 / 85.17 | 77.67 / 80.00 | 74.67 / 77.33 |
| H144 hand active rate | 87.45% | 82.91% | 83.40% |
| H144 other-crop plant actions | 12.24 | 18.00 | 18.00 |
| H144 Wool / Milk sells | 33.94 / 39.11 | 28.00 / 51.00 | 31.33 / 45.67 |
| Terminal Wool / Milk sells | 233.69 / 166.05 | 136.00 / 280.67 | 142.67 / 235.33 |

The material cohort co-moves with greater hand utilization, Sheep-specific
FEED/CARE, later Wool throughput, lower Milk throughput, and fewer non-Wheat
crop planting actions. In lineage-level correlations, actual tilt correlates
with H144 Sheep FEED (+0.774), Sheep CARE (+0.776), and hand-active rate
(+0.722); it is negatively correlated with H144 other-crop planting (-0.655)
and Milk sales (-0.406). Terminal Wool sales correlate +0.709, while terminal
Milk sales correlate -0.376.

These are continuation-package co-movements, not isolated treatment effects.
State, shop regime, source selection, and lineage can jointly cause all of
them.

## Dominant no-material archetype

The 24-episode lineage follows a stable non-conversion continuation: by H72 it
adds about 15.21 Wheat tiles, adds 18 Strawberry tiles, removes 12 Melon tiles,
and emits 18 other-crop plant actions. It holds much more Wheat market exposure
than the material cohort (56.43 versus 26.27 mean exposed units at H72) and
finishes with substantially more Milk than Wool sales (280.67 versus 136.00).

The four remaining no-material episodes look similar on coarse route metrics,
but they remain a separate three-lineage cohort in the JSON. Source names are
not treated as independent policies.

## Retained feature families

Each window (H72, H144, terminal) now includes:

- Cow, Sheep, Goose, Wheat, and every other crop portfolio delta;
- crop seed/product holdings, PLANT, WATER, HARVEST, seed buys, and sells;
- generic and animal-specific FEED/CARE plus crop/product-specific HARVEST;
- hand availability, active rate, and FEED/CARE/HARVEST/PLANT/WATER task mix;
- Wool/Milk and all-product sale occurrence, first/mean/last timing;
- public price/inventory start, end, mean, range, and change per product;
- private sellable-inventory unit-step exposure and public-price-weighted
  marked-to-market exposure;
- requested market-order coverage, units, and public-price-valued sells.

The next valid step is to freeze a continuation-package hypothesis and test it
on unseen action lineages as E2. No package should be transferred to an Agent
from this report alone.
