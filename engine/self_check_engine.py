"""Final self-check layer for KeibaAI race outputs.

SelfCheckEngine audits existing decisions, confidence, explanations, and race
summaries. It does not change scores, decisions, summaries, or rankings.
"""


class SelfCheckEngine:
    """Detect contradictions and missing explanation data in final outputs."""

    def check(self, race_context=None, horses=None):
        """Return self_check_result for a race without mutating inputs."""

        context = race_context if isinstance(race_context, dict) else {}
        rows = [horse for horse in horses if isinstance(horse, dict)] if isinstance(horses, list) else []

        warnings = []
        self._check_horses(rows, warnings)
        self._check_race(context, rows, warnings)

        score = max(0, min(1, round(1 - (len(warnings) * 0.08), 2)))
        level = self._level(score)
        passed = score >= 0.7 and not self._has_critical_warning(warnings)
        comment = self._comment(level, warnings, passed)

        return {
            "self_check_score": score,
            "self_check_level": level,
            "self_check_comment": comment,
            "self_check_warnings": warnings,
            "self_check_passed": passed,
        }

    def _check_horses(self, rows, warnings):
        if not rows:
            warnings.append("評価対象馬がありません")
            return

        ranked = sorted(rows, key=self._rank_key)
        top = ranked[0] if ranked else {}
        if str(top.get("decision") or "").upper() == "PASS":
            warnings.append("TopHorseがPASS判定です")

        for row in rows:
            name = row.get("horse_name") or row.get("name") or "unknown"
            decision = str(row.get("decision") or "").upper()
            confidence_level = str(row.get("confidence_level") or "").lower()
            consistency_level = str(row.get("consistency_level") or "").lower()
            risks = self._list(row.get("final_risks")) or self._list(row.get("risk_factors"))
            risks += self._list(row.get("decision_risks"))
            risks += self._list(row.get("confidence_risks"))
            warnings_list = self._list(row.get("warnings"))
            conflicts = self._list(row.get("conflict_factors"))
            reason = str(row.get("decision_reason") or row.get("explanation") or "")
            summary = str(row.get("final_summary") or row.get("explain_summary") or "")
            strengths = self._list(row.get("final_strengths")) or self._list(row.get("strengths"))

            if decision == "BUY" and len(self._unique(risks + warnings_list + conflicts)) >= 5:
                warnings.append(f"BUYなのにRisk多数: {name}")
            if decision == "BUY" and confidence_level in {"low", "very_low"}:
                warnings.append(f"BUYなのにConfidence低: {name}")
            if decision == "BUY" and consistency_level in {"low", "conflict"}:
                warnings.append(f"BUYなのにConsistency低: {name}")
            if decision == "PASS" and confidence_level == "very_high":
                warnings.append(f"PASSなのにConfidence very_high: {name}")
            if len(reason.strip()) < 12:
                warnings.append(f"説明reasonが短い: {name}")
            if not summary.strip():
                warnings.append(f"Summaryが空: {name}")
            if not strengths:
                warnings.append(f"Strengthが空: {name}")
            if not risks and not warnings_list and not conflicts:
                warnings.append(f"Riskが空: {name}")

    def _check_race(self, context, rows, warnings):
        buy_count = sum(1 for row in rows if str(row.get("decision") or "").upper() == "BUY")
        pass_count = sum(1 for row in rows if str(row.get("decision") or "").upper() == "PASS")
        race_decision = str(context.get("race_decision") or "").upper()
        race_confidence = str(context.get("race_confidence") or "").lower()
        summary = str(context.get("race_summary") or context.get("race_summary_short") or "")
        confidence_summary = context.get("race_confidence_summary")

        if race_decision == "PLAY" and buy_count == 0:
            warnings.append("RaceDecisionがPLAYなのにBUY馬ゼロ")
        if race_decision == "PASS" and buy_count >= 2:
            warnings.append("RaceDecisionがPASSなのにBUY馬が複数")
        if buy_count == 0:
            warnings.append("BUY馬ゼロ")
        if rows and pass_count == len(rows):
            warnings.append("PASS馬だけです")
        if race_confidence == "high" and isinstance(confidence_summary, dict):
            counts = confidence_summary.get("counts", {})
            high_count = counts.get("very_high", 0) + counts.get("high", 0)
            if high_count == 0:
                warnings.append("RaceConfidence highなのに高Confidence馬がいません")
        if race_confidence == "low" and isinstance(confidence_summary, dict):
            counts = confidence_summary.get("counts", {})
            high_count = counts.get("very_high", 0) + counts.get("high", 0)
            if high_count >= 2:
                warnings.append("RaceConfidence lowなのに高Confidence馬が複数います")
        if not summary.strip():
            warnings.append("RaceSummary不足")

    def _level(self, score):
        if score >= 0.9:
            return "excellent"
        if score >= 0.75:
            return "good"
        if score >= 0.55:
            return "fair"
        return "poor"

    def _comment(self, level, warnings, passed):
        if passed and not warnings:
            return "大きな矛盾は検出されませんでした。"
        if passed:
            return "軽微な注意点はありますが、自己チェックは通過しました。"
        if level == "fair":
            return "評価は利用可能ですが、いくつかの説明不足や矛盾候補があります。"
        return "危険な評価、説明不足、または判定矛盾が検出されました。"

    def _has_critical_warning(self, warnings):
        critical_words = [
            "BUYなのにConfidence低",
            "BUYなのにConsistency低",
            "RaceDecisionがPLAYなのにBUY馬ゼロ",
            "PASS馬だけ",
            "TopHorseがPASS",
        ]
        return any(any(word in warning for word in critical_words) for warning in warnings)

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

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _unique(self, values):
        unique = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique


if __name__ == "__main__":
    engine = SelfCheckEngine()
    sample_horses = [
        {
            "horse_name": "A",
            "decision": "BUY",
            "confidence_level": "high",
            "consistency_level": "high",
            "decision_reason": "理由は十分にあります。",
            "final_summary": "評価理由あり。",
            "final_strengths": ["構造一致"],
        }
    ]
    print(engine.check({"race_decision": "PLAY", "race_summary": "sample"}, sample_horses))
