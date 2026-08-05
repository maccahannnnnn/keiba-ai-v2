"""Build PhaseG Step3 22-race health-check reports.

This module is diagnostic only. It reads existing analysis/result files,
recreates the current 22-race baseline with existing adapters, and writes
reports. It does not change evaluator logic, scores, decisions, Knowledge,
CSV definitions, or main.py.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from evaluation.race_file_locator import RaceFileLocator
from evaluation.target_result_adapter import TargetResultAdapter
from evaluation.target_trial_adapter import TargetTrialAdapter


class Overall22RaceHealthCheck:
    """Create evaluator and cross-race diagnostics for the fixed baseline."""

    VERSION = "phase_g_step3_v1"
    BASELINE_DATES = {"20260705", "20260711", "20260712"}
    EXPECTED = {
        "races": 22,
        "horses": 304,
        "BUY": 45,
        "CAUTION": 88,
        "PASS": 171,
        "FN": 55,
        "FP": 34,
        "BUY3": 11,
        "Top5_3": 30,
    }
    REPORTS = {
        "overall": Path("reports/overall_22race_health_check.md"),
        "evaluator": Path("reports/evaluator_health_check.md"),
        "evaluator_metrics": Path("reports/evaluator_health_metrics.json"),
        "fn": Path("reports/fn_root_cause_summary.md"),
        "fp": Path("reports/fp_root_cause_summary.md"),
        "race": Path("reports/race_health_check.md"),
        "patterns": Path("reports/cross_race_pattern_ranking.md"),
        "decision": Path("reports/decision_structure_diagnosis.md"),
        "data_gap": Path("reports/data_gap_inventory.md"),
        "priority": Path("reports/next_improvement_priority.md"),
        "metrics": Path("reports/overall_22race_health_metrics.json"),
    }
    EVALUATORS = [
        ("AbilityEvaluator", ["past_performance_score"], 30, 70),
        ("PastPerformanceEvaluator", ["past_performance_score"], 30, 70),
        ("DistanceEvaluator", ["distance_score"], 20, 35),
        ("CourseEvaluator", ["course_shape_score", "course_score"], -4, 8),
        ("CourseShapeEvaluator", ["course_shape_score", "course_score"], -4, 8),
        ("PaceEvaluator", ["pace_style_score"], 10, 20),
        ("RunningStyleEvaluator", ["pace_style_score", "running_style_score"], 10, 20),
        ("PaceStyleEvaluator", ["pace_style_score", "running_style_score"], 10, 20),
        ("LapSuitabilityEvaluator", ["lap_score"], -4, 8),
        ("RaceShapeEvaluator", ["shape_score"], -4, 8),
        ("TrackBiasEvaluator", ["track_bias_score"], -1, 4),
        ("BloodlineEvaluator", ["bloodline_score", "blood_score"], 0, 20),
        ("WeightEvaluator", ["weight_score"], 0, 8),
        ("ConditionEvaluator", ["condition_score", "track_condition_score"], -1, 18),
        ("TrackConditionSuitabilityEvaluator", ["track_condition_score", "track_score"], -1, 18),
        ("ImpactEvaluator", ["impact_score"], -1, 8),
        ("ScoreWeightEvaluator", ["adjusted_score"], 120, 170),
        ("ConfidenceEngine", ["confidence_score"], 0.45, 0.75),
        ("DecisionEngine", ["decision_score"], 0.5, 0.8),
        ("RaceDecisionEngine", [], 0, 0),
        ("ExplainEngine", [], 0, 0),
    ]

    def run(self, analysis_dir="data/analysis", results_dir="data/results"):
        started = datetime.now(timezone.utc).isoformat()
        races, rows, errors = self._collect(analysis_dir, results_dir)
        baseline = self._baseline(rows)
        fn_rows = [row for row in rows if row.get("case_type") == "FN"]
        fp_rows = [row for row in rows if row.get("case_type") == "FP"]
        evaluator_health = self._evaluator_health(rows, fn_rows, fp_rows)
        fn_summary = self._case_summary(fn_rows, "FN")
        fp_summary = self._case_summary(fp_rows, "FP")
        race_health = self._race_health(races, rows)
        patterns = self._cross_patterns(rows)
        decision = self._decision_structure(rows, fn_rows, fp_rows)
        data_gaps = self._data_gaps(rows, races)
        priority = self._priority_ranking(
            evaluator_health=evaluator_health,
            fn_summary=fn_summary,
            fp_summary=fp_summary,
            patterns=patterns,
            decision=decision,
            data_gaps=data_gaps,
        )
        metrics = {
            "validation_version": self.VERSION,
            "generated_at": started,
            "baseline": baseline,
            "expected_baseline": self.EXPECTED,
            "baseline_match": baseline == self.EXPECTED,
            "race_count": len(races),
            "horse_count": len(rows),
            "errors": errors,
            "race_diagnosis_counts": dict(Counter(row.get("race_diagnosis") for row in race_health)),
            "fn_category_counts": fn_summary.get("category_counts"),
            "fp_category_counts": fp_summary.get("category_counts"),
            "evaluator_health_summary": dict(Counter(item.get("health") for item in evaluator_health)),
            "decision_issue_count": decision.get("decision_issue_count"),
            "evaluator_issue_count": decision.get("evaluator_issue_count"),
            "multiple_cause_count": fn_summary.get("category_counts", {}).get("H_MULTIPLE_CAUSES", 0)
            + fp_summary.get("category_counts", {}).get("H_MULTIPLE_CAUSES", 0),
            "data_insufficient_count": data_gaps.get("high_priority_gap_count"),
            "top_cross_race_patterns": patterns[:10],
            "top_priority_area": (priority[0] if priority else {}).get("area", "No Immediate Change"),
            "recommended_next_step": (priority[0] if priority else {}).get("recommended_action", "NO_CHANGE"),
            "official_baseline_unchanged": baseline == self.EXPECTED,
            "final_judgment": "ACCEPT" if baseline == self.EXPECTED and not errors else "REANALYSIS_REQUIRED",
        }
        self._write_outputs(
            metrics=metrics,
            evaluator_health=evaluator_health,
            fn_summary=fn_summary,
            fp_summary=fp_summary,
            race_health=race_health,
            patterns=patterns,
            decision=decision,
            data_gaps=data_gaps,
            priority=priority,
        )
        learning_update = self._update_learning_candidate(metrics)
        metrics["learning_candidate_update"] = learning_update
        self._write_json(self.REPORTS["metrics"], metrics)
        return metrics

    def _collect(self, analysis_dir, results_dir):
        complete_sets = self._complete_sets(analysis_dir, results_dir)
        adapter = TargetTrialAdapter()
        result_adapter = TargetResultAdapter()
        races = []
        rows = []
        errors = []
        for race_set in complete_sets:
            race_id = race_set.get("race_id")
            try:
                analysis = adapter.run(
                    race_set.get("entry_path"),
                    horse_data_csv_path=race_set.get("horses_path"),
                )
                official = result_adapter.load(
                    race_set.get("race_result_path"),
                    race_set.get("horse_result_path"),
                )
                official_rows = self._list(official.get("horse_results"))
                official_map = self._official_map(official_rows)
                ranked = self._ranked(analysis.get("ranked_results"))
                last3f_ranks = self._last3f_ranks(official_rows)
                race_context = self._race_context(race_id, official.get("race_result") or {}, analysis)
                race_rows = []
                for rank, horse in enumerate(ranked, start=1):
                    result = self._lookup(official_map, horse.get("horse_name"))
                    row = self._row(race_id, race_context, horse, result, rank, last3f_ranks)
                    race_rows.append(row)
                    rows.append(row)
                races.append(
                    {
                        "race_id": race_id,
                        "race_context": race_context,
                        "analysis": analysis,
                        "official": official,
                        "rows": race_rows,
                    }
                )
            except Exception as exc:
                errors.append({"race_id": race_id, "error": str(exc)})
        return races, rows, errors

    def _row(self, race_id, context, horse, result, rank, last3f_ranks):
        result = result if isinstance(result, dict) else {}
        decision = str(horse.get("decision") or "").upper()
        finish = self._to_int(result.get("finish_position"))
        case_type = "FN" if finish in {1, 2, 3} and decision != "BUY" else "FP" if decision == "BUY" and finish not in {1, 2, 3} else "TP_TN"
        root = horse.get("decision_root_cause") if isinstance(horse.get("decision_root_cause"), dict) else {}
        attribution = horse.get("decision_attribution") if isinstance(horse.get("decision_attribution"), dict) else {}
        primary = (
            root.get("root_primary_candidate")
            or self._nested(attribution, ["primary_blocker", "target"])
            or self._nested(attribution, ["primary_supporter", "target"])
            or self._score_primary(horse, case_type)
        )
        secondary = self._secondary_causes(horse, attribution, root, primary)
        category = self._case_category(case_type, horse, rank, primary, secondary)
        return {
            **context,
            "race_id": race_id,
            "horse_name": horse.get("horse_name"),
            "horse_number": self._to_int(horse.get("horse_number") or result.get("horse_number")),
            "frame_number": self._to_int(horse.get("frame_number") or result.get("frame_number")),
            "finish_position": finish,
            "corner_positions": result.get("corner_positions"),
            "fourth_corner_position": self._to_int(result.get("fourth_corner_position")),
            "fourth_corner_bucket": self._corner_bucket(result.get("fourth_corner_position")),
            "last_3f": self._to_float(result.get("last_3f")),
            "last_3f_rank": last3f_ranks.get(self._norm(horse.get("horse_name"))),
            "decision": decision,
            "final_score": self._to_float(horse.get("final_score")),
            "adjusted_score": self._to_float(horse.get("adjusted_score")),
            "decision_score": self._to_float(horse.get("decision_score")),
            "confidence": horse.get("confidence_level") or horse.get("confidence"),
            "confidence_score": self._to_float(horse.get("confidence_score")),
            "ai_rank": rank,
            "top5": rank <= 5,
            "case_type": case_type,
            "primary_cause": primary,
            "secondary_causes": secondary,
            "case_category": category,
            "running_style": horse.get("pace_style") or horse.get("running_style"),
            "race_decision": horse.get("race_decision"),
            "explain_summary": horse.get("explain_summary") or horse.get("explanation") or "",
            "root_cause": root,
            "decision_attribution": attribution,
            "scores": self._scores(horse),
            "major_plus": self._major_plus(horse),
            "major_minus": self._major_minus(horse),
            "data_limitations": self._row_data_limitations(horse, result, context),
        }

    def _evaluator_health(self, rows, fn_rows, fp_rows):
        items = []
        for name, keys, low, high in self.EVALUATORS:
            valid = [row for row in rows if not keys or any(self._score(row, key) is not None for key in keys)]
            fn_impacted = [row for row in fn_rows if row.get("primary_cause") == name or name in row.get("secondary_causes", [])]
            fp_impacted = [row for row in fp_rows if row.get("primary_cause") == name or name in row.get("secondary_causes", [])]
            low_signal = [row for row in rows if any((self._score(row, key) is not None and self._score(row, key) < low) for key in keys)]
            high_signal = [row for row in rows if any((self._score(row, key) is not None and self._score(row, key) >= high) for key in keys)]
            data_missing = len(rows) - len(valid) if keys else 0
            multiple = sum(1 for row in rows if row.get("case_type") in {"FN", "FP"} and row.get("primary_cause") != name and name in row.get("secondary_causes", []))
            explanation_mismatch = self._explain_mismatch_count(rows, name, keys)
            health = self._health_status(name, len(fn_impacted), len(fp_impacted), data_missing, explanation_mismatch, multiple)
            items.append(
                {
                    "evaluator": name,
                    "health": health,
                    "valid_count": len(valid),
                    "fn_possible_impact_count": len(fn_impacted),
                    "fp_possible_impact_count": len(fp_impacted),
                    "low_signal_count": len(low_signal),
                    "high_signal_count": len(high_signal),
                    "overlap_count": multiple,
                    "explanation_score_consistent_count": len(valid) - explanation_mismatch,
                    "explanation_score_mismatch_count": explanation_mismatch,
                    "data_insufficient_count": data_missing,
                    "multiple_causes_count": multiple,
                    "comment": self._health_comment(health, name),
                }
            )
        return items

    def _case_summary(self, rows, case_type):
        category_counts = Counter(row.get("case_category") for row in rows)
        cause_counts = Counter(row.get("primary_cause") or "UNKNOWN" for row in rows)
        records = []
        for row in rows:
            records.append(
                {
                    "race_id": row.get("race_id"),
                    "horse_number": row.get("horse_number"),
                    "horse_name": row.get("horse_name"),
                    "finish_position": row.get("finish_position"),
                    "decision": row.get("decision"),
                    "final_score": row.get("final_score"),
                    "adjusted_score": row.get("adjusted_score"),
                    "ai_rank": row.get("ai_rank"),
                    "fourth_corner_position": row.get("fourth_corner_position"),
                    "last_3f_rank": row.get("last_3f_rank"),
                    "major_plus": row.get("major_plus"),
                    "major_minus": row.get("major_minus"),
                    "primary_cause": row.get("primary_cause"),
                    "secondary_causes": row.get("secondary_causes"),
                    "category": row.get("case_category"),
                    "multiple_causes": len(row.get("secondary_causes", [])) >= 2,
                    "decision_boundary": self._decision_boundary(row),
                    "relative_ranking": self._relative_ranking(row),
                    "track_bias_overlap": "TrackBiasEvaluator" in row.get("secondary_causes", []) or row.get("primary_cause") == "TrackBiasEvaluator",
                    "course_overlap": "CourseShapeEvaluator" in row.get("secondary_causes", []) or row.get("primary_cause") in {"CourseEvaluator", "CourseShapeEvaluator"},
                    "bloodline_overlap": "BloodlineEvaluator" in row.get("secondary_causes", []) or row.get("primary_cause") == "BloodlineEvaluator",
                    "input_data_limitation": bool(row.get("data_limitations")),
                    "same_pattern_count": 0,
                }
            )
        pattern_counts = Counter((row.get("primary_cause"), row.get("case_category")) for row in records)
        for row in records:
            row["same_pattern_count"] = pattern_counts[(row.get("primary_cause"), row.get("category"))]
        return {
            "case_type": case_type,
            "count": len(rows),
            "category_counts": dict(category_counts),
            "primary_cause_counts": dict(cause_counts.most_common()),
            "records": records,
        }

    def _race_health(self, races, rows):
        by_race = defaultdict(list)
        for row in rows:
            by_race[row.get("race_id")].append(row)
        output = []
        for race in races:
            race_id = race.get("race_id")
            race_rows = by_race.get(race_id, [])
            top3 = sorted([row for row in race_rows if row.get("finish_position") in {1, 2, 3}], key=lambda row: row.get("finish_position") or 99)
            top5 = [row for row in race_rows if row.get("top5")]
            decisions = Counter(row.get("decision") for row in race_rows)
            fn = [row for row in race_rows if row.get("case_type") == "FN"]
            fp = [row for row in race_rows if row.get("case_type") == "FP"]
            buy3 = sum(1 for row in race_rows if row.get("decision") == "BUY" and row.get("finish_position") in {1, 2, 3})
            top5_3 = sum(1 for row in top5 if row.get("finish_position") in {1, 2, 3})
            primary = self._race_primary_area(fn, fp, buy3, top5_3)
            diagnosis = self._race_diagnosis(fn, fp, buy3, top5_3, race_rows)
            context = race.get("race_context") or {}
            output.append(
                {
                    "race_id": race_id,
                    "racecourse": context.get("racecourse"),
                    "surface": context.get("surface"),
                    "distance": context.get("distance"),
                    "track_condition": context.get("track_condition"),
                    "field_size": len(race_rows),
                    "actual_top3": [row.get("horse_name") for row in top3],
                    "buy_count": decisions.get("BUY", 0),
                    "caution_count": decisions.get("CAUTION", 0),
                    "pass_count": decisions.get("PASS", 0),
                    "actual_top3_decisions": [row.get("decision") for row in top3],
                    "actual_top3_final_rank": [row.get("ai_rank") for row in top3],
                    "actual_top3_final_score": [row.get("final_score") for row in top3],
                    "actual_top3_adjusted_score": [row.get("adjusted_score") for row in top3],
                    "fn_count": len(fn),
                    "fp_count": len(fp),
                    "buy3_hit": buy3 > 0,
                    "top5_3_hit": top5_3 > 0,
                    "buy3_count": buy3,
                    "top5_3_count": top5_3,
                    "success_factors": self._race_success_factors(race_rows),
                    "failure_factors": self._race_failure_factors(fn, fp),
                    "primary_problem_area": primary,
                    "secondary_problem_area": self._secondary_problem_area(fn, fp),
                    "data_limitation": self._race_data_limitation(race_rows),
                    "race_diagnosis": diagnosis,
                }
            )
        return output

    def _cross_patterns(self, rows):
        specs = [
            ("racecourse", lambda row: row.get("racecourse")),
            ("surface", lambda row: row.get("surface")),
            ("distance_category", lambda row: row.get("distance_category")),
            ("track_condition", lambda row: row.get("track_condition")),
            ("running_style", lambda row: row.get("running_style")),
            ("fourth_corner_bucket", lambda row: row.get("fourth_corner_bucket")),
            ("frame_bucket", lambda row: self._frame_bucket(row.get("frame_number"))),
            ("decision", lambda row: row.get("decision")),
            ("final_score_band", lambda row: self._score_band(row.get("final_score"))),
            ("adjusted_score_band", lambda row: self._score_band(row.get("adjusted_score"))),
            ("primary_cause", lambda row: row.get("primary_cause")),
        ]
        patterns = []
        for name, getter in specs:
            grouped = defaultdict(list)
            for row in rows:
                grouped[getter(row) or "UNKNOWN"].append(row)
            for value, group in grouped.items():
                fn_count = sum(1 for row in group if row.get("case_type") == "FN")
                fp_count = sum(1 for row in group if row.get("case_type") == "FP")
                success = sum(1 for row in group if row.get("decision") == "BUY" and row.get("finish_position") in {1, 2, 3})
                counter = sum(1 for row in group if row.get("decision") == "BUY" and row.get("finish_position") not in {1, 2, 3})
                if fn_count + fp_count + success < 2:
                    continue
                affected_races = len({row.get("race_id") for row in group})
                patterns.append(
                    {
                        "pattern_id": f"{name}:{value}",
                        "pattern_name": f"{name}={value}",
                        "occurrence_count": len(group),
                        "affected_races": affected_races,
                        "affected_horses": len(group),
                        "fn_count": fn_count,
                        "fp_count": fp_count,
                        "success_count": success,
                        "counterexample_count": counter,
                        "related_evaluators": self._related_evaluators(group),
                        "related_conditions": dict(Counter(row.get("racecourse") for row in group)),
                        "estimated_cause": self._pattern_cause(name, value, fn_count, fp_count),
                        "reproducibility": "HIGH" if affected_races >= 3 else "MEDIUM" if affected_races >= 2 else "LOW",
                        "fix_feasibility": "MEDIUM" if affected_races >= 2 and (fn_count or fp_count) else "LOW",
                        "side_effect_risk": "HIGH" if counter >= success + 3 else "MEDIUM" if counter else "LOW",
                        "evidence_strength": "HIGH" if affected_races >= 3 and fn_count + fp_count >= 5 else "MEDIUM",
                        "next_step_candidate": affected_races >= 2 and fn_count + fp_count >= 4,
                        "recommendation": "PRIORITY_REVIEW" if affected_races >= 3 and fn_count + fp_count >= 5 else "WATCH",
                    }
                )
        patterns.sort(key=lambda row: (-(row.get("fn_count") + row.get("fp_count")), -row.get("affected_races"), row.get("pattern_id")))
        return patterns

    def _decision_structure(self, rows, fn_rows, fp_rows):
        final_high_fn = [row for row in fn_rows if (row.get("final_score") or 0) >= 150 and row.get("decision") != "BUY"]
        final_low = [row for row in rows if (row.get("final_score") or 0) < 120]
        adjusted_issue = [row for row in fn_rows + fp_rows if abs((row.get("adjusted_score") or 0) - (row.get("final_score") or 0)) >= 25]
        near_boundary = [row for row in fn_rows + fp_rows if self._near_boundary(row)]
        relative = [row for row in fn_rows + fp_rows if row.get("ai_rank", 99) > 5 or (row.get("decision") == "BUY" and row.get("ai_rank", 99) > 5)]
        buy_by_race = Counter(row.get("race_id") for row in rows if row.get("decision") == "BUY")
        buy_too_many = [race for race, count in buy_by_race.items() if count >= 4]
        buy_too_few = [race for race, count in buy_by_race.items() if count == 0]
        return {
            "high_final_score_non_buy_count": len(final_high_fn),
            "low_final_score_count": len(final_low),
            "adjusted_conversion_issue_count": len(adjusted_issue),
            "near_decision_boundary_count": len(near_boundary),
            "relative_ranking_issue_count": len(relative),
            "buy_too_many_races": buy_too_many,
            "buy_too_few_races": buy_too_few,
            "buy3_miss_races": sorted({row.get("race_id") for row in fn_rows if row.get("finish_position") in {1, 2, 3}}),
            "top5_3_miss_races": sorted({row.get("race_id") for row in fn_rows if row.get("ai_rank", 99) > 5}),
            "decision_issue_count": len(near_boundary) + len(final_high_fn),
            "evaluator_issue_count": sum(1 for row in fn_rows + fp_rows if row.get("primary_cause") not in {"DecisionEngine", "UNKNOWN"}),
            "no_change_cases": sum(1 for row in rows if row.get("case_type") == "TP_TN"),
            "details": {
                "high_final_score_non_buy": self._brief_rows(final_high_fn[:30]),
                "near_boundary": self._brief_rows(near_boundary[:30]),
                "relative_ranking": self._brief_rows(relative[:30]),
            },
        }

    def _data_gaps(self, rows, races):
        specs = [
            ("course_configuration", "A", "MeetingBias", "all evidence records", "Target CSV if present; otherwise external official course-use metadata", "weekly", "no", "HIGH"),
            ("meeting_day", "A", "MeetingBias", "meeting stage precision", "Target CSV/entry metadata if present", "per race", "no", "HIGH"),
            ("meeting_week", "A", "MeetingBias", "meeting stage precision", "Target CSV/entry metadata if present", "per race", "no", "HIGH"),
            ("water_content", "B", "TrackBias/MeetingBias", "track-condition interpretation", "Not present in current target files", "per race day", "no", "MEDIUM"),
            ("previous_day_trend", "C", "MeetingBias", "cross-day continuity", "Additional review data", "race-day review", "yes", "MEDIUM"),
            ("manual_track_bias", "D", "TrackBias", "same-day bias separation", "manual input", "race day", "no", "MEDIUM"),
            ("last_3f", "A", "Lap/MeetingBias", "late-speed pattern", "horse_result.csv", "none", "yes", "LOW"),
            ("fourth_corner_position", "A", "Pace/RaceShape/MeetingBias", "position pattern", "horse_result.csv", "none", "yes", "LOW"),
            ("odds_popularity", "F", "not used", "diagnostic only", "horse_result.csv", "none", "no", "LOW"),
        ]
        gaps = []
        for item, category, area, impact, possibility, burden, historical, priority in specs:
            missing = self._missing_count(item, rows, races)
            gaps.append(
                {
                    "item_name": item,
                    "category": category,
                    "affected_area": area,
                    "missing_count": missing,
                    "additional_possible": possibility,
                    "weekly_input_burden": burden,
                    "historical_data_addable": historical,
                    "priority": priority,
                    "recommendation": "DATA_COLLECTION" if priority == "HIGH" else "WATCH" if priority == "MEDIUM" else "NO_ACTION",
                    "note": impact,
                }
            )
        return {
            "items": gaps,
            "high_priority_gap_count": sum(1 for row in gaps if row.get("priority") == "HIGH" and row.get("missing_count", 0) > 0),
        }

    def _priority_ranking(self, evaluator_health, fn_summary, fp_summary, patterns, decision, data_gaps):
        areas = []
        fn_counts = fn_summary.get("primary_cause_counts", {})
        fp_counts = fp_summary.get("primary_cause_counts", {})
        evaluator_issue = {
            item.get("evaluator"): item
            for item in evaluator_health
            if item.get("health") in {"WATCH", "UNDERVALUATION_RISK", "OVERVALUEATION_RISK", "OVERVALUATION_RISK", "CONFLICT_RISK"}
        }
        candidates = [
            "Decision Boundary",
            "Relative Ranking",
            "RaceShape",
            "Pace",
            "RunningStyle",
            "Course",
            "TrackBias",
            "LapSuitability",
            "Ability",
            "Distance",
            "Bloodline",
            "Confidence",
            "Impact",
            "Explain",
            "MeetingBias",
            "Input Data",
            "Evaluator Combination",
            "No Immediate Change",
        ]
        for area in candidates:
            evidence_count = self._area_evidence_count(area, fn_counts, fp_counts, evaluator_issue, decision, data_gaps, patterns)
            affected_races = self._area_races(area, patterns)
            fn_related = self._area_count(area, fn_counts)
            fp_related = self._area_count(area, fp_counts)
            risk = self._area_risk(area, data_gaps, fp_related)
            confidence = self._area_confidence(evidence_count, affected_races, area)
            action = self._area_action(area, evidence_count, confidence, risk)
            areas.append(
                {
                    "rank": 0,
                    "area": area,
                    "evidence_count": evidence_count,
                    "affected_races": affected_races,
                    "fn_related": fn_related,
                    "fp_related": fp_related,
                    "success_counterexamples": self._area_counterexamples(area, patterns),
                    "estimated_benefit": self._benefit(evidence_count, fn_related, fp_related),
                    "side_effect_risk": risk,
                    "confidence": confidence,
                    "recommended_action": action,
                    "reason": self._area_reason(area, evidence_count, fn_related, fp_related, risk),
                }
            )
        areas.sort(
            key=lambda row: (
                -self._action_value(row.get("recommended_action")),
                -row.get("evidence_count", 0),
                row.get("side_effect_risk") == "HIGH",
                row.get("area"),
            )
        )
        for index, row in enumerate(areas, start=1):
            row["rank"] = index
        return areas

    def _write_outputs(self, metrics, evaluator_health, fn_summary, fp_summary, race_health, patterns, decision, data_gaps, priority):
        self._write_json(self.REPORTS["evaluator_metrics"], {"validation_version": self.VERSION, "evaluator_health": evaluator_health})
        self._write_json(self.REPORTS["metrics"], metrics)
        self._write_md(self.REPORTS["overall"], self._overall_report(metrics, evaluator_health, fn_summary, fp_summary, patterns, priority))
        self._write_md(self.REPORTS["evaluator"], self._evaluator_report(evaluator_health))
        self._write_md(self.REPORTS["fn"], self._case_report(fn_summary, "False Negative"))
        self._write_md(self.REPORTS["fp"], self._case_report(fp_summary, "False Positive"))
        self._write_md(self.REPORTS["race"], self._race_report(race_health))
        self._write_md(self.REPORTS["patterns"], self._pattern_report(patterns))
        self._write_md(self.REPORTS["decision"], self._decision_report(decision))
        self._write_md(self.REPORTS["data_gap"], self._data_gap_report(data_gaps))
        self._write_md(self.REPORTS["priority"], self._priority_report(priority))

    def _overall_report(self, metrics, evaluator_health, fn_summary, fp_summary, patterns, priority):
        lines = [
            "# Overall 22-Race Health Check",
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
                "## Race Diagnosis Counts",
                "",
                json.dumps(metrics.get("race_diagnosis_counts"), ensure_ascii=False, indent=2),
                "",
                "## FN / FP Category Counts",
                "",
                f"- FN: {json.dumps(fn_summary.get('category_counts'), ensure_ascii=False)}",
                f"- FP: {json.dumps(fp_summary.get('category_counts'), ensure_ascii=False)}",
                "",
                "## Evaluator Health Summary",
                "",
                json.dumps(metrics.get("evaluator_health_summary"), ensure_ascii=False, indent=2),
                "",
                "## Top Cross-Race Patterns",
                "",
                "| pattern | races | horses | FN | FP | recommendation |",
                "|---|---:|---:|---:|---:|---|",
            ]
        )
        for row in patterns[:10]:
            lines.append(f"| {row.get('pattern_name')} | {row.get('affected_races')} | {row.get('affected_horses')} | {row.get('fn_count')} | {row.get('fp_count')} | {row.get('recommendation')} |")
        lines.extend(
            [
                "",
                "## Priority",
                "",
                "| rank | area | evidence | FN | FP | risk | confidence | action |",
                "|---:|---|---:|---:|---:|---|---|---|",
            ]
        )
        for row in priority[:10]:
            lines.append(f"| {row.get('rank')} | {row.get('area')} | {row.get('evidence_count')} | {row.get('fn_related')} | {row.get('fp_related')} | {row.get('side_effect_risk')} | {row.get('confidence')} | {row.get('recommended_action')} |")
        lines.extend(["", "## Final Judgment", "", f"- {metrics.get('final_judgment')}"])
        return "\n".join(lines) + "\n"

    def _evaluator_report(self, items):
        lines = [
            "# Evaluator Health Check",
            "",
            "| evaluator | health | valid | FN impact | FP impact | low | high | overlap | explain mismatch | data gaps | comment |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for row in items:
            lines.append(
                f"| {row.get('evaluator')} | {row.get('health')} | {row.get('valid_count')} | "
                f"{row.get('fn_possible_impact_count')} | {row.get('fp_possible_impact_count')} | "
                f"{row.get('low_signal_count')} | {row.get('high_signal_count')} | {row.get('overlap_count')} | "
                f"{row.get('explanation_score_mismatch_count')} | {row.get('data_insufficient_count')} | {row.get('comment')} |"
            )
        return "\n".join(lines) + "\n"

    def _case_report(self, summary, title):
        lines = [
            f"# {title} Root Cause Summary",
            "",
            f"- Count: {summary.get('count')}",
            "",
            "## Category Counts",
            "",
            json.dumps(summary.get("category_counts"), ensure_ascii=False, indent=2),
            "",
            "## Primary Cause Counts",
            "",
            json.dumps(summary.get("primary_cause_counts"), ensure_ascii=False, indent=2),
            "",
            "## Cases",
            "",
            "| race_id | horse | finish | decision | rank | final | adjusted | primary | secondary | category | decision boundary | relative ranking | data limitation | same pattern |",
            "|---|---|---:|---|---:|---:|---:|---|---|---|---|---|---|---:|",
        ]
        for row in summary.get("records") or []:
            lines.append(
                f"| {row.get('race_id')} | {row.get('horse_name')} | {row.get('finish_position')} | {row.get('decision')} | "
                f"{row.get('ai_rank')} | {row.get('final_score')} | {row.get('adjusted_score')} | "
                f"{row.get('primary_cause')} | {', '.join(row.get('secondary_causes') or [])} | "
                f"{row.get('category')} | {row.get('decision_boundary')} | {row.get('relative_ranking')} | "
                f"{row.get('input_data_limitation')} | {row.get('same_pattern_count')} |"
            )
        return "\n".join(lines) + "\n"

    def _race_report(self, rows):
        lines = [
            "# Race Health Check",
            "",
            "| race_id | course | surface | distance | condition | field | BUY | CAUTION | PASS | FN | FP | BUY3 | Top5_3 | primary | secondary | data | diagnosis |",
            "|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|",
        ]
        for row in rows:
            lines.append(
                f"| {row.get('race_id')} | {row.get('racecourse')} | {row.get('surface')} | {row.get('distance')} | "
                f"{row.get('track_condition')} | {row.get('field_size')} | {row.get('buy_count')} | "
                f"{row.get('caution_count')} | {row.get('pass_count')} | {row.get('fn_count')} | {row.get('fp_count')} | "
                f"{row.get('buy3_count')} | {row.get('top5_3_count')} | {row.get('primary_problem_area')} | "
                f"{row.get('secondary_problem_area')} | {row.get('data_limitation')} | {row.get('race_diagnosis')} |"
            )
        return "\n".join(lines) + "\n"

    def _pattern_report(self, patterns):
        lines = [
            "# Cross-Race Pattern Ranking",
            "",
            "| rank | pattern | races | horses | FN | FP | success | counter | evaluators | reproducibility | risk | evidence | next | recommendation |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|",
        ]
        for index, row in enumerate(patterns, start=1):
            lines.append(
                f"| {index} | {row.get('pattern_name')} | {row.get('affected_races')} | {row.get('affected_horses')} | "
                f"{row.get('fn_count')} | {row.get('fp_count')} | {row.get('success_count')} | {row.get('counterexample_count')} | "
                f"{', '.join(row.get('related_evaluators') or [])} | {row.get('reproducibility')} | {row.get('side_effect_risk')} | "
                f"{row.get('evidence_strength')} | {row.get('next_step_candidate')} | {row.get('recommendation')} |"
            )
        return "\n".join(lines) + "\n"

    def _decision_report(self, decision):
        lines = [
            "# Decision Structure Diagnosis",
            "",
            f"- High FinalScore but non-BUY: {decision.get('high_final_score_non_buy_count')}",
            f"- Low FinalScore cases: {decision.get('low_final_score_count')}",
            f"- AdjustedScore conversion issue candidates: {decision.get('adjusted_conversion_issue_count')}",
            f"- Near Decision boundary cases: {decision.get('near_decision_boundary_count')}",
            f"- Relative ranking issue cases: {decision.get('relative_ranking_issue_count')}",
            f"- BUY too many races: {decision.get('buy_too_many_races')}",
            f"- BUY zero races: {decision.get('buy_too_few_races')}",
            "",
            "## Details",
            "",
            json.dumps(decision.get("details"), ensure_ascii=False, indent=2),
        ]
        return "\n".join(lines) + "\n"

    def _data_gap_report(self, data_gaps):
        lines = [
            "# Data Gap Inventory",
            "",
            "| item | category | area | missing | addable | burden | historical | priority | recommendation | note |",
            "|---|---|---|---:|---|---|---|---|---|---|",
        ]
        for row in data_gaps.get("items") or []:
            lines.append(
                f"| {row.get('item_name')} | {row.get('category')} | {row.get('affected_area')} | {row.get('missing_count')} | "
                f"{row.get('additional_possible')} | {row.get('weekly_input_burden')} | {row.get('historical_data_addable')} | "
                f"{row.get('priority')} | {row.get('recommendation')} | {row.get('note')} |"
            )
        return "\n".join(lines) + "\n"

    def _priority_report(self, rows):
        lines = [
            "# Next Improvement Priority",
            "",
            "| rank | area | evidence | races | FN | FP | counter | benefit | risk | confidence | action | reason |",
            "|---:|---|---:|---:|---:|---:|---:|---|---|---|---|---|",
        ]
        for row in rows:
            lines.append(
                f"| {row.get('rank')} | {row.get('area')} | {row.get('evidence_count')} | {row.get('affected_races')} | "
                f"{row.get('fn_related')} | {row.get('fp_related')} | {row.get('success_counterexamples')} | "
                f"{row.get('estimated_benefit')} | {row.get('side_effect_risk')} | {row.get('confidence')} | "
                f"{row.get('recommended_action')} | {row.get('reason')} |"
            )
        return "\n".join(lines) + "\n"

    def _update_learning_candidate(self, metrics):
        path = Path("learning/improvement_candidates.json")
        database = self._load_json(path, {"version": "1.0", "engine": "LearningCandidateEngine", "records": []})
        records = self._list(database.get("records"))
        now = datetime.now(timezone.utc).isoformat()
        record = None
        for item in records:
            if item.get("candidate_id") == "overall_22race_health_check":
                record = item
                break
        if record is None:
            record = {
                "candidate_id": "overall_22race_health_check",
                "race_id": "phase_g_step3_22race_health",
                "horse": "overall_health_check",
                "case_type": "SYSTEM_DIAGNOSTIC",
                "decision": "N/A",
                "actual_finish": None,
                "fn": False,
                "fp": False,
                "primary_candidate": "HealthCheck",
                "status": "NEW",
                "priority": "high",
                "created_at": now,
                "attribution_candidates": [
                    {
                        "target": "HealthCheck",
                        "target_type": "Diagnostic",
                        "candidate_type": "Diagnostic",
                        "score": 1.0,
                        "confidence": "HIGH",
                        "evidence": ["22-race evaluator health check completed"],
                        "counter_evidence": [],
                    }
                ],
            }
            records.insert(0, record)
        record.update(
            {
                "validation_version": self.VERSION,
                "status": "NEW" if record.get("status") in {None, "", "IMPLEMENTED"} else record.get("status"),
                "baseline": metrics.get("baseline"),
                "evaluator_health_summary": metrics.get("evaluator_health_summary"),
                "FN_category_counts": metrics.get("fn_category_counts"),
                "FP_category_counts": metrics.get("fp_category_counts"),
                "race_diagnosis_counts": metrics.get("race_diagnosis_counts"),
                "top_cross_race_patterns": metrics.get("top_cross_race_patterns"),
                "decision_issue_count": metrics.get("decision_issue_count"),
                "evaluator_issue_count": metrics.get("evaluator_issue_count"),
                "multiple_cause_count": metrics.get("multiple_cause_count"),
                "data_insufficient_count": metrics.get("data_insufficient_count"),
                "top_priority_area": metrics.get("top_priority_area"),
                "recommended_next_step": metrics.get("recommended_next_step"),
                "official_baseline_unchanged": metrics.get("official_baseline_unchanged"),
                "diagnostic_only": True,
                "note": "Diagnostic-only PhaseG Step3 record; no evaluator, score, Decision, Knowledge, CSV, or main.py logic was changed.",
                "updated_at": now,
                "ranking_active": True,
            }
        )
        database["records"] = records
        database["updated_at"] = now
        self._write_json(path, database)
        return {"candidate_id": record.get("candidate_id"), "updated": True, "status": record.get("status")}

    # Helpers
    def _complete_sets(self, analysis_dir, results_dir):
        found = RaceFileLocator().find_complete_race_sets(analysis_dir, results_dir)
        return [
            row for row in self._list(found.get("complete_sets"))
            if self._race_id_part(row.get("race_id"), 1) in self.BASELINE_DATES
        ]

    def _race_context(self, race_id, race_result, analysis):
        parts = str(race_id or "").split("_")
        return {
            "race_date": race_result.get("race_date") or (parts[1] if len(parts) > 1 else ""),
            "racecourse": race_result.get("racecourse") or (parts[2] if len(parts) > 2 else ""),
            "race_number": race_result.get("race_number") or (parts[3] if len(parts) > 3 else ""),
            "surface": race_result.get("surface") or self._first_present(analysis, ["surface"]),
            "distance": self._to_int(race_result.get("distance") or self._first_present(analysis, ["distance"])),
            "distance_category": self._distance_category(race_result.get("distance") or self._first_present(analysis, ["distance"])),
            "track_condition": race_result.get("track_condition") or self._first_present(analysis, ["track_condition"]),
            "field_size": self._to_int(race_result.get("field_size")),
        }

    def _baseline(self, rows):
        decisions = Counter(row.get("decision") for row in rows)
        return {
            "races": len(set(row.get("race_id") for row in rows)),
            "horses": len(rows),
            "BUY": decisions.get("BUY", 0),
            "CAUTION": decisions.get("CAUTION", 0),
            "PASS": decisions.get("PASS", 0),
            "FN": sum(1 for row in rows if row.get("case_type") == "FN"),
            "FP": sum(1 for row in rows if row.get("case_type") == "FP"),
            "BUY3": sum(1 for row in rows if row.get("decision") == "BUY" and row.get("finish_position") in {1, 2, 3}),
            "Top5_3": sum(1 for row in rows if row.get("top5") and row.get("finish_position") in {1, 2, 3}),
        }

    def _ranked(self, rows):
        ranked = [row for row in self._list(rows) if isinstance(row, dict)]
        return sorted(
            ranked,
            key=lambda row: (
                self._to_float(row.get("adjusted_score")) or 0.0,
                self._to_int(row.get("horse_number")) or 0,
            ),
            reverse=True,
        )

    def _official_map(self, rows):
        return {self._norm(row.get("horse_name")): row for row in rows if isinstance(row, dict)}

    def _lookup(self, mapping, name):
        return mapping.get(self._norm(name))

    def _last3f_ranks(self, rows):
        values = []
        for row in rows:
            value = self._to_float(row.get("last_3f"))
            if value is not None:
                values.append((value, self._norm(row.get("horse_name"))))
        values.sort()
        return {name: rank for rank, (_, name) in enumerate(values, start=1)}

    def _scores(self, horse):
        keys = [
            "past_performance_score",
            "distance_score",
            "course_shape_score",
            "pace_style_score",
            "lap_score",
            "shape_score",
            "track_bias_score",
            "bloodline_score",
            "track_condition_score",
            "impact_score",
            "confidence_score",
            "decision_score",
        ]
        return {key: self._to_float(horse.get(key)) for key in keys}

    def _score(self, row, key):
        return (row.get("scores") or {}).get(key)

    def _score_primary(self, horse, case_type):
        scores = self._scores(horse)
        if case_type == "FN":
            lows = [
                ("LapSuitabilityEvaluator", scores.get("lap_score"), -4),
                ("RaceShapeEvaluator", scores.get("shape_score"), -4),
                ("PaceStyleEvaluator", scores.get("pace_style_score"), 10),
                ("DistanceEvaluator", scores.get("distance_score"), 20),
                ("BloodlineEvaluator", scores.get("bloodline_score"), 0),
                ("PastPerformanceEvaluator", scores.get("past_performance_score"), 30),
            ]
            candidates = [(name, value, threshold) for name, value, threshold in lows if value is not None and value <= threshold]
            if candidates:
                return sorted(candidates, key=lambda item: item[1] - item[2])[0][0]
            return "DecisionEngine"
        if case_type == "FP":
            highs = [
                ("PastPerformanceEvaluator", scores.get("past_performance_score"), 70),
                ("BloodlineEvaluator", scores.get("bloodline_score"), 20),
                ("RaceShapeEvaluator", scores.get("shape_score"), 8),
                ("PaceStyleEvaluator", scores.get("pace_style_score"), 20),
                ("DistanceEvaluator", scores.get("distance_score"), 35),
                ("ImpactEvaluator", scores.get("impact_score"), 8),
            ]
            candidates = [(name, value, threshold) for name, value, threshold in highs if value is not None and value >= threshold]
            if candidates:
                return sorted(candidates, key=lambda item: item[1] - item[2], reverse=True)[0][0]
            return "DecisionEngine"
        return "No Immediate Change"

    def _secondary_causes(self, horse, attribution, root, primary):
        values = []
        for key in ["root_secondary_candidates", "secondary_blockers", "secondary_supporters"]:
            source = root.get(key) if key.startswith("root") else attribution.get(key)
            for item in self._list(source):
                target = item.get("target") if isinstance(item, dict) else item
                if target and target != primary and target not in values:
                    values.append(target)
        for name, keys, low, high in self.EVALUATORS:
            if name == primary:
                continue
            for key in keys:
                value = self._to_float(horse.get(key))
                if value is None:
                    continue
                if value < low or value >= high:
                    if name not in values:
                        values.append(name)
                    break
        return values[:5]

    def _case_category(self, case_type, horse, rank, primary, secondary):
        data_missing = bool(self._row_data_limitations(horse, {}, {}))
        decision_score = self._to_float(horse.get("decision_score")) or 0
        if case_type == "FN":
            if data_missing:
                return "F_INPUT_DATA_LIMITATION"
            if len(secondary) >= 2:
                return "H_MULTIPLE_CAUSES"
            if rank > 5:
                return "D_RELATIVE_RANKING"
            if decision_score >= 0.65:
                return "C_DECISION_BOUNDARY"
            if primary and primary not in {"DecisionEngine", "UNKNOWN"}:
                return "A_EVALUATOR_UNDERESTIMATION"
            return "G_HARD_TO_PREDICT"
        if case_type == "FP":
            if data_missing:
                return "F_INPUT_DATA_LIMITATION"
            if len(secondary) >= 2:
                return "H_MULTIPLE_CAUSES"
            if primary and primary not in {"DecisionEngine", "UNKNOWN"}:
                return "A_EVALUATOR_OVERVALUATION"
            if decision_score >= 0.75:
                return "C_DECISION_REFLECTION_INSUFFICIENT"
            return "G_HARD_TO_PREDICT"
        return "NORMAL"

    def _decision_boundary(self, row):
        score = row.get("decision_score")
        if score is None:
            return "UNKNOWN"
        if 0.65 <= score < 0.8 and row.get("decision") != "BUY":
            return "NEAR_BUY"
        if row.get("decision") == "BUY" and score < 0.85:
            return "LOW_MARGIN_BUY"
        return "NOT_BOUNDARY"

    def _relative_ranking(self, row):
        rank = row.get("ai_rank") or 99
        if row.get("case_type") == "FN" and rank > 5:
            return "RANK_BLOCKED"
        if row.get("case_type") == "FP" and rank <= 5:
            return "TOP5_BUY_FAILED"
        return "NOT_PRIMARY"

    def _near_boundary(self, row):
        score = row.get("decision_score")
        if score is None:
            return False
        return 0.65 <= score < 0.85

    def _major_plus(self, horse):
        scores = self._scores(horse)
        return [key for key, value in scores.items() if value is not None and value >= self._plus_threshold(key)][:5]

    def _major_minus(self, horse):
        scores = self._scores(horse)
        return [key for key, value in scores.items() if value is not None and value <= self._minus_threshold(key)][:5]

    def _plus_threshold(self, key):
        return {"decision_score": 0.8, "confidence_score": 0.75, "impact_score": 8, "shape_score": 8, "lap_score": 8}.get(key, 20)

    def _minus_threshold(self, key):
        return {"decision_score": 0.5, "confidence_score": 0.45, "impact_score": -1, "shape_score": -4, "lap_score": -4}.get(key, 0)

    def _row_data_limitations(self, horse, result, context):
        missing = []
        if not horse.get("explain_summary") and not horse.get("explanation"):
            missing.append("explain")
        if self._to_float(horse.get("bloodline_score")) in {None, 0}:
            missing.append("bloodline_score_zero_or_missing")
        if result and self._to_int(result.get("fourth_corner_position")) is None:
            missing.append("fourth_corner_position")
        if result and self._to_float(result.get("last_3f")) is None:
            missing.append("last_3f")
        if context and context.get("track_condition") in {None, "", "UNKNOWN"}:
            missing.append("track_condition")
        return missing

    def _health_status(self, name, fn_count, fp_count, data_missing, mismatch, multiple):
        if data_missing >= 250 and name not in {"RaceDecisionEngine", "ExplainEngine"}:
            return "DATA_INSUFFICIENT"
        if fn_count >= 10 and fp_count >= 5:
            return "CONFLICT_RISK"
        if fn_count >= 8:
            return "UNDERVALUATION_RISK"
        if fp_count >= 8:
            return "OVERVALUATION_RISK"
        if multiple >= 10:
            return "WATCH"
        if mismatch >= 20:
            return "WEAK_SIGNAL"
        if fn_count + fp_count == 0:
            return "HEALTHY"
        return "WATCH"

    def _health_comment(self, health, name):
        return {
            "HEALTHY": "No clear cross-race issue in this diagnostic.",
            "WATCH": "Signals exist but are not enough for immediate implementation.",
            "WEAK_SIGNAL": "Score/explain linkage needs review before changes.",
            "OVERVALUATION_RISK": "Related more often to FP than FN.",
            "UNDERVALUATION_RISK": "Related more often to FN than FP.",
            "CONFLICT_RISK": "Appears on both FN and FP paths.",
            "DATA_INSUFFICIENT": "Current data is insufficient for reliable judgment.",
        }.get(health, f"{name} not assessable")

    def _explain_mismatch_count(self, rows, evaluator, keys):
        if not keys:
            return 0
        mismatch = 0
        token = evaluator.replace("Evaluator", "").replace("Engine", "").lower()
        for row in rows:
            has_score = any(self._score(row, key) is not None for key in keys)
            text = str(row.get("explain_summary") or "").lower()
            if has_score and token not in text and len(text) < 10:
                mismatch += 1
        return mismatch

    def _race_primary_area(self, fn, fp, buy3, top5_3):
        if len(fn) + len(fp) == 0:
            return "No Immediate Change"
        counter = Counter(row.get("primary_cause") for row in fn + fp)
        return counter.most_common(1)[0][0] if counter else "UNKNOWN"

    def _secondary_problem_area(self, fn, fp):
        counter = Counter()
        for row in fn + fp:
            for cause in row.get("secondary_causes", []):
                counter[cause] += 1
        return counter.most_common(1)[0][0] if counter else "none"

    def _race_diagnosis(self, fn, fp, buy3, top5_3, rows):
        if not fn and not fp:
            return "HEALTHY"
        if len(fn) + len(fp) <= 2 and (buy3 or top5_3):
            return "MOSTLY_HEALTHY"
        if any(row.get("data_limitations") for row in rows) and len(fn) + len(fp) >= 4:
            return "DATA_INSUFFICIENT"
        if len(fn) >= 3 and len(fp) >= 2:
            return "MULTIPLE_CAUSES"
        if len(fn) >= 3 or len(fp) >= 3:
            return "EVALUATOR_ISSUE"
        return "REVIEW_REQUIRED"

    def _race_success_factors(self, rows):
        return Counter(row.get("primary_cause") for row in rows if row.get("decision") == "BUY" and row.get("finish_position") in {1, 2, 3}).most_common(3)

    def _race_failure_factors(self, fn, fp):
        return Counter(row.get("primary_cause") for row in fn + fp).most_common(3)

    def _race_data_limitation(self, rows):
        return "YES" if any(row.get("data_limitations") for row in rows) else "NO"

    def _related_evaluators(self, group):
        counter = Counter(row.get("primary_cause") for row in group if row.get("case_type") in {"FN", "FP"})
        return [name for name, _ in counter.most_common(4) if name]

    def _pattern_cause(self, name, value, fn_count, fp_count):
        if name in {"primary_cause", "decision", "final_score_band", "adjusted_score_band"}:
            return "Decision/Evaluator boundary"
        if name in {"running_style", "fourth_corner_bucket"}:
            return "Pace/RaceShape interaction"
        if name in {"racecourse", "surface", "distance_category", "track_condition"}:
            return "Condition segment bias"
        return "Cross-race segment"

    def _missing_count(self, item, rows, races):
        if item == "course_configuration":
            return len(races)
        if item in {"meeting_day", "meeting_week", "water_content", "previous_day_trend", "manual_track_bias"}:
            return len(races)
        if item == "last_3f":
            return sum(1 for row in rows if row.get("last_3f") is None)
        if item == "fourth_corner_position":
            return sum(1 for row in rows if row.get("fourth_corner_position") is None)
        if item == "odds_popularity":
            return 0
        return 0

    def _area_evidence_count(self, area, fn_counts, fp_counts, evaluator_issue, decision, data_gaps, patterns):
        if area == "Decision Boundary":
            return decision.get("near_decision_boundary_count", 0)
        if area == "Relative Ranking":
            return decision.get("relative_ranking_issue_count", 0)
        if area == "Input Data":
            return sum(1 for row in data_gaps.get("items", []) if row.get("priority") == "HIGH" and row.get("missing_count", 0) > 0)
        if area == "Evaluator Combination":
            return sum(1 for row in patterns if len(row.get("related_evaluators") or []) >= 2)
        mapping = {
            "RaceShape": "RaceShapeEvaluator",
            "Pace": "PaceStyleEvaluator",
            "RunningStyle": "RunningStyleEvaluator",
            "Course": "CourseShapeEvaluator",
            "TrackBias": "TrackBiasEvaluator",
            "LapSuitability": "LapSuitabilityEvaluator",
            "Ability": "PastPerformanceEvaluator",
            "Distance": "DistanceEvaluator",
            "Bloodline": "BloodlineEvaluator",
            "Confidence": "ConfidenceEngine",
            "Impact": "ImpactEvaluator",
            "Explain": "ExplainEngine",
            "MeetingBias": "MeetingBias",
        }
        target = mapping.get(area, area)
        return fn_counts.get(target, 0) + fp_counts.get(target, 0) + (1 if target in evaluator_issue else 0)

    def _area_count(self, area, counts):
        mapping = {
            "RaceShape": "RaceShapeEvaluator",
            "Pace": "PaceStyleEvaluator",
            "RunningStyle": "RunningStyleEvaluator",
            "Course": "CourseShapeEvaluator",
            "TrackBias": "TrackBiasEvaluator",
            "LapSuitability": "LapSuitabilityEvaluator",
            "Ability": "PastPerformanceEvaluator",
            "Distance": "DistanceEvaluator",
            "Bloodline": "BloodlineEvaluator",
            "Confidence": "ConfidenceEngine",
            "Impact": "ImpactEvaluator",
            "Decision Boundary": "DecisionEngine",
        }
        return counts.get(mapping.get(area, area), 0)

    def _area_races(self, area, patterns):
        related = [row.get("affected_races", 0) for row in patterns if area.lower().split()[0] in row.get("pattern_name", "").lower()]
        return max(related) if related else 0

    def _area_counterexamples(self, area, patterns):
        return sum(row.get("counterexample_count", 0) for row in patterns if area.lower().split()[0] in row.get("pattern_name", "").lower())

    def _area_risk(self, area, data_gaps, fp_related):
        if area in {"MeetingBias", "Input Data"}:
            return "MEDIUM"
        if fp_related >= 8:
            return "HIGH"
        if fp_related >= 3:
            return "MEDIUM"
        return "LOW"

    def _area_confidence(self, evidence_count, affected_races, area):
        if area == "MeetingBias":
            return "LOW"
        if evidence_count >= 10:
            return "HIGH"
        if evidence_count >= 4:
            return "MEDIUM"
        return "LOW"

    def _area_action(self, area, evidence_count, confidence, risk):
        if area == "Input Data" and evidence_count:
            return "DATA_COLLECTION"
        if area == "MeetingBias":
            return "HOLD"
        if confidence == "HIGH" and risk != "HIGH":
            return "NEXT_ANALYSIS"
        if confidence == "MEDIUM":
            return "WATCH"
        return "HOLD" if evidence_count else "NO_CHANGE"

    def _benefit(self, evidence_count, fn_related, fp_related):
        if fn_related >= 8 and fp_related <= 3:
            return "HIGH"
        if evidence_count >= 8:
            return "MEDIUM"
        return "LOW"

    def _area_reason(self, area, evidence_count, fn_related, fp_related, risk):
        return f"evidence={evidence_count}, FN={fn_related}, FP={fp_related}, risk={risk}"

    def _action_value(self, action):
        return {"NEXT_ANALYSIS": 5, "DATA_COLLECTION": 4, "SHADOW_CANDIDATE": 4, "WATCH": 3, "HOLD": 2, "NO_CHANGE": 1, "REJECT": 0}.get(action, 0)

    def _brief_rows(self, rows):
        return [
            {
                "race_id": row.get("race_id"),
                "horse": row.get("horse_name"),
                "finish": row.get("finish_position"),
                "decision": row.get("decision"),
                "rank": row.get("ai_rank"),
                "final_score": row.get("final_score"),
                "adjusted_score": row.get("adjusted_score"),
                "decision_score": row.get("decision_score"),
                "primary_cause": row.get("primary_cause"),
            }
            for row in rows
        ]

    def _frame_bucket(self, value):
        frame = self._to_int(value)
        if frame is None:
            return "unknown"
        if frame <= 3:
            return "inside"
        if frame >= 6:
            return "outside"
        return "middle"

    def _corner_bucket(self, value):
        pos = self._to_int(value)
        if pos is None:
            return "unknown"
        if pos <= 4:
            return "front"
        if pos <= 8:
            return "middle"
        return "rear"

    def _score_band(self, value):
        score = self._to_float(value)
        if score is None:
            return "unknown"
        lower = int(score // 20) * 20
        return f"{lower}-{lower + 19}"

    def _distance_category(self, value):
        distance = self._to_int(value)
        if distance is None:
            return "unknown"
        if distance <= 1400:
            return "sprint"
        if distance <= 1600:
            return "mile"
        if distance <= 2200:
            return "middle"
        return "long"

    def _first_present(self, mapping, keys):
        if not isinstance(mapping, dict):
            return None
        for key in keys:
            value = mapping.get(key)
            if value not in {None, ""}:
                return value
        return None

    def _nested(self, mapping, keys):
        value = mapping
        for key in keys:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value

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

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _norm(self, value):
        return "".join(str(value or "").split())

    def _race_id_part(self, race_id, index):
        parts = str(race_id or "").split("_")
        return parts[index] if len(parts) > index else ""

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
    result = Overall22RaceHealthCheck().run()
    print(
        {
            "race_count": result.get("race_count"),
            "horse_count": result.get("horse_count"),
            "baseline_match": result.get("baseline_match"),
            "top_priority_area": result.get("top_priority_area"),
            "final_judgment": result.get("final_judgment"),
        }
    )
