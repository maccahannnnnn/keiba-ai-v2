"""Metadata/PRE-only population inventory; never open Result CSV contents."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/prediction_input"
RESULT_DIR = ROOT / "data/raw/target/daily_result_list"
OUT = ROOT / "reports/current_population_audit_v1"
COHORT = ROOT / "reports/pl_current_race_selection_dev_diagnostic_v1/selected_horses.csv"
META = ROOT / "reports/pl_current_race_selection_dev_diagnostic_v1/diagnostic_metadata.json"
SECONDARY = ROOT / "reports/full_field_redesign_iteration2_v1/secondary_metrics.csv"
BUDGET = ROOT / "reports/full_field_redesign_iteration2_v1/daily_current_buy_budget.csv"
DECEMBER = ROOT / "reports/december_2025_three_lane_one_shot_holdout_pre/population_freeze.json"
JANUARY = ROOT / "reports/selection_authority_protocol_v1_january_2026_historical_holdout/realized_population_manifest.json"
APRIL_CORRECTION = ROOT / "reports/ml_v4_buy_selection_dataset_v5_source_lineage_correction_20260418_v1/correction.json"
AUGUST_EXCLUSION = ROOT / "reports/ws2_known_data_integrity_exclusion_bridge_20260823_v1/exclusion_bridge.json"
COURSE = {
    "札幌": "sapporo", "函館": "hakodate", "福島": "fukushima",
    "新潟": "niigata", "東京": "tokyo", "中山": "nakayama",
    "中京": "chuukyou", "京都": "kyoto", "阪神": "hanshin", "小倉": "kokura",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name: str, obj: object) -> None:
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(name: str, rows: list[dict], fields: list[str]) -> None:
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if OUT.exists():
        raise RuntimeError("STOP_EXISTING_OUTPUT_ROOT")
    cohort_rows = list(csv.DictReader(COHORT.open(encoding="utf-8-sig", newline="")))
    metadata = json.loads(META.read_text(encoding="utf-8"))
    secondary = list(csv.DictReader(SECONDARY.open(encoding="utf-8-sig", newline="")))
    budget = list(csv.DictReader(BUDGET.open(encoding="utf-8-sig", newline="")))
    december = json.loads(DECEMBER.read_text(encoding="utf-8"))
    january = json.loads(JANUARY.read_text(encoding="utf-8"))
    if (december["eligible_races"], january["eligible_population_races"]) != (146, 149):
        raise RuntimeError("STOP_HISTORICAL_HOLDOUT_AUTHORITY_CHANGED")
    eval_races = {row["race_id"] for row in cohort_rows}
    eval_dates = {row["date"] for row in cohort_rows}
    buy_races = {row["race_id"] for row in cohort_rows if row["C"] == "True"}
    if (len(eval_dates), len(eval_races), len(buy_races)) != (53, 951, 432):
        raise RuntimeError("STOP_COHORT_AUTHORITY_COUNT_MISMATCH")
    if int(metadata["races"]) != 951 or int(metadata["current_buy_races"]) != 432:
        raise RuntimeError("STOP_METADATA_COHORT_MISMATCH")
    current_secondary = next(row for row in secondary if row["comparator"] == "CURRENT_GLOBAL")
    if int(current_secondary["selected_races"]) != 432:
        raise RuntimeError("STOP_ITER2_SECONDARY_MISMATCH")

    source_files: dict[str, dict[str, Path]] = defaultdict(dict)
    for kind in ("DG", "DE", "DS"):
        for path in RAW.glob(f"{kind}??????.CSV"):
            day = "20" + path.name[2:8]
            if "20251201" <= day <= "20261025":
                source_files[day][kind] = path
    result_dates = {
        path.stem[-8:]
        for path in RESULT_DIR.glob("*.csv")
        if len(path.stem) >= 8 and path.stem[-8:].isdigit()
        and "20251201" <= path.stem[-8:] <= "20261025"
    }
    observed_dates = sorted(set(source_files) | result_dates)
    raw_dates = sorted(source_files)
    if len(raw_dates) != 94 or any(set(source_files[d]) != {"DG", "DE", "DS"} for d in raw_dates):
        raise RuntimeError("STOP_SOURCE_DATE_SET_CHANGED")

    races: list[dict] = []
    date_rows: list[dict] = []
    source_sha: dict[str, dict[str, str]] = {}
    for date in observed_dates:
        paths = source_files.get(date, {})
        if not paths:
            date_rows.append({"date": date, "dg_de_ds_present": False, "result_filename_present": True,
                              "evidence_role": "UNRESOLVED_RESULT_ONLY_DATE", "authority": "Result filenames only; content not read"})
            continue
        source_sha[date] = {kind: digest(path) for kind, path in paths.items()}
        dg = list(csv.reader(paths["DG"].open(encoding="cp932", newline="")))
        de = list(csv.reader(paths["DE"].open(encoding="cp932", newline="")))
        de_counts = Counter((row[1], int(row[2])) for row in de)
        dg_keys = {(row[3], int(row[4])) for row in dg}
        if dg_keys != set(de_counts):
            raise RuntimeError(f"STOP_DG_DE_RACE_SET_MISMATCH:{date}")
        for row in dg:
            venue, number = row[3], int(row[4])
            race_id = f"race_{date}_{COURSE[venue]}_{number}R"
            race_text = " ".join(row[5:8])
            obstacle = "障害" in race_text
            newcomer = "新馬" in race_text
            if obstacle:
                status, reason = "EXCLUDED_OBSTACLE", "DG surface/race text contains 障害; original source version retained"
            elif newcomer:
                status, reason = "EXCLUDED_NEWCOMER", "DG race text contains 新馬"
            elif race_id in eval_races:
                status, reason = "CONSUMED_DEVELOPMENT", "Iteration2 corrected rolling-OOS diagnostic race"
            elif race_id == "race_20260823_niigata_7R":
                status, reason = "ENGINE_INCOMPATIBLE", "Human-approved 2026-08-23 race exclusion; not in corrected Iteration2 cohort"
            elif race_id == "race_20251213_hanshin_8R":
                status, reason = "ENGINE_INCOMPATIBLE", "December one-shot human-approved zero-history race exclusion"
            elif date.startswith("202512") or date.startswith("202601"):
                status, reason = "CONSUMED_FORMAL_HOLDOUT", "December one-shot or January historical holdout; race-level inclusion requires authority recheck"
            elif date.startswith("202602"):
                status, reason = "CONSUMED_DEVELOPMENT", "Iteration2 budget period; exact race-level use requires authority recheck"
            else:
                status, reason = "OTHER_EXCLUSION_REQUIRES_REVIEW", "Outside Iteration2 dates; prospective role and race-level reuse authority not established"
            missing = []
            if not date in result_dates:
                missing.append("Result filename")
            races.append({
                "race_date": date, "venue": venue, "race_number": number, "race_id": race_id,
                "race_name": row[5], "race_type": row[6], "surface": row[7], "distance": row[8],
                "class": row[6], "newcomer_flag": newcomer, "obstacle_flag": obstacle,
                "dg_field_size": row[9], "de_horse_count": de_counts[(venue, number)],
                "primary_population_status": status, "status_reason": reason,
                "in_iteration2_eval_951": race_id in eval_races, "in_current_buy_432": race_id in buy_races,
                "dg_de_ds_files_present": True, "result_filename_present": date in result_dates,
                "result_rows_verified": False, "missing_source_metadata": ";".join(missing),
                "dg_path": str(paths["DG"].relative_to(ROOT)),
            })
        if date.startswith("202512"):
            role, authority = "CONSUMED_HISTORICAL_EXTERNAL_HOLDOUT", "December 2025 one-shot holdout reports"
        elif date.startswith("202601"):
            role, authority = "CONSUMED_HISTORICAL_EXTERNAL_HOLDOUT", "January 2026 historical holdout reports"
        elif date in eval_dates:
            role, authority = "CONSUMED_DEVELOPMENT_ROLLING_OOS", str(META.relative_to(ROOT))
        elif date.startswith("202602"):
            role, authority = "CONSUMED_DEVELOPMENT_BUDGET_PERIOD", str(BUDGET.relative_to(ROOT))
        else:
            role, authority = "PROSPECTIVE_ROLE_REVIEW_REQUIRED", "Date-specific PRE/POST authority not fully reconciled"
        date_rows.append({"date": date, "dg_de_ds_present": True, "result_filename_present": date in result_dates,
                          "evidence_role": role, "authority": authority})

    if len(races) != 1626:
        raise RuntimeError(f"STOP_SOURCE_RACE_COUNT_CHANGED:{len(races)}")
    out_ids = {r["race_id"] for r in races}
    if not eval_races <= out_ids:
        raise RuntimeError("STOP_EVAL_RACE_OUTSIDE_SOURCE")
    outside = [r for r in races if not r["in_current_buy_432"]]
    outside_reasons = Counter(
        "OBSTACLE" if r["obstacle_flag"] else
        "ENGINE_FAILURE" if r["race_id"] == "race_20260823_niigata_7R" else
        "OTHER_NO_CURRENT_BUY" if r["in_iteration2_eval_951"] else
        "DATE_NOT_INCLUDED"
        for r in outside
    )
    if sum(outside_reasons.values()) != len(outside):
        raise RuntimeError("STOP_OUTSIDE_REASON_PARTITION")
    months = ["202512"] + [f"2026{month:02d}" for month in range(1, 11)]
    month_rows = []
    for month in months:
        rs = [r for r in races if r["race_date"].startswith(month)]
        month_rows.append({
            "month": month, "source_races": len(rs),
            "newcomer_excluded_observed_dg": sum(r["newcomer_flag"] for r in rs),
            "obstacle_excluded_observed_dg": sum(r["obstacle_flag"] for r in rs),
            "data_incomplete_metadata_only": sum(bool(r["missing_source_metadata"]) for r in rs),
            "protected_holdout_confirmed": "NOT_ESTABLISHED",
            "consumed_development_confirmed": sum(r["in_iteration2_eval_951"] for r in rs),
            "eligible_proposed_diagnostic_races": "NOT_DETERMINED",
        })
    venue_rows = [
        {"venue": venue, "iteration2_eval_races_confirmed": sum(r["venue"] == venue and r["in_iteration2_eval_951"] for r in races),
         "largest_safe_proposal_count": "NOT_DETERMINED"}
        for venue in COURSE
    ]

    OUT.mkdir(parents=True)
    write_csv("race_inventory.csv", races, list(races[0]))
    write_csv("exclusion_inventory.csv", outside, list(outside[0]))
    write_csv("date_evidence_roles.csv", date_rows, list(date_rows[0]))
    write_csv("monthly_coverage.csv", month_rows, list(month_rows[0]))
    write_csv("venue_coverage.csv", venue_rows, list(venue_rows[0]))
    write_json("source_file_hashes.json", source_sha)
    april = json.loads(APRIL_CORRECTION.read_text(encoding="utf-8"))
    for kind in ("DG", "DE", "DS"):
        info = april["corrected_sources"][kind]
        if digest(ROOT / info["path"]) != info["sha256"]:
            raise RuntimeError(f"STOP_APRIL_V2_SOURCE_SHA_MISMATCH:{kind}")
    write_json("source_lineage_notes.json", {
        "role": "SOURCE_METADATA_ONLY", "result_content_access": 0,
        "20260418_authoritative_v2": {
            "correction_record": str(APRIL_CORRECTION.relative_to(ROOT)),
            "correction_record_sha256": digest(APRIL_CORRECTION),
            **april["corrected_sources"],
            "original_DG_obstacle_race": "race_20260418_nakayama_11R",
        },
        "20260823_approved_exclusion": {
            "record": str(AUGUST_EXCLUSION.relative_to(ROOT)),
            "record_sha256": digest(AUGUST_EXCLUSION),
            "race": "race_20260823_niigata_7R",
        },
    })
    write_json("rolling_oos_432_reconstruction.json", {
        "interpretation": "432 is Current BUY race subset, not all rolling-OOS races",
        "date_range": [min(eval_dates), max(eval_dates)], "dates": sorted(eval_dates),
        "evaluation_dates": len(eval_dates), "evaluation_races": len(eval_races),
        "current_buy_races": len(buy_races), "current_buy_horses_raw_from_existing_metadata": metadata["totals"]["A"]["raw_n"],
        "source_dg_races_on_evaluation_dates": sum(r["race_date"] in eval_dates for r in races),
        "source_minus_evaluation_races": sorted(out_ids & {r["race_id"] for r in races if r["race_date"] in eval_dates} - eval_races),
        "source_artifacts": {str(p.relative_to(ROOT)): digest(p) for p in (COHORT, META, SECONDARY, BUDGET)},
        "filters": ["2026-03-01 through 2026-09-13 rolling-OOS evaluation dates", "Current BUY race has at least one BUY horse"],
        "not_in_432_reason_counts_within_DG_source": dict(outside_reasons),
        "source_race_to_432_scope_warning": "DG is already a scoped input, not the complete JRA calendar",
    })
    write_json("diagnostic_population_proposal.json", {
        "status": "NOT_DETERMINED", "conservative_reused_development_races": len(eval_races),
        "conservative_reused_development_dates": len(eval_dates),
        "largest_safe_dates": None, "largest_safe_races": None, "largest_safe_horses": None,
        "technical_readiness": False,
        "reason": "Full JRA race scope, protected holdout authority, Result row completeness, and Current candidate_count/PLAY/convergence/per-race k availability not proven",
    })
    write_json("population_summary.json", {
        "status": "REVIEW_REQUIRED", "audit_range": ["2025-12-01", "2026-10-25"],
        "observed_repository_dates": observed_dates, "observed_repository_date_count": len(observed_dates),
        "source_dates": raw_dates, "source_date_count": len(raw_dates),
        "dates_without_DG_DE_DS": sorted(set(observed_dates) - set(raw_dates)),
        "jra_calendar_completeness_proven": False,
        "source_dg_races": len(races), "source_de_horse_rows": sum(int(r["de_horse_count"]) for r in races),
        "newcomer_races_visible_in_DG": sum(r["newcomer_flag"] for r in races),
        "obstacle_races_visible_in_DG": sum(r["obstacle_flag"] for r in races),
        "source_dg_scope_is_full_jra_calendar": False,
        "source_dg_is_pre_filtered_evidence": "252 date-venue groups have race-number gaps within 1R-12R",
        "iteration2_eval_races": len(eval_races), "iteration2_current_buy_races": len(buy_races),
        "races_outside_432_within_DG": len(outside), "outside_432_reason_counts": dict(outside_reasons),
        "unexplained_outside_432_within_DG": 0,
        "data_incomplete_races_file_presence_only": 0,
        "races_with_invalid_horse_results": "NOT_AUDITED",
        "invalid_result_horses_full_scope": "NOT_AUDITED_RESULT_CONTENT_PROTECTED",
        "protected_unused_holdout_races": "NOT_ESTABLISHED",
        "protected_unused_holdout_dates": "NOT_ESTABLISHED",
        "consumed_historical_holdout_races_confirmed": 295,
        "consumed_historical_holdout_authorities": {
            "december_2025_eligible_races": 146, "december_population_freeze_sha256": digest(DECEMBER),
            "january_2026_eligible_races": 149, "january_realized_population_manifest_sha256": digest(JANUARY),
        },
        "consumed_formal_evidence_races": "NOT_ESTABLISHED",
        "current_k_play_field_availability": "NOT_ESTABLISHED",
        "result_rows_parsed": False, "performance_calculated": False,
    })
    report = (
        "# Current development population audit v1 — review required\n\n"
        "The existing 432 count is **Current BUY races**, not the full rolling-OOS population. "
        "The corrected diagnostic covers 53 dates and 951 evaluation races (2026-03-01 to 2026-09-13); "
        "432 of those races have Current BUY. The original DG files on those dates contain 953 races; "
        "the two extras are 2026-04-18 Nakayama 11R (obstacle, removed in authoritative v2) "
        "and 2026-08-23 Niigata 7R (approved exclusion).\n\n"
        f"Across the requested interval the repository has {len(raw_dates)} dates with DG/DE/DS, "
        f"{len(races)} DG race rows and {sum(int(r['de_horse_count']) for r in races)} DE horse rows. "
        "A result filename exists for 2026-09-22 without DG/DE/DS in this directory. "
        "The DG feed is already scoped: 252 date-venue groups have gaps in 1R–12R. "
        "Therefore these counts are **not** all JRA races, and 0 newcomer rows in DG does not mean no newcomer races occurred.\n\n"
        "Temporal gap: the DG/DE/DS directory has no dates from 2026-06-01 through 2026-06-19. "
        "The REG-009 frozen spec names 2026-06-13 and 2026-06-14 as candidate target weekends; "
        "this audit does not assume their race counts or inspect their outcomes.\n\n"
        "Existing population authorities confirm 146 eligible December 2025 one-shot races and "
        "149 eligible January 2026 historical-holdout races (295 total). The December original DG "
        "contains one additional excluded race, Hanshin 8R on 2025-12-13. These are consumed "
        "historical/external holdouts, not untouched holdouts or newly promoted formal prospective evidence. "
        "No full-calendar race count or untouched-holdout count is claimed.\n\n"
        f"The {len(outside)} DG races outside the 432 partition as: {dict(outside_reasons)}. "
        "`OTHER_NO_CURRENT_BUY` is a cohort condition, not a new race exclusion. "
        "No 432-to-DG remainder is unexplained; full-calendar coverage remains unproven.\n\n"
        "No Result CSV content was opened. Therefore invalid-result race/horse counts, "
        "Result join completeness, protected unused holdout list, all-date evidence roles, "
        "and the largest safe Current k/PLAY diagnostic population are **not established**. "
        "The 951 races are a conservative already-consumed development subset, not a maximal proposal. "
        "Current candidate count, PLAY state, convergence state and per-race k are not proven available for all of them.\n\n"
        "No model, training, Production, existing artifact, or EXP-024 Block 001 state was changed.\n"
    )
    (OUT / "audit_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"output": str(OUT), "source_dates": len(raw_dates), "source_races": len(races),
                      "eval_races": len(eval_races), "buy_races": len(buy_races),
                      "outside_reasons": dict(outside_reasons)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
