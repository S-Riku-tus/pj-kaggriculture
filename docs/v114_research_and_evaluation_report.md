# V114 research and evaluation report

**REJECT V114 / V114r1 / forced-delivery ablation. Keep V111. Do not submit these artifacts to Kaggle. No improvement in competitive strength was demonstrated.**

The latest checked leader is **SpaTaro, 3136.2**, at `2026-09-11T01:22:20.024283+00:00`. The detailed September 10 replay snapshot had the same leader/submission at 3062.4. The result of this research is a stronger diagnostic opponent pool, a falsified route-switch implementation, and a clearer feasibility requirement; it is not a 3000-class Agent. [Latest state](current_state_20260911.md), [full repository audit](current_state_20260910.md).

## A–P decision record

| Requested item | Finding |
| --- | --- |
| A. Current #1 rating | 3136.2, SpaTaro, submission 56114097; timestamp above. |
| B. Top meta | A large shared-opening cluster plus distinct rank-1 Carrot and rank-3 Tomato/Goose structures in the analyzed September 10 sample. 18 submissions share one field h48; their continuations differ. This is observational, not a causal recipe. |
| C. True Champion | Local production V111, exact archive/source match. GitHub main and local HEAD matched; neither has a root main.py. Latest own remote artifact remains unmapped despite near action fidelity. |
| D. Largest gap | Narrow continuation choices and incomplete state-specific cash/work feasibility. New public reacting policies beat V111 heavily. The exact causal explanation of the leader's advantage remains unidentified. |
| E. Hypotheses | Residual-demand routes; terminal liquidation; opponent supply; sale preemption; Carrot route; Sheep expansion; service intensity; delayed commitment; current Top continuation package; mixed opening/PSRO. |
| F. Primary choice | H1 directly addresses middle-game portfolio commitment while retaining an exact common prefix and existing coherent suffixes. It was ranked before implementation/outcomes. |
| G. Implementation | One decision at t153 between default/yarn_second using projected relative cash, Town absorption and public opponent supply at scales .75/1/1.25; require all advantages >2000 and nonnegative projected cash. Latch once. V114r1 fixes only the internal configuration argument. |
| H. Paired results | 32 pairs per variant, four acquired policies × four development seeds × both seats, 720 states each. V114r1 12W/0D/20L equals V111; forced delivery 0W/0D/32L. |
| I. L→W / W→L | V114r1 0/0; forced delivery 0/12. No Draw→Win or Win→Draw in either panel. |
| J. Lineage payoff | Matrix below; four executables conservatively merge to two broad source-ancestry groups. |
| K. Safety | Original V114 has a checkpoint runtime bug. V114r1 adds no actions/states or safety events; two inherited-transaction flags were measurement errors. Forced delivery adds crop-to-weed and field no-op regressions in all 24 activated pairs, plus spawned weeds in 11. |
| L. Fresh holdout | Not opened. Earlier gates fail. Twelve unused seeds and 8 replay-body reservations remain sealed; metadata is public and not fully blind. |
| M. Promotion | REJECT. V114r1 did not deliver an intervention; forced delivery fails safety first and worsens pairwise outcome. |
| N. Submit? | No. Preserve V111 until an improved candidate passes diverse E4 + fresh E5 evaluation. |
| O. Estimated strength | 3000 contender is unsupported. Historical older-field ~1600-class context is the most that can be said about V111; exact current rating is unmeasured. The latest unmapped submission's 1347.3 cannot be assigned to frozen V111. |
| P. Next five hours | Validate feasible state-specific suffixes and collect causal route-value labels against stronger distinct source families; detailed priority below. |

## Research and evidence

The initial clean repository snapshot captured 895 tracked-file hashes, version archives, registries, environment, source layouts and engine identity before agent changes. V111 archive SHA256 is `85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e`. Kaggle CLI 2.2.4 was inspected; authenticated access failed, while public APIs using competition ID147734 supplied current data. Four full GitHub sources were acquired and frozen; no fixed replay was substituted as a causal opponent. Their discovery probe produced V111 10W/22L, exposing losses absent from the old near-all-winning pool.

The September 10 extraction contains 236 unique episodes / 472 seat records, with multi-horizon action and field hashes, daily farm/market/Town/opponent trajectories, pre24/post72 shop event windows, sale phase rows and terminal diagnostics. V111's identifiable episodes remain historical through September1: 95W/4D/48L, with 17 Day18 leads becoming losses. These are not newly played current V111 ladder games. The event study is descriptive and does not solve day/route/opponent confounding. Market row quantities are requested/capped, not exact realized revenue. [Meta analysis](current_meta_analysis_20260910.md), [weakness map](champion_weakness_map_20260910.md).

