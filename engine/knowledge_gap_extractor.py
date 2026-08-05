"""Extract concrete knowledge gaps from Bloodline root-cause records.

This engine is diagnostic only. It reads Learning Candidate style records,
classifies missing bloodline knowledge, and writes a report. It never updates
Knowledge, evaluator logic, scores, decisions, or CSV definitions.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import re
from pathlib import Path


class KnowledgeGapExtractor:
    """Create explainable Knowledge Gap candidates for human review."""

    GAP_VERSION = "phase_e_step4_v1"
    DEFAULT_DB_PATH = Path("learning/improvement_candidates.json")
    DEFAULT_REPORT_PATH = Path("reports/knowledge_gap_report.md")

    PROFILE_PATTERN = re.compile(r"profile missing or insufficient:\s*(?P<sire>.*?)\s*/\s*(?P<dam>.*)$")

    def __init__(self, db_path=None, report_path=None):
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB_PATH
        self.report_path = Path(report_path) if report_path else self.DEFAULT_REPORT_PATH

    def extract_from_records(self, records=None):
        rows = [row for row in self._list(records) if isinstance(row, dict)]
        target_records = [row for row in rows if self._is_target_record(row)]
        gaps = []
        for record in target_records:
            gaps.extend(self.extract_record(record))
        ranking = self.rank_gaps(gaps)
        recommended = self.recommended_gap(ranking)
        return {
            "status": "extracted",
            "knowledge_gap_version": self.GAP_VERSION,
            "target_record_count": len(target_records),
            "knowledge_gap_count": len(gaps),
            "knowledge_gaps": gaps,
            "ranking": ranking,
            "recommended_knowledge": recommended,
            "summary": self.summary(gaps, ranking),
            "warnings": [],
        }

    def extract(self):
        database = self._load_database()
        result = self.extract_from_records(database.get("records"))
        self.write_report(result)
        return result

    def extract_record(self, record):
        if not self._is_target_record(record):
            return []
        sire, dam_sire = self._bloodline_pair(record)
        context = {
            "surface": self._clean(record.get("surface")),
            "distance": self._clean(record.get("distance")),
            "racecourse": self._clean(record.get("racecourse")),
            "track_condition": self._clean(record.get("track_condition")),
            "running_style": self._clean(record.get("running_style") or record.get("pace_style")),
        }
        base = {
            "knowledge_gap_version": self.GAP_VERSION,
            "race_id": record.get("race_id"),
            "horse": record.get("horse") or record.get("horse_name"),
            "case_type": record.get("case_type"),
            "decision": record.get("decision"),
            "finish_position": record.get("actual_finish"),
            "importance": self._importance(record),
            "confidence": self._confidence(record),
        }
        gaps = []
        if sire:
            gaps.append(self._gap(base, "SireMissing", sire, sire, "sire profile missing", context))
        if dam_sire:
            gaps.append(self._gap(base, "DamSireMissing", dam_sire, dam_sire, "broodmare sire profile missing", context))
        if sire and context["distance"] != "unknown":
            gaps.append(
                self._gap(
                    base,
                    "DistanceMissing",
                    f"{sire} {context['surface']} {context['distance']}",
                    sire,
                    "distance fit is unavailable because bloodline profile is missing",
                    context,
                )
            )
        if sire and context["track_condition"] != "unknown":
            gaps.append(
                self._gap(
                    base,
                    "TrackConditionMissing",
                    f"{sire} {context['track_condition']}",
                    sire,
                    "track condition fit is unavailable because bloodline profile is missing",
                    context,
                )
            )
        if sire and context["racecourse"] != "unknown":
            gaps.append(
                self._gap(
                    base,
                    "CourseMissing",
                    f"{sire} {context['racecourse']}",
                    sire,
                    "course fit is unavailable because bloodline profile is missing",
                    context,
                )
            )
        if sire and dam_sire:
            gaps.append(self._gap(base, "NickMissing", f"{sire} x {dam_sire}", f"{sire} x {dam_sire}", "nick knowledge missing", context))
        return gaps

    def rank_gaps(self, gaps):
        groups = {}
        for gap in self._list(gaps):
            if not isinstance(gap, dict):
                continue
            key = f"{gap.get('category')}::{gap.get('detail')}"
            group = groups.setdefault(
                key,
                {
                    "category": gap.get("category"),
                    "detail": gap.get("detail"),
                    "bloodline": gap.get("bloodline"),
                    "occurrence": 0,
                    "fn": 0,
                    "fp": 0,
                    "importance_values": [],
                    "confidence_counts": Counter(),
                    "race_ids": [],
                    "horses": [],
                    "surfaces": [],
                    "distances": [],
                    "racecourses": [],
                    "track_conditions": [],
                    "evidence": [],
                },
            )
            group["occurrence"] += 1
            group["fn"] += 1 if gap.get("case_type") == "FN" else 0
            group["fp"] += 1 if gap.get("case_type") == "FP" else 0
            group["importance_values"].append(float(gap.get("importance") or 0))
            group["confidence_counts"][gap.get("confidence") or "LOW"] += 1
            self._append(group["race_ids"], gap.get("race_id"))
            self._append(group["horses"], gap.get("horse"))
            self._append(group["surfaces"], gap.get("surface"))
            self._append(group["distances"], gap.get("distance"))
            self._append(group["racecourses"], gap.get("racecourse"))
            self._append(group["track_conditions"], gap.get("track_condition"))
            self._append(group["evidence"], gap.get("reason"))

        ranking = []
        for group in groups.values():
            occurrence = group["occurrence"]
            fn_ratio = group["fn"] / occurrence if occurrence else 0.0
            avg_importance = sum(group["importance_values"]) / max(1, len(group["importance_values"]))
            score = min(1.0, occurrence / 4.0) * 0.42 + fn_ratio * 0.32 + avg_importance * 0.20 + min(1.0, len(set(group["race_ids"])) / 3.0) * 0.06
            ranking.append(
                {
                    "category": group["category"],
                    "detail": group["detail"],
                    "bloodline": group["bloodline"],
                    "occurrence": occurrence,
                    "fn": group["fn"],
                    "fp": group["fp"],
                    "fn_ratio": round(fn_ratio, 3),
                    "average_importance": round(avg_importance, 3),
                    "confidence_counts": dict(group["confidence_counts"]),
                    "race_count": len(set(group["race_ids"])),
                    "race_ids": sorted(set(group["race_ids"])),
                    "horses": sorted(set(group["horses"])),
                    "surfaces": self._counter_items(group["surfaces"]),
                    "distances": self._counter_items(group["distances"]),
                    "racecourses": self._counter_items(group["racecourses"]),
                    "track_conditions": self._counter_items(group["track_conditions"]),
                    "score": round(score, 3),
                    "evidence": group["evidence"][:5],
                }
            )
        ranking.sort(key=lambda item: (-item["score"], -item["occurrence"], item["category"], item["detail"]))
        for index, item in enumerate(ranking, start=1):
            item["rank"] = index
        return ranking

    def recommended_gap(self, ranking):
        for item in self._list(ranking):
            if (
                item.get("occurrence", 0) >= 2
                and item.get("fn", 0) >= item.get("fp", 0)
                and item.get("category") in {"SireMissing", "DamSireMissing", "DistanceMissing"}
            ):
                return item
        return self._list(ranking)[0] if ranking else {}

    def summary(self, gaps, ranking):
        categories = Counter(gap.get("category") for gap in self._list(gaps))
        bloodlines = Counter(gap.get("bloodline") for gap in self._list(gaps))
        distances = Counter(gap.get("distance") for gap in self._list(gaps))
        surfaces = Counter(gap.get("surface") for gap in self._list(gaps))
        racecourses = Counter(gap.get("racecourse") for gap in self._list(gaps))
        return {
            "category_counts": dict(categories.most_common()),
            "bloodline_counts": dict(bloodlines.most_common()),
            "distance_counts": dict(distances.most_common()),
            "surface_counts": dict(surfaces.most_common()),
            "racecourse_counts": dict(racecourses.most_common()),
            "top_gap": ranking[0] if ranking else {},
        }

    def write_report(self, result):
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        recommended = result.get("recommended_knowledge") if isinstance(result.get("recommended_knowledge"), dict) else {}
        lines = [
            "# Knowledge Gap Report",
            "",
            f"- Generated: {datetime.now(timezone.utc).isoformat()}",
            f"- Target records: {result.get('target_record_count')}",
            f"- Knowledge gaps: {result.get('knowledge_gap_count')}",
            "",
            "## Category Counts",
            "",
            "| Category | Count |",
            "|---|---:|",
        ]
        for key, count in (summary.get("category_counts") or {}).items():
            lines.append(f"| {key} | {count} |")
        lines.extend(["", "## Bloodline Counts", "", "| Bloodline | Count |", "|---|---:|"])
        for key, count in list((summary.get("bloodline_counts") or {}).items())[:20]:
            lines.append(f"| {key} | {count} |")
        lines.extend(["", "## Distance Counts", "", "| Distance | Count |", "|---|---:|"])
        for key, count in (summary.get("distance_counts") or {}).items():
            lines.append(f"| {key} | {count} |")
        lines.extend(["", "## Surface Counts", "", "| Surface | Count |", "|---|---:|"])
        for key, count in (summary.get("surface_counts") or {}).items():
            lines.append(f"| {key} | {count} |")
        lines.extend(["", "## Ranking", "", "| Rank | Category | Detail | Occurrence | FN | FP | Avg Importance | Score |", "|---:|---|---|---:|---:|---:|---:|---:|"])
        for item in self._list(result.get("ranking"))[:30]:
            lines.append(
                f"| {item.get('rank')} | {item.get('category')} | {item.get('detail')} | "
                f"{item.get('occurrence')} | {item.get('fn')} | {item.get('fp')} | "
                f"{item.get('average_importance')} | {item.get('score')} |"
            )
        lines.extend(
            [
                "",
                "## Recommended Knowledge",
                "",
                f"- Category: {recommended.get('category')}",
                f"- Detail: {recommended.get('detail')}",
                f"- Bloodline: {recommended.get('bloodline')}",
                f"- Occurrence: {recommended.get('occurrence')}",
                f"- FN: {recommended.get('fn')}",
                f"- FP: {recommended.get('fp')}",
                f"- Average Importance: {recommended.get('average_importance')}",
                "- Reason: highest repeated FN-oriented gap that can be added as limited bloodline knowledge.",
                "",
                "## Guardrails",
                "",
                "- This report does not add Knowledge.",
                "- This report does not change evaluators, scores, decisions, CSV, or Explain text.",
            ]
        )
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _is_target_record(self, record):
        return (
            record.get("root_primary_candidate") == "BloodlineEvaluator"
            and record.get("bloodline_primary_factor") == "KnowledgeMissing"
            and record.get("case_type") in {"FN", "FP"}
            and record.get("ranking_active") is not False
        )

    def _bloodline_pair(self, record):
        causes = self._list(record.get("bloodline_root_causes"))
        detail = ""
        if causes and isinstance(causes[0], dict):
            detail = str(causes[0].get("detail") or "")
        match = self.PROFILE_PATTERN.search(detail)
        if match:
            return self._clean(match.group("sire")), self._clean(match.group("dam"))
        return "unknown_sire", "unknown_dam_sire"

    def _gap(self, base, category, detail, bloodline, reason, context):
        item = dict(base)
        item.update(
            {
                "category": category,
                "detail": detail,
                "bloodline": bloodline,
                "reason": reason,
                "surface": context.get("surface"),
                "distance": context.get("distance"),
                "racecourse": context.get("racecourse"),
                "track_condition": context.get("track_condition"),
                "running_style": context.get("running_style"),
            }
        )
        return item

    def _importance(self, record):
        value = record.get("root_importance")
        try:
            return round(float(value), 3)
        except (TypeError, ValueError):
            return 0.82

    def _confidence(self, record):
        return record.get("root_confidence") or "MEDIUM"

    def _load_database(self):
        if not self.db_path.exists():
            return {"records": [], "warnings": [f"candidate database not found: {self.db_path}"]}
        try:
            return json.loads(self.db_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"records": [], "warnings": [f"candidate database unreadable: {exc}"]}

    def _counter_items(self, values):
        return [{"value": key, "count": value} for key, value in Counter(values).most_common()]

    def _append(self, values, value):
        if value not in (None, ""):
            values.append(value)

    def _clean(self, value):
        text = str(value or "").strip()
        return text if text else "unknown"

    def _list(self, value):
        return value if isinstance(value, list) else []


if __name__ == "__main__":
    output = KnowledgeGapExtractor().extract()
    print(
        {
            "status": output.get("status"),
            "target_record_count": output.get("target_record_count"),
            "knowledge_gap_count": output.get("knowledge_gap_count"),
            "report_path": str(KnowledgeGapExtractor.DEFAULT_REPORT_PATH),
        }
    )
