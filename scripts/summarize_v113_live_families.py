"""Summarize V113 live-opponent behavioral families without replaying games.

This is a derived E6/Bronze analysis.  A single recorded action trajectory is
not an executable policy family.  The script therefore keeps full-trajectory
hashes separate from quantity-agnostic prefix clusters and only calls a local
Gold correspondence strong when an exact recorded-action prefix matches an
executable common-probe trajectory through step 200 or later.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVALUATION_DIR = ROOT / "data/evaluation/v113_live_e6_55933145"
DEFAULT_COMMON_PROBE = ROOT / "data/evaluation/independent_gold_pool/common_probe.json"
DEFAULT_ADDITIONAL_PROBES = (
    ROOT / "data/evaluation/independent_gold_pool/public_candidate_addendum_probe.json",
    ROOT / "data/evaluation/independent_gold_pool/public_pure_route_probe.json",
    ROOT / "data/evaluation/independent_gold_pool/public_history_candidate_probe.json",
    ROOT
    / "data/evaluation/independent_gold_pool/"
    "public_external_github_candidate_probe.json",
)
DEFAULT_REPORT = (
    ROOT / "docs/v113_live_opponent_family_analysis_expanded_public_20260902.md"
)
DEFAULT_OUTPUT_NAME = "live_family_summary_expanded_public_20260902.json"

MODES = ("quantity_agnostic_field_route", "quantity_agnostic_field_and_market")
HORIZONS = (24, 100, 200, 400, 719)
CLOSE_MARGIN_THRESHOLD = 3_000.0
HIGH_ABSOLUTE_RATING_THRESHOLD = 1_600.0
RATING_UPSET_GAP_THRESHOLD = 100.0
STRONG_GOLD_PREFIX_HORIZON = 200


def _resolve(path: str | Path) -> Path:
    value = Path(path)
    return (value if value.is_absolute() else ROOT / value).resolve()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _outcome_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = Counter(str(row.get("result")) for row in rows)
    margins = [float(row["margin"]) for row in rows]
    return {
        "episodes": len(rows),
        "wins": results["win"],
        "draws": results["draw"],
        "losses": results["loss"],
        "win_rate": results["win"] / len(rows),
        "win_score": (results["win"] + 0.5 * results["draw"]) / len(rows),
        "mean_margin": mean(margins),
        "median_margin": median(margins),
    }


def _episode_interest(row: dict[str, Any]) -> dict[str, bool]:
    margin = float(row["margin"])
    opponent_rating = float(row["opponent_initial_rating"])
    rating_gap = float(row["rating_gap_opponent_minus_self"])
    won = row.get("result") == "win"
    return {
        "loss": row.get("result") == "loss",
        "close_margin_abs_le_3000": abs(margin) <= CLOSE_MARGIN_THRESHOLD,
        "high_absolute_rating_win_ge_1600": won and opponent_rating >= HIGH_ABSOLUTE_RATING_THRESHOLD,
        "rating_upset_win_opponent_plus_100": won and rating_gap >= RATING_UPSET_GAP_THRESHOLD,
    }


def _episode_row(row: dict[str, Any], cluster_ids: dict[tuple[str, int, int], str]) -> dict[str, Any]:
    episode_id = int(row["episode_id"])
    interest = _episode_interest(row)
    gate = row.get("generalized_cow_sheep_gate") or {}
    return {
        "episode_id": episode_id,
        "opponent_submission_id": row.get("opponent_submission_id"),
        "opponent_team_id": row.get("opponent_team_id"),
        "opponent_team_name": row.get("opponent_team_name"),
        "seat": row.get("seat"),
        "result": row.get("result"),
        "margin": row.get("margin"),
        "self_initial_rating": row.get("self_initial_rating"),
        "opponent_initial_rating": row.get("opponent_initial_rating"),
        "rating_gap_opponent_minus_self": row.get("rating_gap_opponent_minus_self"),
        "town_regime_signature": (row.get("town_regime") or {}).get("signature"),
        "gate_cohort": gate.get("cohort"),
        "interest": interest,
        "behavioral_prefix_clusters": {
            mode: {str(horizon): cluster_ids[(mode, horizon, episode_id)] for horizon in HORIZONS} for mode in MODES
        },
        "full_recorded_trajectory_hash": (row.get("opponent_action_fingerprints") or {}).get("719"),
    }


def _build_cluster_views(
    episodes: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[tuple[str, int, int], str]]:
    views: dict[str, Any] = {}
    episode_cluster_ids: dict[tuple[str, int, int], str] = {}
    for mode in MODES:
        mode_views: dict[str, Any] = {}
        for horizon in HORIZONS:
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in episodes:
                fingerprint = ((row.get("opponent_seed_robust_fingerprints") or {}).get(mode) or {}).get(str(horizon))
                if not fingerprint:
                    raise ValueError(f"missing {mode} horizon {horizon} for episode {row.get('episode_id')}")
                grouped[str(fingerprint)].append(row)

            ordered = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
            clusters = []
            for index, (fingerprint, rows) in enumerate(ordered, start=1):
                cluster_id = f"live_{mode.removeprefix('quantity_agnostic_')}_h{horizon}_c{index:02d}"
                rows = sorted(rows, key=lambda item: int(item["episode_id"]))
                for row in rows:
                    episode_cluster_ids[(mode, horizon, int(row["episode_id"]))] = cluster_id
                interests = {key: [] for key in _episode_interest(rows[0])}
                for row in rows:
                    for key, selected in _episode_interest(row).items():
                        if selected:
                            interests[key].append(int(row["episode_id"]))
                clusters.append(
                    {
                        "cluster_id": cluster_id,
                        "fingerprint": fingerprint,
                        "episode_ids": [int(row["episode_id"]) for row in rows],
                        "opponent_submission_ids": sorted(
                            {
                                int(row["opponent_submission_id"])
                                for row in rows
                                if row.get("opponent_submission_id") is not None
                            }
                        ),
                        "opponent_team_names": sorted({str(row["opponent_team_name"]) for row in rows}),
                        "performance": _outcome_summary(rows),
                        "interest_episode_ids": interests,
                        "gate_cohorts": dict(
                            sorted(
                                Counter(
                                    str((row.get("generalized_cow_sheep_gate") or {}).get("cohort")) for row in rows
                                ).items()
                            )
                        ),
                        "town_regimes": dict(
                            sorted(
                                Counter(str((row.get("town_regime") or {}).get("signature")) for row in rows).items()
                            )
                        ),
                    }
                )
            mode_views[str(horizon)] = {
                "semantic_role": (
                    "opening_behavioral_prefix"
                    if horizon <= 100
                    else "early_continuation_behavioral_prefix"
                    if horizon == 200
                    else "later_recorded_behavioral_prefix"
                ),
                "unique_clusters": len(clusters),
                "multi_episode_clusters": sum(len(cluster["episode_ids"]) > 1 for cluster in clusters),
                "clusters": clusters,
            }
        views[mode] = mode_views
    return views, episode_cluster_ids


def _gold_correspondence(
    lineages: dict[str, Any],
    probe: dict[str, Any],
    episodes_by_id: dict[int, dict[str, Any]],
    cluster_ids: dict[tuple[str, int, int], str],
) -> dict[str, Any]:
    correspondence = lineages.get("common_probe_correspondence") or {}
    matches = correspondence.get("matches") or []
    probe_families = {
        str(row["behavior_family_id"]): row for row in (probe.get("clustering") or {}).get("exact_families") or []
    }

    by_episode: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in matches:
        episode_id = int(row["live_episode_id"])
        family_id = str(row["gold_behavior_family_id"])
        if family_id not in probe_families:
            raise ValueError(f"correspondence references absent common-probe family: {family_id}")
        by_episode[episode_id].append(row)

    strong = []
    shared_opening = []
    weak_h24_only = []
    for episode_id, rows in sorted(by_episode.items()):
        maximum_horizon = max(max(int(value) for value in row["exact_matching_checkpoints"]) for row in rows)
        selected = [
            row for row in rows if max(int(value) for value in row["exact_matching_checkpoints"]) == maximum_horizon
        ]
        family_ids = sorted({str(row["gold_behavior_family_id"]) for row in selected})
        candidates = sorted({str(row["candidate_id"]) for row in selected})
        episode = episodes_by_id[episode_id]
        summary = {
            "episode_id": episode_id,
            "opponent_submission_id": episode.get("opponent_submission_id"),
            "opponent_team_name": episode.get("opponent_team_name"),
            "result": episode.get("result"),
            "margin": episode.get("margin"),
            "maximum_exact_prefix_horizon": maximum_horizon,
            "gold_behavior_family_ids": family_ids,
            "gold_family_representatives": sorted(
                {str(probe_families[family_id]["representative_candidate_id"]) for family_id in family_ids}
            ),
            "matching_candidate_ids": candidates,
            "h200_field_route_cluster": cluster_ids[("quantity_agnostic_field_route", 200, episode_id)],
            "interpretation": (
                "strong recorded-prefix correspondence; live trajectory remains Bronze and does not inherit Gold status"
                if maximum_horizon >= STRONG_GOLD_PREFIX_HORIZON
                else "shared opening only; insufficient to assign the live opponent to a local Gold policy family"
            ),
        }
        if maximum_horizon >= STRONG_GOLD_PREFIX_HORIZON:
            strong.append(summary)
        elif maximum_horizon >= 100:
            shared_opening.append(summary)
        else:
            weak_h24_only.append(summary)

    strong_episode_ids = {row["episode_id"] for row in strong}
    matched_episode_ids = set(by_episode)
    all_episode_ids = set(episodes_by_id)
    strong_family_ids = sorted({family_id for row in strong for family_id in row["gold_behavior_family_ids"]})
    h200_route_all = {cluster_ids[("quantity_agnostic_field_route", 200, episode_id)] for episode_id in all_episode_ids}
    h200_route_strong = {
        cluster_ids[("quantity_agnostic_field_route", 200, episode_id)] for episode_id in strong_episode_ids
    }
    return {
        "rule": {
            "strong": (
                "exact recorded-action prefix match to an executable common-probe trajectory through h200 or later"
            ),
            "shared_opening": "exact prefix match ends at h100; not a policy-family assignment",
            "evidence_boundary": "the executable source remains Gold; every live replay trajectory remains Bronze",
        },
        "common_probe_exact_family_count": len(probe_families),
        "episodes_with_any_exact_prefix_match": len(matched_episode_ids),
        "strong_correspondence_episodes": strong,
        "strong_correspondence_episode_count": len(strong),
        "strong_correspondence_gold_family_ids": strong_family_ids,
        "shared_opening_episodes": shared_opening,
        "shared_opening_episode_count": len(shared_opening),
        "h24_only_episodes": weak_h24_only,
        "h24_only_episode_count": len(weak_h24_only),
        "no_common_probe_match_episode_ids": sorted(all_episode_ids - matched_episode_ids),
        "no_common_probe_match_episode_count": len(all_episode_ids - matched_episode_ids),
        "no_strong_gold_correspondence_episode_ids": sorted(all_episode_ids - strong_episode_ids),
        "no_strong_gold_correspondence_episode_count": len(all_episode_ids - strong_episode_ids),
        "h200_field_route_cluster_count": len(h200_route_all),
        "h200_field_route_clusters_with_strong_gold_correspondence": sorted(h200_route_strong),
        "h200_field_route_clusters_without_strong_gold_correspondence": sorted(h200_route_all - h200_route_strong),
        "h200_field_route_clusters_without_strong_gold_correspondence_count": len(h200_route_all - h200_route_strong),
        "interpretation": (
            "Unmatched clusters are live-only Bronze behavioral-cluster candidates, "
            "not proven new executable policy families."
        ),
    }


def _merge_probe_correspondence(
    lineages: dict[str, Any],
    primary_probe: dict[str, Any],
    additional_probes: list[tuple[str, dict[str, Any]]],
    episodes_by_id: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge hash-only correspondence from separately frozen common probes.

    The original live analyzer already stored matches for ``primary_probe``.
    Additional probes were acquired later, so their cumulative action hashes
    are compared to the saved live hashes without replaying either policy.
    New family identifiers are namespaced by probe file stem.  When two probes
    contain the same complete common-seed/both-seat family signature, they are
    collapsed to one canonical family instead of being counted twice.
    """

    merged_lineages = dict(lineages)
    original = (lineages.get("common_probe_correspondence") or {}).get("matches") or []
    merged_matches = [dict(row) for row in original]
    merged_families = [
        dict(row)
        for row in (primary_probe.get("clustering") or {}).get("exact_families") or []
    ]
    family_by_signature = {
        str(row["family_signature"]): row
        for row in merged_families
        if row.get("family_signature")
    }

    for probe_label, probe in additional_probes:
        clustering = probe.get("clustering") or {}
        families = clustering.get("exact_families") or []
        source_to_family: dict[str, str] = {}
        for family in families:
            signature = str(family.get("family_signature") or "")
            existing = family_by_signature.get(signature) if signature else None
            if existing is not None:
                canonical_id = str(existing["behavior_family_id"])
                existing["source_members"] = sorted(
                    {
                        *(str(value) for value in existing.get("source_members") or []),
                        *(str(value) for value in family.get("source_members") or []),
                    }
                )
                existing["source_ancestry_ids"] = sorted(
                    {
                        *(
                            str(value)
                            for value in existing.get("source_ancestry_ids") or []
                        ),
                        *(
                            str(value)
                            for value in family.get("source_ancestry_ids") or []
                        ),
                    }
                )
            else:
                canonical_id = f"{probe_label}:{family['behavior_family_id']}"
                qualified = dict(family)
                qualified["behavior_family_id"] = canonical_id
                merged_families.append(qualified)
                if signature:
                    family_by_signature[signature] = qualified
            for candidate_id in family.get("source_members") or []:
                source_to_family[str(candidate_id)] = canonical_id

        for source in clustering.get("sources") or []:
            if source.get("probe_status") != "COMPLETE":
                continue
            candidate_id = str(source["candidate_id"])
            family_id = source_to_family.get(candidate_id)
            if family_id is None:
                raise ValueError(
                    f"additional probe source has no exact family: {probe_label}:{candidate_id}"
                )
            vectors = [
                row.get("opponent") or {}
                for row in source.get("probe_vector") or []
                if isinstance(row, dict)
            ]
            for episode_id, episode in episodes_by_id.items():
                live_hashes = episode.get("opponent_action_fingerprints") or {}
                checkpoints = sorted(
                    horizon
                    for horizon in HORIZONS
                    if any(
                        str(live_hashes.get(str(horizon)))
                        == str(vector.get(str(horizon)))
                        for vector in vectors
                    )
                )
                if checkpoints:
                    merged_matches.append(
                        {
                            "live_episode_id": episode_id,
                            "gold_behavior_family_id": family_id,
                            "candidate_id": candidate_id,
                            "exact_matching_checkpoints": checkpoints,
                            "probe_label": probe_label,
                        }
                    )

    merged_lineages["common_probe_correspondence"] = {
        **(lineages.get("common_probe_correspondence") or {}),
        "matches": merged_matches,
        "additional_probe_count": len(additional_probes),
    }
    merged_probe = {
        "clustering": {
            "exact_families": merged_families,
        }
    }
    return merged_lineages, merged_probe