**The assumption that all Top openings have converged was rejected.** There is a dominant shared-opening cluster, but the leader and rank3 use different structures. **The assumption that more route diversity is automatically useful was rejected for this intervention.** The fixed suffix can match the action prefix yet fail later capital and maintenance requirements. **No non-transitive payoff cycle was established**, so mixed openings/PSRO were not introduced.

The public-stock/supply ridge study improved supply MAE under a stricter episode-excluding split, but remains E2. It does not establish sell timing or win improvement. [Supply report](opponent_supply_estimation_20260910.md). Ten hypotheses and their mechanism, evidence, upside, risk, complexity and evaluation cost were ranked before coding. [Preregistered ranking](research_hypothesis_ranking_20260910.md).

## Implementation bug, inactive gate, forced-delivery ablation

Original V114 passed pricing/prefix/private-input tests and standalone smoke, but its t153 direct call supplied raw engine configuration to the internal route selector. A full paired runner supplied that configuration explicitly and raised `AttributeError: yarn_second_start`. Diagnostic logs preserve the failure. V114 is rejected for an implementation bug; it has no valid competitive panel. The corrected V114r1 retains the original archive separately and uses the frozen internal route configuration plus canonical observation step. A regression test covers first-Yarn, second-Yarn and default regimes with raw engine configuration and no explicit observation step.

V114r1 then completed 32 pairs with exact action/state identity and zero gate activations. Twenty-four states had a default route eligible for comparison; eight already selected yarn_second. None met the complete projection gate. This is **treatment delivery failure / insufficient activation**, not a successful safety-preserving strategic improvement. A postmortem on 16 Discovery control states found the yarn_second projection infeasible in 13, usually at a Sheep purchase at t192 with projected cash between -39 and -113. The default projection remained feasible in all16. These labels do not prove an error in the cash gate; the subsequent forced test shows that simply removing it is harmful.

H2 was screened next. In 26/32 Discovery games the last action already used all10 market slots. In the remaining six, terminal private stock was one Strawberry, worth a small observed-price proxy against deficits of thousands. No potential Loss→Win was found in this append-only opportunity screen. It is E0/E1, not a fixed-replay causal claim, and it does not reject all earlier liquidation scheduling. No second submission candidate was created for that limited opportunity.

The final **research-only forced-delivery ablation** keeps the same V111 control, t153 prefix and suffix choice, but chooses yarn_second whenever the original route is default. It isolates whether gate inactivity hides a useful route. Development seeds were already spent; no holdout was used and no new threshold was fitted. It is explicitly ineligible for submission. It activates in24/32 pairs and loses all12 baseline wins.

## Pairwise promotion dashboard

| Executable policy | Pairs | V111 W/D/L | V114r1 W/D/L | Forced W/D/L | Forced L→W | Forced W→L | Forced mean Δmargin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ggmljs_v16 | 8 | 8/0/0 | 8/0/0 | 0/0/8 | 0 | 8 | -21588.1 |
| mooman_e052a | 8 | 2/0/6 | 2/0/6 | 0/0/8 | 0 | 2 | -11953.2 |
| qeinstein_moev2 | 8 | 2/0/6 | 2/0/6 | 0/0/8 | 0 | 2 | -2550.0 |
| souvik_v4 | 8 | 0/0/8 | 0/0/8 | 0/0/8 | 0 | 0 | -2336.2 |

Mooman/souvik share PSR continuation ancestry; mooman/ggmljs also share Kaito ancestry. Conservative transitive merging leaves two broad ancestry groups, not four independent lineages. Both seats remain in each requested/resolved-seed cluster. Four seeds limit uncertainty estimation; these are **negative development screens (E3)**, not a diverse E4 tournament or fresh E5 evaluation.

V114r1: Δwin-score=0, mean Δself/Δopponent/Δmargin=0, P10 margin=-23861, all32 first-divergence audits null. Forced delivery: Δwin-score=-0.375, mean Δself=-9534.25, Δopponent=72.66, Δmargin=-9606.91, P10 control/candidate=-23861.0/-27764.0.

Equal-source and equal-ancestry hierarchical bootstrap results, lineage-specific rates, worst-source results and ±.2 reweighting stress scenarios are saved in the dashboards. Actual live source frequencies are unidentified; equal weights must not be called measured current-meta weights. Forced worst reweighting Δ=-0.542; conservative ancestry worst Δ=-0.367. Bradley–Terry is diagnostic only and does not convert these games to a Kaggle rating: forced candidate-minus-control ability=-24.956. Non-transitivity remains unresolved.

## Safety and first divergence

Both completed panels have zero runtime failures, incomplete games, negative-cash games and animal losses. V111 already emits many oversized sale requests and has crop-to-weed events; absolute counters are retained so absence of a *new* regression is not confused with absence of all events. In V114r1 the raw evaluator flagged two incomplete Cow→Sheep transactions because it audited purchases at the new route intervention t153, while V111's inherited purchase remains at t248. The stored replays were re-audited at t248 with the existing engine transaction simulator; both transactions complete. Raw flags remain preserved alongside the correction. This correction does not alter the rejection decision.

