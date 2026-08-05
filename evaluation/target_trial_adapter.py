"""Trial adapter for TARGET entry and history CSV files.

This module is only a trial connector.  It reads TARGET-style entry data and
TARGET S-style history data, converts them into the existing TrialRunner input
shape, and runs the current Evaluation Engine without touching the production
Analyzer or main.py.
"""

import csv
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine.bloodline_root_cause_engine import BloodlineRootCauseEngine
from engine.buy_v1_rc1_engine import BUYV1RC1Engine
from engine.consistency_engine import ConsistencyEngine
from engine.confidence_engine import ConfidenceEngine
from engine.decision_attribution_engine import DecisionAttributionEngine
from engine.decision_engine import DecisionEngine
from engine.explain_engine import ExplainEngine
from engine.final_output_formatter import FinalOutputFormatter
from engine.improvement_advisor import ImprovementAdvisor
from engine.learning_candidate_engine import LearningCandidateEngine
from engine.learning_database import LearningDatabase
from engine.learning_engine import LearningEngine
from engine.meeting_bias_engine import MeetingBiasEngine
from engine.meeting_stage_detector import MeetingStageDetector
from engine.race_decision_engine import RaceDecisionEngine
from engine.race_decision_buy_synchronizer import RaceDecisionBuySynchronizer
from engine.race_structure_engine import RaceStructureEngine
from engine.race_summary_engine import RaceSummaryEngine
from engine.review_recorder import ReviewRecorder
from engine.review_engine import ReviewEngine
from engine.result_importer import ResultImporter
from engine.self_check_engine import SelfCheckEngine
from engine.shadow_buy_decision_engine import ShadowBUYDecisionEngine
from engine.trial_report_exporter import TrialReportExporter
from evaluation.distance_suitability_evaluator import DistanceSuitabilityEvaluator
from evaluation.course_name_normalizer import knowledge_course_key, normalize_course_name
from evaluation.final_score_integrator import FinalScoreIntegrator
from evaluation.impact_evaluator import ImpactEvaluator
from evaluation.manual_track_bias_builder import ManualTrackBiasBuilder
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
from learning.learning_writer import LearningWriter


