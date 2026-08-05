"""Export KeibaAI trial results as a human-readable text report.

TrialReportExporter only formats existing race_output and horse evaluation
results. It does not change scores, decisions, confidence, rankings, or any
Evaluator calculation.
"""


class TrialReportExporter:
    """Create detailed trial_report text and compact horse report rows."""

    EVALUATOR_DEFINITIONS = [
        {
            "name": "Bloodline",
            "score_key": "bloodline_score",
            "result_key": "bloodline_result",
            "comment_keys": ["sections.bloodline"],
        },
        {
            "name": "PastPerformance",
            "score_key": "past_performance_score",
            "result_key": "past_performance_result",
            "comment_keys": [],
        },
        {
            "name": "PaceStyle",
            "score_key": "pace_style_score",
            "result_key": "pace_style_result",
            "comment_keys": ["pace_style_label"],
        },
        {
            "name": "Distance",
            "score_key": "distance_score",
            "result_key": "distance_result",
            "comment_keys": ["distance_fit_label"],
        },
        {
            "name": "TrackCondition",
            "score_key": "track_condition_score",
            "result_key": "track_condition_suitability_result",
            "comment_keys": ["track_condition_fit_label"],
        },
        {
            "name": "RaceShape",
            "score_key": "shape_score",
            "result_key": "shape_result",
            "comment_keys": ["shape_comment"],
        },
        {
            "name": "CourseShape",
            "score_key": "course_shape_score",
            "result_key": "course_shape_result",
            "comment_keys": ["course_shape_comment"],
        },
        {
            "name": "TrackBias",
            "score_key": "track_bias_score",
            "result_key": "track_bias_result",
            "comment_keys": ["track_bias_comment"],
        },
        {
            "name": "MeetingBias",
            "score_key": "meeting_bias_score",
            "result_key": "meeting_bias_result",
            "comment_keys": ["meeting_bias_comment"],
        },
        {
            "name": "Lap",
            "score_key": "lap_score",
            "result_key": "lap_result",
            "comment_keys": ["lap_style", "lap_comment"],
        },
        {
            "name": "ScoreWeight",
            "score_key": "weighted_score",
            "result_key": "weight_result",
            "comment_keys": ["weight_source", "weight_comment"],
        },
        {
            "name": "Impact",
            "score_key": "impact_score",
            "result_key": "impact_result",
            "comment_keys": ["impact_comment"],
        },
    ]

    def export(self, race_output=None, final_outputs=None):
        """Return trial_report_result from existing output dictionaries."""

        output = race_output if isinstance(race_output, dict) else {}
        horses = final_outputs if isinstance(final_outputs, list) else output.get("horses", [])
        if not isinstance(horses, list):
            horses = []

        report_summary = self._report_summary(output, horses)
        report_horses = self._report_horses(horses)
        report = self._report_text(output, report_summary, report_horses)

        return {
            "trial_report": report,
            "trial_report_summary": report_summary,
            "trial_report_horses": report_horses,
        }

    def _report_summary(self, output, horses):
        race_decision = output.get("race_decision") or "unknown"
        race_confidence = output.get("race_confidence") or "unknown"
        race_complexity = output.get("race_complexity") or "unknown"
        race_volatility = output.get("race_volatility") or "unknown"
        summary = (
            output.get("race_summary_short")
            or output.get("race_summary")
            or "Race summary is unavailable."
        )
        top3 = self._top_horse_names(horses, 3)
        buy_horses = self._decision_horse_names(horses, "BUY")

        return (
            f"RaceDecision: {race_decision} / Confidence: {race_confidence} / "
            f"Complexity: {race_complexity} / Volatility: {race_volatility}\n"
            f"{summary}\n"
            f"Top3: {self._join(top3)}\n"
            f"BUY候補: {self._join(buy_horses)}"
        )

    def _report_horses(self, horses):
        rows = []
        for fallback_rank, horse in enumerate(horses, start=1):
            if not isinstance(horse, dict):
                continue
            rows.append(
                {
                    "rank": horse.get("rank") or horse.get("final_rank") or fallback_rank,
                    "horse_name": self._horse_name(horse),
                    "decision": horse.get("decision") or "unknown",
                    "decision_reason": horse.get("decision_reason") or "",
                    "confidence_level": horse.get("confidence_level") or "unknown",
                    "confidence_reason": horse.get("confidence_reason") or "",
                    "final_score": horse.get("final_score"),
                    "adjusted_score": self._score_from_view(horse),
                    "evaluator_details": self._evaluator_details(horse),
                    "warnings": self._list(horse.get("warnings")),
                    "summary": self._summary(horse),
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
            f"Score: {self._value_or_unknown(output.get('race_decision_score'))}",
            f"Level: {output.get('race_decision_level') or 'unknown'}",
            f"Reason: {output.get('race_decision_reason') or '情報不足'}",
            "",
            "4. Race Risk / Confidence",
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
            "6. Race Summary Points",
            f"上位3頭: {self._join([row.get('horse_name') for row in report_horses[:3]])}",
            f"BUY候補: {self._join([row.get('horse_name') for row in report_horses if row.get('decision') == 'BUY'])}",
            "PASS理由:",
        ]

        pass_rows = [row for row in report_horses if row.get("decision") == "PASS"]
        if pass_rows:
            for row in pass_rows[:5]:
                lines.append(
                    f"- {row.get('horse_name')}: {row.get('decision_reason') or self._join(row.get('warnings'))}"
                )
        else:
            lines.append("- PASS対象なし")

        lines.extend(
            [
                "Confidence理由:",
                self._confidence_reason_summary(report_horses),
                "",
                "7. Horse Details",
            ]
        )

        for horse in report_horses:
            lines.extend(
                [
                    "",
                    f"Rank {horse.get('rank')}: {horse.get('horse_name')}",
                    f"Decision: {horse.get('decision')}",
                    f"DecisionReason: {horse.get('decision_reason') or '-'}",
                    f"Confidence: {horse.get('confidence_level')}",
                    f"ConfidenceReason: {horse.get('confidence_reason') or '-'}",
                    f"FinalScore: {self._value_or_unknown(horse.get('final_score'))}",
                    f"AdjustedScore: {self._value_or_unknown(horse.get('adjusted_score'))}",
                    f"Summary: {horse.get('summary')}",
                    f"Warnings: {self._join(horse.get('warnings'))}",
                    "Evaluator Scores / Explain:",
                ]
            )
            for detail in horse.get("evaluator_details", []):
                lines.append(f"- {detail.get('name')}: {self._value_or_unknown(detail.get('score'))}")
                for text in detail.get("explains", []):
                    lines.append(f"  {text}")
        return "\n".join(lines)

    def _evaluator_details(self, horse):
        details = []
        for definition in self.EVALUATOR_DEFINITIONS:
            explains = self._definition_explains(horse, definition)
            if not explains:
                explains = self._fallback_explains(horse, definition)
            details.append(
                {
                    "name": definition.get("name"),
                    "score": horse.get(definition.get("score_key")),
                    "explains": explains[:3],
                }
            )
        return details

    def _definition_explains(self, horse, definition):
        texts = []
        for key in definition.get("comment_keys", []):
            self._append_texts(texts, self._nested_value(horse, key))
        result = horse.get(definition.get("result_key"))
        if isinstance(result, dict):
            self._append_texts(texts, result.get("explain"))
            self._append_texts(texts, result.get("Explain"))
            self._append_texts(texts, result.get("comment"))
            self._append_texts(texts, result.get("reason"))
            summary = result.get("summary")
            if isinstance(summary, dict):
                for explain in summary.get("explains", []):
                    if isinstance(explain, dict):
                        self._append_texts(texts, explain.get("explain"))
                    else:
                        self._append_texts(texts, explain)
                for reason in summary.get("reasons", []):
                    if isinstance(reason, dict):
                        self._append_texts(texts, reason.get("reason"))
                    else:
                        self._append_texts(texts, reason)
        return self._unique(texts)

    def _fallback_explains(self, horse, definition):
        name = definition.get("name")
        score = self._number(horse.get(definition.get("score_key")))
        if name == "Bloodline":
            sire = horse.get("sire")
            broodmare_sire = horse.get("broodmare_sire")
            texts = []
            if sire:
                texts.append(f"父{sire}の血統Profileを評価。")
            if broodmare_sire:
                texts.append(f"母父{broodmare_sire}の補正を評価。")
            if not texts:
                texts.append("血統情報またはProfileが不足。")
            return texts
        if name == "PastPerformance":
            count = horse.get("history_count")
            return [f"近走{count}走をもとに着順・着差・上がり・PCI/RPCIを評価。"]
        if name == "PaceStyle":
            return [f"通過順から脚質を{horse.get('pace_style') or 'unknown'}と判定。"]
        if name == "Distance":
            return [f"今回距離{horse.get('distance') or 'unknown'}mとの近走距離適性を評価。"]
        if name == "TrackCondition":
            return [f"今回馬場{horse.get('track_condition') or 'unknown'}への適性を評価。"]
        if name == "RaceShape":
            return ["予測ペースと脚質の噛み合わせを評価。"]
        if name == "CourseShape":
            return ["コース形状・脚質・枠順の噛み合わせを評価。"]
        if name == "TrackBias":
            return ["当日バイアス情報が不足する場合は中立評価。"]
        if name == "Lap":
            return [f"ラップ適性を{horse.get('lap_style') or 'unknown'}として評価。"]
        if name == "ScoreWeight":
            return ["RaceStructureEngineの重みヒントと既存スコアを整理。"]
        if name == "Impact":
            return ["展開影響による最終補正を表示。"]
        if score == 0:
            return ["評価材料不足または中立評価。"]
        return ["既存Evaluatorの結果を表示。"]

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
        view = horse.get("score_view") or horse.get("final_score_view")
        if isinstance(view, dict):
            for key in ["adjusted_score", "integrated_score", "weighted_score", "final_score"]:
                if view.get(key) is not None:
                    return view.get(key)
        return horse.get("adjusted_score")

    def _summary(self, horse):
        return (
            horse.get("summary")
            or horse.get("final_summary")
            or horse.get("explain_summary")
            or "情報不足"
        )

    def _confidence_reason_summary(self, rows):
        reasons = []
        for row in rows:
            reason = row.get("confidence_reason")
            if reason:
                reasons.append(f"{row.get('horse_name')}: {reason}")
        return "\n".join(reasons[:5]) if reasons else "Confidence理由は未取得"

    def _top_horse_names(self, horses, limit):
        names = []
        for horse in horses[:limit]:
            if isinstance(horse, dict):
                names.append(self._horse_name(horse))
        return names

    def _decision_horse_names(self, horses, decision):
        names = []
        for horse in horses:
            if isinstance(horse, dict) and horse.get("decision") == decision:
                names.append(self._horse_name(horse))
        return names

    def _horse_name(self, horse):
        return horse.get("horse_name") or horse.get("name") or "unknown"

    def _nested_value(self, data, dotted_key):
        value = data
        for part in str(dotted_key).split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value

    def _append_texts(self, target, value):
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                target.append(text)
            return
        if isinstance(value, dict):
            for key in ["explain", "Explain", "reason", "comment", "summary"]:
                self._append_texts(target, value.get(key))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                self._append_texts(target, item)

    def _value_or_unknown(self, value):
        return value if value not in {None, ""} else "unknown"

    def _number(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _join(self, values):
        items = self._list(values)
        if not items:
            return "-"
        return "、".join(str(value) for value in items[:8] if value)

    def _list(self, value):
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if value is None or value == "":
            return []
        return [value]

    def _unique(self, values):
        seen = set()
        unique_values = []
        for value in values:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            unique_values.append(text)
        return unique_values


if __name__ == "__main__":
    exporter = TrialReportExporter()
    sample = {
        "race_decision": "PLAY",
        "race_confidence": "high",
        "race_summary_short": "Sample race summary.",
    }
    horses = [
        {
            "horse_name": "A",
            "decision": "BUY",
            "confidence_level": "high",
            "final_score": 100,
            "adjusted_score": 110,
            "bloodline_score": 12,
            "sire": "キズナ",
        }
    ]
    print(exporter.export(sample, horses)["trial_report"])
