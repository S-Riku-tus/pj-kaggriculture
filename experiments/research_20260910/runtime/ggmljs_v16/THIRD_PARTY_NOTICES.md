# Third-party notices

## Public-behavior recovery route reconstruction

V10 adds two compressed, re-serialized recovery routes reconstructed from
opponent actions visible in 111 public Kaggriculture episode replays:

- the low route is a component-wise majority over 61 episodes whose opponent
  ended with 10 cows and 4 sheep;
- the high route uses the low prefix through step 167 and a component-wise
  majority over nine episodes whose opponent ended with 6 cows and 8 sheep;
- farmer actions, each hand slot, and the complete market list were voted
  separately, normalized as JSON, and recompressed.

This is a majority reconstruction of observable behavior. It is not
source-code copying from every replay participant, does not establish that a
participant used a named public Notebook, and does not recover any
participant's current or private submission binary. V10 uses these routes only
behind its fail-closed public opening gate.

## Adaptive public-shop route lineage

`main.py` contains ten compressed, re-serialized public-shop action routes
derived from the Apache-2.0 Adaptive Farming Strategy artifact identified
below and connected to the V8 controller. Five are current routes and five are
legacy fallback routes selected by observable shop prefixes and farm state:

- current: `10c4s_3q`, `8c6s_3q`, `6c8s_3q`,
  `6c12s_4q_first_yarn`, and `6c12s_4q_second_yarn`;
- legacy: the corresponding `10c4s_3q`, `8c6s_3q`, `6c8s_3q`,
  `6c12s_4q_first_yarn`, and `6c12s_4q_second_yarn` fallback tapes;
- the route data was extracted, JSON-normalized, and recompressed for this
  repository, while the selector and execution path were integrated with the
  independently maintained V6 recovery controller.

These route data are modified derivative portions of the attributed Apache-2.0
artifact. Similar actions in a public replay do not establish that a replay
participant used that Notebook or recover a participant's current or private
submission binary. Public replay identity and public Notebook artifact identity
are therefore kept as separate provenance claims.

## Apache-2.0 public Notebook references

The following Kaggle Notebook pages displayed an Apache 2.0 license when
accessed on the dates recorded below. Their downloaded artifacts were inspected
as mechanism references and used as hash-pinned local opponents:

### V17 10C/4S

- [V17-R1-RC2 High-Score 10C/4S Market Storage](https://www.kaggle.com/code/boatlee/v17-r1-rc2-high-score-10c-4s-market-storage)
- license inspected on 2026-08-17;
- downloaded `main.py` SHA-256:
  `ccf2aefdadd600d3e6fcaad2879a310eb15bbd14183fc2deeff9bb2525697b9a`
- downloaded `submission.tar.gz` SHA-256:
  `d5e2ef7a24ecb279d2d0a16efae7f7de9bc23efdc71518d5800d51ec2abf43f7`

### Public shop-routed mixture of experts

- [Rank Top10: Read the Market, Choose the Farm](https://www.kaggle.com/code/indarkarhana/rank-top10-read-the-market-choose-the-farm)
- license inspected on 2026-08-17;
- downloaded `main.py` SHA-256:
  `d39dba50793d9777c990347443bf0c481c78adaea86055f6f6b0600dcfcd9f2e`
- downloaded `submission.tar.gz` SHA-256:
  `a5f0e99ef483408fb524e7ae7c9c2df0c71fd849a30e4fcc54ef50fc166e3ee8`

### Adaptive farming strategy

- [Adaptive Farming Strategy for Kaggriculture](https://www.kaggle.com/code/tetsutani/adaptive-farming-strategy-for-kaggriculture)
- the Notebook page displayed an Apache 2.0 license when inspected on
  2026-08-20;
- the 2026-08-20 artifact `main.py` SHA-256:
  `c26402b67a0d04a46348353069645b1a49c3cb3df6df69d7fa35d8adbbdbeae`
- the 2026-08-20 artifact `submission.tar.gz` SHA-256:
  `697d4e0144bcb8c190d91e904641a61e1d09ee0ca00342c8033f9ffe8e4cb978`
- the earlier inspected artifact `main.py` SHA-256:
  `475709377b8d82a21fa298eea770ea5c005d5e329e343775c7de6e9b702bd73c`
- the earlier inspected `submission.tar.gz` SHA-256:
  `483a72e47bfe8e34af4b4858f252b3f3a9221f3cdf47bfba174929146f3ba381`
- the older artifact remains the recorded mechanism source for the published
  product price-curve parameters and requested-sale impact-ranking idea;
- V8 retains V7's inspection of the 2026-08-20 artifact for adaptive route,
  preemption, and room safety mechanisms. Its five current routes, five legacy
  routes, and related
  mechanisms were modified, made deterministic, and integrated into the V6
  execution controller; this repository does not claim byte-for-byte copying
  of the Notebook's full policy or route.

The downloaded 2026-08-20 tar archive contained only `main.py`; it did not
carry a license or notice file. The Apache 2.0 page attribution is therefore
preserved here, while this repository's own submission package carries
`LICENSE-APACHE-2.0.txt` and `THIRD_PARTY_NOTICES.txt` beside `main.py`.

These downloads support artifact-level inspection and local evaluation only.
Similar behavior in a public episode is not proof that the episode executed
the downloaded bytes.

## Retained V10 controller lineage

V10 retains controller and market-schedule lineage previously attributed to:

- [V16-RC5-R5A High-Score 8C/4S Recovery](https://www.kaggle.com/code/boatlee/v16-rc5-r5a-high-score-8c-4s-recovery),
  reference `main.py` SHA-256
  `7f87c941af3050d0f21376f2843b324d7a06a1a8c050fa554cf07a769e5c937c`;
- [Kaggriculture: Breaking the Tie](https://www.kaggle.com/code/andrewsokolovsky/kaggriculture-breaking-the-tie),
  reference `main.py` SHA-256
  `df4e899ad535754cf2ddbd3c16e48085916b0cd2baa5182a1a2cfc6a856abae5`.

The earlier 8C/4S action tape is no longer the sole current V10 production
route. V10 retains bounded weed and cow-placement repair plus the reduced public
premium-sale schedule, the five current/five legacy shop routes,
public-state route selection, route-aware purchase reconciliation,
quantity-conserving repayment, modified preemption and room-safety controls,
malformed observation protection, retry-safe action caching, tests, packaging,
and evidence controls. V8's third-Yarn milk-support decision remains an
independently implemented selector over public farm counts; it does not add or
modify third-party route data. V10 independently adds the seat-relative
opening gate and preserves V9's projected terminal liquidation.

## Repository license and distribution

Except for third-party portions identified in this notice, this repository's
independently written code and documentation are licensed under the Apache
License, Version 2.0. The complete repository license is included at
[`LICENSE`](LICENSE).

The applicable Apache 2.0 text used for third-party attribution is also kept at
[`LICENSES/Apache-2.0.txt`](LICENSES/Apache-2.0.txt). The Kaggle submission
archive carries this notice as `THIRD_PARTY_NOTICES.txt` and the same full
license text as `LICENSE-APACHE-2.0.txt`, both at the archive root beside
`main.py`.

This notice preserves the provenance and license scope of attributed
third-party portions. It does not relicense public episode data or claim
ownership of the attributed source artifacts.
