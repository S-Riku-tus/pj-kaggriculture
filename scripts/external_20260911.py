"""Freeze a new source and compare complete policies without transplanting components."""

# ruff: noqa: E402, E501

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.research_20260911 import EVAL, OLD, OUT, digest, save

ADAPTER = '''"""Import isolation and diagnostics only; native entrypoint is preserved verbatim."""
import importlib.util
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
for key in list(sys.modules):
    if key.split(".")[0] in {"kaggisim", "strategies"}:
        del sys.modules[key]
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("_rob_native", HERE / "native_entrypoint.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
_caught = []
def reset_runtime_state():
    _caught.clear()
    native._agent = native.STRATEGY()
    original = native._agent.act
    def tracked(state):
        try:
            return original(state)
        except Exception as exc:
            _caught.append({"type": type(exc).__name__, "message": str(exc)})
            raise
    native._agent.act = tracked
def agent(obs, configuration=None):
    return native.agent(obs)
def policy_diagnostics(obs):
    return {"research_decision": {"native_caught_exceptions": list(_caught), "committed": False}}
reset_runtime_state()
'''


def prepare():
    from scripts.evaluation.runner import extract_archive
    from scripts.research_20260910 import package

    base = OUT / "sources/robriculture"
    registry = OUT / "external_source_registry.json"
    if registry.exists():
        raise SystemExit("External source already frozen")
    source = ast.parse((base / "build/package.py").read_text(encoding="utf-8"))
    shim = next(ast.literal_eval(node.value) for node in source.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "MAIN_SHIM" for t in node.targets))
    contents = {str(p.relative_to(base)).replace("\\", "/"): p.read_bytes()
                for folder in ("kaggisim", "strategies") for p in (base / folder).rglob("*")
                if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    contents.update({"main.py": ADAPTER.encode(), "native_entrypoint.py": shim.format(module="lean_feed").encode(),
                     "LICENSE": (base / "LICENSE").read_bytes(),
                     "NOTICE.md": b"Rob Sartin and robriculture contributors, CC-BY-4.0. https://github.com/robsartin/robriculture\nNative lean_feed source unchanged. Added import isolation and exception-count diagnostics only.\n"})
    archive = OUT / "opponents/robriculture_lean_feed.tar.gz"
    package(contents, archive)
    extract_archive(archive, OUT / "runtime/robriculture_lean_feed")
    save(registry, {
        "candidate_id": "robriculture_lean_feed", "repository": "https://github.com/robsartin/robriculture",
        "commit": "7f54373b67cf41f71168f09457390f6663e3a6a1", "license": "CC-BY-4.0",
        "entrypoint_basis": "native MAIN_SHIM from build/package.py; lean_feed named in harness/champion.json",
        "archive": str(archive.relative_to(ROOT)), "archive_sha256": digest(archive),
        "source_hashes": {name: digest(base / name) for name in contents if (base / name).is_file()},
        "native_entrypoint_sha256": digest(OUT / "runtime/robriculture_lean_feed/native_entrypoint.py"),
        "tier": "pending executable completion and exception audit", "ancestry": "robriculture hand/job economy; no PSR/Kaito code dependency found in runtime imports",
        "comparison_scope": "unmodified full public package; not evidence for any single component or current Kaggle rank",
        "seeds": [10091011, 10091012], "seats": [0, 1], "fresh": "not used",
    })


def game_task(task):
    from scripts.evaluation.runner import _run_game, _write_replay

    start = time.perf_counter()
    game = _run_game(Path(task["focal"]), Path(task["opponent"]), task["seed"], task["seat"], 720, "package_compare")
    replay = game.pop("replay")
    path = EVAL / "complete_policy/replays" / f"{task['a']}_{task['b']}_{task['seed']}_{task['seat']}.json.gz"
    game.update({"a": task["a"], "b": task["b"], "elapsed_seconds": time.perf_counter() - start,
                 "replay": _write_replay(path, replay), "stored_steps": len(replay["steps"])})
    return game


def run(workers, full=False):
    pool = json.loads((OLD / "source_registry.json").read_text(encoding="utf-8"))["sources"]
    policies = {s["candidate_id"]: str(ROOT / s["entrypoint"]) for s in pool}
    tasks = []
    if full:
        names = sorted(policies)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                for seed in range(10091011, 10091015):
                    for seat in (0, 1):
                        tasks.append({"a": a, "b": b, "focal": policies[a], "opponent": policies[b], "seed": seed, "seat": seat})
    else:
        for seed in (10091011, 10091012):
            for seat in (0, 1):
                tasks.append({"a": "robriculture_lean_feed", "b": "v111",
                              "focal": str(OUT / "runtime/robriculture_lean_feed/main.py"),
                              "opponent": str(OLD / "runtime/control/main.py"), "seed": seed, "seat": seat})
    target = EVAL / "complete_policy" / ("round_robin.jsonl" if full else "new_source_pilot.jsonl")
    existing = [json.loads(x) for x in target.read_text(encoding="utf-8").splitlines()] if target.exists() else []
    done = {(r["a"], r["b"], r["requested_seed"], r["seat"]) for r in existing}
    tasks = [t for t in tasks if (t["a"], t["b"], t["seed"], t["seat"]) not in done]
    target.parent.mkdir(parents=True, exist_ok=True)
    save(target.with_suffix(".manifest.json"), {"scope": "complete policy comparison, development, no component claim",
         "remaining_tasks": tasks, "seed_and_seat_pairing": True, "full_horizon": 720})
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(game_task, task) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(row["a"], row["b"], row["requested_seed"], row["seat"], row["result"], row["margin"], row["elapsed_seconds"], flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "pilot", "roundrobin"])
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare()
    else:
        run(args.workers, args.mode == "roundrobin")


if __name__ == "__main__":
    main()
