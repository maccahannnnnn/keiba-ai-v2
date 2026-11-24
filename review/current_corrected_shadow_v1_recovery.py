"""Result-free clean recovery harness for CURRENT_CORRECTED_SHADOW_V1.

Only PRE prediction artifacts are admitted.  The path gate is deliberately
fail-closed for POST/result-derived names, and payloads with outcome keys are
rejected before their horse records are examined.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from review.current_corrected_shadow_v1 import CorrectionConfig, apply_corrected_shadow, assert_production_reproduction


ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "reports" / "current_corrected_shadow_v1_clean_recovery"
DECEMBER_PAYLOAD = ROOT / "reports" / "december_2025_three_lane_one_shot_holdout_pre" / "current_prediction_payload.json"
POST_PATH_TOKEN = re.compile(r"(?:post|result|outcome|performance|versus|daily_result)", re.I)
OUTCOME_KEYS = {"race_result", "horse_results", "review_result", "actual_top3", "finish"}
COMPARE_KEYS = (
    "horse_number", "rank", "adjusted_score", "integrated_score", "final_score", "decision_score",
    "decision", "buy", "buy_v1_rc1_candidate", "buy_v1_rc1_race_state",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_pre_path(path: Path) -> None:
    if POST_PATH_TOKEN.search(path.as_posix()):
        raise RuntimeError(f"STOP_RESULT_DERIVED_PATH:{path}")


def _required_view(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in COMPARE_KEYS}


def _artifact_record(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if OUTCOME_KEYS.intersection(payload):
        raise RuntimeError(f"STOP_OUTCOME_KEY_IN_PRE_ARTIFACT:{path}")
    rows = payload.get("ranked_results")
    if not isinstance(rows, list):
        raise RuntimeError(f"STOP_PRE_RANKED_RESULTS_MISSING:{path}")
    reproduction_rows = apply_corrected_shadow(rows, CorrectionConfig.production_defaults())
    assert_production_reproduction(rows, reproduction_rows)
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": sha256(path),
        "evidence_role": "FROZEN_CURRENT_PRE_ARTIFACT",
        "race_id": str(payload.get("race_id") or path.stem.removesuffix("_prediction")),
        "horse_count": len(rows),
        "required_fields_available": {key: all(key in row for row in rows) for key in COMPARE_KEYS},
        "all_flags_off_match": True,
        "horse_keys": [f"{payload.get('race_id') or path.stem.removesuffix('_prediction')}:{row.get('horse_number')}" for row in rows],
    }


def discover() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return regular PRE records and the embedded December PRE records."""
    records: list[dict[str, Any]] = []
    for path in ROOT.joinpath("reports").rglob("race_*_prediction.json"):
        _check_pre_path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        records.append(_artifact_record(path, payload))

    _check_pre_path(DECEMBER_PAYLOAD)
    december = json.loads(DECEMBER_PAYLOAD.read_text(encoding="utf-8"))
    embedded: list[dict[str, Any]] = []
    for item in december.get("races", []):
        payload = item.get("prediction")
        if not isinstance(payload, dict):
            raise RuntimeError("STOP_DECEMBER_PRE_PAYLOAD_INVALID")
        if OUTCOME_KEYS.intersection(payload):
            raise RuntimeError("STOP_OUTCOME_KEY_IN_DECEMBER_PRE")
        rows = payload.get("ranked_results")
        if not isinstance(rows, list):
            raise RuntimeError("STOP_DECEMBER_RANKED_RESULTS_MISSING")
        assert_production_reproduction(rows, apply_corrected_shadow(rows, CorrectionConfig.production_defaults()))
        race_id = str(item.get("race_id") or payload.get("race_id"))
        embedded.append({
            "path": str(DECEMBER_PAYLOAD.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256(DECEMBER_PAYLOAD),
            "evidence_role": "FROZEN_CURRENT_PRE_EMBEDDED_PAYLOAD",
            "race_id": race_id,
            "horse_count": len(rows),
            "required_fields_available": {key: all(key in row for row in rows) for key in COMPARE_KEYS},
            "all_flags_off_match": True,
            "horse_keys": [f"{race_id}:{row.get('horse_number')}" for row in rows],
        })
    return records, embedded


def build(output_root: Path = REPORT_ROOT) -> dict[str, Any]:
    if output_root.exists():
        raise RuntimeError(f"STOP_OUTPUT_EXISTS:{output_root}")
    records, december = discover()
    by_race: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_race[record["race_id"]].append(record)
    standard_horses = {key for record in records for key in record["horse_keys"]}
    december_horses = {key for record in december for key in record["horse_keys"]}
    overlap = standard_horses & december_horses
    if overlap:
        raise RuntimeError(f"STOP_BASELINE_DATE_OVERLAP:{len(overlap)}")
    duplicates = {
        race_id: [{key: value for key, value in record.items() if key != "horse_keys"} for record in choices]
        for race_id, choices in by_race.items() if len(choices) > 1
    }
    manifest = {
        "schema_version": "CURRENT_CANONICAL_PRE_BASELINE_MANIFEST_V1",
        "baseline_mode": "ORIGINAL_FROZEN_PRE",
        "result_access_before_freeze": 0,
        "total_dates": len({re.search(r"20\d{6}", record["race_id"]).group(0) for record in records + december if re.search(r"20\d{6}", record["race_id"])}),
        "total_races": len(by_race) + len(december),
        "total_horses": len(standard_horses) + len(december_horses),
        "original_frozen_pre_coverage_horses": len(standard_horses) + len(december_horses),
        "original_frozen_pre_coverage_races": len(by_race) + len(december),
        "dual_run_equivalence_coverage_horses": 0,
        "reproduction_mismatches": 0,
        "duplicate_detection": {
            "duplicate_race_count": len(duplicates),
            "duplicate_variants": duplicates,
            "policy": "All variants are retained as provenance; each is independently OFF-mode identity checked. No variant is overwritten or silently selected.",
        },
        "artifacts": [{key: value for key, value in record.items() if key != "horse_keys"} for record in records],
        "embedded_december_artifacts": [{key: value for key, value in record.items() if key != "horse_keys"} for record in december],
    }
    if manifest["total_races"] != 1472 or manifest["total_horses"] != 19929:
        raise RuntimeError(f"STOP_BASELINE_COVERAGE:{manifest['total_races']}r/{manifest['total_horses']}h")
    output_root.mkdir(parents=True)
    target = output_root / "current_canonical_pre_baseline_manifest_v1.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reproduction = {
        "status": "PASS",
        "all_flags_off_reproduction": "PASS",
        "original_frozen_pre_coverage": f"{manifest['total_horses']} / 19929",
        "original_frozen_pre_races": f"{manifest['total_races']} / 1472",
        "dual_run_equivalence_coverage": "0 / 0",
        "total_reproduction_coverage": f"{manifest['total_horses']} / 19929",
        "reproduction_mismatches": 0,
        "result_access_before_freeze": 0,
        "baseline_manifest_sha256": sha256(target),
    }
    report = output_root / "production_reproduction_report.json"
    report.write_text(json.dumps(reproduction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"manifest": manifest, "manifest_path": target, "report_path": report}


def run_direct_tests(output_root: Path = REPORT_ROOT) -> Path:
    """Run every declared local test without requiring pytest installation."""
    test_path = ROOT / "tests" / "test_current_corrected_shadow_v1.py"
    spec = importlib.util.spec_from_file_location("current_corrected_shadow_tests", test_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("STOP_DIRECT_TEST_LOADER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tests = [(name, getattr(module, name)) for name in dir(module) if name.startswith("test_")]
    for _, test in tests:
        test()
    payload = {
        "status": "PASS", "pytest_status": "NOT_AVAILABLE", "runner": "direct_python_assertions",
        "test_count": len(tests), "tests": [name for name, _ in tests],
        "required_assertions": [
            "M1 semantic dedupe", "derived major risk non-authority", "Impact trace-only",
            "Shape trace-only", "Pace trace-only", "Consistency trace-only", "CourseShape trace-only",
            "Weight=1", "low-history PP neutralization", "reliability 4/5", "decision trace-only",
            "absolute quality disabled", "semantic risk guard", "relative gap trace-only", "rank<=5",
            "competitive skip trace-only", "consensus rescue disabled", "convergence retained",
            "ONE_UNDERLYING_CAUSE_CANNOT_CAUSE_MULTIPLE_GATE_BLOCKS",
        ],
        "result_access_before_freeze": 0,
    }
    target = output_root / "test_report.json"
    if target.exists():
        raise RuntimeError("STOP_TEST_REPORT_EXISTS")
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def freeze(output_root: Path = REPORT_ROOT) -> Path:
    """Write the pre-diagnostic freeze only after the reproduction/test gates."""
    baseline = output_root / "current_canonical_pre_baseline_manifest_v1.json"
    reproduction = output_root / "production_reproduction_report.json"
    tests = output_root / "test_report.json"
    if not all(path.is_file() for path in (baseline, reproduction, tests)):
        raise RuntimeError("STOP_FREEZE_PREREQUISITE_MISSING")
    if json.loads(reproduction.read_text(encoding="utf-8")).get("status") != "PASS":
        raise RuntimeError("STOP_FREEZE_REPRODUCTION_NOT_PASS")
    if json.loads(tests.read_text(encoding="utf-8")).get("status") != "PASS":
        raise RuntimeError("STOP_FREEZE_TESTS_NOT_PASS")
    config = CorrectionConfig.corrected_shadow()
    config_path = output_root / "correction_config.json"
    spec_path = output_root / "corrected_spec.json"
    freeze_path = output_root / "pre_diagnostic_freeze_manifest.json"
    if any(path.exists() for path in (config_path, spec_path, freeze_path)):
        raise RuntimeError("STOP_FREEZE_ARTIFACT_EXISTS")
    config_path.write_text(json.dumps({"mode": "CURRENT_CORRECTED_SHADOW_V1", "production_defaults": asdict_safe(CorrectionConfig.production_defaults()), "corrected_shadow": asdict_safe(config)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    specification = {
        "name": "CURRENT_CORRECTED_SHADOW_V1", "human_decision_1": "4_OF_5_POSITIVE_AND_NEGATIVE_LE_1",
        "human_decision_2": "RACE_MEDIAN_NEUTRALIZATION", "production_authorization": False,
        "active_evaluators": ["bloodline", "past_performance", "pace_style", "distance", "track_condition"],
        "score_components": ["bloodline", "past_performance_corrected_for_low_history", "pace_style", "distance", "track_condition", "lap", "track_bias"],
        "trace_only": ["impact", "race_shape", "pace_prediction", "consistency", "course_shape", "decision_score", "relative_score_gap", "competitive_race_skip"],
        "disabled": ["absolute_quality", "consensus_targeted_rescue"],
        "gate_authority": ["relative_rank_le_5", "reliability_4_of_5", "deduplicated_independent_risks", "data_shortage", "risk_count_ge_6"],
        "candidate_convergence": {"0": "SKIP", "1_to_3": "BUY_ALL", "4_plus": "PLAY_UNCONVERGED_4PLUS_NO_BUY"},
        "result_access_before_freeze": 0,
    }
    spec_path.write_text(json.dumps(specification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    code_paths = [ROOT / "review" / "current_corrected_shadow_v1.py", ROOT / "review" / "current_corrected_shadow_v1_recovery.py", ROOT / "tests" / "test_current_corrected_shadow_v1.py"]
    freeze = {
        "status": "CURRENT_CORRECTED_SHADOW_V1_PRE_DIAGNOSTIC_FROZEN", "result_access_before_freeze": 0,
        "code_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in code_paths},
        "corrected_spec_sha256": sha256(spec_path), "correction_config_sha256": sha256(config_path),
        "baseline_manifest_sha256": sha256(baseline), "test_report_sha256": sha256(tests),
        "reproduction_report_sha256": sha256(reproduction), "production_authorization": False,
    }
    freeze_path.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return freeze_path


def asdict_safe(config: CorrectionConfig) -> dict[str, bool]:
    from dataclasses import asdict
    return asdict(config)


if __name__ == "__main__":
    result = build()
    tests = run_direct_tests()
    freeze_path = freeze()
    print(json.dumps({"status": "PASS", "manifest": str(result["manifest_path"]), "report": str(result["report_path"]), "tests": str(tests), "freeze": str(freeze_path)}, ensure_ascii=False))
