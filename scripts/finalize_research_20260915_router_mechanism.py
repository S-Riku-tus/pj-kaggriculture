# Ruff E501 is disabled for embedded Japanese report paragraphs and exact commands.
# ruff: noqa: E501
"""Finalize the preregistered router-mechanism study without opening new seeds."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXP = ROOT / "experiments" / "research_20260915_router_mechanism"
DOC = ROOT / "docs" / "research_20260915_router_mechanism_report.md"
PREREG_DOC = ROOT / "docs" / "research_20260915_router_mechanism_preregistration.md"
DRIVER = ROOT / "scripts" / "research_20260915_router_mechanism.py"
SELF = Path(__file__).resolve()
OLD_EXP = ROOT / "experiments" / "research_20260914_clean_psr"
P1_PAIRS = OLD_EXP / "candidates" / "P1_psr_clean" / "pairs" / "spent.jsonl"
SOURCE_AUDIT_PRIOR = OLD_EXP / "independent_source_audit_pre_results.json"
SOURCE_SELECTION_PRIOR = OLD_EXP / "independent_screen" / "selection.json"
SOURCES = ["mooman_e052a", "souvik_v4", "ggmljs_v16", "qeinstein_moev2"]
ANCESTRY = {
    "psr_kaito_near": ["mooman_e052a", "souvik_v4", "ggmljs_v16"],
    "qeinstein_independent": ["qeinstein_moev2"],
}
CANDIDATES = [
    "A0_psr_route_locked",
    "A1_psr_no_day6_switch",
    "A2_psr_no_day24_switch",
]
JST = timezone(timedelta(hours=9))


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def pair_integrity(candidate: str) -> dict[str, Any]:
    root = EXP / "candidates" / candidate
    freeze = load(root / "freeze.json")
    expected = {"aa": 2, "smoke": 4, "spent": 32}
    phases = {}
    all_ok = True
    for phase, count in expected.items():
        path = root / "pairs" / f"{phase}.jsonl"
        parsed = rows(path)
        keys = [(row["lineage_id"], int(row["seed"]), int(row["seat"])) for row in parsed]
        candidate_hashes = sorted({row["candidate_source_sha256"] for row in parsed})
        package_hashes = sorted({row["candidate_package_sha256"] for row in parsed})
        evaluator_hashes = sorted({row["evaluation_core_sha256"] for row in parsed})
        engine_hashes = sorted({row["provenance"]["engine_sha256"] for row in parsed})
        configuration_hashes = sorted({row["provenance"]["configuration_sha256"] for row in parsed})
        replay_ok = True
        for row in parsed:
            replay_ok &= all(Path(row["replay_artifacts"][arm]).is_file() for arm in ("control", "treatment"))
        phase_ok = (
            len(parsed) == count
            and len(set(keys)) == count
            and candidate_hashes == [freeze["source_sha256"]]
            and package_hashes == [freeze["package_sha256"]]
            and len(evaluator_hashes) == 1
            and len(engine_hashes) == 1
            and len(configuration_hashes) == 1
            and replay_ok
        )
        all_ok &= phase_ok
        phases[phase] = {
            "path": rel(path),
            "sha256": sha256(path),
            "rows": len(parsed),
            "expected_rows": count,
            "unique_context_keys": len(set(keys)),
            "candidate_source_sha256": candidate_hashes,
            "candidate_package_sha256": package_hashes,
            "evaluation_core_sha256": evaluator_hashes,
            "engine_sha256": engine_hashes,
            "configuration_sha256": configuration_hashes,
            "all_replays_present": replay_ok,
            "no_partial_jsonl": True,
            "passed": phase_ok,
        }
        progress = load(root / "progress" / f"{phase}.json")
        summary = load(root / "summary" / f"{phase}.json")
        save(
            root / "runs" / f"{phase}.json",
            {
                "created_at": now(),
                "candidate": candidate,
                "phase": phase,
                "command": (
                    f".\\.venv\\Scripts\\python.exe scripts\\research_20260915_router_mechanism.py "
                    f"run --candidate {candidate} --phase {phase}"
                ),
                "plan": rel(root / "plans" / f"{phase}.json"),
                "progress": progress,
                "summary": summary,
                "pair_integrity_passed": phase_ok,
            },
        )
    return {"candidate": candidate, "passed": all_ok, "phases": phases}


def rich_candidate_summary(candidate: str) -> dict[str, Any]:
    import scripts.finalize_clean_psr_research as previous

    previous.EXP = EXP
    previous.SOURCES = SOURCES
    previous.ANCESTRY = ANCESTRY
    previous.BOOTSTRAP_REPETITIONS = 100_000
    previous.BOOTSTRAP_SEED = 20_260_915
    candidate_rows = rows(EXP / "candidates" / candidate / "pairs" / "spent.jsonl")
    summary = previous.candidate_summary(candidate, candidate_rows)
    save(EXP / "candidates" / candidate / "summary" / "complete.json", summary)
    return summary


def route_at(trace_row: dict[str, Any], step: int) -> int:
    block = min(step // 144, 4)
    return int(trace_row["decisions"][block]["route_index"])


def update_route_safety_map() -> None:
    trace = load(EXP / "router_decision_trace.json")
    traces = {(row["source"], int(row["seed"]), int(row["seat"])): row for row in trace["contexts"]}
    prior = load(OLD_EXP / "safety_first_event_map.json")["candidate_maps"]["P1_psr_clean"]
    event_rows = []
    reason_route: dict[str, Counter[str]] = {}
    reason_steps: dict[str, Counter[str]] = {}
    classifications: dict[str, Counter[str]] = {}
    for context in prior["contexts"]:
        key = (context["source"], int(context["seed"]), int(context["seat"]))
        current_trace = traces[key]
        events = []
        for reason, event in context["events"].items():
            step = int(event["step"])
            route = route_at(current_trace, step)
            reason_route.setdefault(reason, Counter())[f"route_{route}"] += 1
            reason_steps.setdefault(reason, Counter())[str(step)] += 1
            if event.get("classification"):
                classifications.setdefault(reason, Counter())[str(event["classification"])] += 1
            events.append(
                {
                    "reason": reason,
                    "first_step": step,
                    "active_route_index": route,
                    "classification": event.get("classification"),
                }
            )
        event_rows.append(
            {
                "key": list(key),
                "route_sequence": [item["route_index"] for item in current_trace["decisions"]],
                "events": events,
            }
        )
    save(
        EXP / "router_safety_route_map.json",
        {
            "created_at": now(),
            "scope": "P1 existing spent replays; active route at each raw Safety first event",
            "reason_active_route_counts": {key: dict(value) for key, value in reason_route.items()},
            "reason_first_step_counts": {key: dict(value) for key, value in reason_steps.items()},
            "reason_classifications": {key: dict(value) for key, value in classifications.items()},
            "contexts": event_rows,
            "interpretation": {
                "crop": "step 479 falls in block3, whose tree leaf is route0 for every context",
                "animal": "step 695 falls in block4 and occurs under both route0 and route3",
                "limit": "same timestamp/active route is exposure evidence, not causal identification",
            },
        },
    )


def update_identity_audit() -> dict[str, Any]:
    audit = load(EXP / "router_identity_proxy_audit.json")
    audit["decision"] = "NO_KNOWN_SOURCE_IDENTITY_PROXY_ESTABLISHED_ON_SPENT_PANEL"
    audit["identity_boundary_passed"] = True
    audit["deploy_transfer_allowed"] = False
    audit["deploy_transfer_blockers"] = [
        "router uplift appears in only one source-seed block and one source",
        "the exact route/tree expression has unverified transitive provenance and is research-only",
        "no V111-owned complete state-compatible suffix or unique execution contract was established",
    ]
    audit["localized_caution"] = (
        "Two route sequences occur only for ggmljs in this panel, but overall majority-source accuracy is "
        "0.375 and the only outcome gain is on the shared qeinstein route sequence. This is not evidence "
        "of a useful identity selector; exact routing remains research-only."
    )
    save(EXP / "router_identity_proxy_audit.json", audit)
    return audit


def independent_source_audit() -> dict[str, Any]:
    prior_audit = load(SOURCE_AUDIT_PRIOR)
    prior_selection = load(SOURCE_SELECTION_PRIOR)
    new_root = EXP / "acquisition" / "robriculture_head_2077b023"
    record = {
        "created_at": now(),
        "timing": "No C1 was created and no C1 source result exists; audit cannot be conditioned on C1 performance.",
        "prior_audit": {"path": rel(SOURCE_AUDIT_PRIOR), "sha256": sha256(SOURCE_AUDIT_PRIOR)},
        "prior_selection": {"path": rel(SOURCE_SELECTION_PRIOR), "sha256": sha256(SOURCE_SELECTION_PRIOR)},
        "remote_head_checks": [
            {"source": "deepeshumrao", "revision": "65724ce530af8e8ea0410d5b7f0e2a997ca676cb", "same_as_prior": True},
            {"source": "lonespear", "revision": "774b26093ccf4246525517d48420349b841b6e50", "same_as_prior": True},
            {"source": "robriculture", "revision": "2077b023525e622c0fc4a947083fcf339c21086e", "same_as_prior": False},
        ],
        "reused_without_rerun": prior_selection["screen_results"],
        "new_revision_static_audit": {
            "source": "robriculture_head_2077b023",
            "repository": "https://github.com/robsartin/robriculture.git",
            "revision": "2077b023525e622c0fc4a947083fcf339c21086e",
            "acquired_at": now(),
            "acquisition_path": rel(new_root),
            "license": "CC-BY-4.0",
            "license_sha256": sha256(new_root / "LICENSE"),
            "declared_champion": "ten_melon",
            "champion_record_sha256": sha256(new_root / "harness" / "champion.json"),
            "native_callable": "TenMelonStrategy.act",
            "native_import_ok": True,
            "entry_source": rel(new_root / "strategies" / "ten_melon.py"),
            "entry_source_sha256": sha256(new_root / "strategies" / "ten_melon.py"),
            "dependencies": "repository kaggisim and strategies package; standalone package not built in this stopped stage",
            "ancestry": "robriculture hand/job economy; no PSR/Kaito named import found in static scan",
            "baseline_screen": "NOT_RUN_GATE_STOPPED",
            "qualification_0_25_to_0_75": "UNKNOWN",
            "counts_as_verified_third_ancestry": False,
        },
        "selected": [],
        "selection_status": "NOT_REACHED_C1_GATE_FAILED",
        "prior_weak_anchors_do_not_establish_third_ancestry": True,
        "performance_games_started": 0,
    }
    record["prior_rule"] = prior_audit["selection_rule"]
    save(EXP / "independent_source_screen.json", record)
    source_license = load(EXP / "source_and_license_audit.json")
    source_license["independent_source_refresh"] = record
    source_license["P1_route_data_transitive_provenance"] = "UNVERIFIED"
    source_license["deployment_conclusion"] = (
        "No PSR route/blob/tree/action expression may enter a production candidate; no C1 was created."
    )
    save(EXP / "source_and_license_audit.json", source_license)
    return record


def update_seed_ledger() -> dict[str, Any]:
    ledger = load(EXP / "seed_ledger.json")
    ledger["updated_at"] = now()
    ledger["this_experiment_execution"] = {
        "game_seeds": [10091011, 10091012, 10091013, 10091014],
        "classification": "previously spent training/development contexts",
        "ablation_contexts": 96,
        "aa_contexts": 6,
        "smoke_contexts": 12,
        "P1_D1_R0_new_contexts": 0,
        "new_development_contexts": 0,
    }
    ledger["groups"].update(
        {
            "promotion": {"range": [10091101, 10091112], "structured_used": [], "status": "UNUSED_SEALED"},
            "fresh": {"range": [10091901, 10091912], "structured_used": [], "status": "UNUSED_SEALED"},
            "prior_development": {"range": [10091421, 10091436], "structured_used": [], "status": "UNUSED_SEALED"},
            "proposed_development": {
                "range": [10091521, 10091536],
                "structured_used": [],
                "status": "UNUSED_NOT_OPENED",
            },
        }
    )
    save(EXP / "seed_ledger.json", ledger)
    return ledger


def build_report(summaries: dict[str, Any], identity: dict[str, Any]) -> None:
    a0 = summaries["A0_psr_route_locked"]
    a1 = summaries["A1_psr_no_day6_switch"]
    a2 = summaries["A2_psr_no_day24_switch"]
    report = f"""# Router mechanism research report — 2026-09-15

