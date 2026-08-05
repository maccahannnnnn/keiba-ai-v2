"""Review-layer RISK_PRIMARY root cause analysis.

Reads existing Priority4/BUY shadow artifacts and classifies RISK_PRIMARY
cases. This script does not call Production adapters and does not change BUY,
Decision, Score, Learning, MeetingBias, Knowledge, or Shadow Project state.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RiskPrimaryRootCauseReview:
    """Classify RISK_PRIMARY cases using saved review artifacts only."""

    VERSION = "risk_primary_root_cause_review_v1"
    REQUIRED_CATEGORIES = [
        "Absolute",
        "Relative",
        "Consensus",
        "RaceDecision",
        "MeetingBias_Candidate",
        "TrackBias_Candidate",
        "CourseKnowledge_Candidate",
    ]

    def __init__(
        self,
        root: Path | str = Path("."),
        trace_path: Path | str = "reports/absolute_shadow_baseline_trace_v1.csv",
        output_dir: Path | str = "reports",
    ) -> None:
        self.root = Path(root)
        self.trace_path = self.root / Path(trace_path)
        self.output_dir = self.root / Path(output_dir)

    def run(self) -> dict[str, Any]:
        trace_rows = [row for row in self._read_csv(self.trace_path) if row.get("primary_cause") == "RISK_PRIMARY"]
        review_index = self._review_index()
        meeting_bias_races = self._meeting_bias_races()
        classified = [self._classify(row, review_index, meeting_bias_races) for row in trace_rows]
        summary = self._summary(classified)
        candidates = self._candidates(summary)

        self._write_csv(self.output_dir / "risk_primary_classification_v1.csv", classified)
        self._write_json(self.output_dir / "risk_primary_summary_v1.json", summary)
        self._write_json(self.output_dir / "risk_primary_candidate_v1.json", candidates)
        (self.output_dir / "risk_primary_root_cause_v1.md").write_text(
            self._report(summary, candidates),
            encoding="utf-8",
        )
        return summary

    def _classify(
        self,
        row: dict[str, Any],
        review_index: dict[tuple[str, str], dict[str, Any]],
        meeting_bias_races: set[str],
    ) -> dict[str, Any]:
        joined = review_index.get((row.get("race_id") or "", self._norm(row.get("horse_name"))), {})
        risk_text = "; ".join(
            value for value in [
                row.get("rc1_reason"),
                joined.get("risk_reasons"),
                joined.get("negative_evaluators"),
                joined.get("warnings"),
            ]
            if value
        )
        categories: list[str] = []
        reasons: list[str] = []

        if self._false(row.get("absolute_pass")):
            categories.append("Absolute")
            reasons.append(f"absolute_pass=False:{row.get('absolute_failure_category')}")
        if self._false(row.get("relative_pass")):
            categories.append("Relative")
            reasons.append("relative_pass=False")
        if self._false(row.get("consensus_pass")):
            categories.append("Consensus")
            reasons.append(f"consensus_pass=False:{row.get('consensus_fail_reason')}")
        if row.get("race_decision") in {"SKIP", "PASS", "CAUTION"}:
            categories.append("RaceDecision")
            reasons.append(f"race_decision={row.get('race_decision')}")
        if (row.get("race_id") in meeting_bias_races) and self._contains(risk_text, ["当日バイアス", "bias", "バイアス"]):
            categories.append("MeetingBias_Candidate")
            reasons.append("meeting_bias_evidence_available_with_bias_risk_text")
        if self._contains(risk_text, ["当日バイアス", "trackbias", "track_bias", "馬場バイアス"]):
            categories.append("TrackBias_Candidate")
            reasons.append("bias_or_trackbias_risk_text_present")
        if self._contains(risk_text, ["CourseShape", "コース形状", "小回り", "course"]):
            categories.append("CourseKnowledge_Candidate")
            reasons.append("course_shape_or_course_risk_text_present")

        categories = self._dedupe(categories)
        return {
            "race_id": row.get("race_id"),
            "horse_name": row.get("horse_name"),
            "finish_position": row.get("finish_position"),
            "actual_top3": row.get("actual_top3"),
            "ai_rank": row.get("ai_rank"),
            "legacy_decision": row.get("legacy_decision"),
            "rc1_decision": row.get("rc1_decision"),
            "race_decision": row.get("race_decision"),
            "decision_score": row.get("decision_score"),
            "final_score": row.get("final_score"),
            "adjusted_score": row.get("adjusted_score"),
            "absolute_pass": row.get("absolute_pass"),
            "relative_pass": row.get("relative_pass"),
            "consensus_pass": row.get("consensus_pass"),
            "risk_pass": row.get("risk_pass"),
            "race_shape_status": row.get("race_shape_status"),
            "consensus_fail_reason": row.get("consensus_fail_reason"),
            "absolute_failure_category": row.get("absolute_failure_category"),
            "secondary_causes": row.get("secondary_causes"),
            "risk_reasons_joined": risk_text,
            "classification": ";".join(categories),
            "representative_group": self._representative_group(categories),
            "classification_reason": "; ".join(reasons),
            "reproducibility": self._reproducibility(categories),
            "explainability": self._explainability(categories, risk_text),
            "improvement_feasibility": self._feasibility(categories),
            "roi": self._roi_label(categories),
            "review_candidate_only": True,
        }

    def _summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(rows)
        category_counts = Counter()
        group_counts = Counter(row.get("representative_group") for row in rows)
        examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            for category in str(row.get("classification") or "").split(";"):
                if category:
                    category_counts[category] += 1
                    if len(examples[category]) < 3:
                        examples[category].append(
                            {
                                "race_id": row.get("race_id"),
                                "horse_name": row.get("horse_name"),
                                "finish_position": row.get("finish_position"),
                                "reason": row.get("classification_reason"),
                            }
                        )
        category_summary = []
        for category in self.REQUIRED_CATEGORIES:
            count = category_counts.get(category, 0)
            category_summary.append(
                {
                    "category": category,
                    "count": count,
                    "ratio": round(count / total, 4) if total else 0,
                    "representative_examples": examples.get(category, []),
                    "reproducibility": self._category_reproducibility(category, count, total),
                    "explainability": self._category_explainability(category),
                    "improvement_feasibility": self._category_feasibility(category),
                    "roi": self._category_roi(category, count, total),
                }
            )
        return {
            "status": "REVIEW_COMPLETE",
            "version": self.VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "target": "RISK_PRIMARY",
            "risk_primary_count": total,
            "category_summary": category_summary,
            "representative_group_counts": dict(group_counts),
            "race_count": len({row.get("race_id") for row in rows}),
            "production_changed": False,
            "buy_changed": False,
            "decision_changed": False,
            "score_changed": False,
            "learning_changed": False,
            "meeting_bias_changed": False,
            "shadow_implemented": False,
            "target_trial_adapter_run_executed": False,
            "main_py_executed": False,
        }

    def _candidates(self, summary: dict[str, Any]) -> dict[str, Any]:
        ranked = sorted(
            summary.get("category_summary", []),
            key=lambda item: (
                item.get("count", 0),
                {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(item.get("improvement_feasibility"), 0),
            ),
            reverse=True,
        )
        candidates = []
        for index, item in enumerate(ranked[:5], start=1):
            candidates.append(
                {
                    "rank": index,
                    "candidate_name": f"RISK_PRIMARY {item.get('category')} review candidate",
                    "category": item.get("category"),
                    "occurrence": item.get("count"),
                    "ratio": item.get("ratio"),
                    "review_action": self._review_action(item),
                    "expected_benefit": item.get("roi"),
                    "implementation_scope": "REVIEW_CANDIDATE_ONLY",
                    "shadow_required_before_production": True,
                    "production_change_allowed_now": False,
                }
            )
        return {
            "status": "REVIEW_COMPLETE",
            "version": self.VERSION,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "recommended_next_review": candidates[0] if candidates else None,
            "production_change_allowed": False,
        }

    def _report(self, summary: dict[str, Any], candidates: dict[str, Any]) -> str:
        lines = [
            "# RISK_PRIMARY Root Cause Review v1",
            "",
            "## Scope",
            "",
            "- Review Layer only.",
            "- Target: `primary_cause == RISK_PRIMARY` from `absolute_shadow_baseline_trace_v1.csv`.",
            "- Production / BUY / Decision / Score / Learning / MeetingBias / Shadow were not changed.",
            "",
            "## Summary",
            "",
            f"- RISK_PRIMARY count: {summary.get('risk_primary_count')}",
            f"- Race count: {summary.get('race_count')}",
            "",
            "## Category Counts",
            "",
            "| Category | Count | Ratio | Reproducibility | Explainability | Feasibility | ROI |",
            "|---|---:|---:|---|---|---|---|",
        ]
        for item in summary.get("category_summary", []):
            lines.append(
                f"| {item.get('category')} | {item.get('count')} | {item.get('ratio')} | "
                f"{item.get('reproducibility')} | {item.get('explainability')} | "
                f"{item.get('improvement_feasibility')} | {item.get('roi')} |"
            )
        lines.extend(["", "## Representative Examples", ""])
        for item in summary.get("category_summary", []):
            lines.append(f"### {item.get('category')}")
            examples = item.get("representative_examples") or []
            if not examples:
                lines.append("- None")
            for example in examples:
                lines.append(
                    f"- {example.get('race_id')} {example.get('horse_name')} finish={example.get('finish_position')} "
                    f"reason={example.get('reason')}"
                )
            lines.append("")
        lines.extend(
            [
                "## Review Candidates",
                "",
                "| Rank | Candidate | Occurrence | Action | Expected benefit |",
                "|---:|---|---:|---|---|",
            ]
        )
        for item in candidates.get("candidates", []):
            lines.append(
                f"| {item.get('rank')} | {item.get('candidate_name')} | {item.get('occurrence')} | "
                f"{item.get('review_action')} | {item.get('expected_benefit')} |"
            )
        lines.extend(
            [
                "",
                "## Priority4 Remaining Tasks",
                "",
                "1. Register RISK_PRIMARY review candidates as WATCH or REVIEW_REQUIRED in Human Review.",
                "2. Split RaceDecision SKIP cases from Absolute/Consensus compound cases in a follow-up review.",
                "3. Check whether TrackBias/MeetingBias information-limitation risks are double-counted in Decision/Risk.",
                "4. Keep CourseKnowledge candidates on hold until additional evidence accumulates.",
                "5. Limit Production implementation judgment until after a separate Shadow design.",
                "",
                "## Safety",
                "",
                "- TargetTrialAdapter.run executed: false",
                "- main.py executed: false",
                "- Production changed: false",
                "- BUY changed: false",
                "- Decision changed: false",
                "- Score changed: false",
                "- Learning changed: false",
                "- MeetingBias changed: false",
                "- Shadow implemented: false",
                "",
                "## Final Judgment",
                "",
                "**REVIEW_COMPLETE**",
            ]
        )
        return "\n".join(lines) + "\n"

    def _review_index(self) -> dict[tuple[str, str], dict[str, Any]]:
        index: dict[tuple[str, str], dict[str, Any]] = {}
        for path in sorted((self.root / "reports").glob("review_*/horse_review*.csv")):
            for row in self._read_csv(path):
                race_id = row.get("race_id") or ""
                horse_name = self._norm(row.get("horse_name"))
                if race_id and horse_name:
                    index[(race_id, horse_name)] = row
        return index

    def _meeting_bias_races(self) -> set[str]:
        path = self.root / "reports" / "meeting_bias" / "meeting_bias_read_only_evidence_v2.json"
        if not path.exists():
            return set()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {row.get("race_id") for row in payload.get("evidence", []) if row.get("race_id")}

    def _representative_group(self, categories: list[str]) -> str:
        for category in ["RaceDecision", "Absolute", "Consensus", "Relative", "TrackBias_Candidate", "MeetingBias_Candidate", "CourseKnowledge_Candidate"]:
            if category in categories:
                return category
        return "OTHER"

    def _reproducibility(self, categories: list[str]) -> str:
        if "RaceDecision" in categories and "Absolute" in categories and "Consensus" in categories:
            return "HIGH"
        if len(categories) >= 2:
            return "MEDIUM"
        return "LOW"

    def _explainability(self, categories: list[str], risk_text: str) -> str:
        if risk_text and categories:
            return "HIGH"
        if categories:
            return "MEDIUM"
        return "LOW"

    def _feasibility(self, categories: list[str]) -> str:
        if "RaceDecision" in categories or "Absolute" in categories:
            return "MEDIUM"
        if "TrackBias_Candidate" in categories or "MeetingBias_Candidate" in categories:
            return "LOW"
        return "LOW"

    def _roi_label(self, categories: list[str]) -> str:
        if "RaceDecision" in categories and "Absolute" in categories and "Consensus" in categories:
            return "MEDIUM"
        if "TrackBias_Candidate" in categories or "MeetingBias_Candidate" in categories:
            return "LOW"
        return "LOW"

    def _category_reproducibility(self, category: str, count: int, total: int) -> str:
        ratio = count / total if total else 0
        if ratio >= 0.6:
            return "HIGH"
        if ratio >= 0.25:
            return "MEDIUM"
        return "LOW"

    def _category_explainability(self, category: str) -> str:
        return "HIGH" if category in {"Absolute", "Relative", "Consensus", "RaceDecision"} else "MEDIUM"

    def _category_feasibility(self, category: str) -> str:
        return "MEDIUM" if category in {"Absolute", "Consensus", "RaceDecision"} else "LOW"

    def _category_roi(self, category: str, count: int, total: int) -> str:
        if total and count / total >= 0.5 and category in {"Absolute", "Consensus", "RaceDecision"}:
            return "MEDIUM"
        return "LOW"

    def _review_action(self, item: dict[str, Any]) -> str:
        category = item.get("category")
        if category in {"RaceDecision", "Absolute", "Consensus"}:
            return "Split compound risk gate and verify with separate Shadow design."
        if category in {"MeetingBias_Candidate", "TrackBias_Candidate"}:
            return "Continue diagnostic evidence collection; do not feed Production risk yet."
        return "Keep as watch candidate until more evidence exists."

    def _contains(self, text: str, needles: list[str]) -> bool:
        lower = str(text or "").lower()
        return any(needle.lower() in lower for needle in needles)

    def _dedupe(self, values: list[str]) -> list[str]:
        result = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    def _false(self, value: Any) -> bool:
        return str(value).strip().lower() == "false"

    def _norm(self, value: Any) -> str:
        return "".join(str(value or "").split())

    def _read_csv(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        for encoding in ("utf-8-sig", "cp932"):
            try:
                with path.open("r", encoding=encoding, newline="") as handle:
                    return [dict(row) for row in csv.DictReader(handle)]
            except UnicodeDecodeError:
                continue
        return []

    def _write_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8-sig")
            return
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def _write_json(self, path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    result = RiskPrimaryRootCauseReview().run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
