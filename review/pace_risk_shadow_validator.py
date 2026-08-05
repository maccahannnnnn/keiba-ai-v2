from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.risk_statistics_engine import DECISIONS, RiskStatisticsEngine


class PaceRiskShadowValidator:
    """Shadow-only validation for duplicated PACE risks.

    This validator never changes official Decision output.  It reads existing
    horse_review.csv files and estimates what would happen if the duplicate
    impact of "展開不向き" + "展開面の不安" were counted once.
    """

    OUTPUT_DIR = Path("reports/shadow")
    TARGET_RISKS = ("展開不向き", "展開面の不安")
    SHADOW_VERSION = "phase_h4_pace_risk_dedup_v1"

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.engine = RiskStatisticsEngine(base_dir=self.base_dir)

    def run(self) -> Dict[str, object]:
        input_files = self.engine.find_input_files()
        rows = self.engine.load_rows(input_files)
        output_dir = self.base_dir / self.OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        report_rows = [self._shadow_row(row) for row in rows]
        summary = self._summary(rows, report_rows)

        self._write_csv(output_dir / "pace_risk_shadow_report.csv", report_rows)
        self._write_summary(output_dir / "pace_risk_shadow_summary.md", input_files, summary)

        return {
            "input_files": [str(path) for path in input_files],
            "output_dir": str(output_dir),
            "summary": summary,
        }

    def _shadow_row(self, row: Mapping[str, str]) -> Dict[str, object]:
        reasons = self.engine.split_risk_reasons(row.get("risk_reasons"))
        target = all(risk in reasons for risk in self.TARGET_RISKS)
        original = self.engine.decision(row)
        shadow = self._shadow_decision(row, target)
        return {
            "race_id": row.get("race_id", ""),
            "racecourse": row.get("racecourse", ""),
            "race_number": row.get("race_number", ""),
            "horse_name": row.get("horse_name", ""),
            "horse_number": row.get("horse_number", ""),
            "ai_rank": row.get("ai_rank", ""),
            "final_score": row.get("final_score", ""),
            "adjusted_score": row.get("adjusted_score", ""),
            "actual_finish": row.get("actual_finish", ""),
            "actual_top3": self.engine.is_actual_top3(row),
            "actual_top5": self.engine.is_actual_top5(row),
            "original_decision": original,
            "shadow_decision": shadow,
            "decision_changed": original != shadow,
            "change_type": self._change_type(original, shadow),
            "target_duplicate_pace_risk": target,
            "risk_reasons": row.get("risk_reasons", ""),
            "shadow_rule": "count_展開不向き_and_展開面の不安_as_one_decision_impact" if target else "",
            "shadow_basis": self._shadow_basis(row, target),
            "shadow_version": self.SHADOW_VERSION,
        }

    def _shadow_decision(self, row: Mapping[str, str], target: bool) -> str:
        original = self.engine.decision(row)
        if not target:
            return original
        if original == "PASS" and self._near_boundary(row):
            return "CAUTION"
        if original == "CAUTION" and self._near_boundary(row):
            return "BUY"
        return original

    def _near_boundary(self, row: Mapping[str, str]) -> bool:
        # Diagnostic estimate only: horse_review.csv does not include decision_score.
        rank = self._to_int(row.get("ai_rank"))
        adjusted = self._to_float(row.get("adjusted_score"))
        final = self._to_float(row.get("final_score"))
        return rank <= 5 or adjusted >= 140.0 or final >= 135.0

    def _shadow_basis(self, row: Mapping[str, str], target: bool) -> str:
        if not target:
            return "not_target"
        if self._near_boundary(row):
            return "diagnostic_estimate_near_boundary_without_decision_score"
        return "duplicate_detected_but_not_near_boundary"

    def _summary(self, rows: List[Mapping[str, str]], report_rows: List[Mapping[str, object]]) -> Dict[str, object]:
        original_counts = Counter(row["original_decision"] for row in report_rows)
        shadow_counts = Counter(row["shadow_decision"] for row in report_rows)
        change_counts = Counter(row["change_type"] for row in report_rows if row["decision_changed"])
        target_rows = [row for row in report_rows if row["target_duplicate_pace_risk"]]
        changed_rows = [row for row in report_rows if row["decision_changed"]]
        race_ids = sorted({row.get("race_id", "") for row in rows if row.get("race_id")})
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "shadow_version": self.SHADOW_VERSION,
            "race_count": len(race_ids),
            "horse_count": len(report_rows),
            "race_ids": race_ids,
            "target_duplicate_count": len(target_rows),
            "decision_changed_count": len(changed_rows),
            "pass_to_caution": change_counts.get("PASS->CAUTION", 0),
            "caution_to_buy": change_counts.get("CAUTION->BUY", 0),
            "buy_to_other": sum(1 for row in changed_rows if row["original_decision"] == "BUY"),
            "original_counts": {decision: original_counts.get(decision, 0) for decision in DECISIONS},
            "shadow_counts": {decision: shadow_counts.get(decision, 0) for decision in DECISIONS},
            "original_result": self._decision_result_counts(report_rows, "original_decision"),
            "shadow_result": self._decision_result_counts(report_rows, "shadow_decision"),
            "target_top3": sum(1 for row in target_rows if row["actual_top3"]),
            "target_top5": sum(1 for row in target_rows if row["actual_top5"]),
            "changed_top3": sum(1 for row in changed_rows if row["actual_top3"]),
            "changed_top5": sum(1 for row in changed_rows if row["actual_top5"]),
            "input_note": "Shadow decisions are diagnostic estimates because horse_review.csv has no decision_score.",
        }

    def _decision_result_counts(self, rows: Iterable[Mapping[str, object]], decision_key: str) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for decision in DECISIONS:
            scoped = [row for row in rows if row.get(decision_key) == decision]
            result[f"{decision}_count"] = len(scoped)
            result[f"{decision}_top3"] = sum(1 for row in scoped if row.get("actual_top3"))
            result[f"{decision}_top5"] = sum(1 for row in scoped if row.get("actual_top5"))
        return result

    def _change_type(self, before: str, after: str) -> str:
        if before == after:
            return ""
        return f"{before}->{after}"

    def _to_int(self, value: str | None) -> int:
        try:
            return int(float(str(value or "").strip()))
        except ValueError:
            return 10**9

    def _to_float(self, value: str | None) -> float:
        try:
            return float(str(value or "").strip())
        except ValueError:
            return 0.0

    def _write_csv(self, path: Path, rows: List[Dict[str, object]]) -> None:
        fieldnames = list(rows[0].keys()) if rows else []
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _write_summary(self, path: Path, input_files: Iterable[Path], summary: Dict[str, object]) -> None:
        original = summary["original_counts"]
        shadow = summary["shadow_counts"]
        original_result = summary["original_result"]
        shadow_result = summary["shadow_result"]
        lines = [
            "# PACE Risk Shadow Validation Summary",
            "",
            f"generated_at: {summary['generated_at']}",
            f"shadow_version: {summary['shadow_version']}",
            "",
            "## Input",
            "",
            f"- review_csv_files: {len(list(input_files))}",
            f"- races: {summary['race_count']}",
            f"- horses: {summary['horse_count']}",
            f"- note: {summary['input_note']}",
            "",
            "## Shadow Rule",
            "",
            "- Target: same horse has both `展開不向き` and `展開面の不安`.",
            "- Shadow only: count duplicated PACE decision impact once.",
            "- Risk display remains unchanged.",
            "- Official Decision is not changed.",
            "",
            "## Target And Changes",
            "",
            f"- target_duplicate_count: {summary['target_duplicate_count']}",
            f"- decision_changed_count: {summary['decision_changed_count']}",
            f"- PASS->CAUTION: {summary['pass_to_caution']}",
            f"- CAUTION->BUY: {summary['caution_to_buy']}",
            f"- BUY changed: {summary['buy_to_other']}",
            f"- changed_top3: {summary['changed_top3']}",
            f"- changed_top5: {summary['changed_top5']}",
            "",
            "## Decision Counts",
            "",
            "| Decision | Original | Shadow | Delta |",
            "|---|---:|---:|---:|",
        ]
        for decision in DECISIONS:
            lines.append(f"| {decision} | {original[decision]} | {shadow[decision]} | {shadow[decision] - original[decision]} |")
        lines.extend(
            [
                "",
                "## Result Comparison",
                "",
                "| Decision | Original Top3 | Shadow Top3 | Original Top5 | Shadow Top5 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for decision in DECISIONS:
            lines.append(
                f"| {decision} | {original_result[f'{decision}_top3']} | {shadow_result[f'{decision}_top3']} | "
                f"{original_result[f'{decision}_top5']} | {shadow_result[f'{decision}_top5']} |"
            )
        lines.extend(["", "## Race IDs", ""])
        lines.extend(f"- {race_id}" for race_id in summary["race_ids"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def main() -> None:
    result = PaceRiskShadowValidator().run()
    summary = result["summary"]
    print("PACE Risk Shadow Validator completed")
    print(f"input_files={len(result['input_files'])}")
    print(f"races={summary['race_count']} horses={summary['horse_count']}")
    print(f"target_duplicate_count={summary['target_duplicate_count']}")
    print(f"decision_changed_count={summary['decision_changed_count']}")
    print(f"PASS->CAUTION={summary['pass_to_caution']} CAUTION->BUY={summary['caution_to_buy']}")
    print(f"output_dir={result['output_dir']}")


if __name__ == "__main__":
    main()
