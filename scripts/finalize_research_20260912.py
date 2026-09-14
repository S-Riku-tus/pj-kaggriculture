"""Synthesize continuation research into auditable decision artifacts; no submission."""

# ruff: noqa: E402, E501

from __future__ import annotations

import gzip
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluation.replay import observation

OUT = ROOT / "experiments/research_20260911_continuations"
EVAL = ROOT / "data/evaluation/research_20260911_continuations"
OLD_EVAL = ROOT / "data/evaluation/research_20260910"

VERSIONS = (
    "v115p_immediate",
    "v115p_town",
    "v115p_livestock",
    "v115p_retain_cow",
    "v115p_retain_cow_r1",
    "v115p_managed_sheep",
    "v115p_managed_goose",
)
INVALID_BY_DESIGN = {"v115p_retain_cow"}
LABELS = {
    "v115p_immediate": "在庫即時売却",
    "v115p_town": "Town更新時売却",
    "v115p_livestock": "非管理Sheep強制",
    "v115p_retain_cow": "Cow保持（区間設定不正）",
    "v115p_retain_cow_r1": "Cow保持r1",
    "v115p_managed_sheep": "管理付きSheep",
    "v115p_managed_goose": "管理付きGoose",
}


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def md_table(headers, body):
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *["| " + " | ".join(str(v).replace("|", "/") for v in line) + " |" for line in body],
    ])


def seed_block_ci(pair_rows, repetitions=5000):
    grouped = defaultdict(list)
    for row in pair_rows:
        grouped[row["seed"]].append(float(row["delta_win_score"]))
    means = [statistics.mean(values) for values in grouped.values()]
    rng = random.Random(20260912)
    samples = sorted(statistics.mean(rng.choices(means, k=len(means))) for _ in range(repetitions))
    return {
        "estimate": statistics.mean(means),
        "low_95": samples[int(0.025 * repetitions)],
        "high_95": samples[int(0.975 * repetitions)],
        "independent_seed_blocks": len(means),
        "method": "whole-seed bootstrap; both seats and all lineages move together",
    }


def percentile10(values):
    ordered = sorted(values)
    return ordered[math.floor(0.1 * (len(ordered) - 1))]


def replay_economy(pair_rows):
    arms = {"control": [], "treatment": []}
    for row in pair_rows:
        for arm in arms:
            replay_path = Path(row["replay_artifacts"][arm])
            with gzip.open(replay_path, "rt", encoding="utf-8") as handle:
                replay = json.load(handle)
            seat = row["seat"]
            final = observation(replay, 719, seat)
            private = final["private"]
            items = list(final["market"]["prices"])
            stock = {
                item: sum(int(inv.get(item, 0) or 0) for inv in [private.get("shed", {}), *private.get("inventories", [])])
                for item in items
            }
            checkpoints = {}
            for step in (288, 432, 480, 576):
                obs = observation(replay, step, seat)
                checkpoints[f"day{step // 24}"] = float(obs["farms"][seat]["money"] - obs["farms"][1 - seat]["money"])
            arms[arm].append({
                "margin": float(row[arm]["margin"]),
                "lead_to_loss": {key: value > 0 and row[arm]["result"] == "loss" for key, value in checkpoints.items()},
                "stranded_inventory": stock,
                "stranded_observed_price_proxy": sum(stock[item] * float(final["market"]["prices"][item]) for item in stock),
            })
    result = {}
    for arm, records in arms.items():
        result[arm] = {
            "p10_margin": percentile10([record["margin"] for record in records]),
            "lead_to_loss": {key: sum(record["lead_to_loss"][key] for record in records) for key in records[0]["lead_to_loss"]},
            "mean_terminal_stranded_observed_price_proxy": statistics.mean(record["stranded_observed_price_proxy"] for record in records),
            "terminal_stranded_units": {
                item: sum(record["stranded_inventory"][item] for record in records)
                for item in records[0]["stranded_inventory"]
            },
        }
    result["warning"] = "Observed final-price proxy, not attainable liquidation revenue and not score."
    return result


