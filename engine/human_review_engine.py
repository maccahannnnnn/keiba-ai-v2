"""Manage human review status for learning candidates.

HumanReviewEngine is a lifecycle management layer only. It records human
review status for ranked improvement candidates and writes a report. It does
not change candidates, rankings, evaluators, decisions, knowledge, scores, or
CSV files.
"""

from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine.learning_candidate_ranking_engine import LearningCandidateRankingEngine


class HumanReviewEngine:
    """Store approval/rejection lifecycle status for ranked candidates."""

    DEFAULT_STATUS_DB_PATH = Path("learning/candidate_review_status.json")
    DEFAULT_REPORT_PATH = Path("reports/human_review_report.md")

    VALID_STATUSES = {
        "REVIEW_REQUIRED",
        "APPROVED",
        "WATCH",
        "REJECTED",
        "IMPLEMENTED",
        "REVERTED",
    }

    TERMINAL_OR_HUMAN_STATUSES = {
        "APPROVED",
        "REJECTED",
        "IMPLEMENTED",
        "REVERTED",
    }

    VALID_STATUS_SOURCES = {
        "RANKING",
        "HUMAN",
    }

    REVIEW_DETAIL_FIELDS = [
        "expected_effect",
        "side_effect",
        "additional_data_needed",
        "shadow_test_target",
        "recheck_condition",
    ]

    def __init__(
        self,
        status_db_path=None,
        report_path=None,
        ranking_engine=None,
    ):
        self.status_db_path = (
            Path(status_db_path) if status_db_path else self.DEFAULT_STATUS_DB_PATH
        )
        self.report_path = Path(report_path) if report_path else self.DEFAULT_REPORT_PATH
        self.ranking_engine = ranking_engine or LearningCandidateRankingEngine()

    def sync_from_ranking(self, reviewer="system", review_comment=""):
        """Create or refresh review status records from current ranking output."""

        ranking = self._current_ranking()
        database = self._load_status_database()
        records = self._records_by_id(database)
        now = self._now()

        for item in ranking:
            candidate_id = self._candidate_id(item)
            existing = records.get(candidate_id)
            if existing:
                self._refresh_existing_record(existing, item, now)
                continue
            records[candidate_id] = self._new_record(
                item=item,
                candidate_id=candidate_id,
                reviewer=reviewer,
                review_comment=review_comment,
                now=now,
            )

        active_ids = {self._candidate_id(item) for item in ranking}
        for candidate_id, record in records.items():
            if candidate_id in active_ids:
                record["ranking_active"] = True
                record["archive_reason"] = ""
                continue
            record["ranking_active"] = False
            record.setdefault("archived_at", now)
            record["archive_reason"] = "not_present_in_current_learning_candidate_ranking"

        database["records"] = sorted(
            records.values(),
            key=lambda record: (
                self._status_order(record.get("status")),
                str(record.get("candidate_name") or ""),
            ),
        )
        database["summary"] = self._summary(database["records"])
        database["updated_at"] = now
        self._save_status_database(database)
        report = self._write_report(database)
        return {
            "status": "synced",
            "candidate_count": len(database["records"]),
            "summary": database["summary"],
            "status_db_path": str(self.status_db_path),
            "report_path": str(self.report_path),
            "report": report,
            "warnings": self._list(database.get("warnings")),
        }

    def update_review(
        self,
        candidate_id=None,
        candidate_name=None,
        status=None,
        review_comment="",
        reviewer="human",
        expected_effect="",
        side_effect="",
        additional_data_needed="",
        shadow_test_target="",
        recheck_condition="",
    ):
        """Update one candidate's human review status."""

        normalized_status = str(status or "").upper()
        if normalized_status not in self.VALID_STATUSES:
            return {
                "status": "failed",
                "reason": "invalid_status",
                "valid_statuses": sorted(self.VALID_STATUSES),
            }

        database = self._load_status_database()
        records = self._records_by_id(database)
        target_id = candidate_id or self._find_candidate_id(records, candidate_name)
        if not target_id or target_id not in records:
            return {
                "status": "failed",
                "reason": "candidate_not_found",
                "candidate_id": candidate_id,
                "candidate_name": candidate_name,
            }

        record = records[target_id]
        previous_status = record.get("status")
        now = self._now()
        record["status"] = normalized_status
        record["review_comment"] = review_comment
        record["reviewer"] = reviewer
        record["review_date"] = now
        record["status_source"] = "HUMAN"
        review_details = self._review_details(
            expected_effect=expected_effect,
            side_effect=side_effect,
            additional_data_needed=additional_data_needed,
            shadow_test_target=shadow_test_target,
            recheck_condition=recheck_condition,
        )
        record["review_details"] = review_details
        record.setdefault("implementation_history", [])
        record["implementation_history"].append(
            {
                "date": now,
                "reviewer": reviewer,
                "from_status": previous_status,
                "to_status": normalized_status,
                "comment": review_comment,
                "review_details": review_details,
            }
        )

        database["records"] = sorted(
            records.values(),
            key=lambda item: (
                self._status_order(item.get("status")),
                str(item.get("candidate_name") or ""),
            ),
        )
        database["summary"] = self._summary(database["records"])
        database["updated_at"] = now
        self._save_status_database(database)
        report = self._write_report(database)
        return {
            "status": "updated",
            "candidate_id": target_id,
            "previous_status": previous_status,
            "new_status": normalized_status,
            "summary": database["summary"],
            "report_path": str(self.report_path),
            "report": report,
        }

    def _current_ranking(self):
        database = self.ranking_engine._load_database()
        records = self.ranking_engine._list(database.get("records"))
        return self.ranking_engine._build_ranking(records)

    def _new_record(self, item, candidate_id, reviewer, review_comment, now):
        status = item.get("status") or "REVIEW_REQUIRED"
        if status not in self.VALID_STATUSES:
            status = "REVIEW_REQUIRED"
        return {
            "candidate_id": candidate_id,
            "candidate_name": item.get("candidate_name"),
            "candidate_type": item.get("candidate_type"),
            "priority": item.get("priority"),
            "ranking_score": item.get("ranking_score"),
            "rank": item.get("rank"),
            "status": status,
            "status_source": "RANKING",
            "review_comment": review_comment,
            "review_details": self._review_details(),
            "reviewer": reviewer,
            "review_date": now,
            "implementation_history": [
                {
                    "date": now,
                    "reviewer": reviewer,
                    "from_status": None,
                    "to_status": status,
                    "comment": "initial sync from Learning Candidate Ranking",
                }
            ],
            "ranking_snapshot": self._ranking_snapshot(item),
            "ranking_active": True,
            "archive_reason": "",
            "created_at": now,
            "updated_at": now,
        }

    def _refresh_existing_record(self, record, item, now):
        record["candidate_name"] = item.get("candidate_name")
        record["candidate_type"] = item.get("candidate_type")
        record["priority"] = item.get("priority")
        record["ranking_score"] = item.get("ranking_score")
        record["rank"] = item.get("rank")
        if record.get("status") not in self.TERMINAL_OR_HUMAN_STATUSES:
            if record.get("status") == "WATCH" and record.get("status_source") == "HUMAN":
                record["ranking_snapshot"] = self._ranking_snapshot(item)
                record["updated_at"] = now
                record.setdefault("implementation_history", [])
                record.setdefault("review_comment", "")
                record.setdefault("reviewer", "")
                record.setdefault("review_date", "")
                return
            status = item.get("status") or record.get("status") or "REVIEW_REQUIRED"
            normalized_status = status if status in self.VALID_STATUSES else "REVIEW_REQUIRED"
            previous_status = record.get("status")
            record["status"] = normalized_status
            if record.get("status_source") in self.VALID_STATUS_SOURCES or normalized_status != previous_status:
                record["status_source"] = "RANKING"
        record["ranking_snapshot"] = self._ranking_snapshot(item)
        record["updated_at"] = now
        record.setdefault("implementation_history", [])
        record.setdefault("review_comment", "")
        record.setdefault("reviewer", "")
        record.setdefault("review_date", "")

    def _ranking_snapshot(self, item):
        return {
            "occurrences": item.get("occurrences"),
            "fn_count": item.get("fn_count"),
            "fp_count": item.get("fp_count"),
            "race_count": item.get("race_count"),
            "racecourses": item.get("racecourses", []),
            "distances": item.get("distances", []),
            "surfaces": item.get("surfaces", []),
            "track_conditions": item.get("track_conditions", []),
            "race_classes": item.get("race_classes", []),
            "first_seen": item.get("first_seen"),
            "latest_seen": item.get("latest_seen"),
            "average_confidence": item.get("average_confidence"),
            "average_decision_score": item.get("average_decision_score"),
            "related_evaluators": item.get("related_evaluators", []),
            "related_knowledge": item.get("related_knowledge", []),
            "related_decisions": item.get("related_decisions", []),
            "improvement_candidate": item.get("improvement_candidate"),
        }

    def _write_report(self, database):
        records = self._list(database.get("records"))
        summary = database.get("summary") if isinstance(database.get("summary"), dict) else {}
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Human Review Report",
            "",
            f"- Updated: {database.get('updated_at')}",
            f"- Candidate Count: {len(records)}",
            f"- Active Ranking Candidates: {summary.get('ACTIVE', 0)}",
            f"- Inactive Historical Candidates: {summary.get('INACTIVE', 0)}",
            f"- REVIEW_REQUIRED: {summary.get('REVIEW_REQUIRED', 0)}",
            f"- APPROVED: {summary.get('APPROVED', 0)}",
            f"- WATCH: {summary.get('WATCH', 0)}",
            f"- REJECTED: {summary.get('REJECTED', 0)}",
            f"- IMPLEMENTED: {summary.get('IMPLEMENTED', 0)}",
            f"- REVERTED: {summary.get('REVERTED', 0)}",
            "",
            "## Status Table",
            "",
            "| Candidate ID | Candidate | Active | Priority | Status | Reviewer | Review Date | Comment |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for record in records:
            lines.append(
                "| {candidate_id} | {candidate_name} | {active} | {priority} | {status} | "
                "{reviewer} | {review_date} | {review_comment} |".format(
                    candidate_id=record.get("candidate_id"),
                    candidate_name=record.get("candidate_name"),
                    active=record.get("ranking_active", True),
                    priority=record.get("priority"),
                    status=record.get("status"),
                    reviewer=record.get("reviewer") or "",
                    review_date=record.get("review_date") or "",
                    review_comment=str(record.get("review_comment") or "").replace("|", "/"),
                )
            )

        lines.extend(["", "## Candidate Details", ""])
        for record in records:
            snapshot = record.get("ranking_snapshot")
            if not isinstance(snapshot, dict):
                snapshot = {}
            lines.extend(
                [
                    f"### {record.get('candidate_name')}",
                    "",
                    f"- Candidate ID: {record.get('candidate_id')}",
                    f"- Priority: {record.get('priority')}",
                    f"- Status: {record.get('status')}",
                    f"- Rank: {record.get('rank')}",
                    f"- Ranking Score: {record.get('ranking_score')}",
                    f"- Occurrence: {snapshot.get('occurrences')}",
                    f"- FN: {snapshot.get('fn_count')}",
                    f"- FP: {snapshot.get('fp_count')}",
                    f"- Race Count: {snapshot.get('race_count')}",
                    f"- Improvement Candidate: {snapshot.get('improvement_candidate')}",
                    f"- Review Comment: {record.get('review_comment') or ''}",
                    "",
                ]
            )

        lines.extend(
            [
                "## Guardrails",
                "",
                "- APPROVED candidates are eligible for the next Candidate Implementation phase.",
                "- This engine stores lifecycle status only.",
                "- It does not change Learning Candidate, Ranking, Decision, Evaluator, Knowledge, weights, scores, or CSV files.",
            ]
        )
        report = "\n".join(lines) + "\n"
        self.report_path.write_text(report, encoding="utf-8")
        return report

    def _load_status_database(self):
        if not self.status_db_path.exists():
            return {
                "version": "1.0",
                "engine": "HumanReviewEngine",
                "records": [],
                "summary": {},
                "updated_at": None,
            }
        try:
            return json.loads(self.status_db_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "version": "1.0",
                "engine": "HumanReviewEngine",
                "records": [],
                "summary": {},
                "updated_at": None,
                "warnings": [f"status database unreadable: {exc}"],
            }

    def _save_status_database(self, database):
        self.status_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_db_path.write_text(
            json.dumps(database, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _records_by_id(self, database):
        records = {}
        for record in self._list(database.get("records")):
            if isinstance(record, dict) and record.get("candidate_id"):
                records[record["candidate_id"]] = record
        return records

    def _summary(self, records):
        summary = {status: 0 for status in sorted(self.VALID_STATUSES)}
        summary["ACTIVE"] = 0
        summary["INACTIVE"] = 0
        for record in records:
            status = record.get("status")
            if status in summary:
                summary[status] += 1
            if record.get("ranking_active") is False:
                summary["INACTIVE"] += 1
            else:
                summary["ACTIVE"] += 1
        return summary

    def _review_details(
        self,
        expected_effect="",
        side_effect="",
        additional_data_needed="",
        shadow_test_target="",
        recheck_condition="",
    ):
        return {
            "expected_effect": expected_effect or "",
            "side_effect": side_effect or "",
            "additional_data_needed": additional_data_needed or "",
            "shadow_test_target": shadow_test_target or "",
            "recheck_condition": recheck_condition or "",
        }

    def _candidate_id(self, item):
        raw = f"{item.get('candidate_type') or 'Other'}::{item.get('candidate_name')}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return f"hr_{digest}"

    def _find_candidate_id(self, records, candidate_name):
        if not candidate_name:
            return None
        for candidate_id, record in records.items():
            if record.get("candidate_name") == candidate_name:
                return candidate_id
        return None

    def _status_order(self, status):
        return {
            "REVIEW_REQUIRED": 0,
            "APPROVED": 1,
            "WATCH": 2,
            "REJECTED": 3,
            "IMPLEMENTED": 4,
            "REVERTED": 5,
        }.get(status, 9)

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def _list(self, value):
        return value if isinstance(value, list) else []


if __name__ == "__main__":
    result = HumanReviewEngine().sync_from_ranking()
    print(
        {
            "status": result.get("status"),
            "candidate_count": result.get("candidate_count"),
            "status_db_path": result.get("status_db_path"),
            "report_path": result.get("report_path"),
        }
    )
