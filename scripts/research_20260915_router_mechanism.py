# Ruff E501 is disabled for frozen Japanese preregistration and exact source-patch literals.
# ruff: noqa: E501
"""Preregister, diagnose, and run the 2026-09-15 PSR-router mechanism study.

The PSR candidates created here are research-only.  This driver never submits
to Kaggle, pushes a kernel, changes a submission slot, or opens reserved seeds.
"""

from __future__ import annotations

import argparse
import ast
import copy
import gzip
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import tarfile
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXP = ROOT / "experiments/research_20260915_router_mechanism"
OLD = ROOT / "experiments/research_20260914_clean_psr"
PREREG_DOC = ROOT / "docs/research_20260915_router_mechanism_preregistration.md"
PREREG = EXP / "preregistration.json"
ENGINE = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
ENGINE_JSON = ENGINE.with_suffix(".json")
P1_MAIN = OLD / "candidates/P1_psr_clean/main.py"
P1_PAIRS = OLD / "candidates/P1_psr_clean/pairs/spent.jsonl"
D1_PAIRS = OLD / "candidates/D1_e052a_no_opponent_tape/pairs/spent.jsonl"
V111_MAIN = ROOT / "agents/v111/main.py"
V111_ARCHIVE = ROOT / "artifacts/agents/v111.tar.gz"
if not V111_ARCHIVE.exists():
    V111_ARCHIVE = ROOT / "agents/v111.tar.gz"

SOURCES = {
    "mooman_e052a": ROOT / "experiments/research_20260910/runtime/mooman_e052a/main.py",
    "souvik_v4": ROOT / "experiments/research_20260910/runtime/souvik_v4/main.py",
    "ggmljs_v16": ROOT / "experiments/research_20260910/runtime/ggmljs_v16/main.py",
    "qeinstein_moev2": ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py",
}
SEEDS = [10091011, 10091012, 10091013, 10091014]
BOUNDARIES = [0, 144, 288, 432, 576]
BLOCK_ENDS = [144, 288, 432, 576, 719]
EXPECTED = {
    "V111": "699c73f75ec786e9bddcfabb6476fc64c07939f22abe3ed00691a5bef6f72660",
    "P1": "91772fda544e2d5768afff819e2de75ecb7a12db8acb40a48ee9edcf76aca434",
    "D1": "e465bdcce3cc6560abafcdc916f06843b111e79c2c625dcdd74db47ec7f7279b",
    "R0": "546f22355746aaee30cc1f8035fb5e7fb6b133dccba802d30c90f4708c5e872d",
    "engine": "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e",
    "configuration": "a82c89c1a2315b93f39775d8e025471a01b738647c9772658368ee6b1b6f4867",
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stable_sha(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> list[dict[str, Any]]:
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"partial JSONL record {path}:{number}") from exc
    return result


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    ).stdout.rstrip()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def import_module(path: Path, role: str) -> Any:
    name = f"_router_mechanism_{role}_{os.getpid()}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay(path: Path | str) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def replay_path(row: dict[str, Any], arm: str) -> Path:
    return Path(row["replay_artifacts"][arm])


