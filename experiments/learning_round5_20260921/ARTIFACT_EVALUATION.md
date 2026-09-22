# Artifact evaluation

| Axis | Status | Scope | Reason |
|---|---|---|---|
| PACKAGE_VALID | PASS | final archive | archive passed loader and full-episode checks |
| EXECUTION_CORRECT | PASS | declared P1 semantic contracts; unrelated base primitives with unobservable day-boundary outcomes remain UNKNOWN | all 8 required contracts passed |
| TRAINING_EXECUTED | PASS | Round5 training run | 216 optimizer updates; parameter delta=2.44463 |
| MODEL_USED | PASS | runtime | reloaded model executed 2876 runtime inferences |
| SKILL_COMPLETION | PASS | fixed-engine cow/sheep end-to-end realization and duplicate animal yield | completed=3 with no failed/unknown required skill |
| LOCAL_ECONOMIC_EFFECT | UNKNOWN | local skill/economic scenarios | non-negative point estimate but uncertainty unresolved: self=228, opponent=0, margin=228 |
| EXTERNAL_ECONOMIC_EFFECT | FAIL | fixed external proxy panel | delta self=-760.5, opponent=1245, margin=-2005.5 |
| ONLINE_EVIDENCE | UNKNOWN | Kaggle online | no Round5 online submission/result |
| READY_FOR_LIMITED_SUBMISSION | NOT_APPLICABLE | limited diagnostic submission only | all four learned proxy games lost and the two family-seed clusters disagree; no Round5 online submission is proposed |
| CHAMPION_PROMOTION | FAIL | champion replacement | at least one promotion axis failed |
