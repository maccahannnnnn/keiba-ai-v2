from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.input_limitation_analyzer import InputLimitationAnalyzer
from review.risk_statistics_engine import RiskStatisticsEngine


class DecisionThresholdAnalyzer:
    """Generate diagnostic statistics for decision threshold review."""

    OUTPUT_DIR = Path("reports/review_statistics")

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.engine = RiskStatisticsEngine(base_dir=self.base_dir)
        self.input_analyzer = InputLimitationAnalyzer(base_dir=self.base_dir)

    def run(self) -> Dict[str, object]:
        input_files = self.engine.find_input_files()
        rows = self.engine.load_rows(input_files)
        output_dir = self.base_dir / self.OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        reason_stats = self.engine.aggregate_by_reason(rows)
        category_stats = self.engine.aggregate_by_category(rows)
        top5_pass_stats = self.engine.aggregate_top5_pass(rows)
        input_limitation_stats = self.input_analyzer.analyze(rows)
        summary = self.engine.summarize_overall(rows)

        self._write_csv(output_dir / "decision_threshold_statistics.csv", reason_stats)
        self._write_csv(output_dir / "risk_statistics.csv", category_stats)
        self._write_csv(output_dir / "top5_pass_statistics.csv", top5_pass_stats)
        self._write_csv(output_dir / "input_limitation_statistics.csv", input_limitation_stats)
        self._write_summary(output_dir / "summary.md", input_files, summary, reason_stats, category_stats, top5_pass_stats, input_limitation_stats)

        return {
            "input_files": [str(path) for path in input_files],
            "output_dir": str(output_dir),
            "summary": summary,
            "reason_stats_count": len(reason_stats),
            "category_stats_count": len(category_stats),
            "top5_pass_stats_count": len(top5_pass_stats),
            "input_limitation_stats_count": len(input_limitation_stats),
        }

    def _write_csv(self, path: Path, rows: List[Dict[str, object]]) -> None:
        fieldnames = self._fieldnames(rows)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _fieldnames(self, rows: List[Dict[str, object]]) -> List[str]:
        preferred = [
            "risk_reason",
            "risk_category",
            "input_limitation_category",
            "count",
            "BUY",
            "CAUTION",
            "PASS",
            "buy_rate",
            "caution_rate",
            "pass_rate",
            "top5_count",
            "non_top5_count",
            "actual_top3",
            "actual_top5",
            "show_rate",
            "top5_rate",
            "top5_actual_top3",
            "top5_actual_top5",
            "top5_show_rate",
        ]
        keys = set()
        for row in rows:
            keys.update(row.keys())
        return [key for key in preferred if key in keys] + sorted(keys.difference(preferred))

    def _write_summary(
        self,
        path: Path,
        input_files: Iterable[Path],
        summary: Dict[str, object],
        reason_stats: List[Dict[str, object]],
        category_stats: List[Dict[str, object]],
        top5_pass_stats: List[Dict[str, object]],
        input_limitation_stats: List[Dict[str, object]],
    ) -> None:
        lines = [
            "# Decision Threshold / Risk Statistics Summary",
            "",
            f"generated_at: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Input",
            "",
            f"- review_csv_files: {len(list(input_files))}",
            f"- races: {summary['race_count']}",
            f"- horses: {summary['horse_count']}",
            "",
            "Note: this analyzer reads `reports/review_*/horse_review.csv`. If the intended 31-race set is not present in that pattern, the statistics reflect only the detected files.",
            "",
            "## Decision Overview",
            "",
            "| Decision | Count |",
            "|---|---:|",
            f"| BUY | {summary['BUY']} |",
            f"| CAUTION | {summary['CAUTION']} |",
            f"| PASS | {summary['PASS']} |",
            "",
            "## Top5 PASS",
            "",
            f"- top5_count: {summary['top5_count']}",
            f"- top5_pass_count: {summary['top5_pass_count']}",
            f"- top5_pass_actual_top3: {summary['top5_pass_actual_top3']}",
            f"- top5_pass_actual_top5: {summary['top5_pass_actual_top5']}",
            "",
            "## Risk Category Ranking",
            "",
            self._markdown_table(category_stats, "risk_category"),
            "",
            "## Top Risk Reasons",
            "",
            self._markdown_table(reason_stats[:10], "risk_reason"),
            "",
            "## Top5 PASS Risk Category",
            "",
            self._markdown_table(top5_pass_stats, "risk_category"),
            "",
            "## Input Limitation Breakdown",
            "",
            self._markdown_table(input_limitation_stats, "input_limitation_category"),
            "",
            "## Race IDs",
            "",
        ]
        lines.extend(f"- {race_id}" for race_id in summary["race_ids"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")

    def _markdown_table(self, rows: List[Dict[str, object]], label_key: str) -> str:
        if not rows:
            return "_No rows._"
        lines = [
            "| Category | Count | BUY | CAUTION | PASS | PASS Rate | Top3 | Top3 Rate | Top5 | Top5 Rate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in rows:
            label = row.get(label_key) or row.get("risk_category") or row.get("risk_reason") or row.get("input_limitation_category")
            lines.append(
                f"| {label} | {row['count']} | {row['BUY']} | {row['CAUTION']} | {row['PASS']} | "
                f"{float(row['pass_rate']) * 100:.1f}% | {row['actual_top3']} | {float(row['show_rate']) * 100:.1f}% | "
                f"{row['actual_top5']} | {float(row['top5_rate']) * 100:.1f}% |"
            )
        return "\n".join(lines)


def main() -> None:
    result = DecisionThresholdAnalyzer().run()
    summary = result["summary"]
    print("Decision Threshold Analyzer completed")
    print(f"input_files={len(result['input_files'])}")
    print(f"races={summary['race_count']} horses={summary['horse_count']}")
    print(f"BUY={summary['BUY']} CAUTION={summary['CAUTION']} PASS={summary['PASS']}")
    print(f"output_dir={result['output_dir']}")


if __name__ == "__main__":
    main()
