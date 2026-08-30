# Kaggriculture V21

V21 is a one-change executor experiment on the selected V14 safe core.  On
Days 11-12 after hour 14, only empty units still assigned `PASS` after normal
assignment and V14 prepositioning may move at most three tiles toward a
currently non-urgent, unwatered plant.  The target must remain reachable with
one turn left to water before end of day.

The hypothesis joins two sources of evidence.  First, watering a current tile
weakly dominates passing only when no real work or future position is
displaced.  Second, Rank 1 and Rank 2 logs convert substantially more late-day
worker capacity into preventive watering than V11, while V11 enters the next
day with a much larger water backlog.  Rank 3 demonstrates that this is not a
universal portfolio rule, so V21 changes only residual execution capacity.

The opponent-supply predictor and market-timing findings are analytical only
and are not connected to V21.

The paired five-seed test rejected this implementation.  Mean reward changed
from 137,619.8 to 137,714.5, but P10 fell from 123,458.5 to 122,372.5 and the
minimum fell from 97,156 to 86,296.  The worst game lost 10,860 despite
reducing the Day-12 water-risk count by five and losing no animals directly.
The changed worker positions altered subsequent assignment identities and,
by Day 15, the candidate had two fewer placed Cows.  V21 is therefore disabled
by default; V14 remains the selected safe candidate.
