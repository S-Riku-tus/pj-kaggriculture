"""Derive independent executable-family panels from the common probe.

The common probe is Discovery/Development data.  This builder never labels a
probed source, family, or seed Fresh Holdout.  Exact action families remain the
unit of evaluation; source names are provenance only.  Shared forced branches
from one router ancestry may be useful sensitivity fixtures, but receive at
most one Meta-panel vote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from scripts.gold_opponent_pool import ROOT, dependency_closure_sha256, sha256_file

FORMAT = "kaggriculture-independent-gold-family-panel-v1"
DEFAULT_DEVELOPMENT_SEEDS = tuple(range(29115001, 29115007))
FORMAL_REGRESSION_SOURCE_IDS = {
    "local_v11",
    "local_v14",
    "local_v18_default",
    "public_v27_raw",
    "public_v43_raw",
}


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def _load_json(path: Path) -> tuple[dict[str, Any], str]:
    encoded = path.read_bytes()
    payload = json.loads(encoded.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload, hashlib.sha256(encoded).hexdigest()


def _candidate_lookup(probe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row["candidate_id"]): row
        for row in probe.get("candidates") or []
        if isinstance(row, dict) and row.get("candidate_id")
    }


def _source_lookup(probe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    clustering = probe.get("clustering") or {}
    return {
        str(row["candidate_id"]): row
        for row in clustering.get("sources") or []
        if isinstance(row, dict) and row.get("candidate_id")
    }


def _games_lookup(probe: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in probe.get("games") or []:
        grouped[str(row["candidate_id"])].append(row)
    return grouped


def _checkpoint_cluster_sizes(
    probe: dict[str, Any]
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = defaultdict(dict)
    clusters = (probe.get("clustering") or {}).get("checkpoint_clusters") or {}
    for checkpoint, groups in clusters.items():
        for group in groups:
            members = [str(value) for value in group.get("members") or []]
            for member in members:
                result[member][str(checkpoint)] = len(members)
    return result


def _family_probe_statistics(
    representative: str,
    source_lookup: dict[str, dict[str, Any]],
) -> dict[str, float]:
    row = source_lookup[representative]
    return {
        "v111_probe_strict_win_rate": float(row["strict_win_rate_of_v111"]),
        "v111_probe_win_score": float(row["win_score_of_v111"]),
        "v111_probe_mean_margin": float(row["mean_margin_of_v111"]),
    }


def _is_close_probe_matchup(row: dict[str, Any]) -> bool:
    """Use draw-adjusted score so an all-draw family is not called a 0% sensitivity loss."""
    return 0.30 <= float(row["v111_probe_win_score"]) <= 0.70


def _candidate_priority(row: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        int(bool(row.get("exact_submitted_or_public_artifact"))),
        int(not bool(row.get("configuration_override"))),
        int(str(row.get("source_ancestry_id") or "").startswith("public_")),
        str(row.get("candidate_id") or ""),
    )


def _representative(
    members: list[str], candidates: dict[str, dict[str, Any]]
) -> str | None:
    usable = [
        candidates[member]
        for member in members
        if member in candidates
        and candidates[member].get("kind") != "builtin"
        and candidates[member].get("panel_restriction") != "calibration_only"
        and Path(str(candidates[member].get("entrypoint") or "")).is_absolute()
        and Path(str(candidates[member]["entrypoint"])).is_file()
    ]
    if not usable:
        return None
    return str(max(usable, key=_candidate_priority)["candidate_id"])


def _mean_quantity(games: list[dict[str, Any]], key: str) -> float:
    return mean(
        float(
            (row.get("diagnostics") or {})
            .get("opponent_action_profile", {})
            .get("market_item_quantity", {})
            .get(key, 0.0)
            or 0.0
        )
        for row in games
    )


def _mean_terminal_animals(
    games: list[dict[str, Any]], animal: str
) -> float:
    values = []
    for row in games:
        states = (row.get("diagnostics") or {}).get("checkpoint_states") or {}
        if not states:
            continue
        terminal = states[str(max(int(step) for step in states))]
        values.append(
            float(
                (terminal.get("opponent_portfolio") or {})
                .get("animals", {})
                .get(animal, 0.0)
                or 0.0
            )
        )
    return mean(values) if values else 0.0


def _style_tags(
    representative: str,
    games: list[dict[str, Any]],
    checkpoint_sizes: dict[str, dict[str, int]],
) -> list[str]:
    if not games:
        return ["unprofiled"]
    premium_sell = sum(
        _mean_quantity(games, f"SELL:{item}")
        for item in ("STRAWBERRY", "MELON", "MILK", "WOOL")
    )
    commodity_sell = sum(
        _mean_quantity(games, f"SELL:{item}")
        for item in ("WHEAT", "CARROT", "TOMATO", "EGG")
    )
    wheat_exposure = _mean_quantity(games, "BUY_SEED:WHEAT") + _mean_quantity(
        games, "BUY_PRODUCT:WHEAT"
    )
    sheep = _mean_terminal_animals(games, "SHEEP")
    cows = _mean_terminal_animals(games, "COW")
    fingerprints = {
        str(row.get("opponent_fingerprint", {}).get("719")) for row in games
    }
    sizes = checkpoint_sizes.get(representative) or {}
    tags = []
    if premium_sell > commodity_sell:
        tags.append("premium_heavy")
    if wheat_exposure > 0.0 or commodity_sell >= premium_sell:
        tags.append("wheat_or_commodity_heavy")
    if sheep > cows and sheep > 0.0:
        tags.append("wool_sheepward")
    elif cows > sheep and cows > 0.0:
        tags.append("milk_cowward")
    elif cows or sheep:
        tags.append("mixed_pasture")
    if int(sizes.get("24", 1)) > int(sizes.get("400", 1)):
        tags.append("shared_opening_continuation_split")
    if len(fingerprints) > 1:
        tags.append("state_or_seat_responsive_observed")
    else:
        tags.append("comparatively_open_loop_observed")
    return sorted(set(tags))


def _meta_vote_group(
    members: list[str], candidates: dict[str, dict[str, Any]], family_id: str
) -> str:
    capped = [
        candidates[member]
        for member in members
        if member in candidates and candidates[member].get("meta_vote_cap")
    ]
    if not capped:
        return family_id
    ancestries = sorted(
        {
            str(row.get("source_ancestry_id") or family_id)
            for row in capped
        }
    )
    return "shared_ancestry:" + "+".join(ancestries)


def derive_families(
    probe: dict[str, Any], *, max_families: int = 15
) -> list[dict[str, Any]]:
    if probe.get("dataset_role") and "Fresh Holdout" not in str(
        probe["dataset_role"]
    ):
        raise ValueError("common probe must explicitly record Fresh Holdout exclusion")
    clustering = probe.get("clustering") or {}
    candidates = _candidate_lookup(probe)
    sources = _source_lookup(probe)
    games = _games_lookup(probe)
    checkpoint_sizes = _checkpoint_cluster_sizes(probe)
    available = []
    for raw in clustering.get("exact_families") or []:
        members = sorted(str(value) for value in raw.get("source_members") or [])
        representative = _representative(members, candidates)
        if representative is None or representative not in sources:
            continue
        source = candidates[representative]
        entrypoint = Path(str(source["entrypoint"])).resolve()
        probe_stats = _family_probe_statistics(representative, sources)
        available.append(
            {
                "behavior_family_id": str(raw["behavior_family_id"]),
                "family_signature": str(raw["family_signature"]),
                "representative_candidate_id": representative,
                "entrypoint": str(entrypoint),
                "entrypoint_sha256": sha256_file(entrypoint),
                "dependency_closure_sha256": dependency_closure_sha256(entrypoint),
                "provenance": str(source.get("provenance") or ""),
                "source_members": members,
                "source_ancestry_ids": sorted(
                    {
                        str(candidates[member].get("source_ancestry_id") or member)
                        for member in members
                        if member in candidates
                        and candidates[member].get("panel_restriction")
                        != "calibration_only"
                    }
                ),
                "meta_vote_group": _meta_vote_group(
                    members, candidates, str(raw["behavior_family_id"])
                ),
                "style_tags": _style_tags(
                    representative, games.get(representative, []), checkpoint_sizes
                ),
                "contains_exact_public_or_submitted_artifact": any(
                    bool(candidates[member].get("exact_submitted_or_public_artifact"))
                    for member in members
                    if member in candidates
                ),
                "contains_forced_fixture": any(
                    bool(candidates[member].get("configuration_override"))
                    for member in members
                    if member in candidates
                ),
                "fresh_holdout_eligible": False,
                **probe_stats,
            }
        )
    if len(available) <= max_families:
        return sorted(available, key=lambda row: row["behavior_family_id"])

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def add(row: dict[str, Any]) -> None:
        family_id = str(row["behavior_family_id"])
        if family_id not in selected_ids and len(selected) < max_families:
            selected.append(row)
            selected_ids.add(family_id)

    ordered = sorted(
        available,
        key=lambda row: (
            abs(float(row["v111_probe_win_score"]) - 0.5),
            abs(float(row["v111_probe_mean_margin"])),
            str(row["behavior_family_id"]),
        ),
    )
    for row in ordered:
        if _is_close_probe_matchup(row):
            add(row)
    represented_styles: set[str] = set()
    for row in selected:
        represented_styles.update(row["style_tags"])
    for row in ordered:
        if any(tag not in represented_styles for tag in row["style_tags"]):
            add(row)
            represented_styles.update(row["style_tags"])
    represented_ancestry = {
        ancestry for row in selected for ancestry in row["source_ancestry_ids"]
    }
    for row in ordered:
        if any(value not in represented_ancestry for value in row["source_ancestry_ids"]):
            add(row)
            represented_ancestry.update(row["source_ancestry_ids"])
    for row in ordered:
        add(row)
    return sorted(selected, key=lambda row: row["behavior_family_id"])


def _select_meta_families(families: list[dict[str, Any]]) -> list[str]:
    eligible = [
        row
        for row in families
        if row["contains_exact_public_or_submitted_artifact"]
        and not row["contains_forced_fixture"]
    ]
    by_vote_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        by_vote_group[str(row["meta_vote_group"])].append(row)
    selected = []
    for vote_group in sorted(by_vote_group):
        representative = min(
            by_vote_group[vote_group],
            key=lambda row: (
                abs(float(row["v111_probe_win_score"]) - 0.5),
                str(row["behavior_family_id"]),
            ),
        )
        selected.append(str(representative["behavior_family_id"]))
    return sorted(selected)


def build_manifest(
    probe: dict[str, Any],
    *,
    source_path: Path,
    source_sha256: str,
    development_seeds: list[int],
    max_families: int = 15,
) -> dict[str, Any]:
    families = derive_families(probe, max_families=max_families)
    if not families:
        raise ValueError("common probe yielded no file-backed executable families")
    family_by_id = {row["behavior_family_id"]: row for row in families}
    sensitivity_targets = [
        family_id
        for family_id, row in family_by_id.items()
        if _is_close_probe_matchup(row)
    ]
    sensitivity_extensions = sorted(set(family_by_id) - set(sensitivity_targets))
    sensitivity = sorted(family_by_id)
    meta = _select_meta_families(families)
    old_pool = [
        family_id
        for family_id, row in family_by_id.items()
        if set(row["source_members"]) & FORMAL_REGRESSION_SOURCE_IDS
    ]
    easy = [
        family_id
        for family_id, row in family_by_id.items()
        if float(row["v111_probe_strict_win_rate"]) >= 0.75
    ]
    regression = sorted(set(old_pool) | set(easy))
    if not regression:
        regression = sorted(
            family_by_id,
            key=lambda family_id: -float(
                family_by_id[family_id]["v111_probe_strict_win_rate"]
            ),
        )[: min(3, len(family_by_id))]
    for row in families:
        row["panels"] = sorted(
            name
            for name, values in (
                ("sensitivity", sensitivity),
                ("meta", meta),
                ("regression", regression),
            )
            if row["behavior_family_id"] in values
        )
        row["meta_weight"] = 1.0 / len(meta) if row["behavior_family_id"] in meta else None
    v111 = (ROOT / "agents/v111/main.py").resolve()
    v113 = (ROOT / "agents/v113/main.py").resolve()
    uniform_sensitivity = {family_id: 1.0 for family_id in sensitivity}
    uniform_meta = {family_id: 1.0 for family_id in meta}
    uniform_regression = {family_id: 1.0 for family_id in regression}
    return {
        "format": FORMAT,
        "created_at": datetime.now().astimezone().isoformat(),
        "dataset_role": (
            "Discovery/Development expanded executable panel; permanently excluded "
            "from Fresh Holdout"
        ),
        "source_common_probe": str(source_path),
        "source_common_probe_sha256": source_sha256,
        "controls": {
            "clean_v111": {
                "entrypoint": str(v111),
                "entrypoint_sha256": sha256_file(v111),
                "dependency_closure_sha256": dependency_closure_sha256(v111),
                "role": "clean causal control",
            },
            "live_benchmark_v113": {
                "entrypoint": str(v113),
                "entrypoint_sha256": sha256_file(v113),
                "dependency_closure_sha256": dependency_closure_sha256(v113),
                "role": "live-validated field benchmark; not gate-causal proof",
            },
        },
        "selection": {
            "target_family_count": "8-15 when the executable inventory permits",
            "selected_family_count": len(families),
            "selection_priority": (
                "30-70% draw-adjusted probe matchups, then style/ancestry diversity, "
                "then closeness"
            ),
            "exact_action_family_collapse": True,
            "shared_forced_router_meta_vote_cap": True,
            "sensitivity_target_family_ids": sorted(sensitivity_targets),
            "sensitivity_coverage_extension_family_ids": sensitivity_extensions,
            "sensitivity_adequacy": {
                "status": (
                    "ADEQUATE" if len(sensitivity_targets) >= 3 else "INSUFFICIENT"
                ),
                "target_family_count": len(sensitivity_targets),
                "reason": (
                    "Fewer than three independent 30-70% draw-adjusted probe "
                    "families; coverage extensions are Regression/diversity, not "
                    "uplift-sensitive evidence."
                    if len(sensitivity_targets) < 3
                    else "At least three target-band executable families."
                ),
            },
        },
        "preregistered_dual_benchmark": {
            "purpose": (
                "Compare clean causal control V111 with the live-viable V113 benchmark; "
                "this is not a rerun or rewrite of the immutable 60-pair experiment."
            ),
            "planned_unique_pairs": len(families) * len(development_seeds) * 2,
            "report_separately": [
                "total_pairs",
                "trigger_pairs",
                "actual_treatment_pairs",
                "discordant_outcome_pairs",
            ],
            "base_selection_rule": {
                "retain_v113_as_v114_base_candidate": (
                    "V113 is non-inferior to V111 on both Meta-weighted and Macro-family "
                    "win score (95% lower bound >= -0.025), has no new Hard Safety Failure, "
                    "and produces a positive net discordant outcome in at least one major "
                    "family without a larger major-family regression."
                ),
                "return_to_v111_base": (
                    "V113 is clearly inferior when either Meta-weighted or Macro-family "
                    "delta win-score 95% upper bound is below -0.025, or major-family "
                    "Win-to-Loss regressions exceed Loss-to-Win improvements."
                ),
                "dual_champion_candidates": (
                    "Use when neither direction is established, including when the "
                    "Sensitivity Panel has fewer than three independent target-band families."
                ),
            },
            "v114_authorization": (
                "No strategy implementation is authorized by this manifest alone. A measured "
                "loss family/regime and a targeted causal efficacy design are required first."
            ),
        },
        "families": families,
        "panels": {
            "sensitivity": {
                "description": (
                    "All selected independent families for weakness mapping; draw-adjusted "
                    "30-70% target-band families are marked separately and receive "
                    "interpretation priority."
                ),
                "family_ids": sensitivity,
                "target_family_ids_30_to_70": sorted(sensitivity_targets),
                "coverage_extension_family_ids": sensitivity_extensions,
                "seeds": development_seeds,
                "both_seats": True,
                "weights": uniform_sensitivity,
            },
            "meta": {
                "description": (
                    "Provisional executable current-field proxy. Equal family weights are "
                    "not claimed to be live field frequencies."
                ),
                "family_ids": meta,
                "seeds": development_seeds,
                "both_seats": True,
                "weights": uniform_meta,
                "weight_source": "provisional_equal_independent_family_weight",
                "shared_ancestry_vote_rule": (
                    "at most one family from a meta_vote_cap group"
                ),
            },
            "regression": {
                "description": (
                    "Known formal-panel sources and easy probe matchups; detects loss of "
                    "existing strengths, not positive uplift."
                ),
                "family_ids": regression,
                "seeds": development_seeds,
                "both_seats": True,
                "weights": uniform_regression,
            },
            "fresh_holdout": {
                "description": (
                    "Reserved for later unprobed executable families and/or newly acquired "
                    "episodes after rules are frozen."
                ),
                "family_ids": [],
                "seeds": [],
                "both_seats": True,
                "reserved": True,
            },
        },
        "fresh_holdout_exclusions": {
            "all_common_probe_family_ids": sorted(family_by_id),
            "common_probe_seeds": list((probe.get("configuration") or {}).get("seeds") or []),
            "expanded_development_seeds": development_seeds,
        },
    }


def _markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Independent Gold executable-family manifest",
        "",
        "This manifest is derived from actual common-seed, both-seat action streams. "
        "Source or submission names do not create extra statistical votes.",
        "",
        f"- Selected families: **{len(manifest['families'])}**",
        "- Sensitivity target (V111 draw-adjusted win score 30–70%): "
        f"`{manifest['selection']['sensitivity_target_family_ids']}`",
        "- Sensitivity adequacy: "
        f"**{manifest['selection']['sensitivity_adequacy']['status']}** — "
        f"{manifest['selection']['sensitivity_adequacy']['reason']}",
        "- Fresh Holdout: reserved and empty; all probed families/seeds excluded",
        "",
        "| Family | Representative | Strict WR | Win score | Margin | Styles | Panels | Meta vote group |",
        "|---|---|---:|---:|---:|---|---|---|",
    ]
    for row in manifest["families"]:
        lines.append(
            "| {family} | {representative} | {wr:.1%} | {score:.1%} | {margin:+.1f} | "
            "{styles} | {panels} | {vote} |".format(
                family=row["behavior_family_id"],
                representative=row["representative_candidate_id"],
                wr=row["v111_probe_strict_win_rate"],
                score=row["v111_probe_win_score"],
                margin=row["v111_probe_mean_margin"],
                styles=", ".join(row["style_tags"]),
                panels=", ".join(row["panels"]),
                vote=row["meta_vote_group"],
            )
        )
    lines.extend(
        [
            "",
            "## Panel semantics",
            "",
            "- Sensitivity emphasizes 30–70% target families; out-of-band families are "
            "explicit coverage extensions, not extra proof of uplift.",
            "- Meta weights are provisional until live-family frequency mapping exists.",
            "- Regression protects known favorable matchups.",
            "- Forced branches sharing public V43 ancestry receive at most one Meta vote.",
            "- Fresh Holdout cannot contain anything used by the common probe or this run.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--common-probe",
        type=Path,
        default=Path("data/evaluation/independent_gold_pool/common_probe.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/independent_gold_pool/family_panel_manifest.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("docs/independent_gold_family_manifest.md"),
    )
    parser.add_argument("--seed", action="append", type=int, default=[])
    parser.add_argument("--max-families", type=int, default=15)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not 1 <= int(args.max_families) <= 15:
        raise ValueError("--max-families must be between 1 and 15")
    common_probe = _resolve(args.common_probe)
    probe, probe_sha = _load_json(common_probe)
    seeds = sorted(set(args.seed or DEFAULT_DEVELOPMENT_SEEDS))
    if len(seeds) < 2:
        raise ValueError("expanded panels require multiple distinct seeds")
    manifest = build_manifest(
        probe,
        source_path=common_probe,
        source_sha256=probe_sha,
        development_seeds=seeds,
        max_families=int(args.max_families),
    )
    output = _resolve(args.output)
    report = _resolve(args.report)
    if (output.exists() or report.exists()) and not args.force:
        raise FileExistsError("derived output exists; pass --force only for Development rebuild")
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report.write_text(_markdown(manifest), encoding="utf-8")
    print(
        json.dumps(
            {
                "families": len(manifest["families"]),
                "sensitivity_target_families": len(
                    manifest["selection"]["sensitivity_target_family_ids"]
                ),
                "meta_families": len(manifest["panels"]["meta"]["family_ids"]),
                "regression_families": len(
                    manifest["panels"]["regression"]["family_ids"]
                ),
                "output": str(output),
                "report": str(report),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
