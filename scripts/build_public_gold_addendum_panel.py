"""Build a preregistered V111/V113 panel for newly acquired public Gold code.

This addendum is separate from the completed 180-pair experiment.  Every
source was already executed on the common probe, so neither its families nor
these seeds can later be called Fresh Holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_gold_family_panel_manifest import _style_tags  # noqa: E402
from scripts.gold_opponent_pool import (  # noqa: E402
    ROOT,
    dependency_closure_sha256,
    sha256_file,
)

DEFAULT_PROBES = (
    ROOT / "data/evaluation/independent_gold_pool/public_candidate_addendum_probe.json",
    ROOT / "data/evaluation/independent_gold_pool/public_pure_route_probe.json",
)
DEFAULT_OUTPUT = (
    ROOT / "experiments/independent_gold_pool/public_gold_addendum_panel_manifest.json"
)
DEVELOPMENT_SEEDS = tuple(range(29117001, 29117007))


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


def build(probe_paths: list[Path]) -> dict[str, Any]:
    families: list[dict[str, Any]] = []
    closed_loop_ids: list[str] = []
    route_ids: list[str] = []
    near_target_ids: list[str] = []
    seen_signatures: set[str] = set()

    for probe_path in probe_paths:
        probe = _load(probe_path)
        candidates = {
            str(row["candidate_id"]): row for row in probe.get("candidates") or []
        }
        sources = {
            str(row["candidate_id"]): row
            for row in (probe.get("clustering") or {}).get("sources") or []
        }
        games_by_source: dict[str, list[dict[str, Any]]] = {}
        for game in probe.get("games") or []:
            games_by_source.setdefault(str(game["candidate_id"]), []).append(game)

        for raw_family in (probe.get("clustering") or {}).get("exact_families") or []:
            signature = str(raw_family["family_signature"])
            if signature in seen_signatures:
                raise ValueError(f"duplicate exact family across addendum probes: {signature}")
            seen_signatures.add(signature)
            representative = str(raw_family["representative_candidate_id"])
            candidate = candidates[representative]
            source = sources[representative]
            entrypoint = Path(str(candidate["entrypoint"])).resolve()
            if not entrypoint.is_file():
                raise FileNotFoundError(entrypoint)
            if sha256_file(entrypoint) != str(candidate["entrypoint_sha256"]):
                raise ValueError(f"entrypoint hash changed: {representative}")
            if dependency_closure_sha256(entrypoint) != str(
                candidate["dependency_closure_sha256"]
            ):
                raise ValueError(f"dependency closure changed: {representative}")

            family_id = f"gold_public_{signature[:8]}"
            is_closed_loop = representative.startswith("public_github_")
            panels = ["sensitivity", "regression"]
            if is_closed_loop:
                panels.append("meta")
                closed_loop_ids.append(family_id)
            else:
                route_ids.append(family_id)
            win_score = float(source["win_score_of_v111"])
            if 0.70 <= win_score <= 0.80:
                near_target_ids.append(family_id)
            families.append(
                {
                    "behavior_family_id": family_id,
                    "family_signature": signature,
                    "representative_candidate_id": representative,
                    "entrypoint": str(entrypoint),
                    "entrypoint_sha256": sha256_file(entrypoint),
                    "dependency_closure_sha256": dependency_closure_sha256(entrypoint),
                    "provenance": candidate.get("provenance"),
                    "artifact_scope": candidate.get("artifact_scope"),
                    "license": candidate.get("license"),
                    "source_members": list(raw_family.get("source_members") or []),
                    "source_ancestry_ids": list(
                        raw_family.get("source_ancestry_ids") or []
                    ),
                    "meta_vote_group": (
                        str((raw_family.get("source_ancestry_ids") or [family_id])[0])
                        if is_closed_loop
                        else f"open_loop_route:{family_id}"
                    ),
                    "style_tags": _style_tags(
                        representative,
                        games_by_source.get(representative, []),
                        {},
                    ),
                    "contains_exact_public_or_submitted_artifact": bool(
                        candidate.get("exact_submitted_or_public_artifact")
                    ),
                    "contains_forced_fixture": False,
                    "closed_loop_policy": is_closed_loop,
                    "fresh_holdout_eligible": False,
                    "v111_probe_strict_win_rate": float(
                        source["strict_win_rate_of_v111"]
                    ),
                    "v111_probe_win_score": win_score,
                    "v111_probe_mean_margin": float(source["mean_margin_of_v111"]),
                    "panels": sorted(panels),
                    "meta_weight": 1.0 if is_closed_loop else None,
                }
            )

    families.sort(key=lambda row: str(row["behavior_family_id"]))
    all_ids = [str(row["behavior_family_id"]) for row in families]
    controls = {}
    for name, relative, role in (
        ("clean_v111", "agents/v111/main.py", "clean causal control"),
        (
            "live_benchmark_v113",
            "agents/v113/main.py",
            "live-validated field benchmark; not gate-causal proof",
        ),
    ):
        entrypoint = (ROOT / relative).resolve()
        controls[name] = {
            "entrypoint": str(entrypoint),
            "entrypoint_sha256": sha256_file(entrypoint),
            "dependency_closure_sha256": dependency_closure_sha256(entrypoint),
            "role": role,
        }

    def panel(family_ids: list[str], description: str) -> dict[str, Any]:
        return {
            "description": description,
            "family_ids": family_ids,
            "seeds": list(DEVELOPMENT_SEEDS),
            "both_seats": True,
            "weights": {family_id: 1.0 for family_id in family_ids},
        }

    return {
        "format": "kaggriculture-public-gold-addendum-panel-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "dataset_role": (
            "Discovery/Development public executable addendum; permanently excluded "
            "from Fresh Holdout"
        ),
        "source_probes": [
            {"path": _relative(path), "sha256": _sha(path)} for path in probe_paths
        ],
        "controls": controls,
        "selection": {
            "selected_family_count": len(families),
            "closed_loop_public_family_count": len(closed_loop_ids),
            "executable_open_loop_route_count": len(route_ids),
            "exact_action_family_collapse": True,
            "sensitivity_target_family_ids": [],
            "near_target_70_to_80_family_ids": near_target_ids,
            "sensitivity_adequacy": {
                "status": "INSUFFICIENT",
                "target_family_count": 0,
                "reason": (
                    "No newly acquired family had a draw-adjusted V111 common-probe "
                    "win score in the preregistered 30-70% target band."
                ),
            },
        },
        "preregistered_dual_benchmark": {
            "purpose": (
                "Add only newly acquired executable public families to the V111/V113 "
                "comparison without rerunning the completed 180-pair experiment."
            ),
            "planned_unique_pairs": len(families) * len(DEVELOPMENT_SEEDS) * 2,
            "report_separately": [
                "total_pairs",
                "trigger_pairs",
                "actual_treatment_pairs",
                "discordant_outcome_pairs",
                "hard_safety_failure_pairs",
                "treatment_delivery_failures",
            ],
            "base_selection_rule": {
                "retain_v113_as_v114_base_candidate": (
                    "Requires no Hard Safety Failure, positive major-family discordance, "
                    "and non-inferior family-clustered win-score intervals; this addendum "
                    "cannot override the completed benchmark's safety failure."
                ),
                "return_to_v111_base": (
                    "Keep V111 as clean champion when V113 has any unresolved Hard Safety "
                    "Failure or a major-family regression."
                ),
                "dual_champion_candidates": (
                    "Allowed only if safety passes and strength is unresolved."
                ),
            },
            "v114_authorization": (
                "None. A repeated executable loss regime and preregistered Targeted "
                "Efficacy experiment are still required."
            ),
        },
        "families": families,
        "panels": {
            "sensitivity": {
                **panel(
                    all_ids,
                    "All newly acquired exact executable families; zero are in the 30-70% target band.",
                ),
                "target_family_ids_30_to_70": [],
                "near_target_family_ids_70_to_80": near_target_ids,
                "coverage_extension_family_ids": all_ids,
            },
            "meta": {
                **panel(
                    sorted(closed_loop_ids),
                    "Provisional equal-weight public closed-loop policies only; not live-frequency weights.",
                ),
                "weight_source": "provisional_equal_public_closed_loop_family_weight",
                "shared_ancestry_vote_rule": "one vote per source ancestry",
            },
            "regression": panel(
                all_ids,
                "Public executable diversity/easy-matchup coverage; not positive-uplift proof.",
            ),
            "fresh_holdout": {
                "description": "Reserved for later unprobed executable families and seeds.",
                "family_ids": [],
                "seeds": [],
                "both_seats": True,
                "reserved": True,
            },
        },
        "fresh_holdout_exclusions": {
            "all_addendum_family_ids": all_ids,
            "common_probe_seeds": [29114001, 29114002],
            "expanded_development_seeds": list(DEVELOPMENT_SEEDS),
        },
    }


def render(manifest: dict[str, Any]) -> str:
    lines = [
        "# Public Gold executable addendum manifest",
        "",
        f"Selected exact executable families: **{len(manifest['families'])}**.",
        "",
        "The four public GitHub HEAD policies form only a provisional Meta diagnostic. "
        "The ten executable routes are Gold for their local route behavior, not proof of "
        "the original author's full closed-loop submission.",
        "",
        "| Family | Representative | Closed loop | V111 probe WR | Margin | Panels |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in manifest["families"]:
        lines.append(
            "| {fid} | {rep} | {closed} | {wr:.1%} | {margin:+.1f} | {panels} |".format(
                fid=row["behavior_family_id"],
                rep=row["representative_candidate_id"],
                closed="yes" if row["closed_loop_policy"] else "no",
                wr=row["v111_probe_strict_win_rate"],
                margin=row["v111_probe_mean_margin"],
                panels=", ".join(row["panels"]),
            )
        )
    lines.extend(
        [
            "",
            "No source is Fresh Holdout. No strategy or Kaggle submission is authorized by this manifest.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="append", default=[])
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--report",
        default=str(ROOT / "docs/independent_gold_public_addendum_manifest.md"),
    )
    args = parser.parse_args()
    probe_paths = [Path(value).resolve() for value in args.probe] or [
        path.resolve() for path in DEFAULT_PROBES
    ]
    output = Path(args.output).resolve()
    report = Path(args.report).resolve()
    manifest = build(probe_paths)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render(manifest), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": _relative(output),
                "sha256": _sha(output),
                "families": len(manifest["families"]),
                "planned_pairs": manifest["preregistered_dual_benchmark"][
                    "planned_unique_pairs"
                ],
                "sensitivity": manifest["selection"]["sensitivity_adequacy"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
