"""Finalize research_20260914_lowcash without opening holdouts or submitting."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import statistics
import sys
import tarfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "experiments/research_20260914_lowcash"
EVAL = ROOT / "data/evaluation/research_20260914_lowcash"
OLD_EVAL = ROOT / "data/evaluation/research_20260911_continuations/v115p_immediate/development/pairs.jsonl"
CHECKPOINTS = (248, 288, 360, 432, 576, 672, 719)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def rows(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf8").splitlines() if x.strip()]


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def replay(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def obs(rep, step, seat):
    value = rep["steps"][step][seat]["observation"]
    if isinstance(value, str):
        value = json.loads(value)
    return value


def semantic_steps(rep):
    """Discard runner timing/log metadata while retaining all game semantics."""
    def clean_observation(value):
        if isinstance(value, str):
            value = json.loads(value)
        value = dict(value or {})
        value.pop("remainingOverageTime", None)
        return value

    return [[{
        "observation": clean_observation(state.get("observation")),
        "action": state.get("action"),
        "reward": state.get("reward"),
        "status": state.get("status"),
    } for state in step] for step in rep["steps"]]


def product_units(private):
    total = Counter(private.get("shed") or {})
    carried = Counter()
    for inv in private.get("inventories") or []:
        carried.update(inv)
        total.update(inv)
    return total, Counter(private.get("shed") or {}), carried


def terminal_proxy(rep, seat, step):
    from kaggle_environments.envs.kaggriculture import kaggriculture as engine

    value = obs(rep, step, seat)
    private = value["private"]
    total, shed, carried = product_units(private)
    inventory = value["market"]["inventory"]
    params = value["market"].get("params")
    product_names = set(engine.PRODUCTS)
    quotes = {item: engine.market_price(item, inventory[item], params) for item in engine.PRODUCTS}
    gross_shed = sum(shed[item] * quotes[item] for item in product_names)
    gross_carried = sum(carried[item] * quotes[item] for item in product_names)
    unharvested = Counter()
    for row in value["farms"][seat]["tiles"]:
        for tile in row:
            if isinstance(tile, dict) and tile.get("crop") in product_names:
                unharvested[tile["crop"]] += max(0, int(tile.get("yield_units", 0) or 0))
    gross_field = sum(unharvested[item] * quotes[item] for item in product_names)
    return {
        "step": step,
        "decisions_remaining": 719 - step,
        "shed_product_units": sum(shed[i] for i in product_names),
        "carried_product_units": sum(carried[i] for i in product_names),
        "unharvested_current_units": sum(unharvested.values()),
        "gross_quote_shed": gross_shed,
        "gross_quote_carried": gross_carried,
        "gross_quote_field_current_yield": gross_field,
        "limit": "Ignores price impact, opponent orders, order slots, travel, harvest readiness, and labor; at step719 no decisions remain.",
    }


def quantile(values, p):
    values = sorted(values)
    position = p * (len(values) - 1)
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] if lo == hi else values[lo] * (hi-position) + values[hi] * (position-lo)


def lifecycle(rep, seat):
    from scripts.evaluation.lifecycle import analyze_lifecycle
    return analyze_lifecycle(rep, seat, 0)


def main():
    data = rows(EVAL / "discovery/pairs.jsonl")
    assert len(data) == 32
    keys = [(r["lineage_id"], r["seed"], r["seat"]) for r in data]
    assert len(set(keys)) == 32
    assert {r["seed"] for r in data} == set(range(10091011, 10091015))
    assert all(len(replay(r["replay_artifacts"][a])["steps"]) == 720 for r in data for a in ("control", "treatment"))

    old = { (r["lineage_id"], r["seed"], r["seat"]): r for r in rows(OLD_EVAL) }
    reproduction = []
    diagnostics = []
    lifecycle_rows = []
    inventory_rows = []
    lifecycle_path = OUT / "lifecycle_diagnostics.json"
    inventory_path = OUT / "inventory_recoverability.json"
    old_lifecycle = read(lifecycle_path)["rows"] if lifecycle_path.exists() else []
    old_inventory = read(inventory_path)["rows"] if inventory_path.exists() else []
    lifecycle_cache = {(tuple(x["key"]), x["arm"]): x for x in old_lifecycle}
    inventory_cache = {(tuple(x["key"]), x["arm"]): x for x in old_inventory}
    for r in data:
        key = (r["lineage_id"], r["seed"], r["seat"])
        previous = old[key]
        old_rep = replay(previous["replay_artifacts"]["control"])
        control_rep = replay(r["replay_artifacts"]["control"])
        treatment_rep = replay(r["replay_artifacts"]["treatment"])
        same_steps = semantic_steps(old_rep) == semantic_steps(control_rep)
        reproduction.append({"key": key, "old_public_arm": previous["control"], "new_public_arm": r["control"],
                             "public_arm_equal": previous["control"] == r["control"], "all_720_steps_equal": same_steps})
        checkpoints = {}
        for step in CHECKPOINTS:
            arms = {}
            for name, rep in (("control", control_rep), ("treatment", treatment_rep)):
                value = obs(rep, step, r["seat"])
                own = float(value["farms"][r["seat"]]["money"])
                opp = float(value["farms"][1-r["seat"]]["money"])
                arms[name] = {"self": own, "opponent": opp, "lead": own-opp}
            checkpoints[str(step)] = arms
        divergence = r["divergence_audit"]
        diagnostics.append({"key": key, "transition": r["control"]["result"]+"->"+r["treatment"]["result"],
                            "delta": {"self":r["delta_self_coin"],"opponent":r["delta_opponent_coin"],"margin":r["delta_margin"]},
                            "hard_safety": r["candidate_new_major_regressions"], "checkpoints": checkpoints,
                            "first_action": divergence["first_focal_action"],
                            "first_public_observation_divergence_step": divergence["first_public_observation_divergence_step"],
                            "first_opponent_response_step": divergence["first_opponent_response_step"],
                            "opponent_response_lag": divergence["opponent_response_lag"],
                            "market_step": (divergence.get("first_market_divergence") or {}).get("step"),
                            "price_step": (divergence.get("first_price_divergence") or {}).get("step"),
                            "town_step": ((divergence.get("first_state_divergence") or {}).get("town") or {}).get("step")})
        for arm, rep in (("control", control_rep), ("treatment", treatment_rep)):
            cached_life = lifecycle_cache.get((key, arm))
            lifecycle_rows.append(cached_life or {"key":key,"arm":arm,**lifecycle(rep, r["seat"])})
            cached_inventory = inventory_cache.get((key, arm))
            inventory_rows.append(cached_inventory or {"key":key,"arm":arm,"at672":terminal_proxy(rep,r["seat"],672),
                                                       "at719":terminal_proxy(rep,r["seat"],719)})

    save(OUT / "control_reproduction.json", {"created_at":datetime.now(UTC).isoformat(),"pairs":reproduction,
                                              "all_public_arms_equal":all(x["public_arm_equal"] for x in reproduction),
                                              "all_720_steps_equal":all(x["all_720_steps_equal"] for x in reproduction)})
    save(OUT / "paired_diagnostics.json", {"created_at":datetime.now(UTC).isoformat(),"pairs":diagnostics})
    save(OUT / "lifecycle_diagnostics.json", {"created_at":datetime.now(UTC).isoformat(),"rows":lifecycle_rows})
    save(OUT / "inventory_recoverability.json", {"created_at":datetime.now(UTC).isoformat(),"rows":inventory_rows})

    summary = read(EVAL / "discovery/summary.json")
    by_source = {x["lineage_id"]:x for x in summary["matrix"]}
    ancestry = {"psr_kaito_combined":["mooman_e052a","souvik_v4","ggmljs_v16"],
                "qeinstein_independent":["qeinstein_moev2"]}
    ancestry_deltas = {}
    for name, sources in ancestry.items():
        subset = [r for r in data if r["lineage_id"] in sources]
        ancestry_deltas[name] = sum(r["delta_win_score"] for r in subset)/len(subset)
    equal_ancestry = statistics.mean(ancestry_deltas.values())
    lead_to_loss = {}
    for arm in ("control","treatment"):
        lead_to_loss[arm] = {str(step):sum(d["checkpoints"][str(step)][arm]["lead"] > 0 and d["transition"].split("->")[0 if arm=="control" else 1] == "loss" for d in diagnostics) for step in CHECKPOINTS}
    response_lags = [d["opponent_response_lag"]["from_first_public_signal"] for d in diagnostics if d["opponent_response_lag"]]
    life_aggregate = {}
    for arm in ("control","treatment"):
        selected = [x for x in lifecycle_rows if x["arm"] == arm]
        counts = Counter(); units = Counter(); harvest = Counter()
        for x in selected:
            counts.update(x["counts"]); units.update(x["lost_current_units"]); harvest.update(x["successful_harvest_units"])
        life_aggregate[arm] = {"counts":dict(counts),"lost_current_units":dict(units),"successful_harvest_units":dict(harvest)}
    inventory_aggregate = {}
    for arm in ("control","treatment"):
        selected = [x for x in inventory_rows if x["arm"]==arm]
        inventory_aggregate[arm] = {point:{field:statistics.mean([x[point][field] for x in selected])
                                                 for field in ("shed_product_units","carried_product_units","unharvested_current_units","gross_quote_shed","gross_quote_carried","gross_quote_field_current_yield")}
                                    for point in ("at672","at719")}

    required = read(OUT / "candidate_freeze.json")["required_file_hashes"]
    required_verification = {name:{"expected":digest,"actual":sha(name),"ok":sha(name)==digest} for name,digest in required.items()}
    replay_hashes = {str(Path(r["replay_artifacts"][a]).relative_to(ROOT)):sha(r["replay_artifacts"][a]) for r in data for a in ("control","treatment")}
    all_results = list(EVAL.rglob("pairs.jsonl"))
    holdout_hits = []
    protected = set(range(10091101,10091113)) | set(range(10091901,10091913))
    for path in all_results:
        for r in rows(path):
            if int(r["seed"]) in protected:
                holdout_hits.append({"file":str(path.relative_to(ROOT)),"seed":r["seed"]})
    with tarfile.open(OUT / "v116_mooman_complete.tar.gz","r:gz") as archive:
        archive_members = sorted(m.name for m in archive.getmembers() if m.isfile())
    artifact = {"created_at":datetime.now(UTC).isoformat(),"required_files":required_verification,
                "required_files_ok":all(x["ok"] for x in required_verification.values()),
                "candidate_archive_sha256":sha(OUT / "v116_mooman_complete.tar.gz"),"candidate_archive_members":archive_members,
                "archive_has_root_main_license_status":all(x in archive_members for x in ["main.py","policy.py","LICENSE","RESEARCH_STATUS.json"]),
                "replay_count":len(replay_hashes),"replay_sha256":replay_hashes,
                "result_files":{str(p.relative_to(ROOT)):sha(p) for p in all_results},"holdout_result_hits":holdout_hits,
                "a_a":{"control":read(EVAL/"aa_control/summary.json"),"candidate":read(EVAL/"aa_candidate/summary.json")},
                "control_reproduction_sha256":sha(OUT/"control_reproduction.json")}
    save(OUT / "final_artifact_verification.json", artifact)

    hard_pairs = [r for r in data if r["candidate_new_major_regressions"]]
    safe = [r for r in data if not r["candidate_new_major_regressions"] and r["behavioral_isolation_valid"]]
    final = {"created_at":datetime.now(UTC).isoformat(),"experiment":"research_20260914_lowcash",
             "production_champion":{"version":"V111","decision":"RETAIN","source_sha256":read(OUT/"initial_audit.json")["identities"]["source"]},
             "candidate":{"version":"v116_mooman_complete","decision":"REJECT","submission":False,
                          "reason":"28/32 raw Safety failures despite positive paired outcome; no post-hoc relaxation"},
             "headline":{"control_wdl":[12,0,20],"candidate_wdl":[20,8,4],"loss_to_win":10,"win_to_loss":0,
                         "delta_win_score":summary["summary"]["delta_win_score"],"seed_block_ci95":summary["seed_block_ci"],
                         "without_self":summary["without_self"],"safe_pairs":len(safe),"unsafe_pairs":len(hard_pairs),
                         "safe_loss_to_win_pairs":sum(r["loss_to_win"] for r in safe),
                         "safe_loss_to_win_seed_blocks":len({r["seed"] for r in safe if r["loss_to_win"]})},
             "source_matrix":by_source,"ancestry":{"mapping":ancestry,"delta_by_group":ancestry_deltas,"equal_ancestry_delta":equal_ancestry,
                                                    "verified_opponent_groups":2},
             "stress":summary["robust_meta"],"bt":summary["bt"],"delta_margin_p10":quantile([r["delta_margin"] for r in data],.1),
             "lead_to_loss":lead_to_loss,"opponent_response":{"median_lag_from_public_signal":statistics.median(response_lags),
                                                               "min":min(response_lags),"max":max(response_lags)},
             "lifecycle":life_aggregate,"inventory_proxy":inventory_aggregate,"safety":{"pairs":len(hard_pairs),"reasons":summary["safety_reasons"]},
             "mechanism_judgment":{"low_cash_contract":"NOT_IMPLEMENTED: 8 target losses had no failed self BUY/HIRE in t216-360 and no t248 Cow2 request",
                                   "complete_policy":"Strong total-policy value on this spent panel; component causality not identified",
                                   "selector":"NOT_STARTED: safe oracle has only one independent L->W seed block"},
             "qualification":{"E4":False,"E5":False,"fresh":"SEALED","promotion":"NOT_OPENED",
                              "failures":["raw Safety failures", "only 2 verified opponent ancestry groups", "4 spent seed blocks", "safe L->W only one seed block"]},
             "next_research":"Isolate mooman complete-policy value into safe components or repair concrete contract failures, then re-preregister and evaluate; do not tune a selector on this unsafe library.",
             "limits":["Spent 4-seed, 4-source local panel; not a Kaggle Rating estimate", "Both seats of one seed are one block",
                       "Opponent actions respond after public divergence; coin mediation is total-policy, not a single action effect"]}
    save(OUT / "final_decision.json", final)
    print(json.dumps({"decision":final["candidate"]["decision"],"headline":final["headline"],"artifacts_ok":artifact["required_files_ok"],"holdout_hits":holdout_hits},ensure_ascii=False,indent=2))


def write_manifest():
    paths = [
        ROOT / "docs/research_20260914_preregistration.md",
        ROOT / "docs/research_20260914_report.md",
        ROOT / "scripts/research_20260914.py",
        ROOT / "scripts/finalize_research_20260914.py",
        OUT / "manifest.json",
        OUT / "initial_audit.json",
        OUT / "candidate_freeze.json",
        OUT / "economy_summary.json",
        OUT / "control_reproduction.json",
        OUT / "paired_diagnostics.json",
        OUT / "lifecycle_diagnostics.json",
        OUT / "inventory_recoverability.json",
        OUT / "final_decision.json",
        OUT / "final_artifact_verification.json",
        OUT / "validation.json",
        OUT / "v116_mooman_complete.tar.gz",
        EVAL / "aa_control/summary.json",
        EVAL / "aa_candidate/summary.json",
        EVAL / "pilot/summary.json",
        EVAL / "discovery/summary.json",
        EVAL / "discovery/pairs.jsonl",
        ROOT / "agents/v116_mooman_complete/research_decision.json",
    ]
    value = {
        "created_at": datetime.now(UTC).isoformat(),
        "files": {str(path.relative_to(ROOT)): {"sha256": sha(path), "bytes": path.stat().st_size} for path in paths},
        "replay_hashes_stored_in": "experiments/research_20260914_lowcash/final_artifact_verification.json",
        "submission": "NOT_PERFORMED",
        "fresh": "SEALED_UNOPENED",
    }
    save(OUT / "final_artifact_manifest.json", value)
    print(json.dumps({"files": len(paths), "manifest": str(OUT / "final_artifact_manifest.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
