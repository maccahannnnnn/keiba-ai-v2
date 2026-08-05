"""Validate one recommended Knowledge addition before implementation.

This engine is diagnostic only. It validates whether a recommended bloodline
Knowledge candidate has causal support, writes reports, and annotates Learning
Candidate records. It never changes Knowledge, evaluator logic, scores,
decisions, CSV definitions, or Explain output.
"""

from collections import Counter
from datetime import datetime, timezone
import json
import sys
import unicodedata
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))


class RecommendedKnowledgeValidator:
    """Validate the Step4 recommended Knowledge candidate."""

    VALIDATION_VERSION = "phase_e_step5_v1"
    DEFAULT_DB_PATH = Path("learning/improvement_candidates.json")
    DEFAULT_REPORT_PATH = Path("reports/recommended_knowledge_validation_report.md")
    DEFAULT_METRICS_PATH = Path("reports/recommended_knowledge_validation_metrics.json")
    DEFAULT_RECOMMENDED_CATEGORY = "DamSireMissing"
    DEFAULT_RECOMMENDED_DETAIL = "マンハッタンカフェ"
    BASELINE_DATES = {"20260705", "20260711", "20260712"}

    def __init__(self, db_path=None, report_path=None, metrics_path=None):
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self.report_path = Path(report_path) if report_path else self.DEFAULT_REPORT_PATH
        self.metrics_path = Path(metrics_path) if metrics_path else self.DEFAULT_METRICS_PATH

    def validate(
        self,
        category=None,
        detail=None,
        analysis_dir="data/analysis",
        results_dir="data/results",
    ):
        """Validate the recommended Knowledge candidate and persist diagnostics."""

        category = category or self.DEFAULT_RECOMMENDED_CATEGORY
        detail = detail or self.DEFAULT_RECOMMENDED_DETAIL
        database = self._load_database()
        records = self._active_records(database.get("records"))
        target_records = self._target_candidate_records(records, category, detail)
        complete_sets = self._complete_sets(analysis_dir, results_dir, records)
        race_rows, errors = self._collect_race_rows(complete_sets)
        target_rows = [row for row in race_rows if self._same(row.get("broodmare_sire"), detail)]
        target_names = {row.get("horse_name") for row in target_rows}
        target_record_names = {row.get("horse") for row in target_records}
        candidate_target_rows = [
            row for row in target_rows if row.get("horse_name") in target_record_names
        ]
        counter_rows = [
            row for row in target_rows if row.get("horse_name") not in target_record_names
        ]

        existing_knowledge = self._existing_knowledge(detail, target_records)
        missing_type = self._missing_type(existing_knowledge, target_records)
        common_conditions = self._common_conditions(candidate_target_rows)
        scopes = self._scope_candidates(candidate_target_rows, counter_rows, detail)
        specification = self._recommended_specification(scopes, detail)
        validation_status = self._validation_status(
            target_records,
            candidate_target_rows,
            counter_rows,
            existing_knowledge,
            specification,
        )

        annotated = self._annotate_database(
            database,
            target_records,
            validation_status,
            missing_type,
            specification,
            counter_rows,
        )
        self._save_database(annotated)

        result = {
            "validation_version": self.VALIDATION_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "recommended_category": category,
            "recommended_detail": detail,
            "target_record_count": len(target_records),
            "target_horse_count": len(candidate_target_rows),
            "all_applicable_horse_count": len(target_rows),
            "counter_group_size": len(counter_rows),
            "complete_race_count": len(complete_sets),
            "horse_count": len(race_rows),
            "target_records": target_records,
            "target_horses": candidate_target_rows,
            "counter_group": counter_rows,
            "existing_knowledge": existing_knowledge,
            "knowledge_missing_type": missing_type,
            "common_conditions": common_conditions,
            "scope_candidates": scopes,
            "recommended_specification": specification,
            "knowledge_validation_status": validation_status,
            "learning_candidate_update_count": self._count_annotated(annotated, detail),
            "baseline": self._baseline_metrics(race_rows),
            "errors": errors,
            "warnings": [],
        }
        self.write_report(result)
        self.write_metrics(result)
        return result

    def build_record_validation(self, record):
        """Return default validation fields for Learning Candidate records."""

        gaps = [
            gap for gap in self._list(record.get("knowledge_gaps"))
            if isinstance(gap, dict)
            and gap.get("category") == self.DEFAULT_RECOMMENDED_CATEGORY
            and self._same(gap.get("detail"), self.DEFAULT_RECOMMENDED_DETAIL)
        ]
        if not gaps:
            return {}
        return {
            "knowledge_validation_status": "VALIDATION_PENDING",
            "knowledge_missing_type": "A_KNOWLEDGE_ENTITY_MISSING",
            "causal_confidence": "PENDING",
            "recommended_scope": {},
            "counter_group_size": None,
            "affected_fn_count": None,
            "affected_non_fn_count": None,
            "potential_fp_risk": "UNKNOWN",
            "recommended_implementation_id": "",
            "knowledge_validation_version": self.VALIDATION_VERSION,
        }

    def write_report(self, result):
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        spec = result.get("recommended_specification") or {}
        existing = result.get("existing_knowledge") or {}
        baseline = result.get("baseline") or {}
        lines = [
            "# Recommended Knowledge Validation",
            "",
            f"- Generated: {result.get('generated_at')}",
            f"- Validation version: {result.get('validation_version')}",
            f"- Recommended category: {result.get('recommended_category')}",
            f"- Recommended detail: {result.get('recommended_detail')}",
            "",
            "## 1. Target Horses",
            "",
            "| Race | Horse | Finish | Decision | AI Rank | DecisionScore | BloodlineScore | Surface | Distance | Track | Sire | DamSire |",
            "|---|---|---:|---|---:|---:|---:|---|---:|---|---|---|",
        ]
        for row in result.get("target_horses") or []:
            lines.append(
                "| {race_id} | {horse_name} | {actual_finish} | {decision} | {ai_rank} | "
                "{decision_score} | {bloodline_score} | {surface} | {distance} | "
                "{track_condition} | {sire} | {broodmare_sire} |".format(**self._report_row(row))
            )

        lines.extend(
            [
                "",
                "## 2. Common Conditions",
                "",
            ]
        )
        for key, value in (result.get("common_conditions") or {}).items():
            lines.append(f"- {key}: {value}")

        lines.extend(
            [
                "",
                "## 3. Existing Knowledge Check",
                "",
                f"- Broodmare profile exists: {existing.get('broodmare_profile_exists')}",
                f"- Profile path: {existing.get('broodmare_profile_path')}",
                f"- Sire profiles found: {existing.get('sire_profiles_found')}",
                f"- Sire profiles missing: {existing.get('sire_profiles_missing')}",
                f"- Nick knowledge found: {existing.get('nick_knowledge_found')}",
                f"- Nick knowledge missing: {existing.get('nick_knowledge_missing')}",
                f"- Missing type: {result.get('knowledge_missing_type')}",
                "",
                "## 4. Counter Group",
                "",
                f"- All applicable horses in 22 races: {result.get('all_applicable_horse_count')}",
                f"- Target FN horses: {result.get('target_horse_count')}",
                f"- Counter group size: {result.get('counter_group_size')}",
            ]
        )
        if result.get("counter_group"):
            lines.extend(["", "| Race | Horse | Finish | Decision | Surface | Distance | Track |", "|---|---|---:|---|---|---:|---|"])
            for row in result.get("counter_group") or []:
                lines.append(
                    "| {race_id} | {horse_name} | {actual_finish} | {decision} | {surface} | {distance} | {track_condition} |".format(
                        **self._report_row(row)
                    )
                )
        else:
            lines.append("- None")

        lines.extend(
            [
                "",
                "## 5. Scope Candidates",
                "",
                "| Candidate | Target | Scope Horses | FN | Non-FN | Counter | Counter FN | Counter Non-FN | FP Risk | Explainable | Verdict |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|",
            ]
        )
        for row in result.get("scope_candidates") or []:
            lines.append(
                "| {name} | {target_count} | {scope_applicable_count} | {fn_count} | "
                "{non_fn_count} | {counter_count} | {counter_fn_count} | "
                "{counter_non_fn_count} | {fp_risk} | {explainable} | {verdict} |".format(**row)
            )

        lines.extend(
            [
                "",
                "## 6. Recommended Implementation Specification",
                "",
                f"- implementation_id: {spec.get('implementation_id')}",
                f"- target_knowledge_file: {spec.get('target_knowledge_file')}",
                f"- add_key: {spec.get('add_key')}",
                f"- dam_sire_only: {spec.get('dam_sire_only')}",
                f"- surface_condition: {spec.get('surface_condition')}",
                f"- distance_condition: {spec.get('distance_condition')}",
                f"- track_condition: {spec.get('track_condition')}",
                f"- course_condition: {spec.get('course_condition')}",
                f"- evaluation_direction: {spec.get('evaluation_direction')}",
                f"- explain_text: {spec.get('explain_text')}",
                f"- applicable_targets: {spec.get('applicable_targets')}",
                f"- excluded_targets: {spec.get('excluded_targets')}",
                f"- accept_criteria: {spec.get('accept_criteria')}",
                f"- revert_criteria: {spec.get('revert_criteria')}",
                "",
                "## 7. Baseline Comparison",
                "",
                "| Metric | Value | Expected |",
                "|---|---:|---:|",
                f"| races | {baseline.get('races')} | 22 |",
                f"| horses | {baseline.get('horses')} | 304 |",
                f"| BUY | {baseline.get('BUY')} | 45 |",
                f"| CAUTION | {baseline.get('CAUTION')} | 88 |",
                f"| PASS | {baseline.get('PASS')} | 171 |",
                f"| FN | {baseline.get('FN')} | 55 |",
                f"| FP | {baseline.get('FP')} | 34 |",
                f"| BUY3 | {baseline.get('BUY3')} | 11 |",
                f"| Top5_3 | {baseline.get('Top5_3')} | 30 |",
                "",
                "## 8. Guardrails",
                "",
                "- Knowledge was not added or edited in this step.",
                "- Evaluators, scores, decisions, CSV definitions, and Explain output were not changed.",
                "- The specification is for the next implementation step only.",
            ]
        )
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_metrics(self, result):
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            key: value
            for key, value in result.items()
            if key not in {"target_records", "target_horses", "counter_group"}
        }
        data["target_horses"] = result.get("target_horses", [])
        data["counter_group"] = result.get("counter_group", [])
        self.metrics_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _collect_race_rows(self, complete_sets):
        from evaluation.target_result_adapter import TargetResultAdapter
        from evaluation.target_trial_adapter import TargetTrialAdapter

        adapter = TargetTrialAdapter()
        result_adapter = TargetResultAdapter()
        rows = []
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
                item for item in self._list(analysis.get("ranked_results"))
                if isinstance(item, dict)
            ]
            top5_names = {
                item.get("horse_name")
                for item in ranked[:5]
                if item.get("horse_name")
            }
            for index, horse in enumerate(ranked, start=1):
                name = horse.get("horse_name")
                official_row = official_map.get(self._normalize(name), {})
                finish = self._to_int(official_row.get("finish_position"))
                rows.append(
                    {
                        "race_id": race_id,
                        "racecourse": horse.get("racecourse"),
                        "surface": horse.get("surface"),
                        "distance": self._to_int(horse.get("distance")),
                        "track_condition": horse.get("track_condition"),
                        "race_class": analysis.get("race_class") or horse.get("race_class"),
                        "frame_number": horse.get("frame_number"),
                        "horse_number": horse.get("horse_number"),
                        "horse_name": name,
                        "running_style": horse.get("pace_style") or horse.get("running_style"),
                        "pace_prediction": self._pace_prediction(analysis),
                        "actual_finish": finish,
                        "ai_rank": index,
                        "top5": name in top5_names,
                        "decision": horse.get("decision"),
                        "decision_score": horse.get("decision_score"),
                        "distance_to_buy": self._distance_to_buy(horse),
                        "bloodline_score": self._first_present(
                            horse.get("bloodline_score"),
                            horse.get("blood_score"),
                        ),
                        "bloodline_explain": self._bloodline_explain(horse),
                        "sire": horse.get("sire"),
                        "broodmare_sire": horse.get("broodmare_sire"),
                        "nick": self._nick_key(horse),
                    }
                )
        return rows, errors

    def _complete_sets(self, analysis_dir, results_dir, records):
        from evaluation.race_file_locator import RaceFileLocator

        locator = RaceFileLocator()
        found = locator.find_complete_race_sets(analysis_dir, results_dir)
        sets = [
            row for row in self._list(found.get("complete_sets"))
            if self._race_date(row.get("race_id")) in self.BASELINE_DATES
        ]
        if len(sets) == 22:
            return sets
        record_ids = {record.get("race_id") for record in records if record.get("race_id")}
        narrowed = [row for row in self._list(found.get("complete_sets")) if row.get("race_id") in record_ids]
        return narrowed if narrowed else sets

    def _existing_knowledge(self, detail, target_records=None):
        result = {
            "broodmare_profile_exists": False,
            "broodmare_profile_path": "knowledge/bloodlines/broodmare.py",
            "sire_profiles_found": [],
            "sire_profiles_missing": [],
            "nick_knowledge_found": [],
            "nick_knowledge_missing": [],
            "connection_status": "not_checked",
        }
        try:
            from knowledge.bloodlines.broodmare import BROODMARE_SIRE_PROFILES
            from knowledge.bloodlines.sire_profiles import SIRE_PROFILES
            try:
                from knowledge.bloodlines.nicks import NICKS_PROFILES as NICK_SOURCE
            except ImportError:
                from knowledge.bloodlines.nicks import NICKS as NICK_SOURCE
        except Exception as exc:  # pragma: no cover - diagnostic path
            result["connection_status"] = f"import_failed: {exc}"
            return result
        result["connection_status"] = "checked"
        result["broodmare_profile_exists"] = detail in BROODMARE_SIRE_PROFILES
        target_sires = self._target_sires_from_records(target_records)
        result["sire_profiles_found"] = sorted(
            key for key in target_sires
            if key in SIRE_PROFILES
        )
        result["sire_profiles_missing"] = sorted(
            key for key in target_sires
            if key not in SIRE_PROFILES
        )
        nick_text = str(NICK_SOURCE)
        for sire in target_sires:
            key = f"{sire} x {detail}"
            if sire in nick_text and detail in nick_text:
                result["nick_knowledge_found"].append(key)
            else:
                result["nick_knowledge_missing"].append(key)
        return result

    def _target_sires_from_records(self, target_records=None):
        records = self._list(target_records)
        sires = set()
        for record in records:
            for cause in self._list(record.get("bloodline_root_causes")):
                if not isinstance(cause, dict):
                    continue
                detail = str(cause.get("detail") or "")
                if "profile missing or insufficient:" not in detail:
                    continue
                pair = detail.split("profile missing or insufficient:", 1)[1]
                sire = pair.split("/", 1)[0].strip()
                if sire:
                    sires.add(sire)
        return sires

    def _missing_type(self, existing, target_records):
        if not existing.get("broodmare_profile_exists"):
            return "A_KNOWLEDGE_ENTITY_MISSING"
        if target_records and existing.get("broodmare_profile_exists"):
            return "B_DAMSIRE_ITEM_MISSING"
        if existing.get("connection_status") != "checked":
            return "E_CONNECTION_UNCHECKED"
        return "G_NOT_TRUE_KNOWLEDGE_MISSING"

    def _scope_candidates(self, target_rows, counter_rows, detail):
        scopes = []
        target_names = [row.get("horse_name") for row in target_rows]
        common_course = self._common_value(target_rows, "racecourse")
        common_track = self._common_value(target_rows, "track_condition")
        turf_middle = [
            row for row in target_rows
            if row.get("surface") == "turf" and 1600 <= int(row.get("distance") or 0) <= 2200
        ]
        scopes.append(
            self._scope_row(
                "A_damsire_manhattan_cafe_general",
                target_rows,
                counter_rows,
                {"dam_sire": detail},
                "General DamSire knowledge has broad coverage but weak condition specificity.",
            )
        )
        scopes.append(
            self._scope_row(
                "B_damsire_manhattan_cafe_turf_middle_distance",
                turf_middle,
                self._matching_counter(counter_rows, surface="turf", min_distance=1600, max_distance=2200),
                {"dam_sire": detail, "surface": "turf", "distance_min": 1600, "distance_max": 2200},
                "Turf middle-distance scope is more explainable but covers only part of the target set.",
            )
        )
        scopes.append(
            self._scope_row(
                "C_damsire_manhattan_cafe_hakodate_good",
                [
                    row for row in target_rows
                    if row.get("racecourse") == common_course and row.get("track_condition") == common_track
                ],
                self._matching_counter(counter_rows, racecourse=common_course, track_condition=common_track),
                {"dam_sire": detail, "racecourse": common_course, "track_condition": common_track},
                "Racecourse and track-condition scope covers the observed FN cluster without surface overreach.",
            )
        )
        for row in scopes:
            row["target_horses"] = target_names if row["name"].startswith("A_") else [item.get("horse_name") for item in row.get("_target_rows", [])]
            row.pop("_target_rows", None)
        return scopes

    def _scope_row(self, name, target_rows, counter_rows, scope, note):
        target_fn_count = sum(1 for row in target_rows if self._is_fn_row(row))
        target_non_fn_count = len(target_rows) - target_fn_count
        counter_fn_count = sum(1 for row in counter_rows if self._is_fn_row(row))
        counter_non_fn_count = len(counter_rows) - counter_fn_count
        fn_count = target_fn_count + counter_fn_count
        non_fn_count = target_non_fn_count + counter_non_fn_count
        fp_risk = "LOW" if non_fn_count == 0 else "MEDIUM" if non_fn_count <= 6 else "HIGH"
        verdict = "RECOMMENDED" if len(target_rows) >= 3 and fp_risk == "LOW" else "LIMITED" if target_rows else "REJECTED"
        return {
            "name": name,
            "scope": scope,
            "_target_rows": target_rows,
            "target_count": len(target_rows),
            "scope_applicable_count": len(target_rows) + len(counter_rows),
            "target_fn_count": target_fn_count,
            "target_non_fn_count": target_non_fn_count,
            "counter_fn_count": counter_fn_count,
            "counter_non_fn_count": counter_non_fn_count,
            "fn_count": fn_count,
            "non_fn_count": non_fn_count,
            "counter_count": len(counter_rows),
            "fp_risk": fp_risk,
            "explainable": "YES" if target_rows else "NO",
            "verdict": verdict,
            "note": note,
        }

    def _recommended_specification(self, scopes, detail):
        selected = None
        for scope in scopes:
            if scope.get("name") == "C_damsire_manhattan_cafe_hakodate_good" and scope.get("verdict") in {"RECOMMENDED", "LIMITED"}:
                selected = scope
                break
        selected = selected or (scopes[0] if scopes else {})
        return {
            "implementation_id": "phase_e_step6_damsire_manhattan_cafe_hakodate_good",
            "target_knowledge_file": "knowledge/bloodlines/broodmare.py",
            "add_key": detail,
            "target_statistics": {
                "target_count": selected.get("target_count"),
                "scope_applicable_count": selected.get("scope_applicable_count"),
                "fn_count": selected.get("fn_count"),
                "non_fn_count": selected.get("non_fn_count"),
                "counter_count": selected.get("counter_count"),
                "counter_fn_count": selected.get("counter_fn_count"),
                "counter_non_fn_count": selected.get("counter_non_fn_count"),
            },
            "dam_sire_only": True,
            "surface_condition": "any",
            "distance_condition": "observed: 1200, 1700, 1800, 2000",
            "track_condition": "good",
            "course_condition": "hakodate",
            "race_shape_condition": "none",
            "running_style_condition": "none",
            "evaluation_direction": "positive_support_only_when existing Bloodline unit would otherwise be missing",
            "same_unit_as_existing_knowledge": "broodmare sire profile",
            "explain_text": "DamSire Manhattan Cafe can support stamina and sustained-speed context at Hakodate when the profile is otherwise missing.",
            "applicable_targets": selected.get("target_horses", []),
            "excluded_targets": [],
            "expected_targets": selected.get("target_horses", []),
            "side_effect_check_targets": "all other Manhattan Cafe dam-sire horses in the 22-race baseline",
            "accept_criteria": "Knowledge key is added without changing baseline before Step6; Step6 must show no unexpected FP expansion.",
            "revert_criteria": "Reject if the addition affects broad non-FN horses or cannot be connected through existing Bloodline units.",
            "selected_scope": selected.get("name"),
        }

    def _validation_status(self, target_records, target_rows, counter_rows, existing, specification):
        if not target_records or not target_rows:
            return "INSUFFICIENT_DATA"
        if existing.get("broodmare_profile_exists"):
            return "PARTIALLY_VALIDATED"
        stats = specification.get("target_statistics") or {}
        if stats.get("fn_count", 0) >= 3 and stats.get("counter_count", 0) == 0:
            return "VALIDATED"
        return "PARTIALLY_VALIDATED"

    def _annotate_database(
        self,
        database,
        target_records,
        validation_status,
        missing_type,
        specification,
        counter_rows,
    ):
        ids = {record.get("candidate_id") for record in target_records}
        stats = specification.get("target_statistics") or {}
        for record in self._list(database.get("records")):
            if not isinstance(record, dict) or record.get("candidate_id") not in ids:
                continue
            record.update(
                {
                    "knowledge_validation_status": validation_status,
                    "knowledge_missing_type": missing_type,
                    "causal_confidence": "HIGH" if validation_status == "VALIDATED" else "MEDIUM",
                    "recommended_scope": specification,
                    "counter_group_size": len(counter_rows),
                    "affected_fn_count": stats.get("fn_count"),
                    "affected_non_fn_count": stats.get("non_fn_count"),
                    "potential_fp_risk": "LOW" if not counter_rows else "MEDIUM",
                    "recommended_implementation_id": specification.get("implementation_id"),
                    "knowledge_validation_version": self.VALIDATION_VERSION,
                }
            )
        database["updated_at"] = datetime.now(timezone.utc).isoformat()
        return database

    def _count_annotated(self, database, detail):
        count = 0
        for record in self._active_records(database.get("records")):
            if record.get("knowledge_validation_version") != self.VALIDATION_VERSION:
                continue
            if record.get("recommended_scope", {}).get("add_key") == detail:
                count += 1
        return count

    def _target_candidate_records(self, records, category, detail):
        result = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("root_primary_candidate") != "BloodlineEvaluator":
                continue
            if record.get("bloodline_primary_factor") != "KnowledgeMissing":
                continue
            for gap in self._list(record.get("knowledge_gaps")):
                if isinstance(gap, dict) and gap.get("category") == category and self._same(gap.get("detail"), detail):
                    result.append(record)
                    break
        return result

    def _common_conditions(self, rows):
        result = {}
        for key in ["racecourse", "surface", "distance", "track_condition", "running_style", "pace_prediction"]:
            result[key] = self._counter_items(row.get(key) for row in rows)
        return result

    def _baseline_metrics(self, rows):
        decisions = Counter(str(row.get("decision") or "").upper() for row in rows)
        fn = sum(1 for row in rows if self._is_fn_row(row))
        fp = sum(1 for row in rows if str(row.get("decision") or "").upper() == "BUY" and self._to_int(row.get("actual_finish")) and self._to_int(row.get("actual_finish")) >= 4)
        buy3 = sum(1 for row in rows if str(row.get("decision") or "").upper() == "BUY" and self._to_int(row.get("actual_finish")) and self._to_int(row.get("actual_finish")) <= 3)
        top5_3 = sum(1 for row in rows if row.get("top5") and self._to_int(row.get("actual_finish")) and self._to_int(row.get("actual_finish")) <= 3)
        return {
            "races": len({row.get("race_id") for row in rows}),
            "horses": len(rows),
            "BUY": decisions.get("BUY", 0),
            "CAUTION": decisions.get("CAUTION", 0),
            "PASS": decisions.get("PASS", 0),
            "FN": fn,
            "FP": fp,
            "BUY3": buy3,
            "Top5_3": top5_3,
        }

    def _matching_counter(self, rows, **conditions):
        result = []
        for row in rows:
            matched = True
            for key, expected in conditions.items():
                if expected in (None, "", "any"):
                    continue
                if key == "min_distance" and int(row.get("distance") or 0) < expected:
                    matched = False
                elif key == "max_distance" and int(row.get("distance") or 0) > expected:
                    matched = False
                elif key not in {"min_distance", "max_distance"} and row.get(key) != expected:
                    matched = False
            if matched:
                result.append(row)
        return result

    def _is_fn_row(self, row):
        finish = self._to_int(row.get("actual_finish"))
        decision = str(row.get("decision") or "").upper()
        return finish is not None and finish <= 3 and decision != "BUY"

    def _official_map(self, rows):
        mapping = {}
        for row in self._list(rows):
            if not isinstance(row, dict):
                continue
            mapping[self._normalize(row.get("horse_name"))] = row
        return mapping

    def _bloodline_explain(self, horse):
        root = horse.get("bloodline_root_cause")
        if isinstance(root, dict):
            causes = self._list(root.get("bloodline_root_causes"))
            if causes:
                return str(causes[0].get("reason") or causes[0].get("detail") or "")
        return str(horse.get("explain_summary") or "")[:160]

    def _distance_to_buy(self, horse):
        attribution = horse.get("decision_attribution")
        if isinstance(attribution, dict):
            return attribution.get("distance_to_buy")
        score = self._to_float(horse.get("decision_score"))
        return round(0.80 - score, 3) if score is not None else None

    def _pace_prediction(self, analysis):
        race_pace = analysis.get("race_pace") if isinstance(analysis.get("race_pace"), dict) else {}
        structure = analysis.get("race_structure") if isinstance(analysis.get("race_structure"), dict) else {}
        return race_pace.get("pace_prediction") or structure.get("pace") or "unknown"

    def _nick_key(self, horse):
        sire = horse.get("sire") or "unknown_sire"
        dam_sire = horse.get("broodmare_sire") or "unknown_dam_sire"
        return f"{sire} x {dam_sire}"

    def _first_present(self, *values):
        for value in values:
            if value not in (None, ""):
                return value
        return None

    def _report_row(self, row):
        data = dict(row)
        for key in [
            "actual_finish",
            "ai_rank",
            "decision_score",
            "bloodline_score",
            "distance",
        ]:
            if data.get(key) in (None, ""):
                data[key] = "-"
        return data

    def _load_database(self):
        if not self.db_path.exists():
            return {"records": [], "aggregates": []}
        try:
            return json.loads(self.db_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"records": [], "aggregates": [], "warnings": ["candidate database unreadable"]}

    def _save_database(self, database):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.write_text(json.dumps(database, ensure_ascii=False, indent=2), encoding="utf-8")

    def _active_records(self, records):
        return [
            record for record in self._list(records)
            if isinstance(record, dict) and record.get("ranking_active") is not False
        ]

    def _race_date(self, race_id):
        parts = str(race_id or "").split("_")
        return parts[1] if len(parts) > 1 else ""

    def _counter_items(self, values):
        return [
            {"value": key, "count": value}
            for key, value in Counter(value for value in values if value not in (None, "")).most_common()
        ]

    def _common_value(self, rows, key):
        counts = Counter(row.get(key) for row in rows if row.get(key) not in (None, ""))
        return counts.most_common(1)[0][0] if counts else None

    def _same(self, left, right):
        return self._normalize(left) == self._normalize(right)

    def _normalize(self, value):
        return "".join(unicodedata.normalize("NFKC", str(value or "")).split())

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


if __name__ == "__main__":
    result = RecommendedKnowledgeValidator().validate()
    print(
        {
            "status": result.get("knowledge_validation_status"),
            "target_horse_count": result.get("target_horse_count"),
            "counter_group_size": result.get("counter_group_size"),
            "recommended_implementation_id": result.get("recommended_specification", {}).get("implementation_id"),
            "report_path": str(RecommendedKnowledgeValidator.DEFAULT_REPORT_PATH),
        }
    )
