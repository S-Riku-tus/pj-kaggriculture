# Current meta analysis — 2026-09-10

Evidence level **E1**, Discovery. Re-extracted 236 unique replays / 472 seat records. Top-ranked cohorts contain 97 selected seat records from 30 submissions; selection favors the latest leader games and is not a random sample of all play. V111's 145 underlying episodes are historical. [Input manifest](../data/analysis/research_20260910_final/current_replay_input_manifest.json).

## Mechanics-first hypotheses

Scarcity pricing, diminishing sale prices and the $1 floor make residual Town absorption more important than gross production. Strawberry, Milk and Wool reach the floor with only about 62, 76 and 59 inventory units above the price reference respectively. Land, animal purchases and worker labor commit cash and future service actions; the same crop can be right against one opponent and overproduced against another. These E0 facts predict state-dependent continuation and sale ordering as plausible advantages.

Both players' sells are interleaved one unit at a time within a market slot. At the floor, a committed sale earns money **without adding inventory**. Thus market differences alone cannot reconstruct hidden stock. Town is consumed at its engine schedule. Daily RNG draws depend on empty farm cells before shop selection, so changing our farm can change a future shop even with an identical requested/resolved seed. Paired evaluations retain this consequence and audit its first occurrence.

## Opening and continuation

| Rank | Seat records | W/D/L | Field h48 variants | Median first land state | Carrot | Tomato | Strawberry | Cow | Sheep | Goose | Stranded price proxy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 8 | 7/0/1 | 8 | 151.0 | 8.6 | 0.0 | 19.0 | 7.9 | 5.3 | 0.0 | 80.8 |
| 2 | 10 | 7/0/3 | 1 | 151.0 | 0.2 | 0.0 | 25.6 | 7.5 | 5.5 | 2.0 | 0.0 |
| 3 | 9 | 6/0/3 | 1 | 121 | 2.8 | 11.7 | 17.7 | 6.4 | 4.8 | 5.7 | 0.0 |
| 4 | 5 | 4/0/1 | 1 | 151 | 0.2 | 0.0 | 25.6 | 6.0 | 7.8 | 1.3 | 0.0 |
| 5 | 5 | 3/0/2 | 1 | 151 | 0.1 | 0.0 | 25.6 | 6.9 | 6.9 | 1.3 | 0.0 |
| 6 | 4 | 2/0/2 | 3 | 88.0 | 2.7 | 5.2 | 20.3 | 5.7 | 7.2 | 2.1 | 0.0 |
| 7 | 5 | 4/0/1 | 1 | 151 | 0.2 | 0.5 | 25.6 | 7.3 | 6.0 | 1.8 | 0.0 |
| 8 | 5 | 4/0/1 | 1 | 151 | 0.4 | 4.3 | 20.5 | 5.6 | 5.4 | 6.1 | 0.0 |
| 9 | 8 | 1/0/7 | 2 | 151.0 | 0.2 | 0.0 | 25.6 | 7.1 | 6.2 | 1.7 | 0.0 |
| 10 | 4 | 3/0/1 | 1 | 89.0 | 0.7 | 3.5 | 23.1 | 5.3 | 7.9 | 2.4 | 208.2 |

Portfolio columns are day 6–25 means used to describe possible routes, never promotion criteria. Opening actions, first animal/hire/seed/sell times, second/third quadrant timings, action utilization, last investment and liquidation times are retained per episode in [seat metrics](../data/analysis/research_20260910_final/current_episode_seat_metrics.json). Cash, labor, quadrants, crop/animal counts, market inventory/prices, Town daily demand and opponent farms are retained in [daily trajectories](../data/analysis/research_20260910_final/current_daily_trajectories.csv).

The largest identical field-opening h48 group covers **18 submissions and 50 seat records**, but has 50 exact continuation action traces and 15 portfolio signatures. This supports shared opening plus varying continuation, while not distinguishing code changes from reactions to different states. Rank 1 has eight observed opening variants; rank 3 uses a separate opening with Tomato/Goose. Therefore opening convergence is substantial but not universal. Retain V111's coherent early execution for an isolated continuation experiment; do not claim its opening is already optimal.

