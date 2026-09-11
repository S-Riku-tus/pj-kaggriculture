# Champion weakness map — 2026-09-10

The frozen Champion is V111. This map was recomputed from downloaded/cached raw replays rather than copied from old reports. However, **the V111 episodes themselves end September 1**. No newer identifiable V111 live games were available. The latest unmapped submission cannot be substituted. Fresh current-field challenge evidence comes from the new reacting executable opponents, separately reported below.

The historical sample is **95W/4D/48L**, 147 seat records / 145 unique episodes; the two self-play duplicate seats are not independent games. Mean margin 7696.5, P10 margin -10756. The 65.99% win-score is selection-dependent and is not a current rating estimate.

| Day checkpoint | Mean margin | Lead → final loss |
| --- | --- | --- |
| day12 | -2300.4 | 9 |
| day18 | 2271.9 | 17 |
| day20 | 2460.6 | 12 |
| day24 | 4894.2 | 4 |

| Loss flag (overlapping, not causal) | Count |
| --- | --- |
| close_loss_5000 | 16 |
| upset_loss_rating_gap_200 | 0 |
| premium_congestion | 48 |
| wool_heavy_opponent_ge5 | 14 |
| milk_heavy_opponent_ge5 | 48 |
| strawberry_heavy_opponent_ge15 | 48 |
| near_clone_mean_portfolio_l1_le5 | 13 |
| same_field_opening_h48 | 17 |
| unusual_crop_opponent_tomato_ge3_or_carrot_ge10 | 1 |

All 48 losses are tagged premium congestion, Milk-heavy and Strawberry-heavy. These are common background exposures, **not 48 proven market-timing failures**. Wool-heavy 14, near-clone portfolio distance ≤5 in 13, same field h48 in 17, unusual Tomato/Carrot in 1. Close losses (within 5000 coin) number 16; rating upset losses by a ≥200 initial-rating gap number 0. Market-timing causality is unidentified from one factual replay.

## Rating, opening-family and Town breakdowns

Rating bins are floored to 250-point boundaries; missing initial ratings remain a separate bin.

| Opponent rating bin | n | W/D/L | Mean margin | P10 margin |
| --- | --- | --- | --- | --- |
| 1000 | 7 | 6/0/1 | 10372.6 | -12107.0 |
| 1250 | 20 | 18/0/2 | 9294.3 | -1091.0 |
| 1500 | 89 | 54/0/35 | 3381.3 | -9532.0 |
| 1750 | 14 | 4/0/10 | -6254.2 | -20255.0 |
| 500 | 6 | 6/0/0 | 72393.2 | 61113.0 |
| 750 | 7 | 7/0/0 | 32165.6 | 17815.0 |
| unknown | 4 | 0/4/0 | 0.0 | 0.0 |

