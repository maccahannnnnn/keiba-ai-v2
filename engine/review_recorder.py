"""Record prediction-time snapshots for later self review.

ReviewRecorder is storage-shape only. It does not learn, re-score, or mutate
existing scores, decisions, summaries, confidence, or reports.
"""

from datetime import datetime, timezone


class ReviewRecorder:
    """Create review-ready prediction snapshots from final trial output."""

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

        return {
            "horse_name": item.get("horse_name") or item.get("name") or "unknown",
            "rank": item.get("rank") or item.get("final_rank") or fallback_rank,
            "adjusted_score": score_view.get("adjusted_score", item.get("adjusted_score")),
            "decision": item.get("decision"),
            "confidence": {
                "score": item.get("confidence_score"),
                "level": item.get("confidence_level"),
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
            "summary": item.get("summary") or item.get("final_summary") or "",
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


if __name__ == "__main__":
    recorder = ReviewRecorder()
    sample_output = {
        "race_decision": "PLAY",
        "race_confidence": "high",
        "trial_report_summary": "sample summary",
        "horses": [{"horse_name": "A", "rank": 1, "decision": "BUY"}],
    }
    print(recorder.record(sample_output))
