"""Static execution-safety and entry inventory for extracted Round11 agents."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path


def dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def audit(path: Path) -> dict:
    data = path.read_bytes()
    source = data.decode("utf-8")
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")

    risky_prefixes = (
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "http.client",
        "shutil.rmtree",
        "os.system",
        "os.popen",
        "os.remove",
        "os.unlink",
        "os.rmdir",
    )
    calls = []
    dynamic = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted(node.func)
        if name in {"eval", "exec", "compile", "__import__"}:
            first = node.args[0] if node.args else None
            literal = isinstance(first, ast.Constant) and isinstance(first.value, (str, bytes))
            parseable = None
            literal_sha256 = None
            literal_bytes = None
            if literal:
                value = first.value.encode("utf-8") if isinstance(first.value, str) else first.value
                literal_sha256 = hashlib.sha256(value).hexdigest()
                literal_bytes = len(value)
                try:
                    ast.parse(value.decode("utf-8"))
                    parseable = True
                except (UnicodeDecodeError, SyntaxError):
                    parseable = False
            dynamic.append(
                {
                    "line": node.lineno,
                    "call": name,
                    "literal": literal,
                    "literal_parseable_python": parseable,
                    "literal_bytes": literal_bytes,
                    "literal_sha256": literal_sha256,
                }
            )
        if name == "open" or name.startswith(risky_prefixes) or name.endswith(
            (".write_text", ".write_bytes", ".unlink", ".rmdir")
        ):
            calls.append({"line": node.lineno, "call": name})

    top_functions = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "imports": sorted(set(imports)),
        "external_io_imports": sorted(
            {
                name
                for name in imports
                if name.split(".")[0]
                in {"requests", "urllib", "http", "socket", "subprocess", "shutil"}
            }
        ),
        "risky_calls": calls,
        "dynamic_execution": dynamic,
        "top_level_function_count": len(top_functions),
        "last_top_level_function": top_functions[-1] if top_functions else None,
        "static_audit_pass": not calls
        and not any(
            row["call"] in {"eval", "__import__"}
            or (row["call"] == "exec" and not (row["literal"] and row["literal_parseable_python"]))
            for row in dynamic
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [audit(path.resolve()) for path in args.paths]
    result = {
        "schema": "round11-static-agent-audit-v1",
        "agents": rows,
        "all_pass": all(row["static_audit_pass"] for row in rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
