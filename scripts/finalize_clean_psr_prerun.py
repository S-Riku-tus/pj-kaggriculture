"""Finalize clean-PSR preregistration audits from completed offline artifacts."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/research_20260914_clean_psr"
PAIRS = ROOT / "data/evaluation/research_20260914_lowcash/discovery/pairs.jsonl"
POLICY = ROOT / "experiments/research_20260914_lowcash/runtime/v116_mooman_complete/policy.py"


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in PAIRS.read_text(encoding="utf-8").splitlines() if line]


def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    c = Counter(row["treatment"]["result"] for row in items)
    score = sum(float(row["delta_win_score"]) for row in items)
    return {
        "contexts": len(items),
        "treatment_wdl": {"wins": c["win"], "draws": c["draw"], "losses": c["loss"]},
        "paired_win_score_delta": score / len(items) if items else None,
        "loss_to_win": sum(bool(row.get("loss_to_win")) for row in items),
        "win_to_loss": sum(bool(row.get("win_to_loss")) for row in items),
    }


def trace_index(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    traces = []
    for row in items:
        seat = int(row["seat"])
        path = EXP / "sidecar/v116" / f"{row['lineage_id']}_{row['seed']}_{seat}.json.gz"
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            records = json.load(handle)
        mismatches = [record for record in records if not record.get("matches_replay")]
        if len(records) != 719 or mismatches:
            raise RuntimeError(f"invalid sidecar {path}: records={len(records)} mismatches={len(mismatches)}")
        traces.append(
            {
                "source": row["lineage_id"],
                "seed": row["seed"],
                "seat": seat,
                "steps": len(records),
                "action_mismatch_count": 0,
                "observation_step_reconstructed_count": sum(
                    bool(record.get("observation_step_reconstructed")) for record in records
                ),
                "sidecar": str(path.relative_to(ROOT)),
                "sidecar_sha256": sha(path),
            }
        )
    return traces


def seed_ledger() -> dict[str, Any]:
    groups = {
        "promotion": set(range(10091101, 10091113)),
        "fresh": set(range(10091901, 10091913)),
        "new_development": set(range(10091421, 10091437)),
    }
    target = set().union(*groups.values())
    records = []
    excluded = {".git", ".venv", ".uv-cache", "vendor", "node_modules", "__pycache__"}
    for path in ROOT.rglob("*.jsonl"):
        if any(part in excluded for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            for key in ("seed", "requested_seed", "resolved_seed"):
                seed = value.get(key)
                if isinstance(seed, int) and seed in target:
                    records.append({"path": str(path.relative_to(ROOT)), "line": number, "field": key, "seed": seed})
    used = {record["seed"] for record in records}
    result: dict[str, Any] = {
        "created_at": now(),
        "method": "repository-wide structured *.jsonl seed-field audit; binary/cache/vendor excluded",
        "structured_usage_records": records,
    }
    for name, seeds in groups.items():
        hit = sorted(used & seeds)
        result[name] = {
            "range": [min(seeds), max(seeds)],
            "used": hit,
            "status": "UNUSED" if not hit else "USED",
        }
    return result


def main() -> None:
    prior = rows()
    if len(prior) != 32:
        raise RuntimeError(f"expected 32 frozen pairs, got {len(prior)}")
    traces = trace_index(prior)
    save(
        EXP / "source_layer_map.json",
        {
            "created_at": now(),
            "source": str(POLICY.relative_to(ROOT)),
            "source_sha256": sha(POLICY),
            "method": (
                "offline replay-observation re-execution with return-value wrappers; seat-1 public "
                "step reconstructed from turn index because serialized observation omitted it"
            ),
            "layers": [
                {"order": 1, "name": "v56/backbone + sweep/opening/E030", "entry": "_pre_orak_agent"},
                {"order": 2, "name": "self-route phantom horizon", "entry": "_orak_front_run"},
                {
                    "order": 3,
                    "name": "known-opponent tape/future SELL",
                    "entry": "_tape_observe/_tape_preds",
                    "prohibited": True,
                },
                {"order": 4, "name": "opening churn guard", "entry": "_open_guard"},
                {"order": 5, "name": "embedded PSR hybrid from step216", "entry": "_psr_act"},
                {
                    "order": 6,
                    "name": "feed/carrot/eager/sells-first",
                    "entry": "_feed_g/_carrot_swap/_carrot_seeds/_eager_sell/_sells_first",
                },
            ],
            "traces": traces,
            "all_final_actions_reproduced": True,
            "contexts": len(traces),
            "decisions": sum(trace["steps"] for trace in traces),
        },
    )
    subsets = {
        "all": prior,
        "exclude_mooman_self": [row for row in prior if row["lineage_id"] != "mooman_e052a"],
        "exclude_tape2_sources": [row for row in prior if row["lineage_id"] not in {"mooman_e052a", "souvik_v4"}],
        "exclude_psr_kaito_near_lineage": [row for row in prior if row["lineage_id"] == "qeinstein_moev2"],
    }
    save(
        EXP / "r0_sensitivity.json",
        {
            "created_at": now(),
            "frozen_reference": "R0_v116_frozen_reference",
            **{name: summary(items) for name, items in subsets.items()},
            "interpretation": "source exclusions are sensitivity analyses, not deployable selectors",
        },
    )
    ledger = seed_ledger()
    save(EXP / "seed_ledger.json", ledger)
    tape = json.loads((EXP / "tape_confounding_audit.json").read_text(encoding="utf-8"))
    safety = json.loads((EXP / "safety_first_event_map.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "tape_match": tape["prior_audit_gate_counts_match"],
                "safety_contexts": safety["contexts_with_raw_safety"],
                "traces": len(traces),
                "decisions": sum(trace["steps"] for trace in traces),
                "all_actions_match": True,
                "seed_status": {name: ledger[name]["status"] for name in groups_names()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def groups_names() -> tuple[str, ...]:
    return ("promotion", "fresh", "new_development")


if __name__ == "__main__":
    main()
