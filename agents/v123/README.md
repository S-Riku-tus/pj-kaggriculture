# Kaggriculture V123

V123 retains V122's exact V120 opening, sparse winning continuation library,
weed repair, dead-SELL removal, and terminal liquidation.

It adds one promoted control based on the V122 live audit:

1. An opponent that independently matches the public farm trajectory at days
   1–4 is latched as an opening clone. From day 12 onward, a sale already
   scheduled by the active continuation for the next turn may move one turn
   early when the opponent publicly owns the matching production asset.

A measured gate-coherent source latch is implemented for continued research,
but disabled in the promoted policy. At tolerance 250 it produced positive
average margin against V122 but only 11 wins, 7 losses, and 2 draws, so it did
not pass the paired stability gate. Per-turn state-compatible routing therefore
remains V122-exact unless the clone market controller intervenes.

No identity, rating, replay id, outcome, or future observation is used at
runtime. Unconditional SELL ranking remains disabled.
