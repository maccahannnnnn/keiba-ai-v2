"""Repository for Shadow Validation projects."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from learning.shadow_validation_project import ShadowValidationProject


class ShadowValidationRepository:
    """Persist shadow projects and append meaningful lifecycle history."""

    def __init__(self, output_dir=None):
        root = Path(__file__).resolve().parents[1]
        self.output_dir = Path(output_dir) if output_dir else root / "reports" / "shadow_validation"
        self.json_path = self.output_dir / "shadow_projects.json"
        self.history_path = self.output_dir / "shadow_project_history.jsonl"

    def load(self) -> dict[str, ShadowValidationProject]:
        if not self.json_path.exists():
            return {}
        with self.json_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        rows = data.get("projects", [])
        return {
            row.get("project_id"): ShadowValidationProject.from_dict(row)
            for row in rows
            if isinstance(row, dict) and row.get("project_id")
        }

    def save(self, projects: dict[str, ShadowValidationProject]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        rows = [project.to_dict() for project in projects.values()]
        rows.sort(key=lambda row: (row.get("project_status", ""), row.get("project_id", "")))
        with self.json_path.open("w", encoding="utf-8") as handle:
            json.dump({"projects": rows}, handle, ensure_ascii=False, indent=2)

    def upsert(self, project: ShadowValidationProject) -> ShadowValidationProject:
        projects = self.load()
        existing = projects.get(project.project_id)
        action = "create"
        old_status = ""
        if existing:
            action = "update"
            old_status = existing.project_status
            project.created_at = existing.created_at
            project.validation_run_count = existing.validation_run_count
            project.result_summary = existing.result_summary or project.result_summary
            project.final_decision = existing.final_decision or project.final_decision
            project.decision_reason = existing.decision_reason or project.decision_reason
        project.updated_at = datetime.now().isoformat(timespec="seconds")
        projects[project.project_id] = project
        self.save(projects)
        if not existing or old_status != project.project_status or existing.approval_status != project.approval_status:
            self.append_history(
                project,
                action=action,
                old_status=old_status,
                new_status=project.project_status,
                reason="shadow_project_upsert",
                source="ShadowValidationManager",
            )
        return project

    def get_by_project_id(self, project_id: str):
        return self.load().get(project_id)

    def get_by_candidate_id(self, candidate_id: str):
        return [project for project in self.load().values() if project.candidate_id == candidate_id]

    def list_all(self) -> list[ShadowValidationProject]:
        return list(self.load().values())

    def list_by_status(self, status: str) -> list[ShadowValidationProject]:
        return [project for project in self.list_all() if project.project_status == status]

    def list_ready_for_implementation(self) -> list[ShadowValidationProject]:
        return self.list_by_status("READY_FOR_IMPLEMENTATION")

    def update_project_status(self, project_id: str, status: str, reason: str = ""):
        projects = self.load()
        project = projects.get(project_id)
        if not project:
            return None
        old = project.project_status
        project.project_status = status
        project.updated_at = datetime.now().isoformat(timespec="seconds")
        projects[project_id] = project
        self.save(projects)
        self.append_history(project, "status_update", old, status, reason, "repository")
        return project

    def update_approval_status(self, project_id: str, approval_status: str, reason: str = ""):
        projects = self.load()
        project = projects.get(project_id)
        if not project:
            return None
        old = project.approval_status
        project.approval_status = approval_status
        project.updated_at = datetime.now().isoformat(timespec="seconds")
        projects[project_id] = project
        self.save(projects)
        self.append_history(project, "approval_update", old, project.project_status, reason, "repository")
        return project

    def record_validation_run(self, project_id: str, result_summary=None):
        projects = self.load()
        project = projects.get(project_id)
        if not project:
            return None
        project.validation_run_count += 1
        project.result_summary = result_summary or {}
        project.updated_at = datetime.now().isoformat(timespec="seconds")
        projects[project_id] = project
        self.save(projects)
        self.append_history(project, "validation_run", project.project_status, project.project_status, "", "repository")
        return project

    def record_final_decision(self, project_id: str, final_decision: str, reason: str = ""):
        projects = self.load()
        project = projects.get(project_id)
        if not project:
            return None
        old = project.final_decision
        project.final_decision = final_decision
        project.decision_reason = reason
        project.updated_at = datetime.now().isoformat(timespec="seconds")
        projects[project_id] = project
        self.save(projects)
        self.append_history(project, "final_decision", old, project.project_status, reason, "repository")
        return project

    def append_history(
        self,
        project: ShadowValidationProject,
        action: str,
        old_status: str = "",
        new_status: str = "",
        reason: str = "",
        source: str = "",
    ) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "project_id": project.project_id,
            "candidate_id": project.candidate_id,
            "action": action,
            "old_status": old_status,
            "new_status": new_status,
            "approval_status": project.approval_status,
            "reason": reason,
            "source": source,
        }
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
