from __future__ import annotations

import csv
import itertools
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.risk_statistics_engine import DECISIONS, RiskStatisticsEngine


class RiskDetailAnalyzer:
    """Create detailed risk wording and combination diagnostics."""

    OUTPUT_DIR = Path("reports/review_statistics")

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.engine = RiskStatisticsEngine(base_dir=self.base_dir)

    def run(self) -> Dict[str, object]:
        input_files = self.engine.find_input_files()
        rows = self.engine.load_rows(input_files)
        output_dir = self.base_dir / self.OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        detail_stats = self.aggregate_risk_details(rows)
        combination_stats = self.aggregate_risk_combinations(rows)
        pass_stats = self.aggregate_pass_reasons(rows)
        top5_pass_stats = self.aggregate_top5_pass_details(rows)
        review_required_stats = self.aggregate_review_required(rows)
        summary = self.engine.summarize_overall(rows)

        self._write_csv(output_dir / "risk_detail_statistics.csv", detail_stats)
        self._write_csv(output_dir / "risk_combination_statistics.csv", combination_stats)
        self._write_csv(output_dir / "pass_reason_statistics.csv", pass_stats)
        self._write_csv(output_dir / "top5_pass_detail_statistics.csv", top5_pass_stats)
        self._write_csv(output_dir / "review_required_statistics.csv", review_required_stats)
        self._write_summary(
            output_dir / "summary.md",
            input_files,
            summary,
            detail_stats,
            combination_stats,
            pass_stats,
            top5_pass_stats,
            review_required_stats,
        )

        return {
            "input_files": [str(path) for path in input_files],
            "summary": summary,
            "detail_count": len(detail_stats),
            "combination_count": len(combination_stats),
            "pass_reason_count": len(pass_stats),
            "top5_pass_reason_count": len(top5_pass_stats),
            "review_required_reason_count": len(review_required_stats),
            "output_dir": str(output_dir),
        }

    def aggregate_risk_details(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        return self._aggregate_reasons(rows)

    def aggregate_pass_reasons(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        return self._aggregate_reasons(row for row in rows if self.engine.decision(row) == "PASS")

    def aggregate_top5_pass_details(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        return self._aggregate_reasons(
            row for row in rows if self.engine.is_top5(row) and self.engine.decision(row) == "PASS"
        )

    def aggregate_review_required(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        return self._aggregate_reasons(row for row in rows if self._is_review_required(row))

    def aggregate_risk_combinations(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        stats: Dict[str, Dict[str, object]] = {}
        for row in rows:
            reasons = sorted(set(self.engine.split_risk_reasons(row.get("risk_reasons"))))
            reasons = [reason for reason in reasons if reason != "NO_RISK_REASON"]
            if len(reasons) < 2:
                continue
            for left, right in itertools.combinations(reasons, 2):
                key = f"{left} + {right}"
                if key not in stats:
                    stats[key] = self._new_stat(
                        risk_combination=key,
                        risk_category_combination=(
                            f"{self.engine.categorize_reason(left)} + {self.engine.categorize_reason(right)}"
                        ),
                    )
                self._add_row(stats[key], row)
        return self._finalize(stats.values(), primary_key="risk_combination")

    def _aggregate_reasons(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        stats: Dict[str, Dict[str, object]] = {}
        for row in rows:
            for reason in sorted(set(self.engine.split_risk_reasons(row.get("risk_reasons")))):
                if reason not in stats:
                    stats[reason] = self._new_stat(
                        risk_reason=reason,
                        risk_category=self.engine.categorize_reason(reason),
                        input_limitation_category=(
                            self.engine.categorize_input_limitation(reason)
                            if self.engine.categorize_reason(reason) == "INPUT_LIMITATION"
                            else ""
                        ),
                    )
                self._add_row(stats[reason], row)
        return self._finalize(stats.values(), primary_key="risk_reason")

    def _new_stat(self, **labels: object) -> Dict[str, object]:
        stat: Dict[str, object] = {
            "risk_reason": "",
            "risk_category": "",
            "input_limitation_category": "",
            "risk_combination": "",
            "risk_category_combination": "",
            "count": 0,
            "BUY": 0,
            "CAUTION": 0,
            "PASS": 0,
            "top5_count": 0,
            "non_top5_count": 0,
            "actual_top3": 0,
            "actual_top5": 0,
            "top5_actual_top3": 0,
            "top5_actual_top5": 0,
        }
        stat.update(labels)
        return stat

    def _add_row(self, stat: Dict[str, object], row: Mapping[str, str]) -> None:
        stat["count"] = int(stat["count"]) + 1
        decision = self.engine.decision(row)
        if decision in DECISIONS:
            stat[decision] = int(stat[decision]) + 1
        top5 = self.engine.is_top5(row)
        if top5:
            stat["top5_count"] = int(stat["top5_count"]) + 1
        else:
            stat["non_top5_count"] = int(stat["non_top5_count"]) + 1
        if self.engine.is_actual_top3(row):
            stat["actual_top3"] = int(stat["actual_top3"]) + 1
            if top5:
                stat["top5_actual_top3"] = int(stat["top5_actual_top3"]) + 1
        if self.engine.is_actual_top5(row):
            stat["actual_top5"] = int(stat["actual_top5"]) + 1
            if top5:
                stat["top5_actual_top5"] = int(stat["top5_actual_top5"]) + 1

    def _finalize(self, stats: Iterable[Dict[str, object]], primary_key: str) -> List[Dict[str, object]]:
        rows = []
        for stat in stats:
            count = int(stat["count"])
            top5_count = int(stat["top5_count"])
            stat["buy_rate"] = self._rate(int(stat["BUY"]), count)
            stat["caution_rate"] = self._rate(int(stat["CAUTION"]), count)
            stat["pass_rate"] = self._rate(int(stat["PASS"]), count)
            stat["show_rate"] = self._rate(int(stat["actual_top3"]), count)
            stat["top5_rate"] = self._rate(int(stat["actual_top5"]), count)
            stat["top5_show_rate"] = self._rate(int(stat["top5_actual_top3"]), top5_count)
            rows.append(stat)
        return sorted(rows, key=lambda item: (-int(item["count"]), str(item.get(primary_key, ""))))

    def _rate(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator, 4)

    def _is_review_required(self, row: Mapping[str, str]) -> bool:
        fields = (
            row.get("review_classification", ""),
            row.get("root_cause_candidates", ""),
            row.get("review_comment", ""),
            row.get("status", ""),
            row.get("candidate_status", ""),
        )
        return any("REVIEW_REQUIRED" in str(value).upper() for value in fields)

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
            "risk_combination",
            "risk_category_combination",
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
        detail_stats: List[Dict[str, object]],
        combination_stats: List[Dict[str, object]],
        pass_stats: List[Dict[str, object]],
        top5_pass_stats: List[Dict[str, object]],
        review_required_stats: List[Dict[str, object]],
    ) -> None:
        input_file_list = list(input_files)
        lines = [
            "# Risk Detail Analyzer Summary",
            "",
            f"generated_at: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Input",
            "",
            f"- review_csv_files: {len(input_file_list)}",
            f"- races: {summary['race_count']}",
            f"- horses: {summary['horse_count']}",
            "",
            "Note: this analyzer reads `reports/review_*/horse_review.csv`. Statistics reflect only detected files.",
            "",
            "## Decision Overview",
            "",
            "| Decision | Count |",
            "|---|---:|",
            f"| BUY | {summary['BUY']} |",
            f"| CAUTION | {summary['CAUTION']} |",
            f"| PASS | {summary['PASS']} |",
            "",
            "## Top Risk Wording",
            "",
            self._markdown_table(detail_stats[:10], "risk_reason"),
            "",
            "## PASS Reason Ranking",
            "",
            self._markdown_table(pass_stats[:10], "risk_reason"),
            "",
            "## Top5 PASS Detail",
            "",
            self._markdown_table(top5_pass_stats[:10], "risk_reason"),
            "",
            "## Risk Combination Ranking",
            "",
            self._markdown_table(combination_stats[:10], "risk_combination"),
            "",
            "## REVIEW_REQUIRED Risk Ranking",
            "",
            self._markdown_table(review_required_stats[:10], "risk_reason"),
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
            "| Risk | Category | Count | BUY | CAUTION | PASS | PASS Rate | Top3 | Top3 Rate | Top5 | Top5 Rate |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in rows:
            label = row.get(label_key) or row.get("risk_reason") or row.get("risk_combination") or ""
            category = row.get("risk_category") or row.get("risk_category_combination") or ""
            lines.append(
                f"| {label} | {category} | {row['count']} | {row['BUY']} | {row['CAUTION']} | {row['PASS']} | "
                f"{float(row['pass_rate']) * 100:.1f}% | {row['actual_top3']} | {float(row['show_rate']) * 100:.1f}% | "
                f"{row['actual_top5']} | {float(row['top5_rate']) * 100:.1f}% |"
            )
        return "\n".join(lines)


def main() -> None:
    result = RiskDetailAnalyzer().run()
    summary = result["summary"]
    print("Risk Detail Analyzer completed")
    print(f"input_files={len(result['input_files'])}")
    print(f"races={summary['race_count']} horses={summary['horse_count']}")
    print(f"BUY={summary['BUY']} CAUTION={summary['CAUTION']} PASS={summary['PASS']}")
    print(f"risk_details={result['detail_count']} combinations={result['combination_count']}")
    print(f"output_dir={result['output_dir']}")


if __name__ == "__main__":
    main()
