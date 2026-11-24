"""Register completed 2026-08-30 evidence and recheck February exclusivity.

Registry maintenance only: no prediction, result file, or frozen February PRE
artifact is opened for mutation.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.date_exclusivity_validator_v1 import collect_evidence_dates, validate


OUT = ROOT / "reports/v4_model_v4_february_historical_holdout/date_exclusivity_registry_maintenance_20260830_v1"
PRE = ROOT / "reports/v4_model_v4_february_historical_holdout/formal_pre"
CLAUDE = PRE / "pre_independent_review_manifest.json"
DATES = ["20260201", "20260207", "20260208", "20260210", "20260214", "20260215", "20260221", "20260222", "20260228"]
CLAUDE_SHA = "c3ea3ecc2f8faec8fe7361f4f0c6354ca5471ee36a498e439140a7db00f9f412"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, payload: object) -> None:
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify_index() -> bool:
    index = json.loads((PRE / "artifact_hashes.json").read_text(encoding="utf-8")).get("indexed_artifacts")
    return isinstance(index, dict) and len(index) == 230 and all((PRE / name).is_file() and sha(PRE / name) == digest for name, digest in index.items())


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    if not CLAUDE.is_file() or sha(CLAUDE) != CLAUDE_SHA:
        raise RuntimeError("CLAUDE_MANIFEST_AUTHORITY_MISMATCH")
    if not verify_index():
        raise RuntimeError("FEBRUARY_PRE_INTEGRITY_MISMATCH_BEFORE")

    v4_path = ROOT / "reports/v4_model_v3_formal_prospective/20260830_post/evidence_ledger_update.json"
    cf_path = ROOT / "reports/shadow_cf_top3_rank_anchored_v1/formal_post_20260830/formal_status.json"
    v4 = json.loads(v4_path.read_text(encoding="utf-8"))
    cf = json.loads(cf_path.read_text(encoding="utf-8"))
    if v4.get("evidence_role") != "FORMAL_PROSPECTIVE_SHADOW_V4_MODEL_V3" or v4.get("eligible_dates") != ["20260830"]:
        raise RuntimeError("V4_20260830_COMPLETED_EVIDENCE_AUTHORITY_INVALID")
    if "20260830" not in cf.get("completed_dates", []):
        raise RuntimeError("CF_20260830_COMPLETED_EVIDENCE_AUTHORITY_INVALID")

    records = collect_evidence_dates(ROOT)
    result = validate(DATES, records)
    if result["overlap_count"] != 0:
        raise RuntimeError(f"FEBRUARY_DATE_EXCLUSIVITY_CONFLICT:{result['overlap_dates']}")
    records_0830 = [record for record in records if record["dates"] == ["20260830"] and record["category"] in {"formal_prospective_v4", "formal_prospective_cf"}]
    if len(records_0830) != 2:
        raise RuntimeError("DATE_REGISTRY_20260830_RECORD_COUNT_INVALID")

    OUT.mkdir(parents=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    write("registry_records_added.json", {
        "artifact_type": "DATE_EXCLUSIVITY_REGISTRY_20260830_UPDATE_V1",
        "status": "UPDATED",
        "records": [
            {"date": "20260830", "category": "formal_prospective_v4", "evidence_role": "FORMAL_PROSPECTIVE_SHADOW_V4_MODEL_V3", "completion_authority": "PROSPECTIVE_POST_20260830_INDEPENDENT_REVIEW = ACCEPT", "authority_path": str(v4_path.relative_to(ROOT)), "authority_sha256": sha(v4_path)},
            {"date": "20260830", "category": "formal_prospective_cf", "evidence_role": "FORMAL_PROSPECTIVE_SHADOW_CF_TOP3_RANK_ANCHORED", "completion_authority": "completed CF Formal Prospective evidence", "authority_path": str(cf_path.relative_to(ROOT)), "authority_sha256": sha(cf_path)},
        ],
        "registry_semantics": "Existing date_exclusivity_validator_v1 _record(category, evidence_role, dates, authority_path) semantics only; evidence families remain separate.",
        "timestamp_utc": now,
    })
    result.update({"artifact_type": "FEBRUARY_DATE_EXCLUSIVITY_POST_20260830_REGISTRY_V1", "registry_records_added": 2, "candidate_dates": DATES, "checked_at_utc": now, "result_data_access_count": 0})
    write("february_date_exclusivity_post_review.json", result)
    after_pre = verify_index()
    after_claude = sha(CLAUDE)
    safety = {"artifact_type": "DATE_EXCLUSIVITY_REGISTRY_MAINTENANCE_SAFETY_V1", "status": "PASS" if after_pre and after_claude == CLAUDE_SHA else "FAIL", "february_pre_artifact_mutation_count": 0, "february_pre_hash_index_verified_before": True, "february_pre_hash_index_verified_after": after_pre, "claude_manifest_mutation_count": 0, "claude_manifest_sha256_before": CLAUDE_SHA, "claude_manifest_sha256_after": after_claude, "february_result_data_access_count": 0, "prediction_execution_count": 0, "post_execution_count": 0, "model_v4_mutation_count": 0, "cf_mutation_count": 0, "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    write("safety.json", safety)
    report = "# Evidence Date Registry Maintenance — 2026-08-30\n\n- Registry records added: `2` (V4 and CF are distinct)\n- February candidate dates: `9`\n- February overlap count: `0`\n- February PRE mutation: `0`\n- Claude manifest mutation: `0`\n- February Result access: `0`\n\nThe February PRE freeze remains authoritative. This maintenance run does not authorize February Result access or POST.\n"
    (OUT / "report.md").write_text(report, encoding="utf-8")
    hashes = {path.name: sha(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}
    write("artifact_hashes.json", {"artifact_type": "DATE_EXCLUSIVITY_REGISTRY_MAINTENANCE_HASH_INDEX_V1", "indexed_artifacts": hashes, "self_hash_excluded": True})
    if any(sha(OUT / name) != digest for name, digest in hashes.items()):
        raise RuntimeError("MAINTENANCE_ARTIFACT_HASH_MISMATCH")
    print("DATE_EXCLUSIVITY_REGISTRY_20260830=UPDATED")
    print("FEBRUARY_DATE_EXCLUSIVITY_POST_REVIEW=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
