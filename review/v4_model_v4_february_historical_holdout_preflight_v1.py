"""Fail-closed source-acquisition preparation for the V4 Model v4 February holdout.

This utility only freezes calendar candidates, checks source-file presence, and
uses the existing date-exclusivity validator.  It deliberately never opens a
Daily Result List, never invokes an adapter, and never runs prediction.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Permit direct execution from the repository root without relying on an
# externally configured PYTHONPATH.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from review.date_exclusivity_validator_v1 import collect_evidence_dates, validate


ARTIFACT_TYPE = "V4_MODEL_V4_FEBRUARY_HISTORICAL_HOLDOUT_PREFLIGHT_V1"
EVIDENCE_ROLE = "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_V4_MODEL_V4"
RESULT_ACCESS_COUNT = 0

# These are actual central-racing dates, fixed before any February source
# acquisition.  Venue lists reflect the official JRA daily calendar, including
# the February 8 partial cancellation and February 10 substitute programme.
CANDIDATES = [
    ("20260201", ["東京", "京都", "小倉"], "https://www.jra.go.jp/keiba/calendar2026/2026/2/0201.html", None),
    ("20260207", ["東京", "京都", "小倉"], "https://www.jra.go.jp/keiba/calendar2026/2026/2/0207.html", None),
    ("20260208", ["小倉"], "https://www.jra.go.jp/keiba/calendar2026/2026/2/0208.html", "東京・京都は開催中止"),
    ("20260210", ["東京", "京都"], "https://www.jra.go.jp/keiba/calendar2026/2026/2/0210.html", "代替開催"),
    ("20260214", ["東京", "京都", "小倉"], "https://www.jra.go.jp/keiba/calendar2026/2026/2/0214.html", None),
    ("20260215", ["東京", "京都", "小倉"], "https://www.jra.go.jp/keiba/calendar2026/2026/2/0215.html", None),
    ("20260221", ["東京", "阪神", "小倉"], "https://www.jra.go.jp/keiba/calendar2026/2026/2/0221.html", None),
    ("20260222", ["東京", "阪神", "小倉"], "https://www.jra.go.jp/keiba/calendar2026/2026/2/0222.html", None),
    ("20260228", ["中山", "阪神", "小倉"], "https://www.jra.go.jp/keiba/calendar2026/2026/2/0228.html", None),
]

EXPECTED = {
    "model": ("reports/ml_v4_buy_selection_model_v4/model.joblib", "58d3977d0f44eab325a2b384f0c17b66ddc276fff6370f6e05b7a1680642d74f"),
    "scaler": ("reports/ml_v4_buy_selection_model_v4/scaler.joblib", "3d18757f4991c21a4a645f92ca26361d88c030a4097696d2cc4a6c86d3767b90"),
    "dataset": ("reports/ml_v4_buy_selection_dataset_v4/dataset.csv", "b02bb4b59b5f297e60964f96050890dbf32a7ac3b5a9ef93424b9d612e3ae80a"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    output = root / "reports/v4_model_v4_february_historical_holdout/preflight"
    if output.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{output}")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    head = git_head(root)
    candidate_dates = [item[0] for item in CANDIDATES]

    # Freeze candidates before checking any February prediction input.
    output.mkdir(parents=True)
    preregistration = {
        "artifact_type": "FEBRUARY_CANDIDATE_DATE_PREREGISTRATION_V1",
        "evidence_role": EVIDENCE_ROLE,
        "candidate_dates": candidate_dates,
        "candidate_date_count": len(candidate_dates),
        "candidate_calendar": [
            {"date": date, "scheduled_venues": venues, "official_jra_calendar_url": url, "calendar_note": note}
            for date, venues, url, note in CANDIDATES
        ],
        "calendar_authority": "JRA official 2026 daily calendar pages; calendar/programme information only",
        "excluded_non_racing_date": {"date": "20260209", "reason": "京都開催中止。2月10日へ代替開催"},
        "acquisition_started": False,
        "result_access": False,
        "timestamp_utc": now,
        "git_head": head,
        "result_data_access_count": RESULT_ACCESS_COUNT,
        "rule": "All actual JRA central-racing dates in February 2026 are frozen before source acquisition; no result data informed the list.",
    }
    write_json(output / "february_candidate_date_preregistration.json", preregistration)

    frozen_checks = {}
    for label, (relative, expected) in EXPECTED.items():
        path = root / relative
        observed = sha256(path) if path.is_file() else None
        frozen_checks[label] = {"path": relative, "expected_sha256": expected, "observed_sha256": observed, "status": "PASS" if observed == expected else "FAIL"}
    if any(check["status"] != "PASS" for check in frozen_checks.values()):
        raise RuntimeError("FROZEN_V4_AUTHORITY_HASH_MISMATCH")

    source_root = root / "data/raw/prediction_input"
    result_root = root / "data/raw/target/daily_result_list"
    source_inventory = []
    for date in candidate_dates:
        suffix = date[2:]
        for kind, column_count in (("DG", 11), ("DE", 33), ("DS", 50)):
            path = source_root / f"{kind}{suffix}.CSV"
            source_inventory.append({
                "date": date,
                "source_type": kind,
                "expected_path": rel(root, path),
                "expected_column_count": column_count,
                "status": "FOUND_NOT_READ" if path.is_file() else "MISSING",
                "sha256": None,
                "byte_size": None,
                "content_read": False,
            })
    result_names = sorted(path.name for path in result_root.glob("*202602*.csv")) if result_root.is_dir() else []
    found_sources = [item for item in source_inventory if item["status"] == "FOUND_NOT_READ"]
    missing_sources = [item for item in source_inventory if item["status"] == "MISSING"]
    untouched = {
        "artifact_type": "FEBRUARY_UNTOUCHED_STATUS_BEFORE_V1",
        "checked_at_utc": now,
        "prediction_source_existing_file_count": len(found_sources),
        "prediction_source_expected_file_count": len(source_inventory),
        "prediction_source_paths_checked_by_existence_only": [item["expected_path"] for item in source_inventory],
        "february_result_file_name_count": len(result_names),
        "february_result_file_names": result_names,
        "result_contents_read": False,
        "status": "PASS_UNTOUCHED" if not found_sources and not result_names else "FAIL_NOT_UNTOUCHED",
        "result_data_access_count": RESULT_ACCESS_COUNT,
    }
    write_json(output / "untouched_status_before.json", untouched)

    exclusivity = validate(candidate_dates, collect_evidence_dates(root))
    exclusivity.update({
        "artifact_type": "DATE_EXCLUSIVITY_PRE_ACQUISITION_V1",
        "evidence_role": EVIDENCE_ROLE,
        "checked_at_utc": now,
        "git_head": head,
        "result_data_access_count": RESULT_ACCESS_COUNT,
        "scope_note": "Existing validator authority scope used unchanged; no raw inputs or results were read.",
    })
    write_json(output / "date_exclusivity_pre_acquisition.json", exclusivity)

    acquisition_status = "PENDING_HUMAN_SOURCE_ACQUISITION" if missing_sources else "SOURCES_PRESENT_PRECHECK_REQUIRED"
    write_json(output / "prediction_source_inventory.json", {
        "artifact_type": "FEBRUARY_PREDICTION_SOURCE_INVENTORY_V1",
        "checked_at_utc": now,
        "sources": source_inventory,
        "found_count": len(found_sources),
        "missing_count": len(missing_sources),
        "status": acquisition_status,
        "result_data_access_count": RESULT_ACCESS_COUNT,
    })
    integrity = {
        "artifact_type": "FEBRUARY_DG_DE_DS_INTEGRITY_V1",
        "status": "NOT_RUN_SOURCES_MISSING" if missing_sources else "NOT_RUN_SEPARATE_ADAPTER_PREFLIGHT_REQUIRED",
        "reason": "DG/DE/DS contents were not read during acquisition preparation." if missing_sources else "Sources exist but this acquisition-preparation run does not parse them.",
        "expected_dg_columns": 11,
        "expected_de_columns": 33,
        "expected_ds_columns": 50,
        "adapter_execution_count": 0,
        "result_data_access_count": RESULT_ACCESS_COUNT,
    }
    write_json(output / "dg_de_ds_integrity.json", integrity)
    source_preflight = {
        "artifact_type": "FEBRUARY_SOURCE_PREFLIGHT_V1",
        "status": "PENDING_HUMAN_SOURCE_ACQUISITION" if missing_sources else "PENDING_PREDICTION_SIDE_VALIDATION",
        "source_acquisition_status": acquisition_status,
        "formal_pre_freeze_ready": "NO",
        "prediction_execution_count": 0,
        "current_ai_execution_count": 0,
        "cf_execution_count": 0,
        "v4_model_v4_inference_count": 0,
        "result_data_access_count": RESULT_ACCESS_COUNT,
        "reason": "All 27 DG/DE/DS source files must be available and pass content validation before PRE freeze." if missing_sources else "Content validation has not yet been run.",
    }
    write_json(output / "source_preflight.json", source_preflight)
    write_json(output / "exclusion_inventory.json", {
        "artifact_type": "FEBRUARY_EXCLUSION_INVENTORY_V1",
        "formal_exclusions": ["新馬", "障害"],
        "excluded_races": [],
        "status": "NOT_EVALUATED_SOURCES_MISSING" if missing_sources else "DEFERRED_UNTIL_SOURCE_PREFLIGHT",
        "rule": "No subjective/date-specific exclusions. Race-level eligibility is determined only after source integrity validation.",
        "result_data_access_count": RESULT_ACCESS_COUNT,
    })
    write_json(output / "evidence_boundary.json", {
        "artifact_type": "FEBRUARY_HOLDOUT_EVIDENCE_BOUNDARY_V1",
        "evidence_role": EVIDENCE_ROLE,
        "not_prospective_evidence": True,
        "candidate_advancement_gate": "Historical FAIL rejects V4 Model v4; Historical PASS only permits later prospective governance review.",
        "forbidden_this_phase": ["result access", "actual_top3", "finish", "payout", "prediction", "POST evaluation", "training", "model selection"],
        "result_data_access_count": RESULT_ACCESS_COUNT,
    })
    safety = {
        "artifact_type": "FEBRUARY_HOLDOUT_PREFLIGHT_SAFETY_V1",
        "status": "PASS",
        "production_change_count": 0,
        "current_ai_change_count": 0,
        "buy_gate_change_count": 0,
        "cf_change_count": 0,
        "v4_model_v4_change_count": 0,
        "dataset_v4_change_count": 0,
        "result_data_access_count": RESULT_ACCESS_COUNT,
        "prediction_execution_count": 0,
        "adapter_execution_count": 0,
        "git_head": head,
        "frozen_authority_hashes": frozen_checks,
    }
    write_json(output / "safety.json", safety)
    report = """# V4 Model v4 — February 2026 Temporally Reversed External Holdout\n\n## Phase A-0 status\n\n- Evidence role: `TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_V4_MODEL_V4`\n- Candidate dates frozen before acquisition: 9\n- Date exclusivity: `{exclusivity}`\n- February result-data access: `0`\n- Prediction execution: `0`\n- Source acquisition status: `{source_status}`\n- Formal PRE-freeze readiness: `NO`\n\n## Frozen candidate dates\n\n{dates}\n\n## Required next input\n\nEach listed date requires its unmodified TARGET `DG`, `DE`, and `DS` CSV in `data/raw/prediction_input/`. No result file is authorized at this phase. Once all sources exist, run content-level source integrity validation; do not infer, fill, or substitute absent source data.\n\n## Boundary\n\nThis is a temporally reversed external holdout for V4 Model v4, not prospective evidence. This run did not read February result contents or execute Current AI, CF, Model v4 inference, P50, or POST evaluation.\n""".format(
        exclusivity=exclusivity["status"],
        source_status=acquisition_status,
        dates="\n".join(f"- `{date}`: {', '.join(venues)}" for date, venues, _, _ in CANDIDATES),
    )
    (output / "report.md").write_text(report, encoding="utf-8")
    indexed = {path.name: sha256(path) for path in sorted(output.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}
    write_json(output / "artifact_hashes.json", {
        "artifact_type": "FEBRUARY_HOLDOUT_PREFLIGHT_HASH_INDEX_V1",
        "indexed_artifacts": indexed,
        "self_hash_excluded": True,
        "status": "PASS",
    })
    print("FEBRUARY_HOLDOUT_SOURCE_ACQUISITION_PREPARATION_COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