def _priority_sets(
    episodes: list[dict[str, Any]],
    cluster_ids: dict[tuple[str, int, int], str],
    gold: dict[str, Any],
) -> dict[str, Any]:
    strong_by_episode = {int(row["episode_id"]): row for row in gold["strong_correspondence_episodes"]}
    shared_by_episode = {int(row["episode_id"]): row for row in gold["shared_opening_episodes"]}

    def details(row: dict[str, Any]) -> dict[str, Any]:
        episode_id = int(row["episode_id"])
        if episode_id in strong_by_episode:
            local_status = "strong_h200_plus_gold_correspondence"
            local_families = strong_by_episode[episode_id]["gold_behavior_family_ids"]
        elif episode_id in shared_by_episode:
            local_status = "shared_opening_h100_only"
            local_families = shared_by_episode[episode_id]["gold_behavior_family_ids"]
        else:
            local_status = "no_strong_local_gold_correspondence"
            local_families = []
        return {
            **_episode_row(row, cluster_ids),
            "local_gold_correspondence_status": local_status,
            "local_gold_behavior_family_ids": local_families,
        }

    categories = {
        "losses": lambda row: row.get("result") == "loss",
        "close_margin_abs_le_3000": lambda row: abs(float(row["margin"])) <= CLOSE_MARGIN_THRESHOLD,
        "high_absolute_rating_wins_ge_1600": lambda row: (
            row.get("result") == "win" and float(row["opponent_initial_rating"]) >= HIGH_ABSOLUTE_RATING_THRESHOLD
        ),
        "rating_upset_wins_opponent_plus_100": lambda row: (
            row.get("result") == "win" and float(row["rating_gap_opponent_minus_self"]) >= RATING_UPSET_GAP_THRESHOLD
        ),
    }
    result: dict[str, Any] = {}
    for name, predicate in categories.items():
        selected = [row for row in episodes if predicate(row)]
        selected.sort(key=lambda row: (float(row["margin"]), int(row["episode_id"])))
        result[name] = {
            "episodes": len(selected),
            "h200_field_route_clusters": sorted(
                {cluster_ids[("quantity_agnostic_field_route", 200, int(row["episode_id"]))] for row in selected}
            ),
            "episode_details": [details(row) for row in selected],
        }
    return result