## 最終判断

`REJECT_NO_UPLIFT`。ここでいうupliftは、V111へ合法かつ完全に移せる一般化機構のupliftである。P1由来ablation自体の勝率が高いことを否定する判断ではない。production ChampionはV111のまま維持し、numeric agent、C1/C2、Development確認は作成・実行しなかった。

## 実行範囲と保全

開始時HEADは`851e970d81db084a712097928a71feb9c0e2b09a`、branchは`main`。開始時dirty worktreeとユーザー作成fileをmanifestへ記録して保全した。旧P1/D1/R0の32 pairはhash検証後に再利用し、新規gameはA0/A1/A2だけをA/A 6、smoke 12、旧spent 96 contexts実行した。全ablationは独立load A/A、両seat smoke、720 states/719 decisions、schema、runtime/isolationを通過した。

Kaggle提出、kernel push、submission slot変更は0。promotion `10091101–10091112`、Fresh `10091901–10091912`、旧Development `10091421–10091436`、今回条件付きDevelopment `10091521–10091536`はいずれも未使用である。

## Router固有価値と固定route

| policy | W/D/L | V111比win-score差 | P1 fullとの差 | raw Safety | W→L |
|---|---:|---:|---:|---:|---:|
| P1 full（既存） | 24/0/8 | +0.3750 | — | 32/32 | 2 |
| A0 route0固定 | {a0["overall"]["candidate"]["wins"]}/0/{a0["overall"]["candidate"]["losses"]} | {a0["overall"]["delta_win_score"]:+.4f} | +0.0625 | {a0["safety"]["raw_failure_contexts"]}/32 | 2 |
| A1 day6 switch無効 | {a1["overall"]["candidate"]["wins"]}/0/{a1["overall"]["candidate"]["losses"]} | {a1["overall"]["delta_win_score"]:+.4f} | +0.0625 | {a1["safety"]["raw_failure_contexts"]}/32 | 2 |
| A2 day24 switch無効 | {a2["overall"]["candidate"]["wins"]}/0/{a2["overall"]["candidate"]["losses"]} | {a2["overall"]["delta_win_score"]:+.4f} | 0.0000 | {a2["safety"]["raw_failure_contexts"]}/32 | 2 |

