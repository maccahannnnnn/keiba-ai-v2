"""Priority4 Shadow readiness review for UNCONVERGED improvement.

Review-layer only. This script reads existing Priority4 review artifacts and
summarizes whether the current guard candidates are ready to proceed to Shadow.
It never calls Production adapters and never writes Learning, Shadow Project,
Knowledge, score, BUY, or Decision state.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Priority4ShadowReadinessReview:
    """Build latest-only guard comparison and Shadow readiness artifacts."""

    VERSION = "priority4_shadow_readiness_review_v1"
    GUARD_NAME_MAP = {
        "NO_GUARD_REFERENCE": "NO_GUARD",
        "ADJUSTED_GAP_GUARD": "ADJUSTED_GAP",
        "COMPOSITE_GAP_GUARD": "COMPOSITE_MARGIN",
        "CLUSTER_DENSITY_GUARD": "CLUSTER_DENSITY",
        "MULTI_SIGNAL_SEPARATION_GUARD": "MULTI_SIGNAL",
    }
    GO_RULES = {
        "fn_improvement_min": 1,
        "roi_min": 0,
        "fp_increase_max": 1,
        "explainability_min": "HIGH",
        "rollback_ease_required": "HIGH",
        "feature_flag_fit_required": "HIGH",
    }

    def __init__(
        self,
        root: Path | str = Path("."),
        guard_comparison_path: Path | str = "reports/guard_comparison_v1.csv",
        latest_simulation_path: Path | str = "reports/latest_only_simulation_v1.csv",
        output_dir: Path | str = "reports",
    ) -> None:
        self.root = Path(root)
        self.guard_comparison_path = self.root / Path(guard_comparison_path)
        self.latest_simulation_path = self.root / Path(latest_simulation_path)
        self.output_dir = self.root / Path(output_dir)

    def run(self) -> dict[str, Any]:
        guard_rows = self._read_csv(self.guard_comparison_path)
        latest_rows = self._read_csv(self.latest_simulation_path)
        latest_guard_rows = [row for row in guard_rows if row.get("cohort") == "LATEST"]
        comparison = [self._normalize_guard_row(row) for row in latest_guard_rows]
        comparison.sort(key=lambda row: (row["roi"], row["fn_improvement"], -row["fp_increase"]), reverse=True)
        latest_summary = self._latest_summary(comparison, latest_rows)
        candidate = self._candidate(comparison, latest_summary)
        report = self._report(comparison, latest_summary, candidate)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_csv(self.output_dir / "priority4_guard_comparison_v2.csv", comparison)
        self._write_json(self.output_dir / "priority4_latest_only_summary_v2.json", latest_summary)
        self._write_json(self.output_dir / "priority4_shadow_candidate_v1.json", candidate)
        (self.output_dir / "priority4_shadow_readiness_v1.md").write_text(report, encoding="utf-8")
        return candidate

    def _normalize_guard_row(self, row: dict[str, Any]) -> dict[str, Any]:
        canonical = self.GUARD_NAME_MAP.get(row.get("guard_name"), row.get("guard_name"))
        fn = self._to_int(row.get("fn_improvement")) or 0
        fp = self._to_int(row.get("fp_increase")) or 0
        roi = self._to_int(row.get("roi"))
        if roi is None:
            roi = fn - fp
        explainability = row.get("explainability") or "UNKNOWN"
        implementation = row.get("implementation_difficulty") or "UNKNOWN"
        safety = row.get("production_safety") or "UNKNOWN"
        return {
            "guard": canonical,
            "source_guard_name": row.get("guard_name"),
            "cohort": "LATEST",
            "race_count": self._to_int(row.get("race_count")) or 0,
            "horse_count": self._to_int(row.get("horse_count")) or 0,
            "selected_races": self._to_int(row.get("selected_races")) or 0,
            "guard_blocked_races": self._to_int(row.get("guard_blocked_races")) or 0,
            "selected_count": self._to_int(row.get("selected_count")) or 0,
            "fn_improvement": fn,
            "fp_increase": fp,
            "roi": roi,
            "top3_rate": self._to_float(row.get("top3_rate")),
            "top5_rate": self._to_float(row.get("top5_rate")),
            "explainability": explainability,
            "rollback_ease": "HIGH" if implementation in {"LOW", "MEDIUM"} else "MEDIUM",
            "feature_flag_fit": "HIGH",
            "implementation_difficulty": implementation,
            "production_safety": safety,
            "go_condition_result": self._go_result(fn, fp, roi, explainability, implementation),
            "go_blockers": ";".join(self._go_blockers(fn, fp, roi, explainability, implementation)),
            "description": row.get("description") or "",
        }

    def _go_result(self, fn: int, fp: int, roi: int, explainability: str, implementation: str) -> str:
        return "PASS" if not self._go_blockers(fn, fp, roi, explainability, implementation) else "FAIL"

    def _go_blockers(self, fn: int, fp: int, roi: int, explainability: str, implementation: str) -> list[str]:
        blockers = []
        if fn < self.GO_RULES["fn_improvement_min"]:
            blockers.append("FN_IMPROVEMENT_BELOW_MIN")
        if roi < self.GO_RULES["roi_min"]:
            blockers.append("ROI_BELOW_ZERO")
        if fp > self.GO_RULES["fp_increase_max"]:
            blockers.append("FP_INCREASE_ABOVE_1")
        if explainability != "HIGH":
            blockers.append("EXPLAINABILITY_BELOW_HIGH")
        if implementation not in {"LOW", "MEDIUM"}:
            blockers.append("ROLLBACK_EASE_BELOW_HIGH")
        return blockers

    def _latest_summary(self, comparison: list[dict[str, Any]], latest_rows: list[dict[str, Any]]) -> dict[str, Any]:
        race_ids = sorted({row.get("race_id") for row in latest_rows if row.get("race_id")})
        horse_count = sum(self._to_int(row.get("candidate_count")) or 0 for row in self._dedupe_by_race(latest_rows).values())
        best = comparison[0] if comparison else {}
        return {
            "status": "REVIEW_COMPLETE",
            "version": self.VERSION,
            "cohort": "LATEST",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "race_count": len(race_ids) or (best.get("race_count") or 0),
            "horse_count": horse_count or (best.get("horse_count") or 0),
            "race_ids": race_ids,
            "guard_count": len(comparison),
            "best_guard_by_roi": best.get("guard"),
            "best_guard_roi": best.get("roi"),
            "best_guard_fn_improvement": best.get("fn_improvement"),
            "best_guard_fp_increase": best.get("fp_increase"),
            "go_rules": self.GO_RULES,
            "past_cohort_excluded": True,
            "combined_reference_excluded": True,
            "production_changed": False,
            "learning_changed": False,
            "shadow_project_changed": False,
            "knowledge_changed": False,
            "target_trial_adapter_run_executed": False,
            "main_py_executed": False,
        }

    def _candidate(self, comparison: list[dict[str, Any]], latest_summary: dict[str, Any]) -> dict[str, Any]:
        passing = [row for row in comparison if row.get("go_condition_result") == "PASS"]
        if passing:
            decision = "Shadow GO"
            selected = passing[0]
            reason = "At least one existing guard satisfies all latest-only Shadow GO conditions."
        else:
            selected = comparison[0] if comparison else {}
            if selected and (selected.get("fn_improvement") or 0) > 0:
                decision = "HOLD"
                reason = "Latest-only FN improvement exists, but ROI/FP guard conditions are not yet acceptable."
            else:
                decision = "REJECT"
                reason = "No existing guard shows latest-only FN improvement."
        return {
            "status": "REVIEW_COMPLETE",
            "version": self.VERSION,
            "final_judgment": decision,
            "selected_guard": selected.get("guard"),
            "selected_source_guard_name": selected.get("source_guard_name"),
            "reason": reason,
            "latest_only": latest_summary,
            "selected_metrics": selected,
            "shadow_implementation_allowed": False,
            "production_changed": False,
            "learning_changed": False,
            "shadow_project_changed": False,
            "knowledge_changed": False,
            "target_trial_adapter_run_executed": False,
            "main_py_executed": False,
        }

    def _report(
        self,
        comparison: list[dict[str, Any]],
        latest_summary: dict[str, Any],
        candidate: dict[str, Any],
    ) -> str:
        lines = [
            "# Priority4 Shadow Readiness Final Review v1",
            "",
            "## Scope",
            "",
            "- LATEST cohort only.",
            "- PAST and Combined are excluded from readiness judgment.",
            "- Existing guards only; no new guard was added.",
            "- Review Layer only; Production / BUY / Decision / Score were not changed.",
            "",
            "## LATEST Summary",
            "",
            f"- Race count: {latest_summary.get('race_count')}",
            f"- Horse count: {latest_summary.get('horse_count')}",
            f"- Best guard by ROI: {latest_summary.get('best_guard_by_roi')}",
            f"- Best guard FN improvement: {latest_summary.get('best_guard_fn_improvement')}",
            f"- Best guard FP increase: {latest_summary.get('best_guard_fp_increase')}",
            f"- Best guard ROI: {latest_summary.get('best_guard_roi')}",
            "",
            "## Guard Comparison",
            "",
            "| Guard | FN改善 | FP増加 | ROI | Selected | Explain | Rollback | FeatureFlag | GO | Blockers |",
            "|---|---:|---:|---:|---:|---|---|---|---|---|",
        ]
        for row in comparison:
            lines.append(
                f"| {row.get('guard')} | {row.get('fn_improvement')} | {row.get('fp_increase')} | "
                f"{row.get('roi')} | {row.get('selected_count')} | {row.get('explainability')} | "
                f"{row.get('rollback_ease')} | {row.get('feature_flag_fit')} | "
                f"{row.get('go_condition_result')} | {row.get('go_blockers')} |"
            )
        lines.extend(
            [
                "",
                "## Shadow GO Conditions",
                "",
                "- FN improvement >= 1",
                "- FP increase <= 1",
                "- ROI >= 0",
                "- Explainability HIGH",
                "- Rollback ease HIGH",
                "- Feature Flag fit HIGH",
                "",
                "## Final Judgment",
                "",
                f"**{candidate.get('final_judgment')}**",
                "",
                f"- Reason: {candidate.get('reason')}",
                "- Shadow implementation was not performed.",
                "",
                "## Safety",
                "",
                "- TargetTrialAdapter.run executed: false",
                "- main.py executed: false",
                "- Production changed: false",
                "- Learning changed: false",
                "- Shadow Project changed: false",
                "- Knowledge changed: false",
            ]
        )
        return "\n".join(lines) + "\n"

    def _dedupe_by_race(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result = {}
        for row in rows:
            race_id = row.get("race_id")
            if race_id and race_id not in result:
                result[race_id] = row
        return result

    def _read_csv(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

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

    def _to_int(self, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(float(str(value)))
        except ValueError:
            return None

    def _to_float(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value))
        except ValueError:
            return None


if __name__ == "__main__":
    result = Priority4ShadowReadinessReview().run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
