"""Post-decision guard layer for DecisionEngine.

DecisionGuard receives an already calculated decision and may narrow risky BUY
labels to CAUTION. It does not calculate scores, change ranks, or create new
BUY/PASS labels.
"""

from engine.past_performance_quality_guard import PastPerformanceQualityGuard
from engine.multi_evaluator_consensus_guard import MultiEvaluatorConsensusGuard


class DecisionGuard:
    """Apply final safety guards after the base DecisionEngine judgment."""

    def __init__(
        self,
        enable_past_performance_quality_guard=False,
        enable_multi_evaluator_consensus_guard=False,
    ):
        self.past_performance_quality_guard = PastPerformanceQualityGuard(
            enabled=enable_past_performance_quality_guard
        )
        self.multi_evaluator_consensus_guard = MultiEvaluatorConsensusGuard(
            enabled=enable_multi_evaluator_consensus_guard
        )

    def apply(self, item=None, context=None, decision=None, decision_score=None):
        """Return final decision and guard diagnostics."""

        base_decision = decision or ""
        quality = self.past_performance_quality_guard.apply(
            item or {},
            context or {},
            base_decision,
            decision_score,
        )
        after_quality = quality.get("guarded_decision") or base_decision
        consensus = self.multi_evaluator_consensus_guard.apply(
            item or {},
            context or {},
            after_quality,
            decision_score,
        )
        after_consensus = consensus.get("guarded_decision") or after_quality
        low_rank = self._low_rank_buy_guard(item or {}, context or {}, after_consensus)
        final_decision = low_rank.get("guarded_decision") or after_quality
        guards_applied = []
        if quality.get("quality_guard_applied"):
            guards_applied.append("past_performance_quality_guard")
        if consensus.get("consensus_guard_applied"):
            guards_applied.append("multi_evaluator_consensus_guard")
        if low_rank.get("low_rank_buy_guard_applied"):
            guards_applied.append("low_rank_buy_guard")

        return {
            "decision": final_decision,
            "pre_guard_decision": base_decision,
            "post_guard_decision": final_decision,
            "decision_guards_applied": guards_applied,
            "decision_guard_count": len(guards_applied),
            "past_performance_quality_guard": quality,
            "multi_evaluator_consensus_guard": consensus,
            "low_rank_buy_guard": low_rank,
        }

    def _low_rank_buy_guard(self, item, context, decision):
        """Suppress only BUY labels whose AI score rank is outside Top5."""

        rank = context.get("rank")
        if rank is None:
            rank = item.get("rank") or item.get("final_rank") or item.get("score_rank")
        rank = self._number_or_none(rank)

        if decision != "BUY":
            return {
                "low_rank_buy_guard_applied": False,
                "original_decision": decision,
                "guarded_decision": decision,
                "ai_rank": rank,
                "guard_reason": "",
                "guard_skipped_reason": "decision_is_not_buy",
            }
        if rank is None:
            return {
                "low_rank_buy_guard_applied": False,
                "original_decision": "BUY",
                "guarded_decision": "BUY",
                "ai_rank": None,
                "guard_reason": "",
                "guard_skipped_reason": "rank_unavailable",
            }
        if rank <= 5:
            return {
                "low_rank_buy_guard_applied": False,
                "original_decision": "BUY",
                "guarded_decision": "BUY",
                "ai_rank": rank,
                "guard_reason": "",
                "guard_skipped_reason": "rank_top5",
            }

        reason = (
            f"Low Rank BUY Guard: AI順位{rank:g}位のためBUYからCAUTIONへ調整"
        )
        return {
            "low_rank_buy_guard_applied": True,
            "original_decision": "BUY",
            "guarded_decision": "CAUTION",
            "ai_rank": rank,
            "guard_reason": reason,
            "guard_skipped_reason": "",
        }

    def _number_or_none(self, value):
        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
