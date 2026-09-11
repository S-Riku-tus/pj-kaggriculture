# Public opponent supply estimation — 2026-09-10

E2 predictive diagnostic only. Frozen ridge lambda=10, H24/72/144, 24 newest Discovery episodes, both seats; 13 connected groups of same submission or identical field h48. Raw public features and separately generated private targets are in [rows.jsonl](../data/analysis/research_20260910_supply/rows.jsonl). Current stock targets use the opponent's own private observation offline; future supply targets use exact engine-committed SELL quantities via the existing safety simulator. No opponent private input, seed or future observation enters a live Agent.

The initial leave-group-out analysis allowed the other player's rows from the same episode in training. A stricter audit now excludes **every held-out episode, including its other player**, with parameters unchanged. This stricter result is authoritative. Feature standardization is fitted on training rows only. These observed groups do not prove independent latent source ancestry, and 912 temporally overlapping examples are not 912 independent games.

| Product | Horizon | Target | Ridge MAE | Train-mean MAE | Maintained calendar MAE |
| --- | --- | --- | --- | --- | --- |
| STRAWBERRY | 24 | supply | 1.950 | 10.019 | 9.833 |
| STRAWBERRY | 72 | supply | 3.876 | 27.090 | 8.451 |
| STRAWBERRY | 144 | supply | 5.763 | 47.376 | 8.261 |
| MILK | 24 | supply | 3.002 | 4.908 | 10.661 |
| MILK | 72 | supply | 3.219 | 9.940 | 12.755 |
| MILK | 144 | supply | 4.770 | 17.593 | 16.213 |
| WOOL | 24 | supply | 3.887 | 5.262 | 8.629 |
| WOOL | 72 | supply | 4.157 | 9.532 | 10.219 |
| WOOL | 144 | supply | 5.180 | 16.346 | 12.017 |

At H72, strict stock MAE is 2.841 Strawberry, 2.183 Milk, 2.774 Wool, versus training means 5.772/3.824/4.500. Broad-horizon Milk/Wool any-sale hazards are almost always true; ridge remains worse than the training-mean hazard predictor. Thus the result supports estimating supply quantity, not precise sell preemption. The calendar baseline assumes continued service and collection, and no new investment. A tree or larger model was not justified before resolving these target and causal-decision limitations.

At the $1 price floor, sales do not increase market inventory, so exact opponent stock is not identifiable from market differences alone. The output should be a distribution/interval with a missing-flow model, not a false exact balance. The next validation should use truly unseen source ancestry and a shorter 1–4-turn competing-sale hazard. Prediction accuracy alone does not select a portfolio or establish pairwise uplift. No trained forecast was installed in V114r1; its route valuation used a separate, simple maintained-supply scenario.

[Initial result retained](../data/analysis/research_20260910_supply/result.json); [strict result](../data/analysis/research_20260910_supply/result_strict_episode_exclusion.json); [reproducible analysis](../scripts/analyze_opponent_supply_20260910.py).
