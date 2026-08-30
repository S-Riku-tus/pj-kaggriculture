# Changelog

## 104.0.0 - 2026-08-30

- Retain V102's strict episode-held-out entry gate.
- Latch only the admitted crop-target delta for at most 24 turns.
- Reproject through current crop, feed, and capacity floors every turn.
- Decay toward V11 on OOD/uncertain states and stop immediately after recovery.
- Leave all concrete execution to V11's deterministic executor.
