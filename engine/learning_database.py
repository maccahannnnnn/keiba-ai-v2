"""Store review records for future self-improvement analysis.

LearningDatabase is storage-shape only. It does not learn, re-score, update
knowledge, mutate decisions, or change confidence.
"""

from datetime import datetime, timezone


class LearningDatabase:
    """In-memory review history store for trial architecture."""

    def __init__(self):
        self.learning_history = []

    def save(
        self,
        prediction_snapshot=None,
        review_result=None,
        improvement_result=None,
        review_record=None,
    ):
        """Create and store a learning_record from review artifacts."""

        snapshot = prediction_snapshot if isinstance(prediction_snapshot, dict) else {}
        review = review_result if isinstance(review_result, dict) else {}
        improvement = improvement_result if isinstance(improvement_result, dict) else {}
        record_source = review_record if isinstance(review_record, dict) else {}

        timestamp = datetime.now(timezone.utc).isoformat()
        prediction_id = (
            record_source.get("prediction_id")
            or snapshot.get("prediction_id")
            or self._snapshot_prediction_id(snapshot)
        )
        review_level = review.get("review_level") or "pending"
        learning_status = "waiting_result" if review_level == "pending" else "recorded"

        learning_record = {
            "learning_id": self._learning_id(timestamp, prediction_id),
            "prediction_id": prediction_id,
            "timestamp": timestamp,
            "learning_time": timestamp,
            "learning_status": learning_status,
            "review_score": review.get("review_score"),
            "review_level": review_level,
            "improvement_priority": improvement.get("improvement_priority"),
            "review_hits": self._list(review.get("review_hits")),
            "review_misses": self._list(review.get("review_misses")),
            "improvement_targets": self._list(improvement.get("improvement_targets")),
        }

        self.learning_history.append(learning_record)

        return {
            "learning_record": learning_record,
            "learning_history": list(self.learning_history),
            "learning_id": learning_record.get("learning_id"),
            "learning_time": timestamp,
            "learning_status": learning_status,
        }

    def _snapshot_prediction_id(self, snapshot):
        timestamp = snapshot.get("timestamp") or datetime.now(timezone.utc).isoformat()
        race_name = snapshot.get("race_name") or "unknown_race"
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in str(race_name)).strip("_")
        compact_time = str(timestamp).replace("-", "").replace(":", "").replace("+", "_").replace(".", "_")
        return f"{compact_time}_{safe_name or 'unknown_race'}"

    def _learning_id(self, timestamp, prediction_id):
        compact_time = str(timestamp).replace("-", "").replace(":", "").replace("+", "_").replace(".", "_")
        safe_prediction_id = "".join(
            ch if ch.isalnum() else "_" for ch in str(prediction_id or "unknown_prediction")
        ).strip("_")
        return f"learning_{compact_time}_{safe_prediction_id or 'unknown_prediction'}"

    def _list(self, value):
        return value if isinstance(value, list) else []


if __name__ == "__main__":
    database = LearningDatabase()
    print(database.save(review_result={"review_level": "pending"}))
