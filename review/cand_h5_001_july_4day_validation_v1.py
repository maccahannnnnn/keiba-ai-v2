"""Frozen H5-only retrospective external validation; no candidate discovery."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "cand_h5_001_july_4day_validation_v1"
RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
DATES = ("20260704", "20260705", "20260711", "20260712")
VENUES = {"sapporo": "札幌", "niigata": "新潟", "chuukyou": "中京", "hakodate": "函館", "fukushima": "福島", "kokura": "小倉"}
ABNORMAL = {"中止", "除外", "取消", "失格"}


def write(name: str, data: object) -> None:
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def result_source(date: str) -> tuple[dict[tuple[str, int], list[str]], dict]:
    primary, auxiliary = RAW / f"馬番順着順_{date}.csv", RAW / f"着順馬番_{date}.csv"
    validation = validate_source_pair(primary, auxiliary, date)
    with primary.open(encoding="cp932", newline="") as source:
        rows = list(csv.reader(source))
    indexed = {(row[1], int(row[2])): row for row in rows}
    if len(indexed) != len(rows):
        raise RuntimeError(f"DUPLICATE_RESULT_RACE:{date}")
    return indexed, validation


def metrics(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    hit = [row for row in valid if row["actual_top3"]]
    return {"race_count": len({row["race_id"] for row in rows}), "BUY_count": len(rows), "valid_BUY_count": len(valid),
            "Top3_count": len(hit), "failure_count": len(valid) - len(hit), "Top3_rate": len(hit) / len(valid) if valid else None}


def main() -> None:
    if (OUT / "summary.json").exists():
        raise RuntimeError("OUTPUT_EXISTS")
    rows, input_summary, result_summary, coverage = [], {}, {}, []
    for date in DATES:
        results, validation = result_source(date)
        root = OUT / f"prediction_{date}"
        artifacts = sorted(root.glob("race_*_prediction.json"))
        date_rows = []
        for path in artifacts:
            art = json.loads(path.read_text(encoding="utf-8")); parts = art["race_id"].split("_")
            venue, race_number = parts[-2], int(parts[-1][:-1])
            result = results.get((VENUES[venue], race_number))
            if result is None:
                raise RuntimeError(f"MISSING_RESULT_RACE:{art['race_id']}")
            for horse in art["ranked_results"]:
                if horse.get("decision") != "BUY":
                    continue
                number = int(horse["horse_number"]); raw = result[11 + number]
                valid = raw.isdigit() and int(raw) > 0
                if not valid and raw not in ABNORMAL:
                    raise RuntimeError(f"UNKNOWN_FINISH_STATUS:{art['race_id']}:{number}:{raw}")
                date_rows.append({"date": date, "race_id": art["race_id"], "horse_number": number, "race_buy_count": art["buy_count"],
                                  "valid_result": valid, "actual_top3": bool(valid and int(raw) <= 3), "raw_result": raw})
        if len({a["race_id"] for a in [json.loads(p.read_text(encoding="utf-8")) for p in artifacts]}) != len(artifacts):
            raise RuntimeError(f"DUPLICATE_PREDICTION_RACE:{date}")
        input_summary[date] = {"prediction_race_count": len(artifacts), "eligible_horse_count": sum(len(json.loads(p.read_text(encoding="utf-8"))["ranked_results"]) for p in artifacts)}
        result_summary[date] = {"status": validation["status"], "race_set_count": validation["race_set_count"],
                                "primary_width": validation["source_d_primary"]["raw_column_count"], "auxiliary_width": validation["source_c_auxiliary"]["raw_column_count"]}
        coverage.append({"date": date, "prediction_races": len(artifacts), "mapped_races": len(artifacts),
                         "prediction_horses": input_summary[date]["eligible_horse_count"], "mapped_horses": input_summary[date]["eligible_horse_count"],
                         "missing": 0, "duplicate": 0, "collision": 0, "ambiguous": 0,
                         "abnormal_BUY_exclusions": sum(not row["valid_result"] for row in date_rows)})
        rows.extend(date_rows)
    by_date = {date: {str(count): metrics([row for row in rows if row["date"] == date and row["race_buy_count"] == count]) for count in (1, 2, 3)} for date in DATES}
    pooled = {str(count): metrics([row for row in rows if row["race_buy_count"] == count]) for count in (1, 2, 3)}
    with (OUT / "h5_buy_rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "race_id", "horse_number", "race_buy_count", "valid_result", "actual_top3", "raw_result"])
        writer.writeheader(); writer.writerows(rows)
    write("input_validation_summary.json", input_summary); write("result_validation_summary.json", result_summary)
    write("prediction_coverage_summary.json", {"total_prediction_races": sum(x["prediction_races"] for x in coverage), "by_date": coverage})
    write("result_mapping_summary.json", {"by_date": coverage, "total": {"prediction_races": sum(x["prediction_races"] for x in coverage), "mapped_races": sum(x["mapped_races"] for x in coverage), "prediction_horses": sum(x["prediction_horses"] for x in coverage), "mapped_horses": sum(x["mapped_horses"] for x in coverage), "missing": 0, "duplicate": 0, "collision": 0, "ambiguous": 0}})
    write("h5_per_date.json", by_date); write("h5_pooled.json", pooled)
    write("validation_decision.json", {"state": "PENDING_REVIEW_OF_FROZEN_H5_DIRECTION", "development_reference": {"1": "12/27", "2": "10/26", "3": "2/18"}, "condition": "race_buy_count == 3", "no_other_analysis": True})
    write("summary.json", {"final_decision": "PENDING_REVIEW_OF_FROZEN_H5_DIRECTION", "evidence_classification": "RETROSPECTIVE_EXTERNAL_VALIDATION", "prediction_coverage": sum(x["prediction_races"] for x in coverage), "mapping_coverage": sum(x["mapped_races"] for x in coverage), "h5_pooled": pooled, "production_changes": 0})
    (OUT / "report.md").write_text("# CAND-H5-001 July 4-Day Retrospective External Validation\n\nFrozen H5 condition only: `race_buy_count == 3`. Decision pending mechanical review of the generated 1/2/3-BUY measurements. No Trace field was used in the validation logic.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
