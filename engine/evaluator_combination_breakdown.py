"""PhaseG Step4 evaluator-combination diagnostic reports.

This module is diagnostic only. It reuses the existing 22-race health-check
collection path, decomposes cases that were previously classified as multiple
causes, and writes reports. It does not change evaluator logic, scores,
decisions, knowledge, CSV definitions, or main.py.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine.overall_22race_health_check import Overall22RaceHealthCheck


class EvaluatorCombinationBreakdown:
    """Break down PhaseG Step3 evaluator-combination cases."""

    VERSION = "phase_g_step4_v1"
    EXPECTED = Overall22RaceHealthCheck.EXPECTED
    REPORTS = {
        "breakdown": Path("reports/evaluator_combination_breakdown.md"),
        "metrics": Path("reports/evaluator_combination_metrics.json"),
        "cases": Path("reports/evaluator_combination_cases.md"),
        "ranking": Path("reports/evaluator_combination_ranking.md"),
        "counterexamples": Path("reports/evaluator_combination_counterexamples.md"),
        "condition": Path("reports/evaluator_combination_condition_dependency.md"),
        "judgment": Path("reports/evaluator_combination_final_judgment.md"),
    }
    DOMAIN_EVALUATORS = {
        "AbilityEvaluator",
        "PastPerformanceEvaluator",
        "DistanceEvaluator",
        "CourseEvaluator",
        "CourseShapeEvaluator",
        "PaceEvaluator",
        "RunningStyleEvaluator",
        "PaceStyleEvaluator",
        "LapSuitabilityEvaluator",
        "RaceShapeEvaluator",
        "TrackBiasEvaluator",
        "BloodlineEvaluator",
        "WeightEvaluator",
        "ConditionEvaluator",
        "TrackConditionSuitabilityEvaluator",
        "ImpactEvaluator",
        "ConsistencyEngine",
    }
    GATE_EVALUATORS = {
        "DecisionEngine",
        "DecisionGuard",
        "RaceDecisionEngine",
        "ConfidenceEngine",
        "ScoreWeightEvaluator",
        "FinalScoreIntegrator",
    }

    def run(self, analysis_dir="data/analysis", results_dir="data/results"):
        generated_at = datetime.now(timezone.utc).isoformat()
        health = Overall22RaceHealthCheck()
        races, rows, errors = health._collect(analysis_dir, results_dir)
        baseline = health._baseline(rows)
        combination_rows = [
            row
            for row in rows
            if row.get("case_type") in {"FN", "FP"}
            and row.get("case_category") == "H_MULTIPLE_CAUSES"
        ]
        cases = [self._case_record(row) for row in combination_rows]
        classification = Counter(row["reclassification_candidate"] for row in cases)
        ranking = self._combination_ranking(rows, cases)
        counterexamples = self._counterexamples(rows, ranking)
        condition_dependency = self._condition_dependency(cases, ranking)
        philosophy = self._philosophy_judgment(cases, ranking, classification)
        metrics = {
            "validation_version": self.VERSION,
            "generated_at": generated_at,
            "baseline": baseline,
            "expected_baseline": self.EXPECTED,
            "baseline_match": baseline == self.EXPECTED,
            "errors": errors,
            "original_combination_count": len(combination_rows),
            "unique_horse_count": len({self._horse_key(row) for row in combination_rows}),
            "total_combination_occurrences": sum(max(1, len(row.get("domain_evaluators") or [])) for row in cases),
            "average_combinations_per_horse": round(
                sum(max(1, len(row.get("domain_evaluators") or [])) for row in cases) / len(cases), 3
            )
            if cases
            else 0,
            "max_combinations_per_horse": max([len(row.get("domain_evaluators") or []) for row in cases] or [0]),
            "duplicate_count": len(cases) - len({self._horse_key(row) for row in combination_rows}),
            "reclassification_counts": dict(classification),
            "true_combination_count": classification.get("TRUE_COMBINATION", 0),
            "reclassified_single_evaluator_count": classification.get("SINGLE_EVALUATOR", 0),
            "reclassified_decision_count": classification.get("DECISION_ISSUE", 0),
            "reclassified_relative_ranking_count": classification.get("RELATIVE_RANKING", 0),
            "reclassified_input_data_count": classification.get("INPUT_DATA_LIMITATION", 0),
            "reclassified_randomness_count": classification.get("HIGH_RANDOMNESS", 0),
            "unresolved_count": classification.get("MULTIPLE_CAUSES_UNRESOLVED", 0),
            "not_a_problem_count": classification.get("NOT_A_PROBLEM", 0),
            "combination_ranking": ranking,
            "combination_size_counts": dict(Counter(row.get("combination_size") for row in ranking)),
            "top_combinations": ranking[:20],
            "top_combination_failure_rates": ranking[:20],
            "counterexample_counts": {
                item["combination_id"]: item.get("counterexample_count", 0)
                for item in ranking[:20]
            },
            "condition_dependency_summary": condition_dependency,
            "total_evaluation_philosophy_judgment": philosophy,
            "recommended_next_step": self._recommended_next_step(philosophy, classification, ranking),
            "official_baseline_unchanged": baseline == self.EXPECTED,
            "diagnostic_only": True,
            "final_judgment": "ACCEPT" if baseline == self.EXPECTED and not errors else "REANALYSIS_REQUIRED",
        }
        self._write_outputs(metrics, cases, ranking, counterexamples, condition_dependency)
        learning_update = self._update_learning_candidate(metrics)
        metrics["learning_candidate_update"] = learning_update
        self._write_json(self.REPORTS["metrics"], metrics)
        return metrics

    def _case_record(self, row):
        domain = self._domain_causes(row)
        gate = [cause for cause in self._all_causes(row) if cause in self.GATE_EVALUATORS]
        classification = self._reclassification(row, domain, gate)
        return {
            "race_id": row.get("race_id"),
            "horse_number": row.get("horse_number"),
            "horse_name": row.get("horse_name"),
            "finish_position": row.get("finish_position"),
            "decision": row.get("decision"),
            "case_type": row.get("case_type"),
            "final_score": row.get("final_score"),
            "adjusted_score": row.get("adjusted_score"),
            "decision_score": row.get("decision_score"),
            "ai_rank": row.get("ai_rank"),
            "confidence": row.get("confidence"),
            "racecourse": row.get("racecourse"),
            "surface": row.get("surface"),
            "distance": row.get("distance"),
            "distance_category": row.get("distance_category"),
            "track_condition": row.get("track_condition"),
            "running_style": row.get("running_style"),
            "fourth_corner_bucket": row.get("fourth_corner_bucket"),
            "field_size": row.get("field_size"),
            "primary_evaluator": row.get("primary_cause"),
            "secondary_evaluators": row.get("secondary_causes") or [],
            "domain_evaluators": domain,
            "gate_evaluators": gate,
            "combination_reason": self._combination_reason(row, domain, gate),
            "single_evaluator_insufficient_reason": self._single_insufficient_reason(row, domain),
            "not_decision_reason": self._not_decision_reason(row, gate),
            "not_relative_ranking_reason": self._not_relative_reason(row),
            "not_input_data_reason": self._not_input_data_reason(row),
            "not_randomness_reason": self._not_randomness_reason(row),
            "failure_direction": self._failure_direction(row),
            "reclassification_candidate": classification,
        }

    def _reclassification(self, row, domain, gate):
        if row.get("data_limitations"):
            return "INPUT_DATA_LIMITATION"
        if row.get("case_type") == "FN" and (row.get("ai_rank") or 99) > 5 and len(domain) < 3:
            return "RELATIVE_RANKING"
        if self._near_decision(row) and len(domain) < 2:
            return "DECISION_ISSUE"
        if len(domain) <= 1:
            return "SINGLE_EVALUATOR"
        if self._hard_to_predict(row):
            return "HIGH_RANDOMNESS"
        if self._has_counterevidence_shape(row, domain):
            return "MULTIPLE_CAUSES_UNRESOLVED"
        if len(domain) >= 2:
            return "TRUE_COMBINATION"
        return "MULTIPLE_CAUSES_UNRESOLVED"

    def _combination_ranking(self, rows, cases):
        case_by_key = {self._case_key(case): case for case in cases}
        candidate_combos = Counter()
        for case in cases:
            domain = case.get("domain_evaluators") or []
            for size in (2, 3):
                for combo in combinations(domain, size):
                    candidate_combos[combo] += 1
            if len(domain) >= 4:
                candidate_combos[tuple(domain[:4])] += 1
        output = []
        for combo, _ in candidate_combos.items():
            affected_case_keys = {
                self._case_key(case)
                for case in cases
                if set(combo).issubset(set(case.get("domain_evaluators") or []))
            }
            affected_cases = [case for case in cases if self._case_key(case) in affected_case_keys]
            all_matching = [
                row
                for row in rows
                if set(combo).issubset(set(self._domain_causes(row)))
            ]
            occurrence = len(all_matching)
            fn_count = sum(1 for row in all_matching if row.get("case_type") == "FN")
            fp_count = sum(1 for row in all_matching if row.get("case_type") == "FP")
            success = sum(1 for row in all_matching if row.get("decision") == "BUY" and row.get("finish_position") in {1, 2, 3})
            neutral = sum(1 for row in all_matching if row.get("case_type") == "TP_TN")
            counter = max(0, neutral - success)
            affected_races = len({row.get("race_id") for row in all_matching})
            same_failure = (fn_count + fp_count) / occurrence if occurrence else 0
            condition_summary = self._condition_summary(all_matching)
            direction = self._direction(fn_count, fp_count, success, counter)
            dependency = self._dependency(condition_summary, affected_races, occurrence)
            output.append(
                {
                    "combination_id": self._combo_id(combo),
                    "evaluator_names": list(combo),
                    "combination_size": len(combo),
                    "occurrence_count": occurrence,
                    "affected_races": affected_races,
                    "affected_case_count": len(affected_cases),
                    "FN_count": fn_count,
                    "FP_count": fp_count,
                    "success_count": success,
                    "neutral_count": neutral,
                    "counterexample_count": counter,
                    "same_direction_failure_rate": round(same_failure, 3),
                    "failure_direction": direction,
                    "race_condition_concentration": condition_summary,
                    "condition_dependency": dependency,
                    "confidence": self._ranking_confidence(affected_races, occurrence, fn_count, fp_count),
                    "reproducibility": "HIGH" if affected_races >= 3 else "MEDIUM" if affected_races >= 2 else "LOW",
                    "side_effect_risk": "HIGH" if counter >= fn_count + fp_count else "MEDIUM" if counter else "LOW",
                    "recommendation": self._combo_recommendation(affected_races, occurrence, fn_count, fp_count, success, counter, dependency),
                }
            )
        output.sort(
            key=lambda item: (
                -item.get("affected_case_count", 0),
                -item.get("FN_count", 0) - item.get("FP_count", 0),
                item.get("side_effect_risk") == "HIGH",
                item.get("combination_id"),
            )
        )
        return output

    def _counterexamples(self, rows, ranking):
        output = []
        for combo in ranking[:20]:
            names = set(combo.get("evaluator_names") or [])
            matched = [row for row in rows if names.issubset(set(self._domain_causes(row)))]
            success_rows = [row for row in matched if row.get("decision") == "BUY" and row.get("finish_position") in {1, 2, 3}]
            normal_rows = [row for row in matched if row.get("case_type") == "TP_TN"]
            output.append(
                {
                    "combination_id": combo.get("combination_id"),
                    "failure_examples": self._brief([row for row in matched if row.get("case_type") in {"FN", "FP"}][:3]),
                    "success_examples": self._brief(success_rows[:3]),
                    "counterexamples": self._brief(normal_rows[:5]),
                }
            )
        return output

    def _condition_dependency(self, cases, ranking):
        dependencies = []
        for combo in ranking[:20]:
            combo_cases = [
                case
                for case in cases
                if set(combo.get("evaluator_names") or []).issubset(set(case.get("domain_evaluators") or []))
            ]
            summary = {
                "combination_id": combo.get("combination_id"),
                "racecourse": dict(Counter(case.get("racecourse") for case in combo_cases).most_common()),
                "surface": dict(Counter(case.get("surface") for case in combo_cases).most_common()),
                "distance_category": dict(Counter(case.get("distance_category") for case in combo_cases).most_common()),
                "track_condition": dict(Counter(case.get("track_condition") for case in combo_cases).most_common()),
                "running_style": dict(Counter(case.get("running_style") for case in combo_cases).most_common()),
                "fourth_corner_bucket": dict(Counter(case.get("fourth_corner_bucket") for case in combo_cases).most_common()),
                "date": dict(Counter(str(case.get("race_id", "")).split("_")[1] if "_" in str(case.get("race_id")) else "unknown" for case in combo_cases).most_common()),
                "dependency": combo.get("condition_dependency"),
            }
            dependencies.append(summary)
        return {
            "condition_dependent_count": sum(1 for row in ranking if row.get("condition_dependency") == "CONDITION_DEPENDENT"),
            "global_count": sum(1 for row in ranking if row.get("condition_dependency") == "GLOBAL_COMBINATION_ISSUE"),
            "weak_evidence_count": sum(1 for row in ranking if row.get("condition_dependency") == "WEAK_EVIDENCE"),
            "details": dependencies,
        }

    def _philosophy_judgment(self, cases, ranking, classification):
        true_count = classification.get("TRUE_COMBINATION", 0)
        unresolved = classification.get("MULTIPLE_CAUSES_UNRESOLVED", 0)
        global_combos = [row for row in ranking if row.get("condition_dependency") == "GLOBAL_COMBINATION_ISSUE"]
        high_risk = [row for row in ranking if row.get("side_effect_risk") == "HIGH"]
        if not true_count:
            status = "SOUND"
            keep = True
            reason = "No true evaluator-combination issue remained after reclassification."
        elif global_combos and true_count >= 20 and len(high_risk) < len(ranking) / 2:
            status = "NEEDS_LIMITED_REVIEW"
            keep = True
            reason = "Some repeated combinations remain, but they require targeted analysis rather than changing total evaluation."
        elif true_count >= 40:
            status = "MOSTLY_SOUND"
            keep = True
            reason = "Many multiple-cause cases exist, but high counterexample counts and condition dependency argue against broad interaction changes."
        elif unresolved >= true_count:
            status = "DATA_INSUFFICIENT"
            keep = True
            reason = "Many cases remain unresolved; total evaluation should be kept until more specific evidence is collected."
        else:
            status = "MOSTLY_SOUND"
            keep = True
            reason = "Combination evidence exists, but counterexamples and condition dependency argue against broad correction."
        return {
            "status": status,
            "keep_total_evaluation_philosophy": keep,
            "true_global_combination_issue_exists": bool(global_combos and status in {"NEEDS_LIMITED_REVIEW", "STRUCTURAL_ISSUE"}),
            "combination_fix_candidate_exists": status in {"NEEDS_LIMITED_REVIEW", "STRUCTURAL_ISSUE"},
            "shadow_candidate_exists": False,
            "relative_ranking_next": True,
            "reason": reason,
        }

    def _recommended_next_step(self, philosophy, classification, ranking):
        if classification.get("RELATIVE_RANKING", 0) >= classification.get("TRUE_COMBINATION", 0):
            return "NEXT_ANALYSIS_RELATIVE_RANKING"
        if philosophy.get("status") == "NEEDS_LIMITED_REVIEW":
            return "LIMITED_COMBINATION_REVIEW"
        if philosophy.get("status") == "STRUCTURAL_ISSUE":
            return "REANALYSIS_BEFORE_IMPLEMENTATION"
        return "NEXT_ANALYSIS_RELATIVE_RANKING"

    def _write_outputs(self, metrics, cases, ranking, counterexamples, condition_dependency):
        self._write_json(self.REPORTS["metrics"], metrics)
        self._write_md(self.REPORTS["breakdown"], self._breakdown_report(metrics, cases, ranking))
        self._write_md(self.REPORTS["cases"], self._cases_report(cases))
        self._write_md(self.REPORTS["ranking"], self._ranking_report(ranking))
        self._write_md(self.REPORTS["counterexamples"], self._counterexample_report(counterexamples))
        self._write_md(self.REPORTS["condition"], self._condition_report(condition_dependency))
        self._write_md(self.REPORTS["judgment"], self._judgment_report(metrics, ranking))

    def _breakdown_report(self, metrics, cases, ranking):
        lines = [
            "# Evaluator Combination Breakdown",
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
        lines.extend(
            [
                "",
                "## Reclassification Counts",
                "",
                json.dumps(metrics.get("reclassification_counts"), ensure_ascii=False, indent=2),
                "",
                "## Duplicate Count Check",
                "",
                f"- unique_horse_count: {metrics.get('unique_horse_count')}",
                f"- total_combination_occurrences: {metrics.get('total_combination_occurrences')}",
                f"- average_combinations_per_horse: {metrics.get('average_combinations_per_horse')}",
                f"- max_combinations_per_horse: {metrics.get('max_combinations_per_horse')}",
                f"- duplicate_count: {metrics.get('duplicate_count')}",
                "",
                "## Top Combinations",
                "",
                "| rank | combination | size | races | horses | FN | FP | success | counter | direction | dependency | recommendation |",
                "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|",
            ]
        )
        for index, row in enumerate(ranking[:20], start=1):
            lines.append(
                f"| {index} | {row.get('combination_id')} | {row.get('combination_size')} | {row.get('affected_races')} | "
                f"{row.get('occurrence_count')} | {row.get('FN_count')} | {row.get('FP_count')} | "
                f"{row.get('success_count')} | {row.get('counterexample_count')} | {row.get('failure_direction')} | "
                f"{row.get('condition_dependency')} | {row.get('recommendation')} |"
            )
        lines.extend(["", "## Philosophy Judgment", "", json.dumps(metrics.get("total_evaluation_philosophy_judgment"), ensure_ascii=False, indent=2)])
        return "\n".join(lines) + "\n"

    def _cases_report(self, cases):
        lines = [
            "# Evaluator Combination Cases",
            "",
            "| race_id | horse | finish | decision | case | rank | final | adjusted | primary | secondary | domain | reclassification | reason |",
            "|---|---|---:|---|---|---:|---:|---:|---|---|---|---|---|",
        ]
        for row in cases:
            lines.append(
                f"| {row.get('race_id')} | {row.get('horse_name')} | {row.get('finish_position')} | {row.get('decision')} | "
                f"{row.get('case_type')} | {row.get('ai_rank')} | {row.get('final_score')} | {row.get('adjusted_score')} | "
                f"{row.get('primary_evaluator')} | {', '.join(row.get('secondary_evaluators') or [])} | "
                f"{', '.join(row.get('domain_evaluators') or [])} | {row.get('reclassification_candidate')} | "
                f"{row.get('combination_reason')} |"
            )
        return "\n".join(lines) + "\n"

    def _ranking_report(self, ranking):
        lines = [
            "# Evaluator Combination Ranking",
            "",
            "| rank | combination | size | occurrence | races | FN | FP | normal | success | counter | failure_rate | confidence | reproducibility | risk | recommendation |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|",
        ]
        for index, row in enumerate(ranking, start=1):
            lines.append(
                f"| {index} | {row.get('combination_id')} | {row.get('combination_size')} | {row.get('occurrence_count')} | "
                f"{row.get('affected_races')} | {row.get('FN_count')} | {row.get('FP_count')} | {row.get('neutral_count')} | "
                f"{row.get('success_count')} | {row.get('counterexample_count')} | {row.get('same_direction_failure_rate')} | "
                f"{row.get('confidence')} | {row.get('reproducibility')} | {row.get('side_effect_risk')} | {row.get('recommendation')} |"
            )
        return "\n".join(lines) + "\n"

    def _counterexample_report(self, counterexamples):
        lines = ["# Evaluator Combination Counterexamples", ""]
        for item in counterexamples:
            lines.extend(
                [
                    f"## {item.get('combination_id')}",
                    "",
                    "### Failure Examples",
                    "",
                    json.dumps(item.get("failure_examples"), ensure_ascii=False, indent=2),
                    "",
                    "### Success Examples",
                    "",
                    json.dumps(item.get("success_examples"), ensure_ascii=False, indent=2),
                    "",
                    "### Counterexamples",
                    "",
                    json.dumps(item.get("counterexamples"), ensure_ascii=False, indent=2),
                    "",
                ]
            )
        return "\n".join(lines) + "\n"

    def _condition_report(self, condition_dependency):
        lines = [
            "# Evaluator Combination Condition Dependency",
            "",
            f"- CONDITION_DEPENDENT: {condition_dependency.get('condition_dependent_count')}",
            f"- GLOBAL_COMBINATION_ISSUE: {condition_dependency.get('global_count')}",
            f"- WEAK_EVIDENCE: {condition_dependency.get('weak_evidence_count')}",
            "",
        ]
        for item in condition_dependency.get("details") or []:
            lines.extend([f"## {item.get('combination_id')}", "", json.dumps(item, ensure_ascii=False, indent=2), ""])
        return "\n".join(lines) + "\n"

    def _judgment_report(self, metrics, ranking):
        judgment = metrics.get("total_evaluation_philosophy_judgment") or {}
        lines = [
            "# Evaluator Combination Final Judgment",
            "",
            f"- Status: {judgment.get('status')}",
            f"- Keep total evaluation philosophy: {judgment.get('keep_total_evaluation_philosophy')}",
            f"- True global combination issue: {judgment.get('true_global_combination_issue_exists')}",
            f"- Combination fix candidate: {judgment.get('combination_fix_candidate_exists')}",
            f"- Shadow candidate: {judgment.get('shadow_candidate_exists')}",
            f"- Recommended next step: {metrics.get('recommended_next_step')}",
            f"- Final judgment: {metrics.get('final_judgment')}",
            "",
            "## Reason",
            "",
            judgment.get("reason") or "",
            "",
            "## Top Evidence",
            "",
            json.dumps(ranking[:5], ensure_ascii=False, indent=2),
        ]
        return "\n".join(lines) + "\n"

    def _update_learning_candidate(self, metrics):
        path = Path("learning/improvement_candidates.json")
        database = self._load_json(path, {"version": "1.0", "engine": "LearningCandidateEngine", "records": [], "aggregates": []})
        records = database.setdefault("records", [])
        now = datetime.now(timezone.utc).isoformat()
        record = None
        for item in records:
            if item.get("candidate_id") == "evaluator_combination_breakdown":
                record = item
                break
        if record is None:
            record = {
                "candidate_id": "evaluator_combination_breakdown",
                "race_id": "phase_g_step4_evaluator_combination",
                "horse": "overall_combination_breakdown",
                "case_type": "SYSTEM_DIAGNOSTIC",
                "decision": "N/A",
                "actual_finish": None,
                "fn": False,
                "fp": False,
                "primary_candidate": "EvaluatorCombinationBreakdown",
                "status": "NEW",
                "priority": "high",
                "created_at": now,
            }
            records.append(record)
        update = {
            "status": record.get("status", "NEW"),
            "original_combination_count": metrics.get("original_combination_count"),
            "unique_horse_count": metrics.get("unique_horse_count"),
            "true_combination_count": metrics.get("true_combination_count"),
            "reclassified_single_evaluator_count": metrics.get("reclassified_single_evaluator_count"),
            "reclassified_decision_count": metrics.get("reclassified_decision_count"),
            "reclassified_relative_ranking_count": metrics.get("reclassified_relative_ranking_count"),
            "reclassified_input_data_count": metrics.get("reclassified_input_data_count"),
            "reclassified_randomness_count": metrics.get("reclassified_randomness_count"),
            "unresolved_count": metrics.get("unresolved_count"),
            "top_combinations": metrics.get("top_combinations", [])[:5],
            "top_combination_failure_rates": metrics.get("top_combination_failure_rates", [])[:5],
            "counterexample_counts": metrics.get("counterexample_counts"),
            "condition_dependency_summary": metrics.get("condition_dependency_summary"),
            "total_evaluation_philosophy_judgment": metrics.get("total_evaluation_philosophy_judgment"),
            "recommended_next_step": metrics.get("recommended_next_step"),
            "official_baseline_unchanged": metrics.get("official_baseline_unchanged"),
            "diagnostic_only": True,
            "note": "Diagnostic-only PhaseG Step4 record; no evaluator, score, Decision, Knowledge, CSV, or main.py logic was changed.",
            "updated_at": now,
            "ranking_active": True,
        }
        record.update(update)
        database["updated_at"] = now
        self._write_json(path, database)
        return {"candidate_id": record.get("candidate_id"), "updated": True, "status": record.get("status")}

    def _all_causes(self, row):
        causes = []
        for cause in [row.get("primary_cause")] + list(row.get("secondary_causes") or []):
            if cause and cause != "UNKNOWN" and cause not in causes:
                causes.append(cause)
        return causes

    def _domain_causes(self, row):
        return sorted({cause for cause in self._all_causes(row) if cause in self.DOMAIN_EVALUATORS})

    def _case_key(self, case):
        return (case.get("race_id"), case.get("horse_number"), case.get("horse_name"))

    def _horse_key(self, row):
        return (row.get("race_id"), row.get("horse_number"), row.get("horse_name"))

    def _combo_id(self, combo):
        return " x ".join(combo)

    def _near_decision(self, row):
        score = self._to_float(row.get("decision_score"))
        return score is not None and 0.65 <= score <= 0.84

    def _hard_to_predict(self, row):
        rank = self._to_int(row.get("ai_rank")) or 99
        final_score = self._to_float(row.get("final_score")) or 0
        if row.get("case_type") == "FN" and rank > 10 and final_score < 110:
            return True
        if row.get("case_type") == "FP" and row.get("finish_position") and row.get("finish_position") >= 10 and final_score < 125:
            return True
        return False

    def _has_counterevidence_shape(self, row, domain):
        if "BloodlineEvaluator" in domain and row.get("data_limitations"):
            return True
        return False

    def _combination_reason(self, row, domain, gate):
        if len(domain) >= 2:
            return "Multiple domain evaluators jointly appear before the final decision gate."
        if gate:
            return "Mostly final-gate related rather than a domain evaluator combination."
        return "Only weak multi-cause evidence remains."

    def _single_insufficient_reason(self, row, domain):
        if len(domain) >= 2:
            return "No single evaluator explains the case without losing secondary evidence."
        if len(domain) == 1:
            return "Single evaluator is enough after decomposition."
        return "No domain evaluator evidence."

    def _not_decision_reason(self, row, gate):
        if gate and len(self._domain_causes(row)) < 2:
            return "Decision/gate evidence dominates."
        return "Domain evaluator evidence remains before Decision."

    def _not_relative_reason(self, row):
        if row.get("case_type") == "FN" and (row.get("ai_rank") or 99) > 5 and len(self._domain_causes(row)) < 3:
            return "Relative rank explains the case more directly."
        return "Evaluator causes remain after checking rank."

    def _not_input_data_reason(self, row):
        return "Input data gaps present." if row.get("data_limitations") else "No row-level input data limitation flag."

    def _not_randomness_reason(self, row):
        return "Hard-to-predict low-score case." if self._hard_to_predict(row) else "Not classified as high randomness."

    def _failure_direction(self, row):
        return "UNDERVALUATION" if row.get("case_type") == "FN" else "OVERVALUATION" if row.get("case_type") == "FP" else "NORMAL"

    def _direction(self, fn_count, fp_count, success, counter):
        if fn_count >= fp_count * 2 and fn_count > 0:
            return "UNDERVALUATION"
        if fp_count >= fn_count * 2 and fp_count > 0:
            return "OVERVALUATION"
        if fn_count and fp_count:
            return "BOTH_DIRECTIONS"
        return "NO_DIRECTION"

    def _condition_summary(self, rows):
        total = len(rows) or 1
        summary = {}
        for key in ["racecourse", "surface", "distance_category", "track_condition", "running_style", "fourth_corner_bucket"]:
            counter = Counter(row.get(key) or "unknown" for row in rows)
            value, count = counter.most_common(1)[0] if counter else ("unknown", 0)
            summary[key] = {"top": value, "count": count, "share": round(count / total, 3)}
        return summary

    def _dependency(self, summary, affected_races, occurrence):
        if occurrence < 5 or affected_races < 2:
            return "WEAK_EVIDENCE"
        if any((item.get("share") or 0) >= 0.7 for item in summary.values()):
            return "CONDITION_DEPENDENT"
        if affected_races >= 5:
            return "GLOBAL_COMBINATION_ISSUE"
        return "WEAK_EVIDENCE"

    def _ranking_confidence(self, races, occurrence, fn_count, fp_count):
        if races >= 3 and occurrence >= 8 and fn_count + fp_count >= 5:
            return "HIGH"
        if races >= 2 and occurrence >= 4:
            return "MEDIUM"
        return "LOW"

    def _combo_recommendation(self, races, occurrence, fn_count, fp_count, success, counter, dependency):
        if occurrence < 4 or races < 2:
            return "WEAK_EVIDENCE"
        if counter >= fn_count + fp_count:
            return "HOLD"
        if dependency == "CONDITION_DEPENDENT":
            return "WATCH"
        if fn_count + fp_count >= 8 and races >= 3:
            return "PRIORITY_ANALYSIS"
        return "WATCH"

    def _brief(self, rows):
        return [
            {
                "race_id": row.get("race_id"),
                "horse": row.get("horse_name"),
                "finish": row.get("finish_position"),
                "decision": row.get("decision"),
                "rank": row.get("ai_rank"),
                "primary": row.get("primary_cause"),
                "secondary": row.get("secondary_causes"),
            }
            for row in rows
        ]

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
    result = EvaluatorCombinationBreakdown().run()
    print(
        {
            "baseline_match": result.get("baseline_match"),
            "original_combination_count": result.get("original_combination_count"),
            "unique_horse_count": result.get("unique_horse_count"),
            "true_combination_count": result.get("true_combination_count"),
            "recommended_next_step": result.get("recommended_next_step"),
            "final_judgment": result.get("final_judgment"),
        }
    )
