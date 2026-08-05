from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.target_trial_adapter import TargetTrialAdapter
from review.risk_statistics_engine import RiskStatisticsEngine


class ReviewTraceRecorderValidation:
    """Generate a non-legacy validation CSV for ReviewRecorder trace columns."""

    OUTPUT_CSV = Path("reports/review_statistics/review_trace_recorder_validation.csv")
    OUTPUT_MD = Path("reports/review_statistics/review_trace_recorder_validation.md")

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.adapter = TargetTrialAdapter()
        self.risk_engine = RiskStatisticsEngine(base_dir=self.base_dir)

    def run(self, entry_csv_path: str | Path | None = None) -> Dict[str, object]:
        entry_path = Path(entry_csv_path) if entry_csv_path else self._default_entry_path()
        history_path = self._history_path(entry_path)
        result = self.adapter.run(entry_path, history_path)
        race_output = result.get("race_output", {}) if isinstance(result, dict) else {}
        review_record = race_output.get("review_record", {}) if isinstance(race_output, dict) else {}
        rows = self._rows(review_record, race_output)

        output_csv = self.base_dir / self.OUTPUT_CSV
        output_md = self.base_dir / self.OUTPUT_MD
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        self._write_csv(output_csv, rows)

        legacy_files = self.risk_engine.find_input_files()
        legacy_rows = self.risk_engine.load_rows(legacy_files)
        new_rows = self.risk_engine.load_rows([output_csv])
        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entry_csv": str(entry_path),
            "history_csv": str(history_path),
            "validation_csv": str(output_csv),
            "validation_rows": len(rows),
            "official_decision_filled": sum(1 for row in rows if row.get("official_decision") not in (None, "")),
            "decision_score_filled": sum(1 for row in rows if row.get("decision_score") not in (None, "")),
            "risk_trace_filled": sum(1 for row in rows if row.get("risk_trace") not in (None, "")),
            "legacy_review_files_readable": len(legacy_files),
            "legacy_rows_readable": len(legacy_rows),
            "new_rows_readable": len(new_rows),
            "old_new_compatible": bool(legacy_rows) and len(new_rows) == len(rows),
        }
        self._write_summary(output_md, summary)
        return summary

    def _rows(self, review_record: Mapping[str, object], race_output: Mapping[str, object]) -> List[Dict[str, object]]:
        recorder = self.adapter.review_recorder
        race = review_record.get("race") if isinstance(review_record.get("race"), dict) else {}
        race_context = {
            "race_id": race_output.get("race_id", ""),
            "racecourse": self._nested(race_output, ["race_structure", "racecourse"]),
            "race_number": "",
        }
        race_context.update({key: value for key, value in race.items() if key not in race_context})
        horses = review_record.get("horses") if isinstance(review_record.get("horses"), list) else []
        return [recorder.horse_review_row(horse, race_context=race_context) for horse in horses]

    def _default_entry_path(self) -> Path:
        candidates = sorted((self.base_dir / "data/analysis").glob("race_20260725*_entry.csv"))
        if not candidates:
            raise FileNotFoundError("No 20260725 entry CSV found under data/analysis.")
        return candidates[0]

    def _history_path(self, entry_path: Path) -> Path:
        text = str(entry_path)
        candidate = Path(text.replace("_entry.csv", "_horses.csv"))
        if not candidate.exists():
            raise FileNotFoundError(f"History CSV not found for {entry_path}")
        return candidate

    def _write_csv(self, path: Path, rows: List[Dict[str, object]]) -> None:
        fieldnames = list(rows[0].keys()) if rows else []
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _write_summary(self, path: Path, summary: Mapping[str, object]) -> None:
        lines = [
            "# Review Trace Recorder Validation",
            "",
            f"generated_at: {summary['generated_at']}",
            f"entry_csv: {summary['entry_csv']}",
            f"history_csv: {summary['history_csv']}",
            f"validation_csv: {summary['validation_csv']}",
            "",
            "## Trace Columns",
            "",
            f"- validation_rows: {summary['validation_rows']}",
            f"- official_decision_filled: {summary['official_decision_filled']}",
            f"- decision_score_filled: {summary['decision_score_filled']}",
            f"- risk_trace_filled: {summary['risk_trace_filled']}",
            "",
            "## Compatibility",
            "",
            f"- legacy_review_files_readable: {summary['legacy_review_files_readable']}",
            f"- legacy_rows_readable: {summary['legacy_rows_readable']}",
            f"- new_rows_readable: {summary['new_rows_readable']}",
            f"- old_new_compatible: {summary['old_new_compatible']}",
            "",
            "Note: validation output is stored outside `reports/review_*/horse_review.csv` to avoid overwriting legacy reviews.",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _nested(self, item: Mapping[str, object], keys: List[str]) -> object:
        current: object = item
        for key in keys:
            if not isinstance(current, dict):
                return ""
            current = current.get(key, "")
        return current


if __name__ == "__main__":
    print(ReviewTraceRecorderValidation().run())
