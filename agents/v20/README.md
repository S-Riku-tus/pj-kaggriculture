# Kaggriculture V20

V20 retains only V19's validation-supported Cow branch and requires independent
24-hour and 72-hour winner models to agree before delaying a Cow purchase. The
state must pass intraday OOD and both model-disagreement limits. Sheep remains
exactly V11.

On untouched recovery rows, Cow MAE improves from 0.805 to 0.408 at 24 hours
and from 0.977 to 0.636 at 72 hours. Freeze precision is 98.8% at 24 hours,
96.3% at 72 hours, and 96.3% jointly. Both seats, all sampled hours, and the
bottom final-margin quartile improve over V11. These are future-state metrics,
not a rating estimate or guarantee.

Closed-loop recheck invalidated the proxy: delaying Cow growth for only one or
two effective steps changed downstream market ordering and produced -34,788 as
seat 0 and -1,388 as seat 1 versus V14. V20 is disabled by default. The V17-V20
herd-gate line is closed because even multi-horizon herd fidelity does not make
the path-dependent execution consequence safe.
