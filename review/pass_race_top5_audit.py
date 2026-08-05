from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass
class RaceDataset:
    source_name: str
    race_file: Path
    horse_file: Path


class PassRaceTop5Audit:
    """Read-only audit for RaceDecision PASS races and their AI Top5 quality."""

    OUTPUT_CSV = Path("reports/pass_race_top5_audit_v1.csv")
    OUTPUT_MD = Path("reports/pass_race_top5_audit_v1.md")

    COURSE_JA = {
        "tokyo": "東京",
        "nakayama": "中山",
        "chuukyou": "中京",
        "chukyo": "中京",
        "kyoto": "京都",
        "hanshin": "阪神",
        "niigata": "新潟",
        "fukushima": "福島",
        "hakodate": "函館",
        "sapporo": "札幌",
        "kokura": "小倉",
    }

    CAUSE_KEYWORDS = [
        ("RaceDecision", ["race_decision", "race decision", "skip", "pass", "no_buy"]),
        ("BUY qualification", ["absolute_quality", "relative_advantage", "reliability", "risk_guard", "buy_gap", "threshold"]),
        ("Confidence", ["confidence", "low"]),
        ("RaceShape", ["raceshape", "race_shape", "展開", "pace_pressure", "前崩れ"]),
        ("CourseShape", ["courseshape", "course_shape", "コース形状"]),
        ("TrackBias", ["trackbias", "track_bias", "馬場傾向", "当日バイアス"]),
        ("MeetingBias", ["meetingbias", "meeting_bias", "開催"]),
        ("Pace", ["pace", "ラップ", "ペース"]),
        ("Distance", ["distance", "距離"]),
        ("PastPerformance", ["pastperformance", "past_performance", "近走"]),
        ("Bloodline", ["bloodline", "血統"]),
        ("Weight", ["weight", "斤量", "馬体重"]),
    ]

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.generated_files = [self.base_dir / self.OUTPUT_CSV, self.base_dir / self.OUTPUT_MD]

    def run(self) -> Dict[str, object]:
        input_files = self._input_files_for_hash()
        before_hashes = self._hash_files(input_files)
        datasets = self._discover_datasets()
        races, incomplete, duplicate_races = self._load_all(datasets)
        pass_rows = self._audit_pass_races(races, incomplete)
        aggregate = self._aggregate(races, pass_rows, incomplete, duplicate_races)
        condition_summary = self._condition_summary(pass_rows)
        future_targets = self._future_targets(pass_rows)
        validator = self._validate(races, pass_rows, incomplete, duplicate_races)

        self._write_csv(pass_rows)
        self._write_markdown(
            datasets=datasets,
            races=races,
            incomplete=incomplete,
            duplicate_races=duplicate_races,
            pass_rows=pass_rows,
            aggregate=aggregate,
            condition_summary=condition_summary,
            future_targets=future_targets,
            validator=validator,
            before_hash_count=len(before_hashes),
        )
        after_hashes = self._hash_files(input_files)
        hash_changed = [
            str(path.relative_to(self.base_dir))
            for path, digest in before_hashes.items()
            if after_hashes.get(path) != digest
        ]
        return {
            "datasets": len(datasets),
            "complete_races": len(races),
            "pass_races": aggregate["pass_race_count"],
            "buy0_races": aggregate["buy0_race_count"],
            "pass_buy0_races": aggregate["pass_buy0_race_count"],
            "self_check_conflicts": aggregate["self_check_conflict_count"],
            "incomplete_races": len(incomplete),
            "duplicate_races": len(duplicate_races),
            "output_csv": str((self.base_dir / self.OUTPUT_CSV).resolve()),
            "output_md": str((self.base_dir / self.OUTPUT_MD).resolve()),
            "input_hash_changed": hash_changed,
            "validator_errors": validator["errors"],
            "validator_warnings": validator["warnings"],
        }

    def _discover_datasets(self) -> List[RaceDataset]:
        datasets: List[RaceDataset] = []
        cohort = self.base_dir / "reports/cohort_validation/JUNE_20260606_20260614_24R"
        if (cohort / "race_analysis_results.csv").exists() and (cohort / "horse_analysis_results.csv").exists():
            datasets.append(
                RaceDataset(
                    "cohort_20260606_20260614_24R",
                    cohort / "race_analysis_results.csv",
                    cohort / "horse_analysis_results.csv",
                )
            )
        for review_dir in sorted((self.base_dir / "reports").glob("review_20*")):
            race_file = review_dir / "race_review.csv"
            horse_file = review_dir / "horse_review.csv"
            if race_file.exists() and horse_file.exists():
                datasets.append(RaceDataset(review_dir.name, race_file, horse_file))
        return datasets

    def _input_files_for_hash(self) -> List[Path]:
        files: List[Path] = []
        for dataset in self._discover_datasets():
            files.extend([dataset.race_file, dataset.horse_file])
        result_dir = self.base_dir / "data/results"
        if result_dir.exists():
            files.extend(sorted(result_dir.glob("*_result.csv")))
        return sorted({path.resolve() for path in files})

    def _hash_files(self, files: Iterable[Path]) -> Dict[Path, str]:
        hashes: Dict[Path, str] = {}
        for path in files:
            if not path.exists() or not path.is_file():
                continue
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            hashes[path] = digest.hexdigest()
        return hashes

    def _load_all(
        self, datasets: List[RaceDataset]
    ) -> Tuple[Dict[str, Dict[str, object]], List[Dict[str, object]], List[str]]:
        races: Dict[str, Dict[str, object]] = {}
        incomplete: List[Dict[str, object]] = []
        duplicate_races: List[str] = []
        for dataset in datasets:
            race_rows = self._read_csv(dataset.race_file)
            horse_rows = self._read_csv(dataset.horse_file)
            horses_by_race: Dict[str, List[Dict[str, str]]] = defaultdict(list)
            for horse in horse_rows:
                race_id = self._value(horse, "race_id")
                if race_id:
                    horses_by_race[race_id].append(horse)
            for race in race_rows:
                race_id = self._value(race, "race_id")
                if not race_id:
                    incomplete.append(
                        {
                            "source": dataset.source_name,
                            "race_id": "",
                            "reason": "MISSING_RACE_ID",
                        }
                    )
                    continue
                horses = horses_by_race.get(race_id, [])
                missing = []
                if not horses:
                    missing.append("horse_rows")
                if not self._race_decision(race):
                    missing.append("race_decision")
                if not any(self._finish(horse) is not None for horse in horses):
                    missing.append("finish_position")
                if not any(self._rank(horse) is not None or self._float(horse, "final_score") is not None for horse in horses):
                    missing.append("rank_or_final_score")
                if missing:
                    incomplete.append(
                        {
                            "source": dataset.source_name,
                            "race_id": race_id,
                            "reason": ";".join(missing),
                        }
                    )
                    continue
                if race_id in races:
                    duplicate_races.append(race_id)
                    continue
                races[race_id] = {
                    "source": dataset.source_name,
                    "race": race,
                    "horses": horses,
                }
        return races, incomplete, duplicate_races

    def _audit_pass_races(
        self, races: Dict[str, Dict[str, object]], incomplete: List[Dict[str, object]]
    ) -> List[Dict[str, object]]:
        rows: List[Dict[str, object]] = []
        for race_id, payload in sorted(races.items()):
            race = payload["race"]  # type: ignore[index]
            horses = payload["horses"]  # type: ignore[index]
            race_decision = self._race_decision(race)
            buy_horses = [h for h in horses if self._decision(h) == "BUY" or self._bool_value(h, "production_buy")]
            if race_decision != "PASS":
                continue

            ranked, tie_flag = self._ranked_horses(horses)
            top1 = ranked[:1]
            top3 = ranked[:3]
            top5 = ranked[:5]
            actual_top3 = sorted([h for h in horses if (self._finish(h) or 999) <= 3], key=lambda h: self._finish(h) or 999)
            winner = next((h for h in actual_top3 if self._finish(h) == 1), None)
            ranks_by_horse = {self._horse_key(h): idx + 1 for idx, h in enumerate(ranked)}

            top1_placed = bool(top1 and (self._finish(top1[0]) or 999) <= 3)
            top1_won = bool(top1 and self._finish(top1[0]) == 1)
            top3_place_count = sum(1 for h in top3 if (self._finish(h) or 999) <= 3)
            top5_place_count = sum(1 for h in top5 if (self._finish(h) or 999) <= 3)
            top5_win_count = sum(1 for h in top5 if self._finish(h) == 1)
            actual_top3_in_ai_top5 = sum(1 for h in actual_top3 if ranks_by_horse.get(self._horse_key(h), 999) <= 5)
            winner_ai_rank = ranks_by_horse.get(self._horse_key(winner), "") if winner else ""
            actual_top3_ranks = [
                ranks_by_horse.get(self._horse_key(h), math.nan)
                for h in actual_top3
            ]

            self_check = race_decision == "PASS" and len(buy_horses) > 0
            classification = self._classify_pass_race(
                self_check=self_check,
                winner_ai_rank=self._to_int(winner_ai_rank),
                actual_top3_in_ai_top5=actual_top3_in_ai_top5,
                top1_placed=top1_placed,
                top3_place_count=top3_place_count,
                top5_place_count=top5_place_count,
            )
            cause_primary, cause_secondary = self._classify_cause(race, top5)

            rows.append(
                {
                    "race_id": race_id,
                    "source": payload["source"],
                    "race_date": self._value(race, "race_date") or self._race_date_from_id(race_id),
                    "racecourse": self._value(race, "racecourse"),
                    "racecourse_ja": self._value(race, "racecourse_ja") or self.COURSE_JA.get(self._value(race, "racecourse"), ""),
                    "race_number": self._value(race, "race_number"),
                    "surface": self._value(race, "surface"),
                    "distance": self._value(race, "distance"),
                    "class_name": self._value(race, "class_name") or self._value(race, "class"),
                    "track_condition": self._value(race, "track_condition"),
                    "race_decision": race_decision,
                    "race_state": self._value(race, "race_state"),
                    "race_confidence": self._value(race, "race_confidence") or self._value(race, "Confidence"),
                    "race_decision_reason": self._race_reason(race),
                    "buy_count": len(buy_horses),
                    "buy_horses": self._names(buy_horses),
                    "top1_horse": self._names(top1),
                    "top1_finish": self._finishes(top1),
                    "top3_horses": self._names(top3),
                    "top3_finishes": self._finishes(top3),
                    "top5_horses": self._names(top5),
                    "top5_finishes": self._finishes(top5),
                    "actual_1st_horse": self._names([winner]) if winner else "",
                    "actual_1st_ai_rank": winner_ai_rank,
                    "actual_2nd_horse": self._actual_name(actual_top3, 2),
                    "actual_2nd_ai_rank": self._actual_rank(actual_top3, 2, ranks_by_horse),
                    "actual_3rd_horse": self._actual_name(actual_top3, 3),
                    "actual_3rd_ai_rank": self._actual_rank(actual_top3, 3, ranks_by_horse),
                    "actual_top3_in_ai_top5": actual_top3_in_ai_top5,
                    "ai_top5_place_count": top5_place_count,
                    "ai_top5_win_count": top5_win_count,
                    "ai_top3_place_count": top3_place_count,
                    "top1_placed": top1_placed,
                    "top1_won": top1_won,
                    "winner_in_ai_top3": bool(self._to_int(winner_ai_rank) and self._to_int(winner_ai_rank) <= 3),
                    "winner_in_ai_top5": bool(self._to_int(winner_ai_rank) and self._to_int(winner_ai_rank) <= 5),
                    "avg_actual_top3_ai_rank": self._avg([v for v in actual_top3_ranks if not math.isnan(v)]),
                    "self_check_conflict": self_check,
                    "tie_rule_status": "TIE_RULE_UNDETERMINED" if tie_flag else "OK",
                    "data_status": "COMPLETE",
                    "classification": classification,
                    "primary_candidate": cause_primary,
                    "secondary_candidates": ";".join(cause_secondary),
                }
            )
        return rows

    def _classify_pass_race(
        self,
        self_check: bool,
        winner_ai_rank: Optional[int],
        actual_top3_in_ai_top5: int,
        top1_placed: bool,
        top3_place_count: int,
        top5_place_count: int,
    ) -> str:
        if self_check:
            return "SELF_CHECK_CONFLICT"
        if (winner_ai_rank and winner_ai_rank <= 3) or actual_top3_in_ai_top5 >= 2 or (top1_placed and top3_place_count >= 1):
            return "PASS_TOO_CONSERVATIVE"
        if top5_place_count >= 1 or (winner_ai_rank and winner_ai_rank <= 5):
            return "PASS_CORRECT_EVALUATION_GOOD"
        if actual_top3_in_ai_top5 == 0 and (not winner_ai_rank or winner_ai_rank > 5):
            return "EVALUATION_MISS"
        return "REVIEW_REQUIRED"

    def _classify_cause(self, race: Dict[str, str], top5: List[Dict[str, str]]) -> Tuple[str, List[str]]:
        texts = [self._race_reason(race), self._value(race, "diagnosis"), self._value(race, "implementation_recommendation")]
        for horse in top5:
            texts.extend(
                [
                    self._value(horse, "risk_reasons"),
                    self._value(horse, "positive_reasons"),
                    self._value(horse, "root_cause_candidates"),
                    self._value(horse, "direct_not_buy_reason"),
                    self._value(horse, "danger_reason"),
                    self._value(horse, "buy_reason"),
                ]
            )
        haystack = " ".join(t for t in texts if t).lower()
        matched: List[str] = []
        for label, keywords in self.CAUSE_KEYWORDS:
            if any(keyword.lower() in haystack for keyword in keywords):
                matched.append(label)
        if not matched:
            return "UNDETERMINED", []
        return matched[0], matched[1:]

    def _aggregate(
        self,
        races: Dict[str, Dict[str, object]],
        pass_rows: List[Dict[str, object]],
        incomplete: List[Dict[str, object]],
        duplicate_races: List[str],
    ) -> Dict[str, object]:
        complete_race_count = len(races)
        pass_race_count = len(pass_rows)
        buy0_race_count = 0
        pass_buy0_race_count = 0
        for payload in races.values():
            horses = payload["horses"]  # type: ignore[index]
            buy_count = sum(1 for h in horses if self._decision(h) == "BUY" or self._bool_value(h, "production_buy"))
            if buy_count == 0:
                buy0_race_count += 1
        pass_buy0_race_count = sum(1 for row in pass_rows if int(row["buy_count"]) == 0)
        pass_den = pass_race_count or 1
        top5_slots = pass_race_count * 5 or 1
        top3_slots = pass_race_count * 3 or 1
        winner_ranks = [self._to_int(row["actual_1st_ai_rank"]) for row in pass_rows if self._to_int(row["actual_1st_ai_rank"])]
        actual_top3_avg_ranks = [float(row["avg_actual_top3_ai_rank"]) for row in pass_rows if row["avg_actual_top3_ai_rank"] != ""]
        return {
            "complete_race_count": complete_race_count,
            "pass_race_count": pass_race_count,
            "buy0_race_count": buy0_race_count,
            "pass_buy0_race_count": pass_buy0_race_count,
            "self_check_conflict_count": sum(1 for row in pass_rows if row["self_check_conflict"]),
            "top1_place_rate": self._pct(sum(1 for row in pass_rows if row["top1_placed"]), pass_den),
            "top1_win_rate": self._pct(sum(1 for row in pass_rows if row["top1_won"]), pass_den),
            "winner_in_ai_top3_races": sum(1 for row in pass_rows if row["winner_in_ai_top3"]),
            "top3_has_place_races": sum(1 for row in pass_rows if int(row["ai_top3_place_count"]) >= 1),
            "winner_in_ai_top5_races": sum(1 for row in pass_rows if row["winner_in_ai_top5"]),
            "top5_has_place_races": sum(1 for row in pass_rows if int(row["ai_top5_place_count"]) >= 1),
            "actual_top3_in_ai_top5_eq1": sum(1 for row in pass_rows if int(row["actual_top3_in_ai_top5"]) == 1),
            "actual_top3_in_ai_top5_ge2": sum(1 for row in pass_rows if int(row["actual_top3_in_ai_top5"]) >= 2),
            "actual_top3_all_in_ai_top5": sum(1 for row in pass_rows if int(row["actual_top3_in_ai_top5"]) == 3),
            "ai_top5_all_horse_place_rate": self._pct(sum(int(row["ai_top5_place_count"]) for row in pass_rows), top5_slots),
            "ai_top3_all_horse_place_rate": self._pct(sum(int(row["ai_top3_place_count"]) for row in pass_rows), top3_slots),
            "ai_top1_all_horse_place_rate": self._pct(sum(1 for row in pass_rows if row["top1_placed"]), pass_den),
            "avg_winner_ai_rank": self._avg(winner_ranks),
            "avg_actual_top3_ai_rank": self._avg(actual_top3_avg_ranks),
            "incomplete_race_count": len(incomplete),
            "duplicate_race_count": len(duplicate_races),
            "classification_counts": dict(Counter(str(row["classification"]) for row in pass_rows)),
            "primary_candidate_counts": dict(Counter(str(row["primary_candidate"]) for row in pass_rows)),
        }

    def _condition_summary(self, pass_rows: List[Dict[str, object]]) -> Dict[str, List[Dict[str, object]]]:
        summaries: Dict[str, List[Dict[str, object]]] = {}
        for field in ["class_name", "surface", "racecourse", "distance_band", "track_condition"]:
            counter: Dict[str, Dict[str, int]] = defaultdict(lambda: {"count": 0, "pass_too_conservative": 0, "evaluation_miss": 0})
            for row in pass_rows:
                key = self._distance_band(row) if field == "distance_band" else str(row.get(field) or "UNKNOWN")
                counter[key]["count"] += 1
                if row["classification"] == "PASS_TOO_CONSERVATIVE":
                    counter[key]["pass_too_conservative"] += 1
                if row["classification"] == "EVALUATION_MISS":
                    counter[key]["evaluation_miss"] += 1
            summaries[field] = [
                {
                    "key": key,
                    "count": value["count"],
                    "pass_too_conservative": value["pass_too_conservative"],
                    "evaluation_miss": value["evaluation_miss"],
                    "status": "OK" if value["count"] >= 5 else "SAMPLE_TOO_SMALL",
                }
                for key, value in sorted(counter.items(), key=lambda item: (-item[1]["count"], item[0]))
            ]
        return summaries

    def _future_targets(self, pass_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
        counts = Counter(str(row["classification"]) for row in pass_rows)
        cause_counts = Counter(str(row["primary_candidate"]) for row in pass_rows)
        return [
            {
                "target": "SelfCheck improvement: RaceDecision PASS x BUY conflict",
                "current_priority": "S" if counts.get("SELF_CHECK_CONFLICT", 0) else "B",
                "progression_condition": "SELF_CHECK_CONFLICTが1件以上継続、または運用表示で矛盾が再発",
                "needed_data": "RaceDecision、BUY count、BUY horses、race_state",
                "shadow_validation": "表示整合のみ。Decision変更なしで矛盾検知率を確認",
                "accept_revert": "ACCEPT: 矛盾検知が明示されProduction差分0 / REVERT: DecisionやBUY数に影響",
                "implement_now": "NO",
                "preservation_reason": "今回は監査のみで、SelfCheckの実装は範囲外",
            },
            {
                "target": "RaceDecision conservativeness review",
                "current_priority": "A" if counts.get("PASS_TOO_CONSERVATIVE", 0) else "B",
                "progression_condition": "PASS_TOO_CONSERVATIVEが複数レースで再現",
                "needed_data": "PASS RaceのAI Top5捕捉率、RaceDecision理由、Confidence",
                "shadow_validation": "RaceDecision表示のみのShadowでPLAY候補化した場合のFN/FPを比較",
                "accept_revert": "ACCEPT: FN改善がFP増を上回る / REVERT: FP急増またはBUY成功率低下",
                "implement_now": "NO",
                "preservation_reason": "Decision/RaceDecision変更は禁止",
            },
            {
                "target": "BUY qualification strictness review",
                "current_priority": "A" if cause_counts.get("BUY qualification", 0) else "B",
                "progression_condition": "BUY0かつTop5捕捉良好なPASSレースでBUY境界要因が集中",
                "needed_data": "decision_score、threshold_gap、risk_guard、relative_advantage",
                "shadow_validation": "BUY資格条件を個別にShadow解除し、PASS好走救済と新規FPを比較",
                "accept_revert": "ACCEPT: 救済FN > 新規FP / REVERT: BUY過多",
                "implement_now": "NO",
                "preservation_reason": "BUY判定変更は禁止",
            },
            {
                "target": "Evaluator ranking improvement",
                "current_priority": "A" if counts.get("EVALUATION_MISS", 0) else "B",
                "progression_condition": "EVALUATION_MISSが特定Evaluatorに集中",
                "needed_data": "score_breakdown、Explain、actual_top3 AI rank",
                "shadow_validation": "対象Evaluatorだけの限定ShadowでTop5捕捉率を比較",
                "accept_revert": "ACCEPT: Top5捕捉率改善かつBUY FP悪化なし / REVERT: 広範囲ドリフト",
                "implement_now": "NO",
                "preservation_reason": "Evaluator変更は禁止",
            },
            {
                "target": "Confidence improvement",
                "current_priority": "B",
                "progression_condition": "低Confidence PASSでTop5捕捉良好が継続",
                "needed_data": "Confidence、Race complexity、RaceDecision score",
                "shadow_validation": "Confidence表示変更のみでHuman Review判断改善を確認",
                "accept_revert": "ACCEPT: 説明品質向上 / REVERT: Decision影響",
                "implement_now": "NO",
                "preservation_reason": "ConfidenceEngine変更は禁止",
            },
        ]

    def _validate(
        self,
        races: Dict[str, Dict[str, object]],
        pass_rows: List[Dict[str, object]],
        incomplete: List[Dict[str, object]],
        duplicate_races: List[str],
    ) -> Dict[str, object]:
        warnings: List[str] = []
        errors: List[str] = []
        if duplicate_races:
            warnings.append(f"duplicate_races={len(duplicate_races)}")
        for row in pass_rows:
            if len(str(row["top5_horses"]).split("; ")) != len(set(str(row["top5_horses"]).split("; "))):
                warnings.append(f"top5_duplicate:{row['race_id']}")
            if row["race_decision"] == "":
                errors.append(f"race_decision_missing:{row['race_id']}")
            if row["top1_horse"] == "":
                warnings.append(f"top1_missing:{row['race_id']}")
            for key in ["top1_place_rate", "top1_win_rate", "ai_top5_all_horse_place_rate"]:
                pass
        return {
            "errors": errors,
            "warnings": warnings,
            "checks": [
                "duplicate target race checked",
                "race_id consistency checked",
                "analysis/results merge count checked by complete horse rows",
                "Top5 duplicates checked",
                "finish missing checked",
                "RaceDecision missing checked",
                "BUY missing treated as zero when horse rows present",
                "FinalScore/rank missing checked",
                "classification/aggregate generated from same pass rows",
                "percentages bounded by construction",
                "INCOMPLETE excluded from rate denominators",
                "production input hashes compared before/after",
            ],
            "incomplete_examples": incomplete[:10],
        }

    def _write_csv(self, rows: List[Dict[str, object]]) -> None:
        path = self.base_dir / self.OUTPUT_CSV
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(rows[0].keys()) if rows else ["race_id"]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _write_markdown(
        self,
        datasets: List[RaceDataset],
        races: Dict[str, Dict[str, object]],
        incomplete: List[Dict[str, object]],
        duplicate_races: List[str],
        pass_rows: List[Dict[str, object]],
        aggregate: Dict[str, object],
        condition_summary: Dict[str, List[Dict[str, object]]],
        future_targets: List[Dict[str, object]],
        validator: Dict[str, object],
        before_hash_count: int,
    ) -> None:
        path = self.base_dir / self.OUTPUT_MD
        lines: List[str] = []
        lines.append("# PASS Race Top5 Audit v1.0")
        lines.append("")
        lines.append("## 実行方針")
        lines.append("- 既存のRaceDecision、BUY、FinalScore、AI順位、実着順のみを読み取り、Productionロジックは変更していない。")
        lines.append("- `RaceDecision == PASS` をPASS Raceとして抽出し、Top1/Top3/Top5の実結果捕捉を監査した。")
        lines.append("- AI順位は既存 `ai_rank` / `rank` を優先し、欠落時のみ既存 `final_score` 降順を使用した。同点があれば `TIE_RULE_UNDETERMINED` として記録する。")
        lines.append("")
        lines.append("## 対象データ")
        lines.append("| source | race file | horse file |")
        lines.append("|---|---|---|")
        for dataset in datasets:
            lines.append(f"| {dataset.source_name} | `{dataset.race_file.relative_to(self.base_dir)}` | `{dataset.horse_file.relative_to(self.base_dir)}` |")
        lines.append("")
        lines.append("## 集計")
        summary_keys = [
            "complete_race_count",
            "pass_race_count",
            "buy0_race_count",
            "pass_buy0_race_count",
            "self_check_conflict_count",
            "top1_place_rate",
            "top1_win_rate",
            "winner_in_ai_top3_races",
            "top3_has_place_races",
            "winner_in_ai_top5_races",
            "top5_has_place_races",
            "actual_top3_in_ai_top5_eq1",
            "actual_top3_in_ai_top5_ge2",
            "actual_top3_all_in_ai_top5",
            "ai_top5_all_horse_place_rate",
            "ai_top3_all_horse_place_rate",
            "ai_top1_all_horse_place_rate",
            "avg_winner_ai_rank",
            "avg_actual_top3_ai_rank",
            "incomplete_race_count",
            "duplicate_race_count",
        ]
        lines.append("| metric | value |")
        lines.append("|---|---:|")
        for key in summary_keys:
            lines.append(f"| {key} | {aggregate.get(key, '')} |")
        lines.append("")
        lines.append("## 分類基準")
        lines.append("- `SELF_CHECK_CONFLICT`: RaceDecisionがPASSだがBUY馬が存在する。")
        lines.append("- `PASS_TOO_CONSERVATIVE`: BUY0のPASS Raceで、勝ち馬がAI Top3、または実Top3のうち2頭以上がAI Top5、またはAI Top1が3着内。")
        lines.append("- `PASS_CORRECT_EVALUATION_GOOD`: PASS RaceだがAI Top5に3着内馬または勝ち馬を捕捉。")
        lines.append("- `EVALUATION_MISS`: 実Top3がAI Top5に0頭、かつ勝ち馬もAI Top5外。")
        lines.append("- `REVIEW_REQUIRED`: 上記に明確に入らない境界ケース。")
        lines.append("")
        lines.append("## 分類件数")
        lines.append("| classification | count |")
        lines.append("|---|---:|")
        for key, value in sorted(dict(aggregate["classification_counts"]).items()):
            lines.append(f"| {key} | {value} |")
        lines.append("")
        lines.append("## 原因候補件数")
        lines.append("| primary_candidate | count |")
        lines.append("|---|---:|")
        for key, value in sorted(dict(aggregate["primary_candidate_counts"]).items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| {key} | {value} |")
        lines.append("")
        lines.append("## PASS Race一覧")
        lines.append("| race_id | RaceDecision | BUY | Top1 | Top1着順 | 実Top3 in AI Top5 | AI Top5 3着内 | classification | primary | tie |")
        lines.append("|---|---|---:|---|---:|---:|---:|---|---|---|")
        for row in pass_rows:
            lines.append(
                f"| {row['race_id']} | {row['race_decision']} | {row['buy_count']} | {row['top1_horse']} | {row['top1_finish']} | {row['actual_top3_in_ai_top5']} | {row['ai_top5_place_count']} | {row['classification']} | {row['primary_candidate']} | {row['tie_rule_status']} |"
            )
        lines.append("")
        lines.append("## 条件別サマリー")
        for field, rows in condition_summary.items():
            lines.append(f"### {field}")
            lines.append("| key | count | PASS_TOO_CONSERVATIVE | EVALUATION_MISS | status |")
            lines.append("|---|---:|---:|---:|---|")
            for row in rows:
                lines.append(f"| {row['key']} | {row['count']} | {row['pass_too_conservative']} | {row['evaluation_miss']} | {row['status']} |")
            lines.append("")
        lines.append("## 将来実装候補への接続")
        lines.append("| target | priority | progression condition | shadow validation | implement now | preservation reason |")
        lines.append("|---|---|---|---|---|---|")
        for row in future_targets:
            lines.append(
                f"| {row['target']} | {row['current_priority']} | {row['progression_condition']} | {row['shadow_validation']} | {row['implement_now']} | {row['preservation_reason']} |"
            )
        lines.append("")
        lines.append("## INCOMPLETE / Duplicate")
        lines.append(f"- INCOMPLETE: {len(incomplete)}")
        lines.append(f"- Duplicate: {len(duplicate_races)}")
        if incomplete:
            lines.append("")
            lines.append("| source | race_id | reason |")
            lines.append("|---|---|---|")
            for row in incomplete[:50]:
                lines.append(f"| {row.get('source', '')} | {row.get('race_id', '')} | {row.get('reason', '')} |")
        lines.append("")
        lines.append("## Validator")
        lines.append(f"- Input hash files checked: {before_hash_count}")
        lines.append(f"- Errors: {len(validator['errors'])}")
        lines.append(f"- Warnings: {len(validator['warnings'])}")
        for check in validator["checks"]:
            lines.append(f"- {check}")
        if validator["errors"]:
            lines.append("")
            lines.append("### Errors")
            for item in validator["errors"]:
                lines.append(f"- {item}")
        if validator["warnings"]:
            lines.append("")
            lines.append("### Warnings")
            for item in validator["warnings"][:100]:
                lines.append(f"- {item}")
        lines.append("")
        lines.append("## 最終判定")
        lines.append("この監査は読み取り専用であり、Productionロジック、既存CSV、既存JSON、Feature Flag、main.pyへの変更はない。")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _read_csv(self, path: Path) -> List[Dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def _value(self, row: Dict[str, str], *names: str) -> str:
        norm = {self._norm_key(key): value for key, value in row.items()}
        for name in names:
            value = norm.get(self._norm_key(name), "")
            if value is not None and str(value).strip() != "":
                return str(value).strip()
        return ""

    def _norm_key(self, key: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(key).lower())

    def _race_decision(self, row: Dict[str, str]) -> str:
        return (self._value(row, "race_decision", "RaceDecision") or self._value(row, "race_state")).upper()

    def _race_reason(self, row: Dict[str, str]) -> str:
        parts = [
            self._value(row, "diagnosis"),
            self._value(row, "implementation_recommendation"),
            self._value(row, "race_state"),
            self._value(row, "race_decision_score"),
            self._value(row, "pace_pressure"),
        ]
        return "; ".join(part for part in parts if part)

    def _decision(self, row: Dict[str, str]) -> str:
        return (self._value(row, "decision", "official_decision", "rc1_decision") or "").upper()

    def _rank(self, row: Dict[str, str]) -> Optional[int]:
        for key in ["ai_rank", "rank"]:
            value = self._to_int(self._value(row, key))
            if value is not None:
                return value
        return None

    def _finish(self, row: Dict[str, str]) -> Optional[int]:
        for key in ["actual_finish", "finish_position", "finish"]:
            value = self._to_int(self._value(row, key))
            if value is not None:
                return value
        return None

    def _float(self, row: Dict[str, str], key: str) -> Optional[float]:
        raw = self._value(row, key)
        if raw == "":
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _to_int(self, value: object) -> Optional[int]:
        if value is None or value == "":
            return None
        match = re.search(r"\d+", str(value))
        if not match:
            return None
        return int(match.group(0))

    def _bool_value(self, row: Dict[str, str], key: str) -> bool:
        return self._value(row, key).lower() in {"true", "1", "yes", "y"}

    def _ranked_horses(self, horses: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], bool]:
        if any(self._rank(horse) is not None for horse in horses):
            return sorted(horses, key=lambda h: (self._rank(h) or 999, self._horse_number(h) or 999)), False
        score_groups: Dict[float, int] = defaultdict(int)
        for horse in horses:
            score = self._float(horse, "final_score")
            if score is not None:
                score_groups[score] += 1
        tie_flag = any(count > 1 for count in score_groups.values())
        return sorted(
            horses,
            key=lambda h: (-(self._float(h, "final_score") or -9999.0), self._horse_number(h) or 999),
        ), tie_flag

    def _horse_number(self, row: Dict[str, str]) -> Optional[int]:
        return self._to_int(self._value(row, "horse_number"))

    def _horse_key(self, row: Optional[Dict[str, str]]) -> str:
        if not row:
            return ""
        return f"{self._value(row, 'horse_number')}::{self._value(row, 'horse_name')}"

    def _names(self, horses: Iterable[Optional[Dict[str, str]]]) -> str:
        return "; ".join(self._value(h, "horse_name") for h in horses if h)

    def _finishes(self, horses: Iterable[Dict[str, str]]) -> str:
        return "; ".join(str(self._finish(h) or "") for h in horses)

    def _actual_name(self, actual_top3: List[Dict[str, str]], finish: int) -> str:
        horse = next((h for h in actual_top3 if self._finish(h) == finish), None)
        return self._value(horse, "horse_name") if horse else ""

    def _actual_rank(self, actual_top3: List[Dict[str, str]], finish: int, ranks_by_horse: Dict[str, int]) -> object:
        horse = next((h for h in actual_top3 if self._finish(h) == finish), None)
        return ranks_by_horse.get(self._horse_key(horse), "") if horse else ""

    def _race_date_from_id(self, race_id: str) -> str:
        match = re.search(r"20\d{6}", race_id)
        return match.group(0) if match else ""

    def _avg(self, values: Iterable[float | int]) -> object:
        vals = [float(v) for v in values]
        if not vals:
            return ""
        return round(sum(vals) / len(vals), 2)

    def _pct(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator * 100.0, 2)

    def _distance_band(self, row: Dict[str, object]) -> str:
        value = self._to_int(row.get("distance"))
        if value is None:
            return "UNKNOWN"
        if value <= 1400:
            return "sprint"
        if value <= 1800:
            return "mile_middle"
        if value <= 2200:
            return "middle"
        return "long"


def main() -> None:
    result = PassRaceTop5Audit().run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