class TargetTrialAdapter:
    """Connect TARGET importer output to the trial Evaluation Engine."""

    HISTORY_LIMIT = 5

    def __init__(
        self,
        enable_past_performance_quality_guard=False,
        enable_multi_evaluator_consensus_guard=False,
        learning_phase2_enabled=False,
        learning_phase2_storage_path=None,
        shadow_buy_spec_v1_enabled=False,
        buy_v1_rc1_enabled=None,
        enable_learning_candidate_engine=True,
    ):
        self.entry_importer = TargetEntryImporter()
        self.bloodline_root_cause_engine = BloodlineRootCauseEngine()
        self.consistency_engine = ConsistencyEngine()
        self.confidence_engine = ConfidenceEngine()
        self.decision_attribution_engine = DecisionAttributionEngine()
        self.decision_engine = DecisionEngine(
            enable_past_performance_quality_guard=enable_past_performance_quality_guard,
            enable_multi_evaluator_consensus_guard=enable_multi_evaluator_consensus_guard,
        )
        self.explain_engine = ExplainEngine()
        self.final_output_formatter = FinalOutputFormatter()
        self.history_importer = TargetHistoryImporter()
        self.improvement_advisor = ImprovementAdvisor()
        self.learning_candidate_engine = LearningCandidateEngine()
        self.enable_learning_candidate_engine = bool(enable_learning_candidate_engine)
        self.learning_database = LearningDatabase()
        self.learning_phase2_writer = LearningWriter(
            enabled=learning_phase2_enabled,
            storage_path=learning_phase2_storage_path,
        )
        self.learning_engine = LearningEngine()
        self.meeting_bias_engine = MeetingBiasEngine()
        self.meeting_stage_detector = MeetingStageDetector()
        self.course_shape_evaluator = CourseShapeEvaluator()
        self.distance_suitability_evaluator = DistanceSuitabilityEvaluator()
        self.final_score_integrator = FinalScoreIntegrator()
        self.impact_evaluator = ImpactEvaluator()
        self.lap_suitability_evaluator = LapSuitabilityEvaluator()
        self.manual_track_bias_builder = ManualTrackBiasBuilder()
        self.past_performance_evaluator = PastPerformanceEvaluator()
        self.pace_style_evaluator = PaceStyleEvaluator()
        self.race_decision_engine = RaceDecisionEngine()
        self.race_decision_buy_synchronizer = RaceDecisionBuySynchronizer()
        self.race_pace_predictor = RacePacePredictor()
        self.race_structure_engine = RaceStructureEngine()
        self.race_summary_engine = RaceSummaryEngine()
        self.review_recorder = ReviewRecorder()
        self.review_engine = ReviewEngine()
        self.result_importer = ResultImporter()
        self.self_check_engine = SelfCheckEngine()
        self.shadow_buy_decision_engine = ShadowBUYDecisionEngine(
            enabled=shadow_buy_spec_v1_enabled
        )
        self.buy_v1_rc1_engine = BUYV1RC1Engine(enabled=buy_v1_rc1_enabled)
        self.trial_report_exporter = TrialReportExporter()
        self.race_shape_evaluator = RaceShapeEvaluator()
        self.score_weight_evaluator = ScoreWeightEvaluator()
        self.track_bias_evaluator = TrackBiasEvaluator()
        self.track_condition_suitability_evaluator = TrackConditionSuitabilityEvaluator()
        self.runner = TrialRunner()

    def run(
        self,
        entry_csv_path,
        history_csv_path=None,
        manual_track_bias=None,
        horse_data_csv_path=None,
        _skip_track_bias_baseline=False,
    ):
        """Load entry/history CSV files and evaluate all entries safely."""

        history_path = history_csv_path if history_csv_path is not None else horse_data_csv_path
        track_bias_baseline = None
        if (
            self._manual_track_bias_active(manual_track_bias)
            and not _skip_track_bias_baseline
        ):
            track_bias_baseline = self.run(
                entry_csv_path,
                history_path,
                manual_track_bias="neutral",
                _skip_track_bias_baseline=True,
            )
        entries = self.entry_importer.load(entry_csv_path)
        histories = self.history_importer.load(history_path)
        pairs = attach_histories_to_entries(entries, histories)
        race_defaults = self._read_race_defaults(entry_csv_path)
        race_defaults = self._enrich_race_defaults(race_defaults, entries, histories)
        race_defaults = self._apply_manual_track_bias(race_defaults, manual_track_bias)

        horse_results = []
        for entry, history in pairs:
            self._fill_entry_from_history(entry, history)
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
                    "sire": getattr(entry, "sire", None),
                    "dam": getattr(entry, "dam", None),
                    "broodmare_sire": getattr(entry, "broodmare_sire", None),
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
                    "track_bias_reasons": [],
                    "track_bias_matched": False,
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
            track_bias_baseline,
        )
        race_structure_result = race_pace_result.get("race_structure_result", {})
        meeting_bias_result = race_pace_result.get("meeting_bias_result", {})
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
                "manual_track_bias_active": self._manual_track_bias_active(manual_track_bias),
                "baseline_race_decision_result": self._baseline_race_decision_result(track_bias_baseline),
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
            item["race_decision"] = race_decision_result.get("race_decision")
        buy_v1_rc1_result = self.buy_v1_rc1_engine.evaluate(
            race_output={
                "race_id": self._race_id_from_defaults(race_defaults),
                "race_decision": race_decision_result.get("race_decision"),
                "race_confidence": race_decision_result.get("race_confidence"),
            },
            horses=ranked_results,
        )
        self.buy_v1_rc1_engine.apply_to_horses(ranked_results, buy_v1_rc1_result)
        race_decision_sync_result = self.race_decision_buy_synchronizer.synchronize(
            race_decision_result,
            ranked_results,
            buy_v1_rc1_result,
        )
        race_decision_result = race_decision_sync_result.get(
            "race_decision_result",
            race_decision_result,
        )
        for item in horse_results:
            item["race_decision"] = race_decision_result.get("race_decision")
            item["race_decision_original"] = race_decision_result.get("race_decision_original")
            item["race_decision_final"] = race_decision_result.get("race_decision_final")
            item["race_decision_sync_applied"] = race_decision_result.get("race_decision_sync_applied")
            item["race_decision_sync_reason"] = race_decision_result.get("race_decision_sync_reason")
        decision_attribution_result = self.decision_attribution_engine.evaluate_many(
            horse_results,
            {
                "race_decision": race_decision_result.get("race_decision"),
                "race_decision_score": race_decision_result.get("race_decision_score"),
                "race_confidence": race_decision_result.get("race_confidence"),
            },
        )
        bloodline_root_cause_result = self.bloodline_root_cause_engine.analyze_many(
            horse_results,
        )
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
                "meeting_bias_result": meeting_bias_result,
                "race_decision_result": race_decision_result,
                "race_summary_result": race_summary_result,
                "self_check_result": self_check_result,
            },
        )
        race_output["race_id"] = self._race_id_from_defaults(race_defaults)
        race_output["meeting_bias_result"] = meeting_bias_result
        race_output["meeting_bias"] = meeting_bias_result.get("meeting_bias", {})
        race_output["meeting_bias_comment"] = meeting_bias_result.get("meeting_bias_comment", "")
        race_output["meeting_bias_factors"] = meeting_bias_result.get("meeting_bias_factors", [])
        race_output["meeting_bias_warnings"] = meeting_bias_result.get("meeting_bias_warnings", [])
        race_output["meeting_bias_ready"] = meeting_bias_result.get("meeting_bias_ready", False)
        race_output["decision_attribution_result"] = decision_attribution_result
        race_output["decision_attribution_summary"] = decision_attribution_result.get("summary", {})
        race_output["decision_root_cause_summary"] = (
            decision_attribution_result.get("summary", {}).get("primary_root_causes", {})
        )
        race_output["bloodline_root_cause_result"] = bloodline_root_cause_result
        race_output["bloodline_root_cause_summary"] = bloodline_root_cause_result.get("summary", {})
        trial_report_result = self.trial_report_exporter.export(
            race_output,
            ranked_results,
        )
        race_output["trial_report"] = trial_report_result.get("trial_report")
        race_output["trial_report_summary"] = trial_report_result.get("trial_report_summary")
        race_output["trial_report_horses"] = trial_report_result.get("trial_report_horses", [])
        race_output["trial_report_result"] = trial_report_result
        review_record_result = self.review_recorder.record(
            race_output,
            ranked_results,
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
        if self.enable_learning_candidate_engine:
            learning_candidate_result = self.learning_candidate_engine.generate(
                race_output=race_output,
                ranked_results=ranked_results,
                review_result=review_result,
                improvement_result=improvement_result,
            )
        else:
            learning_candidate_result = {
                "status": "disabled",
                "candidates": [],
                "summary": {},
                "warnings": ["learning_candidate_engine_disabled"],
            }
        race_output["learning_candidate_result"] = learning_candidate_result
        race_output["improvement_candidates"] = learning_candidate_result.get("candidates", [])
        race_output["improvement_candidate_summary"] = learning_candidate_result.get("summary", {})
        shadow_buy_result = self.shadow_buy_decision_engine.evaluate(
            race_output=race_output,
            horses=ranked_results,
        )
        race_output["shadow_buy_spec_v1_result"] = shadow_buy_result
        race_output["shadow_buy_spec_v1_enabled"] = shadow_buy_result.get("enabled", False)
        race_output["shadow_race_decision"] = shadow_buy_result.get("shadow_race_decision", "")
        race_output["shadow_buy_summary"] = shadow_buy_result.get("summary", {})
        race_output["buy_v1_rc1_result"] = buy_v1_rc1_result
        race_output["buy_v1_rc1_enabled"] = buy_v1_rc1_result.get("enabled", False)
        race_output["buy_v1_rc1_summary"] = buy_v1_rc1_result.get("summary", {})
        race_output["buy_v1_rc1_race_state"] = buy_v1_rc1_result.get("race_state", "")
        race_output["buy_v1_rc1_race_decision"] = buy_v1_rc1_result.get("race_decision", "")
        race_output["race_decision_sync_result"] = race_decision_sync_result
        race_output["race_decision_original"] = race_decision_result.get("race_decision_original")
        race_output["race_decision_final"] = race_decision_result.get("race_decision_final")
        race_output["race_decision_sync_applied"] = race_decision_result.get("race_decision_sync_applied")
        race_output["race_decision_sync_reason"] = race_decision_result.get("race_decision_sync_reason")
        learning_phase2_result = self.learning_phase2_writer.write_analysis(
            race_output=race_output,
            horses=ranked_results,
        )
        race_output["learning_phase2_result"] = learning_phase2_result
        race_output["learning_phase2_enabled"] = learning_phase2_result.get("enabled", False)
        race_output["learning_phase2_saved"] = learning_phase2_result.get("saved", False)
        race_output["learning_phase2_record_count"] = learning_phase2_result.get("record_count", 0)
        race_output["learning_phase2_storage_path"] = learning_phase2_result.get("storage_path")

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
            "meeting_bias_result": meeting_bias_result,
            "meeting_bias": meeting_bias_result.get("meeting_bias", {}),
            "meeting_bias_comment": meeting_bias_result.get("meeting_bias_comment", ""),
            "meeting_bias_factors": meeting_bias_result.get("meeting_bias_factors", []),
            "meeting_bias_warnings": meeting_bias_result.get("meeting_bias_warnings", []),
            "meeting_bias_ready": meeting_bias_result.get("meeting_bias_ready", False),
            "decision_attribution_result": decision_attribution_result,
            "decision_attribution_summary": decision_attribution_result.get("summary", {}),
            "decision_root_cause_summary": (
                decision_attribution_result.get("summary", {}).get("primary_root_causes", {})
            ),
            "bloodline_root_cause_result": bloodline_root_cause_result,
            "bloodline_root_cause_summary": bloodline_root_cause_result.get("summary", {}),
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
            "learning_candidate_result": learning_candidate_result,
            "improvement_candidates": learning_candidate_result.get("candidates", []),
            "improvement_candidate_summary": learning_candidate_result.get("summary", {}),
            "shadow_buy_spec_v1_result": shadow_buy_result,
            "shadow_buy_spec_v1_enabled": shadow_buy_result.get("enabled", False),
            "shadow_race_decision": shadow_buy_result.get("shadow_race_decision", ""),
            "shadow_buy_summary": shadow_buy_result.get("summary", {}),
            "buy_v1_rc1_result": buy_v1_rc1_result,
            "buy_v1_rc1_enabled": buy_v1_rc1_result.get("enabled", False),
            "buy_v1_rc1_summary": buy_v1_rc1_result.get("summary", {}),
            "buy_v1_rc1_race_state": buy_v1_rc1_result.get("race_state", ""),
            "buy_v1_rc1_race_decision": buy_v1_rc1_result.get("race_decision", ""),
            "race_decision_sync_result": race_decision_sync_result,
            "race_decision_original": race_decision_result.get("race_decision_original"),
            "race_decision_final": race_decision_result.get("race_decision_final"),
            "race_decision_sync_applied": race_decision_result.get("race_decision_sync_applied"),
            "race_decision_sync_reason": race_decision_result.get("race_decision_sync_reason"),
            "learning_phase2_result": learning_phase2_result,
            "learning_phase2_enabled": learning_phase2_result.get("enabled", False),
            "learning_phase2_saved": learning_phase2_result.get("saved", False),
            "learning_phase2_record_count": learning_phase2_result.get("record_count", 0),
            "learning_phase2_storage_path": learning_phase2_result.get("storage_path"),
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
            "race_date": None,
            "race_number": None,
            "meeting_stage": None,
            "meeting_week": None,
            "meeting_day": None,
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

    def _enrich_race_defaults(self, defaults, entries, histories):
        """Fill missing race context from entry metadata and TARGET history rows."""

        enriched = dict(defaults if isinstance(defaults, dict) else {})
        for key in [
            "racecourse",
            "surface",
            "distance",
            "track_condition",
            "track_bias",
            "inside_bias",
            "outside_bias",
            "front_bias",
            "closer_bias",
            "bias_comment",
            "bias_type",
            "pace",
            "race_date",
            "race_number",
            "meeting_stage",
            "meeting_week",
            "meeting_day",
        ]:
            enriched.setdefault(key, None)

        if not enriched.get("racecourse"):
            for entry in entries or []:
                racecourse = getattr(entry, "racecourse", None)
                if racecourse:
                    enriched["racecourse"] = self._normalize_racecourse(racecourse)
                    break

        if not enriched.get("race_date"):
            for entry in entries or []:
                race_date = getattr(entry, "race_date", None)
                if race_date:
                    enriched["race_date"] = race_date
                    break

        if not enriched.get("race_number"):
            for entry in entries or []:
                race_number = getattr(entry, "race_number", None)
                if race_number:
                    enriched["race_number"] = race_number
                    break

        runs = self._all_history_runs(histories)
        if not enriched.get("surface"):
            enriched["surface"] = self._dominant_value(
                self._normalize_surface(run.get("surface")) for run in runs
            )

        if not enriched.get("distance"):
            enriched["distance"] = self._infer_target_distance(
                racecourse=enriched.get("racecourse"),
                surface=enriched.get("surface"),
                runs=runs,
            )

        if not enriched.get("track_condition"):
            enriched["track_condition"] = self._dominant_value(
                self._normalize_track_condition(run.get("track_condition")) for run in runs
            )

        enriched["meeting_stage"] = self.meeting_stage_detector.detect(enriched)
        return enriched

    def _apply_manual_track_bias(self, race_defaults, manual_track_bias=None):
        """Merge optional manual track-bias fields into race defaults."""

        defaults = dict(race_defaults if isinstance(race_defaults, dict) else {})
        manual_bias = self.manual_track_bias_builder.build(manual_track_bias)
        if not manual_bias:
            return defaults
        defaults.update(manual_bias)
        return defaults

    def _load_meeting_bias_knowledge(self, racecourse):
        """Load course-level MeetingBias knowledge for explain text only."""

        normalized = self._normalize_racecourse(racecourse)
        if not normalized:
            return {}
        path = Path("knowledge") / "meeting_bias" / f"{normalized}.json"
        try:
            with path.open("r", encoding="utf-8-sig") as file:
                data = json.load(file)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _fill_entry_from_history(self, entry, history):
        """Copy horse-level CSV fields from the latest history row when entry lacks them."""

        if entry is None or history is None:
            return
        runs = getattr(history, "runs", []) or []
        if not runs:
            return
        latest = runs[0]

        for field_name in ["sire", "dam", "broodmare_sire"]:
            if getattr(entry, field_name, None):
                continue
            value = getattr(latest, field_name, None)
            if value:
                setattr(entry, field_name, value)

    def _all_history_runs(self, histories):
        runs = []
        if isinstance(histories, dict):
            iterable = histories.values()
        else:
            iterable = histories or []
        for history in iterable:
            for run in getattr(history, "runs", []) or []:
                try:
                    runs.append(asdict(run))
                except TypeError:
                    runs.append(dict(run) if isinstance(run, dict) else {})
        return runs

    def _dominant_value(self, values):
        cleaned = [value for value in values if value]
        if not cleaned:
            return None
        return Counter(cleaned).most_common(1)[0][0]

    def _infer_target_distance(self, racecourse, surface, runs):
        distances = [
            self._safe_int(run.get("distance"))
            for run in runs
            if self._normalize_surface(run.get("surface")) == surface
        ]
        distances = [distance for distance in distances if distance is not None]
        if not distances:
            return None

        available_distances = self._course_profile_distances(racecourse, surface)
        if available_distances:
            for distance, _ in Counter(distances).most_common():
                if distance in available_distances:
                    return distance
            dominant = Counter(distances).most_common(1)[0][0]
            return min(available_distances, key=lambda candidate: abs(candidate - dominant))

        return Counter(distances).most_common(1)[0][0]

    def _course_profile_distances(self, racecourse, surface):
        if not racecourse or not surface:
            return []

        try:
            from evaluation.course_evaluator import CourseEvaluator
        except Exception:
            return []

        evaluator = CourseEvaluator()
        course_key = knowledge_course_key(racecourse)
        course_info = evaluator.COURSE_MODULES.get(str(course_key).lower())
        if course_info is None:
            return []

        profiles = evaluator._load_profiles(str(course_key).lower())
        if not isinstance(profiles, dict):
            return []

        distances = []
        for key in profiles:
            if not isinstance(key, tuple) or len(key) != 3:
                continue
            key_course, key_surface, key_distance = key
            if (
                str(key_course).lower() == str(racecourse).lower()
                or str(key_course).lower() == str(course_key).lower()
                or key_course == self._racecourse_japanese(racecourse)
            ):
                if self._normalize_surface(key_surface) == surface:
                    distances.append(key_distance)
        return sorted({distance for distance in distances if isinstance(distance, int)})

    def _racecourse_japanese(self, racecourse):
        mapping = {
            "sapporo": "札幌",
            "hakodate": "函館",
            "fukushima": "福島",
            "niigata": "新潟",
            "tokyo": "東京",
            "nakayama": "中山",
            "chukyo": "中京",
            "chuukyou": "中京",
            "kyoto": "京都",
            "hanshin": "阪神",
            "kokura": "小倉",
        }
        return mapping.get(str(racecourse).lower(), racecourse)

    def _race_id_from_defaults(self, race_defaults):
        """Build race_id for downstream record keeping when metadata is present."""

        defaults = race_defaults if isinstance(race_defaults, dict) else {}
        race_date = self._normalize_race_date(defaults.get("race_date"))
        racecourse = self._normalize_racecourse(defaults.get("racecourse"))
        race_number = self._normalize_race_number(defaults.get("race_number"))
        if race_date and racecourse and race_number:
            return f"race_{race_date}_{racecourse}_{race_number}"
        return None

    def _normalize_race_date(self, value):
        text = str(value or "").strip()
        digits = "".join(char for char in text if char.isdigit())
        if len(digits) >= 8:
            return digits[:8]
        return None

    def _normalize_race_number(self, value):
        text = str(value or "").strip()
        if not text:
            return None
        digits = "".join(char for char in text if char.isdigit())
        if not digits:
            return None
        return f"{int(digits)}R"

    def _normalize_racecourse(self, value):
        mapping = {
            "札幌": "sapporo",
            "函館": "hakodate",
            "福島": "fukushima",
            "新潟": "niigata",
            "東京": "tokyo",
            "中山": "nakayama",
            "中京": "chuukyou",
            "京都": "kyoto",
            "阪神": "hanshin",
            "小倉": "kokura",
        }
        text = str(value).strip() if value is not None else ""
        return normalize_course_name(mapping.get(text, text.lower() or None))

    def _normalize_surface(self, value):
        text = str(value).strip().lower() if value is not None else ""
        if text in {"ダ", "ダート", "d", "dirt"}:
            return "dirt"
        if text in {"芝", "t", "turf"}:
            return "turf"
        return text or None

    def _normalize_track_condition(self, value):
        text = str(value).strip().lower() if value is not None else ""
        aliases = {
            "良": "good",
            "稍": "yielding",
            "稍重": "yielding",
            "重": "soft",
            "不": "heavy",
            "不良": "heavy",
        }
        return aliases.get(text, text or None)

    def _safe_int(self, value):
        try:
            return int(float(str(value).strip().replace("m", "")))
        except (TypeError, ValueError):
            return None

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

    def _apply_race_shape_and_final_scores(
        self,
        horse_results,
        race_defaults=None,
        track_bias_baseline=None,
    ):
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
        meeting_bias_result = self.meeting_bias_engine.analyze(
            race_context=race_context,
            meeting_knowledge=self._load_meeting_bias_knowledge(
                race_context.get("racecourse")
            ),
        )
        pace_result["meeting_bias_result"] = meeting_bias_result
        shape_results = self.race_shape_evaluator.evaluate_many(
            pace_prediction,
            horse_results,
            race_context=race_context,
            structure_result=structure_result,
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
            item["meeting_bias_result"] = meeting_bias_result
            item["meeting_bias"] = meeting_bias_result.get("meeting_bias", {})
            item["meeting_bias_comment"] = meeting_bias_result.get("meeting_bias_comment", "")
            item["meeting_bias_factors"] = meeting_bias_result.get("meeting_bias_factors", [])
            item["meeting_bias_warnings"] = meeting_bias_result.get("meeting_bias_warnings", [])
            item["meeting_bias_ready"] = meeting_bias_result.get("meeting_bias_ready", False)
            item["shape_score"] = shape_result.get("shape_score", 0)
            item["shape_comment"] = shape_result.get("shape_comment", "")
            item["shape_result"] = shape_result
            item["course_shape_score"] = course_shape_result.get("course_shape_score", 0)
            item["course_shape_comment"] = course_shape_result.get("course_shape_comment", "")
            item["course_shape_result"] = course_shape_result
            item["track_bias_score"] = track_bias_result.get("track_bias_score", 0)
            item["track_bias_comment"] = track_bias_result.get("track_bias_comment", "")
            item["track_bias_reasons"] = track_bias_result.get("track_bias_reasons", [])
            item["track_bias_matched"] = track_bias_result.get("track_bias_matched", False)
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
            item["evaluator_provenance"] = weight_result.get("evaluator_provenance", [])
            item["score_weight_provenance_version"] = weight_result.get("score_weight_provenance_version", "")
            item["weight_calculation_version"] = weight_result.get("weight_calculation_version", "")

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

        if track_bias_baseline:
            self._attach_track_bias_baseline(horse_results, track_bias_baseline)

        decision_results = self.decision_engine.decide_many(horse_results)
        for index, item in enumerate(horse_results):
            decision_result = decision_results[index] if index < len(decision_results) else {}
            item["decision"] = decision_result.get("decision", "")
            item["decision_score"] = decision_result.get("decision_score", 0)
            item["decision_level"] = decision_result.get("decision_level", "")
            item["decision_reason"] = decision_result.get("decision_reason", "")
            item["decision_factors"] = decision_result.get("decision_factors", [])
            item["decision_risks"] = decision_result.get("decision_risks", [])
            item["top_score_pass_rescued"] = decision_result.get("top_score_pass_rescued", False)
            item["top_score_pass_rescue_reason"] = decision_result.get("top_score_pass_rescue_reason", "")
            item["top_score_pass_rescue_skipped_reason"] = decision_result.get(
                "top_score_pass_rescue_skipped_reason",
                "",
            )
            item["quality_guard_applied"] = decision_result.get("quality_guard_applied", False)
            item["quality_guard_name"] = decision_result.get("quality_guard_name", "")
            item["quality_guard_reason"] = decision_result.get("quality_guard_reason", "")
            item["quality_guard_original_decision"] = decision_result.get("quality_guard_original_decision", "")
            item["quality_guard_adjusted_decision"] = decision_result.get("quality_guard_adjusted_decision", "")
            item["quality_guard_original_race_shape_penalty"] = decision_result.get(
                "quality_guard_original_race_shape_penalty",
                "",
            )
            item["quality_guard_adjusted_race_shape_penalty"] = decision_result.get(
                "quality_guard_adjusted_race_shape_penalty",
                "",
            )
            item["quality_guard_multiplier"] = decision_result.get("quality_guard_multiplier", "")
            item["quality_guard_past_performance_score"] = decision_result.get(
                "quality_guard_past_performance_score",
                "",
            )
            item["quality_guard_distance_score"] = decision_result.get("quality_guard_distance_score", "")
            item["quality_guard_decision_cap"] = decision_result.get("quality_guard_decision_cap", "")
            item["consensus_guard_enabled"] = decision_result.get("consensus_guard_enabled", False)
            item["consensus_guard_candidate"] = decision_result.get("consensus_guard_candidate", False)
            item["consensus_guard_applied"] = decision_result.get("consensus_guard_applied", False)
            item["consensus_guard_original_decision"] = decision_result.get(
                "consensus_guard_original_decision",
                "",
            )
            item["consensus_guard_final_decision"] = decision_result.get("consensus_guard_final_decision", "")
            item["consensus_positive_count"] = decision_result.get("consensus_positive_count", 0)
            item["consensus_negative_count"] = decision_result.get("consensus_negative_count", 0)
            item["consensus_positive_evaluators"] = decision_result.get("consensus_positive_evaluators", [])
            item["consensus_negative_evaluators"] = decision_result.get("consensus_negative_evaluators", [])
            item["consensus_block_reasons"] = decision_result.get("consensus_block_reasons", [])
            item["consensus_guard_reason"] = decision_result.get("consensus_guard_reason", "")
            item["risk_items"] = decision_result.get("risk_items", [])
            item["risk_count"] = decision_result.get("risk_count", 0)
            item["risk_score"] = decision_result.get("risk_score", 0)
            item["conflict_items"] = decision_result.get("conflict_items", [])
            item["conflict_count"] = decision_result.get("conflict_count", 0)
            item["conflict_score"] = decision_result.get("conflict_score", 0)
            item["decision_reason_detail"] = decision_result.get("decision_reason_detail", [])
            item["decision_trace"] = decision_result.get("decision_trace", [])
            item["decision_diagnostic_text"] = decision_result.get("decision_diagnostic_text", "")
            item["decision_diagnostics"] = decision_result.get("decision_diagnostics", {})
            item["decision_result"] = decision_result

        return pace_result

    def _manual_track_bias_active(self, manual_track_bias):
        """Return True only for actual manual bias values."""

        text = str(manual_track_bias or "").strip().lower()
        return bool(text) and text != "neutral"

    def _attach_track_bias_baseline(self, horse_results, baseline_result):
        """Attach neutral decision/rank data for TrackBias BUY guard."""

        baseline_rows = (
            baseline_result.get("results", [])
            if isinstance(baseline_result, dict)
            else []
        )
        baseline_map = self._track_bias_baseline_map(baseline_rows)
        for item in horse_results:
            if not isinstance(item, dict):
                continue
            name = item.get("horse_name")
            baseline = baseline_map.get(name)
            if not baseline:
                item["baseline_available"] = False
                item["baseline_decision"] = ""
                item["baseline_rank"] = None
                continue
            item["baseline_available"] = True
            item["baseline_decision"] = baseline.get("decision")
            item["baseline_rank"] = baseline.get("rank")
            item["baseline_decision_score"] = baseline.get("decision_score")
            item["baseline_adjusted_score"] = baseline.get("adjusted_score")

    def _baseline_race_decision_result(self, baseline_result):
        """Return the neutral race decision result for TrackBias race guard."""

        if not isinstance(baseline_result, dict):
            return {}
        race_decision = baseline_result.get("race_decision_result")
        if isinstance(race_decision, dict):
            return race_decision
        return {
            "race_decision": baseline_result.get("race_decision"),
            "race_decision_score": baseline_result.get("race_decision_score"),
            "race_confidence": baseline_result.get("race_confidence"),
            "race_complexity": baseline_result.get("race_complexity"),
            "race_volatility": baseline_result.get("race_volatility"),
            "race_stats": baseline_result.get("race_stats", {}),
        }

    def _track_bias_baseline_map(self, baseline_rows):
        rows = [
            row for row in baseline_rows
            if isinstance(row, dict) and row.get("horse_name")
        ]
        ranked = sorted(
            rows,
            key=lambda row: self._ranking_score(row),
            reverse=True,
        )
        result = {}
        for index, row in enumerate(ranked, start=1):
            result[row.get("horse_name")] = {
                "decision": row.get("decision"),
                "decision_score": row.get("decision_score"),
                "adjusted_score": row.get("adjusted_score"),
                "rank": index,
            }
        return result

    def _ranking_score(self, row):
        for key in ["adjusted_score", "integrated_score", "weighted_score", "final_score"]:
            value = row.get(key)
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return float("-inf")

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

    def clean_value(value):
        if value in (None, "", [], {}):
            return None
        return value

    def unique_list(values, limit=None):
        if not isinstance(values, list):
            return []
        seen = set()
        result = []
        for value in values:
            if value in (None, "", [], {}):
                continue
            text = str(value)
            if text in seen:
                continue
            seen.add(text)
            result.append(text)
            if limit is not None and len(result) >= limit:
                break
        return result

    def append_field(label, value):
        value = clean_value(value)
        if value is not None:
            lines.append(f"{label}: {value}")

    def append_list(title, values, limit=None):
        items = unique_list(values, limit=limit)
        if not items:
            return
        lines.append(title)
        for item in items:
            lines.append(f"- {item}")

    def append_dict(title, values):
        if not isinstance(values, dict) or not values:
            return
        lines.append(title)
        for key, value in values.items():
            if clean_value(value) is not None:
                lines.append(f"- {key}: {value}")

    def collect_warnings():
        warnings = []
        for item in data.get("ranked_results", []) or data.get("results", []):
            if not isinstance(item, dict):
                continue
            horse_name = item.get("horse_name") or "unknown"
            for warning in item.get("warnings") or []:
                if warning:
                    warnings.append(f"{horse_name}: {warning}")
        for horse_name in data.get("unlinked_horses") or []:
            if horse_name:
                warnings.append(f"{horse_name}: unlinked horse history")
        return unique_list(warnings)

    def append_horse_detail(rank, item):
        lines.append(f"{rank}. {item.get('horse_name')}")
        summary = item.get("explain_summary") or item.get("summary") or item.get("explanation")
        append_field("総評", summary)
        append_list("Strengths", item.get("strengths"), limit=5)
        append_list("Weaknesses", item.get("weaknesses"), limit=5)
        append_list("RiskFactors", item.get("risk_factors"), limit=5)
        impact_parts = []
        if clean_value(item.get("impact_score")) is not None:
            impact_parts.append(f"score={item.get('impact_score')}")
        if clean_value(item.get("impact_comment")) is not None:
            impact_parts.append(str(item.get("impact_comment")))
        if impact_parts:
            lines.append(f"Impact: {' / '.join(impact_parts)}")
        append_field("Shape", item.get("shape_comment"))
        append_field("CourseShape", item.get("course_shape_comment"))
        append_field("TrackBias", item.get("track_bias_comment"))
        append_field("MeetingBias", item.get("meeting_bias_comment"))
        append_field("Lap", item.get("lap_comment"))
        append_list("Warning", item.get("warnings"))
        lines.append("")

    ranked_results = [
        item for item in data.get("ranked_results", []) or data.get("results", [])
        if isinstance(item, dict)
    ]
    top5 = data.get("top5") or ranked_results[:5]
    top3_names = [
        item.get("horse_name")
        for item in ranked_results[:3]
        if isinstance(item, dict) and item.get("horse_name")
    ]
    buy_candidates = [
        item.get("horse_name")
        for item in ranked_results
        if isinstance(item, dict) and item.get("decision") == "BUY"
    ]
    warnings = collect_warnings()

    lines.append("=== 1. Race Summary ===")
    append_field("RaceDecision", data.get("race_decision"))
    append_field("RaceConfidence", data.get("race_confidence"))
    append_list("BUY候補", buy_candidates)
    append_list("上位3頭", top3_names)
    lines.append(f"Warning件数: {len(warnings)}")

    lines.append("")
    lines.append("=== 2. Race Structure ===")
    append_field("race_structure", data.get("race_structure"))
    append_field("structure_comment", data.get("structure_comment"))
    append_list("key_factors", data.get("key_factors"))
    append_dict("structure_flags", data.get("structure_flags"))
    race_pace = data.get("race_pace") if isinstance(data.get("race_pace"), dict) else {}
    append_field("race_pace", race_pace)
    append_field(
        "pace_comment",
        race_pace.get("pace_comment") or race_pace.get("comment") or data.get("structure_comment"),
    )

    lines.append("")
    lines.append("=== 3. Top5 Table ===")
    lines.append("順位 | 馬名 | adjusted_score | final_score | decision | confidence | impact_score")
    for index, item in enumerate(top5[:5], 1):
        lines.append(
            f"{index} | {item.get('horse_name')} | {item.get('adjusted_score')} | "
            f"{item.get('final_score')} | {item.get('decision')} | "
            f"{item.get('confidence_level')} | {item.get('impact_score')}"
        )

    lines.append("")
    lines.append("=== 4. Top5 Detail ===")
    for index, item in enumerate(top5[:5], 1):
        append_horse_detail(index, item)

    lines.append("=== 5. Warning Summary ===")
    append_list("馬ごとのwarning一覧", warnings)
    race_warning = data.get("warning") or data.get("warnings")
    if clean_value(race_warning) is not None:
        append_field("レース全体warning", race_warning)

    return "\n".join(lines)


def format_target_trial_report(result):
    """Create a compact race report for practical trial review."""

    data = result if isinstance(result, dict) else {}
    lines = []

    def clean_value(value):
        if value in (None, "", [], {}):
            return None
        return value

    def unique_list(values, limit=None, exclude=None):
        if not isinstance(values, list):
            return []
        seen = set(str(value) for value in (exclude or []) if value not in (None, "", [], {}))
        result = []
        for value in values:
            if value in (None, "", [], {}):
                continue
            text = str(value)
            if text in seen:
                continue
            seen.add(text)
            result.append(text)
            if limit is not None and len(result) >= limit:
                break
        return result

    def format_names(values):
        items = unique_list(values)
        return "、".join(items) if items else "なし"

    def append_field(label, value):
        value = clean_value(value)
        if value is not None:
            lines.append(f"{label}: {value}")

    def append_list(title, values, limit=None, exclude=None):
        items = unique_list(values, limit=limit, exclude=exclude)
        if not items:
            return
        lines.append(title)
        for item in items:
            lines.append(f"- {item}")

    def collect_warnings():
        warnings = []
        for item in data.get("ranked_results", []) or data.get("results", []):
            if not isinstance(item, dict):
                continue
            horse_name = item.get("horse_name") or "unknown"
            for warning in item.get("warnings") or []:
                if warning:
                    warnings.append(f"{horse_name}: {warning}")
        for horse_name in data.get("unlinked_horses") or []:
            if horse_name:
                warnings.append(f"{horse_name}: unlinked horse history")
        return unique_list(warnings)

    def readable_pace(value):
        mapping = {
            "slow": "Slow",
            "average": "Average",
            "fast": "Fast",
            "very_fast": "Very Fast",
        }
        return mapping.get(str(value), value)

    def style_advantage(pace):
        if pace in ("fast", "very_fast"):
            return "差し・追込が浮上しやすい一方、逃げ先行は前半負荷が高い"
        if pace == "slow":
            return "逃げ・先行が有利で、後方一気は届きにくい"
        return "先行・好位・差しがバランスよく評価される"

    def compact_summary(value):
        text = str(value or "").strip()
        if not text:
            return None
        return text.splitlines()[0]

    def append_horse_detail(rank, item):
        lines.append(f"{rank}. {item.get('horse_name')}")
        summary = item.get("explain_summary") or compact_summary(item.get("explanation")) or item.get("summary")
        append_field("総評", summary)
        strengths = unique_list(item.get("strengths"), limit=5)
        weaknesses = unique_list(item.get("weaknesses"), limit=5)
        risks = unique_list(item.get("risk_factors"), limit=5, exclude=weaknesses)
        append_list("Strengths", strengths)
        append_list("Weaknesses", weaknesses)
        append_list("RiskFactors", risks)
        impact_parts = []
        if clean_value(item.get("impact_score")) is not None:
            impact_parts.append(f"score={item.get('impact_score')}")
        if clean_value(item.get("impact_comment")) is not None:
            impact_parts.append(str(item.get("impact_comment")))
        if impact_parts:
            lines.append(f"Impact: {' / '.join(impact_parts)}")
        append_field("Shape", item.get("shape_comment"))
        append_field("CourseShape", item.get("course_shape_comment"))
        append_field("TrackBias", item.get("track_bias_comment"))
        append_field("MeetingBias", item.get("meeting_bias_comment"))
        append_field("Lap", item.get("lap_comment"))
        append_list("Warning", item.get("warnings"))
        lines.append("")

    ranked_results = [
        item for item in data.get("ranked_results", []) or data.get("results", [])
        if isinstance(item, dict)
    ]
    top5 = data.get("top5") or ranked_results[:5]
    top3_names = [
        item.get("horse_name")
        for item in ranked_results[:3]
        if isinstance(item, dict) and item.get("horse_name")
    ]
    buy_candidates = [
        item.get("horse_name")
        for item in ranked_results
        if isinstance(item, dict) and item.get("decision") == "BUY"
    ]
    warnings = collect_warnings()
    race_structure = data.get("race_structure") if isinstance(data.get("race_structure"), dict) else {}
    race_pace = data.get("race_pace") if isinstance(data.get("race_pace"), dict) else {}
    key_factors = data.get("key_factors") or race_structure.get("key_factors") or []
    course_name = race_structure.get("course")
    surface = race_structure.get("surface")
    distance = race_structure.get("distance")
    track_condition = race_structure.get("track_condition")
    pace_prediction = race_pace.get("pace_prediction") or race_structure.get("pace")
    pace_pressure = race_structure.get("pace_pressure")
    course_shape = race_structure.get("course_shape")
    draw_impact = race_structure.get("draw_impact")

    lines.append("========================")
    lines.append("1. AI総括")
    lines.append("========================")
    append_field("RaceDecision", data.get("race_decision"))
    append_field("RaceConfidence", data.get("race_confidence"))
    lines.append(f"BUY候補: {format_names(buy_candidates)}")
    lines.append(f"レースタイプ: {course_name or '-'}")
    append_field("馬場", track_condition)
    lines.append(f"想定ペース: {readable_pace(pace_prediction)}")
    lines.append(f"脚質傾向: {style_advantage(pace_prediction)}")
    lines.append(f"重要評価ポイント: {format_names(key_factors)}")
    primary_factors = unique_list(key_factors, limit=3)
    lines.append(f"AIが最も重視した要素: {format_names(primary_factors)}")
    decision = data.get("race_decision") or "-"
    if decision == "BUY":
        lines.append("判定理由: BUY候補とレース構造の一致が見られ、勝負可能と判断。")
    elif decision == "PASS":
        lines.append("判定理由: 評価材料はあるが、リスクや構造上の不確実性が残るためPASS。")
    else:
        lines.append(f"判定理由: RaceDecisionは{decision}。詳細は各馬の評価要素を確認。")
    lines.append(f"上位3頭: {format_names(top3_names)}")
    lines.append(f"Warning件数: {len(warnings)}")

    lines.append("")
    lines.append("========================")
    lines.append("2. RaceStructure")
    lines.append("========================")
    append_field("コース", course_name)
    append_field("芝/ダート", surface)
    append_field("距離", f"{distance}m" if distance is not None else None)
    append_field("馬場", track_condition)
    append_field("想定ペース", readable_pace(pace_prediction))
    append_field("ペース圧", pace_pressure)
    append_field("コース形状", course_shape)
    append_field("枠影響", draw_impact)
    append_list("重要評価要素(KeyFactors)", key_factors)
    append_field(
        "pace_comment",
        race_pace.get("pace_comment") or race_pace.get("comment") or data.get("structure_comment"),
    )

    lines.append("")
    lines.append("========================")
    lines.append("3. Top5一覧")
    lines.append("========================")
    lines.append("順位 | 馬名 | adjusted_score | final_score | decision | confidence | impact_score")
    for index, item in enumerate(top5[:5], 1):
        lines.append(
            f"{index} | {item.get('horse_name')} | {item.get('adjusted_score')} | "
            f"{item.get('final_score')} | {item.get('decision')} | "
            f"{item.get('confidence_level')} | {item.get('impact_score')}"
        )

    lines.append("")
    lines.append("========================")
    lines.append("4. Top5詳細")
    lines.append("========================")
    for index, item in enumerate(top5[:5], 1):
        append_horse_detail(index, item)

    lines.append("========================")
    lines.append("5. Warning")
    lines.append("========================")
    append_list("馬ごとのwarning一覧", warnings)
    race_warning = data.get("warning") or data.get("warnings")
    if clean_value(race_warning) is not None:
        append_field("レース全体warning", race_warning)

    return "\n".join(lines)


if __name__ == "__main__":
    adapter = TargetTrialAdapter()
    trial_result = adapter.run(
        "data/trial/kokura4r_trial.csv",
        "data/raw/test3.csv",
    )
    print(format_target_trial_report(trial_result))
