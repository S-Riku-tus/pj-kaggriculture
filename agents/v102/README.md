# Kaggriculture V102

V102 is a neutral recovery meta-gate and is not a promoted submission.
V11 remains the default policy because its observed public rating (1014.6) is
the strongest local evidence. V14's bounded 72-hour crop projection is used
only on Days 10-11 or 14-17 when the agent is at least 5% behind in observable
cash, confidence is at least 0.65, forest uncertainty is below 0.8 of its
validation P90, and the projected target differs materially from V11.

The gate was selected on complete-episode train/validation Top-3 winner logs.
It triggered in 26/78 validation episodes; mean, P10, and minimum episode-level
72-hour target improvement were positive. The previously inspected historical
test also had positive mean and P10. With thresholds frozen, it triggered in
8/68 recent opponent wins against submitted V14/V18: mean improvement was
positive, but P10 and the worst episode were slightly negative. This is a
reason for conservative closed-loop testing, not a rating claim.

Closed-loop calibration then found no natural activation in six paired games.
Eight exact recent-replay forks each activated the target gate for one turn,
but every emitted action and the entire downstream trajectory remained equal
to V11. V102 is therefore safe in those diagnostics but behaviorally neutral;
it does not qualify as an improvement.

All action feasibility, feeding, watering, routing, assignment, cash, market,
land, liquidation, and malformed/OOD fallbacks remain deterministic V11/V14
execution. The 3000 rating is an aspiration and remains unverified.
