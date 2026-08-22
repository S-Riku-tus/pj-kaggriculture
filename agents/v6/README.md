# V6 Early Capital Agent

V6 keeps V5's adaptive animal allocation and sequential animal-service
executor. It advances the early Strawberry schedule, recognizes the temporary
utilization dip after opening Wheat is harvested, and gives Strawberry planting
precedence when it competes with discretionary Wheat for the same cells.

Broader crop rotation, reduced herd size, forced land purchases, and stronger
animal-mission locking were tested but intentionally excluded after holdout
regressions.

See `docs/v6_design_report.md` for the replay evidence, ablations, and paired
validation.