| Opponent field h48 | n | W/D/L | Mean margin |
| --- | --- | --- | --- |
| cfc595c6cf7b9f0b5fc1 | 46 | 42/0/4 | 8911.0 |
| 6793ceb55b7cd1916b38 | 36 | 15/4/17 | 893.7 |
| 96cfd968e334c017412d | 14 | 1/0/13 | -7120.6 |
| 88fe8152215124c16467 | 12 | 10/0/2 | 7320.8 |
| 496399bf8c85c620df76 | 4 | 1/0/3 | -14309.5 |
| 5f25e75e93846f4de2db | 3 | 3/0/0 | 23650.3 |
| 774059f26f155c404981 | 2 | 2/0/0 | 4483.0 |
| 7e64c493102eb3c082b0 | 2 | 2/0/0 | 10055.5 |
| a936955ceec7995af628 | 2 | 0/0/2 | -11440.5 |
| cbe432f8d897c9268756 | 2 | 0/0/2 | -12816.5 |
| 329468ddf396503def5d | 1 | 1/0/0 | 72049.0 |
| 024948a101d27d3d53fb | 1 | 1/0/0 | 86015.0 |
| 8d01ae1db4f2d18f5356 | 1 | 1/0/0 | 55301.0 |
| 760029b953716cfd8cab | 1 | 0/0/1 | -12107.0 |
| e0e217c7d11d4e0def5d | 1 | 1/0/0 | 28315.0 |
| 6d51d2c8b07d04d3911f | 1 | 1/0/0 | 29956.0 |
| fad44258e49987938d6c | 1 | 1/0/0 | 36914.0 |
| cc03e336c1b351b4ec17 | 1 | 1/0/0 | 26099.0 |
| 2463c1404092353dc2f1 | 1 | 1/0/0 | 30639.0 |
| 2a1fa693bfdb198fda39 | 1 | 1/0/0 | 14213.0 |
| 0c61d839498dd7b52502 | 1 | 1/0/0 | 11249.0 |
| 2a578963ac342bdbaa35 | 1 | 0/0/1 | -7826.0 |
| 3d8989e2986a29450886 | 1 | 1/0/0 | 80325.0 |
| b3d3c0ffa204479f8961 | 1 | 1/0/0 | 61113.0 |
| b0a53fce9883a07bbb17 | 1 | 1/0/0 | 64084.0 |
| bf50b627fe0cca432954 | 1 | 1/0/0 | 70773.0 |
| 62f5b6fcf5a087adad8b | 1 | 1/0/0 | 30759.0 |
| 18e9aa1956a6bca47bd2 | 1 | 0/0/1 | -1091.0 |
| 937d88325dbfd2b2f97d | 1 | 1/0/0 | 3776.0 |
| fbae40477615497c1446 | 1 | 1/0/0 | 24153.0 |
| def010772c8a514cb408 | 1 | 1/0/0 | 556.0 |
| c053081a0877590cc1aa | 1 | 0/0/1 | -10756.0 |
| ad214f640cc6037db3b2 | 1 | 1/0/0 | 12688.0 |
| 892fe22c6e147923fbbd | 1 | 0/0/1 | -324.0 |