Fingerprints h24/48/100/200/300/400/600/719 are stored for complete actions and farm actions. Connecting same submission or identical field h48 yields **9 conservative observed components**, not 30 independent policies and not a verified count of latent action-policy families. Different openings with similar portfolios and exact continuation mismatch can both arise through state-dependent execution; ancestry is unresolved without source.

| Field h48 | Submissions | Seat records | Exact continuations | Portfolio continuations |
| --- | --- | --- | --- | --- |
| fc3d6b3d0349544a39de | 18 | 50 | 50 | 15 |
| a936955ceec7995af628 | 4 | 10 | 10 | 10 |
| 0fb01798d3bdeebc23a3 | 1 | 9 | 9 | 9 |
| 957c2a61dd030deb2397 | 2 | 7 | 7 | 6 |
| a0508e1a3bf82127b514 | 1 | 4 | 4 | 4 |
| 5bc6791acd94a082aee1 | 1 | 2 | 2 | 2 |
| dda27db803ab0d36c277 | 1 | 2 | 2 | 2 |
| 30914d9ac624494e9a84 | 1 | 2 | 2 | 2 |
| 5b6818666c5dcacbd529 | 1 | 1 | 1 | 1 |
| cc7ac2928d44b7a13fac | 1 | 1 | 1 | 1 |
| b4d47d620fc83c80e66d | 1 | 1 | 1 | 1 |
| 63b8d934b6c1072348d9 | 1 | 1 | 1 | 1 |
| 3aa67495c1d79c0dbc45 | 1 | 1 | 1 | 1 |
| a16422ccf68a7a383e3d | 1 | 1 | 1 | 1 |
| 106bcfcef283fdb44e04 | 1 | 1 | 1 | 1 |
| 5472fadeff242d4aeb64 | 1 | 1 | 1 | 1 |
| b3163494d9e9bfe28a81 | 1 | 1 | 1 | 1 |
| fbd26eb7b7d53d010ab6 | 1 | 1 | 1 | 1 |
| 7b06eaad34f5a85cc0c3 | 1 | 1 | 1 | 1 |

## Shop event study and opponent dependence

Events are actual newly unlocked shops, with pre-event 24-step asset change and post-event 72-step asset/margin change. Product-demand events are compared with other new-shop events. These windows have overlapping episodes and day/route/opponent confounding. They are descriptive event studies, **not difference-in-differences causal estimates**.

| Cohort | Product | New shop demands it | Event rows | Pre24 asset Δ | Post72 asset Δ | Post72 margin Δ |
| --- | --- | --- | --- | --- | --- | --- |
| champion_v111 | CARROT | False | 774 | 0.163 | 1.760 | 890.3 |
| champion_v111 | CARROT | True | 255 | -0.067 | 1.576 | 305.7 |
| champion_v111 | MILK | False | 664 | 0.229 | 1.182 | 700.8 |
| champion_v111 | MILK | True | 365 | 0.214 | 1.222 | 826.6 |
| champion_v111 | STRAWBERRY | False | 520 | 0.940 | 0.283 | 778.2 |
| champion_v111 | STRAWBERRY | True | 509 | 0.849 | -0.041 | 711.9 |
| champion_v111 | TOMATO | False | 766 | 0.000 | 0.000 | 825.6 |
| champion_v111 | TOMATO | True | 263 | 0.000 | 0.000 | 511.7 |
| champion_v111 | WOOL | False | 905 | 0.053 | 0.199 | 697.2 |
| champion_v111 | WOOL | True | 124 | 0.032 | 0.565 | 1096.8 |
| top | CARROT | False | 475 | 0.101 | 3.789 | 3.4 |
| top | CARROT | True | 204 | 0.368 | 3.461 | 244.4 |
| top | MILK | False | 448 | 0.025 | 0.326 | 133.5 |
| top | MILK | True | 231 | 0.048 | 0.589 | -36.1 |
| top | STRAWBERRY | False | 332 | 1.693 | 1.039 | 51.1 |
| top | STRAWBERRY | True | 347 | 0.847 | 0.720 | 99.5 |
| top | TOMATO | False | 493 | 0.116 | -0.093 | 102.9 |
| top | TOMATO | True | 186 | 0.457 | 0.823 | 3.9 |
| top | WOOL | False | 599 | 0.299 | 0.487 | 56.0 |
| top | WOOL | True | 80 | 0.225 | 1.488 | 224.0 |

