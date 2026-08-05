"""Validation report for BUY v1.0 RC1.

Runs the accepted Shadow v1.1 BUY policy as the RC1 candidate against the
40-race review population.  It does not run HOLD consensus rescue features.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine.buy_v1_rc1_engine import BUYV1RC1Engine
from review.ability_override_shadow_validator import load_population, to_float, to_int


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "buy_v1_rc1_validation"

LEGACY_FIELDS = [
    "race_id",
    "horse_name",
    "actual_finish",
    "actual_top3",
    "actual_top5",
    "ai_rank",
    "legacy_decision",
    "legacy_buy",
    "rc1_decision",
    "rc1_buy",
    "rc1_status",
    "rc1_race_state",
    "rc1_candidate",
    "legacy_buy_to_rc1_buy",
    "legacy_buy_to_unconverged",
    "legacy_buy_excluded",
    "rc1_new_buy",
    "final_score",
    "adjusted_score",
    "decision_score",
    "rc1_reason",
]

BUY_REPORT_FIELDS = [
    "race_id",
    "horse_name",
    "actual_finish",
    "ai_rank",
    "rc1_decision",
    "rc1_status",
    "rc1_race_state",
    "absolute_quality_pass",
    "relative_advantage_pass",
    "reliability_pass",
    "risk_guard_pass",
    "positive_evaluator_count",
    "negative_evaluator_count",
    "strong_positive_count",
    "strong_negative_count",
    "risk_count",
    "confidence",
    "rc1_reason",
]


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def to_engine_horse(row: dict[str, object]) -> dict[str, object]:
    """Map review-population rows to the shadow/RC1 engine input shape."""

    return {
        "horse_name": row.get("horse_name"),
        "decision": row.get("official_decision"),
        "rank": to_int(row.get("ai_rank"), 999),
        "final_score": to_float(row.get("final_score"), 0.0),
        "adjusted_score": to_float(row.get("adjusted_score"), 0.0),
        "decision_score": to_float(row.get("decision_score"), 0.0),
        "ability_score": to_float(row.get("ability_score"), None),
        "total_score": to_float(row.get("ability_score"), None),
        "past_performance_score": to_float(row.get("past_performance_score"), None),
        "distance_score": to_float(row.get("distance_score"), None),
        "course_score": to_float(row.get("course_score"), None),
        "course_shape_score": to_float(row.get("course_score"), None),
        "lap_suitability_score": to_float(row.get("lap_score"), None),
        "lap_score": to_float(row.get("lap_score"), None),
        "race_shape_score": to_float(row.get("race_shape_score"), None),
        "shape_score": to_float(row.get("race_shape_score"), None),
        "pace_score": to_float(row.get("pace_score"), None),
        "pace_style_score": to_float(row.get("pace_score"), None),
        "risk_reasons": row.get("risk_reasons") or "",
        "positive_reasons": row.get("positive_reasons") or "",
        "confidence": row.get("confidence"),
    }


def metrics(rows: list[dict[str, object]], decision_key: str) -> dict[str, object]:
    buy_rows = [row for row in rows if row.get(decision_key) == "BUY"]
    top3_buy = [row for row in buy_rows if row.get("actual_top3")]
    top5_buy = [row for row in buy_rows if row.get("actual_top5")]
    return {
        "BUY": len(buy_rows),
        "CAUTION": sum(1 for row in rows if row.get(decision_key) == "CAUTION"),
        "PASS": sum(1 for row in rows if row.get(decision_key) == "PASS"),
        "BUY_top3": len(top3_buy),
        "BUY_top5": len(top5_buy),
        "BUY_top3_rate": len(top3_buy) / len(buy_rows) if buy_rows else 0.0,
        "BUY_top5_rate": len(top5_buy) / len(buy_rows) if buy_rows else 0.0,
        "FN": sum(1 for row in rows if row.get("actual_top3") and row.get(decision_key) != "BUY"),
        "FP": sum(1 for row in rows if row.get(decision_key) == "BUY" and not row.get("actual_top3")),
    }


def main() -> None:
    rows, warnings = load_population()
    engine = BUYV1RC1Engine(enabled=True)
    by_race: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_race[str(row.get("race_id") or "")].append(row)

    comparison_rows: list[dict[str, object]] = []
    buy_report_rows: list[dict[str, object]] = []
    race_states = Counter()
    race_buy_counts = {}
    explain_missing = 0

    for race_id, race_rows in sorted(by_race.items()):
        engine_rows = [to_engine_horse(row) for row in race_rows]
        result = engine.evaluate(race_output={"race_id": race_id}, horses=engine_rows)
        records = {row.get("horse_name"): row for row in result.get("horse_records", [])}
        race_state = result.get("race_state", "")
        race_states[race_state] += 1
        race_buy_counts[race_id] = result.get("summary", {}).get("rc1_buy_count", 0)

        for source in race_rows:
            name = source.get("horse_name")
            record = records.get(name, {})
            profile = record.get("consensus_profile", {}) if isinstance(record.get("consensus_profile"), dict) else {}
            legacy_decision = str(source.get("official_decision") or "").upper()
            rc1_decision = record.get("rc1_decision") or legacy_decision
            rc1_status = record.get("rc1_status", "")
            reason = record.get("rc1_reason", "")
            if not reason:
                explain_missing += 1

            comparison_rows.append(
                {
                    "race_id": race_id,
                    "horse_name": name,
                    "actual_finish": source.get("actual_finish"),
                    "actual_top3": source.get("actual_top3"),
                    "actual_top5": source.get("actual_top5"),
                    "ai_rank": source.get("ai_rank"),
                    "legacy_decision": legacy_decision,
                    "legacy_buy": legacy_decision == "BUY",
                    "rc1_decision": rc1_decision,
                    "rc1_buy": rc1_decision == "BUY",
                    "rc1_status": rc1_status,
                    "rc1_race_state": race_state,
                    "rc1_candidate": record.get("rc1_candidate", False),
                    "legacy_buy_to_rc1_buy": legacy_decision == "BUY" and rc1_decision == "BUY",
                    "legacy_buy_to_unconverged": legacy_decision == "BUY"
                    and rc1_status == "RC1_CANDIDATE_UNCONVERGED_4PLUS",
                    "legacy_buy_excluded": legacy_decision == "BUY" and rc1_decision != "BUY",
                    "rc1_new_buy": legacy_decision != "BUY" and rc1_decision == "BUY",
                    "final_score": source.get("final_score"),
                    "adjusted_score": source.get("adjusted_score"),
                    "decision_score": source.get("decision_score"),
                    "rc1_reason": reason,
                }
            )
            buy_report_rows.append(
                {
                    "race_id": race_id,
                    "horse_name": name,
                    "actual_finish": source.get("actual_finish"),
                    "ai_rank": source.get("ai_rank"),
                    "rc1_decision": rc1_decision,
                    "rc1_status": rc1_status,
                    "rc1_race_state": race_state,
                    "absolute_quality_pass": record.get("absolute_quality_pass"),
                    "relative_advantage_pass": record.get("relative_advantage_pass"),
                    "reliability_pass": record.get("reliability_pass"),
                    "risk_guard_pass": record.get("risk_guard_pass"),
                    "positive_evaluator_count": profile.get("positive_evaluator_count"),
                    "negative_evaluator_count": profile.get("negative_evaluator_count"),
                    "strong_positive_count": profile.get("strong_positive_count"),
                    "strong_negative_count": profile.get("strong_negative_count"),
                    "risk_count": len(record.get("risk_summary", [])),
                    "confidence": record.get("confidence"),
                    "rc1_reason": reason,
                }
            )

    legacy_metrics = metrics(comparison_rows, "legacy_decision")
    rc1_metrics = metrics(comparison_rows, "rc1_decision")
    unconverged_rows = [
        row
        for row in comparison_rows
        if row.get("rc1_status") == "RC1_CANDIDATE_UNCONVERGED_4PLUS"
    ]
    skip_races = [race_id for race_id, count in race_buy_counts.items() if count == 0]
    legacy_buy_excluded = [row for row in comparison_rows if row.get("legacy_buy_excluded")]
    rc1_new_buy = [row for row in comparison_rows if row.get("rc1_new_buy")]

    write_csv(OUT_DIR / "legacy_comparison.csv", comparison_rows, LEGACY_FIELDS)
    write_csv(OUT_DIR / "buy_report.csv", buy_report_rows, BUY_REPORT_FIELDS)

    summary_data = {
        "race_count": len(by_race),
        "horse_count": len(comparison_rows),
        "legacy": legacy_metrics,
        "rc1": rc1_metrics,
        "race_states": dict(race_states),
        "unconverged_candidate_count": len(unconverged_rows),
        "unconverged_candidate_top3": sum(1 for row in unconverged_rows if row.get("actual_top3")),
        "legacy_buy_excluded": len(legacy_buy_excluded),
        "legacy_buy_success_excluded": sum(1 for row in legacy_buy_excluded if row.get("actual_top3")),
        "rc1_new_buy": len(rc1_new_buy),
        "rc1_new_buy_top3": sum(1 for row in rc1_new_buy if row.get("actual_top3")),
        "buy_zero_races": len(skip_races),
        "explain_missing": explain_missing,
        "warnings": warnings,
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    judgment = "ACCEPT" if explain_missing == 0 and len(comparison_rows) == 540 else "HOLD"
    summary_md = [
        "# BUY v1.0 RC1 Validation",
        "",
        "## RC1概要",
        "- Accepted Shadow v1.1 behavior promoted behind BUY_V1_RC1_ENABLED.",
        "- Consensus Targeted Rescue and threshold changes are not adopted.",
        "",
        "## 採用機能",
        "- BUY Specification / BUY 0頭許容 / PLAY-SKIP / PLAY_CONVERGED / PLAY_UNCONVERGED_4PLUS",
        "- 4頭以上候補保持 / Race State / Horse Status / Absolute Quality / Relative Advantage",
        "- Existing Consensus Reliability / Risk Guard / Explain fields",
        "",
        "## 採用しなかった機能",
        "- Consensus Targeted Rescue / positive_count=4 rescue / B1-B2-B3-C / consensus threshold changes",
        "",
        "## BUY結果",
        f"- 対象: {len(by_race)} races / {len(comparison_rows)} horses",
        f"- RC1 BUY: {rc1_metrics['BUY']}",
        f"- RC1 BUY 3着内: {rc1_metrics['BUY_top3']} ({rc1_metrics['BUY_top3_rate']:.1%})",
        f"- RC1 FN: {rc1_metrics['FN']}",
        f"- RC1 FP: {rc1_metrics['FP']}",
        "",
        "## Legacy比較",
        f"- Legacy BUY: {legacy_metrics['BUY']}",
        f"- Legacy BUY 3着内: {legacy_metrics['BUY_top3']} ({legacy_metrics['BUY_top3_rate']:.1%})",
        f"- Legacy FN: {legacy_metrics['FN']}",
        f"- Legacy FP: {legacy_metrics['FP']}",
        f"- Legacy BUY -> RC1 BUY: {sum(1 for row in comparison_rows if row.get('legacy_buy_to_rc1_buy'))}",
        f"- Legacy BUY formal除外: {len(legacy_buy_excluded)}",
        f"- RC1新規BUY: {len(rc1_new_buy)}",
        "",
        "## Race State",
        f"- PLAY_CONVERGED: {race_states.get('PLAY_CONVERGED', 0)}",
        f"- PLAY_UNCONVERGED_4PLUS: {race_states.get('PLAY_UNCONVERGED_4PLUS', 0)}",
        f"- SKIP: {race_states.get('SKIP', 0)}",
        f"- 未収束候補: {len(unconverged_rows)}",
        f"- BUY0レース: {len(skip_races)}",
        "",
        "## Explain確認",
        f"- RC1理由欠損: {explain_missing}",
        "",
        f"## RC1判定: {judgment}",
    ]
    (OUT_DIR / "summary.md").write_text("\n".join(summary_md) + "\n", encoding="utf-8")
    print(json.dumps(summary_data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
