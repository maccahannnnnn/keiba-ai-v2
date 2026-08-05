"""Fixed tests for the MeetingBias explain prototype renderer.

These tests are pure in-memory checks. The renderer reads no files, writes no
files, and is not connected to Production, so no temporary workspace or
Production artifact is touched.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from review.meeting_bias_explain_renderer import MeetingBiasExplainRenderer


def base_context(**overrides):
    context = {
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
        "track_bias_observation": {"available": True, "inside_outside": "outside_watch"},
        "race_shape_observation": {"available": True, "front_closer": "stalk_closer"},
    }
    context.update(overrides)
    return context


class MeetingBiasExplainRendererTest(unittest.TestCase):
    def setUp(self):
        self.renderer = MeetingBiasExplainRenderer()

    # --- suppression -------------------------------------------------

    def test_unknown_meeting_stage_is_suppressed(self):
        result = self.renderer.render(base_context(meeting_stage="UNKNOWN"))
        self.assertEqual(result["explain_tier"], "SUPPRESSED")
        self.assertEqual(result["evidence_tier"], "INSUFFICIENT")
        self.assertEqual(result["suppression_reason"], "meeting_stage_unknown")
        self.assertIn("評価に使用しない", result["text"])

    def test_unknown_stage_source_is_suppressed(self):
        result = self.renderer.render(base_context(meeting_stage_source="UNKNOWN"))
        self.assertEqual(result["explain_tier"], "SUPPRESSED")
        self.assertEqual(result["suppression_reason"], "meeting_stage_source_unknown")

    def test_knowledge_not_connected_is_suppressed(self):
        result = self.renderer.render(base_context(knowledge_source="not_connected"))
        self.assertEqual(result["explain_tier"], "SUPPRESSED")
        self.assertEqual(result["suppression_reason"], "meeting_bias_knowledge_not_connected")

    def test_empty_context_is_safe_and_suppressed(self):
        for payload in (None, {}, {"meeting_stage": ""}):
            with self.subTest(payload=payload):
                result = self.renderer.render(payload)
                self.assertEqual(result["explain_tier"], "SUPPRESSED")
                self.assertEqual(result["score_impact"], "none")

    # --- evidence tiers ----------------------------------------------

    def test_manual_template_is_context_only_and_not_used(self):
        result = self.renderer.render(
            base_context(knowledge_source="manual_template", validated=False)
        )
        self.assertEqual(result["evidence_tier"], "TEMPLATE_ONLY")
        self.assertEqual(result["explain_tier"], "CONTEXT_ONLY")
        self.assertIn("検証済みEvidenceではない", result["text"])
        self.assertIn("評価には使用しない", result["text"])

    def test_insufficient_support_races_is_provisional(self):
        result = self.renderer.render(base_context(support_races=5))
        self.assertEqual(result["evidence_tier"], "PROVISIONAL")
        self.assertEqual(result["explain_tier"], "CONTEXT_ONLY")
        self.assertEqual(result["suppression_reason"], "support_races_below_minimum")

    def test_single_meeting_support_is_provisional(self):
        result = self.renderer.render(base_context(support_meetings=1))
        self.assertEqual(result["evidence_tier"], "PROVISIONAL")
        self.assertEqual(result["suppression_reason"], "support_meetings_below_minimum")

    def test_validated_and_agreeing_is_supporting(self):
        result = self.renderer.render(base_context())
        self.assertEqual(result["evidence_tier"], "VALIDATED")
        self.assertEqual(result["explain_tier"], "SUPPORTING")
        self.assertEqual(result["relations"]["track_bias"], "AGREEMENT")
        self.assertEqual(result["relations"]["race_shape"], "AGREEMENT")

    # --- observed layer precedence -----------------------------------

    def test_track_bias_conflict_demotes_and_suppresses_correction(self):
        result = self.renderer.render(
            base_context(track_bias_observation={"available": True, "inside_outside": "inside"})
        )
        self.assertEqual(result["evidence_tier"], "VALIDATED")
        self.assertEqual(result["explain_tier"], "CONTEXT_ONLY")
        self.assertEqual(result["relations"]["track_bias"], "CONFLICT")
        self.assertIn("当日実測を優先", result["text"])
        self.assertIn("抑制", result["text"])

    def test_race_shape_conflict_demotes_and_suppresses_correction(self):
        result = self.renderer.render(
            base_context(race_shape_observation={"available": True, "front_closer": "front_stalk"})
        )
        self.assertEqual(result["explain_tier"], "CONTEXT_ONLY")
        self.assertEqual(result["relations"]["race_shape"], "CONFLICT")
        self.assertIn("レース固有の展開を優先", result["text"])

    def test_missing_observation_is_prior_only(self):
        result = self.renderer.render(
            base_context(
                track_bias_observation={"available": False},
                race_shape_observation={"available": False},
            )
        )
        self.assertEqual(result["relations"]["track_bias"], "NO_OBSERVATION")
        self.assertEqual(result["relations"]["race_shape"], "NO_OBSERVATION")
        self.assertIn("事前分布としてのみ参照", result["text"])

    # --- wording and safety ------------------------------------------

    def test_score_impact_is_always_none(self):
        contexts = [
            base_context(),
            base_context(meeting_stage="UNKNOWN"),
            base_context(validated=False, knowledge_source="manual_template"),
            base_context(track_bias_observation={"available": True, "inside_outside": "inside"}),
        ]
        for context in contexts:
            with self.subTest(stage=context.get("meeting_stage")):
                self.assertEqual(self.renderer.render(context)["score_impact"], "none")

    def test_no_assertive_wording(self):
        banned = ["必ず", "確実", "間違いなく", "断定", "確定的"]
        contexts = [
            base_context(),
            base_context(meeting_stage="UNKNOWN"),
            base_context(validated=False, knowledge_source="manual_template"),
            base_context(support_races=1),
            base_context(track_bias_observation={"available": True, "inside_outside": "inside"}),
        ]
        for context in contexts:
            text = self.renderer.render(context)["text"]
            for word in banned:
                self.assertNotIn(word, text)

    def test_renderer_does_not_import_production_modules(self):
        source = Path("review/meeting_bias_explain_renderer.py").read_text(encoding="utf-8")
        forbidden = [
            "engine.explain_engine",
            "engine.decision_engine",
            "engine.race_decision_engine",
            "engine.shadow_buy_decision_engine",
            "engine.buy_v1_rc1_engine",
            "engine.buy_specification",
            "evaluation.target_trial_adapter",
            "evaluation.target_result_adapter",
        ]
        for name in forbidden:
            self.assertNotIn(f"from {name}", source)
            self.assertNotIn(f"import {name}", source)

    # --- Option E future note ----------------------------------------

    def test_tiebreak_note_requires_supporting_tier(self):
        blocked = self.renderer.tiebreak_note(base_context(meeting_stage="UNKNOWN"))
        self.assertFalse(blocked["available"])
        self.assertEqual(blocked["lines"], [])

    def test_tiebreak_note_is_marked_unimplemented(self):
        note = self.renderer.tiebreak_note(base_context())
        self.assertTrue(note["available"])
        self.assertEqual(note["feature_state"], "NOT_IMPLEMENTED")
        self.assertEqual(note["score_impact"], "none")
        self.assertIn("未実装", note["lines"][0])
        self.assertIn("変更しない", note["lines"][1])


if __name__ == "__main__":
    unittest.main()
