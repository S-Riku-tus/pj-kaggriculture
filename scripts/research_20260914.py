"""New research run, reusing frozen evaluation core; never submits to Kaggle."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "experiments/research_20260914_lowcash"
EVAL = ROOT / "data/evaluation/research_20260914_lowcash"
OLD = ROOT / "experiments/research_20260910"
PRIOR = ROOT / "experiments/research_20260911_continuations"
ENGINE = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"


def now():
    return datetime.now(UTC).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.{time.time_ns()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf8").splitlines() if line.strip()]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL).decode("utf8").strip()


def identity():
    import importlib.metadata

    result = {"source": sha(ROOT / "agents/v111/main.py"),
              "archive": sha(OLD / "champion_v111.tar.gz"), "engine": sha(ENGINE)}
    assert result == {"source": "699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660",
                      "archive": "85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e",
                      "engine": "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e"}
    result["engine_version"] = importlib.metadata.version("kaggle-environments")
    result["engine_json"] = sha(ENGINE.with_suffix(".json"))
    result["evaluation_core"] = {p.name: sha(p) for p in (ROOT / "scripts/evaluation").glob("*.py")}
    return result


def audit():
    target = OUT / "initial_audit.json"
    if target.exists():
        raise SystemExit("Audit already frozen")
    before = {name: sha(ROOT / name) for name in git("ls-files").splitlines() if (ROOT / name).is_file()}
    before.update({name: sha(ROOT / name) for name in read(OUT / "manifest.json")["initial_dirty_files_preserved"]})
    protected = set(range(10091101, 10091113)) | set(range(10091901, 10091913))
    proposed = set(range(10091421, 10091437))
    files = subprocess.check_output(["rg", "--files", "--hidden", "-g", "!.git", "-g", "!.venv",
                                    "-g", "!vendor", "-g", "!node_modules"], cwd=ROOT).decode("utf8").splitlines()
    hits, record_audit, used = [], [], set()
    tokens = [str(n).encode() for n in sorted(protected | proposed)]
    for name in files:
        path = ROOT / name
        if path.suffix.lower() in {".jsonl", ".json", ".py", ".md", ".log", ".csv", ".txt"}:
            data = path.read_bytes()
            found = [t.decode() for t in tokens if t in data]
            if found:
                hits.append({"file": name, "tokens": found})
        if path.suffix == ".jsonl" and "opponent_pool" not in name:
            seen, partial, duplicate = set(), [], []
            for i, line in enumerate(path.read_text(encoding="utf8").splitlines()):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    partial.append(i + 1)
                    continue
                seed = value.get("requested_seed", value.get("seed"))
                if isinstance(seed, int):
                    used.add(seed)
                key = json.dumps([value.get("phase"), value.get("lineage_id", value.get("a")),
                                  value.get("b"), seed, value.get("seat")])
                if seed is not None and key in seen:
                    duplicate.append(i + 1)
                seen.add(key)
            record_audit.append({"file": name, "sha256": sha(path), "unique_keys": len(seen),
                                 "partial_lines": partial, "duplicate_lines": duplicate})
    old = read(PRIOR / "final_decision.json")
    evidence = read(ROOT / "data/analysis/research_reassessment_20260914/evidence_v2.json")
    input_mismatch = [name for name, digest in evidence["input_sha256"].items() if sha(ROOT / name) != digest]
    result = {"created_at": now(), "head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
              "status": git("status", "--short"), "identities": identity(), "before_hashes": before,
              "prior_status": old["overall"], "prior_evidence_input_mismatches": input_mismatch,
              "prior_confirmed_contexts": evidence["unique_baseline_contexts"],
              "process_audit": "Escalated read-only Win32_Process query: no Python/Kaggle process at startup",
              "repository_text_seed_hits": hits, "jsonl_audit": record_audit,
              "used_record_seeds": sorted(used), "protected_record_overlap": sorted(used & protected),
              "proposed_confirmation_overlap": sorted(used & proposed),
              "holdout_scope_limit": "All repository text excluding .git/.venv/vendor/node_modules scanned; opaque archives and compressed replays not inferred unused from this alone. Inspect matching reservation/usage files before any holdout opening.",
              "initial_dirty_preserved": read(OUT / "manifest.json")["initial_dirty_files_preserved"]}
    save(target, result)
    assert not input_mismatch
    print(json.dumps({k: result[k] for k in ["created_at", "identities", "protected_record_overlap", "proposed_confirmation_overlap"]}), flush=True)


def refresh():
    from scripts import acquire_research_field_20260910 as acquisition
    import requests

    acquisition.OUT = OUT / "remote" / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    for name, endpoint, payload in [
        ("leaderboard", "competitions.LeaderboardService/GetLeaderboard", {"competitionId": 147734}),
        ("our_team", "competitions.SubmissionService/ListTeamPublicSubmissions", {"teamId": 16749257}),
    ]:
        acquisition.fetch(name, endpoint, payload)
    url = "https://api.github.com/search/repositories?q=kaggriculture&sort=updated&per_page=50"
    response = requests.get(url, timeout=45)
    save(acquisition.OUT / "github_search.json", {"fetched_at": now(), "url": url,
                                                "status": response.status_code, "data": response.json()})
    print(str(acquisition.OUT), flush=True)


def replay(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def trace_turn(rep, step):
    """Instrument original market functions; retain old helper and compare both paths."""
    from scripts.evaluation import safety
    from scripts.evaluation.replay import action, observation

    engine = safety.engine
    obs = [observation(rep, step, p) for p in (0, 1)]
    farms = copy.deepcopy(obs[0]["farms"])
    privates = [copy.deepcopy(o["private"]) for o in obs]
    market = copy.deepcopy(obs[0]["market"])
    actions = [action(rep, step, p) for p in (0, 1)]
    cash = [Counter(), Counter()]
    harvest = [Counter(), Counter()]
    work = [[], []]
    original = {name: getattr(engine, name) for name in ["_apply_unit_action", "_do_hire", "_do_buy_land", "_commit_unit"]}

    def player(farm):
        return 0 if farm is farms[0] else 1

    def unit(farm, private, index, act, *args):
        p = player(farm)
        before = farm["money"]
        inv_before = Counter(private["shed"])
        for inv in private["inventories"]:
            inv_before.update(inv)
        original["_apply_unit_action"](farm, private, index, act, *args)
        op = act[0] if isinstance(act, list) and act else "MALFORMED"
        cash[p][op] += farm["money"] - before
        if op == "HARVEST":
            inv_after = Counter(private["shed"])
            for inv in private["inventories"]:
                inv_after.update(inv)
            harvest[p].update(inv_after - inv_before)
        if 240 <= step <= 280 and op in {"BUY_ANIMAL", "PICKUP", "PLACE", "BUILD_COOP", "BUILD_PASTURE", "FEED", "CARE"}:
            work[p].append({"unit": index, "action": act, "cash_delta": farm["money"] - before})

    def hire(farm, private, *args):
        before = farm["money"]
        original["_do_hire"](farm, private, *args)
        cash[player(farm)]["HIRE"] += farm["money"] - before

    def land(farm, *args):
        before = farm["money"]
        original["_do_buy_land"](farm, *args)
        cash[player(farm)]["BUY_LAND"] += farm["money"] - before

    def commit(op, item, price, farm, private, *args):
        before = farm["money"]
        ok = original["_commit_unit"](op, item, price, farm, private, *args)
        cash[player(farm)][op + ":" + item] += farm["money"] - before
        return ok

    try:
        for name, fn in zip(original, [unit, hire, land, commit], strict=True):
            setattr(engine, name, fn)
        field_events = safety._apply_fields(farms, privates, actions, obs[0].get("day", step // 24))
        projected_shed = copy.deepcopy([p["shed"] for p in privates])
        helper_input = copy.deepcopy((farms, privates, market))
        state = [SimpleNamespace(observation=SimpleNamespace(farms=farms, private=privates[p], market=market),
                                 action=actions[p]) for p in (0, 1)]
        engine._process_market(state, SimpleNamespace(configuration=rep["configuration"]))
    finally:
        for name, fn in original.items():
            setattr(engine, name, fn)
    hf, hp, hm = helper_input
    market_events = safety._simulate_market(hf, hp, hm, actions)
    assert (hf, hp, hm) == (farms, privates, market), (step, "helper differs from native market")
    result = []
    for p in (0, 1):
        actual = observation(rep, step + 1, p)["farms"][p]["money"] - obs[p]["farms"][p]["money"]
        result.append({"step": step, "cash": {k: v for k, v in cash[p].items() if v},
                       "cash_delta": actual, "residual": actual - sum(cash[p].values()),
                       "native_next_cash_matches": farms[p]["money"] == observation(rep, step + 1, p)["farms"][p]["money"],
                       "harvest": dict(harvest[p]), "events": field_events[p] + market_events[p],
                       "field_work": work[p], "projected_shed": projected_shed[p], "market": actions[p].get("market", [])})
    return result


def snapshot(rep, step, p):
    from scripts.evaluation.divergence import portfolio, workers
    from scripts.evaluation.replay import observation
    obs = observation(rep, step, p)
    farm = obs["farms"][p]
    unharvested = Counter()
    service = Counter()
    for row in farm["tiles"]:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            name = tile.get("crop", tile.get("animal"))
            if name:
                unharvested[name] += tile.get("yield_units", 0)
                service["needs_water"] += tile.get("kind") == "PLANT" and not tile.get("watered_today", False)
                service["needs_feed"] += bool(tile.get("animal")) and not tile.get("fed_today", False)
    return {"money": farm["money"], "margin": farm["money"] - obs["farms"][1-p]["money"],
            "portfolio": portfolio(farm), "workers": workers(farm), "private": obs["private"],
            "unharvested_units": dict(unharvested), "service": dict(service),
            "market": obs["market"], "town": obs["town"]}


def economy():
    source = ROOT / "data/evaluation/research_20260911_continuations/v115p_immediate/development/pairs.jsonl"
    dataset = rows(source)
    target = OUT / "economy"
    target.mkdir(exist_ok=True)
    summaries = []
    for row in sorted(dataset, key=lambda r: (r["lineage_id"], r["seed"], r["seat"])):
        key = f"{row['lineage_id']}_{row['seed']}_{row['seat']}"
        path = target / (key + ".json")
        if path.exists():
            result = read(path)
        else:
            rep = replay(row["replay_artifacts"]["control"])
            seat = row["seat"]
            # All baseline contexts receive the same t216-360 audit; both players observed offline.
            turns = [trace_turn(rep, step) for step in range(216, 360)]
            ledgers = {}
            for start, end in [(216, 248), (248, 288), (288, 360), (216, 360)]:
                arms = []
                for p in [seat, 1-seat]:
                    cash, harvest, failures = Counter(), Counter(), []
                    for t in turns[start-216:end-216]:
                        cash.update(t[p]["cash"])
                        harvest.update(t[p]["harvest"])
                        failures += [{"step": t[p]["step"], **e} for e in t[p]["events"] if e["kind"] != "market_commit" or e.get("committed", 0) < e.get("requested", 0)]
                    arms.append({"cash": dict(cash), "cash_delta": sum(t[p]["cash_delta"] for t in turns[start-216:end-216]),
                                 "residual": sum(t[p]["residual"] for t in turns[start-216:end-216]),
                                 "harvest_units": dict(harvest), "failures": failures})
                ledgers[f"{start}:{end}"] = {"self": arms[0], "opponent": arms[1]}
            t248 = turns[32][seat]
            purchases = [i for i,o in enumerate(t248["market"]) if o == ["BUY_ANIMAL", "COW", 2]]
            snap248 = snapshot(rep, 248, seat)
            conditions = {"exact_cow2_order": len(purchases) == 1, "order_within_cap": bool(purchases) and purchases[0] < 10,
                          "cash_at_least_1500": snap248["money"] >= 1500,
                          "projected_shed_at_most_98": sum(t248["projected_shed"].values()) <= 98,
                          "no_fallback": row["agent_trace"]["control"]["fallback_steps"] == 0,
                          "standard_config": all(rep["configuration"].get(k,v) == v for k,v in {"boardSize":10,"turnsPerDay":24,"shedCapacity":100,"maxMarketOrdersPerTurn":10}.items())}
            result = {"key": key, "lineage": row["lineage_id"], "seed": row["seed"], "seat": seat,
                      "baseline": row["control"], "input_replay_sha256": sha(row["replay_artifacts"]["control"]),
                      "configuration": rep["configuration"], "ledgers": ledgers, "old_managed_conditions": conditions,
                      "condition_limit": "no_fallback from full-run trace; conservative, check exact step if it is false",
                      "snapshots": {str(t): snapshot(rep,t,seat) for t in [216,240,248,249,264,288,312,336,360,432,576,719]},
                      "turns": turns, "zero_residual_all_steps": all(t[p]["residual"] == 0 and t[p]["native_next_cash_matches"] for t in turns for p in (0,1))}
            save(path, result)
        summaries.append({k: result[k] for k in ["key","lineage","seed","seat","baseline","ledgers","old_managed_conditions","zero_residual_all_steps"]})
        print(key, result["baseline"]["result"], "cash", result["snapshots"]["248"]["money"],
              "failed_conditions", [k for k,v in result["old_managed_conditions"].items() if not v],
              "residual_ok", result["zero_residual_all_steps"], flush=True)
    save(OUT / "economy_summary.json", {"created_at": now(), "contexts": summaries,
                                       "inference_limit": "Offline resource accounting; no causal intervention evidence"})


def members(archive):
    with tarfile.open(archive, "r:gz") as handle:
        return {m.name: handle.extractfile(m).read() for m in handle.getmembers() if m.isfile()}


def freeze():
    from scripts.evaluation.runner import extract_archive
    from scripts.research_20260910 import package

    target = OUT / "candidate_freeze.json"
    if target.exists():
        raise SystemExit("Candidate already frozen")
    version = "v116_mooman_complete"
    registry = read(OLD / "source_registry.json")
    source = next(s for s in registry["sources"] if s["candidate_id"] == "mooman_e052a")
    archive = ROOT / source["archive"]
    assert sha(archive) == source["archive_sha256"]
    contents = members(archive)
    assert hashlib.sha256(contents["policy.py"]).hexdigest() == source["source_sha256"]
    assert b"MIT License" in contents["LICENSE"]
    # Preserve native policy; use the same tested adapter plus a last callable for file entry.
    contents["main.py"] += b'\n\ndef _kaggle_submission_entrypoint(obs, configuration=None):\n    return agent(obs, configuration)\n'
    contents["RESEARCH_STATUS.json"] = json.dumps({"version": version, "status": "RESEARCH_ONLY_UNEVALUATED",
                                                  "source": source["source_repository"], "revision": source["source_revision"],
                                                  "native_entrypoint": "policy.agent_entry", "submitted": False}).encode()
    directory = ROOT / "agents" / version
    directory.mkdir(exist_ok=False)
    for name, data in contents.items():
        file = directory / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    save(directory / "submission_manifest.json", {"files": [{"target": n, "source": n} for n in sorted(contents)]})
    new_archive = OUT / (version + ".tar.gz")
    package(contents, new_archive)
    extract_archive(new_archive, OUT / "runtime" / version)
    extract_archive(OLD / "champion_v111.tar.gz", OUT / "runtime/control")
    frozen_files = {str(ENGINE): sha(ENGINE), str(ENGINE.with_suffix(".json")): sha(ENGINE.with_suffix(".json")),
                    str(ROOT / "docs/research_20260914_preregistration.md"): sha(ROOT / "docs/research_20260914_preregistration.md")}
    for path in (ROOT / "scripts/evaluation").glob("*.py"):
        frozen_files[str(path)] = sha(path)
    runtime_sets = {}
    for name, path, runtime in [("control", OLD / "champion_v111.tar.gz", OUT / "runtime/control"),
                                (version, new_archive, OUT / "runtime" / version),
                                *[(s["candidate_id"], ROOT / s["archive"], Path(ROOT / s["entrypoint"]).parent) for s in registry["sources"]]]:
        content = members(path)
        for member, data in content.items():
            assert (runtime / member).read_bytes() == data, (name, member)
            frozen_files[str(runtime / member)] = hashlib.sha256(data).hexdigest()
        frozen_files[str(path)] = sha(path)
        runtime_sets[name] = {"archive": str(path.relative_to(ROOT)), "archive_sha256": sha(path),
                              "main": str((runtime / "main.py").relative_to(ROOT)),
                              "member_hashes": {n: hashlib.sha256(d).hexdigest() for n,d in content.items()}}
    result = {"created_at": now(), "version": version, "hypothesis": "unmodified complete-policy comparison from initial state",
              "identity": identity(), "source": source, "runtimes": runtime_sets,
              "required_file_hashes": frozen_files, "source_ids": [s["candidate_id"] for s in registry["sources"]],
              "discovery_seeds": list(range(10091011,10091015)), "confirmation_seed_candidates": list(range(10091421,10091437)),
              "isolate_packages": ["kaggriculture"], "fresh": "SEALED", "submission": "DO_NOT_SUBMIT"}
    save(target, result)
    print(json.dumps({"version": version, "archive": str(new_archive), "sha256": sha(new_archive), "files_verified": len(frozen_files)}), flush=True)


def amend_freeze():
    """Record a pre-result evaluator correction and refresh frozen core hashes."""
    path = OUT / "candidate_freeze.json"
    value = read(path)
    assert not list(EVAL.rglob("pairs.jsonl")), "Cannot amend after any paired result"
    amendment = {
        "created_at": now(),
        "reason": "qeinstein dynamically imports kaggriculture.* during play; keep current-game namespace until env.run ends",
        "result_rows_before_amendment": 0,
    }
    value.setdefault("pre_evaluation_amendments", []).append(amendment)
    for core in (ROOT / "scripts/evaluation").glob("*.py"):
        value["required_file_hashes"][str(core)] = sha(core)
    save(path, value)
    print(json.dumps(amendment), flush=True)


def batch(phase, workers=4, aa_candidate=False):
    from scripts.evaluation.runner import run_tasks

    freeze_data = read(OUT / "candidate_freeze.json")
    version = freeze_data["version"]
    runtimes = freeze_data["runtimes"]
    if phase == "aa":
        phase = "aa_candidate" if aa_candidate else "aa_control"
        source_ids, seeds = ["qeinstein_moev2"], [10091011]
    elif phase == "pilot":
        source_ids, seeds = ["mooman_e052a", "qeinstein_moev2"], [10091011]
    elif phase == "discovery":
        source_ids, seeds = freeze_data["source_ids"], freeze_data["discovery_seeds"]
    elif phase == "confirmation":
        plan = read(OUT / "confirmation_plan.json")
        assert plan["candidate_freeze_sha256"] == sha(OUT / "candidate_freeze.json")
        source_ids, seeds = plan["source_ids"], plan["seeds"]
    else:
        raise ValueError(phase)
    protected = set(range(10091101,10091113)) | set(range(10091901,10091913))
    assert not protected.intersection(seeds), "This command cannot open holdouts"
    required = dict(freeze_data["required_file_hashes"])
    required[str(OUT / "candidate_freeze.json")] = sha(OUT / "candidate_freeze.json")
    for filename, expected in required.items():
        assert sha(filename) == expected, filename
    protocol = {"phase": phase, "source_ids": source_ids, "seeds": seeds, "seats": [0,1],
                "candidate_freeze_sha256": sha(OUT / "candidate_freeze.json"),
                "driver_sha256": sha(Path(__file__)), "configuration": "frozen standard defaults + episodeSteps=720 + requested seed",
                "isolate_packages": freeze_data["isolate_packages"], "arm_mode": "aa" if phase.startswith("aa") else "complete_policy"}
    phase_dir = EVAL / phase
    plan_path = phase_dir / "plan.json"
    result_path = phase_dir / "pairs.jsonl"
    if plan_path.exists():
        if not result_path.exists():
            save(plan_path, protocol)
        else:
            assert read(plan_path) == protocol, "Resume identity mismatch"
    else:
        save(plan_path, protocol)
    provenance = {"phase_plan_sha256": sha(plan_path), "candidate_freeze_sha256": sha(OUT / "candidate_freeze.json"),
                  "engine_sha256": freeze_data["identity"]["engine"], "configuration_schema_sha256": freeze_data["identity"]["engine_json"]}
    required[str(plan_path)] = sha(plan_path)
    existing = rows(result_path) if result_path.exists() else []
    key = lambda r: (r["lineage_id"], r["seed"], r["seat"])
    seen = set()
    for row in existing:
        assert key(row) not in seen, "Duplicate result key"
        seen.add(key(row))
        assert row["provenance"] == provenance, "Cached result identity mismatch"
        assert all(row["safety"][a]["completed_720"] for a in ["control","treatment"]), "Incomplete cached result"
    tasks = []
    for source_id in source_ids:
        for seed in seeds:
            for seat in [0,1]:
                if (source_id,seed,seat) in seen:
                    continue
                control = version if phase == "aa_candidate" else "control"
                treatment = "control" if phase == "aa_control" else version
                tasks.append({"control_main": str(ROOT / runtimes[control]["main"]),
                              "treatment_main": str(ROOT / runtimes[treatment]["main"]),
                              "opponent_main": str(ROOT / runtimes[source_id]["main"]),
                              "seed":seed,"seat":seat,"episode_steps":720,"phase":phase,"lineage_id":source_id,
                              "opponent_name":source_id,"opponent_tier":"Gold frozen old source","meta_weight":1/len(source_ids),
                              "intended_action_step":0,"inherited_transaction_step":248,
                              "intervention_kind":"route_choice" if phase.startswith("aa") else "complete_policy",
                              "strict_all_step_safety":True,"save_all_replays":True,"replay_dir":str(phase_dir / "replays"),
                              "isolate_packages":freeze_data["isolate_packages"],"provenance":provenance,"required_file_hashes":required})
    started = time.perf_counter()
    manifest = read(OUT / "manifest.json")
    manifest.update({"phase":phase,"running":[{"pid":os.getpid(),"phase":phase,"log":str(OUT / (phase+'.log'))}],
                     "next_action":"Each completed pair is appended with frozen provenance; summarize after phase completion"})
    save(OUT / "manifest.json", manifest)

    def progress(done,total,row):
        with result_path.open("a",encoding="utf8") as handle:
            handle.write(json.dumps(row,ensure_ascii=False)+"\n")
            handle.flush()
            os.fsync(handle.fileno())
        save(phase_dir / "progress.json", {"updated_at":now(),"pid":os.getpid(),"new_completed":done,"new_total":total,
                                           "reused":len(existing),"elapsed_seconds":time.perf_counter()-started,
                                           "last_key":key(row),"worker_pid":row.get("worker_pid")})
        print(json.dumps({"done":done,"total":total,"source":row["lineage_id"],"seed":row["seed"],"seat":row["seat"],
                          "C":row["control"]["result"],"T":row["treatment"]["result"],"delta_margin":row["delta_margin"],
                          "safety":row["candidate_new_major_regressions"],"valid":row["behavioral_isolation_valid"],
                          "seconds":row.get("execution_seconds")}),flush=True)
    new = run_tasks(tasks,workers,progress)
    elapsed = time.perf_counter()-started
    timing_path = phase_dir / "runs.jsonl"
    with timing_path.open("a",encoding="utf8") as handle:
        handle.write(json.dumps({"finished_at":now(),"new_pairs":len(new),"reused_pairs":len(existing),"wall_seconds":elapsed,
                                 "workers":workers,"new_games_per_minute":120*len(new)/elapsed if new else None})+"\n")
    summarize(phase)


def summarize(phase):
    from scripts.evaluation.statistics import summarize_pairs, pairwise_payoff_matrix, robust_meta, bradley_terry_diagnostic, _bootstrap_lineage_ci
    import random

    dataset = rows(EVAL / phase / "pairs.jsonl")
    safe = lambda r: r["behavioral_isolation_valid"] and not r["candidate_new_major_regressions"] and not r["candidate_incident_classification"]["treatment_delivery_failure"]
    loss = [r for r in dataset if r["control"]["result"] == "loss"]
    safe_rows = [r for r in dataset if safe(r)]
    weights = {s:1/len({r["lineage_id"] for r in dataset}) for s in {r["lineage_id"] for r in dataset}}
    matrix = pairwise_payoff_matrix(dataset, 10000, 20260914)
    result = {"created_at":now(),"summary":summarize_pairs(dataset),"matrix":matrix,
              "robust_meta":robust_meta(matrix,weights,0.2),"bt":bradley_terry_diagnostic(dataset),
              "seed_block_ci":_bootstrap_lineage_ci(dataset,lambda r:r["delta_win_score"],10000,random.Random(20260914)),
              "safety_pairs":sum(bool(r["candidate_new_major_regressions"]) for r in dataset),
              "safety_reasons":dict(Counter(x for r in dataset for x in r["candidate_new_major_regressions"])),
              "invalid_pairs":sum(not r["behavioral_isolation_valid"] for r in dataset),
              "completed_pairs":sum(all(r["safety"][a]["completed_720"] for a in ["control","treatment"]) for r in dataset),
              "activation":{"eligible":len(dataset),"active":sum(r["incremental_treatment"] for r in dataset),"safe":len(safe_rows),
                            "baseline_losses":len(loss),"loss_active":sum(r["incremental_treatment"] for r in loss),"loss_safe":sum(safe(r) for r in loss)},
              "safe_oracle":{"mean_gain":sum(max(0,r["delta_win_score"]) if safe(r) else 0 for r in dataset)/len(dataset),
                             "safe_loss_to_win":sum(r["loss_to_win"] for r in safe_rows),
                             "limit":"in-sample optimistic diagnostic, not deployable score; event-level safety supplement pending"},
              "transitions":dict(Counter(r["control"]["result"]+"->"+r["treatment"]["result"] for r in dataset)),
              "without_self":summarize_pairs([r for r in dataset if r["lineage_id"]!="mooman_e052a"]),
              "without_psr_kaito":summarize_pairs([r for r in dataset if r["lineage_id"]=="qeinstein_moev2"])}
    save(EVAL / phase / "summary.json",result)
    print(json.dumps({"phase":phase,"summary":result["summary"],"safety_pairs":result["safety_pairs"],"oracle":result["safe_oracle"]}),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["audit", "refresh", "economy", "freeze", "amend_freeze", "batch", "summarize"])
    parser.add_argument("--phase", default="discovery", choices=["aa", "aa_control", "aa_candidate", "pilot", "discovery", "confirmation"])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--aa-candidate", action="store_true")
    args = parser.parse_args()
    if args.command == "batch":
        batch(args.phase,args.workers,args.aa_candidate)
    elif args.command == "summarize":
        summarize(args.phase)
    else:
        globals()[args.command]()


if __name__ == "__main__":
    main()
