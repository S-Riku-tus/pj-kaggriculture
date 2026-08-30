# Changelog

## 103.0.0 - 2026-08-29

- Retain V102's strict future-goal entry gate.
- Add a maximum 12-turn strategic goal commitment with one start per day.
- Re-evaluate V14 OOD/uncertainty every turn and fail closed to V11.
- Keep action execution fully deterministic and observation-driven.
- Freeze the experiment disabled after eight clean replay forks yielded zero
  emitted-action and reward differences.
