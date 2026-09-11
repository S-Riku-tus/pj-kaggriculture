"""Final evidence synthesis and immutable decision records; no promotion action."""

# Long Markdown prose is kept intact in report templates.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def table(headers, rows):
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *["| " + " | ".join(str(v).replace("|", "/") for v in row) + " |" for row in rows],
        ]
    )


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    from scripts.evaluation.registry import bundle_sha256, verify_inputs, write_record
    from scripts.package_submission import submission_files
    from scripts.research_20260910 import package

    experiment = ROOT / "experiments/research_20260910"
    evaluation = ROOT / "data/evaluation/research_20260910"
    source_registry = read(experiment / "source_registry.json")
    verification = {}
    for version in ("v114", "v114r1", "v114probe"):
        spec = read(experiment / f"{version}_preregistration.json")
        assert sha(ROOT / spec["archive"]) == spec["archive_sha256"]
        assert all(sha(ROOT / name) == expected for name, expected in spec["framework_hashes"].items())
        current = {name: path.read_bytes() for name, path in submission_files(ROOT / "agents" / version).items()}
        assert {name: hashlib.sha256(value).hexdigest() for name, value in current.items()} == spec["source_hashes"]
        rebuilt = experiment / "verification" / f"{version}_rebuilt.tar.gz"
        package(current, rebuilt)
        assert sha(rebuilt) == spec["archive_sha256"]
        with tarfile.open(ROOT / spec["archive"], "r:gz") as handle:
            for member in handle.getmembers():
                if member.isfile():
                    expected = hashlib.sha256(handle.extractfile(member).read()).hexdigest()
                    assert sha(experiment / "runtime" / version / member.name) == expected
        engine = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
        input_spec = {
            "arms": {
                "control": {"archive": source_registry["champion_archive"], "sha256": spec["control_sha256"]},
                "treatment": {"archive": spec["archive"], "sha256": spec["archive_sha256"]},
            },
            "opponent_pool": [
                {"path": source["archive"], "sha256": source["archive_sha256"], "lineage_id": source["candidate_id"]}
                for source in source_registry["sources"]
            ],
            "evaluator": {
                "files": sorted(spec["framework_hashes"]),
                "version": "existing framework plus declared route intervention",
                "sha256": bundle_sha256(ROOT, sorted(spec["framework_hashes"])),
            },
            "engine": {"source_path": str(engine), "sha256": spec["engine_sha256"], "version": spec["engine_version"]},
        }
        verification[version] = {
            "deterministic_rebuild_matches": True,
            "source_archive_runtime_members_match": True,
            "existing_registry_verification": verify_inputs(ROOT, input_spec),
        }
    for source in source_registry["sources"]:
        with tarfile.open(ROOT / source["archive"], "r:gz") as handle:
            for member in handle.getmembers():
                if member.isfile():
                    assert (
                        sha((ROOT / source["entrypoint"]).parent / member.name)
                        == hashlib.sha256(handle.extractfile(member).read()).hexdigest()
                    )
    save(experiment / "final_artifact_verification.json", verification)

    versions = ("v114r1", "v114probe")
    dashboard = {v: read(evaluation / v / "development/promotion_dashboard.json") for v in versions}
    safety = {v: read(evaluation / v / "development/transaction_checkpoint_adjudication.json") for v in versions}
    assert not safety["v114r1"]["adjudicated_candidate_new_failure_pair_counts"]
    assert safety["v114probe"]["adjudicated_candidate_new_failure_pair_counts"]["new_crop_to_weed"] == 24
    economy = {v: read(evaluation / v / "development/economy_diagnostics.json") for v in versions}
    pair_rows = {
        v: [
            json.loads(line)
            for line in (evaluation / v / "development/pairs.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        for v in versions
    }
    for version in versions:
        assert len(pair_rows[version]) == 32
        assert {r["seat"] for r in pair_rows[version]} == {0, 1}
        assert all(
            r["control"]["requested_seed"]
            == r["control"]["resolved_seed"]
            == r["treatment"]["requested_seed"]
            == r["treatment"]["resolved_seed"]
            == r["seed"]
            for r in pair_rows[version]
        )
        assert all(r["safety"][arm]["completed_720"] for r in pair_rows[version] for arm in ("control", "treatment"))
        assert all(r["behavioral_isolation_valid"] for r in pair_rows[version])
    fresh_seeds = set(source_registry["fresh_holdout_seeds"])
    assert not any(r["seed"] in fresh_seeds for rows in pair_rows.values() for r in rows)
    assert not any((evaluation / version / "fresh_holdout/pairs.jsonl").exists() for version in versions)
    reserved = read(ROOT / "data/current_field_20260910/fresh_episode_reservations.json")
    used = {
        r["episode_id"] for r in read(ROOT / "data/analysis/research_20260910_final/current_replay_input_manifest.json")
    }
    reserved_ids = {r["episode_id"] for r in reserved}
    assert reserved_ids.isdisjoint(used)
    present = [
        eid for eid in reserved_ids if (ROOT / f"data/current_field_20260910/replays/episode_{eid}.json.gz").exists()
    ]
    assert not present
    holdout = {
        "unused_simulation_seeds": sorted(fresh_seeds),
        "reserved_replay_count": len(reserved_ids),
        "reserved_replay_bodies_downloaded": present,
        "discovery_overlap": [],
        "status": "SEALED; promotion prerequisites failed",
        "metadata_caveat": "Public metadata includes outcomes; these reservations are not fully blind at metadata level. Simulation seeds have not been run.",
    }
    save(experiment / "final_holdout_audit.json", holdout)

    matrix_rows = []
    probe_matrix = {r["lineage_id"]: r for r in dashboard["v114probe"]["source_payoff_matrix"]}
    for row in dashboard["v114r1"]["source_payoff_matrix"]:
        forced = probe_matrix[row["lineage_id"]]
        matrix_rows.append(
            [
                row["lineage_id"],
                row["pairs"],
                f"{row['baseline']['wins']}/0/{row['baseline']['losses']}",
                f"{row['candidate']['wins']}/0/{row['candidate']['losses']}",
                f"{forced['candidate']['wins']}/0/{forced['candidate']['losses']}",
                forced["loss_to_win"],
                forced["win_to_loss"],
                f"{forced['mean_delta_margin']:.1f}",
            ]
        )
    divergent = [r for r in pair_rows["v114probe"] if r["incremental_treatment"]]
    divergence_rows = []
    for row in divergent:
        audit = row["divergence_audit"]
        states = audit["first_state_divergence"]

        def get_step(key, state_values=states):
            return state_values[key]["step"] if state_values[key] else "none"

        response = audit.get("first_opponent_response_step")
        divergence_rows.append(
            [
                row["lineage_id"],
                row["seed"],
                row["seat"],
                audit["own_first_divergence_step"],
                get_step("self_money"),
                get_step("self_portfolio"),
                get_step("self_workers"),
                response if response is not None else "none",
                response - 153 if response is not None else "none",
                get_step("opponent_money"),
                get_step("market_inventory"),
                get_step("prices"),
                get_step("town"),
            ]
        )
    source = read(ROOT / "data/analysis/research_20260910_supply/result_strict_episode_exclusion.json")
    supply_rows = [
        [
            r["item"],
            r["horizon"],
            r["target"],
            f"{r['MAE']['ridge']:.3f}",
            f"{r['MAE']['training_mean']:.3f}",
            f"{r['MAE'].get('maintained_calendar', 0):.3f}" if "maintained_calendar" in r["MAE"] else "n/a",
        ]
        for r in source["results"]
        if r["item"] in ("STRAWBERRY", "MILK", "WOOL") and r["target"] == "supply"
    ]
    supply_doc = f"""# Public opponent supply estimation — 2026-09-10

E2 predictive diagnostic only. Frozen ridge lambda=10, H24/72/144, 24 newest Discovery episodes, both seats; 13 connected groups of same submission or identical field h48. Raw public features and separately generated private targets are in [rows.jsonl](../data/analysis/research_20260910_supply/rows.jsonl). Current stock targets use the opponent's own private observation offline; future supply targets use exact engine-committed SELL quantities via the existing safety simulator. No opponent private input, seed or future observation enters a live Agent.

The initial leave-group-out analysis allowed the other player's rows from the same episode in training. A stricter audit now excludes **every held-out episode, including its other player**, with parameters unchanged. This stricter result is authoritative. Feature standardization is fitted on training rows only. These observed groups do not prove independent latent source ancestry, and 912 temporally overlapping examples are not 912 independent games.

{table(["Product", "Horizon", "Target", "Ridge MAE", "Train-mean MAE", "Maintained calendar MAE"], supply_rows)}

At H72, strict stock MAE is 2.841 Strawberry, 2.183 Milk, 2.774 Wool, versus training means 5.772/3.824/4.500. Broad-horizon Milk/Wool any-sale hazards are almost always true; ridge remains worse than the training-mean hazard predictor. Thus the result supports estimating supply quantity, not precise sell preemption. The calendar baseline assumes continued service and collection, and no new investment. A tree or larger model was not justified before resolving these target and causal-decision limitations.

At the $1 price floor, sales do not increase market inventory, so exact opponent stock is not identifiable from market differences alone. The output should be a distribution/interval with a missing-flow model, not a false exact balance. The next validation should use truly unseen source ancestry and a shorter 1–4-turn competing-sale hazard. Prediction accuracy alone does not select a portfolio or establish pairwise uplift. No trained forecast was installed in V114r1; its route valuation used a separate, simple maintained-supply scenario.

[Initial result retained](../data/analysis/research_20260910_supply/result.json); [strict result](../data/analysis/research_20260910_supply/result_strict_episode_exclusion.json); [reproducible analysis](../scripts/analyze_opponent_supply_20260910.py).
"""
    (ROOT / "docs/opponent_supply_estimation_20260910.md").write_text(supply_doc, encoding="utf-8")
    p = dashboard["v114probe"]
    spec1 = read(experiment / "v114r1_preregistration.json")
    specp = read(experiment / "v114probe_preregistration.json")
    latest = read(ROOT / "data/current_field_20260910/leaderboard_refresh_20260911.json")
    report = f"""# V114 research and evaluation report

**REJECT V114 / V114r1 / forced-delivery ablation. Keep V111. Do not submit these artifacts to Kaggle. No improvement in competitive strength was demonstrated.**

The latest checked leader is **SpaTaro, 3136.2**, at `{latest["fetched_at"]}`. The detailed September 10 replay snapshot had the same leader/submission at 3062.4. The result of this research is a stronger diagnostic opponent pool, a falsified route-switch implementation, and a clearer feasibility requirement; it is not a 3000-class Agent. [Latest state](current_state_20260911.md), [full repository audit](current_state_20260910.md).

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
| L. Fresh holdout | Not opened. Earlier gates fail. Twelve unused seeds and {len(reserved_ids)} replay-body reservations remain sealed; metadata is public and not fully blind. |
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

{table(["Executable policy", "Pairs", "V111 W/D/L", "V114r1 W/D/L", "Forced W/D/L", "Forced L→W", "Forced W→L", "Forced mean Δmargin"], matrix_rows)}

Mooman/souvik share PSR continuation ancestry; mooman/ggmljs also share Kaito ancestry. Conservative transitive merging leaves two broad ancestry groups, not four independent lineages. Both seats remain in each requested/resolved-seed cluster. Four seeds limit uncertainty estimation; these are **negative development screens (E3)**, not a diverse E4 tournament or fresh E5 evaluation.

V114r1: Δwin-score=0, mean Δself/Δopponent/Δmargin=0, P10 margin=-23861, all32 first-divergence audits null. Forced delivery: Δwin-score={p["summary"]["delta_win_score"]:.3f}, mean Δself={p["summary"]["mean_delta_self_coin"]:.2f}, Δopponent={p["summary"]["mean_delta_opponent_coin"]:.2f}, Δmargin={p["summary"]["mean_delta_margin"]:.2f}, P10 control/candidate={p["p10_margin"]["control"]}/{p["p10_margin"]["treatment"]}.

Equal-source and equal-ancestry hierarchical bootstrap results, lineage-specific rates, worst-source results and ±.2 reweighting stress scenarios are saved in the dashboards. Actual live source frequencies are unidentified; equal weights must not be called measured current-meta weights. Forced worst reweighting Δ={p["robust_source_reweighting"]["worst_delta"]:.3f}; conservative ancestry worst Δ={p["robust_ancestry_reweighting"]["worst_delta"]:.3f}. Bradley–Terry is diagnostic only and does not convert these games to a Kaggle rating: forced candidate-minus-control ability={p["bradley_terry_diagnostic"]["candidate_minus_baseline_ability"]:.3f}. Non-transitivity remains unresolved.

## Safety and first divergence

Both completed panels have zero runtime failures, incomplete games, negative-cash games and animal losses. V111 already emits many oversized sale requests and has crop-to-weed events; absolute counters are retained so absence of a *new* regression is not confused with absence of all events. In V114r1 the raw evaluator flagged two incomplete Cow→Sheep transactions because it audited purchases at the new route intervention t153, while V111's inherited purchase remains at t248. The stored replays were re-audited at t248 with the existing engine transaction simulator; both transactions complete. Raw flags remain preserved alongside the correction. This correction does not alter the rejection decision.

Forced delivery adds **24 crop-to-weed regressions, 24 field no-op regressions, 11 spawned-weed regressions**. No coin gain rescues those failures. All24 activated pairs first differ at t153 and have no earlier action/state divergence. All32 requested seeds equal resolved seeds in both arms; archives and engine hashes match frozen inputs.

{table(["Policy", "Seed", "Seat", "Self action", "Self money", "Portfolio", "Workers", "Opponent action", "Response lag", "Opponent money", "Market", "Price", "Town"], divergence_rows)}

Numbers are first differing action/state indices; action t is stored at replay state t+1. Example mooman/10091012/seat0: at t153 the candidate omits a Wool sell; price and own money differ at state154, portfolio159, workers160, opponent coin166, Town216. The opponent's actions stay identical in that pair, yet its coin changes through the shared market. Other responding pairs are explicitly recorded above. Town divergence is an observed RNG-mediated consequence; internal PRNG draw-state divergence was not separately instrumented. The full audits preserve actual actions, state values and response ordering. [V114r1 dashboard](../data/evaluation/research_20260910/v114r1/development/promotion_dashboard.json), [forced dashboard](../data/evaluation/research_20260910/v114probe/development/promotion_dashboard.json), [raw first-divergence audits](../data/evaluation/research_20260910/v114probe/development/first_divergence_audits.json).

## Economy diagnostics and holdout

V111/V114r1 lead→loss counts: `{json.dumps(economy["v114r1"]["summary"]["control"]["lead_to_loss"])}`. Forced lead→loss: `{json.dumps(economy["v114probe"]["summary"]["treatment"]["lead_to_loss"])}`. Mean terminal stranded observed-price proxy is {economy["v114r1"]["summary"]["control"]["mean_stranded_price_proxy"]:.2f} for V111/V114r1 versus {economy["v114probe"]["summary"]["treatment"]["mean_stranded_price_proxy"]:.2f} forced. This proxy is not attainable sale revenue and not score. Per-game stock quantities and checkpoints are saved in `economy_diagnostics.json`. Eight inactive controls omitted by the default replay-saving policy were rerun solely to retain these requested diagnostics; their final coins exactly matched the original pairs.

Fresh simulation seeds `10091901–10091912` remain unused. Promotion seeds `10091101–10091112` also remain unused. The fresh replay reservations have no overlap with Discovery bodies; public metadata includes outcomes and is not claimed to be completely blind. **E4 and E5 were not run because prior gates fail.** No tuning on holdout and no live submission took place.

## Artifacts, tests and reproducibility

- Research Candidate: `agents/v114r1/`; deterministic archive `artifacts/submissions/v114r1.tar.gz`, SHA256 `{spec1["archive_sha256"]}`.
- Rejected original: `agents/v114/`, `artifacts/submissions/v114.tar.gz`, SHA256 `bd3972926c5ecb6613d355fc9fbfc827728dbc5b83d8b64dd317e69cd37f0851`.
- Research-only ablation: `agents/v114probe/`, `artifacts/submissions/v114probe.tar.gz`, SHA256 `{specp["archive_sha256"]}`.
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
"""
    (ROOT / "docs/v114_research_and_evaluation_report.md").write_text(report, encoding="utf-8")
    decision = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "champion": "v111",
        "champion_archive_sha256": source_registry["champion_sha256"],
        "decisions": {
            "v114": {"status": "REJECT", "reason": "checkpoint configuration implementation bug"},
            "v114r1": {"status": "REJECT", "reason": "zero delivered intervention, no causal uplift"},
            "v114probe": {
                "status": "REJECT",
                "reason": "research-only forced delivery; safety regressions and 12 Win-to-Loss",
            },
        },
        "submission_recommendation": "DO_NOT_SUBMIT",
        "evidence": ["E0", "E1", "E2_predictive_only", "E3_negative_development"],
        "E4": "not reached",
        "E5": "sealed",
        "E6": "no new candidate live evidence",
        "report": "docs/v114_research_and_evaluation_report.md",
    }
    target = experiment / "champion_challenger_decision.json"
    if not target.exists():
        write_record(target, decision)
    for version in ("v114", "v114r1", "v114probe"):
        (ROOT / "agents" / version / "README.md").write_text(
            f"# {version}: REJECT\n\nResearch artifact; do not submit or promote. Champion remains V111.\n\nSee [research/evaluation report](../../docs/v114_research_and_evaluation_report.md) and [frozen specification](../../experiments/research_20260910/{version}_preregistration.json).\n",
            encoding="utf-8",
        )
    print(
        "Final report, supply report, frozen artifact verification, holdout audit and decision registry written.",
        flush=True,
    )


if __name__ == "__main__":
    main()
