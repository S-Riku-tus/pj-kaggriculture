# V19 changelog

- Added seat to the intraday feature vector to model market processing order.
- Trained independent Cow and Sheep advantage forests.
- Required material validation improvement per animal before runtime enablement.
- Enabled Cow only; Sheep deterministically falls back to V11.
- Retained intraday OOD, uncertainty, ownership, and deterministic execution gates.
- Rejected and disabled after opposite seat outcomes persisted despite held-out herd-error gains.
