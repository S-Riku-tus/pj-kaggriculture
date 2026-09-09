"""Observed executable-action-lineage validation.

Source files are not automatically independent policy lineages.  This module
uses paired pre-intervention action fingerprints to identify source variants
that behaved identically on the frozen calibration grid.  The result is a
conservative statistical clustering diagnostic, not proof that two policies
are identical on every possible state.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from typing import Any


def _family_id(signature: list[tuple[int, int, str]]) -> str:
    encoded = json.dumps(signature, separators=(",", ":")).encode("utf-8")
    return f"action_family_{hashlib.sha256(encoded).hexdigest()[:12]}"


def audit_action_lineage_independence(
    rows: list[dict[str, Any]],
    *,
    fingerprint_key: str | None = None,
) -> dict[str, Any]:
    """Cluster declared source lineages with identical fingerprint vectors.

    The vector is ordered by requested seed and focal seat.  A complete common
    grid is required; otherwise the audit is invalid and no independence claim
    should be made.
    """
    if fingerprint_key is None:
        complete_pre_intervention = all(
            (row.get("executed_lineages") or {}).get("opponent_control_pre_intervention")
            is not None
            for row in rows
        )
        fingerprint_key = (
            "opponent_control_pre_intervention"
            if complete_pre_intervention
            else "opponent_control_h200"
        )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["lineage_id"])].append(row)
    all_grid = sorted({(int(row["seed"]), int(row["seat"])) for row in rows})
    signatures: dict[str, list[tuple[int, int, str]]] = {}
    missing: list[dict[str, Any]] = []
    for lineage, selected in sorted(grouped.items()):
        by_key = {(int(row["seed"]), int(row["seat"])): row for row in selected}
        signature = []
        for seed, seat in all_grid:
            row = by_key.get((seed, seat))
            fingerprint = (
                (row.get("executed_lineages") or {}).get(fingerprint_key) if row else None
            )
            if fingerprint is None:
                missing.append({"lineage_id": lineage, "seed": seed, "seat": seat})
                continue
            signature.append((seed, seat, str(fingerprint)))
        signatures[lineage] = signature

    signature_groups: dict[str, list[str]] = defaultdict(list)
    signature_rows: dict[str, list[tuple[int, int, str]]] = {}
    for lineage, signature in signatures.items():
        canonical = json.dumps(signature, separators=(",", ":"))
        signature_groups[canonical].append(lineage)
        signature_rows[canonical] = signature

    source_weights = {
        lineage: float(selected[0].get("meta_weight", 0.0))
        for lineage, selected in grouped.items()
    }
    families = []
    source_to_family: dict[str, str] = {}
    for canonical in sorted(signature_groups):
        sources = sorted(signature_groups[canonical])
        signature = signature_rows[canonical]
        family_id = _family_id(signature)
        for source in sources:
            source_to_family[source] = family_id
        families.append(
            {
                "family_id": family_id,
                "source_lineages": sources,
                "source_count": len(sources),
                "aggregate_meta_weight": sum(source_weights[source] for source in sources),
                "fingerprint_vector": [
                    {"seed": seed, "seat": seat, "sha": fingerprint}
                    for seed, seat, fingerprint in signature
                ],
            }
        )
    duplicate_families = [row for row in families if row["source_count"] > 1]
    return {
        "method": (
            "Exact equality of opponent Control action-fingerprint vectors on the common "
            "pre-intervention seed/seat grid"
        ),
        "fingerprint_key": fingerprint_key,
        "checkpoint_limitation": (
            "A common pre-intervention fingerprint is not a universal-policy identity proof; "
            "future experiments must calibrate and freeze the fingerprint grid before promotion games."
        ),
        "declared_source_lineages": len(grouped),
        "observed_action_families": len(families),
        "common_grid_size": len(all_grid),
        "complete_common_grid": not missing,
        "missing_fingerprints": missing,
        "families": families,
        "duplicate_source_families": duplicate_families,
        "source_to_family": source_to_family,
        "independence_claim_valid": not missing and len(families) == len(grouped),
    }


def collapse_to_action_families(
    rows: list[dict[str, Any]], audit: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return rows clustered at the observed executable-action-family level."""
    if not audit.get("complete_common_grid"):
        raise ValueError("cannot collapse lineages without a complete fingerprint grid")
    mapping = dict(audit["source_to_family"])
    weights = {
        str(row["family_id"]): float(row["aggregate_meta_weight"])
        for row in audit["families"]
    }
    result = []
    for source_row in rows:
        row = copy.deepcopy(source_row)
        source = str(row["lineage_id"])
        family = mapping[source]
        row["source_lineage_id"] = source
        row["lineage_id"] = family
        row["meta_weight"] = weights[family]
        result.append(row)
    return result
