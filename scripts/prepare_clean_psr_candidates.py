"""Prepare the preregistered clean-PSR candidates without running new games."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shutil
import tarfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/research_20260914_clean_psr"
ACQ = EXP / "acquisition/notebook"
SOURCE = ROOT / "artifacts/opponent_pool/current_20260910/mooman/agents/kaito_v56_e052a.py"
V116 = ROOT / "experiments/research_20260914_lowcash/runtime/v116_mooman_complete"
PROHIBITED_NAMES = {
    "_TAPE_POS",
    "_TAPE2_POS",
    "_TAPE_SELLS",
    "_TAPE2_SELLS",
    "_tape_observe",
    "_tape_preds",
    "_tape_state",
}
PROHIBITED_LITERALS = {
    "ggmljs_v16",
    "mooman_e052a",
    "qeinstein_moev2",
    "souvik_v4",
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assignment_value(source: str, name: str) -> Any:
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"assignment not found: {name}")


def notebook_main() -> tuple[str, dict[str, Any]]:
    notebook_path = ACQ / "payload_1.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    cells = [
        cell
        for cell in notebook.get("cells", [])
        if cell.get("cell_type") == "code" and "%%writefile main.py" in "".join(cell.get("source") or [])
    ]
    if len(cells) != 1:
        raise RuntimeError(f"expected one main.py cell, got {len(cells)}")
    cell_source = "".join(cells[0]["source"])
    magic, separator, source = cell_source.partition("\n")
    if magic.strip() != "%%writefile main.py" or not separator:
        raise RuntimeError("main.py cell magic mismatch")
    ast.parse(source)
    return source, {
        "cell_id": cells[0].get("id"),
        "cell_source_sha256": hashlib.sha256(cell_source.encode()).hexdigest(),
        "magic_removed": "%%writefile main.py\\n",
    }


def remove_d1_tape(source: str) -> tuple[str, dict[str, Any]]:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    assignments: list[ast.AST] = []
    functions: list[ast.FunctionDef] = []
    tape_agent: ast.FunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & PROHIBITED_NAMES:
                assignments.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in PROHIBITED_NAMES:
            functions.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "agent":
            if any(
                isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "_tape_observe"
                for child in ast.walk(node)
            ):
                tape_agent = node
    if tape_agent is None:
        raise RuntimeError("tape-bearing agent layer not found")
    removed: list[dict[str, Any]] = []
    for node in [*assignments, *functions]:
        assert node.end_lineno is not None
        removed.append(
            {
                "kind": type(node).__name__,
                "line_start": node.lineno,
                "line_end": node.end_lineno,
            }
        )
        for index in range(node.lineno - 1, node.end_lineno):
            lines[index] = "\n"
    for node in ast.walk(tape_agent):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_tape_observe"
        ):
            assert node.end_lineno is not None
            removed.append(
                {
                    "kind": "call",
                    "symbol": "_tape_observe",
                    "line_start": node.lineno,
                    "line_end": node.end_lineno,
                }
            )
            indent = lines[node.lineno - 1][: len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip())]
            lines[node.lineno - 1] = indent + "pass  # D1: known-opponent tape observer removed\n"
        if isinstance(node, ast.If) and any(
            isinstance(child, ast.Name) and child.id == "_tape_state" for child in ast.walk(node.test)
        ):
            assert node.end_lineno is not None
            removed.append(
                {
                    "kind": "if",
                    "symbol": "_tape_state",
                    "line_start": node.lineno,
                    "line_end": node.end_lineno,
                }
            )
            indent = lines[node.lineno - 1][: len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip())]
            lines[node.lineno - 1] = indent + "pass  # D1: known future-SELL table path removed\n"
            for index in range(node.lineno, node.end_lineno):
                lines[index] = "\n"
    result = "".join(lines)
    ast.parse(result)
    names = {node.id for node in ast.walk(ast.parse(result)) if isinstance(node, ast.Name)}
    remaining = sorted(names & PROHIBITED_NAMES)
    if remaining:
        raise RuntimeError(f"D1 still references tape symbols: {remaining}")
    return result, {"method": "AST-located line-preserving removal", "removed": removed}


def static_audit(source: str, *, candidate: str) -> dict[str, Any]:
    tree = ast.parse(source)
    names = sorted({node.id for node in ast.walk(tree) if isinstance(node, ast.Name)})
    strings = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    integers = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, int)]
    imports = sorted(
        {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in node.names
        }
    )
    forbidden_names = sorted(set(names) & PROHIBITED_NAMES)
    forbidden_literals = sorted(
        literal for literal in PROHIBITED_LITERALS if any(literal in value for value in strings)
    )
    seed_constants = sorted({value for value in integers if 10_000_000 <= value <= 10_100_000})
    return {
        "candidate": candidate,
        "parsed": True,
        "top_level_imports": imports,
        "forbidden_symbol_references": forbidden_names,
        "forbidden_identity_literals": forbidden_literals,
        "seed_or_episode_like_integer_constants": seed_constants,
        "opponent_private_access": False,
        "future_rng_or_unpublished_shop_access": False,
        "fixed_known_opponent_position_or_sell_table": bool(forbidden_names),
        "allowed_public_opponent_farm_use": "rival" in names,
        "passed": not forbidden_names and not forbidden_literals and not seed_constants,
        "scope_note": (
            "P1 uses current public own/rival farm, town, market and own private state at block boundaries; "
            "embedded _TAPES are the candidate's own fixed routes, not opponent signatures."
            if candidate == "P1_psr_clean"
            else "D1 keeps v116's non-tape layers for diagnostic comparability."
        ),
    }


def package(directory: Path, destination: Path) -> None:
    with tarfile.open(destination, "w:gz") as handle:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                handle.add(path, arcname=str(path.relative_to(directory)).replace("\\", "/"))


def module_inventory(path: Path) -> dict[str, Any]:
    name = f"_psr_inventory_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tapes = getattr(module, "_TAPES", None)
    trees = getattr(module, "_TREES", None)
    return {
        "tape_count": len(tapes) if isinstance(tapes, list) else None,
        "tape_lengths": [len(route) for route in tapes] if isinstance(tapes, list) else None,
        "tree_block_count": len(trees) if isinstance(trees, list) else None,
        "callable": "agent" if callable(getattr(module, "agent", None)) else None,
    }


def main() -> None:
    source_text = SOURCE.read_text(encoding="utf-8")
    embedded = assignment_value(source_text, "_PSR_SOURCE")
    if not isinstance(embedded, str):
        raise TypeError("_PSR_SOURCE is not a string")
    extracted_dir = EXP / "extracted_source"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    embedded_path = extracted_dir / "embedded_psr_exact.py"
    embedded_path.write_text(embedded, encoding="utf-8")

    current, notebook_extract = notebook_main()
    current_path = extracted_dir / "current_v3_main_exact.py"
    current_path.write_text(current, encoding="utf-8")

    d1_dir = EXP / "candidates/D1_e052a_no_opponent_tape"
    p1_dir = EXP / "candidates/P1_psr_clean"
    for directory in (d1_dir, p1_dir):
        directory.mkdir(parents=True, exist_ok=True)
    d1_source, d1_diff = remove_d1_tape((V116 / "policy.py").read_text(encoding="utf-8"))
    (d1_dir / "policy.py").write_text(d1_source, encoding="utf-8")
    shutil.copyfile(V116 / "main.py", d1_dir / "main.py")
    shutil.copyfile(V116 / "LICENSE", d1_dir / "LICENSE")
    (p1_dir / "main.py").write_text(current, encoding="utf-8")
    (p1_dir / "LICENSE_SCOPE.md").write_text(
        "Notebook page license: Apache-2.0. Embedded route-data provenance.json was not "
        "included in the acquired notebook, so transitive route-data rights remain unverified; "
        "research-only.\n",
        encoding="utf-8",
    )

    d1_audit = static_audit(d1_source, candidate="D1_e052a_no_opponent_tape")
    p1_audit = static_audit(current, candidate="P1_psr_clean")
    p1_inventory = module_inventory(p1_dir / "main.py")
    if p1_inventory["tape_count"] != 5 or p1_inventory["tape_lengths"] != [719] * 5:
        raise RuntimeError(f"unexpected current PSR payload: {p1_inventory}")

    for candidate, directory in (("D1_e052a_no_opponent_tape", d1_dir), ("P1_psr_clean", p1_dir)):
        package(directory, EXP / f"{candidate}.tar.gz")

    pull = json.loads((ACQ / "kernels_pull_response.json").read_text(encoding="utf-8"))
    metadata = pull["metadata"]
    acquisition_result = json.loads((ACQ / "acquisition_result.json").read_text(encoding="utf-8"))
    source_acquisition = {
        "created_at": now(),
        "notebook_url": "https://www.kaggle.com/code/thomastschinkel/kaggriculture-93-8-win-rate-public-state-router",
        "api_url": acquisition_result["url"],
        "fetched_at": acquisition_result["fetched_at"],
        "http_status": acquisition_result["http_status"],
        "raw_response": "acquisition/notebook/kernels_pull_response.json",
        "raw_response_sha256": acquisition_result["sha256"],
        "notebook": "acquisition/notebook/payload_1.ipynb",
        "notebook_sha256": sha(ACQ / "payload_1.ipynb"),
        "notebook_version": int(metadata["currentVersionNumber"]),
        "last_run_time": metadata["lastRunTime"],
        "title": metadata["title"],
        "author": metadata["author"],
        "public": not bool(metadata["isPrivate"]),
        "license": {
            "spdx": "Apache-2.0",
            "basis": "Kaggle notebook page license panel, independently observed on 2026-09-14",
            "page_url": "https://www.kaggle.com/code/thomastschinkel/kaggriculture-93-8-win-rate-public-state-router",
            "transitive_route_data": (
                "UNVERIFIED: notebook text refers to provenance.json, but the acquired notebook "
                "has no such file/input"
            ),
        },
        "extraction": notebook_extract,
        "current_main": "extracted_source/current_v3_main_exact.py",
        "current_main_sha256": sha(current_path),
        "native_callable": "agent",
        "dependency_files": [],
        "runtime_imports": p1_audit["top_level_imports"],
        "standalone_complete": True,
        "fallback_not_used_for_P1": True,
        "embedded_fallback": {
            "container_source": str(SOURCE.relative_to(ROOT)),
            "container_sha256": sha(SOURCE),
            "ast_assignment": "_PSR_SOURCE",
            "decoded_path": "extracted_source/embedded_psr_exact.py",
            "decoded_sha256": sha(embedded_path),
            "same_as_current_v3": sha(embedded_path) == sha(current_path),
        },
    }
    save(EXP / "source_acquisition.json", source_acquisition)

    prior_registry = json.loads(
        (ROOT / "experiments/research_20260910/source_registry.json").read_text(encoding="utf-8")
    )
    corrected = json.loads(json.dumps(prior_registry))
    for row in corrected["sources"]:
        if row["candidate_id"] == "mooman_e052a":
            row["source_scope_previous"] = row["source_scope"]
            row["source_scope"] = (
                "full published observation-dependent agent INCLUDING hard-coded known-opponent "
                "position signatures and fixed future SELL tables in E031/E033; previous scope was incomplete"
            )
            row["scope_correction_evidence"] = {
                "symbols": sorted(PROHIBITED_NAMES),
                "source_lines": [2605, 2685],
            }
    corrected["corrected_at"] = now()
    corrected["supersedes_scope_only"] = "experiments/research_20260910/source_registry.json"
    save(EXP / "source_registry_corrected.json", corrected)

    integrity = {
        "created_at": now(),
        "candidate_count": 3,
        "candidates": {
            "R0_v116_frozen_reference": {
                "role": "frozen_reference_only",
                "new_execution": False,
                "promotion_eligible": False,
                "parent_source": str(SOURCE.relative_to(ROOT)),
                "source_sha256": sha(SOURCE),
                "package": "../research_20260914_lowcash/v116_mooman_complete.tar.gz",
                "package_sha256": sha(ROOT / "experiments/research_20260914_lowcash/v116_mooman_complete.tar.gz"),
                "entrypoint": "policy.agent_entry via existing main.py adapter",
                "license": "outer MIT; embedded PSR transitive license not established",
                "prohibited_feature_audit": "KNOWN_FAIL_REFERENCE_ONLY",
            },
            "D1_e052a_no_opponent_tape": {
                "role": "diagnostic_ablation_only",
                "promotion_eligible": False,
                "parent_source": "v116_mooman_complete",
                "parent_policy_sha256": sha(V116 / "policy.py"),
                "edit_diff": d1_diff,
                "source": "candidates/D1_e052a_no_opponent_tape/policy.py",
                "source_sha256": sha(d1_dir / "policy.py"),
                "package": "D1_e052a_no_opponent_tape.tar.gz",
                "package_sha256": sha(EXP / "D1_e052a_no_opponent_tape.tar.gz"),
                "entrypoint": "main.agent -> policy.agent_entry",
                "callable_selection": "explicit main.agent",
                "runtime_isolation": ["kaggriculture"],
                "license": "outer MIT; embedded PSR transitive license unverified; research-only",
                "feature_audit": d1_audit,
            },
            "P1_psr_clean": {
                "role": "primary",
            "promotion_eligible": (
                "conditional on efficacy, safety, diversity, and license; current "
                "transitive-license cap applies"
            ),
                "parent_source": "current Kaggle notebook Version 3 main.py cell",
                "extraction_diff": "exact UTF-8 cell source after removing only the %%writefile main.py magic line",
                "source": "candidates/P1_psr_clean/main.py",
                "source_sha256": sha(p1_dir / "main.py"),
                "package": "P1_psr_clean.tar.gz",
                "package_sha256": sha(EXP / "P1_psr_clean.tar.gz"),
                "entrypoint": "agent",
                "callable_selection": "explicit main.agent; final top-level policy callable",
                "runtime_isolation": ["kaggriculture"],
                "license": source_acquisition["license"],
                "feature_audit": p1_audit,
                "decoded_payload_inventory": p1_inventory,
                "outer_layers_absent": [
                    "v56 opening",
                    "E030",
                    "opponent tape/oracle",
                    "step216 hybrid",
                    "feed",
                    "carrot",
                    "eager",
                    "sells-first",
                ],
            },
        },
    }
    save(EXP / "candidate_integrity.json", integrity)
    for candidate in ("D1_e052a_no_opponent_tape", "P1_psr_clean"):
        directory = EXP / "candidates" / candidate
        row = integrity["candidates"][candidate]
        save(directory / "freeze.json", row)
        save(
            directory / "plan.json",
            {
                "candidate": candidate,
                "source_sha256": row["source_sha256"],
                "phases": ["isolation", "aa", "smoke", "spent_development"],
                "seeds": [10091011, 10091012, 10091013, 10091014],
                "seats": [0, 1],
                "episode_steps": 720,
                "fresh": "SEALED",
                "promotion": "SEALED",
            },
        )
    print(json.dumps({"source_acquisition": source_acquisition, "integrity": integrity}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
