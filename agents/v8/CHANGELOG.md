# Changelog

## 8.0.0 - 2026-08-24

- Replaced old-agent win-rate selection with held-out Top-3 trajectory fidelity.
- Trained 24-hour and 72-hour absolute portfolio-anchor forests on the Rank 1
  teacher trajectory and calibrated the OOD envelope from all Rank 1-3 games.
- Added confidence-weighted recovery to the V7 safe strategy outside the
  observed expert manifold.
- Distilled Rank 1's high-consensus Days 1-5 field route with position checks
  and separate market-order consensus.
- Added demand-conditioned Carrot/Tomato rotation through feasible market and
  field tasks.
- Corrected the opening Melon lifecycle to harvest at its actual capped-yield
  age, accelerating capital recovery and third-land refill.
- Added bounded midgame refill and late Wheat/Carrot rotation priorities while
  retaining emergency feed, care, and deterministic liquidation safeguards.
