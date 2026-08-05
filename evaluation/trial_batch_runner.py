"""Batch runner for trial TARGET race CSV evaluation.

This module is a trial-only verification runner. It discovers matching
TARGET entry/history CSV pairs, runs the existing TargetTrialAdapter, and
summarizes the output. It does not change Analyzer, Evaluator calculations,
FinalScore, Decision, Confidence, Knowledge, CSV specs, or main.py.
"""

from __future__ import annotations

import csv
import os
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.target_trial_adapter import TargetTrialAdapter
from importer.target_entry_importer import TargetEntryImporter
from importer.target_history_importer import TargetHistoryImporter
from review.ranking_provenance_exporter import PIPELINE_VERSION, export as export_ranking_provenance, update_ledger, write_weight_source


class TrialBatchRunner:
    """Run multiple TARGET trial races through TargetTrialAdapter."""

    BATCH_VERSION = "trial_batch_v1"
    RANKING_PROVENANCE_FLAG = "RANKING_PROVENANCE_EXPORT_ENABLED"
    ENTRY_SUFFIX = "_entry.csv"
    HORSES_SUFFIX = "_horses.csv"
    JUMP_KEYWORDS = ("障害", "JG", "ジャンプ")
    NEWCOMER_KEYWORDS = ("新馬", "メイクデビュー")
    SCORE_KEYS = {
        "bloodline": "bloodline_score",
        "past": "past_performance_score",
        "pace": "pace_style_score",
        "distance": "distance_score",
        "track_condition": "track_condition_score",
        "race_shape": "shape_score",
        "course_shape": "course_shape_score",
        "bias": "track_bias_score",
        "lap": "lap_score",
    }

    def __init__(self, entry_dir="data/entries", horse_data_dir="data/horse_data"):
        self.entry_dir = Path(entry_dir)
        self.horse_data_dir = Path(horse_data_dir)
        self.adapter = TargetTrialAdapter()
        self.entry_importer = TargetEntryImporter()
        self.history_importer = TargetHistoryImporter()

    def run(self, exclude_jump=True, exclude_newcomer=True, limit=None):
        """Run all discovered race pairs and return batch_result."""

        race_pairs = self.find_race_pairs()
        warnings = []
        race_results = []
        executed = 0

        for pair in race_pairs:
            race_id = pair.get("race_id")
            entry_file = pair.get("entry_file")
            horse_data_file = pair.get("horse_data_file")

            if limit is not None and executed >= limit:
                break

            if not entry_file or not horse_data_file:
                reason = "missing paired CSV"
                race_result = self._skipped_result(race_id, entry_file, horse_data_file, reason)
                race_results.append(race_result)
                warnings.append(f"{race_id}: {reason}")
                continue

            skip = self.should_skip_race(
                race_id,
                entry_file,
                horse_data_file,
                exclude_jump=exclude_jump,
                exclude_newcomer=exclude_newcomer,
            )
            if skip.get("skip"):
                race_results.append(
                    self._skipped_result(
                        race_id,
                        entry_file,
                        horse_data_file,
                        skip.get("reason") or "excluded race",
                        skip.get("evidence") or "",
                    )
                )
                warnings.append(f"{race_id}: {skip.get('reason')}")
                continue

            race_result = self.run_single_race(race_id, entry_file, horse_data_file)
            race_results.append(race_result)
            if race_result.get("status") == "executed":
                executed += 1
            elif race_result.get("warning"):
                warnings.append(f"{race_id}: {race_result.get('warning')}")

        summary = self.build_summary(race_results)
        diagnostic_summary = self.build_diagnostic_summary(race_results)
        summary["diagnostic_summary"] = diagnostic_summary
        metadata = {
            "batch_version": self.BATCH_VERSION,
            "entry_dir": str(self.entry_dir),
            "horse_data_dir": str(self.horse_data_dir),
            "total_pairs_found": len(race_pairs),
            "total_races": len(race_results),
            "executed_races": sum(1 for item in race_results if item.get("status") == "executed"),
            "skipped_races": sum(1 for item in race_results if item.get("status") == "skipped"),
            "error_races": sum(1 for item in race_results if item.get("status") == "error"),
        }
        metadata["skipped_races"] += max(0, len(race_pairs) - len(race_results))

        return {
            "metadata": metadata,
            "race_results": race_results,
            "summary": summary,
            "diagnostic_summary": diagnostic_summary,
            "warnings": warnings,
        }

    def find_race_pairs(self):
        """Detect matching *_entry.csv and *_horses.csv race pairs."""

        entries = {}
        histories = {}
        race_ids = {}

        if self.entry_dir.exists():
            for path in sorted(self.entry_dir.glob(f"*{self.ENTRY_SUFFIX}")):
                race_id = self._race_id_from_entry(path)
                if race_id:
                    key = self._race_pair_key(race_id)
                    entries[key] = path
                    race_ids[key] = race_id

        if self.horse_data_dir.exists():
            for path in sorted(self.horse_data_dir.glob(f"*{self.HORSES_SUFFIX}")):
                race_id = self._race_id_from_horses(path)
                if race_id:
                    key = self._race_pair_key(race_id)
                    histories[key] = path
                    race_ids.setdefault(key, self._canonical_race_id(race_id))

        keys = sorted(set(entries) | set(histories))
        return [
            {
                "race_id": race_ids.get(key) or key,
                "entry_file": entries.get(key),
                "horse_data_file": histories.get(key),
            }
            for key in keys
        ]

    def should_skip_race(
        self,
        race_id,
        entry_file,
        horse_data_file,
        exclude_jump=True,
        exclude_newcomer=True,
    ):
        """Return skip decision for jump and newcomer races."""

        texts = [str(race_id or ""), self._file_stem(entry_file), self._file_stem(horse_data_file)]
        texts.extend(self._sample_csv_text(entry_file))
        joined = " ".join(text for text in texts if text)

        if exclude_jump and self._contains_any(joined, self.JUMP_KEYWORDS):
            return {"skip": True, "reason": "jump race excluded", "evidence": joined[:200]}
        if exclude_newcomer and self._contains_any(joined, self.NEWCOMER_KEYWORDS):
            return {"skip": True, "reason": "newcomer race excluded", "evidence": joined[:200]}
        return {"skip": False, "reason": "", "evidence": ""}

    def run_single_race(self, race_id, entry_file, horse_data_file):
        """Run one race with TargetTrialAdapter and return compact result."""

        try:
            adapter_result = self.adapter.run(str(entry_file), str(horse_data_file))
        except Exception as exc:
            return {
                "race_id": race_id,
                "entry_file": str(entry_file) if entry_file else "",
                "horse_data_file": str(horse_data_file) if horse_data_file else "",
                "status": "error",
                "skip_reason": "",
                "warning": str(exc),
                "entry_count": 0,
                "horse_data_count": 0,
                "history_count": 0,
                "linked_count": 0,
                "analyzer_input_count": 0,
                "results_count": 0,
                "race_decision": "unknown",
                "race_confidence": "unknown",
                "buy_candidates": [],
                "top3": [],
                "warnings": [str(exc)],
                "summary": "",
            }

        results = adapter_result.get("ranked_results") or adapter_result.get("results") or []
        provenance_export = self._export_ranking_provenance_after_pre_race(
            race_id, entry_file, adapter_result, results
        )
        warnings = self._collect_warnings(adapter_result, results)
        diagnostics = self.build_race_diagnostics(entry_file, horse_data_file, adapter_result, results)
        buy_candidates = [
            item.get("horse_name")
            for item in results
            if isinstance(item, dict) and item.get("decision") == "BUY"
        ]
        top3 = [
            item.get("horse_name")
            for item in results[:3]
            if isinstance(item, dict) and item.get("horse_name")
        ]

        return {
            "race_id": race_id,
            "entry_file": str(entry_file),
            "horse_data_file": str(horse_data_file),
            "status": "executed",
            "ranking_provenance_export": provenance_export,
            "skip_reason": "",
            "entry_count": adapter_result.get("entry_count", 0),
            "horse_data_count": adapter_result.get("history_count", 0),
            "history_count": adapter_result.get("history_count", 0),
            "linked_count": adapter_result.get("linked_count", 0),
            "analyzer_input_count": len(results),
            "results_count": len(results),
            "race_decision": adapter_result.get("race_decision") or "unknown",
            "race_confidence": adapter_result.get("race_confidence") or "unknown",
            "buy_candidates": buy_candidates,
            "top3": top3,
            "warnings": warnings,
            "diagnostics": diagnostics,
            "diagnostic_report": self.format_race_diagnostic_report(race_id, diagnostics),
            "summary": adapter_result.get("trial_report_summary") or adapter_result.get("race_summary_short") or "",
            "trial_report": adapter_result.get("trial_report") or "",
            "adapter_result": adapter_result,
        }

    def build_summary(self, race_results):
        """Build aggregate summary for all race results."""

        rows = [item for item in race_results if isinstance(item, dict)]
        executed = [item for item in rows if item.get("status") == "executed"]
        all_horses = []
        for race in executed:
            adapter_result = race.get("adapter_result")
            if isinstance(adapter_result, dict):
                all_horses.extend(adapter_result.get("ranked_results") or adapter_result.get("results") or [])

        race_decision_counts = Counter(item.get("race_decision") or "unknown" for item in executed)
        race_confidence_counts = Counter(item.get("race_confidence") or "unknown" for item in executed)
        decision_counts = Counter(
            horse.get("decision") or "unknown"
            for horse in all_horses
            if isinstance(horse, dict)
        )
        warning_frequency = Counter()
        for race in rows:
            warning_frequency.update(race.get("warnings") or [])

        evaluator_average_scores = self._average_scores(all_horses)
        summary_comment = self._summary_comment(
            executed_count=len(executed),
            skipped_count=sum(1 for item in rows if item.get("status") == "skipped"),
            error_count=sum(1 for item in rows if item.get("status") == "error"),
            warning_frequency=warning_frequency,
        )

        return {
            "total_races": len(rows),
            "executed_races": len(executed),
            "skipped_races": sum(1 for item in rows if item.get("status") == "skipped"),
            "error_races": sum(1 for item in rows if item.get("status") == "error"),
            "race_decision_counts": dict(race_decision_counts),
            "race_confidence_counts": dict(race_confidence_counts),
            "decision_counts": dict(decision_counts),
            "buy_candidate_count": decision_counts.get("BUY", 0),
            "caution_horse_count": decision_counts.get("CAUTION", 0),
            "pass_horse_count": decision_counts.get("PASS", 0),
            "warning_frequency": dict(warning_frequency),
            "bloodline_profile_missing_count": self._warning_count(warning_frequency, "Bloodline profile not found"),
            "course_profile_missing_count": self._warning_count(warning_frequency, "Course profile not found"),
            "distance_unknown_count": self._warning_count(warning_frequency, "distance unknown"),
            "track_condition_unknown_count": self._warning_count(warning_frequency, "track condition unknown"),
            "evaluator_average_scores": evaluator_average_scores,
            "summary_comment": summary_comment,
        }

    def build_race_diagnostics(self, entry_file, horse_data_file, adapter_result, results):
        """Build per-race information completeness diagnostics by horse name."""

        entry_names = self._entry_horse_names(entry_file)
        history_names = self._history_horse_names(horse_data_file)
        result_rows = [item for item in results if isinstance(item, dict)]
        result_names = [item.get("horse_name") for item in result_rows if item.get("horse_name")]

        horse_data_missing = [name for name in entry_names if name and name not in history_names]
        history_missing = [
            item.get("horse_name")
            for item in result_rows
            if item.get("horse_name") and self._has_warning(item, "history not found")
        ]
        bloodline_missing = [
            item.get("horse_name")
            for item in result_rows
            if item.get("horse_name") and self._has_warning(item, "Bloodline profile not found")
        ]
        warning_rows = []
        for item in result_rows:
            horse_name = item.get("horse_name") or "unknown"
            for warning in item.get("warnings") or []:
                if warning:
                    warning_rows.append({"horse_name": horse_name, "warning": str(warning)})

        return {
            "entry_count": len(entry_names),
            "horse_data_count": len(history_names),
            "history_count": adapter_result.get("history_count", len(history_names)),
            "analyzer_input_count": len(result_names),
            "entry_horses": entry_names,
            "horse_data_horses": history_names,
            "horse_data_missing": horse_data_missing,
            "history_missing": self._unique(history_missing),
            "bloodline_missing": self._unique(bloodline_missing),
            "warnings": warning_rows,
            "warning_count": len(warning_rows),
        }

    def build_diagnostic_summary(self, race_results):
        """Aggregate diagnostics across all races."""

        total_horse_data_missing = 0
        total_history_missing = 0
        total_bloodline_missing = 0
        total_warning_count = 0
        for race in race_results or []:
            diagnostics = race.get("diagnostics") if isinstance(race, dict) else {}
            if not isinstance(diagnostics, dict):
                continue
            total_horse_data_missing += len(diagnostics.get("horse_data_missing") or [])
            total_history_missing += len(diagnostics.get("history_missing") or [])
            total_bloodline_missing += len(diagnostics.get("bloodline_missing") or [])
            total_warning_count += diagnostics.get("warning_count") or 0

        return {
            "horse_data_missing_total": total_horse_data_missing,
            "history_missing_total": total_history_missing,
            "bloodline_missing_total": total_bloodline_missing,
            "warning_total": total_warning_count,
        }

    def format_race_diagnostic_report(self, race_id, diagnostics):
        """Return a readable per-race diagnostic report."""

        data = diagnostics if isinstance(diagnostics, dict) else {}
        lines = [
            f"------------------------------------",
            f"Race {race_id}",
            f"------------------------------------",
            f"entry: {data.get('entry_count', 0)}",
            f"horse_data: {data.get('horse_data_count', 0)}",
            f"history: {data.get('history_count', 0)}",
            f"analyzer_input: {data.get('analyzer_input_count', 0)}",
            "",
            "horse_data missing",
        ]
        lines.extend(self._bullet_lines(data.get("horse_data_missing")))
        lines.append("")
        lines.append("history missing")
        lines.extend(self._bullet_lines(data.get("history_missing")))
        lines.append("")
        lines.append("bloodline missing")
        lines.extend(self._bullet_lines(data.get("bloodline_missing")))
        lines.append("")
        lines.append("warnings")
        warning_rows = data.get("warnings") or []
        if warning_rows:
            for row in warning_rows:
                lines.append(f"- {row.get('horse_name')}: {row.get('warning')}")
        else:
            lines.append("- none")
        return "\n".join(lines)

    def _skipped_result(self, race_id, entry_file, horse_data_file, reason, evidence=""):
        return {
            "race_id": race_id or "",
            "entry_file": str(entry_file) if entry_file else "",
            "horse_data_file": str(horse_data_file) if horse_data_file else "",
            "status": "skipped",
            "skip_reason": reason,
            "skip_evidence": evidence,
            "entry_count": 0,
            "horse_data_count": 0,
            "history_count": 0,
            "linked_count": 0,
            "analyzer_input_count": 0,
            "results_count": 0,
            "race_decision": "unknown",
            "race_confidence": "unknown",
            "buy_candidates": [],
            "top3": [],
            "warnings": [reason] if reason else [],
            "summary": "",
        }

    def _export_ranking_provenance_after_pre_race(self, race_id, entry_file, adapter_result, results):
        """Additive PRE hook. Never feeds diagnostics back into evaluation."""

        if os.environ.get(self.RANKING_PROVENANCE_FLAG, "OFF").upper() != "ON":
            return {"status": "DISABLED", "feature_flag": "OFF"}
        output_root = Path("reports/ranking_provenance").resolve()
        race_date = self._race_date(race_id, adapter_result)
        rows = []
        for item in results:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.update({
                "race_id": race_id,
                "race_date": race_date,
                "horse_name": item.get("horse_name") or item.get("name") or "",
                "horse_number": item.get("horse_number") or item.get("number") or "",
                "source_version": self.BATCH_VERSION,
                "pipeline_version": PIPELINE_VERSION,
            })
            rows.append(row)
        try:
            source = write_weight_source(rows, output_root, race_date, self.BATCH_VERSION, entry_file)
            pre = export_ranking_provenance(
                rows, output_root / "pre_race", race_date, self.BATCH_VERSION,
                entry_file, provenance_source_file=source,
            )
            ledger = update_ledger(output_root / "ranking_provenance_ledger_v1.json", pre["manifest"])
            return {"status": "COMPLETE", "feature_flag": "ON", "source_file": str(source),
                    "pre_manifest": str(pre["manifest_path"]), "ledger_entries": len(ledger["entries"])}
        except FileExistsError as exc:
            return {"status": "SKIPPED_DUPLICATE", "feature_flag": "ON", "message": str(exc)}
        except Exception as exc:
            error_dir = output_root / "errors";error_dir.mkdir(parents=True, exist_ok=True)
            error_path = error_dir / f"ranking_provenance_export_failed_{race_date}_{race_id}.txt"
            if not error_path.exists():error_path.write_text(str(exc)+"\n",encoding="utf-8")
            return {"status": "EXPORT_FAILED", "feature_flag": "ON", "message": str(exc),
                    "operational_action": "CONTINUE_PRODUCTION_AND_HOLD_RANKING_EVIDENCE", "error_report": str(error_path)}

    def _race_date(self, race_id, adapter_result):
        value = adapter_result.get("race_date")
        if value:return "".join(ch for ch in str(value) if ch.isdigit())[:8]
        for part in str(race_id).split("_"):
            digits="".join(ch for ch in part if ch.isdigit())
            if len(digits)==8:return digits
        raise ValueError("RACE_DATE_NOT_AVAILABLE_FOR_PROVENANCE")

    def _average_scores(self, horses):
        totals = defaultdict(float)
        counts = defaultdict(int)
        for horse in horses:
            if not isinstance(horse, dict):
                continue
            for label, key in self.SCORE_KEYS.items():
                value = self._number_or_none(horse.get(key))
                if value is None:
                    continue
                totals[label] += value
                counts[label] += 1
        return {
            label: round(totals[label] / counts[label], 2)
            for label in self.SCORE_KEYS
            if counts[label]
        }

    def _collect_warnings(self, adapter_result, results):
        warnings = []
        for value in adapter_result.get("warnings", []) if isinstance(adapter_result, dict) else []:
            if value:
                warnings.append(str(value))
        for horse in results:
            if not isinstance(horse, dict):
                continue
            horse_name = horse.get("horse_name") or "unknown"
            for warning in horse.get("warnings") or []:
                if warning:
                    warnings.append(f"{horse_name}: {warning}")
        return warnings

    def _entry_horse_names(self, entry_file):
        try:
            entries = self.entry_importer.load(entry_file)
        except Exception:
            return []
        return [
            getattr(entry, "horse_name", None)
            for entry in entries or []
            if getattr(entry, "horse_name", None)
        ]

    def _history_horse_names(self, horse_data_file):
        try:
            histories = self.history_importer.load(horse_data_file)
        except Exception:
            return []
        if isinstance(histories, dict):
            return sorted(name for name in histories if name)
        return []

    def _has_warning(self, horse, text):
        needle = str(text)
        for warning in horse.get("warnings") or []:
            if needle in str(warning):
                return True
        return False

    def _bullet_lines(self, values):
        items = [value for value in values or [] if value]
        if not items:
            return ["- none"]
        return [f"- {value}" for value in items]

    def _unique(self, values):
        seen = set()
        result = []
        for value in values or []:
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _sample_csv_text(self, path, max_rows=5):
        if not path:
            return []
        file_path = Path(path)
        if not file_path.exists():
            return []
        for encoding in ("utf-8-sig", "cp932", "shift_jis"):
            try:
                with file_path.open("r", encoding=encoding, newline="") as handle:
                    reader = csv.reader(handle)
                    rows = []
                    for index, row in enumerate(reader):
                        if index >= max_rows:
                            break
                        rows.append(" ".join(str(value) for value in row if value))
                    return rows
            except (OSError, UnicodeDecodeError, csv.Error):
                continue
        return []

    def _contains_any(self, text, keywords):
        return any(keyword in text for keyword in keywords)

    def _warning_count(self, warning_frequency, needle):
        return sum(count for warning, count in warning_frequency.items() if needle in warning)

    def _summary_comment(self, executed_count, skipped_count, error_count, warning_frequency):
        if not executed_count:
            return "実行できたレースがありません。ペアCSVの配置を確認してください。"
        parts = [f"{executed_count}レースを一括評価しました。"]
        if skipped_count:
            parts.append(f"{skipped_count}レースを除外しました。")
        if error_count:
            parts.append(f"{error_count}レースでエラーが発生しました。")
        if warning_frequency:
            parts.append("Warningがあるため、血統Profileや条件情報の不足を確認してください。")
        else:
            parts.append("重大なWarningはありません。")
        return " ".join(parts)

    def _race_id_from_entry(self, path):
        name = Path(path).name
        if not name.endswith(self.ENTRY_SUFFIX):
            return ""
        return name[: -len(self.ENTRY_SUFFIX)]

    def _race_id_from_horses(self, path):
        name = Path(path).name
        if not name.endswith(self.HORSES_SUFFIX):
            return ""
        return name[: -len(self.HORSES_SUFFIX)]

    def _race_pair_key(self, race_id):
        parts = str(race_id or "").split("_")
        if not parts:
            return str(race_id or "")
        last = parts[-1]
        if last.endswith("R") and last[:-1].isdigit():
            parts[-1] = last[:-1]
        return "_".join(parts)

    def _canonical_race_id(self, race_id):
        parts = str(race_id or "").split("_")
        if not parts:
            return str(race_id or "")
        last = parts[-1]
        if last.isdigit():
            parts[-1] = f"{last}R"
        return "_".join(parts)

    def _file_stem(self, path):
        return Path(path).stem if path else ""

    def _number_or_none(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


if __name__ == "__main__":
    runner = TrialBatchRunner()
    result = runner.run()
    print("TrialBatchRunner")
    print(result.get("metadata"))
    print(result.get("summary"))
    for race in result.get("race_results", []):
        print(
            race.get("race_id"),
            race.get("status"),
            race.get("race_decision"),
            race.get("race_confidence"),
            race.get("top3"),
        )
