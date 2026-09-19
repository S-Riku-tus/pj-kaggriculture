# V123 final decision

V123 promotes a clone-aware next-turn sale preemption layer over V122. It keeps
V122's opening, sparse continuation router, weed repair, dead-SELL removal, and
terminal liquidation unchanged.

## Evidence from 162 V122 live games

- Overall: 95-65-2, 58.6%, mean margin +5,996.
- At own initial rating >=1600: 52-50, mean margin +721.
- BALANCED at that tier: 28-35, mean margin -1,556.
- Exact public opening through step 100 against external opponents: 0-8.
- Average losing margin was only -164 at day 12, then -2,334 at day 20.

## Implemented controller

At steps 24, 48, 72, and 96, V123 compares only public farm state. Three or
more near-exact checkpoints latch `opening_clone`. From step 288 onward, when
the active continuation already plans a premium sale on the next turn, V123
may sell that stock one turn early if all of the following hold:

- the stock is actually present after same-turn worker transfers;
- the opponent publicly owns the corresponding crop or animal;
- neither the current nor target turn has matching shop consumption;
- market price is above the floor and an order slot is available;
- at least two units can be sold.

No identity, rating, episode id, outcome, or future observation is used.

## Paired results

- Clone controller only vs V122: 19-1 over 20 games, mean margin +900.
- Independent seven-lineage panel: 26-2 over 28 games, mean margin +9,645.
- V122 reference on that panel: 28-0, mean margin +9,632.
- The two regressions are the same Smart Farm seed in both seats, margin -31;
  V122 won it by +84. The other Smart Farm seed improved from +5,089 to +7,005.

## Rejected default

A gate-coherent source latch was tested at distance tolerances 1000 and 250.
At 250, the isolated controller scored 11 wins, 7 losses, and 2 draws against
V122 despite positive mean margin. It therefore stays implemented but disabled.

## Decision

Promote the clone market controller as the V123 challenger. Do not claim a
3000 rating from local tests; live validation is still required.
