# V92

V92 connects the V90 candidate-relative ranker to V14's worker/task cost
matrix. It activates only for non-moving workers, in-distribution states, and
model score gaps of at least 0.12. The selected moving task receives a bounded
worker-specific bonus that cannot raise its effective priority above 14,900.
All task creation, legality, mission continuity, market, and survival logic
remain V14. This is an unpromoted experiment.
