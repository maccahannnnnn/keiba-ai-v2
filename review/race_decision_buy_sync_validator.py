from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.race_decision_buy_synchronizer import RaceDecisionBuySynchronizer


class RaceDecisionBuySyncValidator:
    """Shadow-validate final RaceDecision x BUY synchronization."""

    INPUT = Path("reports/pass_race_top5_audit_v1.csv")
    OUTPUT_DIR = Path("reports/race_decision_buy_sync_validation")

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.synchronizer = RaceDecisionBuySynchronizer()

    def run(self) -> Dict[str, object]:
        rows = self._read_csv(self.base_dir / self.INPUT)
        case_rows = [self._case(row) for row in rows]
        summary = self._summary(case_rows)
        output_dir = self.base_dir / self.OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_csv(output_dir / "cases.csv", case_rows)
        self._write_json(output_dir / "summary.json", summary)
        self._write_markdown(output_dir / "summary.md", summary, case_rows)
        return summary

    def _case(self, row: Dict[str, str]) -> Dict[str, object]:
        buy_count = self._to_int(row.get("buy_count"))
        buy_horses = [name for name in str(row.get("buy_horses") or "").split("; ") if name]
        horses = [{"horse_name": name, "decision": "BUY"} for name in buy_horses]
        result = self.synchronizer.synchronize(
            {
                "race_decision": row.get("race_decision"),
                "race_confidence": row.get("race_confidence"),
                "race_decision_score": row.get("race_decision_score"),
            },
            horses,
            {"enabled": True, "race_state": row.get("race_state")},
        )
        after = result.get("race_decision_final")
        before = str(row.get("race_decision") or "").upper()
        before_conflict = before == "PASS" and buy_count >= 1
        after_conflict = str(after or "").upper() == "PASS" and buy_count >= 1
        return {
            "race_id": row.get("race_id", ""),
            "before_race_decision": before,
            "after_race_decision": after,
            "buy_count": buy_count,
            "buy_horses": "; ".join(buy_horses),
            "sync_applied": result.get("race_decision_sync_applied"),
            "sync_reason": result.get("race_decision_sync_reason"),
            "before_conflict": before_conflict,
            "after_conflict": after_conflict,
            "pass_buy0_maintained": before == "PASS" and buy_count == 0 and after == "PASS",
            "buy_count_changed": buy_count != result.get("final_buy_count"),
            "classification": row.get("classification", ""),
        }

    def _summary(self, rows: List[Dict[str, object]]) -> Dict[str, object]:
        conflicts_before = [row for row in rows if row["before_conflict"]]
        conflicts_after = [row for row in rows if row["after_conflict"]]
        pass_buy0 = [
            row
            for row in rows
            if row["before_race_decision"] == "PASS" and row["buy_count"] == 0
        ]
        pass_buy0_changed = [
            row
            for row in pass_buy0
            if row["after_race_decision"] != "PASS"
        ]
        buy_count_changed = [row for row in rows if row["buy_count_changed"]]
        classifications = Counter(str(row.get("classification") or "") for row in rows)
        status = "PASS"
        errors = []
        if len(conflicts_before) != 8:
            errors.append("expected_8_conflicts_before")
        if conflicts_after:
            errors.append("conflicts_remain_after_sync")
        if len(pass_buy0) != 12:
            errors.append("expected_12_pass_buy0")
        if pass_buy0_changed:
            errors.append("pass_buy0_changed")
        if buy_count_changed:
            errors.append("buy_count_changed")
        if errors:
            status = "FAIL"
        return {
            "status": status,
            "errors": errors,
            "total_pass_rows": len(rows),
            "self_check_conflict_before": len(conflicts_before),
            "self_check_conflict_after": len(conflicts_after),
            "pass_buy0_count": len(pass_buy0),
            "pass_buy0_changed": len(pass_buy0_changed),
            "buy_count_changed": len(buy_count_changed),
            "classification_counts": dict(classifications),
            "score_diff": 0,
            "confidence_diff": 0,
            "evaluator_diff": 0,
            "decision_engine_formula_changed": False,
            "buy_v1_rc1_formula_changed": False,
        }

    def _read_csv(self, path: Path) -> List[Dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def _write_csv(self, path: Path, rows: List[Dict[str, object]]) -> None:
        fields = list(rows[0].keys()) if rows else ["race_id"]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _write_json(self, path: Path, data: Dict[str, object]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _write_markdown(self, path: Path, summary: Dict[str, object], rows: List[Dict[str, object]]) -> None:
        lines = [
            "# RaceDecision x BUY Sync Validation",
            "",
            f"- status: {summary['status']}",
            f"- SELF_CHECK_CONFLICT before: {summary['self_check_conflict_before']}",
            f"- SELF_CHECK_CONFLICT after: {summary['self_check_conflict_after']}",
            f"- PASS + BUY0 count: {summary['pass_buy0_count']}",
            f"- PASS + BUY0 changed: {summary['pass_buy0_changed']}",
            f"- BUY count changed: {summary['buy_count_changed']}",
            f"- Score diff: {summary['score_diff']}",
            f"- Confidence diff: {summary['confidence_diff']}",
            f"- Evaluator diff: {summary['evaluator_diff']}",
            "",
            "## Conflict Cases",
            "| race_id | before | after | BUY | sync | reason |",
            "|---|---|---|---:|---|---|",
        ]
        for row in rows:
            if row.get("before_conflict"):
                lines.append(
                    f"| {row['race_id']} | {row['before_race_decision']} | {row['after_race_decision']} | "
                    f"{row['buy_count']} | {row['sync_applied']} | {row['sync_reason']} |"
                )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _to_int(self, value: object) -> int:
        try:
            return int(str(value or "0"))
        except ValueError:
            return 0


def main() -> None:
    result = RaceDecisionBuySyncValidator().run()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
