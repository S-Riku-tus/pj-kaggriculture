# V17 changelog

- Added a winner-log regression gate for the advantage of freezing herd growth.
- Limited the learned choice to V11 targets versus already-owned Cow/Sheep.
- Included animals carried in the shed or worker inventories in the freeze goal.
- Preserved the cached episode split; test episodes were excluded from model and threshold selection.
- Added winner-manifold and herd-model disagreement fallbacks before changing targets.
- Preserved V14 crop recovery and V11 deterministic execution unchanged.
- Rejected and disabled the gate after closed-loop tests showed no persistent execution change.
