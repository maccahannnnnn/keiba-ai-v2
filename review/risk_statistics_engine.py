from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping


DECISIONS = ("BUY", "CAUTION", "PASS")


class RiskStatisticsEngine:
    """Aggregate risk reason statistics from review horse CSV files."""

    INPUT_PATTERN = "reports/review_*/horse_review.csv"

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()

    def find_input_files(self, pattern: str | None = None) -> List[Path]:
        pattern = pattern or self.INPUT_PATTERN
        return sorted(self.base_dir.glob(pattern))

    def load_rows(self, files: Iterable[Path] | None = None) -> List[Dict[str, str]]:
        paths = list(files) if files is not None else self.find_input_files()
        rows: List[Dict[str, str]] = []
        for path in paths:
            text = self._read_text_with_best_encoding(path)
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                normalized = {key: (value or "").strip() for key, value in row.items()}
                normalized["_source_file"] = str(path)
                rows.append(normalized)
        return rows

    def split_risk_reasons(self, text: str | None) -> List[str]:
        if not text or not text.strip():
            return ["NO_RISK_REASON"]
        parts = re.split(r"[;；\n\r|]+", text)
        reasons = [part.strip() for part in parts if part and part.strip()]
        return reasons or ["NO_RISK_REASON"]

    def categorize_reason(self, reason: str) -> str:
        value = reason.lower()
        if reason == "NO_RISK_REASON":
            return "NO_RISK_REASON"
        if self._contains(value, ["構造評価", "入力", "情報不足", "不足", "not found", "profile"]):
            return "INPUT_LIMITATION"
        if self._contains(value, ["展開", "ラップ", "pace", "前半", "後半", "脚質"]):
            return "PACE_RISK"
        if self._contains(value, ["コース", "形状", "course"]):
            return "COURSE_RISK"
        if self._contains(value, ["距離", "distance"]):
            return "DISTANCE_RISK"
        if self._contains(value, ["馬場", "track", "バイアス", "bias"]):
            return "TRACK_RISK"
        if self._contains(value, ["血統", "blood", "sire", "dam"]):
            return "BLOODLINE_RISK"
        if self._contains(value, ["体重", "斤量", "weight"]):
            return "WEIGHT_RISK"
        if self._contains(value, ["condition", "状態", "調子"]):
            return "CONDITION_RISK"
        if self._contains(value, ["decision", "confidence", "conflict", "guard", "risk"]):
            return "DECISION_RISK"
        return "OTHER_RISK"

    def categorize_input_limitation(self, reason: str) -> str:
        value = reason.lower()
        if self._contains(value, ["raceshape", "race_shape", "構造評価", "構造"]):
            return "RaceShape"
        if self._contains(value, ["trackbias", "track_bias", "バイアス"]):
            return "TrackBias"
        if self._contains(value, ["courseknowledge", "course_knowledge", "コース", "course"]):
            return "CourseKnowledge"
        if self._contains(value, ["pace", "展開", "ラップ"]):
            return "Pace"
        if self._contains(value, ["blood", "bloodline", "血統", "sire", "dam"]):
            return "Blood"
        if self._contains(value, ["past", "過去", "近走"]):
            return "PastPerformance"
        return "Unknown"

    def aggregate_by_reason(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        stats: Dict[str, Dict[str, object]] = defaultdict(lambda: self._new_stat())
        for row in rows:
            reasons = sorted(set(self.split_risk_reasons(row.get("risk_reasons"))))
            for reason in reasons:
                stats[reason]["risk_reason"] = reason
                stats[reason]["risk_category"] = self.categorize_reason(reason)
                self._add_row(stats[reason], row)
        return self._finalize(stats.values())

    def aggregate_by_category(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        stats: Dict[str, Dict[str, object]] = defaultdict(lambda: self._new_stat())
        for row in rows:
            categories = sorted(
                {self.categorize_reason(reason) for reason in self.split_risk_reasons(row.get("risk_reasons"))}
            )
            for category in categories:
                stats[category]["risk_category"] = category
                self._add_row(stats[category], row)
        return self._finalize(stats.values(), primary_key="risk_category")

    def aggregate_top5_pass(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        stats: Dict[str, Dict[str, object]] = defaultdict(lambda: self._new_stat())
        for row in rows:
            if not self.is_top5(row) or self.decision(row) != "PASS":
                continue
            categories = sorted(
                {self.categorize_reason(reason) for reason in self.split_risk_reasons(row.get("risk_reasons"))}
            )
            for category in categories:
                stats[category]["risk_category"] = category
                self._add_row(stats[category], row)
        return self._finalize(stats.values(), primary_key="risk_category")

    def aggregate_input_limitations(self, rows: Iterable[Mapping[str, str]]) -> List[Dict[str, object]]:
        stats: Dict[str, Dict[str, object]] = defaultdict(lambda: self._new_stat())
        for row in rows:
            subcategories = set()
            for reason in self.split_risk_reasons(row.get("risk_reasons")):
                if self.categorize_reason(reason) == "INPUT_LIMITATION":
                    subcategories.add(self.categorize_input_limitation(reason))
            for subcategory in sorted(subcategories):
                stats[subcategory]["input_limitation_category"] = subcategory
                self._add_row(stats[subcategory], row)
        return self._finalize(stats.values(), primary_key="input_limitation_category")

    def summarize_overall(self, rows: Iterable[Mapping[str, str]]) -> Dict[str, object]:
        rows_list = list(rows)
        races = sorted({row.get("race_id", "") for row in rows_list if row.get("race_id")})
        summary: Dict[str, object] = {
            "race_count": len(races),
            "horse_count": len(rows_list),
            "top5_count": sum(1 for row in rows_list if self.is_top5(row)),
            "top5_pass_count": sum(1 for row in rows_list if self.is_top5(row) and self.decision(row) == "PASS"),
        }
        for decision in DECISIONS:
            summary[decision] = sum(1 for row in rows_list if self.decision(row) == decision)
        summary["actual_top3"] = sum(1 for row in rows_list if self.is_actual_top3(row))
        summary["actual_top5"] = sum(1 for row in rows_list if self.is_actual_top5(row))
        summary["top5_pass_actual_top3"] = sum(
            1 for row in rows_list if self.is_top5(row) and self.decision(row) == "PASS" and self.is_actual_top3(row)
        )
        summary["top5_pass_actual_top5"] = sum(
            1 for row in rows_list if self.is_top5(row) and self.decision(row) == "PASS" and self.is_actual_top5(row)
        )
        summary["race_ids"] = races
        return summary

    def decision(self, row: Mapping[str, str]) -> str:
        return (row.get("decision") or "").strip().upper()

    def is_top5(self, row: Mapping[str, str]) -> bool:
        return self._to_int(row.get("ai_rank")) <= 5

    def is_actual_top3(self, row: Mapping[str, str]) -> bool:
        return self._to_bool(row.get("actual_top3")) or self._to_int(row.get("actual_finish")) <= 3

    def is_actual_top5(self, row: Mapping[str, str]) -> bool:
        return self._to_bool(row.get("actual_top5")) or self._to_int(row.get("actual_finish")) <= 5

    def _new_stat(self) -> Dict[str, object]:
        return {
            "risk_reason": "",
            "risk_category": "",
            "input_limitation_category": "",
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

    def _add_row(self, stat: Dict[str, object], row: Mapping[str, str]) -> None:
        stat["count"] = int(stat["count"]) + 1
        decision = self.decision(row)
        if decision in DECISIONS:
            stat[decision] = int(stat[decision]) + 1
        top5 = self.is_top5(row)
        if top5:
            stat["top5_count"] = int(stat["top5_count"]) + 1
        else:
            stat["non_top5_count"] = int(stat["non_top5_count"]) + 1
        if self.is_actual_top3(row):
            stat["actual_top3"] = int(stat["actual_top3"]) + 1
            if top5:
                stat["top5_actual_top3"] = int(stat["top5_actual_top3"]) + 1
        if self.is_actual_top5(row):
            stat["actual_top5"] = int(stat["actual_top5"]) + 1
            if top5:
                stat["top5_actual_top5"] = int(stat["top5_actual_top5"]) + 1

    def _finalize(self, stats: Iterable[Dict[str, object]], primary_key: str = "risk_reason") -> List[Dict[str, object]]:
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

    def _to_bool(self, value: str | None) -> bool:
        return str(value or "").strip().lower() in {"true", "1", "yes", "y"}

    def _to_int(self, value: str | None) -> int:
        try:
            return int(float(str(value or "").strip()))
        except ValueError:
            return 10**9

    def _contains(self, value: str, needles: Iterable[str]) -> bool:
        return any(needle.lower() in value for needle in needles)

    def _read_text_with_best_encoding(self, path: Path) -> str:
        data = path.read_bytes()
        candidates = []
        for encoding in ("utf-8-sig", "cp932"):
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError:
                continue
            candidates.append((self._mojibake_score(text), text))
        if not candidates:
            return data.decode("utf-8-sig", errors="replace")
        return min(candidates, key=lambda item: item[0])[1]

    def _mojibake_score(self, text: str) -> int:
        markers = ("繧", "縺", "荳", "螻", "諠", "蜷", "譁", "�")
        return sum(text.count(marker) for marker in markers)
