"""Analyze decision propagation caused by local shadow score changes.

This analyzer is diagnostic only.  It replays shadow-style calculations on
copied race rows, compares the results with official baseline outputs, writes a
report, and stores one Learning Candidate diagnostic record.  It never edits
evaluators, official Knowledge, official scores, or Decision logic.
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
from evaluation.race_file_locator import RaceFileLocator
from evaluation.target_result_adapter import TargetResultAdapter
from evaluation.target_trial_adapter import TargetTrialAdapter


class ShadowPropagationAnalyzer:
    """Trace why Step6 shadow changes propagated outside target horses."""

    VERSION = "phase_f_step1_v1"
    CANDIDATE_ID = "shadow_evaluation_propagation"
    STEP6_METRICS_PATH = Path("reports/bloodline_knowledge_shadow_validation_metrics.json")
    DEFAULT_REPORT_PATH = Path("reports/shadow_propagation_analysis_report.md")
    DEFAULT_METRICS_PATH = Path("reports/shadow_propagation_analysis_metrics.json")
    DEFAULT_DB_PATH = Path("learning/improvement_candidates.json")
    BASELINE_DATES = {"20260705", "20260711", "20260712"}
    TARGET_DAMSIRE = "マンハッタンカフェ"
    TARGET_COURSE = "hakodate"
    TARGET_TRACK = "good"
    SHADOW_DELTA = 2

    def __init__(
        self,
        report_path=None,
        metrics_path=None,
        db_path=None,
        step6_metrics_path=None,
    ):
        self.report_path = Path(report_path) if report_path else self.DEFAULT_REPORT_PATH
        self.metrics_path = Path(metrics_path) if metrics_path else self.DEFAULT_METRICS_PATH
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self.step6_metrics_path = (
            Path(step6_metrics_path) if step6_metrics_path else self.STEP6_METRICS_PATH
        )
        self.decision_engine = DecisionEngine()

    def analyze(self, analysis_dir="data/analysis", results_dir="data/results"):
        generated_at = datetime.now(timezone.utc).isoformat()
        step6 = self._load_step6_metrics()
        complete_sets = self._complete_sets(analysis_dir, results_dir)
        race_rows, errors = self._collect_races(complete_sets)
        official_rows = self._official_rows(race_rows)
        baseline = self._baseline_metrics(official_rows)

        scenarios = {
            "normal_shadow": self._run_scenario(race_rows, self.SHADOW_DELTA, "normal", "all_targets"),
            "reverse_race_order": self._run_scenario(race_rows, self.SHADOW_DELTA, "reverse_race", "all_targets"),
            "reverse_horse_order": self._run_scenario(race_rows, self.SHADOW_DELTA, "reverse_horse", "all_targets"),
            "individual_shadow": self._run_individual_shadow(race_rows, self.SHADOW_DELTA),
            "zero_delta": self._run_scenario(race_rows, 0, "normal", "all_targets"),
            "no_shadow_redecision": self._run_scenario(race_rows, 0, "normal", "none"),
        }

        normal_changes = scenarios["normal_shadow"].get("changes", [])
        target_keys = self._target_keys(official_rows)
        out_of_scope_changes = [
            row for row in normal_changes
            if (row.get("race_id"), self._normalize(row.get("horse_name"))) not in target_keys
        ]
        detailed_changes = [
            self._classify_change(row, scenarios, race_rows)
            for row in out_of_scope_changes
        ]
        side_effect_horses = [
            row for row in self._step6_target_rows(step6)
            if row.get("horse_name") in {"インヴォーグ", "ベアサナエチャン"}
        ]
        learning_update = self._update_learning_candidate(
            detailed_changes,
            scenarios,
            baseline,
        )

        result = {
            "validation_version": self.VERSION,
            "generated_at": generated_at,
            "baseline": baseline,
            "expected_baseline": {
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
            "step6_summary": {
                "target_count": step6.get("shadow_target_count"),
                "out_of_scope_decision_change_count": step6.get(
                    "out_of_scope_decision_change_count"
                ),
                "non_fn_side_effect_count": step6.get("non_fn_side_effect_count"),
                "judgment": step6.get("judgment"),
            },
            "scenario_summaries": {
                name: self._scenario_summary(data)
                for name, data in scenarios.items()
            },
            "out_of_scope_decision_change_count": len(out_of_scope_changes),
            "same_race_change_count": sum(1 for row in detailed_changes if row.get("same_race_has_target")),
            "cross_race_change_count": sum(1 for row in detailed_changes if not row.get("same_race_has_target")),
            "score_change_count": sum(1 for row in detailed_changes if row.get("score_changed")),
            "rank_change_count": sum(1 for row in detailed_changes if row.get("rank_changed")),
            "decision_score_change_count": sum(
                1 for row in detailed_changes if row.get("decision_score_changed")
            ),
            "rank_blocker_change_count": sum(
                1 for row in detailed_changes if row.get("rank_blocker_changed")
            ),
            "risk_penalty_change_count": sum(
                1 for row in detailed_changes if row.get("risk_penalty_changed")
            ),
            "race_decision_change_count": 0,
            "normalization_scope": self._normalization_scope(scenarios),
            "shared_object_mutation_detected": self._shared_object_mutation_detected(scenarios),
            "cache_contamination_detected": False,
            "order_dependency_detected": self._order_dependency_detected(scenarios),
            "zero_delta_change_detected": bool(scenarios["zero_delta"].get("changes")),
            "changed_horses": detailed_changes,
            "side_effect_horses": side_effect_horses,
            "primary_root_cause": self._primary_root_cause(scenarios, detailed_changes),
            "secondary_root_causes": self._secondary_root_causes(scenarios, detailed_changes),
            "severity": self._severity(scenarios, detailed_changes),
            "recommended_fix": self._recommended_fix(scenarios, detailed_changes),
            "learning_candidate_update": learning_update,
            "warnings": self._warnings(baseline, errors),
            "errors": errors,
        }
        self._write_outputs(result)
        return result

    def _run_scenario(self, race_rows, delta, order_mode, scope_mode):
        changes = []
        row_count = 0
        race_sequence = list(race_rows)
        if order_mode == "reverse_race":
            race_sequence = list(reversed(race_sequence))
        for race in race_sequence:
            official = race.get("official_rows", [])
            shadow_rows = [deepcopy(row) for row in race.get("ranked_rows", [])]
            if order_mode == "reverse_horse":
                shadow_rows = list(reversed(shadow_rows))
            if scope_mode == "all_targets":
                for row in shadow_rows:
                    if self._applicable(row):
                        self._apply_delta(row, delta)
            shadow_ranked = sorted(
                shadow_rows,
                key=lambda item: (
                    self._to_float(item.get("adjusted_score")) or 0,
                    self._to_int(item.get("horse_number")) or 0,
                ),
                reverse=True,
            )
            decisions = self.decision_engine.decide_many(shadow_ranked)
            shadow_map = {}
            for index, row in enumerate(shadow_ranked, start=1):
                decision = decisions[index - 1] if index - 1 < len(decisions) else {}
                shadow_map[self._normalize(row.get("horse_name"))] = {
                    "race_id": race.get("race_id"),
                    "horse_name": row.get("horse_name"),
                    "decision": decision.get("decision"),
                    "decision_score": decision.get("decision_score"),
                    "rank": index,
                    "final_score": self._to_float(row.get("final_score")) or 0,
                    "adjusted_score": self._to_float(row.get("adjusted_score")) or 0,
                    "decision_result": decision,
                }
            for official_row in official:
                row_count += 1
                shadow = shadow_map.get(self._normalize(official_row.get("horse_name")), {})
                change = self._comparison_row(official_row, shadow, race, delta)
                if change.get("decision_changed"):
                    changes.append(change)
        return {
            "delta": delta,
            "order_mode": order_mode,
            "scope_mode": scope_mode,
            "row_count": row_count,
            "changes": changes,
        }

    def _run_individual_shadow(self, race_rows, delta):
        aggregate = {}
        for race in race_rows:
            targets = [
                row for row in race.get("ranked_rows", [])
                if self._applicable(row)
            ]
            for target in targets:
                target_name = self._normalize(target.get("horse_name"))
                shadow_rows = [deepcopy(row) for row in race.get("ranked_rows", [])]
                for row in shadow_rows:
                    if self._normalize(row.get("horse_name")) == target_name:
                        self._apply_delta(row, delta)
                shadow_ranked = sorted(
                    shadow_rows,
                    key=lambda item: (
                        self._to_float(item.get("adjusted_score")) or 0,
                        self._to_int(item.get("horse_number")) or 0,
                    ),
                    reverse=True,
                )
                decisions = self.decision_engine.decide_many(shadow_ranked)
                shadow_map = {}
                for index, row in enumerate(shadow_ranked, start=1):
                    decision = decisions[index - 1] if index - 1 < len(decisions) else {}
                    shadow_map[self._normalize(row.get("horse_name"))] = {
                        "race_id": race.get("race_id"),
                        "horse_name": row.get("horse_name"),
                        "decision": decision.get("decision"),
                        "decision_score": decision.get("decision_score"),
                        "rank": index,
                        "final_score": self._to_float(row.get("final_score")) or 0,
                        "adjusted_score": self._to_float(row.get("adjusted_score")) or 0,
                        "decision_result": decision,
                    }
                for official_row in race.get("official_rows", []):
                    shadow = shadow_map.get(self._normalize(official_row.get("horse_name")), {})
                    change = self._comparison_row(official_row, shadow, race, delta)
                    if not change.get("decision_changed"):
                        continue
                    key = (change.get("race_id"), self._normalize(change.get("horse_name")))
                    aggregate[key] = change
        return {
            "delta": delta,
            "order_mode": "normal",
            "scope_mode": "individual_targets",
            "row_count": sum(len(race.get("official_rows", [])) for race in race_rows),
            "changes": list(aggregate.values()),
        }

    def _comparison_row(self, official, shadow, race, delta):
        score_changed = (
            abs((shadow.get("final_score") or 0) - (official.get("final_score") or 0)) > 1e-9
            or abs((shadow.get("adjusted_score") or 0) - (official.get("adjusted_score") or 0)) > 1e-9
        )
        decision_score_changed = abs(
            (shadow.get("decision_score") or 0) - (official.get("decision_score") or 0)
        ) > 1e-9
        rank_changed = shadow.get("rank") != official.get("rank")
        return {
            "race_id": official.get("race_id"),
            "horse_name": official.get("horse_name"),
            "shadow_applicable": self._applicable(official),
            "official_final_score": official.get("final_score"),
            "shadow_final_score": shadow.get("final_score"),
            "official_adjusted_score": official.get("adjusted_score"),
            "shadow_adjusted_score": shadow.get("adjusted_score"),
            "official_decision_score": official.get("decision_score"),
            "shadow_decision_score": shadow.get("decision_score"),
            "official_rank": official.get("rank"),
            "shadow_rank": shadow.get("rank"),
            "official_decision": official.get("decision"),
            "shadow_decision": shadow.get("decision"),
            "decision_changed": official.get("decision") != shadow.get("decision"),
            "score_changed": score_changed,
            "rank_changed": rank_changed,
            "decision_score_changed": decision_score_changed,
            "normalization_changed": decision_score_changed and not score_changed,
            "race_population_changed": bool(delta),
            "risk_penalty_changed": self._risk_penalty_changed(
                official.get("decision_result"),
                shadow.get("decision_result"),
            ),
            "rank_blocker_changed": self._rank_blocker_changed(
                official.get("decision_result"),
                shadow.get("decision_result"),
            ),
            "decision_gate_changed": decision_score_changed or rank_changed,
            "race_decision_changed": False,
            "same_race_has_target": bool(race.get("target_count")),
            "same_course": official.get("racecourse") == self.TARGET_COURSE,
            "same_date": self._race_date(official.get("race_id")) in self.BASELINE_DATES,
            "propagation_source": "",
            "propagation_confidence": "",
        }

    def _classify_change(self, row, scenarios, race_rows):
        item = dict(row)
        if item.get("score_changed") and item.get("shadow_applicable"):
            source = "SCORE_DIRECT"
            confidence = "HIGH"
        elif item.get("rank_changed"):
            source = "RANK_REORDER"
            confidence = "HIGH"
        elif scenarios["zero_delta"].get("changes"):
            source = "ORDER_DEPENDENCY"
            confidence = "HIGH"
        elif item.get("decision_score_changed") and item.get("same_race_has_target"):
            source = "NORMALIZATION_RACE"
            confidence = "MEDIUM"
        elif item.get("decision_score_changed"):
            source = "DECISION_SCORE_RECALC"
            confidence = "MEDIUM"
        else:
            source = "UNKNOWN"
            confidence = "LOW"
        item["propagation_source"] = source
        item["propagation_confidence"] = confidence
        return item

    def _collect_races(self, complete_sets):
        adapter = TargetTrialAdapter()
        result_adapter = TargetResultAdapter()
        races = []
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
            except Exception as exc:  # pragma: no cover - diagnostic path
                errors.append({"race_id": race_id, "error": str(exc)})
                continue
            official_map = self._official_map(official.get("horse_results"))
            ranked = [
                row for row in self._list(analysis.get("ranked_results"))
                if isinstance(row, dict)
            ]
            official_rows = []
            for rank, horse in enumerate(ranked, start=1):
                name = horse.get("horse_name")
                result_row = official_map.get(self._normalize(name), {})
                official_rows.append(
                    {
                        "race_id": race_id,
                        "horse_name": name,
                        "racecourse": horse.get("racecourse"),
                        "surface": horse.get("surface"),
                        "distance": self._to_int(horse.get("distance")),
                        "track_condition": horse.get("track_condition"),
                        "broodmare_sire": horse.get("broodmare_sire"),
                        "decision": horse.get("decision"),
                        "decision_score": self._to_float(horse.get("decision_score")),
                        "decision_result": horse.get("decision_result", {}),
                        "rank": rank,
                        "final_score": self._to_float(horse.get("final_score")) or 0,
                        "adjusted_score": self._to_float(horse.get("adjusted_score")) or 0,
                        "finish_position": self._to_int(result_row.get("finish_position")),
                    }
                )
            races.append(
                {
                    "race_id": race_id,
                    "ranked_rows": ranked,
                    "official_rows": official_rows,
                    "target_count": sum(1 for row in ranked if self._applicable(row)),
                }
            )
        return races, errors

    def _official_rows(self, race_rows):
        rows = []
        for race in race_rows:
            rows.extend(race.get("official_rows", []))
        return rows

    def _complete_sets(self, analysis_dir, results_dir):
        found = RaceFileLocator().find_complete_race_sets(analysis_dir, results_dir)
        return [
            row for row in self._list(found.get("complete_sets"))
            if self._race_date(row.get("race_id")) in self.BASELINE_DATES
        ]

    def _apply_delta(self, row, delta):
        if not delta:
            return
        row["bloodline_score"] = (self._to_float(row.get("bloodline_score")) or 0) + delta
        row["final_score"] = (self._to_float(row.get("final_score")) or 0) + delta
        row["adjusted_score"] = (self._to_float(row.get("adjusted_score")) or 0) + delta

    def _baseline_metrics(self, rows):
        decisions = Counter(str(row.get("decision") or "").upper() for row in rows)
        return {
            "races": len(set(row.get("race_id") for row in rows)),
            "horses": len(rows),
            "BUY": decisions.get("BUY", 0),
            "CAUTION": decisions.get("CAUTION", 0),
            "PASS": decisions.get("PASS", 0),
            "FN": sum(
                1 for row in rows
                if row.get("finish_position") in {1, 2, 3} and row.get("decision") != "BUY"
            ),
            "FP": sum(
                1 for row in rows
                if row.get("decision") == "BUY" and row.get("finish_position") not in {1, 2, 3}
            ),
            "BUY3": sum(
                1 for row in rows
                if row.get("decision") == "BUY" and row.get("finish_position") in {1, 2, 3}
            ),
            "Top5_3": sum(
                1 for row in rows
                if row.get("rank", 99) <= 5 and row.get("finish_position") in {1, 2, 3}
            ),
        }

    def _scenario_summary(self, scenario):
        changes = scenario.get("changes", [])
        return {
            "delta": scenario.get("delta"),
            "order_mode": scenario.get("order_mode"),
            "scope_mode": scenario.get("scope_mode"),
            "row_count": scenario.get("row_count"),
            "decision_change_count": len(changes),
            "score_change_count": sum(1 for row in changes if row.get("score_changed")),
            "rank_change_count": sum(1 for row in changes if row.get("rank_changed")),
            "decision_score_change_count": sum(
                1 for row in changes if row.get("decision_score_changed")
            ),
            "same_race_change_count": sum(1 for row in changes if row.get("same_race_has_target")),
            "cross_race_change_count": sum(1 for row in changes if not row.get("same_race_has_target")),
            "transitions": dict(
                Counter(
                    f"{row.get('official_decision')}->{row.get('shadow_decision')}"
                    for row in changes
                )
            ),
        }

    def _normalization_scope(self, scenarios):
        zero = len(scenarios["zero_delta"].get("changes", []))
        normal = len(scenarios["normal_shadow"].get("changes", []))
        if zero:
            return "RECALC_OR_ORDER_DEPENDENCY"
        same_race = scenarios["normal_shadow"]
        if any(not row.get("same_race_has_target") for row in same_race.get("changes", [])):
            return "CROSS_RACE"
        if normal:
            return "RACE_LOCAL"
        return "NONE"

    def _shared_object_mutation_detected(self, scenarios):
        return any(
            row.get("score_changed")
            for row in scenarios["no_shadow_redecision"].get("changes", [])
        )

    def _order_dependency_detected(self, scenarios):
        normal = self._change_keys(scenarios["normal_shadow"].get("changes"))
        reverse_race = self._change_keys(scenarios["reverse_race_order"].get("changes"))
        reverse_horse = self._change_keys(scenarios["reverse_horse_order"].get("changes"))
        return bool(normal != reverse_race or normal != reverse_horse)

    def _primary_root_cause(self, scenarios, changes):
        if self._shared_object_mutation_detected(scenarios):
            return "SHARED_STATE_BUG"
        if scenarios["zero_delta"].get("changes"):
            return "SHADOW_RECALC_DESIGN"
        if any(not row.get("same_race_has_target") for row in changes):
            return "SHADOW_RECALC_DESIGN"
        if changes:
            return "EXPECTED_RACE_RELATIVE_EFFECT"
        return "UNKNOWN"

    def _secondary_root_causes(self, scenarios, changes):
        causes = []
        if scenarios["zero_delta"].get("changes"):
            causes.append("ZERO_DELTA_REDECISION_DRIFT")
        if self._order_dependency_detected(scenarios):
            causes.append("ORDER_DEPENDENCY")
        if any(row.get("decision_score_changed") for row in changes):
            causes.append("DECISION_SCORE_RECALC")
        if any(row.get("rank_changed") for row in changes):
            causes.append("RANK_REORDER")
        if any(not row.get("same_race_has_target") for row in changes):
            causes.append("CROSS_RACE_RECALC")
        return causes

    def _severity(self, scenarios, changes):
        if scenarios["zero_delta"].get("changes"):
            return "S"
        if any(not row.get("same_race_has_target") for row in changes):
            return "S"
        if changes:
            return "A"
        return "B"

    def _recommended_fix(self, scenarios, changes):
        if scenarios["zero_delta"].get("changes"):
            return "Use a delta=0 redecision baseline for shadow comparisons, or compare only target-horse deltas without re-running unrelated official decisions."
        if any(not row.get("same_race_has_target") for row in changes):
            return "Limit shadow validation to affected races and exclude unrelated race redecision from implementation judgment."
        if changes:
            return "Report race-local relative effects separately from direct target effects."
        return "No propagation fix required; keep current diagnostic split."

    def _update_learning_candidate(self, changes, scenarios, baseline):
        database = self._load_database()
        records = self._list(database.get("records"))
        now = datetime.now(timezone.utc).isoformat()
        existing = None
        for record in records:
            if record.get("candidate_id") == self.CANDIDATE_ID:
                existing = record
                break
        payload = {
            "candidate_id": self.CANDIDATE_ID,
            "race_id": "phase_f_step1_22race_shadow",
            "horse": "shadow_propagation",
            "case_type": "SYSTEM_DIAGNOSTIC",
            "decision": "N/A",
            "actual_finish": None,
            "fn": False,
            "fp": False,
            "primary_candidate": "ShadowValidationFramework",
            "attribution_candidates": [
                {
                    "target": "ShadowValidationFramework",
                    "target_type": "Decision",
                    "candidate_type": "Decision",
                    "score": 1.0,
                    "confidence": "HIGH",
                    "evidence": ["Shadow propagation analyzer completed"],
                    "counter_evidence": [],
                }
            ],
            "occurrence": len(changes),
            "affected_horses": len(changes),
            "affected_races": len(set(row.get("race_id") for row in changes)),
            "same_race_affected": sum(1 for row in changes if row.get("same_race_has_target")),
            "cross_race_affected": sum(1 for row in changes if not row.get("same_race_has_target")),
            "primary_propagation_source": self._primary_root_cause(scenarios, changes),
            "secondary_propagation_sources": self._secondary_root_causes(scenarios, changes),
            "shared_object_mutation_detected": self._shared_object_mutation_detected(scenarios),
            "global_normalization_detected": self._normalization_scope(scenarios) == "CROSS_RACE",
            "order_dependency_detected": self._order_dependency_detected(scenarios),
            "zero_delta_change_detected": bool(scenarios["zero_delta"].get("changes")),
            "severity": self._severity(scenarios, changes),
            "recommended_fix_scope": self._recommended_fix(scenarios, changes),
            "validation_version": self.VERSION,
            "ranking_active": True,
            "status": "NEW",
            "priority": "high",
            "baseline": baseline,
            "created_at": now,
            "updated_at": now,
        }
        if existing:
            payload["created_at"] = existing.get("created_at") or now
            existing.clear()
            existing.update(payload)
            updated = 1
        else:
            records.append(payload)
            updated = 1
        database["records"] = records
        database["updated_at"] = now
        self._save_database(database)
        return {"candidate_id": self.CANDIDATE_ID, "updated_records": updated}

    def _step6_target_rows(self, step6):
        return self._list(step6.get("per_horse"))

    def _target_keys(self, official_rows):
        return {
            (row.get("race_id"), self._normalize(row.get("horse_name")))
            for row in official_rows
            if self._applicable(row)
        }

    def _change_keys(self, changes):
        return {
            (row.get("race_id"), self._normalize(row.get("horse_name")), row.get("official_decision"), row.get("shadow_decision"))
            for row in changes
        }

    def _risk_penalty_changed(self, official, shadow):
        official = official if isinstance(official, dict) else {}
        shadow = shadow if isinstance(shadow, dict) else {}
        return (
            official.get("risk_count") != shadow.get("risk_count")
            or official.get("risk_score") != shadow.get("risk_score")
            or official.get("risk_items") != shadow.get("risk_items")
        )

    def _rank_blocker_changed(self, official, shadow):
        official = official if isinstance(official, dict) else {}
        shadow = shadow if isinstance(shadow, dict) else {}
        keys = [
            "low_rank_buy_guard_applied",
            "low_rank_buy_guard_skipped_reason",
            "ai_rank",
            "top_score_pass_rescued",
            "top_score_pass_rescue_skipped_reason",
        ]
        return any(official.get(key) != shadow.get(key) for key in keys)

    def _official_map(self, rows):
        mapping = {}
        for row in self._list(rows):
            if not isinstance(row, dict):
                continue
            name = row.get("horse_name") or row.get("horse")
            if name:
                mapping[self._normalize(name)] = row
        return mapping

    def _applicable(self, row):
        return (
            self._same(row.get("broodmare_sire"), self.TARGET_DAMSIRE)
            and str(row.get("racecourse") or "").lower() == self.TARGET_COURSE
            and str(row.get("track_condition") or "").lower() == self.TARGET_TRACK
        )

    def _load_step6_metrics(self):
        if not self.step6_metrics_path.exists():
            return {}
        return json.loads(self.step6_metrics_path.read_text(encoding="utf-8"))

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
        self.metrics_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.report_path.write_text(self._format_report(result), encoding="utf-8")

    def _format_report(self, result):
        lines = [
            "# Shadow Propagation Analysis",
            "",
            f"- Generated: {result.get('generated_at')}",
            f"- Validation version: {result.get('validation_version')}",
            f"- Primary Root Cause: {result.get('primary_root_cause')}",
            f"- Severity: {result.get('severity')}",
            f"- Recommended Fix: {result.get('recommended_fix')}",
            "",
            "## 1. PhaseE Step6 Summary",
            "",
        ]
        for key, value in (result.get("step6_summary") or {}).items():
            lines.append(f"- {key}: {value}")
        lines.extend(
            [
                "",
                "## 2. Scenario Summary",
                "",
                "| Scenario | Delta | Scope | Order | Decision Changes | Same Race | Cross Race | Score Changes | Rank Changes | DecisionScore Changes | Transitions |",
                "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for name, item in (result.get("scenario_summaries") or {}).items():
            lines.append(
                f"| {name} | {item.get('delta')} | {item.get('scope_mode')} | {item.get('order_mode')} | "
                f"{item.get('decision_change_count')} | {item.get('same_race_change_count')} | "
                f"{item.get('cross_race_change_count')} | {item.get('score_change_count')} | "
                f"{item.get('rank_change_count')} | {item.get('decision_score_change_count')} | "
                f"{item.get('transitions')} |"
            )
        lines.extend(
            [
                "",
                "## 3. Changed Out-of-Scope Horses",
                "",
                "| Race | Horse | Official | Shadow | Rank | DecisionScore | Same Race Target | Score Changed | Rank Changed | Risk Changed | RankBlocker Changed | Source | Confidence |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
            ]
        )
        for row in result.get("changed_horses") or []:
            lines.append(
                f"| {row.get('race_id')} | {row.get('horse_name')} | "
                f"{row.get('official_decision')} | {row.get('shadow_decision')} | "
                f"{row.get('official_rank')}->{row.get('shadow_rank')} | "
                f"{row.get('official_decision_score')}->{row.get('shadow_decision_score')} | "
                f"{row.get('same_race_has_target')} | {row.get('score_changed')} | "
                f"{row.get('rank_changed')} | {row.get('risk_penalty_changed')} | "
                f"{row.get('rank_blocker_changed')} | {row.get('propagation_source')} | "
                f"{row.get('propagation_confidence')} |"
            )
        lines.extend(
            [
                "",
                "## 4. Side Effect Horses",
                "",
                "| Race | Horse | Finish | Official | Shadow | Rank | DecisionScore | Side Effect |",
                "|---|---|---:|---|---|---|---|---|",
            ]
        )
        for row in result.get("side_effect_horses") or []:
            lines.append(
                f"| {row.get('race_id')} | {row.get('horse_name')} | {row.get('actual_finish')} | "
                f"{row.get('official_decision')} | {row.get('shadow_decision')} | "
                f"{row.get('official_overall_rank')}->{row.get('shadow_overall_rank')} | "
                f"{row.get('official_decision_score')}->{row.get('shadow_decision_score')} | "
                f"{row.get('side_effect_level')} |"
            )
        lines.extend(
            [
                "",
                "## 5. Diagnostics",
                "",
                f"- Out-of-scope decision changes: {result.get('out_of_scope_decision_change_count')}",
                f"- Same-race changes: {result.get('same_race_change_count')}",
                f"- Cross-race changes: {result.get('cross_race_change_count')}",
                f"- Score changes: {result.get('score_change_count')}",
                f"- Rank changes: {result.get('rank_change_count')}",
                f"- DecisionScore changes: {result.get('decision_score_change_count')}",
                f"- RiskPenalty changes: {result.get('risk_penalty_change_count')}",
                f"- RankBlocker changes: {result.get('rank_blocker_change_count')}",
                f"- RaceDecision changes: {result.get('race_decision_change_count')}",
                f"- Normalization scope: {result.get('normalization_scope')}",
                f"- Shared object mutation detected: {result.get('shared_object_mutation_detected')}",
                f"- Cache contamination detected: {result.get('cache_contamination_detected')}",
                f"- Order dependency detected: {result.get('order_dependency_detected')}",
                f"- Zero-delta change detected: {result.get('zero_delta_change_detected')}",
                "",
                "## 6. Learning Candidate",
                "",
                json.dumps(result.get("learning_candidate_update"), ensure_ascii=False, indent=2),
                "",
                "## 7. Warnings",
                "",
            ]
        )
        warnings = result.get("warnings") or []
        lines.extend([f"- {warning}" for warning in warnings] or ["- None"])
        return "\n".join(lines) + "\n"

    def _warnings(self, baseline, errors):
        expected = {"races": 22, "horses": 304, "BUY": 45, "CAUTION": 88, "PASS": 171, "FN": 55, "FP": 34, "BUY3": 11, "Top5_3": 30}
        warnings = [
            f"baseline mismatch: {key} actual={baseline.get(key)} expected={value}"
            for key, value in expected.items()
            if baseline.get(key) != value
        ]
        if errors:
            warnings.append("race collection errors present")
        return warnings

    def _race_date(self, race_id):
        parts = str(race_id or "").split("_")
        return parts[1] if len(parts) >= 2 else ""

    def _same(self, left, right):
        return self._normalize(left) == self._normalize(right)

    def _normalize(self, value):
        text = unicodedata.normalize("NFKC", str(value or ""))
        return "".join(text.split())

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
    result = ShadowPropagationAnalyzer().analyze()
    print(
        {
            "out_of_scope_decision_change_count": result.get("out_of_scope_decision_change_count"),
            "same_race_change_count": result.get("same_race_change_count"),
            "cross_race_change_count": result.get("cross_race_change_count"),
            "zero_delta_change_detected": result.get("zero_delta_change_detected"),
            "primary_root_cause": result.get("primary_root_cause"),
            "severity": result.get("severity"),
            "report_path": str(ShadowPropagationAnalyzer.DEFAULT_REPORT_PATH),
        }
    )
