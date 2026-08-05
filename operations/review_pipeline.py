"""Review Pipeline v1.0 for post-result operations.

The pipeline orchestrates existing review/monitoring/learning/shadow utilities.
It does not change evaluator logic, production BUY, scores, decisions, race
state, thresholds, knowledge, CSV inputs, or main.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from evaluation.race_file_locator import RaceFileLocator


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "review_pipeline"
RUNS_DIR = REPORT_DIR / "runs"

STAGE_IDS = [
    "STAGE_01_INPUT_DISCOVERY",
    "STAGE_02_COMPLETE_RACE_SET_VALIDATION",
    "STAGE_03_BUY_MONITORING",
    "STAGE_04_IMPROVEMENT_CANDIDATES",
    "STAGE_05_IMPROVEMENT_PRIORITY",
    "STAGE_06_SHADOW_VALIDATION",
    "STAGE_07_SHADOW_FP_FILTER",
    "STAGE_08_PIPELINE_SUMMARY",
]


@dataclass
class StageResult:
    stage_id: str
    stage_name: str
    status: str = "PENDING"
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    input_files: list[str] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    records_processed: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    message: str = ""
    command_or_function: str = ""
    skipped_reason: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "stage_name": self.stage_name,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": f"{self.duration_seconds:.3f}",
            "input_files": ";".join(self.input_files),
            "output_files": ";".join(self.output_files),
            "records_processed": self.records_processed,
            "warnings": " | ".join(self.warnings),
            "errors": " | ".join(self.errors),
            "message": self.message,
            "command_or_function": self.command_or_function,
            "skipped_reason": self.skipped_reason,
        }


class ReviewPipeline:
    """Run the operational review stages in a fixed, traceable order."""

    def __init__(
        self,
        date: str = "",
        from_date: str = "",
        to_date: str = "",
        race_id: str = "",
        dry_run: bool = False,
        with_validators: bool = False,
        skip_shadow: bool = False,
        enable_shadow_fp_filter: bool = False,
        run_id: str = "",
    ):
        self.date = date
        self.from_date = from_date
        self.to_date = to_date
        self.race_id = race_id
        self.dry_run = dry_run
        self.with_validators = with_validators
        self.skip_shadow = skip_shadow
        self.enable_shadow_fp_filter = enable_shadow_fp_filter
        self.run_id = run_id or f"REVIEW_PIPELINE_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.run_dir = RUNS_DIR / self.run_id
        self.stage_results: list[StageResult] = []
        self.race_inventory: list[dict[str, Any]] = []
        self.output_inventory: list[dict[str, Any]] = []
        self.pipeline_warnings: list[dict[str, Any]] = []
        self.pipeline_errors: list[dict[str, Any]] = []
        self.context: dict[str, Any] = {}

    def run(self) -> dict[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        stages: list[tuple[str, str, Callable[[], StageResult]]] = [
            ("STAGE_01_INPUT_DISCOVERY", "INPUT_DISCOVERY", self.stage_input_discovery),
            ("STAGE_02_COMPLETE_RACE_SET_VALIDATION", "COMPLETE_RACE_SET_VALIDATION", self.stage_complete_sets),
            ("STAGE_03_BUY_MONITORING", "BUY_MONITORING", self.stage_buy_monitoring),
            ("STAGE_04_IMPROVEMENT_CANDIDATES", "IMPROVEMENT_CANDIDATES", self.stage_improvement_candidates),
            ("STAGE_05_IMPROVEMENT_PRIORITY", "IMPROVEMENT_PRIORITY", self.stage_improvement_priority),
            ("STAGE_06_SHADOW_VALIDATION", "SHADOW_VALIDATION", self.stage_shadow_validation),
            ("STAGE_07_SHADOW_FP_FILTER", "SHADOW_FP_FILTER", self.stage_shadow_fp_filter),
            ("STAGE_08_PIPELINE_SUMMARY", "PIPELINE_SUMMARY", self.stage_pipeline_summary),
        ]
        blocked = False
        for idx, (stage_id, stage_name, func) in enumerate(stages, 1):
            if blocked and stage_id != "STAGE_08_PIPELINE_SUMMARY":
                result = StageResult(
                    stage_id,
                    stage_name,
                    status="BLOCKED",
                    skipped_reason="previous_required_stage_failed",
                    message="Blocked because an earlier required stage failed.",
                )
            else:
                result = self._execute_stage(idx, len(stages), stage_id, stage_name, func)
            self.stage_results.append(result)
            self._print_stage(idx, len(stages), result)
            if result.status == "FAILED" and stage_id != "STAGE_08_PIPELINE_SUMMARY":
                blocked = True
        summary = self._build_summary()
        self._write_outputs(summary)
        return summary

    def _execute_stage(
        self,
        index: int,
        total: int,
        stage_id: str,
        stage_name: str,
        func: Callable[[], StageResult],
    ) -> StageResult:
        result = StageResult(stage_id, stage_name, status="RUNNING")
        result.started_at = datetime.now().isoformat(timespec="seconds")
        start = datetime.now()
        try:
            result = func()
            result.stage_id = stage_id
            result.stage_name = stage_name
            result.started_at = result.started_at or datetime.now().isoformat(timespec="seconds")
            if not result.status or result.status == "RUNNING":
                result.status = "SUCCESS"
        except Exception as exc:  # fail-safe logging
            result.status = "FAILED"
            result.errors.append(str(exc))
            result.errors.append(traceback.format_exc())
        result.started_at = result.started_at or start.isoformat(timespec="seconds")
        result.completed_at = datetime.now().isoformat(timespec="seconds")
        result.duration_seconds = (datetime.now() - start).total_seconds()
        for warning in result.warnings:
            self.pipeline_warnings.append({"stage_id": stage_id, "warning": warning})
        for error in result.errors:
            self.pipeline_errors.append({"stage_id": stage_id, "error": error})
        return result

    def stage_input_discovery(self) -> StageResult:
        locator = RaceFileLocator()
        analysis = locator.find_analysis_pairs(ROOT / "data" / "analysis")
        results = locator.find_result_pairs(ROOT / "data" / "results")
        self.context["analysis"] = analysis
        self.context["results"] = results
        analysis_count = len(analysis.get("pairs", []))
        result_count = len(results.get("pairs", []))
        warnings = list(analysis.get("warnings", [])) + list(results.get("warnings", []))
        return StageResult(
            "STAGE_01_INPUT_DISCOVERY",
            "INPUT_DISCOVERY",
            status="SUCCESS_WITH_WARNINGS" if warnings else "SUCCESS",
            records_processed=analysis_count + result_count,
            warnings=warnings,
            message=f"analysis_pairs={analysis_count}, result_pairs={result_count}",
            command_or_function="RaceFileLocator.find_analysis_pairs/find_result_pairs",
        )

    def stage_complete_sets(self) -> StageResult:
        locator = RaceFileLocator()
        found = locator.find_complete_race_sets(ROOT / "data" / "analysis", ROOT / "data" / "results")
        rows = self._build_race_inventory(found)
        filtered = [row for row in rows if row["is_complete"] and self._matches_filter(row)]
        for row in rows:
            row["included_in_run"] = row["race_id"] in {item["race_id"] for item in filtered}
            if row["is_complete"] and not row["included_in_run"]:
                row["excluded_reason"] = "outside_requested_scope"
        self.race_inventory = rows
        self.context["complete_sets"] = filtered
        warnings = list(found.get("warnings", []))
        warnings.extend(
            f"incomplete:{row['race_id']}:{row['excluded_reason']}"
            for row in rows
            if not row["is_complete"]
        )
        status = "SUCCESS_WITH_WARNINGS" if warnings else "SUCCESS"
        if not filtered:
            status = "SKIPPED" if rows else "SUCCESS_WITH_WARNINGS"
            warnings.append("no_complete_race_sets_in_scope")
        return StageResult(
            "STAGE_02_COMPLETE_RACE_SET_VALIDATION",
            "COMPLETE_RACE_SET_VALIDATION",
            status=status,
            records_processed=len(filtered),
            warnings=warnings,
            message=f"complete_in_scope={len(filtered)}, inventory={len(rows)}",
            command_or_function="RaceFileLocator.find_complete_race_sets",
        )

    def stage_buy_monitoring(self) -> StageResult:
        if self.dry_run:
            return self._dry_stage("BUY_MONITORING", "dry_run")
        from review.buy_monitor import build_reports

        summary = build_reports()
        self.context["buy_monitor"] = summary
        outputs = self._existing_outputs(ROOT / "reports" / "buy_monitor")
        return StageResult(
            "STAGE_03_BUY_MONITORING",
            "BUY_MONITORING",
            status="SUCCESS",
            output_files=outputs,
            records_processed=int(summary.get("horse_count", summary.get("unseen_horse_count", 0)) or 0),
            message=f"BUY={summary.get('buy_count')}, FP={summary.get('fp')}, FN={summary.get('fn')}",
            command_or_function="review.buy_monitor.build_reports",
        )

    def stage_improvement_candidates(self) -> StageResult:
        if self.dry_run:
            return self._dry_stage("IMPROVEMENT_CANDIDATES", "dry_run")
        from learning.improvement_candidate_engine import ImprovementCandidateEngine

        result = ImprovementCandidateEngine().generate()
        self.context["improvement_candidates"] = result
        return StageResult(
            "STAGE_04_IMPROVEMENT_CANDIDATES",
            "IMPROVEMENT_CANDIDATES",
            status="SUCCESS_WITH_WARNINGS" if result.get("warnings") else "SUCCESS",
            output_files=self._existing_outputs(ROOT / "reports" / "improvement_candidates"),
            records_processed=int(result.get("candidate_count", 0) or 0),
            warnings=list(result.get("warnings", [])),
            message=f"candidates={result.get('candidate_count')}",
            command_or_function="ImprovementCandidateEngine.generate",
        )

    def stage_improvement_priority(self) -> StageResult:
        if self.dry_run:
            return self._dry_stage("IMPROVEMENT_PRIORITY", "dry_run")
        from learning.improvement_priority_manager import ImprovementPriorityManager

        result = ImprovementPriorityManager().run()
        self.context["improvement_priority"] = result
        return StageResult(
            "STAGE_05_IMPROVEMENT_PRIORITY",
            "IMPROVEMENT_PRIORITY",
            status="SUCCESS_WITH_WARNINGS" if result.get("warnings") else "SUCCESS",
            output_files=self._existing_outputs(ROOT / "reports" / "improvement_priority"),
            records_processed=int(result.get("candidate_count", 0) or 0),
            warnings=list(result.get("warnings", [])),
            message=f"priority={result.get('priority_counts')}, queue={result.get('shadow_queue_count')}",
            command_or_function="ImprovementPriorityManager.run",
        )

    def stage_shadow_validation(self) -> StageResult:
        if self.dry_run:
            return self._dry_stage("SHADOW_VALIDATION", "dry_run")
        if self.skip_shadow:
            return self._dry_stage("SHADOW_VALIDATION", "--skip-shadow")

        # Avoid regressing a validation-complete project back to implementation.
        summary_path = ROOT / "reports" / "shadow_validation" / "summary.json"
        projects_path = ROOT / "reports" / "shadow_validation" / "shadow_projects.json"
        summary = self._read_json(summary_path)
        projects = self._read_json(projects_path).get("projects", [])
        validation_complete = any(
            p.get("project_id") == "SHADOW_BUY_FALSE_POSITIVE_RC1_V1"
            and p.get("project_status") == "VALIDATION_COMPLETE"
            for p in projects
        )
        if not validation_complete:
            from learning.shadow_validation_manager import ShadowValidationManager

            summary = ShadowValidationManager().run()
            message = f"shadow_projects={summary.get('project_count')}"
            command = "ShadowValidationManager.run"
        else:
            summary = self._shadow_validation_summary_from_projects(projects)
            message = "validation-complete project reused; manager not rerun"
            command = "read reports/shadow_validation"
        self.context["shadow_validation"] = summary
        return StageResult(
            "STAGE_06_SHADOW_VALIDATION",
            "SHADOW_VALIDATION",
            status="SUCCESS",
            output_files=self._existing_outputs(ROOT / "reports" / "shadow_validation"),
            records_processed=int(summary.get("project_count", len(projects)) or 0),
            message=message,
            command_or_function=command,
        )

    def _shadow_validation_summary_from_projects(self, projects: list[dict[str, Any]]) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        approval_counts: dict[str, int] = {}
        for project in projects:
            status = str(project.get("project_status", ""))
            approval = str(project.get("approval_status", ""))
            status_counts[status] = status_counts.get(status, 0) + 1
            approval_counts[approval] = approval_counts.get(approval, 0) + 1
        approved = [p.get("project_id", "") for p in projects if p.get("approval_status") == "APPROVED"]
        pending = [p.get("project_id", "") for p in projects if p.get("approval_status") == "PENDING"]
        return {
            "project_count": len(projects),
            "repository_count": len(projects),
            "status_counts": status_counts,
            "approval_counts": approval_counts,
            "approved_projects": approved,
            "pending_projects": pending,
            "next_shadow_project": approved[0] if approved else "",
            "warnings": [],
            "buy_diff": 0,
            "score_diff": 0,
            "decision_diff": 0,
            "source": "shadow_projects.json",
        }

    def stage_shadow_fp_filter(self) -> StageResult:
        if self.dry_run:
            return self._dry_stage("SHADOW_FP_FILTER", "dry_run")
        if self.skip_shadow:
            return self._dry_stage("SHADOW_FP_FILTER", "--skip-shadow")
        if not self.enable_shadow_fp_filter and not os.getenv("SHADOW_BUY_FP_FILTER_V1_ENABLED"):
            # The validator itself is shadow-only, but keep the stage explicit.
            message = "shadow flag off; existing shadow report summarized"
            summary = self._read_json(ROOT / "reports" / "shadow_buy_fp_filter" / "summary.json")
            status = "SUCCESS_WITH_WARNINGS" if summary.get("warnings") else "SUCCESS"
            return StageResult(
                "STAGE_07_SHADOW_FP_FILTER",
                "SHADOW_FP_FILTER",
                status=status,
                output_files=self._existing_outputs(ROOT / "reports" / "shadow_buy_fp_filter"),
                records_processed=int(summary.get("horse_count", 0) or 0),
                warnings=["shadow_flag_off_existing_report_used"],
                message=message,
                command_or_function="read reports/shadow_buy_fp_filter",
            )

        if self.from_date or self.to_date:
            from review.unseen_shadow_fp_validator import run_validation

            result = run_validation(from_date=self.from_date or "", to_date=self.to_date or "")
        else:
            from review.shadow_buy_fp_filter_validator import run_validation

            result = run_validation()
        summary = result.get("result_summary", {})
        warnings = list(summary.get("warnings", []))
        self.context["shadow_fp_filter"] = summary
        return StageResult(
            "STAGE_07_SHADOW_FP_FILTER",
            "SHADOW_FP_FILTER",
            status="SUCCESS_WITH_WARNINGS" if warnings else "SUCCESS",
            output_files=self._existing_outputs(ROOT / "reports" / "shadow_buy_fp_filter"),
            records_processed=int(summary.get("horse_count", 0) or 0),
            warnings=warnings,
            message=f"final={summary.get('final_decision')}, removed_fp={summary.get('removed_fp')}",
            command_or_function="review.unseen_shadow_fp_validator.run_validation"
            if self.from_date or self.to_date
            else "review.shadow_buy_fp_filter_validator.run_validation",
        )

    def stage_pipeline_summary(self) -> StageResult:
        return StageResult(
            "STAGE_08_PIPELINE_SUMMARY",
            "PIPELINE_SUMMARY",
            status="SUCCESS",
            records_processed=len(self.stage_results),
            message="Pipeline summary generated.",
            command_or_function="ReviewPipeline._write_outputs",
        )

    def run_validators(self) -> dict[str, Any]:
        validators = [
            ("improvement_candidate", "review.improvement_candidate_validator", "run_validation"),
            ("improvement_priority", "review.improvement_priority_validator", "run_validation"),
            ("shadow_validation", "review.shadow_validation_manager_validator", "run_validation"),
            ("shadow_fp_filter", "review.shadow_buy_fp_filter_validator", "run_validation"),
        ]
        results = {}
        for name, module_name, function_name in validators:
            try:
                module = __import__(module_name, fromlist=[function_name])
                results[name] = getattr(module, function_name)()
            except Exception as exc:
                results[name] = {"status": "FAILED", "error": str(exc), "traceback": traceback.format_exc()}
                self.pipeline_errors.append({"stage_id": "VALIDATOR", "error": f"{name}: {exc}"})
        return results

    def _dry_stage(self, stage_name: str, reason: str) -> StageResult:
        return StageResult(
            "",
            stage_name,
            status="SKIPPED",
            skipped_reason=reason,
            message=f"{stage_name} skipped ({reason}).",
        )

    def _build_race_inventory(self, found: dict[str, Any]) -> list[dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for item in found.get("complete_sets", []):
            parsed = RaceFileLocator().parse_filename(Path(item.get("entry_path", "")).name) or {}
            rows[item["race_id"]] = {
                "race_id": item["race_id"],
                "race_date": parsed.get("race_date", ""),
                "racecourse": parsed.get("racecourse", ""),
                "race_number": parsed.get("race_number", ""),
                "analysis_entry_exists": bool(item.get("entry_path")),
                "analysis_horses_exists": bool(item.get("horses_path")),
                "result_race_exists": bool(item.get("race_result_path")),
                "result_horses_exists": bool(item.get("horse_result_path")),
                "is_complete": True,
                "included_in_run": False,
                "excluded_reason": "",
                "analysis_entry_path": item.get("entry_path", ""),
                "analysis_horses_path": item.get("horses_path", ""),
                "result_race_path": item.get("race_result_path", ""),
                "result_horses_path": item.get("horse_result_path", ""),
            }
        for bucket, reason in [("analysis_only", "missing_results"), ("results_only", "missing_analysis")]:
            for item in found.get(bucket, []):
                parsed = RaceFileLocator().parse_filename(
                    Path(item.get("entry_path") or item.get("race_result_path") or "").name
                ) or {}
                race_id = item.get("race_id", "")
                rows[race_id] = {
                    "race_id": race_id,
                    "race_date": parsed.get("race_date", ""),
                    "racecourse": parsed.get("racecourse", ""),
                    "race_number": parsed.get("race_number", ""),
                    "analysis_entry_exists": bool(item.get("entry_path")),
                    "analysis_horses_exists": bool(item.get("horses_path")),
                    "result_race_exists": bool(item.get("race_result_path")),
                    "result_horses_exists": bool(item.get("horse_result_path")),
                    "is_complete": False,
                    "included_in_run": False,
                    "excluded_reason": reason,
                    "analysis_entry_path": item.get("entry_path", ""),
                    "analysis_horses_path": item.get("horses_path", ""),
                    "result_race_path": item.get("race_result_path", ""),
                    "result_horses_path": item.get("horse_result_path", ""),
                }
        return [rows[key] for key in sorted(rows)]

    def _matches_filter(self, row: dict[str, Any]) -> bool:
        race_id = str(row.get("race_id", ""))
        race_date = str(row.get("race_date", ""))
        if self.race_id and race_id != self.race_id:
            return False
        if self.date and race_date != self.date:
            return False
        if self.from_date and race_date < self.from_date:
            return False
        if self.to_date and race_date > self.to_date:
            return False
        return True

    def _print_stage(self, idx: int, total: int, result: StageResult) -> None:
        label = result.stage_name.replace("_", " ").title()
        extra = f" ({result.records_processed})" if result.records_processed else ""
        print(f"[{idx}/{total}] {label:<32} {result.status}{extra}")

    def _build_summary(self) -> dict[str, Any]:
        counts = {status: sum(1 for r in self.stage_results if r.status == status) for status in [
            "SUCCESS",
            "SUCCESS_WITH_WARNINGS",
            "SKIPPED",
            "FAILED",
            "BLOCKED",
        ]}
        if self.dry_run:
            final_status = "DRY_RUN_COMPLETE"
        elif not self.context.get("complete_sets"):
            final_status = "NO_DATA"
        elif counts["FAILED"]:
            final_status = "FAILED"
        elif counts["BLOCKED"]:
            final_status = "PARTIAL_SUCCESS"
        elif counts["SUCCESS_WITH_WARNINGS"] or counts["SKIPPED"]:
            final_status = "SUCCESS_WITH_WARNINGS"
        else:
            final_status = "SUCCESS"

        buy_monitor = self.context.get("buy_monitor") or self._read_json(ROOT / "reports" / "buy_monitor" / "summary.json")
        candidates = self.context.get("improvement_candidates") or self._read_json(ROOT / "reports" / "improvement_candidates" / "summary.json")
        priority = self.context.get("improvement_priority") or self._read_json(ROOT / "reports" / "improvement_priority" / "priority_summary.json")
        shadow_validation = self.context.get("shadow_validation") or self._read_json(ROOT / "reports" / "shadow_validation" / "summary.json")
        shadow_fp = self.context.get("shadow_fp_filter") or self._read_json(ROOT / "reports" / "shadow_buy_fp_filter" / "summary.json")
        return {
            "pipeline_run_id": self.run_id,
            "started_at": self.stage_results[0].started_at if self.stage_results else "",
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "dry_run" if self.dry_run else "normal",
            "date": self.date,
            "from_date": self.from_date,
            "to_date": self.to_date,
            "race_id": self.race_id,
            "target_race_count": len([r for r in self.race_inventory if r.get("included_in_run")]),
            "complete_race_set_count": len([r for r in self.race_inventory if r.get("is_complete")]),
            "incomplete_race_count": len([r for r in self.race_inventory if not r.get("is_complete")]),
            "stage_counts": counts,
            "pipeline_status": final_status,
            "buy_monitor": buy_monitor or "NOT_AVAILABLE",
            "improvement_candidates": candidates or "NOT_AVAILABLE",
            "improvement_priority": priority or "NOT_AVAILABLE",
            "shadow_validation": shadow_validation or "NOT_AVAILABLE",
            "shadow_fp_filter": shadow_fp or "NOT_AVAILABLE",
            "warning_count": len(self.pipeline_warnings),
            "error_count": len(self.pipeline_errors),
            "generated_files": [item["file_path"] for item in self.output_inventory],
        }

    def _write_outputs(self, summary: dict[str, Any]) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        self._refresh_output_inventory()
        summary["generated_files"] = [item["file_path"] for item in self.output_inventory]
        self._write_json_file(self.run_dir / "pipeline_summary.json", summary)
        self._write_json_file(REPORT_DIR / "latest_pipeline_summary.json", summary)
        self._write_csv(self.run_dir / "stage_results.csv", [r.to_row() for r in self.stage_results])
        self._write_csv(REPORT_DIR / "latest_stage_results.csv", [r.to_row() for r in self.stage_results])
        self._write_csv(self.run_dir / "race_inventory.csv", self.race_inventory)
        self._write_csv(REPORT_DIR / "latest_race_inventory.csv", self.race_inventory)
        self._write_csv(self.run_dir / "output_inventory.csv", self.output_inventory)
        self._write_csv(REPORT_DIR / "latest_output_inventory.csv", self.output_inventory)
        self._write_csv(self.run_dir / "warnings.csv", self.pipeline_warnings)
        self._write_csv(REPORT_DIR / "latest_warnings.csv", self.pipeline_warnings)
        self._write_csv(self.run_dir / "errors.csv", self.pipeline_errors)
        self._write_csv(REPORT_DIR / "latest_errors.csv", self.pipeline_errors)
        md = self._summary_md(summary)
        (self.run_dir / "pipeline_summary.md").write_text(md, encoding="utf-8")
        (REPORT_DIR / "latest_pipeline_summary.md").write_text(md, encoding="utf-8")
        with (REPORT_DIR / "pipeline_history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n")
        (self.run_dir / "pipeline.log").write_text(
            "\n".join(f"{r.stage_id} {r.status} {r.message}" for r in self.stage_results) + "\n",
            encoding="utf-8",
        )

    def _refresh_output_inventory(self) -> None:
        roots = [
            ROOT / "reports" / "buy_monitor",
            ROOT / "reports" / "improvement_candidates",
            ROOT / "reports" / "improvement_priority",
            ROOT / "reports" / "shadow_validation",
            ROOT / "reports" / "shadow_buy_fp_filter",
        ]
        rows = []
        for report_root in roots:
            if not report_root.exists():
                continue
            for path in sorted(report_root.rglob("*")):
                if not path.is_file():
                    continue
                stage_id = self._stage_for_output(path)
                stat = path.stat()
                rows.append(
                    {
                        "stage_id": stage_id,
                        "output_type": path.suffix.lstrip(".") or "file",
                        "file_path": str(path.relative_to(ROOT)),
                        "exists": True,
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                        "source_run_id": self.run_id,
                    }
                )
        self.output_inventory = rows

    def _stage_for_output(self, path: Path) -> str:
        text = str(path)
        if "buy_monitor" in text:
            return "STAGE_03_BUY_MONITORING"
        if "improvement_candidates" in text:
            return "STAGE_04_IMPROVEMENT_CANDIDATES"
        if "improvement_priority" in text:
            return "STAGE_05_IMPROVEMENT_PRIORITY"
        if "shadow_validation" in text:
            return "STAGE_06_SHADOW_VALIDATION"
        if "shadow_buy_fp_filter" in text:
            return "STAGE_07_SHADOW_FP_FILTER"
        return "UNKNOWN"

    def _summary_md(self, summary: dict[str, Any]) -> str:
        lines = [
            "# Review Pipeline v1.0",
            "",
            f"- Pipeline Run ID: {summary['pipeline_run_id']}",
            f"- Mode: {summary['mode']}",
            f"- Pipeline Status: {summary['pipeline_status']}",
            f"- Target Race Count: {summary['target_race_count']}",
            f"- Complete Race Sets: {summary['complete_race_set_count']}",
            f"- Incomplete Race Sets: {summary['incomplete_race_count']}",
            f"- Warnings: {summary['warning_count']}",
            f"- Errors: {summary['error_count']}",
            "",
            "## Stages",
        ]
        for result in self.stage_results:
            lines.append(f"- {result.stage_id}: {result.status} ({result.message})")
        lines.extend(["", "## BUY Monitoring"])
        buy = summary.get("buy_monitor")
        if isinstance(buy, dict):
            lines.extend(
                [
                    f"- BUY: {buy.get('buy_count')}",
                    f"- FN: {buy.get('fn')}",
                    f"- FP: {buy.get('fp')}",
                ]
            )
        else:
            lines.append("- NOT_AVAILABLE")
        lines.extend(["", "## Improvement Priority"])
        priority = summary.get("improvement_priority")
        if isinstance(priority, dict):
            lines.append(f"- Priority Counts: {priority.get('priority_counts')}")
            lines.append(f"- Shadow Queue: {priority.get('shadow_queue_count')}")
        else:
            lines.append("- NOT_AVAILABLE")
        lines.extend(["", "## Shadow FP Filter"])
        shadow_fp = summary.get("shadow_fp_filter")
        if isinstance(shadow_fp, dict):
            lines.append(f"- Final: {shadow_fp.get('final_decision')}")
            lines.append(f"- Removed FP: {shadow_fp.get('removed_fp')}")
            lines.append(f"- Reason: {shadow_fp.get('final_reason')}")
        else:
            lines.append("- NOT_AVAILABLE")
        lines.extend(["", "## Generated Files"])
        lines.extend(f"- {path}" for path in summary.get("generated_files", []))
        return "\n".join(lines) + "\n"

    @staticmethod
    def _existing_outputs(path: Path) -> list[str]:
        if not path.exists():
            return []
        return [str(p.relative_to(ROOT)) for p in sorted(path.rglob("*")) if p.is_file()]

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _write_json_file(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fields: list[str] = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KeibaAI Review Pipeline v1.0")
    parser.add_argument("--date", default="")
    parser.add_argument("--from-date", default="")
    parser.add_argument("--to-date", default="")
    parser.add_argument("--race-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--with-validators", action="store_true")
    parser.add_argument("--skip-shadow", action="store_true")
    parser.add_argument("--enable-shadow-fp-filter", action="store_true")
    parser.add_argument("--run-id", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    pipeline = ReviewPipeline(
        date=args.date,
        from_date=args.from_date,
        to_date=args.to_date,
        race_id=args.race_id,
        dry_run=args.dry_run,
        with_validators=args.with_validators,
        skip_shadow=args.skip_shadow,
        enable_shadow_fp_filter=args.enable_shadow_fp_filter,
        run_id=args.run_id,
    )
    summary = pipeline.run()
    validator_results = {}
    if args.with_validators and not args.dry_run:
        validator_results = pipeline.run_validators()
        summary["validator_results"] = validator_results
        pipeline._write_outputs(summary)
    print(f"Final: {summary['pipeline_status']}")
    print(f"Run ID: {summary['pipeline_run_id']}")
    return summary


if __name__ == "__main__":
    main()
