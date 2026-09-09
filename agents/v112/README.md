# Kaggriculture V112

V112 is an independent rebase, not another narrow patch over V111.  Its
submitted `main.py` is the exact Apache-2.0 output artifact from Kaito
Fukami's public Kaggle notebook **25/27 Strict-Future | v27 Midgame Meta
Reset** (version 4).

The artifact was selected because it satisfies a stronger evidence boundary
than a local win-rate comparison against V109/V110/V111:

- Kaggle displays a public score of **3090.1** for the exact notebook output.
- The local file SHA-256 is
  `f48c21166eac68d1b05a401f04f94a2eb6154e65415af64893672365ff33c7b8`,
  matching the machine-readable hash in the notebook log.
- Current Rank 1-3 replay analysis shows that the competitive meta has moved
  to a four-hire opening, aggressive early farm deployment, price-impact
  aware selling, and a late Wheat/liquidation reset.  The frozen route has
  those properties.
- It runs one coherent route in both seats, with actor-local weed recovery and
  safe reordering of route-existing sell slots.  It does not guess opponent
  identity or emit learned field actions.

The displayed notebook score is evidence about the public artifact, not a
guarantee about a new submission.  Matchmaking, rating lag, the opponent pool,
and future meta changes remain outside the offline tests.

See `docs/v112_design_report.md` for the full known/inferred/unverified split,
the current top-three teacher analysis, rejected counterfactuals, and the
verification protocol.
