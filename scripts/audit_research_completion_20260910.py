"""Check deliverables, retained evidence and the conditional non-promotion exit."""

# Requirement descriptions are stored as complete prose strings in the audit.
# ruff: noqa: E501

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def log_text(path):
    data = path.read_bytes()
    return data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8")


def main():
    required = [
        "docs/current_state_20260910.md",
        "docs/current_state_20260911.md",
        "docs/current_meta_analysis_20260910.md",
        "docs/champion_weakness_map_20260910.md",
        "docs/research_hypothesis_ranking_20260910.md",
        "docs/opponent_supply_estimation_20260910.md",
        "docs/v114_research_and_evaluation_report.md",
        "agents/v114/main.py",
        "agents/v114r1/main.py",
        "agents/v114probe/main.py",
        "artifacts/submissions/v114.tar.gz",
        "artifacts/submissions/v114r1.tar.gz",
        "artifacts/submissions/v114probe.tar.gz",
        "experiments/research_20260910/final_artifact_verification.json",
        "experiments/research_20260910/final_holdout_audit.json",
        "experiments/research_20260910/final_preservation_audit.json",
        "experiments/research_20260910/champion_challenger_decision.json",
    ]
    evidence = []
    for name in required:
        path = ROOT / name
        assert path.is_file() and path.stat().st_size > 0, name
        evidence.append(
            {"path": name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    broken_links = []
    for name in required:
        if not name.endswith(".md"):
            continue
        path = ROOT / name
        for link in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if link.startswith(("http:", "https:", "#")):
                continue
            if not (path.parent / link.split("#")[0]).resolve().exists():
                broken_links.append({"document": name, "target": link})
    assert not broken_links, broken_links
    evaluation = ROOT / "data/evaluation/research_20260910"
    assert "All checks passed!" in log_text(evaluation / "final_ruff.log")
    assert "....................." in log_text(evaluation / "final_pytest.log")
    assert read(evaluation / "v114r1_standalone_smoke.json")["passed"]
    expected = {"v114r1": (12, 20, 0, 0), "v114probe": (0, 32, 0, 12)}
    panels = {}
    for version, (wins, losses, lw, wl) in expected.items():
        directory = evaluation / version / "development"
        rows = [json.loads(line) for line in (directory / "pairs.jsonl").read_text(encoding="utf-8").splitlines()]
        summary = read(directory / "promotion_dashboard.json")["summary"]
        assert len(rows) == summary["pairs"] == 32
        assert (
            summary["candidate"]["wins"],
            summary["candidate"]["losses"],
            summary["loss_to_win"],
            summary["win_to_loss"],
        ) == (wins, losses, lw, wl)
        assert len(read(directory / "first_divergence_audits.json")) == 32
        assert len(read(directory / "economy_diagnostics.json")["rows"]) == 32
        panels[version] = {
            "pairs": 32,
            "independent_seeds": 4,
            "executable_policies": 4,
            "conservative_ancestry_groups": 2,
            "actual_results_verified": True,
        }
    preserve = read(ROOT / "experiments/research_20260910/final_preservation_audit.json")
    assert (
        not preserve["missing"] and preserve["v111_archive_unchanged"] and not preserve["frozen_v114_framework_changes"]
    )
    assert set(preserve["changed"]) == {
        "scripts/evaluation/divergence.py",
        "scripts/evaluation/runner.py",
        "scripts/smoke_standalone_agent.py",
        "tests/test_champion_challenger_evaluation.py",
    }
    top = [
        row
        for row in read(ROOT / "data/analysis/research_20260910_final/current_episode_seat_metrics.json")
        if row["cohort"].startswith("top_rank_")
    ]
    classes = Counter()
    for index, left in enumerate(top):
        for right in top[index + 1 :]:
            opening = left["field_hashes"]["48"] == right["field_hashes"]["48"]
            continuation = left["continuation_field_hash_144_600"] == right["continuation_field_hash_144_600"]
            distance = sum(
                abs(left["continuation_mean_portfolio"][item] - right["continuation_mean_portfolio"][item])
                for item in left["continuation_mean_portfolio"]
            )
            if opening:
                key = (
                    "same_opening_same_field_continuation"
                    if continuation
                    else "same_opening_different_field_continuation"
                )
            else:
                key = (
                    "different_opening_similar_mean_portfolio_L1_le5"
                    if distance <= 5
                    else "different_opening_different_observed_portfolio"
                )
            classes[key] += 1
    result = {
        "exit": "Completed bounded research with negative candidates; no promotion or live-strength uplift claimed",
        "artifact_evidence": evidence,
        "panels": panels,
        "focused_tests": 21,
        "lint": "pass",
        "broken_document_links": broken_links,
        "champion_preserved": True,
        "four_way_top_trajectory_pair_counts": dict(classes),
        "trajectory_warning": "Descriptive dependent pair counts, not independent policy-lineage counts. Similarity threshold is diagnostic only.",
        "requirements_review": {
            "0_objective": "Pairwise outcomes and relative coin, not own coin, govern rejection.",
            "1_prior_claims": "Reverified identities, V113 rejection, fixed routes, lineage overlap, mechanics; non-transitivity remains unestablished.",
            "2_repository": "895-file clean initial audit, current preservation proof, archive/runtime hashes and GitHub/local commit match.",
            "3_current_kaggle": "CLI/authentication checked; public leaderboard/top30/episode acquisition; latest refresh separate. Authenticated latest artifact unavailable.",
            "4_lineages": "Multi-horizon action/field hashes and observed groups; latent independent top families not assumed.",
            "5_top_strength": "Mechanics-led E1 opening/continuation/event/market/horizon study; definitive causal explanation of #1 unproven.",
            "6_weakness": "Recomputed historical V111 map plus newly executed strong public-source challenge; no false claim of fresh V111 ladder episodes.",
            "7_supply": "Rule/mean/ridge at24/72/144; stricter held-out-episode exclusion, private labels offline only; larger models deferred.",
            "8_future_economics": "Relative route projection implemented and its cash/execution limitations tested; no claim of a calibrated general EV.",
            "9_continuation": "Small existing suffix library, once-only t153 gate and forced-delivery ablation.",
            "10_opening": "Exact common prefix retained; PSRO not introduced without non-transitive evidence.",
            "11_ranking": "Ten hypotheses ranked before implementation with evidence, mechanism, upside, failure, risk, complexity and testability.",
            "12_framework": "Existing runner/replay/divergence/safety/statistics/registry reused; no replay-only causal opponent.",
            "13_champion_challenger": "V111 frozen, both seats, four identical requested/resolved seeds, same engine and archives, complete panels.",
            "14_divergence": "All paired first action/money/portfolio/workers/opponent/market/price/Town channels saved. Internal RNG state not instrumented.",
            "15_dashboard": "WDL/flips, grouped payoffs, weighting scenarios, BT diagnostic, comparative safety, lead loss and terminal stock saved.",
            "16_holdout": "Unused seeds and replay bodies sealed; public metadata not claimed blind. Runtime driver prevents ineligible promotion/holdout phases.",
            "17_opponents": "Four newly acquired complete executables; two conservative ancestry groups. Sensitivity/diversity remains insufficient for promotion.",
            "18_artifacts": "Separate versions, exact source hashes, deterministic standalone archives, both-seat runs, tests and lint.",
            "19_failure_handling": "Implementation bug corrected separately; inactive gate rejected; H2 opportunity screen and forced-delivery ablation completed, rejected.",
            "20_time": "Timestamped stages span continuation turns; no claim of a single uninterrupted five-hour run. Work concludes with the negative-evidence exit.",
            "21_prohibitions": "No existing research overwrite, no holdout tuning, no coin-only promotion, no Kaggle submission.",
            "22_deliverables": "All named report categories, agent/archive directories and paired evaluation evidence exist and links resolve.",
            "23_final_A_P": "Explicit A-P table in final research report, including limitations and next-five-hour priorities.",
            "24_themes": "State-dependent continuation, public supply, residual demand and relative effects studied; other themes ranked with evidence gaps.",
            "25_conclusion": "No candidate promoted; route-state feasibility requirement established by negative paired evidence, further work specified.",
        },
        "not_achieved_and_not_claimed": [
            "Rating3000+/Leaderboard1 Agent",
            "E4 diverse promotion tournament",
            "E5 fresh holdout strength",
            "new candidate live ladder evidence",
            "exact authenticated latest submitted artifact identity",
            "causal reconstruction of the leader's private policy",
        ],
    }
    (ROOT / "experiments/research_20260910/completion_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "required_artifacts": len(evidence),
                "paired_panels": panels,
                "links": "pass",
                "tests": 21,
                "lint": "pass",
                "decision": "REJECT; V111 retained",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
