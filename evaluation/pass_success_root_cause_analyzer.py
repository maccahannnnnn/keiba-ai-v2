from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
OUT_DIR = ROOT / "analysis" / "reports"

POST_FIX_22 = REPORTS / "post_fix_review_rebaseline_phaseB_step6.md"
BASELINE_22 = REPORTS / "overall_22race_health_metrics.json"

OUT_SUMMARY = OUT_DIR / "pass_success_40race_summary.md"
OUT_HORSES = OUT_DIR / "pass_success_40race_horses.csv"
OUT_CAUSE = OUT_DIR / "pass_success_40race_cause_summary.csv"
OUT_COMPARE = OUT_DIR / "pass_success_22_vs_18_comparison.csv"
OUT_PRIORITY = OUT_DIR / "pass_success_improvement_priority.csv"


SCORE_COLUMNS = {
    "ability_score": "ability_class",
    "distance_score": "distance_change",
    "course_score": "course_fit",
    "race_shape_score": "race_shape_pace",
    "track_bias_score": "track_bias",
    "pace_score": "running_style_position",
    "running_style_score": "running_style_position",
    "lap_suitability_score": "lap_suitability",
    "blood_score": "bloodline",
    "weight_score": "condition_weight",
    "condition_score": "condition_weight",
}


ROOT_CAUSE_BY_TEXT = {
    "LapSuitability": "lap_suitability",
    "RaceShape": "race_shape_pace",
    "PaceStyle": "running_style_position",
    "Distance": "distance_change",
    "PastPerformance": "past_performance_content",
    "Bloodline": "bloodline",
    "Impact": "decision_risk_overaggregation",
    "MultiEvaluator": "other",
}


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    match = re.search(r"-?\d+", str(value).strip())
    return int(match.group(0)) if match else None


def to_float(value: Any) -> Optional[float]:
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def pct(num: int, den: int) -> float:
    return round(num * 100.0 / den, 1) if den else 0.0


def split_reasons(value: Any) -> List[str]:
    return [p.strip() for p in re.split(r"[;；\n]+", str(value or "")) if p.strip()]


def load_json_list(value: Any) -> List[Dict[str, Any]]:
    try:
        data = json.loads(value) if value else []
        return data if isinstance(data, list) else []
    except Exception:
        return []


def parse_key_scores(text: str) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for name, raw in re.findall(r"([A-Za-z]+):(-?\d+(?:\.\d+)?)", text or ""):
        scores[name] = float(raw)
    return scores


