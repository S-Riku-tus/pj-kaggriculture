# V81 late decay-harvest candidate

This candidate adds or raises `HARVEST` tasks only after a plant's public
`max_lifespan_step` has been reached while it still holds output. It is limited
to Days 23--26 and disabled by default pending paired calibration and holdout.

Emergency feeding retains the higher base priority. V14 remains the safe
fallback and owns every other decision.
