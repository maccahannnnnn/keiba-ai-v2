"""Human Review Comment / Status quality validator.

This validator is read-only. It inspects Human Review and Shadow Validation
status artifacts and writes operation-quality reports without changing
candidate databases, statuses, comments, production logic, or shadow logic.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    from review.human_review_template_generator import HumanReviewTemplateGenerator
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from human_review_template_generator import HumanReviewTemplateGenerator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HUMAN_REVIEW_DB = ROOT / "learning" / "candidate_review_status.json"
DEFAULT_SHADOW_PROJECTS = ROOT / "reports" / "shadow_validation" / "shadow_projects.json"
DEFAULT_REPORT_MD = ROOT / "reports" / "human_review_quality_validation.md"
DEFAULT_REPORT_JSON = ROOT / "reports" / "human_review_quality_validation.json"
DEFAULT_REPORT_CSV = ROOT / "reports" / "human_review_quality_validation_candidates.csv"

VALID_STATUSES = {
    "REVIEW_REQUIRED",
    "APPROVED",
    "WATCH",
    "REJECTED",
    "IMPLEMENTED",
    "REVERTED",
}

VALID_STATUS_SOURCES = {"RANKING", "HUMAN"}
REVIEW_DETAIL_FIELDS = [
    "expected_effect",
    "side_effect",
    "additional_data_needed",
    "shadow_test_target",
    "recheck_condition",
]

COMMENT_RECOMMENDED_STATUSES = {
    "APPROVED",
    "WATCH",
    "REJECTED",
    "IMPLEMENTED",
    "REVERTED",
}

HISTORY_REQUIRED_STATUSES = {"IMPLEMENTED", "REVERTED"}
SHADOW_TERMINAL_STATUSES = {
    "READY_FOR_IMPLEMENTATION",
    "VALIDATION_COMPLETE",
    "IMPLEMENTED",
    "REVERTED",
}

SEVERITY_ORDER = {"ERROR": 0, "WARNING": 1, "UNDETERMINED": 2, "INFO": 3, "OK": 4}


class HumanReviewQualityValidator:
    """Validate Human Review operation quality without mutating source data."""

    def __init__(
        self,
        human_review_db: Path | str = DEFAULT_HUMAN_REVIEW_DB,
        shadow_projects_path: Path | str = DEFAULT_SHADOW_PROJECTS,
        report_md: Path | str = DEFAULT_REPORT_MD,
        report_json: Path | str = DEFAULT_REPORT_JSON,
        report_csv: Path | str = DEFAULT_REPORT_CSV,
    ) -> None:
        self.human_review_db = Path(human_review_db)
        self.shadow_projects_path = Path(shadow_projects_path)
        self.report_md = Path(report_md)
        self.report_json = Path(report_json)
        self.report_csv = Path(report_csv)

    def validate(self, write_reports: bool = True) -> dict[str, object]:
        records, human_load_error = self._load_records(self.human_review_db, "records")
        projects, shadow_load_error = self._load_records(self.shadow_projects_path, "projects")
        issues: list[dict[str, object]] = []
        candidate_rows: list[dict[str, object]] = []

        if human_load_error:
            issues.append(self._issue("ERROR", "", "HUMAN_REVIEW_DB_UNREADABLE", human_load_error))
        if shadow_load_error:
            issues.append(self._issue("WARNING", "", "SHADOW_PROJECTS_UNREADABLE", shadow_load_error))

        shadow_index = self._shadow_index(projects)
        for record in records:
            row_issues = self._validate_record(record, shadow_index)
            issues.extend(row_issues)
            candidate_rows.append(self._candidate_row(record, row_issues, shadow_index))

        shadow_rows = self._validate_shadow_projects(projects)
        issues.extend(shadow_rows)

        self_tests = self._self_tests()
        summary = self._summary(records, projects, candidate_rows, issues, self_tests)
        result = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "input_files": {
                "human_review_db": str(self.human_review_db),
                "shadow_projects": str(self.shadow_projects_path),
            },
            "summary": summary,
            "severity_rules": self._severity_rules(),
            "candidate_rows": candidate_rows,
            "issues": sorted(issues, key=self._issue_sort_key),
            "self_tests": self_tests,
            "guardrails": {
                "read_only": True,
                "status_updates": False,
                "comment_autofill": False,
                "candidate_migration": False,
                "production_logic_changes": False,
                "json_db_mutation": False,
            },
        }

        if write_reports:
            self._write_reports(result)
        return result

    def _validate_record(self, record: dict[str, object], shadow_index: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
        issues: list[dict[str, object]] = []
        candidate_id = str(record.get("candidate_id") or "")
        status = record.get("status")

        for key in ["candidate_id", "status", "implementation_history"]:
            if key not in record:
                issues.append(self._issue("ERROR", candidate_id, "MISSING_REQUIRED_KEY", f"Missing key: {key}"))

        if not candidate_id:
            issues.append(self._issue("ERROR", candidate_id, "EMPTY_CANDIDATE_ID", "candidate_id is empty."))

        if status in (None, ""):
            issues.append(self._issue("ERROR", candidate_id, "MISSING_STATUS", "status is missing or empty."))
            normalized_status = ""
        else:
            normalized_status = str(status).strip().upper()
            if normalized_status != str(status).strip():
                issues.append(
                    self._issue(
                        "ERROR",
                        candidate_id,
                        "NON_NORMALIZED_STATUS",
                        f"status should be uppercase canonical form: {status}",
                    )
                )
            if normalized_status not in VALID_STATUSES:
                issues.append(self._issue("ERROR", candidate_id, "INVALID_STATUS", f"Invalid status: {status}"))

        comment_state = self._comment_state(record)
        status_source = self._status_source(record)
        if status_source == "LEGACY_UNKNOWN":
            issues.append(
                self._issue(
                    "INFO",
                    candidate_id,
                    "STATUS_SOURCE_LEGACY_UNKNOWN",
                    "status_source is missing on an existing record; shown as LEGACY_UNKNOWN without inferring HUMAN.",
                )
            )
        elif status_source not in VALID_STATUS_SOURCES:
            issues.append(self._issue("ERROR", candidate_id, "INVALID_STATUS_SOURCE", f"Invalid status_source: {status_source}"))
        if normalized_status == "WATCH" and status_source == "HUMAN":
            issues.append(
                self._issue(
                    "INFO",
                    candidate_id,
                    "HUMAN_WATCH_SYNC_PROTECTED",
                    "HUMAN WATCH is expected to be preserved by sync_from_ranking.",
                )
            )
        if normalized_status == "WATCH" and status_source == "RANKING":
            issues.append(
                self._issue(
                    "INFO",
                    candidate_id,
                    "RANKING_WATCH_SYNC_MUTABLE",
                    "RANKING WATCH can follow future ranking priority changes.",
                )
            )
        issues.extend(self._validate_review_details(record, candidate_id))
        if "review_comment" not in record:
            issues.append(self._issue("ERROR", candidate_id, "MISSING_REVIEW_COMMENT_KEY", "review_comment key is missing."))
        elif normalized_status in COMMENT_RECOMMENDED_STATUSES and comment_state != "PRESENT":
            issues.append(
                self._issue(
                    "WARNING",
                    candidate_id,
                    "COMMENT_RECOMMENDED_BUT_EMPTY",
                    f"{normalized_status} should keep a human-readable reason.",
                )
            )
        elif normalized_status == "REVIEW_REQUIRED" and comment_state != "PRESENT":
            issues.append(
                self._issue(
                    "INFO",
                    candidate_id,
                    "COMMENT_EMPTY_BEFORE_REVIEW",
                    "REVIEW_REQUIRED can be empty before human judgment.",
                )
            )

        history = record.get("implementation_history")
        if normalized_status in HISTORY_REQUIRED_STATUSES:
            if not isinstance(history, list) or not history:
                issues.append(
                    self._issue(
                        "ERROR",
                        candidate_id,
                        "IMPLEMENTATION_HISTORY_REQUIRED",
                        f"{normalized_status} requires non-empty implementation_history.",
                    )
                )
            else:
                latest = history[-1] if isinstance(history[-1], dict) else {}
                if str(latest.get("to_status") or "").upper() != normalized_status:
                    issues.append(
                        self._issue(
                            "WARNING",
                            candidate_id,
                            "LATEST_HISTORY_STATUS_MISMATCH",
                            f"Latest history to_status does not match current status {normalized_status}.",
                        )
                    )
                if not str(latest.get("comment") or "").strip():
                    issues.append(
                        self._issue(
                            "WARNING",
                            candidate_id,
                            "LATEST_HISTORY_COMMENT_EMPTY",
                            f"Latest {normalized_status} history comment is empty.",
                        )
                    )

        linked_projects = self._linked_projects(record, shadow_index)
        if linked_projects:
            for project in linked_projects:
                issues.extend(self._validate_linked_shadow(record, project))
        elif normalized_status in {"APPROVED", "IMPLEMENTED", "REVERTED"}:
            issues.append(
                self._issue(
                    "UNDETERMINED",
                    candidate_id,
                    "SHADOW_LINK_UNDETERMINED",
                    "No direct Shadow project link could be confirmed from current schema.",
                )
            )

        return issues

    def _validate_linked_shadow(self, record: dict[str, object], project: dict[str, object]) -> list[dict[str, object]]:
        issues = []
        candidate_id = str(record.get("candidate_id") or "")
        status = str(record.get("status") or "").upper()
        project_status = str(project.get("project_status") or "")
        approval_status = str(project.get("approval_status") or "")
        final_decision = str(project.get("final_decision") or "").strip()

        if status == "APPROVED" and approval_status != "APPROVED":
            issues.append(
                self._issue(
                    "WARNING",
                    candidate_id,
                    "APPROVED_WITHOUT_SHADOW_APPROVAL",
                    f"Linked shadow approval_status is {approval_status or 'empty'}.",
                )
            )
        if status in {"IMPLEMENTED", "REVERTED"} and not final_decision:
            issues.append(
                self._issue(
                    "WARNING",
                    candidate_id,
                    "FINAL_DECISION_EXPECTED_BUT_EMPTY",
                    f"Linked shadow project_status={project_status} has empty final_decision.",
                )
            )
        return issues

    def _validate_shadow_projects(self, projects: list[dict[str, object]]) -> list[dict[str, object]]:
        issues = []
        for project in projects:
            project_id = str(project.get("project_id") or "")
            project_status = str(project.get("project_status") or "")
            approval_status = str(project.get("approval_status") or "")
            final_decision = str(project.get("final_decision") or "").strip()

            if not project_id:
                issues.append(self._issue("ERROR", "", "SHADOW_PROJECT_ID_EMPTY", "Shadow project_id is empty."))
            if project_status in SHADOW_TERMINAL_STATUSES and not final_decision:
                issues.append(
                    self._issue(
                        "WARNING",
                        project_id,
                        "SHADOW_FINAL_DECISION_EMPTY",
                        f"project_status={project_status} suggests final_decision should be recorded.",
                    )
                )
            elif project_status == "DRAFT" and approval_status == "PENDING" and not final_decision:
                issues.append(
                    self._issue(
                        "INFO",
                        project_id,
                        "SHADOW_PENDING_NO_FINAL_DECISION",
                        "Pending draft shadow project does not require final_decision yet.",
                    )
                )
        return issues

    def _candidate_row(self, record: dict[str, object], issues: list[dict[str, object]], shadow_index: dict[str, list[dict[str, object]]]) -> dict[str, object]:
        severities = [str(issue.get("severity")) for issue in issues]
        highest = self._highest_severity(severities)
        linked = self._linked_projects(record, shadow_index)
        final_states = [self._final_decision_state(project) for project in linked]
        template_suggestion = HumanReviewTemplateGenerator().suggestion_for(
            record.get("status"),
            self._comment_state(record),
        )
        return {
            "candidate_id": record.get("candidate_id", ""),
            "candidate_name": record.get("candidate_name", ""),
            "target_component": record.get("candidate_type", ""),
            "status": record.get("status", ""),
            "status_source": self._status_source(record),
            "priority": record.get("priority", ""),
            "review_comment_state": self._comment_state(record),
            "review_comment_length": self._comment_length(record),
            "review_details_state": self._review_details_state(record),
            "final_decision_state": ";".join(final_states) if final_states else "NOT_LINKED",
            "severity": highest,
            "reason": " | ".join(str(issue.get("rule")) for issue in issues) if issues else "OK",
            "issue_count": len(issues),
            "comment_policy": template_suggestion.get("comment_policy", ""),
            "recommended_template": template_suggestion.get("recommended_template", ""),
            "template_suggestion_reason": template_suggestion.get("suggestion_reason", ""),
        }

    def _summary(
        self,
        records: list[dict[str, object]],
        projects: list[dict[str, object]],
        candidate_rows: list[dict[str, object]],
        issues: list[dict[str, object]],
        self_tests: dict[str, object],
    ) -> dict[str, object]:
        status_counts = Counter(str(record.get("status") or "MISSING") for record in records)
        severity_counts = Counter(str(issue.get("severity")) for issue in issues)
        comment_states = Counter(row.get("review_comment_state") for row in candidate_rows)
        status_sources = Counter(row.get("status_source") for row in candidate_rows)
        review_detail_states = Counter(row.get("review_details_state") for row in candidate_rows)
        final_states = Counter(row.get("final_decision_state") for row in candidate_rows)
        return {
            "candidate_count": len(records),
            "shadow_project_count": len(projects),
            "status_counts": dict(status_counts),
            "review_comment_present_count": comment_states.get("PRESENT", 0),
            "review_comment_empty_count": comment_states.get("EMPTY", 0),
            "review_comment_whitespace_only_count": comment_states.get("WHITESPACE_ONLY", 0),
            "review_comment_missing_key_count": comment_states.get("MISSING_KEY", 0),
            "status_source_counts": dict(status_sources),
            "review_details_state_counts": dict(review_detail_states),
            "final_decision_empty_count": sum(1 for project in projects if not str(project.get("final_decision") or "").strip()),
            "implementation_history_insufficient_count": sum(
                1
                for issue in issues
                if issue.get("rule") == "IMPLEMENTATION_HISTORY_REQUIRED"
            ),
            "severity_counts": dict(severity_counts),
            "error_count": severity_counts.get("ERROR", 0),
            "warning_count": severity_counts.get("WARNING", 0),
            "info_count": severity_counts.get("INFO", 0),
            "undetermined_count": severity_counts.get("UNDETERMINED", 0),
            "candidate_severity_counts": dict(Counter(row.get("severity") for row in candidate_rows)),
            "final_decision_state_counts": dict(final_states),
            "self_tests_passed": self_tests.get("passed", False),
            "exit_code_recommendation": self._exit_code_recommendation(severity_counts),
        }

    def _comment_state(self, record: dict[str, object]) -> str:
        if "review_comment" not in record:
            return "MISSING_KEY"
        value = record.get("review_comment")
        if value is None or value == "":
            return "EMPTY"
        if not str(value).strip():
            return "WHITESPACE_ONLY"
        return "PRESENT"

    def _comment_length(self, record: dict[str, object]) -> int:
        value = record.get("review_comment")
        return len(str(value)) if value is not None else 0

    def _status_source(self, record: dict[str, object]) -> str:
        value = record.get("status_source")
        if value in (None, ""):
            return "LEGACY_UNKNOWN"
        return str(value).strip().upper()

    def _review_details_state(self, record: dict[str, object]) -> str:
        if "review_details" not in record:
            return "MISSING"
        details = record.get("review_details")
        if not isinstance(details, dict):
            return "INVALID"
        present = sum(1 for field in REVIEW_DETAIL_FIELDS if str(details.get(field) or "").strip())
        return "PRESENT" if present else "EMPTY"

    def _validate_review_details(self, record: dict[str, object], candidate_id: str) -> list[dict[str, object]]:
        if "review_details" not in record:
            return [
                self._issue(
                    "INFO",
                    candidate_id,
                    "REVIEW_DETAILS_MISSING",
                    "Structured review_details are missing; legacy records can omit them.",
                )
            ]
        details = record.get("review_details")
        if not isinstance(details, dict):
            return [self._issue("ERROR", candidate_id, "REVIEW_DETAILS_INVALID", "review_details must be a dictionary when present.")]
        issues = []
        for field in REVIEW_DETAIL_FIELDS:
            if field not in details:
                issues.append(
                    self._issue(
                        "WARNING",
                        candidate_id,
                        "REVIEW_DETAILS_FIELD_MISSING",
                        f"review_details.{field} is missing.",
                    )
                )
        return issues

    def _final_decision_state(self, project: dict[str, object]) -> str:
        if "final_decision" not in project:
            return "MISSING_KEY"
        value = project.get("final_decision")
        if value is None or value == "":
            return "EMPTY"
        if not str(value).strip():
            return "WHITESPACE_ONLY"
        return "PRESENT"

    def _linked_projects(self, record: dict[str, object], shadow_index: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
        keys = [
            str(record.get("candidate_id") or ""),
            str(record.get("candidate_name") or ""),
            str(record.get("candidate_type") or ""),
        ]
        linked: list[dict[str, object]] = []
        seen = set()
        for key in keys:
            for project in shadow_index.get(key, []):
                project_key = project.get("project_id")
                if project_key in seen:
                    continue
                seen.add(project_key)
                linked.append(project)
        return linked

    def _shadow_index(self, projects: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
        index: dict[str, list[dict[str, object]]] = {}
        for project in projects:
            for key in [
                project.get("candidate_id"),
                project.get("candidate_name"),
                project.get("target_component"),
                project.get("project_id"),
            ]:
                if key in (None, ""):
                    continue
                index.setdefault(str(key), []).append(project)
        return index

    def _load_records(self, path: Path, key: str) -> tuple[list[dict[str, object]], str]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except OSError as exc:
            return [], f"{path}: {exc}"
        except ValueError as exc:
            return [], f"{path}: {exc}"
        rows = data.get(key)
        if not isinstance(rows, list):
            return [], f"{path}: missing list key {key}"
        return [row for row in rows if isinstance(row, dict)], ""

    def _issue(self, severity: str, candidate_id: str, rule: str, message: str) -> dict[str, object]:
        return {
            "severity": severity,
            "candidate_id": candidate_id,
            "rule": rule,
            "message": message,
        }

    def _highest_severity(self, severities: list[str]) -> str:
        if not severities:
            return "OK"
        return min(severities, key=lambda value: SEVERITY_ORDER.get(value, 99))

    def _issue_sort_key(self, issue: dict[str, object]) -> tuple[int, str, str]:
        return (
            SEVERITY_ORDER.get(str(issue.get("severity")), 99),
            str(issue.get("candidate_id") or ""),
            str(issue.get("rule") or ""),
        )

    def _exit_code_recommendation(self, severity_counts: Counter) -> str:
        if severity_counts.get("ERROR", 0):
            return "ERRORS_PRESENT_REVIEW_REQUIRED"
        if severity_counts.get("WARNING", 0):
            return "WARNINGS_PRESENT_OPERATION_REVIEW"
        return "PASS"

    def _severity_rules(self) -> dict[str, list[str]]:
        return {
            "ERROR": [
                "missing required key",
                "missing or invalid status",
                "non-canonical status notation",
                "IMPLEMENTED/REVERTED without implementation_history",
                "invalid status_source",
                "invalid review_details structure",
            ],
            "WARNING": [
                "APPROVED/WATCH/REJECTED/IMPLEMENTED/REVERTED without review_comment",
                "terminal shadow project without final_decision",
                "implementation history latest status/comment incomplete",
                "review_details field missing when review_details exists",
            ],
            "INFO": [
                "REVIEW_REQUIRED without comment",
                "DRAFT/PENDING shadow project without final_decision",
                "legacy record missing status_source",
                "legacy record missing review_details",
                "HUMAN WATCH protection visibility",
                "RANKING WATCH mutability visibility",
            ],
            "UNDETERMINED": [
                "schema cannot directly link Human Review candidate to Shadow project",
            ],
        }

    def _self_tests(self) -> dict[str, object]:
        details = {
            "expected_effect": "",
            "side_effect": "",
            "additional_data_needed": "",
            "shadow_test_target": "",
            "recheck_condition": "",
        }
        test_index = {
            "Shadowed": [
                {
                    "project_id": "shadow_ok",
                    "candidate_id": "Shadowed",
                    "project_status": "READY_FOR_IMPLEMENTATION",
                    "approval_status": "APPROVED",
                    "final_decision": "ACCEPT",
                }
            ]
        }
        record_cases = [
            (
                "normal_review_required",
                {"candidate_id": "a", "status": "REVIEW_REQUIRED", "status_source": "RANKING", "review_comment": "", "review_details": details, "implementation_history": []},
                "INFO",
            ),
            (
                "approved_empty_comment",
                {"candidate_id": "b", "status": "APPROVED", "status_source": "HUMAN", "review_comment": "", "review_details": details, "implementation_history": []},
                "WARNING",
            ),
            (
                "approved_with_reason",
                {"candidate_id": "Shadowed", "status": "APPROVED", "status_source": "HUMAN", "review_comment": "approved reason", "review_details": details, "implementation_history": []},
                "OK",
            ),
            (
                "rejected_empty_comment",
                {"candidate_id": "d", "status": "REJECTED", "status_source": "HUMAN", "review_comment": "", "review_details": details, "implementation_history": []},
                "WARNING",
            ),
            (
                "invalid_status",
                {"candidate_id": "e", "status": "BAD", "status_source": "RANKING", "review_comment": "", "review_details": details, "implementation_history": []},
                "ERROR",
            ),
            (
                "missing_status",
                {"candidate_id": "f", "status_source": "RANKING", "review_comment": "", "review_details": details, "implementation_history": []},
                "ERROR",
            ),
            (
                "final_decision_required_but_empty",
                {
                    "project_id": "shadow_missing_final",
                    "candidate_id": "shadow_candidate",
                    "project_status": "READY_FOR_IMPLEMENTATION",
                    "approval_status": "APPROVED",
                    "final_decision": "",
                },
                "WARNING",
            ),
            (
                "implemented_no_history",
                {"candidate_id": "g", "status": "IMPLEMENTED", "status_source": "HUMAN", "review_comment": "done", "review_details": details, "implementation_history": []},
                "ERROR",
            ),
            (
                "reverted_no_revert_reason",
                {
                    "candidate_id": "i",
                    "status": "REVERTED",
                    "status_source": "HUMAN",
                    "review_comment": "reverted",
                    "review_details": details,
                    "implementation_history": [{"to_status": "REVERTED", "comment": ""}],
                },
                "WARNING",
            ),
            (
                "whitespace_only_comment",
                {"candidate_id": "h", "status": "WATCH", "status_source": "HUMAN", "review_comment": "   ", "review_details": details, "implementation_history": []},
                "WARNING",
            ),
            (
                "unknown_additional_fields",
                {
                    "candidate_id": "j",
                    "status": "REVIEW_REQUIRED",
                    "status_source": "RANKING",
                    "review_comment": "ready for review",
                    "review_details": details,
                    "implementation_history": [],
                    "future_schema_field": {"kept": True},
                },
                "OK",
            ),
            (
                "legacy_missing_status_source",
                {"candidate_id": "k", "status": "WATCH", "review_comment": "", "implementation_history": []},
                "WARNING",
            ),
            ("empty_candidate_list", [], "OK"),
        ]
        results = []
        for name, payload, expected in record_cases:
            if name == "final_decision_required_but_empty":
                issues = self._validate_shadow_projects([payload])
            elif name == "empty_candidate_list":
                issues = []
                candidate_rows: list[dict[str, object]] = []
                summary = self._summary(payload, [], candidate_rows, issues, {"passed": True})
                if summary.get("candidate_count") != 0:
                    issues = [self._issue("ERROR", "", "EMPTY_LIST_SUMMARY_FAILED", "Empty candidate list was not summarized as 0.")]
            else:
                issues = self._validate_record(payload, test_index)
            actual = self._highest_severity([str(issue.get("severity")) for issue in issues])
            results.append(
                {
                    "case": name,
                    "expected": expected,
                    "actual": actual,
                    "passed": actual == expected,
                }
            )
        return {
            "passed": all(row["passed"] for row in results),
            "case_count": len(results),
            "results": results,
        }

    def _write_reports(self, result: dict[str, object]) -> None:
        self.report_md.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(self.report_json, result)
        self._write_csv(self.report_csv, result.get("candidate_rows", []))
        self.report_md.write_text(self._markdown(result), encoding="utf-8")

    def _write_json(self, path: Path, data: dict[str, object]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

    def _write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        fields = [
            "candidate_id",
            "candidate_name",
            "target_component",
            "status",
            "priority",
            "status_source",
            "review_comment_state",
            "review_comment_length",
            "review_details_state",
            "final_decision_state",
            "severity",
            "reason",
            "issue_count",
            "comment_policy",
            "recommended_template",
            "template_suggestion_reason",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def _markdown(self, result: dict[str, object]) -> str:
        summary = result.get("summary", {})
        issues = result.get("issues", [])
        candidates = result.get("candidate_rows", [])
        lines = [
            "# Human Review Quality Validation",
            "",
            f"- Generated: {result.get('generated_at')}",
            f"- Human Review DB: {result.get('input_files', {}).get('human_review_db')}",
            f"- Shadow Projects: {result.get('input_files', {}).get('shadow_projects')}",
            "",
            "## Summary",
            "",
            f"- Candidate Count: {summary.get('candidate_count')}",
            f"- Shadow Project Count: {summary.get('shadow_project_count')}",
            f"- Status Counts: {summary.get('status_counts')}",
            f"- Review Comment Present: {summary.get('review_comment_present_count')}",
            f"- Review Comment Empty: {summary.get('review_comment_empty_count')}",
            f"- Final Decision Empty: {summary.get('final_decision_empty_count')}",
            f"- Implementation History Insufficient: {summary.get('implementation_history_insufficient_count')}",
            f"- ERROR: {summary.get('error_count')}",
            f"- WARNING: {summary.get('warning_count')}",
            f"- INFO: {summary.get('info_count')}",
            f"- UNDETERMINED: {summary.get('undetermined_count')}",
            f"- Self Tests Passed: {summary.get('self_tests_passed')}",
            f"- Recommendation: {summary.get('exit_code_recommendation')}",
            "",
            "## Candidate Validation",
            "",
            "| candidate_id | target_component | status | status_source | priority | comment | details | final_decision | severity | template | reason |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for row in candidates:
            lines.append(
                "| {candidate_id} | {target_component} | {status} | {status_source} | {priority} | {comment} | {details} | {final_decision} | {severity} | {template} | {reason} |".format(
                    candidate_id=row.get("candidate_id", ""),
                    target_component=row.get("target_component", ""),
                    status=row.get("status", ""),
                    status_source=row.get("status_source", ""),
                    priority=row.get("priority", ""),
                    comment=row.get("review_comment_state", ""),
                    details=row.get("review_details_state", ""),
                    final_decision=row.get("final_decision_state", ""),
                    severity=row.get("severity", ""),
                    template=row.get("recommended_template", ""),
                    reason=str(row.get("reason", "")).replace("|", "/"),
                )
            )
        lines.extend(["", "## Template Suggestions", ""])
        for row in candidates:
            suggestion = str(row.get("template_suggestion_reason") or "").replace("|", "/")
            lines.append(
                f"- `{row.get('candidate_id')}` {row.get('status')}: {row.get('recommended_template')} - {suggestion}"
            )
        for severity in ["ERROR", "WARNING", "INFO", "UNDETERMINED"]:
            rows = [issue for issue in issues if issue.get("severity") == severity]
            lines.extend(["", f"## {severity}", ""])
            if not rows:
                lines.append("- none")
                continue
            for issue in rows:
                lines.append(
                    f"- `{issue.get('candidate_id')}` {issue.get('rule')}: {issue.get('message')}"
                )
        lines.extend(
            [
                "",
                "## Guardrails",
                "",
                "- Read-only validator.",
                "- No status update.",
                "- No comment autofill.",
                "- No Candidate migration.",
                "- No Production logic change.",
                "- No JSON DB mutation.",
            ]
        )
        return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Human Review operation quality.")
    parser.add_argument("--no-write", action="store_true", help="Run validation without writing report files.")
    args = parser.parse_args()
    result = HumanReviewQualityValidator().validate(write_reports=not args.no_write)
    print(json.dumps(result.get("summary", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