def adjudication(version, summary, pair_rows):
    invalid = int(summary["invalid"])
    safety = int(summary["hard_safety_pairs"])
    l2w = int(summary["summary"]["loss_to_win"])
    w2l = int(summary["summary"]["win_to_loss"])
    if version in INVALID_BY_DESIGN or invalid:
        return "INVALID_EVALUATION_CONFIGURATION"
    if safety:
        return "REJECT_SAFETY_REGRESSION"
    if l2w == 0:
        return (
            "REJECT_NO_CAUSAL_UPLIFT_WITH_WIN_REGRESSION"
            if w2l
            else "REJECT_NO_CAUSAL_UPLIFT"
        )
    if l2w <= w2l:
        return "REJECT_NO_NET_WIN_UPLIFT"
    flip_sources = {row["lineage_id"] for row in pair_rows if row["loss_to_win"] and not row["candidate_new_major_regressions"]}
    flip_seeds = {row["seed"] for row in pair_rows if row["loss_to_win"] and not row["candidate_new_major_regressions"]}
    if len(flip_sources) < 2 or len(flip_seeds) < 2:
        return "PROMISING_UNPROVEN_SINGLE_CONTEXT"
    return "PROMISING_UNPROVEN_REQUIRES_SELECTOR_E4_E5"


def engine_backed_treatment(version, row):
    if not row["incremental_treatment"] or not row["behavioral_isolation_valid"]:
        return False
    if row["candidate_incident_classification"]["treatment_delivery_failure"]:
        return False
    decision = row["agent_trace"]["treatment"].get("research_decision", {})
    if version.startswith("v115p_managed_"):
        return bool(decision.get("purchase_confirmed")) and int(decision.get("placement_confirmed", 0)) >= 2
    if version == "v115p_livestock":
        transaction = row["safety"]["treatment"]["transaction"]
        return bool(transaction["complete"]) and int(transaction["purchase_units_committed"]) >= 2
    return row["divergence_audit"].get("first_public_observation_divergence_step") is not None


def operational_summary(pair_rows):
    def safety(row, arm):
        return row["safety"][arm]

    def audit(row, arm, key):
        return int(safety(row, arm).get("engine_action_audit", {}).get(key, 0))

    def positive_audit_delta(row, key):
        return max(0, audit(row, "treatment", key) - audit(row, "control", key))

    return {
        "incomplete_pairs": sum(not safety(row, "treatment")["completed_720"] for row in pair_rows),
        "runtime_failure_events": sum(
            len(safety(row, "treatment")["runtime_failures"]) for row in pair_rows
        ),
        "unexpected_divergence_pairs": sum(
            not row["behavioral_isolation_valid"] for row in pair_rows
        ),
        "transaction_incomplete_pairs": sum(
            not safety(row, "treatment")["transaction"]["complete"] for row in pair_rows
        ),
        "new_silent_field_noop": sum(
            positive_audit_delta(row, "silent_field_noop") for row in pair_rows
        ),
        "new_silent_market_noop": sum(
            positive_audit_delta(row, "silent_market_noop") for row in pair_rows
        ),
        "new_failed_required_purchase": sum(
            positive_audit_delta(row, "failed_required_purchase") for row in pair_rows
        ),
        "animal_loss_delta": sum(
            safety(row, "treatment")["animal_loss_total"]
            - safety(row, "control")["animal_loss_total"]
            for row in pair_rows
        ),
        "plant_to_weed_delta": sum(
            safety(row, "treatment")["plant_to_weed"]
            - safety(row, "control")["plant_to_weed"]
            for row in pair_rows
        ),
        "spawned_weed_delta": sum(
            safety(row, "treatment")["spawned_weeds"]
            - safety(row, "control")["spawned_weeds"]
            for row in pair_rows
        ),
        "negative_cash_pairs": sum(
            safety(row, "treatment")["minimum_cash"] < 0 for row in pair_rows
        ),
    }


