"""PhaseG Step5 relative-ranking diagnostic reports.

This module is diagnostic only. It reads the existing 22-race baseline through
the current analysis/result adapters, compares AI rank with official finish,
and writes reports. It does not change evaluator logic, scores, decisions,
knowledge, CSV definitions, or main.py.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import statistics
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine.overall_22race_health_check import Overall22RaceHealthCheck


class RelativeRankingBreakdown:
    """Diagnose whether within-race AI ordering is appropriate."""

    VERSION = "phase_g_step5_v1"
    EXPECTED = Overall22RaceHealthCheck.EXPECTED
    REPORTS = {
        "breakdown": Path("reports/relative_ranking_breakdown.md"),
        "metrics": Path("reports/relative_ranking_metrics.json"),
        "cases": Path("reports/relative_ranking_cases.md"),
        "condition": Path("reports/relative_ranking_condition_analysis.md"),
        "judgment": Path("reports/relative_ranking_final_judgment.md"),
    }

    def run(self, analysis_dir="data/analysis", results_dir="data/results"):
        generated_at = datetime.now(timezone.utc).isoformat()
        health = Overall22RaceHealthCheck()
        races, rows, errors = health._collect(analysis_dir, results_dir)
        baseline = health._baseline(rows)
        race_summaries = self._race_summaries(races)
        top5 = self._top5_analysis(rows)
        boundary = self._buy_boundary_analysis(races)
        reversals = self._reversal_cases(races)
        reversal_counts = Counter(row.get("reversal_type") for row in reversals)
        margin_counts = Counter(row.get("margin_class") for row in reversals)
        cause_counts = Counter(row.get("cause_class") for row in reversals)
        condition = self._condition_analysis(reversals)
        judgment = self._judgment(baseline, top5, reversals, cause_counts)
        metrics = {
            "validation_version": self.VERSION,
            "generated_at": generated_at,
            "baseline": baseline,
            "expected_baseline": self.EXPECTED,
            "baseline_match": baseline == self.EXPECTED,
            "errors": errors,
            "race_count": len(races),
            "horse_count": len(rows),
            "race_rank_summary": race_summaries,
            "top5_analysis": top5,
            "buy_boundary_analysis": boundary,
            "reversal_count": len(reversals),
            "reversal_type_counts": dict(reversal_counts),
            "close_reversal_count": margin_counts.get("CLOSE", 0),
            "medium_reversal_count": margin_counts.get("MEDIUM", 0),
            "large_reversal_count": margin_counts.get("LARGE", 0),
            "margin_class_counts": dict(margin_counts),
            "cause_class_counts": dict(cause_counts),
            "condition_dependency": condition,
            "ranking_issue_count": cause_counts.get("RANKING_ISSUE", 0),
            "input_data_count": cause_counts.get("INPUT_DATA_LIMITATION", 0),
            "randomness_count": cause_counts.get("RANDOMNESS", 0),
            "improvement_candidate_exists": judgment.get("improvement_candidate_exists"),
            "shadow_candidate_exists": False,
            "relative_ranking_judgment": judgment,
            "official_baseline_unchanged": baseline == self.EXPECTED,
            "diagnostic_only": True,
            "final_judgment": "ACCEPT" if baseline == self.EXPECTED and not errors else "REANALYSIS_REQUIRED",
        }
        self._write_outputs(metrics, reversals)
        learning_update = self._update_learning_candidate(metrics)
        metrics["learning_candidate_update"] = learning_update
        self._write_json(self.REPORTS["metrics"], metrics)
        return metrics

    def _race_summaries(self, races):
        summaries = []
        for race in races:
            rows = [row for row in race.get("rows", []) if self._to_int(row.get("finish_position")) is not None]
            diffs = [abs((row.get("ai_rank") or 0) - (row.get("finish_position") or 0)) for row in rows]
            signed = [(row.get("ai_rank") or 0) - (row.get("finish_position") or 0) for row in rows]
            summaries.append(
                {
                    "race_id": race.get("race_id"),
                    "racecourse": self._context(race).get("racecourse"),
                    "surface": self._context(race).get("surface"),
                    "distance": self._context(race).get("distance"),
                    "track_condition": self._context(race).get("track_condition"),
                    "field_size": len(rows),
                    "mean_abs_rank_error": round(statistics.mean(diffs), 3) if diffs else 0,
                    "median_abs_rank_error": round(statistics.median(diffs), 3) if diffs else 0,
                    "max_abs_rank_error": max(diffs) if diffs else 0,
                    "mean_signed_rank_error": round(statistics.mean(signed), 3) if signed else 0,
                    "ai_top1_finish": self._finish_of_rank(rows, 1),
                    "top5_top3_count": sum(1 for row in rows if (row.get("ai_rank") or 99) <= 5 and row.get("finish_position") in {1, 2, 3}),
                    "top5_board_count": sum(1 for row in rows if (row.get("ai_rank") or 99) <= 5 and (row.get("finish_position") or 99) <= 5),
                    "top5_pass_count": sum(1 for row in rows if (row.get("ai_rank") or 99) <= 5 and row.get("decision") == "PASS"),
                    "ai8_or_lower_actual_top3": sum(1 for row in rows if (row.get("ai_rank") or 0) >= 8 and row.get("finish_position") in {1, 2, 3}),
                    "ai_top3_actual_out": sum(1 for row in rows if (row.get("ai_rank") or 99) <= 3 and (row.get("finish_position") or 0) > 5),
                    "ai4_6_actual_win": sum(1 for row in rows if 4 <= (row.get("ai_rank") or 99) <= 6 and row.get("finish_position") == 1),
                }
            )
        return summaries

    def _top5_analysis(self, rows):
        top5_rows = [row for row in rows if (row.get("ai_rank") or 99) <= 5]
        pass_rows = [row for row in top5_rows if row.get("decision") == "PASS"]
        return {
            "target_count": len(top5_rows),
            "actual_top3_count": sum(1 for row in top5_rows if row.get("finish_position") in {1, 2, 3}),
            "actual_board_count": sum(1 for row in top5_rows if (row.get("finish_position") or 99) <= 5),
            "actual_out_count": sum(1 for row in top5_rows if (row.get("finish_position") or 0) > 5),
            "top5_pass_count": len(pass_rows),
            "top5_pass_top3_count": sum(1 for row in pass_rows if row.get("finish_position") in {1, 2, 3}),
            "top5_pass_board_count": sum(1 for row in pass_rows if (row.get("finish_position") or 99) <= 5),
            "top5_decision_counts": dict(Counter(row.get("decision") for row in top5_rows)),
        }

    def _buy_boundary_analysis(self, races):
        records = []
        for race in races:
            rows = race.get("rows") or []
            buy = [row for row in rows if row.get("decision") == "BUY"]
            caution = [row for row in rows if row.get("decision") == "CAUTION"]
            passed = [row for row in rows if row.get("decision") == "PASS"]
            buy_worst = max((row.get("ai_rank") or 0 for row in buy), default=None)
            caution_best = min((row.get("ai_rank") or 99 for row in caution), default=None)
            pass_best = min((row.get("ai_rank") or 99 for row in passed), default=None)
            records.append(
                {
                    "race_id": race.get("race_id"),
                    "buy_count": len(buy),
                    "buy_lowest_rank": buy_worst,
                    "caution_top_rank": caution_best,
                    "pass_top_rank": pass_best,
                    "caution_above_buy": bool(buy_worst and caution_best and caution_best < buy_worst),
                    "pass_above_buy": bool(buy_worst and pass_best and pass_best < buy_worst),
                    "boundary_comment": self._boundary_comment(buy_worst, caution_best, pass_best),
                }
            )
        return {
            "records": records,
            "caution_above_buy_count": sum(1 for row in records if row.get("caution_above_buy")),
            "pass_above_buy_count": sum(1 for row in records if row.get("pass_above_buy")),
            "buy_zero_count": sum(1 for row in records if row.get("buy_count") == 0),
        }

    def _reversal_cases(self, races):
        cases = []
        for race in races:
            rows = sorted(race.get("rows") or [], key=lambda row: row.get("ai_rank") or 99)
            ai1 = rows[0] if rows else {}
            for row in rows:
                reversal_type = self._reversal_type(row)
                if not reversal_type:
                    continue
                score_gap = self._score_gap(ai1, row, "final_score")
                adjusted_gap = self._score_gap(ai1, row, "adjusted_score")
                impact_gap = self._score_gap(ai1, row, "impact_score")
                record = {
                    "race_id": row.get("race_id"),
                    "horse_number": row.get("horse_number"),
                    "horse_name": row.get("horse_name"),
                    "racecourse": row.get("racecourse"),
                    "surface": row.get("surface"),
                    "distance": row.get("distance"),
                    "distance_category": row.get("distance_category"),
                    "track_condition": row.get("track_condition"),
                    "running_style": row.get("running_style"),
                    "fourth_corner_bucket": row.get("fourth_corner_bucket"),
                    "decision": row.get("decision"),
                    "ai_rank": row.get("ai_rank"),
                    "finish_position": row.get("finish_position"),
                    "final_score": row.get("final_score"),
                    "adjusted_score": row.get("adjusted_score"),
                    "impact_score": (row.get("scores") or {}).get("impact_score"),
                    "score_gap_to_ai1": score_gap,
                    "adjusted_gap_to_ai1": adjusted_gap,
                    "impact_gap_to_ai1": impact_gap,
                    "reversal_type": reversal_type,
                    "margin_class": self._margin_class(score_gap, adjusted_gap),
                    "cause_class": self._cause_class(row, score_gap, adjusted_gap),
                    "primary_cause": row.get("primary_cause"),
                    "secondary_causes": row.get("secondary_causes") or [],
                    "data_limitations": row.get("data_limitations") or [],
                }
                cases.append(record)
        return cases

    def _condition_analysis(self, cases):
        specs = ["racecourse", "surface", "distance_category", "track_condition", "running_style", "fourth_corner_bucket", "decision", "cause_class"]
        details = {}
        for spec in specs:
            groups = defaultdict(list)
            for row in cases:
                groups[row.get(spec) or "unknown"].append(row)
            details[spec] = [
                {
                    "value": value,
                    "count": len(group),
                    "races": len({row.get("race_id") for row in group}),
                    "AI8_actual_top3": sum(1 for row in group if row.get("reversal_type") == "AI8_OR_LOWER_ACTUAL_TOP3"),
                    "AI1_3_actual_out": sum(1 for row in group if row.get("reversal_type") == "AI_TOP3_ACTUAL_OUT"),
                    "AI4_6_actual_win": sum(1 for row in group if row.get("reversal_type") == "AI4_6_ACTUAL_WIN"),
                }
                for value, group in sorted(groups.items(), key=lambda item: (-len(item[1]), str(item[0])))
            ]
        top = {}
        for spec, rows in details.items():
            top[spec] = rows[0] if rows else {}
        return {"top_segments": top, "details": details}

    def _judgment(self, baseline, top5, reversals, cause_counts):
        large = sum(1 for row in reversals if row.get("margin_class") == "LARGE")
        ranking_issue = cause_counts.get("RANKING_ISSUE", 0)
        top5_rate = top5.get("actual_top3_count", 0) / top5.get("target_count", 1)
        if baseline != self.EXPECTED:
            status = "STRUCTURAL_ISSUE"
            reason = "Official baseline did not match."
        elif ranking_issue >= 20 or large >= 25:
            status = "STRUCTURAL_ISSUE"
            reason = "Large rank inversions are frequent enough to question ranking structure."
        elif ranking_issue >= 8 or large >= 10:
            status = "LIMITED_REVIEW"
            reason = "Ranking-specific issue exists, but it should be reviewed narrowly."
        elif top5_rate >= 0.25:
            status = "MOSTLY_SOUND"
            reason = "Top5 captures enough actual Top3 cases, while reversals are mixed and condition-dependent."
        else:
            status = "LIMITED_REVIEW"
            reason = "Top5 capture is low enough to require focused ranking review."
        return {
            "status": status,
            "reason": reason,
            "improvement_candidate_exists": status in {"LIMITED_REVIEW", "STRUCTURAL_ISSUE"},
            "recommended_next_step": "RELATIVE_RANKING_LIMITED_REVIEW" if status == "LIMITED_REVIEW" else "NO_RANKING_FIX" if status == "MOSTLY_SOUND" else "REANALYSIS_REQUIRED",
        }

    def _write_outputs(self, metrics, cases):
        self._write_json(self.REPORTS["metrics"], metrics)
        self._write_md(self.REPORTS["breakdown"], self._breakdown_report(metrics))
        self._write_md(self.REPORTS["cases"], self._cases_report(cases))
        self._write_md(self.REPORTS["condition"], self._condition_report(metrics.get("condition_dependency")))
        self._write_md(self.REPORTS["judgment"], self._judgment_report(metrics))

    def _breakdown_report(self, metrics):
        lines = [
            "# Relative Ranking Breakdown",
            "",
            f"- Generated: {metrics.get('generated_at')}",
            f"- Validation version: {self.VERSION}",
            f"- Baseline match: {metrics.get('baseline_match')}",
            "",
            "## Baseline",
            "",
            "| item | actual | expected |",
            "|---|---:|---:|",
        ]
        for key, expected in self.EXPECTED.items():
            lines.append(f"| {key} | {metrics.get('baseline', {}).get(key)} | {expected} |")
        top5 = metrics.get("top5_analysis") or {}
        lines.extend(
            [
                "",
                "## Top5 Analysis",
                "",
                json.dumps(top5, ensure_ascii=False, indent=2),
                "",
                "## Reversal Counts",
                "",
                json.dumps(metrics.get("reversal_type_counts"), ensure_ascii=False, indent=2),
                "",
                "## Margin Classes",
                "",
                json.dumps(metrics.get("margin_class_counts"), ensure_ascii=False, indent=2),
                "",
                "## Cause Classes",
                "",
                json.dumps(metrics.get("cause_class_counts"), ensure_ascii=False, indent=2),
                "",
                "## Race Rank Summary",
                "",
                "| race_id | mean_abs | median_abs | max_abs | AI1 finish | Top5 Top3 | Top5 board | Top5 PASS |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in metrics.get("race_rank_summary") or []:
            lines.append(
                f"| {row.get('race_id')} | {row.get('mean_abs_rank_error')} | {row.get('median_abs_rank_error')} | "
                f"{row.get('max_abs_rank_error')} | {row.get('ai_top1_finish')} | {row.get('top5_top3_count')} | "
                f"{row.get('top5_board_count')} | {row.get('top5_pass_count')} |"
            )
        return "\n".join(lines) + "\n"

    def _cases_report(self, cases):
        lines = [
            "# Relative Ranking Cases",
            "",
            "| race_id | horse | type | AI rank | finish | decision | final | adjusted | score gap | adjusted gap | impact gap | margin | cause | primary |",
            "|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---|---|---|",
        ]
        for row in cases:
            lines.append(
                f"| {row.get('race_id')} | {row.get('horse_name')} | {row.get('reversal_type')} | "
                f"{row.get('ai_rank')} | {row.get('finish_position')} | {row.get('decision')} | "
                f"{row.get('final_score')} | {row.get('adjusted_score')} | {row.get('score_gap_to_ai1')} | "
                f"{row.get('adjusted_gap_to_ai1')} | {row.get('impact_gap_to_ai1')} | {row.get('margin_class')} | "
                f"{row.get('cause_class')} | {row.get('primary_cause')} |"
            )
        return "\n".join(lines) + "\n"

    def _condition_report(self, condition):
        lines = ["# Relative Ranking Condition Analysis", ""]
        for spec, rows in (condition or {}).get("details", {}).items():
            lines.extend(
                [
                    f"## {spec}",
                    "",
                    "| value | count | races | AI8 actual Top3 | AI1-3 actual out | AI4-6 actual win |",
                    "|---|---:|---:|---:|---:|---:|",
                ]
            )
            for row in rows:
                lines.append(
                    f"| {row.get('value')} | {row.get('count')} | {row.get('races')} | "
                    f"{row.get('AI8_actual_top3')} | {row.get('AI1_3_actual_out')} | {row.get('AI4_6_actual_win')} |"
                )
            lines.append("")
        return "\n".join(lines) + "\n"

    def _judgment_report(self, metrics):
        judgment = metrics.get("relative_ranking_judgment") or {}
        boundary = metrics.get("buy_boundary_analysis") or {}
        lines = [
            "# Relative Ranking Final Judgment",
            "",
            f"- Status: {judgment.get('status')}",
            f"- Reason: {judgment.get('reason')}",
            f"- Improvement candidate exists: {metrics.get('improvement_candidate_exists')}",
            f"- Shadow candidate exists: {metrics.get('shadow_candidate_exists')}",
            f"- Final judgment: {metrics.get('final_judgment')}",
            "",
            "## BUY Boundary",
            "",
            f"- caution_above_buy_count: {boundary.get('caution_above_buy_count')}",
            f"- pass_above_buy_count: {boundary.get('pass_above_buy_count')}",
            f"- buy_zero_count: {boundary.get('buy_zero_count')}",
            "",
            "## Boundary Records",
            "",
            "| race_id | BUY | BUY lowest rank | CAUTION top rank | PASS top rank | comment |",
            "|---|---:|---:|---:|---:|---|",
        ]
        for row in boundary.get("records") or []:
            lines.append(
                f"| {row.get('race_id')} | {row.get('buy_count')} | {row.get('buy_lowest_rank')} | "
                f"{row.get('caution_top_rank')} | {row.get('pass_top_rank')} | {row.get('boundary_comment')} |"
            )
        return "\n".join(lines) + "\n"

    def _update_learning_candidate(self, metrics):
        path = Path("learning/improvement_candidates.json")
        database = self._load_json(path, {"version": "1.0", "engine": "LearningCandidateEngine", "records": [], "aggregates": []})
        records = database.setdefault("records", [])
        now = datetime.now(timezone.utc).isoformat()
        record = None
        for item in records:
            if item.get("candidate_id") == "relative_ranking_breakdown":
                record = item
                break
        if record is None:
            record = {
                "candidate_id": "relative_ranking_breakdown",
                "race_id": "phase_g_step5_relative_ranking",
                "horse": "overall_relative_ranking",
                "case_type": "SYSTEM_DIAGNOSTIC",
                "decision": "N/A",
                "actual_finish": None,
                "fn": False,
                "fp": False,
                "primary_candidate": "RelativeRankingBreakdown",
                "status": "NEW",
                "priority": "medium",
                "created_at": now,
            }
            records.append(record)
        record.update(
            {
                "status": record.get("status", "NEW"),
                "baseline": metrics.get("baseline"),
                "relative_ranking_status": (metrics.get("relative_ranking_judgment") or {}).get("status"),
                "top5_analysis": metrics.get("top5_analysis"),
                "buy_boundary_analysis": {
                    "caution_above_buy_count": (metrics.get("buy_boundary_analysis") or {}).get("caution_above_buy_count"),
                    "pass_above_buy_count": (metrics.get("buy_boundary_analysis") or {}).get("pass_above_buy_count"),
                    "buy_zero_count": (metrics.get("buy_boundary_analysis") or {}).get("buy_zero_count"),
                },
                "reversal_count": metrics.get("reversal_count"),
                "reversal_type_counts": metrics.get("reversal_type_counts"),
                "margin_class_counts": metrics.get("margin_class_counts"),
                "cause_class_counts": metrics.get("cause_class_counts"),
                "improvement_candidate_exists": metrics.get("improvement_candidate_exists"),
                "shadow_candidate_exists": metrics.get("shadow_candidate_exists"),
                "recommended_next_step": (metrics.get("relative_ranking_judgment") or {}).get("recommended_next_step"),
                "official_baseline_unchanged": metrics.get("official_baseline_unchanged"),
                "diagnostic_only": True,
                "note": "Diagnostic-only PhaseG Step5 record; no evaluator, score, Decision, Knowledge, CSV, or main.py logic was changed.",
                "updated_at": now,
                "ranking_active": True,
            }
        )
        database["updated_at"] = now
        self._write_json(path, database)
        return {"candidate_id": record.get("candidate_id"), "updated": True, "status": record.get("status")}

    def _reversal_type(self, row):
        rank = self._to_int(row.get("ai_rank")) or 99
        finish = self._to_int(row.get("finish_position")) or 99
        if rank >= 8 and finish <= 3:
            return "AI8_OR_LOWER_ACTUAL_TOP3"
        if rank <= 3 and finish > 5:
            return "AI_TOP3_ACTUAL_OUT"
        if 4 <= rank <= 6 and finish == 1:
            return "AI4_6_ACTUAL_WIN"
        return None

    def _margin_class(self, score_gap, adjusted_gap):
        comparable = min(abs(score_gap or 0), abs(adjusted_gap or 0))
        if comparable <= 5:
            return "CLOSE"
        if comparable <= 15:
            return "MEDIUM"
        return "LARGE"

    def _cause_class(self, row, score_gap, adjusted_gap):
        if row.get("data_limitations"):
            return "INPUT_DATA_LIMITATION"
        if self._margin_class(score_gap, adjusted_gap) == "CLOSE":
            return "CLOSE_SCORE"
        if row.get("primary_cause") in {"RaceShapeEvaluator", "PaceStyleEvaluator", "TrackBiasEvaluator", "CourseEvaluator"}:
            return "CONDITION_DEPENDENT"
        if row.get("case_type") in {"FN", "FP"}:
            return "RANKING_ISSUE"
        return "RANDOMNESS"

    def _score_gap(self, ai1, row, key):
        if key == "impact_score":
            left = ((ai1.get("scores") or {}).get(key))
            right = ((row.get("scores") or {}).get(key))
        else:
            left = ai1.get(key)
            right = row.get(key)
        left = self._to_float(left)
        right = self._to_float(right)
        if left is None or right is None:
            return None
        return round(left - right, 3)

    def _boundary_comment(self, buy_worst, caution_best, pass_best):
        if buy_worst is None:
            return "No BUY in race."
        if pass_best and pass_best < buy_worst:
            return "PASS horse ranked above lowest BUY."
        if caution_best and caution_best < buy_worst:
            return "CAUTION horse ranked above lowest BUY."
        return "Decision boundary follows ranking order."

    def _finish_of_rank(self, rows, rank):
        for row in rows:
            if row.get("ai_rank") == rank:
                return row.get("finish_position")
        return None

    def _context(self, race):
        return race.get("race_context") or {}

    def _load_json(self, path, default):
        path = Path(path)
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path, payload):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_md(self, path, text):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _to_int(self, value):
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def _to_float(self, value):
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None


if __name__ == "__main__":
    result = RelativeRankingBreakdown().run()
    print(
        {
            "baseline_match": result.get("baseline_match"),
            "reversal_count": result.get("reversal_count"),
            "status": (result.get("relative_ranking_judgment") or {}).get("status"),
            "final_judgment": result.get("final_judgment"),
        }
    )
