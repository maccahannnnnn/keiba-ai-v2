"""Result-free technical calibration for the V2 prospective protocol."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from review.current_corrected_shadow_v2 import CorrectionConfigV2, apply_corrected_shadow_v2
from review.current_corrected_shadow_v2_prospective_protocol_v1 import control_observables, load_protocol, sha, validate_protocol, verify_freeze_pins
from review.current_corrected_shadow_v2_runner import run_new_v2
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "current_corrected_shadow_v2_prospective_calibration_v1"
DATES = ("20260926", "20260927")
FIELDS = ("horse_set", "buy_set", "race_state", "rank", "adjusted_score", "final_score", "decision", "decision_score")

def assert_result_free(value: object) -> None:
    forbidden = {"actual_top3", "finish", "result", "placing", "buy_top3_rate", "hits"}
    if isinstance(value, dict):
        if any(str(key).lower() in forbidden for key in value): raise RuntimeError("STOP_RESULT_LEAKAGE")
        for item in value.values(): assert_result_free(item)
    elif isinstance(value, list):
        for item in value: assert_result_free(item)

def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def run(output: Path = OUTPUT) -> dict[str, object]:
    if output.exists(): raise RuntimeError("STOP_CALIBRATION_OUTPUT_EXISTS")
    protocol = load_protocol(); validate_protocol(protocol); verify_freeze_pins(protocol)
    all_rows, by_date = [], []
    for date in DATES:
        current_root = ROOT / "reports" / f"daily_pre_analysis_{date}" / "current_frozen"
        index = json.loads((current_root / "race_index.json").read_text(encoding="utf-8"))["race_index"]
        provenance = json.loads((current_root / "provenance.json").read_text(encoding="utf-8"))
        if provenance.get("target_date") != date or provenance.get("result_data_access_count") != 0:
            raise RuntimeError("STOP_CALIBRATION_CURRENT_PRE_PROVENANCE")
        bundle = TargetBulkPredictionInputAdapterV1().load(*(ROOT / "data/raw/prediction_input" / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")))
        if bundle.date != date: raise RuntimeError("STOP_CALIBRATION_INPUT_DATE")
        date_counts = {field: 0 for field in FIELDS}; corrected_count = 0
        for entry in index:
            frozen = json.loads((current_root / entry["artifact"]).read_text(encoding="utf-8")); assert_result_free(frozen)
            control = run_new_v2(entry["race_id"], bundle.races[entry["race_id"]], CorrectionConfigV2.all_off())
            mismatches = control_observables(control, frozen)
            for field, count in mismatches.items(): date_counts[field] += count
            corrected = apply_corrected_shadow_v2(run_new_v2(entry["race_id"], bundle.races[entry["race_id"]], CorrectionConfigV2.all_on())["ranked_results"], CorrectionConfigV2.all_on())
            corrected_count += len(corrected)
            all_rows.append({"date": date, "race_id": entry["race_id"], "control_mismatches": mismatches, "corrected_row_count": len(corrected)})
        by_date.append({"date": date, "current_pre_root": str(current_root.relative_to(ROOT)).replace("\\", "/"), "race_count": len(index), "control_mismatch_counts": date_counts, "corrected_row_count": corrected_count})
    totals = {field: sum(item["control_mismatch_counts"][field] for item in by_date) for field in FIELDS}
    required = ("horse_set", "buy_set", "race_state", "rank", "adjusted_score")
    if any(totals[field] for field in required): raise RuntimeError("STOP_DAILY_CONTROL_CALIBRATION_INSUFFICIENT")
    output.mkdir(parents=True)
    summary = {"schema_version": "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_CALIBRATION_V1", "status": "TECHNICAL_CALIBRATION_ONLY", "calibration_dates": list(DATES), "result_data_access_count": 0, "performance_evaluation": False, "final_control_field_set": list(FIELDS), "mismatch_counts": totals, "unavailable_fields": [], "calibration_verdict": "PASS", "runtime_sha256": {path.name: sha(path) for path in (ROOT / "review" / "current_corrected_shadow_v2.py", ROOT / "review" / "current_corrected_shadow_v2_runner.py", ROOT / "review" / "current_corrected_shadow_v2_replay.py", ROOT / "review" / "current_corrected_shadow_v2_aggregator.py")}, "driver_sha256": sha(Path(__file__))}
    _write(output / "summary.json", summary); _write(output / "race_controls.json", {"rows": all_rows}); _write(output / "date_controls.json", {"dates": by_date})
    _write(output / "provenance.json", {"generated_at": datetime.now(timezone.utc).isoformat(), "role": "NON_FORMAL_TECHNICAL_CALIBRATION_ONLY", "result_data_access_count": 0, "protocol_sha256": sha(ROOT / "docs/current_corrected_shadow_v2_prospective_protocol_v1.json")})
    _write(output / "report.md", "# V2 Prospective Technical Calibration\n\nNON_FORMAL_TECHNICAL_CALIBRATION_ONLY。Resultアクセス・性能評価は0。\n")
    hashes = {path.name: sha(path) for path in output.iterdir() if path.is_file()}; _write(output / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": hashes})
    return summary

if __name__ == "__main__": print(json.dumps(run(), ensure_ascii=False))
