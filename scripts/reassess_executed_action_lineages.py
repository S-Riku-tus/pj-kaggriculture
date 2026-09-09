"""Conservative post-run action-lineage independence assessment.

This never overwrites or upgrades a preregistered result.  It exists to
correct a source-version/independent-action-lineage mismatch discovered from
the frozen formal traces and can only be used as a downgrade/sensitivity
assessment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluation.registry import write_record  # noqa: E402
from scripts.evaluation.report import build_evaluation, markdown_report  # noqa: E402
from scripts.evaluation.schema import load_preregistration  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result_path = args.result.resolve()
    output = args.output.resolve()
    source = json.loads(result_path.read_text(encoding="utf-8"))
    preregistration_path = Path(source["preregistration"])
    spec, preregistration_hash = load_preregistration(preregistration_path)
    if preregistration_hash != source["preregistration_sha256"]:
        raise ValueError("source result and preregistration hash disagree")
    evaluation = build_evaluation(
        list(source["pairs"]["fast_screen"]),
        list(source["pairs"]["formal_promotion"]),
        list(source["pairs"]["diagnostic_reproduction"]),
        spec,
        source["provenance"],
    )
    payload = {
        "format": "kaggriculture-posthoc-action-lineage-assessment-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "assessment_scope": (
            "Conservative downgrade/sensitivity audit after identical executable action "
            "fingerprints were discovered. It is not preregistered evidence and cannot "
            "upgrade the original promotion decision."
        ),
        "source_result": str(result_path),
        "source_result_sha256": _sha256(result_path),
        "original_decision": source["evaluation"]["decision"],
        "preregistration": str(preregistration_path),
        "preregistration_sha256": preregistration_hash,
        "provenance": source["provenance"],
        "dataset_roles": source["dataset_roles"],
        "evidence_policy": source["evidence_policy"],
        "evaluation": evaluation,
    }
    write_record(output, payload)
    report_path = output.with_suffix(".md")
    warning = (
        "# Post-run independent action-lineage correction\n\n"
        "> This is a conservative posthoc downgrade audit. The immutable preregistered "
        "result remains the experiment record, and this assessment cannot promote V113.\n\n"
    )
    report_path.write_text(warning + markdown_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "decision": evaluation["decision"],
                "observed_action_families": evaluation["formal_promotion"][
                    "lineage_independence_audit"
                ]["observed_action_families"],
                "assessment": str(output),
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
