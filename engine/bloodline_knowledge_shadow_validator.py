"""Shadow-validate a recommended bloodline Knowledge candidate.

This module is diagnostic only.  It simulates the weakest existing positive
broodmare-sire Knowledge score on copied race rows, writes validation reports,
and annotates Learning Candidate records.  It never edits official Knowledge,
evaluator logic, official scores, decisions, CSV definitions, or main.py.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
import sys
import unicodedata
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine.decision_engine import DecisionEngine
from engine.shadow_validation_framework import ShadowValidationFramework
from evaluation.race_file_locator import RaceFileLocator
from evaluation.target_result_adapter import TargetResultAdapter
from evaluation.target_trial_adapter import TargetTrialAdapter


class BloodlineKnowledgeShadowValidator:
    """Run shadow validation for the Manhattan Cafe dam-sire candidate."""

    SHADOW_VERSION = "phase_e_step6_v1"
    CANDIDATE_ID = "phase_e_step6_damsire_manhattan_cafe_hakodate_good"
    DAMSIRE = "マンハッタンカフェ"
    TARGET_COURSE = "hakodate"
    TARGET_TRACK = "good"
    BASELINE_DATES = {"20260705", "20260711", "20260712"}
    ORIGINAL_VALIDATED_HORSES = {
        "キープサインオン",
        "カテリーナ",
        "ヴーレヴー",
        "ヒミノエトワール",
    }

    DEFAULT_DB_PATH = Path("learning/improvement_candidates.json")
    DEFAULT_REPORT_PATH = Path("reports/bloodline_knowledge_shadow_validation_report.md")
    DEFAULT_METRICS_PATH = Path("reports/bloodline_knowledge_shadow_validation_metrics.json")
    DEFAULT_FRAMEWORK_REPORT_PATH = Path("reports/shadow_validation_framework_report.md")
    DEFAULT_FRAMEWORK_METRICS_PATH = Path("reports/shadow_validation_framework_metrics.json")

    def __init__(self, db_path=None, report_path=None, metrics_path=None):
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self.report_path = Path(report_path) if report_path else self.DEFAULT_REPORT_PATH
        self.metrics_path = Path(metrics_path) if metrics_path else self.DEFAULT_METRICS_PATH
        self.decision_engine = DecisionEngine()
        self.shadow_framework = ShadowValidationFramework(self.decision_engine)

    def validate(self, analysis_dir="data/analysis", results_dir="data/results"):
        """Run shadow validation and persist report/metrics."""

        started = datetime.now(timezone.utc).isoformat()
        score_unit = self._existing_broodmare_positive_unit()
        complete_sets = self._complete_sets(analysis_dir, results_dir)
        race_results, errors = self._collect_race_results(complete_sets)
        official_rows = self._official_rows(race_results)
        official_baseline = self._baseline_metrics(official_rows)

        if score_unit is None:
            result = self._insufficient_spec_result(started, complete_sets, official_rows, errors)
            self._write_outputs(result)
            return result

        framework_result = self.shadow_framework.validate(
            race_results=race_results,
            shadow_applier=lambda row: self._apply_shadow_delta(row, score_unit),
            scope_filter=self._applicable,
            candidate_id=self.CANDIDATE_ID,
        )
        comparisons = self._corrected_compare_rows(
            official_rows,
            framework_result,
            score_unit,
        )
        applicable = [row for row in comparisons if row.get("applicable")]
        fn_rows = [row for row in applicable if row.get("is_fn")]
        non_fn_rows = [row for row in applicable if not row.get("is_fn")]
        same_bloodline_control = [
            row for row in comparisons
            if self._same(row.get("broodmare_sire"), self.DAMSIRE)
            and not row.get("applicable")
        ]
        course_control = [
            row for row in comparisons
            if row.get("racecourse") == self.TARGET_COURSE
            and row.get("track_condition") == self.TARGET_TRACK
            and not self._same(row.get("broodmare_sire"), self.DAMSIRE)
        ]

        database = self._load_database()
        updated_db, update_count = self._annotate_learning_candidates(database, comparisons)

        result = {
            "shadow_validation_version": self.SHADOW_VERSION,
            "generated_at": started,
            "candidate_id": self.CANDIDATE_ID,
            "comparison_mode": "corrected_baseline",
            "framework_validation_version": "phase_f_step2_v1",
            "score_unit": {
                "source": "knowledge.bloodlines.broodmare.BROODMARE_SIRE_PROFILES score_modifiers",
                "unit": score_unit,
                "method": "minimum positive existing broodmare-sire modifier",
            },
            "complete_race_count": len(complete_sets),
            "horse_count": len(official_rows),
            "baseline": official_baseline,
            "official_baseline_expected": {
                "races": 22,
                "horses": 304,
                "BUY": 45,
                "CAUTION": 88,
                "PASS": 171,
                "FN": 55,
                "FP": 34,
                "BUY3": 11,
                "Top5_3": 30,
            },
            "shadow_target_count": len(applicable),
            "fn_target_count": len(fn_rows),
            "non_fn_target_count": len(non_fn_rows),
            "original_validated_count": len(
                [row for row in applicable if row.get("horse_name") in self.ORIGINAL_VALIDATED_HORSES]
            ),
            "same_bloodline_control_count": len(same_bloodline_control),
            "course_control_count": len(course_control),
            "fn_improvement_count": sum(1 for row in fn_rows if row.get("fn_improved")),
            "pass_to_caution_count": self._transition_count(applicable, "PASS", "CAUTION"),
            "pass_to_buy_count": self._transition_count(applicable, "PASS", "BUY"),
            "caution_to_buy_count": self._transition_count(applicable, "CAUTION", "BUY"),
            "rank_improvement_count": sum(1 for row in applicable if row.get("rank_improved")),
            "top5_entry_count": sum(1 for row in applicable if row.get("top5_entry")),
            "new_fp_count": sum(1 for row in applicable if row.get("new_fp")),
            "outside_place_new_buy_count": sum(
                1 for row in applicable if row.get("outside_place_new_buy")
            ),
            "out_of_scope_decision_change_count": sum(
                1 for row in comparisons
                if not row.get("applicable") and row.get("decision_changed")
            ),
            "non_fn_side_effect_count": sum(
                1 for row in non_fn_rows if row.get("side_effect_level") != "NONE"
            ),
            "turf_dirt_results": self._surface_summary(applicable),
            "distance_results": self._distance_summary(applicable),
            "control_summary": self._control_summary(same_bloodline_control, course_control),
            "course_trackbias_overlap": "PRESENT: candidate scope is restricted by hakodate and good condition",
            "meeting_bias_contamination_risk": "MEDIUM: course/track-condition scope may include non-bloodline venue effects",
            "learning_candidate_update_count": update_count,
            "shadow_decision_changed_count": sum(1 for row in applicable if row.get("decision_changed")),
            "official_to_zero_delta_change_count": framework_result.get("metrics", {}).get("official_to_zero_delta_changes"),
            "official_to_shadow_change_count": framework_result.get("metrics", {}).get("official_to_shadow_changes"),
            "zero_delta_to_shadow_change_count": framework_result.get("metrics", {}).get("zero_delta_to_shadow_changes"),
            "redecision_drift_excluded": framework_result.get("metrics", {}).get("redecision_drift_excluded"),
            "framework_metrics": framework_result.get("metrics", {}),
            "decision_change_attribution": self._shadow_attribution(applicable),
            "per_horse": applicable,
            "same_bloodline_control": same_bloodline_control,
            "warnings": self._warnings(official_baseline, errors),
            "errors": errors,
        }
        result["judgment"] = self._judgment(result)
        result["next_step_recommendation"] = self._next_step(result)
        updated_db, framework_update = self._annotate_framework_candidate(updated_db, result)
        result["framework_learning_candidate_update"] = framework_update
        self._save_database(updated_db)
        self._write_outputs(result)
        return result

    def _collect_race_results(self, complete_sets):
        adapter = TargetTrialAdapter()
        result_adapter = TargetResultAdapter()
        results = []
        errors = []
        for race_set in complete_sets:
            race_id = race_set.get("race_id")
            try:
                analysis = adapter.run(
                    race_set.get("entry_path"),
                    horse_data_csv_path=race_set.get("horses_path"),
                )
                official = result_adapter.load(
                    race_set.get("race_result_path"),
                    race_set.get("horse_result_path"),
                )
                results.append({"race_set": race_set, "analysis": analysis, "official": official})
            except Exception as exc:  # pragma: no cover - diagnostic path
                errors.append({"race_id": race_id, "error": str(exc)})
        return results, errors

    def _official_rows(self, race_results):
        rows = []
        for race in race_results:
            race_id = race.get("race_set", {}).get("race_id")
            official_map = self._official_map(race.get("official", {}).get("horse_results"))
            ranked = [
                row for row in self._list(race.get("analysis", {}).get("ranked_results"))
                if isinstance(row, dict)
            ]
            for rank, horse in enumerate(ranked, start=1):
                name = horse.get("horse_name")
                official = official_map.get(self._normalize(name), {})
                rows.append(self._base_row(race_id, horse, official, rank))
        return rows

    def _corrected_compare_rows(self, official_rows, framework_result, score_delta):
        official_by_key = {
            (row.get("race_id"), self._normalize(row.get("horse_name"))): row
            for row in official_rows
        }
        comparisons = []
        for item in self._list(framework_result.get("comparisons")):
            key = (item.get("race_id"), self._normalize(item.get("horse_name")))
            official_result = official_by_key.get(key, {})
            zero = item.get("zero_delta_baseline") if isinstance(item.get("zero_delta_baseline"), dict) else {}
            shadow = item.get("shadow") if isinstance(item.get("shadow"), dict) else {}
            official = item.get("official") if isinstance(item.get("official"), dict) else {}
            applicable = bool(item.get("shadow_applicable"))
            finish = official_result.get("actual_finish")
            is_fn = finish is not None and finish <= 3 and official_result.get("decision") != "BUY"
            zero_level = self._decision_level(zero.get("decision"))
            shadow_level = self._decision_level(shadow.get("decision"))
            new_buy = zero.get("decision") != "BUY" and shadow.get("decision") == "BUY"
            row = {
                "candidate_id": self.CANDIDATE_ID,
                "comparison_mode": "corrected_baseline",
                "applicable": applicable,
                "race_id": item.get("race_id"),
                "horse_name": item.get("horse_name"),
                "racecourse": official_result.get("racecourse") or official.get("racecourse"),
                "surface": official_result.get("surface") or official.get("surface"),
                "distance": official_result.get("distance") or official.get("distance"),
                "track_condition": official_result.get("track_condition") or official.get("track_condition"),
                "running_style": official_result.get("running_style"),
                "sire": official_result.get("sire"),
                "broodmare_sire": official_result.get("broodmare_sire") or official.get("broodmare_sire"),
                "actual_finish": finish,
                "official_overall_rank": official_result.get("overall_rank") or official.get("rank"),
                "zero_delta_overall_rank": zero.get("rank"),
                "shadow_overall_rank": shadow.get("rank"),
                "official_decision": official_result.get("decision") or official.get("decision"),
                "zero_delta_decision": zero.get("decision"),
                "shadow_decision": shadow.get("decision"),
                "official_decision_score": official_result.get("decision_score") or official.get("decision_score"),
                "zero_delta_decision_score": zero.get("decision_score"),
                "shadow_decision_score": shadow.get("decision_score"),
                "official_bloodline_score": official_result.get("bloodline_score") or official.get("bloodline_score"),
                "zero_delta_bloodline_score": zero.get("bloodline_score"),
                "shadow_bloodline_score": shadow.get("bloodline_score"),
                "official_final_score": official_result.get("final_score") or official.get("final_score"),
                "zero_delta_final_score": zero.get("final_score"),
                "shadow_final_score": shadow.get("final_score"),
                "official_adjusted_score": official_result.get("adjusted_score") or official.get("adjusted_score"),
                "zero_delta_adjusted_score": zero.get("adjusted_score"),
                "shadow_adjusted_score": shadow.get("adjusted_score"),
                "shadow_score_delta": score_delta if applicable else 0,
                "redecision_final_score_drift": item.get("redecision_final_score_drift"),
                "corrected_shadow_final_score_delta": item.get("corrected_shadow_final_score_delta"),
                "redecision_adjusted_score_drift": item.get("redecision_adjusted_score_drift"),
                "corrected_shadow_adjusted_score_delta": item.get("corrected_shadow_adjusted_score_delta"),
                "redecision_decision_score_drift": item.get("redecision_decision_score_drift"),
                "corrected_shadow_decision_score_delta": item.get("corrected_shadow_decision_score_delta"),
                "official_to_zero_delta_changed": item.get("official_to_zero_delta_changed"),
                "official_to_shadow_changed": item.get("official_to_shadow_changed"),
                "zero_delta_to_shadow_changed": item.get("zero_delta_to_shadow_changed"),
                "decision_changed": item.get("zero_delta_to_shadow_changed"),
                "is_fn": is_fn,
                "fn_improved": bool(is_fn and shadow_level > zero_level),
                "new_fp": bool(new_buy and finish is not None and finish >= 4),
                "outside_place_new_buy": bool(new_buy and finish is not None and finish >= 4),
                "rank_improved": bool((shadow.get("rank") or 999) < (zero.get("rank") or 999)),
                "top5_entry": bool((zero.get("rank") or 999) > 5 and (shadow.get("rank") or 999) <= 5),
                "distance_to_buy_before": self._distance_to_buy(zero.get("decision_score")),
                "distance_to_buy_after": self._distance_to_buy(shadow.get("decision_score")),
                "distance_to_buy_shrunk": self._distance_to_buy(shadow.get("decision_score")) < self._distance_to_buy(zero.get("decision_score")),
                "side_effect_level": self._corrected_side_effect_level(
                    zero,
                    shadow,
                    applicable,
                    finish,
                    is_fn,
                ),
                "side_effect_evaluation": self._corrected_side_effect_text(
                    zero,
                    shadow,
                    applicable,
                    finish,
                    is_fn,
                ),
                "shadow_attribution": self._corrected_attribution(item),
                "propagation_class": item.get("propagation_class"),
            }
            comparisons.append(row)
        return comparisons

    def _shadow_rows(self, race_results, score_delta):
        all_shadow_rows = []
        shadow_by_key = {}
        for race in race_results:
            race_id = race.get("race_set", {}).get("race_id")
            official_map = self._official_map(race.get("official", {}).get("horse_results"))
            raw_rows = [
                deepcopy(row) for row in self._list(race.get("analysis", {}).get("ranked_results"))
                if isinstance(row, dict)
            ]
            for row in raw_rows:
                if self._applicable(row):
                    self._apply_shadow_delta(row, score_delta)
                else:
                    row["bloodline_shadow_validation"] = {
                        "candidate_id": self.CANDIDATE_ID,
                        "applicable": False,
                        "shadow_score_delta": 0,
                        "reason": "outside candidate scope",
                    }
            shadow_ranked = sorted(
                raw_rows,
                key=lambda item: (self._to_float(item.get("adjusted_score")) or 0, self._to_int(item.get("horse_number")) or 0),
                reverse=True,
            )
            decision_results = self.decision_engine.decide_many(shadow_ranked)
            for rank, row in enumerate(shadow_ranked, start=1):
                decision = decision_results[rank - 1] if rank - 1 < len(decision_results) else {}
                row["decision"] = decision.get("decision", row.get("decision"))
                row["decision_score"] = decision.get("decision_score", row.get("decision_score"))
                row["decision_result"] = decision
                name = row.get("horse_name")
                official = official_map.get(self._normalize(name), {})
                base = self._base_row(race_id, row, official, rank)
                shadow_by_key[(race_id, self._normalize(name))] = base
                all_shadow_rows.append(base)
        return all_shadow_rows, shadow_by_key

    def _base_row(self, race_id, horse, official, rank):
        finish = self._to_int((official or {}).get("finish_position"))
        return {
            "race_id": race_id,
            "horse_name": horse.get("horse_name"),
            "racecourse": horse.get("racecourse"),
            "surface": horse.get("surface"),
            "distance": self._to_int(horse.get("distance")),
            "track_condition": horse.get("track_condition"),
            "running_style": horse.get("pace_style") or horse.get("running_style"),
            "sire": horse.get("sire"),
            "broodmare_sire": horse.get("broodmare_sire"),
            "actual_finish": finish,
            "overall_rank": rank,
            "decision": horse.get("decision"),
            "decision_score": self._to_float(horse.get("decision_score")),
            "bloodline_score": self._to_float(horse.get("bloodline_score")) or 0,
            "final_score": self._to_float(horse.get("final_score")) or 0,
            "adjusted_score": self._to_float(horse.get("adjusted_score")) or 0,
            "top5": rank <= 5,
            "bloodline_shadow_validation": horse.get("bloodline_shadow_validation", {}),
        }

    def _compare_rows(self, official_rows, shadow_by_key, score_delta):
        comparisons = []
        for official in official_rows:
            key = (official.get("race_id"), self._normalize(official.get("horse_name")))
            shadow = shadow_by_key.get(key, {})
            applicable = self._applicable(official)
            finish = official.get("actual_finish")
            is_fn = finish is not None and finish <= 3 and official.get("decision") != "BUY"
            official_level = self._decision_level(official.get("decision"))
            shadow_level = self._decision_level(shadow.get("decision"))
            rank_improved = (
                shadow.get("overall_rank") is not None
                and official.get("overall_rank") is not None
                and shadow.get("overall_rank") < official.get("overall_rank")
            )
            decision_improved = shadow_level > official_level
            new_buy = official.get("decision") != "BUY" and shadow.get("decision") == "BUY"
            row = {
                "candidate_id": self.CANDIDATE_ID,
                "applicable": applicable,
                "race_id": official.get("race_id"),
                "horse_name": official.get("horse_name"),
                "racecourse": official.get("racecourse"),
                "surface": official.get("surface"),
                "distance": official.get("distance"),
                "track_condition": official.get("track_condition"),
                "running_style": official.get("running_style"),
                "sire": official.get("sire"),
                "broodmare_sire": official.get("broodmare_sire"),
                "actual_finish": finish,
                "official_overall_rank": official.get("overall_rank"),
                "official_decision": official.get("decision"),
                "official_decision_score": official.get("decision_score"),
                "official_bloodline_score": official.get("bloodline_score"),
                "official_final_score": official.get("final_score"),
                "official_adjusted_score": official.get("adjusted_score"),
                "shadow_overall_rank": shadow.get("overall_rank"),
                "shadow_decision": shadow.get("decision"),
                "shadow_decision_score": shadow.get("decision_score"),
                "shadow_bloodline_score": shadow.get("bloodline_score"),
                "shadow_final_score": shadow.get("final_score"),
                "shadow_adjusted_score": shadow.get("adjusted_score"),
                "shadow_score_delta": score_delta if applicable else 0,
                "decision_changed": official.get("decision") != shadow.get("decision"),
                "is_fn": is_fn,
                "fn_improved": bool(is_fn and decision_improved),
                "new_fp": bool(new_buy and finish is not None and finish >= 4),
                "outside_place_new_buy": bool(new_buy and finish is not None and finish >= 4),
                "rank_improved": rank_improved,
                "top5_entry": bool(rank_improved and official.get("overall_rank", 99) > 5 and shadow.get("overall_rank", 99) <= 5),
                "distance_to_buy_before": self._distance_to_buy(official.get("decision_score")),
                "distance_to_buy_after": self._distance_to_buy(shadow.get("decision_score")),
                "distance_to_buy_shrunk": self._distance_to_buy(shadow.get("decision_score")) < self._distance_to_buy(official.get("decision_score")),
                "side_effect_level": self._side_effect_level(official, shadow, applicable, finish, is_fn),
                "side_effect_evaluation": self._side_effect_text(official, shadow, applicable, finish, is_fn),
                "shadow_attribution": self._decision_change_attribution(official, shadow),
            }
            comparisons.append(row)
        return comparisons

    def _apply_shadow_delta(self, row, score_delta):
        bloodline = self._to_float(row.get("bloodline_score")) or 0
        final = self._to_float(row.get("final_score")) or 0
        adjusted = self._to_float(row.get("adjusted_score")) or 0
        row["bloodline_score"] = bloodline + score_delta
        row["final_score"] = final + score_delta
        row["adjusted_score"] = adjusted + score_delta
        breakdown = row.get("score_breakdown")
        if isinstance(breakdown, dict):
            breakdown["Bloodline"] = (self._to_float(breakdown.get("Bloodline")) or 0) + score_delta
            breakdown["Final"] = (self._to_float(breakdown.get("Final")) or 0) + score_delta
        row["bloodline_shadow_validation"] = {
            "candidate_id": self.CANDIDATE_ID,
            "applicable": True,
            "official_bloodline_score": bloodline,
            "shadow_bloodline_score": bloodline + score_delta,
            "shadow_score_delta": score_delta,
            "reason": "weakest existing positive broodmare-sire modifier applied in shadow only",
        }

    def _annotate_learning_candidates(self, database, comparisons):
        records = self._list(database.get("records"))
        by_key = {
            (row.get("race_id"), self._normalize(row.get("horse_name"))): row
            for row in comparisons
            if row.get("applicable")
        }
        update_count = 0
        for record in records:
            key = (record.get("race_id"), self._normalize(record.get("horse")))
            shadow = by_key.get(key)
            if not shadow:
                continue
            record["shadow_validation_status"] = self._record_shadow_status(shadow)
            record["shadow_candidate_id"] = self.CANDIDATE_ID
            record["shadow_applicable"] = True
            record["shadow_score_delta"] = shadow.get("shadow_score_delta")
            record["shadow_official_decision"] = shadow.get("official_decision")
            record["shadow_zero_delta_decision"] = shadow.get("zero_delta_decision")
            record["shadow_decision_before"] = shadow.get("zero_delta_decision")
            record["shadow_decision_after"] = shadow.get("shadow_decision")
            record["shadow_decision_changed"] = shadow.get("decision_changed")
            record["shadow_fn_improved"] = shadow.get("fn_improved")
            record["shadow_fp_created"] = shadow.get("new_fp")
            record["shadow_side_effect_level"] = shadow.get("side_effect_level")
            record["zero_delta_baseline_enabled"] = True
            record["corrected_shadow_diff_enabled"] = True
            record["shadow_official_to_zero_delta_changed"] = shadow.get("official_to_zero_delta_changed")
            record["shadow_official_to_shadow_changed"] = shadow.get("official_to_shadow_changed")
            record["shadow_zero_delta_to_shadow_changed"] = shadow.get("zero_delta_to_shadow_changed")
            record["shadow_redecision_drift_excluded"] = True
            record["shadow_reclassification_candidate"] = (
                "Course/TrackBias/MeetingBias overlap"
                if shadow.get("applicable")
                and shadow.get("racecourse") == self.TARGET_COURSE
                and shadow.get("track_condition") == self.TARGET_TRACK
                else ""
            )
            record["shadow_validation_version"] = self.SHADOW_VERSION
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            update_count += 1
        database["updated_at"] = datetime.now(timezone.utc).isoformat()
        return database, update_count

    def _annotate_framework_candidate(self, database, result):
        records = self._list(database.get("records"))
        now = datetime.now(timezone.utc).isoformat()
        record = None
        for item in records:
            if item.get("candidate_id") == "shadow_evaluation_propagation":
                record = item
                break
        if record is None:
            record = {
                "candidate_id": "shadow_evaluation_propagation",
                "race_id": "phase_f_step2_shadow_framework",
                "horse": "shadow_validation_framework",
                "case_type": "SYSTEM_DIAGNOSTIC",
                "decision": "N/A",
                "actual_finish": None,
                "fn": False,
                "fp": False,
                "primary_candidate": "ShadowValidationFramework",
                "status": "NEW",
                "priority": "high",
                "created_at": now,
            }
            records.insert(0, record)

        metrics = result.get("framework_metrics") or {}
        cross_race = metrics.get("cross_race_corrected_changes")
        zero_to_shadow = result.get("zero_delta_to_shadow_change_count")
        framework_status = "VALIDATED" if cross_race == 0 else "REVIEW_REQUIRED"
        record.update(
            {
                "fix_status": "VALIDATED",
                "fix_version": "phase_f_step2_v1",
                "zero_delta_baseline_enabled": True,
                "corrected_shadow_diff_enabled": True,
                "official_to_zero_delta_changes": result.get("official_to_zero_delta_change_count"),
                "official_to_shadow_changes": result.get("official_to_shadow_change_count"),
                "zero_delta_to_shadow_changes": zero_to_shadow,
                "cross_race_corrected_changes": cross_race,
                "same_race_corrected_changes": metrics.get("same_race_corrected_changes"),
                "redecision_drift_excluded": result.get("redecision_drift_excluded"),
                "framework_validation_status": framework_status,
                "recommended_next_action": result.get("next_step_recommendation"),
                "baseline": result.get("baseline"),
                "ranking_active": True,
                "updated_at": now,
            }
        )
        if record.get("status") == "IMPLEMENTED":
            record["status"] = "WATCH"
        database["records"] = records
        database["updated_at"] = now
        return database, {
            "candidate_id": record.get("candidate_id"),
            "fix_version": record.get("fix_version"),
            "framework_validation_status": record.get("framework_validation_status"),
            "status": record.get("status"),
            "zero_delta_to_shadow_changes": zero_to_shadow,
        }

    def _record_shadow_status(self, shadow):
        if shadow.get("new_fp") or shadow.get("outside_place_new_buy"):
            return "REJECTED"
        if shadow.get("fn_improved"):
            return "VALIDATED"
        if shadow.get("shadow_score_delta", 0) > 0:
            return "PARTIALLY_VALIDATED"
        return "PENDING"

    def _judgment(self, result):
        if result.get("fn_improvement_count", 0) <= 0:
            return "REJECT"
        if result.get("new_fp_count") or result.get("outside_place_new_buy_count"):
            return "REJECT"
        if result.get("out_of_scope_decision_change_count"):
            return "REJECT"
        if result.get("non_fn_side_effect_count"):
            return "HOLD"
        return "HOLD"

    def _next_step(self, result):
        if result.get("judgment") == "REJECT":
            return "Do not implement this Knowledge as-is; reclassify or narrow the causal hypothesis before editing Knowledge."
        return "Keep as shadow-validated candidate and require human review before any Knowledge edit."

    def _complete_sets(self, analysis_dir, results_dir):
        locator = RaceFileLocator()
        found = locator.find_complete_race_sets(analysis_dir, results_dir)
        return [
            row for row in self._list(found.get("complete_sets"))
            if self._race_date(row.get("race_id")) in self.BASELINE_DATES
        ]

    def _existing_broodmare_positive_unit(self):
        try:
            from knowledge.bloodlines.broodmare import BROODMARE_SIRE_PROFILES
        except Exception:
            return None
        values = []
        for profile in BROODMARE_SIRE_PROFILES.values():
            modifiers = profile.get("score_modifiers", {}) if isinstance(profile, dict) else {}
            values.extend(
                value for value in modifiers.values()
                if isinstance(value, (int, float)) and value > 0
            )
        return min(values) if values else None

    def _baseline_metrics(self, rows):
        decisions = Counter(str(row.get("decision") or "").upper() for row in rows)
        return {
            "races": len(set(row.get("race_id") for row in rows)),
            "horses": len(rows),
            "BUY": decisions.get("BUY", 0),
            "CAUTION": decisions.get("CAUTION", 0),
            "PASS": decisions.get("PASS", 0),
            "FN": sum(1 for row in rows if row.get("actual_finish") in {1, 2, 3} and row.get("decision") != "BUY"),
            "FP": sum(1 for row in rows if row.get("decision") == "BUY" and self._to_int(row.get("actual_finish")) not in {1, 2, 3}),
            "BUY3": sum(1 for row in rows if row.get("decision") == "BUY" and row.get("actual_finish") in {1, 2, 3}),
            "Top5_3": sum(1 for row in rows if row.get("top5") and row.get("actual_finish") in {1, 2, 3}),
        }

    def _surface_summary(self, rows):
        return self._group_summary(rows, "surface")

    def _distance_summary(self, rows):
        return self._group_summary(rows, "distance")

    def _group_summary(self, rows, key):
        summary = {}
        for value in sorted({row.get(key) for row in rows}, key=lambda item: str(item)):
            subset = [row for row in rows if row.get(key) == value]
            summary[str(value)] = {
                "count": len(subset),
                "fn": sum(1 for row in subset if row.get("is_fn")),
                "fn_improved": sum(1 for row in subset if row.get("fn_improved")),
                "new_fp": sum(1 for row in subset if row.get("new_fp")),
                "decision_changed": sum(1 for row in subset if row.get("decision_changed")),
            }
        return summary

    def _control_summary(self, same_bloodline_control, course_control):
        return {
            "same_bloodline_control": {
                "count": len(same_bloodline_control),
                "decision_changed": sum(1 for row in same_bloodline_control if row.get("decision_changed")),
            },
            "hakodate_good_non_manhattan_control": {
                "count": len(course_control),
                "decision_changed": sum(1 for row in course_control if row.get("decision_changed")),
            },
        }

    def _shadow_attribution(self, rows):
        counter = Counter(row.get("shadow_attribution") for row in rows if row.get("decision_changed"))
        return dict(counter)

    def _decision_change_attribution(self, official, shadow):
        if official.get("decision") == shadow.get("decision"):
            return "none"
        if shadow.get("decision_score", 0) != official.get("decision_score", 0):
            return "BloodlineShadow + DecisionScore"
        if shadow.get("overall_rank") != official.get("overall_rank"):
            return "BloodlineShadow + Rank change"
        return "UNKNOWN"

    def _transition_count(self, rows, before, after):
        return sum(
            1 for row in rows
            if row.get("zero_delta_decision", row.get("official_decision")) == before
            and row.get("shadow_decision") == after
        )

    def _side_effect_level(self, official, shadow, applicable, finish, is_fn):
        if not applicable or is_fn:
            return "NONE"
        if official.get("decision") != shadow.get("decision"):
            if shadow.get("decision") == "BUY" and finish not in {1, 2, 3}:
                return "HIGH"
            return "MEDIUM"
        if shadow.get("overall_rank", 99) < official.get("overall_rank", 99):
            return "LOW"
        return "NONE"

    def _side_effect_text(self, official, shadow, applicable, finish, is_fn):
        if not applicable:
            return "out_of_scope"
        if is_fn:
            return "target_fn"
        level = self._side_effect_level(official, shadow, applicable, finish, is_fn)
        if level == "HIGH":
            return "new BUY outside Top3 risk"
        if level == "MEDIUM":
            return "non-FN decision changed"
        if level == "LOW":
            return "non-FN rank strengthened only"
        return "no side effect"

    def _corrected_side_effect_level(self, zero, shadow, applicable, finish, is_fn):
        if not applicable or is_fn:
            return "NONE"
        if zero.get("decision") != shadow.get("decision"):
            if shadow.get("decision") == "BUY" and finish not in {1, 2, 3}:
                return "HIGH"
            return "MEDIUM"
        if (shadow.get("rank") or 999) < (zero.get("rank") or 999):
            return "LOW"
        return "NONE"

    def _corrected_side_effect_text(self, zero, shadow, applicable, finish, is_fn):
        if not applicable:
            return "out_of_scope"
        if is_fn:
            return "target_fn"
        level = self._corrected_side_effect_level(zero, shadow, applicable, finish, is_fn)
        if level == "HIGH":
            return "new BUY outside Top3 risk"
        if level == "MEDIUM":
            return "non-FN corrected decision changed"
        if level == "LOW":
            return "non-FN corrected rank strengthened only"
        return "no corrected side effect"

    def _corrected_attribution(self, item):
        if not item.get("zero_delta_to_shadow_changed"):
            return "none"
        if item.get("shadow_applicable"):
            return "BloodlineShadow corrected effect"
        if item.get("same_race_relative_effect"):
            return "Same-race relative shadow effect"
        return "UNKNOWN"

    def _applicable(self, row):
        return (
            self._same(row.get("broodmare_sire"), self.DAMSIRE)
            and str(row.get("racecourse") or "").lower() == self.TARGET_COURSE
            and str(row.get("track_condition") or "").lower() == self.TARGET_TRACK
        )

    def _distance_to_buy(self, decision_score):
        score = self._to_float(decision_score)
        if score is None:
            return 0.8
        return round(max(0.0, 0.8 - score), 3)

    def _decision_level(self, decision):
        return {"PASS": 0, "CAUTION": 1, "BUY": 2}.get(str(decision or "").upper(), -1)

    def _warnings(self, baseline, errors):
        warnings = []
        expected = {"races": 22, "horses": 304, "BUY": 45, "CAUTION": 88, "PASS": 171, "FN": 55, "FP": 34, "BUY3": 11, "Top5_3": 30}
        for key, value in expected.items():
            if baseline.get(key) != value:
                warnings.append(f"baseline mismatch: {key} actual={baseline.get(key)} expected={value}")
        if errors:
            warnings.append("race collection errors present")
        return warnings

    def _insufficient_spec_result(self, started, complete_sets, rows, errors):
        return {
            "shadow_validation_version": self.SHADOW_VERSION,
            "generated_at": started,
            "candidate_id": self.CANDIDATE_ID,
            "status": "INSUFFICIENT_SPEC",
            "complete_race_count": len(complete_sets),
            "horse_count": len(rows),
            "baseline": self._baseline_metrics(rows),
            "per_horse": [],
            "errors": errors,
            "warnings": ["No existing positive broodmare-sire score unit was available."],
            "judgment": "HOLD",
            "next_step_recommendation": "Define an official Knowledge scoring unit before shadow validation.",
        }

    def _official_map(self, rows):
        mapping = {}
        for row in self._list(rows):
            if not isinstance(row, dict):
                continue
            name = row.get("horse_name") or row.get("horse")
            if not name:
                continue
            mapping[self._normalize(name)] = row
        return mapping

    def _load_database(self):
        if not self.db_path.exists():
            return {"records": [], "aggregates": []}
        return json.loads(self.db_path.read_text(encoding="utf-8"))

    def _save_database(self, database):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.write_text(json.dumps(database, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_outputs(self, result):
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(self._format_report(result), encoding="utf-8")
        self.metrics_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if result.get("comparison_mode") == "corrected_baseline":
            self.DEFAULT_FRAMEWORK_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.DEFAULT_FRAMEWORK_REPORT_PATH.write_text(
                self._format_framework_report(result),
                encoding="utf-8",
            )
            self.DEFAULT_FRAMEWORK_METRICS_PATH.write_text(
                json.dumps(
                    {
                        "framework_validation_version": result.get("framework_validation_version"),
                        "comparison_mode": result.get("comparison_mode"),
                        "candidate_id": result.get("candidate_id"),
                        "baseline": result.get("baseline"),
                        "framework_metrics": result.get("framework_metrics"),
                        "official_to_zero_delta_change_count": result.get("official_to_zero_delta_change_count"),
                        "official_to_shadow_change_count": result.get("official_to_shadow_change_count"),
                        "zero_delta_to_shadow_change_count": result.get("zero_delta_to_shadow_change_count"),
                        "redecision_drift_excluded": result.get("redecision_drift_excluded"),
                        "per_horse": result.get("per_horse"),
                        "judgment": result.get("judgment"),
                        "warnings": result.get("warnings"),
                        "errors": result.get("errors"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    def _format_report(self, result):
        lines = [
            "# Bloodline Knowledge Shadow Validation",
            "",
            f"- Generated: {result.get('generated_at')}",
            f"- Candidate ID: {result.get('candidate_id')}",
            f"- Shadow version: {result.get('shadow_validation_version')}",
            f"- Comparison mode: {result.get('comparison_mode')}",
            f"- Framework validation version: {result.get('framework_validation_version')}",
            f"- Judgment: {result.get('judgment')}",
            f"- Next step: {result.get('next_step_recommendation')}",
            "",
            "## Score Unit",
            "",
            f"- Source: {result.get('score_unit', {}).get('source')}",
            f"- Unit: {result.get('score_unit', {}).get('unit')}",
            f"- Method: {result.get('score_unit', {}).get('method')}",
            "",
            "## Baseline",
            "",
            "| Metric | Actual | Expected |",
            "|---|---:|---:|",
        ]
        expected = result.get("official_baseline_expected") or {}
        for key, value in (result.get("baseline") or {}).items():
            lines.append(f"| {key} | {value} | {expected.get(key, '')} |")
        lines.extend(
            [
                "",
                "## Summary",
                "",
                f"- Shadow target count: {result.get('shadow_target_count')}",
                f"- FN target count: {result.get('fn_target_count')}",
                f"- Non-FN target count: {result.get('non_fn_target_count')}",
                f"- FN improvement count: {result.get('fn_improvement_count')}",
                f"- PASS -> CAUTION: {result.get('pass_to_caution_count')}",
                f"- PASS -> BUY: {result.get('pass_to_buy_count')}",
                f"- CAUTION -> BUY: {result.get('caution_to_buy_count')}",
                f"- Rank improvement count: {result.get('rank_improvement_count')}",
                f"- New FP count: {result.get('new_fp_count')}",
                f"- Outside-place new BUY count: {result.get('outside_place_new_buy_count')}",
                f"- Out-of-scope decision changes: {result.get('out_of_scope_decision_change_count')}",
                f"- Non-FN side effects: {result.get('non_fn_side_effect_count')}",
                f"- Learning Candidate updates: {result.get('learning_candidate_update_count')}",
                f"- Official -> Zero Delta changes: {result.get('official_to_zero_delta_change_count')}",
                f"- Official -> Shadow changes: {result.get('official_to_shadow_change_count')}",
                f"- Zero Delta -> Shadow changes: {result.get('zero_delta_to_shadow_change_count')}",
                f"- ReDecision drift excluded: {result.get('redecision_drift_excluded')}",
                "",
                "## Per-Horse Shadow Results",
                "",
                "| Race | Horse | Finish | Surface | Distance | Style | Official Decision | Zero Delta | Shadow | Official DS | Zero DS | Shadow DS | Delta | Corrected Change | FN Improved | New FP | Side Effect |",
                "|---|---|---:|---|---:|---|---|---|---|---:|---:|---:|---:|---|---|---|---|",
            ]
        )
        for row in result.get("per_horse") or []:
            lines.append(
                "| {race_id} | {horse_name} | {actual_finish} | {surface} | {distance} | {running_style} | "
                "{official_decision} | {zero_delta_decision} | {shadow_decision} | "
                "{official_decision_score} | {zero_delta_decision_score} | {shadow_decision_score} | "
                "{shadow_score_delta} | {decision_changed} | {fn_improved} | {new_fp} | "
                "{side_effect_level} |".format(**row)
            )
        lines.extend(
            [
                "",
                "## Surface Summary",
                "",
                json.dumps(result.get("turf_dirt_results", {}), ensure_ascii=False, indent=2),
                "",
                "## Distance Summary",
                "",
                json.dumps(result.get("distance_results", {}), ensure_ascii=False, indent=2),
                "",
                "## Control Summary",
                "",
                json.dumps(result.get("control_summary", {}), ensure_ascii=False, indent=2),
                "",
                "## Overlap Risks",
                "",
                f"- Course/TrackBias overlap: {result.get('course_trackbias_overlap')}",
                f"- MeetingBias contamination risk: {result.get('meeting_bias_contamination_risk')}",
                "",
                "## Warnings",
                "",
            ]
        )
        warnings = result.get("warnings") or []
        lines.extend([f"- {warning}" for warning in warnings] or ["- None"])
        return "\n".join(lines) + "\n"

    def _format_framework_report(self, result):
        metrics = result.get("framework_metrics") or {}
        lines = [
            "# Shadow Validation Framework Report",
            "",
            "## 1. PhaseF Step1 Root Cause",
            "",
            "- Primary root cause: SHADOW_RECALC_DESIGN",
            "- The old comparison mixed raw shadow effects with delta=0 re-decision drift.",
            "",
            "## 2. Correction Summary",
            "",
            "- New comparison layers: OFFICIAL / ZERO_DELTA_BASELINE / SHADOW",
            "- Corrected shadow effect: SHADOW - ZERO_DELTA_BASELINE",
            "- Official output remains read-only.",
            "",
            "## 3. Core Metrics",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Official -> Zero Delta changes | {result.get('official_to_zero_delta_change_count')} |",
            f"| Official -> Shadow changes | {result.get('official_to_shadow_change_count')} |",
            f"| Zero Delta -> Shadow changes | {result.get('zero_delta_to_shadow_change_count')} |",
            f"| ReDecision drift excluded | {result.get('redecision_drift_excluded')} |",
            f"| Target corrected changes | {metrics.get('target_corrected_changes')} |",
            f"| Non-target corrected changes | {metrics.get('non_target_corrected_changes')} |",
            f"| Same-race corrected changes | {metrics.get('same_race_corrected_changes')} |",
            f"| Cross-race corrected changes | {metrics.get('cross_race_corrected_changes')} |",
            f"| FN improved | {result.get('fn_improvement_count')} |",
            f"| New FP | {result.get('new_fp_count')} |",
            f"| PASS -> CAUTION | {result.get('pass_to_caution_count')} |",
            f"| PASS -> BUY | {result.get('pass_to_buy_count')} |",
            f"| CAUTION -> BUY | {result.get('caution_to_buy_count')} |",
            f"| Rank improvement | {result.get('rank_improvement_count')} |",
            f"| DecisionScore improvement | {metrics.get('decision_score_improvement_count')} |",
            "",
            "## 4. Target Horses",
            "",
            "| Race | Horse | Finish | Official | Zero Delta | Shadow | Official DS | Zero DS | Shadow DS | Corrected Change | FN Improved | New FP |",
            "|---|---|---:|---|---|---|---:|---:|---:|---|---|---|",
        ]
        for row in result.get("per_horse") or []:
            lines.append(
                f"| {row.get('race_id')} | {row.get('horse_name')} | {row.get('actual_finish')} | "
                f"{row.get('official_decision')} | {row.get('zero_delta_decision')} | {row.get('shadow_decision')} | "
                f"{row.get('official_decision_score')} | {row.get('zero_delta_decision_score')} | "
                f"{row.get('shadow_decision_score')} | {row.get('decision_changed')} | "
                f"{row.get('fn_improved')} | {row.get('new_fp')} |"
            )
        lines.extend(
            [
                "",
                "## 5. Side Effect Review",
                "",
                "- Side effects are counted only when Zero Delta -> Shadow changes.",
                f"- Corrected non-FN side effects: {result.get('non_fn_side_effect_count')}",
                f"- Out-of-scope corrected changes: {result.get('out_of_scope_decision_change_count')}",
                "",
                "## 6. Baseline",
                "",
                json.dumps(result.get("baseline"), ensure_ascii=False, indent=2),
                "",
                "## 7. Judgment",
                "",
                f"- Judgment: {result.get('judgment')}",
                f"- Next step: {result.get('next_step_recommendation')}",
            ]
        )
        return "\n".join(lines) + "\n"

    def _race_date(self, race_id):
        parts = str(race_id or "").split("_")
        return parts[1] if len(parts) >= 2 else ""

    def _normalize(self, value):
        text = unicodedata.normalize("NFKC", str(value or ""))
        return "".join(text.split())

    def _same(self, left, right):
        return self._normalize(left) == self._normalize(right)

    def _list(self, value):
        return value if isinstance(value, list) else []

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
    result = BloodlineKnowledgeShadowValidator().validate()
    print(
        {
            "candidate_id": result.get("candidate_id"),
            "shadow_target_count": result.get("shadow_target_count"),
            "fn_improvement_count": result.get("fn_improvement_count"),
            "new_fp_count": result.get("new_fp_count"),
            "judgment": result.get("judgment"),
            "report_path": str(BloodlineKnowledgeShadowValidator.DEFAULT_REPORT_PATH),
        }
    )
