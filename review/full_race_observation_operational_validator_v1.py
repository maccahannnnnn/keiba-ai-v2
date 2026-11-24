"""Independent operational validation of finalized Full Race Observation v1."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from review.observation_manifest_validator import ObservationManifestValidator


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/full_race_observation_finalization_v1"
EXPECTED_RAW_SHA = "9264844e79c99e2e8f06a39116b4599bf5f8722e83b4059be689041069b65336"
EXPECTED_SCHEMA_SHA = "54ce8fe71652daeadadee46397b115cb8ea2377a3c24e2f32060d5de7d6b5a88"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(x for x in path.rglob("*") if x.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return digest.hexdigest()


def validate(root: str | Path = ROOT) -> dict:
    base = Path(root)
    findings = []
    summary = json.loads((base / "reports/full_race_observation_finalization_v1/full_race_observation_finalization_summary_v1.json").read_text(encoding="utf-8"))
    provenance = json.loads((base / "reports/full_race_observation_finalization_v1/full_race_observation_provenance_v1.json").read_text(encoding="utf-8"))
    expected_summary = {
        "status": "PASS", "row_count": 1146, "race_count": 96,
        "existing_result_reused_race_count": 25, "new_result_placed_race_count": 71,
        "new_result_placed_file_count": 142, "existing_result_overwrite_count": 0,
        "population_count": 8, "complete_population_count": 8,
        "incomplete_population_count": 0, "conflict_stop_count": 0,
        "prediction_output_in_manifest_count": 0, "baseline_membership": "EXCLUDED",
        "kpi_eligible": "NO", "production_evidence": "NO",
    }
    for key, expected in expected_summary.items():
        if summary.get(key) != expected:
            findings.append({"code": "SUMMARY_MISMATCH", "field": key, "expected": expected, "actual": summary.get(key)})
    if summary.get("missing_race_list") != []:
        findings.append({"code": "MISSING_RACE_REMAINS", "actual": summary.get("missing_race_list")})
    if provenance.get("raw_source_sha256") != EXPECTED_RAW_SHA or provenance.get("schema_sha256") != EXPECTED_SCHEMA_SHA:
        findings.append({"code": "SOURCE_PROVENANCE_MISMATCH"})
    if len(provenance.get("files", [])) != 192:
        findings.append({"code": "PROVENANCE_FILE_COUNT", "actual": len(provenance.get("files", []))})

    placement_counts = {key: 0 for key in ("EXISTING_RESULT_REUSED", "NEW_BULK_RESULT_PLACED")}
    file_failures = []
    for row in provenance.get("files", []):
        placement_counts[row["placement_mode"]] = placement_counts.get(row["placement_mode"], 0) + 1
        path = Path(row["official_path"])
        actual = sha(path) if path.is_file() else "MISSING"
        if actual != row["official_sha256"]:
            file_failures.append({"path": str(path), "expected": row["official_sha256"], "actual": actual})
        if row["placement_mode"] == "EXISTING_RESULT_REUSED" and actual != row["preexisting_sha256"]:
            file_failures.append({"path": str(path), "code": "PREEXISTING_SHA_CHANGED"})
        if row["placement_mode"] == "NEW_BULK_RESULT_PLACED" and actual != row["staged_sha256"]:
            file_failures.append({"path": str(path), "code": "NEW_RESULT_NOT_SOURCE_IDENTICAL"})
    if placement_counts != {"EXISTING_RESULT_REUSED": 50, "NEW_BULK_RESULT_PLACED": 142}:
        findings.append({"code": "PLACEMENT_FILE_COUNTS", "actual": placement_counts})
    if file_failures:
        findings.append({"code": "RESULT_FILE_SHA_FAILURE", "count": len(file_failures)})

    manifest_validator = ObservationManifestValidator()
    validations = []
    population_ids = set()
    for item in summary.get("manifests", []):
        path = Path(item["path"])
        manifest = json.loads(path.read_text(encoding="utf-8"))
        result = manifest_validator.validate(manifest)
        validations.append({"population_id": manifest.get("population_id"), **result})
        population_ids.add(manifest.get("population_id"))
        if result["status"] != "PASS":
            findings.append({"code": "MANIFEST_VALIDATOR_FAIL", "population_id": manifest.get("population_id"), "reasons": result["reason_codes"]})
        if set(manifest.get("expected_race_ids", [])) != {f"race_{manifest['date']}_{manifest['racecourse']}_{n}R" for n in range(1, 13)}:
            findings.append({"code": "EXPECTED_RACE_SET_NOT_1_TO_12", "population_id": manifest.get("population_id")})
        guards = (manifest.get("source"), manifest.get("baseline_membership"), manifest.get("kpi_eligible"), manifest.get("production_evidence"))
        if guards != ("TARGET_FRONTIER_JV", "EXCLUDED", "NO", "NO"):
            findings.append({"code": "POPULATION_GUARD_FAILURE", "population_id": manifest.get("population_id"), "actual": guards})
        if manifest.get("target_bulk_source_sha256") != EXPECTED_RAW_SHA or manifest.get("target_bulk_schema_sha256") != EXPECTED_SCHEMA_SHA:
            findings.append({"code": "MANIFEST_SOURCE_SHA_MISMATCH", "population_id": manifest.get("population_id")})
        if manifest.get("human_review_evidence_path") != str((base / "reports/target_bulk_human_review_v1/target_bulk_human_review_cells_v1.csv").resolve()):
            findings.append({"code": "HUMAN_EVIDENCE_LINK_MISSING", "population_id": manifest.get("population_id")})

    with (base / "reports/target_bulk_human_review_v1/target_bulk_human_review_cells_v1.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        human_rows = list(csv.DictReader(handle))
    if len(human_rows) != 5 or any(row.get("human_decision") != "BULK_RESULT_CORRECT" for row in human_rows):
        findings.append({"code": "HUMAN_EVIDENCE_NOT_PRESERVED"})

    kpi = json.loads((base / "reports/baseline/baseline_34_race_v1_kpi.json").read_text(encoding="utf-8"))
    metrics = {key: kpi[key] for key in ("buy_total", "valid_result_buy", "buy_top3", "official_buy_place_rate")}
    if metrics != {"buy_total": 40, "valid_result_buy": 39, "buy_top3": 10, "official_buy_place_rate": 25.64}:
        findings.append({"code": "BASELINE_KPI_CHANGED", "actual": metrics})
    return {
        "version": "FULL_RACE_OBSERVATION_OPERATIONAL_VALIDATOR_V1",
        "status": "PASS" if not findings else "FAIL", "findings": findings,
        "raw_sha256": sha(base / "data/raw/target/scehema_samples/テスト３.csv"),
        "schema_sha256": sha(base / "docs/target_bulk_result_schema_v1.json"),
        "race_count": 96, "horse_count": summary.get("horse_count"), "file_count": len(provenance.get("files", [])),
        "placement_file_counts": placement_counts, "result_file_sha_failure_count": len(file_failures),
        "population_count": len(population_ids), "complete_population_count": sum(row["completeness_status"] == "COMPLETE" for row in validations),
        "incomplete_population_count": sum(row["completeness_status"] == "INCOMPLETE" for row in validations),
        "manifest_validations": validations, "human_review_evidence_count": len(human_rows),
        "baseline_metrics": metrics, "baseline_tree_sha256": tree_hash(base / "reports/baseline"),
        "replay_tree_sha256": tree_hash(base / "reports/historical_replay"),
        "learning_tree_sha256": tree_hash(base / "learning"), "knowledge_tree_sha256": tree_hash(base / "knowledge"),
        "prediction_ranking_decision_buy_recalculation_count": 0,
        "trend_bias_ml_execution_count": 0,
    }


if __name__ == "__main__":
    payload = validate()
    path = OUT / "full_race_observation_operational_validation_v1.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
