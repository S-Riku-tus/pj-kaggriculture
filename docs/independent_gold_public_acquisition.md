# Independent Gold public acquisition audit

Date: 2026-09-02 (JST)

## Outcome

Four initial public repository HEADs, ten self-contained public-notebook
routes, 25 historical executable policies from the already downloaded
repository snapshots, and three additional pinned GitHub executables were run
for 720 turns on two common seeds and both seats. All 168 public-acquisition
games completed and none raised an exception. Combined with the original
common probe, 100 source labels collapse to 63 exact executed action families.
This is an inventory count, not 63 independent Meta votes; the registry
normalizes shared history/HEAD ancestry and retains 22 source-ancestry ids.

The newly acquired closed-loop repository snapshots are:

| Snapshot | Pinned revision | Common-probe result |
|---|---|---|
| `GzmCR/Kaggriculture` | `6a76335397d5cd2facffa91c938f629b119ea350` | V111 4/4, mean margin +29,362.25 |
| `Seyamalam/Kaggriculture` | `8b8c421eb10634c756583ce10c75189f50c83a72` | V111 4/4, mean margin +19,015.25 |
| `COK-ZhangZiliang/Kaggriculture` | `7ef67eac458cd9ecd13786063e2e581fbe7403ec` | V111 4/4, mean margin +11,724.50 |
| `lonespear/kaggriculture` | `774b26093ccf4246525517d48420349b841b6e50` | V111 4/4, mean margin +49,368.00 |

Their exact files, hashes, licenses, dependency-closure hashes, and provenance
are in `experiments/independent_gold_pool/public_candidate_addendum_sources.json`.
The executed output is
`data/evaluation/independent_gold_pool/public_candidate_addendum_probe.json`.

Ten additional executable routes were recovered from public notebook snapshots
preserved by the GzmCR repository. They are Gold for the route that actually
executes locally, but are not claimed to be the notebook author's full
closed-loop policy or submitted binary. All ten were distinct full common-probe
families. V111 won 39/40 route games; `public_route_frontier_soil` was the only
route to win one game, giving V111 a 75% four-game probe WR. The route source
and result manifests are:

- `experiments/independent_gold_pool/public_pure_route_candidate_sources.json`
- `data/evaluation/independent_gold_pool/public_pure_route_probe.json`

The repository-history addendum deliberately sampled distinct strategic eras:
melon/geese, milk flooding, sheep/wool specialization, wheat-only and
livestock-only branches, market-wave/cross-product guards, multi-opponent
fitting, and route-conditioned timing. Its immutable-before-probe source list
and output are:

- `experiments/independent_gold_pool/public_history_candidate_sources.json`
- `data/evaluation/independent_gold_pool/public_history_candidate_probe.json`

All 25 sources completed all four games. They formed 24 families inside the
addendum: `gzmcr_rl10_milk_bidirectional` and `gzmcr_v32_v27_timing` collapsed
together. The GzmCR public-meta-counter family also collapsed with the already
probed GzmCR repository HEAD, so the consolidated registry gained 23, not 24,
families. V111 won all 100 history games; the smallest family mean margin was
+8,967.5. Consequently these histories improve Regression coverage but add no
30–70% or 70–80% Sensitivity matchup.

Two further public repositories were pinned and inspected. Three standalone
executables were eligible: Alpesh Kumar's crop-first mixed-livestock HEAD and
its rejected marginal-revenue allocator, plus Deepesh Rao's single-farmer
FarmBrain deliverable. All 12 games completed, all three action families were
distinct, and V111 won every game; the smallest family mean margin was
+58,852.5. Their manifests are:

- `experiments/independent_gold_pool/public_external_github_candidate_sources.json`
- `data/evaluation/independent_gold_pool/public_external_github_candidate_probe.json`

The Kaggle page for `flexonafft/kaggriculture-multi-route-farming-agent`
advertised a public score of 1961.6 and is the strongest remaining acquisition
lead. It was not promoted to Gold: the local Kaggle CLI had no authenticated
session and anonymous `GetKernel` / `ListKernelSessionOutput` returned HTTP
403, so no executable output bytes were obtained.

## Live-field correspondence

Re-matching the saved V113 live action hashes after acquisition retains two
strong h200 correspondences to the COK public HEAD (episodes `104514450` and
`104520088`) and three public-V27 correspondences. The latter also match the
collapsed GzmCR RL10/V32 history family, but that does not create three more
episodes or a second policy vote. Thus 5/58 live episodes have h200+
correspondence to known executable artifacts; none matches through h719. The
other 53 trajectories remain Bronze.

This is source identification evidence, not a claim that the live opponent ran
byte-identical code. Prefix correspondence never promotes a replay to Gold.

## Kaggle notebook/output acquisition boundary

The following public Kaggle pages were examined as executable-code leads:

- `kiykhoi/kaggriculture-agents`
- `ryanmyers03/kaggriculture-agent-v1`
- `nagatakengo/kaggriculture`
- `raykkretzschmar/kaggriculture-rank-your-agent`
- `tetsutani/read-the-town-build-the-farm-kaggriculture`
- `andrewsokolovsky/kaggriculture`
- `flexonafft/kaggriculture-adaptive-replay-agent`

Anonymous HTML/API probing did not yield authenticated output downloads in this
environment; Kaggle `GetKernel` / `ListKernelSessionOutput` requests returned
HTTP 403. Those pages therefore remain acquisition leads and are not counted as
Gold. No replay-only artifact was upgraded to executable evidence.

## Panel interpretation

The action-family diversity objective is met at the inventory level, but the
Sensitivity objective is not. The consolidated pool contains zero 30–70%
draw-adjusted matchups and only one 70–80% near-target family. Adding opponents
that V111 beats nearly always improves Regression coverage, not
strategy-uplift sensitivity. For that reason the history addendum was not
expanded into another V111/V113 strength tournament.

All probed sources, action families, and probe seeds are Development data and
are permanently excluded from Fresh Holdout.
