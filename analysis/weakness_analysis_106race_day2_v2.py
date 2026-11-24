"""Day2-only observational analysis for the frozen 106-race weakness study V2."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SPEC_PATH = REPORTS / "weakness_analysis_106race_preregistered_spec_v2.md"
SPEC_SHA256 = "3f010795f76ef85f410e1fcfe7b224fa18ac37a4be68a386ee94fc537c593800"
RUN_IDS = tuple(f"HR_PHASE4_BATCH{i}_RESULT_JOIN_ALIGNED_V2" for i in range(1, 5))

EVALUATORS = (
    ("PastPerformance", "past_performance_score"),
    ("Distance", "distance_score"),
    ("CourseShape", "course_shape_score"),
    ("LapSuitability", "lap_score"),
    ("RaceShape", "shape_score"),
    ("PaceStyle", "pace_style_score"),
    ("Bloodline", "bloodline_score"),
    ("TrackCondition", "track_condition_score"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def average_rank_percentiles(values: Iterable[float]) -> list[float]:
    """Return 1-based average-rank percentiles in the interval (0, 100]."""
    numbers = list(values)
    if not numbers:
        return []
    order = sorted(range(len(numbers)), key=numbers.__getitem__)
    result = [0.0] * len(numbers)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and numbers[order[end]] == numbers[order[start]]:
            end += 1
        average_rank = ((start + 1) + end) / 2.0
        percentile = average_rank / len(numbers) * 100.0
        for position in range(start, end):
            result[order[position]] = percentile
        start = end
    return result


def classify_percentiles(values: Iterable[float]) -> tuple[str, float, int]:
    percentiles = list(values)
    if len(percentiles) != 8:
        raise ValueError("ABC_REQUIRES_EIGHT_EVALUATORS")
    median = statistics.median(percentiles)
    below_ten = sum(value < 10.0 for value in percentiles)
    if median < 40.0:
        label = "a"
    elif median >= 50.0 and 1 <= below_ten <= 2:
        label = "b"
    else:
        label = "c"
    return label, median, below_ten


def cohort_role(row: dict[str, Any]) -> str:
    if not row.get("valid_result"):
        return "INVALID_RESULT_EXCLUDED"
    if row.get("decision") not in {"PASS", "CAUTION"}:
        return "OTHER"
    if row.get("actual_top3") and int(row["final_rank"]) >= 6:
        return "TARGET"
    if not row.get("actual_top3"):
        return "CONTROL"
    return "OTHER"


def load_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if sha256(SPEC_PATH) != SPEC_SHA256:
        raise RuntimeError("FROZEN_SPEC_SHA_MISMATCH")
    rows: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    race_ids: list[str] = []
    for run_id in RUN_IDS:
        root = REPORTS / "historical_replay_current_code" / run_id
        summary = read_json(root / "summary.json")
        if summary["status"] != "RUN_COMPLETE" or sum(x["trace_count"] for x in summary["entries"]) != 0:
            raise RuntimeError(f"INVALID_RUN:{run_id}")
        batch_rows: list[dict[str, Any]] = []
        for path in root.glob("*/race_*/post_race/post_joined.json"):
            payload = read_json(path)
            batch_rows.extend(payload if isinstance(payload, list) else payload["horses"])
        if len(batch_rows) != summary["horse_count"]:
            raise RuntimeError(f"HORSE_COUNT_MISMATCH:{run_id}")
        rows.extend(batch_rows)
        batch_races = [x["race_id"] for x in summary["entries"]]
        race_ids.extend(batch_races)
        runs.append({"run_id": run_id, "race_count": summary["race_count"], "horse_count": summary["horse_count"]})
    if len(race_ids) != len(set(race_ids)) != 106:
        raise RuntimeError("RACE_SET_INVALID")
    if len(race_ids) != 106 or len(rows) != 1462:
        raise RuntimeError("FORMAL_COHORT_SIZE_MISMATCH")
    horse_keys = {(row["race_id"], str(row["horse_number"])) for row in rows}
    if len(horse_keys) != len(rows):
        raise RuntimeError("HORSE_DUPLICATE")
    return rows, runs


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    percentile_by_evaluator: dict[str, list[float]] = {}
    for evaluator, field in EVALUATORS:
        percentile_by_evaluator[evaluator] = average_rank_percentiles(float(row[field]) for row in rows)

    percentile_rows: list[dict[str, Any]] = []
    classification_rows: list[dict[str, Any]] = []
    for index, source in enumerate(rows):
        role = cohort_role(source)
        evaluator_values = {evaluator: percentile_by_evaluator[evaluator][index] for evaluator, _ in EVALUATORS}
        percentile_row = {
            "race_id": source["race_id"],
            "race_date": source["race_date"],
            "racecourse": source["racecourse"],
            "horse_number": source["horse_number"],
            "horse_name": source["horse_name"],
            "ai_rank": source["final_rank"],
            "decision": source["decision"],
            "actual_finish": source["actual_finish"],
            "valid_result": source["valid_result"],
            "cohort_role": role,
        }
        for evaluator, field in EVALUATORS:
            percentile_row[f"{evaluator}_raw_score"] = source[field]
            percentile_row[f"{evaluator}_percentile"] = evaluator_values[evaluator]
        percentile_rows.append(percentile_row)
        if role in {"TARGET", "CONTROL"}:
            label, median, below_ten = classify_percentiles(evaluator_values.values())
            classification_rows.append({
                "race_id": source["race_id"],
                "horse_number": source["horse_number"],
                "horse_name": source["horse_name"],
                "ai_rank": source["final_rank"],
                "cohort_role": role,
                "abc_classification": label,
                "eight_evaluator_percentile_median": median,
                "evaluator_below_10pct_count": below_ten,
            })

    target_indexes = [i for i, row in enumerate(rows) if cohort_role(row) == "TARGET"]
    control_indexes = [i for i, row in enumerate(rows) if cohort_role(row) == "CONTROL"]
    median_rows: list[dict[str, Any]] = []
    for evaluator, _ in EVALUATORS:
        target_median = statistics.median(percentile_by_evaluator[evaluator][i] for i in target_indexes)
        control_median = statistics.median(percentile_by_evaluator[evaluator][i] for i in control_indexes)
        difference = target_median - control_median
        median_rows.append({
            "evaluator": evaluator,
            "target_count": len(target_indexes),
            "control_count": len(control_indexes),
            "target_median_percentile": target_median,
            "control_median_percentile": control_median,
            "target_minus_control_points": difference,
            "absolute_difference_points": abs(difference),
            "ten_point_criterion": "MATERIAL_DIFFERENCE" if abs(difference) >= 10.0 else "NO_MATERIAL_DIFFERENCE",
            "difference_direction": "TARGET_HIGHER" if difference > 0 else ("TARGET_LOWER" if difference < 0 else "EQUAL"),
        })

    counts: dict[str, Counter[str]] = {
        "TARGET": Counter(row["abc_classification"] for row in classification_rows if row["cohort_role"] == "TARGET"),
        "CONTROL": Counter(row["abc_classification"] for row in classification_rows if row["cohort_role"] == "CONTROL"),
    }
    abc_share_rows: list[dict[str, Any]] = []
    for label in ("a", "b", "c"):
        target_count = counts["TARGET"][label]
        control_count = counts["CONTROL"][label]
        target_share = target_count / len(target_indexes)
        control_share = control_count / len(control_indexes)
        abc_share_rows.append({
            "abc_classification": label,
            "target_count": target_count,
            "target_total": len(target_indexes),
            "target_share": target_share,
            "control_count": control_count,
            "control_total": len(control_indexes),
            "control_share": control_share,
            "target_minus_control_share_points": (target_share - control_share) * 100.0,
        })

    return {
        "percentile_rows": percentile_rows,
        "median_rows": median_rows,
        "classification_rows": classification_rows,
        "abc_share_rows": abc_share_rows,
        "target_count": len(target_indexes),
        "control_count": len(control_indexes),
        "valid_result_count": sum(bool(row.get("valid_result")) for row in rows),
        "invalid_result_count": sum(not bool(row.get("valid_result")) for row in rows),
    }


def write_report(result: dict[str, Any], runs: list[dict[str, Any]], tables_path: Path) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "status": "DAY2_OBSERVATION_COMPLETE",
        "generated_at": generated_at,
        "frozen_spec_path": str(SPEC_PATH.relative_to(ROOT)).replace("\\", "/"),
        "frozen_spec_sha256": SPEC_SHA256,
        "runs": runs,
        "race_count": 106,
        "horse_count": len(result["percentile_rows"]),
        "valid_result_count": result["valid_result_count"],
        "invalid_result_count": result["invalid_result_count"],
        "target_count": result["target_count"],
        "control_count": result["control_count"],
        "percentile_reference_population_count": len(result["percentile_rows"]),
        "percentile_method": "average_rank_1_based_divided_by_N_times_100",
        "evaluator_median_comparison": result["median_rows"],
        "abc_share_comparison": result["abc_share_rows"],
        "direction_judgment_performed": False,
        "day3_executed": False,
        "observation_only": True,
    }
    (REPORTS / "weakness_analysis_106race_day2_summary_v2.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 106レース弱点分析 V2 — Day2観察結果",
        "",
        f"- Status: `DAY2_OBSERVATION_COMPLETE`",
        f"- Frozen spec SHA256: `{SPEC_SHA256}`",
        f"- 母集団: 106レース / {len(result['percentile_rows'])}頭（valid {result['valid_result_count']} / invalid {result['invalid_result_count']}）",
        f"- 主対象群: {result['target_count']}頭",
        f"- 対照群: {result['control_count']}頭",
        "- Day3: 未実行",
        "- 方向性判定: 未実行",
        "",
        "## Evaluator中央値比較",
        "",
        "| Evaluator | 主対象中央値 | 対照群中央値 | 差（主対象−対照） | 絶対差 | 10pt基準 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in result["median_rows"]:
        lines.append(
            f"| {row['evaluator']} | {row['target_median_percentile']:.3f} | {row['control_median_percentile']:.3f} | "
            f"{row['target_minus_control_points']:+.3f} | {row['absolute_difference_points']:.3f} | {row['ten_point_criterion']} |"
        )
    lines += [
        "",
        "## (a)/(b)/(c)割合比較",
        "",
        "| 分類 | 主対象 | 対照群 | 差（主対象−対照、pt） |",
        "|---|---:|---:|---:|",
    ]
    for row in result["abc_share_rows"]:
        lines.append(
            f"| {row['abc_classification']} | {row['target_count']}/{row['target_total']} ({row['target_share']:.2%}) | "
            f"{row['control_count']}/{row['control_total']} ({row['control_share']:.2%}) | "
            f"{row['target_minus_control_share_points']:+.3f} |"
        )
    lines += [
        "",
        "## Day2停止境界",
        "",
        "本成果物は観察値のみを保存する。方向性の正式判定、弱点ランキング、ROI順位、改善案、Shadow候補は生成していない。解釈はDay3へ持ち越す。",
    ]
    (REPORTS / "weakness_analysis_106race_day2_report_v2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    tables_path.write_text(json.dumps({
        "evaluator_percentiles": result["percentile_rows"],
        "evaluator_median_comparison": result["median_rows"],
        "abc_classification": result["classification_rows"],
        "abc_share_comparison": result["abc_share_rows"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tables-json", type=Path, required=True)
    args = parser.parse_args()
    rows, runs = load_rows()
    result = analyze(rows)
    write_report(result, runs, args.tables_json)
    print(json.dumps({
        "status": "DAY2_OBSERVATION_COMPLETE",
        "target_count": result["target_count"],
        "control_count": result["control_count"],
        "median_rows": result["median_rows"],
        "abc_share_rows": result["abc_share_rows"],
        "direction_judgment_performed": False,
        "day3_executed": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