| Town signature (largest 30) | n | W/D/L | Mean margin |
| --- | --- | --- | --- |
| BAKERY:1/BRUNCH_SPOT:1/FARMERS_MARKET:2/ICE_CREAM_SHOP:1/PET_CAFE:1/PIZZA_SHOP:2 | 4 | 0/4/0 | 0.0 |
| FARMERS_MARKET:2/ICE_CREAM_SHOP:2/PET_CAFE:1/PIZZA_SHOP:1/SMOOTHIE_SHOP:2 | 2 | 1/0/1 | 3644.0 |
| BAKERY:1/BRUNCH_SPOT:1/FARMERS_MARKET:1/PIZZA_SHOP:1/SMOOTHIE_SHOP:2/YARN_STORE:2 | 2 | 2/0/0 | 10306.0 |
| BAKERY:3/BRUNCH_SPOT:1/ICE_CREAM_SHOP:1/PET_CAFE:1/PIZZA_SHOP:1/YARN_STORE:1 | 2 | 1/0/1 | -4886.0 |
| BAKERY:1/BRUNCH_SPOT:1/FARMERS_MARKET:1/PET_CAFE:2/SMOOTHIE_SHOP:3 | 1 | 1/0/0 | 72049.0 |
| BAKERY:1/BRUNCH_SPOT:1/FARMERS_MARKET:1/ICE_CREAM_SHOP:1/SMOOTHIE_SHOP:3/YARN_STORE:1 | 1 | 1/0/0 | 86015.0 |
| BAKERY:1/BRUNCH_SPOT:1/FARMERS_MARKET:1/ICE_CREAM_SHOP:2/PIZZA_SHOP:2/SMOOTHIE_SHOP:1 | 1 | 1/0/0 | 55301.0 |
| BAKERY:3/FARMERS_MARKET:3/ICE_CREAM_SHOP:1/SMOOTHIE_SHOP:1 | 1 | 0/0/1 | -12107.0 |
| ICE_CREAM_SHOP:2/PIZZA_SHOP:2/SMOOTHIE_SHOP:2/YARN_STORE:2 | 1 | 1/0/0 | 28315.0 |
| BAKERY:1/BRUNCH_SPOT:1/FARMERS_MARKET:1/ICE_CREAM_SHOP:2/PET_CAFE:1/SMOOTHIE_SHOP:2 | 1 | 1/0/0 | 29956.0 |
| BAKERY:1/BRUNCH_SPOT:1/ICE_CREAM_SHOP:2/PET_CAFE:1/SMOOTHIE_SHOP:2/YARN_STORE:1 | 1 | 1/0/0 | 36914.0 |
| BAKERY:3/BRUNCH_SPOT:1/ICE_CREAM_SHOP:1/PIZZA_SHOP:1/SMOOTHIE_SHOP:2 | 1 | 1/0/0 | 26099.0 |
| BAKERY:1/FARMERS_MARKET:1/PET_CAFE:2/SMOOTHIE_SHOP:1/YARN_STORE:3 | 1 | 1/0/0 | 30639.0 |
| BAKERY:1/BRUNCH_SPOT:1/FARMERS_MARKET:1/PET_CAFE:3/PIZZA_SHOP:1/YARN_STORE:1 | 1 | 1/0/0 | 2789.0 |
| BAKERY:1/ICE_CREAM_SHOP:2/PET_CAFE:2/YARN_STORE:3 | 1 | 1/0/0 | 27400.0 |
| BRUNCH_SPOT:3/FARMERS_MARKET:1/SMOOTHIE_SHOP:2/YARN_STORE:2 | 1 | 1/0/0 | 5587.0 |
| BAKERY:1/BRUNCH_SPOT:1/FARMERS_MARKET:1/ICE_CREAM_SHOP:1/PET_CAFE:1/PIZZA_SHOP:1/SMOOTHIE_SHOP:1/YARN_STORE:1 | 1 | 1/0/0 | 28609.0 |
| BAKERY:1/BRUNCH_SPOT:3/FARMERS_MARKET:1/PET_CAFE:1/PIZZA_SHOP:2 | 1 | 1/0/0 | 7514.0 |
| BAKERY:2/BRUNCH_SPOT:1/FARMERS_MARKET:2/PET_CAFE:1/SMOOTHIE_SHOP:1/YARN_STORE:1 | 1 | 1/0/0 | 2034.0 |
| BAKERY:1/PET_CAFE:3/SMOOTHIE_SHOP:3/YARN_STORE:1 | 1 | 1/0/0 | 4105.0 |
| BAKERY:1/BRUNCH_SPOT:2/FARMERS_MARKET:1/ICE_CREAM_SHOP:2/PET_CAFE:1/PIZZA_SHOP:1 | 1 | 1/0/0 | 9147.0 |
| BAKERY:1/FARMERS_MARKET:2/ICE_CREAM_SHOP:1/SMOOTHIE_SHOP:2/YARN_STORE:2 | 1 | 1/0/0 | 2208.0 |
| BAKERY:3/BRUNCH_SPOT:2/FARMERS_MARKET:1/PET_CAFE:1/PIZZA_SHOP:1 | 1 | 0/0/1 | -4819.0 |
| BAKERY:2/BRUNCH_SPOT:1/FARMERS_MARKET:1/ICE_CREAM_SHOP:2/PIZZA_SHOP:2 | 1 | 1/0/0 | 8925.0 |
| FARMERS_MARKET:2/ICE_CREAM_SHOP:3/PET_CAFE:1/PIZZA_SHOP:2 | 1 | 1/0/0 | 12220.0 |
| BAKERY:1/BRUNCH_SPOT:1/FARMERS_MARKET:2/ICE_CREAM_SHOP:1/PET_CAFE:2/YARN_STORE:1 | 1 | 1/0/0 | 14213.0 |
| BAKERY:3/BRUNCH_SPOT:1/ICE_CREAM_SHOP:2/PET_CAFE:1/YARN_STORE:1 | 1 | 1/0/0 | 9996.0 |
| BAKERY:1/BRUNCH_SPOT:1/FARMERS_MARKET:2/ICE_CREAM_SHOP:1/PIZZA_SHOP:1/YARN_STORE:2 | 1 | 1/0/0 | 7532.0 |
| BAKERY:1/BRUNCH_SPOT:1/PET_CAFE:2/PIZZA_SHOP:1/SMOOTHIE_SHOP:1/YARN_STORE:2 | 1 | 1/0/0 | 2019.0 |
| BRUNCH_SPOT:1/FARMERS_MARKET:3/ICE_CREAM_SHOP:1/PET_CAFE:1/PIZZA_SHOP:1/SMOOTHIE_SHOP:1 | 1 | 1/0/0 | 8768.0 |

Complete h100/h200 and Town breakdowns, rather than only the displayed large groups, are in [machine-readable summary](../data/analysis/research_20260910_final/current_meta_weakness_summary.json). Fingerprints are trajectory groups, not independent latent code lineages.

## Closest losses and current challenge sensitivity

