# V13 (rejected-hypothesis checkpoint)

V13 ranks V11 and separate expert macro trajectories with an episode-held-out
relative-value residual critic. The offline residual model improved validation
MAE at 24h, 72h, and final, but paired closed-loop diagnostics regressed mean
reward and the lower tail. The learned route is therefore disabled by default;
release behavior falls back exactly to V11.

This is evidence that logged action/outcome association was not a safe
counterfactual value estimate. The rating-3000 target remains unverified.
