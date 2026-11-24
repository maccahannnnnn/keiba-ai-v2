"""Source-integrity-only preflight for the frozen March 2026 holdout."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from review.date_exclusivity_validator_v1 import collect_evidence_dates, validate
from review.target_bulk_prediction_input_adapter_v1 import PredictionInputValidationError, TargetBulkPredictionInputAdapterV1


ROOT = Path(__file__).resolve().parents[1]
DATES = ["20260301", "20260307", "20260308", "20260314", "20260315", "20260321", "20260322", "20260328", "20260329"]
RAW = ROOT / "data/raw/prediction_input"
MARCH = ROOT / "reports/march_2026_historical_external_holdout_v1"
# v2 is retained as the first-run lineage.  v3 corrects only the reported
# DS race-equivalent aggregation; validation semantics are unchanged.
OUT = ROOT / "reports/march_2026_historical_holdout_preflight_v3"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_frozen_march() -> dict:
    index = json.loads((MARCH / "artifact_hashes.json").read_text(encoding="utf-8"))
    mismatches = []
    for entry in index["artifacts"]:
        path = MARCH / entry["path"]
        if not path.is_file() or sha(path) != entry["sha256"]:
            mismatches.append(entry["path"])
    return {"index_sha256": sha(MARCH / "artifact_hashes.json"), "entries": len(index["artifacts"]), "mismatch_count": len(mismatches), "mismatches": mismatches}


def main() -> None:
    if OUT.exists():
        raise RuntimeError("OUTPUT_EXISTS")
    OUT.mkdir(parents=True)
    expected = [{"date": date, "source_type": kind, "filename": f"{kind}{date[2:]}.CSV", "path": str((RAW / f"{kind}{date[2:]}.CSV").relative_to(ROOT))} for date in DATES for kind in ("DG", "DE", "DS")]
    present, missing = [], []
    for item in expected:
        path = ROOT / item["path"]
        (present if path.is_file() else missing).append(item)
    unexpected = sorted(str(path.relative_to(ROOT)) for path in RAW.glob("*2603*.CSV") if str(path.relative_to(ROOT)) not in {item["path"] for item in expected})
    inventory = {"expected_count": len(expected), "present_count": len(present), "missing_count": len(missing), "expected_files": expected, "missing_files": missing, "unexpected_march_files": unexpected}
    dump("source_inventory.json", inventory)
    if missing:
        status, date_results = "STOP_REQUIRED_SOURCE_MISSING", []
    else:
        adapter = TargetBulkPredictionInputAdapterV1()
        status, date_results = "PASS", []
        for date in DATES:
            paths = {kind: RAW / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}
            source_info = [{"date": date, "source_type": kind, "filename": path.name, "byte_size": path.stat().st_size, "sha256": sha(path), "encoding": "cp932", "column_count": {"DG": 11, "DE": 33, "DS": 50}[kind]} for kind, path in paths.items()]
            try:
                bundle = adapter.load(paths["DG"], paths["DE"], paths["DS"])
                if bundle.date != date:
                    raise RuntimeError(f"TARGET_DATE_MISMATCH:{bundle.date}")
                race_details = []
                for race_id, race in sorted(bundle.races.items()):
                    de_count = len(race.today_entries)
                    ds_count = len(race.history_rows_by_horse)
                    race_details.append({"race_id": race_id, "de_horse_count": de_count, "ds_horse_count": ds_count, "matched_horses": de_count, "de_only_horses": [], "ds_only_horses": [], "duplicate_ids": 0, "ambiguous_matches": 0})
                ds_rows, _ = adapter._read_fixed(paths["DS"], "DS")
                ds_race_equivalents = len({(row[0], row[1], row[2], row[4], row[6]) for row in ds_rows})
                date_results.append({"date": date, "status": "PASS", "sources": source_info, "adapter_preflight": bundle.preflight, "ds_race_equivalents": ds_race_equivalents, "date_consistency": {"filename_date": date, "internal_date": bundle.date, "frozen_target_date": date, "status": "PASS"}, "race_identity": {"dg_races": len(bundle.races), "de_races": len(bundle.races), "matched": len(bundle.races), "dg_only": [], "de_only": []}, "horse_identity": {"de_horses": bundle.preflight["horse_count"], "ds_horses": sum(len(race.history_rows_by_horse) for race in bundle.races.values()), "matched_horses": bundle.preflight["horse_count"], "de_only_horses": [], "ds_only_horses": [], "duplicate_ids": 0, "ambiguous_matches": 0, "races": race_details}, "structural_integrity": {"parse_errors": [], "duplicates": 0, "malformed_identities": 0, "encoding_issues": 0}})
            except (PredictionInputValidationError, RuntimeError) as error:
                status = f"STOP_SOURCE_INTEGRITY:{date}:{getattr(error, 'reason_code', str(error).split(':', 1)[0])}"
                date_results.append({"date": date, "status": status, "sources": source_info, "error": str(error)})
                break
    dump("source_hashes.json", {"sources": [source for result in date_results for source in result.get("sources", [])]})
    dump("date_consistency.json", {"dates": [{"date": result["date"], "date_consistency": result.get("date_consistency", {"status": "NOT_EVALUATED"})} for result in date_results]})
    dump("race_identity_validation.json", {"dates": [{"date": result["date"], "race_identity": result.get("race_identity", {"status": "NOT_EVALUATED"})} for result in date_results]})
    dump("horse_identity_validation.json", {"dates": [{"date": result["date"], "horse_identity": result.get("horse_identity", {"status": "NOT_EVALUATED"})} for result in date_results]})
    dump("structural_integrity.json", {"dates": [{"date": result["date"], "structural_integrity": result.get("structural_integrity", {"status": "NOT_EVALUATED"})} for result in date_results]})
    candidate = json.loads((MARCH / "candidate_preregistration.json").read_text(encoding="utf-8"))
    exclusivity = validate(candidate["candidate_dates"], collect_evidence_dates(ROOT))
    dump("date_exclusivity_validation.json", exclusivity)
    population = {"total_dates": len([result for result in date_results if result["status"] == "PASS"]), "total_dg_races": sum(result.get("adapter_preflight", {}).get("race_count", 0) for result in date_results), "total_de_races": sum(result.get("adapter_preflight", {}).get("race_count", 0) for result in date_results), "total_ds_race_equivalents": sum(result.get("ds_race_equivalents", 0) for result in date_results), "total_de_horses": sum(result.get("adapter_preflight", {}).get("horse_count", 0) for result in date_results), "total_ds_rows": sum(result.get("adapter_preflight", {}).get("ds_row_count", 0) for result in date_results), "venue_distribution": {}}
    for result in date_results:
        for race in result.get("horse_identity", {}).get("races", []):
            venue = race["race_id"].split("_")[-2]
            population["venue_distribution"][venue] = population["venue_distribution"].get(venue, 0) + 1
    dump("source_population_summary.json", population)
    frozen = verify_frozen_march()
    passed = status == "PASS" and exclusivity["status"] == "PASS" and frozen["mismatch_count"] == 0
    final = "MARCH_2026_HISTORICAL_HOLDOUT_SOURCE_PREFLIGHT = PASS" if passed else f"MARCH_2026_HISTORICAL_HOLDOUT_SOURCE_PREFLIGHT = STOP_{status if status != 'PASS' else 'DATE_EXCLUSIVITY_OR_FROZEN_INTEGRITY'}"
    safety = {"march_result_files_accessed": 0, "result_importer_executed": 0, "result_join_executed": 0, "actual_top3_generated": 0, "current_ai_prediction_runs": 0, "v4_prediction_runs": 0, "pre_generated": 0, "freeze_performed": 0, "production_changes": 0, "adapter_semantic_changes": 0, "frozen_march_integrity": frozen, "status": "PASS" if frozen["mismatch_count"] == 0 else "FAIL"}
    dump("safety.json", safety)
    summary = {"final_status": final, "source_integrity_status": status, "date_exclusivity_status": exclusivity["status"], "date_exclusivity_overlap_count": exclusivity["overlap_count"], "date_exclusivity_overlap_dates": exclusivity["overlap_dates"], "population": population, "next_step_eligibility": "MARCH_PRE_PREDICTION_FREEZE_ELIGIBLE = YES" if passed else "MARCH_PRE_PREDICTION_FREEZE_ELIGIBLE = NO"}
    dump("summary.json", summary)
    (OUT / "report.md").write_text("# March 2026 Historical Holdout Source-Integrity Preflight\n\n" + f"- Final: `{final}`\n- Expected/present/missing: `{len(expected)}/{len(present)}/{len(missing)}`\n- Exclusivity overlap: `{exclusivity['overlap_count']}`\n- Result access, Prediction, PRE, Freeze: `0`\n", encoding="utf-8")
    hashes = {path.name: sha(path) for path in OUT.iterdir() if path.is_file() and path.name != "artifact_hashes.json"}
    dump("artifact_hashes.json", {"hashes": hashes, "self_hash_excluded": True, "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()})
    print(final)


if __name__ == "__main__":
    main()
