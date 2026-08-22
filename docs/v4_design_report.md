# V4 design and validation report

## Inputs and identity check

The analysis uses the corrected submission mapping from replay metadata:

| Agent | Submission ID | Reported rating | Public games in supplied analysis |
| --- | ---: | ---: | ---: |
| V2 | 55659329 | 648.2 | 38 |
| V3 | 55661347 | 632.6 | 32 |
| Rank1 | 55614463 | 3170.6 | 133 |
| Rank2 | 55623460 | 3079.3 | 130 |
| Rank3 | 55574890 | 3058.9 | 184 |

The supplied episode metrics and aggregate JSON were checked against the downloaded replay layout and the V2/V3 implementation. The diagnosis is consistent at all three levels: aggregate result, daily state, and planner code.

## Root cause

V3 improved the lower tail of final coin but did not turn its learned portfolio into working capital:

- Around 35% of owned Cow/Sheep remained undeployed because pasture construction lagged animal purchase.
- The V2 executor, inherited by V3, prioritized task classes globally. A worker standing on an animal could leave for a distant higher-priority task instead of finishing FEED, CARE, COLLECT, and HARVEST locally.
- Animal slot selection could point at occupied crop cells even when other free cells existed, preventing pasture expansion.
- Every unwatered crop was scheduled for WATER every day, although survival normally requires alternating days. This consumed travel and worker actions.
- Expired ongoing crops were not recycled immediately, and weed DIG priority was too low.
- Learned state targets were interpreted as purchase targets, creating late Melon replacement and large Wheat seed inventories.

These defects explain the observed gap without assuming that the strategic model itself is useless. V3's P10 and minimum coin improvement are evidence that its learned macro strategy carries information.

## V4 architecture

V4 retains the V3 model and exact Rank1 opening. It replaces the conversion from desired portfolio to actions:

1. Apply Top-agent scale floors to the learned Cow, Sheep, Wheat, and Strawberry goals.
2. Build pasture capacity ahead of the planned animal portfolio.
3. Permit BUY_ANIMAL only when an empty pasture or a pasture built in the current turn backs the purchase.
4. Buy seeds in small just-in-time batches bounded by reusable cells.
5. Block new Melon from Day10 and new Strawberry from Day18.
6. DIG completed ongoing crops immediately and recycle weeds at materially higher priority.
7. WATER for survival, one-time crop yield, or fertilized ongoing production rather than watering every crop every day.
8. Solve one global worker assignment with distance, task value, same-tile completion bonus, and route density.
9. Load up to four Fertilizer per route instead of making one-unit shed trips.

The runtime remains observation-only and deterministic; no mutable cross-episode state is introduced.

## Ablation result

An experimental variant pushed Day20 utilization from 85.3% to 97.3% by planting earlier and more aggressively. It reduced FEED, CARE, and COLLECT completion and lowered same-seed mean coin from 99,019 to 79,503. It was rejected.

This supports the supplied Rank3 observation: idle cells or PASS actions are not the objective. Critical work completed per route is more important than maximizing utilization in isolation.

## Local paired validation

All comparisons use identical seeds in both seats for each seed.

| Opponent | Seeds | Games | V4 wins | Mean V4 coin | Mean opponent coin | Mean margin |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| V2 | 5 | 10 | 10 | 94,103 | 54,324 | +39,779 |
| V3 packaged 3.0.1 | 5 | 10 | 10 | 105,323 | 63,116 | +42,208 |
| Combined | 10 matchups | 20 | 20 | 99,713 | 58,720 | +40,993 |

On the saved V4-vs-V2 seed 20260830 pair, operational KPIs were:

| KPI | V3 public analysis | V4 local pair |
| --- | ---: | ---: |
| Owned animal deployed | about 64% | 100% at Day20 |
| Hand movement rate | 68.1% | 55.3% |
| COLLECT_FERTILIZER | 76.6 | 303 |
| HARVEST | 186 | 306 |
| DIG | 1.0 | 29.5 |
| Final seed units | 36.3 | 9.5 |
| Day20 cash | 23,353 | 29,977 |

The package was extracted and run for a full 720-turn paired match. It exactly reproduced the development-tree result, confirming that helper and model resolution works in submission form.

## Interpretation and limits

The results are strong evidence that V4 fixes the measured execution failures and is materially stronger than V2/V3 in the local official environment. They do not guarantee a particular Kaggle rating: the public ladder has a different opponent distribution, simultaneous market interaction matters, and the top agents' executable policies are unavailable for direct local matches.

The next evidence-driven step is to submit V4, collect at least 30 public matches, and rerun the same KPI analysis. Further model retraining should use future action or portfolio delta labels only after the V4 executor's public behavior is measured.
