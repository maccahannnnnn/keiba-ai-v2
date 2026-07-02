"""Analyze stored review records without changing any evaluation output.

LearningEngine only summarizes LearningDatabase records. It does not learn
weights, re-score horses, update knowledge, or change decisions/confidence.
"""

from collections import Counter


class LearningEngine:
    """Build trend summaries from learning_history / learning_record."""

    INSUFFICIENT_SUMMARY = "学習履歴が不足しているため傾向分析は保留"
    INSUFFICIENT_COMMENT = "レース結果とレビュー履歴が蓄積された後に傾向分析を行います。"

    def analyze(
        self,
        learning_history=None,
        learning_record=None,
        review_result=None,
        improvement_result=None,
    ):
        """Return learning_analysis_result from stored review information."""

        records = self._collect_records(learning_history, learning_record)
        completed_records = [
            record
            for record in records
            if isinstance(record, dict) and record.get("review_level") != "pending"
        ]

        if not completed_records:
            return self._insufficient_result(records)

        level_counter = Counter()
        priority_counter = Counter()
        hit_counter = Counter()
        miss_counter = Counter()
        target_counter = Counter()
        scores = []

        for record in completed_records:
            level_counter.update([record.get("review_level") or "unknown"])
            priority_counter.update([record.get("improvement_priority") or "unknown"])
            hit_counter.update(self._list(record.get("review_hits")))
            miss_counter.update(self._list(record.get("review_misses")))
            target_counter.update(self._list(record.get("improvement_targets")))
            score = record.get("review_score")
            if isinstance(score, (int, float)):
                scores.append(score)

        average_score = round(sum(scores) / len(scores), 3) if scores else None
        success_patterns = self._patterns(hit_counter, "success")
        failure_patterns = self._patterns(miss_counter, "failure")
        frequent_targets = [
            {"target": key, "count": count}
            for key, count in target_counter.most_common()
        ]

        learning_trends = {
            "record_count": len(records),
            "completed_record_count": len(completed_records),
            "review_level_distribution": dict(level_counter),
            "average_review_score": average_score,
            "improvement_priority_distribution": dict(priority_counter),
            "review_hits_frequency": dict(hit_counter),
            "review_misses_frequency": dict(miss_counter),
            "improvement_targets_frequency": dict(target_counter),
        }
        decision_trends = self._decision_trends(hit_counter, miss_counter)
        confidence_trends = self._confidence_trends(hit_counter, miss_counter)
        summary = self._summary(completed_records, average_score, target_counter, miss_counter)
        comment = self._comment(completed_records, target_counter, miss_counter)

        return {
            "learning_analysis_result": {
                "learning_summary": summary,
                "learning_trends": learning_trends,
                "success_patterns": success_patterns,
                "failure_patterns": failure_patterns,
                "frequent_improvement_targets": frequent_targets,
                "decision_trends": decision_trends,
                "confidence_trends": confidence_trends,
                "learning_comment": comment,
            },
            "learning_summary": summary,
            "learning_trends": learning_trends,
            "success_patterns": success_patterns,
            "failure_patterns": failure_patterns,
            "frequent_improvement_targets": frequent_targets,
            "decision_trends": decision_trends,
            "confidence_trends": confidence_trends,
            "learning_comment": comment,
        }

    def _insufficient_result(self, records):
        learning_trends = {
            "record_count": len(records),
            "completed_record_count": 0,
        }
        result = {
            "learning_summary": self.INSUFFICIENT_SUMMARY,
            "learning_trends": learning_trends,
            "success_patterns": [],
            "failure_patterns": [],
            "frequent_improvement_targets": [],
            "decision_trends": {},
            "confidence_trends": {},
            "learning_comment": self.INSUFFICIENT_COMMENT,
        }
        return {"learning_analysis_result": result, **result}

    def _collect_records(self, learning_history, learning_record):
        records = []
        if isinstance(learning_history, list):
            records.extend(record for record in learning_history if isinstance(record, dict))
        if isinstance(learning_record, dict) and learning_record not in records:
            records.append(learning_record)
        return records

    def _patterns(self, counter, pattern_type):
        key_name = "hit" if pattern_type == "success" else "miss"
        return [
            {key_name: key, "count": count}
            for key, count in counter.most_common()
        ]

    def _decision_trends(self, hit_counter, miss_counter):
        return {
            "buy_success_notes": self._filter_counter(hit_counter, ["BUY", "buy"]),
            "buy_failure_notes": self._filter_counter(miss_counter, ["BUY", "buy"]),
            "pass_risk_notes": self._filter_counter(miss_counter, ["PASS", "pass"]),
            "race_decision_notes": self._filter_counter(miss_counter, ["RaceDecision", "race_decision"]),
        }

    def _confidence_trends(self, hit_counter, miss_counter):
        return {
            "high_confidence_notes": self._filter_counter(hit_counter, ["Confidence", "confidence"]),
            "overconfidence_notes": self._filter_counter(miss_counter, ["Confidence", "confidence"]),
            "low_confidence_notes": self._filter_counter(miss_counter, ["low confidence", "Confidence low"]),
        }

    def _filter_counter(self, counter, keywords):
        notes = []
        for text, count in counter.most_common():
            if any(keyword in str(text) for keyword in keywords):
                notes.append({"note": text, "count": count})
        return notes

    def _summary(self, records, average_score, target_counter, miss_counter):
        if average_score is None:
            return "レビュー履歴はありますが、review_scoreが不足しているため傾向分析は限定的です。"
        if average_score >= 0.75:
            base = "レビュー履歴では良好な評価傾向が見られます。"
        elif average_score >= 0.55:
            base = "レビュー履歴では一部に改善余地があります。"
        else:
            base = "レビュー履歴では評価ズレが目立つため、改善対象の確認が必要です。"

        top_target = target_counter.most_common(1)
        if top_target:
            return f"{base} 最も多い改善対象は {top_target[0][0]} です。"
        top_miss = miss_counter.most_common(1)
        if top_miss:
            return f"{base} 目立つ失敗パターンは {top_miss[0][0]} です。"
        return base

    def _comment(self, records, target_counter, miss_counter):
        if len(records) < 3:
            return "履歴数が少ないため即修正せず、同じ傾向が複数レースで続くか確認してください。"
        if target_counter:
            target = target_counter.most_common(1)[0][0]
            return f"LearningDatabase上では {target} が改善対象として複数回出現しています。継続傾向か確認してください。"
        if miss_counter:
            miss = miss_counter.most_common(1)[0][0]
            return f"失敗パターンとして {miss} が見られます。原因の再確認を推奨します。"
        return "大きな失敗傾向はまだ明確ではありません。履歴を蓄積してください。"

    def _list(self, value):
        return value if isinstance(value, list) else []


if __name__ == "__main__":
    engine = LearningEngine()
    print(engine.analyze(learning_history=[]))
