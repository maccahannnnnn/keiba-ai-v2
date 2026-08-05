"""Synchronize final RaceDecision display with production BUY output.

This layer is intentionally additive. It does not change RaceDecisionEngine,
BUY V1 RC1, horse scores, evaluator outputs, confidence, or BUY selection.
It only prevents the final report layer from exposing RaceDecision PASS while
the final production horse decisions contain BUY.
"""

from __future__ import annotations

from copy import deepcopy


class RaceDecisionBuySynchronizer:
    """Create final race-decision fields after BUY V1 RC1 is applied."""

    TARGET_DECISION = "PLAY"
    SYNC_REASON = (
        "BUY V1 RC1適用後に最終BUY馬が存在するため、"
        "RaceDecisionをPASSからPLAYへ同期"
    )
    BUY0_NON_PASS_WARNING = (
        "最終BUY馬は存在しないが、元RaceDecisionが非PASSのため既存RaceDecisionを維持"
    )

    def synchronize(self, race_decision_result=None, horses=None, rc1_result=None):
        original = deepcopy(race_decision_result) if isinstance(race_decision_result, dict) else {}
        rows = [horse for horse in horses if isinstance(horse, dict)] if isinstance(horses, list) else []
        final_buy_horses = [
            str(horse.get("horse_name") or horse.get("name") or "")
            for horse in rows
            if str(horse.get("decision") or "").upper() == "BUY"
        ]
        final_buy_horses = [name for name in final_buy_horses if name]
        final_buy_count = len(final_buy_horses)

        original_decision = str(original.get("race_decision") or "").upper()
        final_decision = original_decision
        sync_applied = False
        sync_reason = ""
        warnings = []

        if original_decision == "PASS" and final_buy_count >= 1:
            final_decision = self.TARGET_DECISION
            sync_applied = True
            sync_reason = self.SYNC_REASON
        elif original_decision != "PASS" and final_buy_count == 0 and original_decision:
            warnings.append(self.BUY0_NON_PASS_WARNING)

        synchronized = deepcopy(original)
        synchronized["race_decision_original"] = original_decision
        synchronized["race_decision_final"] = final_decision
        synchronized["race_decision_sync_applied"] = sync_applied
        synchronized["race_decision_sync_reason"] = sync_reason
        synchronized["race_decision_sync_final_buy_count"] = final_buy_count
        synchronized["race_decision_sync_final_buy_horses"] = final_buy_horses
        synchronized["race_decision_sync_warnings"] = warnings
        synchronized["race_decision_sync_source"] = "buy_v1_rc1_final_output"
        synchronized["race_decision_sync_rc1_enabled"] = (
            bool(rc1_result.get("enabled")) if isinstance(rc1_result, dict) else False
        )
        synchronized["race_decision_sync_rc1_race_state"] = (
            rc1_result.get("race_state") if isinstance(rc1_result, dict) else ""
        )
        synchronized["race_decision"] = final_decision or original.get("race_decision")
        if sync_applied:
            synchronized["race_decision_reason_original"] = original.get("race_decision_reason", "")
            synchronized["race_decision_reason"] = self._append_reason(
                original.get("race_decision_reason", ""),
                sync_reason,
            )

        return {
            "race_decision_result": synchronized,
            "race_decision_original": original_decision,
            "race_decision_final": final_decision,
            "race_decision_sync_applied": sync_applied,
            "race_decision_sync_reason": sync_reason,
            "final_buy_count": final_buy_count,
            "final_buy_horses": final_buy_horses,
            "warnings": warnings,
        }

    def _append_reason(self, original_reason, sync_reason):
        original_text = str(original_reason or "").strip()
        if not original_text:
            return sync_reason
        if sync_reason in original_text:
            return original_text
        return f"{original_text} / {sync_reason}"
