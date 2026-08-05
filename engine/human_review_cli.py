"""Human Review operation CLI.

The CLI helps a human reviewer inspect candidates and submit a structured
review. It never writes JSON directly; successful saves call
HumanReviewEngine.update_review() exactly once.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from engine.human_review_engine import HumanReviewEngine
from review.human_review_template_generator import HumanReviewTemplateGenerator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMPROVEMENT_DB = ROOT / "learning" / "improvement_candidates.json"

CLI_STATUSES = {"APPROVED", "WATCH", "REJECTED"}


class HumanReviewEvidenceReader:
    """Read existing candidate evidence without changing source files."""

    def __init__(self, improvement_db_path: Path | str = DEFAULT_IMPROVEMENT_DB):
        self.improvement_db_path = Path(improvement_db_path)

    def evidence_for_candidate(self, candidate: dict[str, object], limit: int = 3) -> dict[str, object]:
        records = self._load_records()
        candidate_name = str(candidate.get("candidate_name") or "")
        candidate_type = str(candidate.get("candidate_type") or "")
        matched = [record for record in records if self._record_matches(record, candidate_name, candidate_type)]
        categories = {
            "representative_failures": [],
            "representative_successes": [],
            "counterexamples": [],
            "undetermined": [],
        }
        race_ids = []
        for record in matched:
            race_id = str(record.get("race_id") or "")
            if race_id and race_id not in race_ids:
                race_ids.append(race_id)
            row = self._evidence_row(record, candidate_name)
            bucket = self._classify_record(record, candidate_name)
            if len(categories[bucket]) < limit:
                categories[bucket].append(row)
        return {
            "source": str(self.improvement_db_path),
            "matched_record_count": len(matched),
            "matched_race_ids": race_ids,
            **categories,
        }

    def _record_matches(self, record: dict[str, object], candidate_name: str, candidate_type: str) -> bool:
        for field in ["primary_candidate", "root_primary_candidate", "decision_primary_factor"]:
            if record.get(field) == candidate_name:
                return True
        for key in ["attribution_candidates", "cause_candidates", "root_causes"]:
            for item in self._list(record.get(key)):
                if not isinstance(item, dict):
                    continue
                if item.get("target") == candidate_name:
                    return True
                if candidate_type and item.get("target_type") == candidate_type and item.get("target") == candidate_name:
                    return True
        return False

    def _classify_record(self, record: dict[str, object], candidate_name: str) -> str:
        case_type = str(record.get("case_type") or "").upper()
        if record.get("fn") or case_type in {"FALSE_NEGATIVE", "MISSED_TOP3", "FN"}:
            return "representative_failures"
        if record.get("fp") or case_type in {"FALSE_POSITIVE", "FAILED_BUY", "FP"}:
            return "representative_failures"
        for item in self._list(record.get("attribution_candidates")):
            if not isinstance(item, dict) or item.get("target") != candidate_name:
                continue
            if self._list(item.get("counter_evidence")):
                return "counterexamples"
            if self._list(item.get("evidence")):
                return "representative_successes"
        return "undetermined"

    def _evidence_row(self, record: dict[str, object], candidate_name: str) -> dict[str, object]:
        attribution = []
        for key in ["attribution_candidates", "cause_candidates"]:
            for item in self._list(record.get(key)):
                if isinstance(item, dict) and item.get("target") == candidate_name:
                    attribution.append(item)
        return {
            "race_id": record.get("race_id", ""),
            "horse": record.get("horse") or record.get("horse_name") or "",
            "decision": record.get("decision") or record.get("official_decision") or "",
            "finish_position": record.get("finish_position") or record.get("finish") or "",
            "case_type": record.get("case_type") or ("FN" if record.get("fn") else ("FP" if record.get("fp") else "")),
            "root_primary_candidate": record.get("root_primary_candidate") or record.get("primary_candidate") or "",
            "attribution_candidates": [item.get("target") for item in attribution if isinstance(item, dict)],
            "major_evaluators": record.get("related_evaluators") or record.get("major_evaluators") or [],
        }

    def _load_records(self) -> list[dict[str, object]]:
        if not self.improvement_db_path.exists():
            return []
        try:
            data = json.loads(self.improvement_db_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        records = data.get("records")
        return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []

    def _list(self, value):
        return value if isinstance(value, list) else []


class HumanReviewCLI:
    """List, inspect, and update Human Review candidates through the engine."""

    def __init__(
        self,
        engine: HumanReviewEngine | None = None,
        evidence_reader: HumanReviewEvidenceReader | None = None,
    ):
        self.engine = engine or HumanReviewEngine()
        self.evidence_reader = evidence_reader or HumanReviewEvidenceReader()
        self.template_generator = HumanReviewTemplateGenerator()

    def list_candidates(self, mode: str = "all") -> list[dict[str, object]]:
        database = self.engine._load_status_database()
        records = self.engine._list(database.get("records"))
        return [record for record in records if self._matches_mode(record, mode)]

    def candidate_summary(self, record: dict[str, object]) -> dict[str, object]:
        snapshot = record.get("ranking_snapshot") if isinstance(record.get("ranking_snapshot"), dict) else {}
        return {
            "candidate_id": record.get("candidate_id", ""),
            "candidate_name": record.get("candidate_name", ""),
            "candidate_type": record.get("candidate_type", ""),
            "priority": record.get("priority", ""),
            "ranking_score": record.get("ranking_score", ""),
            "occurrences": snapshot.get("occurrences", ""),
            "fn": snapshot.get("fn_count", ""),
            "fp": snapshot.get("fp_count", ""),
            "race_count": snapshot.get("race_count", ""),
            "racecourses": snapshot.get("racecourses", []),
            "distances": snapshot.get("distances", []),
            "related_evaluators": snapshot.get("related_evaluators", []),
            "current_status": record.get("status", ""),
            "status_source": record.get("status_source", "LEGACY_UNKNOWN"),
            "review_comment_state": self._comment_state(record),
        }

    def evidence_summary(self, record: dict[str, object]) -> dict[str, object]:
        return self.evidence_reader.evidence_for_candidate(record)

    def review(
        self,
        candidate_id: str,
        status: str,
        reviewer: str,
        review_comment: str,
        expected_effect: str = "",
        side_effect: str = "",
        additional_data_needed: str = "",
        shadow_test_target: str = "",
        recheck_condition: str = "",
        confirm: bool = False,
        dry_run: bool = False,
    ) -> dict[str, object]:
        normalized_status = str(status or "").strip().upper()
        if normalized_status not in CLI_STATUSES:
            return {
                "status": "failed",
                "reason": "cli_status_not_allowed",
                "allowed_statuses": sorted(CLI_STATUSES),
            }
        if not str(reviewer or "").strip():
            return {"status": "failed", "reason": "reviewer_required"}
        if normalized_status in CLI_STATUSES and not str(review_comment or "").strip() and not confirm:
            return {
                "status": "confirmation_required",
                "reason": "empty_review_comment",
                "message": f"{normalized_status} should keep a review_comment. Re-run with --yes to save anyway.",
            }
        if dry_run:
            return {
                "status": "dry_run",
                "candidate_id": candidate_id,
                "new_status": normalized_status,
                "would_call_update_review": True,
            }
        return self.engine.update_review(
            candidate_id=candidate_id,
            status=normalized_status,
            review_comment=review_comment,
            reviewer=reviewer,
            expected_effect=expected_effect,
            side_effect=side_effect,
            additional_data_needed=additional_data_needed,
            shadow_test_target=shadow_test_target,
            recheck_condition=recheck_condition,
        )

    def interactive_review(self, mode: str = "all") -> dict[str, object]:
        candidates = self.list_candidates(mode)
        if not candidates:
            print("No candidates.")
            return {"status": "skipped", "reason": "empty_candidate_list"}
        self.print_candidates(candidates)
        selected = input("candidate_id (blank to abort): ").strip()
        if not selected:
            return {"status": "aborted"}
        record = next((item for item in candidates if item.get("candidate_id") == selected), None)
        if not record:
            return {"status": "failed", "reason": "candidate_not_found"}
        self.print_candidate_detail(record)
        status = input("status APPROVED/WATCH/REJECTED (blank to skip): ").strip().upper()
        if not status:
            return {"status": "skipped"}
        reviewer = input("reviewer identifier: ").strip()
        print(self.template_generator.template_for(status))
        review_comment = input("review_comment: ")
        expected_effect = input("expected_effect: ")
        side_effect = input("side_effect: ")
        additional_data_needed = input("additional_data_needed: ")
        shadow_test_target = input("shadow_test_target: ")
        recheck_condition = input("recheck_condition: ")
        confirm_value = input("save? type YES: ").strip()
        if confirm_value != "YES":
            return {"status": "cancelled"}
        result = self.review(
            candidate_id=selected,
            status=status,
            reviewer=reviewer,
            review_comment=review_comment,
            expected_effect=expected_effect,
            side_effect=side_effect,
            additional_data_needed=additional_data_needed,
            shadow_test_target=shadow_test_target,
            recheck_condition=recheck_condition,
            confirm=True,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def print_candidates(self, records: list[dict[str, object]]) -> None:
        for record in records:
            summary = self.candidate_summary(record)
            print(
                "{candidate_id} | {candidate_name} | {candidate_type} | {priority} | "
                "{current_status} | {status_source} | score={ranking_score}".format(**summary)
            )

    def print_candidate_detail(self, record: dict[str, object]) -> None:
        print(json.dumps(self.candidate_summary(record), ensure_ascii=False, indent=2))
        print(json.dumps(self.evidence_summary(record), ensure_ascii=False, indent=2))

    def _matches_mode(self, record: dict[str, object], mode: str) -> bool:
        mode = (mode or "all").strip().lower()
        status = record.get("status")
        source = record.get("status_source", "LEGACY_UNKNOWN")
        priority = record.get("priority")
        if mode == "all":
            return True
        if mode == "review-required":
            return status == "REVIEW_REQUIRED"
        if mode == "human-watch":
            return status == "WATCH" and source == "HUMAN"
        if mode == "approved":
            return status == "APPROVED"
        if mode == "new":
            return status == "REVIEW_REQUIRED" and source in {"RANKING", "LEGACY_UNKNOWN"}
        if mode == "high-priority":
            return priority in {"S", "A", "P0", "P1"}
        return True

    def _comment_state(self, record: dict[str, object]) -> str:
        value = record.get("review_comment")
        if value is None or value == "":
            return "EMPTY"
        if not str(value).strip():
            return "WHITESPACE_ONLY"
        return "PRESENT"


def _build_engine(args) -> HumanReviewEngine:
    return HumanReviewEngine(
        status_db_path=args.status_db or None,
        report_path=args.report_path or None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Human Review CLI.")
    parser.add_argument("--status-db", default="", help="Path to candidate_review_status.json.")
    parser.add_argument("--report-path", default="", help="Path to generated Human Review report.")
    parser.add_argument("--improvement-db", default=str(DEFAULT_IMPROVEMENT_DB), help="Path to improvement_candidates.json.")
    parser.add_argument("--mode", default="all", choices=["all", "review-required", "human-watch", "approved", "new", "high-priority"])
    parser.add_argument("--list", action="store_true", help="List candidates.")
    parser.add_argument("--show", default="", help="Show one candidate by candidate_id.")
    parser.add_argument("--candidate-id", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--review-comment", default="")
    parser.add_argument("--expected-effect", default="")
    parser.add_argument("--side-effect", default="")
    parser.add_argument("--additional-data-needed", default="")
    parser.add_argument("--shadow-test-target", default="")
    parser.add_argument("--recheck-condition", default="")
    parser.add_argument("--yes", action="store_true", help="Confirm saving even when warnings are present.")
    parser.add_argument("--dry-run", action="store_true", help="Do not save; show intended action.")
    args = parser.parse_args()

    cli = HumanReviewCLI(
        engine=_build_engine(args),
        evidence_reader=HumanReviewEvidenceReader(args.improvement_db),
    )
    if args.list:
        cli.print_candidates(cli.list_candidates(args.mode))
        return
    if args.show:
        record = next((item for item in cli.list_candidates("all") if item.get("candidate_id") == args.show), None)
        if not record:
            print(json.dumps({"status": "failed", "reason": "candidate_not_found"}, ensure_ascii=False, indent=2))
            return
        cli.print_candidate_detail(record)
        return
    if args.candidate_id or args.status:
        result = cli.review(
            candidate_id=args.candidate_id,
            status=args.status,
            reviewer=args.reviewer,
            review_comment=args.review_comment,
            expected_effect=args.expected_effect,
            side_effect=args.side_effect,
            additional_data_needed=args.additional_data_needed,
            shadow_test_target=args.shadow_test_target,
            recheck_condition=args.recheck_condition,
            confirm=args.yes,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    cli.interactive_review(args.mode)


if __name__ == "__main__":
    main()
