"""Shadow Validation Manager v1.0.

Registers human-approved shadow validation projects from the priority queue.
It manages project plans only; it does not implement shadow logic or change any
production scoring/decision behavior.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from learning.shadow_validation_project import ShadowValidationProject
from learning.shadow_validation_repository import ShadowValidationRepository


APPROVED_CANDIDATE_ID = "BUY_FALSE_POSITIVE_RC1"
APPROVED_PROJECT_ID = "SHADOW_BUY_FALSE_POSITIVE_RC1_V1"


class ShadowValidationManager:
    """Create and classify shadow validation project records."""

    def __init__(self, root_dir=None, output_dir=None):
        self.root = Path(root_dir) if root_dir else Path(__file__).resolve().parents[1]
        self.output_dir = Path(output_dir) if output_dir else self.root / "reports" / "shadow_validation"
        self.repository = ShadowValidationRepository(self.output_dir)
        self.warnings: list[str] = []

    def run(self) -> dict[str, object]:
        candidate_map = self._load_candidates()
        queue_rows = self._read_csv(self.root / "reports" / "improvement_priority" / "shadow_queue.csv")
        baseline = self._load_json(self.root / "reports" / "buy_v1_rc1_validation" / "summary.json")

        projects = []
        for queue_row in queue_rows:
            candidate_id = queue_row.get("candidate_id", "")
            candidate = candidate_map.get(candidate_id, {})
            projects.append(self._build_project(queue_row, candidate, baseline))

        persisted = [self.repository.upsert(project) for project in projects]
        all_projects = self.repository.list_all()
        self._write_reports(all_projects, baseline)
        summary = self._summary(all_projects, queue_rows)
        self._write_json(self.output_dir / "summary.json", summary)
        return summary

    def _build_project(self, queue_row, candidate, baseline):
        candidate_id = queue_row.get("candidate_id", "")
        approved = candidate_id == APPROVED_CANDIDATE_ID
        project_id = APPROVED_PROJECT_ID if approved else f"SHADOW_{candidate_id}_V1"
        now = datetime.now().isoformat(timespec="seconds")
        project_status = "READY_FOR_IMPLEMENTATION" if approved else "DRAFT"
        approval_status = "APPROVED" if approved else "PENDING"
        approved_by = "HUMAN" if approved else ""
        approved_at = now if approved else ""
        objective = (
            "Validate whether RC1 BUY false positives can be reduced without removing successful BUY horses."
            if approved
            else "Pending shadow validation project. Await human approval before implementation planning."
        )
        hypothesis = (
            "RC1 FP 13 horses may contain explainable common factors that differ from successful BUY 6 horses."
            if approved
            else "No approved hypothesis yet."
        )
        return ShadowValidationProject(
            project_id=project_id,
            candidate_id=candidate_id,
            candidate_name=queue_row.get("candidate_name") or candidate.get("candidate_name", ""),
            candidate_category=candidate.get("candidate_category", ""),
            target_component=candidate.get("target_component", ""),
            priority=queue_row.get("priority", ""),
            project_status=project_status,
            approval_status=approval_status,
            approved_by=approved_by,
            approved_at=approved_at,
            feature_flag_name=f"{project_id}_ENABLED" if approved else "",
            objective=objective,
            hypothesis=hypothesis,
            baseline_definition=self._baseline_definition(baseline),
            comparison_definition=(
                "Compare future shadow result against BUY v1.0 RC1 baseline; no production result changes."
            ),
            implementation_scope=(
                "Create one minimal shadow rule proposal from existing input fields only; do not implement in this phase."
                if approved
                else "Pending. No implementation scope is authorized."
            ),
            prohibited_changes=self._prohibited_changes(),
            validation_dataset={
                "baseline_races": 40,
                "baseline_horses": 540,
                "unseen_dataset_required_before_accept": True,
            },
            unseen_dataset_requirement=[
                "Use race days not included in the 40-race development set.",
                "Validate across multiple racecourses and classes where possible.",
                "Do not advance to ACCEPTED without unseen-data validation.",
            ],
            required_metrics=self._required_metrics(),
            acceptance_criteria=self._acceptance_criteria(),
            hold_criteria=self._hold_criteria(),
            revert_criteria=self._revert_criteria(),
            production_impact_expected="none_until_shadow_is_implemented_and_approved",
            source_files=[
                "reports/improvement_candidates/improvement_candidates.json",
                "reports/improvement_priority/shadow_queue.csv",
                "reports/buy_v1_rc1_validation/summary.json",
            ],
            notes=[
                "This project record manages validation planning only.",
                "No BUY, score, threshold, evaluator, or Decision logic has been changed.",
            ],
        )

    def _baseline_definition(self, baseline):
        rc1 = baseline.get("rc1", {}) if isinstance(baseline, dict) else {}
        states = baseline.get("race_states", {}) if isinstance(baseline, dict) else {}
        return {
            "race_count": baseline.get("race_count", 40),
            "horse_count": baseline.get("horse_count", 540),
            "BUY": rc1.get("BUY", 19),
            "BUY_top3": rc1.get("BUY_top3", 6),
            "BUY_place_rate": rc1.get("BUY_top3_rate", 0.3157894736842105),
            "FN": rc1.get("FN", 114),
            "FP": rc1.get("FP", 13),
            "PLAY_CONVERGED": states.get("PLAY_CONVERGED", 11),
            "SKIP": states.get("SKIP", 24),
            "PLAY_UNCONVERGED_4PLUS": states.get("PLAY_UNCONVERGED_4PLUS", 5),
            "BUY0_races": baseline.get("buy_zero_races", 29),
        }

    def _summary(self, projects, queue_rows):
        status_counts = Counter(project.project_status for project in projects)
        approval_counts = Counter(project.approval_status for project in projects)
        ids = [project.project_id for project in projects]
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "queue_count": len(queue_rows),
            "project_count": len(projects),
            "approved_projects": [
                project.project_id for project in projects if project.approval_status == "APPROVED"
            ],
            "pending_projects": [
                project.project_id for project in projects if project.approval_status == "PENDING"
            ],
            "status_counts": dict(status_counts),
            "approval_counts": dict(approval_counts),
            "repository_count": len(projects),
            "duplicate_project_ids": self._duplicates(ids),
            "next_shadow_project": APPROVED_PROJECT_ID,
            "warnings": self.warnings,
            "buy_diff": 0,
            "score_diff": 0,
            "decision_diff": 0,
        }

    def _write_reports(self, projects, baseline):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        rows = [project.to_dict() for project in projects]
        self._write_json(self.output_dir / "shadow_projects.json", {"projects": rows})
        self._write_csv(
            self.output_dir / "shadow_projects.csv",
            rows,
            [
                "project_id",
                "candidate_id",
                "candidate_name",
                "priority",
                "project_status",
                "approval_status",
                "approved_by",
                "approved_at",
                "shadow_version",
                "feature_flag_name",
                "final_decision",
            ],
        )
        approved = [row for row in rows if row.get("approval_status") == "APPROVED"]
        pending = [row for row in rows if row.get("approval_status") == "PENDING"]
        self._write_csv(self.output_dir / "approved_queue.csv", approved, ["project_id", "candidate_id", "candidate_name", "priority", "project_status", "approval_status"])
        self._write_csv(self.output_dir / "pending_queue.csv", pending, ["project_id", "candidate_id", "candidate_name", "priority", "project_status", "approval_status"])
        self._write_summary_md(projects)
        next_project = next((project for project in projects if project.project_id == APPROVED_PROJECT_ID), None)
        if next_project:
            self._write_next_project(next_project)

    def _write_summary_md(self, projects):
        approved = [project for project in projects if project.approval_status == "APPROVED"]
        pending = [project for project in projects if project.approval_status == "PENDING"]
        lines = [
            "# Shadow Validation Summary",
            "",
            f"- Shadow案件数: {len(projects)}",
            f"- 承認済み案件: {len(approved)}",
            f"- Pending案件: {len(pending)}",
            "- BUY差分: 0",
            "- Score差分: 0",
            "- Decision差分: 0",
            "",
            "## 承認済み案件",
        ]
        for project in approved:
            lines.append(f"- {project.project_id}: {project.candidate_id} / {project.project_status}")
        lines.extend(["", "## Pending案件"])
        for project in pending:
            lines.append(f"- {project.project_id}: {project.candidate_id} / {project.project_status}")
        lines.extend(["", "## 注意"])
        lines.append("- Shadow改善ロジックは未実装。今回は案件管理のみ。")
        (self.output_dir / "shadow_validation_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_next_project(self, project):
        baseline = project.baseline_definition
        lines = [
            "# Next Shadow Project",
            "",
            f"- project_id: {project.project_id}",
            f"- candidate_id: {project.candidate_id}",
            f"- candidate_name: {project.candidate_name}",
            f"- Priority: {project.priority}",
            "- 選択理由: 人間指示によりBUY_FALSE_POSITIVE_RC1のみ承認済み",
            "",
            "## 目的",
            project.objective,
            "",
            "## 仮説",
            project.hypothesis,
            "",
            "## Baseline",
            f"- races: {baseline.get('race_count')}",
            f"- horses: {baseline.get('horse_count')}",
            f"- BUY: {baseline.get('BUY')}",
            f"- BUY Top3: {baseline.get('BUY_top3')}",
            f"- BUY place rate: {baseline.get('BUY_place_rate')}",
            f"- FN: {baseline.get('FN')}",
            f"- FP: {baseline.get('FP')}",
            f"- PLAY_CONVERGED: {baseline.get('PLAY_CONVERGED')}",
            f"- SKIP: {baseline.get('SKIP')}",
            f"- PLAY_UNCONVERGED_4PLUS: {baseline.get('PLAY_UNCONVERGED_4PLUS')}",
            "",
            "## 実装可能範囲",
            project.implementation_scope,
            "",
            "## 禁止事項",
        ]
        lines.extend(f"- {item}" for item in project.prohibited_changes)
        lines.extend(["", "## 必要な指標"])
        lines.extend(f"- {item}" for item in project.required_metrics)
        lines.extend(["", "## ACCEPT条件"])
        lines.extend(f"- {item}" for item in project.acceptance_criteria)
        lines.extend(["", "## HOLD条件"])
        lines.extend(f"- {item}" for item in project.hold_criteria)
        lines.extend(["", "## REVERT条件"])
        lines.extend(f"- {item}" for item in project.revert_criteria)
        lines.extend(["", "## 未使用データ要件"])
        lines.extend(f"- {item}" for item in project.unseen_dataset_requirement)
        lines.extend(["", "## 次の実装ステップ"])
        lines.append("- FP 13頭と成功BUY 6頭の差分を既存入力項目だけで構造化し、最小限のShadow改善案を1つ作る。")
        lines.append("- 今回は差分分析や改善案実装は行わない。")
        (self.output_dir / "next_shadow_project.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _load_candidates(self):
        path = self.root / "reports" / "improvement_candidates" / "improvement_candidates.json"
        if not path.exists():
            self.warnings.append(f"missing candidates: {path}")
            return {}
        data = self._load_json(path)
        return {
            row.get("candidate_id"): row
            for row in data.get("candidates", [])
            if isinstance(row, dict) and row.get("candidate_id")
        }

    def _load_json(self, path):
        if not path.exists():
            self.warnings.append(f"missing json: {path}")
            return {}
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)

    def _read_csv(self, path):
        if not path.exists():
            self.warnings.append(f"missing csv: {path}")
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def _write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

    def _write_csv(self, path, rows, fields):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def _duplicates(self, values):
        counts = Counter(values)
        return [value for value, count in counts.items() if count > 1]

    def _required_metrics(self):
        return [
            "Shadow BUY count",
            "Shadow BUY Top3 count",
            "Shadow BUY place rate",
            "Shadow FN",
            "Shadow FP",
            "Removed FP",
            "Removed Successful BUY",
            "New BUY",
            "New BUY Top3",
            "New FP",
            "RaceState diff",
            "Production BUY diff",
            "Score diff",
            "Decision diff",
            "Explain missing",
            "Racecourse distribution",
            "Distance distribution",
            "Class distribution",
        ]

    def _acceptance_criteria(self):
        return [
            "Feature Flag OFF has zero production diff.",
            "Score diff is zero outside shadow output.",
            "Decision diff is zero outside shadow output.",
            "FP decreases from baseline.",
            "Removed successful BUY count does not exceed removed FP count.",
            "BUY place rate does not materially decline from baseline.",
            "Effect is not limited to one racecourse, distance, or class only.",
            "Improvement reason is explainable at evaluator level.",
            "No narrow optimized threshold is introduced.",
            "Unseen dataset validation is completed before ACCEPTED.",
        ]

    def _hold_criteria(self):
        return [
            "FP decreases but successful BUY is lost at similar scale.",
            "Effect does not reproduce on unseen data.",
            "Condition dependence is too narrow.",
            "FN increase trades off against FP reduction.",
            "Explainable reason exists but data count is insufficient.",
        ]

    def _revert_criteria(self):
        return [
            "Feature Flag OFF creates production diff.",
            "Unexpected score or decision diff appears.",
            "FP increases.",
            "Successful BUY loss exceeds removed FP.",
            "Explain becomes inconsistent.",
            "40-race-only overfit rule is introduced.",
            "BUY RC1 compatibility breaks.",
            "Logic changes occur outside project management.",
        ]

    def _prohibited_changes(self):
        return [
            "Analyzer",
            "Knowledge",
            "Evaluator",
            "FinalScore",
            "DecisionEngine",
            "RaceDecisionEngine",
            "ConfidenceEngine",
            "ExplainEngine",
            "BUY v1.0 RC1",
            "BUY Monitoring",
            "Consensus",
            "Risk",
            "Threshold",
            "Learning Phase1/2/3",
            "Improvement Candidate Engine",
            "Improvement Priority Manager",
            "CSV schema",
            "Importer",
            "ResultImporter",
            "main.py",
        ]
