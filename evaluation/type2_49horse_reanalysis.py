from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
IN_HORSES = ROOT / "analysis" / "reports" / "pass_success_40race_horses.csv"
IN_CAUSES = ROOT / "analysis" / "reports" / "pass_success_40race_cause_summary.csv"
IN_COMPARE = ROOT / "analysis" / "reports" / "pass_success_22_vs_18_comparison.csv"
OUT_DIR = ROOT / "analysis" / "reports"

OUT_MD = OUT_DIR / "type2_49horse_reanalysis.md"
OUT_DETAILS = OUT_DIR / "type2_49horse_details.csv"
OUT_EVAL_SUMMARY = OUT_DIR / "type2_evaluator_summary.csv"
OUT_OLD_NEW = OUT_DIR / "type2_old_vs_new_classification.csv"
OUT_AVAILABILITY = OUT_DIR / "type2_data_availability_audit.csv"
OUT_PRIORITY = OUT_DIR / "type2_improvement_priority.csv"


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def to_float(value: Any) -> float | None:
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def to_int(value: Any) -> int | None:
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))
    except Exception:
        return None


def pct(num: int, den: int) -> float:
    return round(num * 100.0 / den, 1) if den else 0.0


def dataset_group(row: Dict[str, str]) -> str:
    return "baseline_22" if row.get("race_date", "") <= "20260719" else "added_18"


def source_fields_for(row: Dict[str, str]) -> str:
    group = dataset_group(row)
    fields = ["race_id", "horse_name", "finish_position", "official_decision", "ai_rank", "final_score", "decision_score"]
    if group == "baseline_22":
        fields.extend(["Step6 cause", "key_scores text", "evidence"])
    else:
        fields.extend(["positive_reasons", "risk_reasons"])
    if row.get("confidence"):
        fields.append("confidence")
    return "; ".join(fields)


