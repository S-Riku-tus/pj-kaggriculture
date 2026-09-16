# V117 limited live trial preregistration — 2026-09-16

## Status boundary

V111 remains `PRODUCTION_CHAMPION`.  V117 is initially a
`RESEARCH_ARTIFACT`; at most it may become `LIVE_TRIAL_CANDIDATE` or
`LIVE_TRIAL_SUBMITTED`.  This experiment cannot promote V117.

Candidate source SHA-256 is
`2772e5fa31476db3dc4f015d4a8cf11bf7c48d75ab617a9bd782bb4c7aa696a8`.
Any source/package change invalidates all candidate results and requires a new
experiment identity.

## Primary-to-fallback decision (frozen before W/D/L)

The Primary `midgame_land_cash_reserve_live_trial` would defer V111-requested
Cow orders into FIFO debt and must close land activation, harvest/sale,
Cow repurchase/pickup/place/feed, and state-compatible rejoin.  The preceding
replay-only audit found 232 early Cow placements and 2,494 dependent
pickup/place/feed/care/fertilizer actions, but zero complete
maintenance-to-sale-and-rejoin contracts.  A bounded executor cannot recover
that debt without replacing V111's field policy.  Therefore Primary is
statically infeasible and is not selected.

Before any candidate W/D/L is inspected, the one permitted fallback is frozen
as `late_land_order_resequence`.  It is still named under the overall contract
`midgame_land_cash_reserve_live_trial`, but it is a small ordering/identity live
trial and its results never count as Primary mechanism successes.

## Frozen fallback

V117 calls V111 exactly once per decision.  It changes an action only when all
of these current-state conditions hold:

- standard 720-step, 10x10, 24-turn/day configuration;
- exactly two own quadrants unlocked;
- V111 currently emits a positive `SELL MELON` before exactly one
  `BUY_ANIMAL COW 2`, and no `BUY_LAND`;
- emitted hands match current hands and adding one order stays within the
  market slot limit;
- deterministic same-turn shed projection makes the Melon sale available;
- the standard engine price function, current public inventory, and ordered
  own transaction leave land 2,000, Cow 800, current-state Wheat maintenance
  reserve, and V111's inherited 500-coin reserve;
- projected shed use remains within capacity.

On commit it appends `BUY_LAND` immediately after the original Cow order.
The original sell, Cow order, all field/hand actions, pickup/place/pasture/feed,
and all unrelated orders stay unchanged.  When state confirms that the third
quadrant is unlocked, the first later V111 `BUY_LAND` is removed once as a
duplicate.  No fixed step triggers the intervention.

Pre-commit failure is a safe cancel with byte-equivalent V111 action.
Post-commit failure to observe both land and the two Cows, candidate-new
partial/no-op transaction, maintenance loss, animal loss, or water-death crop
loss is a hard failure.  Rejoin is recorded only after land/Cow confirmation
and duplicate-land removal; it is not based on a fixed step.

## Forbidden inputs and scope

Runtime may use only current own/private state, current/past public state,
configuration, and V111's current proposed action.  It does not use source,
seed, opponent name, episode/submission ID, discrete replay signature, future
RNG/shop/price, opponent private state, or a replay lookup table.

No Tomato, Carrot, Goose, Sheep, new livestock/crop portfolio, terminal sale,
PSR repair, P1/v116 route, Top action sequence, generic sanitizer, or broad
rule fallback is added.

## Evaluation order

1. source/license/package/manifest hash audit;
2. import isolation, final callable, both seats, step-0 reset, same-process
   episodes, fresh process;
3. V111 A/A and V117 A/A on fixed contexts;
4. a non-trigger both-seat context with exact V111 action/state identity;
5. commit smoke on at least two sources and both seats;
6. old-spent engineering panel: sources `ggmljs_v16`, `mooman_e052a`,
   `qeinstein_moev2`, `souvik_v4`; seeds `10091011–10091014`; both seats;
7. only if old-spent hard Safety is zero, confirmation sources are the same
   four and the mechanically selected unused consecutive seeds are
   `10091521–10091524`, both seats, full 720.

No implementation, threshold, reserve, Cow count, or tile count is changed
after observing outcomes.  Any source change invalidates the whole panel.

## Trial Gate

Hard gate requires verified source/license/package/manifest, no forbidden
feature, zero runtime/timeout/incomplete/negative-cash/malformed/missing-hands,
zero candidate-new non-terminal animal escape or required maintenance/crop
loss, zero broken post-commit transaction, and exact non-trigger fidelity.

Confirmation efficacy loss budget requires:

- paired V117−V111 win-score `>= -0.0625`;
- W→L source-seed blocks exceed L→W blocks by at most one;
- every source delta `>= -0.25`;
- commit in at least two sources and four source-seed blocks;
- for this fallback, same-turn land+COW commit and later duplicate-land
  removal in multiple blocks.

Bootstrap lower bound, all-source non-regression, W→L zero, three ancestries,
and Fresh are not required.  A pass is labeled `EXPLORATORY_E6_REQUIRED`, not
promotion evidence.

## Submission boundary

At most one competition upload may occur and kernel push is forbidden.  If an
upload can replace or activate an existing slot—or this cannot be disproved—
execution stops for explicit user approval after presenting current slots,
replacement proposal, exact archive hash, and local results.

Promotion `10091101–10091112`, Fresh `10091901–10091912`, reserved
`10091421–10091436`, and unused confirmation tail `10091525–10091536` remain
sealed.
