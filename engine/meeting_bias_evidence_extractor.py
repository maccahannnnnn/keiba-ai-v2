"""Extract MeetingBias evidence from reviewed races without scoring changes."""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine.meeting_bias_candidate_ranker import MeetingBiasCandidateRanker
from review.meeting_bias_read_only_collector import MeetingBiasReadOnlyCollector
from review.meeting_stage_resolver import MeetingStageResolver


class MeetingBiasEvidenceExtractor:
    """Create race-pattern evidence and candidate records for MeetingBias."""

    VERSION = "phase_g_step2_v1"
    BASELINE_DATES = {"20260705", "20260711", "20260712"}
    DEFAULT_CANDIDATE_DB_PATH = Path("learning/meeting_bias_candidates.json")
    DEFAULT_IMPROVEMENT_DB_PATH = None
    DEFAULT_REPORT_PATH = Path("reports/meeting_bias/meeting_bias_candidate_report_v1.md")
    DEFAULT_METRICS_PATH = Path("reports/meeting_bias/meeting_bias_diagnostic_safety_v1.json")
    DEFAULT_EVIDENCE_PATH = Path("reports/meeting_bias/meeting_bias_read_only_evidence_v1.json")
    DEFAULT_SOURCE_MANIFEST_PATH = Path("reports/meeting_bias/meeting_bias_source_manifest_v1.json")
    BASELINE_EXPECTED = {
        "races": 22,
        "horses": 304,
        "BUY": 45,
        "CAUTION": 88,
        "PASS": 171,
        "FN": 55,
        "FP": 34,
        "BUY3": 11,
        "Top5_3": 30,
    }

    def __init__(
        self,
        candidate_db_path=None,
        improvement_db_path=None,
        report_path=None,
        metrics_path=None,
        evidence_path=None,
        source_manifest_path=None,
        collector=None,
    ):
        self.candidate_db_path = Path(candidate_db_path) if candidate_db_path else self.DEFAULT_CANDIDATE_DB_PATH
        self.improvement_db_path = Path(improvement_db_path) if improvement_db_path else self.DEFAULT_IMPROVEMENT_DB_PATH
        self.report_path = Path(report_path) if report_path else self.DEFAULT_REPORT_PATH
        self.metrics_path = Path(metrics_path) if metrics_path else self.DEFAULT_METRICS_PATH
        self.evidence_path = Path(evidence_path) if evidence_path else self.DEFAULT_EVIDENCE_PATH
        self.source_manifest_path = Path(source_manifest_path) if source_manifest_path else self.DEFAULT_SOURCE_MANIFEST_PATH
        self.ranker = MeetingBiasCandidateRanker()
        self.collector = collector or MeetingBiasReadOnlyCollector()

    def extract(self, analysis_dir="data/analysis", results_dir="data/results"):
        started = datetime.now(timezone.utc).isoformat()
        collected = self.collector.collect()
        race_records = collected.get("race_records", [])
        horse_rows = collected.get("horse_rows", [])
        errors = collected.get("errors", [])
        baseline = self._baseline_metrics(horse_rows)
        evidence = []
        for race in race_records:
            evidence.extend(self._race_evidence(race))
        readiness = self._diagnostic_readiness_from_evidence(evidence)
        for row in evidence:
            row["shadow_testable"] = readiness.get("level")
            row["diagnostic_readiness_level"] = readiness.get("level")
            row["diagnostic_readiness_reason"] = readiness.get("reason")
            row["diagnostic_missing_conditions"] = readiness.get("missing_conditions", [])
            row["diagnostic_comparable_stage_count"] = readiness.get("comparable_stage_count")
            row["diagnostic_target_meeting_count"] = readiness.get("target_meeting_count")
        evidence = [self._with_provenance(row, collected) for row in evidence]
        ranking = self.ranker.rank(evidence)
        candidate_db = {
            "version": self.VERSION,
            "generated_at": started,
            "evidence_origin": "DAILY_REVIEW",
            "validated": False,
            "scoring_enabled": False,
            "collector_version": collected.get("collector_version"),
            "replay_mode": collected.get("replay_mode"),
            "evaluator_reexecuted": collected.get("evaluator_reexecuted"),
            "decision_recalculated": collected.get("decision_recalculated"),
            "buy_recalculated": collected.get("buy_recalculated"),
            "production_adapter_used": collected.get("production_adapter_used"),
            "result_data_used_as_evaluation_input": collected.get("result_data_used_as_evaluation_input"),
            "baseline": baseline,
            "reviewed_races": len(race_records),
            "reviewed_horses": len(horse_rows),
            "evidence": evidence,
            "candidates": ranking.get("candidates", []),
            "top_candidate": ranking.get("top_candidate"),
            "source_manifest": collected.get("source_manifest", []),
            "errors": errors,
            "warnings": self._warnings(baseline, errors),
            "diagnostic_readiness": readiness,
        }
        self._write_json(self.evidence_path, candidate_db)
        self._write_json(self.source_manifest_path, collected.get("source_manifest", []))
        learning_update = self._learning_write_disabled(candidate_db)
        metrics = self._metrics(candidate_db, learning_update)
        self._write_json(self.metrics_path, metrics)
        self._write_report(candidate_db, metrics)
        return metrics

    def _collect(self, complete_sets):
        raise RuntimeError("MeetingBiasEvidenceExtractor uses MeetingBiasReadOnlyCollector; direct collection is disabled.")

    def _race_evidence(self, race):
        race_id = race.get("race_id")
        analysis = race.get("analysis") or {}
        official = race.get("official") or {}
        race_result = official.get("race_result") or {}
        horse_results = [
            row for row in self._list(official.get("horse_results"))
            if self._to_int(row.get("finish_position")) is not None
        ]
        top3 = [
            row for row in horse_results
            if self._to_int(row.get("finish_position")) in {1, 2, 3}
        ]
        top3.sort(key=lambda row: self._to_int(row.get("finish_position")) or 99)
        if not top3:
            return []

        ranked_map = self._analysis_name_map(analysis.get("ranked_results"))
        last3f_ranks = self._last3f_ranks(horse_results)
        race_context = self._race_context(race_id, race_result, analysis)
        pattern_rows = []
        pattern_rows.extend(self._frame_patterns(top3, ranked_map, race_context))
        pattern_rows.extend(self._position_patterns(top3, ranked_map, race_context))
        pattern_rows.extend(self._last3f_patterns(top3, ranked_map, race_context, last3f_ranks))
        if not pattern_rows:
            pattern_rows.append(
                self._evidence(
                    race_context,
                    "no_clear_meeting_bias_pattern",
                    [],
                    self._horse_briefs(top3, ranked_map, last3f_ranks),
                    "DATA_INSUFFICIENT",
                    ["No single lane, position, or last3F pattern had enough support."],
                )
            )
        return pattern_rows

    def _frame_patterns(self, top3, ranked_map, context):
        inside = [row for row in top3 if (self._to_int(row.get("frame_number")) or 99) <= 3]
        outside = [row for row in top3 if (self._to_int(row.get("frame_number")) or 0) >= 6]
        rows = []
        if len(inside) >= 2:
            rows.append(self._pattern_from_horses(context, "inside_lane_advantage", inside, top3, ranked_map))
        if len(outside) >= 2:
            rows.append(self._pattern_from_horses(context, "outside_lane_advantage", outside, top3, ranked_map))
        return rows

    def _position_patterns(self, top3, ranked_map, context):
        front = [row for row in top3 if (self._to_int(row.get("fourth_corner_position")) or 99) <= 4]
        middle = [
            row for row in top3
            if 5 <= (self._to_int(row.get("fourth_corner_position")) or 99) <= 8
        ]
        closer = [row for row in top3 if (self._to_int(row.get("fourth_corner_position")) or 0) >= 9]
        rows = []
        if len(front) >= 2:
            rows.append(self._pattern_from_horses(context, "front_position_advantage", front, top3, ranked_map))
        if len(middle) >= 2:
            rows.append(self._pattern_from_horses(context, "middle_position_advantage", middle, top3, ranked_map))
        if len(closer) >= 2:
            rows.append(self._pattern_from_horses(context, "closer_position_advantage", closer, top3, ranked_map))
        return rows

    def _last3f_patterns(self, top3, ranked_map, context, last3f_ranks):
        fast_late = [
            row for row in top3
            if (last3f_ranks.get(self._norm(row.get("horse_name"))) or 99) <= 5
        ]
        if len(fast_late) >= 2:
            return [self._pattern_from_horses(context, "strong_late_3f_advantage", fast_late, top3, ranked_map, last3f_ranks)]
        return []

    def _pattern_from_horses(self, context, pattern, supporting, top3, ranked_map, last3f_ranks=None):
        supporting_keys = {self._norm(row.get("horse_name")) for row in supporting}
        counter = [row for row in top3 if self._norm(row.get("horse_name")) not in supporting_keys]
        responsibility, secondary, notes = self._responsibility(context, pattern, supporting, counter)
        return self._evidence(
            context,
            pattern,
            self._horse_briefs(supporting, ranked_map, last3f_ranks or {}),
            self._horse_briefs(counter, ranked_map, last3f_ranks or {}),
            responsibility,
            notes,
            secondary_responsibilities=secondary,
        )

    def _evidence(
        self,
        context,
        pattern,
        supporting_horses,
        counterexample_horses,
        responsibility,
        notes,
        secondary_responsibilities=None,
    ):
        support_count = len(supporting_horses)
        counter_count = len(counterexample_horses)
        fn_count = sum(1 for horse in supporting_horses if horse.get("decision") != "BUY" and horse.get("finish_position") in {1, 2, 3})
        fp_count = sum(1 for horse in supporting_horses if horse.get("decision") == "BUY" and horse.get("finish_position") not in {1, 2, 3})
        evidence_strength = self._evidence_strength(support_count, counter_count, fn_count, responsibility)
        data_completeness = self._data_completeness(context)
        evidence_id = self._evidence_id(context.get("race_id"), pattern)
        return {
            "evidence_id": evidence_id,
            "race_id": context.get("race_id"),
            "race_date": context.get("race_date"),
            "racecourse": context.get("racecourse"),
            "race_number": context.get("race_number"),
            "surface": context.get("surface"),
            "distance": context.get("distance"),
            "distance_category": context.get("distance_category"),
            "track_condition": context.get("track_condition"),
            "meeting_stage": context.get("meeting_stage"),
            "meeting_stage_source": context.get("meeting_stage_source"),
            "meeting_stage_confidence": context.get("meeting_stage_confidence"),
            "course_configuration": context.get("course_configuration"),
            "course_configuration_source": context.get("course_configuration_source"),
            "observed_pattern": pattern,
            "supporting_horses": supporting_horses,
            "counterexample_horses": counterexample_horses,
            "support_count": support_count,
            "counterexample_count": counter_count,
            "fn_count": fn_count,
            "fp_count": fp_count,
            "top3_count": 3,
            "inside_result": self._pattern_result(pattern, "inside"),
            "outside_result": self._pattern_result(pattern, "outside"),
            "front_result": self._pattern_result(pattern, "front"),
            "closer_result": self._pattern_result(pattern, "closer"),
            "last_3f_result": self._pattern_result(pattern, "late_3f"),
            "manual_track_bias": context.get("manual_track_bias"),
            "track_bias_overlap": self._overlap_level(pattern, "TrackBias", context),
            "course_overlap": self._overlap_level(pattern, "CourseKnowledge", context),
            "race_shape_overlap": self._overlap_level(pattern, "RaceShape", context),
            "pace_overlap": self._overlap_level(pattern, "Pace", context),
            "bloodline_overlap": "LOW",
            "primary_responsibility": responsibility,
            "secondary_responsibilities": secondary_responsibilities or [],
            "meeting_bias_hypothesis": self._hypothesis(context, pattern, responsibility),
            "evidence_strength": evidence_strength,
            "data_completeness": data_completeness,
            "shadow_testable": responsibility in {"MEETING_BIAS_PRIMARY", "MULTIPLE_CAUSES"} and data_completeness != "LOW",
            "notes": notes,
        }

    def _responsibility(self, context, pattern, supporting, counter):
        secondary = []
        notes = []
        if pattern == "no_clear_meeting_bias_pattern":
            return "DATA_INSUFFICIENT", [], notes
        if context.get("meeting_stage_source") == "UNKNOWN":
            return "DATA_INSUFFICIENT", [], ["meeting stage is unavailable"]
        if pattern in {"inside_lane_advantage", "outside_lane_advantage"}:
            secondary.append("TrackBias")
            if context.get("manual_track_bias"):
                return "TRACK_BIAS_PRIMARY", secondary, ["manual TrackBias can explain lane tendency"]
        if pattern in {"front_position_advantage", "closer_position_advantage", "strong_late_3f_advantage"}:
            secondary.extend(["RaceShape", "Pace"])
        if len(supporting) >= 3:
            return "MULTIPLE_CAUSES", ["MeetingBias"] + secondary, ["all Top3 share this race pattern"]
        if context.get("meeting_stage_source") in {"EXPLICIT", "MEETING_DAY", "MEETING_WEEK", "RELATIVE_OBSERVED_SEQUENCE"}:
            return "MEETING_BIAS_PRIMARY", secondary, ["meeting metadata is available and pattern has multiple supports"]
        return "MULTIPLE_CAUSES", ["MeetingBias"] + secondary, ["meeting stage is derived, so keep as hypothesis"]

    def _race_context(self, race_id, race_result, analysis):
        race_output = analysis.get("race_output") if isinstance(analysis.get("race_output"), dict) else {}
        meeting_bias_result = analysis.get("meeting_bias_result") if isinstance(analysis.get("meeting_bias_result"), dict) else {}
        stage = (
            meeting_bias_result.get("selected_meeting_stage")
            or (meeting_bias_result.get("meeting_bias") or {}).get("meeting_stage")
            or race_output.get("meeting_stage")
            or "UNKNOWN"
        )
        source = "UNKNOWN"
        if race_output.get("meeting_stage_source"):
            source = race_output.get("meeting_stage_source")
        elif race_output.get("meeting_stage"):
            source = "EXPLICIT"
        elif race_output.get("meeting_week"):
            source = "MEETING_WEEK"
        elif race_output.get("meeting_day") or race_output.get("meeting_day_number"):
            source = "MEETING_DAY"
        elif stage not in {"", None, "UNKNOWN"}:
            source = "DERIVED_OR_ENGINE"
        return {
            "race_id": race_id,
            "race_date": race_result.get("race_date") or self._race_id_part(race_id, 1),
            "racecourse": race_result.get("racecourse") or self._race_id_part(race_id, 2),
            "race_number": race_result.get("race_number") or self._race_id_part(race_id, 3),
            "surface": race_result.get("surface") or race_output.get("surface"),
            "distance": self._to_int(race_result.get("distance") or race_output.get("distance")),
            "distance_category": self._distance_category(race_result.get("distance") or race_output.get("distance")),
            "track_condition": race_result.get("track_condition") or race_output.get("track_condition"),
            "meeting_stage": stage or "UNKNOWN",
            "meeting_stage_source": source,
            "meeting_stage_confidence": race_output.get("meeting_stage_derivation_confidence") or self._stage_confidence(source),
            "course_configuration": race_output.get("course_configuration") or "UNKNOWN",
            "course_configuration_source": "CSV_OR_ANALYSIS" if race_output.get("course_configuration") else "UNKNOWN",
            "manual_track_bias": race_output.get("manual_track_bias") or analysis.get("manual_track_bias"),
            "race_shape": (analysis.get("race_structure") or {}).get("race_shape") or analysis.get("race_shape"),
        }

    def _horse_briefs(self, horses, ranked_map, last3f_ranks):
        briefs = []
        for result in horses:
            name = result.get("horse_name")
            ranked = ranked_map.get(self._norm(name), {})
            briefs.append(
                {
                    "horse_name": name,
                    "finish_position": self._to_int(result.get("finish_position")),
                    "frame_number": self._to_int(result.get("frame_number")),
                    "horse_number": self._to_int(result.get("horse_number")),
                    "fourth_corner_position": self._to_int(result.get("fourth_corner_position")),
                    "last_3f": self._to_float(result.get("last_3f")),
                    "last_3f_rank": last3f_ranks.get(self._norm(name)),
                    "decision": ranked.get("decision"),
                    "ai_rank": ranked.get("final_rank") or ranked.get("ai_rank"),
                    "running_style": ranked.get("pace_style") or ranked.get("running_style"),
                    "final_score": self._to_float(ranked.get("final_score")),
                    "adjusted_score": self._to_float(ranked.get("adjusted_score")),
                    "shape_score": self._to_float(ranked.get("shape_score")),
                    "track_bias_score": self._to_float(ranked.get("track_bias_score")),
                }
            )
        return briefs

    def _metrics(self, candidate_db, learning_update):
        evidence = candidate_db.get("evidence") or []
        candidates = candidate_db.get("candidates") or []
        baseline = candidate_db.get("baseline") or {}
        responsibility_counts = Counter(row.get("primary_responsibility") or "UNKNOWN" for row in evidence)
        surface_counts = Counter(row.get("surface") or "UNKNOWN" for row in evidence)
        course_counts = Counter(row.get("racecourse") or "UNKNOWN" for row in evidence)
        date_counts = Counter(row.get("race_date") or "UNKNOWN" for row in evidence)
        distance_counts = Counter(row.get("distance_category") or "UNKNOWN" for row in evidence)
        pattern_counts = Counter(row.get("observed_pattern") or "UNKNOWN" for row in evidence)
        overlap_counts = {
            "track_bias": sum(1 for row in evidence if row.get("track_bias_overlap") in {"MEDIUM", "HIGH"}),
            "course": sum(1 for row in evidence if row.get("course_overlap") in {"MEDIUM", "HIGH"}),
            "race_shape": sum(1 for row in evidence if row.get("race_shape_overlap") in {"MEDIUM", "HIGH"}),
        }
        top_candidate = candidate_db.get("top_candidate") or {}
        return {
            "validation_version": self.VERSION,
            "generated_at": candidate_db.get("generated_at"),
            "baseline": baseline,
            "baseline_expected": self.BASELINE_EXPECTED,
            "baseline_match": baseline == self.BASELINE_EXPECTED,
            "reviewed_races": candidate_db.get("reviewed_races"),
            "reviewed_horses": candidate_db.get("reviewed_horses"),
            "evidence_count": len(evidence),
            "meeting_bias_primary_count": responsibility_counts.get("MEETING_BIAS_PRIMARY", 0),
            "track_bias_primary_count": responsibility_counts.get("TRACK_BIAS_PRIMARY", 0),
            "course_primary_count": responsibility_counts.get("COURSE_KNOWLEDGE_PRIMARY", 0),
            "race_shape_primary_count": responsibility_counts.get("RACE_SHAPE_PRIMARY", 0),
            "multiple_causes_count": responsibility_counts.get("MULTIPLE_CAUSES", 0),
            "data_insufficient_count": responsibility_counts.get("DATA_INSUFFICIENT", 0),
            "responsibility_counts": dict(responsibility_counts),
            "surface_counts": dict(surface_counts),
            "racecourse_counts": dict(course_counts),
            "date_counts": dict(date_counts),
            "distance_category_counts": dict(distance_counts),
            "pattern_counts": dict(pattern_counts),
            "track_bias_overlap_count": overlap_counts["track_bias"],
            "course_overlap_count": overlap_counts["course"],
            "race_shape_overlap_count": overlap_counts["race_shape"],
            "candidate_count": len(candidates),
            "shadow_ready_candidate_count": sum(1 for item in candidates if item.get("shadow_testability") == "HIGH"),
            "top_candidate_id": top_candidate.get("candidate_id") or "NO_SHADOW_CANDIDATE",
            "top_candidate_priority": top_candidate.get("priority") or "HOLD",
            "recommended_shadow_scope": top_candidate.get("recommended_shadow_scope") or {},
            "missing_required_inputs": self._missing_required_inputs(evidence),
            "learning_candidate_update": learning_update,
            "errors": candidate_db.get("errors") or [],
            "warnings": candidate_db.get("warnings") or [],
            "final_judgment": "SAFETY_FIX_COMPLETE" if not candidate_db.get("errors") else "SAFETY_FIX_INCOMPLETE",
            "recommended_next_action": self._recommended_next_action(top_candidate),
            "diagnostic_readiness": candidate_db.get("diagnostic_readiness") or {},
        }

    def _diagnostic_readiness_from_evidence(self, evidence):
        rows = []
        for row in evidence or []:
            rows.append(
                type(
                    "ResolutionLike",
                    (),
                    {
                        "meeting_stage": row.get("meeting_stage") or "UNKNOWN",
                        "racecourse": row.get("racecourse") or "",
                    },
                )()
            )
        return MeetingStageResolver().diagnostic_readiness(rows)

    def _with_provenance(self, row, collected):
        manifest = {
            item.get("race_id"): item
            for item in self._list(collected.get("source_manifest"))
            if isinstance(item, dict)
        }
        source = manifest.get(row.get("race_id"), {})
        enriched = dict(row)
        enriched.update(
            {
                "evidence_origin": "DAILY_REVIEW",
                "validated": False,
                "scoring_enabled": False,
                "source_file": source.get("source_file", ""),
                "source_version": source.get("source_version", ""),
                "source_sha256": source.get("source_sha256", ""),
                "source_evaluation_origin": source.get("source_evaluation_origin", "SAVED_REVIEW_OR_PRE_RACE_OUTPUT"),
                "replay_mode": source.get("replay_mode", collected.get("replay_mode")),
                "evaluator_reexecuted": source.get("evaluator_reexecuted", collected.get("evaluator_reexecuted")),
                "decision_recalculated": source.get("decision_recalculated", collected.get("decision_recalculated")),
                "buy_recalculated": source.get("buy_recalculated", collected.get("buy_recalculated")),
                "production_adapter_used": source.get("production_adapter_used", collected.get("production_adapter_used")),
                "result_data_used_as_evaluation_input": source.get(
                    "result_data_used_as_evaluation_input",
                    collected.get("result_data_used_as_evaluation_input"),
                ),
                "created_at": collected.get("created_at"),
                "collector_version": collected.get("collector_version"),
            }
        )
        return enriched

    def _learning_write_disabled(self, candidate_db):
        """Return a Learning proposal stub without writing Learning DB."""

        metrics_stub = {
            "reviewed_races": candidate_db.get("reviewed_races"),
            "reviewed_horses": candidate_db.get("reviewed_horses"),
            "evidence_count": len(candidate_db.get("evidence") or []),
            "candidate_count": len(candidate_db.get("candidates") or []),
            "shadow_ready_candidate_count": sum(
                1 for item in candidate_db.get("candidates") or []
                if item.get("shadow_testability") == "HIGH"
            ),
            "top_candidate_id": (candidate_db.get("top_candidate") or {}).get("candidate_id"),
            "top_candidate_priority": (candidate_db.get("top_candidate") or {}).get("priority"),
            "learning_write_enabled": False,
            "learning_write_target": "reports/meeting_bias",
            "learning_write_status": "DISABLED_BY_SAFETY_FIX",
        }
        return metrics_stub

    def _write_report(self, candidate_db, metrics):
        evidence = candidate_db.get("evidence") or []
        candidates = candidate_db.get("candidates") or []
        top_candidate = candidate_db.get("top_candidate") or {}
        lines = [
            "# MeetingBias Evidence Report",
            "",
            f"- Generated: {candidate_db.get('generated_at')}",
                f"- Validation version: {self.VERSION}",
                f"- Reviewed races: {metrics.get('reviewed_races')}",
                f"- Reviewed horses: {metrics.get('reviewed_horses')}",
                f"- Baseline match: {metrics.get('baseline_match')}",
                f"- Evidence origin: {candidate_db.get('evidence_origin')}",
                f"- Validated: {candidate_db.get('validated')}",
                f"- Scoring enabled: {candidate_db.get('scoring_enabled')}",
                f"- Replay mode: {candidate_db.get('replay_mode')}",
                f"- Production adapter used: {candidate_db.get('production_adapter_used')}",
                f"- Result data used as evaluation input: {candidate_db.get('result_data_used_as_evaluation_input')}",
                f"- Learning direct write: {metrics.get('learning_candidate_update', {}).get('learning_write_status')}",
                "",
                "## 1. Target Races",
            "",
        ]
        lines.extend([f"- {race_id}" for race_id in sorted({row.get("race_id") for row in evidence})])
        lines.extend(
            [
                "",
                "## 2. Available Meeting Information",
                "",
                f"- meeting_stage sources: {self._counter_text(row.get('meeting_stage_source') for row in evidence)}",
                f"- course configuration known: {sum(1 for row in evidence if row.get('course_configuration') not in {'UNKNOWN', None, ''})}",
                "",
                "## 3. Missing Meeting Information",
                "",
            ]
        )
        missing = metrics.get("missing_required_inputs") or {}
        lines.extend([f"- {key}: {value}" for key, value in missing.items()] or ["- None"])
        lines.extend(
            [
                "",
                "## 4. Evidence Summary",
                "",
                f"- Evidence total: {metrics.get('evidence_count')}",
                f"- MeetingBias Primary: {metrics.get('meeting_bias_primary_count')}",
                f"- TrackBias Primary: {metrics.get('track_bias_primary_count')}",
                f"- Course Primary: {metrics.get('course_primary_count')}",
                f"- RaceShape Primary: {metrics.get('race_shape_primary_count')}",
                f"- Multiple Causes: {metrics.get('multiple_causes_count')}",
                f"- Data Insufficient: {metrics.get('data_insufficient_count')}",
                "",
                "## 5. Evidence Tables",
                "",
                "| evidence_id | race_id | surface | distance | stage | pattern | support | counter | FN | FP | responsibility | strength | data | shadow |",
                "|---|---|---|---:|---|---|---:|---:|---:|---:|---|---|---|---|",
            ]
        )
        for row in evidence:
            lines.append(
                f"| {row.get('evidence_id')} | {row.get('race_id')} | {row.get('surface')} | "
                f"{row.get('distance')} | {row.get('meeting_stage')} | {row.get('observed_pattern')} | "
                f"{row.get('support_count')} | {row.get('counterexample_count')} | {row.get('fn_count')} | "
                f"{row.get('fp_count')} | {row.get('primary_responsibility')} | {row.get('evidence_strength')} | "
                f"{row.get('data_completeness')} | {row.get('shadow_testable')} |"
            )
        lines.extend(
            [
                "",
                "## 26. Manhattan Cafe Candidate Reclassification",
                "",
                "- The prior Manhattan Cafe / Hakodate / good condition hypothesis is not kept as a Bloodline candidate.",
                "- Related Hakodate good-condition cases are treated as MeetingBias evidence only when race-pattern support exists.",
                "- If evidence is insufficient, the case remains DATA_INSUFFICIENT or MULTIPLE_CAUSES.",
                "",
                "## 27. MeetingBias Candidate List",
                "",
                "| candidate_id | name | support races | support horses | FN | FP | shadow | priority | status |",
                "|---|---|---:|---:|---:|---:|---|---|---|",
            ]
        )
        for item in candidates:
            lines.append(
                f"| {item.get('candidate_id')} | {item.get('candidate_name')} | {item.get('support_races')} | "
                f"{item.get('support_horses')} | {item.get('fn_related_count')} | {item.get('fp_related_count')} | "
                f"{item.get('shadow_testability')} | {item.get('priority')} | {item.get('status')} |"
            )
        lines.extend(
            [
                "",
                "## 28. Top Candidate",
                "",
                json.dumps(top_candidate or "NO_SHADOW_CANDIDATE", ensure_ascii=False, indent=2),
                "",
                "## 30. Shadow Testability",
                "",
                f"- Shadow ready candidate count: {metrics.get('shadow_ready_candidate_count')}",
                f"- Recommended shadow scope: {json.dumps(metrics.get('recommended_shadow_scope'), ensure_ascii=False)}",
                "",
                "## 31. Data Limitations",
                "",
                "- Course rotation is UNKNOWN unless present in existing analysis data.",
                "- Meeting day/week is not inferred beyond existing MeetingStageDetector output.",
                "- Water content and previous-day trends are UNKNOWN unless already present.",
                "",
                "## 32. Next Step",
                "",
                f"- {metrics.get('recommended_next_action')}",
            ]
        )
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _baseline_metrics(self, rows):
        decisions = Counter(str(row.get("decision") or "").upper() for row in rows)
        return {
            "races": len({row.get("race_id") for row in rows}),
            "horses": len(rows),
            "BUY": decisions.get("BUY", 0),
            "CAUTION": decisions.get("CAUTION", 0),
            "PASS": decisions.get("PASS", 0),
            "FN": sum(1 for row in rows if row.get("actual_finish") in {1, 2, 3} and row.get("decision") != "BUY"),
            "FP": sum(1 for row in rows if row.get("decision") == "BUY" and row.get("actual_finish") not in {1, 2, 3}),
            "BUY3": sum(1 for row in rows if row.get("decision") == "BUY" and row.get("actual_finish") in {1, 2, 3}),
            "Top5_3": sum(1 for row in rows if row.get("top5") and row.get("actual_finish") in {1, 2, 3}),
        }

    def _complete_sets(self, analysis_dir, results_dir):
        raise RuntimeError("Direct analysis/result discovery is disabled; use MeetingBiasReadOnlyCollector.")

    def _ranked_rows(self, analysis):
        ranked = [row for row in self._list((analysis or {}).get("ranked_results")) if isinstance(row, dict)]
        return sorted(
            ranked,
            key=lambda row: (
                self._to_float(row.get("adjusted_score")) or 0.0,
                self._to_int(row.get("horse_number")) or 0,
            ),
            reverse=True,
        )

    def _official_map(self, rows):
        return {
            self._norm(row.get("horse_name")): row
            for row in self._list(rows)
            if isinstance(row, dict) and row.get("horse_name")
        }

    def _analysis_name_map(self, rows):
        return {
            self._norm(row.get("horse_name")): row
            for row in self._list(rows)
            if isinstance(row, dict) and row.get("horse_name")
        }

    def _lookup(self, mapping, name):
        return mapping.get(self._norm(name))

    def _last3f_ranks(self, rows):
        timed = []
        for row in rows:
            value = self._to_float(row.get("last_3f"))
            if value is not None:
                timed.append((value, self._norm(row.get("horse_name"))))
        timed.sort()
        return {name: index for index, (_, name) in enumerate(timed, start=1)}

    def _overlap_level(self, pattern, layer, context):
        if layer == "TrackBias" and pattern in {"inside_lane_advantage", "outside_lane_advantage", "front_position_advantage", "closer_position_advantage"}:
            return "MEDIUM"
        if layer == "CourseKnowledge" and pattern in {"inside_lane_advantage", "front_position_advantage"}:
            return "MEDIUM"
        if layer == "RaceShape" and pattern in {"front_position_advantage", "middle_position_advantage", "closer_position_advantage", "strong_late_3f_advantage"}:
            return "MEDIUM"
        if layer == "Pace" and pattern in {"front_position_advantage", "closer_position_advantage", "strong_late_3f_advantage"}:
            return "MEDIUM"
        return "LOW"

    def _evidence_strength(self, support_count, counter_count, fn_count, responsibility):
        if responsibility == "DATA_INSUFFICIENT":
            return "LOW"
        if support_count >= 3 and counter_count == 0:
            return "HIGH"
        if support_count >= 2 and fn_count >= 1:
            return "MEDIUM"
        if support_count >= 2:
            return "LOW"
        return "LOW"

    def _data_completeness(self, context):
        required = ["race_date", "racecourse", "surface", "distance", "track_condition", "meeting_stage"]
        present = sum(1 for key in required if context.get(key) not in {None, "", "UNKNOWN", "unknown"})
        if present == len(required) and context.get("meeting_stage_source") != "UNKNOWN":
            return "HIGH"
        if present >= 5:
            return "MEDIUM"
        return "LOW"

    def _missing_required_inputs(self, evidence):
        keys = [
            "meeting_stage",
            "course_configuration",
            "manual_track_bias",
            "course_configuration_source",
        ]
        return {
            key: sum(1 for row in evidence if row.get(key) in {None, "", "UNKNOWN", "unknown"})
            for key in keys
        }

    def _hypothesis(self, context, pattern, responsibility):
        if responsibility == "DATA_INSUFFICIENT":
            return "MeetingBias evidence is insufficient for this race pattern."
        return (
            f"{context.get('racecourse')} {context.get('surface')} {context.get('distance_category')} "
            f"{context.get('track_condition')} {context.get('meeting_stage')} may show {pattern}."
        )

    def _pattern_result(self, pattern, target):
        if target == "inside" and pattern == "inside_lane_advantage":
            return "ADVANTAGE"
        if target == "outside" and pattern == "outside_lane_advantage":
            return "ADVANTAGE"
        if target == "front" and pattern == "front_position_advantage":
            return "ADVANTAGE"
        if target == "closer" and pattern == "closer_position_advantage":
            return "ADVANTAGE"
        if target == "late_3f" and pattern == "strong_late_3f_advantage":
            return "ADVANTAGE"
        return "NEUTRAL"

    def _distance_category(self, value):
        distance = self._to_int(value)
        if distance is None:
            return "UNKNOWN"
        if distance <= 1400:
            return "sprint"
        if distance <= 1600:
            return "mile"
        if distance <= 2200:
            return "middle"
        return "long"

    def _stage_confidence(self, source):
        return {
            "EXPLICIT": "HIGH",
            "MEETING_WEEK": "HIGH",
            "MEETING_DAY": "HIGH",
            "DERIVED_OR_ENGINE": "MEDIUM",
            "UNKNOWN": "UNKNOWN",
        }.get(source, "UNKNOWN")

    def _race_id_part(self, race_id, index):
        parts = str(race_id or "").split("_")
        return parts[index] if len(parts) > index else ""

    def _evidence_id(self, race_id, pattern):
        return f"mbe_{self._race_id_part(race_id, 1)}_{self._race_id_part(race_id, 2)}_{self._race_id_part(race_id, 3)}_{pattern}"

    def _recommended_next_action(self, top_candidate):
        if top_candidate:
            return "Proceed to one narrow MeetingBias shadow validation candidate using the corrected Shadow Framework."
        return "NO_SHADOW_CANDIDATE: collect more meeting metadata before shadow validation."

    def _warnings(self, baseline, errors):
        warnings = []
        for key, expected in self.BASELINE_EXPECTED.items():
            if baseline.get(key) != expected:
                warnings.append(f"baseline mismatch: {key} actual={baseline.get(key)} expected={expected}")
        if errors:
            warnings.append("race extraction errors present")
        return warnings

    def _counter_text(self, values):
        return dict(Counter(value or "UNKNOWN" for value in values))

    def _load_json(self, path, default):
        path = Path(path)
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path, payload):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _list(self, value):
        return value if isinstance(value, list) else []

    def _norm(self, value):
        return "".join(str(value or "").split())

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


if __name__ == "__main__":
    result = MeetingBiasEvidenceExtractor().extract()
    print(
        {
            "reviewed_races": result.get("reviewed_races"),
            "reviewed_horses": result.get("reviewed_horses"),
            "evidence_count": result.get("evidence_count"),
            "candidate_count": result.get("candidate_count"),
            "shadow_ready_candidate_count": result.get("shadow_ready_candidate_count"),
            "top_candidate_id": result.get("top_candidate_id"),
            "final_judgment": result.get("final_judgment"),
        }
    )
