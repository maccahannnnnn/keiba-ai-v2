from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.decision_engine import DecisionEngine
from review.risk_attribution_analyzer import RiskAttributionAnalyzer
from review.risk_statistics_engine import DECISIONS, RiskStatisticsEngine


class DecisionScoreTrace:
    """Trace DecisionEngine diagnostics from review CSV inputs.

    The official review rows are never modified.  This tool recomputes
    DecisionEngine diagnostics from existing CSV fields and stores the result
    separately as trace output.
    """

    OUTPUT_DIR = Path("reports/review_statistics")
    BUY_THRESHOLD = 0.80
    CAUTION_THRESHOLD = 0.50
    TRACE_VERSION = "phase_h5_decision_score_trace_v1"

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.risk_engine = RiskStatisticsEngine(base_dir=self.base_dir)
        self.decision_engine = DecisionEngine()
        self.attribution = RiskAttributionAnalyzer(base_dir=self.base_dir)

    def run(self) -> Dict[str, object]:
        input_files = self.risk_engine.find_input_files()
        review_rows = self.risk_engine.load_rows(input_files)
        trace_rows = self._trace_rows(review_rows)
        summary = self._summary(trace_rows, review_rows, input_files)

        output_dir = self.base_dir / self.OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_csv(output_dir / "decision_score_trace.csv", trace_rows)
        self._write_summary(output_dir / "decision_score_summary.md", summary)

        return {
            "input_files": [str(path) for path in input_files],
            "output_dir": str(output_dir),
            "summary": summary,
        }

    def _trace_rows(self, review_rows: List[Mapping[str, str]]) -> List[Dict[str, object]]:
        trace_rows: List[Dict[str, object]] = []
        by_race: Dict[str, List[Dict[str, object]]] = defaultdict(list)
        for row in review_rows:
            item = self._decision_item(row)
            by_race[str(row.get("race_id") or "")].append(item)

        decision_by_key: Dict[tuple, Dict[str, object]] = {}
        for race_rows in by_race.values():
            results = self.decision_engine.decide_many(race_rows)
            for item, result in zip(race_rows, results):
                decision_by_key[(item.get("race_id"), item.get("horse_name"))] = result

        for row in review_rows:
            key = (row.get("race_id"), row.get("horse_name"))
            result = decision_by_key.get(key, {})
            trace_rows.append(self._trace_row(row, result))
        return trace_rows

    def _decision_item(self, row: Mapping[str, str]) -> Dict[str, object]:
        risk_reasons = self.risk_engine.split_risk_reasons(row.get("risk_reasons"))
        positive_reasons = self.risk_engine.split_risk_reasons(row.get("positive_reasons"))
        return {
            "race_id": row.get("race_id", ""),
            "horse_name": row.get("horse_name", ""),
            "horse_number": row.get("horse_number", ""),
            "final_score": self._to_float(row.get("final_score")),
            "adjusted_score": self._to_float(row.get("adjusted_score")),
            "rank": self._to_int(row.get("ai_rank")),
            "score_rank": self._to_int(row.get("ai_rank")),
            "confidence": row.get("confidence", ""),
            "final_strengths": positive_reasons,
            "strengths": positive_reasons,
            "final_risks": risk_reasons,
            "risk_factors": risk_reasons,
            "warnings": self._warnings_from_risks(risk_reasons),
            "final_summary": row.get("review_comment", ""),
            "explain_summary": row.get("risk_reasons", ""),
        }

    def _trace_row(self, row: Mapping[str, str], result: Mapping[str, object]) -> Dict[str, object]:
        official_decision = self.risk_engine.decision(row)
        trace_decision = str(result.get("decision") or "")
        decision_score = self._to_float(result.get("decision_score"))
        risk_items = self._list(result.get("risk_items"))
        decision_risks = self._list(result.get("decision_risks"))
        risk_score = self._to_float(result.get("risk_score"))
        conflict_score = self._to_float(result.get("conflict_score"))
        estimated_before_risk = self._estimate_before_risk(decision_score, risk_score, conflict_score)
        evaluator_impacts = self._evaluator_impacts(decision_risks or self.risk_engine.split_risk_reasons(row.get("risk_reasons")))
        per_risk_penalty = self._per_risk_penalties(decision_risks, risk_score)
        trace = result.get("decision_trace") if isinstance(result.get("decision_trace"), list) else []
        return {
            "race_id": row.get("race_id", ""),
            "racecourse": row.get("racecourse", ""),
            "race_number": row.get("race_number", ""),
            "horse_name": row.get("horse_name", ""),
            "horse_number": row.get("horse_number", ""),
            "ai_rank": row.get("ai_rank", ""),
            "final_score": row.get("final_score", ""),
            "adjusted_score": row.get("adjusted_score", ""),
            "official_decision": official_decision,
            "trace_decision": trace_decision,
            "trace_decision_matches_official": official_decision == trace_decision,
            "confidence": row.get("confidence", ""),
            "trace_confidence": result.get("confidence", ""),
            "decision_score": decision_score,
            "buy_threshold": self.BUY_THRESHOLD,
            "caution_threshold": self.CAUTION_THRESHOLD,
            "distance_to_buy": self._distance(self.BUY_THRESHOLD, decision_score),
            "distance_to_caution": self._distance(self.CAUTION_THRESHOLD, decision_score),
            "estimated_before_risk_score": estimated_before_risk,
            "estimated_after_risk_score": decision_score,
            "risk_score": risk_score,
            "risk_count": result.get("risk_count", 0),
            "risk_items": self._json(risk_items),
            "decision_risks": self._json(decision_risks),
            "risk_penalty_detail": self._json(per_risk_penalty),
            "conflict_score": conflict_score,
            "conflict_count": result.get("conflict_count", 0),
            "conflict_items": self._json(self._list(result.get("conflict_items"))),
            "decision_reason_detail": self._json(self._list(result.get("decision_reason_detail"))),
            "decision_trace": self._json(trace),
            "decision_diagnostic_text": result.get("decision_diagnostic_text", ""),
            "decision_influencing_evaluators": self._json(evaluator_impacts),
            "threshold_trace_basis": "recomputed_by_DecisionEngine_from_review_csv_fields",
            "per_risk_penalty_basis": "estimated_even_split_from_risk_score; exact per-risk penalty is not stored",
            "trace_version": self.TRACE_VERSION,
            "actual_finish": row.get("actual_finish", ""),
            "actual_top3": self.risk_engine.is_actual_top3(row),
            "actual_top5": self.risk_engine.is_actual_top5(row),
        }

    def _warnings_from_risks(self, risks: Iterable[str]) -> List[str]:
        return [risk for risk in risks if "warning" in str(risk).lower() or "warnings" in str(risk).lower()]

    def _evaluator_impacts(self, risks: Iterable[str]) -> List[Dict[str, object]]:
        impacts = []
        seen = set()
        for risk in risks:
            source = self.attribution.infer_source(str(risk))
            evaluator = source.get("evaluator") or "UnknownEvaluator"
            key = (evaluator, risk)
            if key in seen:
                continue
            seen.add(key)
            impacts.append(
                {
                    "risk": str(risk),
                    "source_engine": source.get("engine"),
                    "source_evaluator": evaluator,
                    "basis": source.get("basis"),
                }
            )
        return impacts

    def _per_risk_penalties(self, risks: List[str], risk_score: float | None) -> List[Dict[str, object]]:
        if not risks:
            return []
        score = risk_score if risk_score is not None else 0.0
        estimate = round(score / len(risks), 4) if risks else 0.0
        return [{"risk": risk, "estimated_penalty": estimate} for risk in risks]

    def _estimate_before_risk(self, decision_score: float | None, risk_score: float | None, conflict_score: float | None) -> float | None:
        if decision_score is None:
            return None
        return round(min(1.0, decision_score + (risk_score or 0.0) + (conflict_score or 0.0)), 4)

    def _summary(
        self,
        trace_rows: List[Mapping[str, object]],
        review_rows: List[Mapping[str, str]],
        input_files: Iterable[Path],
    ) -> Dict[str, object]:
        official = Counter(row.get("official_decision") for row in trace_rows)
        trace = Counter(row.get("trace_decision") for row in trace_rows)
        mismatches = [row for row in trace_rows if not row.get("trace_decision_matches_official")]
        scores = [row.get("decision_score") for row in trace_rows if row.get("decision_score") is not None]
        risk_scores = [row.get("risk_score") for row in trace_rows if row.get("risk_score") is not None]
        race_ids = sorted({row.get("race_id", "") for row in review_rows if row.get("race_id")})
        top_risks = Counter()
        top_evaluators = Counter()
        near_buy = 0
        for row in trace_rows:
            if 0 < float(row.get("distance_to_buy") or 0) <= 0.1:
                near_buy += 1
            for risk in json.loads(str(row.get("decision_risks") or "[]")):
                top_risks[str(risk)] += 1
            for item in json.loads(str(row.get("decision_influencing_evaluators") or "[]")):
                top_evaluators[str(item.get("source_evaluator"))] += 1
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "trace_version": self.TRACE_VERSION,
            "review_csv_files": len(list(input_files)),
            "race_count": len(race_ids),
            "horse_count": len(trace_rows),
            "race_ids": race_ids,
            "official_counts": {decision: official.get(decision, 0) for decision in DECISIONS},
            "trace_counts": {decision: trace.get(decision, 0) for decision in DECISIONS},
            "official_trace_mismatch_count": len(mismatches),
            "decision_score_available_count": len(scores),
            "decision_score_min": min(scores) if scores else None,
            "decision_score_max": max(scores) if scores else None,
            "decision_score_avg": round(sum(scores) / len(scores), 4) if scores else None,
            "risk_score_avg": round(sum(risk_scores) / len(risk_scores), 4) if risk_scores else None,
            "near_buy_boundary_count": near_buy,
            "top_risks": top_risks.most_common(10),
            "top_evaluators": top_evaluators.most_common(10),
            "note": "DecisionScore is recomputed for diagnostics; official CSV did not store decision_score.",
        }

    def _write_csv(self, path: Path, rows: List[Dict[str, object]]) -> None:
        fieldnames = list(rows[0].keys()) if rows else []
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _write_summary(self, path: Path, summary: Mapping[str, object]) -> None:
        lines = [
            "# Decision Score Trace Summary",
            "",
            f"generated_at: {summary['generated_at']}",
            f"trace_version: {summary['trace_version']}",
            "",
            "## Input",
            "",
            f"- review_csv_files: {summary['review_csv_files']}",
            f"- races: {summary['race_count']}",
            f"- horses: {summary['horse_count']}",
            f"- note: {summary['note']}",
            "",
            "## Decision Counts",
            "",
            "| Decision | Official | Trace Recomputed |",
            "|---|---:|---:|",
        ]
        official = summary["official_counts"]
        trace = summary["trace_counts"]
        for decision in DECISIONS:
            lines.append(f"| {decision} | {official[decision]} | {trace[decision]} |")
        lines.extend(
            [
                "",
                "## Score Availability",
                "",
                f"- decision_score_available_count: {summary['decision_score_available_count']}",
                f"- decision_score_min: {summary['decision_score_min']}",
                f"- decision_score_max: {summary['decision_score_max']}",
                f"- decision_score_avg: {summary['decision_score_avg']}",
                f"- risk_score_avg: {summary['risk_score_avg']}",
                f"- near_buy_boundary_count: {summary['near_buy_boundary_count']}",
                f"- official_trace_mismatch_count: {summary['official_trace_mismatch_count']}",
                "",
                "## Top Risks In Trace",
                "",
                "| Risk | Count |",
                "|---|---:|",
            ]
        )
        for risk, count in summary["top_risks"]:
            lines.append(f"| {risk} | {count} |")
        lines.extend(["", "## Decision Influencing Evaluators", "", "| Evaluator | Count |", "|---|---:|"])
        for evaluator, count in summary["top_evaluators"]:
            lines.append(f"| {evaluator} | {count} |")
        lines.extend(["", "## Race IDs", ""])
        lines.extend(f"- {race_id}" for race_id in summary["race_ids"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")

    def _distance(self, threshold: float, score: float | None) -> float | None:
        if score is None:
            return None
        return round(max(0.0, threshold - score), 4)

    def _to_int(self, value: object) -> int | None:
        try:
            if value is None or value == "":
                return None
            return int(float(str(value).strip()))
        except ValueError:
            return None

    def _to_float(self, value: object) -> float | None:
        try:
            if value is None or value == "":
                return None
            return float(str(value).strip())
        except ValueError:
            return None

    def _list(self, value: object) -> List[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        if value is None or value == "":
            return []
        return [str(value)]

    def _json(self, value: object) -> str:
        return json.dumps(value, ensure_ascii=False)


def main() -> None:
    result = DecisionScoreTrace().run()
    summary = result["summary"]
    print("Decision Score Trace completed")
    print(f"input_files={len(result['input_files'])}")
    print(f"races={summary['race_count']} horses={summary['horse_count']}")
    print(f"decision_score_available_count={summary['decision_score_available_count']}")
    print(f"official_trace_mismatch_count={summary['official_trace_mismatch_count']}")
    print(f"output_dir={result['output_dir']}")


if __name__ == "__main__":
    main()