| Episode | Seat | Opponent submission | Opponent field h100 | Day18 margin | Final margin |
| --- | --- | --- | --- | --- | --- |
| 104085098 | 0 | 55874566 | bdc618943247f5de2f23 | -472.0 | -248.0 |
| 104470507 | 1 | 55924626 | 7ed68a302d037fba0f97 | 3584.0 | -324.0 |
| 104096148 | 0 | 55914250 | bdc618943247f5de2f23 | -1886.0 | -809.0 |
| 104026854 | 0 | 55867931 | 8cc4069c071a83fbfec5 | 7814.0 | -1091.0 |
| 104467537 | 0 | 55920730 | bdc618943247f5de2f23 | -1008.0 | -1214.0 |
| 104212380 | 0 | 55917201 | bdc618943247f5de2f23 | 405.0 | -1229.0 |
| 104486462 | 0 | 55928681 | d23d2cafd0e4c94345e0 | -1821.0 | -1736.0 |
| 104118543 | 1 | 55914968 | a40d2e310b79e1c8922e | -10276.0 | -1807.0 |
| 104366202 | 1 | 55922225 | bdc618943247f5de2f23 | 386.0 | -2324.0 |
| 104076150 | 0 | 55891180 | d23d2cafd0e4c94345e0 | -4921.0 | -2411.0 |
| 104073726 | 0 | 55914250 | eed6d2bfaa3770413841 | 589.0 | -2976.0 |
| 104236949 | 1 | 55917201 | bdc618943247f5de2f23 | 38.0 | -3646.0 |
| 103973489 | 0 | 55801371 | 8237b2201ec9e70cde8c | 1816.0 | -4264.0 |
| 104112011 | 0 | 55899037 | bdc618943247f5de2f23 | 319.0 | -4278.0 |
| 103935492 | 1 | 55519344 | 5167cad44af4e887f31e | 9384.0 | -4819.0 |
| 104134027 | 0 | 55915899 | a40d2e310b79e1c8922e | -9618.0 | -4979.0 |
| 104296997 | 1 | 55921229 | 5c3d304f206d625e83e3 | -7904.0 | -5378.0 |
| 104051535 | 0 | 55756320 | 8237b2201ec9e70cde8c | -3594.0 | -6083.0 |
| 104366418 | 0 | 55919325 | a40d2e310b79e1c8922e | -10392.0 | -6100.0 |
| 104439945 | 0 | 55867683 | bdc618943247f5de2f23 | 1464.0 | -6272.0 |

New current public source probes: mooman 0W/8L, souvik 2W/6L, ggmljs 8W/0L, qeinstein 0W/8L (four seeds × both seats). This falsifies the usefulness of the old near-all-winning Gold pool as the only improvement screen. It also exposes an unresolved problem: none of the conservatively independent groups is yet well established as a 30–70% matchup. Souvik is 25% on four seeds and shares ancestry. More seeds and more distinct strong source acquisitions are needed before precise promotion inference.

## Mechanism map

1. **Limited middle-game routes (E0/E1):** three route backbones; all new plants on days 15–24 are Wheat. This is a structural constraint, although portfolio diversity itself is not the objective.
2. **Shared-market congestion (E0/E1):** substantial opposing premium exposure and steep price collapse. Cow→Sheep is not automatically beneficial when both farms saturate Wool. Relative revenue and Town absorption must be considered jointly.
3. **Continuation/execution coupling (E0):** new portfolios require different harvest, feed, movement and deposit actions. Replacing purchases alone can create weeds/no-ops and change future Town RNG.
4. **Late loss recovery (E1):** 17 Day18 leads become losses; only four Day24 leads do. This prioritizes middle-game investigation over terminal tweaks as the largest prospective gap.
5. **Terminal stranded stock (E0/E1):** small and actionable, but 264.7 coin average cannot by itself close common 10k–20k current-source deficits.
6. **Opponent stock estimation (E2 predictive only):** public farm features support better stock/supply estimates, but broad-horizon any-sale probability is often nearly one and is not an effective sale-timing gate.

The largest supported **structural** gap is a narrow continuation library coupled to imperfect future-market estimates. The largest **causal** source of the leader's win advantage remains unidentified; neither mean coin, diversity nor leader imitation establishes it. The ranked interventions and new paired results determine what can be retained.
