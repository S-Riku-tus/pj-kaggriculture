# Kaggriculture V109

V109 is a strategic reset after V108 produced a user-reported live rating near
885. It does not tune V108 against older local agents. The primary policy is
the exact public V43 current-meta route artifact, including its two sparse YARN
continuations and deterministic weed/hand/SELL execution overlays.

The common route is identical for the first 88 steps. A first YARN_STORE draw
switches at step 88; a later second YARN_STORE draw has a separate continuation
from step 153. These are complete 719-step plans, so the policy represents
future farm states rather than independent action labels.

V109 adds three conservative runtime guarantees:

- reconstruct a missing `obs.step` from `day * 24 + hour`;
- isolate the bundled policy's temporary modules so repository tooling is not
  shadowed;
- latch a confirmed broken state to V11's deterministic executor after all of
  its learned models and imitation opening have been disabled.

Fallback is deliberately narrow. A malformed action or two consecutive missed
feeds is critical. A missing second land must persist for two observations.
A missing third land is recorded but does not trigger fallback: a same-seed
counterfactual recovered the land but reduced mean reward from 97,961 to
85,395. One missed feed is also left to the coherent night route because it
recovered in a real seed; terminal feeding is not forced after step 696.

Across 34 final-policy normal diagnostic games (both seats, four opponent
state sources), all games completed, animal losses were zero, and fallback did
not activate. These matches are safety/state-coverage diagnostics, not the
promotion criterion. The public teacher's documented held-outs are the primary
selection evidence. Rating 3000 remains an objective, not a verified claim.

See `docs/v109_design_report.md` and `data/analysis/v109_diagnostics.json`.
