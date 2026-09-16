# V117 changelog

- Added the V111-only `late_land_order_resequence` fallback after rejecting the
  broader Cow-debt Primary contract before outcome evaluation.
- Added current-state standard configuration, two-quadrant, hands, shed,
  market-slot, feed reserve, and sequential market cash preflight.
- Preserved V111's original two-Cow order and all field/hand actions.
- Removed only the later duplicate `BUY_LAND` after the third quadrant is
  observed unlocked.
- Added transaction, land, Cow, activation, duplicate-removal, and rejoin
  diagnostics.
