# Changelog

## 9.0.0

- Added episode-split Rank-1 BUY/WAIT/LAND/PLANT intent distillation.
- Added learned SELL/WAIT timing and batch fractions using Town, price,
  inventory, opponent production, and hidden-supply pressure features.
- Added validation-only feature selection and untouched episode-level test
  reporting against V8's decision rules.
- Added option-value protection for irreversible herd slots.
- Evaluated two animal-service mission-continuation designs and disabled both
  after causal ablations showed regressions.
- Coupled Cow/Sheep learned purchase controls so a one-sided validated model
  cannot distort the irreversible herd mix.
- Softened WAIT from an hourly purchase freeze to a bounded option-value cap.
- Preserved V8's opening, Top-3 OOD gate, safe executor, and liquidation.
