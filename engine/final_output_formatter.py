"""Format final KeibaAI trial results for human review.

This formatter does not score, re-score, or adjust horses. It only gathers
existing scores, explanations, consistency, and decision results into a compact
final_output structure.
"""


class FinalOutputFormatter:
    """Create final_output and race_output from evaluated horse results."""

    SCORE_PRIORITY = [
        "adjusted_score",
        "integrated_score",
        "weighted_score",
        "final_score",
    ]

    SCORE_VIEW_KEYS = [
        "final_score",
        "weighted_score",
        "integrated_score",
        "impact_score",
        "adjusted_score",
    ]

    REASON_KEYS = [
        "explain_summary",
        "explanation",
        "consistency_summary",
        "consistency_explanation",
        "consistency_comment",
        "confidence_reason",
        "decision_reason",
        "impact_comment",
        "shape_comment",
        "course_shape_comment",
        "track_bias_comment",
        "lap_comment",
        "weight_comment",
    ]

    def format_race(self, horses=None, race_context=None):
        """Attach final_output to horses and return race_output."""

        rows = horses if isinstance(horses, list) else []
        context = race_context if isinstance(race_context, dict) else {}
        ranked = self._rank_horses(rows)

        final_outputs = []
        for rank, horse in enumerate(ranked, start=1):
            if not isinstance(horse, dict):
                continue
            output = self.format_horse(horse, rank)
            horse["final_rank"] = rank
            horse["final_summary"] = output.get("summary", "")
            horse["final_reasons"] = output.get("reasons", [])
            horse["final_strengths"] = output.get("strengths", [])
            horse["final_weaknesses"] = output.get("weaknesses", [])
            horse["final_risks"] = output.get("risks", [])
            horse["final_score_view"] = output.get("score_view", {})
            horse["final_output"] = output
            final_outputs.append(output)

        race_decision_result = context.get("race_decision_result")
        if not isinstance(race_decision_result, dict):
            race_decision_result = {}
        race_summary_result = context.get("race_summary_result")
        if not isinstance(race_summary_result, dict):
            race_summary_result = {}
        self_check_result = context.get("self_check_result")
        if not isinstance(self_check_result, dict):
            self_check_result = {}

        return {
            "race_structure": context.get("race_structure", {}),
            "structure_comment": context.get("structure_comment", ""),
            "key_factors": context.get("key_factors", []),
            "recommended_weights_hint": context.get("recommended_weights_hint", {}),
            "race_decision": race_decision_result.get("race_decision"),
            "race_decision_original": race_decision_result.get("race_decision_original"),
            "race_decision_final": race_decision_result.get("race_decision_final"),
            "race_decision_sync_applied": race_decision_result.get("race_decision_sync_applied"),
            "race_decision_sync_reason": race_decision_result.get("race_decision_sync_reason"),
            "race_decision_sync_final_buy_count": race_decision_result.get("race_decision_sync_final_buy_count"),
            "race_decision_sync_final_buy_horses": race_decision_result.get("race_decision_sync_final_buy_horses", []),
            "race_decision_sync_warnings": race_decision_result.get("race_decision_sync_warnings", []),
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
            "horses": final_outputs,
        }

    def format_horse(self, horse=None, rank=None):
        """Return a final_output dict for one horse."""

        item = horse if isinstance(horse, dict) else {}
        strengths = self._final_strengths(item)
        weaknesses = self._final_weaknesses(item)
        risks = self._final_risks(item)
        reasons = self._final_reasons(item)
        summary = self._final_summary(item, strengths, weaknesses, risks)

        decision_result = item.get("decision_result")
        if not isinstance(decision_result, dict):
            decision_result = {}

        return {
            "rank": rank,
            "horse_name": item.get("horse_name") or item.get("name") or "",
            "score_view": self._score_view(item),
            "consistency_view": self._consistency_view(item),
            "decision": item.get("decision") or "",
            "decision_score": item.get("decision_score"),
            "decision_level": item.get("decision_level") or "",
            "decision_reason": item.get("decision_reason") or "",
            "decision_factors": self._list(item.get("decision_factors")),
            "decision_risks": self._list(item.get("decision_risks")),
            "decision_result": decision_result,
            "confidence_score": item.get("confidence_score"),
            "confidence_level": item.get("confidence_level") or "",
            "confidence_reason": item.get("confidence_reason") or "",
            "confidence_factors": self._list(item.get("confidence_factors")),
            "confidence_risks": self._list(item.get("confidence_risks")),
            "confidence_result": item.get("confidence_result") if isinstance(item.get("confidence_result"), dict) else {},
            "summary": summary,
            "reasons": reasons,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "risks": risks,
            "confidence_reason": item.get("confidence_reason") or "",
        }

    def _rank_horses(self, horses):
        rows = [horse for horse in horses if isinstance(horse, dict)]
        return sorted(rows, key=self._rank_key, reverse=True)

    def _rank_key(self, horse):
        for index, key in enumerate(self.SCORE_PRIORITY):
            number = self._number_or_none(horse.get(key))
            if number is not None:
                return (len(self.SCORE_PRIORITY) - index, number)
        return (0, 0)

    def _score_view(self, item):
        view = {}
        for key in self.SCORE_VIEW_KEYS:
            if key in item and item.get(key) not in {None, ""}:
                view[key] = item.get(key)
        return view

    def _final_reasons(self, item):
        reasons = []
        for key in self.REASON_KEYS:
            self._append_unique(reasons, item.get(key))
        return reasons

    def _final_strengths(self, item):
        strengths = self._list(item.get("strengths"))
        for value in self._list(item.get("decision_factors")):
            strengths.append(value)
        for value in self._list(item.get("confidence_factors")):
            strengths.append(value)
        for factor in self._list(item.get("strong_matches")):
            label = self._consistency_strength_label(factor)
            if label:
                strengths.append(label)
        if strengths:
            return self._unique(strengths)

        guessed = []
        self._guess_from_comment(guessed, item.get("shape_comment"), "展開適性")
        self._guess_from_comment(guessed, item.get("course_shape_comment"), "コース形状適性")
        self._guess_from_comment(guessed, item.get("lap_comment"), "ラップ適性")
        if self._number(item.get("distance_score")) > 0:
            guessed.append("距離適性")
        if self._number(item.get("bloodline_score")) > 0:
            guessed.append("血統適性")
        if self._number(item.get("track_condition_score")) > 0:
            guessed.append("馬場適性")
        return self._unique(guessed)

    def _final_weaknesses(self, item):
        weaknesses = self._list(item.get("weaknesses"))
        for factor in self._list(item.get("conflict_factors")):
            label = self._consistency_weakness_label(factor)
            if label:
                weaknesses.append(label)
        for warning in self._list(item.get("warnings")):
            text = str(warning)
            if "unknown" in text or "missing" in text:
                weaknesses.append(text)
        for key in ["shape_comment", "course_shape_comment", "track_bias_comment", "lap_comment"]:
            text = str(item.get(key) or "")
            if "不向き" in text or "不足" in text or "不安" in text:
                weaknesses.append(text)
        return self._unique(weaknesses)

    def _final_risks(self, item):
        risks = self._list(item.get("risk_factors"))
        risks.extend(self._list(item.get("decision_risks")))
        risks.extend(self._list(item.get("confidence_risks")))
        level = str(item.get("consistency_level") or "").lower()
        if level in {"low", "conflict"}:
            risks.append("構造一致度が低い")
        for factor in self._list(item.get("conflict_factors")):
            label = self._consistency_weakness_label(factor)
            if label:
                risks.append(label)
        for warning in self._list(item.get("warnings")):
            risks.append(str(warning))
        if not item.get("track_bias_comment"):
            risks.append("当日バイアス情報が不足")
        if item.get("pace_style") == "unknown":
            risks.append("脚質不明")
        if item.get("lap_style") == "unknown":
            risks.append("ラップ情報不足")
        if item.get("track_condition_fit") == "unknown":
            risks.append("馬場適性情報不足")
        return self._unique(risks)

    def _final_summary(self, item, strengths, weaknesses, risks):
        base = item.get("explain_summary")
        if base:
            summary = str(base)
        elif strengths and not weaknesses:
            summary = "評価材料がそろっており、総合的に前向きに評価できる。"
        elif strengths and weaknesses:
            summary = "評価材料はあるが、不安要素も残るため過信は禁物。"
        elif weaknesses:
            summary = "不安材料が目立つため、慎重な評価が必要。"
        else:
            summary = "取得できた材料では中立寄りの評価。"

        decision = item.get("decision")
        if decision and f"DecisionEngineでは{decision}" not in summary:
            summary = f"{summary} DecisionEngineでは{decision}判断。"

        if risks and "過信" not in summary and len(summary) < 80:
            summary = f"{summary} リスク要素も確認したい。"
        consistency_summary = item.get("consistency_summary")
        has_structure_match = "構造" in summary and "一致" in summary
        if consistency_summary and str(consistency_summary) not in summary and not has_structure_match:
            summary = f"{summary} {consistency_summary}。"
        return summary

    def _consistency_view(self, item):
        result = item.get("consistency_result")
        if not isinstance(result, dict):
            result = {}
        view = {}
        for key in [
            "consistency_score",
            "consistency_level",
            "strong_matches",
            "weak_matches",
            "conflict_factors",
        ]:
            value = result.get(key, item.get(key))
            if value is not None and value != "":
                view[key] = value
        summary = item.get("consistency_summary")
        if summary:
            view["summary"] = summary
        return view

    def _consistency_strength_label(self, factor):
        mapping = {
            "course_shape": "コース形状との一致",
            "shape": "展開・位置取りとの一致",
            "pace": "展開・位置取りとの一致",
            "positioning": "展開・位置取りとの一致",
            "distance": "距離適性との一致",
            "bloodline": "血統適性との一致",
            "lap": "ラップ適性との一致",
            "track_bias": "馬場バイアスとの一致",
            "past": "近走内容との一致",
        }
        return mapping.get(str(factor))

    def _consistency_weakness_label(self, factor):
        mapping = {
            "course_shape": "コース形状とのズレ",
            "shape": "展開面の不安",
            "pace": "展開面の不安",
            "positioning": "展開面の不安",
            "distance": "距離適性の不安",
            "bloodline": "血統面のズレ",
            "lap": "ラップ適性の不安",
            "track_bias": "馬場バイアスとのズレ",
            "past": "近走内容との不安",
        }
        return mapping.get(str(factor))

    def _guess_from_comment(self, destination, comment, label):
        text = str(comment or "")
        if not text:
            return
        if "向く" in text or "評価" in text or "加点" in text or "一致" in text:
            destination.append(label)

    def _append_unique(self, destination, value):
        if value is None:
            return
        if isinstance(value, list):
            for item in value:
                self._append_unique(destination, item)
            return
        text = str(value).strip()
        if text and text not in destination:
            destination.append(text)

    def _unique(self, values):
        unique = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _number(self, value):
        number = self._number_or_none(value)
        return number if number is not None else 0

    def _number_or_none(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


if __name__ == "__main__":
    formatter = FinalOutputFormatter()
    sample_horses = [
        {
            "horse_name": "sample_a",
            "final_score": 100,
            "weighted_score": 110,
            "integrated_score": 110,
            "impact_score": 10,
            "adjusted_score": 120,
            "explain_summary": "構造との一致率が高く、展開利が見込める。",
            "strengths": ["先行力", "距離適性"],
            "risk_factors": ["当日バイアス情報が限定的"],
            "decision": "BUY",
            "decision_score": 0.86,
            "decision_level": "buy",
            "decision_reason": "構造一致度と評価材料のバランスが良い。",
        }
    ]
    print(formatter.format_race(sample_horses))
