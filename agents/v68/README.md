# V68

V68 relaxes V67's strict relative-money gate by an uncertainty band of 0.464,
approximately twice the worse of validation/test raw MAE for the 72-hour
money-gap target. Predicted declines larger than that are rejected; smaller
changes remain uncertain and may use V63's late role-continuity tie-break.

The tolerance is calibrated from held-out teacher prediction error, not local
match rewards. Closed-loop rating improvement remains unverified.

V18 holdout diagnostics improved both reward and margin while preserving the
lower tail. A separate V11 diagnostic improved margin but reduced absolute
reward and its lower tail, so V68 is not promoted to a submission artifact.
