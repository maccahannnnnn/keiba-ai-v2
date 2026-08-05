from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.risk_statistics_engine import DECISIONS, RiskStatisticsEngine


class RiskAttributionAnalyzer:
    """Audit risk source attribution and same-system double counting."""

    OUTPUT_DIR = Path("reports/review_statistics")

    FOCUS_RISKS = {
        "展開不向き",
        "展開面の不安",
        "構造評価に必要な情報が不足しているため中立",
        "コース形状とのズレ",
        "コース形状と噛み合わない",
    }

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.engine = RiskStatisticsEngine(base_dir=self.base_dir)

    def run(self) -> Dict[str, object]:
        input_files = self.engine.find_input_files()
        rows = self.engine.load_rows(input_files)
        output_dir = self.base_dir / self.OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        attribution = self.aggregate_attribution(rows)
        double_counting = self.aggregate_double_counting(rows)
        counterfactual = self.aggregate_counterfactual(rows)
        impact_ranking = self.aggregate_impact_ranking(rows)
        summary = self.engine.summarize_overall(rows)

        self._write_csv(output_dir / "risk_attribution_statistics.csv", attribution)
        self._write_csv(output_dir / "double_counting_statistics.csv", double_counting)
        self._write_csv(output_dir / "counterfactual_statistics.csv", counterfactual)
        self._write_csv(output_dir / "risk_impact_ranking.csv", impact_ranking)
        self._write_summary(output_dir / "summary.md", input_files, summary, attribution, double_counting, counterfactual, impact_ranking)

        return {
            "input_files": [str(path) for path in input_files],
            "summary": summary,
            "attribution_count": len(attribution),
            "double_counting_count": len(double_counting),
            "counterfactual_count": len(counterfactual),
            "impact_ranking_count": len(impact_ranking),
            "output_dir": str(output_dir),
        }

    def aggregate_attribution(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        stats: Dict[Tuple[str, str, str], Dict[str, object]] = {}
        for row in rows:
            for reason in sorted(set(self.engine.split_risk_reasons(row.get("risk_reasons")))):
                source = self.infer_source(reason, row)
                key = (reason, source["engine"], source["evaluator"])
                if key not in stats:
                    stats[key] = self._new_stat(
                        risk_reason=reason,
                        risk_category=self.engine.categorize_reason(reason),
                        source_engine=source["engine"],
                        source_evaluator=source["evaluator"],
                        attribution_basis=source["basis"],
                        focus_risk=reason in self.FOCUS_RISKS,
                    )
                self._add_row(stats[key], row)
        return self._finalize(stats.values(), primary_key="risk_reason")

    def aggregate_double_counting(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        stats: Dict[Tuple[str, str, str], Dict[str, object]] = {}
        for row in rows:
            grouped = self._group_reasons_by_system(row)
            for system, reasons in grouped.items():
                count = len(reasons)
                if count <= 0:
                    continue
                bucket = str(count) if count < 4 else "4+"
                joined = " + ".join(sorted(reasons))
                key = (system, bucket, joined)
                if key not in stats:
                    stats[key] = self._new_stat(
                        risk_system=system,
                        same_system_risk_count=bucket,
                        same_system_risks=joined,
                    )
                self._add_row(stats[key], row)
        return self._finalize(stats.values(), primary_key="risk_system")

    def aggregate_counterfactual(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        stats: Dict[Tuple[str, str], Dict[str, object]] = {}
        for row in rows:
            grouped = self._group_reasons_by_system(row)
            decision = self.engine.decision(row)
            for system, reasons in grouped.items():
                if len(reasons) < 2:
                    continue
                key = (system, self._counterfactual_removed_reason(reasons))
                if key not in stats:
                    stats[key] = self._new_stat(
                        risk_system=system,
                        hypothetical_removed_risk=key[1],
                        counterfactual_basis="DIAGNOSTIC_ESTIMATE_FROM_SAME_SYSTEM_DUPLICATION",
                    )
                    stats[key]["estimated_pass_to_caution"] = 0
                    stats[key]["estimated_caution_to_buy"] = 0
                    stats[key]["estimated_buy_unchanged"] = 0
                self._add_row(stats[key], row)
                if decision == "PASS" and self._near_boundary(row):
                    stats[key]["estimated_pass_to_caution"] = int(stats[key]["estimated_pass_to_caution"]) + 1
                elif decision == "CAUTION" and self._near_boundary(row):
                    stats[key]["estimated_caution_to_buy"] = int(stats[key]["estimated_caution_to_buy"]) + 1
                elif decision == "BUY":
                    stats[key]["estimated_buy_unchanged"] = int(stats[key]["estimated_buy_unchanged"]) + 1
        return self._finalize(stats.values(), primary_key="risk_system")

    def aggregate_impact_ranking(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        attribution = self.aggregate_attribution(rows)
        for item in attribution:
            item["pass_impact_count"] = item["PASS"]
            item["caution_impact_count"] = item["CAUTION"]
            item["buy_impact_count"] = item["BUY"]
            item["impact_score"] = int(item["PASS"]) * 3 + int(item["CAUTION"]) * 2 + int(item["BUY"])
        return sorted(attribution, key=lambda item: (-int(item["impact_score"]), -int(item["PASS"]), str(item["risk_reason"])))

    def infer_source(self, reason: str, row: Mapping[str, str] | None = None) -> Dict[str, str]:
        value = reason.lower()
        if "展開不向き" in reason:
            return self._source("RaceShapeEngine", "RaceShapeEvaluator", "INFERRED_FROM_REVIEW_TEXT")
        if "展開面の不安" in reason:
            return self._source("PaceEngine", "PaceStyleEvaluator", "INFERRED_FROM_REVIEW_TEXT")
        if "想定ラップ" in reason or "ラップ適性" in reason:
            return self._source("LapEngine", "LapSuitabilityEvaluator", "INFERRED_FROM_REVIEW_TEXT")
        if "バイアス" in reason or "馬場" in reason or "track" in value:
            return self._source("TrackBiasEngine", "TrackBiasEvaluator", "INFERRED_FROM_REVIEW_TEXT")
        if "構造評価" in reason or "入力データ" in reason or "情報" in reason:
            return self._source("RaceShapeEngine", "RaceShapeEvaluator", "INFERRED_FROM_INPUT_LIMITATION_TEXT")
        if "コース形状" in reason or "コース" in reason or "course" in value:
            return self._source("CourseEngine", "CourseShapeEvaluator", "INFERRED_FROM_REVIEW_TEXT")
        if "距離" in reason or "distance" in value:
            return self._source("DistanceEngine", "DistanceEvaluator", "INFERRED_FROM_REVIEW_TEXT")
        if "decision" in value:
            return self._source("DecisionEngine", "DecisionEngine", "INFERRED_FROM_REVIEW_TEXT")
        if "racedecision" in value:
            return self._source("RaceDecisionEngine", "RaceDecisionEngine", "INFERRED_FROM_REVIEW_TEXT")
        if "weakmatches" in value:
            return self._source("ReviewEngine", "ReviewEngine", "INFERRED_FROM_REVIEW_TEXT")
        return self._source("UnknownEngine", "UnknownEvaluator", "UNKNOWN")

    def _source(self, engine: str, evaluator: str, basis: str) -> Dict[str, str]:
        return {"engine": engine, "evaluator": evaluator, "basis": basis}

    def _group_reasons_by_system(self, row: Mapping[str, str]) -> Dict[str, List[str]]:
        grouped: Dict[str, List[str]] = {}
        for reason in sorted(set(self.engine.split_risk_reasons(row.get("risk_reasons")))):
            if reason == "NO_RISK_REASON":
                continue
            system = self._system_for_reason(reason)
            grouped.setdefault(system, []).append(reason)
        return grouped

    def _system_for_reason(self, reason: str) -> str:
        category = self.engine.categorize_reason(reason)
        if category == "PACE_RISK":
            return "PACE_SYSTEM"
        if category == "COURSE_RISK":
            return "COURSE_SYSTEM"
        if category == "INPUT_LIMITATION":
            return "INPUT_SYSTEM"
        if category == "TRACK_RISK":
            return "TRACK_SYSTEM"
        if category == "DISTANCE_RISK":
            return "DISTANCE_SYSTEM"
        if category == "DECISION_RISK":
            return "DECISION_SYSTEM"
        return "OTHER_SYSTEM"

    def _counterfactual_removed_reason(self, reasons: Sequence[str]) -> str:
        preferred = sorted(reasons, key=lambda reason: (-self._risk_severity(reason), reason))
        return preferred[0] if preferred else ""

    def _risk_severity(self, reason: str) -> int:
        if reason in {"展開不向き", "展開面の不安", "コース形状とのズレ", "コース形状と噛み合わない"}:
            return 3
        if "構造評価" in reason or "想定ラップ" in reason:
            return 2
        return 1

    def _near_boundary(self, row: Mapping[str, str]) -> bool:
        rank = self._to_int(row.get("ai_rank"))
        adjusted = self._to_float(row.get("adjusted_score"))
        final = self._to_float(row.get("final_score"))
        return rank <= 5 or adjusted >= 140.0 or final >= 135.0

    def _new_stat(self, **labels: object) -> Dict[str, object]:
        stat: Dict[str, object] = {
            "risk_reason": "",
            "risk_category": "",
            "source_engine": "",
            "source_evaluator": "",
            "attribution_basis": "",
            "focus_risk": False,
            "risk_system": "",
            "same_system_risk_count": "",
            "same_system_risks": "",
            "hypothetical_removed_risk": "",
            "counterfactual_basis": "",
            "count": 0,
            "BUY": 0,
            "CAUTION": 0,
            "PASS": 0,
            "top5_count": 0,
            "actual_top3": 0,
            "actual_top5": 0,
        }
        stat.update(labels)
        return stat

    def _add_row(self, stat: Dict[str, object], row: Mapping[str, str]) -> None:
        stat["count"] = int(stat["count"]) + 1
        decision = self.engine.decision(row)
        if decision in DECISIONS:
            stat[decision] = int(stat[decision]) + 1
        if self.engine.is_top5(row):
            stat["top5_count"] = int(stat["top5_count"]) + 1
        if self.engine.is_actual_top3(row):
            stat["actual_top3"] = int(stat["actual_top3"]) + 1
        if self.engine.is_actual_top5(row):
            stat["actual_top5"] = int(stat["actual_top5"]) + 1

    def _finalize(self, stats: Iterable[Dict[str, object]], primary_key: str) -> List[Dict[str, object]]:
        rows = []
        for stat in stats:
            count = int(stat["count"])
            stat["buy_rate"] = self._rate(int(stat["BUY"]), count)
            stat["caution_rate"] = self._rate(int(stat["CAUTION"]), count)
            stat["pass_rate"] = self._rate(int(stat["PASS"]), count)
            stat["show_rate"] = self._rate(int(stat["actual_top3"]), count)
            stat["top5_rate"] = self._rate(int(stat["actual_top5"]), count)
            rows.append(stat)
        return sorted(rows, key=lambda item: (-int(item["count"]), str(item.get(primary_key, ""))))

    def _rate(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator, 4)

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
            "source_engine",
            "source_evaluator",
            "attribution_basis",
            "focus_risk",
            "risk_system",
            "same_system_risk_count",
            "same_system_risks",
            "hypothetical_removed_risk",
            "counterfactual_basis",
            "count",
            "BUY",
            "CAUTION",
            "PASS",
            "pass_impact_count",
            "caution_impact_count",
            "buy_impact_count",
            "impact_score",
            "estimated_pass_to_caution",
            "estimated_caution_to_buy",
            "estimated_buy_unchanged",
            "buy_rate",
            "caution_rate",
            "pass_rate",
            "top5_count",
            "actual_top3",
            "actual_top5",
            "show_rate",
            "top5_rate",
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
        attribution: List[Dict[str, object]],
        double_counting: List[Dict[str, object]],
        counterfactual: List[Dict[str, object]],
        impact_ranking: List[Dict[str, object]],
    ) -> None:
        input_file_list = list(input_files)
        lines = [
            "# Risk Attribution / Double Counting Audit Summary",
            "",
            f"generated_at: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Input",
            "",
            f"- review_csv_files: {len(input_file_list)}",
            f"- races: {summary['race_count']}",
            f"- horses: {summary['horse_count']}",
            "",
            "Note: attribution is inferred from review risk wording because the current horse_review.csv does not include source trace IDs or decision_score.",
            "",
            "## Decision Overview",
            "",
            "| Decision | Count |",
            "|---|---:|",
            f"| BUY | {summary['BUY']} |",
            f"| CAUTION | {summary['CAUTION']} |",
            f"| PASS | {summary['PASS']} |",
            "",
            "## Focus Risk Attribution",
            "",
            self._markdown_table([row for row in attribution if row.get("focus_risk")], "risk_reason"),
            "",
            "## Double Counting Buckets",
            "",
            self._markdown_table(double_counting[:12], "same_system_risks"),
            "",
            "## Counterfactual Estimates",
            "",
            self._counterfactual_table(counterfactual),
            "",
            "## Risk Impact Ranking",
            "",
            self._impact_table(impact_ranking[:12]),
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
            "| Risk | Source | Count | BUY | CAUTION | PASS | PASS Rate | Top3 | Top3 Rate | Top5 | Top5 Rate |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in rows:
            label = row.get(label_key) or row.get("risk_reason") or row.get("same_system_risks") or ""
            source = row.get("source_evaluator") or row.get("risk_system") or row.get("source_engine") or ""
            lines.append(
                f"| {label} | {source} | {row['count']} | {row['BUY']} | {row['CAUTION']} | {row['PASS']} | "
                f"{float(row['pass_rate']) * 100:.1f}% | {row['actual_top3']} | {float(row['show_rate']) * 100:.1f}% | "
                f"{row['actual_top5']} | {float(row['top5_rate']) * 100:.1f}% |"
            )
        return "\n".join(lines)

    def _counterfactual_table(self, rows: List[Dict[str, object]]) -> str:
        if not rows:
            return "_No rows._"
        lines = [
            "| System | Removed Risk | Count | Estimated PASS->CAUTION | Estimated CAUTION->BUY | Basis |",
            "|---|---|---:|---:|---:|---|",
        ]
        for row in rows:
            lines.append(
                f"| {row['risk_system']} | {row['hypothetical_removed_risk']} | {row['count']} | "
                f"{row.get('estimated_pass_to_caution', 0)} | {row.get('estimated_caution_to_buy', 0)} | "
                f"{row.get('counterfactual_basis', '')} |"
            )
        return "\n".join(lines)

    def _impact_table(self, rows: List[Dict[str, object]]) -> str:
        if not rows:
            return "_No rows._"
        lines = [
            "| Risk | Source | PASS Impact | CAUTION Impact | BUY Impact | Impact Score |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for row in rows:
            lines.append(
                f"| {row['risk_reason']} | {row['source_evaluator']} | {row['pass_impact_count']} | "
                f"{row['caution_impact_count']} | {row['buy_impact_count']} | {row['impact_score']} |"
            )
        return "\n".join(lines)


def main() -> None:
    result = RiskAttributionAnalyzer().run()
    summary = result["summary"]
    print("Risk Attribution Analyzer completed")
    print(f"input_files={len(result['input_files'])}")
    print(f"races={summary['race_count']} horses={summary['horse_count']}")
    print(f"BUY={summary['BUY']} CAUTION={summary['CAUTION']} PASS={summary['PASS']}")
    print(
        f"attribution={result['attribution_count']} "
        f"double_counting={result['double_counting_count']} "
        f"counterfactual={result['counterfactual_count']}"
    )
    print(f"output_dir={result['output_dir']}")


if __name__ == "__main__":
    main()