Forced delivery adds **24 crop-to-weed regressions, 24 field no-op regressions, 11 spawned-weed regressions**. No coin gain rescues those failures. All24 activated pairs first differ at t153 and have no earlier action/state divergence. All32 requested seeds equal resolved seeds in both arms; archives and engine hashes match frozen inputs.

| Policy | Seed | Seat | Self action | Self money | Portfolio | Workers | Opponent action | Response lag | Opponent money | Market | Price | Town |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mooman_e052a | 10091012 | 0 | 153 | 154 | 159 | 160 | none | none | 166 | 154 | 154 | 216 |
| mooman_e052a | 10091012 | 1 | 153 | 154 | 159 | 160 | none | none | 166 | 154 | 154 | 216 |
| mooman_e052a | 10091013 | 0 | 153 | 154 | 159 | 160 | 285 | 132 | 166 | 154 | 154 | 216 |
| mooman_e052a | 10091013 | 1 | 153 | 154 | 159 | 160 | 285 | 132 | 166 | 154 | 154 | 216 |
| souvik_v4 | 10091012 | 0 | 153 | 154 | 159 | 160 | 625 | 472 | 165 | 154 | 154 | 216 |
| souvik_v4 | 10091012 | 1 | 153 | 154 | 159 | 160 | 625 | 472 | 165 | 154 | 154 | 216 |
| souvik_v4 | 10091013 | 0 | 153 | 154 | 159 | 160 | 226 | 73 | 167 | 154 | 154 | 216 |
| souvik_v4 | 10091013 | 1 | 153 | 154 | 159 | 160 | 226 | 73 | 167 | 154 | 154 | 216 |
| ggmljs_v16 | 10091011 | 0 | 153 | 154 | 159 | 160 | 206 | 53 | 169 | 154 | 154 | 288 |
| ggmljs_v16 | 10091011 | 1 | 153 | 154 | 159 | 160 | 258 | 105 | 169 | 154 | 154 | 216 |
| ggmljs_v16 | 10091012 | 0 | 153 | 154 | 159 | 160 | 359 | 206 | 169 | 154 | 154 | 216 |
| ggmljs_v16 | 10091012 | 1 | 153 | 154 | 159 | 160 | 264 | 111 | 169 | 154 | 154 | 216 |
| ggmljs_v16 | 10091013 | 0 | 153 | 154 | 159 | 160 | 216 | 63 | 169 | 154 | 154 | 216 |
| ggmljs_v16 | 10091013 | 1 | 153 | 154 | 159 | 160 | 216 | 63 | 169 | 154 | 154 | 216 |
| ggmljs_v16 | 10091014 | 0 | 153 | 154 | 159 | 160 | 253 | 100 | 169 | 154 | 154 | 216 |
| ggmljs_v16 | 10091014 | 1 | 153 | 154 | 159 | 160 | 253 | 100 | 169 | 154 | 154 | 216 |
| qeinstein_moev2 | 10091011 | 0 | 153 | 154 | 159 | 160 | 263 | 110 | 167 | 154 | 154 | 216 |
| qeinstein_moev2 | 10091011 | 1 | 153 | 154 | 159 | 160 | 263 | 110 | 167 | 154 | 154 | 216 |
| qeinstein_moev2 | 10091012 | 0 | 153 | 154 | 159 | 160 | 263 | 110 | 167 | 154 | 154 | 216 |
| qeinstein_moev2 | 10091012 | 1 | 153 | 154 | 159 | 160 | 263 | 110 | 167 | 154 | 154 | 216 |
| qeinstein_moev2 | 10091013 | 0 | 153 | 154 | 159 | 160 | 313 | 160 | 167 | 154 | 154 | 216 |
| qeinstein_moev2 | 10091013 | 1 | 153 | 154 | 159 | 160 | 313 | 160 | 167 | 154 | 154 | 216 |
| qeinstein_moev2 | 10091014 | 0 | 153 | 154 | 159 | 160 | 263 | 110 | 167 | 154 | 154 | 216 |
| qeinstein_moev2 | 10091014 | 1 | 153 | 154 | 159 | 160 | 263 | 110 | 167 | 154 | 154 | 216 |

