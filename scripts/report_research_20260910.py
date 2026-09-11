"""Reproducible descriptive reports and paired dashboard; no new evaluator."""

# Markdown report templates retain full paragraphs for readable generated output.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ANALYSIS = ROOT / "data/analysis/research_20260910_final"
EXPERIMENT = ROOT / "experiments/research_20260910"
EVAL = ROOT / "data/evaluation/research_20260910"
DOCS = ROOT / "docs"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(v).replace("|", "/") for v in row) + " |" for row in rows)
    return "\n".join(lines)


def wdl(data):
    return "/".join(str(data.get(k, 0)) for k in ("win", "draw", "loss"))


def quantile(values, fraction):
    values = sorted(values)
    return values[int((len(values) - 1) * fraction)] if values else None


def describe():
    summary = read(ANALYSIS / "current_meta_weakness_summary.json")
    rows = read(ANALYSIS / "current_episode_seat_metrics.json")
    snapshot = read(ROOT / "data/current_field_20260910/leaderboard.json")
    leaders = snapshot["data"]["publicLeaderboard"]
    teams = {row["teamId"]: row for row in snapshot["data"]["teams"]}
    captured = datetime.fromisoformat(snapshot["fetched_at"])
    scores = [float(row["displayScore"].replace(",", "")) for row in leaders if row.get("displayScore")]
    leaderboard_rows = []
    for row in leaders[:30]:
        team = teams[row["teamId"]]
        age = (
            captured - datetime.fromisoformat(team["lastSubmissionDate"].replace("Z", "+00:00"))
        ).total_seconds() / 3600
        episode_file = ROOT / f"data/current_field_20260910/episodes_{row['submissionId']}.json"
        count = len(read(episode_file).get("data", {}).get("episodes", [])) if episode_file.exists() else "unavailable"
        leaderboard_rows.append(
            [
                row["rank"],
                team["teamName"],
                row["teamId"],
                row["submissionId"],
                row["displayScore"],
                f"{age:.1f}",
                count,
            ]
        )
    distribution = {str(q): quantile(scores, q) for q in (0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1)}
    save(
        ANALYSIS / "leaderboard_table_and_distribution.json",
        {"snapshot": snapshot["fetched_at"], "n": len(scores), "quantiles": distribution, "top30": leaderboard_rows},
    )
    state = f"""# Current state — 2026-09-10

Decision context: the observed leader is **SpaTaro, 3062.4**, at `{snapshot["fetched_at"]}`. The target 3000 is therefore a real current competitive tier, not a sufficient condition for first place. This is a timestamped snapshot, not a promise that a live leaderboard remains unchanged. [Official leaderboard](https://www.kaggle.com/competitions/kaggriculture/leaderboard); [saved API response](../data/current_field_20260910/leaderboard.json).

## Champion and repository identity

The frozen **local production Champion is V111**. Branch `main`, initial HEAD `f4d9e35c47bfbe9815bb9c65c998218ccf08d5c0`; `git ls-remote origin refs/heads/main` matched. The initial tracked and untracked status was clean. There is no root `main.py` in local HEAD or GitHub main: this repository uses versioned `agents/<version>/main.py`. Thus a root-file equality claim would be incorrect.

- V111 main SHA256: `699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660`.
- V111 archive SHA256: `85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e`; all archived source members match local source. A byte-identical control is frozen in `experiments/research_20260910/champion_v111.tar.gz`.
- V113 is a rejected Challenger, not the production Champion. Its historical formal evaluation had 0 Loss→Win and 0 Win→Loss, with two Draw→Win against the clone calibration case and new weed incidents in four pairs. Current V113 source differs from its submitted archive in documentation/diagnostic strings; it is not byte-identical. No previous V114 existed at initial audit.
- **Remote latest submission identity is unresolved.** Our team's latest public submission is `56089444`, submitted September 8, with rating 1347.3 at acquisition; previous `55941525` was 1384.9. Neither has a verified local artifact mapping. Do not label either V111 or V114. Known V111 IDs are `55909167` and `55912910`; their available games end September 1. A fresh download of those games is still historical evidence.

The initial audit inventories `agents`, `artifacts/submissions`, `experiments`, `data/evaluation`, `data/analysis`, `docs`, `scripts/evaluation`, `tests`, environment files, registries and 895 tracked-file hashes. Existing research and Champion files are preserved. [Full initial audit](../experiments/research_20260909/initial_repository_audit.json).

## Engine and access

Installed `kaggle-environments 1.32.7`; Kaggle CLI `2.2.4`; pytest `8.4.2`; Ruff `0.12.12`; NumPy `2.5.2`. The installed Kaggriculture engine SHA256 is `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`, exactly matching the downloaded official master engine. [Official engine](https://github.com/Kaggle/kaggle-environments/blob/master/kaggle_environments/envs/kaggriculture/kaggriculture.py); [mechanics probes](../experiments/research_20260909/mechanics_probes.json).

CLI command help and authentication were checked. Authenticated competition access reported `AUTHENTICATION_REQUIRED`; public Kaggle APIs using competition ID **147734** supplied leaderboard, teams and episode metadata/replays. Anonymous notebook source/output calls returned 403; those failures are retained, not interpreted as unavailable private code. Public GitHub archives supplied four executable policies. HTTP 429 responses were retried sequentially with delays, and successful downloads were cached.

There are **720 stored states, 719 decisions (t0–t718)**. The last decision is day 29 hour 22, and the final state is day 29 hour 23. There is no final end-of-day automatic deposit. The score is final coin; shed or carried inventory is not terminal score.

## Leaderboard snapshot

{table(["Rank", "Team", "Team ID", "Submission", "Rating", "Team last submission age (hours)", "API episodes returned"], leaderboard_rows)}

Age is the team's last submission timestamp, not a verified source build age. Returned episode counts can be an API window rather than lifetime counts. Full rating distribution: N={len(scores)}, quantiles `{json.dumps(distribution)}`. The complete leaderboard is in the raw response.

## Current gap and evidence boundary

V111 has three coherent route backbones and very little midseason new-crop choice. During days 15–24 all planned new planting in all three backbones is Wheat (69/72/70 actions). Current top replays show a common opening cluster but material alternative continuations, including Carrot exposure at rank 1 and Tomato/Goose at rank 3. These are mechanistic research leads, not proof that copying their asset counts wins.

New full-source opponents exposed a large gap: on four discovery seeds and both seats V111 scored **10W/0D/22L**, versus mooman 0/0/8, souvik 2/0/6, ggmljs 8/0/0, qeinstein 0/0/8. The first three share source ancestry; four executable policies are at most two conservatively merged broad ancestry groups. These results are not a calibrated Kaggle rating.

No current evidence supports calling V111 a 2500-class or 3000 contender. Historical V111 games mostly concern the older ~1500 field, the latest unmapped submission is 1347.3, and V111 loses heavily to newly acquired public policies. A provisional **older ~1600-class baseline** is defensible only as historical context; its exact current rating is unmeasured.

Discovery, development, promotion and fresh seeds are separately registered. New replay holdout entries contain public metadata (including outcomes) but their replay bodies were not downloaded; they are not completely blind metadata. The genuinely unused simulation seeds remain sealed unless all prior gates pass. Existing evaluation seeds are development data. [Frozen registry](../experiments/research_20260910/source_registry.json).
"""
    (DOCS / "current_state_20260910.md").write_text(state, encoding="utf-8")

    top = [row for row in rows if row["cohort"].startswith("top_rank_")]
    top_ids = sorted({r["submission_id"] for r in top})
    parent = {key: key for key in top_ids}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for group in summary["top_opening_continuation_groups"]:
        members = group["submissions"]
        for item in members[1:]:
            parent[find(item)] = find(members[0])
    components = defaultdict(list)
    for item in top_ids:
        components[find(item)].append(item)
    opening = [
        [
            g["field_h48"],
            len(g["submissions"]),
            g["episode_seats"],
            g["exact_continuations"],
            g["portfolio_continuations"],
        ]
        for g in summary["top_opening_continuation_groups"]
    ]
    top_table = []
    for rank in range(1, 11):
        cohort = summary["cohorts"][f"top_rank_{rank}"]
        selected = [r for r in top if r["cohort"] == f"top_rank_{rank}"]
        portfolio = cohort["mean_portfolio"]
        land = [r["land_timing"][0] for r in selected if r["land_timing"]]
        top_table.append(
            [
                rank,
                cohort["n"],
                wdl(cohort["wdl"]),
                cohort["unique_field_hashes"]["48"],
                median(land) if land else "none",
                f"{portfolio['CARROT']:.1f}",
                f"{portfolio['TOMATO']:.1f}",
                f"{portfolio['STRAWBERRY']:.1f}",
                f"{portfolio['COW']:.1f}",
                f"{portfolio['SHEEP']:.1f}",
                f"{portfolio['GOOSE']:.1f}",
                f"{cohort['mean_stranded_price_proxy']:.1f}",
            ]
        )
    matched = defaultdict(list)
    for row in top:
        matched[(row["submission_id"], tuple(row["final_shops"][:3]))].append(row)
    matched_rows = []
    for (sid, shops), selected in matched.items():
        if len(selected) >= 2 and len({r["opponent_field_hashes"]["100"] for r in selected}) > 1:
            matched_rows.append(
                {
                    "submission": sid,
                    "first_three_shops": shops,
                    "n": len(selected),
                    "opponent_h100_groups": len({r["opponent_field_hashes"]["100"] for r in selected}),
                    "portfolio_signatures": len({r["daily_portfolio_hash_144_600"] for r in selected}),
                    "episodes": [r["episode_id"] for r in selected],
                }
            )
    save(
        ANALYSIS / "top_lineage_and_opponent_dependence.json",
        {
            "components": list(components.values()),
            "component_definition": "same submission or exact field h48; conservative observed groups, not independent latent policies",
            "matched_first_three_shops": matched_rows,
        },
    )
    event_rows = [
        [
            r["cohort"],
            r["product"],
            r["new_shop_demands_product"],
            r["n_event_rows"],
            f"{r['mean_pre24_delta_asset']:.3f}",
            f"{r['mean_delta_asset72']:.3f}",
            f"{r['mean_delta_margin72']:.1f}",
        ]
        for r in summary["shop_events72"]
    ]
    micro = defaultdict(Counter)
    with (ANALYSIS / "current_sell_microstructure.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            category = "top" if row["cohort"].startswith("top_rank_") else row["cohort"]
            if category in ("top", "champion_v111"):
                micro[(category, row["product"])][int(row["phase4"])] += int(row["availability_capped_qty"])
    micro_table = [
        [category, item, *[counts[p] for p in range(4)]] for (category, item), counts in sorted(micro.items())
    ]
    meta = f"""# Current meta analysis — 2026-09-10

Evidence level **E1**, Discovery. Re-extracted {summary["unique_replays"]} unique replays / {summary["seat_records"]} seat records. Top-ranked cohorts contain {len(top)} selected seat records from {len(top_ids)} submissions; selection favors the latest leader games and is not a random sample of all play. V111's 145 underlying episodes are historical. [Input manifest](../data/analysis/research_20260910_final/current_replay_input_manifest.json).

## Mechanics-first hypotheses

Scarcity pricing, diminishing sale prices and the $1 floor make residual Town absorption more important than gross production. Strawberry, Milk and Wool reach the floor with only about 62, 76 and 59 inventory units above the price reference respectively. Land, animal purchases and worker labor commit cash and future service actions; the same crop can be right against one opponent and overproduced against another. These E0 facts predict state-dependent continuation and sale ordering as plausible advantages.

Both players' sells are interleaved one unit at a time within a market slot. At the floor, a committed sale earns money **without adding inventory**. Thus market differences alone cannot reconstruct hidden stock. Town is consumed at its engine schedule. Daily RNG draws depend on empty farm cells before shop selection, so changing our farm can change a future shop even with an identical requested/resolved seed. Paired evaluations retain this consequence and audit its first occurrence.

## Opening and continuation

{table(["Rank", "Seat records", "W/D/L", "Field h48 variants", "Median first land state", "Carrot", "Tomato", "Strawberry", "Cow", "Sheep", "Goose", "Stranded price proxy"], top_table)}

Portfolio columns are day 6–25 means used to describe possible routes, never promotion criteria. Opening actions, first animal/hire/seed/sell times, second/third quadrant timings, action utilization, last investment and liquidation times are retained per episode in [seat metrics](../data/analysis/research_20260910_final/current_episode_seat_metrics.json). Cash, labor, quadrants, crop/animal counts, market inventory/prices, Town daily demand and opponent farms are retained in [daily trajectories](../data/analysis/research_20260910_final/current_daily_trajectories.csv).

The largest identical field-opening h48 group covers **18 submissions and 50 seat records**, but has 50 exact continuation action traces and 15 portfolio signatures. This supports shared opening plus varying continuation, while not distinguishing code changes from reactions to different states. Rank 1 has eight observed opening variants; rank 3 uses a separate opening with Tomato/Goose. Therefore opening convergence is substantial but not universal. Retain V111's coherent early execution for an isolated continuation experiment; do not claim its opening is already optimal.

Fingerprints h24/48/100/200/300/400/600/719 are stored for complete actions and farm actions. Connecting same submission or identical field h48 yields **{len(components)} conservative observed components**, not {len(top_ids)} independent policies and not a verified count of latent action-policy families. Different openings with similar portfolios and exact continuation mismatch can both arise through state-dependent execution; ancestry is unresolved without source.

{table(["Field h48", "Submissions", "Seat records", "Exact continuations", "Portfolio continuations"], opening)}

## Shop event study and opponent dependence

Events are actual newly unlocked shops, with pre-event 24-step asset change and post-event 72-step asset/margin change. Product-demand events are compared with other new-shop events. These windows have overlapping episodes and day/route/opponent confounding. They are descriptive event studies, **not difference-in-differences causal estimates**.

{table(["Cohort", "Product", "New shop demands it", "Event rows", "Pre24 asset Δ", "Post72 asset Δ", "Post72 margin Δ"], event_rows)}

Top Tomato exposure increases after demand unlock while V111 never enters Tomato; Top Sheep growth after Wool demand exceeds growth after other shops. Carrot expansion occurs in both demand and non-demand windows, so attributing all Carrot changes to a new shop is unsupported. No single KPI is a causal explanation for first place.

There are {len(matched_rows)} same-submission/first-three-shop groups with multiple opponent h100 fingerprints. Their portfolios and episode IDs are saved in [opponent-dependence matches](../data/analysis/research_20260910_final/top_lineage_and_opponent_dependence.json). This matching does not hold later shops, market or private state fixed. Opponent dependence is plausible, but a separate opponent-farm intervention is still needed to distinguish reaction from correlated regimes. No reproducible non-transitive payoff cycle was established; mixed opening/PSRO is deferred.

## Market and exact horizon

{table(["Cohort", "Product", "Phase 0 qty", "Phase 1 qty", "Phase 2 qty", "Phase 3 qty"], micro_table)}

Quantities above are requested sales capped by the pre-action shed, **not exact committed quantity or realized revenue**. [Transaction rows](../data/analysis/research_20260910_final/current_sell_microstructure.csv) include product, turn/hour, both players' orders, inventory/price before and after, exposure, and final relative outcome. Those rows are inadequate to attribute win probability to sale phase. The separate supply study uses engine-committed transaction labels on its 24-episode subset.

V111's mean stranded private stock has a 264.7-coin observed-price proxy; leader rank 1 averages 80.8 and several other Top cohorts zero. Field yield is separately retained and is not liquid inventory. Investment stop, last crop planting and last sell vary by product; the actual last action t718 precedes any day-30 auto-deposit. This motivates H2, but its upside is too small to explain the observed 10k–20k losses alone.

## Executable opponents and meta weights

Four full published policies were acquired and completed both-seat 720-state games: [mooman](https://github.com/mooman0222/Kaggriculture-opencode), [souvik](https://github.com/Souvik6222/Kaggriculture), [ggmljs](https://github.com/ggmljs/Kaggriculture), [qeinstein](https://github.com/qeinstein/kaggriculture). Exact commits, source hashes, entrypoints and archive hashes are in the [source registry](../experiments/research_20260910/source_registry.json). Mooman must execute `agent_entry`, not its underlying `agent`; the adapter preserves that public entrypoint. These are Gold for executable closed-loop tests, not proof of a claimed public score.

Mooman/souvik overlap PSR ancestry, and mooman/ggmljs overlap Kaito ancestry. Conservatively merge those three; qeinstein is a second acquired ancestry group. Top replay-only policies remain Bronze. The new forecast is a predictor, not a validated Silver opponent. Current opening frequencies above describe the selected Top snapshot; the Gold source frequency in the live field is **unidentified**. Equal-source and equal-ancestry weighting are explicit stress scenarios, not estimated current-meta weights.
"""
    (DOCS / "current_meta_analysis_20260910.md").write_text(meta, encoding="utf-8")

    champion = summary["champion"]
    rating_rows = [
        [key, data["n"], wdl(data["wdl"]), f"{data['mean_margin']:.1f}", data["p10_margin"]]
        for key, data in sorted(summary["champion_by_rating"].items())
    ]
    family_rows = [
        [key, data["n"], wdl(data["wdl"]), f"{data['mean_margin']:.1f}"]
        for key, data in sorted(summary["champion_by_opponent_field_h48"].items(), key=lambda x: -x[1]["n"])
    ]
    town_rows = [
        [key, data["n"], wdl(data["wdl"]), f"{data['mean_margin']:.1f}"]
        for key, data in sorted(summary["champion_by_town"].items(), key=lambda x: -x[1]["n"])[:30]
    ]
    champion_rows = [r for r in rows if r["cohort"] == "champion_v111"]
    check_rows = [
        [day, f"{mean(r['checkpoint_margins'][day] for r in champion_rows):.1f}", champion["lead_to_loss"][day]]
        for day in ("day12", "day18", "day20", "day24")
    ]
    losses = sorted([r for r in champion_rows if r["result"] == "loss"], key=lambda r: abs(r["final_margin"]))
    loss_rows = [
        [
            r["episode_id"],
            r["seat"],
            r["opponent_submission_id"],
            r["opponent_field_hashes"]["100"],
            r["checkpoint_margins"]["day18"],
            r["final_margin"],
        ]
        for r in losses[:20]
    ]
    weakness = f"""# Champion weakness map — 2026-09-10

The frozen Champion is V111. This map was recomputed from downloaded/cached raw replays rather than copied from old reports. However, **the V111 episodes themselves end September 1**. No newer identifiable V111 live games were available. The latest unmapped submission cannot be substituted. Fresh current-field challenge evidence comes from the new reacting executable opponents, separately reported below.

The historical sample is **95W/4D/48L**, 147 seat records / 145 unique episodes; the two self-play duplicate seats are not independent games. Mean margin 7696.5, P10 margin -10756. The 65.99% win-score is selection-dependent and is not a current rating estimate.

{table(["Day checkpoint", "Mean margin", "Lead → final loss"], check_rows)}

{table(["Loss flag (overlapping, not causal)", "Count"], list(champion["loss_flags"].items()))}

All 48 losses are tagged premium congestion, Milk-heavy and Strawberry-heavy. These are common background exposures, **not 48 proven market-timing failures**. Wool-heavy 14, near-clone portfolio distance ≤5 in 13, same field h48 in 17, unusual Tomato/Carrot in 1. Close losses (within 5000 coin) number 16; rating upset losses by a ≥200 initial-rating gap number 0. Market-timing causality is unidentified from one factual replay.

## Rating, opening-family and Town breakdowns

Rating bins are floored to 250-point boundaries; missing initial ratings remain a separate bin.

{table(["Opponent rating bin", "n", "W/D/L", "Mean margin", "P10 margin"], rating_rows)}

{table(["Opponent field h48", "n", "W/D/L", "Mean margin"], family_rows)}

{table(["Town signature (largest 30)", "n", "W/D/L", "Mean margin"], town_rows)}

Complete h100/h200 and Town breakdowns, rather than only the displayed large groups, are in [machine-readable summary](../data/analysis/research_20260910_final/current_meta_weakness_summary.json). Fingerprints are trajectory groups, not independent latent code lineages.

## Closest losses and current challenge sensitivity

{table(["Episode", "Seat", "Opponent submission", "Opponent field h100", "Day18 margin", "Final margin"], loss_rows)}

New current public source probes: mooman 0W/8L, souvik 2W/6L, ggmljs 8W/0L, qeinstein 0W/8L (four seeds × both seats). This falsifies the usefulness of the old near-all-winning Gold pool as the only improvement screen. It also exposes an unresolved problem: none of the conservatively independent groups is yet well established as a 30–70% matchup. Souvik is 25% on four seeds and shares ancestry. More seeds and more distinct strong source acquisitions are needed before precise promotion inference.

## Mechanism map

1. **Limited middle-game routes (E0/E1):** three route backbones; all new plants on days 15–24 are Wheat. This is a structural constraint, although portfolio diversity itself is not the objective.
2. **Shared-market congestion (E0/E1):** substantial opposing premium exposure and steep price collapse. Cow→Sheep is not automatically beneficial when both farms saturate Wool. Relative revenue and Town absorption must be considered jointly.
3. **Continuation/execution coupling (E0):** new portfolios require different harvest, feed, movement and deposit actions. Replacing purchases alone can create weeds/no-ops and change future Town RNG.
4. **Late loss recovery (E1):** 17 Day18 leads become losses; only four Day24 leads do. This prioritizes middle-game investigation over terminal tweaks as the largest prospective gap.
5. **Terminal stranded stock (E0/E1):** small and actionable, but 264.7 coin average cannot by itself close common 10k–20k current-source deficits.
6. **Opponent stock estimation (E2 predictive only):** public farm features support better stock/supply estimates, but broad-horizon any-sale probability is often nearly one and is not an effective sale-timing gate.

The largest supported **structural** gap is a narrow continuation library coupled to imperfect future-market estimates. The largest **causal** source of the leader's win advantage remains unidentified; neither mean coin, diversity nor leader imitation establishes it. The ranked interventions and new paired results determine what can be retained.
"""
    (DOCS / "champion_weakness_map_20260910.md").write_text(weakness, encoding="utf-8")
    print("Wrote current_state, current_meta_analysis, champion_weakness_map", flush=True)


def dashboard(version, phase):
    from scripts.evaluation.statistics import (
        bradley_terry_diagnostic,
        hierarchical_bootstrap,
        pairwise_payoff_matrix,
        robust_meta,
        summarize_pairs,
    )

    path = EVAL / version / phase
    rows = [json.loads(line) for line in (path / "pairs.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(rows) != 32 and phase == "development":
        raise SystemExit(f"Incomplete development panel: {len(rows)}/32")
    matrix = pairwise_payoff_matrix(rows, 2000, 20260910)
    weights = {r["lineage_id"]: 1 / len(matrix) for r in matrix}
    merged = []
    for row in rows:
        family = "qeinstein" if row["lineage_id"] == "qeinstein_moev2" else "overlapping_PSR_Kaito"
        merged.append({**row, "lineage_id": family, "meta_weight": 0.5})
    merged_matrix = pairwise_payoff_matrix(merged, 2000, 20260910)
    safety_counts = Counter(key for r in rows for key in r["candidate_new_major_regressions"])
    isolation = sum(not r["behavioral_isolation_valid"] for r in rows)
    summary = summarize_pairs(rows)
    reasons = []
    if safety_counts:
        reasons.append("safety_regression")
    if isolation:
        reasons.append("unexpected_divergence")
    if summary["loss_to_win"] <= summary["win_to_loss"]:
        reasons.append("no_net_loss_to_win_uplift")
    if len(merged_matrix) < 3:
        reasons.append("insufficient_independent_opponent_diversity")
    decision = "REJECT" if safety_counts or isolation or summary["score_worsened"] else "PROMISING_UNPROVEN"
    if not summary["incremental_treatments"]:
        reasons.append("treatment_delivery_failure_no_incremental_action")
        decision = "REJECT"
    result = {
        "version": version,
        "phase": phase,
        "evidence_level": "E3 development screen; not E4/E5",
        "decision": decision,
        "reasons": reasons,
        "summary": summary,
        "source_payoff_matrix": matrix,
        "conservative_ancestry_matrix": merged_matrix,
        "source_equal_weight_scenario": hierarchical_bootstrap(rows, weights, 2000, 20260910),
        "ancestry_equal_weight_scenario": hierarchical_bootstrap(
            merged, {r["lineage_id"]: 0.5 for r in merged_matrix}, 2000, 20260910
        ),
        "robust_source_reweighting": robust_meta(matrix, weights, 0.2),
        "robust_ancestry_reweighting": robust_meta(merged_matrix, {r["lineage_id"]: 0.5 for r in merged_matrix}, 0.2),
        "bradley_terry_diagnostic": bradley_terry_diagnostic(rows),
        "meta_weight_warning": "Live source frequencies unidentified. Equal-source and equal-ancestry are assumptions, not estimated current meta.",
        "safety_failure_pair_counts": dict(safety_counts),
        "unexpected_divergence_pairs": isolation,
        "draw_to_win": sum(r["control"]["result"] == "draw" and r["treatment"]["result"] == "win" for r in rows),
        "win_to_draw": sum(r["control"]["result"] == "win" and r["treatment"]["result"] == "draw" for r in rows),
        "p10_margin": {arm: quantile([r[arm]["margin"] for r in rows], 0.1) for arm in ("control", "treatment")},
        "fresh_holdout": "UNUSED; earlier gates did not establish promotion eligibility",
    }
    save(path / "promotion_dashboard.json", result)
    save(
        path / "first_divergence_audits.json",
        [
            {"source": r["lineage_id"], "seed": r["seed"], "seat": r["seat"], "audit": r["divergence_audit"]}
            for r in rows
        ],
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("decision", "reasons", "summary", "safety_failure_pair_counts", "unexpected_divergence_pairs")
            },
            indent=2,
        )
    )


def preservation():
    audit = read(ROOT / "experiments/research_20260909/initial_repository_audit.json")
    changed, missing = [], []
    for name, value in audit["tracked_file_hashes"].items():
        path = ROOT / name
        if not path.exists():
            missing.append(name)
        elif digest(path) != value["sha256"]:
            changed.append(name)
    spec = read(EXPERIMENT / "v114_preregistration.json")
    framework_changes = [name for name, expected in spec["framework_hashes"].items() if digest(ROOT / name) != expected]
    result = {
        "initial_tracked_files": len(audit["tracked_file_hashes"]),
        "changed": changed,
        "missing": missing,
        "frozen_v114_framework_changes": framework_changes,
        "v111_archive_unchanged": digest(ROOT / "artifacts/submissions/v111.tar.gz")
        == audit["version_identities"]["v111"]["archive_sha256"],
        "v114_archive_matches_frozen": digest(ROOT / spec["archive"]) == spec["archive_sha256"],
    }
    save(EXPERIMENT / "final_preservation_audit.json", result)
    print(json.dumps(result, indent=2))


def adjudicate(version):
    """Retain raw flags and audit the inherited V111 purchase at its actual t248."""
    import gzip

    from scripts.evaluation.safety import analyze_safety

    directory = EVAL / version / "development"
    rows = [json.loads(line) for line in (directory / "pairs.jsonl").read_text(encoding="utf-8").splitlines()]
    details = []
    corrected = Counter()
    for row in rows:
        flags = list(row["candidate_new_major_regressions"])
        if "transaction_incomplete" in flags:
            audited = {}
            for arm in ("control", "treatment"):
                with gzip.open(row["replay_artifacts"][arm], "rt", encoding="utf-8") as handle:
                    replay = json.load(handle)
                audited[arm] = analyze_safety(replay, row["seat"], row["agent_trace"][arm], transaction_step=248)[
                    "transaction"
                ]
            false_flag = audited["treatment"]["complete"]
            if false_flag:
                flags.remove("transaction_incomplete")
            details.append(
                {
                    "source": row["lineage_id"],
                    "seed": row["seed"],
                    "seat": row["seat"],
                    "raw_transaction_step": 153,
                    "actual_inherited_transaction_step": 248,
                    "engine_audit": audited,
                    "raw_flag_is_checkpoint_measurement_error": false_flag,
                }
            )
        corrected.update(flags)
    total = {}
    for arm in ("control", "treatment"):
        safety = [r["safety"][arm] for r in rows]
        total[arm] = {
            "runtime_failure_records": sum(len(s["runtime_failures"]) for s in safety),
            "incomplete_games": sum(not s["completed_720"] for s in safety),
            "negative_cash_games": sum(s["minimum_cash"] < 0 for s in safety),
            "animal_loss_total": sum(s["animal_loss_total"] for s in safety),
            "plant_to_weed": sum(s["plant_to_weed"] for s in safety),
            "spawned_weeds": sum(s["spawned_weeds"] for s in safety),
            "engine_action_audit": dict(sum((Counter(s["engine_action_audit"]) for s in safety), Counter())),
        }
    payload = {
        "reason": "Route intervention at t153 does not move V111's inherited Cow-to-Sheep purchase from t248. Raw records are retained; recomputation audits actual engine-committed transaction units.",
        "details": details,
        "adjudicated_candidate_new_failure_pair_counts": dict(corrected),
        "arm_safety_totals": total,
        "promotion_consequence": "None: candidate remains rejected for no causal uplift/delivery or other failed gates; no threshold changed.",
    }
    save(directory / "transaction_checkpoint_adjudication.json", payload)
    print(
        json.dumps(
            {
                "adjudicated_failures": dict(corrected),
                "measurement_errors": sum(r["raw_flag_is_checkpoint_measurement_error"] for r in details),
                "safety": total,
            },
            indent=2,
        )
    )


def latest():
    snapshot = read(ROOT / "data/current_field_20260910/leaderboard_refresh_20260911.json")
    teams = {row["teamId"]: row for row in snapshot["data"]["teams"]}
    leaderboard = snapshot["data"]["publicLeaderboard"]
    old = read(ROOT / "data/current_field_20260910/leaderboard.json")["data"]["publicLeaderboard"]
    overlap = len({r["submissionId"] for r in leaderboard[:30]} & {r["submissionId"] for r in old[:30]})
    values = [
        [
            r["rank"],
            teams[r["teamId"]]["teamName"],
            r["teamId"],
            r["submissionId"],
            r["displayScore"],
            teams[r["teamId"]].get("lastSubmissionDate", "unknown"),
        ]
        for r in leaderboard[:30]
    ]
    text = f"""# Current state refresh — 2026-09-11

At **{snapshot["fetched_at"]}**, the leader remained **SpaTaro**, same submission `56114097`, now **3136.2**. The September 10 research snapshot had 3062.4. [Official leaderboard](https://www.kaggle.com/competitions/kaggriculture/leaderboard); [new raw API snapshot](../data/current_field_20260910/leaderboard_refresh_20260911.json).

{table(["Rank", "Team", "Team ID", "Submission", "Rating", "Team last submission UTC"], values)}

Only **{overlap}/30** active Top30 submission IDs overlap the September 10 snapshot. The detailed replay/meta analysis applies to the September 10 field and has not been silently relabeled September 11 evidence. Leader #1's submission is unchanged, but rank 2/3 and other rows have changed. This limits any current-meta weighting claim and further argues against promotion from a narrow old source pool.

Champion source/archive identity and engine details remain in [the full September 10 audit](current_state_20260910.md). A new factual-observation fidelity check of our latest submission `56089444` matched 712/719 actions for both local V111 and V113, first mismatch t349; previous `55941525` matched 715/719, first mismatch t378. Thus a near-relative is plausible, but exact remote artifact identity remains **unverified**. The replay check is not an authenticated archive hash and cannot establish which source was submitted. [Fidelity audit](../experiments/research_20260910/latest_submission_action_fidelity.json).

The local Champion remains V111. V114 had a checkpoint configuration bug; V114r1 fixes that bug but produced zero interventions and zero paired win improvement. A forced-delivery ablation investigates route feasibility separately. The final report records its result. No Kaggle submission or Champion registry promotion was made.
"""
    (DOCS / "current_state_20260911.md").write_text(text, encoding="utf-8")
    print("Wrote latest snapshot addendum", flush=True)


def economy():
    import gzip

    from scripts.evaluation.replay import observation

    probe_path = EVAL / "v114probe/development"
    rows = [json.loads(line) for line in (probe_path / "pairs.jsonl").read_text(encoding="utf-8").splitlines()]
    inactive = [
        json.loads(line)
        for line in (EVAL / "development_inactive_controls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    inactive_paths = {(r["candidate_id"], r["requested_seed"], r["seat"]): r["replay_path"] for r in inactive}
    assert len(rows) == 32 and len(inactive) == 8
    records = []
    for row in rows:
        key = (row["lineage_id"], row["seed"], row["seat"])
        arms = {}
        for arm in ("control", "treatment"):
            replay_path = row["replay_artifacts"].get(arm) or inactive_paths.get(key)
            assert replay_path, f"Missing replay for economy diagnostics: {key}"
            with gzip.open(replay_path, "rt", encoding="utf-8") as handle:
                replay = json.load(handle)
            seat = row["seat"]
            final = observation(replay, 719, seat)
            assert final["farms"][seat]["money"] == row[arm]["ours"]
            assert final["farms"][1 - seat]["money"] == row[arm]["theirs"]
            private = final["private"]
            stock = {
                item: sum(int(inv.get(item, 0)) for inv in [private.get("shed", {}), *private.get("inventories", [])])
                for item in final["market"]["prices"]
            }
            checkpoints = {}
            for step in (288, 432, 480, 576):
                obs = observation(replay, step, seat)
                checkpoints[f"day{step // 24}"] = obs["farms"][seat]["money"] - obs["farms"][1 - seat]["money"]
            arms[arm] = {
                "checkpoint_margins": checkpoints,
                "lead_to_loss": {
                    day: margin > 0 and row[arm]["result"] == "loss" for day, margin in checkpoints.items()
                },
                "stranded_inventory": stock,
                "stranded_observed_price_proxy": sum(stock[item] * final["market"]["prices"][item] for item in stock),
            }
        records.append({"source": key[0], "seed": key[1], "seat": key[2], **arms})
    summaries = {}
    for arm in ("control", "treatment"):
        summaries[arm] = {
            "lead_to_loss": {
                day: sum(r[arm]["lead_to_loss"][day] for r in records) for day in ("day12", "day18", "day20", "day24")
            },
            "mean_stranded_price_proxy": mean(r[arm]["stranded_observed_price_proxy"] for r in records),
            "stranded_units_by_product": {
                item: sum(r[arm]["stranded_inventory"][item] for r in records)
                for item in records[0][arm]["stranded_inventory"]
            },
        }
    save(
        probe_path / "economy_diagnostics.json",
        {
            "summary": summaries,
            "rows": records,
            "stranded_warning": "Final observed-price proxy, not attainable liquidation revenue or score.",
        },
    )
    r1_records = [{**r, "treatment": r["control"]} for r in records]
    save(
        EVAL / "v114r1/development/economy_diagnostics.json",
        {
            "summary": {"control": summaries["control"], "treatment": summaries["control"]},
            "rows": r1_records,
            "method": "V114r1 full paired actions/states were identical to V111; controls cross-checked against stored probe or separately repeated inactive controls with exact final-coin equality.",
        },
    )
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["describe", "dashboard", "preservation", "adjudicate", "latest", "economy"])
    parser.add_argument("--version", default="v114")
    parser.add_argument("--phase", default="development")
    arguments = parser.parse_args()
    if arguments.command == "describe":
        describe()
    elif arguments.command == "dashboard":
        dashboard(arguments.version, arguments.phase)
    elif arguments.command == "adjudicate":
        adjudicate(arguments.version)
    elif arguments.command == "latest":
        latest()
    elif arguments.command == "economy":
        economy()
    else:
        preservation()
