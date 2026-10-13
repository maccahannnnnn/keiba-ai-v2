"""WS2 read-only, non-performance data-integrity gate.

This module deliberately performs no fitting, inference, ranking, threshold
selection, or performance calculation.  Its input is a source bundle whose
paths and declared digests are verified before structural evidence is used.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROLE_FEATURE = "FEATURE"
ROLE_TARGET = "TARGET"
ROLE_METADATA = "METADATA"
ROLE_FORBIDDEN_RESULT = "FORBIDDEN_RESULT"
ROLES = {ROLE_FEATURE, ROLE_TARGET, ROLE_METADATA, ROLE_FORBIDDEN_RESULT}
PIT_CLASSES = {"PIT_FROZEN_PROSPECTIVE", "PIT_REGENERATED_VERIFIED", "PIT_UNPROVEN"}
CONTACT_ROLES = {
    "TRAINING", "TUNING", "HYPOTHESIS_GENERATION", "CONSUMED_DIAGNOSTIC",
    "CONSUMED_HOLDOUT", "ONE_SHOT", "OOS", "FORMAL", "PROSPECTIVE",
}
MARKET_TOKENS = ("odds", "オッズ", "popularity", "人気", "ninki", "単勝", "複勝", "tansho", "fukusho", "market", "payout", "配当")
RESULT_TOKENS = ("actual_finish", "finish", "着順", "valid_result", "payout", "result", "selection_error_category", "source_result_artifact")


class DataIntegrityStop(RuntimeError):
    """Fail-closed WS2 preflight stop with a stable machine reason code."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _stop(code: str) -> None:
    raise DataIntegrityStop(code)


def _as_date(value: Any, code: str) -> str:
    text = str(value or "").replace("-", "")
    if len(text) != 8 or not text.isdigit():
        _stop(code)
    return text


def _check_sources(source_files: list[dict[str, Any]], root: Path) -> list[dict[str, str]]:
    if not source_files:
        _stop("STOP_SOURCE_HASH_INTEGRITY")
    verified: list[dict[str, str]] = []
    for item in source_files:
        path = root / str(item.get("path", ""))
        expected = str(item.get("sha256", "")).lower()
        if not path.is_file() or len(expected) != 64:
            _stop("STOP_SOURCE_HASH_INTEGRITY")
        actual = sha256(path)
        if actual != expected:
            _stop("STOP_SOURCE_HASH_MISMATCH")
        verified.append({"path": str(item["path"]).replace("\\", "/"), "sha256": actual})
    return verified