Numbers are first differing action/state indices; action t is stored at replay state t+1. Example mooman/10091012/seat0: at t153 the candidate omits a Wool sell; price and own money differ at state154, portfolio159, workers160, opponent coin166, Town216. The opponent's actions stay identical in that pair, yet its coin changes through the shared market. Other responding pairs are explicitly recorded above. Town divergence is an observed RNG-mediated consequence; internal PRNG draw-state divergence was not separately instrumented. The full audits preserve actual actions, state values and response ordering. [V114r1 dashboard](../data/evaluation/research_20260910/v114r1/development/promotion_dashboard.json), [forced dashboard](../data/evaluation/research_20260910/v114probe/development/promotion_dashboard.json), [raw first-divergence audits](../data/evaluation/research_20260910/v114probe/development/first_divergence_audits.json).

## Economy diagnostics and holdout

V111/V114r1 lead→loss counts: `{"day12": 0, "day18": 0, "day20": 0, "day24": 0}`. Forced lead→loss: `{"day12": 0, "day18": 2, "day20": 2, "day24": 2}`. Mean terminal stranded observed-price proxy is 46.44 for V111/V114r1 versus 287.09 forced. This proxy is not attainable sale revenue and not score. Per-game stock quantities and checkpoints are saved in `economy_diagnostics.json`. Eight inactive controls omitted by the default replay-saving policy were rerun solely to retain these requested diagnostics; their final coins exactly matched the original pairs.

Fresh simulation seeds `10091901–10091912` remain unused. Promotion seeds `10091101–10091112` also remain unused. The fresh replay reservations have no overlap with Discovery bodies; public metadata includes outcomes and is not claimed to be completely blind. **E4 and E5 were not run because prior gates fail.** No tuning on holdout and no live submission took place.

## Artifacts, tests and reproducibility

- Research Candidate: `agents/v114r1/`; deterministic archive `artifacts/submissions/v114r1.tar.gz`, SHA256 `08b249b246949424fa519c1b06ac234c82957dbf302c21d00a305f3fb676505c`.
- Rejected original: `agents/v114/`, `artifacts/submissions/v114.tar.gz`, SHA256 `bd3972926c5ecb6613d355fc9fbfc827728dbc5b83d8b64dd317e69cd37f0851`.
- Research-only ablation: `agents/v114probe/`, `artifacts/submissions/v114probe.tar.gz`, SHA256 `f99a614a5901ff33ecf00cc420385b0f9284c4c27513eba9c72109d09c8d1a2f`.
- Both panels: `data/evaluation/research_20260910/<version>/development/`, containing32 paired records, dashboards, all differing full replays, safety corrections and divergence/economy diagnostics.
- Frozen specifications and source registry: `experiments/research_20260910/`. Rebuilt archives exactly match source, runtime members and frozen hashes; the existing registry verifier checks Champion, treatment, opponents, evaluator and engine. Old Champion and research files remain preserved.

Twenty-one focused tests cover engine price agreement, exact route prefix, exclusion of private forecast input, the three configuration regimes, V111 behavior and evaluation isolation/safety. Ruff checks the changed production/evaluation code and research scripts. V114r1 standalone runs both seats to720 states. No new policy is promoted on those software checks alone.

Reproduction: run `scripts/research_20260910.py paired --version v114r1 --phase development --workers 4` or `--version v114probe`; existing completed rows are skipped. Packaging is deterministic; freezing an existing registered candidate refuses overwrite. Original failed V114 is retained for the regression case. Forecast strict validation uses `scripts/analyze_opponent_supply_20260910.py --strict-split` on stored rows. Report/table generation scripts are retained.

## Next five hours: highest-value work

1. **0–60 min: state feasibility before value fitting.** For each proposed suffix, replay its full labor/cash/feed/land pipeline from actual checkpoint state against a reacting opponent. Preserve the common prefix, but require correct carried goods, seed availability, shop-dependent cash and worker schedule. Explain the t192 purchase deficit and crop-maintenance failures before lowering any gate.
2. **60–150 min: expand executable ancestry and sensitive matchups.** Acquire at least one more materially distinct strong source and seek 30–70% matchups. Use mooman/qeinstein as strong anchors; treat PSR/Kaito overlaps as one broad family. Link current loss lineages to actual code where possible; keep replays Bronze otherwise.
3. **150–230 min: collect causal route-value labels.** Test a small number of fully feasible continuations, including the current Carrot/Goose/Tomato packages only when a complete pipeline is available. Fit Q to paired win/margin effects, with outcome flips as the decision criterion. The public supply forecast should support those decisions with uncertainty, not substitute for causal labels.
4. **230–300 min: freeze one small working gate, then diverse promotion and fresh holdout.** Use an actual activated intervention with no comparative safety failures; retain seed/seat clustering and robust ancestry reweighting. Open the reserved holdout only after the earlier gates pass.

The most useful new conclusion is **route-prefix compatibility does not establish economic/execution compatibility**. The adaptive-continuation direction remains a research hypothesis, while this gate and this forced suffix are rejected. No claimed win improvement, leader rating, average coin, imitation accuracy or portfolio diversity overrides the failed paired/safety evidence.
