"""Rank MeetingBias evidence candidates without changing evaluation output."""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path


class MeetingBiasCandidateRanker:
    """Aggregate race-pattern evidence into narrow MeetingBias candidates."""

    RANKING_VERSION = "phase_g_step2_v1"
    DEFAULT_REPORT_PATH = Path("reports/meeting_bias_candidate_ranking.md")

    def rank(self, evidence=None, report_path=None):
        rows = [row for row in (evidence or []) if isinstance(row, dict)]
        groups = {}
        for row in rows:
            responsibility = row.get("primary_responsibility")
            if responsibility not in {"MEETING_BIAS_PRIMARY", "MULTIPLE_CAUSES"}:
                continue
            if responsibility == "MULTIPLE_CAUSES" and "MeetingBias" not in row.get("secondary_responsibilities", []):
                continue
            key = self._candidate_key(row)
            groups.setdefault(key, self._empty_candidate(row))
            self._add_evidence(groups[key], row)

        candidates = [self._finalize(item) for item in groups.values()]
        candidates.sort(
            key=lambda item: (
                -self._priority_value(item.get("priority")),
                -item.get("ranking_score", 0),
                -item.get("support_races", 0),
                item.get("candidate_name", ""),
            )
        )
        for index, candidate in enumerate(candidates, start=1):
            candidate["rank"] = index

        selected = self._select_shadow_candidate(candidates)
        for candidate in candidates:
            candidate["selected_for_initial_shadow"] = (
                bool(selected) and candidate.get("candidate_id") == selected.get("candidate_id")
            )

        report = self._format_report(candidates, selected)
        path = Path(report_path) if report_path else self.DEFAULT_REPORT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        return {
            "ranking_version": self.RANKING_VERSION,
            "candidate_count": len(candidates),
            "shadow_ready_candidate_count": sum(1 for item in candidates if item.get("shadow_testability") == "HIGH"),
            "top_candidate": selected,
            "candidates": candidates,
            "report_path": str(path),
        }

    def _candidate_key(self, row):
        return (
            row.get("racecourse"),
            row.get("surface"),
            row.get("distance_category"),
            row.get("track_condition"),
            row.get("meeting_stage"),
            row.get("observed_pattern"),
        )

    def _empty_candidate(self, row):
        course = row.get("racecourse") or "unknown"
        surface = row.get("surface") or "unknown"
        distance = row.get("distance_category") or "unknown"
        condition = row.get("track_condition") or "unknown"
        stage = row.get("meeting_stage") or "unknown"
        pattern = row.get("observed_pattern") or "unknown_pattern"
        return {
            "candidate_id": self._candidate_id(course, surface, distance, condition, stage, pattern),
            "candidate_name": f"{course} {surface} {distance} {condition} {stage} {pattern}",
            "racecourse": course,
            "surface": surface,
            "distance_scope": distance,
            "track_condition_scope": condition,
            "meeting_stage_scope": stage,
            "course_configuration_scope": row.get("course_configuration") or "UNKNOWN",
            "running_style_scope": self._running_style_scope(pattern),
            "frame_scope": self._frame_scope(pattern),
            "evidence_ids": [],
            "support_race_ids": [],
            "support_horse_names": [],
            "counterexample_race_ids": [],
            "counterexample_horse_names": [],
            "fn_related_count": 0,
            "fp_related_count": 0,
            "track_bias_overlap_count": 0,
            "course_overlap_count": 0,
            "race_shape_overlap_count": 0,
            "pace_overlap_count": 0,
            "evidence_strength_values": [],
            "data_completeness_values": [],
            "responsibility_counts": Counter(),
            "pattern_counts": Counter(),
            "status": "EXTRACTED",
            "validation_version": self.RANKING_VERSION,
        }

    def _add_evidence(self, candidate, row):
        self._append(candidate["evidence_ids"], row.get("evidence_id"))
        self._append(candidate["support_race_ids"], row.get("race_id"))
        for horse in row.get("supporting_horses") or []:
            if isinstance(horse, dict):
                self._append(candidate["support_horse_names"], horse.get("horse_name"))
        for horse in row.get("counterexample_horses") or []:
            if isinstance(horse, dict):
                self._append(candidate["counterexample_horse_names"], horse.get("horse_name"))
                self._append(candidate["counterexample_race_ids"], row.get("race_id"))
        candidate["fn_related_count"] += int(row.get("fn_count") or 0)
        candidate["fp_related_count"] += int(row.get("fp_count") or 0)
        candidate["track_bias_overlap_count"] += 1 if row.get("track_bias_overlap") in {"MEDIUM", "HIGH"} else 0
        candidate["course_overlap_count"] += 1 if row.get("course_overlap") in {"MEDIUM", "HIGH"} else 0
        candidate["race_shape_overlap_count"] += 1 if row.get("race_shape_overlap") in {"MEDIUM", "HIGH"} else 0
        candidate["pace_overlap_count"] += 1 if row.get("pace_overlap") in {"MEDIUM", "HIGH"} else 0
        candidate["evidence_strength_values"].append(self._strength_score(row.get("evidence_strength")))
        candidate["data_completeness_values"].append(self._strength_score(row.get("data_completeness")))
        candidate["responsibility_counts"][row.get("primary_responsibility") or "UNKNOWN"] += 1
        candidate["pattern_counts"][row.get("observed_pattern") or "UNKNOWN"] += 1

    def _finalize(self, candidate):
        support_races = len(set(candidate.get("support_race_ids") or []))
        support_horses = len(set(candidate.get("support_horse_names") or []))
        counterexamples = len(set(candidate.get("counterexample_horse_names") or []))
        evidence_count = len(candidate.get("evidence_ids") or [])
        avg_strength = self._average(candidate.get("evidence_strength_values"))
        avg_completeness = self._average(candidate.get("data_completeness_values"))
        overlap = (
            candidate.get("track_bias_overlap_count", 0)
            + candidate.get("course_overlap_count", 0)
            + candidate.get("race_shape_overlap_count", 0)
            + candidate.get("pace_overlap_count", 0)
        )
        fp_risk = self._risk_level(candidate.get("fp_related_count", 0), counterexamples)
        specificity = self._specificity(candidate)
        shadow_testability = self._shadow_testability(
            support_races,
            candidate.get("fn_related_count", 0),
            overlap,
            avg_completeness,
        )
        score = (
            support_races * 2.0
            + support_horses * 0.5
            + candidate.get("fn_related_count", 0) * 1.5
            + avg_strength
            + avg_completeness
            - overlap * 0.8
            - candidate.get("fp_related_count", 0) * 1.2
            - counterexamples * 0.4
        )
        priority = self._priority(score, shadow_testability, fp_risk, support_races)
        candidate.update(
            {
                "support_races": support_races,
                "support_horses": support_horses,
                "counterexample_races": len(set(candidate.get("counterexample_race_ids") or [])),
                "counterexample_horses": counterexamples,
                "meeting_bias_specificity": specificity,
                "evidence_strength": self._label(avg_strength),
                "data_completeness": self._label(avg_completeness),
                "fp_risk": fp_risk,
                "shadow_testability": shadow_testability,
                "recommended_shadow_scope": self._shadow_scope(candidate),
                "ranking_score": round(score, 3),
                "priority": priority,
                "recommended_reason": self._reason(candidate, support_races, overlap, fp_risk),
            }
        )
        for key in ["evidence_strength_values", "data_completeness_values"]:
            candidate.pop(key, None)
        candidate["responsibility_counts"] = dict(candidate["responsibility_counts"])
        candidate["pattern_counts"] = dict(candidate["pattern_counts"])
        return candidate

    def _select_shadow_candidate(self, candidates):
        eligible = [
            item for item in candidates
            if item.get("shadow_testability") == "HIGH"
            and item.get("priority") in {"S", "A", "B"}
            and item.get("data_completeness") != "LOW"
        ]
        if not eligible:
            return None
        return sorted(
            eligible,
            key=lambda item: (
                -self._priority_value(item.get("priority")),
                -item.get("ranking_score", 0),
                -item.get("fn_related_count", 0),
            ),
        )[0]

    def _shadow_testability(self, support_races, fn_count, overlap, completeness):
        if support_races >= 2 and fn_count >= 1 and overlap <= 2 and completeness >= 2:
            return "HIGH"
        if support_races >= 1 and completeness >= 1:
            return "MEDIUM"
        return "LOW"

    def _priority(self, score, shadow_testability, fp_risk, support_races):
        if shadow_testability == "HIGH" and fp_risk == "LOW" and score >= 6 and support_races >= 2:
            return "S"
        if shadow_testability in {"HIGH", "MEDIUM"} and score >= 4:
            return "A"
        if score >= 2:
            return "B"
        if score >= 0:
            return "C"
        return "HOLD"

    def _reason(self, candidate, support_races, overlap, fp_risk):
        return (
            f"support_races={support_races}, fn={candidate.get('fn_related_count')}, "
            f"fp={candidate.get('fp_related_count')}, overlap={overlap}, fp_risk={fp_risk}"
        )

    def _shadow_scope(self, candidate):
        return {
            "racecourse": candidate.get("racecourse"),
            "surface": candidate.get("surface"),
            "distance_category": candidate.get("distance_scope"),
            "track_condition": candidate.get("track_condition_scope"),
            "meeting_stage": candidate.get("meeting_stage_scope"),
            "observed_pattern": next(iter(candidate.get("pattern_counts") or {"unknown": 1})),
        }

    def _candidate_id(self, *parts):
        text = "_".join(str(part or "unknown").lower().replace(" ", "_") for part in parts)
        safe = "".join(ch for ch in text if ch.isalnum() or ch == "_")
        return f"mb_{safe[:96]}"

    def _running_style_scope(self, pattern):
        if "front" in str(pattern):
            return "front_or_stalk"
        if "closer" in str(pattern) or "late" in str(pattern):
            return "closer"
        return "UNKNOWN"

    def _frame_scope(self, pattern):
        if "inside" in str(pattern):
            return "inside"
        if "outside" in str(pattern):
            return "outside"
        return "UNKNOWN"

    def _specificity(self, candidate):
        known = sum(
            1
            for key in [
                "racecourse",
                "surface",
                "distance_scope",
                "track_condition_scope",
                "meeting_stage_scope",
                "running_style_scope",
                "frame_scope",
            ]
            if candidate.get(key) not in {None, "", "UNKNOWN", "unknown"}
        )
        if known >= 6:
            return "HIGH"
        if known >= 4:
            return "MEDIUM"
        return "LOW"

    def _risk_level(self, fp_count, counterexamples):
        if fp_count >= 2 or counterexamples >= 5:
            return "HIGH"
        if fp_count or counterexamples >= 2:
            return "MEDIUM"
        return "LOW"

    def _strength_score(self, label):
        return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(str(label or "").upper(), 0)

    def _label(self, score):
        if score >= 2.5:
            return "HIGH"
        if score >= 1.5:
            return "MEDIUM"
        if score > 0:
            return "LOW"
        return "UNKNOWN"

    def _priority_value(self, value):
        return {"S": 5, "A": 4, "B": 3, "C": 2, "HOLD": 1}.get(str(value or ""), 0)

    def _average(self, values):
        values = [value for value in values if isinstance(value, (int, float))]
        return sum(values) / len(values) if values else 0.0

    def _append(self, values, value):
        if value in (None, ""):
            return
        if value not in values:
            values.append(value)

    def _format_report(self, candidates, selected):
        lines = [
            "# MeetingBias Candidate Ranking",
            "",
            f"- Generated: {datetime.now(timezone.utc).isoformat()}",
            f"- Validation version: {self.RANKING_VERSION}",
            f"- Candidate count: {len(candidates)}",
            f"- Shadow ready candidate count: {sum(1 for item in candidates if item.get('shadow_testability') == 'HIGH')}",
            f"- Top candidate: {(selected or {}).get('candidate_id', 'NO_SHADOW_CANDIDATE')}",
            "",
            "| Rank | candidate_id | candidate_name | support races | support horses | counterexamples | FN | FP | overlap | specificity | completeness | fp risk | shadow | priority | status | reason |",
            "|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|---|",
        ]
        for item in candidates:
            overlap = (
                item.get("track_bias_overlap_count", 0)
                + item.get("course_overlap_count", 0)
                + item.get("race_shape_overlap_count", 0)
                + item.get("pace_overlap_count", 0)
            )
            lines.append(
                f"| {item.get('rank')} | {item.get('candidate_id')} | {item.get('candidate_name')} | "
                f"{item.get('support_races')} | {item.get('support_horses')} | {item.get('counterexample_horses')} | "
                f"{item.get('fn_related_count')} | {item.get('fp_related_count')} | {overlap} | "
                f"{item.get('meeting_bias_specificity')} | {item.get('data_completeness')} | "
                f"{item.get('fp_risk')} | {item.get('shadow_testability')} | {item.get('priority')} | "
                f"{item.get('status')} | {item.get('recommended_reason')} |"
            )
        lines.extend(["", "## Selected Initial Shadow Candidate", ""])
        if selected:
            lines.append(json.dumps(selected, ensure_ascii=False, indent=2))
        else:
            lines.append("NO_SHADOW_CANDIDATE")
        return "\n".join(lines) + "\n"


if __name__ == "__main__":
    path = Path("learning/meeting_bias_candidates.json")
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    result = MeetingBiasCandidateRanker().rank(data.get("evidence", []))
    print(
        {
            "candidate_count": result.get("candidate_count"),
            "shadow_ready_candidate_count": result.get("shadow_ready_candidate_count"),
            "top_candidate_id": (result.get("top_candidate") or {}).get("candidate_id"),
            "report_path": result.get("report_path"),
        }
    )
