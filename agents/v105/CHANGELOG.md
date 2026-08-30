# Changelog

## 105.0.0 - 2026-08-30

- Restrict V14 prediction and OOD admission to its day-boundary time scale.
- Hold an admitted goal for at most the following 24 turns.
- Reproject safety floors every turn through V104's deterministic projection.
- Fall back immediately when a consecutive-unfed animal is observed.
