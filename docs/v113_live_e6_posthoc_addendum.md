# V113 live E6 post-hoc addendum

Date: 2026-09-02 (JST)

## Status separation

This addendum does not modify the preregistration, the immutable 60-pair
result, or the frozen V113 Agent package.

| Field | Current value | Meaning |
|---|---|---|
| Preregistered experiment verdict | `REJECTED_SAFETY` | Frozen verdict of the original 60-pair experiment |
| Current research interpretation | `LIVE_VIABLE / CAUSAL_UNRESOLVED` | V113 is a viable live benchmark, but its advantage and gate effect are unresolved |
| Live ladder evidence | submission `55933145`, final rating approximately `1675` | E6 observational evidence for the whole submitted Agent |

The immutable formal result still has SHA-256
`70f4e3ebd86b77686247f82ff253300d5374040cc70bc96ba6d3fbdc181597d5`.
The structured post-hoc record is
`data/evaluation/v113_cow_sheep_gate_e3e4_20260901_2024/posthoc_e6_interpretation_and_forensics_v1.json`
(SHA-256
`a811c160833849bd1a24ce132e62e3ef3745557fee594d9a828dd6c621c572e2`).

The rating supports Agent-level live viability. It does not identify the
Cow-to-Sheep gate as its cause, establish `V113 > V111`, or satisfy E3-E5.
Episode-level collection, rating-trajectory reconstruction, live family
clustering, and A/B/C gate reconstruction are separate E6 analyses and must be
linked without rewriting this record.

## Why the formal result and live rating can coexist

The local experiment asked a narrow causal question: did the single frozen
gate improve outcomes over V111 against its preregistered executable panel?
That panel collapsed from five source labels to only three action families,
and V111 already won 58/60 games. It consequently had almost no Loss-to-Win
headroom and poor sensitivity to strategy improvement.

The live rating asks a different observational question about the whole V113
submission in a sampled, changing field. A live population can contain
matchups absent from the local panel, and its rating also reflects sampling,
field composition, seat mix, and rating uncertainty. Therefore `0/60`
discordant local outcomes and a live rating near 1675 are not contradictory.
Neither observation is allowed to answer the other one's causal question.

## Complete formal Trigger Funnel

All 29 requests are now classified; there is no residual bucket.

| Reason code | Pairs | Interpretation |
|---|---:|---|
| `ACTUAL_INCREMENTAL_COW_TO_SHEEP` | 13 | Treatment emitted a new Cow2-to-Sheep2 transaction |
| `ALREADY_SATISFIED_BASELINE_ROUTE_OVERLAP` | 8 | Control already emitted and completed the same conversion |
| `SAFE_CANCEL_PURCHASE_SLOT_ABSENT` | 8 | The expected purchase slot did not exist at step248; both arms retained baseline actions |
| Total | 29 | `13 + 8 + 8` |

The eight route-overlap pairs were V11/V14/V18 on seed `19135102`, both
seats (six), and public V43 on seed `19135103`, both seats (two). Both arms
emitted and committed Cow2-to-Sheep2, so they are not an incremental treatment
sample.

The eight purchase-slot-absent pairs were V11, V14, V18, and public V27 on
seed `19135103`, both seats. At step248 the baseline market action contained
only `SELL MELON 6`; there was no Cow purchase to rewrite. The V11/V14/V18
states had 1,603 coin and field COW5/SHEEP7, while public V27 had 2,904 coin
and COW6/SHEEP8. Thus the immediate cause was not insufficient cash. It was
the absence of the baseline purchase slot / route interference.

For each of these eight pairs:

- both players' complete 720-turn action streams were identical across arms;
- final self coin, opponent coin, margin, and W/D/L were identical;
- both games completed normally with no runtime error;
- there was no candidate-new animal loss, negative cash, or incomplete
  transaction;
- Behavioral Isolation remained valid.

The legacy `unexpected-late-purchase-action` reason was latched from step248
through step718, producing 471 diagnostic observations per pair. That means
one undelivered branch per pair, not 471 action failures.

## Safety taxonomy correction for future experiments