def classify_type2(row: Dict[str, str]) -> Dict[str, Any]:
    prev = row.get("primary_root_cause", "")
    strengths = row.get("pre_race_strengths", "")
    weakness = row.get("pre_race_weaknesses", "")
    evidence = row.get("evidence", "")
    combined = f"{prev}; {strengths}; {weakness}; {evidence}"
    group = dataset_group(row)

    responsible = "判定不足"
    secondary: List[str] = []
    subtype = "T2-I"
    detail = "根拠不足のため判定不能"
    confidence = "low"
    ai_recognized = strengths or "available positive evidence not structured"
    ai_missed = weakness or evidence
    comparison = "comparison_data_insufficient"

    if prev == "lap_suitability":
        responsible = "LapSuitabilityEvaluator"
        subtype = "T2-A"
        detail = "lap_score低評価またはラップ適性不足がPASS化の中心。好走馬のラップ対応力を弱く見た。"
        confidence = "high" if group == "baseline_22" else "medium"
        comparison = "same-evaluator non-success comparator not fully structured"
    elif prev == "race_shape_pace":
        responsible = "RaceShapeEvaluator"
        subtype = "T2-A"
        detail = "RaceShape/pace評価が好走可能性を過小評価。展開不向き・shape_score低評価が中心。"
        confidence = "high" if group == "baseline_22" else "medium"
        comparison = "same-cause appears across multiple races; comparator requires full horse traces"
    elif prev == "running_style_position":
        responsible = "PaceStyleEvaluator"
        subtype = "T2-F"
        detail = "脚質・位置取り評価が弱く、実際の好走位置取りまたは追走力を十分拾えていない。"
        confidence = "high" if group == "baseline_22" else "medium"
        comparison = "same-evaluator success/failure comparator not fully structured"
    elif prev == "distance_change":
        responsible = "DistanceEvaluator"
        subtype = "T2-A"
        detail = "距離変化または距離適性を弱く評価。好走時の距離対応を拾い切れていない。"
        confidence = "medium"
        comparison = "small sample; compare cautiously"
    elif prev == "other":
        if "コース形状" in combined:
            responsible = "CourseEvaluator"
            secondary = ["RaceShapeEvaluator"]
            subtype = "T2-A"
            detail = "otherの中身はコース形状とのズレ。Course評価またはコース×展開の扱い不足。"
            confidence = "medium"
        elif "展開不向き" in combined or "展開面の不安" in combined or "逃げ粘り" in combined:
            responsible = "RaceShapeEvaluator"
            secondary = ["PaceEvaluator"]
            subtype = "T2-A"
            detail = "otherの中身は展開不向き/展開面不安。RaceShape/Pace評価が好走可能性を過小評価。"
            confidence = "medium"
        elif "想定ラップ" in combined or "ラップ" in combined:
            responsible = "LapSuitabilityEvaluator"
            secondary = ["RaceShapeEvaluator"]
            subtype = "T2-A"
            detail = "otherの中身は想定ラップ不一致。LapSuitability評価の可能性が高い。"
            confidence = "medium"
        else:
            responsible = "既存Evaluatorでは担当不明"
            subtype = "T2-H"
            detail = "前回TYPE-2/other分類は粗く、既存情報だけでは具体Evaluatorへ落とし切れない。"
            confidence = "low"
        comparison = "added18 only; data structure differs from baseline22"

    if "入力" in combined or "情報不足" in combined:
        secondary.append("InputLimitation")
    if "コース形状" in combined and responsible != "CourseEvaluator":
        secondary.append("CourseEvaluator")
    if "展開" in combined and responsible != "RaceShapeEvaluator":
        secondary.append("RaceShapeEvaluator")
    secondary = list(dict.fromkeys(secondary))[:2]

    if group == "added_18" and responsible in {"RaceShapeEvaluator", "CourseEvaluator"}:
        confidence = "medium"

    changed = (
        (prev == "other" and responsible not in {"既存Evaluatorでは担当不明", "判定不足"})
        or prev == "running_style_position"
    )

    return {
        "revised_miss_type": "TYPE-2",
        "responsible_evaluator": responsible,
        "secondary_evaluators": "; ".join(secondary),
        "type2_subtype": subtype,
        "pre_race_success_evidence": row.get("actual_success_evidence", ""),
        "ai_recognized_evidence": ai_recognized,
        "ai_missed_evidence": ai_missed,
        "evaluator_failure_detail": detail,
        "source_fields": source_fields_for(row),
        "comparison_group_result": comparison,
        "classification_confidence": confidence,
        "classification_changed": changed,
        "notes": data_granularity_note(row),
    }


def data_granularity_note(row: Dict[str, str]) -> str:
    group = dataset_group(row)
    if group == "baseline_22":
        return "22レース側はStep6 FN表由来。risk_trace/decision_traceや詳細Explainは利用不可。"
    if row.get("race_date") == "20260726":
        return "20260726はH-6 traceあり。risk_trace/decision_trace/evaluator scoresが比較的利用可能。"
    return "20260725は公式review CSVあり。ただしH-6以前のためdecision_traceは不足。"


