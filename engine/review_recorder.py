"""Record prediction-time snapshots for later self review.

ReviewRecorder is storage-shape only. It does not learn, re-score, or mutate
existing scores, decisions, summaries, confidence, or reports.
"""

import json
from datetime import datetime, timezone


class ReviewRecorder:
    """Create review-ready prediction snapshots from final trial output."""

    BUY_THRESHOLD = 0.80
    CAUTION_THRESHOLD = 0.50

    def record(self, race_output=None, final_outputs=None, trial_report=None):
        """Return review_record and prediction_snapshot for later comparison."""

        output = race_output if isinstance(race_output, dict) else {}
        horses = final_outputs if isinstance(final_outputs, list) else output.get("horses", [])
        if not isinstance(horses, list):
            horses = []

        timestamp = datetime.now(timezone.utc).isoformat()
        race_name = self._race_name(output)
        prediction_id = self._prediction_id(timestamp, race_name)
        horse_records = [self._horse_record(horse, index) for index, horse in enumerate(horses, start=1)]

        top_horses = horse_records[:5]
        buy_horses = [horse for horse in horse_records if horse.get("decision") == "BUY"]

        prediction_snapshot = {
            "timestamp": timestamp,
            "race_name": race_name,
            "top_horses": top_horses,
            "buy_horses": buy_horses,
            "race_decision": output.get("race_decision"),
            "race_confidence": output.get("race_confidence"),
            "trial_report_summary": output.get("trial_report_summary"),
        }

        review_record = {
            "prediction_id": prediction_id,
            "prediction_time": timestamp,
            "review_status": "pending",
            "review_ready": True,
            "prediction_snapshot": prediction_snapshot,
            "race": {
                "race_name": race_name,
                "race_decision": output.get("race_decision"),
                "race_confidence": output.get("race_confidence"),
                "race_summary": output.get("race_summary") or output.get("race_summary_short"),
                "self_check": output.get("self_check_result", {}),
                "trial_report_summary": output.get("trial_report_summary"),
            },
            "horses": horse_records,
            "trial_report": trial_report if trial_report is not None else output.get("trial_report"),
        }

        return {
            "prediction_snapshot": prediction_snapshot,
            "prediction_time": timestamp,
            "prediction_id": prediction_id,
            "review_record": review_record,
            "review_status": "pending",
            "review_ready": True,
        }

    def _horse_record(self, horse, fallback_rank):
        item = horse if isinstance(horse, dict) else {}
        score_view = item.get("score_view") if isinstance(item.get("score_view"), dict) else {}
        consistency_view = item.get("consistency_view") if isinstance(item.get("consistency_view"), dict) else {}
        decision_result = item.get("decision_result") if isinstance(item.get("decision_result"), dict) else {}
        decision_diagnostics = (
            decision_result.get("decision_diagnostics")
            if isinstance(decision_result.get("decision_diagnostics"), dict)
            else item.get("decision_diagnostics")
        )
        if not isinstance(decision_diagnostics, dict):
            decision_diagnostics = {}

        decision = item.get("decision") or decision_result.get("decision")
        decision_score = self._first_present(
            item.get("decision_score"),
            decision_result.get("decision_score"),
            decision_diagnostics.get("decision_score"),
        )
        confidence_level = self._first_present(
            item.get("confidence_level"),
            decision_diagnostics.get("confidence"),
            item.get("confidence"),
        )

        return {
            "horse_name": item.get("horse_name") or item.get("name") or "unknown",
            "rank": item.get("rank") or item.get("final_rank") or fallback_rank,
            "adjusted_score": self._score_value(item, score_view, "adjusted_score"),
            "decision": decision,
            "confidence": {
                "score": item.get("confidence_score"),
                "level": confidence_level,
                "reason": item.get("confidence_reason"),
            },
            "consistency": {
                "score": consistency_view.get("consistency_score", item.get("consistency_score")),
                "level": consistency_view.get("consistency_level", item.get("consistency_level")),
            },
            "strengths": self._list(item.get("strengths") or item.get("final_strengths")),
            "weaknesses": self._list(item.get("weaknesses") or item.get("final_weaknesses")),
            "risks": self._list(item.get("risks") or item.get("final_risks")),
            "warnings": self._list(item.get("warnings")),
            "meeting_bias": {
                "comment": item.get("meeting_bias_comment", ""),
                "factors": self._list(item.get("meeting_bias_factors")),
                "warnings": self._list(item.get("meeting_bias_warnings")),
                "ready": item.get("meeting_bias_ready", False),
                "selected_stage": self._meeting_bias_value(item, "selected_meeting_stage"),
                "selected_surface": self._meeting_bias_value(item, "selected_surface"),
                "selected_distance_category": self._meeting_bias_value(item, "selected_distance_category"),
                "source": self._meeting_bias_value(item, "meeting_bias_source"),
                "score_impact": self._meeting_bias_value(item, "score_impact"),
            },
            "summary": item.get("summary") or item.get("final_summary") or "",
            "review_trace": self._review_trace(
                item,
                score_view,
                decision_result,
                decision_diagnostics,
                decision,
                decision_score,
                confidence_level,
            ),
        }

    def _review_trace(
        self,
        item,
        score_view,
        decision_result,
        decision_diagnostics,
        decision,
        decision_score,
        confidence_level,
    ):
        """Return same-run Decision trace values that already exist on the horse."""

        risk_reasons = self._list(
            item.get("decision_risks")
            or decision_result.get("decision_risks")
            or decision_diagnostics.get("risk_texts")
        )
        positive_reasons = self._list(
            item.get("decision_factors")
            or decision_result.get("decision_factors")
        )
        conflict_reasons = self._list(
            item.get("conflict_factors")
            or decision_diagnostics.get("conflict_raw")
            or decision_result.get("conflict_items")
        )
        risk_score = self._first_present(
            item.get("risk_score"),
            decision_result.get("risk_score"),
            decision_diagnostics.get("risk_score"),
        )
        conflict_score = self._first_present(
            item.get("conflict_score"),
            decision_result.get("conflict_score"),
            decision_diagnostics.get("conflict_score"),
        )

        return {
            "official_decision": decision,
            "decision_score": decision_score,
            "buy_threshold": self.BUY_THRESHOLD,
            "caution_threshold": self.CAUTION_THRESHOLD,
            "buy_threshold_gap": self._threshold_gap(self.BUY_THRESHOLD, decision_score),
            "caution_threshold_gap": self._threshold_gap(self.CAUTION_THRESHOLD, decision_score),
            "final_score": self._score_value(item, score_view, "final_score"),
            "adjusted_score": self._score_value(item, score_view, "adjusted_score"),
            "confidence": confidence_level,
            "risk_reasons": risk_reasons,
            "positive_reasons": positive_reasons,
            "conflict_reasons": conflict_reasons,
            "ability_score": self._first_present(item.get("ability_score"), item.get("total_score")),
            "distance_score": item.get("distance_score"),
            "course_score": self._first_present(item.get("course_score"), item.get("course_shape_score")),
            "race_shape_score": self._first_present(item.get("race_shape_score"), item.get("shape_score")),
            "track_bias_score": item.get("track_bias_score"),
            "pace_score": self._first_present(item.get("pace_score"), item.get("pace_style_score")),
            "running_style_score": self._first_present(item.get("running_style_score"), item.get("pace_style_score")),
            "lap_suitability_score": self._first_present(item.get("lap_suitability_score"), item.get("lap_score")),
            "blood_score": self._first_present(item.get("blood_score"), item.get("bloodline_score")),
            "weight_score": self._first_present(item.get("weight_score"), item.get("weighted_score")),
            "condition_score": self._first_present(item.get("condition_score"), item.get("track_condition_score")),
            "risk_trace": self._risk_trace(decision_diagnostics, risk_reasons),
            "decision_trace": decision_diagnostics.get("decision_trace", decision_result.get("decision_trace", [])),
            "score_before_decision_adjustment": "",
            "risk_adjustment_total": risk_score,
            "conflict_adjustment_total": conflict_score,
            "score_after_decision_adjustment": decision_score,
            "quality_guard_applied": decision_result.get("quality_guard_applied", False),
            "quality_guard_name": decision_result.get("quality_guard_name", ""),
            "original_race_shape_penalty": decision_result.get("quality_guard_original_race_shape_penalty", ""),
            "adjusted_race_shape_penalty": decision_result.get("quality_guard_adjusted_race_shape_penalty", ""),
            "guard_multiplier": decision_result.get("quality_guard_multiplier", ""),
            "quality_guard_past_performance_score": decision_result.get("quality_guard_past_performance_score", ""),
            "quality_guard_distance_score": decision_result.get("quality_guard_distance_score", ""),
            "quality_guard_original_decision": decision_result.get("quality_guard_original_decision", ""),
            "quality_guard_adjusted_decision": decision_result.get("quality_guard_adjusted_decision", ""),
            "quality_guard_decision_cap": decision_result.get("quality_guard_decision_cap", ""),
            "quality_guard_reason": decision_result.get("quality_guard_reason", ""),
            "consensus_guard_enabled": decision_result.get("consensus_guard_enabled", False),
            "consensus_guard_candidate": decision_result.get("consensus_guard_candidate", False),
            "consensus_guard_applied": decision_result.get("consensus_guard_applied", False),
            "consensus_guard_original_decision": decision_result.get("consensus_guard_original_decision", ""),
            "consensus_guard_final_decision": decision_result.get("consensus_guard_final_decision", ""),
            "consensus_positive_count": decision_result.get("consensus_positive_count", 0),
            "consensus_negative_count": decision_result.get("consensus_negative_count", 0),
            "consensus_positive_evaluators": decision_result.get("consensus_positive_evaluators", []),
            "consensus_negative_evaluators": decision_result.get("consensus_negative_evaluators", []),
            "consensus_block_reasons": decision_result.get("consensus_block_reasons", []),
            "consensus_guard_reason": decision_result.get("consensus_guard_reason", ""),
            "meeting_bias_comment": item.get("meeting_bias_comment", ""),
            "meeting_bias_factors": self._list(item.get("meeting_bias_factors")),
            "meeting_bias_warnings": self._list(item.get("meeting_bias_warnings")),
            "meeting_bias_ready": item.get("meeting_bias_ready", False),
            "meeting_bias_stage": self._meeting_bias_value(item, "selected_meeting_stage"),
            "meeting_bias_surface": self._meeting_bias_value(item, "selected_surface"),
            "meeting_bias_distance_category": self._meeting_bias_value(item, "selected_distance_category"),
            "meeting_bias_source": self._meeting_bias_value(item, "meeting_bias_source"),
            "meeting_bias_score_impact": self._meeting_bias_value(item, "score_impact"),
        }

    def horse_review_row(self, horse_record, race_context=None, result_row=None):
        """Flatten a review horse record for future horse_review.csv writers."""

        race = race_context if isinstance(race_context, dict) else {}
        result = result_row if isinstance(result_row, dict) else {}
        item = horse_record if isinstance(horse_record, dict) else {}
        trace = item.get("review_trace") if isinstance(item.get("review_trace"), dict) else {}
        confidence = item.get("confidence") if isinstance(item.get("confidence"), dict) else {}

        return {
            "race_id": race.get("race_id", ""),
            "racecourse": race.get("racecourse", ""),
            "race_number": race.get("race_number", ""),
            "horse_name": item.get("horse_name", ""),
            "horse_number": result.get("horse_number", ""),
            "ai_rank": item.get("rank", ""),
            "final_score": trace.get("final_score", ""),
            "adjusted_score": trace.get("adjusted_score", item.get("adjusted_score", "")),
            "decision": item.get("decision", ""),
            "confidence": confidence.get("level", trace.get("confidence", "")),
            "actual_finish": result.get("finish_position", ""),
            "actual_top3": self._actual_within(result.get("finish_position"), 3),
            "actual_top5": self._actual_within(result.get("finish_position"), 5),
            "fourth_corner_position": result.get("fourth_corner_position", ""),
            "last_3f": result.get("last_3f", result.get("last3f", "")),
            "last_3f_rank": result.get("last_3f_rank", result.get("last3f_rank", "")),
            "positive_reasons": self._join(trace.get("positive_reasons")),
            "risk_reasons": self._join(trace.get("risk_reasons")),
            "conflict_reasons": self._join(trace.get("conflict_reasons")),
            "review_classification": "",
            "root_cause_candidates": "",
            "review_comment": item.get("summary", ""),
            "official_decision": trace.get("official_decision", item.get("decision", "")),
            "decision_score": trace.get("decision_score", ""),
            "buy_threshold": trace.get("buy_threshold", ""),
            "caution_threshold": trace.get("caution_threshold", ""),
            "buy_threshold_gap": trace.get("buy_threshold_gap", ""),
            "caution_threshold_gap": trace.get("caution_threshold_gap", ""),
            "ability_score": trace.get("ability_score", ""),
            "distance_score": trace.get("distance_score", ""),
            "course_score": trace.get("course_score", ""),
            "race_shape_score": trace.get("race_shape_score", ""),
            "track_bias_score": trace.get("track_bias_score", ""),
            "pace_score": trace.get("pace_score", ""),
            "running_style_score": trace.get("running_style_score", ""),
            "lap_suitability_score": trace.get("lap_suitability_score", ""),
            "blood_score": trace.get("blood_score", ""),
            "weight_score": trace.get("weight_score", ""),
            "condition_score": trace.get("condition_score", ""),
            "risk_trace": self._json(trace.get("risk_trace")),
            "decision_trace": self._json(trace.get("decision_trace")),
            "score_before_decision_adjustment": trace.get("score_before_decision_adjustment", ""),
            "risk_adjustment_total": trace.get("risk_adjustment_total", ""),
            "conflict_adjustment_total": trace.get("conflict_adjustment_total", ""),
            "score_after_decision_adjustment": trace.get("score_after_decision_adjustment", ""),
            "quality_guard_applied": trace.get("quality_guard_applied", ""),
            "quality_guard_name": trace.get("quality_guard_name", ""),
            "original_race_shape_penalty": trace.get("original_race_shape_penalty", ""),
            "adjusted_race_shape_penalty": trace.get("adjusted_race_shape_penalty", ""),
            "guard_multiplier": trace.get("guard_multiplier", ""),
            "quality_guard_past_performance_score": trace.get("quality_guard_past_performance_score", ""),
            "quality_guard_distance_score": trace.get("quality_guard_distance_score", ""),
            "quality_guard_original_decision": trace.get("quality_guard_original_decision", ""),
            "quality_guard_adjusted_decision": trace.get("quality_guard_adjusted_decision", ""),
            "quality_guard_decision_cap": trace.get("quality_guard_decision_cap", ""),
            "quality_guard_reason": trace.get("quality_guard_reason", ""),
            "consensus_guard_enabled": trace.get("consensus_guard_enabled", ""),
            "consensus_guard_candidate": trace.get("consensus_guard_candidate", ""),
            "consensus_guard_applied": trace.get("consensus_guard_applied", ""),
            "consensus_guard_original_decision": trace.get("consensus_guard_original_decision", ""),
            "consensus_guard_final_decision": trace.get("consensus_guard_final_decision", ""),
            "consensus_positive_count": trace.get("consensus_positive_count", ""),
            "consensus_negative_count": trace.get("consensus_negative_count", ""),
            "consensus_positive_evaluators": self._json(trace.get("consensus_positive_evaluators")),
            "consensus_negative_evaluators": self._json(trace.get("consensus_negative_evaluators")),
            "consensus_block_reasons": self._json(trace.get("consensus_block_reasons")),
            "consensus_guard_reason": trace.get("consensus_guard_reason", ""),
            "meeting_bias_comment": trace.get("meeting_bias_comment", ""),
            "meeting_bias_factors": self._json(trace.get("meeting_bias_factors")),
            "meeting_bias_warnings": self._json(trace.get("meeting_bias_warnings")),
            "meeting_bias_ready": trace.get("meeting_bias_ready", ""),
            "meeting_bias_stage": trace.get("meeting_bias_stage", ""),
            "meeting_bias_surface": trace.get("meeting_bias_surface", ""),
            "meeting_bias_distance_category": trace.get("meeting_bias_distance_category", ""),
            "meeting_bias_source": trace.get("meeting_bias_source", ""),
            "meeting_bias_score_impact": trace.get("meeting_bias_score_impact", ""),
        }

    def _race_name(self, output):
        structure = output.get("race_structure")
        if isinstance(structure, dict):
            parts = [
                structure.get("racecourse"),
                structure.get("surface"),
                structure.get("distance"),
            ]
            text = "_".join(str(part) for part in parts if part not in {None, ""})
            if text:
                return text
        detail = output.get("race_summary_detail") or output.get("structure_comment")
        if detail:
            return str(detail).split("。")[0][:60]
        return "unknown_race"

    def _prediction_id(self, timestamp, race_name):
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in str(race_name)).strip("_")
        compact_time = timestamp.replace("-", "").replace(":", "").replace("+", "_").replace(".", "_")
        return f"{compact_time}_{safe_name or 'unknown_race'}"

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _first_present(self, *values):
        for value in values:
            if value not in (None, ""):
                return value
        return ""

    def _score_value(self, item, score_view, key):
        return self._first_present(score_view.get(key), item.get(key))

    def _threshold_gap(self, threshold, score):
        try:
            return round(float(threshold) - float(score), 4)
        except (TypeError, ValueError):
            return ""

    def _risk_trace(self, diagnostics, risk_reasons):
        risk_items = self._list(diagnostics.get("risk_items"))
        traces = []
        for index, text in enumerate(self._list(risk_reasons), start=1):
            risk_id = risk_items[index - 1] if index - 1 < len(risk_items) else ""
            traces.append(
                {
                    "risk_id": risk_id,
                    "risk_text": text,
                    "risk_category": "",
                    "source_engine": "",
                    "source_evaluator": "",
                    "score_impact": "",
                    "decision_impact": "",
                }
            )
        return traces

    def _join(self, values):
        return "; ".join(str(value) for value in self._list(values) if value not in (None, ""))

    def _json(self, value):
        if value in (None, ""):
            return ""
        return json.dumps(value, ensure_ascii=False)

    def _meeting_bias_value(self, item, key):
        result = item.get("meeting_bias_result")
        if isinstance(result, dict):
            value = result.get(key)
            if value not in (None, ""):
                return value
        return item.get(key, "")

    def _actual_within(self, finish, limit):
        try:
            return int(finish) <= limit
        except (TypeError, ValueError):
            return ""


if __name__ == "__main__":
    recorder = ReviewRecorder()
    sample_output = {
        "race_decision": "PLAY",
        "race_confidence": "high",
        "trial_report_summary": "sample summary",
        "horses": [{"horse_name": "A", "rank": 1, "decision": "BUY"}],
    }
    print(recorder.record(sample_output))
