"""Trial adapter for TARGET entry and history CSV files.

This module is only a trial connector.  It reads TARGET-style entry data and
TARGET S-style history data, converts them into the existing TrialRunner input
shape, and runs the current Evaluation Engine without touching the production
Analyzer or main.py.
"""

import csv
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine.consistency_engine import ConsistencyEngine
from engine.confidence_engine import ConfidenceEngine
from engine.decision_engine import DecisionEngine
from engine.explain_engine import ExplainEngine
from engine.final_output_formatter import FinalOutputFormatter
from engine.improvement_advisor import ImprovementAdvisor
from engine.learning_database import LearningDatabase
from engine.learning_engine import LearningEngine
from engine.race_decision_engine import RaceDecisionEngine
from engine.race_structure_engine import RaceStructureEngine
from engine.race_summary_engine import RaceSummaryEngine
from engine.review_recorder import ReviewRecorder
from engine.review_engine import ReviewEngine
from engine.result_importer import ResultImporter
from engine.self_check_engine import SelfCheckEngine
from engine.trial_report_exporter import TrialReportExporter
from evaluation.distance_suitability_evaluator import DistanceSuitabilityEvaluator
from evaluation.final_score_integrator import FinalScoreIntegrator
from evaluation.impact_evaluator import ImpactEvaluator
from evaluation.pace_style_evaluator import PaceStyleEvaluator
from evaluation.past_performance_evaluator import PastPerformanceEvaluator
from evaluation.race_pace_predictor import RacePacePredictor
from evaluation.race_shape_evaluator import RaceShapeEvaluator
from evaluation.track_condition_suitability_evaluator import TrackConditionSuitabilityEvaluator
from evaluation.trial_runner import TrialRunner
from evaluators.course_shape_evaluator import CourseShapeEvaluator
from evaluators.lap_suitability_evaluator import LapSuitabilityEvaluator
from evaluators.score_weight_evaluator import ScoreWeightEvaluator
from evaluators.track_bias_evaluator import TrackBiasEvaluator
from importer.target_entry_importer import TargetEntryImporter
from importer.target_history_importer import (
    TargetHistoryImporter,
    attach_histories_to_entries,
)