Top Tomato exposure increases after demand unlock while V111 never enters Tomato; Top Sheep growth after Wool demand exceeds growth after other shops. Carrot expansion occurs in both demand and non-demand windows, so attributing all Carrot changes to a new shop is unsupported. No single KPI is a causal explanation for first place.

There are 1 same-submission/first-three-shop groups with multiple opponent h100 fingerprints. Their portfolios and episode IDs are saved in [opponent-dependence matches](../data/analysis/research_20260910_final/top_lineage_and_opponent_dependence.json). This matching does not hold later shops, market or private state fixed. Opponent dependence is plausible, but a separate opponent-farm intervention is still needed to distinguish reaction from correlated regimes. No reproducible non-transitive payoff cycle was established; mixed opening/PSRO is deferred.

## Market and exact horizon

| Cohort | Product | Phase 0 qty | Phase 1 qty | Phase 2 qty | Phase 3 qty |
| --- | --- | --- | --- | --- | --- |
| champion_v111 | CARROT | 1131 | 1254 | 3815 | 449 |
| champion_v111 | FERTILIZER | 6776 | 13195 | 9205 | 6222 |
| champion_v111 | MELON | 1928 | 3288 | 334 | 310 |
| champion_v111 | MILK | 1420 | 13648 | 6474 | 6401 |
| champion_v111 | STRAWBERRY | 2530 | 22159 | 5389 | 7403 |
| champion_v111 | WHEAT | 2925 | 7031 | 4127 | 3375 |
| champion_v111 | WOOL | 2845 | 8331 | 8305 | 2502 |
| top | CARROT | 2229 | 4120 | 512 | 274 |
| top | EGG | 2954 | 3588 | 171 | 95 |
| top | FERTILIZER | 10552 | 8165 | 3152 | 1676 |
| top | MELON | 1263 | 27 | 21 | 6 |
| top | MILK | 2719 | 7028 | 1431 | 1277 |
| top | STRAWBERRY | 4080 | 7315 | 1101 | 1346 |
| top | TOMATO | 1748 | 585 | 104 | 38 |
| top | WHEAT | 16031 | 6808 | 5071 | 3065 |
| top | WOOL | 1583 | 6379 | 990 | 1105 |

Quantities above are requested sales capped by the pre-action shed, **not exact committed quantity or realized revenue**. [Transaction rows](../data/analysis/research_20260910_final/current_sell_microstructure.csv) include product, turn/hour, both players' orders, inventory/price before and after, exposure, and final relative outcome. Those rows are inadequate to attribute win probability to sale phase. The separate supply study uses engine-committed transaction labels on its 24-episode subset.

V111's mean stranded private stock has a 264.7-coin observed-price proxy; leader rank 1 averages 80.8 and several other Top cohorts zero. Field yield is separately retained and is not liquid inventory. Investment stop, last crop planting and last sell vary by product; the actual last action t718 precedes any day-30 auto-deposit. This motivates H2, but its upside is too small to explain the observed 10k–20k losses alone.

## Executable opponents and meta weights

Four full published policies were acquired and completed both-seat 720-state games: [mooman](https://github.com/mooman0222/Kaggriculture-opencode), [souvik](https://github.com/Souvik6222/Kaggriculture), [ggmljs](https://github.com/ggmljs/Kaggriculture), [qeinstein](https://github.com/qeinstein/kaggriculture). Exact commits, source hashes, entrypoints and archive hashes are in the [source registry](../experiments/research_20260910/source_registry.json). Mooman must execute `agent_entry`, not its underlying `agent`; the adapter preserves that public entrypoint. These are Gold for executable closed-loop tests, not proof of a claimed public score.

Mooman/souvik overlap PSR ancestry, and mooman/ggmljs overlap Kaito ancestry. Conservatively merge those three; qeinstein is a second acquired ancestry group. Top replay-only policies remain Bronze. The new forecast is a predictor, not a validated Silver opponent. Current opening frequencies above describe the selected Top snapshot; the Gold source frequency in the live field is **unidentified**. Equal-source and equal-ancestry weighting are explicit stress scenarios, not estimated current-meta weights.
