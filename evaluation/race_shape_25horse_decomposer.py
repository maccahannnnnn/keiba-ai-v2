"""Decompose RaceShape-attributed PASS-success cases.

This script is diagnostic-only. It reads the previous 40-race PASS-success
analysis and produces a finer review of the 25 horses attributed to
RaceShapeEvaluator. It does not import or execute production evaluators.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "analysis" / "reports"
TYPE2_DETAILS = REPORT_DIR / "type2_49horse_details.csv"
PASS_SUCCESS = REPORT_DIR / "pass_success_40race_horses.csv"
PRE_RACE_20260725 = ROOT / "reports" / "pre_race" / "20260725" / "pre_race_20260725_all_horses.csv"
REVIEW_20260725 = ROOT / "reports" / "review_20260725" / "horse_review.csv"
RACE_SHAPE_FILE = ROOT / "evaluation" / "race_shape_evaluator.py"


DETAIL_FIELDS = [
    "race_id",
    "race_date",
    "racecourse",
    "race_number",
    "horse_name",
    "finish_position",
    "dataset_group",
    "surface",
    "distance",
    "race_class",
    "ai_rank",
    "final_score",
    "decision_score",
    "official_decision",
    "confidence",
    "ai_predicted_pace",
    "actual_pace",
    "ai_running_style",
    "actual_running_style",
    "ai_expected_position",
    "actual_position",
    "pace_pressure",
    "race_shape_score",
    "race_shape_positive_reason",
    "race_shape_negative_reason",
    "race_shape_risks",
    "pre_race_success_evidence",
    "actual_race_summary",
    "prediction_actual_gap",
    "primary_rs_pattern",
    "secondary_rs_patterns",
    "final_race_shape_judgment",
    "actual_responsible_evaluator",
    "direct_race_shape_issue",
    "cross_evaluator_issue",
    "comparison_group_result",
    "evidence",
    "source_fields",
    "classification_confidence",
    "notes",
]


PATTERNS = {
    "RS-1": "ペース予測または展開語の粗さ",
    "RS-2": "逃げ/先行頭数・圧力評価の粗さ",
    "RS-3": "対象馬の脚質認識・適性認識のズレ",
    "RS-4": "位置取り変化の可能性を評価できない",
    "RS-5": "展開は概ね合うが対象馬の展開耐性を過小評価",
    "RS-6": "RaceShapeではなくAbility/PastPerformance過小評価",
    "RS-7": "RaceShapeではなくLapSuitability問題",
    "RS-8": "RaceShapeではなくRunningStyle/PaceStyle問題",
    "RS-9": "RaceShapeではなくTrackBias問題",
    "RS-10": "RaceShapeではなくMeetingBias問題",
    "RS-11": "RaceShapeではなくCourseEvaluator問題",
    "RS-12": "複数Evaluatorの組み合わせ不足",
    "RS-13": "偶発・事前安定把握困難",
    "RS-14": "データ不足で判定不能",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def key(row: dict[str, str]) -> tuple[str, str]:
    return (row.get("race_id", ""), row.get("horse_name", ""))


def to_int(value: object, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value)))
    except ValueError:
        return default


def load_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {key(row): row for row in rows}


def normalize_race_id_from_review(row: dict[str, str]) -> str:
    return row.get("race_id", "")


def parse_race_shape_structure() -> dict[str, object]:
    text = RACE_SHAPE_FILE.read_text(encoding="utf-8")
    return {
        "responsibility": "RacePacePredictorの予測ペースと各馬pace_styleを掛け合わせ、shape_score/commentを返す。",
        "direct_inputs": [
            "pace_prediction",
            "pace_style",
            "surface",
            "distance",
            "course_shape",
        ],
        "not_directly_scored": [
            "実際の4角位置",
            "過去走の位置取り変化",
            "相手関係",
            "枠順による位置取り変化",
            "MeetingBias",
            "TrackBias",
            "能力で展開不利を補う余地",
        ],
        "tables_detected": [
            "slow",
            "average",
            "fast",
            "very_fast",
            "sprint_turf_very_fast",
            "dirt_small_turn_1700_very_fast",
            "default_very_fast",
        ],
        "limited_adjustments": [
            "fast_turf_sprint_closer_overvaluation_guard",
            "sprint_turf_very_fast_escape_mitigation",
        ],
        "comment_logic": "shape_score >= 10: 展開向く / shape_score <= -10: 展開不向き / otherwise: 展開普通",
        "code_size": len(text),
    }


def infer_pattern(base: dict[str, str], review: dict[str, str] | None) -> tuple[str, list[str], str, str, str]:
    """Return primary pattern, secondary patterns, judgment, confidence, notes."""

    dataset = base.get("dataset_group", "")
    ai_rank = to_int(base.get("ai_rank"), 99) or 99
    final_score = float(base.get("final_score") or 0)
    risk = (review or {}).get("risk_reasons", "")
    root = (review or {}).get("root_cause_candidates", "")
    horse = base.get("horse_name", "")
    race_id = base.get("race_id", "")
    prev_cause = base.get("previous_primary_root_cause", "")

    if dataset == "baseline_22":
        if ai_rank <= 5:
            return (
                "RS-5",
                ["RS-12"],
                "B",
                "medium",
                "baseline22は詳細Trace不足。Top5内PASS好走のため、展開耐性またはDecision連携の不足として中信頼で分類。",
            )
        if final_score >= 120:
            return (
                "RS-12",
                ["RS-5"],
                "B",
                "medium",
                "baseline22は詳細Trace不足。FinalScoreは一定水準のためRaceShape単独断定ではなく複合不足。",
            )
        return (
            "RS-14",
            ["RS-12"],
            "E",
            "low",
            "baseline22はRaceShape詳細、通過順、risk_traceが不足。RaceShapeとされた根拠はあるが直接ロジックまでは判定不能。",
        )

    # added_18 has review rows with actual 4c, last3f, and risk text.
    fourth = to_int((review or {}).get("fourth_corner_position"), None)
    last_rank = to_int((review or {}).get("last_3f_rank"), None)
    finish = to_int(base.get("finish_position"), None)
    top5 = ai_rank <= 5
    frontish_actual = fourth is not None and fourth <= 4
    closed_well = last_rank is not None and last_rank <= 5

    if "長い直線で逃げ粘り" in risk:
        return (
            "RS-3" if not frontish_actual else "RS-5",
            ["RS-4", "RS-12"],
            "C",
            "high",
            "長い直線で逃げ粘り課題とされたが、実際の位置取り/末脚から対象馬の脚質固定が粗かった可能性。",
        )
    if "想定ラップ" in risk:
        return (
            "RS-12",
            ["RS-1", "RS-7"],
            "B",
            "medium",
            "RaceShape系RiskとLap系Riskが重なっており、RaceShape単独ではなく連携不足。",
        )
    if "展開不向き" in risk and "展開面の不安" in risk:
        if frontish_actual and finish is not None and finish <= 3:
            return (
                "RS-5",
                ["RS-2", "RS-12"],
                "A",
                "high",
                "展開不向き/展開面不安が重複したが、実際は前目または好位で好走。展開耐性の過小評価。",
            )
        if closed_well:
            return (
                "RS-3",
                ["RS-1", "RS-12"],
                "C",
                "high",
                "展開不向きとされたが、実際は末脚で補完。脚質/適性認識のズレが中心。",
            )
        if top5:
            return (
                "RS-5",
                ["RS-12"],
                "B",
                "medium",
                "AI順位は高く、RaceShapeリスクがDecision側で強く残った疑い。",
            )
        return (
            "RS-1",
            ["RS-12"],
            "B",
            "medium",
            "展開語が粗く、具体的に何が不向きか分解できていない。",
        )

    if prev_cause == "race_shape_pace":
        return ("RS-1", ["RS-12"], "B", "medium", "展開・ペース系に分類されるが詳細Riskは不足。")

    return ("RS-14", [], "E", "low", "RaceShape詳細根拠が不足。")


def build_detail_rows() -> list[dict[str, object]]:
    type2 = read_csv(TYPE2_DETAILS)
    pass_success = load_lookup(read_csv(PASS_SUCCESS))
    pre25 = load_lookup(read_csv(PRE_RACE_20260725))
    review25 = load_lookup(read_csv(REVIEW_20260725))

    rows = [row for row in type2 if row.get("responsible_evaluator") == "RaceShapeEvaluator"]
    if len(rows) != 25:
        raise RuntimeError(f"RaceShapeEvaluator target count mismatch: expected 25, got {len(rows)}")
    if len({key(row) for row in rows}) != len(rows):
        raise RuntimeError("Duplicate race_id/horse_name found in RaceShape target rows")

    details: list[dict[str, object]] = []
    for row in rows:
        ps = pass_success.get(key(row), {})
        pre = pre25.get(key(row), {})
        review = review25.get(key(row), {})
        pattern, secondary, judgment, confidence, notes = infer_pattern(row, review if review else None)
        risk = review.get("risk_reasons") or row.get("ai_missed_evidence") or ps.get("pre_race_weaknesses", "")
        positive = review.get("positive_reasons") or row.get("ai_recognized_evidence") or ps.get("pre_race_strengths", "")
        fourth = review.get("fourth_corner_position", "")
        last_rank = review.get("last_3f_rank", "")
        actual_pos = f"4角{fourth}" if fourth else ""
        actual_style = ""
        if fourth:
            fourth_i = to_int(fourth)
            if fourth_i is not None:
                if fourth_i <= 2:
                    actual_style = "front/escape"
                elif fourth_i <= 6:
                    actual_style = "stalk"
                else:
                    actual_style = "closer"
        pre_race_evidence = row.get("pre_race_success_evidence") or ps.get("actual_success_evidence", "")
        actual_summary_parts = []
        if review:
            actual_summary_parts = [
                f"実着順{review.get('actual_finish')}",
                f"4角{review.get('fourth_corner_position') or 'NA'}",
                f"上がり3F{review.get('last_3f') or 'NA'}",
                f"上がり順位{review.get('last_3f_rank') or 'NA'}",
            ]

        detail = {
            "race_id": row.get("race_id"),
            "race_date": row.get("race_date"),
            "racecourse": row.get("racecourse"),
            "race_number": row.get("race_number"),
            "horse_name": row.get("horse_name"),
            "finish_position": row.get("finish_position"),
            "dataset_group": row.get("dataset_group"),
            "surface": pre.get("surface") or ps.get("surface", ""),
            "distance": pre.get("distance") or ps.get("distance", ""),
            "race_class": "",
            "ai_rank": row.get("ai_rank"),
            "final_score": row.get("final_score"),
            "decision_score": row.get("decision_score"),
            "official_decision": row.get("official_decision"),
            "confidence": row.get("confidence") or review.get("confidence", ""),
            "ai_predicted_pace": "",
            "actual_pace": "not_available",
            "ai_running_style": "",
            "actual_running_style": actual_style,
            "ai_expected_position": "",
            "actual_position": actual_pos,
            "pace_pressure": "",
            "race_shape_score": review.get("race_shape_score", ""),
            "race_shape_positive_reason": "",
            "race_shape_negative_reason": risk,
            "race_shape_risks": risk,
            "pre_race_success_evidence": pre_race_evidence,
            "actual_race_summary": "; ".join(actual_summary_parts) if actual_summary_parts else "result detail limited",
            "prediction_actual_gap": PATTERNS[pattern],
            "primary_rs_pattern": pattern,
            "secondary_rs_patterns": ";".join(secondary),
            "final_race_shape_judgment": judgment,
            "actual_responsible_evaluator": "RaceShapeEvaluator" if judgment in {"A", "B"} else "CrossEvaluator/Unknown",
            "direct_race_shape_issue": judgment == "A",
            "cross_evaluator_issue": judgment in {"B", "C"},
            "comparison_group_result": comparison_note(row, review),
            "evidence": "; ".join(filter(None, [positive, risk, row.get("evaluator_failure_detail", "")])),
            "source_fields": source_fields(row, review, pre, ps),
            "classification_confidence": confidence,
            "notes": notes,
        }
        details.append(detail)
    return details


def source_fields(row: dict[str, str], review: dict[str, str], pre: dict[str, str], ps: dict[str, str]) -> str:
    fields = [
        "type2_49horse_details",
        "pass_success_40race_horses",
    ]
    if pre:
        fields.append("pre_race_20260725_all_horses")
    if review:
        fields.append("review_20260725_horse_review")
    if row.get("dataset_group") == "baseline_22":
        fields.append("legacy_step6_summary_only")
    return ";".join(fields)


def comparison_note(row: dict[str, str], review: dict[str, str]) -> str:
    if row.get("dataset_group") == "baseline_22":
        return "comparison group unavailable in structured form for baseline22"
    if not review:
        return "review row unavailable"
    rank = to_int(row.get("ai_rank"), 99) or 99
    finish = to_int(row.get("finish_position"), 99) or 99
    if rank <= 5 and finish <= 3:
        return "AI Top5 PASS success; decision/risk side deserves review"
    if rank > 5 and finish <= 3:
        return "relative ranking also missed; not RaceShape-only"
    return "limited comparison"


def summarize(details: list[dict[str, object]]) -> dict[str, Counter]:
    counters = {
        "dataset": Counter(row["dataset_group"] for row in details),
        "race": Counter(row["race_id"] for row in details),
        "pattern": Counter(row["primary_rs_pattern"] for row in details),
        "judgment": Counter(row["final_race_shape_judgment"] for row in details),
        "confidence": Counter(row["classification_confidence"] for row in details),
        "top5": Counter("top5" if (to_int(row["ai_rank"], 99) or 99) <= 5 else "outside_top5" for row in details),
    }
    return counters


def write_summary_files(details: list[dict[str, object]], structure: dict[str, object]) -> None:
    counters = summarize(details)

    pattern_rows = []
    for pattern, count in counters["pattern"].most_common():
        subset = [row for row in details if row["primary_rs_pattern"] == pattern]
        races = {row["race_id"] for row in subset}
        pattern_rows.append(
            {
                "rs_pattern": pattern,
                "pattern_name": PATTERNS.get(pattern, ""),
                "horse_count": count,
                "race_count": len(races),
                "baseline_22_count": sum(1 for row in subset if row["dataset_group"] == "baseline_22"),
                "added_18_count": sum(1 for row in subset if row["dataset_group"] == "added_18"),
                "top5_count": sum(1 for row in subset if (to_int(row["ai_rank"], 99) or 99) <= 5),
                "high_confidence_count": sum(1 for row in subset if row["classification_confidence"] == "high"),
                "direct_fix_possible": "yes" if pattern in {"RS-5", "RS-1"} else "limited",
                "needs_other_evaluator": "yes" if pattern in {"RS-7", "RS-8", "RS-9", "RS-10", "RS-11", "RS-12"} else "no",
            }
        )

    write_csv(
        REPORT_DIR / "race_shape_pattern_summary.csv",
        pattern_rows,
        [
            "rs_pattern",
            "pattern_name",
            "horse_count",
            "race_count",
            "baseline_22_count",
            "added_18_count",
            "top5_count",
            "high_confidence_count",
            "direct_fix_possible",
            "needs_other_evaluator",
        ],
    )

    judgment_rows = []
    for judgment, count in sorted(counters["judgment"].items()):
        judgment_rows.append(
            {
                "judgment": judgment,
                "meaning": {
                    "A": "RaceShapeEvaluatorの直接的な分析不足",
                    "B": "RaceShapeと他Evaluatorの連携不足",
                    "C": "RaceShapeへの誤分類で別Evaluator問題",
                    "D": "事前に安定して拾いにくい",
                    "E": "データ不足",
                }.get(judgment, ""),
                "horse_count": count,
                "baseline_22_count": sum(1 for row in details if row["final_race_shape_judgment"] == judgment and row["dataset_group"] == "baseline_22"),
                "added_18_count": sum(1 for row in details if row["final_race_shape_judgment"] == judgment and row["dataset_group"] == "added_18"),
            }
        )

    write_csv(
        REPORT_DIR / "race_shape_reclassification_summary.csv",
        judgment_rows,
        ["judgment", "meaning", "horse_count", "baseline_22_count", "added_18_count"],
    )

    comparison_rows = [
        {
            "comparison_group": "RaceShape-attributed PASS success",
            "horse_count": len(details),
            "top5_count": counters["top5"]["top5"],
            "top5_rate": round(counters["top5"]["top5"] / len(details), 3),
            "baseline_22_count": counters["dataset"]["baseline_22"],
            "added_18_count": counters["dataset"]["added_18"],
            "finding": "好走馬側に偏った診断であり、非好走比較群は構造化不足。Shadowでは全40レースを母集団にする必要あり。",
        },
        {
            "comparison_group": "RaceShape low/negative non-success",
            "horse_count": "not_structured",
            "top5_count": "not_structured",
            "top5_rate": "",
            "baseline_22_count": "not_structured",
            "added_18_count": "not_structured",
            "finding": "現行入力では25頭と同一条件の非好走群を完全抽出できない。",
        },
    ]
    write_csv(
        REPORT_DIR / "race_shape_comparison_group.csv",
        comparison_rows,
        ["comparison_group", "horse_count", "top5_count", "top5_rate", "baseline_22_count", "added_18_count", "finding"],
    )

    priority_rows = [
        {
            "priority": "A",
            "candidate": "展開不向き/展開面の不安の同系統Risk統合Shadow",
            "target_pattern": "RS-5 + RS-1",
            "target_horse_count": sum(1 for row in details if row["primary_rs_pattern"] in {"RS-5", "RS-1"}),
            "expected_effect": "PASS好走馬側で過剰な展開Risk重複を減らせる可能性",
            "side_effect_risk": "全RaceShape緩和より小さいが、展開Riskが正しく効いていた凡走馬のCAUTION化に注意",
            "shadow_ready": "yes",
            "adoption_condition": "対象25頭の救済数が新規FP増加を上回り、既存BUY成功馬の判定維持率が高いこと",
        },
        {
            "priority": "B",
            "candidate": "対象馬の脚質固定を弱めるShadow",
            "target_pattern": "RS-3",
            "target_horse_count": counters["pattern"]["RS-3"],
            "expected_effect": "実際に控え/差しで好走した馬の見落とし軽減",
            "side_effect_risk": "脚質情報が薄いレースでは誤救済しやすい",
            "shadow_ready": "limited",
            "adoption_condition": "4角位置や過去走位置が取れる新形式レビューに限定",
        },
        {
            "priority": "C",
            "candidate": "RaceShape×Lap/PaceStyle連携不足の診断強化",
            "target_pattern": "RS-12",
            "target_horse_count": counters["pattern"]["RS-12"],
            "expected_effect": "原因帰属の精度向上",
            "side_effect_risk": "直接Decision改善にはつながりにくい",
            "shadow_ready": "no",
            "adoption_condition": "比較群とTraceが揃った後に再評価",
        },
    ]
    write_csv(
        REPORT_DIR / "race_shape_improvement_priority.csv",
        priority_rows,
        [
            "priority",
            "candidate",
            "target_pattern",
            "target_horse_count",
            "expected_effect",
            "side_effect_risk",
            "shadow_ready",
            "adoption_condition",
        ],
    )

    shadow_md = REPORT_DIR / "race_shape_shadow_candidate.md"
    shadow_md.write_text(build_shadow_markdown(priority_rows[0], details), encoding="utf-8")

    review_md = REPORT_DIR / "race_shape_25horse_review.md"
    review_md.write_text(build_review_markdown(details, counters, structure, priority_rows), encoding="utf-8")


def build_shadow_markdown(priority: dict[str, object], details: list[dict[str, object]]) -> str:
    target_count = priority["target_horse_count"]
    lines = [
        "# RaceShape Limited Shadow Candidate",
        "",
        "## Candidate",
        "",
        str(priority["candidate"]),
        "",
        "## Target Condition",
        "",
        "- official_decision is PASS",
        "- actual finish is Top3",
        "- RaceShape-attributed TYPE-2",
        "- primary pattern is RS-5 or RS-1",
        "- Risk text contains 展開不向き or 展開面の不安 when available",
        "",
        "## Non-target Condition",
        "",
        "- RaceShape detail is unavailable and confidence is low",
        "- Main pattern is RS-14 data insufficiency",
        "- Main issue is another evaluator such as LapSuitability or Course",
        "- Existing BUY successful horses must not be downgraded",
        "",
        "## Shadow Evaluation",
        "",
        "- Keep displayed Risk text unchanged.",
        "- Shadow-only: treat 展開不向き and 展開面の不安 as one same-family RaceShape risk when both exist.",
        "- Do not change FinalScore, production Decision, thresholds, or RaceShapeEvaluator.",
        "",
        "## Expected Measurement",
        "",
        f"- Target horses in current 25: {target_count}",
        "- Count rescued FN / PASS success horses.",
        "- Count new BUY / CAUTION outside target.",
        "- Count new FP and compare net_rescue.",
        "- Confirm existing BUY Top3 decisions are preserved.",
        "- Confirm all 40 races, not only these 25 horses.",
        "",
        "## Adoption Condition",
        "",
        str(priority["adoption_condition"]),
        "",
        "## Rejection Condition",
        "",
        "- New FP increase cancels target rescue.",
        "- BUY increases broadly outside the target condition.",
        "- Existing BUY successful horses lose their status.",
        "- Shadow changes cases without RaceShape risk evidence.",
    ]
    return "\n".join(lines) + "\n"


def build_review_markdown(
    details: list[dict[str, object]],
    counters: dict[str, Counter],
    structure: dict[str, object],
    priority_rows: list[dict[str, object]],
) -> str:
    lines = [
        "# RaceShapeEvaluator 25 Horse Detailed Review",
        "",
        "## 1. Target Confirmation",
        "",
        f"- Target horses: {len(details)}",
        f"- Target races: {len({row['race_id'] for row in details})}",
        f"- baseline22: {counters['dataset']['baseline_22']}",
        f"- added18: {counters['dataset']['added_18']}",
        "- Duplicate race_id / horse_name: 0",
        "",
        "## 2. Current RaceShapeEvaluator Responsibility",
        "",
        f"- Responsibility: {structure['responsibility']}",
        f"- Direct inputs: {', '.join(structure['direct_inputs'])}",
        f"- Tables: {', '.join(structure['tables_detected'])}",
        f"- Comment logic: {structure['comment_logic']}",
        "",
        "RaceShapeEvaluator currently predicts whether the expected race pace helps a fixed running style. It does not directly evaluate position flexibility, opponent pressure reliability, draw-driven position change, or whether ability can overcome a race-shape disadvantage.",
        "",
        "## 3. Available And Missing Data",
        "",
        "- Available for all 25: race_id, horse_name, finish_position, AI rank, FinalScore, official decision, previous RaceShape attribution.",
        "- Available mainly for added18: fourth corner position, last 3F, last 3F rank, detailed risk text.",
        "- Missing or weak for baseline22: race_shape_score, pace_pressure, decision_trace, risk_trace, actual pace, structured comparison group.",
        "- Therefore, baseline22 classifications are intentionally conservative.",
        "",
        "## 4. Pattern Summary",
        "",
        "| Pattern | Meaning | Count |",
        "|---|---|---:|",
    ]
    for pattern, count in counters["pattern"].most_common():
        lines.append(f"| {pattern} | {PATTERNS.get(pattern, '')} | {count} |")

    lines.extend(
        [
            "",
            "## 5. Final RaceShape Judgment",
            "",
            "| Judgment | Meaning | Count |",
            "|---|---|---:|",
        ]
    )
    meanings = {
        "A": "RaceShape direct analysis insufficiency",
        "B": "RaceShape and another evaluator interaction insufficiency",
        "C": "Misattributed to RaceShape; another evaluator is likely",
        "D": "Hard to capture stably pre-race",
        "E": "Insufficient data",
    }
    for judgment, count in sorted(counters["judgment"].items()):
        lines.append(f"| {judgment} | {meanings.get(judgment, '')} | {count} |")

    lines.extend(
        [
            "",
            "## 6. baseline22 vs added18",
            "",
            f"- baseline22 has {counters['dataset']['baseline_22']} cases, but detailed trace is limited.",
            f"- added18 has {counters['dataset']['added_18']} cases and richer review fields.",
            "- A broad conclusion that RaceShapeEvaluator is weak would be too abstract.",
            "- The reproducible issue is narrower: RaceShape risk language and same-family pace/race-shape risk may be too coarse around PASS-success horses.",
            "",
            "## 7. Most Important Individual Examples",
            "",
        ]
    )
    examples = [
        row
        for row in details
        if row["dataset_group"] == "added_18" and row["primary_rs_pattern"] in {"RS-5", "RS-3", "RS-1"}
    ][:6]
    for row in examples:
        lines.extend(
            [
                f"### {row['race_id']} / {row['horse_name']}",
                "",
                f"- Finish: {row['finish_position']}",
                f"- AI rank: {row['ai_rank']}",
                f"- Decision: {row['official_decision']}",
                f"- Risk: {row['race_shape_risks']}",
                f"- Actual: {row['actual_race_summary']}",
                f"- Pattern: {row['primary_rs_pattern']} ({PATTERNS.get(str(row['primary_rs_pattern']), '')})",
                f"- Judgment: {row['final_race_shape_judgment']}",
                "",
            ]
        )

    lines.extend(
        [
            "## 8. First Improvement Candidate",
            "",
            f"- Candidate: {priority_rows[0]['candidate']}",
            f"- Target pattern: {priority_rows[0]['target_pattern']}",
            f"- Target horse count in 25: {priority_rows[0]['target_horse_count']}",
            "- This is a Shadow-only candidate. Do not directly change RaceShapeEvaluator.",
            "",
            "## 9. Limited Shadow Specification",
            "",
            "- Keep production Decision and RaceShapeEvaluator unchanged.",
            "- In Shadow only, when both 展開不向き and 展開面の不安 exist for the same horse, treat them as one same-family RaceShape/PACE risk for decision-impact diagnostics.",
            "- Measure target rescue, new FP, new BUY, existing BUY-success preservation, and non-target drift across all 40 races.",
            "",
            "## 10. Final Judgment",
            "",
            "Proceed to limited Shadow Validation only. There is enough evidence to test a narrow same-family RaceShape/PACE risk consolidation, but not enough evidence to relax RaceShapeEvaluator broadly.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    structure = parse_race_shape_structure()
    details = build_detail_rows()
    write_csv(REPORT_DIR / "race_shape_25horse_details.csv", details, DETAIL_FIELDS)
    write_summary_files(details, structure)

    result = {
        "target_horses": len(details),
        "target_races": len({row["race_id"] for row in details}),
        "dataset_group": dict(summarize(details)["dataset"]),
        "patterns": dict(summarize(details)["pattern"]),
        "judgments": dict(summarize(details)["judgment"]),
        "outputs": [
            str(REPORT_DIR / "race_shape_25horse_review.md"),
            str(REPORT_DIR / "race_shape_25horse_details.csv"),
            str(REPORT_DIR / "race_shape_pattern_summary.csv"),
            str(REPORT_DIR / "race_shape_reclassification_summary.csv"),
            str(REPORT_DIR / "race_shape_comparison_group.csv"),
            str(REPORT_DIR / "race_shape_shadow_candidate.md"),
            str(REPORT_DIR / "race_shape_improvement_priority.csv"),
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