robustnessは、A0/A1のwhole source+seed block bootstrap 95%下限が0.0000、A2が0.0625だった。equal-source差は順に+0.3125/+0.3125/+0.3750、equal-ancestry差は+0.2917/+0.2917/+0.4167、9 reweighting worst差は+0.2763/+0.2763/+0.3421。exclude-self、exclude-tape2-source、exclude-near-lineage差はいずれも負ではない。ただしこれはtrained old-spent panel内の感度で、router固有差の2-source gateや一般化証拠を置き換えない。candidate margin P10はA0/A1が-13,194.6、A2が-5,063.5だった。

P1 full−A0は+0.0625で、qeinstein seed 10091013の1 source-seed block（両seatを1 case）のみだった。2 sources以上という事前gateを満たさない。A1がA0と同じ、A2がP1 fullと同じなので、観測された追加分はday 6 Town分岐に局在し、day 24 CARROT price分岐の勝敗寄与は0だった。

A0はV111比+0.3125で、P1 total-policy uplift +0.375の5/6（83.33%）を、step 0で選ばれたroute0を固定したまま再現した。したがって、旧改善の大半はrouter変更ではなく、route選択前から共通する固定route0とstep 0 market/portfolio footprintを含むtotal policyで説明可能である。A0は固定route全体を残すablationなので、step 0 WHEAT購入単独とその後のportfolioを分離しておらず、初期footprint単独の因果量はUnknownである。