The original evaluator treated any candidate-new fallback as a Safety failure;
that preregistered verdict remains unchanged. Under the future framework, the
eight cases above are **Treatment Delivery Failures**, not **Hard Safety
Failures**, because they returned exactly to the baseline continuation without
damaging game integrity.

- Hard Safety Failure: runtime/incomplete game, materially harmful illegal or
  silent no-op, animal/weed loss, negative cash, transaction corruption, or a
  partial emitted intervention.
- Treatment Delivery Failure: the branch is not delivered, but baseline action
  identity and game integrity are verified.

Delivery failures remain mandatory funnel counts and reduce the actual
treatment sample. They cannot be hidden by reporting only total pairs or
trigger requests.

## Delayed transaction-controller design

The generic lifecycle is:

`ARM -> REVALIDATE -> COMMIT / SAFE_CANCEL`

At ARM, save intent, the trigger-state digest, intended delta, and expiry, but
do not assume the future route still contains the intended purchase. At
REVALIDATE, verify the exact purchase slot, already-satisfied status, cash
reserve, order capacity, pasture/shed capacity, pickup/place workers,
inventory, route ownership, and remaining horizon.

COMMIT may rewrite only the exact revalidated order and must audit purchase,
pickup, and placement completion. If a precondition changed, SAFE_CANCEL must
clear intent, emit the byte-equivalent baseline action, and record one reason
code. `unexpected-late-purchase-action` maps to
`SAFE_CANCEL_PURCHASE_SLOT_ABSENT`; it must not become a sticky per-turn error.
Failure after COMMIT remains a Hard Safety Failure.

This controller work is experimental infrastructure. It is not V113 strength
evidence and is not, by itself, a V113.1 or V114 strategy.

## V14 anomaly: opponent-response mediator

The first-response timeline is:

| Channel | Step | Detail |
|---|---:|---|
| First self action divergence | 248 | `BUY_ANIMAL COW 2` became `BUY_ANIMAL SHEEP 2` |
| First self money divergence | 249 | Treatment was 200 coin lower |
| First self portfolio divergence | 257 | Two public pasture tiles became Sheep instead of Cow |
| First opponent response | 270 | V14 changed Strawberry seed purchase quantity |
| First opponent money divergence | 271 | V14 retained 100 more coin in Treatment world |
| First market-inventory divergence | 302 | Wheat inventory differed |
| First price divergence | 312 | Fertilizer price differed |

Opponent-response lag was 22 turns from our action and 21 turns from the first
public signal. At step270, V14's farmer path, all Hand actions, and
`BUY_PRODUCT WHEAT 1` were unchanged. The only changed component was:

`BUY_SEED STRAWBERRY 2 -> BUY_SEED STRAWBERRY 1`

Immediately before that response, market inventory/prices, Town state, and
V14's private state were identical. The public V113-side differences were:

- money: Control 8,212, Treatment 8,012;
- field animals: Control COW9/SHEEP4, Treatment COW7/SHEEP6;
- exactly two otherwise identical pasture tiles changed `COW -> SHEEP`.

A deterministic one-step source probe reproduced both recorded actions.
Restoring only V113's money to 8,212 left V14 at one Strawberry seed. Restoring
only the two public pasture tiles returned V14 to two Strawberry seeds.
Therefore the most supported mediator in this pair is the public Cow/Sheep
portfolio, not the 200-coin difference.

The precise channel is:

`our Cow-to-Sheep intervention -> public animal portfolio -> V14 seed-buy response -> V14 money -> shared inventory -> price`

Calling this only a shared-market externality was incomplete because the
Opponent changed action 32 turns before market inventory diverged and 42 turns
before price diverged. It is a second-order response: the Opponent policy reads
our public farm and changes its own continuation. This is a deterministic
mediator diagnosis for one pair, not a population-level causal estimate.

## Required paired-evaluator fields

Future pair records retain:

- `first_self_divergence`
- `first_opponent_response`
- `opponent_response_lag`
- `first_market_divergence`
- `first_price_divergence`
- `first_money_divergence`

These fields supplement, rather than replace, the full action and state audit.
