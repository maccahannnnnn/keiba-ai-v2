"""Generate and persist explainable improvement candidates from reviews.

LearningCandidateEngine is a recording layer only. It does not learn
automatically, re-score horses, update knowledge, mutate decisions, or change
confidence. Human review remains the required next step.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import unicodedata
from pathlib import Path

from engine.knowledge_gap_extractor import KnowledgeGapExtractor
from engine.recommended_knowledge_validator import RecommendedKnowledgeValidator


class LearningCandidateEngine:
    """Create improvement candidates from review output and aggregate repeats."""

    DEFAULT_DB_PATH = Path("learning/improvement_candidates.json")
    DEFAULT_REPORT_PATH = Path("reports/improvement_candidates.md")
    CANDIDATE_GENERATION_VERSION = "phase_e_step5_v1"
    CURRENT_BASELINE_IMPLEMENTATION_ID = "phase_d_step5_fast_turf_sprint_closer_guard"

    SCORE_ATTRIBUTION_RULES = {
        "shape_score": ("RaceShapeEvaluator", -4, 8),
        "lap_score": ("LapSuitabilityEvaluator", -4, 8),
        "pace_style_score": ("PaceStyleEvaluator", 10, 20),
        "running_style_score": ("PaceStyleEvaluator", 10, 20),
        "course_shape_score": ("CourseShapeEvaluator", -4, 8),
        "course_score": ("CourseShapeEvaluator", -4, 8),
        "distance_score": ("DistanceEvaluator", 20, 35),
        "track_condition_score": ("TrackConditionSuitabilityEvaluator", -1, 18),
        "track_score": ("TrackConditionSuitabilityEvaluator", -1, 18),
        "bloodline_score": ("BloodlineEvaluator", 0, 20),
        "blood_score": ("BloodlineEvaluator", 0, 20),
        "past_performance_score": ("PastPerformanceEvaluator", 30, 70),
        "past_score": ("PastPerformanceEvaluator", 30, 70),
        "impact_score": ("ImpactEvaluator", -10, 10),
    }

    EVALUATOR_SIGNALS = [
        (
            "RaceShapeEvaluator",
            "Evaluator",
            ("shape_score",),
            ("RaceShape", "shape", "展開", "ペース", "very_fast", "fast"),
        ),
        (
            "LapSuitabilityEvaluator",
            "Evaluator",
            ("lap_score",),
            ("Lap", "lap", "ラップ", "上がり", "終い"),
        ),
        (
            "PaceStyleEvaluator",
            "Evaluator",
            ("pace_style_score", "running_style_score"),
            ("PaceStyle", "pace_style", "running_style", "脚質", "位置取り"),
        ),
        (
            "CourseShapeEvaluator",
            "Evaluator",
            ("course_shape_score", "course_score"),
            ("CourseShape", "course_shape", "コース", "小回り", "直線"),
        ),
        (
            "DistanceEvaluator",
            "Evaluator",
            ("distance_score",),
            ("Distance", "distance", "距離"),
        ),
        (
            "TrackBiasEvaluator",
            "Evaluator",
            ("track_bias_score",),
            ("TrackBias", "track_bias", "バイアス", "内", "外"),
        ),
        (
            "TrackConditionSuitabilityEvaluator",
            "Evaluator",
            ("track_condition_score", "track_score"),
            ("TrackCondition", "track_condition", "馬場"),
        ),
        (
            "BloodlineEvaluator",
            "Evaluator",
            ("bloodline_score", "blood_score"),
            ("Bloodline", "bloodline", "血統", "profile not found"),
        ),
        (
            "PastPerformanceEvaluator",
            "Evaluator",
            ("past_performance_score", "past_score"),
            ("PastPerformance", "past", "過去走", "安定"),
        ),
        (
            "MeetingBias",
            "Knowledge",
            (),
            ("Meeting Bias", "MeetingBias", "開催", "コース替わり"),
        ),
        (
            "DecisionEngine",
            "Decision",
            ("decision_score",),
            ("Decision", "decision", "BUY", "PASS", "CAUTION", "Risk", "Conflict"),
        ),
        (
            "ConfidenceEngine",
            "Decision",
            (),
            ("Confidence", "confidence", "信頼"),
        ),
    ]

    def __init__(self, db_path=None, report_path=None):
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self.report_path = Path(report_path) if report_path else self.DEFAULT_REPORT_PATH
        self.knowledge_gap_extractor = KnowledgeGapExtractor()
        self.recommended_knowledge_validator = RecommendedKnowledgeValidator()

    def generate(
        self,
        race_output=None,
        ranked_results=None,
        review_result=None,
        improvement_result=None,
        official_results=None,
    ):
        """Generate, save, and aggregate review-driven candidates."""

        race = race_output if isinstance(race_output, dict) else {}
        review = review_result if isinstance(review_result, dict) else {}
        improvement = improvement_result if isinstance(improvement_result, dict) else {}
        official = official_results if isinstance(official_results, dict) else {}
        warnings = []

        horse_rows = self._horse_rows(race, ranked_results)
        result_rows = self._result_rows(race, official)
        result_map = self._result_map(result_rows)
        review_map = self._review_map(review.get("horse_reviews"))
        race_id = (
            race.get("race_id")
            or official.get("race_id")
            or self._nested_get(official, ["race_result", "race_id"])
            or "unknown_race"
        )
        race_context = self._race_context(race, official, race_id)

        if not result_map:
            warnings.append("official_result_unavailable")

        candidates = []
        for horse in horse_rows:
            if not isinstance(horse, dict):
                continue
            name = horse.get("horse_name") or horse.get("name")
            if not name:
                continue
            result = self._lookup_result(result_map, name)
            finish = self._to_int((result or {}).get("finish_position"))
            if finish is None:
                continue

            decision = str(horse.get("decision") or "").upper()
            case_type = self._case_type(decision, finish)
            if case_type is None:
                continue

            review_item = self._lookup_result(review_map, name) or {}
            candidates.append(
                self._candidate_record(
                    race_id=race_id,
                    horse=horse,
                    result=result,
                    review_item=review_item,
                    improvement=improvement,
                    case_type=case_type,
                    race_context=race_context,
                )
            )

        database = self._load_database()
        database = self._merge_candidates(database, candidates)
        self._save_database(database)
        self._write_report(database)

        summary = self._summary(database, candidates, warnings)
        return {
            "status": "recorded",
            "race_id": race_id,
            "candidates": candidates,
            "learning_candidates": candidates,
            "candidate_count": len(candidates),
            "aggregate_summary": database.get("aggregates", []),
            "summary": summary,
            "db_path": str(self.db_path),
            "report_path": str(self.report_path),
            "warnings": warnings,
        }

    def _candidate_record(
        self,
        race_id,
        horse,
        result,
        review_item,
        improvement,
        case_type,
        race_context=None,
    ):
        decision = str(horse.get("decision") or "").upper()
        finish = self._to_int((result or {}).get("finish_position"))
        context = dict(race_context if isinstance(race_context, dict) else {})
        context.update(self._horse_context(horse, result))
        attribution_candidates = self._attribution_candidates(
            horse,
            review_item,
            improvement,
            case_type,
        )
        primary_candidate = self._primary_candidate(attribution_candidates)
        secondary_candidates = [
            item.get("target")
            for item in attribution_candidates
            if item.get("rank") != 1 and item.get("target") != "UNKNOWN"
        ][:3]
        decision_attribution = (
            horse.get("decision_attribution")
            if isinstance(horse.get("decision_attribution"), dict)
            else {}
        )
        decision_primary_detail = self._decision_primary_detail(
            decision_attribution,
            case_type,
        )
        decision_secondary_details = self._decision_secondary_details(
            decision_attribution,
            case_type,
        )
        decision_root_cause = self._decision_root_cause(decision_attribution)
        root_primary_candidate = decision_root_cause.get("root_primary_candidate")
        root_secondary_candidates = self._list(
            decision_root_cause.get("root_secondary_candidates")
        )
        bloodline_root_cause = (
            horse.get("bloodline_root_cause")
            if isinstance(horse.get("bloodline_root_cause"), dict)
            else {}
        )
        unknown_factors = self._unknown_factors(attribution_candidates)
        attribution_confidence = self._overall_attribution_confidence(
            attribution_candidates,
            primary_candidate,
        )
        if (
            primary_candidate == "DecisionEngine"
            and root_primary_candidate not in (None, "", "UNKNOWN", "DecisionEngine")
        ):
            primary_candidate = root_primary_candidate
            attribution_confidence = decision_root_cause.get("root_confidence") or attribution_confidence
        cause_candidates = self._legacy_cause_candidates(attribution_candidates)
        evaluator_candidates = [
            item for item in cause_candidates if item.get("candidate_type") == "Evaluator"
        ]
        knowledge_candidates = [
            item for item in cause_candidates if item.get("candidate_type") == "Knowledge"
        ]
        decision_candidates = [
            item for item in cause_candidates if item.get("candidate_type") == "Decision"
        ]
        knowledge_gap_record = {
            "race_id": race_id,
            "horse": horse.get("horse_name"),
            "case_type": case_type,
            "decision": decision,
            "actual_finish": finish,
            "racecourse": context.get("racecourse"),
            "surface": context.get("surface"),
            "distance": context.get("distance"),
            "track_condition": context.get("track_condition"),
            "root_primary_candidate": root_primary_candidate,
            "root_importance": decision_root_cause.get("root_importance"),
            "root_confidence": decision_root_cause.get("root_confidence"),
            "bloodline_primary_factor": bloodline_root_cause.get("bloodline_primary_factor"),
            "bloodline_root_causes": self._list(
                bloodline_root_cause.get("bloodline_root_causes")
            ),
            "ranking_active": True,
        }
        knowledge_gaps = self.knowledge_gap_extractor.extract_record(knowledge_gap_record)
        primary_knowledge_gap = knowledge_gaps[0] if knowledge_gaps else {}
        knowledge_validation = self.recommended_knowledge_validator.build_record_validation(
            {"knowledge_gaps": knowledge_gaps}
        )
        now = self._now()
        return {
            "candidate_id": self._candidate_id(race_id, horse.get("horse_name"), case_type),
            "race_id": race_id,
            "race_date": context.get("race_date"),
            "racecourse": context.get("racecourse"),
            "race_number": context.get("race_number"),
            "surface": context.get("surface"),
            "distance": context.get("distance"),
            "track_condition": context.get("track_condition"),
            "race_class": context.get("race_class"),
            "horse": horse.get("horse_name"),
            "decision": decision,
            "actual_finish": finish,
            "fn": case_type == "FN",
            "fp": case_type == "FP",
            "case_type": case_type,
            "ai_rank": self._to_int(horse.get("rank")),
            "final_score": self._to_float(horse.get("final_score")),
            "adjusted_score": self._to_float(horse.get("adjusted_score")),
            "decision_score": self._to_float(horse.get("decision_score")),
            "explain_summary": self._explain_summary(horse, review_item),
            "review_summary": self._review_summary(review_item, case_type, finish),
            "missed_candidate": self._missed_candidate(case_type, decision, finish),
            "attribution_candidates": attribution_candidates,
            "primary_candidate": primary_candidate,
            "secondary_candidates": secondary_candidates,
            "decision_primary_factor": decision_primary_detail.get("target"),
            "decision_primary_factor_type": decision_primary_detail.get("target_type"),
            "decision_secondary_factors": [
                item.get("target") for item in decision_secondary_details
            ],
            "distance_to_buy": decision_attribution.get("distance_to_buy"),
            "decision_margin": decision_attribution.get("decision_margin"),
            "decision_counterfactual": self._list(
                decision_attribution.get("counterfactuals")
            ),
            "decision_counterfactual_feasible": decision_attribution.get(
                "counterfactual_feasible",
                False,
            ),
            "decision_attribution_confidence": decision_attribution.get(
                "attribution_confidence",
            ),
            "decision_specific_blocker": self._decision_specific_blocker(
                decision_attribution,
            ),
            "decision_attribution_version": decision_attribution.get(
                "attribution_version",
            ),
            "decision_cause_count_type": decision_attribution.get("cause_count_type"),
            "decision_fixed_blocker": decision_attribution.get(
                "fixed_decision_blocker",
                False,
            ),
            "root_primary_candidate": root_primary_candidate,
            "root_secondary_candidates": root_secondary_candidates,
            "decision_gate": decision_root_cause.get("decision_gate"),
            "root_importance": decision_root_cause.get("root_importance"),
            "root_confidence": decision_root_cause.get("root_confidence"),
            "root_version": decision_root_cause.get("root_version"),
            "root_cause_type": decision_root_cause.get("root_cause_type"),
            "decision_root_causes": self._list(decision_root_cause.get("root_causes")),
            "bloodline_primary_factor": bloodline_root_cause.get("bloodline_primary_factor"),
            "bloodline_secondary_factors": self._list(
                bloodline_root_cause.get("bloodline_secondary_factors")
            ),
            "bloodline_root_version": bloodline_root_cause.get("bloodline_root_version"),
            "bloodline_root_causes": self._list(
                bloodline_root_cause.get("bloodline_root_causes")
            ),
            "bloodline_knowledge_paths": self._list(
                bloodline_root_cause.get("knowledge_paths")
            ),
            "bloodline_knowledge_classified": bloodline_root_cause.get(
                "knowledge_classified",
                False,
            ),
            "knowledge_gap_version": self.knowledge_gap_extractor.GAP_VERSION if knowledge_gaps else None,
            "knowledge_gaps": knowledge_gaps,
            "knowledge_gap_primary_category": primary_knowledge_gap.get("category"),
            "knowledge_gap_primary_detail": primary_knowledge_gap.get("detail"),
            "knowledge_gap_primary_bloodline": primary_knowledge_gap.get("bloodline"),
            "knowledge_validation_status": knowledge_validation.get("knowledge_validation_status"),
            "knowledge_missing_type": knowledge_validation.get("knowledge_missing_type"),
            "causal_confidence": knowledge_validation.get("causal_confidence"),
            "recommended_scope": knowledge_validation.get("recommended_scope", {}),
            "counter_group_size": knowledge_validation.get("counter_group_size"),
            "affected_fn_count": knowledge_validation.get("affected_fn_count"),
            "affected_non_fn_count": knowledge_validation.get("affected_non_fn_count"),
            "potential_fp_risk": knowledge_validation.get("potential_fp_risk"),
            "recommended_implementation_id": knowledge_validation.get("recommended_implementation_id"),
            "knowledge_validation_version": knowledge_validation.get("knowledge_validation_version"),
            "unknown_factors": unknown_factors,
            "attribution_confidence": attribution_confidence,
            "evidence_count": sum(
                len(self._list(item.get("evidence")))
                for item in attribution_candidates
            ),
            "counter_evidence_count": sum(
                len(self._list(item.get("counter_evidence")))
                for item in attribution_candidates
            ),
            "candidate_generation_version": self.CANDIDATE_GENERATION_VERSION,
            "generation_version": self.CANDIDATE_GENERATION_VERSION,
            "ranking_active": True,
            "resolved_by_implementation_id": "",
            "resolution_status": "UNRESOLVED",
            "resolved_date": "",
            "cause_candidates": cause_candidates,
            "evaluator_candidates": evaluator_candidates,
            "knowledge_candidates": knowledge_candidates,
            "decision_candidates": decision_candidates,
            "confidence": self._confidence(horse, review_item),
            "risk": self._risk(horse, review_item),
            "recurrence_count": 1,
            "priority": self._priority(case_type, finish, cause_candidates),
            "status": "NEW",
            "created_at": now,
            "updated_at": now,
        }

    def _attribution_candidates(self, horse, review_item, improvement, case_type):
        buckets = {}

        def add(target, target_type, score, evidence_text=None, counter_text=None):
            item = buckets.setdefault(
                target,
                {
                    "target": target,
                    "target_type": target_type,
                    "candidate_type": target_type,
                    "score": 0.0,
                    "evidence": [],
                    "counter_evidence": [],
                },
            )
            item["score"] = min(1.0, item["score"] + score)
            if evidence_text:
                item["evidence"].append(evidence_text)
            if counter_text:
                item["counter_evidence"].append(counter_text)

        self._add_phase_e_decision_attribution(add, horse, case_type)
        self._add_bloodline_root_cause(add, horse, case_type)

        for target in self._list(review_item.get("root_causes")):
            target = str(target or "")
            if not target:
                continue
            add(
                target,
                self._candidate_type(target),
                0.28,
                "ReviewEngine listed this as a root cause",
            )

        for target in self._list(improvement.get("improvement_targets")):
            target = str(target or "")
            if not target:
                continue
            if target in buckets:
                add(target, self._candidate_type(target), 0.12, "ImprovementAdvisor repeated this target")

        for key, (target, fn_threshold, fp_threshold) in self.SCORE_ATTRIBUTION_RULES.items():
            value = self._to_float(horse.get(key))
            if value is None:
                continue
            if case_type == "FN":
                if value <= fn_threshold:
                    add(
                        target,
                        self._candidate_type(target),
                        self._score_gap(value, fn_threshold, inverse=True),
                        f"{key}={value:g} was below FN attribution threshold {fn_threshold:g}",
                    )
                elif value >= fp_threshold:
                    add(
                        target,
                        self._candidate_type(target),
                        0.0,
                        counter_text=f"{key}={value:g} was strong, so this is weak as an FN cause",
                    )
            elif case_type == "FP":
                if value >= fp_threshold:
                    add(
                        target,
                        self._candidate_type(target),
                        self._score_gap(value, fp_threshold, inverse=False),
                        f"{key}={value:g} was high enough to support FP overvaluation review",
                    )
                elif value <= fn_threshold:
                    add(
                        target,
                        self._candidate_type(target),
                        0.0,
                        counter_text=f"{key}={value:g} was weak, so this is weak as an FP overvaluation cause",
                    )

        self._add_decision_attribution(add, horse, case_type)
        self._add_knowledge_attribution(add, horse)

        candidates = []
        for item in buckets.values():
            item["evidence"] = self._unique(item.get("evidence"))[:6]
            item["counter_evidence"] = self._unique(item.get("counter_evidence"))[:4]
            evidence_count = len(item["evidence"])
            counter_count = len(item["counter_evidence"])
            if item["score"] <= 0 and evidence_count == 0:
                continue
            if evidence_count == 0 and item["target"] != "UNKNOWN":
                continue
            item["score"] = round(max(0.0, min(1.0, item["score"] - counter_count * 0.08)), 3)
            if item["score"] < 0.12 and item["target"] != "UNKNOWN":
                continue
            item["confidence"] = self._attribution_confidence(item)
            candidates.append(item)

        if not candidates:
            candidates = [
                {
                    "target": "UNKNOWN",
                    "target_type": "UNKNOWN",
                    "candidate_type": "UNKNOWN",
                    "score": 1.0,
                    "rank": 1,
                    "evidence": ["Available data did not identify a direct evaluator, decision, or knowledge blocker"],
                    "counter_evidence": [],
                    "confidence": "LOW",
                }
            ]
            return candidates

        candidates.sort(
            key=lambda item: (
                -item.get("score", 0),
                -len(item.get("evidence", [])),
                item.get("target", ""),
            )
        )
        for index, item in enumerate(candidates, start=1):
            item["rank"] = index
        return candidates

    def _add_decision_attribution(self, add, horse, case_type):
        decision_score = self._to_float(horse.get("decision_score"))
        ai_rank = self._to_int(horse.get("rank") or horse.get("final_rank"))
        decision = str(horse.get("decision") or "").upper()
        diagnostics = horse.get("decision_diagnostics")
        if not isinstance(diagnostics, dict):
            diagnostics = {}

        if case_type == "FN" and decision_score is not None:
            if 0.7 <= decision_score < 0.8:
                add(
                    "DecisionEngine",
                    "Decision",
                    0.38,
                    f"DecisionScore={decision_score:g} was near the BUY boundary but did not reach 0.80",
                )
            elif decision_score < 0.55:
                add(
                    "DecisionEngine",
                    "Decision",
                    0.18,
                    f"DecisionScore={decision_score:g} was far below BUY boundary",
                    counter_text="Low DecisionScore may reflect upstream evaluator weakness rather than Decision logic alone",
                )

        if case_type == "FP" and decision == "BUY" and decision_score is not None:
            if decision_score >= 0.8:
                add(
                    "DecisionEngine",
                    "Decision",
                    0.22,
                    f"BUY was allowed with DecisionScore={decision_score:g}",
                )

        if diagnostics.get("low_rank_buy_guard_applied"):
            add(
                "DecisionEngine",
                "Decision",
                0.55,
                "Low Rank BUY Guard affected final Decision",
            )
        if ai_rank is not None and case_type == "FN" and ai_rank <= 5 and decision != "BUY":
            add(
                "DecisionEngine",
                "Decision",
                0.25,
                f"AI rank {ai_rank} was Top5, but final Decision was {decision}",
            )

        major_risks = self._list(diagnostics.get("major_risks"))
        if major_risks:
            add(
                "DecisionEngine",
                "Decision",
                0.2,
                f"Decision major risks present: {', '.join(str(item) for item in major_risks[:3])}",
            )

    def _add_knowledge_attribution(self, add, horse):
        risk_text = " ".join(str(item) for item in self._risk(horse, {}))
        if "バイアス情報が限定的" in risk_text or "bias" in risk_text.lower():
            add(
                "TrackBiasEvaluator",
                "Knowledge",
                0.16,
                "Track bias information was limited or neutral",
            )
        if "profile not found" in risk_text.lower() or "Bloodline profile not found" in str(horse):
            add(
                "BloodlineEvaluator",
                "Knowledge",
                0.18,
                "Bloodline profile information was missing",
            )

    def _add_phase_e_decision_attribution(self, add, horse, case_type):
        attribution = horse.get("decision_attribution")
        if not isinstance(attribution, dict):
            return
        self._add_phase_e_root_cause(add, attribution, case_type)
        primary = self._decision_primary_detail(attribution, case_type)
        if primary and primary.get("target") and primary.get("target") != "UNKNOWN":
            importance = self._to_float(primary.get("importance")) or 0.0
            add(
                primary.get("target"),
                primary.get("target_type") or self._candidate_type(primary.get("target")),
                min(0.55, 0.20 + importance * 0.35),
                self._decision_detail_text(primary, attribution, case_type),
            )
        for secondary in self._decision_secondary_details(attribution, case_type)[:3]:
            target = secondary.get("target")
            if not target or target == "UNKNOWN":
                continue
            importance = self._to_float(secondary.get("importance")) or 0.0
            add(
                target,
                secondary.get("target_type") or self._candidate_type(target),
                min(0.32, 0.10 + importance * 0.22),
                self._decision_detail_text(secondary, attribution, case_type),
            )
        if primary.get("target") == "UNKNOWN":
            add(
                "UNKNOWN",
                "UNKNOWN",
                0.22,
                "Decision Attribution could not identify a supported primary factor",
            )

    def _add_phase_e_root_cause(self, add, attribution, case_type):
        root = self._decision_root_cause(attribution)
        root_causes = self._list(root.get("root_causes"))
        for cause in root_causes[:4]:
            if not isinstance(cause, dict):
                continue
            target = cause.get("target")
            if not target or target == "UNKNOWN":
                continue
            importance = self._to_float(cause.get("importance")) or 0.0
            root_score = min(0.78, 0.28 + importance * 0.55)
            if target == "DecisionEngine" and root.get("decision_gate") not in {
                "BUY Guard",
                "RankBlocker",
                "RiskPenalty",
                "MajorPenalty",
                "Confidence Gate",
                "Decision Rule",
            }:
                root_score = min(root_score, 0.24)
            add(
                target,
                self._candidate_type(target),
                root_score,
                self._root_cause_detail_text(cause, root, case_type),
            )

    def _add_bloodline_root_cause(self, add, horse, case_type):
        root = horse.get("bloodline_root_cause")
        if not isinstance(root, dict) or not root.get("bloodline_root_relevant"):
            return
        for cause in self._list(root.get("bloodline_root_causes"))[:4]:
            if not isinstance(cause, dict):
                continue
            category = cause.get("category") or "UNKNOWN"
            target = f"BloodlineEvaluator:{category}" if category != "UNKNOWN" else "UNKNOWN"
            importance = self._to_float(cause.get("importance")) or 0.0
            add(
                target,
                "Knowledge" if category not in {"UNKNOWN"} else "UNKNOWN",
                min(0.82, 0.34 + importance * 0.48),
                self._bloodline_root_text(cause, root, case_type),
            )

    def _decision_root_cause(self, attribution):
        if not isinstance(attribution, dict):
            return {}
        root = attribution.get("decision_root_cause")
        return root if isinstance(root, dict) else {}

    def _decision_primary_detail(self, attribution, case_type):
        if not isinstance(attribution, dict):
            return {}
        if case_type == "FP":
            detail = attribution.get("primary_supporter")
        else:
            detail = attribution.get("primary_blocker")
        return detail if isinstance(detail, dict) else {}

    def _decision_secondary_details(self, attribution, case_type):
        if not isinstance(attribution, dict):
            return []
        if case_type == "FP":
            value = attribution.get("secondary_supporters")
        else:
            value = attribution.get("secondary_blockers")
        return [item for item in self._list(value) if isinstance(item, dict)]

    def _decision_specific_blocker(self, attribution):
        if not isinstance(attribution, dict):
            return ""
        for key in [
            "rank_blocker",
            "risk_blocker",
            "major_penalty_blocker",
            "confidence_blocker",
            "score_blocker",
            "relative_evaluation_blocker",
        ]:
            detail = attribution.get(key)
            if isinstance(detail, dict) and detail.get("target"):
                return detail.get("effect") or key
        return ""

    def _decision_detail_text(self, detail, attribution, case_type):
        reason = detail.get("reason") or "Decision Attribution factor"
        distance = attribution.get("distance_to_buy")
        confidence = attribution.get("attribution_confidence")
        return (
            f"Decision Attribution {case_type}: {reason}; "
            f"distance_to_buy={distance}; confidence={confidence}"
        )

    def _root_cause_detail_text(self, cause, root, case_type):
        reason = cause.get("reason") or "Decision Root Cause factor"
        gate = root.get("decision_gate")
        confidence = cause.get("confidence") or root.get("root_confidence")
        return (
            f"Decision Root Cause {case_type}: {reason}; "
            f"decision_gate={gate}; confidence={confidence}"
        )

    def _bloodline_root_text(self, cause, root, case_type):
        paths = ", ".join(self._list(cause.get("knowledge_paths"))[:2])
        return (
            f"Bloodline Root Cause {case_type}: {cause.get('category')} "
            f"{cause.get('detail')}; confidence={cause.get('confidence')}; "
            f"knowledge={paths or 'unclassified'}"
        )

    def _score_gap(self, value, threshold, inverse=False):
        if inverse:
            gap = abs(threshold - value)
        else:
            gap = abs(value - threshold)
        return min(0.45, 0.18 + gap / 40.0)

    def _attribution_confidence(self, item):
        score = item.get("score", 0)
        evidence_count = len(self._list(item.get("evidence")))
        counter_count = len(self._list(item.get("counter_evidence")))
        if score >= 0.65 and evidence_count >= 3 and counter_count == 0:
            return "HIGH"
        if score >= 0.35 and evidence_count >= 2:
            return "MEDIUM"
        return "LOW"

    def _primary_candidate(self, candidates):
        if not candidates:
            return "UNKNOWN"
        top = candidates[0]
        if (
            top.get("target") != "UNKNOWN"
            and top.get("score", 0) >= 0.35
            and len(self._list(top.get("evidence"))) >= 2
        ):
            return top.get("target")
        return "UNKNOWN"

    def _unknown_factors(self, candidates):
        if not candidates:
            return ["no_attribution_candidates"]
        if candidates[0].get("target") == "UNKNOWN":
            return self._list(candidates[0].get("evidence"))
        factors = []
        for item in candidates:
            if item.get("confidence") == "LOW":
                factors.append(f"low_confidence:{item.get('target')}")
        return factors

    def _overall_attribution_confidence(self, candidates, primary_candidate):
        if primary_candidate == "UNKNOWN":
            return "LOW"
        levels = [item.get("confidence") for item in candidates if item.get("target") == primary_candidate]
        return levels[0] if levels else "LOW"

    def _legacy_cause_candidates(self, attribution_candidates):
        candidates = []
        for item in attribution_candidates:
            candidates.append(
                {
                    "target": item.get("target"),
                    "candidate_type": item.get("target_type") or item.get("candidate_type"),
                    "weight": item.get("score"),
                    "weight_percent": round(float(item.get("score") or 0) * 100, 1),
                    "evidence": self._list(item.get("evidence")),
                    "counter_evidence": self._list(item.get("counter_evidence")),
                    "confidence": item.get("confidence"),
                }
            )
        return candidates

    def _cause_candidates(self, horse, review_item, improvement, case_type):
        scores = defaultdict(float)
        evidence = defaultdict(list)
        text = self._combined_text(horse, review_item, improvement)

        for target in self._list(review_item.get("root_causes")):
            if target:
                scores[str(target)] += 4.0
                evidence[str(target)].append("ReviewEngine root cause")

        for target in self._list(improvement.get("improvement_targets")):
            if target:
                scores[str(target)] += 2.0
                evidence[str(target)].append("ImprovementAdvisor target")

        for name, _kind, keys, keywords in self.EVALUATOR_SIGNALS:
            if any(keyword and keyword in text for keyword in keywords):
                scores[name] += 1.5
                evidence[name].append("Explain/diagnostic text match")
            for key in keys:
                value = self._to_float(horse.get(key))
                if value is None:
                    continue
                severity = self._score_severity(key, value, case_type)
                if severity:
                    scores[name] += severity
                    evidence[name].append(f"{key}={value:g}")

        if not scores:
            scores["ReviewEngine"] = 1.0
            evidence["ReviewEngine"].append("No specific evaluator signal")

        total = sum(scores.values()) or 1.0
        candidates = []
        for target, score in sorted(scores.items(), key=lambda item: (-item[1], item[0])):
            candidate_type = self._candidate_type(target)
            candidates.append(
                {
                    "target": target,
                    "candidate_type": candidate_type,
                    "weight": round(score / total, 4),
                    "weight_percent": round(score / total * 100, 1),
                    "evidence": self._unique(evidence[target])[:5],
                }
            )
        return candidates

    def _score_severity(self, key, value, case_type):
        if key == "decision_score":
            if case_type == "FN" and value < 0.8:
                return min(3.0, (0.8 - value) * 10)
            if case_type == "FP" and value >= 0.8:
                return 1.0
            return 0.0
        if case_type == "FN":
            if value <= -5:
                return 3.0
            if value <= 0:
                return 2.0
            if value < 10:
                return 1.0
        if case_type == "FP":
            if value >= 30:
                return 2.5
            if value >= 20:
                return 1.5
        return 0.0

    def _merge_candidates(self, database, candidates):
        records = database.get("records")
        if not isinstance(records, list):
            records = []

        by_id = {
            item.get("candidate_id"): item
            for item in records
            if isinstance(item, dict) and item.get("candidate_id")
        }

        current_ids = {candidate.get("candidate_id") for candidate in candidates}
        current_race_ids = {
            candidate.get("race_id") for candidate in candidates if candidate.get("race_id")
        }
        now = self._now()
        for existing in records:
            if not isinstance(existing, dict):
                continue
            candidate_id = existing.get("candidate_id")
            if existing.get("race_id") not in current_race_ids:
                continue
            if candidate_id in current_ids or existing.get("ranking_active") is False:
                continue
            existing["ranking_active"] = False
            existing["resolution_status"] = "RESOLVED_BY_CURRENT_BASELINE"
            existing["resolved_by_implementation_id"] = self.CURRENT_BASELINE_IMPLEMENTATION_ID
            existing["resolved_date"] = now
            existing["updated_at"] = now

        for candidate in candidates:
            candidate_id = candidate.get("candidate_id")
            if candidate_id in by_id:
                existing = by_id[candidate_id]
                existing.update(candidate)
                existing["created_at"] = existing.get("created_at") or candidate.get("created_at")
                existing["ranking_active"] = True
                existing["resolution_status"] = "UNRESOLVED"
                existing["resolved_by_implementation_id"] = ""
                existing["resolved_date"] = ""
                existing["updated_at"] = now
            else:
                records.append(candidate)
                by_id[candidate_id] = candidate

        database["records"] = sorted(
            records,
            key=lambda item: (
                str(item.get("race_id") or ""),
                str(item.get("horse") or ""),
                str(item.get("case_type") or ""),
            ),
        )
        database["aggregates"] = self._aggregates(self._active_records(database["records"]))
        database["updated_at"] = now
        return database

    def _aggregates(self, records):
        groups = {}
        for record in records:
            attribution_items = self._list(record.get("attribution_candidates"))
            if not attribution_items:
                attribution_items = self._list(record.get("cause_candidates"))
            primary = record.get("primary_candidate") or "UNKNOWN"
            for candidate in attribution_items:
                target = candidate.get("target")
                if not target:
                    continue
                candidate_type = candidate.get("target_type") or candidate.get("candidate_type")
                key = f"{candidate_type}::{target}"
                group = groups.setdefault(
                    key,
                    {
                        "aggregate_id": key,
                        "target": target,
                        "candidate_type": candidate_type,
                        "occurrences": 0,
                        "primary_count": 0,
                        "secondary_count": 0,
                        "fn_count": 0,
                        "fp_count": 0,
                        "races": [],
                        "horses": [],
                        "score_total": 0.0,
                        "evidence_total": 0,
                        "counter_evidence_total": 0,
                        "confidence_counts": Counter(),
                        "status": "NEW",
                    },
                )
                group["occurrences"] += 1
                if target == primary:
                    group["primary_count"] += 1
                elif target != "UNKNOWN":
                    group["secondary_count"] += 1
                group["fn_count"] += 1 if record.get("fn") else 0
                group["fp_count"] += 1 if record.get("fp") else 0
                group["score_total"] += float(candidate.get("score", candidate.get("weight")) or 0)
                group["evidence_total"] += len(self._list(candidate.get("evidence")))
                group["counter_evidence_total"] += len(self._list(candidate.get("counter_evidence")))
                group["confidence_counts"][candidate.get("confidence") or "UNKNOWN"] += 1
                self._append_unique(group["races"], record.get("race_id"))
                self._append_unique(group["horses"], record.get("horse"))

        for group in groups.values():
            group["average_attribution_score"] = round(
                group.pop("score_total") / max(1, group["occurrences"]),
                3,
            )
            group["average_weight_percent"] = round(group["average_attribution_score"] * 100, 1)
            group["evidence_count"] = group.pop("evidence_total")
            group["counter_evidence_count"] = group.pop("counter_evidence_total")
            confidence_counts = group.pop("confidence_counts")
            group["confidence_counts"] = dict(confidence_counts)
            group["priority"] = self._aggregate_priority(group)
            group["recurrence_count"] = group["occurrences"]
        return sorted(
            groups.values(),
            key=lambda item: (
                -item.get("primary_count", 0),
                -item.get("average_attribution_score", 0),
                -item.get("evidence_count", 0),
                item.get("target", ""),
            ),
        )

    def _write_report(self, database):
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        records = self._list(database.get("records"))
        active_records = self._active_records(records)
        inactive_records = [
            item
            for item in records
            if isinstance(item, dict) and item.get("ranking_active") is False
        ]
        aggregates = self._list(database.get("aggregates"))
        lines = [
            "# Improvement Candidates",
            "",
            f"- Updated: {database.get('updated_at')}",
            f"- Records: {len(records)}",
            f"- Active Records: {len(active_records)}",
            f"- Inactive Historical Records: {len(inactive_records)}",
            f"- Aggregates: {len(aggregates)}",
            "",
            "## Aggregate Summary",
            "",
            "| Target | Type | Occurrences | Primary | Secondary | FN | FP | Avg Attribution | Evidence | Counter | Priority | Status |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
        for item in aggregates:
            lines.append(
                "| {target} | {candidate_type} | {occurrences} | {primary_count} | "
                "{secondary_count} | {fn_count} | {fp_count} | {average_attribution_score:.3f} | "
                "{evidence_count} | {counter_evidence_count} | {priority} | {status} |".format(
                    **item
                )
            )
        lines.extend(
            [
                "",
                "## Candidate Records",
                "",
                "| Race | Horse | Case | Decision | Finish | Primary | Confidence | Evidence | Counter | Top Attribution |",
                "|---|---|---|---|---:|---|---|---:|---:|---|",
            ]
        )
        for item in active_records:
            causes = ", ".join(
                f"{cause.get('target')} {float(cause.get('score') or cause.get('weight') or 0):.2f}"
                for cause in self._list(item.get("attribution_candidates") or item.get("cause_candidates"))[:3]
            )
            lines.append(
                f"| {item.get('race_id')} | {item.get('horse')} | "
                f"{item.get('case_type')} | {item.get('decision')} | "
                f"{item.get('actual_finish')} | {item.get('primary_candidate')} | "
                f"{item.get('attribution_confidence')} | {item.get('evidence_count')} | "
                f"{item.get('counter_evidence_count')} | {causes} |"
            )
        lines.extend(["", "## UNKNOWN Records", ""])
        unknown_records = [item for item in active_records if item.get("primary_candidate") == "UNKNOWN"]
        if not unknown_records:
            lines.append("- None")
        else:
            for item in unknown_records:
                reasons = ", ".join(str(value) for value in self._list(item.get("unknown_factors")))
                lines.append(
                    f"- {item.get('race_id')} {item.get('horse')} {item.get('case_type')}: {reasons}"
                )
        lines.extend(["", "## Resolved Historical Records", ""])
        if not inactive_records:
            lines.append("- None")
        else:
            for item in inactive_records:
                lines.append(
                    f"- {item.get('race_id')} {item.get('horse')} {item.get('case_type')}: "
                    f"{item.get('resolution_status')} by {item.get('resolved_by_implementation_id')}"
                )
        lines.extend(
            [
                "",
                "## Guardrails",
                "",
                "- This file is for human review only.",
                "- No evaluator, decision, score, knowledge, or CSV setting is changed by this engine.",
                "- Repeated candidate records are aggregated for prioritization only.",
            ]
        )
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _summary(self, database, candidates, warnings):
        records = self._list(database.get("records"))
        active_records = self._active_records(records)
        aggregates = self._list(database.get("aggregates"))
        cases = Counter(item.get("case_type") for item in active_records)
        return {
            "generated_candidates": len(candidates),
            "stored_candidates": len(records),
            "active_candidates": len(active_records),
            "inactive_candidates": len(records) - len(active_records),
            "fn_count": cases.get("FN", 0),
            "fp_count": cases.get("FP", 0),
            "top_aggregates": aggregates[:5],
            "warnings": warnings,
        }

    def _active_records(self, records):
        return [
            item
            for item in self._list(records)
            if isinstance(item, dict) and item.get("ranking_active") is not False
        ]

    def _load_database(self):
        if not self.db_path.exists():
            return {
                "version": "1.0",
                "engine": "LearningCandidateEngine",
                "records": [],
                "aggregates": [],
                "updated_at": None,
            }
        try:
            return json.loads(self.db_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "version": "1.0",
                "engine": "LearningCandidateEngine",
                "records": [],
                "aggregates": [],
                "updated_at": None,
                "warnings": ["existing_database_unreadable"],
            }

    def _save_database(self, database):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.write_text(
            json.dumps(database, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _horse_rows(self, race, ranked_results):
        rows = ranked_results if isinstance(ranked_results, list) else []
        if rows:
            return rows
        rows = race.get("horses")
        return rows if isinstance(rows, list) else []

    def _result_rows(self, race, official):
        for source in [
            official.get("horse_results"),
            self._nested_get(official, ["race_result", "horse_results"]),
            race.get("horse_results"),
        ]:
            if isinstance(source, list) and source:
                return source
        return []

    def _race_context(self, race, official, race_id):
        race_result = official.get("race_result") if isinstance(official, dict) else {}
        if not isinstance(race_result, dict):
            race_result = {}
        parsed = self._parse_race_id(race_id)
        context = {
            "race_date": self._first_value(
                race.get("race_date"),
                race_result.get("race_date"),
                parsed.get("race_date"),
            ),
            "racecourse": self._first_value(
                race.get("racecourse"),
                race_result.get("racecourse"),
                parsed.get("racecourse"),
            ),
            "race_number": self._first_value(
                race.get("race_number"),
                race_result.get("race_number"),
                parsed.get("race_number"),
            ),
            "surface": self._first_value(race.get("surface"), race_result.get("surface")),
            "distance": self._first_value(race.get("distance"), race_result.get("distance")),
            "track_condition": self._first_value(
                race.get("track_condition"),
                race_result.get("track_condition"),
                race_result.get("track_condition_raw"),
            ),
            "race_class": self._first_value(race.get("race_class"), race_result.get("race_class")),
        }
        return {key: (value if value not in (None, "") else "unknown") for key, value in context.items()}

    def _horse_context(self, horse, result):
        return {
            "racecourse": self._first_value(horse.get("racecourse"), result.get("racecourse")),
            "surface": self._first_value(horse.get("surface"), result.get("surface")),
            "distance": self._first_value(horse.get("distance"), result.get("distance")),
            "track_condition": self._first_value(
                horse.get("track_condition"),
                result.get("track_condition"),
            ),
            "race_class": self._first_value(horse.get("race_class"), result.get("race_class")),
        }

    def _parse_race_id(self, race_id):
        parts = str(race_id or "").split("_")
        if len(parts) >= 4 and parts[0] == "race":
            return {
                "race_date": parts[1],
                "racecourse": parts[2],
                "race_number": parts[3],
            }
        return {}

    def _first_value(self, *values):
        for value in values:
            if value not in (None, ""):
                return value
        return None

    def _result_map(self, rows):
        mapping = {}
        for row in self._list(rows):
            if not isinstance(row, dict):
                continue
            name = row.get("horse_name") or row.get("horse")
            if not name:
                continue
            mapping[str(name)] = row
            mapping[self._normalize_name(name)] = row
        return mapping

    def _review_map(self, rows):
        mapping = {}
        for row in self._list(rows):
            if not isinstance(row, dict):
                continue
            name = row.get("horse_name") or row.get("horse")
            if not name:
                continue
            mapping[str(name)] = row
            mapping[self._normalize_name(name)] = row
        return mapping

    def _lookup_result(self, mapping, name):
        if not isinstance(mapping, dict):
            return {}
        if name in mapping:
            return mapping.get(name) or {}
        return mapping.get(self._normalize_name(name), {}) or {}

    def _case_type(self, decision, finish):
        if finish is None:
            return None
        if finish <= 3 and decision != "BUY":
            return "FN"
        if decision == "BUY" and finish >= 4:
            return "FP"
        return None

    def _explain_summary(self, horse, review_item):
        summary = horse.get("summary") or review_item.get("explain_summary") or ""
        factors = []
        for key in ["strengths", "weaknesses", "risks", "warnings"]:
            factors.extend(str(item) for item in self._list(horse.get(key))[:3])
        return self._shorten(" / ".join([str(summary)] + factors), 500)

    def _review_summary(self, review_item, case_type, finish):
        root_causes = ", ".join(str(item) for item in self._list(review_item.get("root_causes")))
        status = review_item.get("review_status") or ""
        return self._shorten(f"{case_type}: finish={finish}; status={status}; causes={root_causes}", 300)

    def _missed_candidate(self, case_type, decision, finish):
        if case_type == "FN":
            return f"Non-BUY horse finished in Top3: decision={decision}, finish={finish}"
        return f"BUY horse finished outside Top3: finish={finish}"

    def _confidence(self, horse, review_item):
        confidence = horse.get("confidence")
        if confidence is None:
            confidence = review_item.get("confidence")
        return confidence if confidence is not None else {}

    def _risk(self, horse, review_item):
        risks = []
        for source in [horse, review_item]:
            risks.extend(str(item) for item in self._list(source.get("risks")))
            factors = source.get("explain_factors")
            if isinstance(factors, dict):
                risks.extend(str(item) for item in self._list(factors.get("risks")))
        diagnostics = horse.get("decision_diagnostics")
        if isinstance(diagnostics, dict):
            risks.extend(str(item) for item in self._list(diagnostics.get("risk_items")))
            risks.extend(str(item) for item in self._list(diagnostics.get("major_risks")))
        return self._unique(risks)

    def _priority(self, case_type, finish, cause_candidates):
        top_weight = max(
            [float(item.get("weight") or 0) for item in self._list(cause_candidates)] or [0]
        )
        if case_type == "FN" and finish == 1:
            return "high"
        if case_type == "FN":
            return "medium" if top_weight < 0.5 else "high"
        if case_type == "FP" and finish is not None and finish >= 8:
            return "medium"
        return "low"

    def _aggregate_priority(self, group):
        occurrences = int(group.get("occurrences") or 0)
        fn_count = int(group.get("fn_count") or 0)
        fp_count = int(group.get("fp_count") or 0)
        if occurrences >= 8 or fn_count >= 5:
            return "P5"
        if occurrences >= 5 or fn_count >= 3 or fp_count >= 4:
            return "P4"
        if occurrences >= 3:
            return "P3"
        if occurrences >= 2:
            return "P2"
        return "P1"

    def _candidate_type(self, target):
        for name, kind, _keys, _keywords in self.EVALUATOR_SIGNALS:
            if target == name:
                return kind
        if str(target).endswith("Evaluator"):
            return "Evaluator"
        if "Knowledge" in str(target) or "Bias" in str(target):
            return "Knowledge"
        if "Decision" in str(target) or "Confidence" in str(target):
            return "Decision"
        return "Other"

    def _candidate_id(self, race_id, horse_name, case_type):
        raw = f"{race_id}|{self._normalize_name(horse_name)}|{case_type}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return f"lc_{digest}"

    def _combined_text(self, horse, review_item, improvement):
        values = []
        for key in [
            "summary",
            "explain_summary",
            "decision_reason",
            "lap_comment",
            "shape_comment",
            "impact_comment",
        ]:
            if horse.get(key):
                values.append(str(horse.get(key)))
        for key in ["weaknesses", "risks", "warnings", "decision_risks"]:
            values.extend(str(item) for item in self._list(horse.get(key)))

        factors = review_item.get("explain_factors")
        if isinstance(factors, dict):
            for key in ["weaknesses", "risks", "warnings"]:
                values.extend(str(item) for item in self._list(factors.get(key)))
        values.extend(str(item) for item in self._list(review_item.get("root_causes")))
        values.extend(str(item) for item in self._list(improvement.get("improvement_targets")))
        return " ".join(values)

    def _nested_get(self, data, keys):
        item = data
        for key in keys:
            if not isinstance(item, dict):
                return None
            item = item.get(key)
        return item

    def _normalize_name(self, value):
        text = unicodedata.normalize("NFKC", str(value or ""))
        return "".join(text.split())

    def _to_int(self, value):
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None

    def _to_float(self, value):
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _unique(self, values):
        unique = []
        for value in values:
            if value not in (None, "") and value not in unique:
                unique.append(value)
        return unique

    def _append_unique(self, values, value):
        if value not in (None, "") and value not in values:
            values.append(value)

    def _shorten(self, text, limit):
        value = str(text or "").strip()
        return value if len(value) <= limit else value[: limit - 3] + "..."

    def _now(self):
        return datetime.now(timezone.utc).isoformat()
