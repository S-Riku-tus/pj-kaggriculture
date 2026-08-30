# Kaggriculture V105

V105 corrects a temporal-granularity error found in V103/V104. The V14
72-hour model and OOD profile are evaluated only at day boundaries, matching
their training rows. An admitted crop-target delta remains active for that
day so it can reach planting and replacement opportunities.

Every turn re-applies current crop ownership, herd feed reserve, and capacity
floors. V11 alone chooses legal actions, assignments, routing, purchases, and
sales. A consecutive-unfed animal is an explicit emergency fallback to V11.
This is experimental pending replay-fork and independent closed-loop checks;
rating 3000 is an objective, not a verified claim.
