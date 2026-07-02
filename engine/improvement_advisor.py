"""Create improvement suggestions from ReviewEngine output.

ImprovementAdvisor does not learn, re-score, or auto-correct anything. It only
turns review_result misses into human-readable improvement targets.
"""


class ImprovementAdvisor:
    """Suggest which evaluation areas should be checked after a review."""

    MISS_RULES = [
        (
            ("TopHorse",),
            ["DecisionEngine", "ConfidenceEngine", "ScoreWeightEvaluator", "PastPerformanceEvaluator"],
            "Top評価馬が凡走したため、最上位判断・Confidence・重み付け・近走評価の根拠を確認してください。",
        ),
        (
            ("BUY",),
            ["DecisionEngine", "ConfidenceEngine", "RaceShapeEvaluator", "CourseShapeEvaluator", "TrackBiasEvaluator"],
            "BUY馬が結果に結びつかなかったため、BUY条件と展開・コース構造・当日バイアス評価を確認してください。",
        ),
        (
            ("PASS",),
            ["DecisionEngine", "ConsistencyEngine", "ScoreWeightEvaluator", "PastPerformanceEvaluator"],
            "PASS馬が好走したため、過小評価されたEvaluatorと整合性判定を確認してください。",
        ),
        (
            ("Confidence",),
            ["ConfidenceEngine", "ConsistencyEngine", "ScoreWeightEvaluator"],
            "Confidenceの過大評価が疑われるため、risk_factorsとconflict_factorsの減点反映を確認してください。",
        ),
        (
            ("RaceDecision",),
            ["RaceDecisionEngine", "RaceSummaryEngine", "SelfCheckEngine"],
            "RaceDecisionが過信寄りだったため、レース全体判断とSelfCheckの警告条件を確認してください。",
        ),
        (
            ("展開", "ズレ"),
            ["RacePacePredictor", "RaceShapeEvaluator", "PaceStyleEvaluator"],
            "展開評価のズレが疑われるため、脚質集計・ペース予測・展開利判定を確認してください。",
        ),
        (
            ("距離", "ズレ"),
            ["DistanceSuitabilityEvaluator"],
            "距離評価のズレが疑われるため、同距離・近似距離実績の扱いを確認してください。",
        ),
        (
            ("馬場", "ズレ"),
            ["TrackConditionSuitabilityEvaluator", "TrackBiasEvaluator"],
            "馬場評価のズレが疑われるため、当日馬場と過去馬場適性の扱いを確認してください。",
        ),
        (
            ("ラップ", "ズレ"),
            ["LapSuitabilityEvaluator"],
            "ラップ評価のズレが疑われるため、瞬発戦・持続戦・消耗戦の判定を確認してください。",
        ),
        (
            ("血統", "ズレ"),
            ["BloodlineEvaluator"],
            "血統評価のズレが疑われるため、血統適性の参照内容を確認してください。",
        ),
        (
            ("相手関係", "ズレ"),
            ["PastPerformanceEvaluator", "ClassEvaluator"],
            "相手関係評価のズレが疑われるため、近走クラスと相手レベルの扱いを確認してください。",
        ),
    ]

    def advise(self, review_result=None):
        """Return improvement_result from review_result only."""

        result = review_result if isinstance(review_result, dict) else {}
        level = result.get("review_level") or "pending"
        score = result.get("review_score")

        if level == "pending" or score is None:
            return self._pending()

        misses = self._list(result.get("review_misses"))
        hits = self._list(result.get("review_hits"))
        targets = []
        suggestions = []

        for miss in misses:
            self._apply_rules(str(miss), targets, suggestions)

        if not misses:
            suggestions.append("大きなズレは少ないため、現行評価を維持しつつ複数レースで再確認してください。")
        if hits:
            suggestions.append("的中した評価要素も保持し、同条件で再現性を確認してください。")

        targets = self._unique(targets)
        suggestions = self._unique(suggestions)
        priority = self._priority(level)

        return {
            "improvement_priority": priority,
            "improvement_summary": self._summary(priority, misses),
            "improvement_suggestions": suggestions,
            "improvement_targets": targets,
            "improvement_comment": self._comment(level),
        }

    def _pending(self):
        return {
            "improvement_priority": "pending",
            "improvement_summary": "結果未入力のため改善提案は保留",
            "improvement_suggestions": [],
            "improvement_targets": [],
            "improvement_comment": "レース結果が入力された後に改善候補を生成します。",
        }

    def _apply_rules(self, miss_text, targets, suggestions):
        matched = False
        for keywords, rule_targets, suggestion in self.MISS_RULES:
            if all(keyword in miss_text for keyword in keywords):
                targets.extend(rule_targets)
                suggestions.append(suggestion)
                matched = True
        if not matched:
            targets.append("ReviewEngine")
            suggestions.append(f"未分類のズレ「{miss_text}」を確認してください。")

    def _priority(self, review_level):
        if review_level in {"bad", "poor"}:
            return "high"
        if review_level == "normal":
            return "medium"
        if review_level in {"good", "excellent"}:
            return "low"
        return "pending"

    def _summary(self, priority, misses):
        if priority == "pending":
            return "結果未入力のため改善提案は保留"
        if not misses:
            return "大きなズレは少なく、改善優先度は低めです。"
        if priority == "high":
            return "大きなズレがあるため、評価条件の確認が必要です。"
        if priority == "medium":
            return "一部ズレがあるため、対象Evaluatorの確認を推奨します。"
        return "概ね良好ですが、軽微な改善候補を確認してください。"

    def _comment(self, review_level):
        if review_level in {"bad", "poor"}:
            return "今回のレビューでは外れた評価が目立つため、自動修正ではなく複数レースで同じ傾向が出るか確認してください。"
        if review_level == "normal":
            return "当たった評価と外れた評価が混在しているため、miss内容ごとに分解して確認してください。"
        if review_level in {"good", "excellent"}:
            return "現行評価は概ね機能しています。改善する場合も小さく検証してください。"
        return "結果入力後に改善コメントを生成します。"

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _unique(self, values):
        unique = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique


if __name__ == "__main__":
    advisor = ImprovementAdvisor()
    print(advisor.advise({"review_level": "pending", "review_score": None}))
    print(
        advisor.advise(
            {
                "review_level": "bad",
                "review_score": 0.1,
                "review_misses": ["TopHorse凡走", "BUY馬全滅", "Confidence過大評価"],
            }
        )
    )
