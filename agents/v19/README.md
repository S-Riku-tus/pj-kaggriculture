# Kaggriculture V19

V19 fixes two V18 confounders: market-order seat is an explicit feature, and
Cow/Sheep gates are selected independently. A branch must improve validation
MAE by at least 0.01 and 2%; only Cow passes, so Sheep remains exactly V11.

The intraday corpus has 44,688 rows from 399 Top-3 matches split 243/78/78 by
episode. On untouched recovery rows, Cow 72-hour MAE improves from 0.977 to
0.587; seat 0 improves 0.945 to 0.512 and seat 1 improves 1.004 to 0.651. The
bottom final-margin quartile improves 0.759 to 0.529. These offline metrics are
not a rating estimate or guarantee.

Closed-loop recheck on V18's divergent seed did not stabilize the policy:
seat 0 moved to -19,626 versus V14 while seat 1 moved to +23,938. The seat
feature is used by the forest and held-out herd error improves, so the failure
is a mismatch between the single 72-hour herd proxy and final performance.
V19 is disabled by default and does not replace V14.
