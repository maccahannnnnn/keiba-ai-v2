"""BUY v1.0 RC1 production-candidate adapter.

This layer promotes the accepted Shadow BUY v1.1 behavior to a feature-flagged
RC1 view.  It does not change evaluator scores, DecisionEngine thresholds, or
the shadow consensus rescue experiments that remain on HOLD.
"""

from engine.buy_specification import (
    BUY_V1_RC1_ENABLED,
    BUYV1RC1Config,
    ShadowConsensusTargetedRescueConfig,
)
from engine.shadow_buy_decision_engine import ShadowBUYDecisionEngine


class BUYV1RC1Engine:
    """Convert accepted shadow BUY records into RC1 decision fields."""

    VERSION = BUYV1RC1Config.VERSION

    def __init__(self, enabled=None):
        self.enabled = BUY_V1_RC1_ENABLED if enabled is None else bool(enabled)
        self.config = BUYV1RC1Config()
        self.shadow_engine = ShadowBUYDecisionEngine(
            enabled=self.enabled,
            use_v1_1=True,
            consensus_rescue_config=ShadowConsensusTargetedRescueConfig.disabled(),
        )

    def evaluate(self, race_output=None, horses=None):
        """Return RC1 race and horse records without mutating inputs."""

        if not self.enabled:
            return {
                "enabled": False,
                "version": self.VERSION,
                "race_state": "",
                "race_decision": "",
                "horse_records": [],
                "summary": {"rc1_buy_count": 0},
            }

        shadow_result = self.shadow_engine.evaluate(race_output=race_output, horses=horses)
        horse_records = [
            self._rc1_horse_record(row, shadow_result)
            for row in shadow_result.get("horse_records", [])
        ]
        summary = self._summary(shadow_result, horse_records)
        return {
            "enabled": True,
            "version": self.VERSION,
            "shadow_result": shadow_result,
            "race_state": shadow_result.get("shadow_race_state"),
            "race_decision": shadow_result.get("shadow_race_decision"),
            "play_skip_reason": shadow_result.get("shadow_play_skip_reason", []),
            "race_record": shadow_result.get("race_record", {}),
            "horse_records": horse_records,
            "summary": summary,
        }

    def apply_to_horses(self, horses, rc1_result):
        """Attach RC1 fields and make RC1 BUY official when the flag is ON."""

        if not self.enabled or not isinstance(horses, list):
            return horses
        by_name = {
            row.get("horse_name"): row
            for row in rc1_result.get("horse_records", [])
            if row.get("horse_name")
        }
        for horse in horses:
            if not isinstance(horse, dict):
                continue
            record = by_name.get(horse.get("horse_name") or horse.get("name"))
            if not record:
                continue
            legacy_decision = horse.get("decision")
            horse["legacy_decision"] = legacy_decision
            horse["legacy_buy"] = legacy_decision == "BUY"
            horse["buy_v1_rc1_enabled"] = True
            horse["buy_v1_rc1_decision"] = record.get("rc1_decision")
            horse["buy_v1_rc1_buy"] = record.get("rc1_buy", False)
            horse["buy_v1_rc1_status"] = record.get("rc1_status")
            horse["buy_v1_rc1_race_state"] = record.get("race_state")
            horse["buy_v1_rc1_reason"] = record.get("rc1_reason")
            horse["buy_v1_rc1_candidate"] = record.get("rc1_candidate", False)
            horse["decision"] = record.get("rc1_decision") or legacy_decision
        return horses

    def _rc1_horse_record(self, shadow_row, shadow_result):
        status = shadow_row.get("shadow_status")
        legacy_decision = shadow_row.get("current_decision", "")
        rc1_buy = status == "SHADOW_BUY"
        if rc1_buy:
            rc1_decision = "BUY"
            reason = shadow_row.get("shadow_buy_reason") or "rc1_play_converged_buy"
        elif legacy_decision == "BUY":
            rc1_decision = "CAUTION"
            reason = self._non_buy_reason(shadow_row, shadow_result)
        else:
            rc1_decision = legacy_decision
            reason = self._non_buy_reason(shadow_row, shadow_result)

        return {
            "race_id": shadow_row.get("race_id"),
            "horse_name": shadow_row.get("horse_name"),
            "legacy_decision": legacy_decision,
            "legacy_buy": legacy_decision == "BUY",
            "rc1_decision": rc1_decision,
            "rc1_buy": rc1_buy,
            "rc1_candidate": shadow_row.get("shadow_buy_candidate", False),
            "rc1_status": self._rc1_status(status),
            "race_state": shadow_result.get("shadow_race_state"),
            "race_decision": shadow_result.get("shadow_race_decision"),
            "rc1_reason": reason,
            "ai_rank": shadow_row.get("ai_rank"),
            "final_score": shadow_row.get("final_score"),
            "adjusted_score": shadow_row.get("adjusted_score"),
            "decision_score": shadow_row.get("decision_score"),
            "confidence": shadow_row.get("confidence"),
            "absolute_quality_pass": shadow_row.get("absolute_quality_pass"),
            "relative_advantage_pass": shadow_row.get("relative_advantage_pass"),
            "reliability_pass": shadow_row.get("reliability_pass"),
            "risk_guard_pass": shadow_row.get("risk_guard_pass"),
            "consensus": shadow_row.get("consensus", {}),
            "consensus_profile": shadow_row.get("consensus_profile", {}),
            "risk_summary": shadow_row.get("risk_summary", []),
            "shadow_not_buy_reason": shadow_row.get("shadow_not_buy_reason", ""),
            "shadow_buy_reason": shadow_row.get("shadow_buy_reason", ""),
        }

    def _rc1_status(self, shadow_status):
        if shadow_status == "SHADOW_BUY":
            return "RC1_BUY"
        if shadow_status == "SHADOW_BUY_CANDIDATE_UNCONVERGED":
            return "RC1_CANDIDATE_UNCONVERGED_4PLUS"
        if shadow_status == "SHADOW_REJECTED":
            return "RC1_REJECTED"
        return "RC1_NOT_BUY"

    def _non_buy_reason(self, shadow_row, shadow_result):
        race_state = shadow_result.get("shadow_race_state", "")
        if shadow_row.get("shadow_candidate_unconverged"):
            return "play_unconverged_4plus_candidate_retained"
        if race_state == "SKIP":
            reasons = shadow_result.get("shadow_play_skip_reason", [])
            return "skip:" + ";".join(str(reason) for reason in reasons)
        return shadow_row.get("shadow_not_buy_reason") or "not_rc1_buy_candidate"

    def _summary(self, shadow_result, horse_records):
        race_state = shadow_result.get("shadow_race_state")
        return {
            "version": self.VERSION,
            "race_state": race_state,
            "race_decision": shadow_result.get("shadow_race_decision"),
            "rc1_buy_count": sum(1 for row in horse_records if row.get("rc1_buy")),
            "legacy_buy_count": sum(1 for row in horse_records if row.get("legacy_buy")),
            "candidate_count": sum(1 for row in horse_records if row.get("rc1_candidate")),
            "unconverged_candidate_count": sum(
                1
                for row in horse_records
                if row.get("rc1_status") == "RC1_CANDIDATE_UNCONVERGED_4PLUS"
            ),
            "skip_reason": shadow_result.get("shadow_play_skip_reason", [])
            if race_state == "SKIP"
            else [],
        }