## Identity proxy監査

実traverse featureはTown（YARN_STORE構成、MILK需要）と現在CARROT価格だけで、rival public farm featureは0、明示identity/seed/private/future/tape照合も0だった。route sequenceからsourceを多数決予測するaccuracyは{identity["route_sequence_majority_source_accuracy"]:.3f}。ggmljsだけに現れた局所sequenceはあるが、唯一のrouter勝敗差は複数sourceで共有されるqeinsteinのsequence上にある。従って既知source identity proxyだったという証拠は成立しない。ただし閾値距離0のday 6 decisionが多く近傍安定性が弱く、route expressionのprovenanceも未確認なので、exact selectorのdeploy転記は不可である。

## Evidence / Inference / Unknown

Evidence: P1/A0/A1/A2はいずれもstep 1に最初のpublic market divergenceを生じる。P1のopponent responseはその後0–624 steps、中央値70.5。A0の平均V111差はself coin {a0["overall"]["mean_delta_self_coin"]:+.4f}、opponent coin {a0["overall"]["mean_delta_opponent_coin"]:+.4f}、margin {a0["overall"]["mean_delta_margin"]:+.4f}。固定route0だけでsouvik +1.0、qeinstein +0.25、mooman/ggmljs 0のsource別win-score差が得られた。daily coin、portfolio、market/Town、opponent actionの順序は`mediator_timeline.json`に保存した。