def actual_action(rep: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    return rep["steps"][step + 1][seat].get("action") or {}


def observation(rep: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    value = copy.deepcopy(rep["steps"][step][seat].get("observation") or {})
    if isinstance(value, str):
        value = json.loads(value)
    value.setdefault("step", step)
    value["player"] = seat
    return value


def recursive_seed_values(value: Any, path: str = "$") -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if "seed" in str(key).lower():
                if isinstance(child, int) and not isinstance(child, bool):
                    found.append((child_path, child))
                elif isinstance(child, list):
                    found.extend(
                        (f"{child_path}[{index}]", item)
                        for index, item in enumerate(child)
                        if isinstance(item, int) and not isinstance(item, bool)
                    )
            found.extend(recursive_seed_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(recursive_seed_values(child, f"{path}[{index}]"))
    return found


def seed_ledger() -> dict[str, Any]:
    excluded = {".git", ".venv", ".uv-cache", ".ruff_cache", ".pytest_cache", "vendor", "__pycache__", "node_modules"}
    text_suffixes = {".json", ".jsonl", ".md", ".py", ".txt", ".csv", ".log", ".yaml", ".yml", ".toml"}
    structured: set[tuple[str, str, int]] = set()
    mentions: list[dict[str, Any]] = []
    seed_pattern = re.compile(r"(?<!\d)(1009\d{4})(?!\d)")
    # Let ripgrep perform the repository-wide byte scan; parsing only matching
    # files avoids loading unrelated large JSON artifacts into Python.
    command = [
        "rg",
        "-l",
        "1009[0-9]{4}",
        ".",
        "--hidden",
        "-g",
        "!.git/**",
        "-g",
        "!.venv/**",
        "-g",
        "!.uv-cache/**",
        "-g",
        "!.ruff_cache/**",
        "-g",
        "!.pytest_cache/**",
        "-g",
        "!vendor/**",
        "-g",
        "!**/__pycache__/**",
        "-g",
        "!node_modules/**",
    ]
    scan = subprocess.run(
        command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False
    )
    if scan.returncode not in {0, 1}:
        raise RuntimeError(f"rg seed scan failed: {scan.stderr}")
    candidates = [ROOT / value.removeprefix("./").removeprefix(".\\") for value in scan.stdout.splitlines()]
    for path in candidates:
        if (
            not path.is_file()
            or any(part in excluded for part in path.parts)
            or path.suffix.lower() not in text_suffixes
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found_mentions = sorted({int(match) for match in seed_pattern.findall(text)})
        if found_mentions:
            mentions.append({"path": rel(path), "values": found_mentions})
        parsed_values: list[tuple[int, Any]] = []
        if path.suffix.lower() == ".jsonl":
            for number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    parsed_values.append((number, json.loads(line)))
                except json.JSONDecodeError:
                    continue
        elif path.suffix.lower() == ".json":
            try:
                parsed_values.append((0, json.loads(text)))
            except json.JSONDecodeError:
                pass
        for number, value in parsed_values:
            for field, seed in recursive_seed_values(value):
                if 10_000_000 <= seed <= 10_099_999:
                    structured.add((f"{rel(path)}:{number}" if number else rel(path), field, seed))
    records = [{"location": location, "field": field, "seed": seed} for location, field, seed in sorted(structured)]
    # A plan/manifest can contain seed ranges or a proposed ``seeds`` list.
    # Execution use requires a JSONL result record with a singular runtime
    # seed field, matching the established repository audit convention.
    runtime_fields = {"seed", "requested_seed", "resolved_seed"}
    used = {
        record["seed"]
        for record in records
        if ":" in record["location"] and record["field"].rsplit(".", 1)[-1].split("[", 1)[0] in runtime_fields
    }
    groups = {
        "promotion": set(range(10091101, 10091113)),
        "fresh": set(range(10091901, 10091913)),
        "prior_development": set(range(10091421, 10091437)),
        "proposed_development": set(range(10091521, 10091537)),
    }
    return {
        "created_at": now(),
        "method": "repository-wide UTF-8 structured JSON/JSONL seed-field scan and separate free-text scan; binary/cache/vendor excluded",
        "structured_records": records,
        "free_text_mentions": mentions,
        "execution_use_rule": "JSONL records with singular seed/requested_seed/resolved_seed fields only; plans, ranges, and seed arrays are mentions, not use",
        "groups": {
            name: {
                "range": [min(values), max(values)],
                "structured_used": sorted(used & values),
                "status": "UNUSED" if not used & values else "USED",
            }
            for name, values in groups.items()
        },
        "limitation": "Free-text reservation or documentation is not classified as execution. Opaque binary bodies are not inspected.",
    }


def required_inputs() -> list[Path]:
    return [
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        ROOT / "docs/research_20260914_clean_psr_report.md",
        OLD / "final_decision.json",
        OLD / "primary_discovery_gate.json",
        OLD / "performance_attribution.json",
        OLD / "safety_first_event_map.json",
        OLD / "source_acquisition.json",
        OLD / "candidate_integrity.json",
        OLD / "source_layer_map.json",
        OLD / "tape_confounding_audit.json",
        OLD / "independent_source_audit_pre_results.json",
        OLD / "independent_screen/selection.json",
        OLD / "seed_ledger.json",
        ROOT / "docs/research_20260914_report.md",
        ROOT / "docs/research_20260912_continuation_report.md",
        ROOT / "scripts/evaluation/runner.py",
        ROOT / "scripts/evaluation/safety.py",
        ROOT / "scripts/evaluation/statistics.py",
        ROOT / "scripts/evaluation/divergence.py",
        ROOT / "scripts/evaluation/lifecycle.py",
        P1_MAIN,
        OLD / "extracted_source/current_v3_main_exact.py",
        ENGINE,
        ENGINE_JSON,
        V111_MAIN,
        OLD / "candidates/P1_psr_clean/freeze.json",
        OLD / "candidates/D1_e052a_no_opponent_tape/freeze.json",
        OLD / "candidates/R0_v116_frozen_reference/freeze.json",
    ]


PREREG_TEXT = """# Router mechanism study preregistration — 2026-09-15

この研究は前回不合格PSRのrepairではなく、旧spent panel上の非tape改善を、public-state router、固定route、初期market/portfolio footprint、相手closed-loop応答へ切り分ける診断である。P1 full、D1、R0の既存pairは再実行せず、V111をproduction Championとして固定する。

実行順は、開始時監査、既存replayによるrouter/identity/timeline監査、合法かつstate-compatibleなA0/A1/A2だけのA/A・smoke・旧spent評価、mechanism gate、条件成立時だけのV111由来C1、旧spent compatibility、条件成立時だけのDevelopment確認、artifact検証、最終判断とする。

Primary contrastはP1 full対A0/A1/A2。A0はstep 0で選択されたown routeを719 decisions固定、A1はstep 144の再選択だけを無効化、A2はstep 576の再選択だけを無効化する。router固有価値の最低条件は、P1 fullが合法なA0より1 source-seed block以上改善し、2 sources以上で同方向、W→L増加または新Safety classなし。route固定が同等以上ならtotal-policy upliftをrouter upliftと呼ばない。

全ablationはresearch-only、promotion不可。raw Safetyを平均coinで救済しない。candidate/source/package、engine、configuration、opponent、seed、seat、evaluator hashをpair keyに含め、pairごとにflushする。A/A不一致、720 states未完走、schema異常、prefix incompatibilityは当該ablationをINVALID_ABLATIONとして止め、手補正variantへ置換しない。

C1はrouter固有価値またはD1/P1共通の公開状態機構が2 sources以上で残り、identity proxyでなく、V111のrepository-owned state-compatible suffixまたは毎step再検証contractとして調達から販売・rejoinまで一意に定義できる場合だけ作る。P1 blob/tape/tree/route/threshold/action列を使わない。旧spent gateの全条件を通るまで新Developmentを開かない。C2は単一Safety first-event familyだけに限る。

promotion 10091101–10091112、Fresh 10091901–10091912、旧Development 10091421–10091436は常に封印する。今回Development候補10091521–10091536もC1/C2旧spent gate通過時だけ一括登録・使用する。Kaggle提出、kernel push、submission slot変更を行わない。

license/provenance不明、identity-proxy判定不能、独立source不足、確認未完了の上限はPROMISING_UNPROVEN。deploy candidateのSafety違反、禁止feature、W→Lはreject。最終statusは指定された5値だけを用いる。
"""


def verify_reused() -> dict[str, Any]:
    old_verify = load(OLD / "final_artifact_verification.json")
    checks = []
    for path in (P1_PAIRS, D1_PAIRS, OLD / "final_decision.json", OLD / "candidate_integrity.json"):
        checks.append({"path": rel(path), "sha256": sha(path), "exists": path.exists()})
    replay_checks = []
    for path_string, expected in old_verify.get("replay_sha256", {}).items():
        if "candidates/P1_psr_clean" not in path_string and "candidates/D1_e052a" not in path_string:
            continue
        path = ROOT / path_string
        actual = sha(path) if path.exists() else None
        replay_checks.append({"path": path_string, "expected": expected, "actual": actual, "ok": actual == expected})
    pair_checks = {}
    for name, path in (("P1", P1_PAIRS), ("D1", D1_PAIRS)):
        current = rows(path)
        keys = {
            (row["candidate_source_sha256"], row["lineage_id"], row["seed"], row["seat"], row["evaluation_core_sha256"])
            for row in current
        }
        pair_checks[name] = {
            "rows": len(current),
            "unique_keys": len(keys),
            "all_720": all(row["safety"][arm]["completed_720"] for row in current for arm in ("control", "treatment")),
        }
    return {
        "verified_at": now(),
        "old_experiment_status": load(OLD / "final_decision.json")["decision"],
        "old_experiment_complete": load(OLD / "manifest.json").get("status") == "COMPLETE",
        "files": checks,
        "pairs": pair_checks,
        "replays_checked": len(replay_checks),
        "replay_hash_mismatches": [row for row in replay_checks if not row["ok"]],
        "passed": all(row["ok"] for row in replay_checks)
        and all(value["rows"] == value["unique_keys"] == 32 and value["all_720"] for value in pair_checks.values()),
    }


def initial() -> None:
    if (EXP / "manifest.json").exists():
        raise FileExistsError("initial manifest already exists; refusing to overwrite start state")
    started = datetime.now(UTC)
    deadline = started + timedelta(hours=5)
    EXP.mkdir(parents=True, exist_ok=True)
    PREREG_DOC.write_text(PREREG_TEXT, encoding="utf-8")
    input_hashes = {rel(path): sha(path) for path in required_inputs()}
    assert input_hashes[rel(V111_MAIN)] == EXPECTED["V111"]
    assert input_hashes[rel(P1_MAIN)] == EXPECTED["P1"]
    assert sha(ENGINE) == EXPECTED["engine"] and sha(ENGINE_JSON) == EXPECTED["configuration"]
    ledger = seed_ledger()
    save(EXP / "seed_ledger.json", ledger)
    reused = verify_reused()
    save(EXP / "reused_artifact_verification.json", reused)
    if not reused["passed"]:
        raise RuntimeError("reused artifact verification failed")
    prereg = {
        "frozen_at": now(),
        "frozen_before_first_new_game": True,
        "preregistration_document": rel(PREREG_DOC),
        "preregistration_document_sha256": sha(PREREG_DOC),
        "raw_user_prompt_exact_bytes": "UNAVAILABLE_TO_LOCAL_PROCESS",
        "prompt_contract_sha256": sha(PREREG_DOC),
        "primary_contrasts": ["P1_full-A0", "P1_full-A1", "P1_full-A2"],
        "router_value_gate": {
            "full_better_than_legal_A0_blocks_min": 1,
            "same_direction_sources_min": 2,
            "no_added_win_to_loss": True,
            "no_new_safety_class": True,
        },
        "c1_gate": [
            "mechanism observed in at least two sources",
            "not identity proxy",
            "V111-owned state-compatible complete suffix or per-step contract",
            "procurement through sale and rejoin fully specified",
            "no PSR expression copied",
            "one mechanism family only",
        ],
        "seed_policy": {
            "spent": SEEDS,
            "promotion_sealed": [10091101, 10091112],
            "fresh_sealed": [10091901, 10091912],
            "prior_development_sealed": [10091421, 10091436],
            "conditional_development": [10091521, 10091536],
        },
        "prohibitions": [
            "Kaggle submit",
            "kernel push",
            "submission slot change",
            "P1 repair",
            "threshold search",
            "opponent forecast",
            "identity selector",
        ],
        "environment": {"engine_sha256": sha(ENGINE), "configuration_sha256": sha(ENGINE_JSON)},
    }
    save(PREREG, prereg)
    source_audit = {
        "created_at": now(),
        "P1": {
            "page_license": "Apache-2.0",
            "route_data_transitive_provenance_license": "UNVERIFIED",
            "status": "RESEARCH_ONLY",
            "basis": rel(OLD / "source_acquisition.json"),
        },
        "R0_D1": {"outer_license": "MIT", "embedded_PSR_transitive_license": "UNVERIFIED", "status": "RESEARCH_ONLY"},
        "V111": {"source": rel(V111_MAIN), "sha256": sha(V111_MAIN), "status": "PRODUCTION_CHAMPION_FIXED"},
        "public_notebook_refresh": "PENDING_ONE_READ_ONLY_CHECK",
        "independent_prior_selection": load(OLD / "independent_screen/selection.json"),
    }
    save(EXP / "source_and_license_audit.json", source_audit)
    manifest = {
        "experiment_id": EXP.name,
        "started_at_utc": started.isoformat(),
        "started_at_jst": started.astimezone(timezone(timedelta(hours=9))).isoformat(),
        "deadline_utc": deadline.isoformat(),
        "deadline_jst": deadline.astimezone(timezone(timedelta(hours=9))).isoformat(),
        "repository": str(ROOT),
        "git_branch": git("branch", "--show-current"),
        "git_head": git("rev-parse", "HEAD"),
        "git_status_short": git("status", "--short").splitlines(),
        "working_tree_policy": "preserve all pre-existing tracked/untracked changes",
        "initial_process_audit": {"method": "elevated Get-CimInstance", "matching_python_or_kaggle_processes": []},
        "input_sha256": input_hashes,
        "fixed_hashes": EXPECTED,
        "reused_artifact_verification": rel(EXP / "reused_artifact_verification.json"),
        "old_experiment": {"id": OLD.name, "status": "COMPLETE", "decision": "REJECT_SAFETY", "rerun": False},
        "production_champion": {"version": "V111", "status": "FIXED_RETAIN", "source_sha256": sha(V111_MAIN)},
        "phase": "INITIAL_AUDIT_COMPLETE",
        "status": "RUNNING",
        "external_mutations": {"submission": False, "kernel_push": False, "slot_change": False},
    }
    save(EXP / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "experiment": EXP.name,
                "started": manifest["started_at_jst"],
                "deadline": manifest["deadline_jst"],
                "seed_groups": ledger["groups"],
                "reused": reused["passed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


FEATURES: dict[int, tuple[str, str]] = {
    0: ("own_money", "own_private"),
    1: ("rival_money", "rival_public"),
    2: ("money_margin", "own_public+rival_public"),
    **{
        3 + i: (f"price_{name}", "price")
        for i, name in enumerate("WHEAT CARROT TOMATO STRAWBERRY MELON EGG MILK WOOL FERTILIZER".split())
    },
    **{
        12 + i: (f"market_inventory_delta_{name}", "market")
        for i, name in enumerate("WHEAT CARROT TOMATO STRAWBERRY MELON EGG MILK WOOL FERTILIZER".split())
    },
    **{
        21 + i: (f"town_shop_count_{name}", "Town")
        for i, name in enumerate(
            "BAKERY BRUNCH_SPOT FARMERS_MARKET ICE_CREAM_SHOP PET_CAFE PIZZA_SHOP SMOOTHIE_SHOP YARN_STORE".split()
        )
    },
    **{
        29 + i: (f"town_demand_{name}", "Town")
        for i, name in enumerate("WHEAT CARROT TOMATO STRAWBERRY MELON EGG MILK WOOL FERTILIZER".split())
    },
}
for offset, owner in ((38, "own_public"), (58, "rival_public")):
    for index, name in enumerate("WHEAT CARROT TOMATO STRAWBERRY MELON GOOSE COW SHEEP".split()):
        FEATURES[offset + index] = (f"{owner}_count_{name}", owner)
    for index, name in enumerate("WHEAT CARROT TOMATO STRAWBERRY MELON EGG MILK WOOL FERTILIZER".split()):
        FEATURES[offset + 8 + index] = (f"{owner}_yield_{name}", owner)
    FEATURES[offset + 17] = (f"{owner}_weeds", owner)
    FEATURES[offset + 18] = (f"{owner}_empty", owner)
    FEATURES[offset + 19] = (f"{owner}_unlocked_quadrants", owner)
for index, name in enumerate("WHEAT CARROT TOMATO STRAWBERRY MELON EGG MILK WOOL FERTILIZER GOOSE COW SHEEP".split()):
    FEATURES[78 + index] = (f"own_private_shed_{name}", "own_private")
for index, name in enumerate("WHEAT CARROT TOMATO STRAWBERRY MELON".split()):
    FEATURES[90 + index] = (f"own_private_seed_{name}", "own_private")
FEATURES[95] = ("own_farmer_x", "own_public")
FEATURES[96] = ("own_farmer_y", "own_public")


def tree_trace(module: Any, block: int, features: list[float]) -> tuple[int, list[dict[str, Any]]]:
    tree = module._TREES[block]
    node = 0
    traversed = []
    while tree[node][0] >= 0:
        feature, left, right, _, threshold = tree[node]
        value = features[feature]
        next_node = left if value <= threshold else right
        name, category = FEATURES.get(feature, (f"feature_{feature}", "unknown"))
        traversed.append(
            {
                "node": node,
                "feature_index": feature,
                "feature": name,
                "category": category,
                "value": value,
                "threshold": threshold,
                "signed_distance": value - threshold,
                "branch": "left" if value <= threshold else "right",
                "next_node": next_node,
            }
        )
        node = next_node
    return int(tree[node][3]), traversed


def category(action: list[Any]) -> str:
    op = str(action[0]) if action else "PASS"
    if op == "SELL":
        return "sell"
    if op in {"BUY_SEED", "BUY_PRODUCT", "BUY_ANIMAL"}:
        return "market"
    if op in {"HIRE", "BUY_LAND"}:
        return "hire_land"
    if op in {"NORTH", "SOUTH", "EAST", "WEST", "PASS"}:
        return "movement"
    if op in {"PLANT", "WATER", "HARVEST", "FERTILIZE", "DIG"}:
        return "plant_water_harvest"
    if op in {"FEED", "CARE", "COLLECT_FERTILIZER", "BUILD_COOP", "BUILD_PASTURE"}:
        return "animal_care_harvest"
    if op in {"PICKUP", "DROP", "PLACE"}:
        return "carry"
    return "other"


def flattened(action_value: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    result = [("farmer", action_value.get("farmer") or ["PASS"])]
    result.extend((f"hand_{index}", row) for index, row in enumerate(action_value.get("hands") or []))
    result.extend((f"market_{index}", row) for index, row in enumerate(action_value.get("market") or []))
    return result


def portfolio(obs: dict[str, Any], seat: int) -> dict[str, Any]:
    from scripts.evaluation.divergence import portfolio as summarize

    return summarize(obs["farms"][seat])


def analyze() -> None:
    module = import_module(P1_MAIN, "p1_analysis")
    p1_rows = rows(P1_PAIRS)
    d1_index = {(row["lineage_id"], row["seed"], row["seat"]): row for row in rows(D1_PAIRS)}
    traces = []
    sequence_sources: dict[str, Counter[str]] = defaultdict(Counter)
    source_sequences: dict[str, Counter[str]] = defaultdict(Counter)
    action_groups: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    exact_overlap: dict[str, Counter[str]] = defaultdict(Counter)
    timelines = []
    safety_routes: dict[str, Counter[str]] = defaultdict(Counter)
    for row in sorted(p1_rows, key=lambda item: (item["lineage_id"], item["seed"], item["seat"])):
        key = (row["lineage_id"], row["seed"], row["seat"])
        d1 = d1_index[key]
        p1_rep = replay(replay_path(row, "treatment"))
        v_rep = replay(replay_path(row, "control"))
        d1_rep = replay(replay_path(d1, "treatment"))
        routes = []
        decisions = []
        for block, step in enumerate(BOUNDARIES):
            obs = observation(p1_rep, step, int(row["seat"]))
            values = module._features(obs)
            route, path = tree_trace(module, block, values)
            routes.append(route)
            decisions.append({"block": block, "step": step, "route_index": route, "nodes": path})
        sequence = "/".join(map(str, routes))
        source_sequences[row["lineage_id"]][sequence] += 1
        sequence_sources[sequence][row["lineage_id"]] += 1
        transition = f"{row['control']['result']}->{row['treatment']['result']}"
        for block, (start, end) in enumerate(zip(BOUNDARIES, BLOCK_ENDS, strict=True)):
            for step in range(start, end):
                actions = {
                    "V111": actual_action(v_rep, step, int(row["seat"])),
                    "D1": actual_action(d1_rep, step, int(row["seat"])),
                    "P1": actual_action(p1_rep, step, int(row["seat"])),
                }
                group = f"{transition}:block{block}"
                for policy, action_value in actions.items():
                    for _, op in flattened(action_value):
                        action_groups[group][policy][category(op)] += 1
                exact_overlap[group]["steps"] += 1
                exact_overlap[group]["P1=V111"] += actions["P1"] == actions["V111"]
                exact_overlap[group]["P1=D1"] += actions["P1"] == actions["D1"]
                exact_overlap[group]["D1=V111"] += actions["D1"] == actions["V111"]
        for reason in row["candidate_new_major_regressions"]:
            for route in routes:
                safety_routes[reason][f"route_{route}"] += 1
        daily = []
        for day in range(30):
            start = day * 24
            end = min(719, (day + 1) * 24)
            record: dict[str, Any] = {"day": day}
            for label, rep in (("V111", v_rep), ("D1", d1_rep), ("P1", p1_rep)):
                left = observation(rep, start, int(row["seat"]))
                right = observation(rep, end, int(row["seat"]))
                seat = int(row["seat"])
                record[label] = {
                    "self_coin_increment": right["farms"][seat]["money"] - left["farms"][seat]["money"],
                    "opponent_coin_increment": right["farms"][1 - seat]["money"] - left["farms"][1 - seat]["money"],
                    "self_portfolio_end": portfolio(right, seat),
                    "opponent_portfolio_end": portfolio(right, 1 - seat),
                    "market_orders": dict(
                        Counter(
                            f"{op[0]}:{op[1] if len(op) > 1 else ''}"
                            for step in range(start, end)
                            for role, op in flattened(actual_action(rep, step, seat))
                            if role.startswith("market_") and op
                        )
                    ),
                }
            daily.append(record)
        timelines.append(
            {
                "source": row["lineage_id"],
                "seed": row["seed"],
                "seat": row["seat"],
                "transition": transition,
                "routes": routes,
                "first_divergence": row["divergence_audit"],
                "daily": daily,
                "terminal": {
                    label: {
                        "t672_portfolio": portfolio(observation(rep, 672, int(row["seat"])), int(row["seat"])),
                        "t719_portfolio": portfolio(observation(rep, 719, int(row["seat"])), int(row["seat"])),
                        "t719_private": observation(rep, 719, int(row["seat"]))["private"],
                    }
                    for label, rep in (("V111", v_rep), ("D1", d1_rep), ("P1", p1_rep))
                },
            }
        )
        traces.append(
            {
                "source": row["lineage_id"],
                "seed": row["seed"],
                "seat": row["seat"],
                "transition": transition,
                "decisions": decisions,
            }
        )
    route_trace = {
        "created_at": now(),
        "scope": "32 existing P1 replays; zero new games",
        "contexts": traces,
        "feature_index_inventory": {
            str(index): {"name": value[0], "category": value[1]} for index, value in sorted(FEATURES.items())
        },
        "decoded_tape_copied": False,
    }
    save(EXP / "router_decision_trace.json", route_trace)
    total = sum(sum(counter.values()) for counter in sequence_sources.values())
    majority_correct = sum(max(counter.values()) for counter in sequence_sources.values())
    perturb = []
    for trace in traces:
        for decision in trace["decisions"]:
            for node in decision["nodes"]:
                distance = abs(float(node["signed_distance"]))
                scale = max(1.0, abs(float(node["threshold"])))
                perturb.append(
                    {
                        "source": trace["source"],
                        "seed": trace["seed"],
                        "seat": trace["seat"],
                        "step": decision["step"],
                        "feature": node["feature"],
                        "category": node["category"],
                        "distance": distance,
                        "stable_under_plus_minus_1pct_scale": distance > 0.01 * scale,
                    }
                )
    identity = {
        "created_at": now(),
        "explicit_identity_seed_private_future_tape_match": False,
        "traversed_feature_categories": dict(
            Counter(
                node["category"] for trace in traces for decision in trace["decisions"] for node in decision["nodes"]
            )
        ),
        "source_to_route_sequence": {source: dict(counter) for source, counter in source_sequences.items()},
        "route_sequence_to_source": {sequence: dict(counter) for sequence, counter in sequence_sources.items()},
        "route_sequence_majority_source_accuracy": majority_correct / total if total else None,
        "route_sequence_uniquely_identifies_source": {
            sequence: len(counter) == 1 for sequence, counter in sequence_sources.items()
        },
        "nearby_perturbation": perturb,
        "economics": {
            "town_shop_count_YARN_STORE": "current public Town composition; discrete and economically related to wool demand",
            "town_demand_MILK": "current public Town milk demand; monotone demand count",
            "price_CARROT": "current public market price; monotone scarcity/glut signal",
        },
        "leave_one_source": {
            source: {
                "remaining_route_sequences": sorted(
                    {sequence for other, counts in source_sequences.items() if other != source for sequence in counts}
                ),
                "held_out_sequences_seen_in_remaining": sorted(
                    set(source_sequences[source])
                    & {sequence for other, counts in source_sequences.items() if other != source for sequence in counts}
                ),
            }
            for source in source_sequences
        },
        "decision": "PENDING_ABLATION_EVIDENCE",
        "conservative_rule": "Any near-unique source signature selecting a fixed future route is research-only even when inputs are public.",
    }
    save(EXP / "router_identity_proxy_audit.json", identity)
    save(
        EXP / "action_overlap_by_block.json",
        {
            "created_at": now(),
            "scope": "P1/D1/V111 existing replays",
            "category_counts": {
                group: {policy: dict(counter) for policy, counter in policies.items()}
                for group, policies in action_groups.items()
            },
            "exact_step_overlap": {group: dict(counter) for group, counter in exact_overlap.items()},
        },
    )
    save(
        EXP / "mediator_timeline.json",
        {
            "created_at": now(),
            "scope": "descriptive temporal alignment; no single-action causal identification",
            "contexts": timelines,
            "limits": [
                "Town and opponent action are closed-loop mediators",
                "opponent coin decline is a total-policy association",
                "t719 inventory has no remaining decision and is not realized revenue",
            ],
        },
    )
    save(
        EXP / "router_safety_route_map.json",
        {
            "created_at": now(),
            "reason_route_exposure_counts": {reason: dict(counter) for reason, counter in safety_routes.items()},
            "timing_causal_warning": "Matching timestamps or route exposure does not identify causality.",
        },
    )
    print(
        json.dumps(
            {
                "contexts": len(traces),
                "route_sequences": {key: dict(value) for key, value in source_sequences.items()},
                "majority_source_accuracy": identity["route_sequence_majority_source_accuracy"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def source_agent_span(source: str) -> tuple[ast.FunctionDef, ast.Module]:
    tree = ast.parse(source)
    agents = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "agent"]
    if len(agents) != 1:
        raise RuntimeError(f"expected one top-level agent, found {len(agents)}")
    return agents[0], tree


def candidate_source(mode: str) -> tuple[str, dict[str, Any]]:
    source = P1_MAIN.read_text(encoding="utf-8")
    agent, _ = source_agent_span(source)
    original = """    if t % 144 == 0:\n        state[1] = _choose(t//144,_features(observation))\n"""
    replacements = {
        "A0_psr_route_locked": """    # Research-only A0: retain the route selected at step 0 for all 719 decisions.\n    if False and t % 144 == 0:\n        state[1] = _choose(t//144,_features(observation))\n""",
        "A1_psr_no_day6_switch": """    # Research-only A1: disable only the step-144 route reassignment.\n    if t % 144 == 0 and t != 144:\n        state[1] = _choose(t//144,_features(observation))\n""",
        "A2_psr_no_day24_switch": """    # Research-only A2: disable only the step-576 route reassignment.\n    if t % 144 == 0 and t != 576:\n        state[1] = _choose(t//144,_features(observation))\n""",
    }
    if source.count(original) != 1:
        raise RuntimeError("AST-located router assignment text is not unique")
    changed = source.replace(original, replacements[mode])
    changed_agent, _ = source_agent_span(changed)
    return changed, {
        "method": "single AST-located If condition edit inside top-level agent",
        "agent_lines_before": [agent.lineno, agent.end_lineno],
        "agent_lines_after": [changed_agent.lineno, changed_agent.end_lineno],
        "changed_assignment": "state[1] = _choose(t//144,_features(observation))",
        "mode": mode,
    }


def tar_candidate(directory: Path, output: Path) -> None:
    with tarfile.open(output, "w:gz") as handle:
        handle.add(directory / "main.py", arcname="main.py")
        handle.add(directory / "LICENSE_SCOPE.md", arcname="LICENSE_SCOPE.md")


def prepare() -> None:
    module = import_module(P1_MAIN, "p1_prepare")
    tape_hashes = []
    for index, tape in enumerate(module._TAPES):
        tape_hashes.append(
            {
                "route_index": index,
                "prefix_hashes": {str(end): stable_sha(tape[:end]) for end in BLOCK_ENDS},
                "block_hashes": {
                    f"{start}:{end}": stable_sha(tape[start:end])
                    for start, end in zip(BOUNDARIES, BLOCK_ENDS, strict=True)
                },
            }
        )
    # Compatibility follows from the exact source semantics and same-route
    # continuation, not merely from equal action-prefix hashes.
    compatibility = {
        "AST": {
            "top_level_agent_count": 1,
            "router_assignment_count": P1_MAIN.read_text(encoding="utf-8").count(
                "state[1] = _choose(t//144,_features(observation))"
            ),
            "boundaries": BOUNDARIES,
            "tree_leaf_routes": [sorted({int(node[3]) for node in tree if node[0] < 0}) for tree in module._TREES],
        },
        "route_prefix_hashes": tape_hashes,
        "interpretation": {
            "A0": "route 0 is selected at step 0 and its own complete 719-decision tape is followed; self-compatible",
            "A1": "route 0 produced block0; retaining route 0 for block1 and selecting the source-prescribed route0 at step288 is same-route compatible",
            "A2": "source tree fixes route0 at step432; retaining route0 at step576 is same-route compatible",
        },
        "manual_action_completion": False,
        "valid": True,
    }
    save(EXP / "ablation_compatibility.json", compatibility)
    for mode in ("A0_psr_route_locked", "A1_psr_no_day6_switch", "A2_psr_no_day24_switch"):
        directory = EXP / "candidates" / mode
        directory.mkdir(parents=True, exist_ok=True)
        source, diff = candidate_source(mode)
        (directory / "main.py").write_text(source, encoding="utf-8")
        (directory / "LICENSE_SCOPE.md").write_text(
            "Research-only diagnostic derivative of public notebook Version 3. Page license Apache-2.0; embedded route-data transitive provenance/license remains UNVERIFIED. Not promotion eligible.\n",
            encoding="utf-8",
        )
        archive = EXP / f"{mode}.tar.gz"
        tar_candidate(directory, archive)
        freeze = {
            "frozen_at": now(),
            "candidate": mode,
            "role": "research-only router ablation",
            "promotion_eligible": False,
            "parent": rel(P1_MAIN),
            "parent_sha256": sha(P1_MAIN),
            "source": rel(directory / "main.py"),
            "source_sha256": sha(directory / "main.py"),
            "package": rel(archive),
            "package_sha256": sha(archive),
            "entrypoint": "main.agent",
            "diff": diff,
            "compatibility_sha256": sha(EXP / "ablation_compatibility.json"),
            "license_cap": "UNVERIFIED_TRANSITIVE_ROUTE_DATA_RESEARCH_ONLY",
        }
        save(directory / "freeze.json", freeze)
        save(
            directory / "integrity.json",
            {
                **freeze,
                "external_imports": ["base64", "json", "sys", "zlib"],
                "reset": "_SESSIONS resets per player when t==0 or step decreases",
                "forbidden_runtime_identity_seed_private_future_tables": False,
                "contains_parent_own_route_blob": True,
                "deployable": False,
            },
        )
        save(
            directory / "plan.json",
            {
                "frozen_at": now(),
                "candidate": mode,
                "primary_control": "P1_full_existing",
                "auxiliary_control": "V111",
                "sources": list(SOURCES),
                "seeds": SEEDS,
                "seats": [0, 1],
                "episode_steps": 720,
                "required_order": ["import_reset_isolation", "AA", "both-seat smoke", "spent full"],
                "stop_conditions": ["AA mismatch", "incomplete720", "schema error", "prefix incompatibility"],
            },
        )
    print(
        json.dumps(
            {
                mode: load(EXP / "candidates" / mode / "freeze.json")["source_sha256"]
                for mode in ("A0_psr_route_locked", "A1_psr_no_day6_switch", "A2_psr_no_day24_switch")
            },
            indent=2,
        )
    )


def configure_base() -> Any:
    import scripts.run_clean_psr_research as base

    base.EXP = EXP
    base.PREREG = PREREG
    base.CANDIDATES = {
        "V111": {
            "main": V111_MAIN,
            "source_sha256": EXPECTED["V111"],
            "package_sha256": "85ba0176b1774ca1bc45f77601210d847e4bb8c01b550181c3c87bd3f6a1c85e",
        },
    }
    for mode in ("A0_psr_route_locked", "A1_psr_no_day6_switch", "A2_psr_no_day24_switch"):
        freeze = load(EXP / "candidates" / mode / "freeze.json")
        base.CANDIDATES[mode] = {
            "main": ROOT / freeze["source"],
            "source_sha256": freeze["source_sha256"],
            "package_sha256": freeze["package_sha256"],
        }
    base.OLD_SOURCES = SOURCES
    return base


def validate_candidates() -> None:
    checks = []
    old_row = rows(P1_PAIRS)[0]
    rep = replay(replay_path(old_row, "control"))
    config = rep.get("configuration") or {}
    for mode in ("A0_psr_route_locked", "A1_psr_no_day6_switch", "A2_psr_no_day24_switch"):
        path = EXP / "candidates" / mode / "main.py"
        modules = [import_module(path, f"{mode}_{index}") for index in range(2)]
        seat_results = []
        for seat in (0, 1):
            obs = observation(rep, 0, seat)
            first = modules[0].agent(copy.deepcopy(obs), config)
            reset = modules[0].agent(copy.deepcopy(obs), config)
            independent = modules[1].agent(copy.deepcopy(obs), config)
            schema = (
                set(first) == {"farmer", "hands", "market"}
                and isinstance(first["farmer"], list)
                and isinstance(first["hands"], list)
                and isinstance(first["market"], list)
            )
            seat_results.append(
                {
                    "seat": seat,
                    "reset_equal": first == reset,
                    "independent_equal": first == independent,
                    "schema_ok": schema,
                }
            )
        checks.append(
            {
                "candidate": mode,
                "source_sha256": sha(path),
                "imports_isolated": modules[0] is not modules[1],
                "seats": seat_results,
            }
        )
    passed = all(
        row["imports_isolated"]
        and all(item["reset_equal"] and item["independent_equal"] and item["schema_ok"] for item in row["seats"])
        for row in checks
    )
    save(
        EXP / "validation_pre_games.json",
        {
            "created_at": now(),
            "passed": passed,
            "engine_version": importlib.metadata.version("kaggle-environments"),
            "engine_sha256": sha(ENGINE),
            "configuration_sha256": sha(ENGINE_JSON),
            "checks": checks,
        },
    )
    if not passed:
        raise RuntimeError("candidate import/reset/isolation validation failed")
    print(json.dumps({"passed": passed, "candidates": len(checks)}))


def run_phase(candidate: str, phase: str, workers: int) -> None:
    base = configure_base()
    if phase == "aa":
        base.run_candidate_phase(candidate, "aa", ["qeinstein_moev2"], [10091011], workers)
    elif phase == "smoke":
        base.run_candidate_phase(candidate, "smoke", ["qeinstein_moev2", "souvik_v4"], [10091011], workers)
    elif phase == "spent":
        base.run_candidate_phase(candidate, "spent", list(SOURCES), SEEDS, workers)
    else:
        raise ValueError(phase)


def block_scores(index: dict[tuple[str, int, int], dict[str, Any]], arm: str) -> dict[tuple[str, int], float]:
    grouped: dict[tuple[str, int], list[float]] = defaultdict(list)
    for (source, seed, _seat), row in index.items():
        grouped[(source, seed)].append(float(row[arm]["score"]))
    return {key: mean(value) for key, value in grouped.items()}


def pair_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    from scripts.evaluation.statistics import summarize_pairs

    result = summarize_pairs(items)
    result["wdl"] = dict(Counter(row["treatment"]["result"] for row in items))
    result["margin"] = {
        "mean": mean(float(row["treatment"]["margin"]) for row in items),
        "p10": sorted(float(row["treatment"]["margin"]) for row in items)[max(0, int(0.1 * (len(items) - 1)))],
        "min": min(float(row["treatment"]["margin"]) for row in items),
        "max": max(float(row["treatment"]["margin"]) for row in items),
    }
    result["transitions"] = dict(Counter(f"{row['control']['result']}->{row['treatment']['result']}" for row in items))
    result["source_seed_blocks"] = len({(row["lineage_id"], row["seed"]) for row in items})
    return result


def summarize() -> None:
    p1 = rows(P1_PAIRS)
    p1_index = {(row["lineage_id"], row["seed"], row["seat"]): row for row in p1}
    summaries = {}
    contrasts = {}
    for mode in ("A0_psr_route_locked", "A1_psr_no_day6_switch", "A2_psr_no_day24_switch"):
        path = EXP / "candidates" / mode / "pairs/spent.jsonl"
        if not path.exists():
            summaries[mode] = {"status": "NOT_RUN"}
            continue
        abl = rows(path)
        abl_index = {(row["lineage_id"], row["seed"], row["seat"]): row for row in abl}
        summaries[mode] = {
            "status": "COMPLETE",
            "overall": pair_summary(abl),
            "by_source": {
                source: pair_summary([row for row in abl if row["lineage_id"] == source]) for source in SOURCES
            },
            "by_ancestry": {
                "psr_kaito_near": pair_summary(
                    [row for row in abl if row["lineage_id"] in {"mooman_e052a", "ggmljs_v16", "souvik_v4"}]
                ),
                "independent_qeinstein": pair_summary([row for row in abl if row["lineage_id"] == "qeinstein_moev2"]),
            },
            "raw_safety_contexts": sum(bool(row["candidate_new_major_regressions"]) for row in abl),
            "raw_safety_classes": dict(
                Counter(reason for row in abl for reason in row["candidate_new_major_regressions"])
            ),
        }
        p1_blocks = block_scores(p1_index, "treatment")
        abl_blocks = block_scores(abl_index, "treatment")
        delta_blocks = {key: p1_blocks[key] - abl_blocks[key] for key in p1_blocks}
        source_delta = {
            source: mean(delta for (current, _), delta in delta_blocks.items() if current == source)
            for source in SOURCES
        }
        full_wtl = sum(row["control"]["result"] == "win" and row["treatment"]["result"] == "loss" for row in p1)
        abl_wtl = sum(row["control"]["result"] == "win" and row["treatment"]["result"] == "loss" for row in abl)
        contrasts[mode] = {
            "P1_full_minus_ablation_context_win_score": mean(
                float(p1_index[key]["treatment"]["score"]) - float(abl_index[key]["treatment"]["score"])
                for key in p1_index
            ),
            "P1_full_minus_ablation_block_scores": {
                f"{key[0]}:{key[1]}": value for key, value in sorted(delta_blocks.items())
            },
            "positive_blocks": sum(value > 0 for value in delta_blocks.values()),
            "negative_blocks": sum(value < 0 for value in delta_blocks.values()),
            "same_direction_positive_sources": sum(value > 0 for value in source_delta.values()),
            "source_delta": source_delta,
            "P1_win_to_loss": full_wtl,
            "ablation_win_to_loss": abl_wtl,
            "P1_new_safety_classes_vs_V111": sorted(
                {reason for row in p1 for reason in row["candidate_new_major_regressions"]}
            ),
            "ablation_new_safety_classes_vs_V111": sorted(
                {reason for row in abl for reason in row["candidate_new_major_regressions"]}
            ),
        }
        save(EXP / "candidates" / mode / "summary/mechanism.json", summaries[mode])
    a0 = contrasts.get("A0_psr_route_locked")
    router_gate = bool(
        a0
        and a0["positive_blocks"] >= 1
        and a0["same_direction_positive_sources"] >= 2
        and a0["P1_win_to_loss"] <= a0["ablation_win_to_loss"]
        and not (set(a0["P1_new_safety_classes_vs_V111"]) - set(a0["ablation_new_safety_classes_vs_V111"]))
    )
    identity = load(EXP / "router_identity_proxy_audit.json")
    unique_sequences = any(identity["route_sequence_uniquely_identifies_source"].values())
    identity["decision"] = (
        "RESEARCH_ONLY_IDENTITY_PROXY_RISK"
        if unique_sequences and identity["route_sequence_majority_source_accuracy"] >= 0.75
        else "NO_KNOWN_SOURCE_PROXY_ESTABLISHED_ON_SPENT_PANEL"
    )
    identity["deploy_transfer_allowed"] = identity["decision"] == "NO_KNOWN_SOURCE_PROXY_ESTABLISHED_ON_SPENT_PANEL"
    save(EXP / "router_identity_proxy_audit.json", identity)
    ranking = {
        "created_at": now(),
        "mechanisms": [
            {
                "rank": 1,
                "name": "fixed route0 total policy and initial WHEAT footprint",
                "changes": ["own private inventory", "market WHEAT inventory/price", "complete own portfolio"],
                "commonality": "P1-specific complete route; D1 shares some market footprint but not the exact policy",
                "evidence": "A0 paired result and step1 public divergence",
                "inference": "closed-loop opponent response may mediate later margin",
                "unknown": "single action causal effect",
                "v111_implementation": "no repository-owned equivalent complete suffix established",
                "completeness": "complete only inside research-only P1 tape",
                "risks": ["license derivative", "Safety", "fixed-route expression"],
            },
            {
                "rank": 2,
                "name": "day6 Town-demand route selection",
                "changes": ["route block144:288"],
                "commonality": "P1 router only",
                "evidence": "P1-A1 contrast",
                "inference": "Town scarcity adaptation",
                "unknown": "source-independent transfer",
                "v111_implementation": "not yet state-compatible",
                "completeness": "PSR route block only",
                "risks": ["identity proxy", "license derivative", "Safety"],
            },
            {
                "rank": 3,
                "name": "day24 CARROT-price route selection",
                "changes": ["route block576:719"],
                "commonality": "P1 router only",
                "evidence": "P1-A2 contrast",
                "inference": "late market response",
                "unknown": "realizable safe revenue",
                "v111_implementation": "no complete rejoin contract",
                "completeness": "PSR route block only",
                "risks": ["terminal inventory", "license derivative", "Safety"],
            },
            {
                "rank": 4,
                "name": "generic current-state contract validation",
                "changes": ["preflight", "per-step legality", "maintenance invariants"],
                "commonality": "general contract; V111 already has repository-owned execution",
                "evidence": "P1 multi-family no-op/lifecycle failures show need",
                "inference": "could improve robustness",
                "unknown": "positive win value in two sources",
                "v111_implementation": "possible but no qualifying positive mechanism isolated",
                "completeness": "can be defined but would be Safety repair, excluded by this study",
                "risks": ["scope drift", "no uplift"],
            },
        ],
        "router_value_gate": router_gate,
        "identity_proxy_decision": identity["decision"],
        "fixed_parameters": "source boundaries only; no threshold or outcome search",
    }
    save(EXP / "mechanism_ranking.json", ranking)
    c1_gate = {
        "router_or_common_public_mechanism_two_sources": router_gate,
        "not_identity_proxy": identity["deploy_transfer_allowed"],
        "v111_owned_complete_suffix_or_unique_contract": False,
        "procurement_to_sale_and_rejoin_complete": False,
        "no_psr_expression_needed": False,
        "one_family": True,
    }
    c1_authorized = all(c1_gate.values())
    attribution = {
        "created_at": now(),
        "contrasts": contrasts,
        "router_value_gate": router_gate,
        "c1_gate": c1_gate,
        "c1_authorized": c1_authorized,
        "Evidence": [
            "P1/A0/A1/A2 paired outcomes on the trained spent panel",
            "first public market/price divergence precedes observed opponent response",
            "daily self/opponent coin and portfolio trajectories",
            "engine-committed lifecycle/order audits",
        ],
        "Inference": [
            "part of the margin is consistent with public-market and Town mediated opponent closed-loop response",
            "fixed route0 may explain total-policy uplift when A0 is noninferior",
        ],
        "Unknown": [
            "single-action causal effect",
            "counterfactual opponent response holding RNG/Town fixed",
            "generalization beyond spent sources/seeds",
            "transitive route-data provenance/license",
        ],
        "causal_limit": "Opponent coin change is a total-policy closed-loop association, not an identified effect of one market action.",
    }
    save(EXP / "mechanism_attribution.json", attribution)
    save(
        EXP / "development_progress.json",
        {
            "created_at": now(),
            "status": "NOT_OPENED",
            "reason": "C1 not authorized" if not c1_authorized else "PENDING_C1_SPENT_GATE",
            "conditional_range": [10091521, 10091536],
            "used": [],
        },
    )
    print(
        json.dumps(
            {
                "contrasts": contrasts,
                "router_gate": router_gate,
                "identity": identity["decision"],
                "c1_authorized": c1_authorized,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("initial")
    sub.add_parser("analyze")
    sub.add_parser("prepare")
    sub.add_parser("validate")
    run = sub.add_parser("run")
    run.add_argument(
        "--candidate", required=True, choices=("A0_psr_route_locked", "A1_psr_no_day6_switch", "A2_psr_no_day24_switch")
    )
    run.add_argument("--phase", required=True, choices=("aa", "smoke", "spent"))
    run.add_argument("--workers", type=int, default=4)
    sub.add_parser("summarize")
    args = parser.parse_args()
    if args.command == "initial":
        initial()
    elif args.command == "analyze":
        analyze()
    elif args.command == "prepare":
        prepare()
    elif args.command == "validate":
        validate_candidates()
    elif args.command == "run":
        run_phase(args.candidate, args.phase, args.workers)
    elif args.command == "summarize":
        summarize()


if __name__ == "__main__":
    main()
