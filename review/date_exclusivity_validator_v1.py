"""Read-only date-exclusivity validation for historical holdout preregistrations.

This module deliberately derives used dates from frozen provenance artifacts.  It
does not read raw race/result data and does not run prediction or scoring.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


VALIDATOR_VERSION = "DATE_EXCLUSIVITY_VALIDATOR_V2"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _dates(values: Any, source: Path) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(v, str) or len(v) != 8 or not v.isdigit() for v in values):
        raise ValueError(f"DATE_LIST_INVALID:{source}")
    return sorted(set(values))


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _record(category: str, role: str, dates: list[str], path: Path, root: Path) -> dict[str, Any]:
    return {"category": category, "evidence_role": role, "dates": dates, "authority_path": _relative(root, path)}


def collect_evidence_dates(root: Path) -> list[dict[str, Any]]:
    """Return auditable date records from existing authorities only."""
    records: list[dict[str, Any]] = []

    inventory_path = root / "reports/ml_v4_buy_selection_dataset_v2/source_date_inventory.json"
    inventory = _read_json(inventory_path)
    records.append(_record("development_training", "TRAIN_DEVELOPMENT_V1", _dates(inventory["v1_dates"], inventory_path), inventory_path, root))

    may_path = root / "reports/may_2026_multi_system_oos_v1/pre_retry_v5/source_manifest.json"
    may_sources = _read_json(may_path).get("sources")
    if not isinstance(may_sources, list):
        raise ValueError(f"MAY_SOURCE_MANIFEST_INVALID:{may_path}")
    records.append(_record("retrospective_external_holdout", "RETROSPECTIVE_EXTERNAL_HOLDOUT", _dates([item.get("date") for item in may_sources if isinstance(item, dict)], may_path), may_path, root))

    april_prediction_root = root / "reports/april_2026_retrospective_external_holdout_v2/pre_execution_full_8date_v1/prediction"
    if not april_prediction_root.is_dir():
        raise ValueError(f"APRIL_PREDICTION_ROOT_MISSING:{april_prediction_root}")
    april_dates = sorted(path.name for path in april_prediction_root.iterdir() if path.is_dir() and len(path.name) == 8 and path.name.isdigit())
    records.append(_record("retrospective_external_holdout", "RETROSPECTIVE_EXTERNAL_HOLDOUT", _dates(april_dates, april_prediction_root), april_prediction_root, root))

    protocol_path = root / "reports/shadow_cf_top3_rank_anchored_v1/protocol.json"
    protocol = _read_json(protocol_path)
    records.append(_record("prospective_shadow", "PROSPECTIVE_SHADOW_PRE_PROTOCOL_CONTEXT", _dates(protocol["pre_protocol_context_dates"], protocol_path), protocol_path, root))

    for path in sorted((root / "reports").glob("prospective_three_system_*/cf_selection_manifest.json")):
        payload = _read_json(path)
        role = payload.get("evidence_role")
        date = payload.get("date")
        if role == "FORMAL_PROSPECTIVE_SHADOW":
            records.append(_record("prospective_shadow", role, _dates([date], path), path, root))
    for path in sorted((root / "reports").glob("prospective_three_system_*/v4_model_v3_reference_selection_manifest.json")):
        payload = _read_json(path)
        role = payload.get("evidence_role")
        date = payload.get("date")
        if role == "REFERENCE_SHADOW_ONLY_PENDING_HISTORICAL_GATE":
            records.append(_record("reference_shadow_only", role, _dates([date], path), path, root))

    # Completed 2026-08-30 Formal Prospective evidence is registered through
    # its own completed-POST authorities.  These remain distinct evidence
    # families: V4-v3 is never merged with CF formal evidence.
    v4_post = root / "reports/v4_model_v3_formal_prospective/20260830_post/evidence_ledger_update.json"
    if v4_post.is_file():
        payload = _read_json(v4_post)
        role = payload.get("evidence_role")
        dates = _dates(payload.get("eligible_dates"), v4_post)
        if role != "FORMAL_PROSPECTIVE_SHADOW_V4_MODEL_V3" or "20260830" not in dates:
            raise ValueError(f"V4_FORMAL_PROSPECTIVE_20260830_AUTHORITY_INVALID:{v4_post}")
        records.append(_record("formal_prospective_v4", role, ["20260830"], v4_post, root))

    cf_post = root / "reports/shadow_cf_top3_rank_anchored_v1/formal_post_20260830/formal_status.json"
    if cf_post.is_file():
        payload = _read_json(cf_post)
        dates = _dates(payload.get("completed_dates"), cf_post)
        if "20260830" not in dates:
            raise ValueError(f"CF_FORMAL_PROSPECTIVE_20260830_AUTHORITY_INVALID:{cf_post}")
        records.append(_record("formal_prospective_cf", "FORMAL_PROSPECTIVE_SHADOW_CF_TOP3_RANK_ANCHORED", ["20260830"], cf_post, root))
    return records


def validate(candidate_dates: list[str], records: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_dates = _dates(candidate_dates, Path("candidate_dates"))
    used_by_date: dict[str, list[dict[str, str]]] = {}
    categories: dict[str, set[str]] = {}
    for record in records:
        categories.setdefault(record["category"], set()).update(record["dates"])
        for date in record["dates"]:
            used_by_date.setdefault(date, []).append({"category": record["category"], "evidence_role": record["evidence_role"], "authority_path": record["authority_path"]})
    overlap = sorted(set(candidate_dates).intersection(used_by_date))
    return {
        "validator_version": VALIDATOR_VERSION,
        "candidate_dates": candidate_dates,
        "candidate_date_count": len(candidate_dates),
        "evidence_records": records,
        "used_target_date_sets": {key: sorted(value) for key, value in sorted(categories.items())},
        "used_dates": sorted(used_by_date),
        "used_date_count": len(used_by_date),
        "overlap_count": len(overlap),
        "overlap_dates": overlap,
        "overlap_evidence": {date: used_by_date[date] for date in overlap},
        "status": "PASS" if not overlap else "FAIL_DATE_EXCLUSIVITY_CONFLICT",
        "rule": "Any candidate overlap with an authoritative prior training, retrospective external holdout, prospective shadow, or reference-shadow date fails exclusivity.",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git_head(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def write_validation(root: Path, candidate_path: Path, output_root: Path) -> dict[str, Any]:
    candidate_path = candidate_path.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{output_root}")
    candidate = _read_json(candidate_path)
    result = validate(candidate.get("candidate_dates"), collect_evidence_dates(root))
    result.update({"artifact_type": "DATE_EXCLUSIVITY_VALIDATION_V2", "candidate_preregistration_path": _relative(root, candidate_path), "git_head": _git_head(root)})
    output_root.mkdir(parents=True)
    validation_path = output_root / "date_exclusivity_validation_v2.json"
    _write_json(validation_path, result)
    _write_json(output_root / "summary.json", {"status": result["status"], "overlap_count": result["overlap_count"], "overlap_dates": result["overlap_dates"], "prospective_shadow_dates": result["used_target_date_sets"].get("prospective_shadow", []), "git_head": result["git_head"]})
    _write_json(output_root / "safety.json", {"result_data_access_count": 0, "prediction_execution_count": 0, "production_change_count": 0, "frozen_artifact_overwrite_count": 0, "status": "PASS"})
    (output_root / "report.md").write_text("# Date Exclusivity Validator Scope Fix\n\n" + f"- Status: `{result['status']}`\n- Overlap count: `{result['overlap_count']}`\n- Prospective shadow dates: `{', '.join(result['used_target_date_sets'].get('prospective_shadow', []))}`\n", encoding="utf-8")
    hashes = {path.name: _sha256(path) for path in sorted(output_root.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}
    _write_json(output_root / "artifact_hashes.json", {"artifact_type": "DATE_EXCLUSIVITY_VALIDATOR_V2_HASH_INDEX", "hashes": hashes, "self_hash_excluded": True})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-preregistration", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = write_validation(root, args.candidate_preregistration, args.output_root)
    print(result["status"])
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