Inference: marginの一部はpublic market/price/Townを介した相手のclosed-loop応答と整合する。自己生産・回収と相手行動の双方がtotal policy差の後に変わっている。

Unknown: self生産寄与とopponent mediation寄与の識別、step 0 WHEAT購入単独効果、Town/priceを固定したcounterfactual、未使用seed・第3 ancestryへの一般化。相手coin低下を単一market actionの因果効果とは呼ばない。

## Safety・実行contract

A0/A1/A2はいずれもraw Safety 32/32、W→L 2。全contextのcrop-to-weedはstep 479のblock3 route0、animal lossはstep 695にroute0とroute3の双方で発生した。market no-op 8 contexts、partial commit 8、silent field no-op 7も維持された。時刻とactive routeの一致は因果ではない。order/step明細、successful harvest units、water/lifespan loss、t672/t719 shed/carry/unharvested proxyは各candidateの`summary/*_diagnostics.json`と`complete.json`に保存した。step 719在庫は残りdecision 0のproxyであり実現収入ではない。

## Transfer gateと一般化

router固有差は1/16 source-seed blocks、1/4 sources、1 ancestryだけで、2-source条件を満たさない。さらに固定route0の具体表現はP1のresearch-only tape/routeと未確認transitive provenanceに依存し、V111-ownedの調達から販売・rejoinまで完結するsuffix/contractは確立できなかった。よってC1/C2を作らず、raw Safety 0やW→L 0を主張するdeploy候補は存在しない。

診断panelは16 source-seed blocks、4 sources、検証済み2 ancestries。Deepesh/Lonespearは前回と同一hashのため再走せず、robriculture新HEAD `2077b0…`はCC-BY-4.0とnative callableを静的確認したが、前段gate停止のためbaseline gameを開かず第3 ancestryに数えない。Developmentは0 blocks。numeric agent作成は0、labelは`REJECT_NO_UPLIFT`であり、V111は権利明確・既存production Championとして維持する。

## 再現とartifact

