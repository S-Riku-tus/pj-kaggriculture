# V7 Robust Adaptive Agent

This repository V7 is a new implementation; it is not the unavailable source
of submission `55693615`.  It uses that submission's 47 replays, V7-2's 44
replays, the Rank 1-3 corpora, and V1-V6 ablations as design evidence.

V7 retains V6's deterministic feasible executor and changes only the future
Cow/Sheep allocation.  Between Days 8 and 20 it blends V6's safe herd ratio
with the observable Town/price/opponent economic ratio.  At most one unowned
slot may move, total herd size is unchanged, and already-owned animals are
hard lower bounds.  Crops, land, workforce, field assignment, market policy,
and liquidation remain exactly V6.

Broader OOD recovery, 100% opening utilization, Carrot/Tomato rotation,
Strawberry/Wheat rotation, and market-timing residuals were implemented as
separate ablations.  They did not beat their immediate baseline and are not
deployed in this version.

The primary selection metrics are paired win rate, P25 coin share, and P10
margin.  Mean coin is diagnostic but is not the optimization target.
