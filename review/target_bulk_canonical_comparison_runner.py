"""Execute the bounded TARGET Bulk Canonical Comparison v1 audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from review.target_bulk_canonical_comparison import TargetBulkCanonicalReconciler, write_json
from review.target_bulk_result_intake import TargetBulkResultSplitter


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/target/scehema_samples/テスト３.csv"
SOURCE_RECONCILIATION = ROOT / "reports/target_bulk_result_sample_validation_v1/target_bulk_reconciliation_v1.json"
CONFLICT_LIST = ROOT / "reports/target_bulk_conflict_audit_v1/target_bulk_conflict_list_v1.csv"
HUMAN_EVIDENCE = ROOT / "reports/target_bulk_human_review_v1/target_bulk_human_review_cells_v1.csv"
TEMP_SPLIT = ROOT / "reports/target_bulk_conflict_audit_v1/temp_split"
OUTPUT = ROOT / "reports/target_bulk_canonical_comparison_v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> dict:
    if TEMP_SPLIT.exists():
        raise RuntimeError("TEMP_SPLIT_ALREADY_EXISTS")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    splitter = TargetBulkResultSplitter()
    staged = splitter.stage(RAW, TEMP_SPLIT)
    try:
        recorded = json.loads(SOURCE_RECONCILIATION.read_text(encoding="utf-8"))
        expected = {Path(row["path"]).name: row["sha256"] for row in recorded["files"]}
        actual = {Path(row["path"]).name: row["sha256"] for row in staged["split_files"]}
        if len(expected) != 192 or actual != expected:
            raise RuntimeError("RECONSTRUCTED_SPLIT_SHA_SET_MISMATCH")

        result = TargetBulkCanonicalReconciler(HUMAN_EVIDENCE).reconcile(CONFLICT_LIST)
        result["generated_at"] = datetime.now().astimezone().isoformat()
        result["inputs"] = {
            "raw_path": RAW.relative_to(ROOT).as_posix(), "raw_sha256": sha(RAW),
            "schema_path": "docs/target_bulk_result_schema_v1.json",
            "schema_sha256": staged["schema_sha256"],
            "source_reconciliation_path": SOURCE_RECONCILIATION.relative_to(ROOT).as_posix(),
            "source_reconciliation_sha256": sha(SOURCE_RECONCILIATION),
            "conflict_list_path": CONFLICT_LIST.relative_to(ROOT).as_posix(),
            "conflict_list_sha256": sha(CONFLICT_LIST),
            "human_evidence_path": HUMAN_EVIDENCE.relative_to(ROOT).as_posix(),
            "human_evidence_sha256": sha(HUMAN_EVIDENCE),
            "reconstructed_split_file_count": len(actual), "reconstructed_split_sha_match_count": len(actual),
        }
        write_json(OUTPUT / "target_bulk_canonical_comparison_result_v1.json", result)
        return result
    finally:
        shutil.rmtree(TEMP_SPLIT, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", required=True)
    parser.parse_args()
    result = run()
    print(json.dumps({key: result[key] for key in ("status", "file_count", "taxonomy_counts", "file_status_counts", "conflict_stop_count")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