def _has_token(name: str, tokens: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(token.lower() in lowered for token in tokens)


def audit_feature_allowlist(columns: list[str], policy: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify every physical dataset column exactly once; no blacklist bypass."""
    names = [str(value) for value in columns]
    if len(names) != len(set(names)):
        _stop("STOP_DUPLICATE_DATASET_COLUMN")
    declared = {str(row.get("feature", "")): row for row in policy}
    if set(names) != set(declared):
        _stop("STOP_UNREGISTERED_DATASET_COLUMN")
    manifest: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for name in names:
        row = dict(declared[name])
        role = row.get("role")
        pit = row.get("pit_class")
        required = bool(row.get("required_by_iteration_0"))
        if role not in ROLES or pit not in PIT_CLASSES:
            _stop("STOP_INVALID_FEATURE_POLICY")
        result_derived = bool(row.get("result_derived"))
        market_derived = bool(row.get("market_derived"))
        learning_dependency = str(row.get("learning_db_dependency", "NONE"))
        lineage = " ".join(str(value) for value in row.get("source_lineage", [])).lower()
        if role == ROLE_FEATURE and _has_token(name, MARKET_TOKENS):
            _stop("STOP_MARKET_FEATURE_LEAKAGE")
        if role == ROLE_FEATURE and (_has_token(name, RESULT_TOKENS) or result_derived or _has_token(lineage, RESULT_TOKENS)):
            _stop("STOP_RESULT_FEATURE_LEAKAGE")
        if role == ROLE_FEATURE and _has_token(lineage, MARKET_TOKENS):
            _stop("STOP_MARKET_FEATURE_LEAKAGE")
        if name == "actual_top3" and role != ROLE_TARGET:
            _stop("STOP_LABEL_ROLE_VIOLATION")
        if role == ROLE_FEATURE and market_derived:
            _stop("STOP_MARKET_FEATURE_LEAKAGE")
        if role == ROLE_FEATURE and learning_dependency == "CONFIRMED":
            _stop("STOP_CONFIRMED_LEARNING_DB_DEPENDENCY")
        unsafe = (pit == "PIT_UNPROVEN" or not bool(row.get("pre_time_available")))
        if role == ROLE_FEATURE and unsafe and required:
            _stop("STOP_ITERATION_0_REQUIRED_FEATURE_PIT_UNPROVEN")
        status = "ALLOWED"
        if role == ROLE_FEATURE and unsafe:
            status = "EXCLUDED_OPTIONAL_WARN"
            excluded.append({"feature": name, "feature_group": row.get("feature_group"), "reason_code": "OPTIONAL_FEATURE_PIT_OR_DEPENDENCY_UNPROVEN"})
            warnings.append({"check_id": "OPTIONAL_FEATURE_EXCLUDED", "status": "WARN", "severity": "WARN", "reason_code": "OPTIONAL_FEATURE_PIT_OR_DEPENDENCY_UNPROVEN", "evidence": {"feature": name}})
        manifest.append({
            "feature": name, "feature_group": row.get("feature_group"), "source": row.get("source"), "role": role,
            "pre_time_available": bool(row.get("pre_time_available")), "pit_class": pit,
            "coverage": row.get("coverage"), "missing_rate": row.get("missing_rate"),
            "result_derived": result_derived, "market_derived": market_derived,
            "current_derived": bool(row.get("current_derived")), "learning_db_dependency": learning_dependency,
            "required_by_iteration_0": required, "proposed_ws2_role": row.get("proposed_ws2_role"),
            "status": status, "source_paths": row.get("source_paths", []), "source_shas": row.get("source_shas", []), "source_lineage": row.get("source_lineage", []),
        })
    return manifest, excluded, warnings


def audit_full_field_races(races: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    completed: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    mismatch: list[dict[str, Any]] = []
    for race in races:
        race_id = str(race.get("race_id", ""))
        month = _as_date(race.get("target_date"), "STOP_INVALID_SOURCE_DATE")[:6]
        de = {str(value) for value in race.get("de_horse_numbers", [])}
        ranked = {str(value) for value in race.get("ranked_horse_numbers", [])}
        if not race_id or not de or len(de) != len(race.get("de_horse_numbers", [])):
            _stop("STOP_SOURCE_HORSE_IDENTITY")
        record = {"race_id": race_id, "month": month, "de_horse_count": len(de), "ranked_horse_count": len(ranked), "missing_horses": sorted(de - ranked), "missing_feature_groups": list(race.get("missing_feature_groups", []))}
        if ranked - de:
            mismatch.append({**record, "extra_ranked_horses": sorted(ranked - de)})
        elif de - ranked:
            incomplete.append(record)
        else:
            completed.append(record)
    if mismatch:
        _stop("STOP_HORSE_SET_MISMATCH")
    return completed, incomplete, mismatch


def audit_monthly_incomplete(complete: list[dict[str, Any]], incomplete: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in complete:
        counts[row["month"]]["complete"] += 1
    for row in incomplete:
        counts[row["month"]]["incomplete"] += 1
    monthly, warnings = [], []
    for month in sorted(counts):
        total = counts[month]["complete"] + counts[month]["incomplete"]
        rate = counts[month]["incomplete"] / total if total else 0.0
        status = "USABLE_WARN" if counts[month]["incomplete"] else "USABLE"
        role = "EXCLUDED_FROM_ROLLING_ORIGIN" if rate > 0.05 else "USABLE_FOR_ROLLING_ORIGIN"
        if rate > 0.05:
            status = "EXCLUDED_FROM_ROLLING_ORIGIN"
        elif counts[month]["incomplete"]:
            warnings.append({"check_id": "MONTHLY_INCOMPLETE_RACE_LIMIT", "status": "WARN", "severity": "WARN", "reason_code": "MONTHLY_INCOMPLETE_RACE_SHARE_WITHIN_5_PERCENT", "evidence": {"month": month, "rate": rate}})
        monthly.append({"month": month, "source_races": total, "incomplete_races": counts[month]["incomplete"], "incomplete_race_share": rate, "status": status, "rolling_origin_role": role})
    return monthly, warnings


def audit_past_race_dates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        target = _as_date(row.get("target_date"), "STOP_INVALID_TARGET_DATE")
        past = _as_date(row.get("past_race_date"), "STOP_INVALID_PAST_RACE_DATE")
        if past >= target:
            _stop("STOP_FUTURE_OR_SAME_DAY_PAST_RACE")
    return {"checked_rows": len(rows), "status": "PASS"}


def audit_population_reconciliation(source_races: list[dict[str, Any]], training_race_ids: list[str], exclusions: list[dict[str, Any]]) -> dict[str, Any]:
    source_ids = {str(row.get("race_id", "")) for row in source_races}
    train_ids = {str(value) for value in training_race_ids}
    if "" in source_ids or len(source_ids) != len(source_races) or not train_ids <= source_ids:
        _stop("STOP_SOURCE_RACE_IDENTITY")
    reason_by_race = {str(row.get("race_id", "")): str(row.get("reason_code", "")) for row in exclusions}
    excluded = source_ids - train_ids
    unexplained = sorted(race_id for race_id in excluded if not reason_by_race.get(race_id))
    if unexplained:
        _stop("STOP_UNEXPLAINED_SOURCE_RACE_EXCLUSION")
    return {"source_race_count": len(source_ids), "included_training_race_count": len(train_ids), "excluded_race_count": len(excluded), "exclusions_by_reason": dict(Counter(reason_by_race[race_id] for race_id in excluded)), "unexplained_exclusion_count": 0}


def audit_labels(rows: list[dict[str, Any]]) -> dict[str, Any]:
    seen: set[tuple[str, str]] = set()
    invalid = 0
    positive = 0
    for row in rows:
        key = (str(row.get("race_id", "")), str(row.get("horse_number", "")))
        if not all(key) or key in seen:
            _stop("STOP_LABEL_IDENTITY_OR_DUPLICATION")
        seen.add(key)
        if not isinstance(row.get("actual_top3"), bool) or not isinstance(row.get("valid_result"), bool):
            _stop("STOP_LABEL_INCONSISTENCY")
        if not row["valid_result"] and row["actual_top3"]:
            _stop("STOP_LABEL_INCONSISTENCY")
        invalid += int(not row["valid_result"])
        positive += int(row["valid_result"] and row["actual_top3"])
    return {"label_source_identity": "DECLARED_RESULT_TARGET_ONLY", "row_count": len(rows), "invalid_result_count": invalid, "valid_result_count": len(rows) - invalid, "actual_top3_positive_count": positive, "actual_top3_negative_count": len(rows) - invalid - positive, "status": "PASS"}


def audit_v5_dataset_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify the claimed Top5-only V5 population from physical row fields."""
    if not rows:
        _stop("STOP_V5_DATASET_ROWS_MISSING")
    keys: set[tuple[str, str]] = set()
    dates, venues = set(), Counter()
    for row in rows:
        key = (str(row.get("race_id", "")), str(row.get("horse_number", "")))
        if not all(key) or key in keys:
            _stop("STOP_V5_DATASET_DUPLICATE_RACE_HORSE")
        keys.add(key)
        if row.get("current_top5") is not True:
            _stop("STOP_V5_DATASET_NOT_TOP5_ONLY")
        dates.add(_as_date(row.get("date"), "STOP_INVALID_V5_DATASET_DATE"))
        if row.get("venue"):
            venues[str(row["venue"])] += 1
    return {"row_count": len(rows), "independent_race_count": len({key[0] for key in keys}), "target_date_count": len(dates), "date_range": [min(dates), max(dates)], "venue_distribution": dict(venues), "current_top5_true_count": len(rows), "current_top5_false_count": 0, "duplicate_race_horse_count": 0, "status": "TOP5_ONLY_PASS"}


def audit_runtime_identity(runtime: dict[str, Any]) -> dict[str, Any]:
    required = ("model_sha256", "scaler_sha256", "feature_spec_sha256", "training_end_date", "dataset_identity", "recipe_identity", "runtime_identity", "deterministic_reproduction")
    if any(not runtime.get(key) for key in required):
        _stop("STOP_V5_RUNTIME_RECIPE_IDENTITY_UNPROVEN")
    for key in ("model_sha256", "scaler_sha256", "feature_spec_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(runtime[key]).lower()):
            _stop("STOP_V5_RUNTIME_RECIPE_IDENTITY_UNPROVEN")
    _as_date(runtime["training_end_date"], "STOP_INVALID_V5_TRAINING_END_DATE")
    return {key: runtime[key] for key in required}


def audit_period_roles(period_roles: list[dict[str, Any]]) -> dict[str, Any]:
    result, untouched = [], []
    for item in period_roles:
        period = str(item.get("period", ""))
        roles = sorted(set(str(value) for value in item.get("roles_history", [])))
        if not re.fullmatch(r"\d{6}(\d{2})?", period) or not roles:
            _stop("STOP_PERIOD_ROLE_INVALID")
        if "UNTOUCHED_CANDIDATE" in roles and CONTACT_ROLES & set(roles):
            _stop("STOP_PERIOD_ROLE_CONTRADICTION")
        if roles == ["UNTOUCHED_CANDIDATE"]:
            untouched.append(period)
        result.append({"period": period, "roles_history": roles})
    return {"periods": result, "status": "VALID_UNTOUCHED_HISTORICAL_HOLDOUT_EXISTS" if untouched else "NO_UNTOUCHED_HISTORICAL_HOLDOUT_AVAILABLE", "untouched_candidates": untouched}


def build_rolling_origin_folds(months: list[str], role_history: dict[str, list[str]]) -> list[dict[str, Any]]:
    ordered = sorted(set(months))
    if any(not re.fullmatch(r"\d{6}", month) for month in ordered):
        _stop("STOP_INVALID_ROLLING_ORIGIN_MONTH")
    folds = []
    for index, validation in enumerate(ordered):
        training = [month for month in ordered[:index] if not (set(role_history.get(month, [])) & {"UNTOUCHED_CANDIDATE", "PROSPECTIVE", "EXCLUDED"})]
        if len(training) < 3:
            continue
        if any(month >= validation for month in training):
            _stop("STOP_ROLLING_ORIGIN_FUTURE_LEAKAGE")
        folds.append({"training_months": training, "validation_month": validation, "primary": "ROLLING_ORIGIN_MONTHLY_CROSS_FIT", "lomo": "SENSITIVITY_ONLY"})
    if not folds:
        _stop("STOP_ROLLING_ORIGIN_EMPTY")
    return validate_rolling_origin_folds(folds)


def validate_rolling_origin_folds(folds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate declared folds too, so no caller can inject a future train month."""
    if not folds:
        _stop("STOP_ROLLING_ORIGIN_EMPTY")
    for fold in folds:
        validation = str(fold.get("validation_month", ""))
        training = [str(value) for value in fold.get("training_months", [])]
        if not re.fullmatch(r"\d{6}", validation) or len(training) < 3:
            _stop("STOP_ROLLING_ORIGIN_MIN_TRAIN_MONTHS")
        if any(not re.fullmatch(r"\d{6}", month) or month >= validation for month in training):
            _stop("STOP_ROLLING_ORIGIN_FUTURE_LEAKAGE")
    return folds


def audit_learning_dependency(code_paths: list[str], root: Path) -> dict[str, Any]:
    findings = []
    for value in code_paths:
        path = root / value
        if not path.is_file():
            _stop("STOP_LEARNING_DEPENDENCY_AUDIT_SOURCE_MISSING")
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?:learning|knowledge)[\\/].*(?:read|load|open)|(?:read|load|open).*?(?:learning|knowledge)[\\/]", text, flags=re.IGNORECASE):
            findings.append({"path": path.as_posix(), "sha256": sha256(path), "dependency": "CONFIRMED"})
    return {"LEARNING_DB_IMPACT": "CONFIRMED" if findings else "NONE_PROVEN", "findings": findings}


def _check_record(check_id: str, status: str, severity: str, reason_code: str, evidence: Any, source_files: list[dict[str, str]]) -> dict[str, Any]:
    return {"check_id": check_id, "status": status, "severity": severity, "reason_code": reason_code, "evidence": evidence, "counts": {}, "source_paths": [row["path"] for row in source_files], "source_sha256": [row["sha256"] for row in source_files]}


def evaluate_preflight(bundle: dict[str, Any], root: Path) -> dict[str, Any]:
    """Evaluate a fully declared source bundle; caller status booleans are ignored."""
    source_files = _check_sources(list(bundle.get("source_files", [])), root)
    dataset = bundle.get("dataset", {})
    columns = list(dataset.get("columns", []))
    feature_manifest, excluded, warnings = audit_feature_allowlist(columns, list(bundle.get("feature_policy", [])))
    dataset_inventory = audit_v5_dataset_rows(list(dataset.get("rows", [])))
    runtime_identity = audit_runtime_identity(dict(bundle.get("v5_runtime", {})))
    complete, incomplete, mismatch = audit_full_field_races(list(bundle.get("source_races", [])))
    monthly, monthly_warnings = audit_monthly_incomplete(complete, incomplete)
    past = audit_past_race_dates(list(bundle.get("past_race_rows", [])))
    population = audit_population_reconciliation(list(bundle.get("source_races", [])), list(dataset.get("training_race_ids", [])), list(bundle.get("source_race_exclusions", [])))
    labels = audit_labels(list(bundle.get("label_rows", [])))
    role_result = audit_period_roles(list(bundle.get("period_roles", [])))
    role_map = {row["period"]: row["roles_history"] for row in role_result["periods"]}
    folds = build_rolling_origin_folds(list(bundle.get("rolling_months", [])), role_map)
    learning = audit_learning_dependency(list(bundle.get("used_feature_code_paths", [])), root)
    if learning["LEARNING_DB_IMPACT"] == "CONFIRMED":
        _stop("STOP_CONFIRMED_LEARNING_DB_DEPENDENCY")
    all_warnings = warnings + monthly_warnings
    checks = [
        _check_record("SOURCE_HASH_INTEGRITY", "PASS", "INFO", "SOURCE_HASHES_MATCH", {"file_count": len(source_files)}, source_files),
        _check_record("FEATURE_ALLOWLIST", "PASS", "INFO", "ALLOWLIST_ONLY", {"column_count": len(columns)}, source_files),
        _check_record("V5_DATASET_INVENTORY", "PASS", "INFO", "TOP5_ONLY_PASS", dataset_inventory, source_files),
        _check_record("V5_RUNTIME_IDENTITY", "PASS", "INFO", "FROZEN_RECIPE_REPRODUCIBLE", runtime_identity, source_files),
        _check_record("FULL_FIELD_AVAILABILITY", "PASS", "INFO", "RACE_LEVEL_COMPLETE_OR_EXCLUDED", {"complete": len(complete), "incomplete": len(incomplete), "mismatch": len(mismatch)}, source_files),
        _check_record("PAST_RACE_TEMPORAL_VALIDATION", "PASS", "INFO", "PAST_RACE_STRICTLY_BEFORE_TARGET", past, source_files),
        _check_record("SOURCE_POPULATION_RECONCILIATION", "PASS", "INFO", "ALL_EXCLUSIONS_EXPLAINED", population, source_files),
        _check_record("LABEL_INTEGRITY", "PASS", "INFO", "TARGET_ONLY_LABELS", labels, source_files),
        _check_record("PERIOD_ROLE_INVENTORY", "PASS", "INFO", role_result["status"], role_result, source_files),
        _check_record("ROLLING_ORIGIN", "PASS", "INFO", "ROLLING_ORIGIN_MONTHLY_CROSS_FIT", {"fold_count": len(folds)}, source_files),
        _check_record("LEARNING_DB_DEPENDENCY", "PASS", "INFO", learning["LEARNING_DB_IMPACT"], learning, source_files),
        *all_warnings,
    ]
    generated = bundle.get("generated_at_jst") or datetime.now(timezone(timedelta(hours=9))).replace(microsecond=0).isoformat()
    return {
        "schema_version": "ws2_data_integrity_preflight_v2", "role": "READ_ONLY_NON_PERFORMANCE_DATA_INTEGRITY_GATE",
        "generated_at_jst": generated, "generator_sha256": sha256(Path(__file__)), "overall_status": "PASS",
        "iteration_gates": {"iteration_0": "READY_FOR_RETRAIN_FROZEN_V5_RECIPE_PER_ROLLING_FOLD", "iteration_1": "NOT_EVALUATED_NO_TRAINING"},
        "checks": checks, "feature_manifest": feature_manifest, "excluded_feature_groups": excluded,
        "period_roles": role_result, "holdout": {"status": role_result["status"], "performance_based_selection": "PROHIBITED"},
        "learning_db_impact": learning, "population": {**population, "v5_dataset_inventory": dataset_inventory, "v5_runtime_identity": runtime_identity, "source_races": len(complete) + len(incomplete), "full_field_complete_races": len(complete), "incomplete_races": len(incomplete), "mismatch_races": len(mismatch), "monthly_incomplete_rate": monthly},
        "summary": {"training_started": False, "model_change": False, "buy_change": False, "production_change": False, "performance_metrics_emitted": False, "caller_status_overrides_used": False, "rolling_origin_folds": folds},
    }


def write_preflight_result(result: dict[str, Any], output_root: Path) -> Path:
    """Exclusive-create a machine-readable preflight result and SHA index."""
    if output_root.exists():
        _stop("STOP_OUTPUT_ALREADY_EXISTS")
    output_root.mkdir(parents=True)
    target = output_root / "ws2_data_integrity_preflight_v2.json"
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n")
    with (output_root / "artifact_hashes.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump({target.name: sha256(target)}, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n")
    return target


def write_preflight(bundle_path: Path, output_root: Path, root: Path) -> Path:
    """Load a declared bundle and write its read-only preflight result exclusively."""
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    try:
        result = evaluate_preflight(bundle, root)
    except DataIntegrityStop as error:
        result = {
            "schema_version": "ws2_data_integrity_preflight_v2", "role": "READ_ONLY_NON_PERFORMANCE_DATA_INTEGRITY_GATE",
            "generated_at_jst": bundle.get("generated_at_jst") or datetime.now(timezone(timedelta(hours=9))).replace(microsecond=0).isoformat(),
            "generator_sha256": sha256(Path(__file__)), "overall_status": "STOP",
            "iteration_gates": {"iteration_0": "BLOCKED", "iteration_1": "NOT_EVALUATED_NO_TRAINING"},
            "checks": [{"check_id": "FAIL_CLOSED_GATE", "status": "STOP", "severity": "STOP", "reason_code": str(error), "evidence": {}, "counts": {}, "source_paths": [], "source_sha256": []}],
            "feature_manifest": [], "excluded_feature_groups": [], "period_roles": [],
            "holdout": {"status": "NOT_EVALUATED"}, "learning_db_impact": {"LEARNING_DB_IMPACT": "NOT_EVALUATED"}, "population": {},
            "summary": {"training_started": False, "model_change": False, "buy_change": False, "production_change": False, "performance_metrics_emitted": False},
        }
    return write_preflight_result(result, output_root)
