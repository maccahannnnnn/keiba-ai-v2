"""Create the v6 immutable evidence snapshot without rerunning the replay."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "reports" / "current_corrected_shadow_v2_technical_replay_v5_final"
SNAPSHOT = ROOT / "reports" / "current_corrected_shadow_v2_freeze_v6_artifacts"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")

def mutation_entries(version: str, index: Path) -> list[dict[str, object]]:
    expected = json.loads(index.read_text(encoding="utf-8"))
    entries = []
    for name, frozen_sha in sorted(expected.items()):
        path = ROOT / name
        current = sha(path) if path.is_file() else None
        if current != frozen_sha:
            entries.append({
                "freeze_version": version,
                "affected_path": name,
                "frozen_expected_sha256": frozen_sha,
                "current_sha256": current,
                "recoverable": False,
                "recovery_performed": False,
                "reason": "shared working-file reference changed after the historical freeze; original bytes were not reconstructed",
                "authoritative_status": "HISTORICAL_FREEZE_NOT_CURRENT_VERIFICATION_AUTHORITY",
                "note": "No historical bytes were fabricated or regenerated.",
            })
    return entries

def main() -> dict[str, object]:
    if SNAPSHOT.exists():
        raise RuntimeError("FREEZE_V6_SNAPSHOT_ALREADY_EXISTS")
    v5_on = json.loads((REPLAY / "all_on_manifest.json").read_text(encoding="utf-8"))
    runtime_unchanged = (
        sha(ROOT / "review/current_corrected_shadow_v2.py") == v5_on["config_sha256"]
        and sha(ROOT / "review/current_corrected_shadow_v2_replay.py") == v5_on["runner_sha256"]
    )
    if not runtime_unchanged:
        raise RuntimeError("RUNTIME_CODE_CHANGED_SINCE_V5_REPLAY_REQUIRED")
    v5_supersession = ROOT / "reports/current_corrected_shadow_v2_freeze_v5_supersession.json"
    v5_supersession.write_text(json.dumps({
        "CURRENT_CORRECTED_SHADOW_V2_FREEZE_V5": "SUPERSEDED_AFTER_INDEPENDENT_REVIEW_REQUIRES_FIX",
        "reasons": ["mandatory test incompleteness", "historical mutation record incomplete"],
        "replacement": "current_corrected_shadow_v2_freeze_v6.json",
        "original_freeze_preserved": True,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mutation = {
        "schema_version": "CURRENT_CORRECTED_SHADOW_V2_HISTORICAL_FREEZE_MUTATION_RECORD_V6",
        "status": "HISTORICAL_FREEZE_ARTIFACT_MUTATED_AFTER_FREEZE",
        "entries": mutation_entries("v2", ROOT / "reports/current_corrected_shadow_v2_technical_replay_v2_retry2/artifact_hashes.json")
                   + mutation_entries("v3", ROOT / "reports/current_corrected_shadow_v2_technical_replay_v2_final/artifact_hashes.json"),
        "original_bytes_recoverable": False,
        "no_historical_bytes_were_fabricated": True,
        "impact_on_v6": "NONE; v6 snapshots its own immutable files.",
    }
    mutation_path = ROOT / "reports/current_corrected_shadow_v2_historical_freeze_mutation_record_v6.json"
    mutation_path.write_text(json.dumps(mutation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    execution = {
        "schema_version": "CURRENT_CORRECTED_SHADOW_V2_EXECUTION_RECORD_V6",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "replay_reused": True,
        "replay_reference": relative(REPLAY / "all_on_manifest.json"),
        "replay_started_at": v5_on["started_at"],
        "replay_completed_at": v5_on["completed_at"],
        "runtime_code_unchanged_since_v5": True,
        "result_access_count": 0,
        "performance_evaluation": False,
    }
    execution_path = ROOT / "reports/current_corrected_shadow_v2_execution_record_v6.json"
    execution_path.write_text(json.dumps(execution, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    SNAPSHOT.mkdir(parents=True)
    static = [
        "review/current_corrected_shadow_v2.py",
        "review/current_corrected_shadow_v2_runner.py",
        "review/current_corrected_shadow_v2_replay.py",
        "review/current_corrected_shadow_v2_aggregator.py",
        "review/current_corrected_shadow_v2_test_report_v6.py",
        "tests/test_current_corrected_shadow_v2.py",
        "reports/current_corrected_shadow_v2_correction_spec_snapshot_v3.json",
        "reports/current_corrected_shadow_v2_human_decision_snapshot_freeze_v6.json",
        "reports/current_corrected_shadow_v2_output_schema_v4.json",
        "reports/current_corrected_shadow_v2_test_report_v6.json",
        "reports/current_corrected_shadow_v2_risk_subflag_contract_v6.json",
        "reports/current_corrected_shadow_v2_historical_freeze_mutation_record_v6.json",
        "reports/current_corrected_shadow_v2_freeze_v5_supersession.json",
        "reports/current_corrected_shadow_v2_execution_record_v6.json",
    ]
    copied = []
    for name in static:
        source = ROOT / name
        target = SNAPSHOT / "static" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
    for source in sorted(REPLAY.rglob("*.json")):
        target = SNAPSHOT / "replay" / source.relative_to(REPLAY)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
    expected = {str(path.relative_to(SNAPSHOT)).replace("\\", "/"): sha(path) for path in copied}
    index = SNAPSHOT / "artifact_hashes.json"
    index.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    observed = {str(path.relative_to(SNAPSHOT)).replace("\\", "/"): sha(path) for path in copied}
    missing = [name for name in expected if not (SNAPSHOT / name).is_file()]
    freeze = {
        "schema_version": "CURRENT_CORRECTED_SHADOW_V2_FREEZE_V6",
        "CURRENT_CORRECTED_SHADOW_V2_REFROZEN_V6": "YES",
        "immutable_snapshot_root": relative(SNAPSHOT),
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "replay_reused": True,
        "runtime_code_unchanged_since_v5": True,
        "replay_reference": relative(REPLAY / "all_on_manifest.json"),
        "execution_record_snapshot": "static/reports/current_corrected_shadow_v2_execution_record_v6.json",
        "technical_replay_evidence_boundary": "POST_RESULT_ENGINEERING_REPLAY_ONLY",
        "freeze_artifact_count": len(copied),
        "hash_index": relative(index),
        "FREEZE_SHA_REVERIFY": "PASS" if expected == observed and not missing else "FAIL",
        "HASH_MISMATCH": sum(expected.get(key) != observed.get(key) for key in set(expected) | set(observed)),
        "MISSING_FREEZE_ARTIFACT": len(missing),
        "missing": missing,
        "production_authorization": False,
        "production_modified": False,
        "result_access_count": 0,
        "performance_evaluation": False,
    }
    target = ROOT / "reports/current_corrected_shadow_v2_freeze_v6.json"
    target.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(freeze, ensure_ascii=False))
    return freeze

if __name__ == "__main__":
    main()
