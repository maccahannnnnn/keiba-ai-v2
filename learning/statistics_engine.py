"""StatisticsEngine for LearningHistory records.

This module is analysis-only. It does not update knowledge, modify scores,
change decisions, alter confidence, or trigger automatic learning.
"""

from collections import Counter


class StatisticsEngine:
    """Aggregate LearningDatabase / review history records into statistics."""

    SUCCESS_KEYS = (
        "success",
        "hit",
        "result",
        "review_result",
        "is_success",
        "decision_result",
    )

    def __init__(self, learning_database=None):
        self.learning_database = learning_database

    def analyze(self, records=None):
        """Return statistics_summary for learning history records."""

        normalized_records = self._records(records)
        total_reviews = len(normalized_records)

        decision_stats = {}
        confidence_stats = {}
        buy_pass_stats = {"BUY": self._empty_stat(), "PASS": self._empty_stat()}
        improvement_counter = Counter()
        course_counter = Counter()
        distance_counter = Counter()
        track_condition_counter = Counter()

        for record in normalized_records:
            decision = str(self._safe_get(record, ["decision", "horse_decision"], "unknown") or "unknown")
            confidence = str(
                self._safe_get(
                    record,
                    ["confidence", "confidence_level", "race_confidence"],
                    "unknown",
                )
                or "unknown"
            ).upper()
            success_result = self._normalize_success_result(record)

            self._add_stat(decision_stats, decision, success_result)
            self._add_stat(confidence_stats, confidence, success_result)
            if decision in buy_pass_stats:
                self._add_existing_stat(buy_pass_stats[decision], success_result)

            improvement_counter.update(self._improvement_values(record))
            course_counter.update([self._course_value(record)])
            distance_counter.update([self._distance_value(record)])
            track_condition_counter.update([self._track_condition_value(record)])

        self._finalize_stats(decision_stats)
        self._finalize_stats(confidence_stats)
        self._finalize_stats(buy_pass_stats)

        statistics_summary = {
            "total_reviews": total_reviews,
            "decision_stats": decision_stats,
            "confidence_stats": confidence_stats,
            "buy_pass_stats": buy_pass_stats,
            "improvement_frequency": dict(improvement_counter),
            "course_stats": dict(course_counter),
            "distance_stats": dict(distance_counter),
            "track_condition_stats": dict(track_condition_counter),
            "summary_comment": self._summary_comment(
                total_reviews,
                decision_stats,
                confidence_stats,
                improvement_counter,
            ),
        }
        return statistics_summary

    def analyze_as_result(self, records=None):
        """Wrap analyze(records) output in a StatisticsResult."""

        from learning.statistics_result import StatisticsResult

        statistics_summary = self.analyze(records)
        record_count = statistics_summary.get("total_reviews", 0)
        warnings = []
        if record_count == 0:
            warnings.append("statistics records are empty")
        return StatisticsResult(
            statistics_summary=statistics_summary,
            record_count=record_count,
            source="LearningHistory",
            warnings=warnings,
        )

    def export_statistics(self, records=None, output_dir="reports/statistics"):
        """Export analyze_as_result(records) to JSON and return the saved path."""

        from learning.statistics_exporter import StatisticsExporter

        statistics_result = self.analyze_as_result(records)
        return StatisticsExporter(output_dir=output_dir).export_json(statistics_result)

    def _normalize_success_result(self, record):
        """Normalize stored result flags into success / failure / unknown."""

        value = self._safe_get(record, self.SUCCESS_KEYS, None)
        if isinstance(value, bool):
            return "success" if value else "failure"
        if isinstance(value, (int, float)):
            if value > 0:
                return "success"
            if value < 0:
                return "failure"
            return "unknown"

        text = str(value).strip().lower() if value is not None else ""
        if not text:
            return "unknown"

        success_words = {"success", "hit", "win", "won", "true", "ok", "good", "excellent"}
        failure_words = {"failure", "miss", "failed", "lose", "lost", "false", "bad", "poor"}
        if text in success_words or any(word in text for word in ("success", "hit", "的中", "好走")):
            return "success"
        if text in failure_words or any(word in text for word in ("failure", "miss", "凡走", "全滅")):
            return "failure"
        return "unknown"

    def _safe_get(self, record, keys, default=None):
        """Safely get a value from several possible keys or nested dicts."""

        item = record if isinstance(record, dict) else {}
        for key in keys:
            if key in item:
                return item.get(key)

        for value in item.values():
            if isinstance(value, dict):
                nested = self._safe_get(value, keys, None)
                if nested is not None:
                    return nested
        return default

    def _records(self, records):
        if records is None and self.learning_database is not None:
            records = getattr(self.learning_database, "learning_history", None)
        if isinstance(records, dict):
            history = records.get("learning_history")
            if isinstance(history, list):
                return [record for record in history if isinstance(record, dict)]
            return [records]
        if isinstance(records, list):
            return [record for record in records if isinstance(record, dict)]
        return []

    def _add_stat(self, stats, key, result):
        if key not in stats:
            stats[key] = self._empty_stat()
        self._add_existing_stat(stats[key], result)

    def _add_existing_stat(self, stat, result):
        stat["count"] += 1
        if result == "success":
            stat["success"] += 1
        elif result == "failure":
            stat["failure"] += 1
        else:
            stat["unknown"] += 1

    def _empty_stat(self):
        return {
            "count": 0,
            "success": 0,
            "failure": 0,
            "unknown": 0,
            "success_rate": 0.0,
        }

    def _finalize_stats(self, stats):
        for stat in stats.values():
            known = stat.get("success", 0) + stat.get("failure", 0)
            stat["success_rate"] = round(stat.get("success", 0) / known, 3) if known else 0.0

    def _improvement_values(self, record):
        values = []
        for key in (
            "improvement_targets",
            "improvement_candidates",
            "improvement_advice",
            "improvement_suggestions",
            "improvement_frequency",
        ):
            value = self._safe_get(record, [key], None)
            if isinstance(value, dict):
                values.extend(str(item) for item in value.keys())
            elif isinstance(value, list):
                values.extend(str(item) for item in value if item not in {None, ""})
            elif value not in {None, ""}:
                values.append(str(value))
        return values

    def _course_value(self, record):
        return str(self._safe_get(record, ["course", "racecourse"], "unknown") or "unknown")

    def _distance_value(self, record):
        return str(self._safe_get(record, ["distance"], "unknown") or "unknown")

    def _track_condition_value(self, record):
        return str(
            self._safe_get(record, ["track_condition", "condition", "馬場状態"], "unknown")
            or "unknown"
        )

    def _summary_comment(self, total_reviews, decision_stats, confidence_stats, improvement_counter):
        if total_reviews == 0:
            return "レビュー履歴がないため、統計サマリーは保留です。"

        comments = [f"総レビュー数は{total_reviews}件です。"]
        buy_stats = decision_stats.get("BUY")
        if buy_stats and buy_stats.get("count", 0) < 3:
            comments.append("BUY判断の件数が少ないため、成功率評価は保留です。")
        elif buy_stats:
            comments.append(f"BUY判断の成功率は{buy_stats.get('success_rate', 0.0)}です。")

        high_confidence = confidence_stats.get("HIGH")
        if high_confidence and high_confidence.get("failure", 0) > 0:
            comments.append("Confidence HIGHの失敗があるため、過信傾向の確認が必要です。")

        if improvement_counter:
            target, count = improvement_counter.most_common(1)[0]
            comments.append(f"改善候補では {target} が{count}回出現しています。")
        return " ".join(comments)


if __name__ == "__main__":
    sample_records = [
        {
            "decision": "BUY",
            "confidence": "HIGH",
            "success": True,
            "course": "kokura",
            "distance": 1700,
            "track_condition": "稍重",
            "improvement_targets": ["ConfidenceEngine"],
        },
        {
            "decision": "PASS",
            "confidence": "LOW",
            "success": "unknown",
            "course": "kokura",
            "distance": 1700,
            "track_condition": "稍重",
        },
    ]
    print(StatisticsEngine().analyze(sample_records))