def _markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(str(value) for value in row) + " |" for row in rows),
    ]


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def _episode_ids(rows: list[dict[str, Any]]) -> str:
    return ", ".join(str(row["episode_id"]) for row in rows)


def _render_report(payload: dict[str, Any]) -> str:
    inventory = payload["behavioral_prefix_inventory"]
    gold = payload["local_gold_correspondence"]
    priority = payload["priority_sets"]
    route_h200 = payload["cluster_views"]["quantity_agnostic_field_route"]["200"]["clusters"]
    important_clusters = [
        row for row in route_h200 if any(row["interest_episode_ids"].values()) or len(row["episode_ids"]) > 1
    ]

    lines = [
        "# V113 Live opponent behavioral-family analysis",
        "",
        "## Conclusion",
        "",
        (
            f"The 58 public live episodes contain {inventory['field_route']['200']} quantity-agnostic h200 field-route "
            "clusters, but these are Bronze recorded-behavior clusters, not "
            f"{inventory['full_recorded_trajectory_hashes']} independent executable policies. Exact h719 trajectory "
            "hashes "
            "are deliberately not counted as policy families."
        ),
        "",
        (
            f"Only {gold['strong_correspondence_episode_count']} episodes strongly correspond to a local Gold family "
            "at h200+, "
            f"and point to {', '.join(gold['strong_correspondence_gold_family_ids'])}. "
            f"Another {gold['shared_opening_episode_count']} episodes match only through h100 and remain ambiguous "
            "shared openings."
        ),
        "",
        (
            f"The field therefore contains {gold['no_strong_gold_correspondence_episode_count']} live trajectories and "
            f"{gold['h200_field_route_clusters_without_strong_gold_correspondence_count']} h200 route clusters without "
            "strong "
            "local-Gold correspondence. They are acquisition leads, not Gold promotions."
        ),
        "",
        "## Evidence and identity boundary",
        "",
        "- Source evidence is E6 observational; live trajectories are Bronze.",
        "- h24/h100 clusters describe openings; h200 describes early continuation. Numeric quantities are removed.",
        "- A common opening does not imply common code. h100-only matches are not assigned to a Gold family.",
        (
            "- Strong correspondence requires an exact, quantity-preserving recorded-action prefix match "
            "through h200 or later."
        ),
        "- Even a strong prefix correspondence does not make the live opponent executable or Gold.",
        "",
        "## Prefix-cluster inventory",
        "",
    ]
    lines.extend(
        _markdown_table(
            ["View", "h24", "h100", "h200", "h400", "h719"],
            [
                ["quantity-agnostic field route", *(inventory["field_route"][str(h)] for h in HORIZONS)],
                ["quantity-agnostic field + market", *(inventory["field_and_market"][str(h)] for h in HORIZONS)],
                ["exact recorded action prefix", *(inventory["exact_recorded_prefix"][str(h)] for h in HORIZONS)],
            ],
        )
    )
    lines.extend(
        [
            "",
            (
                "The final row is trajectory identity, not policy identity. In particular, 58 unique h719 hashes "
                "do not establish 58 families."
            ),
            "",
            "## Strong local Gold correspondence",
            "",
        ]
    )
    strong_rows = []
    for row in gold["strong_correspondence_episodes"]:
        strong_rows.append(
            [
                row["episode_id"],
                row["opponent_submission_id"],
                row["result"],
                f"{row['margin']:+.0f}",
                row["maximum_exact_prefix_horizon"],
                ", ".join(row["gold_family_representatives"]),
                row["h200_field_route_cluster"],
            ]
        )
    lines.extend(
        _markdown_table(
            ["Episode", "Submission", "Result", "Margin", "Exact through", "Gold representative", "h200 route cluster"],
            strong_rows,
        )
    )
    lines.extend(
        [
            "",
            (
                "These are prefix correspondences to the listed executable artifacts. No live episode exactly "
                "matches a common-probe trajectory through h719."
            ),
            "",
            "## h100 shared openings",
            "",
            (
                f"{gold['shared_opening_episode_count']} episodes match a local executable trajectory through h100 "
                "but not h200. These include V43/mainline-style shared openings; their later continuations differ, "
                "so they are not local-family matches."
            ),
            "",
            f"Episodes: {_episode_ids(gold['shared_opening_episodes']) or 'none'}.",
            "",
            "## h200 field-route clusters of interest",
            "",
        ]
    )
    cluster_rows = []
    for row in important_clusters:
        perf = row["performance"]
        interest = row["interest_episode_ids"]
        cluster_rows.append(
            [
                row["cluster_id"],
                perf["episodes"],
                f"{perf['wins']}-{perf['draws']}-{perf['losses']}",
                _pct(perf["win_rate"]),
                f"{perf['mean_margin']:+.0f}",
                ",".join(map(str, interest["loss"])) or "-",
                ",".join(map(str, interest["close_margin_abs_le_3000"])) or "-",
                ",".join(map(str, interest["high_absolute_rating_win_ge_1600"])) or "-",
            ]
        )
    lines.extend(
        _markdown_table(
            ["Cluster", "N", "W-D-L", "WR", "Mean margin", "Loss episodes", "Close episodes", "1600+ wins"],
            cluster_rows,
        )
    )
    lines.extend(
        [
            "",
            "## Priority episode sets",
            "",
            (
                f"Losses: {priority['losses']['episodes']} episodes across "
                f"{len(priority['losses']['h200_field_route_clusters'])} h200 route clusters."
            ),
            "",
        ]
    )
    loss_rows = []
    for row in priority["losses"]["episode_details"]:
        loss_rows.append(
            [
                row["episode_id"],
                row["opponent_submission_id"],
                row["opponent_team_name"],
                f"{row['opponent_initial_rating']:.1f}",
                f"{row['rating_gap_opponent_minus_self']:+.1f}",
                f"{row['margin']:+.0f}",
                row["behavioral_prefix_clusters"]["quantity_agnostic_field_route"]["200"],
                row["local_gold_correspondence_status"],
            ]
        )
    lines.extend(
        _markdown_table(
            ["Episode", "Submission", "Opponent", "Opp rating", "Gap", "Margin", "h200 route", "Local correspondence"],
            loss_rows,
        )
    )
    close = priority["close_margin_abs_le_3000"]
    high = priority["high_absolute_rating_wins_ge_1600"]
    upsets = priority["rating_upset_wins_opponent_plus_100"]
    lines.extend(
        [
            "",
            (
                f"Close-margin diagnostic (`|margin| <= 3000`): {close['episodes']} episodes across "
                f"{len(close['h200_field_route_clusters'])} h200 route clusters. Episode IDs: "
                f"{_episode_ids(close['episode_details'])}."
            ),
            "",
            (
                f"Wins against absolute opponent rating >=1600: {high['episodes']} across "
                f"{len(high['h200_field_route_clusters'])} h200 route clusters. Episode IDs: "
                f"{_episode_ids(high['episode_details'])}."
            ),
            "",
            (
                f"Rating-upset wins (opponent at least +100): {upsets['episodes']} episodes: "
                f"{_episode_ids(upsets['episode_details'])}."
            ),
            "",
            "## Gold-acquisition interpretation",
            "",
            (
                "The h200+ correspondences confirm that known executable action families were represented in the "
                "live field. The remaining losses, close games, and high-rating wins identify opponent submissions "
                "and Bronze h200 clusters to prioritize for public-code discovery. Fingerprint similarity alone "
                "cannot promote them to Gold; executable code and common-seed, both-seat probing are still required."
            ),
            "",
            (
                "A/B/C gate-cohort and outcome fields are retained per episode and cluster in the JSON. They are "
                "descriptive and do not estimate the Cow→Sheep gate's causal effect."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def build_summary(
    episode_metrics_path: Path,
    lineages_path: Path,
    analysis_path: Path,
    common_probe_path: Path,
    additional_probe_paths: list[Path] | None = None,
) -> dict[str, Any]:
    episode_metrics = _load_object(episode_metrics_path)
    lineages = _load_object(lineages_path)
    analysis = _load_object(analysis_path)
    probe = _load_object(common_probe_path)
    additional_probe_paths = additional_probe_paths or []
    additional_probes = [
        (path.stem, _load_object(path)) for path in additional_probe_paths
    ]
    episodes = [row for row in episode_metrics.get("episodes") or [] if isinstance(row, dict)]
    episodes.sort(key=lambda row: int(row["episode_id"]))
    if len(episodes) != 58:
        raise ValueError(f"expected 58 public live episodes, got {len(episodes)}")
    episodes_by_id = {int(row["episode_id"]): row for row in episodes}

    cluster_views, cluster_ids = _build_cluster_views(episodes)
    merged_lineages, merged_probe = _merge_probe_correspondence(
        lineages,
        probe,
        additional_probes,
        episodes_by_id,
    )
    gold = _gold_correspondence(
        merged_lineages, merged_probe, episodes_by_id, cluster_ids
    )
    priority = _priority_sets(episodes, cluster_ids, gold)
    exact_inventory = {
        str(horizon): len({str((row.get("opponent_action_fingerprints") or {}).get(str(horizon))) for row in episodes})
        for horizon in HORIZONS
    }
    inventory = {
        "field_route": {
            str(horizon): cluster_views["quantity_agnostic_field_route"][str(horizon)]["unique_clusters"]
            for horizon in HORIZONS
        },
        "field_and_market": {
            str(horizon): cluster_views["quantity_agnostic_field_and_market"][str(horizon)]["unique_clusters"]
            for horizon in HORIZONS
        },
        "exact_recorded_prefix": exact_inventory,
        "full_recorded_trajectory_hashes": exact_inventory["719"],
    }
    episode_summaries = [_episode_row(row, cluster_ids) for row in episodes]
    return {
        "format": "kaggriculture-v113-live-opponent-family-summary-v1",
        "submission_id": analysis.get("submission_id"),
        "evidence": {
            "level": "E6_OBSERVATIONAL",
            "live_replays": "Bronze",
            "common_probe_sources": "Gold executable",
            "causal_claim": "none",
            "identity_guardrail": (
                "A recorded trajectory hash or quantity-agnostic prefix cluster is not an independent executable "
                "policy family."
            ),
        },
        "inputs": {
            "episode_metrics": {"path": _relative(episode_metrics_path), "sha256": _sha256(episode_metrics_path)},
            "opponent_action_lineages": {"path": _relative(lineages_path), "sha256": _sha256(lineages_path)},
            "analysis": {"path": _relative(analysis_path), "sha256": _sha256(analysis_path)},
            "common_probe": {"path": _relative(common_probe_path), "sha256": _sha256(common_probe_path)},
            "additional_common_probes": [
                {"path": _relative(path), "sha256": _sha256(path)}
                for path in additional_probe_paths
            ],
        },
        "thresholds": {
            "strong_gold_exact_prefix_horizon_minimum": STRONG_GOLD_PREFIX_HORIZON,
            "close_margin_absolute_maximum": CLOSE_MARGIN_THRESHOLD,
            "high_absolute_opponent_rating_minimum": HIGH_ABSOLUTE_RATING_THRESHOLD,
            "rating_upset_gap_opponent_minus_self_minimum": RATING_UPSET_GAP_THRESHOLD,
        },
        "coverage": {
            "public_live_episodes": len(episodes),
            "opponent_submissions": len({row.get("opponent_submission_id") for row in episodes}),
            "opponent_teams": len({row.get("opponent_team_id") for row in episodes}),
        },
        "behavioral_prefix_inventory": inventory,
        "cluster_views": cluster_views,
        "local_gold_correspondence": gold,
        "priority_sets": priority,
        "episode_summaries": episode_summaries,
        "interpretation": {
            "local_gold_present": gold["strong_correspondence_gold_family_ids"],
            "live_only_bronze_h200_route_clusters": gold[
                "h200_field_route_clusters_without_strong_gold_correspondence"
            ],
            "acquisition_priority": (
                "Seek executable artifacts for loss, close-margin, and high-rating-win clusters; then re-probe on "
                "common seeds and seats."
            ),
            "promotion_rule": "No live opponent is promoted to Gold from replay correspondence alone.",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-dir", default=str(DEFAULT_EVALUATION_DIR))
    parser.add_argument("--common-probe", default=str(DEFAULT_COMMON_PROBE))
    parser.add_argument(
        "--additional-probe",
        action="append",
        default=[],
        help="Additional frozen common-probe JSON; repeat for multiple files.",
    )
    parser.add_argument("--output", default=None)
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evaluation_dir = _resolve(args.evaluation_dir)
    output_path = _resolve(args.output) if args.output else evaluation_dir / DEFAULT_OUTPUT_NAME
    report_path = _resolve(args.report)
    additional_probe_paths = (
        [_resolve(path) for path in args.additional_probe]
        if args.additional_probe
        else [path.resolve() for path in DEFAULT_ADDITIONAL_PROBES]
    )
    payload = build_summary(
        evaluation_dir / "episode_metrics.json",
        evaluation_dir / "opponent_action_lineages.json",
        evaluation_dir / "analysis.json",
        _resolve(args.common_probe),
        additional_probe_paths,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": _relative(output_path),
                "output_sha256": _sha256(output_path),
                "report": _relative(report_path),
                "episodes": payload["coverage"]["public_live_episodes"],
                "h200_field_route_clusters": payload["behavioral_prefix_inventory"]["field_route"]["200"],
                "strong_gold_correspondence_episodes": payload["local_gold_correspondence"][
                    "strong_correspondence_episode_count"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
