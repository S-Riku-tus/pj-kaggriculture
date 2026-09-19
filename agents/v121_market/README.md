# V121 market/correctness challenger

V120's learned macro policy is unchanged. This ablation adds only bounded
execution repairs: weed collision recovery, removal of provably dead SELL
orders, price-impact ordering within existing SELL slots, and terminal shed
liquidation. Future-sale preemption and predictive overflow sales are excluded
until this conservative layer passes paired evaluation.

