"""Export KeibaAI trial results as a human-readable text report.

TrialReportExporter only formats existing race_output / final_outputs. It does
not change scores, decisions, confidence, self-check, rankings, or evaluator
results.
"""


class TrialReportExporter:
    """Create trial_report text and compact horse report rows."""

    def export(self, race_output=None, final_outputs=None):
        """Return trial_report_result from existing output dictionaries."""

        output = race_output if isinstance(race_output, dict) else {}
        horses = final_outputs if isinstance(final_outputs, list) else output.get("horses", [])
        if not isinstance(horses, list):
            horses = []

        report_summary = self._report_summary(output)
        report_horses = self._report_horses(horses)
        report = self._report_text(output, report_summary, report_horses)

        return {
            "trial_report": report,
            "trial_report_summary": report_summary,
            "trial_report_horses": report_horses,
        }

    def _report_summary(self, output):
        race_decision = output.get("race_decision") or "unknown"
        race_confidence = output.get("race_confidence") or "unknown"
        race_complexity = output.get("race_complexity") or "unknown"
        race_volatility = output.get("race_volatility") or "unknown"
        summary = output.get("race_summary_short") or output.get("race_summary") or "Race summary is unavailable."

        return (
            f"RaceDecision: {race_decision} / Confidence: {race_confidence} / "
            f"Complexity: {race_complexity} / Volatility: {race_volatility}\n"
            f"{summary}"
        )

    def _report_horses(self, horses):
        rows = []
        for fallback_rank, horse in enumerate(horses, start=1):
            if not isinstance(horse, dict):
                continue
            rows.append(
                {
                    "rank": horse.get("rank") or horse.get("final_rank") or fallback_rank,
                    "horse_name": horse.get("horse_name") or horse.get("name") or "unknown",
                    "decision": horse.get("decision") or "unknown",
                    "confidence_level": horse.get("confidence_level") or "unknown",
                    "adjusted_score": self._score_from_view(horse),
                    "consistency_level": self._consistency_level(horse),
                    "summary": horse.get("summary") or horse.get("final_summary") or "情報不足",
                    "strengths": self._list(horse.get("strengths") or horse.get("final_strengths")),
                    "risks": self._list(horse.get("risks") or horse.get("final_risks")),
                }
            )
        return rows

    def _report_text(self, output, report_summary, report_horses):
        lines = [
            "KeibaAI Trial Report",
            "=" * 24,
            "",
            "1. Race Summary",
            report_summary,
            "",
            "2. Race Detail",
            str(output.get("race_summary_detail") or "情報不足"),
            "",
            "3. Race Decision",
            f"Decision: {output.get('race_decision') or 'unknown'}",
            f"Score: {output.get('race_decision_score') if output.get('race_decision_score') is not None else 'unknown'}",
            f"Level: {output.get('race_decision_level') or 'unknown'}",
            f"Reason: {output.get('race_decision_reason') or '情報不足'}",
            "",
            "4. Race Risk",
            f"Confidence: {output.get('race_confidence') or 'unknown'}",
            f"Complexity: {output.get('race_complexity') or 'unknown'}",
            f"Volatility: {output.get('race_volatility') or 'unknown'}",
            self._risk_text(output.get("race_risk_summary")),
            "",
            "5. Self Check",
            f"Level: {output.get('self_check_level') or 'unknown'}",
            f"Passed: {output.get('self_check_passed')}",
            f"Comment: {output.get('self_check_comment') or '情報不足'}",
            self._warnings_text(output.get("self_check_warnings")),
            "",
            "6. Horse Ranking",
        ]

        for horse in report_horses:
            lines.extend(
                [
                    "",
                    f"{horse.get('rank')}位 {horse.get('horse_name')}",
                    f"Decision: {horse.get('decision')}",
                    f"Confidence: {horse.get('confidence_level')}",
                    f"AdjustedScore: {horse.get('adjusted_score')}",
                    f"Consistency: {horse.get('consistency_level')}",
                    f"Summary: {horse.get('summary')}",
                    f"Strengths: {self._join(horse.get('strengths'))}",
                    f"Risks: {self._join(horse.get('risks'))}",
                ]
            )
        return "\n".join(lines)

    def _risk_text(self, risk_summary):
        if not isinstance(risk_summary, dict):
            return "Risk: 情報不足"
        risks = risk_summary.get("risks")
        return (
            f"RiskLevel: {risk_summary.get('risk_level') or 'unknown'}\n"
            f"RiskComment: {risk_summary.get('risk_comment') or '情報不足'}\n"
            f"Risks: {self._join(risks)}"
        )

    def _warnings_text(self, warnings):
        return f"Warnings: {self._join(warnings)}"

    def _score_from_view(self, horse):
        view = horse.get("score_view")
        if isinstance(view, dict):
            for key in ["adjusted_score", "integrated_score", "weighted_score", "final_score"]:
                if view.get(key) is not None:
                    return view.get(key)
        return horse.get("adjusted_score")

    def _consistency_level(self, horse):
        view = horse.get("consistency_view")
        if isinstance(view, dict):
            return view.get("consistency_level") or "unknown"
        return horse.get("consistency_level") or "unknown"

    def _join(self, values):
        items = self._list(values)
        if not items:
            return "-"
        return "、".join(str(value) for value in items[:8] if value)

    def _list(self, value):
        return value if isinstance(value, list) else []


if __name__ == "__main__":
    exporter = TrialReportExporter()
    sample = {
        "race_decision": "PLAY",
        "race_confidence": "high",
        "race_summary_short": "Sample race summary.",
        "horses": [{"rank": 1, "horse_name": "A", "decision": "BUY", "confidence_level": "high"}],
    }
    print(exporter.export(sample)["trial_report"])
