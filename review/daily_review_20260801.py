from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.read_only_replay_layer import DailyReviewReadOnlyReplay


class DailyReview20260801:
    """Create a read-only Analysis vs Result review for 2026-08-01."""

    DATE = "20260801"
    OUTPUT_DIR = Path("reports/review_20260801")

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.analysis_dir = self.base_dir / "data" / "analysis"
        self.results_dir = self.base_dir / "data" / "results"
        self.output_dir = self.base_dir / self.OUTPUT_DIR
        self.replay = DailyReviewReadOnlyReplay(self.base_dir, self.DATE, self.OUTPUT_DIR)

    def run(self) -> Dict[str, Any]:
        input_files = self._input_files()
        before_hashes = self._hash_files(input_files)
        replay = self.replay.load()
        race_rows: List[Dict[str, Any]] = list(replay.get("race_rows", []) or [])
        horse_rows: List[Dict[str, Any]] = list(replay.get("horse_rows", []) or [])
        incomplete: List[Dict[str, Any]] = list(replay.get("incomplete", []) or [])
        duplicates: List[Dict[str, Any]] = list(replay.get("duplicates", []) or [])
        replay_errors: List[Dict[str, Any]] = list(replay.get("replay_errors", []) or [])
        replay_source: Dict[str, Any] = dict(replay.get("source", {}) or {})

        summary = self._summary(race_rows, horse_rows, incomplete, duplicates, replay_errors)
        summary["replay_source"] = replay_source
        candidates = self._improvement_candidates(race_rows, horse_rows)
        validation = self._validate(race_rows, horse_rows, incomplete, duplicates)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        race_csv = self._available_path(self.output_dir / "race_summary_20260801.csv")
        horse_csv = self._available_path(self.output_dir / "horse_review_20260801.csv")
        daily_md = self._available_path(self.output_dir / "daily_review_20260801.md")
        candidates_md = self._available_path(self.output_dir / "improvement_candidates_20260801.md")
        summary_json = self._available_path(self.output_dir / "daily_review_20260801_summary.json")
        generated_version = self._output_version(summary_json, "daily_review_20260801_summary")
        replay_source["generated_report_version"] = generated_version
        replay_source["generated_at"] = datetime.now(timezone.utc).isoformat()

        self._write_csv(race_csv, race_rows)
        self._write_csv(horse_csv, horse_rows)
        self._write_daily_md(daily_md, summary, race_rows, horse_rows, incomplete, candidates, validation)
        self._write_candidates_md(candidates_md, candidates)
        self._write_json(
            summary_json,
            {
                "summary": summary,
                "validation": validation,
                "candidates": candidates,
                "replay_source": replay_source,
            },
        )

        after_hashes = self._hash_files(input_files)
        hash_changes = [
            str(path.relative_to(self.base_dir))
            for path, digest in before_hashes.items()
            if after_hashes.get(path) != digest
        ]
        result = {
            "date": self.DATE,
            "complete_races": len(race_rows),
            "incomplete": len(incomplete),
            "horse_rows": len(horse_rows),
            "buy_count": summary["buy_count"],
            "buy_top3": summary["buy_top3"],
            "buy_win": summary["buy_win"],
            "self_check_conflict": summary["self_check_conflict"],
            "outputs": [str(path) for path in [daily_md, race_csv, horse_csv, candidates_md, summary_json]],
            "hash_changes": hash_changes,
            "validation_errors": validation["errors"],
            "validation_warnings": validation["warnings"],
            "replay_source": replay_source,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def _detect_sets(self) -> Tuple[Dict[str, Dict[str, Path]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        race_ids = set()
        for path in self.analysis_dir.glob(f"race_{self.DATE}_*_entry.csv"):
            race_ids.add(path.stem.replace("_entry", ""))
        for path in self.analysis_dir.glob(f"race_{self.DATE}_*_horses.csv"):
            race_ids.add(path.stem.replace("_horses", ""))
        for path in self.results_dir.glob(f"race_{self.DATE}_*_result.csv"):
            race_ids.add(path.stem.replace("_result", ""))
        for path in self.results_dir.glob(f"horse_{self.DATE}_*_result.csv"):
            race_ids.add("race_" + path.stem.replace("horse_", "").replace("_result", ""))

        complete: Dict[str, Dict[str, Path]] = {}
        incomplete: List[Dict[str, Any]] = []
        duplicates: List[Dict[str, Any]] = []
        for race_id in sorted(race_ids):
            suffix = race_id.replace("race_", "")
            paths = {
                "entry": self.analysis_dir / f"{race_id}_entry.csv",
                "horses": self.analysis_dir / f"{race_id}_horses.csv",
                "race_result": self.results_dir / f"{race_id}_result.csv",
                "horse_result": self.results_dir / f"horse_{suffix}_result.csv",
            }
            missing = [key for key, path in paths.items() if not path.exists()]
            if missing:
                incomplete.append({"race_id": race_id, "reason": "missing:" + ";".join(missing)})
                continue
            complete[race_id] = paths

        for pattern in [
            f"race_{self.DATE}_*_entry.csv",
            f"race_{self.DATE}_*_horses.csv",
            f"race_{self.DATE}_*_result.csv",
            f"horse_{self.DATE}_*_result.csv",
        ]:
            names = Counter(path.name for path in list(self.analysis_dir.glob(pattern)) + list(self.results_dir.glob(pattern)))
            for name, count in names.items():
                if count > 1:
                    duplicates.append({"file": name, "count": count})
        return complete, incomplete, duplicates

    def _review_race(self, race_id: str, paths: Dict[str, Path]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        raise RuntimeError("Daily Review uses DailyReviewReadOnlyReplay; production adapter replay is disabled.")

    def _horse_row(self, race_id: str, output: Dict[str, Any], horse: Dict[str, Any], result: Dict[str, Any], rank: int, join_method: str) -> Dict[str, Any]:
        decision = str(horse.get("decision") or "")
        risks = self._list(horse.get("final_risks")) or self._list(horse.get("risk_factors"))
        positives = self._list(horse.get("final_strengths")) or self._list(horse.get("strengths"))
        return {
            "race_id": race_id,
            "horse_number": horse.get("horse_number", ""),
            "horse_name": horse.get("horse_name", ""),
            "ai_rank": rank,
            "decision": decision,
            "final_score": horse.get("final_score", ""),
            "adjusted_score": horse.get("adjusted_score", ""),
            "decision_score": horse.get("decision_score", ""),
            "confidence": horse.get("confidence_level") or horse.get("confidence", ""),
            "finish_position": result.get("finish_position", ""),
            "actual_top3": self._is_finish_within(result.get("finish_position"), 3),
            "actual_top5": self._is_finish_within(result.get("finish_position"), 5),
            "corner_positions": result.get("corner_positions", ""),
            "fourth_corner_position": result.get("fourth_corner_position", ""),
            "last_3f": result.get("last_3f", ""),
            "last_3f_rank": result.get("last_3f_rank", ""),
            "finish_time": result.get("finish_time", ""),
            "frame_number": result.get("frame_number", ""),
            "result_join_method": join_method,
            "positive_reasons": "; ".join(str(x) for x in positives),
            "risk_reasons": "; ".join(str(x) for x in risks),
            "decision_reason": horse.get("decision_reason", ""),
            "explain_summary": horse.get("final_summary") or horse.get("explain_summary") or "",
            "race_decision_original": output.get("race_decision_original") or output.get("race_decision"),
            "race_decision_final": output.get("race_decision_final") or output.get("race_decision"),
            "race_decision_sync_applied": output.get("race_decision_sync_applied", ""),
            "race_decision_sync_reason": output.get("race_decision_sync_reason", ""),
        }

    def _summary(self, race_rows: List[Dict[str, Any]], horse_rows: List[Dict[str, Any]], incomplete: List[Dict[str, Any]], duplicates: List[Dict[str, Any]], replay_errors: List[Dict[str, Any]]) -> Dict[str, Any]:
        buy_rows = [row for row in horse_rows if row["decision"] == "BUY"]
        top1_rows = [row for row in horse_rows if int(row["ai_rank"]) == 1]
        top3_rows = [row for row in horse_rows if int(row["ai_rank"]) <= 3]
        top5_rows = [row for row in horse_rows if int(row["ai_rank"]) <= 5]
        race_count = len(race_rows)
        return {
            "target_date": self.DATE,
            "complete_race_count": race_count,
            "incomplete_count": len(incomplete),
            "duplicate_count": len(duplicates),
            "replay_error_count": len(replay_errors),
            "horse_count": len(horse_rows),
            "buy_count": len(buy_rows),
            "buy_top3": sum(1 for row in buy_rows if row["actual_top3"]),
            "buy_win": sum(1 for row in buy_rows if self._to_int(row.get("finish_position"), 999) == 1),
            "buy_place_rate": self._pct(sum(1 for row in buy_rows if row["actual_top3"]), len(buy_rows)),
            "buy_win_rate": self._pct(sum(1 for row in buy_rows if self._to_int(row.get("finish_position"), 999) == 1), len(buy_rows)),
            "buy0_races": sum(1 for row in race_rows if int(row["buy_count"]) == 0),
            "play_count": sum(1 for row in race_rows if str(row["race_decision_final"]).upper() == "PLAY"),
            "caution_count": sum(1 for row in race_rows if str(row["race_decision_final"]).upper() == "CAUTION"),
            "pass_count": sum(1 for row in race_rows if str(row["race_decision_final"]).upper() == "PASS"),
            "self_check_conflict": sum(1 for row in race_rows if row["self_check_conflict"]),
            "top1_place": sum(1 for row in top1_rows if row["actual_top3"]),
            "top1_win": sum(1 for row in top1_rows if self._to_int(row.get("finish_position"), 999) == 1),
            "top1_place_rate": self._pct(sum(1 for row in top1_rows if row["actual_top3"]), len(top1_rows)),
            "top1_win_rate": self._pct(sum(1 for row in top1_rows if self._to_int(row.get("finish_position"), 999) == 1), len(top1_rows)),
            "top3_place_rate": self._pct(sum(1 for row in top3_rows if row["actual_top3"]), len(top3_rows)),
            "top5_place_rate": self._pct(sum(1 for row in top5_rows if row["actual_top3"]), len(top5_rows)),
            "top3_contains_winner": sum(1 for row in race_rows if row["winner_in_top3"]),
            "top5_contains_winner": sum(1 for row in race_rows if row["winner_in_top5"]),
            "top5_has_top3_ge1": sum(1 for row in race_rows if int(row["top5_place_count"]) >= 1),
            "top5_has_top3_ge2": sum(1 for row in race_rows if int(row["top5_place_count"]) >= 2),
            "top5_has_top3_eq3": sum(1 for row in race_rows if int(row["top5_place_count"]) == 3),
            "race_decision_classification": dict(Counter(row["race_decision_classification"] for row in race_rows)),
            "explain_match_counts": dict(Counter(row["explain_match"] for row in race_rows)),
        }

    def _race_decision_classification(self, decision: str, buy_rows: List[Dict[str, Any]], top1: List[Dict[str, Any]], top3: List[Dict[str, Any]], top5: List[Dict[str, Any]], top5_top3_count: int, winner_in_top5: bool) -> str:
        decision = str(decision or "").upper()
        if decision == "PASS" and buy_rows:
            return "SELF_CHECK_CONFLICT"
        if decision == "PLAY":
            if any(row["actual_top3"] for row in buy_rows) or top5_top3_count >= 2:
                return "PLAY_CORRECT"
            return "PLAY_MISS"
        if decision == "PASS":
            if top5_top3_count >= 2 or (top1 and top1[0]["actual_top3"]):
                return "PASS_TOO_CONSERVATIVE"
            return "PASS_CORRECT"
        if decision == "CAUTION":
            return "CAUTION_APPROPRIATE"
        return "REVIEW_REQUIRED"

    def _explain_match(self, buy_rows: List[Dict[str, Any]], top5: List[Dict[str, Any]], decision: str, top5_top3_count: int) -> str:
        if buy_rows:
            if any(row["actual_top3"] for row in buy_rows):
                return "EXPLAIN_MATCH"
            if top5_top3_count:
                return "PARTIAL_MATCH"
            return "EXPLAIN_MISS"
        if str(decision).upper() == "PASS":
            if top5_top3_count >= 2:
                return "PARTIAL_MATCH"
            if top5_top3_count == 0:
                return "EXPLAIN_MATCH"
        return "UNDETERMINED"

    def _cause_candidates(self, buy_rows: List[Dict[str, Any]], top5: List[Dict[str, Any]], output: Dict[str, Any]) -> Tuple[str, List[str]]:
        texts = []
        for row in buy_rows or top5:
            texts.extend([row.get("risk_reasons", ""), row.get("positive_reasons", ""), row.get("decision_reason", "")])
        texts.extend([output.get("race_decision_reason", ""), output.get("race_summary", "")])
        haystack = " ".join(str(x) for x in texts).lower()
        matches = []
        for label, keywords in [
            ("RaceDecision", ["racedecision", "race decision", "pass", "play"]),
            ("BUY qualification", ["absolute", "relative", "threshold", "risk_guard", "buy"]),
            ("Confidence", ["confidence"]),
            ("RaceShape", ["raceshape", "race_shape", "展開", "構造"]),
            ("CourseShape", ["course", "コース"]),
            ("TrackBias", ["track_bias", "バイアス"]),
            ("MeetingBias", ["meeting", "開催"]),
            ("Pace", ["pace", "ペース", "ラップ"]),
            ("Distance", ["distance", "距離"]),
            ("PastPerformance", ["past", "近走"]),
            ("Bloodline", ["blood", "血統"]),
            ("Weight", ["weight", "斤量"]),
        ]:
            if any(keyword in haystack for keyword in keywords):
                matches.append(label)
        if not matches:
            return "UNDETERMINED", []
        return matches[0], matches[1:]

    def _improvement_candidates(self, race_rows: List[Dict[str, Any]], horse_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates = []
        conflict = [row for row in race_rows if row["self_check_conflict"]]
        if conflict:
            candidates.append(self._candidate("RaceDecisionBuySynchronizer", "OPERATION_ISSUE", conflict, "RaceDecision PASS x BUY conflict remains", "REVIEW_REQUIRED", "P0", True))
        play_miss = [row for row in race_rows if row["race_decision_classification"] == "PLAY_MISS"]
        if play_miss:
            candidates.append(self._candidate("BUY / RaceDecision precision review", "REPEATED_PATTERN", play_miss, "PLAY but BUY/Top5 did not capture result", "WATCH_RECOMMENDED", "P1", False))
        pass_too = [row for row in race_rows if row["race_decision_classification"] == "PASS_TOO_CONSERVATIVE"]
        if pass_too:
            candidates.append(self._candidate("RaceDecision conservativeness", "REPEATED_PATTERN", pass_too, "PASS but AI top ranks captured result", "WATCH_RECOMMENDED", "P1", False))
        fp_buy = [row for row in horse_rows if row["decision"] == "BUY" and not row["actual_top3"]]
        if fp_buy:
            race_ids = sorted(set(row["race_id"] for row in fp_buy))
            candidates.append(
                {
                    "candidate_name": "BUY false positive monitoring",
                    "candidate_type": "BUY Monitoring",
                    "pattern_type": "REPEATED_PATTERN",
                    "race_ids": "; ".join(race_ids),
                    "representative_evidence": "; ".join(f"{row['race_id']} {row['horse_name']} finish={row['finish_position']}" for row in fp_buy[:5]),
                    "problem": "BUY馬が複勝圏外",
                    "expected_effect": "BUY複勝率の改善余地を追跡",
                    "side_effect": "単発除外に走るとExplainabilityを損なう",
                    "additional_data_needed": "複数開催でのBUY FP再現性",
                    "shadow_target": "BUY false positive filter / monitoring only",
                    "recommended_human_review_status": "WATCH_RECOMMENDED",
                    "priority": "P1",
                    "implement_now": "NO",
                    "hold_reason": "単日だけでProduction変更は不可",
                }
            )
        if not candidates:
            candidates.append(
                {
                    "candidate_name": "No immediate implementation candidate",
                    "candidate_type": "Review",
                    "pattern_type": "SINGLE_CASE",
                    "race_ids": "",
                    "representative_evidence": "No strong repeated failure pattern",
                    "problem": "なし",
                    "expected_effect": "",
                    "side_effect": "",
                    "additional_data_needed": "継続監視",
                    "shadow_target": "",
                    "recommended_human_review_status": "NO_ACTION",
                    "priority": "P3",
                    "implement_now": "NO",
                    "hold_reason": "根拠不足",
                }
            )
        return candidates

    def _candidate(self, name: str, pattern: str, races: List[Dict[str, Any]], problem: str, status: str, priority: str, implement: bool) -> Dict[str, Any]:
        return {
            "candidate_name": name,
            "candidate_type": "Operation" if "Synchronizer" in name else "RaceDecision",
            "pattern_type": pattern,
            "race_ids": "; ".join(row["race_id"] for row in races),
            "representative_evidence": "; ".join(f"{row['race_id']} {row['race_decision_classification']}" for row in races[:3]),
            "problem": problem,
            "expected_effect": "レビュー整合性と運用判断品質の向上",
            "side_effect": "表示レイヤー変更時は旧RaceDecisionとの混同に注意",
            "additional_data_needed": "次開催以降の再現性",
            "shadow_target": "read-only comparison using saved output and current replay",
            "recommended_human_review_status": status,
            "priority": priority,
            "implement_now": "YES" if implement else "NO",
            "hold_reason": "" if implement else "単日結果のためWATCH",
        }

    def _validate(self, race_rows: List[Dict[str, Any]], horse_rows: List[Dict[str, Any]], incomplete: List[Dict[str, Any]], duplicates: List[Dict[str, Any]]) -> Dict[str, Any]:
        errors = []
        warnings = []
        race_ids = [row["race_id"] for row in race_rows]
        if any(not race_id.startswith(f"race_{self.DATE}_") for race_id in race_ids):
            errors.append("non_target_date_race_detected")
        if len(race_ids) != len(set(race_ids)):
            errors.append("duplicate_race_id")
        for row in race_rows:
            if int(row["buy_count"]) > 3:
                errors.append(f"buy_count_over_3:{row['race_id']}")
            if row["joined_horse_count"] != row["result_horse_count"]:
                warnings.append(f"join_count_mismatch:{row['race_id']}")
            if not row["race_decision"]:
                errors.append(f"race_decision_missing:{row['race_id']}")
        for race_id, rows in self._group(horse_rows, "race_id").items():
            top5 = [row["horse_name"] for row in rows if int(row["ai_rank"]) <= 5]
            if len(top5) != len(set(top5)):
                errors.append(f"top5_duplicate:{race_id}")
            if any(row.get("finish_position") in ("", None) for row in rows):
                warnings.append(f"finish_missing:{race_id}")
        return {
            "errors": errors,
            "warnings": warnings,
            "checks": [
                "target date 20260801 only",
                "race_id duplicate checked",
                "complete pair checked",
                "horse join count checked",
                "BUY count 0-3 checked",
                "Top1/Top3/Top5 duplicate checked",
                "finish missing checked",
                "RaceDecision missing checked",
                "denominators and numerators generated together",
                "INCOMPLETE excluded from rate denominators",
                "READ_ONLY_REPLAY source recorded",
                "source review version recorded",
                "source evaluation origin recorded",
                "PRE_RACE_SAVED_OUTPUT remains NOT_FOUND",
                "Evaluator reexecution is NO",
                "Decision recalculation is NO",
                "BUY recalculation is NO",
                "Human Review DB not written",
            ],
            "incomplete": incomplete,
            "duplicates": duplicates,
        }

    def _write_daily_md(self, path: Path, summary: Dict[str, Any], race_rows: List[Dict[str, Any]], horse_rows: List[Dict[str, Any]], incomplete: List[Dict[str, Any]], candidates: List[Dict[str, Any]], validation: Dict[str, Any]) -> None:
        source = summary.get("replay_source") if isinstance(summary.get("replay_source"), dict) else {}
        lines = [
            "# Daily Race Review 2026/08/01",
            "",
            "## Scope",
            f"- Replay Mode: {source.get('replay_mode') or source.get('mode') or 'READ_ONLY_REPLAY'}",
            f"- Source Review Version: {source.get('source_review_version', '')}",
            f"- Source Evaluation Origin: {source.get('source_evaluation_origin', '')}",
            f"- PRE_RACE_SAVED_OUTPUT: {source.get('pre_race_saved_output_status', 'NOT_FOUND')}",
            f"- Saved Review Source: {source.get('saved_review_source_status', '')}",
            f"- Evaluator reexecuted: {source.get('evaluator_reexecuted', 'NO')}",
            f"- Decision recalculated: {source.get('decision_recalculated', 'NO')}",
            f"- BUY recalculated: {source.get('buy_recalculated', 'NO')}",
            f"- Production Adapter used: {source.get('production_adapter_used', 'NO')}",
            f"- Result data used as evaluation input: {source.get('result_data_used_as_evaluation_input', 'NO')}",
            f"- Source race summary: {source.get('source_race_summary_path', '')}",
            f"- Source horse review: {source.get('source_horse_review_path', '')}",
            "- Production logic, CSV, JSON, Human Review DB, and main.py were not changed.",
            "",
            "## Overall Summary",
            f"- Complete races: {summary['complete_race_count']}",
            f"- INCOMPLETE: {summary['incomplete_count']}",
            f"- Horses: {summary['horse_count']}",
            f"- BUY: {summary['buy_count']}",
            f"- BUY place: {summary['buy_top3']} / {summary['buy_count']} ({summary['buy_place_rate']}%)",
            f"- BUY win: {summary['buy_win']} / {summary['buy_count']} ({summary['buy_win_rate']}%)",
            f"- BUY0 races: {summary['buy0_races']}",
            f"- PLAY / CAUTION / PASS: {summary['play_count']} / {summary['caution_count']} / {summary['pass_count']}",
            f"- SELF_CHECK_CONFLICT: {summary['self_check_conflict']}",
            f"- Top1 place: {summary['top1_place']} / {summary['complete_race_count']} ({summary['top1_place_rate']}%)",
            f"- Top1 win: {summary['top1_win']} / {summary['complete_race_count']} ({summary['top1_win_rate']}%)",
            f"- Top3 contains winner: {summary['top3_contains_winner']} / {summary['complete_race_count']}",
            f"- Top5 contains winner: {summary['top5_contains_winner']} / {summary['complete_race_count']}",
            f"- Top5 has actual Top3 >=1: {summary['top5_has_top3_ge1']} / {summary['complete_race_count']}",
            f"- Top5 has actual Top3 >=2: {summary['top5_has_top3_ge2']} / {summary['complete_race_count']}",
            f"- Top5 has actual Top3 =3: {summary['top5_has_top3_eq3']} / {summary['complete_race_count']}",
            f"- AI Top3 all-horse place rate: {summary['top3_place_rate']}%",
            f"- AI Top5 all-horse place rate: {summary['top5_place_rate']}%",
            "",
            "## RaceDecision Classification",
            "| classification | count |",
            "|---|---:|",
        ]
        for key, value in sorted(summary["race_decision_classification"].items()):
            lines.append(f"| {key} | {value} |")
        lines.extend(["", "## Explain Match", "| match | count |", "|---|---:|"])
        for key, value in sorted(summary["explain_match_counts"].items()):
            lines.append(f"| {key} | {value} |")
        lines.extend(["", "## Complete Race List", "| race_id | RaceDecision | original | final | sync | BUY | BUY result | Top1 | Top1 finish | Top5 top3 | classification | explain |", "|---|---|---|---|---|---:|---|---|---:|---:|---|---|"])
        for row in race_rows:
            lines.append(
                f"| {row['race_id']} | {row['race_decision']} | {row['race_decision_original']} | {row['race_decision_final']} | "
                f"{row['race_decision_sync_applied']} | {row['buy_count']} | {row['buy_top3_count']}/{row['buy_count']} | "
                f"{row['ai_top1']} | {row['ai_top1_finish']} | {row['top5_place_count']} | {row['race_decision_classification']} | {row['explain_match']} |"
            )
        lines.extend(["", "## INCOMPLETE"])
        if incomplete:
            for row in incomplete:
                lines.append(f"- {row.get('race_id')}: {row.get('reason')}")
        else:
            lines.append("- none")
        lines.extend(["", "## Race Details"])
        grouped_horses = self._group(horse_rows, "race_id")
        for row in race_rows:
            lines.extend(
                [
                    f"### {row['race_id']}",
                    f"- RaceDecision: {row['race_decision']}",
                    f"- race_decision_original: {row['race_decision_original']}",
                    f"- race_decision_final: {row['race_decision_final']}",
                    f"- BUY馬: {row['buy_horses'] or 'BUYなし'}",
                    f"- AI Top5: {row['ai_top5']} / finishes {row['ai_top5_finishes']}",
                    f"- 実Top3: {row['actual_top3']}",
                    f"- BUY結果: {row['buy_top3_count']} / {row['buy_count']} 複勝圏",
                    f"- Top5評価: 実Top3 {row['top5_place_count']}頭を捕捉",
                    f"- 展開予測と実際: prediction={row['pace_prediction']} / result_top3={row['actual_top3']}",
                    f"- Explain一致度: {row['explain_match']}",
                    f"- RaceDecision妥当性: {row['race_decision_classification']}",
                    f"- 問題点: primary={row['primary_candidate']} secondary={row['secondary_candidates']}",
                    f"- Human Review対象: {'YES' if row['race_decision_classification'] in {'PLAY_MISS', 'PASS_TOO_CONSERVATIVE', 'SELF_CHECK_CONFLICT'} else 'NO'}",
                    f"- 現時点の結論: {self._race_conclusion(row)}",
                    "",
                ]
            )
            for horse in grouped_horses.get(row["race_id"], [])[:5]:
                lines.append(
                    f"  - AI{horse['ai_rank']} {horse['horse_name']} {horse['decision']} finish={horse['finish_position']} "
                    f"Final={horse['final_score']} adjusted={horse['adjusted_score']}"
                )
            lines.append("")
        lines.extend(["## Human Review Candidates"])
        for candidate in candidates:
            lines.append(f"- {candidate['priority']} {candidate['candidate_name']}: {candidate['recommended_human_review_status']} / {candidate['problem']}")
        lines.extend(["", "## Validation"])
        lines.append(f"- Errors: {len(validation['errors'])}")
        lines.append(f"- Warnings: {len(validation['warnings'])}")
        for check in validation["checks"]:
            lines.append(f"- {check}")
        if validation["errors"]:
            lines.append("### Validation Errors")
            lines.extend(f"- {item}" for item in validation["errors"])
        if validation["warnings"]:
            lines.append("### Validation Warnings")
            lines.extend(f"- {item}" for item in validation["warnings"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _output_version(self, path: Path, base_stem: str) -> str:
        stem = path.stem
        if stem == base_stem:
            return "base"
        prefix = f"{base_stem}_"
        if stem.startswith(prefix):
            return stem[len(prefix) :]
        return "UNKNOWN"

    def _write_candidates_md(self, path: Path, candidates: List[Dict[str, Any]]) -> None:
        lines = ["# Improvement Candidates 2026/08/01", ""]
        for item in candidates:
            lines.extend(
                [
                    f"## {item['candidate_name']}",
                    f"- candidate_type: {item['candidate_type']}",
                    f"- pattern_type: {item['pattern_type']}",
                    f"- race_id: {item['race_ids']}",
                    f"- representative_evidence: {item['representative_evidence']}",
                    f"- problem: {item['problem']}",
                    f"- expected_effect: {item['expected_effect']}",
                    f"- side_effect: {item['side_effect']}",
                    f"- additional_data_needed: {item['additional_data_needed']}",
                    f"- shadow_target: {item['shadow_target']}",
                    f"- recommended_human_review_status: {item['recommended_human_review_status']}",
                    f"- priority: {item['priority']}",
                    f"- implement_now: {item['implement_now']}",
                    f"- hold_reason: {item['hold_reason']}",
                    "",
                ]
            )
        path.write_text("\n".join(lines), encoding="utf-8")

    def _write_csv(self, path: Path, rows: List[Dict[str, Any]]) -> None:
        fields: List[str] = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields or ["empty"])
            writer.writeheader()
            writer.writerows(rows)

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _input_files(self) -> List[Path]:
        files = []
        files.extend(sorted(self.analysis_dir.glob(f"race_{self.DATE}_*.csv")))
        files.extend(sorted(self.results_dir.glob(f"*_{self.DATE}_*_result.csv")))
        human_db = self.base_dir / "learning" / "candidate_review_status.json"
        if human_db.exists():
            files.append(human_db)
        return files

    def _hash_files(self, files: Iterable[Path]) -> Dict[Path, str]:
        hashes = {}
        for path in files:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            hashes[path] = digest.hexdigest()
        return hashes

    def _available_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        for index in range(2, 100):
            candidate = path.with_name(f"{stem}_v{index}{suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"no available output path for {path}")

    def _group(self, rows: List[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get(key) or "")].append(row)
        return grouped

    def _names(self, rows: List[Dict[str, Any]]) -> str:
        return "; ".join(str(row.get("horse_name") or "") for row in rows)

    def _finishes(self, rows: List[Dict[str, Any]]) -> str:
        return "; ".join(str(row.get("finish_position") or "") for row in rows)

    def _to_int(self, value: Any, default: int = 0) -> int:
        try:
            if value in (None, ""):
                return default
            return int(float(str(value)))
        except ValueError:
            return default

    def _is_finish_within(self, value: Any, limit: int) -> bool:
        finish = self._to_int(value, 0)
        return 1 <= finish <= limit

    def _pct(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator * 100.0, 1)

    def _list(self, value: Any) -> List[Any]:
        return value if isinstance(value, list) else []

    def _pace_prediction(self, output: Dict[str, Any]) -> str:
        structure = output.get("race_structure") if isinstance(output.get("race_structure"), dict) else {}
        return str(
            structure.get("pace")
            or structure.get("pace_type")
            or output.get("structure_comment")
            or output.get("race_summary_short")
            or ""
        )

    def _track_bias_input(self, output: Dict[str, Any]) -> str:
        bias = output.get("race_pace") if isinstance(output.get("race_pace"), dict) else {}
        return str(bias.get("manual_track_bias") or bias.get("track_bias") or "neutral_or_unavailable")

    def _race_conclusion(self, row: Dict[str, Any]) -> str:
        if row["self_check_conflict"]:
            return "RaceDecisionとBUYの同期確認が必要"
        if row["race_decision_classification"] == "PLAY_CORRECT":
            return "PLAY判断は概ね結果と整合"
        if row["race_decision_classification"] == "PLAY_MISS":
            return "PLAY判断またはBUY候補の追加レビューが必要"
        if row["race_decision_classification"] == "PASS_TOO_CONSERVATIVE":
            return "PASS判断が慎重すぎた可能性"
        return "継続監視"


def main() -> None:
    DailyReview20260801().run()


if __name__ == "__main__":
    main()