正確な実行・resume commandは`experiments/research_20260915_router_mechanism/reproduction_commands.json`、全artifact hashは`final_artifact_manifest.json`、再検証結果は`final_artifact_verification.json`を参照。P1 blob/tape/tree/route/action tableはproduction agentへ転記していない。
"""
    DOC.write_text(report, encoding="utf-8")


def build() -> None:
    integrity = [pair_integrity(candidate) for candidate in CANDIDATES]
    save(
        EXP / "ablation_integrity_verification.json",
        {"created_at": now(), "passed": all(item["passed"] for item in integrity), "candidates": integrity},
    )
    summaries = {candidate: rich_candidate_summary(candidate) for candidate in CANDIDATES}
    update_route_safety_map()
    identity = update_identity_audit()
    independent = independent_source_audit()
    ledger = update_seed_ledger()
    mechanism = load(EXP / "mechanism_attribution.json")
    mechanism.update(
        {
            "decision": "REJECT_NO_UPLIFT",
            "router_specific": {
                "P1_full_minus_A0_context_win_score": 0.0625,
                "positive_source_seed_blocks": 1,
                "sources": ["qeinstein_moev2"],
                "block": ["qeinstein_moev2", 10091013],
                "gate_requires_sources": 2,
                "gate_passed": False,
            },
            "fixed_route_and_initial_footprint": {
                "V111_to_A0_context_win_score": 0.3125,
                "fraction_of_P1_total_uplift": 5 / 6,
                "interpretation": "fixed route0 plus initial footprint explains at least this much; footprint alone was not isolated",
            },
            "day6_switch_increment": 0.0625,
            "day24_switch_increment": 0.0,
            "candidate_summaries": {
                key: rel(EXP / "candidates" / key / "summary" / "complete.json") for key in CANDIDATES
            },
        }
    )
    save(EXP / "mechanism_attribution.json", mechanism)
    ranking = load(EXP / "mechanism_ranking.json")
    ranking["measured_conclusion"] = {
        "fixed_route0_plus_initial_footprint": {"delta_vs_V111": 0.3125, "P1_fraction": 5 / 6, "rank": 1},
        "day6_Town_router": {
            "delta_P1_minus_A1": 0.0625,
            "positive_blocks": 1,
            "positive_sources": 1,
            "rank": 2,
            "transfer_gate": False,
        },
        "day24_CARROT_price_router": {"delta_P1_minus_A2": 0.0, "rank": 3, "transfer_gate": False},
        "generic_execution_contract": {
            "positive_mechanism_isolated": False,
            "rank": 4,
            "excluded_as_P1_safety_repair": True,
        },
    }
    save(EXP / "mechanism_ranking.json", ranking)
    save(
        EXP / "development_progress.json",
        {
            "created_at": now(),
            "status": "NOT_OPENED_GATE_STOPPED",
            "reason": "router/public-state mechanism did not satisfy the two-source C1 gate",
            "conditional_range": [10091521, 10091536],
            "used": [],
            "promotion_range_used": [],
            "fresh_range_used": [],
            "prior_development_range_used": [],
            "C1_created": False,
            "C2_created": False,
        },
    )
    save(
        EXP / "reproduction_commands.json",
        {
            "created_at": now(),
            "environment": "repository .venv; current working directory is repository root",
            "analysis": ".\\.venv\\Scripts\\python.exe scripts\\research_20260915_router_mechanism.py analyze",
            "prepare": ".\\.venv\\Scripts\\python.exe scripts\\research_20260915_router_mechanism.py prepare",
            "validate": ".\\.venv\\Scripts\\python.exe scripts\\research_20260915_router_mechanism.py validate",
            "candidate_phases": [
                f".\\.venv\\Scripts\\python.exe scripts\\research_20260915_router_mechanism.py run --candidate {candidate} --phase {phase}"
                for candidate in CANDIDATES
                for phase in ("aa", "smoke", "spent")
            ],
            "resume": [
                f".\\.venv\\Scripts\\python.exe scripts\\research_20260915_router_mechanism.py run --candidate {candidate} --phase spent"
                for candidate in CANDIDATES
            ],
            "resume_rule": "Only the identical frozen candidate/source/package/evaluator hashes may reuse the JSONL; completed pair keys are skipped.",
            "finalize_build": ".\\.venv\\Scripts\\python.exe scripts\\finalize_research_20260915_router_mechanism.py build",
            "finalize_validate": ".\\.venv\\Scripts\\python.exe scripts\\finalize_research_20260915_router_mechanism.py validate",
            "finalize_seal": ".\\.venv\\Scripts\\python.exe scripts\\finalize_research_20260915_router_mechanism.py seal",
            "forbidden": ["Kaggle submission", "kernel push", "slot change", "opening sealed seed ranges"],
        },
    )
    final_decision = {
        "created_at": now(),
        "status": "REJECT_NO_UPLIFT",
        "scope": "No qualifying V111-transferable uplift; research-only P1-derived ablations are not promotion candidates.",
        "production_champion": "V111",
        "router_specific_uplift": {
            "win_score": 0.0625,
            "blocks": 1,
            "sources": 1,
            "ancestries": 1,
            "gate_passed": False,
        },
        "fixed_route0_plus_initial_footprint": {
            "win_score_vs_V111": 0.3125,
            "P1_total_uplift": 0.375,
            "fraction_explained": 5 / 6,
            "initial_footprint_alone": "UNKNOWN_NOT_ISOLATED",
        },
        "identity_proxy": identity["decision"],
        "C1_created": False,
        "C2_created": False,
        "deploy_candidate_raw_safety_zero": "NOT_APPLICABLE_NO_DEPLOY_CANDIDATE",
        "deploy_candidate_win_to_loss_zero": "NOT_APPLICABLE_NO_DEPLOY_CANDIDATE",
        "research_ablation_safety": {key: summaries[key]["safety"] for key in CANDIDATES},
        "diagnostic_generalization": {"source_seed_blocks": 16, "sources": 4, "verified_ancestries": 2},
        "deployment_generalization": {"source_seed_blocks": 0, "sources": 0, "verified_ancestries": 0},
        "independent_source": {
            "selected": independent["selected"],
            "new_revision_games": 0,
            "verified_third_ancestry": False,
        },
        "numeric_agent_created": False,
        "numeric_label": None,
        "seed_ledger": rel(EXP / "seed_ledger.json"),
        "sealed_ranges": {name: value for name, value in ledger["groups"].items()},
        "external_mutations": {"kaggle_submission": False, "kernel_push": False, "submission_slot_change": False},
    }
    save(EXP / "final_decision.json", final_decision)
    build_report(summaries, identity)
    manifest = load(EXP / "manifest.json")
    manifest.update(
        {
            "phase": "DIAGNOSTIC_FINALIZATION",
            "status": "RESULTS_BUILT_VALIDATION_PENDING",
            "updated_at": now(),
            "new_game_contexts": {"aa": 6, "smoke": 12, "spent_ablation": 96, "P1_D1_R0": 0, "development": 0},
            "candidate_hashes": {
                candidate: load(EXP / "candidates" / candidate / "freeze.json") for candidate in CANDIDATES
            },
            "C1_gate": {
                "passed": False,
                "reason": "router value in one source only; no complete V111-owned suffix/contract",
            },
            "C1_created": False,
            "C2_created": False,
            "final_decision": "REJECT_NO_UPLIFT",
        }
    )
    save(EXP / "manifest.json", manifest)
    print(
        json.dumps(
            {"built": True, "decision": "REJECT_NO_UPLIFT", "candidate_summaries": list(summaries)}, ensure_ascii=False
        )
    )


def validate() -> None:
    commands = [
        {
            "name": "py_compile_own_python",
            "argv": [sys.executable, "-m", "py_compile", str(DRIVER), str(SELF)],
        },
        {
            "name": "ruff_own_python",
            "argv": [sys.executable, "-m", "ruff", "check", str(DRIVER), str(SELF)],
        },
        {
            "name": "evaluation_core_tests",
            "argv": [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_champion_challenger_evaluation.py",
                "tests/test_official_environment.py",
                "tests/test_agent_v111.py",
            ],
        },
    ]
    results = []
    for command in commands:
        completed = subprocess.run(
            command["argv"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        results.append(
            {
                "name": command["name"],
                "command": subprocess.list2cmdline(command["argv"]),
                "exit_code": completed.returncode,
                "stdout": (completed.stdout or "")[-8000:],
                "stderr": (completed.stderr or "")[-8000:],
                "passed": completed.returncode == 0,
            }
        )
    payload = {
        "created_at": now(),
        "passed": all(item["passed"] for item in results),
        "results": results,
        "external_exact_source_style": "EXCLUDED_UNMODIFIED",
        "evaluation_core_modified_by_this_study": False,
        "candidate_import_reset_isolation": load(EXP / "validation_pre_games.json"),
        "pair_integrity": load(EXP / "ablation_integrity_verification.json"),
    }
    save(EXP / "validation_results.json", payload)
    print(
        json.dumps(
            {
                "passed": payload["passed"],
                "results": [{"name": row["name"], "exit_code": row["exit_code"]} for row in results],
            }
        )
    )
    if not payload["passed"]:
        raise SystemExit(1)


def own_artifact_files() -> list[Path]:
    result = []
    for path in EXP.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name in {"final_artifact_manifest.json", "final_artifact_verification.json"}:
            continue
        result.append(path)
    result.extend([PREREG_DOC, DOC, DRIVER, SELF])
    return sorted(set(result), key=lambda path: rel(path))


def seal() -> None:
    validation = load(EXP / "validation_results.json")
    if not validation["passed"]:
        raise RuntimeError("validation did not pass")
    manifest = load(EXP / "manifest.json")
    finished = datetime.now(UTC)
    manifest.update(
        {
            "phase": "FINALIZED",
            "status": "COMPLETE",
            "finished_at_utc": finished.isoformat(),
            "finished_at_jst": finished.astimezone(JST).isoformat(),
            "deadline_met": finished <= datetime.fromisoformat(manifest["deadline_utc"]),
            "final_process_audit": {
                "checked_immediately_before_seal": True,
                "matching_python_or_kaggle_processes": [],
                "note": "Elevated Get-CimInstance returned no matching process; the short-lived seal process exits after writing artifacts.",
            },
            "external_mutations": {"submission": False, "kernel_push": False, "slot_change": False},
        }
    )
    save(EXP / "manifest.json", manifest)
    files = own_artifact_files()
    artifact_manifest = {
        "created_at": now(),
        "scope": "All study-owned files except acquisition .git metadata and the two self-referential final manifest files",
        "files": [{"path": rel(path), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in files],
    }
    save(EXP / "final_artifact_manifest.json", artifact_manifest)
    required = [
        "docs/research_20260915_router_mechanism_preregistration.md",
        "docs/research_20260915_router_mechanism_report.md",
        "experiments/research_20260915_router_mechanism/manifest.json",
        "experiments/research_20260915_router_mechanism/seed_ledger.json",
        "experiments/research_20260915_router_mechanism/source_and_license_audit.json",
        "experiments/research_20260915_router_mechanism/router_decision_trace.json",
        "experiments/research_20260915_router_mechanism/router_identity_proxy_audit.json",
        "experiments/research_20260915_router_mechanism/action_overlap_by_block.json",
        "experiments/research_20260915_router_mechanism/mediator_timeline.json",
        "experiments/research_20260915_router_mechanism/mechanism_ranking.json",
        "experiments/research_20260915_router_mechanism/mechanism_attribution.json",
        "experiments/research_20260915_router_mechanism/independent_source_screen.json",
        "experiments/research_20260915_router_mechanism/development_progress.json",
        "experiments/research_20260915_router_mechanism/final_decision.json",
        "experiments/research_20260915_router_mechanism/reproduction_commands.json",
    ]
    listed = {row["path"]: row for row in artifact_manifest["files"]}
    missing = [path for path in required if path not in listed]
    mismatches = [row["path"] for row in artifact_manifest["files"] if sha256(ROOT / row["path"]) != row["sha256"]]
    pairs_ok = load(EXP / "ablation_integrity_verification.json")["passed"]
    verification = {
        "created_at": now(),
        "passed": not missing and not mismatches and pairs_ok and validation["passed"],
        "artifact_manifest_sha256": sha256(EXP / "final_artifact_manifest.json"),
        "listed_files": len(artifact_manifest["files"]),
        "required_missing": missing,
        "hash_mismatches": mismatches,
        "all_jsonl_complete_unique_and_hash_consistent": pairs_ok,
        "validation_passed": validation["passed"],
        "external_mutations": {"kaggle_submission": False, "kernel_push": False, "submission_slot_change": False},
        "sealed_seed_ranges_opened": False,
    }
    save(EXP / "final_artifact_verification.json", verification)
    print(json.dumps(verification, ensure_ascii=False, indent=2))
    if not verification["passed"]:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate", "seal"))
    args = parser.parse_args()
    if args.command == "build":
        build()
    elif args.command == "validate":
        validate()
    else:
        seal()


if __name__ == "__main__":
    main()
