"""Collapse every completed common probe into one executed Gold registry."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROBES = (
    ROOT / "data/evaluation/independent_gold_pool/common_probe.json",
    ROOT / "data/evaluation/independent_gold_pool/public_candidate_addendum_probe.json",
    ROOT / "data/evaluation/independent_gold_pool/public_pure_route_probe.json",
    ROOT / "data/evaluation/independent_gold_pool/public_history_candidate_probe.json",
    ROOT
    / "data/evaluation/independent_gold_pool/"
    "public_external_github_candidate_probe.json",
)
DEFAULT_OUTPUT = (
    ROOT
    / "experiments/independent_gold_pool/"
    "consolidated_gold_family_registry_expanded_public_20260902.json"
)
DEFAULT_REPORT = ROOT / "docs/independent_gold_family_registry_expanded_public_20260902.md"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object: {path}")
    return payload


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _normalized_ancestry(candidate_id: str, raw: Any) -> str:
    """Prevent one public repository snapshot from creating extra Meta votes."""
    for prefix, normalized in (
        ("public_github_gzmcr_", "github_gzmcr"),
        ("public_history_gzmcr_", "github_gzmcr"),
        ("public_github_lonespear_", "github_lonespear"),
        ("public_history_lonespear_", "github_lonespear"),
        ("public_github_seyamalam_", "github_seyamalam_public_v18_derived"),
        ("public_history_seyamalam_", "github_seyamalam_public_v18_derived"),
    ):
        if candidate_id.startswith(prefix):
            return normalized
    return str(raw or candidate_id)


def build(
    paths: list[Path],
    *,
    created_at: str | None = None,
    extended_metadata: bool = True,
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    complete_sources = 0
    source_labels = 0
    for path in paths:
        probe = _load(path)
        candidates = {
            str(row["candidate_id"]): row for row in probe.get("candidates") or []
        }
        sources = {
            str(row["candidate_id"]): row
            for row in (probe.get("clustering") or {}).get("sources") or []
        }
        source_labels += len(sources)
        complete_sources += sum(
            str(row.get("probe_status")) == "COMPLETE" for row in sources.values()
        )
        for family in (probe.get("clustering") or {}).get("exact_families") or []:
            signature = str(family["family_signature"])
            record = grouped.setdefault(
                signature,
                {
                    "family_signature": signature,
                    "source_members": [],
                    "probe_origins": [],
                    "source_records": [],
                },
            )
            record["probe_origins"].append(_relative(path))
            for member in family.get("source_members") or []:
                member = str(member)
                candidate = candidates[member]
                source = sources[member]
                if source.get("probe_status") != "COMPLETE":
                    raise ValueError(f"non-complete source entered family: {member}")
                entrypoint = candidate.get("entrypoint")
                if candidate.get("kind") == "python":
                    entry = Path(str(entrypoint)).resolve()
                    if not entry.is_file():
                        raise FileNotFoundError(entry)
                    if _sha(entry) != str(candidate.get("entrypoint_sha256")):
                        raise ValueError(f"entrypoint hash changed: {member}")
                record["source_members"].append(member)
                record["source_records"].append(
                    {
                        "candidate_id": member,
                        "kind": candidate.get("kind"),
                        "entrypoint": entrypoint,
                        "entrypoint_sha256": candidate.get("entrypoint_sha256"),
                        "dependency_closure_sha256": candidate.get(
                            "dependency_closure_sha256"
                        ),
                        "provenance": candidate.get("provenance"),
                        "artifact_scope": candidate.get("artifact_scope"),
                        "source_ancestry_id": candidate.get("source_ancestry_id"),
                        "normalized_source_ancestry_id": _normalized_ancestry(
                            member, candidate.get("source_ancestry_id")
                        ),
                        "archetype_hint": candidate.get("archetype_hint"),
                        "license": candidate.get("license"),
                        "panel_restriction": candidate.get("panel_restriction"),
                        "probe_strict_win_rate_of_v111": source.get(
                            "strict_win_rate_of_v111"
                        ),
                        "probe_win_score_of_v111": source.get("win_score_of_v111"),
                        "probe_mean_margin_of_v111": source.get("mean_margin_of_v111"),
                    }
                )

    families = []
    for signature, record in sorted(grouped.items()):
        sources = record["source_records"]
        win_scores = {float(row["probe_win_score_of_v111"]) for row in sources}
        strict_rates = {
            float(row["probe_strict_win_rate_of_v111"]) for row in sources
        }
        margins = {float(row["probe_mean_margin_of_v111"]) for row in sources}
        if len(win_scores) != 1 or len(strict_rates) != 1 or len(margins) != 1:
            raise ValueError(f"same action family produced inconsistent payoff: {signature}")
        win_score = next(iter(win_scores))
        kinds = sorted({str(row["kind"]) for row in sources})
        calibration_only = any(
            row.get("panel_restriction") == "calibration_only"
            or row["candidate_id"] == "v111_self_calibration"
            for row in sources
        )
        is_open_loop_route = all(
            row["candidate_id"].startswith("public_route_") for row in sources
        )
        is_public_repo_head = any(
            row["candidate_id"].startswith("public_github_") for row in sources
        )
        is_public_repo_history = any(
            row["candidate_id"].startswith("public_history_") for row in sources
        )
        if "builtin" in kinds:
            scope = "engine_builtin_executable"
        elif is_open_loop_route:
            scope = "public_executable_open_loop_route"
        elif is_public_repo_head:
            scope = "public_closed_loop_repository_snapshot"
        elif is_public_repo_history:
            scope = "public_closed_loop_repository_history_snapshot"
        else:
            scope = "local_or_archived_closed_loop_executable"
        family = {
            **record,
            "behavior_family_id": f"gold_exec_{signature[:8]}",
            "source_members": sorted(set(record["source_members"])),
            "probe_origins": sorted(set(record["probe_origins"])),
            "evidence_tier": "Gold executable",
            "policy_scope": scope,
            "source_ancestry_ids": sorted(
                {
                    str(
                        row.get(
                            "normalized_source_ancestry_id"
                            if extended_metadata
                            else "source_ancestry_id"
                        )
                        or row["candidate_id"]
                    )
                    for row in sources
                }
            ),
            "calibration_only": calibration_only,
            "v111_probe_strict_win_rate": next(iter(strict_rates)),
            "v111_probe_win_score": win_score,
            "v111_probe_mean_margin": next(iter(margins)),
            "sensitivity_target_30_to_70": (
                not calibration_only
                and "builtin" not in kinds
                and 0.30 <= win_score <= 0.70
            ),
            "near_sensitivity_70_to_80": (
                not calibration_only
                and "builtin" not in kinds
                and 0.70 < win_score <= 0.80
            ),
        }
        families.append(family)

    target = [
        row["behavior_family_id"]
        for row in families
        if row["sensitivity_target_30_to_70"]
    ]
    near = [
        row["behavior_family_id"]
        for row in families
        if row["near_sensitivity_70_to_80"]
    ]
    registry = {
        "format": "kaggriculture-consolidated-executed-gold-registry-v1",
        "created_at": created_at or datetime.now().astimezone().isoformat(),
        "identity_rule": (
            "Exact equality of the complete common-seed, both-seat action-prefix "
            "vector at turns 24/100/200/400/719. Source names do not create families."
        ),
        "statistical_guardrail": (
            "Executed action families are the clustering unit; shared ancestry and "
            "open-loop routes still receive capped or zero Meta votes as appropriate."
        ),
        "probe_inputs": [
            {"path": _relative(path), "sha256": _sha(path)} for path in paths
        ],
        "coverage": {
            "source_labels": source_labels,
            "complete_source_labels": complete_sources,
            "exact_executed_action_families": len(families),
            "distinct_source_ancestry_ids": len(
                {
                    ancestry
                    for row in families
                    for ancestry in row["source_ancestry_ids"]
                }
            ),
            "python_action_families": sum(
                all(source["kind"] == "python" for source in row["source_records"])
                for row in families
            ),
            "engine_builtin_families": sum(
                any(source["kind"] == "builtin" for source in row["source_records"])
                for row in families
            ),
        },
        "sensitivity": {
            "eligible_opponent_family_ids_30_to_70": target,
            "eligible_opponent_family_count": len(target),
            "near_family_ids_70_to_80": near,
            "adequacy": "INSUFFICIENT" if len(target) < 3 else "ADEQUATE",
            "calibration_clone_excluded": True,
        },
        "operational_manifests": [
            "experiments/independent_gold_pool/family_panel_manifest.json",
            "experiments/independent_gold_pool/public_gold_addendum_panel_manifest.json",
        ],
        "discovery_source_manifests": [
            "experiments/independent_gold_pool/candidate_sources.json",
            "experiments/independent_gold_pool/public_candidate_addendum_sources.json",
            "experiments/independent_gold_pool/public_pure_route_candidate_sources.json",
            "experiments/independent_gold_pool/public_history_candidate_sources.json",
            "experiments/independent_gold_pool/public_external_github_candidate_sources.json",
        ],
        "fresh_holdout_status": (
            "Every family and seed in this registry is Development and ineligible for "
            "Fresh Holdout."
        ),
        "families": families,
    }
    if not extended_metadata:
        registry["coverage"].pop("distinct_source_ancestry_ids", None)
        registry.pop("discovery_source_manifests", None)
        for family in registry["families"]:
            for source in family["source_records"]:
                source.pop("normalized_source_ancestry_id", None)
                source.pop("archetype_hint", None)
                source.pop("license", None)
    return registry


def render(registry: dict[str, Any]) -> str:
    coverage = registry["coverage"]
    sensitivity = registry["sensitivity"]
    lines = [
        "# Consolidated Independent Gold action-family registry",
        "",
        f"- Source labels probed: {coverage['source_labels']}",
        f"- Completed source labels: {coverage['complete_source_labels']}",
        f"- Exact executed action families: {coverage['exact_executed_action_families']}",
        *(
            [
                "- Distinct normalized source-ancestry ids: "
                f"{coverage['distinct_source_ancestry_ids']}"
            ]
            if "distinct_source_ancestry_ids" in coverage
            else []
        ),
        f"- Python action families: {coverage['python_action_families']}",
        f"- Engine builtin families: {coverage['engine_builtin_families']}",
        "",
        "A family is defined by executed actions over common seeds and both seats, not by source name. "
        "Shared ancestry is retained separately and prevents Meta-vote inflation.",
        "",
        (
            "Sensitivity status: **{status}**; genuine 30–70% opponent families: {count}; "
            "near 70–80% families: {near}."
        ).format(
            status=sensitivity["adequacy"],
            count=sensitivity["eligible_opponent_family_count"],
            near=len(sensitivity["near_family_ids_70_to_80"]),
        ),
        "The V110/V111 calibration clone is not counted as a Sensitivity opponent.",
        "",
        "| Family | Sources | Scope | V111 probe score | Mean margin | Target |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for row in registry["families"]:
        lines.append(
            "| {family} | {sources} | {scope} | {score:.1%} | {margin:+.1f} | {target} |".format(
                family=row["behavior_family_id"],
                sources=len(row["source_members"]),
                scope=row["policy_scope"],
                score=row["v111_probe_win_score"],
                margin=row["v111_probe_mean_margin"],
                target="yes" if row["sensitivity_target_30_to_70"] else "no",
            )
        )
    lines.extend(
        [
            "",
            "All entries are Development data. None is Fresh Holdout.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="append", default=[])
    parser.add_argument(
        "--created-at",
        default=None,
        help="Optional frozen ISO timestamp for deterministic registry reproduction.",
    )
    parser.add_argument(
        "--legacy-schema",
        action="store_true",
        help="Omit post-history metadata when reproducing the historical three-probe file.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
    )
    parser.add_argument(
        "--report", default=str(DEFAULT_REPORT)
    )
    args = parser.parse_args()
    paths = [Path(value).resolve() for value in args.probe] or [
        path.resolve() for path in DEFAULT_PROBES
    ]
    output = Path(args.output).resolve()
    report = Path(args.report).resolve()
    registry = build(
        paths,
        created_at=args.created_at,
        extended_metadata=not args.legacy_schema,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render(registry), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": _relative(output),
                "sha256": _sha(output),
                "coverage": registry["coverage"],
                "sensitivity": registry["sensitivity"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
