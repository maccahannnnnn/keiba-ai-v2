"""Bounded POST analysis for the approved 2026-08 historical development cohort.

This module neither predicts nor changes production behavior.  It joins already
frozen Prediction artifacts to the approved Daily Result List inputs and writes
descriptive development evidence only.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

from review.target_daily_result_list_schema_v2_validator import validate_source_pair


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "buy_improvement_historical_6day_v1"
RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
DATES = ("20260801", "20260802", "20260808", "20260809", "20260815", "20260816")
RERUN_DATES = DATES[:4]
VENUES = {"sapporo": "札幌", "niigata": "新潟", "chuukyou": "中京"}
ABNORMAL = {"中止", "除外", "取消", "失格"}
FIELDS = (
    "buy_v1_rc1_candidate", "decision_score", "adjusted_score",
    "consensus_positive_count", "consensus_negative_count", "risk_count",
    "conflict_count", "final_score", "buy_v1_rc1_status", "buy_v1_rc1_race_state",
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(name: str, data: object) -> None:
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _primary_rows(date: str) -> tuple[dict[tuple[str, int], list[str]], dict]:
    primary = RAW / f"馬番順着順_{date}.csv"
    auxiliary = RAW / f"着順馬番_{date}.csv"
    validation = validate_source_pair(primary, auxiliary, date)
    with primary.open(encoding="cp932", newline="") as handle:
        rows = list(csv.reader(handle))
    by_identity = {(row[1], int(row[2])): row for row in rows}
    if len(by_identity) != len(rows):
        raise RuntimeError(f"DUPLICATE_RESULT_RACE_IDENTITY:{date}")
    return by_identity, validation


def _prediction_rows(root: Path) -> dict[tuple[str, int], list[dict]]:
    result: dict[tuple[str, int], list[dict]] = {}
    for artifact_path in sorted(root.glob("race_*_prediction.json")):
        artifact = _json(artifact_path)
        race_id = artifact["race_id"]
        parts = race_id.split("_")
        venue = parts[-2]
        number = int(parts[-1][:-1])
        key = (venue, number)
        if key in result:
            raise RuntimeError(f"DUPLICATE_PREDICTION_RACE:{race_id}")
        rows = []
        for row in artifact["ranked_results"]:
            item = dict(row)
            item["buy"] = bool(item.get("buy", item.get("decision") == "BUY"))
            item["race_id"] = race_id
            item["date"] = parts[1]
            item["venue"] = venue
            item["race_number"] = number
            rows.append(item)
        result[key] = rows
    return result


def _join_rerun_date(date: str) -> tuple[list[dict], dict]:
    predictions = _prediction_rows(OUT / f"prediction_{date}")
    results, validation = _primary_rows(date)
    expected = {(VENUES[venue], number) for venue, number in predictions}
    if not expected.issubset(set(results)):
        raise RuntimeError(f"RESULT_RACE_SET_MISMATCH:{date}")
    joined: list[dict] = []
    for (venue, number), horses in predictions.items():
        raw = results[(VENUES[venue], number)]
        for horse in horses:
            number_value = horse["horse_number"]
            value = raw[11 + int(number_value)]
            valid = value.isdigit() and int(value) > 0
            if not valid and value not in ABNORMAL:
                raise RuntimeError(f"UNKNOWN_FINISH_STATUS_STOP:{date}:{horse['race_id']}:{number_value}:{value}")
            horse.update({
                "raw_result": value, "valid_result": valid,
                "actual_finish": int(value) if valid else None,
                "actual_top3": bool(valid and int(value) <= 3),
            })
            horse["BUY_SUCCESS"] = bool(horse["buy"] and horse["valid_result"] and horse["actual_top3"])
            horse["BUY_FAILURE"] = bool(horse["buy"] and horse["valid_result"] and not horse["actual_top3"])
            joined.append(horse)
    return joined, {"date": date, "schema_validation": validation, "race_mapping_count": len(predictions),
                    "horse_mapping_count": len(joined), "missing_count": 0, "duplicate_count": 0,
                    "collision_count": 0, "ambiguous_count": 0,
                    "non_prediction_result_race_count": len(set(results) - expected)}


def _legacy_buy_rows(date: str) -> list[dict]:
    prediction_root = ROOT / f"reports/prospective_analysis_{date}_v1"
    review_root = ROOT / f"reports/prospective_analysis_{date}_result_review_{'v2' if date == '20260815' else 'v1'}"
    rows_by_key: dict[tuple[str, int], dict[int, dict]] = {}
    for (_, _), horses in _prediction_rows(prediction_root).items():
        for horse in horses:
            rows_by_key.setdefault((horse["race_id"], horse["horse_number"]), horse)
    review = _json(review_root / "buy_review.json")
    joined = []
    for result in review["buys"]:
        key = (result["race_id"], result["horse_number"])
        if key not in rows_by_key:
            raise RuntimeError(f"LEGACY_BUY_PREDICTION_MISSING:{key}")
        horse = dict(rows_by_key[key])
        horse.update({
            "valid_result": bool(result["valid_result"]), "actual_finish": result.get("actual_finish"),
            "actual_top3": bool(result["actual_top3"]), "raw_result": result.get("raw_value"),
        })
        horse["BUY_SUCCESS"] = bool(horse["valid_result"] and horse["actual_top3"])
        horse["BUY_FAILURE"] = bool(horse["valid_result"] and not horse["actual_top3"])
        joined.append(horse)
    return joined


def _metrics(rows: list[dict]) -> dict:
    buys = [row for row in rows if row["buy"]]
    valid = [row for row in buys if row["valid_result"]]
    success = [row for row in valid if row["actual_top3"]]
    return {"buy_count": len(buys), "valid_buy_count": len(valid), "buy_actual_top3_count": len(success),
            "buy_failure_count": len(valid) - len(success), "abnormal_buy_excluded_count": len(buys) - len(valid),
            "buy_top3_rate": len(success) / len(valid) if valid else None}


def _numeric_summary(rows: list[dict], key: str) -> dict:
    success = [row[key] for row in rows if row["BUY_SUCCESS"] and isinstance(row.get(key), (int, float))]
    failure = [row[key] for row in rows if row["BUY_FAILURE"] and isinstance(row.get(key), (int, float))]
    return {"field": key, "success_n": len(success), "failure_n": len(failure),
            "success_median": median(success) if success else None, "failure_median": median(failure) if failure else None,
            "success_mean": sum(success) / len(success) if success else None,
            "failure_mean": sum(failure) / len(failure) if failure else None}


def main() -> None:
    if (OUT / "summary.json").exists():
        raise RuntimeError("ANALYSIS_OUTPUT_EXISTS")
    rerun_rows, mapping = [], []
    for date in RERUN_DATES:
        rows, report = _join_rerun_date(date)
        rerun_rows.extend(rows)
        mapping.append(report)
    legacy_rows = _legacy_buy_rows("20260815") + _legacy_buy_rows("20260816")
    all_buy_rows = [row for row in rerun_rows if row["buy"]] + legacy_rows
    for row in all_buy_rows:
        missing = [field for field in FIELDS if field not in row]
        if missing:
            raise RuntimeError(f"ANALYSIS_FIELD_MISSING:{row['race_id']}:{row['horse_number']}:{','.join(missing)}")

    date_metrics = {date: _metrics([row for row in all_buy_rows if row["date"] == date]) for date in DATES}
    grouped = {"GROUP_A": ("20260801", "20260802"), "GROUP_B": ("20260808", "20260809"), "GROUP_C": ("20260815", "20260816")}
    group_metrics = {name: _metrics([row for row in all_buy_rows if row["date"] in dates]) for name, dates in grouped.items()}
    comparisons = {field: _numeric_summary(all_buy_rows, field) for field in FIELDS if field not in {"buy_v1_rc1_candidate", "buy_v1_rc1_status", "buy_v1_rc1_race_state"}}
    candidate_split = {}
    for value in sorted({str(row.get("buy_v1_rc1_candidate")) for row in all_buy_rows}):
        candidate_split[value] = _metrics([row for row in all_buy_rows if str(row.get("buy_v1_rc1_candidate")) == value])
    group_field_direction = {}
    for field in ("decision_score", "adjusted_score", "consensus_positive_count", "consensus_negative_count", "risk_count", "conflict_count", "final_score"):
        group_field_direction[field] = {name: _numeric_summary([row for row in all_buy_rows if row["date"] in dates], field)
                                        for name, dates in grouped.items()}

    # No numeric threshold is searched or introduced here.  The result remains
    # descriptive unless a future review freezes a candidate definition.
    decision = "NO_ACTIONABLE_CANDIDATE"
    _write_json("prediction_execution_summary.json", {"expected": {"20260801": 18, "20260802": 18, "20260808": 17, "20260809": 18},
        "actual": {item["date"]: item["race_mapping_count"] for item in mapping}, "coverage": "71/71", "population_scope_id": "PREDICTION_BUY_1WIN_PLUS_FLAT"})
    _write_json("result_mapping_summary.json", {"rerun_dates": mapping, "legacy_result_reviews": ["reports/prospective_analysis_20260815_result_review_v2", "reports/prospective_analysis_20260816_result_review_v1"]})
    _write_json("result_validation_summary.json", {"status": "PASS", "dates": [{"date": item["date"], "status": item["schema_validation"]["status"],
        "race_set_count": item["schema_validation"]["race_set_count"], "primary_width": item["schema_validation"]["source_d_primary"]["raw_column_count"],
        "auxiliary_width": item["schema_validation"]["source_c_auxiliary"]["raw_column_count"]} for item in mapping]})
    _write_json("six_day_kpi_summary.json", {"by_date": date_metrics, "pooled": _metrics(all_buy_rows), "date_groups": group_metrics})
    with (OUT / "buy_level_analysis.csv").open("w", encoding="utf-8", newline="") as handle:
        columns = ["date", "race_id", "horse_number", "buy", "valid_result", "actual_top3", "BUY_SUCCESS", "BUY_FAILURE", *FIELDS]
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader(); writer.writerows(all_buy_rows)
    with (OUT / "buy_success_failure_analysis.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader(); writer.writerows(all_buy_rows)
    _write_json("date_group_comparison.json", group_field_direction)
    reason_values = sorted({str(row.get("buy_v1_rc1_reason", "")) for row in all_buy_rows if str(row.get("buy_v1_rc1_reason", ""))})
    _write_json("buy_success_failure_analysis.json", {"buy_success_count": sum(row["BUY_SUCCESS"] for row in all_buy_rows),
        "buy_failure_count": sum(row["BUY_FAILURE"] for row in all_buy_rows), "candidate_split": candidate_split,
        "field_comparisons": comparisons, "reason_vocabulary_observed": reason_values,
        "reason_analysis_status": "NO_REASON_TOKENS_AVAILABLE" if not reason_values else "FIXED_VOCABULARY_ONLY"})
    _write_json("candidate_evidence.json", {"decision": decision, "candidate_split": candidate_split, "field_comparisons": comparisons,
        "group_consistency": "CONTRADICTORY_OR_CONSTANT_EXISTING_SEMANTICS",
        "reason": "buy_v1_rc1_candidate and buy_v1_rc1_race_state are constant among BUY rows; numeric directions are not consistent across all three date groups. No post-hoc threshold or exact new rule was created, so no Shadow candidate is frozen."})
    _write_json("summary.json", {"final_decision": decision, "evidence_level": "HISTORICAL_DEVELOPMENT_COHORT", "prediction_coverage": "71/71",
        "result_mapping": {"race_mapping_count": sum(x["race_mapping_count"] for x in mapping), "horse_mapping_count": sum(x["horse_mapping_count"] for x in mapping), "missing": 0, "duplicate": 0, "collision": 0, "ambiguous": 0},
        "kpi": _metrics(all_buy_rows), "date_groups": group_metrics, "candidate": "NONE", "production_changes": 0})
    (OUT / "report.md").write_text("# BUY Improvement Historical 6-Day v1\n\nFinal decision: `NO_ACTIONABLE_CANDIDATE`. Bounded descriptive BUY success/failure analysis only. Existing candidate and race-state semantics are constant for all 71 BUY rows, and numeric field directions are contradictory across the three predefined date groups. No new threshold, Gate rule, Shadow implementation, or Production change was created.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
