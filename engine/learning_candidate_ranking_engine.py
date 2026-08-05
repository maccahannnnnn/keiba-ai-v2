"""Rank stored learning candidates for human review.

LearningCandidateRankingEngine reads improvement_candidates.json and writes a
ranking report. It does not mutate candidates, change evaluators, update
knowledge, or affect prediction output.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import re
from pathlib import Path


class LearningCandidateRankingEngine:
    """Analyze stored learning candidates and rank review priorities."""

    DEFAULT_DB_PATH = Path("learning/improvement_candidates.json")
    DEFAULT_REPORT_PATH = Path("reports/learning_candidate_ranking.md")

    COURSE_PATTERN = re.compile(
        r"^race_(?P<date>\d{8})_(?P<course>[a-z]+)_(?P<race>\d{1,2}R)$",
        re.IGNORECASE,
    )

    def __init__(self, db_path=None, report_path=None):
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self.report_path = Path(report_path) if report_path else self.DEFAULT_REPORT_PATH

    def rank(self):
        """Read candidate DB, create ranking items, and write report."""

        database = self._load_database()
        records = self._list(database.get("records"))
        active_records = self._active_records(records)
        ranking = self._build_ranking(active_records)
        report = self._write_report(ranking, records, database)
        return {
            "status": "ranked",
            "db_path": str(self.db_path),
            "report_path": str(self.report_path),
            "candidate_records": len(records),
            "active_candidate_records": len(active_records),
            "ranking_count": len(ranking),
            "ranking": ranking,
            "report": report,
            "warnings": self._list(database.get("warnings")),
        }

    def _build_ranking(self, records):
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
                candidate_type = candidate.get("target_type") or candidate.get("candidate_type") or "Other"
                key = f"{candidate_type}::{target}"
                groups.setdefault(
                    key,
                    self._empty_group(target, candidate_type),
                )
                self._add_record(groups[key], record, candidate, primary)

        items = []
        for group in groups.values():
            items.append(self._finalize_group(group))

        items.sort(
            key=lambda item: (
                -item.get("ranking_score", 0),
                -item.get("occurrences", 0),
                item.get("candidate_name", ""),
            )
        )
        for index, item in enumerate(items, start=1):
            item["rank"] = index
        return items

    def _empty_group(self, target, candidate_type):
        return {
            "candidate_name": target,
            "candidate_type": candidate_type,
            "occurrences": 0,
            "fn_count": 0,
            "fp_count": 0,
            "race_ids": [],
            "courses": [],
            "distances": [],
            "surfaces": [],
            "track_conditions": [],
            "race_classes": [],
            "created_at_values": [],
            "updated_at_values": [],
            "confidence_values": [],
            "decision_score_values": [],
            "candidate_weights": [],
            "attribution_scores": [],
            "primary_count": 0,
            "secondary_count": 0,
            "unknown_count": 0,
            "evidence_count": 0,
            "counter_evidence_count": 0,
            "confidence_counts": Counter(),
            "decision_attribution_confidence_counts": Counter(),
            "primary_blocker_count": 0,
            "primary_supporter_count": 0,
            "fn_blocker_count": 0,
            "fp_overvaluation_count": 0,
            "distance_to_buy_values": [],
            "decision_margin_values": [],
            "single_cause_count": 0,
            "multiple_cause_count": 0,
            "fixed_decision_blocker_count": 0,
            "unknown_attribution_count": 0,
            "counterfactual_count": 0,
            "counterfactual_feasible_count": 0,
            "root_primary_count": 0,
            "root_fn_count": 0,
            "root_fp_count": 0,
            "decision_gate_count": 0,
            "root_importance_values": [],
            "root_confidence_counts": Counter(),
            "unknown_root_count": 0,
            "bloodline_root_primary_count": 0,
            "bloodline_factor_counts": Counter(),
            "bloodline_knowledge_missing_count": 0,
            "bloodline_unknown_count": 0,
            "knowledge_gap_count": 0,
            "knowledge_gap_category_counts": Counter(),
            "knowledge_gap_detail_counts": Counter(),
            "knowledge_validation_status_counts": Counter(),
            "knowledge_validation_count": 0,
            "recommended_implementation_ids": Counter(),
            "shadow_validation_count": 0,
            "shadow_validation_status_counts": Counter(),
            "shadow_candidate_ids": Counter(),
            "shadow_fn_improved_count": 0,
            "shadow_fp_created_count": 0,
            "related_evaluators": Counter(),
            "related_knowledge": Counter(),
            "related_decisions": Counter(),
            "horses": [],
        }

    def _add_record(self, group, record, candidate, primary):
        group["occurrences"] += 1
        if candidate.get("target") == primary:
            group["primary_count"] += 1
        elif candidate.get("target") == "UNKNOWN":
            group["unknown_count"] += 1
        else:
            group["secondary_count"] += 1
        if record.get("decision_primary_factor") == candidate.get("target"):
            if record.get("fn"):
                group["primary_blocker_count"] += 1
                group["fn_blocker_count"] += 1
            if record.get("fp"):
                group["primary_supporter_count"] += 1
                group["fp_overvaluation_count"] += 1
        if record.get("root_primary_candidate") == candidate.get("target"):
            group["root_primary_count"] += 1
            group["root_fn_count"] += 1 if record.get("fn") else 0
            group["root_fp_count"] += 1 if record.get("fp") else 0
        bloodline_factor = record.get("bloodline_primary_factor")
        if bloodline_factor:
            group["bloodline_factor_counts"][bloodline_factor] += 1
            if candidate.get("target") == f"BloodlineEvaluator:{bloodline_factor}":
                group["bloodline_root_primary_count"] += 1
        if bloodline_factor == "Knowledge不足":
            group["bloodline_knowledge_missing_count"] += 1
        if bloodline_factor == "UNKNOWN":
            group["bloodline_unknown_count"] += 1
        if bloodline_factor == "KnowledgeMissing":
            group["bloodline_knowledge_missing_count"] += 1
        for gap in self._list(record.get("knowledge_gaps")):
            if not isinstance(gap, dict):
                continue
            group["knowledge_gap_count"] += 1
            if gap.get("category"):
                group["knowledge_gap_category_counts"][gap.get("category")] += 1
            if gap.get("detail"):
                group["knowledge_gap_detail_counts"][gap.get("detail")] += 1
        if record.get("knowledge_validation_version"):
            group["knowledge_validation_count"] += 1
            group["knowledge_validation_status_counts"][
                record.get("knowledge_validation_status") or "UNKNOWN"
            ] += 1
        if record.get("recommended_implementation_id"):
            group["recommended_implementation_ids"][record.get("recommended_implementation_id")] += 1
        if record.get("shadow_validation_version"):
            group["shadow_validation_count"] += 1
            group["shadow_validation_status_counts"][
                record.get("shadow_validation_status") or "UNKNOWN"
            ] += 1
            if record.get("shadow_candidate_id"):
                group["shadow_candidate_ids"][record.get("shadow_candidate_id")] += 1
            if record.get("shadow_fn_improved"):
                group["shadow_fn_improved_count"] += 1
            if record.get("shadow_fp_created"):
                group["shadow_fp_created_count"] += 1
        group["fn_count"] += 1 if record.get("fn") else 0
        group["fp_count"] += 1 if record.get("fp") else 0
        self._append(group["race_ids"], record.get("race_id"))
        self._append(group["horses"], record.get("horse"))

        meta = self._race_meta(record)
        for field, target in [
            ("racecourse", "courses"),
            ("distance", "distances"),
            ("surface", "surfaces"),
            ("track_condition", "track_conditions"),
            ("race_class", "race_classes"),
        ]:
            self._append(group[target], meta.get(field))

        self._append(group["created_at_values"], record.get("created_at"))
        self._append(group["updated_at_values"], record.get("updated_at"))

        confidence = self._confidence_score(record.get("confidence"))
        if confidence is not None:
            group["confidence_values"].append(confidence)

        decision_score = self._to_float(record.get("decision_score"))
        if decision_score is not None:
            group["decision_score_values"].append(decision_score)
        distance_to_buy = self._to_float(record.get("distance_to_buy"))
        if distance_to_buy is not None:
            group["distance_to_buy_values"].append(distance_to_buy)
        decision_margin = self._to_float(record.get("decision_margin"))
        if decision_margin is not None:
            group["decision_margin_values"].append(decision_margin)
        root_importance = self._to_float(record.get("root_importance"))
        if root_importance is not None:
            group["root_importance_values"].append(root_importance)

        weight = self._to_float(candidate.get("weight_percent"))
        if weight is not None:
            group["candidate_weights"].append(weight)
        attribution_score = self._to_float(candidate.get("score"))
        if attribution_score is None:
            attribution_score = self._to_float(candidate.get("weight"))
        if attribution_score is not None:
            group["attribution_scores"].append(attribution_score)
        group["evidence_count"] += len(self._list(candidate.get("evidence")))
        group["counter_evidence_count"] += len(self._list(candidate.get("counter_evidence")))
        group["confidence_counts"][candidate.get("confidence") or "UNKNOWN"] += 1
        group["decision_attribution_confidence_counts"][
            record.get("decision_attribution_confidence") or "UNKNOWN"
        ] += 1
        if record.get("decision_cause_count_type") == "multiple":
            group["multiple_cause_count"] += 1
        else:
            group["single_cause_count"] += 1
        if record.get("decision_fixed_blocker"):
            group["fixed_decision_blocker_count"] += 1
        if record.get("decision_primary_factor") in (None, "", "UNKNOWN"):
            group["unknown_attribution_count"] += 1
        counterfactuals = self._list(record.get("decision_counterfactual"))
        group["counterfactual_count"] += len(counterfactuals)
        if record.get("decision_counterfactual_feasible"):
            group["counterfactual_feasible_count"] += 1
        if record.get("decision_gate") not in (None, "", "none"):
            group["decision_gate_count"] += 1
        group["root_confidence_counts"][record.get("root_confidence") or "UNKNOWN"] += 1
        if record.get("root_primary_candidate") in (None, "", "UNKNOWN"):
            group["unknown_root_count"] += 1

        linked_items = self._list(record.get("attribution_candidates"))
        if not linked_items:
            linked_items = self._list(record.get("cause_candidates"))
        for linked in linked_items:
            linked_target = linked.get("target")
            linked_type = linked.get("target_type") or linked.get("candidate_type") or "Other"
            if not linked_target or linked_target == group["candidate_name"]:
                continue
            if linked_type == "Evaluator":
                group["related_evaluators"][linked_target] += 1
            elif linked_type == "Knowledge":
                group["related_knowledge"][linked_target] += 1
            elif linked_type == "Decision":
                group["related_decisions"][linked_target] += 1

    def _finalize_group(self, group):
        occurrences = group["occurrences"]
        fn_count = group["fn_count"]
        fp_count = group["fp_count"]
        race_count = len(set(group["race_ids"]))
        fn_ratio = fn_count / occurrences if occurrences else 0.0
        fp_ratio = fp_count / occurrences if occurrences else 0.0
        reproducibility = self._reproducibility_score(group)
        condition_bias = self._condition_bias_score(group)
        impact = min(1.0, self._average(group["attribution_scores"]) or 0.0)
        occurrence_score = min(1.0, occurrences / 12.0)
        primary_score = min(1.0, group["primary_count"] / 5.0)
        root_primary_score = min(1.0, group["root_primary_count"] / 5.0)
        evidence_score = min(1.0, group["evidence_count"] / max(1, occurrences * 2))
        confidence_boost = (
            group["confidence_counts"].get("HIGH", 0) * 1.0
            + group["confidence_counts"].get("MEDIUM", 0) * 0.6
            + group["confidence_counts"].get("LOW", 0) * 0.25
        ) / max(1, occurrences)
        ranking_score = (
            primary_score * 0.20
            + root_primary_score * 0.12
            + occurrence_score * 0.14
            + fn_ratio * 0.12
            + fp_ratio * 0.08
            + reproducibility * 0.16
            + condition_bias * 0.07
            + impact * 0.12
            + evidence_score * 0.03
            + confidence_boost * 0.02
        )

        item = {
            "candidate_name": group["candidate_name"],
            "candidate_type": group["candidate_type"],
            "occurrences": occurrences,
            "fn_count": fn_count,
            "fp_count": fp_count,
            "fn_ratio": round(fn_ratio, 3),
            "fp_ratio": round(fp_ratio, 3),
            "race_count": race_count,
            "race_ids": sorted(set(group["race_ids"])),
            "primary_count": group["primary_count"],
            "secondary_count": group["secondary_count"],
            "unknown_count": group["unknown_count"],
            "racecourses": self._counter_items(group["courses"]),
            "distances": self._counter_items(group["distances"]),
            "surfaces": self._counter_items(group["surfaces"]),
            "track_conditions": self._counter_items(group["track_conditions"]),
            "race_classes": self._counter_items(group["race_classes"]),
            "first_seen": self._min_text(group["created_at_values"]),
            "latest_seen": self._max_text(group["updated_at_values"]),
            "average_confidence": self._rounded_average(group["confidence_values"]),
            "average_decision_score": self._rounded_average(group["decision_score_values"]),
            "average_distance_to_buy": self._rounded_average(group["distance_to_buy_values"]),
            "average_decision_margin": self._rounded_average(group["decision_margin_values"]),
            "average_candidate_weight": self._rounded_average(group["candidate_weights"]),
            "attribution_score_total": round(sum(group["attribution_scores"]), 3),
            "average_attribution_score": self._rounded_average(group["attribution_scores"]),
            "evidence_count": group["evidence_count"],
            "counter_evidence_count": group["counter_evidence_count"],
            "confidence_counts": dict(group["confidence_counts"]),
            "decision_attribution_confidence_counts": dict(
                group["decision_attribution_confidence_counts"]
            ),
            "primary_blocker_count": group["primary_blocker_count"],
            "primary_supporter_count": group["primary_supporter_count"],
            "fn_blocker_count": group["fn_blocker_count"],
            "fp_overvaluation_count": group["fp_overvaluation_count"],
            "single_cause_count": group["single_cause_count"],
            "multiple_cause_count": group["multiple_cause_count"],
            "fixed_decision_blocker_count": group["fixed_decision_blocker_count"],
            "unknown_attribution_count": group["unknown_attribution_count"],
            "counterfactual_count": group["counterfactual_count"],
            "counterfactual_feasible_count": group["counterfactual_feasible_count"],
            "root_primary_count": group["root_primary_count"],
            "root_fn_count": group["root_fn_count"],
            "root_fp_count": group["root_fp_count"],
            "decision_gate_count": group["decision_gate_count"],
            "average_root_importance": self._rounded_average(group["root_importance_values"]),
            "root_confidence_counts": dict(group["root_confidence_counts"]),
            "unknown_root_count": group["unknown_root_count"],
            "bloodline_root_primary_count": group["bloodline_root_primary_count"],
            "bloodline_factor_counts": dict(group["bloodline_factor_counts"]),
            "bloodline_knowledge_missing_count": group["bloodline_knowledge_missing_count"],
            "bloodline_unknown_count": group["bloodline_unknown_count"],
            "knowledge_gap_count": group["knowledge_gap_count"],
            "knowledge_gap_category_counts": dict(group["knowledge_gap_category_counts"].most_common(5)),
            "knowledge_gap_detail_counts": dict(group["knowledge_gap_detail_counts"].most_common(5)),
            "knowledge_validation_count": group["knowledge_validation_count"],
            "knowledge_validation_status_counts": dict(group["knowledge_validation_status_counts"]),
            "recommended_implementation_ids": dict(group["recommended_implementation_ids"].most_common(5)),
            "shadow_validation_count": group["shadow_validation_count"],
            "shadow_validation_status_counts": dict(group["shadow_validation_status_counts"]),
            "shadow_candidate_ids": dict(group["shadow_candidate_ids"].most_common(5)),
            "shadow_fn_improved_count": group["shadow_fn_improved_count"],
            "shadow_fp_created_count": group["shadow_fp_created_count"],
            "related_evaluators": self._top_counter(group["related_evaluators"]),
            "related_knowledge": self._top_counter(group["related_knowledge"]),
            "related_decisions": self._top_counter(group["related_decisions"]),
            "reproducibility_score": round(reproducibility, 3),
            "condition_bias_score": round(condition_bias, 3),
            "impact_score": round(impact, 3),
            "ranking_score": round(ranking_score, 3),
        }
        item["priority"] = self._priority(item)
        item["status"] = self._status(item["priority"])
        item["improvement_candidate"] = self._improvement_candidate_text(item)
        return item

    def _race_meta(self, record):
        meta = {
            "racecourse": record.get("racecourse"),
            "distance": record.get("distance"),
            "surface": record.get("surface"),
            "track_condition": record.get("track_condition"),
            "race_class": record.get("race_class"),
        }
        race_id = record.get("race_id") or ""
        match = self.COURSE_PATTERN.match(str(race_id))
        if match and not meta.get("racecourse"):
            meta["racecourse"] = match.group("course").lower()
        for key in meta:
            if meta.get(key) in (None, ""):
                meta[key] = "unknown"
        return meta

    def _reproducibility_score(self, group):
        occurrences = group["occurrences"]
        if not occurrences:
            return 0.0
        race_counter = Counter(group["race_ids"])
        race_count = len(race_counter)
        max_race_share = max(race_counter.values()) / occurrences if race_counter else 1.0
        race_spread = min(1.0, race_count / 5.0)
        anti_single_race = 1.0 - max(0.0, max_race_share - 0.35)
        return max(0.0, min(1.0, (race_spread * 0.65) + (anti_single_race * 0.35)))

    def _condition_bias_score(self, group):
        scores = []
        for key in ["courses", "distances", "surfaces", "track_conditions", "race_classes"]:
            known = [value for value in group[key] if value not in (None, "", "unknown")]
            if not known:
                continue
            counter = Counter(known)
            scores.append(max(counter.values()) / len(known))
        if not scores:
            return 0.0
        return max(scores)

    def _priority(self, item):
        score = item.get("ranking_score", 0)
        occurrences = item.get("occurrences", 0)
        fn_count = item.get("fn_count", 0)
        race_count = item.get("race_count", 0)
        if score >= 0.76 and occurrences >= 8 and race_count >= 3:
            return "S"
        if score >= 0.62 and occurrences >= 5:
            return "A"
        if score >= 0.48 and occurrences >= 3:
            return "B"
        if score >= 0.34:
            return "C"
        if fn_count >= 3:
            return "C"
        return "D"

    def _status(self, priority):
        if priority in {"S", "A"}:
            return "REVIEW_REQUIRED"
        if priority == "B":
            return "WATCH"
        return "LOW_PRIORITY"

    def _improvement_candidate_text(self, item):
        target = item.get("candidate_name")
        ctype = item.get("candidate_type")
        if ctype == "Evaluator":
            return f"{target} evaluation should be reviewed"
        if ctype == "Knowledge":
            return f"{target} knowledge should be reviewed"
        if ctype == "Decision":
            return f"{target} decision path should be reviewed"
        return f"{target} should be reviewed"

    def _write_report(self, ranking, records, database):
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Learning Candidate Ranking",
            "",
            f"- Generated: {datetime.now(timezone.utc).isoformat()}",
            f"- Source DB: {self.db_path}",
            f"- Candidate Records: {len(records)}",
            f"- Active Candidate Records: {len(self._active_records(records))}",
            f"- Inactive Historical Records: {len(records) - len(self._active_records(records))}",
            f"- Ranked Candidates: {len(ranking)}",
            f"- DB Updated At: {database.get('updated_at')}",
            "",
            "## Ranking Summary",
            "",
            "| Rank | Candidate | Priority | Score | Primary | Root Primary | Occurrence | FN | FP | Root FN | Root FP | Avg Root | Decision Gate | Status |",
            "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for item in ranking:
            lines.append(
                "| {rank} | {candidate_name} | {priority} | {ranking_score:.3f} | "
                "{primary_count} | {root_primary_count} | {occurrences} | {fn_count} | {fp_count} | "
                "{root_fn_count} | {root_fp_count} | {average_root_importance} | "
                "{decision_gate_count} | {status} |".format(
                    **item
                )
            )

        lines.extend(["", "## Candidate Details", ""])
        for item in ranking:
            lines.extend(
                [
                    f"### Rank {item['rank']} - {item['candidate_name']}",
                    "",
                    f"- Priority: {item['priority']}",
                    f"- Status: {item['status']}",
                    f"- Occurrence: {item['occurrences']}",
                    f"- Primary Count: {item['primary_count']}",
                    f"- Root Primary Count: {item['root_primary_count']}",
                    f"- Root FN Count: {item['root_fn_count']}",
                    f"- Root FP Count: {item['root_fp_count']}",
                    f"- Average Root Importance: {item['average_root_importance']}",
                    f"- Root Confidence: {item['root_confidence_counts']}",
                    f"- Decision Gate Count: {item['decision_gate_count']}",
                    f"- UNKNOWN Root Count: {item['unknown_root_count']}",
                    f"- Bloodline Root Primary Count: {item['bloodline_root_primary_count']}",
                    f"- Bloodline Factor Counts: {item['bloodline_factor_counts']}",
                    f"- Bloodline Knowledge Missing Count: {item['bloodline_knowledge_missing_count']}",
                    f"- Bloodline UNKNOWN Count: {item['bloodline_unknown_count']}",
                    f"- Knowledge Gap Count: {item['knowledge_gap_count']}",
                    f"- Knowledge Gap Category Counts: {item['knowledge_gap_category_counts']}",
                    f"- Knowledge Gap Detail Counts: {item['knowledge_gap_detail_counts']}",
                    f"- Knowledge Validation Count: {item['knowledge_validation_count']}",
                    f"- Knowledge Validation Status Counts: {item['knowledge_validation_status_counts']}",
                    f"- Recommended Implementation IDs: {item['recommended_implementation_ids']}",
                    f"- Shadow Validation Count: {item['shadow_validation_count']}",
                    f"- Shadow Validation Status Counts: {item['shadow_validation_status_counts']}",
                    f"- Shadow Candidate IDs: {item['shadow_candidate_ids']}",
                    f"- Shadow FN Improved Count: {item['shadow_fn_improved_count']}",
                    f"- Shadow FP Created Count: {item['shadow_fp_created_count']}",
                    f"- Secondary Count: {item['secondary_count']}",
                    f"- UNKNOWN Count: {item['unknown_count']}",
                    f"- FN: {item['fn_count']}",
                    f"- FP: {item['fp_count']}",
                    f"- Race Count: {item['race_count']}",
                    f"- Attribution Score Total: {item['attribution_score_total']}",
                    f"- Average Attribution Score: {item['average_attribution_score']}",
                    f"- Evidence Count: {item['evidence_count']}",
                    f"- Counter Evidence Count: {item['counter_evidence_count']}",
                    f"- Attribution Confidence: {item['confidence_counts']}",
                    f"- Racecourse: {self._format_counter_items(item['racecourses'])}",
                    f"- Surface: {self._format_counter_items(item['surfaces'])}",
                    f"- Distance: {self._format_counter_items(item['distances'])}",
                    f"- Track Condition: {self._format_counter_items(item['track_conditions'])}",
                    f"- Race Class: {self._format_counter_items(item['race_classes'])}",
                    f"- First Seen: {item['first_seen']}",
                    f"- Latest Seen: {item['latest_seen']}",
                    f"- Average Confidence: {item['average_confidence']}",
                    f"- Average DecisionScore: {item['average_decision_score']}",
                    f"- Average Distance To BUY: {item['average_distance_to_buy']}",
                    f"- Average Decision Margin: {item['average_decision_margin']}",
                    f"- Primary Blocker Count: {item['primary_blocker_count']}",
                    f"- Primary Supporter Count: {item['primary_supporter_count']}",
                    f"- FN Blocker Count: {item['fn_blocker_count']}",
                    f"- FP Overvaluation Count: {item['fp_overvaluation_count']}",
                    f"- Single Cause Count: {item['single_cause_count']}",
                    f"- Multiple Cause Count: {item['multiple_cause_count']}",
                    f"- Fixed Decision Blocker Count: {item['fixed_decision_blocker_count']}",
                    f"- UNKNOWN Attribution Count: {item['unknown_attribution_count']}",
                    f"- Counterfactual Count: {item['counterfactual_count']}",
                    f"- Counterfactual Feasible Count: {item['counterfactual_feasible_count']}",
                    f"- Decision Attribution Confidence: {item['decision_attribution_confidence_counts']}",
                    f"- Related Evaluator: {self._format_counter_items(item['related_evaluators'])}",
                    f"- Related Knowledge: {self._format_counter_items(item['related_knowledge'])}",
                    f"- Improvement Candidate: {item['improvement_candidate']}",
                    "",
                ]
            )

        recommended = self._recommended_candidate(ranking)
        lines.extend(
            [
                "## Recommended Implementation Candidate",
                "",
            ]
        )
        if recommended:
            lines.extend(
                [
                    f"- Candidate: {recommended.get('candidate_name')}",
                    f"- Priority: {recommended.get('priority')}",
                    f"- Primary Count: {recommended.get('primary_count')}",
                    f"- Average Attribution Score: {recommended.get('average_attribution_score')}",
                    f"- Evidence Count: {recommended.get('evidence_count')}",
                    f"- Reason: strongest evidence-backed primary candidate in current ranking",
                    "- Status: requires human APPROVED before implementation",
                    "",
                ]
            )
        else:
            lines.extend(["- None", ""])

        lines.extend(
            [
                "## Guardrails",
                "",
                "- This ranking reads learning/improvement_candidates.json only.",
                "- It does not change candidate records, evaluator logic, decision logic, knowledge, weights, CSV, or scores.",
                "- Priority is for human review and implementation judgment only.",
            ]
        )
        report = "\n".join(lines) + "\n"
        self.report_path.write_text(report, encoding="utf-8")
        return report

    def _recommended_candidate(self, ranking):
        for item in ranking:
            if (
                item.get("candidate_name") != "UNKNOWN"
                and item.get("primary_count", 0) > 0
                and item.get("evidence_count", 0) >= item.get("primary_count", 0)
                and item.get("priority") in {"S", "A", "B"}
            ):
                return item
        return None

    def _load_database(self):
        if not self.db_path.exists():
            return {
                "version": "1.0",
                "records": [],
                "aggregates": [],
                "warnings": [f"candidate database not found: {self.db_path}"],
            }
        try:
            return json.loads(self.db_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "version": "1.0",
                "records": [],
                "aggregates": [],
                "warnings": [f"candidate database unreadable: {exc}"],
            }

    def _active_records(self, records):
        return [
            item
            for item in self._list(records)
            if isinstance(item, dict) and item.get("ranking_active") is not False
        ]

    def _confidence_score(self, confidence):
        if isinstance(confidence, dict):
            for key in ["score", "confidence_score"]:
                value = self._to_float(confidence.get(key))
                if value is not None:
                    return value
            level = str(confidence.get("level") or confidence.get("confidence_level") or "").lower()
            return {
                "very_high": 1.0,
                "high": 0.85,
                "medium": 0.6,
                "low": 0.35,
                "very_low": 0.15,
            }.get(level)
        return self._to_float(confidence)

    def _counter_items(self, values):
        counter = Counter(value for value in values if value not in (None, ""))
        if not counter:
            return [{"value": "unknown", "count": 0}]
        return [
            {"value": value, "count": count}
            for value, count in counter.most_common()
        ]

    def _top_counter(self, counter, limit=5):
        return [
            {"value": value, "count": count}
            for value, count in counter.most_common(limit)
        ]

    def _format_counter_items(self, items):
        if not items:
            return "none"
        return ", ".join(
            f"{item.get('value')}({item.get('count')})"
            for item in items[:5]
        )

    def _average(self, values):
        numbers = [value for value in values if isinstance(value, (int, float))]
        if not numbers:
            return None
        return sum(numbers) / len(numbers)

    def _rounded_average(self, values):
        average = self._average(values)
        if average is None:
            return "unknown"
        return round(average, 3)

    def _min_text(self, values):
        values = [str(value) for value in values if value not in (None, "")]
        return min(values) if values else "unknown"

    def _max_text(self, values):
        values = [str(value) for value in values if value not in (None, "")]
        return max(values) if values else "unknown"

    def _append(self, values, value):
        if value not in (None, ""):
            values.append(value)

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
    result = LearningCandidateRankingEngine().rank()
    print(
        {
            "status": result.get("status"),
            "candidate_records": result.get("candidate_records"),
            "ranking_count": result.get("ranking_count"),
            "report_path": result.get("report_path"),
        }
    )