class TargetTrialAdapter:
    """Connect TARGET importer output to the trial Evaluation Engine."""

    HISTORY_LIMIT = 5

    def __init__(self):
        self.entry_importer = TargetEntryImporter()
        self.consistency_engine = ConsistencyEngine()
        self.confidence_engine = ConfidenceEngine()
        self.decision_engine = DecisionEngine()
        self.explain_engine = ExplainEngine()
        self.final_output_formatter = FinalOutputFormatter()
        self.history_importer = TargetHistoryImporter()
        self.improvement_advisor = ImprovementAdvisor()
        self.learning_database = LearningDatabase()
        self.learning_engine = LearningEngine()
        self.course_shape_evaluator = CourseShapeEvaluator()
        self.distance_suitability_evaluator = DistanceSuitabilityEvaluator()
        self.final_score_integrator = FinalScoreIntegrator()
        self.impact_evaluator = ImpactEvaluator()
        self.lap_suitability_evaluator = LapSuitabilityEvaluator()
        self.past_performance_evaluator = PastPerformanceEvaluator()
        self.pace_style_evaluator = PaceStyleEvaluator()
        self.race_decision_engine = RaceDecisionEngine()
        self.race_pace_predictor = RacePacePredictor()
        self.race_structure_engine = RaceStructureEngine()
        self.race_summary_engine = RaceSummaryEngine()
        self.review_recorder = ReviewRecorder()
        self.review_engine = ReviewEngine()
        self.result_importer = ResultImporter()
        self.self_check_engine = SelfCheckEngine()
        self.trial_report_exporter = TrialReportExporter()
        self.race_shape_evaluator = RaceShapeEvaluator()
        self.score_weight_evaluator = ScoreWeightEvaluator()
        self.track_bias_evaluator = TrackBiasEvaluator()
        self.track_condition_suitability_evaluator = TrackConditionSuitabilityEvaluator()
        self.runner = TrialRunner()

    def run(self, entry_csv_path, history_csv_path):
        """Load entry/history CSV files and evaluate all entries safely."""

        entries = self.entry_importer.load(entry_csv_path)
        histories = self.history_importer.load(history_csv_path)
        pairs = attach_histories_to_entries(entries, histories)
        race_defaults = self._read_race_defaults(entry_csv_path)

        horse_results = []
        for entry, history in pairs:
            raw_data = self._build_raw_data(entry, race_defaults, history)
            trial_result = self.runner.run(raw_data)
            history_runs = self._history_runs(history)
            past_result = self.past_performance_evaluator.evaluate(
                recent_runs=history_runs,
                racecourse=race_defaults.get("racecourse"),
                surface=race_defaults.get("surface"),
                distance=race_defaults.get("distance"),
                track_condition=race_defaults.get("track_condition"),
                horse_name=getattr(entry, "horse_name", None),
            )
            combined_result = self._merge_past_performance(trial_result, past_result)
            pace_style_result = self.pace_style_evaluator.evaluate(
                recent_runs=history_runs,
                racecourse=race_defaults.get("racecourse"),
                surface=race_defaults.get("surface"),
                distance=race_defaults.get("distance"),
                horse_name=getattr(entry, "horse_name", None),
            )
            combined_result = self._merge_pace_style(combined_result, pace_style_result)
            distance_result = self.distance_suitability_evaluator.evaluate(
                recent_runs=history_runs,
                distance=race_defaults.get("distance"),
                surface=race_defaults.get("surface"),
                horse_name=getattr(entry, "horse_name", None),
            )
            combined_result = self._merge_distance(combined_result, distance_result)
            condition_result = self.track_condition_suitability_evaluator.evaluate(
                recent_runs=history_runs,
                surface=race_defaults.get("surface"),
                track_condition=race_defaults.get("track_condition"),
                horse_name=getattr(entry, "horse_name", None),
            )
            combined_result = self._merge_track_condition_suitability(
                combined_result,
                condition_result,
            )
            warnings = self._build_warnings(entry, history, combined_result)
            bloodline_score = self._score_by_source_type(combined_result, "bloodline")

            horse_results.append(
                {
                    "horse_name": getattr(entry, "horse_name", None),
                    "horse_number": getattr(entry, "horse_number", None),
                    "frame_number": getattr(entry, "frame_number", None),
                    "gate": getattr(entry, "frame_number", None),
                    "racecourse": race_defaults.get("racecourse"),
                    "surface": race_defaults.get("surface"),
                    "distance": race_defaults.get("distance"),
                    "track_condition": race_defaults.get("track_condition"),
                    "total_score": combined_result.get("total_score", 0),
                    "bloodline_score": bloodline_score,
                    "past_performance_score": past_result.get("past_performance_score", 0),
                    "pace_style_score": pace_style_result.get("pace_style_score", 0),
                    "distance_score": distance_result.get("distance_score", 0),
                    "track_condition_score": condition_result.get("track_condition_score", 0),
                    "shape_score": 0,
                    "shape_comment": "",
                    "race_structure": {},
                    "structure_comment": "",
                    "key_factors": [],
                    "structure_flags": {},
                    "recommended_weights_hint": {},
                    "course_shape_score": 0,
                    "course_shape_comment": "",
                    "course_shape_result": {},
                    "track_bias_score": 0,
                    "track_bias_comment": "",
                    "track_bias_result": {},
                    "lap_style": "unknown",
                    "lap_score": 0,
                    "lap_comment": "",
                    "lap_result": {},
                    "score_weights": {},
                    "weight_source": "default",
                    "weight_comment": "",
                    "weighted_score": 0,
                    "integrated_score": 0,
                    "weighted_score_breakdown": {},
                    "consistency_result": {},
                    "consistency_score": 0,
                    "consistency_level": "",
                    "strong_matches": [],
                    "weak_matches": [],
                    "conflict_factors": [],
                    "consistency_comment": "",
                    "bonus_hint": "none",
                    "penalty_hint": "none",
                    "consistency_weight_adjustments": {},
                    "explanation": "",
                    "explain_summary": "",
                    "consistency_explanation": "",
                    "consistency_summary": "",
                    "strengths": [],
                    "weaknesses": [],
                    "risk_factors": [],
                    "confidence_reason": "",
                    "explain_result": {},
                    "final_rank": None,
                    "final_summary": "",
                    "final_reasons": [],
                    "final_strengths": [],
                    "final_weaknesses": [],
                    "final_risks": [],
                    "final_score_view": {},
                    "final_output": {},
                    "final_score": 0,
                    "impact_score": 0,
                    "adjusted_score": 0,
                    "impact_comment": "",
                    "impact_result": {},
                    "decision": "",
                    "decision_score": 0,
                    "decision_level": "",
                    "decision_reason": "",
                    "decision_factors": [],
                    "decision_risks": [],
                    "decision_result": {},
                    "score_breakdown": {},
                    "distance_fit": distance_result.get("distance_fit", "unknown"),
                    "distance_fit_label": distance_result.get("distance_fit_label", "判定不能"),
                    "track_condition_fit": condition_result.get("track_condition_fit", "unknown"),
                    "track_condition_fit_label": condition_result.get("track_condition_fit_label", "判定不能"),
                    "pace_style": pace_style_result.get("pace_style", "unknown"),
                    "pace_style_label": pace_style_result.get("pace_style_label", "判定不能"),
                    "summary": combined_result.get("summary_text", ""),
                    "sections": combined_result.get("sections", {}),
                    "warnings": warnings,
                    "history_count": len(history_runs),
                    "recent_runs": history_runs[: self.HISTORY_LIMIT],
                    "distance_result": distance_result,
                    "track_condition_suitability_result": condition_result,
                    "past_performance_result": past_result,
                    "pace_style_result": pace_style_result,
                    "matched_results": combined_result.get("matched_results", []),
                    "unmatched_results": combined_result.get("unmatched_results", []),
                    "modifier_summary": combined_result.get("modifier_summary", {}),
                }
            )

        race_pace_result = self._apply_race_shape_and_final_scores(
            horse_results,
            race_defaults,
        )
        race_structure_result = race_pace_result.get("race_structure_result", {})
        ranked_results = sorted(
            horse_results,
            key=lambda item: (self._safe_number(item.get("adjusted_score")), self._horse_number(item)),
            reverse=True,
        )
        race_decision_result = self.race_decision_engine.decide(
            {
                "race_structure": race_structure_result.get("race_structure", {}),
                "structure_comment": race_structure_result.get("structure_comment", ""),
                "key_factors": race_structure_result.get("key_factors", []),
                "structure_flags": race_structure_result.get("structure_flags", {}),
                "recommended_weights_hint": race_structure_result.get("recommended_weights_hint", {}),
            },
            horse_results,
        )
        race_confidence_context = {
            "race_decision": race_decision_result.get("race_decision"),
            "race_confidence": race_decision_result.get("race_confidence"),
            "race_complexity": race_decision_result.get("race_complexity"),
            "race_volatility": race_decision_result.get("race_volatility"),
        }
        confidence_results = self.confidence_engine.evaluate_many(
            horse_results,
            race_confidence_context,
        )
        for index, item in enumerate(horse_results):
            confidence_result = confidence_results[index] if index < len(confidence_results) else {}
            item["explain_confidence_reason"] = item.get("confidence_reason", "")
            item["confidence_score"] = confidence_result.get("confidence_score", 0.5)
            item["confidence_level"] = confidence_result.get("confidence_level", "medium")
            item["confidence_reason"] = confidence_result.get("confidence_reason", "")
            item["confidence_factors"] = confidence_result.get("confidence_factors", [])
            item["confidence_risks"] = confidence_result.get("confidence_risks", [])
            item["confidence_result"] = confidence_result
        race_summary_result = self.race_summary_engine.build(
            {
                "race_structure": race_structure_result.get("race_structure", {}),
                "structure_comment": race_structure_result.get("structure_comment", ""),
                "structure_comment_parts": race_structure_result.get("structure_comment_parts", []),
                "key_factors": race_structure_result.get("key_factors", []),
                "structure_flags": race_structure_result.get("structure_flags", {}),
                "recommended_weights_hint": race_structure_result.get("recommended_weights_hint", {}),
                "race_decision": race_decision_result.get("race_decision"),
                "race_decision_score": race_decision_result.get("race_decision_score"),
                "race_decision_level": race_decision_result.get("race_decision_level"),
                "race_decision_reason": race_decision_result.get("race_decision_reason"),
                "race_decision_factors": race_decision_result.get("race_decision_factors", []),
                "race_decision_risks": race_decision_result.get("race_decision_risks", []),
                "race_confidence": race_decision_result.get("race_confidence"),
                "race_complexity": race_decision_result.get("race_complexity"),
                "race_volatility": race_decision_result.get("race_volatility"),
                "race_decision_result": race_decision_result,
            },
            horse_results,
        )
        self_check_result = self.self_check_engine.check(
            {
                "race_decision": race_decision_result.get("race_decision"),
                "race_confidence": race_decision_result.get("race_confidence"),
                "race_summary": race_summary_result.get("race_summary"),
                "race_summary_short": race_summary_result.get("race_summary_short"),
                "race_confidence_summary": race_summary_result.get("race_confidence_summary", {}),
                "race_risk_summary": race_summary_result.get("race_risk_summary", {}),
            },
            horse_results,
        )
        race_output = self.final_output_formatter.format_race(
            horse_results,
            {
                "race_structure": race_structure_result.get("race_structure", {}),
                "structure_comment": race_structure_result.get("structure_comment", ""),
                "key_factors": race_structure_result.get("key_factors", []),
                "recommended_weights_hint": race_structure_result.get("recommended_weights_hint", {}),
                "race_decision_result": race_decision_result,
                "race_summary_result": race_summary_result,
                "self_check_result": self_check_result,
            },
        )
        trial_report_result = self.trial_report_exporter.export(
            race_output,
            race_output.get("horses", []),
        )
        race_output["trial_report"] = trial_report_result.get("trial_report")
        race_output["trial_report_summary"] = trial_report_result.get("trial_report_summary")
        race_output["trial_report_horses"] = trial_report_result.get("trial_report_horses", [])
        race_output["trial_report_result"] = trial_report_result
        review_record_result = self.review_recorder.record(
            race_output,
            race_output.get("horses", []),
            trial_report_result.get("trial_report"),
        )
        race_output["prediction_snapshot"] = review_record_result.get("prediction_snapshot")
        race_output["prediction_time"] = review_record_result.get("prediction_time")
        race_output["prediction_id"] = review_record_result.get("prediction_id")
        race_output["review_record"] = review_record_result.get("review_record")
        race_output["review_status"] = review_record_result.get("review_status")
        race_output["review_ready"] = review_record_result.get("review_ready")
        result_import_result = self.result_importer.import_result(
            result_data=None,
            prediction_id=review_record_result.get("prediction_id"),
            review_record=review_record_result.get("review_record"),
            prediction_snapshot=review_record_result.get("prediction_snapshot"),
        )
        race_output["race_result"] = result_import_result.get("race_result")
        race_output["horse_results"] = result_import_result.get("horse_results", [])
        race_output["result_loaded"] = result_import_result.get("result_loaded")
        race_output["result_status"] = result_import_result.get("result_status")
        race_output["result_import_result"] = result_import_result
        review_result = self.review_engine.review(
            prediction_snapshot=review_record_result.get("prediction_snapshot"),
            race_result=result_import_result.get("race_result"),
            review_record=review_record_result.get("review_record"),
        )
        race_output["review_result"] = review_result
        race_output["review_summary"] = review_result.get("review_summary")
        race_output["review_score"] = review_result.get("review_score")
        race_output["review_level"] = review_result.get("review_level")
        race_output["review_hits"] = review_result.get("review_hits", [])
        race_output["review_misses"] = review_result.get("review_misses", [])
        race_output["review_comment"] = review_result.get("review_comment")
        improvement_result = self.improvement_advisor.advise(review_result)
        race_output["improvement_result"] = improvement_result
        race_output["improvement_summary"] = improvement_result.get("improvement_summary")
        race_output["improvement_suggestions"] = improvement_result.get("improvement_suggestions", [])
        race_output["improvement_targets"] = improvement_result.get("improvement_targets", [])
        race_output["improvement_priority"] = improvement_result.get("improvement_priority")
        race_output["improvement_comment"] = improvement_result.get("improvement_comment")
        learning_result = self.learning_database.save(
            prediction_snapshot=review_record_result.get("prediction_snapshot"),
            review_result=review_result,
            improvement_result=improvement_result,
            review_record=review_record_result.get("review_record"),
        )
        race_output["learning_record"] = learning_result.get("learning_record")
        race_output["learning_history"] = learning_result.get("learning_history", [])
        race_output["learning_id"] = learning_result.get("learning_id")
        race_output["learning_time"] = learning_result.get("learning_time")
        race_output["learning_status"] = learning_result.get("learning_status")
        learning_analysis = self.learning_engine.analyze(
            learning_history=learning_result.get("learning_history", []),
            learning_record=learning_result.get("learning_record"),
            review_result=review_result,
            improvement_result=improvement_result,
        )
        race_output["learning_analysis_result"] = learning_analysis.get("learning_analysis_result")
        race_output["learning_summary"] = learning_analysis.get("learning_summary")
        race_output["learning_trends"] = learning_analysis.get("learning_trends", {})
        race_output["success_patterns"] = learning_analysis.get("success_patterns", [])
        race_output["failure_patterns"] = learning_analysis.get("failure_patterns", [])
        race_output["frequent_improvement_targets"] = learning_analysis.get("frequent_improvement_targets", [])
        race_output["decision_trends"] = learning_analysis.get("decision_trends", {})
        race_output["confidence_trends"] = learning_analysis.get("confidence_trends", {})
        race_output["learning_comment"] = learning_analysis.get("learning_comment")

        return {
            "entry_count": len(entries),
            "history_count": len(histories),
            "linked_count": sum(1 for _, history in pairs if history is not None),
            "unlinked_horses": [
                getattr(entry, "horse_name", None)
                for entry, history in pairs
                if history is None
            ],
            "race_pace": race_pace_result,
            "race_structure": race_structure_result.get("race_structure", {}),
            "structure_comment": race_structure_result.get("structure_comment", ""),
            "structure_comment_parts": race_structure_result.get("structure_comment_parts", []),
            "key_factors": race_structure_result.get("key_factors", []),
            "structure_flags": race_structure_result.get("structure_flags", {}),
            "recommended_weights_hint": race_structure_result.get("recommended_weights_hint", {}),
            "race_decision": race_decision_result.get("race_decision"),
            "race_decision_score": race_decision_result.get("race_decision_score"),
            "race_decision_level": race_decision_result.get("race_decision_level"),
            "race_decision_reason": race_decision_result.get("race_decision_reason"),
            "race_decision_factors": race_decision_result.get("race_decision_factors", []),
            "race_decision_risks": race_decision_result.get("race_decision_risks", []),
            "race_confidence": race_decision_result.get("race_confidence"),
            "race_complexity": race_decision_result.get("race_complexity"),
            "race_volatility": race_decision_result.get("race_volatility"),
            "race_decision_result": race_decision_result,
            "race_summary": race_summary_result.get("race_summary"),
            "race_summary_short": race_summary_result.get("race_summary_short"),
            "race_summary_detail": race_summary_result.get("race_summary_detail"),
            "race_key_points": race_summary_result.get("race_key_points", []),
            "race_top_horses": race_summary_result.get("race_top_horses", []),
            "race_buy_horses": race_summary_result.get("race_buy_horses", []),
            "race_caution_horses": race_summary_result.get("race_caution_horses", []),
            "race_pass_horses": race_summary_result.get("race_pass_horses", []),
            "race_confidence_summary": race_summary_result.get("race_confidence_summary", {}),
            "race_risk_summary": race_summary_result.get("race_risk_summary", {}),
            "race_summary_result": race_summary_result,
            "self_check_score": self_check_result.get("self_check_score"),
            "self_check_level": self_check_result.get("self_check_level"),
            "self_check_comment": self_check_result.get("self_check_comment"),
            "self_check_warnings": self_check_result.get("self_check_warnings", []),
            "self_check_passed": self_check_result.get("self_check_passed"),
            "self_check_result": self_check_result,
            "trial_report": trial_report_result.get("trial_report"),
            "trial_report_summary": trial_report_result.get("trial_report_summary"),
            "trial_report_horses": trial_report_result.get("trial_report_horses", []),
            "trial_report_result": trial_report_result,
            "prediction_snapshot": review_record_result.get("prediction_snapshot"),
            "prediction_time": review_record_result.get("prediction_time"),
            "prediction_id": review_record_result.get("prediction_id"),
            "review_record": review_record_result.get("review_record"),
            "review_status": review_record_result.get("review_status"),
            "review_ready": review_record_result.get("review_ready"),
            "race_result": result_import_result.get("race_result"),
            "horse_results": result_import_result.get("horse_results", []),
            "result_loaded": result_import_result.get("result_loaded"),
            "result_status": result_import_result.get("result_status"),
            "result_import_result": result_import_result,
            "review_result": review_result,
            "review_summary": review_result.get("review_summary"),
            "review_score": review_result.get("review_score"),
            "review_level": review_result.get("review_level"),
            "review_hits": review_result.get("review_hits", []),
            "review_misses": review_result.get("review_misses", []),
            "review_comment": review_result.get("review_comment"),
            "improvement_result": improvement_result,
            "improvement_summary": improvement_result.get("improvement_summary"),
            "improvement_suggestions": improvement_result.get("improvement_suggestions", []),
            "improvement_targets": improvement_result.get("improvement_targets", []),
            "improvement_priority": improvement_result.get("improvement_priority"),
            "improvement_comment": improvement_result.get("improvement_comment"),
            "learning_record": learning_result.get("learning_record"),
            "learning_history": learning_result.get("learning_history", []),
            "learning_id": learning_result.get("learning_id"),
            "learning_time": learning_result.get("learning_time"),
            "learning_status": learning_result.get("learning_status"),
            "learning_analysis_result": learning_analysis.get("learning_analysis_result"),
            "learning_summary": learning_analysis.get("learning_summary"),
            "learning_trends": learning_analysis.get("learning_trends", {}),
            "success_patterns": learning_analysis.get("success_patterns", []),
            "failure_patterns": learning_analysis.get("failure_patterns", []),
            "frequent_improvement_targets": learning_analysis.get("frequent_improvement_targets", []),
            "decision_trends": learning_analysis.get("decision_trends", {}),
            "confidence_trends": learning_analysis.get("confidence_trends", {}),
            "learning_comment": learning_analysis.get("learning_comment"),
            "race_output": race_output,
            "final_outputs": race_output.get("horses", []),
            "results": horse_results,
            "ranked_results": ranked_results,
            "top5": ranked_results[:5],
            "bottom3": list(reversed(ranked_results[-3:])),
        }

    def _read_race_defaults(self, entry_csv_path):
        """Read race-level columns from the first entry row when available."""

        defaults = {
            "racecourse": None,
            "surface": None,
            "distance": None,
            "track_condition": None,
            "track_bias": None,
            "inside_bias": None,
            "outside_bias": None,
            "front_bias": None,
            "closer_bias": None,
            "bias_comment": None,
            "bias_type": None,
            "pace": None,
        }
        if entry_csv_path is None:
            return defaults

        try:
            path = Path(entry_csv_path)
            with path.open("r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                first_row = next(reader, None)
        except (OSError, csv.Error, UnicodeDecodeError):
            return defaults

        if not isinstance(first_row, dict):
            return defaults

        for key in defaults:
            defaults[key] = first_row.get(key)
        return defaults

    def _build_raw_data(self, entry, race_defaults, history):
        """Build one TrialRunner raw_data dict from Entry and HorseHistory."""

        data = dict(race_defaults)
        data.update(
            {
                "horse_name": getattr(entry, "horse_name", None),
                "name": getattr(entry, "horse_name", None),
                "sire": getattr(entry, "sire", None),
                "sire_name": getattr(entry, "sire", None),
                "broodmare_sire": getattr(entry, "broodmare_sire", None),
                "broodmare_sire_name": getattr(entry, "broodmare_sire", None),
                "body_weight": getattr(entry, "body_weight", None),
                "body_weight_diff": getattr(entry, "body_weight_diff", None),
                "horse_number": getattr(entry, "horse_number", None),
                "frame_number": getattr(entry, "frame_number", None),
                "history_runs": self._history_runs(history),
            }
        )
        return data

    def _merge_past_performance(self, trial_result, past_result):
        """Merge PastPerformanceEvaluator output into a TrialRunner result."""

        combined = dict(trial_result if isinstance(trial_result, dict) else {})
        past_summary = past_result.get("summary") if isinstance(past_result, dict) else {}
        if not isinstance(past_summary, dict):
            past_summary = {}

        past_score = self._safe_number(past_summary.get("total_score"))
        combined["total_score"] = self._safe_number(combined.get("total_score")) + past_score

        modifier_summary = combined.get("modifier_summary")
        if not isinstance(modifier_summary, dict):
            modifier_summary = {}
        self._merge_modifiers(modifier_summary, past_summary.get("modifiers"))
        combined["modifier_summary"] = modifier_summary

        sections = combined.get("sections")
        if not isinstance(sections, dict):
            sections = {}
        explains = past_summary.get("explains")
        past_explains = []
        if isinstance(explains, list):
            for item in explains:
                if isinstance(item, dict) and item.get("explain"):
                    past_explains.append(str(item.get("explain")))
        sections["past_performance"] = past_explains
        combined["sections"] = sections

        if past_explains:
            past_text = " ".join(past_explains)
            base_summary = str(combined.get("summary_text") or "")
            combined["summary_text"] = f"{base_summary}\n\n過去走面では、{past_text}"

        matched_results = list(combined.get("matched_results") or [])
        unmatched_results = list(combined.get("unmatched_results") or [])
        if past_result.get("matched"):
            matched_results.append(past_result)
        else:
            unmatched_results.append(past_result)
        combined["matched_results"] = matched_results
        combined["unmatched_results"] = unmatched_results

        warnings = list(combined.get("warnings") or [])
        for warning in past_result.get("warnings", []):
            if warning and warning not in warnings:
                warnings.append(warning)
        combined["warnings"] = warnings
        return combined

    def _merge_track_condition_suitability(self, trial_result, condition_result):
        """Merge TrackConditionSuitabilityEvaluator output into a trial result."""

        combined = dict(trial_result if isinstance(trial_result, dict) else {})
        condition_summary = (
            condition_result.get("summary") if isinstance(condition_result, dict) else {}
        )
        if not isinstance(condition_summary, dict):
            condition_summary = {}

        condition_score = self._safe_number(condition_summary.get("total_score"))
        combined["total_score"] = self._safe_number(combined.get("total_score")) + condition_score

        modifier_summary = combined.get("modifier_summary")
        if not isinstance(modifier_summary, dict):
            modifier_summary = {}
        self._merge_modifiers(modifier_summary, condition_summary.get("modifiers"))
        combined["modifier_summary"] = modifier_summary

        sections = combined.get("sections")
        if not isinstance(sections, dict):
            sections = {}
        explains = condition_summary.get("explains")
        condition_explains = []
        if isinstance(explains, list):
            for item in explains:
                if isinstance(item, dict) and item.get("explain"):
                    condition_explains.append(str(item.get("explain")))
        sections["track_condition_suitability"] = condition_explains
        combined["sections"] = sections

        if condition_explains:
            condition_text = " ".join(condition_explains)
            base_summary = str(combined.get("summary_text") or "")
            combined["summary_text"] = f"{base_summary}\n\n馬場適性では、{condition_text}"

        matched_results = list(combined.get("matched_results") or [])
        unmatched_results = list(combined.get("unmatched_results") or [])
        if condition_result.get("matched"):
            matched_results.append(condition_result)
        else:
            unmatched_results.append(condition_result)
        combined["matched_results"] = matched_results
        combined["unmatched_results"] = unmatched_results

        warnings = list(combined.get("warnings") or [])
        for warning in condition_result.get("warnings", []):
            if warning and warning not in warnings:
                warnings.append(warning)
        combined["warnings"] = warnings
        return combined

    def _merge_distance(self, trial_result, distance_result):
        """Merge DistanceSuitabilityEvaluator output into a trial result."""

        combined = dict(trial_result if isinstance(trial_result, dict) else {})
        distance_summary = distance_result.get("summary") if isinstance(distance_result, dict) else {}
        if not isinstance(distance_summary, dict):
            distance_summary = {}

        distance_score = self._safe_number(distance_summary.get("total_score"))
        combined["total_score"] = self._safe_number(combined.get("total_score")) + distance_score

        modifier_summary = combined.get("modifier_summary")
        if not isinstance(modifier_summary, dict):
            modifier_summary = {}
        self._merge_modifiers(modifier_summary, distance_summary.get("modifiers"))
        combined["modifier_summary"] = modifier_summary

        sections = combined.get("sections")
        if not isinstance(sections, dict):
            sections = {}
        explains = distance_summary.get("explains")
        distance_explains = []
        if isinstance(explains, list):
            for item in explains:
                if isinstance(item, dict) and item.get("explain"):
                    distance_explains.append(str(item.get("explain")))
        sections["distance"] = distance_explains
        combined["sections"] = sections

        if distance_explains:
            distance_text = " ".join(distance_explains)
            base_summary = str(combined.get("summary_text") or "")
            combined["summary_text"] = f"{base_summary}\n\n距離適性では、{distance_text}"

        matched_results = list(combined.get("matched_results") or [])
        unmatched_results = list(combined.get("unmatched_results") or [])
        if distance_result.get("matched"):
            matched_results.append(distance_result)
        else:
            unmatched_results.append(distance_result)
        combined["matched_results"] = matched_results
        combined["unmatched_results"] = unmatched_results

        warnings = list(combined.get("warnings") or [])
        for warning in distance_result.get("warnings", []):
            if warning and warning not in warnings:
                warnings.append(warning)
        combined["warnings"] = warnings
        return combined

    def _merge_pace_style(self, trial_result, pace_style_result):
        """Merge PaceStyleEvaluator output into a trial result."""

        combined = dict(trial_result if isinstance(trial_result, dict) else {})
        pace_summary = pace_style_result.get("summary") if isinstance(pace_style_result, dict) else {}
        if not isinstance(pace_summary, dict):
            pace_summary = {}

        pace_score = self._safe_number(pace_summary.get("total_score"))
        combined["total_score"] = self._safe_number(combined.get("total_score")) + pace_score

        modifier_summary = combined.get("modifier_summary")
        if not isinstance(modifier_summary, dict):
            modifier_summary = {}
        self._merge_modifiers(modifier_summary, pace_summary.get("modifiers"))
        combined["modifier_summary"] = modifier_summary

        sections = combined.get("sections")
        if not isinstance(sections, dict):
            sections = {}
        explains = pace_summary.get("explains")
        pace_explains = []
        if isinstance(explains, list):
            for item in explains:
                if isinstance(item, dict) and item.get("explain"):
                    pace_explains.append(str(item.get("explain")))
        sections["pace_style"] = pace_explains
        combined["sections"] = sections

        if pace_explains:
            pace_text = " ".join(pace_explains)
            base_summary = str(combined.get("summary_text") or "")
            combined["summary_text"] = f"{base_summary}\n\n脚質傾向では、{pace_text}"

        matched_results = list(combined.get("matched_results") or [])
        unmatched_results = list(combined.get("unmatched_results") or [])
        if pace_style_result.get("matched"):
            matched_results.append(pace_style_result)
        else:
            unmatched_results.append(pace_style_result)
        combined["matched_results"] = matched_results
        combined["unmatched_results"] = unmatched_results

        warnings = list(combined.get("warnings") or [])
        for warning in pace_style_result.get("warnings", []):
            if warning and warning not in warnings:
                warnings.append(warning)
        combined["warnings"] = warnings
        return combined

    def _merge_modifiers(self, destination, source):
        if not isinstance(source, dict):
            return
        for key, value in source.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            destination[str(key)] = destination.get(str(key), 0) + value

    def _apply_race_shape_and_final_scores(self, horse_results, race_defaults=None):
        """Predict race pace, add shape_score, and calculate final_score."""

        race_context = race_defaults if isinstance(race_defaults, dict) else {}
        pace_result = self.race_pace_predictor.predict(horse_results)
        pace_prediction = pace_result.get("pace_prediction", "average")
        structure_input = dict(race_context)
        structure_input.update(pace_result)
        structure_input["pace_prediction"] = pace_prediction
        structure_input["horses"] = horse_results
        structure_result = self.race_structure_engine.analyze(structure_input)
        pace_result["race_structure_result"] = structure_result
        shape_results = self.race_shape_evaluator.evaluate_many(
            pace_prediction,
            horse_results,
        )
        course_shape_results = self.course_shape_evaluator.evaluate_many(
            horse_results,
            pace_result,
            race_context,
        )
        track_bias_results = self.track_bias_evaluator.evaluate_many(
            horse_results,
            race_context,
        )
        lap_results = self.lap_suitability_evaluator.evaluate_many(
            horse_results,
            pace_result,
            race_context,
        )

        for index, item in enumerate(horse_results):
            shape_result = shape_results[index] if index < len(shape_results) else {}
            course_shape_result = (
                course_shape_results[index] if index < len(course_shape_results) else {}
            )
            track_bias_result = (
                track_bias_results[index] if index < len(track_bias_results) else {}
            )
            lap_result = lap_results[index] if index < len(lap_results) else {}
            item["race_pace_prediction"] = pace_prediction
            item["race_structure"] = structure_result.get("race_structure", {})
            item["structure_comment"] = structure_result.get("structure_comment", "")
            item["key_factors"] = structure_result.get("key_factors", [])
            item["structure_flags"] = structure_result.get("structure_flags", {})
            item["recommended_weights_hint"] = structure_result.get("recommended_weights_hint", {})
            item["shape_score"] = shape_result.get("shape_score", 0)
            item["shape_comment"] = shape_result.get("shape_comment", "")
            item["shape_result"] = shape_result
            item["course_shape_score"] = course_shape_result.get("course_shape_score", 0)
            item["course_shape_comment"] = course_shape_result.get("course_shape_comment", "")
            item["course_shape_result"] = course_shape_result
            item["track_bias_score"] = track_bias_result.get("track_bias_score", 0)
            item["track_bias_comment"] = track_bias_result.get("track_bias_comment", "")
            item["track_bias_result"] = track_bias_result
            item["lap_style"] = lap_result.get("lap_style", "unknown")
            item["lap_score"] = lap_result.get("lap_score", 0)
            item["lap_comment"] = lap_result.get("lap_comment", "")
            item["lap_result"] = lap_result

            consistency_result = self.consistency_engine.evaluate(
                item,
                structure_result.get("race_structure", {}),
            )
            item["consistency_result"] = consistency_result
            item["consistency_score"] = consistency_result.get("consistency_score", 0)
            item["consistency_level"] = consistency_result.get("consistency_level", "")
            item["strong_matches"] = consistency_result.get("strong_matches", [])
            item["weak_matches"] = consistency_result.get("weak_matches", [])
            item["conflict_factors"] = consistency_result.get("conflict_factors", [])
            item["consistency_comment"] = consistency_result.get("consistency_comment", "")
            item["bonus_hint"] = consistency_result.get("bonus_hint", "none")
            item["penalty_hint"] = consistency_result.get("penalty_hint", "none")

            weight_result = self.score_weight_evaluator.evaluate(item)
            item["score_weights"] = weight_result.get("score_weights", {})
            item["weight_source"] = weight_result.get("weight_source", "default")
            item["weight_comment"] = weight_result.get("weight_comment", "")
            item["weighted_score"] = weight_result.get("weighted_score", 0)
            item["integrated_score"] = weight_result.get("integrated_score", item.get("weighted_score", 0))
            item["weighted_score_breakdown"] = weight_result.get("weighted_score_breakdown", {})
            item["consistency_weight_adjustments"] = weight_result.get("consistency_weight_adjustments", {})

            final_result = self.final_score_integrator.integrate(
                {
                    "horse_name": item.get("horse_name"),
                    "bloodline_score": item.get("bloodline_score"),
                    "past_performance_score": item.get("past_performance_score"),
                    "pace_style_score": item.get("pace_style_score"),
                    "distance_score": item.get("distance_score"),
                    "track_condition_score": item.get("track_condition_score"),
                    "shape_score": item.get("shape_score"),
                    "course_shape_score": item.get("course_shape_score"),
                    "track_bias_score": item.get("track_bias_score"),
                    "lap_score": item.get("lap_score"),
                }
            )
            item["final_score"] = final_result.get("final_score", 0)
            item["score_breakdown"] = final_result.get("score_breakdown", {})

            explain_result = self.explain_engine.build(item)
            item["explanation"] = explain_result.get("explanation", "")
            item["explain_summary"] = explain_result.get("summary", "")
            item["consistency_explanation"] = explain_result.get("consistency_explanation", "")
            item["consistency_summary"] = explain_result.get("consistency_summary", "")
            item["strengths"] = explain_result.get("strengths", [])
            item["weaknesses"] = explain_result.get("weaknesses", [])
            item["risk_factors"] = explain_result.get("risk_factors", [])
            item["confidence_reason"] = explain_result.get("confidence_reason", "")
            item["explain_result"] = explain_result

            impact_result = self.impact_evaluator.evaluate(
                horse_name=item.get("horse_name"),
                pace_style=item.get("pace_style"),
                shape_score=item.get("shape_score"),
                shape_comment=item.get("shape_comment"),
                final_score=item.get("integrated_score", item.get("final_score")),
            )
            item["impact_score"] = impact_result.get("impact_score", 0)
            item["adjusted_score"] = impact_result.get("adjusted_score", item.get("final_score", 0))
            item["impact_comment"] = impact_result.get("comment", "")
            item["impact_result"] = impact_result

        decision_results = self.decision_engine.decide_many(horse_results)
        for index, item in enumerate(horse_results):
            decision_result = decision_results[index] if index < len(decision_results) else {}
            item["decision"] = decision_result.get("decision", "")
            item["decision_score"] = decision_result.get("decision_score", 0)
            item["decision_level"] = decision_result.get("decision_level", "")
            item["decision_reason"] = decision_result.get("decision_reason", "")
            item["decision_factors"] = decision_result.get("decision_factors", [])
            item["decision_risks"] = decision_result.get("decision_risks", [])
            item["decision_result"] = decision_result

        return pace_result

    def _history_runs(self, history):
        """Return recent HistoryRun objects as dictionaries."""

        if history is None or not hasattr(history, "runs"):
            return []

        runs = []
        for run in history.runs[: self.HISTORY_LIMIT]:
            try:
                runs.append(asdict(run))
            except TypeError:
                runs.append(dict(run) if isinstance(run, dict) else {})
        return runs

    def _build_warnings(self, entry, history, trial_result):
        """Collect non-fatal issues for display."""

        warnings = []
        horse_name = getattr(entry, "horse_name", None) or "unknown"

        if history is None:
            warnings.append(f"history not found: {horse_name}")
        elif not getattr(history, "runs", []):
            warnings.append(f"history is empty: {horse_name}")

        if not getattr(entry, "sire", None):
            warnings.append(f"sire missing: {horse_name}")
        if not getattr(entry, "broodmare_sire", None):
            warnings.append(f"broodmare sire missing: {horse_name}")

        for warning in trial_result.get("warnings", []):
            if warning not in warnings:
                warnings.append(warning)
        return warnings

    def _score_by_source_type(self, trial_result, source_type):
        """Extract a score for one source_type from TrialRunner results."""

        result = trial_result if isinstance(trial_result, dict) else {}
        total = 0
        for matched in result.get("matched_results", []):
            if not isinstance(matched, dict):
                continue
            summary = matched.get("summary")
            if not isinstance(summary, dict):
                continue
            source_summary = summary.get("source_type_summary")
            if not isinstance(source_summary, dict):
                continue
            source_data = source_summary.get(source_type)
            if isinstance(source_data, dict):
                total += self._safe_number(source_data.get("total_score"))
        return total

    def _safe_number(self, value):
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
        return 0

    def _horse_number(self, item):
        try:
            return int(item.get("horse_number") or 0)
        except (TypeError, ValueError):
            return 0


def format_target_trial_report(result):
    """Create a readable plain-text report for trial checks."""

    data = result if isinstance(result, dict) else {}
    lines = []
    lines.append("=== All Horses ===")
    for item in data.get("results", []):
        warnings = item.get("warnings") or []
        warning_text = "; ".join(warnings) if warnings else "-"
        lines.append(
            f"{item.get('horse_name')}: final_score={item.get('final_score')}, "
            f"weighted_score={item.get('weighted_score')}, "
            f"integrated_score={item.get('integrated_score')}, "
            f"impact_score={item.get('impact_score')}, "
            f"adjusted_score={item.get('adjusted_score')}, "
            f"bloodline_score={item.get('bloodline_score')}, "
            f"past_performance_score={item.get('past_performance_score')}, "
            f"pace_style_score={item.get('pace_style_score')}, "
            f"distance_score={item.get('distance_score')}, "
            f"track_condition_score={item.get('track_condition_score')}, "
            f"shape_score={item.get('shape_score')}, "
            f"course_shape_score={item.get('course_shape_score')}, "
            f"track_bias_score={item.get('track_bias_score')}, "
            f"lap_style={item.get('lap_style')}, "
            f"lap_score={item.get('lap_score')}, "
            f"weight_comment={item.get('weight_comment')}, "
            f"shape_comment={item.get('shape_comment')}, "
            f"course_shape_comment={item.get('course_shape_comment')}, "
            f"track_bias_comment={item.get('track_bias_comment')}, "
            f"lap_comment={item.get('lap_comment')}, "
            f"impact_comment={item.get('impact_comment')}, "
            f"distance_fit={item.get('distance_fit_label')}, "
            f"track_condition_fit={item.get('track_condition_fit_label')}, "
            f"pace_style={item.get('pace_style_label')}, "
            f"history_count={item.get('history_count')}, warnings={warning_text}"
        )

    lines.append("")
    lines.append("=== Top 5 ===")
    for item in data.get("top5", []):
        lines.append(
            f"{item.get('horse_name')}: final_score={item.get('final_score')}, "
            f"weighted_score={item.get('weighted_score')}, "
            f"integrated_score={item.get('integrated_score')}, "
            f"impact_score={item.get('impact_score')}, "
            f"adjusted_score={item.get('adjusted_score')}, "
            f"bloodline_score={item.get('bloodline_score')}, "
            f"past_performance_score={item.get('past_performance_score')}, "
            f"pace_style_score={item.get('pace_style_score')}, "
            f"distance_score={item.get('distance_score')}, "
            f"track_condition_score={item.get('track_condition_score')}, "
            f"shape_score={item.get('shape_score')}, "
            f"course_shape_score={item.get('course_shape_score')}, "
            f"track_bias_score={item.get('track_bias_score')}, "
            f"lap_style={item.get('lap_style')}, "
            f"lap_score={item.get('lap_score')}, "
            f"weight_comment={item.get('weight_comment')}, "
            f"shape_comment={item.get('shape_comment')}, "
            f"course_shape_comment={item.get('course_shape_comment')}, "
            f"track_bias_comment={item.get('track_bias_comment')}, "
            f"lap_comment={item.get('lap_comment')}, "
            f"impact_comment={item.get('impact_comment')}, "
            f"distance_fit={item.get('distance_fit_label')}, "
            f"track_condition_fit={item.get('track_condition_fit_label')}, "
            f"pace_style={item.get('pace_style_label')}"
        )
        lines.append(str(item.get("summary") or ""))

    lines.append("")
    lines.append("=== Bottom 3 ===")
    for item in data.get("bottom3", []):
        warnings = item.get("warnings") or []
        lines.append(
            f"{item.get('horse_name')}: final_score={item.get('final_score')}, "
            f"weighted_score={item.get('weighted_score')}, "
            f"integrated_score={item.get('integrated_score')}, "
            f"impact_score={item.get('impact_score')}, "
            f"adjusted_score={item.get('adjusted_score')}, "
            f"bloodline_score={item.get('bloodline_score')}, "
            f"past_performance_score={item.get('past_performance_score')}, "
            f"pace_style_score={item.get('pace_style_score')}, "
            f"distance_score={item.get('distance_score')}, "
            f"track_condition_score={item.get('track_condition_score')}, "
            f"shape_score={item.get('shape_score')}, "
            f"course_shape_score={item.get('course_shape_score')}, "
            f"track_bias_score={item.get('track_bias_score')}, "
            f"lap_style={item.get('lap_style')}, "
            f"lap_score={item.get('lap_score')}, "
            f"weight_comment={item.get('weight_comment')}, "
            f"shape_comment={item.get('shape_comment')}, "
            f"course_shape_comment={item.get('course_shape_comment')}, "
            f"track_bias_comment={item.get('track_bias_comment')}, "
            f"lap_comment={item.get('lap_comment')}, "
            f"impact_comment={item.get('impact_comment')}, "
            f"distance_fit={item.get('distance_fit_label')}, "
            f"track_condition_fit={item.get('track_condition_fit_label')}, "
            f"pace_style={item.get('pace_style_label')}"
        )
        lines.append(str(item.get("summary") or ""))
        lines.append(f"warnings={'; '.join(warnings) if warnings else '-'}")

    return "\n".join(lines)


if __name__ == "__main__":
    adapter = TargetTrialAdapter()
    trial_result = adapter.run(
        "data/trial/kokura4r_trial.csv",
        "data/raw/test3.csv",
    )
    print(format_target_trial_report(trial_result))