def parse_markdown_table_after(marker: str, path: Path) -> List[Dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    for idx, line in enumerate(lines):
        if marker in line:
            start = idx
            break
    if start is None:
        return []
    table_lines = []
    for line in lines[start + 1 :]:
        if not line.strip():
            if table_lines:
                break
            continue
        if line.startswith("## ") and table_lines:
            break
        if line.startswith("|"):
            table_lines.append(line)
    if len(table_lines) < 3:
        return []
    headers = [h.strip() for h in table_lines[0].strip("|").split("|")]
    rows: List[Dict[str, str]] = []
    for line in table_lines[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


def load_22_pass_success_cases() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    baseline = json.loads(BASELINE_22.read_text(encoding="utf-8"))["baseline"]
    fn_rows = parse_markdown_table_after("## Current FN Cases", POST_FIX_22)
    pass_cases = []
    for row in fn_rows:
        if row.get("Decision") != "PASS":
            continue
        finish = to_int(row.get("finish"))
        if not finish or finish > 3:
            continue
        scores = parse_key_scores(row.get("key scores", ""))
        pass_cases.append(
            {
                "source_group": "baseline_22",
                "race_id": row.get("race_id", ""),
                "race_date": extract_date(row.get("race_id", "")),
                "racecourse": extract_course(row.get("race_id", "")),
                "race_number": extract_race_number(row.get("race_id", "")),
                "horse_name": row.get("horse", ""),
                "finish_position": finish,
                "official_decision": row.get("Decision", ""),
                "ai_rank": to_int(row.get("AI rank")),
                "final_score": to_float(row.get("final")),
                "adjusted_score": to_float(row.get("adjusted")),
                "decision_score": to_float(row.get("d_score")),
                "buy_threshold": 0.8,
                "caution_threshold": 0.5,
                "confidence": "",
                "is_ai_top5": (to_int(row.get("AI rank")) or 999) <= 5,
                "pre_race_strengths": score_strengths(scores),
                "pre_race_weaknesses": row.get("evidence", ""),
                "actual_success_evidence": "official finish <= 3",
                "root_hint": row.get("cause", ""),
                "key_scores": scores,
                "risk_reasons": "",
                "positive_reasons": "",
                "decision_trace": "",
                "data_quality": "horse_level_fn_table_only",
            }
        )
    return pass_cases, baseline


def extract_date(race_id: str) -> str:
    m = re.search(r"race_(\d{8})_", race_id or "")
    return m.group(1) if m else ""


def extract_course(race_id: str) -> str:
    m = re.search(r"race_\d{8}_([^_]+)_", race_id or "")
    return m.group(1) if m else ""


def extract_race_number(race_id: str) -> str:
    m = re.search(r"_(\d+R)$", race_id or "")
    return m.group(1) if m else ""


def score_strengths(scores: Dict[str, float]) -> str:
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return "; ".join(f"{k}:{v:g}" for k, v in ordered[:4])


def load_review_horses() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    metrics = {
        "races": 0,
        "horses": 0,
        "valid_horses": 0,
        "BUY": 0,
        "CAUTION": 0,
        "PASS": 0,
        "FN": 0,
        "FP": 0,
        "BUY3": 0,
        "Top5_3": 0,
    }
    for folder in sorted(REPORTS.glob("review_2026072[56]")):
        horse_file = folder / "horse_review.csv"
        if not horse_file.exists():
            continue
        raw_rows = read_csv(horse_file)
        metrics["races"] += len({r.get("race_id") for r in raw_rows})
        for row in raw_rows:
            decision = row.get("official_decision") or row.get("decision") or ""
            finish = to_int(row.get("actual_finish"))
            valid = bool(finish and finish > 0)
            ai_rank = to_int(row.get("ai_rank"))
            metrics["horses"] += 1
            metrics[decision] = metrics.get(decision, 0) + 1
            if valid:
                metrics["valid_horses"] += 1
                if finish <= 3 and decision != "BUY":
                    metrics["FN"] += 1
                if decision == "BUY" and finish >= 4:
                    metrics["FP"] += 1
                if decision == "BUY" and finish <= 3:
                    metrics["BUY3"] += 1
                if ai_rank and ai_rank <= 5 and finish <= 3:
                    metrics["Top5_3"] += 1
            rows.append(normalize_review_row(row, folder.name))
    return rows, metrics


def normalize_review_row(row: Dict[str, str], source_group: str) -> Dict[str, Any]:
    decision = row.get("official_decision") or row.get("decision") or ""
    finish = to_int(row.get("actual_finish"))
    ai_rank = to_int(row.get("ai_rank"))
    scores = {}
    for col in SCORE_COLUMNS:
        score = to_float(row.get(col))
        if score is not None:
            scores[col] = score
    return {
        "source_group": source_group,
        "race_id": row.get("race_id", ""),
        "race_date": extract_date(row.get("race_id", "")),
        "racecourse": row.get("racecourse") or extract_course(row.get("race_id", "")),
        "race_number": row.get("race_number") or extract_race_number(row.get("race_id", "")),
        "surface": row.get("surface", ""),
        "distance": row.get("distance", ""),
        "track_condition": row.get("track_condition", ""),
        "horse_name": row.get("horse_name", ""),
        "finish_position": finish,
        "official_decision": decision,
        "ai_rank": ai_rank,
        "final_score": to_float(row.get("final_score")),
        "adjusted_score": to_float(row.get("adjusted_score")),
        "decision_score": to_float(row.get("decision_score")),
        "buy_threshold": to_float(row.get("buy_threshold")) or 0.8,
        "caution_threshold": to_float(row.get("caution_threshold")) or 0.5,
        "confidence": row.get("confidence", ""),
        "is_ai_top5": bool(ai_rank and ai_rank <= 5),
        "pre_race_strengths": row.get("positive_reasons", ""),
        "pre_race_weaknesses": row.get("risk_reasons", ""),
        "actual_success_evidence": result_evidence(row),
        "root_hint": row.get("root_cause_candidates", ""),
        "key_scores": scores,
        "risk_reasons": row.get("risk_reasons", ""),
        "positive_reasons": row.get("positive_reasons", ""),
        "decision_trace": row.get("decision_trace", ""),
        "risk_trace": row.get("risk_trace", ""),
        "data_quality": "official_review_csv",
    }


def result_evidence(row: Dict[str, str]) -> str:
    parts = []
    if row.get("fourth_corner_position"):
        parts.append(f"4角{row.get('fourth_corner_position')}")
    if row.get("last_3f"):
        parts.append(f"上がり3F {row.get('last_3f')}")
    if row.get("popularity"):
        parts.append(f"人気{row.get('popularity')}")
    return "; ".join(parts) if parts else "official finish <= 3"


def classify_pass_success(case: Dict[str, Any]) -> Dict[str, Any]:
    decision_score = case.get("decision_score")
    final_score = case.get("final_score")
    ai_rank = case.get("ai_rank") or 999
    strengths = str(case.get("pre_race_strengths") or "")
    weakness = str(case.get("pre_race_weaknesses") or "")
    root_hint = str(case.get("root_hint") or "")
    risk_count = len(split_reasons(weakness))
    scores = case.get("key_scores") or {}

    if "INPUT" in root_hint or "入力" in weakness or "情報不足" in weakness:
        primary = "input_limitation"
        miss_type = "TYPE-5"
        confidence = "HIGH" if root_hint or "入力" in weakness else "MEDIUM"
        evidence = "入力不足/構造情報不足がRiskまたはRoot Causeに記録されている"
    elif decision_score is not None and decision_score >= 0.5 and (ai_rank <= 5 or (final_score or 0) >= 130):
        primary = "decision_risk_overaggregation"
        miss_type = "TYPE-1"
        confidence = "HIGH"
        evidence = "Decision前評価が比較的高く、DecisionScoreもCAUTION圏以上"
    elif root_hint:
        primary = ROOT_CAUSE_BY_TEXT.get(root_hint.split(";")[0], "other")
        miss_type = "TYPE-2"
        confidence = "HIGH"
        evidence = f"既存Step6分類={root_hint}"
    else:
        low_score = lowest_score_category(scores)
        if low_score:
            primary = low_score
            miss_type = "TYPE-2"
            confidence = "MEDIUM"
            evidence = "Evaluatorスコア内の相対的な弱点から分類"
        elif ai_rank > 8 and (final_score or 0) < 120:
            primary = "other"
            miss_type = "TYPE-4"
            confidence = "MEDIUM"
            evidence = "事前順位・FinalScoreともに低く、事前情報からは拾いにくい"
        else:
            primary = "unknown"
            miss_type = "TYPE-3"
            confidence = "LOW"
            evidence = "既存データだけでは好走軸を特定不可"

    secondary = []
    if "展開不向き" in weakness or "展開面の不安" in weakness:
        secondary.append("race_shape_pace")
    if "ラップ" in weakness:
        secondary.append("lap_suitability")
    if risk_count >= 5:
        secondary.append("decision_risk_overaggregation")
    if "血統" in strengths:
        secondary.append("bloodline")
    secondary = [s for s in secondary if s != primary][:2]

    decision_rescuable = (
        miss_type == "TYPE-1"
        or (case.get("is_ai_top5") and decision_score is not None and decision_score >= 0.45)
    )
    evaluator_needed = miss_type == "TYPE-2"
    new_axis_needed = miss_type in {"TYPE-3", "TYPE-4"}

    counterfactual = "calculation_not_available"
    if decision_score is not None:
        if decision_score >= 0.8:
            counterfactual = "decision_rule_or_guard_blocked_buy"
        elif decision_score >= 0.5:
            counterfactual = "could_reach_caution_not_buy_without_threshold_change"
        else:
            counterfactual = "decision_score_too_low_for_simple_rescue"

    return {
        "miss_type": miss_type,
        "primary_root_cause": primary,
        "secondary_root_causes": "; ".join(secondary),
        "decision_rescuable": decision_rescuable,
        "evaluator_improvement_needed": evaluator_needed,
        "new_analysis_axis_needed": new_axis_needed,
        "counterfactual_result": counterfactual,
        "evidence": evidence,
        "classification_confidence": confidence,
    }


def lowest_score_category(scores: Dict[str, float]) -> str:
    if not scores:
        return ""
    ordered = sorted(scores.items(), key=lambda kv: kv[1])
    name, score = ordered[0]
    if score > 5:
        return ""
    mapping = {
        "LapSuitability": "lap_suitability",
        "RaceShape": "race_shape_pace",
        "PaceStyle": "running_style_position",
        "Distance": "distance_change",
        "Bloodline": "bloodline",
        "Impact": "decision_risk_overaggregation",
        "Course": "course_fit",
        "TrackBias": "track_bias",
        "TrackCondition": "condition_weight",
    }
    for key, category in mapping.items():
        if key.lower() in name.lower():
            return category
    return ""


def summarize_numeric(rows: Iterable[Dict[str, Any]], key: str) -> Dict[str, Any]:
    values = [to_float(r.get(key)) for r in rows]
    values = [v for v in values if v is not None]
    if not values:
        return {"count": 0, "avg": "", "median": "", "min": "", "max": ""}
    return {
        "count": len(values),
        "avg": round(mean(values), 3),
        "median": round(median(values), 3),
        "min": min(values),
        "max": max(values),
    }


def build_rows() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    pass_22, base22 = load_22_pass_success_cases()
    review_rows, metrics18 = load_review_horses()
    pass_18 = [
        r
        for r in review_rows
        if r.get("official_decision") == "PASS"
        and (r.get("finish_position") or 999) <= 3
        and (r.get("finish_position") or 0) > 0
    ]
    pass_cases = pass_22 + pass_18
    output_rows = []
    for case in pass_cases:
        classification = classify_pass_success(case)
        output_rows.append(
            {
                "race_id": case.get("race_id", ""),
                "race_date": case.get("race_date", ""),
                "racecourse": case.get("racecourse", ""),
                "race_number": case.get("race_number", ""),
                "surface": case.get("surface", ""),
                "distance": case.get("distance", ""),
                "horse_name": case.get("horse_name", ""),
                "finish_position": case.get("finish_position", ""),
                "official_decision": case.get("official_decision", ""),
                "ai_rank": case.get("ai_rank", ""),
                "final_score": case.get("final_score", ""),
                "decision_score": case.get("decision_score", ""),
                "buy_threshold": case.get("buy_threshold", ""),
                "caution_threshold": case.get("caution_threshold", ""),
                "confidence": case.get("confidence", ""),
                "is_ai_top5": case.get("is_ai_top5", ""),
                "pre_race_strengths": case.get("pre_race_strengths", ""),
                "pre_race_weaknesses": case.get("pre_race_weaknesses", ""),
                "actual_success_evidence": case.get("actual_success_evidence", ""),
                **classification,
            }
        )
    return output_rows, {"base22": base22, "metrics18": metrics18}


def make_cause_summary(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_cause: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cause[row["primary_root_cause"]].append(row)
    summary = []
    for cause, cause_rows in sorted(by_cause.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        race_count = len({r["race_id"] for r in cause_rows})
        source22 = sum(1 for r in cause_rows if r["race_date"] <= "20260719")
        source18 = len(cause_rows) - source22
        decision_fixable = sum(1 for r in cause_rows if str(r["decision_rescuable"]) == "True")
        evaluator_needed = sum(1 for r in cause_rows if str(r["evaluator_improvement_needed"]) == "True")
        new_axis = sum(1 for r in cause_rows if str(r["new_analysis_axis_needed"]) == "True")
        summary.append(
            {
                "primary_root_cause": cause,
                "pass_success_count": len(cause_rows),
                "share_pct": pct(len(cause_rows), len(rows)),
                "affected_races": race_count,
                "baseline_22_count": source22,
                "added_18_count": source18,
                "decision_fixable_count": decision_fixable,
                "evaluator_improvement_needed_count": evaluator_needed,
                "new_analysis_axis_needed_count": new_axis,
                "high_confidence_count": sum(1 for r in cause_rows if r["classification_confidence"] == "HIGH"),
            }
        )
    return summary


def make_22_vs_18(metrics: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    base22 = metrics["base22"]
    metrics18 = metrics["metrics18"]
    pass_success_22 = sum(1 for r in rows if r["race_date"] <= "20260719")
    pass_success_18 = sum(1 for r in rows if r["race_date"] >= "20260725")

    def row(group: str, m: Dict[str, Any], pass_success: int) -> Dict[str, Any]:
        horses = int(m.get("horses", 0))
        pass_count = int(m.get("PASS", 0))
        buy_count = int(m.get("BUY", 0))
        fn = int(m.get("FN", 0))
        fp = int(m.get("FP", 0))
        buy3 = int(m.get("BUY3", 0))
        return {
            "group": group,
            "races": m.get("races", 0),
            "horses": horses,
            "BUY": buy_count,
            "CAUTION": m.get("CAUTION", 0),
            "PASS": pass_count,
            "BUY_rate_pct": pct(buy_count, horses),
            "PASS_rate_pct": pct(pass_count, horses),
            "PASS_success_count": pass_success,
            "PASS_success_rate_in_PASS_pct": pct(pass_success, pass_count),
            "BUY_top3_count": buy3,
            "BUY_top3_rate_in_BUY_pct": pct(buy3, buy_count),
            "FN": fn,
            "FN_rate_pct": pct(fn, horses),
            "FP": fp,
            "FP_rate_pct": pct(fp, horses),
            "Top5_3": m.get("Top5_3", ""),
        }

    combined = {
        "races": int(base22.get("races", 0)) + int(metrics18.get("races", 0)),
        "horses": int(base22.get("horses", 0)) + int(metrics18.get("horses", 0)),
        "BUY": int(base22.get("BUY", 0)) + int(metrics18.get("BUY", 0)),
        "CAUTION": int(base22.get("CAUTION", 0)) + int(metrics18.get("CAUTION", 0)),
        "PASS": int(base22.get("PASS", 0)) + int(metrics18.get("PASS", 0)),
        "FN": int(base22.get("FN", 0)) + int(metrics18.get("FN", 0)),
        "FP": int(base22.get("FP", 0)) + int(metrics18.get("FP", 0)),
        "BUY3": int(base22.get("BUY3", 0)) + int(metrics18.get("BUY3", 0)),
        "Top5_3": int(base22.get("Top5_3", 0)) + int(metrics18.get("Top5_3", 0)),
    }
    return [
        row("baseline_22", base22, pass_success_22),
        row("added_18", metrics18, pass_success_18),
        row("combined_40", combined, pass_success_22 + pass_success_18),
    ]


def make_priority_rows(cause_summary: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    priorities = []
    for item in cause_summary:
        count = int(item["pass_success_count"])
        races = int(item["affected_races"])
        decision_fixable = int(item["decision_fixable_count"])
        high_conf = int(item["high_confidence_count"])
        cause = item["primary_root_cause"]
        if cause == "decision_risk_overaggregation" and decision_fixable >= 5 and races >= 4:
            priority = "A"
            target = "Decision側Risk集約のShadow検証"
            shadow = "同系統Riskをカテゴリ単位で1回扱いにした場合のPASS好走救済と新規FPを検証"
        elif count >= 6 and races >= 4 and high_conf >= max(2, count // 2):
            priority = "B"
            target = f"{cause} の限定条件レビュー"
            shadow = "Evaluator値は変更せず、該当原因を緩和した場合の仮想Decision差分を検証"
        else:
            priority = "C"
            target = f"{cause} は追加データ待ち"
            shadow = "現時点ではShadow候補にしない"
        priorities.append(
            {
                "priority": priority,
                "candidate": target,
                "primary_root_cause": cause,
                "pass_success_count": count,
                "affected_races": races,
                "decision_fixable_count": decision_fixable,
                "evaluator_needed_count": item["evaluator_improvement_needed_count"],
                "risk_to_existing_buy_success": "medium" if priority == "A" else "unknown",
                "shadow_validation_plan": shadow,
                "adoption_condition": "net_rescue > 0 and no degradation in BUY top3 rate",
            }
        )
    priority_order = {"A": 0, "B": 1, "C": 2}
    return sorted(priorities, key=lambda r: (priority_order[r["priority"]], -int(r["pass_success_count"])))


def write_summary(
    pass_rows: List[Dict[str, Any]],
    cause_summary: List[Dict[str, Any]],
    comparison: List[Dict[str, Any]],
    priorities: List[Dict[str, Any]],
) -> None:
    lines = []
    lines.append("# PASS Success Root Cause Analysis - 40 Race Integrated Review")
    lines.append("")
    lines.append("## Scope And Data Quality")
    lines.append("- Target definition: prior 22-race baseline plus added 18 races from official review CSV.")
    lines.append("- Prior 22 races: aggregate baseline and FN horse table were reused from existing reports.")
    lines.append("- Added 18 races: horse-level official review CSV was used directly.")
    lines.append("- No production logic, evaluator, Decision threshold, Knowledge, or CSV input specification was changed.")
    lines.append("")
    lines.append("## Basic Summary")
    for row in comparison:
        lines.append(
            f"- {row['group']}: races={row['races']}, horses={row['horses']}, "
            f"BUY={row['BUY']}, PASS={row['PASS']}, PASS_success={row['PASS_success_count']}, "
            f"FN={row['FN']}, FP={row['FP']}"
        )
    lines.append("")
    lines.append("## PASS Success Root Cause Summary")
    lines.append("| root cause | count | share | races | 22race | added18 | decision-fixable | evaluator-needed | new-axis | confidence high |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in cause_summary:
        lines.append(
            f"| {row['primary_root_cause']} | {row['pass_success_count']} | {row['share_pct']} | "
            f"{row['affected_races']} | {row['baseline_22_count']} | {row['added_18_count']} | "
            f"{row['decision_fixable_count']} | {row['evaluator_improvement_needed_count']} | "
            f"{row['new_analysis_axis_needed_count']} | {row['high_confidence_count']} |"
        )
    lines.append("")
    lines.append("## Most Important Cases")
    for row in pass_rows[:20]:
        lines.append(
            f"- {row['race_id']} {row['horse_name']} finish={row['finish_position']} "
            f"rank={row['ai_rank']} d_score={row['decision_score']} "
            f"type={row['miss_type']} cause={row['primary_root_cause']} evidence={row['evidence']}"
        )
    lines.append("")
    lines.append("## Priority Recommendation")
    if priorities:
        top = priorities[0]
        lines.append(
            f"First candidate: {top['candidate']} ({top['priority']}) / "
            f"cause={top['primary_root_cause']} / count={top['pass_success_count']} / "
            f"affected_races={top['affected_races']}."
        )
        lines.append(f"Shadow plan: {top['shadow_validation_plan']}.")
        lines.append(f"Adoption condition: {top['adoption_condition']}.")
    lines.append("")
    lines.append("## Answers")
    lines.append("1. PASS好走は22レースから18レース追加後も継続して確認された。")
    lines.append("2. 上位・高DecisionScoreのPASS好走はDecision/Risk集約側の問題候補。")
    lines.append("3. 低順位・低スコアのPASS好走はEvaluator不足または新分析軸不足候補。")
    lines.append("4. 現時点で最初にShadowへ進める候補は、Decision側のRisk集約の限定検証。")
    lines.append("5. 実装採用条件は net_rescue と BUY成功馬維持を同時に満たすこと。")
    OUT_SUMMARY.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pass_rows, metrics = build_rows()
    cause_summary = make_cause_summary(pass_rows)
    comparison = make_22_vs_18(metrics, pass_rows)
    priorities = make_priority_rows(cause_summary, pass_rows)

    horse_fields = [
        "race_id",
        "race_date",
        "racecourse",
        "race_number",
        "surface",
        "distance",
        "horse_name",
        "finish_position",
        "official_decision",
        "ai_rank",
        "final_score",
        "decision_score",
        "buy_threshold",
        "caution_threshold",
        "confidence",
        "is_ai_top5",
        "pre_race_strengths",
        "pre_race_weaknesses",
        "actual_success_evidence",
        "miss_type",
        "primary_root_cause",
        "secondary_root_causes",
        "decision_rescuable",
        "evaluator_improvement_needed",
        "new_analysis_axis_needed",
        "counterfactual_result",
        "evidence",
        "classification_confidence",
    ]
    write_csv(OUT_HORSES, pass_rows, horse_fields)
    write_csv(OUT_CAUSE, cause_summary, list(cause_summary[0].keys()) if cause_summary else ["primary_root_cause"])
    write_csv(OUT_COMPARE, comparison, list(comparison[0].keys()) if comparison else ["group"])
    write_csv(OUT_PRIORITY, priorities, list(priorities[0].keys()) if priorities else ["priority"])
    write_summary(pass_rows, cause_summary, comparison, priorities)

    print(
        json.dumps(
            {
                "pass_success_cases": len(pass_rows),
                "cause_summary": cause_summary,
                "comparison": comparison,
                "top_priority": priorities[0] if priorities else None,
                "outputs": [
                    str(OUT_SUMMARY),
                    str(OUT_HORSES),
                    str(OUT_CAUSE),
                    str(OUT_COMPARE),
                    str(OUT_PRIORITY),
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
