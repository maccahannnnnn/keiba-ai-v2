"""BUY Monitoring v1.0.

This module reads existing BUY v1.0 RC1 validation outputs and creates compact
monitoring reports.  It does not change BUY logic, evaluator scores, thresholds,
DecisionEngine behavior, learning records, or source CSV formats.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from review.buy_v1_rc1_validator import main as build_rc1_validation


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "reports" / "buy_v1_rc1_validation"
OUT_DIR = ROOT / "reports" / "buy_monitor"

RACE_FIELDS = [
    "race_id",
    "race_state",
    "buy_count",
    "buy_horses",
    "buy_results",
    "buy_top3_count",
    "buy_place_rate",
    "classification",
]

HORSE_FIELDS = [
    "race_id",
    "horse_name",
    "buy_reason",
    "finish",
    "buy_success",
    "confidence",
    "consensus",
    "risk",
    "rc1_decision",
    "rc1_status",
    "race_state",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def to_int(value, default=None):
    if value in (None, ""):
        return default
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return default


def ensure_sources() -> None:
    """Create current RC1 validation files when they do not already exist."""

    if (SOURCE_DIR / "legacy_comparison.csv").exists() and (SOURCE_DIR / "buy_report.csv").exists():
        return
    build_rc1_validation()


def race_classification(buy_rows: list[dict[str, str]], race_state: str) -> str:
    if race_state == "PLAY_UNCONVERGED_4PLUS":
        return "UNCONVERGED"
    if race_state == "SKIP":
        return "SKIP"
    if not buy_rows:
        return "BUY_ZERO"
    if any(to_int(row.get("actual_finish"), 99) in {1, 2, 3} for row in buy_rows):
        return "BUY_SUCCESS"
    return "BUY_FAILURE"


def build_reports() -> dict[str, object]:
    ensure_sources()
    comparison_rows = read_csv(SOURCE_DIR / "legacy_comparison.csv")
    buy_detail_rows = read_csv(SOURCE_DIR / "buy_report.csv")
    detail_by_key = {
        (row.get("race_id"), row.get("horse_name")): row for row in buy_detail_rows
    }

    rows_by_race: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in comparison_rows:
        rows_by_race[row.get("race_id", "")].append(row)

    race_rows: list[dict[str, object]] = []
    horse_rows: list[dict[str, object]] = []
    race_state_counts = Counter()
    classifications = Counter()

    for race_id, race_horses in sorted(rows_by_race.items()):
        race_state = race_horses[0].get("rc1_race_state", "") if race_horses else ""
        race_state_counts[race_state] += 1
        buy_rows = [row for row in race_horses if row.get("rc1_decision") == "BUY"]
        buy_top3_count = sum(
            1 for row in buy_rows if to_int(row.get("actual_finish"), 99) in {1, 2, 3}
        )
        classification = race_classification(buy_rows, race_state)
        classifications[classification] += 1
        buy_count = len(buy_rows)
        race_rows.append(
            {
                "race_id": race_id,
                "race_state": race_state,
                "buy_count": buy_count,
                "buy_horses": "; ".join(row.get("horse_name", "") for row in buy_rows),
                "buy_results": "; ".join(
                    f"{row.get('horse_name')}:{row.get('actual_finish')}" for row in buy_rows
                ),
                "buy_top3_count": buy_top3_count,
                "buy_place_rate": round(buy_top3_count / buy_count, 3) if buy_count else 0.0,
                "classification": classification,
            }
        )

        for row in buy_rows:
            detail = detail_by_key.get((row.get("race_id"), row.get("horse_name")), {})
            finish = to_int(row.get("actual_finish"), 99)
            consensus = (
                f"positive={detail.get('positive_evaluator_count', '')};"
                f"negative={detail.get('negative_evaluator_count', '')};"
                f"strong_positive={detail.get('strong_positive_count', '')};"
                f"strong_negative={detail.get('strong_negative_count', '')}"
            )
            risk = (
                f"risk_count={detail.get('risk_count', '')};"
                f"risk_guard_pass={detail.get('risk_guard_pass', '')}"
            )
            horse_rows.append(
                {
                    "race_id": row.get("race_id"),
                    "horse_name": row.get("horse_name"),
                    "buy_reason": row.get("rc1_reason"),
                    "finish": row.get("actual_finish"),
                    "buy_success": finish in {1, 2, 3},
                    "confidence": detail.get("confidence", ""),
                    "consensus": consensus,
                    "risk": risk,
                    "rc1_decision": row.get("rc1_decision"),
                    "rc1_status": row.get("rc1_status"),
                    "race_state": row.get("rc1_race_state"),
                }
            )

    buy_count = len(horse_rows)
    buy_success = sum(1 for row in horse_rows if truthy(row.get("buy_success")))
    fn_count = sum(
        1
        for row in comparison_rows
        if truthy(row.get("actual_top3")) and row.get("rc1_decision") != "BUY"
    )
    fp_count = sum(
        1
        for row in comparison_rows
        if row.get("rc1_decision") == "BUY" and not truthy(row.get("actual_top3"))
    )
    buy_success_races = [
        row["race_id"] for row in race_rows if row.get("classification") == "BUY_SUCCESS"
    ]
    buy_failure_races = [
        row["race_id"] for row in race_rows if row.get("classification") == "BUY_FAILURE"
    ]
    unconverged_races = [
        row["race_id"] for row in race_rows if row.get("classification") == "UNCONVERGED"
    ]

    summary = {
        "source": str(SOURCE_DIR),
        "race_count": len(race_rows),
        "horse_count": len(comparison_rows),
        "buy_count": buy_count,
        "buy_success_count": buy_success,
        "buy_success_rate": buy_success / buy_count if buy_count else 0.0,
        "fn": fn_count,
        "fp": fp_count,
        "race_state_counts": dict(race_state_counts),
        "classification_counts": dict(classifications),
        "play_count": race_state_counts.get("PLAY_CONVERGED", 0),
        "skip_count": race_state_counts.get("SKIP", 0),
        "unconverged_count": race_state_counts.get("PLAY_UNCONVERGED_4PLUS", 0),
        "buy_success_races": buy_success_races,
        "buy_failure_races": buy_failure_races,
        "unconverged_races": unconverged_races,
    }

    write_csv(OUT_DIR / "buy_monitor_races.csv", race_rows, RACE_FIELDS)
    write_csv(OUT_DIR / "buy_monitor_horses.csv", horse_rows, HORSE_FIELDS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_summary_md(summary)
    return summary


def write_summary_md(summary: dict[str, object]) -> None:
    lines = [
        "# BUY Monitoring v1.0",
        "",
        "## 集計対象",
        f"- 対象レース数: {summary['race_count']}",
        f"- 対象馬数: {summary['horse_count']}",
        "",
        "## 全体",
        f"- BUY数: {summary['buy_count']}",
        f"- BUY成功数: {summary['buy_success_count']}",
        f"- BUY成功率: {summary['buy_success_rate']:.1%}",
        f"- FN: {summary['fn']}",
        f"- FP: {summary['fp']}",
        "",
        "## RaceState内訳",
        f"- PLAY: {summary['play_count']}",
        f"- SKIP: {summary['skip_count']}",
        f"- UNCONVERGED: {summary['unconverged_count']}",
        "",
        "## BUY成功レース一覧",
    ]
    lines.extend(f"- {race_id}" for race_id in summary["buy_success_races"])
    lines.extend(["", "## BUY失敗レース一覧"])
    lines.extend(f"- {race_id}" for race_id in summary["buy_failure_races"])
    lines.extend(["", "## 未収束レース一覧"])
    lines.extend(f"- {race_id}" for race_id in summary["unconverged_races"])
    lines.extend(
        [
            "",
            "## 注意",
            "- Monitoring専用出力。BUY判定、Evaluator、FinalScore、Threshold、Learningは変更していない。",
        ]
    )
    (OUT_DIR / "buy_monitor_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    summary = build_reports()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
