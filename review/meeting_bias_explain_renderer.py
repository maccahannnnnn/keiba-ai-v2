"""MeetingBias explain prototype renderer (R&D only, not connected to Production).

This module converts MeetingBias context into explain-only text. It is a
prototype for a future ExplainEngine integration and is intentionally isolated:

- It has no dependency on ExplainEngine, DecisionEngine, RaceDecisionEngine,
  ShadowBUYDecisionEngine, any Evaluator, or any scoring module.
- It never returns a score, weight, threshold, or decision.
- ``score_impact`` is always ``"none"``.
- MeetingBias is treated as a prior distribution over meeting progression.
  TrackBias owns the same-day observed lane tendency and RaceShape owns the
  per-race running-style structure. When an observed layer disagrees with the
  MeetingBias prior, the observed layer wins and MeetingBias is demoted to
  context-only wording.
- ``manual_template`` knowledge is never presented as validated evidence.

The renderer is a pure function of its input dict. It reads no files, writes no
files, and holds no state between calls.
"""

from __future__ import annotations

from typing import Any


class MeetingBiasExplainRenderer:
    """Render explain-only MeetingBias wording from meeting context."""

    VERSION = "meeting_bias_explain_prototype_v1"

    # Evidence thresholds mirror the Diagnostic Shadow entry criteria.
    MIN_SUPPORT_RACES = 15
    MIN_SUPPORT_MEETINGS = 2

    EXPLAIN_TIERS = ("SUPPRESSED", "CONTEXT_ONLY", "SUPPORTING")
    EVIDENCE_TIERS = ("INSUFFICIENT", "TEMPLATE_ONLY", "PROVISIONAL", "VALIDATED")
    RELATIONS = ("AGREEMENT", "CONFLICT", "NO_OBSERVATION", "NOT_APPLICABLE")

    VALID_STAGES = ("opening", "middle", "closing")
    VALID_STAGE_SOURCES = ("EXPLICIT", "MEETING_WEEK", "MEETING_DAY", "DERIVED_ORDER")

    STAGE_LABELS = {
        "opening": "開催前半",
        "middle": "開催中盤",
        "closing": "開催後半",
    }
    LANE_LABELS = {
        "inside": "内寄り",
        "outside": "外寄り",
        "neutral": "内外中立",
    }
    STYLE_LABELS = {
        "front": "前目・好位",
        "closer": "差し・追込",
        "balanced": "脚質中立",
    }

    def render(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return an explain-only MeetingBias block for one race."""

        data = context if isinstance(context, dict) else {}

        stage = self._stage(data.get("meeting_stage"))
        stage_source = self._stage_source(data.get("meeting_stage_source"))
        knowledge_connected = self._knowledge_connected(data)
        validated = bool(data.get("validated"))
        support_races = self._int(data.get("support_races"))
        support_meetings = self._int(data.get("support_meetings"))

        lane_prior = self._lane(data.get("inside_outside_tendency"))
        style_prior = self._style(data.get("front_closer_tendency"))

        track_bias = data.get("track_bias_observation")
        race_shape = data.get("race_shape_observation")
        lane_observed = self._lane(self._observed(track_bias, "inside_outside"))
        style_observed = self._style(self._observed(race_shape, "front_closer"))

        evidence_tier, suppression_reason = self._evidence_tier(
            stage=stage,
            stage_source=stage_source,
            knowledge_connected=knowledge_connected,
            validated=validated,
            support_races=support_races,
            support_meetings=support_meetings,
        )

        lane_relation = self._relation(lane_prior, lane_observed)
        style_relation = self._relation(style_prior, style_observed)
        has_conflict = "CONFLICT" in (lane_relation, style_relation)

        explain_tier = self._explain_tier(evidence_tier, has_conflict)
        lines = self._lines(
            explain_tier=explain_tier,
            evidence_tier=evidence_tier,
            suppression_reason=suppression_reason,
            data=data,
            stage=stage,
            lane_prior=lane_prior,
            style_prior=style_prior,
            lane_observed=lane_observed,
            style_observed=style_observed,
            lane_relation=lane_relation,
            style_relation=style_relation,
        )

        return {
            "version": self.VERSION,
            "explain_tier": explain_tier,
            "evidence_tier": evidence_tier,
            "suppression_reason": suppression_reason,
            "relations": {
                "track_bias": lane_relation,
                "race_shape": style_relation,
            },
            "lines": lines,
            "text": "\n".join(lines),
            "score_impact": "none",
            "audit": {
                "meeting_stage": stage,
                "meeting_stage_source": stage_source,
                "knowledge_connected": knowledge_connected,
                "validated": validated,
                "support_races": support_races,
                "support_meetings": support_meetings,
                "lane_prior": lane_prior,
                "style_prior": style_prior,
                "lane_observed": lane_observed,
                "style_observed": style_observed,
                "observed_layer_precedence": "TrackBias/RaceShape override MeetingBias prior",
                "min_support_races": self.MIN_SUPPORT_RACES,
                "min_support_meetings": self.MIN_SUPPORT_MEETINGS,
            },
        }

    def tiebreak_note(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the future Option E wording without enabling any behavior.

        Option E is the proposed BUY-selection tiebreak use of MeetingBias for
        unconverged races. This helper only produces the wording that such a
        future feature would need. It never selects, ranks, or scores a horse.
        """

        rendered = self.render(context)
        if rendered["explain_tier"] != "SUPPORTING":
            return {
                "available": False,
                "reason": f"explain_tier={rendered['explain_tier']}",
                "lines": [],
                "score_impact": "none",
                "feature_state": "NOT_IMPLEMENTED",
            }
        style_prior = rendered["audit"]["style_prior"]
        label = self.STYLE_LABELS.get(style_prior, "")
        lines = [
            "【将来案・未実装】候補が3頭に収束しない場合に限り、"
            f"{label}の傾向を並び順の補助情報として参照する案がある。",
            "この案でもゲート閾値・スコア・BUY上限は変更しない。",
        ]
        return {
            "available": True,
            "reason": "",
            "lines": lines,
            "score_impact": "none",
            "feature_state": "NOT_IMPLEMENTED",
        }

    # ------------------------------------------------------------------
    # tier resolution
    # ------------------------------------------------------------------

    def _evidence_tier(
        self,
        stage: str,
        stage_source: str,
        knowledge_connected: bool,
        validated: bool,
        support_races: int,
        support_meetings: int,
    ) -> tuple[str, str]:
        if stage not in self.VALID_STAGES:
            return "INSUFFICIENT", "meeting_stage_unknown"
        if stage_source not in self.VALID_STAGE_SOURCES:
            return "INSUFFICIENT", "meeting_stage_source_unknown"
        if not knowledge_connected:
            return "INSUFFICIENT", "meeting_bias_knowledge_not_connected"
        if not validated:
            return "TEMPLATE_ONLY", "manual_template_not_validated"
        if support_races < self.MIN_SUPPORT_RACES:
            return "PROVISIONAL", "support_races_below_minimum"
        if support_meetings < self.MIN_SUPPORT_MEETINGS:
            return "PROVISIONAL", "support_meetings_below_minimum"
        return "VALIDATED", ""

    def _explain_tier(self, evidence_tier: str, has_conflict: bool) -> str:
        if evidence_tier == "INSUFFICIENT":
            return "SUPPRESSED"
        if evidence_tier in {"TEMPLATE_ONLY", "PROVISIONAL"}:
            return "CONTEXT_ONLY"
        # VALIDATED evidence is still demoted when an observed layer disagrees.
        return "CONTEXT_ONLY" if has_conflict else "SUPPORTING"

    def _relation(self, prior: str, observed: str) -> str:
        if not prior:
            return "NOT_APPLICABLE"
        if not observed:
            return "NO_OBSERVATION"
        return "AGREEMENT" if prior == observed else "CONFLICT"

    # ------------------------------------------------------------------
    # wording
    # ------------------------------------------------------------------

    def _lines(
        self,
        explain_tier: str,
        evidence_tier: str,
        suppression_reason: str,
        data: dict[str, Any],
        stage: str,
        lane_prior: str,
        style_prior: str,
        lane_observed: str,
        style_observed: str,
        lane_relation: str,
        style_relation: str,
    ) -> list[str]:
        if explain_tier == "SUPPRESSED":
            return [self._suppressed_line(suppression_reason, stage)]

        header = self._header(data, stage)
        lines = [header]

        prior_text = self._prior_text(lane_prior, style_prior)
        if evidence_tier == "TEMPLATE_ONLY":
            lines.append(
                f"手動テンプレート由来の一般傾向では、{prior_text}。"
                "検証済みEvidenceではないため、評価には使用しない。"
            )
        elif evidence_tier == "PROVISIONAL":
            lines.append(
                f"事前分布では、{prior_text}。"
                "ただし裏付けレース数・開催数が基準に達していないため、参考情報にとどめる。"
            )
        else:
            lines.append(f"開催進行の事前分布では、{prior_text}。")

        lines.extend(
            self._relation_lines(
                lane_prior,
                lane_observed,
                lane_relation,
                style_prior,
                style_observed,
                style_relation,
            )
        )

        if explain_tier == "CONTEXT_ONLY":
            lines.append("MeetingBiasは参考レイヤーであり、スコアや判定には反映しない。")
        return lines

    def _suppressed_line(self, reason: str, stage: str) -> str:
        if reason == "meeting_stage_unknown":
            return "開催段階を特定できないため、MeetingBiasは評価に使用しない。"
        if reason == "meeting_stage_source_unknown":
            label = self.STAGE_LABELS.get(stage, "開催段階")
            return f"{label}と推定されるが、根拠が不明なため、MeetingBiasは評価に使用しない。"
        return "MeetingBias Knowledgeが未接続のため、MeetingBiasは評価に使用しない。"

    def _header(self, data: dict[str, Any], stage: str) -> str:
        course = str(data.get("racecourse") or "").strip()
        surface = self._surface_label(data.get("surface"))
        category = self._category_label(data.get("distance_category"))
        stage_label = self.STAGE_LABELS.get(stage, "開催段階不明")
        prefix = "".join(part for part in (course, surface, category) if part)
        return f"{prefix}の{stage_label}。" if prefix else f"{stage_label}。"

    def _prior_text(self, lane_prior: str, style_prior: str) -> str:
        parts = []
        if lane_prior:
            parts.append(f"進路は{self.LANE_LABELS.get(lane_prior, lane_prior)}")
        if style_prior:
            parts.append(f"脚質は{self.STYLE_LABELS.get(style_prior, style_prior)}")
        return "、".join(parts) if parts else "明確な方向性なし"

    def _relation_lines(
        self,
        lane_prior: str,
        lane_observed: str,
        lane_relation: str,
        style_prior: str,
        style_observed: str,
        style_relation: str,
    ) -> list[str]:
        lines = []
        if lane_relation == "AGREEMENT":
            lines.append(
                f"当日のTrackBiasも{self.LANE_LABELS.get(lane_observed, lane_observed)}で、"
                "事前傾向と実測は同方向。"
            )
        elif lane_relation == "CONFLICT":
            lines.append(
                f"ただし当日のTrackBiasは{self.LANE_LABELS.get(lane_observed, lane_observed)}。"
                "当日実測を優先し、MeetingBiasによる進路の補正は抑制する。"
            )
        elif lane_relation == "NO_OBSERVATION":
            lines.append("当日のTrackBias情報がないため、進路傾向は事前分布としてのみ参照する。")

        if style_relation == "AGREEMENT":
            lines.append(
                f"当該レースのRaceShapeも{self.STYLE_LABELS.get(style_observed, style_observed)}寄りで、"
                "展開構造とも整合している。"
            )
        elif style_relation == "CONFLICT":
            lines.append(
                f"一方でRaceShapeは{self.STYLE_LABELS.get(style_observed, style_observed)}を示す。"
                "レース固有の展開を優先し、MeetingBiasによる脚質の補正は抑制する。"
            )
        elif style_relation == "NO_OBSERVATION":
            lines.append("RaceShapeの展開情報がないため、脚質傾向は事前分布としてのみ参照する。")
        return lines

    # ------------------------------------------------------------------
    # normalization
    # ------------------------------------------------------------------

    def _stage(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in self.VALID_STAGES else "UNKNOWN"

    def _stage_source(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        return text if text in self.VALID_STAGE_SOURCES else "UNKNOWN"

    def _knowledge_connected(self, data: dict[str, Any]) -> bool:
        if "knowledge_connected" in data:
            return bool(data.get("knowledge_connected"))
        source = str(data.get("knowledge_source") or "").strip().lower()
        return bool(source) and source != "not_connected"

    def _lane(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        if "outside" in text:
            return "outside"
        if "inside" in text:
            return "inside"
        if "neutral" in text or "balanced" in text:
            return "neutral"
        return ""

    def _style(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        if "closer" in text or "sashi" in text:
            return "closer"
        if "front" in text or "nige" in text:
            return "front"
        if "balanced" in text or "neutral" in text:
            return "balanced"
        return ""

    def _observed(self, observation: Any, key: str) -> Any:
        if not isinstance(observation, dict):
            return ""
        if observation.get("available") is False:
            return ""
        return observation.get(key, "")

    def _surface_label(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"turf", "芝"}:
            return "芝"
        if text in {"dirt", "ダート", "ダ"}:
            return "ダート"
        return ""

    def _category_label(self, value: Any) -> str:
        return {
            "sprint": "短距離",
            "mile": "マイル",
            "middle": "中距離",
            "long": "長距離",
        }.get(str(value or "").strip().lower(), "")

    def _int(self, value: Any) -> int:
        if isinstance(value, bool) or value in (None, ""):
            return 0
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return 0


if __name__ == "__main__":
    import json

    sample = {
        "racecourse": "函館",
        "surface": "turf",
        "distance_category": "sprint",
        "meeting_stage": "closing",
        "meeting_stage_source": "MEETING_DAY",
        "knowledge_source": "daily_review_validated",
        "validated": True,
        "support_races": 18,
        "support_meetings": 2,
        "inside_outside_tendency": "outside_watch",
        "front_closer_tendency": "stalk_closer",
        "track_bias_observation": {"available": True, "inside_outside": "inside"},
        "race_shape_observation": {"available": False},
    }
    print(json.dumps(MeetingBiasExplainRenderer().render(sample), ensure_ascii=False, indent=2))