def main():
    champion_source = ROOT / "agents/v111/main.py"
    champion_archive = ROOT / "experiments/research_20260910/champion_v111.tar.gz"
    engine = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
    identity = {"source_sha256": sha(champion_source), "archive_sha256": sha(champion_archive), "engine_sha256": sha(engine)}
    assert identity == {
        "source_sha256": "699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660",
        "archive_sha256": "85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e",
        "engine_sha256": "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e",
    }

    latest_dir = sorted(path for path in (OUT / "remote").iterdir() if path.is_dir())[-1]
    leaderboard = read(latest_dir / "leaderboard.json")
    top = leaderboard["data"]["publicLeaderboard"][0]
    team = next((row for row in leaderboard["data"].get("teams", []) if row.get("teamId") == top["teamId"]), {})
    current_leader = {
        "fetched_at": leaderboard["fetched_at"], "rank": top["rank"], "rating": float(top["displayScore"]),
        "submission_id": top["submissionId"], "team_id": top["teamId"], "team_name": team.get("teamName", "unknown"),
        "source": str((latest_dir / "leaderboard.json").relative_to(ROOT)),
    }
    our_remote = read(latest_dir / "our_team.json")
    our_submissions = [
        {
            "submission_id": row["id"],
            "submitted_at": row["dateSubmitted"],
            "current_public_rating": float(row["publicScoreFormatted"]),
            "artifact_identity": "unknown",
        }
        for row in our_remote["data"]["submissions"]
    ]

    prereg_files = sorted(OUT.glob("*preregistration.json"))
    verification = []
    for prereg_path in prereg_files:
        prereg = read(prereg_path)
        framework_mismatches = [
            name
            for name, expected in prereg.get("framework_hashes", {}).items()
            if sha(ROOT / name) != expected
        ]
        evaluation_core_mismatches = [
            name for name in framework_mismatches if not name.endswith("evaluation\\lifecycle.py")
        ]
        assert not evaluation_core_mismatches
        for variant in prereg.get("variants", []):
            archive = ROOT / variant["archive"]
            runtime = (ROOT / variant["runtime"]).parent
            standalone_path = OUT / f"{variant['version']}_standalone.json"
            standalone_passed = standalone_path.exists() and bool(read(standalone_path).get("passed"))
            archive_ok = sha(archive) == variant["archive_sha256"]
            runtime_ok = all(sha(runtime / name) == expected for name, expected in variant["source_hashes"].items())
            verification.append({
                "version": variant["version"], "archive": str(archive.relative_to(ROOT)),
                "archive_sha256": sha(archive), "archive_ok": archive_ok,
                "runtime_members_ok": runtime_ok,
                "standalone_both_seats_720_passed": standalone_passed,
                "framework_mismatches": framework_mismatches,
                "evaluation_core_mismatches": evaluation_core_mismatches,
                "framework_note": "lifecycle.py is a post-pair replay diagnostic; runner.py and safety.py remain frozen" if framework_mismatches else "exact preregistered framework match",
            })
            assert archive_ok and runtime_ok and standalone_passed

    evaluations = {}
    for version in VERSIONS:
        folder = EVAL / version / "development"
        if not (folder / "summary.json").exists():
            continue
        pair_rows = rows(folder / "pairs.jsonl")
        summary = read(folder / "summary.json")
        assert len(pair_rows) == 32
        assert all(row["seed"] == row["control"]["requested_seed"] == row["control"]["resolved_seed"] == row["treatment"]["requested_seed"] == row["treatment"]["resolved_seed"] for row in pair_rows)
        assert all(row["safety"][arm]["completed_720"] for row in pair_rows for arm in ("control", "treatment"))
        delivery_failures = sum(bool(row["candidate_incident_classification"]["treatment_delivery_failure"]) for row in pair_rows)
        safe_flips = [row for row in pair_rows if row["loss_to_win"] and row["behavioral_isolation_valid"] and not row["candidate_new_major_regressions"]]
        actual_treatments = sum(engine_backed_treatment(version, row) for row in pair_rows)
        contract_summary = None
        contract_path = EVAL / version / "contracts.jsonl"
        if contract_path.exists():
            contracts = rows(contract_path)
            contract_totals = Counter()
            for contract in contracts:
                contract_totals.update(contract["counts"])
            contract_summary = {
                "pairs": len(contracts), "totals": dict(contract_totals),
                "fully_engine_committed_pairs": sum(
                    contract["counts"].get("extra_sale_units", 0) > 0
                    and contract["counts"].get("action_fidelity_mismatch", 0) == 0
                    and contract["counts"].get("required_order_changed", 0) == 0
                    and contract["counts"].get("failed_extra_sale", 0) == 0
                    for contract in contracts
                ),
            }
            actual_treatments = contract_summary["fully_engine_committed_pairs"]
        evaluations[version] = {
            **summary,
            "label": LABELS[version],
            "actual_engine_backed_treatments": actual_treatments,
            "delivery_failure_pairs": delivery_failures,
            "execution_contract": contract_summary,
            "safe_loss_to_win": len(safe_flips),
            "safe_flip_keys": [f"{row['lineage_id']}/{row['seed']}/{row['seat']}" for row in safe_flips],
            "seed_block_ci": seed_block_ci(pair_rows),
            "economy": replay_economy(pair_rows),
            "operational": operational_summary(pair_rows),
            "adjudication": adjudication(version, summary, pair_rows),
        }

    all_safe_flips = {
        version: data["safe_flip_keys"] for version, data in evaluations.items()
        if version not in INVALID_BY_DESIGN and data["safe_flip_keys"]
    }
    selector_evidence = {
        "safe_flips_by_route": all_safe_flips,
        "selector_created": False,
        "reason": "No safe L→W was observed across the executable route library." if not all_safe_flips else "Safe flips exist; inspect cross-context evidence before selector implementation.",
    }

    postmortem = read(OUT / "postmortem_recomputed.json")
    records = postmortem["records"]
    early = {}
    for arm in ("control", "treatment"):
        events = [event for record in records for event in record[arm]["early_execution"]["events"]]
        early[arm] = {
            "silent_field_noop": sum(event["kind"] == "silent_field_noop" for event in events),
            "atomic_plant_block": sum(event["kind"] == "silent_field_noop" and event.get("atomic_plant_block") for event in events),
            "failed_purchase": sum(event["kind"] == "market_commit" and str(event.get("op", "")).startswith("BUY") and event.get("committed") == 0 for event in events),
            "partial_sell": sum(event["kind"] == "market_commit" and event.get("op") == "SELL" and event.get("committed", 0) < event.get("requested", 0) for event in events),
        }
    town_rows = [record for record in records if record["divergence"]["first_state_divergence"]["town"] is not None]
    opponent_response_rows = [record for record in records if record["divergence"].get("first_opponent_response_step") is not None]
    opponent_benefit_rows = [record for record in records if record["divergence"].get("first_opponent_money_benefit") is not None]
    v114_rows = [row for row in rows(OLD_EVAL / "v114probe/development/pairs.jsonl") if row["incremental_treatment"]]
    failure_recheck = {
        "activated_pairs": len(records), "early_execution": early,
        "lifecycle_and_harvest_totals": postmortem["totals"],
        "town_divergence_pairs": len(town_rows),
        "earliest_town_divergence_step": min(record["divergence"]["first_state_divergence"]["town"]["step"] for record in town_rows),
        "opponent_action_response_pairs": len(opponent_response_rows),
        "opponent_money_benefit_pairs": len(opponent_benefit_rows),
        "final_coin": {
            "self_up_pairs": sum(row["delta_self_coin"] > 0 for row in v114_rows),
            "opponent_up_pairs": sum(row["delta_opponent_coin"] > 0 for row in v114_rows),
            "self_up_but_opponent_up_more_pairs": sum(row["delta_self_coin"] > 0 and row["delta_opponent_coin"] > row["delta_self_coin"] for row in v114_rows),
            "mean_delta_self": statistics.mean(row["delta_self_coin"] for row in v114_rows),
            "mean_delta_opponent": statistics.mean(row["delta_opponent_coin"] for row in v114_rows),
            "mean_delta_margin": statistics.mean(row["delta_margin"] for row in v114_rows),
        },
        "attribution_limit": "Town and opponent feedback are part of the original-engine total policy effect; no mediated causal share is identified.",
    }

    rr = rows(EVAL / "complete_policy/round_robin.jsonl")
    grouped = defaultdict(list)
    for row in rr:
        grouped[(row["a"], row["b"])].append(row)
    round_robin = [{
        "a": key[0], "b": key[1], "n": len(group),
        "a_wins": sum(row["result"] == "win" for row in group),
        "draws": sum(row["result"] == "draw" for row in group),
        "a_losses": sum(row["result"] == "loss" for row in group),
        "mean_a_margin": statistics.mean(row["margin"] for row in group),
    } for key, group in sorted(grouped.items())]
    new_source = rows(EVAL / "complete_policy/new_source_pilot.jsonl")
    source_research = {
        "round_robin": round_robin,
        "independent_public_source": {
            "registry": read(OUT / "external_source_registry.json"),
            "pilot_n": len(new_source), "pilot_wdl": dict(Counter(row["result"] for row in new_source)),
            "mean_margin": statistics.mean(row["margin"] for row in new_source),
            "executable_720": all(row["stored_steps"] == 720 and row["final_statuses"] == ["DONE", "DONE"] for row in new_source),
        },
    }

    used_seeds = {row["seed"] for version in evaluations for row in rows(EVAL / version / "development/pairs.jsonl")}
    promotion = set(range(10091101, 10091113))
    fresh = set(range(10091901, 10091913))
    holdout = {
        "used_seeds": sorted(used_seeds), "promotion_reserved": sorted(promotion), "fresh_reserved": sorted(fresh),
        "promotion_overlap": sorted(used_seeds & promotion), "fresh_overlap": sorted(used_seeds & fresh),
        "status": "SEALED; no candidate passed E3, so E4/E5 were not opened",
        "reserved_replay_bodies": "Not downloaded; reservation metadata contains outcomes and is not fully blind.",
    }
    assert not holdout["promotion_overlap"] and not holdout["fresh_overlap"]

    valid = {version: data for version, data in evaluations.items() if version not in INVALID_BY_DESIGN}
    any_promising = any(data["adjudication"].startswith("PROMISING") for data in valid.values())
    decision = {
        "created_at": datetime.now(UTC).isoformat(), "current_leader": current_leader,
        "our_remote_submissions": our_submissions,
        "production_champion": {"version": "V111", **identity},
        "primary_hypothesis": "H1 bounded executable sale continuation",
        "primary_selection_reason": "It acted on live shed state, preserved field/procurement actions, and directly tested a small executable continuation before any selector.",
        "evaluations": evaluations, "selector": selector_evidence,
        "v114_failure_recheck": failure_recheck, "source_research": source_research,
        "holdout": holdout, "artifact_verification": verification,
        "overall": "PROMISING_UNPROVEN" if any_promising else "REJECT_ALL_NEW_CANDIDATES_KEEP_V111",
        "submission_decision": "DO_NOT_SUBMIT",
        "submission_reason": "No new candidate passed executable E3 with safe net L→W evidence; E4 and E5 were not run.",
        "kaggle_submission_performed": False,
    }
    save(OUT / "final_decision.json", decision)
    save(OUT / "final_holdout_audit.json", holdout)
    save(OUT / "final_artifact_verification.json", {"production": identity, "research_variants": verification})

    dashboard_rows = []
    operational_rows = []
    for version, data in evaluations.items():
        s = data["summary"]
        dashboard_rows.append([
            LABELS[version], f"{data['eligible']}/{data['activated']}/{data['actual_engine_backed_treatments']}",
            f"{s['baseline']['wins']}/{s['baseline']['draws']}/{s['baseline']['losses']}",
            f"{s['candidate']['wins']}/{s['candidate']['draws']}/{s['candidate']['losses']}",
            f"{s['loss_to_win']}/{s['win_to_loss']}", f"{s['mean_delta_self_coin']:+.1f}",
            f"{s['mean_delta_opponent_coin']:+.1f}", f"{s['mean_delta_margin']:+.1f}",
            f"{data['hard_safety_pairs']}/{data['invalid']}", data["adjudication"],
        ])
        op = data["operational"]
        operational_rows.append([
            LABELS[version], f"{data['elapsed_seconds_this_run']:.1f}",
            f"{op['incomplete_pairs']}/{op['runtime_failure_events']}",
            f"{data['invalid']}/{op['unexpected_divergence_pairs']}",
            f"{data['delivery_failure_pairs']}/{op['transaction_incomplete_pairs']}",
            f"{op['new_silent_field_noop']}/{op['new_silent_market_noop']}",
            op["new_failed_required_purchase"], op["animal_loss_delta"],
            f"{op['plant_to_weed_delta']:+d}/{op['spawned_weed_delta']:+d}",
            op["negative_cash_pairs"],
        ])
    lineage_rows = []
    for version, data in evaluations.items():
        if version in INVALID_BY_DESIGN:
            continue
        for line in data["matrix"]:
            lineage_rows.append([
                LABELS[version], line["lineage_id"],
                f"{line['candidate']['wins']}/{line['candidate']['draws']}/{line['candidate']['losses']}",
                f"{line['loss_to_win']}/{line['win_to_loss']}", f"{line['mean_delta_margin']:+.1f}",
            ])
    uncertainty_rows = []
    economy_rows = []
    for version, data in valid.items():
        seed_ci = data["seed_block_ci"]
        bt = data["bt"]
        bt_low, bt_high = bt["approx_95_interval"]
        uncertainty_rows.append([
            LABELS[version], f"{data['summary']['delta_win_score']:+.3f}",
            f"{data['robust_meta']['worst_delta']:+.3f}",
            f"[{seed_ci['low_95']:+.3f}, {seed_ci['high_95']:+.3f}]",
            f"{bt['candidate_minus_baseline_ability']:+.3f} [{bt_low:+.3f}, {bt_high:+.3f}]",
        ])
        control = data["economy"]["control"]
        treatment = data["economy"]["treatment"]
        lead_keys = ("day12", "day18", "day20", "day24")
        lead = "/".join(
            f"{control['lead_to_loss'][key]}→{treatment['lead_to_loss'][key]}"
            for key in lead_keys
        )
        control_units = ", ".join(
            f"{item}:{units}" for item, units in control["terminal_stranded_units"].items() if units
        ) or "none"
        treatment_units = ", ".join(
            f"{item}:{units}" for item, units in treatment["terminal_stranded_units"].items() if units
        ) or "none"
        economy_rows.append([
            LABELS[version], f"{control['p10_margin']:.0f}→{treatment['p10_margin']:.0f}", lead,
            f"{control['mean_terminal_stranded_observed_price_proxy']:.1f}→{treatment['mean_terminal_stranded_observed_price_proxy']:.1f}",
            f"{control_units} → {treatment_units}",
        ])
    rr_rows = [[r["a"], r["b"], f"{r['a_wins']}/{r['draws']}/{r['a_losses']}", f"{r['mean_a_margin']:+.1f}"] for r in round_robin]
    totals = failure_recheck["lifecycle_and_harvest_totals"]
    harvest_items = ("WHEAT", "CARROT", "STRAWBERRY", "MELON", "MILK", "WOOL")
    harvest_rows = [[item, totals.get(f"control.successful_harvest_units.{item}", 0), totals.get(f"treatment.successful_harvest_units.{item}", 0), totals.get(f"treatment.successful_harvest_units.{item}", 0) - totals.get(f"control.successful_harvest_units.{item}", 0)] for item in harvest_items]
    report = f"""# Kaggriculture continuation research report — 2026-09-12

## 判断

新しいcandidateは提出しない。production ChampionはV111のまま。実行可能な代替行動を6 options（売却2、非管理Sheep、Cow保持、管理付きSheep/Goose）でfull720 paired評価したが、validかつhard SafetyなしのL→Wを確認できなかった。したがってstate-dependent selectorは作成していない。総合判定は **{decision['overall']}**、提出判断は **DO_NOT_SUBMIT**。

最新取得時点 {current_leader['fetched_at']} のLeaderboard #1は {current_leader['team_name']}、Rating {current_leader['rating']:.1f}、submission {current_leader['submission_id']}。自チームの最新表示はsubmission {our_submissions[0]['submission_id']}、Rating {our_submissions[0]['current_public_rating']:.1f}だが、remote archive identityはunknownでlocal V111へ帰属させない。真のlocal ChampionはV111、source `{identity['source_sha256']}`、archive `{identity['archive_sha256']}`、engine `{identity['engine_sha256']}`（kaggle-environments 1.32.7）。

## Paired evaluation

`eligible / activation / engine-backed treatment`、W/D/L、勝敗反転を同じDevelopment 4 seeds×4 sources×両seatで比較した。seedはsource横断で共有されるため、独立blockは4だけである。平均coinは判断の補助で、勝敗反転を優先した。

{md_table(['Option', 'eligible/active/actual', 'V111 W/D/L', 'candidate W/D/L', 'L→W/W→L', 'Δself', 'Δopp', 'Δmargin', 'Safety/invalid', '判断'], dashboard_rows)}

runner秒は各summaryの`elapsed_seconds_this_run`で、resume済み結果を再利用したrunを含むため候補間の速度比較には使わない。

{md_table(['Option', 'runner sec', 'incomplete/runtime fail', 'invalid/unexpected div', 'delivery/tx fail', 'new no-op field/market', 'new failed buy', 'Δanimal loss', 'Δcrop→weed/empty→weed', 'negative cash'], operational_rows)}

Primaryに売却continuationを選んだ理由は、live shedだけで発火でき、field・必要購入・worker系列を変えず、V111の終盤在庫仮説を最小の実行契約として検証できたため。即時/Town同期の双方が32/32で安全に発火し、全64 contractでaction fidelity mismatch、field rewrite、必要購入変更、failed extra saleは0だった。しかしL→Wは0で、平均marginも悪化した。これは **no causal uplift** で棄却する。

非管理Sheepは22/32で発火し、L→W 0、W→L 2、発火22件すべてで新規silent no-opを生じたため **Safety regression**。Cow保持の初版はactionがt248で正しく変わったが、半開区間を`[248,248]`とした評価設定ミスで2件invalid。上書きせずr1を`[248,249)`で凍結・全件再実行した。管理付き動物も購入から配置後の空HARVEST回避・生成品売却まで契約として評価した。

### lineage別

{md_table(['Option', 'lineage', 'candidate W/D/L', 'L→W/W→L', 'mean Δmargin'], lineage_rows)}

各summaryにはequal-weight payoff matrix、robust reweighting（radius 0.2）、Bradley–Terry diagnostic、whole-seed bootstrapを保存した。4 seed blockと保守的に2 ancestry群しかないため、0反転を「一般に不可能」とは解釈しない。

{md_table(['Option', 'weighted Δwin score', 'robust worst Δ', 'seed-block 95% CI', 'BT ability差 [95%]'], uncertainty_rows)}

このDevelopment panelでのV111は一貫して12W/0D/20L（37.5%）。これは使用済み4 seedと旧4 sourceに条件付けたE3推定で、Leaderboard Ratingの推定値ではない。current Topとのsource照合ができないため、現在の実戦実力は未同定とする。

## V114敗戦説明の再検証

元のV114probe replay 24発火pairsを、凍結engine sourceから再生した。結果自体（0W/32L、L→W 0、W→L 12）は変わらない。

- 実行不整合: t153–215でfailed purchaseはcontrol 0、treatment 24。atomic PLANT blockは16→88、silent field no-opは44→188。固定Wheat=25の投影は実価格ではない。
- 自然寿命終了: lifespan endは360→473だが、その時点の未収穫yield合計は192→192。寿命件数の増加だけを収穫損失と呼べない。
- 水切れ: water deathは120→75、消失時のcurrent yieldは96→48。旧説明の「水管理崩壊」という一括原因は支持されない。
- 実収穫量: 各HARVEST action直前直後のprivate在庫差で、成功HARVESTを直接集計した。

{md_table(['product', 'control', 'forced route', 'delta units'], harvest_rows)}

- 相手価格利益: 24件すべてで相手moneyが一時的にcontrolを上回り、最終self coin増の9件中5件では相手の増分がさらに大きかった。平均Δself {failure_recheck['final_coin']['mean_delta_self']:+.1f}、Δopponent {failure_recheck['final_coin']['mean_delta_opponent']:+.1f}、Δmargin {failure_recheck['final_coin']['mean_delta_margin']:+.1f}。価格・数量・相手応答を含む総効果であり、媒介割合は同定していない。
- Town/RNG: 価格とTownは24/24で分岐し、Townの最初の差はt{failure_recheck['earliest_town_divergence_step']}。22/24では相手actionも後続分岐した。engineは空き地weed抽選後にTownを引くため、同seedでもactionで乱数消費経路が変わる。これらのpairを主評価から除外していない。

## source調査と感度

既存4 policy間のcomplete-policy round robinは非推移性を確認した。

{md_table(['A', 'B', 'A W/D/L', 'A mean margin'], rr_rows)}

独立public source `robriculture/lean_feed`（commit `{source_research['independent_public_source']['registry']['commit']}`、CC-BY-4.0）は4/4完走したがV111に0/0/4、平均margin {source_research['independent_public_source']['mean_margin']:+.1f}。独立ancestryのregression anchorには使えるが、強い代理相手とは扱わない。最新上位artifactのsource identityは依然unknown。

## Safety、holdout、artifact

評価順は実行妥当性→delivery→Safety→対戦改善。Safety違反をcoinで救済していない。P10 margin、day12/18/20/24 lead→loss、terminal stranded inventoryとfinal-price proxyは各candidateの`summary.json`に対応する `final_decision.json` の`economy`へ保存した。proxyは達成可能売却益ではない。

pair recordにはfirst self action/money/portfolio/position、public market/price/Town、opponent responseとlag、opponent moneyのdivergence auditを保存した。介入後のTown分岐を除外条件にはしていない。

{md_table(['Option', 'P10 margin C→T', 'lead→loss D12/18/20/24 C→T', 'stranded proxy C→T', 'terminal stranded units C→T'], economy_rows)}

使用seedは {holdout['used_seeds']} のみ。promotion 10091101–10091112、Fresh 10091901–10091912とのoverlapはともに0で、Freshは **SEALED**。先行E3 gateを通る候補がないためE4/E5を開かなかった。予約replay bodyも取得していない。

research archiveとstandalone runtimeはversion別に保存し、Championを変更していない。旧候補のfreeze後に`lifecycle.py`だけを実収穫量のreplay診断用に拡張したが、paired実行coreの`runner.py`/`safety.py`は変えていない。この差はartifact verificationに明記した。新candidateはすべてresearch-onlyで、提出可能な新artifactとして認定しない。既存V111 archiveだけが保全済みChampion artifactである。Kaggle提出は行っていない。

## 何が強くなり、何が未証明か

実際に強くなった新policyはない。強くなったのは評価系で、requested/emitted/engine commit、自然寿命、水切れ、実HARVEST、相手money、Town分岐を分離できるようになった。売却タイミング、late animal choice、管理付き動物はいずれもこのpanelで勝敗改善を示さなかった。

未証明なのは、現在のTop sourceに対するV111の実力、上位artifactのidentity、異なるdecision pointの安全なroute、独立ancestryを増やしたmetaでの効果、E4/E5/E6である。

次の5時間では、V111と30–60%程度で競る独立complete policyを先に取得・再現し、同じDevelopment seedでV111の敗戦状態を増やす。その上で、t248以外の最初の資金制約decision pointについて、元schedule内の二つの完走済みcontinuationを比較する。safe L→Wが複数相手・複数状態に現れるまでselectorやforecastは作らない。見つかった時だけliveで観測可能な1回限りのgateを凍結し、E4後にFreshを一度開く。

## Artifacts

- [Final decision](../experiments/research_20260911_continuations/final_decision.json)
- [Recomputed V114 postmortem](../experiments/research_20260911_continuations/postmortem_recomputed.json)
- [Holdout audit](../experiments/research_20260911_continuations/final_holdout_audit.json)
- [Artifact verification](../experiments/research_20260911_continuations/final_artifact_verification.json)
- [Evaluation data](../data/evaluation/research_20260911_continuations/)
- [Preregistrations](research_20260911_preregistration.md)

## 再現command

以下は凍結済みartifactとDevelopment seedだけを使い、Freshを開かない。

```powershell
./.venv/Scripts/python.exe scripts/research_20260911.py audit
./.venv/Scripts/python.exe scripts/research_20260911.py aa --workers 6
foreach ($version in @('v115p_immediate','v115p_town','v115p_livestock','v115p_retain_cow_r1','v115p_managed_sheep','v115p_managed_goose')) {{
    ./.venv/Scripts/python.exe scripts/research_20260911.py paired --version $version --workers 6
}}
./.venv/Scripts/python.exe scripts/postmortem_20260911.py
./.venv/Scripts/python.exe scripts/analyze_continuations_20260911.py table
./.venv/Scripts/python.exe scripts/finalize_research_20260912.py
./.venv/Scripts/python.exe -m pytest -q tests/test_continuations_20260911.py
uv run ruff check scripts/research_20260911.py scripts/postmortem_20260911.py scripts/analyze_continuations_20260911.py scripts/external_20260911.py scripts/finalize_research_20260912.py scripts/evaluation/runner.py scripts/evaluation/safety.py scripts/evaluation/lifecycle.py scripts/continuation_option_template.py scripts/livestock_option_template.py scripts/managed_animal_template.py scripts/retain_cow_option_template.py tests/test_continuations_20260911.py
```
"""
    (ROOT / "docs/research_20260912_continuation_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"overall": decision["overall"], "submission": decision["submission_decision"], "selector": selector_evidence, "evaluated": list(evaluations)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
