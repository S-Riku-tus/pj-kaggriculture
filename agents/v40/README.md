# Kaggriculture V40

V40 is a one-change experiment on V14. V11's submitted logs buy most early
Cows late on Days 6 and 8 after same-turn Milk/Wool sales. Across 38 episodes,
141 of 258 Day-3..10 purchases were placed on a later day, versus 21 of 777 for
Rank 1 and 18 of 876 for Rank 3. The pattern recurs in the episode-disjoint
train, validation, and test splits.

The candidate raises only Cow PICKUP and PLACE tasks on Days 6 and 8 after
hour 18 when their shortest route can complete before the day boundary.
Emergency FEED and WATER remain higher, and V14 retains legality, inventory,
capacity, OOD, and fallback ownership. The experiment is disabled until
closed-loop lower-tail and animal-loss checks pass. The rating target is not a
guarantee.
