"""Build human-readable race summaries without changing scores or decisions."""


class RaceSummaryEngine:
    """Summarize race structure, decisions, confidence, and risks."""

    def build(self, race_context=None, horses=None):
        """Return race_summary_result from existing race and horse outputs."""

        context = race_context if isinstance(race_context, dict) else {}
        rows = [horse for horse in horses if isinstance(horse, dict)] if isinstance(horses, list) else []

        top_horses = self._top_horses(rows)
        buy_horses = self._decision_horses(rows, "BUY")
        caution_horses = self._decision_horses(rows, "CAUTION")
        pass_horses = self._decision_horses(rows, "PASS")
        confidence_summary = self._confidence_summary(rows)
        risk_summary = self._risk_summary(context, rows)
        key_points = self._key_points(context, buy_horses, confidence_summary, risk_summary)
        short = self._short_summary(context, buy_horses, risk_summary)
        detail = self._detail_summary(context, buy_horses, caution_horses, pass_horses, risk_summary)

        return {
            "race_summary": short,
            "race_summary_short": short,
            "race_summary_detail": detail,
            "race_key_points": key_points,
            "race_top_horses": top_horses,
            "race_buy_horses": buy_horses,
            "race_caution_horses": caution_horses,
            "race_pass_horses": pass_horses,
            "race_confidence_summary": confidence_summary,
            "race_risk_summary": risk_summary,
        }

    def _top_horses(self, rows, limit=5):
        ranked = sorted(rows, key=self._rank_key)
        return [self._horse_view(row, fallback_rank=index) for index, row in enumerate(ranked[:limit], start=1)]

    def _decision_horses(self, rows, decision):
        ranked = sorted(rows, key=self._rank_key)
        return [
            self._horse_view(row, detailed=True, fallback_rank=index)
            for index, row in enumerate(ranked, start=1)
            if str(row.get("decision") or "").upper() == decision
        ]

    def _horse_view(self, row, detailed=False, fallback_rank=None):
        view = {
            "rank": row.get("final_rank") or fallback_rank,
            "horse_name": row.get("horse_name") or row.get("name") or "",
            "decision": row.get("decision") or "",
            "confidence_level": row.get("confidence_level") or "",
            "adjusted_score": row.get("adjusted_score"),
            "summary": row.get("final_summary") or row.get("explain_summary") or "",
        }
        if detailed:
            view.update(
                {
                    "decision_score": row.get("decision_score"),
                    "confidence_score": row.get("confidence_score"),
                    "decision_reason": row.get("decision_reason") or "",
                    "confidence_reason": row.get("confidence_reason") or "",
                }
            )
        return view

    def _confidence_summary(self, rows):
        counts = {"very_high": 0, "high": 0, "medium": 0, "low": 0, "very_low": 0, "unknown": 0}
        for row in rows:
            level = str(row.get("confidence_level") or "unknown").lower()
            if level not in counts:
                level = "unknown"
            counts[level] += 1

        high_count = counts["very_high"] + counts["high"]
        if high_count:
            comment = f"Confidence high以上の馬が{high_count}頭おり、評価の中心は比較的明確。"
        elif counts["medium"]:
            comment = "Confidenceはmedium中心で、評価可能だが過信は禁物。"
        else:
            comment = "Confidence情報が不足しており、レース全体は慎重評価。"

        return {
            "counts": counts,
            "comment": comment,
        }

    def _risk_summary(self, context, rows):
        risks = []
        self._extend_unique(risks, context.get("race_decision_risks"))
        if context.get("race_volatility") == "high":
            risks.append("race_volatility high")
        if context.get("race_complexity") == "high":
            risks.append("race_complexity high")

        for row in rows:
            self._extend_unique(risks, row.get("confidence_risks"))
            self._extend_unique(risks, row.get("final_risks"))
            self._extend_unique(risks, row.get("warnings"))
            self._extend_unique(risks, row.get("conflict_factors"))

        risks = self._unique(risks)
        if not rows:
            level = "unknown"
            comment = "評価対象馬が不足しているためリスク判定はunknown。"
        elif len(risks) >= max(8, len(rows)):
            level = "high"
            comment = "リスク要素が多く、レース全体は荒れやすさに注意。"
        elif len(risks) >= max(3, len(rows) // 3):
            level = "medium"
            comment = "評価可能だが、不確定要素も残る。"
        else:
            level = "low"
            comment = "目立つリスクは比較的少ない。"

        return {
            "risks": risks[:12],
            "risk_level": level,
            "risk_comment": comment,
        }

    def _key_points(self, context, buy_horses, confidence_summary, risk_summary):
        points = []
        self._extend_unique(points, context.get("key_factors"))

        race_decision = context.get("race_decision")
        if race_decision:
            points.append(f"RaceDecision {race_decision}")
        race_confidence = context.get("race_confidence")
        if race_confidence:
            points.append(f"RaceConfidence {race_confidence}")
        if buy_horses:
            points.append(f"BUY馬 {len(buy_horses)}頭")

        counts = confidence_summary.get("counts", {})
        high_count = counts.get("very_high", 0) + counts.get("high", 0)
        if high_count:
            points.append(f"Confidence高評価 {high_count}頭")
        if risk_summary.get("risk_level") != "low":
            points.append(risk_summary.get("risk_comment"))
        return self._unique(points)

    def _short_summary(self, context, buy_horses, risk_summary):
        race_decision = context.get("race_decision") or "CAUTION"
        race_confidence = context.get("race_confidence") or "unknown"
        buy_text = f"BUY馬は{len(buy_horses)}頭" if buy_horses else "BUY馬は不在"
        risk_text = risk_summary.get("risk_comment") or "リスク情報は限定的。"
        return f"RaceDecisionは{race_decision}、RaceConfidenceは{race_confidence}。{buy_text}で、{risk_text}"

    def _detail_summary(self, context, buy_horses, caution_horses, pass_horses, risk_summary):
        structure_comment = context.get("structure_comment") or "レース構造コメントは限定的。"
        key_factors = context.get("key_factors") or []
        factors_text = "、".join(str(value) for value in key_factors[:5]) if key_factors else "主要因は限定的"
        buy_names = "、".join(horse.get("horse_name", "") for horse in buy_horses[:5]) or "なし"
        return (
            f"{structure_comment} 重要要素は{factors_text}。"
            f" BUY={len(buy_horses)}頭（{buy_names}）、"
            f"CAUTION={len(caution_horses)}頭、PASS={len(pass_horses)}頭。"
            f" {risk_summary.get('risk_comment', '')}"
        )

    def _rank_key(self, row):
        rank = self._number_or_none(row.get("final_rank"))
        if rank is not None and rank > 0:
            return (0, rank)
        score = self._number_or_none(row.get("adjusted_score"))
        return (1, -(score or 0))

    def _number_or_none(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _extend_unique(self, destination, values):
        if values is None:
            return
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if value and value not in destination:
                destination.append(value)

    def _unique(self, values):
        unique = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique


if __name__ == "__main__":
    engine = RaceSummaryEngine()
    sample = [
        {"horse_name": "A", "final_rank": 1, "decision": "BUY", "confidence_level": "high", "adjusted_score": 120},
        {"horse_name": "B", "final_rank": 2, "decision": "CAUTION", "confidence_level": "medium", "adjusted_score": 100},
    ]
    print(engine.build({"race_decision": "PLAY", "race_confidence": "high"}, sample))
