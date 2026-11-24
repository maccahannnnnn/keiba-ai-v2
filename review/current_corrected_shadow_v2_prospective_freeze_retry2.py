"""Create the exclusive retry2 immutable snapshot; does not run Formal PRE."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "current_corrected_shadow_v2_prospective_protocol_v1_freeze_retry3_final_v3"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> dict:
    if OUT.exists():
        raise RuntimeError("STOP_PROTOCOL_RETRY2_FREEZE_OUTPUT_EXISTS")
    files = [
        "docs/current_corrected_shadow_v2_prospective_protocol_v1.json",
        "docs/current_corrected_shadow_v2_prospective_protocol_v1_sha256.json",
        "docs/current_corrected_shadow_v2_prospective_execution_authorization_schema_v1.json",
        "review/current_corrected_shadow_v2_prospective_protocol_v1.py",
        "review/current_corrected_shadow_v2_prospective_validators_v1.py",
        "review/current_corrected_shadow_v2_prospective_pre_v1.py",
        "review/current_corrected_shadow_v2_prospective_post_v1.py",
        "review/current_corrected_shadow_v2_prospective_cumulative_v1.py",
        "review/current_corrected_shadow_v2_prospective_diagnostics_v1.py",
        "review/current_corrected_shadow_v2_prospective_date_registry_v1.py",
        "review/current_corrected_shadow_v2_prospective_calibration_v1.py",
        "review/current_corrected_shadow_v2_prospective_test_runner_retry2.py",
        "review/current_corrected_shadow_v2_prospective_freeze_retry2.py",
        "tests/test_current_corrected_shadow_v2_prospective_protocol_v1.py",
        "tests/test_current_corrected_shadow_v2_prospective_retry2_v1.py",
        "reports/current_corrected_shadow_v2_prospective_human_design_snapshot_retry2.json",
        "reports/current_corrected_shadow_v2_prospective_state_machine_retry2.json",
        "reports/current_corrected_shadow_v2_prospective_ledger_reference_retry2.json",
        "reports/current_corrected_shadow_v2_prospective_output_schema_v1.json",
        "reports/current_corrected_shadow_v2_prospective_calibration_retry2_provenance.json",
        "reports/current_corrected_shadow_v2_prospective_test_report_retry2.json",
        "reports/current_corrected_shadow_v2_prospective_protocol_v1_freeze_retry2_supersession.json",
        "reports/current_corrected_shadow_v2_prospective_protocol_v1_freeze_retry3_supersession.json",
        "reports/current_corrected_shadow_v2_prospective_calibration_v1/summary.json",
        "reports/current_corrected_shadow_v2_prospective_calibration_v1/race_controls.json",
        "reports/current_corrected_shadow_v2_prospective_calibration_v1/date_controls.json",
        "reports/current_corrected_shadow_v2_prospective_calibration_v1/provenance.json",
        "reports/current_corrected_shadow_v2_prospective_calibration_v1/report.md",
        "reports/current_corrected_shadow_v2_prospective_calibration_v1/artifact_hashes.json",
        "reports/current_corrected_shadow_v2_freeze_v6.json",
        "reports/current_corrected_shadow_v2_freeze_v6_artifacts/artifact_hashes.json",
    ]
    OUT.mkdir(parents=True)
    copied: list[Path] = []
    for relative in files:
        source = ROOT / relative
        if not source.is_file():
            raise RuntimeError("STOP_PROTOCOL_RETRY2_FREEZE_MISSING:" + relative)
        target = OUT / "snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
    indexed = {str(path.relative_to(OUT)).replace("\\", "/"): sha(path) for path in copied}
    write(OUT / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": indexed})
    observed = {name: sha(OUT / name) for name in indexed}
    record = {
        "schema_version": "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_PROTOCOL_V1_FREEZE_RETRY3",
        "status": "FROZEN_PENDING_INDEPENDENT_REVIEW",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "artifact_count": len(indexed),
        "FREEZE_SHA_REVERIFY": "PASS" if indexed == observed else "FAIL",
        "HASH_MISMATCH": sum(indexed.get(k) != observed.get(k) for k in set(indexed) | set(observed)),
        "MISSING_FREEZE_ARTIFACT": sum(not (OUT / name).is_file() for name in indexed),
        "formal_execution_authorized": False,
        "formal_prospective_started": False,
        "production_authorization": False,
        "result_access_count": 0,
        "performance_evaluation": False,
        "initial_and_retry1_preserved": True,
        "prior_retry2_preserved": True,
        "prior_retry2_final_path": "reports/current_corrected_shadow_v2_prospective_protocol_v1_freeze_retry2_final",
        "retry3_reason": "Formal POST public runner, freeze-bound external authorization, exact PRE file-set checks, and canonical date-attempt registry.",
    }
    write(OUT / "freeze_record.json", record)
    write(OUT / "root_manifest.json", {
        "self_hash_excluded": True,
        "purpose": "external canonical integrity of non-self-hashable retry2 root artifacts",
        "artifact_hashes_sha256": sha(OUT / "artifact_hashes.json"),
        "freeze_record_sha256": sha(OUT / "freeze_record.json"),
        "supersession_snapshot_sha256": indexed["snapshot/reports/current_corrected_shadow_v2_prospective_protocol_v1_freeze_retry2_supersession.json"],
    })
    (OUT / "root_manifest.sha256").write_text(sha(OUT / "root_manifest.json") + "\n", encoding="utf-8")
    return record | {"root_manifest_sha256": sha(OUT / "root_manifest.json"), "artifact_hashes_sha256": sha(OUT / "artifact_hashes.json")}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
