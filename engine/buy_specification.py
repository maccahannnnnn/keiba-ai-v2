"""BUY specification and feature flags for BUY policy work.

BUY v1.0 RC1 is the production default.  The underlying DecisionEngine,
evaluator scores, thresholds, and shadow experiments remain unchanged; this
flag only controls whether the accepted RC1 view becomes the official BUY
output in the normal TargetTrialAdapter path.
"""

import os


def _enabled_from_env(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class BUYSpecification:
    """Hold BUY policy constants without applying them to current logic."""

    VERSION = "buy_specification_v1_0_foundation"

    MAX_BUY = 3
    MIN_BUY = 0
    ENABLE_PLAY_SKIP = True
    REQUIRE_MINIMUM_QUALITY = True

    SUPPORTED_RACE_DECISIONS = ("PLAY", "CAUTION", "PASS")
    FUTURE_RACE_DECISIONS = ("PLAY", "SKIP")

    # Future roadmap:
    # Phase3: statistics and outcome summaries.
    # Phase4: improvement candidate extraction.
    # Phase5: shadow validation.
    # Phase6: human approval workflow.

    def as_dict(self):
        return {
            "version": self.VERSION,
            "max_buy": self.MAX_BUY,
            "min_buy": self.MIN_BUY,
            "enable_play_skip": self.ENABLE_PLAY_SKIP,
            "require_minimum_quality": self.REQUIRE_MINIMUM_QUALITY,
            "supported_race_decisions": list(self.SUPPORTED_RACE_DECISIONS),
            "future_race_decisions": list(self.FUTURE_RACE_DECISIONS),
        }


SHADOW_BUY_SPEC_V1_ENABLED = False
SHADOW_BUY_SPEC_V1_1_ENABLED = False
SHADOW_CONSENSUS_TARGETED_RESCUE_V1_ENABLED = False
BUY_V1_RC1_ENABLED = _enabled_from_env("BUY_V1_RC1_ENABLED", True)


class BUYV1RC1Config:
    """Release Candidate switch for accepted BUY v1.0 shadow behavior.

    RC1 adopts the accepted Shadow v1.1 PLAY/SKIP, quality, relative advantage,
    consensus reliability, and risk guard behavior.  HOLD items such as
    targeted consensus rescue remain disabled.
    """

    VERSION = "buy_v1_0_rc1"
    ENABLED = BUY_V1_RC1_ENABLED
    USE_SHADOW_V1_1 = True
    CONSENSUS_RESCUE_ENABLED = False

    def as_dict(self):
        return {
            "version": self.VERSION,
            "enabled": self.ENABLED,
            "use_shadow_v1_1": self.USE_SHADOW_V1_1,
            "consensus_rescue_enabled": self.CONSENSUS_RESCUE_ENABLED,
        }


class ShadowBUYSpecV1Config:
    """Declarative thresholds for Shadow BUY Specification v1.0.

    These values are used only by the shadow engine. They do not alter
    DecisionEngine thresholds or production BUY / CAUTION / PASS labels.
    Future validation should tune them with held-out race sets, not by fitting
    one race day or one venue.
    """

    VERSION = "shadow_buy_spec_v1_0"
    MAX_BUY = BUYSpecification.MAX_BUY
    MIN_BUY = BUYSpecification.MIN_BUY

    # Absolute quality: require an already strong production signal.
    MIN_DECISION_SCORE = 0.80
    MIN_FINAL_SCORE = 130.0
    MIN_ADJUSTED_SCORE = 145.0

    # Relative advantage: avoid buying merely because a horse ranks high.
    MAX_AI_RANK = 5
    MIN_TOP_GROUP_GAP = 0.0

    # Reliability: require several independent evaluator supports.
    MIN_POSITIVE_EVALUATORS = 5
    MAX_NEGATIVE_EVALUATORS = 1

    # Race-level playability: skip races whose candidate set does not converge.
    MAX_SHADOW_BUY_CANDIDATES = 3
    MIN_RACE_CANDIDATES_FOR_PLAY = 1

    # Risk: severe items are hard blocks; numerous ordinary risks are soft blocks.
    MAX_RISK_COUNT = 5
    MAX_CONFLICT_COUNT = 1

    def as_dict(self):
        return {
            "version": self.VERSION,
            "max_buy": self.MAX_BUY,
            "min_buy": self.MIN_BUY,
            "min_decision_score": self.MIN_DECISION_SCORE,
            "min_final_score": self.MIN_FINAL_SCORE,
            "min_adjusted_score": self.MIN_ADJUSTED_SCORE,
            "max_ai_rank": self.MAX_AI_RANK,
            "min_top_group_gap": self.MIN_TOP_GROUP_GAP,
            "min_positive_evaluators": self.MIN_POSITIVE_EVALUATORS,
            "max_negative_evaluators": self.MAX_NEGATIVE_EVALUATORS,
            "max_shadow_buy_candidates": self.MAX_SHADOW_BUY_CANDIDATES,
            "min_race_candidates_for_play": self.MIN_RACE_CANDIDATES_FOR_PLAY,
            "max_risk_count": self.MAX_RISK_COUNT,
            "max_conflict_count": self.MAX_CONFLICT_COUNT,
        }


class ShadowConsensusTargetedRescueConfig:
    """Shadow-only targeted rescue for consensus boundary candidates.

    This does not change production consensus thresholds or evaluator scores.
    It only allows validation runs to compare narrowly-scoped rescue patterns.
    """

    VERSION = "shadow_consensus_targeted_rescue_v1"
    ENABLED = SHADOW_CONSENSUS_TARGETED_RESCUE_V1_ENABLED
    CONFIG_NAME = "disabled"
    METHOD = "disabled"

    MIN_POSITIVE_COUNT = 4
    MAX_NEGATIVE_COUNT = 1
    MAX_STRONG_NEGATIVE_COUNT = 0
    MIN_STRONG_POSITIVE_COUNT = None
    MIN_NET_CONSENSUS_SCORE = None

    @classmethod
    def disabled(cls):
        return cls()

    @classmethod
    def strong_positive(cls, min_strong_positive_count=2):
        config = cls()
        config.ENABLED = True
        config.CONFIG_NAME = f"rescue_A_strong_positive_{min_strong_positive_count}"
        config.METHOD = "strong_positive"
        config.MIN_STRONG_POSITIVE_COUNT = min_strong_positive_count
        return config

    @classmethod
    def net_consensus(cls, min_net_consensus_score, name=None):
        config = cls()
        config.ENABLED = True
        config.CONFIG_NAME = name or f"rescue_B_net_{min_net_consensus_score}"
        config.METHOD = "net_consensus"
        config.MIN_NET_CONSENSUS_SCORE = float(min_net_consensus_score)
        return config

    @classmethod
    def strong_positive_and_net(
        cls,
        min_strong_positive_count=2,
        min_net_consensus_score=5.0,
    ):
        config = cls()
        config.ENABLED = True
        config.CONFIG_NAME = (
            f"rescue_C_strong_positive_{min_strong_positive_count}_net_"
            f"{min_net_consensus_score}"
        )
        config.METHOD = "strong_positive_and_net"
        config.MIN_STRONG_POSITIVE_COUNT = min_strong_positive_count
        config.MIN_NET_CONSENSUS_SCORE = float(min_net_consensus_score)
        return config

    def as_dict(self):
        return {
            "version": self.VERSION,
            "enabled": self.ENABLED,
            "config_name": self.CONFIG_NAME,
            "method": self.METHOD,
            "min_positive_count": self.MIN_POSITIVE_COUNT,
            "max_negative_count": self.MAX_NEGATIVE_COUNT,
            "max_strong_negative_count": self.MAX_STRONG_NEGATIVE_COUNT,
            "min_strong_positive_count": self.MIN_STRONG_POSITIVE_COUNT,
            "min_net_consensus_score": self.MIN_NET_CONSENSUS_SCORE,
        }
