"""Create final BUY / CAUTION / PASS labels without changing scores.

DecisionEngine is a final interpretation layer. It reads existing scores,
consistency, explanation, risk, and warning data, then returns a decision label
for review. It never changes final_score, weighted_score, integrated_score,
adjusted_score, score_weights, or any evaluator result.
"""

from engine.decision_guard import DecisionGuard


class DecisionEngine:
    """Judge BUY / CAUTION / PASS from existing evaluation output."""

    def __init__(
        self,
        enable_past_performance_quality_guard=False,
        enable_multi_evaluator_consensus_guard=False,
    ):
        self.decision_guard = DecisionGuard(
            enable_past_performance_quality_guard=enable_past_performance_quality_guard,
            enable_multi_evaluator_consensus_guard=enable_multi_evaluator_consensus_guard,
        )

    MAJOR_RISK_KEYWORDS = [
        "構造一致度が低い",
        "脚質不明",
        "ラップ情報不足",
        "馬場適性情報不足",
        "距離適性の不安",
        "展開面の不安",
        "ズレ",
        "不向き",
        "不足",
    ]

    INFORMATIONAL_RISK_EXCLUDED_FROM_MAJOR_COUNT = {
        "当日バイアス情報が限定的",
    }

    def decide(self, horse=None, rank_context=None):
        """Return decision_result for one horse."""

        item = horse if isinstance(horse, dict) else {}
        context = rank_context if isinstance(rank_context, dict) else {}

        score = self._base_score(item, context)
        factors = []
        risks = []

        score = self._apply_consistency(item, score, factors, risks)
        score = self._apply_strengths_and_risks(item, score, factors, risks)
        score = self._apply_impact(item, score, factors, risks)
        score = self._apply_warnings(item, score, risks)
        score = self._apply_summary_flags(item, score, factors, risks)
        score = max(0, min(1, round(score, 2)))

        decision = self._decision(score, item, risks)
        safety = self._track_bias_buy_safety(item, context, score, decision)
        if safety.get("buy_suppressed"):
            decision = "CAUTION"
            risks.append(safety.get("buy_suppression_reason"))
        rescue = self._top_score_pass_rescue(item, context, score, decision)
        if rescue.get("top_score_pass_rescued"):
            decision = "CAUTION"
            factors.append(rescue.get("top_score_pass_rescue_reason"))
        guard_item = dict(item)
        guard_item["decision_risks"] = list(risks)
        guard_item["decision_factors"] = list(factors)
        guard_result = self.decision_guard.apply(guard_item, context, decision, score)
        quality_guard = guard_result.get("past_performance_quality_guard", {})
        if quality_guard.get("quality_guard_applied"):
            decision = guard_result.get("decision", "CAUTION")
            factors.append(quality_guard.get("guard_reason"))
        consensus_guard = guard_result.get("multi_evaluator_consensus_guard", {})
        if consensus_guard.get("consensus_guard_applied"):
            decision = guard_result.get("decision", decision)
            factors.append(consensus_guard.get("consensus_guard_reason"))
        low_rank_guard = guard_result.get("low_rank_buy_guard", {})
        if low_rank_guard.get("low_rank_buy_guard_applied"):
            decision = guard_result.get("decision", "CAUTION")
            risks.append(low_rank_guard.get("guard_reason"))
        level = self._decision_level(score, decision)
        reason = self._decision_reason(decision, factors, risks)
        diagnostics = self._decision_diagnostics(
            item=item,
            context=context,
            score=score,
            decision=decision,
            level=level,
            factors=factors,
            risks=risks,
            safety=safety,
            rescue=rescue,
            quality_guard=quality_guard,
            consensus_guard=consensus_guard,
            low_rank_guard=low_rank_guard,
        )

        return {
            "decision": decision,
            "decision_score": score,
            "decision_level": level,
            "decision_reason": reason,
            "decision_factors": self._unique(factors),
            "decision_risks": self._unique(risks),
            "baseline_available": safety.get("baseline_available", False),
            "track_bias_sensitive_buy": safety.get("track_bias_sensitive_buy", False),
            "track_bias_only_buy": safety.get("track_bias_only_buy", False),
            "buy_suppressed": safety.get("buy_suppressed", False),
            "buy_suppression_reason": safety.get("buy_suppression_reason", ""),
            "guard_skipped_reason": safety.get("guard_skipped_reason", ""),
            "top_score_pass_rescued": rescue.get("top_score_pass_rescued", False),
            "top_score_pass_rescue_reason": rescue.get("top_score_pass_rescue_reason", ""),
            "top_score_pass_rescue_skipped_reason": rescue.get("top_score_pass_rescue_skipped_reason", ""),
            "quality_guard_applied": quality_guard.get("quality_guard_applied", False),
            "quality_guard_name": quality_guard.get("quality_guard_name", ""),
            "quality_guard_candidate": quality_guard.get("quality_guard_candidate", False),
            "quality_guard_skipped_reason": quality_guard.get("quality_guard_skipped_reason", ""),
            "quality_guard_reason": quality_guard.get("guard_reason", ""),
            "quality_guard_original_decision": quality_guard.get("original_decision", ""),
            "quality_guard_adjusted_decision": quality_guard.get("guarded_decision", ""),
            "quality_guard_original_race_shape_penalty": quality_guard.get("original_race_shape_penalty", ""),
            "quality_guard_adjusted_race_shape_penalty": quality_guard.get("adjusted_race_shape_penalty", ""),
            "quality_guard_multiplier": quality_guard.get("guard_multiplier", ""),
            "quality_guard_past_performance_score": quality_guard.get("past_performance_score", ""),
            "quality_guard_distance_score": quality_guard.get("distance_score", ""),
            "quality_guard_decision_cap": quality_guard.get("decision_cap", ""),
            "quality_guard_adjusted_decision_score": quality_guard.get("adjusted_decision_score", ""),
            "consensus_guard_enabled": consensus_guard.get("consensus_guard_enabled", False),
            "consensus_guard_candidate": consensus_guard.get("consensus_guard_candidate", False),
            "consensus_guard_applied": consensus_guard.get("consensus_guard_applied", False),
            "consensus_guard_original_decision": consensus_guard.get("consensus_guard_original_decision", ""),
            "consensus_guard_final_decision": consensus_guard.get("consensus_guard_final_decision", ""),
            "consensus_positive_count": consensus_guard.get("consensus_positive_count", 0),
            "consensus_negative_count": consensus_guard.get("consensus_negative_count", 0),
            "consensus_positive_evaluators": consensus_guard.get("consensus_positive_evaluators", []),
            "consensus_negative_evaluators": consensus_guard.get("consensus_negative_evaluators", []),
            "consensus_block_reasons": consensus_guard.get("consensus_block_reasons", []),
            "consensus_guard_reason": consensus_guard.get("consensus_guard_reason", ""),
            "low_rank_buy_guard_applied": low_rank_guard.get("low_rank_buy_guard_applied", False),
            "original_decision": low_rank_guard.get("original_decision", ""),
            "guarded_decision": low_rank_guard.get("guarded_decision", ""),
            "ai_rank": low_rank_guard.get("ai_rank"),
            "low_rank_buy_guard_reason": low_rank_guard.get("guard_reason", ""),
            "low_rank_buy_guard_skipped_reason": low_rank_guard.get("guard_skipped_reason", ""),
            "decision_guards_applied": guard_result.get("decision_guards_applied", []),
            "decision_guard_count": guard_result.get("decision_guard_count", 0),
            "pre_guard_decision": guard_result.get("pre_guard_decision", ""),
            "post_guard_decision": guard_result.get("post_guard_decision", ""),
            "final_score": diagnostics.get("final_score"),
            "adjusted_score": diagnostics.get("adjusted_score"),
            "confidence": diagnostics.get("confidence"),
            "risk_items": diagnostics.get("risk_items", []),
            "risk_count": diagnostics.get("risk_count", 0),
            "risk_score": diagnostics.get("risk_score", 0),
            "conflict_items": diagnostics.get("conflict_items", []),
            "conflict_count": diagnostics.get("conflict_count", 0),
            "conflict_score": diagnostics.get("conflict_score", 0),
            "decision_reason_detail": diagnostics.get("decision_reason_detail", []),
            "decision_trace": diagnostics.get("decision_trace", []),
            "decision_diagnostic_text": diagnostics.get("decision_diagnostic_text", ""),
            "decision_diagnostics": diagnostics,
        }

    def decide_many(self, horses=None):
        """Return decision results in input order without mutating scores."""

        rows = horses if isinstance(horses, list) else []
        context = self._rank_context(rows)
        rank_map = self._score_rank_map(rows)
        results = []
        for row in rows:
            row_context = dict(context)
            row_context["rank"] = rank_map.get(id(row))
            results.append(self.decide(row, row_context))
        return results

    def _base_score(self, item, context):
        value = self._best_score(item)
        top = context.get("top_score")
        bottom = context.get("bottom_score")
        if value is None:
            return 0.5
        if top is None or bottom is None or top == bottom:
            return 0.6 if value > 0 else 0.45
        return 0.35 + ((value - bottom) / (top - bottom)) * 0.45

    def _rank_context(self, rows):
        scores = [self._best_score(row) for row in rows if isinstance(row, dict)]
        scores = [score for score in scores if score is not None]
        if not scores:
            return {"top_score": None, "bottom_score": None}
        return {"top_score": max(scores), "bottom_score": min(scores)}

    def _best_score(self, item):
        for key in ["adjusted_score", "integrated_score", "weighted_score", "final_score"]:
            value = self._number_or_none(item.get(key))
            if value is not None:
                return value
        return None

    def _apply_consistency(self, item, score, factors, risks):
        level = str(item.get("consistency_level") or "").lower()
        consistency = self._number_or_none(item.get("consistency_score"))
        strong_matches = self._list(item.get("strong_matches"))
        conflict_factors = self._list(item.get("conflict_factors"))

        if level == "high" or (consistency is not None and consistency >= 0.85):
            score += 0.12
            factors.append("構造一致度が高い")
        elif level == "medium" or (consistency is not None and consistency >= 0.7):
            score += 0.04
            factors.append("構造一致度は標準以上")
        elif level in {"low", "conflict"} or (consistency is not None and consistency < 0.5):
            score -= 0.18
            risks.append("構造一致度が低い")

        if len(strong_matches) >= 4:
            score += 0.06
            factors.append("複数Evaluatorが同方向")
        if len(conflict_factors) >= 2:
            score -= 0.1
            risks.append("構造との矛盾あり")
        return score

    def _apply_strengths_and_risks(self, item, score, factors, risks):
        strengths = self._list(item.get("final_strengths")) or self._list(item.get("strengths"))
        weaknesses = self._list(item.get("final_weaknesses")) or self._list(item.get("weaknesses"))
        risk_factors = self._list(item.get("final_risks")) or self._list(item.get("risk_factors"))

        if len(strengths) >= 6:
            score += 0.08
            factors.append("強みが多い")
        elif len(strengths) >= 3:
            score += 0.04
            factors.append("評価材料あり")

        if weaknesses:
            score -= min(0.12, 0.03 * len(weaknesses))
            risks.extend(str(weakness) for weakness in weaknesses[:4])

        if risk_factors:
            risk_penalty_count = len(risk_factors)
            pace_style = str(item.get("pace_style") or "")
            shape_score = self._number(item.get("shape_score"))
            impact_score = self._number(item.get("impact_score"))
            if pace_style in {"escape", "front"} and (shape_score < 0 or impact_score < 0):
                risk_penalty_count = max(0, risk_penalty_count - 1)
            score -= min(0.18, 0.04 * risk_penalty_count)
            risks.extend(str(risk) for risk in risk_factors[:5])

        major_count = len(self._major_risks(risks))
        if major_count >= 2:
            score -= 0.12
            risks.append("重大リスクが複数")
        return score

    def _apply_impact(self, item, score, factors, risks):
        impact = self._number(item.get("impact_score"))
        if impact > 0:
            score += min(0.08, impact / 100)
            factors.append("展開利あり")
        elif impact < 0:
            score -= min(0.08, abs(impact) / 100)
            risks.append("展開不向き")
        return score

    def _apply_warnings(self, item, score, risks):
        warnings = self._list(item.get("warnings"))
        if warnings:
            score -= min(0.12, 0.03 * len(warnings))
            risks.append("warningsあり")
        return score

    def _apply_summary_flags(self, item, score, factors, risks):
        text = " ".join(
            str(item.get(key) or "")
            for key in ["final_summary", "explain_summary", "confidence_reason"]
        )
        if any(word in text for word in ["過信", "ズレ", "不安", "注意", "不足"]):
            score -= 0.05
            risks.append("説明内に注意要素あり")
        if any(word in text for word in ["一致率が高", "複数Evaluator", "展開利", "整合性が高"]):
            score += 0.04
            factors.append("説明上の整合性が高い")
        return score

    def _decision(self, score, item, risks):
        major_count = len(self._major_risks(risks))
        conflicts = len(self._list(item.get("conflict_factors")))

        if score >= 0.8 and major_count == 0 and conflicts <= 1:
            return "BUY"
        if score < 0.5 or major_count >= 3 or conflicts >= 3:
            return "PASS"
        return "CAUTION"

    def _top_score_pass_rescue(self, item, context, score, decision):
        """Keep high-ranked, high-score PASS horses as CAUTION only."""

        if decision != "PASS":
            return self._pass_rescue_result(False, "", "decision_is_not_pass")

        rank = context.get("rank")
        if rank is None:
            rank = item.get("rank") or item.get("final_rank") or item.get("score_rank")
        rank = self._number_or_none(rank)
        if rank is None:
            return self._pass_rescue_result(False, "", "rank_unavailable")
        if rank > 5:
            return self._pass_rescue_result(False, "", "rank_outside_top5")

        final_score = self._number_or_none(item.get("final_score"))
        adjusted_score = self._number_or_none(item.get("adjusted_score"))
        high_score = (
            (final_score is not None and final_score >= 150)
            or (adjusted_score is not None and adjusted_score >= 155)
        )
        if not high_score:
            return self._pass_rescue_result(False, "", "score_below_rescue_threshold")

        decision_score = self._number_or_none(score)
        if decision_score is None or decision_score < 0.55:
            return self._pass_rescue_result(False, "", "decision_score_too_low")

        if self._has_fatal_exclusion(item):
            return self._pass_rescue_result(False, "", "fatal_exclusion_detected")

        reason = "AI上位かつ高スコアのためPASSからCAUTIONへ保留"
        return self._pass_rescue_result(True, reason, "")

    def _pass_rescue_result(self, rescued, reason, skipped_reason):
        return {
            "top_score_pass_rescued": rescued,
            "top_score_pass_rescue_reason": reason,
            "top_score_pass_rescue_skipped_reason": skipped_reason,
        }

    def _has_fatal_exclusion(self, item):
        texts = []
        for key in [
            "warnings",
            "risk_factors",
            "final_risks",
            "decision_risks",
            "weaknesses",
            "final_weaknesses",
        ]:
            texts.extend(str(value) for value in self._list(item.get(key)))
        joined = " ".join(texts).lower()
        fatal_keywords = [
            "取消",
            "除外",
            "出走不能",
            "データ破損",
            "適性が完全に不明",
            "重大な能力不足",
            "scratched",
            "excluded",
            "fatal",
            "corrupt",
        ]
        return any(keyword.lower() in joined for keyword in fatal_keywords)

    def _track_bias_buy_safety(self, item, context, score, decision):
        baseline_decision = str(item.get("baseline_decision") or "").upper()
        baseline_rank = self._number_or_none(item.get("baseline_rank"))
        baseline_available = bool(baseline_decision)

        if decision != "BUY":
            return {
                "baseline_available": baseline_available,
                "track_bias_sensitive_buy": False,
                "track_bias_only_buy": False,
                "buy_suppressed": False,
                "buy_suppression_reason": "",
                "guard_skipped_reason": "bias_decision_is_not_buy",
            }

        track_bias_score = self._number(item.get("track_bias_score"))
        weighted_track_bias = self._weighted_track_bias_score(item)
        rank = context.get("rank")
        if not baseline_available or baseline_rank is None:
            return {
                "baseline_available": False,
                "track_bias_sensitive_buy": False,
                "track_bias_only_buy": False,
                "buy_suppressed": False,
                "buy_suppression_reason": "",
                "guard_skipped_reason": "baseline_information_unavailable",
            }

        if baseline_decision == "BUY":
            return {
                "baseline_available": True,
                "track_bias_sensitive_buy": False,
                "track_bias_only_buy": False,
                "buy_suppressed": False,
                "buy_suppression_reason": "",
                "guard_skipped_reason": "baseline_decision_is_buy",
            }

        if track_bias_score <= 0:
            return {
                "baseline_available": True,
                "track_bias_sensitive_buy": False,
                "track_bias_only_buy": False,
                "buy_suppressed": False,
                "buy_suppression_reason": "",
                "guard_skipped_reason": "track_bias_score_not_positive",
            }

        if weighted_track_bias is None or weighted_track_bias <= 0:
            return {
                "baseline_available": True,
                "track_bias_sensitive_buy": False,
                "track_bias_only_buy": False,
                "buy_suppressed": False,
                "buy_suppression_reason": "",
                "guard_skipped_reason": "weighted_track_bias_score_not_positive",
            }

        if rank is None:
            return {
                "baseline_available": True,
                "track_bias_sensitive_buy": False,
                "track_bias_only_buy": False,
                "buy_suppressed": False,
                "buy_suppression_reason": "",
                "guard_skipped_reason": "bias_rank_unavailable",
            }

        low_rank = rank > 5
        no_rank_improvement = rank >= baseline_rank
        track_bias_only = track_bias_score > 0 and weighted_track_bias > 0
        sensitive = low_rank or no_rank_improvement

        if not sensitive:
            return {
                "baseline_available": True,
                "track_bias_sensitive_buy": False,
                "track_bias_only_buy": False,
                "buy_suppressed": False,
                "buy_suppression_reason": "",
                "guard_skipped_reason": "top5_rank_improved",
            }

        reason_parts = [
            "TrackBias safety: BUY suppressed because bias-only BUY did not improve enough",
        ]
        if rank is not None:
            reason_parts.append(f"rank={rank}")
        reason_parts.append(f"baseline_rank={baseline_rank:g}")
        reason_parts.append(f"baseline_decision={baseline_decision}")
        reason_parts.append(f"track_bias_score={track_bias_score}")
        reason_parts.append(f"weighted_track_bias_score={weighted_track_bias}")
        return {
            "baseline_available": True,
            "track_bias_sensitive_buy": True,
            "track_bias_only_buy": track_bias_only,
            "buy_suppressed": True,
            "buy_suppression_reason": " / ".join(reason_parts),
            "guard_skipped_reason": "",
        }

    def _decision_level(self, score, decision=None):
        if decision == "PASS":
            return "pass" if score < 0.5 else "weak_caution"
        if decision == "CAUTION":
            return "caution" if score >= 0.5 else "weak_caution"
        if score >= 0.9:
            return "strong_buy"
        if score >= 0.8:
            return "buy"
        if score >= 0.5:
            return "caution"
        if score >= 0.35:
            return "weak_caution"
        return "pass"

    def _decision_reason(self, decision, factors, risks):
        factor_text = "、".join(self._unique(factors)) or "評価材料は限定的"
        risk_text = "、".join(self._unique(risks)) or "大きなリスクは限定的"

        if decision == "BUY":
            return f"構造一致度と評価材料のバランスが良く、{factor_text}を確認。リスクは{risk_text}。"
        if decision == "CAUTION":
            return f"{factor_text}は評価できますが、{risk_text}も残るため慎重評価。"
        return f"一部評価材料はありますが、{risk_text}が大きく、今回は見送り寄りの判断。"

    def _is_major_risk(self, text):
        value = str(text)
        if self._is_informational_risk_excluded_from_major_count(value):
            return False
        return any(keyword in value for keyword in self.MAJOR_RISK_KEYWORDS)

    def _is_informational_risk_excluded_from_major_count(self, text):
        value = str(text)
        return value in self.INFORMATIONAL_RISK_EXCLUDED_FROM_MAJOR_COUNT

    def _major_risks(self, risks):
        return [
            str(risk)
            for risk in self._list(risks)
            if self._is_major_risk(risk)
        ]

    def _informational_risks(self, risks):
        return [
            str(risk)
            for risk in self._list(risks)
            if self._is_informational_risk_excluded_from_major_count(risk)
        ]

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

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _unique(self, values):
        unique = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique

    def _score_rank_map(self, rows):
        scored = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            score = self._best_score(row)
            if score is None:
                continue
            scored.append((score, id(row)))
        scored.sort(reverse=True)
        return {row_id: index + 1 for index, (_, row_id) in enumerate(scored)}

    def _weighted_track_bias_score(self, item):
        breakdown = item.get("weighted_score_breakdown")
        if not isinstance(breakdown, dict):
            return None
        row = breakdown.get("track_bias_score")
        if not isinstance(row, dict):
            return None
        return self._number_or_none(row.get("weighted_value"))

    def _decision_diagnostics(
        self,
        item,
        context,
        score,
        decision,
        level,
        factors,
        risks,
        safety,
        rescue,
        quality_guard=None,
        consensus_guard=None,
        low_rank_guard=None,
    ):
        """Build explainability diagnostics without influencing the decision."""

        quality_guard = quality_guard if isinstance(quality_guard, dict) else {}
        consensus_guard = consensus_guard if isinstance(consensus_guard, dict) else {}
        low_rank_guard = low_rank_guard if isinstance(low_rank_guard, dict) else {}
        final_score = self._number_or_none(item.get("final_score"))
        adjusted_score = self._number_or_none(item.get("adjusted_score"))
        confidence = (
            item.get("confidence")
            or item.get("confidence_level")
            or item.get("race_confidence")
            or item.get("confidence_reason")
        )
        risk_texts = self._unique(str(risk) for risk in risks if risk)
        risk_items = self._risk_items(risk_texts)
        major_count_before_filter = sum(
            1 for risk in risk_texts if any(keyword in risk for keyword in self.MAJOR_RISK_KEYWORDS)
        )
        major_risks = self._major_risks(risk_texts)
        informational_risks = self._informational_risks(risk_texts)
        major_count = len(major_risks)
        risk_score = min(1.0, round((0.04 * len(risk_texts)) + (0.08 * major_count), 3))

        conflict_factors = self._list(item.get("conflict_factors"))
        conflict_items = self._conflict_items(conflict_factors)
        conflict_score = 0
        if len(conflict_items) >= 2:
            conflict_score += 0.1
        if len(conflict_items) >= 3:
            conflict_score += 0.05
        conflict_score = round(conflict_score, 3)

        reason_detail = self._decision_reason_detail(
            score=score,
            decision=decision,
            risk_count=len(risk_items),
            major_count=major_count,
            conflict_items=conflict_items,
            safety=safety,
            rescue=rescue,
            quality_guard=quality_guard,
            consensus_guard=consensus_guard,
            low_rank_guard=low_rank_guard,
        )
        rank = context.get("rank") or item.get("rank") or item.get("final_rank") or item.get("score_rank")
        trace = [
            {"stage": "final_score", "value": final_score},
            {"stage": "adjusted_score", "value": adjusted_score},
            {"stage": "rank", "value": self._number_or_none(rank)},
            {"stage": "decision_score", "value": score},
            {
                "stage": "risk",
                "items": risk_items,
                "count": len(risk_items),
                "score": risk_score,
                "major_count_before_filter": major_count_before_filter,
                "major_count_after_filter": major_count,
                "informational_risks": informational_risks,
            },
            {
                "stage": "conflict",
                "items": conflict_items,
                "count": len(conflict_items),
                "score": conflict_score,
            },
            {
                "stage": "track_bias_guard",
                "applied": bool(safety.get("buy_suppressed")),
                "reason": safety.get("buy_suppression_reason", "")
                or safety.get("guard_skipped_reason", ""),
            },
            {
                "stage": "top_score_pass_rescue",
                "applied": bool(rescue.get("top_score_pass_rescued")),
                "reason": rescue.get("top_score_pass_rescue_reason", "")
                or rescue.get("top_score_pass_rescue_skipped_reason", ""),
            },
            {
                "stage": "past_performance_quality_guard",
                "applied": bool(quality_guard.get("quality_guard_applied")),
                "candidate": bool(quality_guard.get("quality_guard_candidate")),
                "original_decision": quality_guard.get("original_decision", ""),
                "guarded_decision": quality_guard.get("guarded_decision", ""),
                "original_race_shape_penalty": quality_guard.get("original_race_shape_penalty", ""),
                "adjusted_race_shape_penalty": quality_guard.get("adjusted_race_shape_penalty", ""),
                "guard_multiplier": quality_guard.get("guard_multiplier", ""),
                "past_performance_score": quality_guard.get("past_performance_score", ""),
                "distance_score": quality_guard.get("distance_score", ""),
                "decision_cap": quality_guard.get("decision_cap", ""),
                "reason": quality_guard.get("guard_reason", "")
                or quality_guard.get("quality_guard_skipped_reason", ""),
            },
            {
                "stage": "multi_evaluator_consensus_guard",
                "enabled": bool(consensus_guard.get("consensus_guard_enabled")),
                "candidate": bool(consensus_guard.get("consensus_guard_candidate")),
                "applied": bool(consensus_guard.get("consensus_guard_applied")),
                "original_decision": consensus_guard.get("consensus_guard_original_decision", ""),
                "guarded_decision": consensus_guard.get("consensus_guard_final_decision", ""),
                "positive_count": consensus_guard.get("consensus_positive_count", 0),
                "negative_count": consensus_guard.get("consensus_negative_count", 0),
                "positive_evaluators": consensus_guard.get("consensus_positive_evaluators", []),
                "negative_evaluators": consensus_guard.get("consensus_negative_evaluators", []),
                "block_reasons": consensus_guard.get("consensus_block_reasons", []),
                "reason": consensus_guard.get("consensus_guard_reason", ""),
            },
            {
                "stage": "low_rank_buy_guard",
                "applied": bool(low_rank_guard.get("low_rank_buy_guard_applied")),
                "ai_rank": low_rank_guard.get("ai_rank"),
                "reason": low_rank_guard.get("guard_reason", "")
                or low_rank_guard.get("guard_skipped_reason", ""),
            },
            {"stage": "decision", "value": decision, "level": level},
        ]
        return {
            "decision_score": score,
            "final_score": final_score,
            "adjusted_score": adjusted_score,
            "decision": decision,
            "confidence": confidence,
            "risk_items": risk_items,
            "risk_texts": risk_texts,
            "risk_count": len(risk_items),
            "risk_score": risk_score,
            "major_risk_count": major_count,
            "major_risks": major_risks,
            "informational_risks": informational_risks,
            "informational_risk_excluded_from_major_count": bool(informational_risks),
            "major_count_before_filter": major_count_before_filter,
            "major_count_after_filter": major_count,
            "conflict_items": conflict_items,
            "conflict_raw": self._unique(conflict_factors),
            "conflict_count": len(conflict_items),
            "conflict_score": conflict_score,
            "decision_reason_detail": reason_detail,
            "decision_trace": trace,
            "quality_guard_applied": quality_guard.get("quality_guard_applied", False),
            "quality_guard_name": quality_guard.get("quality_guard_name", ""),
            "quality_guard_candidate": quality_guard.get("quality_guard_candidate", False),
            "quality_guard_original_decision": quality_guard.get("original_decision", ""),
            "quality_guard_adjusted_decision": quality_guard.get("guarded_decision", ""),
            "quality_guard_original_race_shape_penalty": quality_guard.get("original_race_shape_penalty", ""),
            "quality_guard_adjusted_race_shape_penalty": quality_guard.get("adjusted_race_shape_penalty", ""),
            "quality_guard_multiplier": quality_guard.get("guard_multiplier", ""),
            "quality_guard_past_performance_score": quality_guard.get("past_performance_score", ""),
            "quality_guard_distance_score": quality_guard.get("distance_score", ""),
            "quality_guard_decision_cap": quality_guard.get("decision_cap", ""),
            "quality_guard_reason": quality_guard.get("guard_reason", ""),
            "quality_guard_skipped_reason": quality_guard.get("quality_guard_skipped_reason", ""),
            "consensus_guard_enabled": consensus_guard.get("consensus_guard_enabled", False),
            "consensus_guard_candidate": consensus_guard.get("consensus_guard_candidate", False),
            "consensus_guard_applied": consensus_guard.get("consensus_guard_applied", False),
            "consensus_guard_original_decision": consensus_guard.get("consensus_guard_original_decision", ""),
            "consensus_guard_final_decision": consensus_guard.get("consensus_guard_final_decision", ""),
            "consensus_positive_count": consensus_guard.get("consensus_positive_count", 0),
            "consensus_negative_count": consensus_guard.get("consensus_negative_count", 0),
            "consensus_positive_evaluators": consensus_guard.get("consensus_positive_evaluators", []),
            "consensus_negative_evaluators": consensus_guard.get("consensus_negative_evaluators", []),
            "consensus_block_reasons": consensus_guard.get("consensus_block_reasons", []),
            "consensus_guard_reason": consensus_guard.get("consensus_guard_reason", ""),
            "low_rank_buy_guard_applied": low_rank_guard.get(
                "low_rank_buy_guard_applied",
                False,
            ),
            "original_decision": low_rank_guard.get("original_decision", ""),
            "guarded_decision": low_rank_guard.get("guarded_decision", ""),
            "ai_rank": low_rank_guard.get("ai_rank"),
            "low_rank_buy_guard_reason": low_rank_guard.get("guard_reason", ""),
            "low_rank_buy_guard_skipped_reason": low_rank_guard.get(
                "guard_skipped_reason",
                "",
            ),
            "decision_diagnostic_text": self._decision_diagnostic_text(
                score,
                decision,
                risk_items,
                conflict_items,
                reason_detail,
            ),
        }

    def _risk_items(self, risks):
        items = []
        for risk in risks:
            text = str(risk)
            lower = text.lower()
            if "very_fast" in lower or "front" in lower or "ハイペース" in text or "前半" in text:
                items.append("very_fast_front")
            elif "small_turn" in lower or "小回り" in text or "後方" in text:
                items.append("small_turn_closer")
            elif "pace" in lower or "展開" in text:
                items.append("pace_risk")
            elif "lap" in lower or "ラップ" in text:
                items.append("lap_risk")
            elif "trackbias" in lower or "track_bias" in lower or "馬場バイアス" in text:
                items.append("track_bias_risk")
            elif "bloodline" in lower or "血統" in text:
                items.append("bloodline_risk")
            elif "warning" in lower:
                items.append("warning_risk")
            elif "conflict" in lower or "矛盾" in text:
                items.append("conflict_risk")
            elif "racedecision pass" in lower:
                items.append("race_decision_pass")
            elif self._is_major_risk(text):
                items.append("major_risk")
            else:
                items.append("risk")
        return self._unique(items)

    def _conflict_items(self, conflicts):
        items = []
        for conflict in conflicts:
            text = str(conflict or "").strip()
            lower = text.lower()
            if not text:
                continue
            if "lap" in lower:
                items.append("lap_conflict")
            elif "pace" in lower:
                items.append("pace_conflict")
            elif "style" in lower or "shape" in lower or "position" in lower:
                items.append("running_style_conflict")
            elif "course" in lower:
                items.append("course_shape_conflict")
            elif "track_bias" in lower or "bias" in lower:
                items.append("track_bias_conflict")
            elif "blood" in lower:
                items.append("bloodline_conflict")
            elif "distance" in lower:
                items.append("distance_conflict")
            else:
                items.append(f"{lower or 'unknown'}_conflict")
        return self._unique(items)

    def _decision_reason_detail(
        self,
        score,
        decision,
        risk_count,
        major_count,
        conflict_items,
        safety,
        rescue,
        quality_guard=None,
        consensus_guard=None,
        low_rank_guard=None,
    ):
        quality_guard = quality_guard if isinstance(quality_guard, dict) else {}
        consensus_guard = consensus_guard if isinstance(consensus_guard, dict) else {}
        low_rank_guard = low_rank_guard if isinstance(low_rank_guard, dict) else {}
        details = []
        if score < 0.5:
            details.append("decision_score_low")
        elif score < 0.8:
            details.append("decision_score_below_buy_threshold")
        else:
            details.append("decision_score_buy_range")

        if risk_count >= 4:
            details.append("risk_many")
        if major_count:
            details.append("major_risk")
        if len(conflict_items) >= 3:
            details.append("conflict_many")
        elif len(conflict_items) >= 2:
            details.append("conflict_present")
        if "lap_conflict" in conflict_items:
            details.append("lap_conflict")
        if "pace_conflict" in conflict_items:
            details.append("pace_conflict")
        if safety.get("buy_suppressed"):
            details.append("track_bias_buy_guard")
        if rescue.get("top_score_pass_rescued"):
            details.append("top_score_pass_rescue")
        if quality_guard.get("quality_guard_applied"):
            details.append("past_performance_quality_guard")
        if consensus_guard.get("consensus_guard_applied"):
            details.append("multi_evaluator_consensus_guard")
        if low_rank_guard.get("low_rank_buy_guard_applied"):
            details.append("low_rank_buy_guard")
        if decision == "BUY":
            details.append("decision_buy")
        elif decision == "CAUTION":
            details.append("decision_caution")
        else:
            details.append("decision_pass")
        return self._unique(details)

    def _decision_diagnostic_text(self, score, decision, risk_items, conflict_items, reason_detail):
        risk_text = ", ".join(risk_items) if risk_items else "none"
        conflict_text = ", ".join(conflict_items) if conflict_items else "none"
        detail_text = ", ".join(reason_detail) if reason_detail else "none"
        return (
            f"Decision diagnostics: DecisionScore={score}; "
            f"Risk={risk_text}; Conflict={conflict_text}; "
            f"Reason={detail_text}; Decision={decision}"
        )


if __name__ == "__main__":
    engine = DecisionEngine()
    sample = {
        "horse_name": "sample",
        "adjusted_score": 120,
        "consistency_score": 0.91,
        "consistency_level": "high",
        "strong_matches": ["course_shape", "distance", "lap", "bloodline"],
        "strengths": ["距離適性", "ラップ適性", "血統適性"],
        "risk_factors": ["当日バイアス情報が限定的"],
        "impact_score": 10,
    }
    print(engine.decide(sample, {"top_score": 120, "bottom_score": 0}))
