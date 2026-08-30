# V15

V15 tests a logistics hypothesis on V14: retain every Wheat carrier selected by
the safe executor, but reduce excess load to one unit per carrier plus 20% of
observable remaining feed demand. This separates delivery parallelism from
inventory surplus, which V12 incorrectly reduced together.

The experiment is disabled by default. Its first paired unseen-seed diagnostic
preserved FEED and zero animal loss, but increased Wheat trips from 293 to 362,
reduced WATER from 867 to 849, and regressed mean and lower-tail reward. V15 is
retained only as a reproducible rejected checkpoint. The rating-3000 target is
unverified.
