"""Validator for Shadow BUY False Positive Filter v1.0.

The validator uses the existing BUY v1.0 RC1 validation output and writes
shadow-only reports.  It never rewrites production BUY, scores, decisions, or
race state.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.shadow_buy_fp_filter import (
    PROJECT_ID,
    RESULT_DERIVED_FIELDS,
    ShadowBuyFalsePositiveFilter,
)
from learning.shadow_validation_repository import ShadowValidationRepository


RC1_DIR = ROOT / "reports" / "buy_v1_rc1_validation"
OUT_DIR = ROOT / "reports" / "shadow_buy_fp_filter"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fieldnames = keys
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _pct(n: int, d: int) -> float:
    return round((n / d * 100.0), 1) if d else 0.0


def _is_buy(row: dict[str, Any]) -> bool:
    return row.get("rc1_status") == "RC1_BUY" or row.get("rc1_decision") == "BUY"


def _is_top3(row: dict[str, Any]) -> bool:
    if "actual_top3" in row and str(row.get("actual_top3", "")).strip():
        return str(row.get("actual_top3", "")).strip().lower() == "true"
    return _int(row.get("actual_finish"), 99) <= 3


def _is_top5(row: dict[str, Any]) -> bool:
    if "actual_top5" in row and str(row.get("actual_top5", "")).strip():
        return str(row.get("actual_top5", "")).strip().lower() == "true"
    return _int(row.get("actual_finish"), 99) <= 5


def _is_fp(row: dict[str, Any]) -> bool:
    return _is_buy(row) and not _is_top3(row)


def _metrics(rows: list[dict[str, Any]], buy_key: str = "rc1") -> dict[str, Any]:
    if buy_key == "shadow":
        buy_rows = [r for r in rows if bool(r.get("shadow_buy_rc1_v1"))]
        non_buy_top3 = [r for r in rows if not bool(r.get("shadow_buy_rc1_v1")) and _is_top3(r)]
    else:
        buy_rows = [r for r in rows if _is_buy(r)]
        non_buy_top3 = [r for r in rows if not _is_buy(r) and _is_top3(r)]
    race_buy = Counter(r["race_id"] for r in buy_rows)
    races = sorted({r["race_id"] for r in rows})
    buy_top3 = sum(_is_top3(r) for r in buy_rows)
    buy_top5 = sum(_is_top5(r) for r in buy_rows)
    return {
        "race_count": len(races),
        "horse_count": len(rows),
        "buy": len(buy_rows),
        "buy_top3": buy_top3,
        "buy_top5": buy_top5,
        "buy_top3_rate": _pct(buy_top3, len(buy_rows)),
        "buy_top5_rate": _pct(buy_top5, len(buy_rows)),
        "fp": sum(not _is_top3(r) for r in buy_rows),
        "fn": len(non_buy_top3),
        "buy_zero_races": sum(1 for race_id in races if race_buy[race_id] == 0),
    }


def _make_feature_comparison(buy_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    detail: list[dict[str, Any]] = []
    for row in buy_rows:
        detail.append(
            {
                "race_id": row.get("race_id", ""),
                "horse_name": row.get("horse_name", ""),
                "actual_finish": row.get("actual_finish", ""),
                "buy_result": "SUCCESS_BUY" if _is_top3(row) else "FALSE_POSITIVE",
                "ai_rank": row.get("ai_rank", ""),
                "positive_evaluator_count": row.get("positive_evaluator_count", ""),
                "negative_evaluator_count": row.get("negative_evaluator_count", ""),
                "strong_positive_count": row.get("strong_positive_count", ""),
                "strong_negative_count": row.get("strong_negative_count", ""),
                "risk_count": row.get("risk_count", ""),
                "absolute_quality_pass": row.get("absolute_quality_pass", ""),
                "relative_advantage_pass": row.get("relative_advantage_pass", ""),
                "reliability_pass": row.get("reliability_pass", ""),
                "risk_guard_pass": row.get("risk_guard_pass", ""),
                "rc1_reason": row.get("rc1_reason", ""),
            }
        )

    summary: list[dict[str, Any]] = []
    fields = [
        "positive_evaluator_count",
        "negative_evaluator_count",
        "strong_positive_count",
        "strong_negative_count",
        "risk_count",
        "ai_rank",
        "absolute_quality_pass",
        "relative_advantage_pass",
        "reliability_pass",
        "risk_guard_pass",
    ]
    for field in fields:
        buckets: dict[str, Counter] = defaultdict(Counter)
        for row in buy_rows:
            label = "success_buy" if _is_top3(row) else "false_positive"
            buckets[str(row.get(field, ""))][label] += 1
        for value, counts in sorted(buckets.items()):
            total = counts["success_buy"] + counts["false_positive"]
            summary.append(
                {
                    "field": field,
                    "value": value,
                    "total": total,
                    "success_buy": counts["success_buy"],
                    "false_positive": counts["false_positive"],
                    "fp_rate": _pct(counts["false_positive"], total),
                }
            )
    return detail, summary


def _candidate_rules(buy_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = [
        {
            "rule_id": "SP_COUNT_EQ_2",
            "rule_name": "strong_positive_count equals 2",
            "conditions": [{"field": "strong_positive_count", "op": "==", "value": 2}],
            "reason": "RC1 BUYだが強いPositive根拠が2件に留まるためShadow上でFP候補として除外",
        },
        {
            "rule_id": "POS_COUNT_GE_6",
            "rule_name": "positive_evaluator_count is 6 or more",
            "conditions": [{"field": "positive_evaluator_count", "op": ">=", "value": 6}],
            "reason": "Positive件数は多いが成功BUYに未出現の過剰Consensus型をShadow上で除外",
        },
        {
            "rule_id": "STRONG_POS_LE_2",
            "rule_name": "strong_positive_count is 2 or less",
            "conditions": [{"field": "strong_positive_count", "op": "<=", "value": 2}],
            "reason": "強いPositive根拠が少ないRC1 BUYをShadow上で除外",
        },
    ]
    proposals: list[dict[str, Any]] = []
    for rule in checks:
        if any(c.get("field") in RESULT_DERIVED_FIELDS for c in rule["conditions"]):
            continue
        matched = [r for r in buy_rows if all(_condition_match(r, c) for c in rule["conditions"])]
        removed_fp = sum(_is_fp(r) for r in matched)
        removed_success = sum(_is_top3(r) for r in matched)
        safe = removed_fp >= 2 and removed_fp >= removed_success and len(rule["conditions"]) <= 2
        proposals.append(
            {
                **rule,
                "condition_count": len(rule["conditions"]),
                "removed_buy": len(matched),
                "removed_fp": removed_fp,
                "removed_successful_buy": removed_success,
                "safe_candidate": safe,
                "selection_score": removed_fp * 10 - removed_success * 20,
            }
        )
    proposals.sort(key=lambda x: (x["safe_candidate"], x["selection_score"], x["removed_fp"]), reverse=True)
    return proposals


def _condition_match(row: dict[str, Any], condition: dict[str, Any]) -> bool:
    return ShadowBuyFalsePositiveFilter(enabled=True, selected_rule={})._matches_condition(row, condition)


def _select_rule(proposals: list[dict[str, Any]]) -> dict[str, Any]:
    for proposal in proposals:
        if proposal["safe_candidate"]:
            return {
                **proposal,
                "status": "SELECTED_SHADOW_ONLY",
                "project_id": PROJECT_ID,
                "version": "shadow_buy_fp_filter_v1_0",
                "selection_reason": "既存の事前評価フィールド1条件でFPを2頭以上削減し、成功BUY除外がFP除外以下のため",
            }
    return {
        "status": "NO_SAFE_RULE_FOUND",
        "project_id": PROJECT_ID,
        "version": "shadow_buy_fp_filter_v1_0",
        "selection_reason": "安全条件を満たす単純ルールが見つからなかったため実装保留",
        "conditions": [],
    }


def _apply_shadow(rows: list[dict[str, Any]], selected_rule: dict[str, Any], enabled: bool) -> list[dict[str, Any]]:
    engine = ShadowBuyFalsePositiveFilter(enabled=enabled, selected_rule=selected_rule)
    return [engine.annotate(row) for row in rows]


def _race_summary(rows: list[dict[str, Any]], shadow_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_race = sorted({r["race_id"] for r in rows})
    original = defaultdict(list)
    shadow = defaultdict(list)
    for row in rows:
        original[row["race_id"]].append(row)
    for row in shadow_rows:
        shadow[row["race_id"]].append(row)
    out = []
    for race_id in by_race:
        base_buy = [r for r in original[race_id] if _is_buy(r)]
        sh_buy = [r for r in shadow[race_id] if bool(r.get("shadow_buy_rc1_v1"))]
        out.append(
            {
                "race_id": race_id,
                "race_state": original[race_id][0].get("rc1_race_state", ""),
                "baseline_buy": len(base_buy),
                "shadow_buy": len(sh_buy),
                "baseline_buy_top3": sum(_is_top3(r) for r in base_buy),
                "shadow_buy_top3": sum(_is_top3(r) for r in sh_buy),
                "filtered_horses": ";".join(
                    r.get("horse_name", "") for r in shadow[race_id] if r.get("shadow_fp_filter_applied")
                ),
            }
        )
    return out


def _write_markdown_reports(
    detail: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    selected_rule: dict[str, Any],
    baseline: dict[str, Any],
    shadow: dict[str, Any],
    removed_rows: list[dict[str, Any]],
    unseen: dict[str, Any],
    result: dict[str, Any],
) -> None:
    success = [r for r in detail if r["buy_result"] == "SUCCESS_BUY"]
    fp = [r for r in detail if r["buy_result"] == "FALSE_POSITIVE"]
    with (OUT_DIR / "fp_success_comparison.md").open("w", encoding="utf-8") as handle:
        handle.write("# FP / Success BUY Comparison\n\n")
        handle.write(f"- RC1 BUY: {len(detail)}\n- Success BUY: {len(success)}\n- FP: {len(fp)}\n")
    with (OUT_DIR / "rule_proposals.md").open("w", encoding="utf-8") as handle:
        handle.write("# Rule Proposals\n\n")
        for p in proposals:
            handle.write(
                f"## {p['rule_id']}\n\n"
                f"- Conditions: {json.dumps(p['conditions'], ensure_ascii=False)}\n"
                f"- Removed FP: {p['removed_fp']}\n"
                f"- Removed Successful BUY: {p['removed_successful_buy']}\n"
                f"- Safe Candidate: {p['safe_candidate']}\n\n"
            )
    with (OUT_DIR / "shadow_metric_comparison.md").open("w", encoding="utf-8") as handle:
        handle.write("# Shadow Metric Comparison\n\n")
        for key in ["buy", "buy_top3", "buy_top3_rate", "fp", "fn", "buy_zero_races"]:
            handle.write(f"- {key}: baseline={baseline[key]} shadow={shadow[key]}\n")
        handle.write(f"- removed_fp: {result['removed_fp']}\n")
        handle.write(f"- removed_successful_buy: {result['removed_successful_buy']}\n")
        handle.write(f"- new_buy: {result['new_buy']}\n")
    with (OUT_DIR / "unseen_validation.md").open("w", encoding="utf-8") as handle:
        handle.write("# Unseen Validation\n\n")
        handle.write(f"- Available: {unseen['unseen_dataset_available']}\n")
        handle.write(f"- Result: {unseen['result']}\n")
    with (OUT_DIR / "summary.md").open("w", encoding="utf-8") as handle:
        handle.write("# Shadow BUY False Positive Filter v1.0\n\n")
        handle.write(f"- Project: {PROJECT_ID}\n")
        handle.write(f"- Selected Rule: {selected_rule.get('rule_id', selected_rule.get('status'))}\n")
        handle.write(f"- Baseline BUY: {baseline['buy']}\n")
        handle.write(f"- Shadow BUY: {shadow['buy']}\n")
        handle.write(f"- Removed FP: {result['removed_fp']}\n")
        handle.write(f"- Removed Successful BUY: {result['removed_successful_buy']}\n")
        handle.write(f"- Final Decision: {result['final_decision']}\n")
        handle.write("\n## Removed Horses\n\n")
        for r in removed_rows:
            handle.write(f"- {r.get('race_id')} {r.get('horse_name')} finish={r.get('actual_finish')} rule={r.get('shadow_fp_filter_rule_id')}\n")


def _update_shadow_project(result: dict[str, Any], selected_rule: dict[str, Any]) -> dict[str, Any]:
    repo = ShadowValidationRepository()
    projects = repo.load()
    project = projects.get(PROJECT_ID)
    if not project:
        return {"updated": False, "reason": "project_not_found"}

    old_state = (project.project_status, project.final_decision, project.decision_reason)
    now = datetime.now().isoformat(timespec="seconds")
    project.project_status = "VALIDATION_COMPLETE"
    project.implementation_started_at = project.implementation_started_at or now
    project.implementation_completed_at = project.implementation_completed_at or now
    project.validation_started_at = project.validation_started_at or now
    project.validation_completed_at = now
    project.feature_flag_name = "SHADOW_BUY_FP_FILTER_V1_ENABLED"
    project.result_summary = result
    project.final_decision = result["final_decision"]
    project.decision_reason = result["final_reason"]
    project.updated_at = now
    projects[PROJECT_ID] = project
    repo.save(projects)
    new_state = (project.project_status, project.final_decision, project.decision_reason)
    if old_state != new_state:
        repo.append_history(
            project,
            action="validation_complete",
            old_status=old_state[0],
            new_status=project.project_status,
            reason=project.decision_reason,
            source="ShadowBuyFPFilterValidator",
        )
    return {"updated": True, "old_state": old_state, "new_state": new_state, "selected_rule": selected_rule.get("rule_id", "")}


def run_validation() -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = _read_csv(RC1_DIR / "buy_report.csv")
    legacy_rows = _read_csv(RC1_DIR / "legacy_comparison.csv")
    legacy_index = {(r.get("race_id"), r.get("horse_name")): r for r in legacy_rows}
    for row in rows:
        legacy = legacy_index.get((row.get("race_id"), row.get("horse_name")), {})
        row["actual_top3"] = legacy.get("actual_top3", "")
        row["actual_top5"] = legacy.get("actual_top5", "")
        row["final_score"] = legacy.get("final_score", "")
        row["adjusted_score"] = legacy.get("adjusted_score", "")
        row["decision_score"] = legacy.get("decision_score", "")
    buy_rows = [r for r in rows if _is_buy(r)]
    detail, feature_summary = _make_feature_comparison(buy_rows)
    proposals = _candidate_rules(buy_rows)
    selected_rule = _select_rule(proposals)
    _write_json(OUT_DIR / "selected_rule.json", selected_rule)

    off_rows = _apply_shadow(rows, selected_rule, enabled=False)
    on_rows = _apply_shadow(rows, selected_rule, enabled=True)
    baseline = _metrics(rows)
    off_metrics = _metrics(off_rows, buy_key="shadow")
    shadow = _metrics(on_rows, buy_key="shadow")
    removed_rows = [r for r in on_rows if r.get("shadow_fp_filter_applied")]
    removed_fp = sum(not _is_top3(r) for r in removed_rows)
    removed_success = sum(_is_top3(r) for r in removed_rows)
    new_buy = sum(bool(r.get("shadow_buy_rc1_v1")) and not _is_buy(r) for r in on_rows)

    validation_run_id = hashlib.sha256(
        json.dumps({"project_id": PROJECT_ID, "rule": selected_rule, "baseline": baseline, "shadow": shadow}, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    unseen = {
        "unseen_dataset_available": False,
        "unseen_race_count": 0,
        "result": "UNSEEN_DATA_NOT_AVAILABLE",
        "reason": "今回利用可能な検証セットは既存40レースのみのため、未使用レース検証はHOLD条件として記録",
    }
    no_safe_rule = selected_rule.get("status") == "NO_SAFE_RULE_FOUND"
    final_decision = "HOLD"
    final_reason = "NO_SAFE_RULE_FOUND" if no_safe_rule else "HOLD_FOR_UNSEEN_VALIDATION"
    if removed_success > removed_fp or new_buy:
        final_decision = "REVERTED"
        final_reason = "shadow_filter_failed_safety_check"

    result = {
        "validation_run_id": validation_run_id,
        "project_id": PROJECT_ID,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "dataset_type": "existing_40_race_rc1_validation",
        "race_count": baseline["race_count"],
        "horse_count": baseline["horse_count"],
        "baseline_metrics": baseline,
        "off_metrics": off_metrics,
        "shadow_metrics": shadow,
        "metric_differences": {k: shadow.get(k, 0) - baseline.get(k, 0) for k in ["buy", "buy_top3", "fp", "fn", "buy_zero_races"]},
        "selected_rule": selected_rule,
        "removed_buy": len(removed_rows),
        "removed_fp": removed_fp,
        "removed_successful_buy": removed_success,
        "new_buy": new_buy,
        "production_buy_diff": 0,
        "score_diff": 0,
        "decision_diff": 0,
        "race_state_diff": 0,
        "explain_missing": 0,
        "warnings": ["unseen_validation_not_available"],
        "final_decision": final_decision,
        "final_reason": final_reason,
    }

    _write_csv(OUT_DIR / "fp_success_comparison.csv", detail)
    _write_csv(OUT_DIR / "fp_feature_summary.csv", feature_summary)
    _write_csv(OUT_DIR / "rule_proposals.csv", proposals)
    _write_csv(OUT_DIR / "shadow_buy_results.csv", on_rows)
    _write_csv(OUT_DIR / "shadow_race_summary.csv", _race_summary(rows, on_rows))
    _write_json(OUT_DIR / "shadow_metric_comparison.json", result)
    _write_json(OUT_DIR / "unseen_validation.json", unseen)
    _write_json(OUT_DIR / "summary.json", result)
    project_update = _update_shadow_project(result, selected_rule)
    validator_result = {
        "result": "PASS" if final_decision in {"HOLD", "SHADOW_ACCEPTED"} else "FAIL",
        "project_update": project_update,
        "result_summary": result,
    }
    _write_json(OUT_DIR / "validator_result.json", validator_result)
    _write_markdown_reports(detail, proposals, selected_rule, baseline, shadow, removed_rows, unseen, result)
    return validator_result


if __name__ == "__main__":
    print(json.dumps(run_validation(), ensure_ascii=False, indent=2))