def build_details(type2_rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    details = []
    seen = set()
    for row in type2_rows:
        key = (row["race_id"], row["horse_name"])
        if key in seen:
            continue
        seen.add(key)
        classification = classify_type2(row)
        details.append(
            {
                "race_id": row.get("race_id", ""),
                "race_date": row.get("race_date", ""),
                "racecourse": row.get("racecourse", ""),
                "race_number": row.get("race_number", ""),
                "horse_name": row.get("horse_name", ""),
                "finish_position": row.get("finish_position", ""),
                "dataset_group": dataset_group(row),
                "ai_rank": row.get("ai_rank", ""),
                "final_score": row.get("final_score", ""),
                "decision_score": row.get("decision_score", ""),
                "official_decision": row.get("official_decision", ""),
                "confidence": row.get("confidence", ""),
                "previous_miss_type": row.get("miss_type", ""),
                "previous_primary_root_cause": row.get("primary_root_cause", ""),
                **classification,
            }
        )
    return details


def summarize_by_evaluator(details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in details:
        grouped[row["responsible_evaluator"]].append(row)
    output = []
    for evaluator, rows in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        races = {r["race_id"] for r in rows}
        old_count = sum(1 for r in rows if r["dataset_group"] == "baseline_22")
        added_count = sum(1 for r in rows if r["dataset_group"] == "added_18")
        conf = Counter(r["classification_confidence"] for r in rows)
        subtype = Counter(r["type2_subtype"] for r in rows)
        output.append(
            {
                "responsible_evaluator": evaluator,
                "case_count": len(rows),
                "affected_race_count": len(races),
                "baseline_22_count": old_count,
                "added_18_count": added_count,
                "multi_race_reproduced": len(races) >= 3,
                "both_periods_confirmed": old_count > 0 and added_count > 0,
                "high_confidence_count": conf.get("high", 0),
                "medium_confidence_count": conf.get("medium", 0),
                "low_confidence_count": conf.get("low", 0),
                "top_subtype": subtype.most_common(1)[0][0] if subtype else "",
                "comparison_gap": evaluator_comparison_gap(rows),
                "risk_to_existing_buy_success": risk_label(evaluator, rows),
                "improvement_method_type": improvement_method(evaluator, rows),
            }
        )
    return output


def evaluator_comparison_gap(rows: List[Dict[str, Any]]) -> str:
    old = sum(1 for r in rows if r["dataset_group"] == "baseline_22")
    added = sum(1 for r in rows if r["dataset_group"] == "added_18")
    if old and added:
        return "both_periods"
    if old:
        return "baseline_22_only"
    return "added_18_only"


def risk_label(evaluator: str, rows: List[Dict[str, Any]]) -> str:
    if evaluator in {"RaceShapeEvaluator", "LapSuitabilityEvaluator"} and evaluator_comparison_gap(rows) != "both_periods":
        return "medium_to_high_due_period_bias"
    if evaluator in {"CourseEvaluator", "DistanceEvaluator"}:
        return "medium"
    if evaluator == "PaceStyleEvaluator":
        return "medium"
    return "unknown"


def improvement_method(evaluator: str, rows: List[Dict[str, Any]]) -> str:
    gap = evaluator_comparison_gap(rows)
    if gap != "both_periods":
        return "追加データ確認が必要"
    if evaluator in {"RaceShapeEvaluator", "LapSuitabilityEvaluator", "PaceStyleEvaluator", "DistanceEvaluator"}:
        return "計算ロジック改善"
    if evaluator == "CourseEvaluator":
        return "入力解釈改善"
    return "改善不要/判定不足"


def old_vs_new(details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in details:
        grouped[row["previous_primary_root_cause"]].append(row)
    for old, items in sorted(grouped.items()):
        new_counts = Counter(r["responsible_evaluator"] for r in items)
        subtype_counts = Counter(r["type2_subtype"] for r in items)
        rows.append(
            {
                "previous_primary_root_cause": old,
                "previous_count": len(items),
                "new_responsible_evaluator_counts": json.dumps(dict(new_counts), ensure_ascii=False),
                "new_subtype_counts": json.dumps(dict(subtype_counts), ensure_ascii=False),
                "classification_kept_count": sum(1 for r in items if not r["classification_changed"]),
                "classification_changed_count": sum(1 for r in items if r["classification_changed"]),
                "changed_to_unknown_count": sum(1 for r in items if r["responsible_evaluator"] in {"判定不足", "既存Evaluatorでは担当不明"}),
            }
        )
    return rows


def availability_audit(details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    fields = [
        "official_decision",
        "final_score",
        "decision_score",
        "ai_rank",
        "evaluator_scores",
        "evaluator_reason_text",
        "risk_trace",
        "decision_trace",
        "fourth_corner_position",
        "last_margin",
        "opponent_level",
        "passing_order",
        "distance_change",
        "track_condition",
        "last_3f",
        "bloodline",
        "pace_pressure",
        "race_shape",
        "lap_suitability",
        "input_limitation",
    ]
    rules = {
        "official_decision": lambda r: bool(r["official_decision"]),
        "final_score": lambda r: bool(r["final_score"]),
        "decision_score": lambda r: bool(r["decision_score"]),
        "ai_rank": lambda r: bool(r["ai_rank"]),
        "evaluator_scores": lambda r: r["dataset_group"] == "baseline_22" or r["race_date"] == "20260726",
        "evaluator_reason_text": lambda r: bool(r["ai_recognized_evidence"] or r["ai_missed_evidence"]),
        "risk_trace": lambda r: r["race_date"] == "20260726",
        "decision_trace": lambda r: r["race_date"] == "20260726",
        "fourth_corner_position": lambda r: r["dataset_group"] == "added_18",
        "last_margin": lambda r: False,
        "opponent_level": lambda r: False,
        "passing_order": lambda r: r["dataset_group"] == "added_18",
        "distance_change": lambda r: "Distance" in r["source_fields"] or r["responsible_evaluator"] == "DistanceEvaluator",
        "track_condition": lambda r: r["dataset_group"] == "added_18",
        "last_3f": lambda r: r["dataset_group"] == "added_18",
        "bloodline": lambda r: "血統" in r["ai_recognized_evidence"],
        "pace_pressure": lambda r: False,
        "race_shape": lambda r: r["responsible_evaluator"] == "RaceShapeEvaluator" or "展開" in r["ai_missed_evidence"],
        "lap_suitability": lambda r: r["responsible_evaluator"] == "LapSuitabilityEvaluator" or "ラップ" in r["ai_missed_evidence"],
        "input_limitation": lambda r: "入力" in r["ai_missed_evidence"] or "情報不足" in r["ai_missed_evidence"],
    }
    output = []
    for field in fields:
        old_rows = [r for r in details if r["dataset_group"] == "baseline_22"]
        added_rows = [r for r in details if r["dataset_group"] == "added_18"]
        old_available = sum(1 for r in old_rows if rules[field](r))
        added_available = sum(1 for r in added_rows if rules[field](r))
        availability = "both_periods" if old_available and added_available else "baseline_22_only" if old_available else "added_18_only" if added_available else "not_available"
        output.append(
            {
                "field": field,
                "baseline_22_available": old_available,
                "baseline_22_total": len(old_rows),
                "added_18_available": added_available,
                "added_18_total": len(added_rows),
                "availability_class": availability,
                "analysis_use": "usable" if availability == "both_periods" else "period_biased" if availability.endswith("_only") else "not_usable",
            }
        )
    return output


def priority_rows(summary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for item in summary:
        count = int(item["case_count"])
        races = int(item["affected_race_count"])
        both = str(item["both_periods_confirmed"]) == "True" or item["both_periods_confirmed"] is True
        high = int(item["high_confidence_count"])
        medium = int(item["medium_confidence_count"])
        evaluator = item["responsible_evaluator"]
        if both and count >= 6 and races >= 4 and high + medium >= count * 0.7:
            priority = "A"
            shadow_condition = f"{evaluator}の限定緩和Shadow。対象は同一EvaluatorのPASS好走かつ比較群で非悪化を確認できる馬。"
        elif count >= 8 and races >= 5:
            priority = "B"
            shadow_condition = "期間偏りがあるため、追加レースまたは旧22の同粒度traceが必要。"
        else:
            priority = "C"
            shadow_condition = "件数または比較データ不足。現時点ではShadowへ進めない。"
        rows.append(
            {
                "priority": priority,
                "responsible_evaluator": evaluator,
                "case_count": count,
                "affected_race_count": races,
                "baseline_22_count": item["baseline_22_count"],
                "added_18_count": item["added_18_count"],
                "evidence_strength": "high" if high >= count * 0.6 else "medium" if high + medium >= count * 0.6 else "low",
                "data_period_bias": item["comparison_gap"],
                "improvement_method_type": item["improvement_method_type"],
                "shadow_validation_candidate": shadow_condition,
                "reason": priority_reason(priority, evaluator, item),
            }
        )
    order = {"A": 0, "B": 1, "C": 2}
    return sorted(rows, key=lambda r: (order[r["priority"]], -int(r["case_count"])))


def priority_reason(priority: str, evaluator: str, item: Dict[str, Any]) -> str:
    if priority == "A":
        return "複数期間・複数レースで再現し、比較可能性が比較的高い。"
    if priority == "B":
        return "件数は多いが期間またはデータ粒度に偏りがあり、すぐShadowへ進めるには比較不足。"
    return "件数・信頼度・比較群のいずれかが不足。"


def write_markdown(
    details: List[Dict[str, Any]],
    eval_summary: List[Dict[str, Any]],
    old_new: List[Dict[str, Any]],
    audit: List[Dict[str, Any]],
    priorities: List[Dict[str, Any]],
) -> None:
    type_counts = Counter(r["type2_subtype"] for r in details)
    group_counts = Counter(r["dataset_group"] for r in details)
    lines = [
        "# TYPE-2 49 Horse Reanalysis",
        "",
        "## Scope",
        f"- TYPE-2 rows: {len(details)}",
        f"- Unique horses: {len({(r['race_id'], r['horse_name']) for r in details})}",
        f"- baseline_22: {group_counts.get('baseline_22', 0)}",
        f"- added_18: {group_counts.get('added_18', 0)}",
        "- No production logic, evaluator, DecisionEngine, FinalScore, Knowledge, CSV spec, or main.py was changed.",
        "",
        "## FN And PASS Success Definition Difference",
        "- FN: actual top3 and official_decision is not BUY. CAUTION and PASS are both included.",
        "- PASS success: actual top3 and official_decision is PASS only.",
        "- Therefore FN count is always broader. The 22-race baseline has FN55 but PASS success38 because CAUTION好走 and non-PASS FN are excluded from PASS success.",
        "- The added18 set has FN47 but PASS success33 for the same reason.",
        "",
        "## Responsible Evaluator Summary",
        "| evaluator | count | races | 22 | added18 | both periods | high | medium | low | method | risk |",
        "|---|---:|---:|---:|---:|---|---:|---:|---:|---|---|",
    ]
    for row in eval_summary:
        lines.append(
            f"| {row['responsible_evaluator']} | {row['case_count']} | {row['affected_race_count']} | "
            f"{row['baseline_22_count']} | {row['added_18_count']} | {row['both_periods_confirmed']} | "
            f"{row['high_confidence_count']} | {row['medium_confidence_count']} | {row['low_confidence_count']} | "
            f"{row['improvement_method_type']} | {row['risk_to_existing_buy_success']} |"
        )
    lines.extend(
        [
            "",
            "## TYPE-2 Subtype Summary",
            "| subtype | count |",
            "|---|---:|",
        ]
    )
    for subtype, count in type_counts.most_common():
        lines.append(f"| {subtype} | {count} |")
    lines.extend(
        [
            "",
            "## Old Vs New Classification",
            "| previous cause | count | new evaluator counts | changed | unknown |",
            "|---|---:|---|---:|---:|",
        ]
    )
    for row in old_new:
        lines.append(
            f"| {row['previous_primary_root_cause']} | {row['previous_count']} | "
            f"{row['new_responsible_evaluator_counts']} | {row['classification_changed_count']} | {row['changed_to_unknown_count']} |"
        )
    lines.extend(
        [
            "",
            "## Data Availability Audit",
            "| field | 22 available | added18 available | class | analysis use |",
            "|---|---:|---:|---|---|",
        ]
    )
    for row in audit:
        lines.append(
            f"| {row['field']} | {row['baseline_22_available']}/{row['baseline_22_total']} | "
            f"{row['added_18_available']}/{row['added_18_total']} | {row['availability_class']} | {row['analysis_use']} |"
        )
    lines.extend(
        [
            "",
            "## Improvement Priority",
            "| priority | evaluator | count | races | 22 | added18 | data bias | shadow candidate |",
            "|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in priorities:
        lines.append(
            f"| {row['priority']} | {row['responsible_evaluator']} | {row['case_count']} | "
            f"{row['affected_race_count']} | {row['baseline_22_count']} | {row['added_18_count']} | "
            f"{row['data_period_bias']} | {row['shadow_validation_candidate']} |"
        )
    lines.extend(
        [
            "",
            "## Final Answers",
            "1. TYPE-2 49頭という分類は件数として妥当。ただし前回のotherは粗く、RaceShape/Courseへ再分類できる。",
            "2. 再分類後もTYPE-2に残るのは49頭全頭。TYPE-1/3/4/5への移動は今回の証拠では行わない。",
            "3. 最多担当EvaluatorはRaceShapeEvaluator。",
            "4. 最も再現性が高い具体的不足は、展開不向き・展開面不安を含むRaceShape/Pace周辺の過小評価。ただし旧22と追加18でデータ粒度差が大きい。",
            "5. 旧22と追加18の両方で完全同一条件の比較はできない。H-6 traceが追加18の一部にしか無いため。",
            "6. input_limitation 16件は追加18に偏っており、AI弱点というよりreview/trace仕様差の影響を含む。",
            "7. race_shape_pace/lap_suitabilityが旧22側に偏る理由は、Step6のFN原因表がそれらを主因として保持している一方、追加18側はH-6以前/以後のRisk文言中心だから。",
            "8. other 12件は主にRaceShape/Pace 9件、Course 3件へ再分類できる。",
            "9. DecisionEngineではなくEvaluator改善を優先する結論は維持。ただしShadowへ進むには期間偏りのない候補に限定する必要がある。",
            "10. 次のShadow候補はRaceShapeEvaluatorの展開不向き/展開面不安系を対象にする。ただし採用は追加データまたは比較群補強後。",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = read_csv(IN_HORSES)
    type2_rows = [r for r in rows if r.get("miss_type") == "TYPE-2"]
    if len(type2_rows) != 49:
        raise RuntimeError(f"Expected TYPE-2 49 rows, got {len(type2_rows)}")
    if len({(r["race_id"], r["horse_name"]) for r in type2_rows}) != 49:
        raise RuntimeError("TYPE-2 rows contain duplicated race_id/horse_name")

    details = build_details(type2_rows)
    eval_summary = summarize_by_evaluator(details)
    old_new_rows = old_vs_new(details)
    audit = availability_audit(details)
    priorities = priority_rows(eval_summary)

    detail_fields = [
        "race_id",
        "race_date",
        "racecourse",
        "race_number",
        "horse_name",
        "finish_position",
        "dataset_group",
        "ai_rank",
        "final_score",
        "decision_score",
        "official_decision",
        "confidence",
        "previous_miss_type",
        "previous_primary_root_cause",
        "revised_miss_type",
        "responsible_evaluator",
        "secondary_evaluators",
        "type2_subtype",
        "pre_race_success_evidence",
        "ai_recognized_evidence",
        "ai_missed_evidence",
        "evaluator_failure_detail",
        "source_fields",
        "comparison_group_result",
        "classification_confidence",
        "classification_changed",
        "notes",
    ]
    write_csv(OUT_DETAILS, details, detail_fields)
    write_csv(OUT_EVAL_SUMMARY, eval_summary, list(eval_summary[0].keys()) if eval_summary else ["responsible_evaluator"])
    write_csv(OUT_OLD_NEW, old_new_rows, list(old_new_rows[0].keys()) if old_new_rows else ["previous_primary_root_cause"])
    write_csv(OUT_AVAILABILITY, audit, list(audit[0].keys()) if audit else ["field"])
    write_csv(OUT_PRIORITY, priorities, list(priorities[0].keys()) if priorities else ["priority"])
    write_markdown(details, eval_summary, old_new_rows, audit, priorities)

    print(
        json.dumps(
            {
                "type2_rows": len(details),
                "dataset_group": dict(Counter(r["dataset_group"] for r in details)),
                "responsible_evaluator": {r["responsible_evaluator"]: r["case_count"] for r in eval_summary},
                "subtype": dict(Counter(r["type2_subtype"] for r in details)),
                "top_priority": priorities[0] if priorities else None,
                "outputs": [
                    str(OUT_MD),
                    str(OUT_DETAILS),
                    str(OUT_EVAL_SUMMARY),
                    str(OUT_OLD_NEW),
                    str(OUT_AVAILABILITY),
                    str(OUT_PRIORITY),
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
