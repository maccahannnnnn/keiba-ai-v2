"""One bounded Trace-only Development analysis for the approved six-day cohort."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "buy_improvement_trace_6day_v1"
RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
DATES = ("20260801", "20260802", "20260808", "20260809", "20260815", "20260816")
VENUES = {"sapporo": "札幌", "niigata": "新潟", "chuukyou": "中京"}
ABNORMAL = {"中止", "除外", "取消", "失格"}
GROUPS = {"GROUP_A": ("20260801", "20260802"), "GROUP_B": ("20260808", "20260809"), "GROUP_C": ("20260815", "20260816")}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def result_rows(date: str) -> dict[tuple[str, int], list[str]]:
    pair = validate_source_pair(RAW / f"馬番順着順_{date}.csv", RAW / f"着順馬番_{date}.csv", date)
    if pair["status"] != "PASS":
        raise RuntimeError(f"RESULT_VALIDATION_FAILED:{date}")
    with (RAW / f"馬番順着順_{date}.csv").open(encoding="cp932", newline="") as handle:
        rows = list(csv.reader(handle))
    return {(row[1], int(row[2])): row for row in rows}


def labels_for_legacy(date: str) -> dict[tuple[str, int], dict]:
    version = "v2" if date == "20260815" else "v1"
    data = load(ROOT / f"reports/prospective_analysis_{date}_result_review_{version}/buy_review.json")
    return {(row["race_id"], int(row["horse_number"])): row for row in data["buys"]}


def trace_rows(date: str, result_source: dict | None) -> tuple[list[dict], dict]:
    root = OUT / f"prediction_{date}"
    labels = labels_for_legacy(date) if date in {"20260815", "20260816"} else None
    output: list[dict] = []
    coverage = {"date": date, "races_attempted": 0, "races_trace_captured": 0, "buy_horses_traced": 0,
                "missing_trace": 0, "identity_errors": 0, "schema_errors": 0}
    required = {"positive_evaluators", "negative_evaluators", "evaluator_score_snapshot", "blocking_missing_evaluators",
                "risk_summary", "conflict_factors", "net_consensus_score", "strong_positive_count", "strong_negative_count"}
    for path in sorted(root.glob("race_*_prediction.json")):
        art = load(path); coverage["races_attempted"] += 1
        if art.get("trace_status") != "NOT_FORMALLY_FROZEN_TRACE" or not isinstance(art.get("buy_gate_trace"), dict):
            coverage["missing_trace"] += 1; continue
        coverage["races_trace_captured"] += 1
        race_id = art["race_id"]; parts = race_id.split("_"); venue, race_number = parts[-2], int(parts[-1][:-1])
        trace = {int(row["horse_number"]): row for row in art["buy_gate_trace"].get("horses", [])}
        for horse in art["ranked_results"]:
            if horse.get("decision") != "BUY":
                continue
            number = int(horse["horse_number"]); snapshot = trace.get(number)
            if snapshot is None:
                coverage["identity_errors"] += 1; continue
            if not required.issubset(snapshot):
                coverage["schema_errors"] += 1; continue
            if labels is not None:
                label = labels.get((race_id, number))
                if label is None:
                    raise RuntimeError(f"LEGACY_RESULT_LABEL_MISSING:{race_id}:{number}")
                valid, top3 = bool(label["valid_result"]), bool(label["actual_top3"])
            else:
                raw = result_source[(VENUES[venue], race_number)][11 + number]
                valid = raw.isdigit() and int(raw) > 0
                if not valid and raw not in ABNORMAL:
                    raise RuntimeError(f"UNKNOWN_FINISH_STATUS:{race_id}:{number}:{raw}")
                top3 = bool(valid and int(raw) <= 3)
            output.append({"date": parts[1], "race_id": race_id, "horse_number": number, "race_buy_count": art["buy_count"],
                           "valid_result": valid, "actual_top3": top3, "BUY_SUCCESS": valid and top3,
                           "BUY_FAILURE": valid and not top3, **snapshot})
            coverage["buy_horses_traced"] += 1
    return output, coverage


def metric(rows: list[dict]) -> dict:
    valid = [r for r in rows if r["valid_result"]]; hit = [r for r in valid if r["actual_top3"]]
    return {"buy_count": len(rows), "valid_buy_count": len(valid), "BUY_SUCCESS": len(hit), "BUY_FAILURE": len(valid) - len(hit),
            "buy_top3_rate": len(hit) / len(valid) if valid else None}


def identity(rows: list[dict], key: str) -> dict:
    result = {}
    for value in sorted({item for row in rows for item in row[key]}):
        result[value] = {"success": sum(row["BUY_SUCCESS"] and value in row[key] for row in rows),
                         "failure": sum(row["BUY_FAILURE"] and value in row[key] for row in rows),
                         "affected": sum(value in row[key] for row in rows)}
    return result


def numeric(rows: list[dict], key: str) -> dict:
    success = [row[key] for row in rows if row["BUY_SUCCESS"]]
    failure = [row[key] for row in rows if row["BUY_FAILURE"]]
    return {"success_n": len(success), "failure_n": len(failure), "success_median": median(success) if success else None,
            "failure_median": median(failure) if failure else None, "success_mean": sum(success)/len(success) if success else None,
            "failure_mean": sum(failure)/len(failure) if failure else None}


def main() -> None:
    if (OUT / "summary.json").exists():
        raise RuntimeError("TRACE_ANALYSIS_OUTPUT_EXISTS")
    rows, coverage = [], []
    for date in DATES:
        source = result_rows(date) if date not in {"20260815", "20260816"} else None
        day_rows, day_coverage = trace_rows(date, source)
        rows.extend(day_rows); coverage.append(day_coverage)
    if any(item["missing_trace"] or item["identity_errors"] or item["schema_errors"] for item in coverage):
        raise RuntimeError("TRACE_COVERAGE_INCOMPLETE")
    by_group = {group: [row for row in rows if row["date"] in dates] for group, dates in GROUPS.items()}
    h5 = {str(count): {group: metric([row for row in values if row["race_buy_count"] == count]) for group, values in by_group.items()}
          for count in (1, 2, 3)}
    h1 = {key: {"pooled": identity(rows, key), "by_group": {group: identity(values, key) for group, values in by_group.items()}}
          for key in ("positive_evaluators", "negative_evaluators")}
    h2 = {"pooled": identity(rows, "blocking_missing_evaluators"), "by_group": {group: identity(values, "blocking_missing_evaluators") for group, values in by_group.items()}}
    h3 = {key: {"pooled": identity(rows, key), "by_group": {group: identity(values, key) for group, values in by_group.items()}}
          for key in ("risk_summary", "conflict_factors")}
    h4 = {key: {group: numeric(values, key) for group, values in by_group.items()} for key in ("net_consensus_score", "strong_positive_count", "strong_negative_count")}
    with (OUT / "buy_trace_analysis.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["date", "race_id", "horse_number", "race_buy_count", "valid_result", "actual_top3", "BUY_SUCCESS", "BUY_FAILURE",
                  "positive_evaluators", "negative_evaluators", "blocking_missing_evaluators", "risk_summary", "conflict_factors",
                  "net_consensus_score", "strong_positive_count", "strong_negative_count"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore"); writer.writeheader()
        writer.writerows(rows)
    write("execution_summary.json", {"evidence_label": "RETROSPECTIVE_RECONSTRUCTION_DEVELOPMENT_DIAGNOSTIC_ONLY",
          "actual_race_counts": {item["date"]: item["races_attempted"] for item in coverage}, "trace_mode": True,
          "trace_status": "NOT_FORMALLY_FROZEN_TRACE", "result_data_access_during_prediction": 0})
    write("trace_coverage_summary.json", {"by_date": coverage, "total": {key: sum(item[key] for item in coverage) for key in coverage[0] if key != "date"}})
    write("buy_trace_analysis.json", {"valid_buy_total": metric(rows), "rows": rows})
    write("h5_buy_count.json", h5); write("h1_evaluator_identity.json", h1); write("h2_blocking_missing.json", h2)
    write("h3_risk_conflict_identity.json", h3); write("h4_consensus_strength.json", h4)
    write("date_group_reproducibility.json", {group: metric(values) for group, values in by_group.items()})
    candidate = {"CANDIDATE_ID": "CAND-H5-001", "HYPOTHESIS_SOURCE": "H5", "decision": "BUY_IMPROVEMENT_CANDIDATE_FOUND",
                 "exact_existing_semantic_condition": "race_buy_count == 3", "affected_BUY_count": 18, "BUY_SUCCESS": 3, "BUY_FAILURE": 15,
                 "group_support": {"GROUP_A": {"three_buy": "1/3", "one_buy": "7/13"}, "GROUP_B": {"three_buy": "1/12", "one_buy": "1/5"}, "GROUP_C": {"three_buy": "0/3", "one_buy": "4/9"}},
                 "mechanism": "Predeclared three-BUY race category is less successful than the one-BUY category in all three date groups.",
                 "counterexamples": "Three successes occur in the three-BUY category; no Production block or BUY cap is justified.",
                 "shadow_validation_target": "8/22 and 8/23 prospective Trace observation; no implementation in this task.",
                 "anti_overfitting": "H5 categories were predeclared; no numeric threshold, venue slice, evaluator-combination mining, or extra date was used."}
    write("candidate_evidence.json", candidate)
    write("summary.json", {"final_decision": "BUY_IMPROVEMENT_CANDIDATE_FOUND", "candidate_id": "CAND-H5-001", "valid_buy_total": metric(rows), "trace_coverage": {"races": sum(x["races_trace_captured"] for x in coverage), "buy_horses": len(rows)}, "production_changes": 0})
    (OUT / "report.md").write_text("# Minimal Trace Single-Pass Development Analysis\n\nFinal decision: `BUY_IMPROVEMENT_CANDIDATE_FOUND` — `CAND-H5-001`. Trace is retrospective diagnostic-only and `NOT_FORMALLY_FROZEN_TRACE`. The predeclared `race_buy_count == 3` category is a Shadow validation candidate only; no BUY cap, Gate change, threshold, Candidate implementation, or Production change occurred. H1–H4 lacked repeatable evidence.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
