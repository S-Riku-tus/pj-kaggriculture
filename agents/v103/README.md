# Kaggriculture V103

V103 tests whether V102 was behaviorally neutral because its supported
72-hour recovery goal survived for only one turn. The same strict entry gate
is retained, but an admitted goal may be recomputed for at most 12 turns while
the state remains inside V14's OOD and uncertainty envelope and the same
supported phase. Only one commitment may start per day.

No worker action is pinned. Every turn V11's deterministic executor replans
feeding, watering, movement, assignment, purchases, land, cash, and
liquidation from the current observation. A repeated/out-of-order step resets
the commitment, so a new episode cannot inherit stale state.

The frozen eight-episode replay-fork evaluation was clean but produced zero
emitted-action differences and therefore identical trajectories and rewards.
The experiment is classified as behaviorally neutral and is disabled by
default; V11 remains the safe core. A 3000 rating remains an unverified goal.
