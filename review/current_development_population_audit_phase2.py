"""Result-free Phase 2 coverage audit over official JRA program metadata.

Never opens Result CSV or outcome-bearing row artifacts. Existing Phase 1
inventory and pre-result raw DG/DE/DS are the only row-level repository inputs.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/current_population_audit_v1"
RAW = ROOT / "data/raw/prediction_input"
CALENDAR = OUT / "jra_official_program_metadata_phase2.json"
PHASE1 = OUT / "race_inventory.csv"
DECEMBER = ROOT / "reports/december_2025_three_lane_one_shot_holdout_pre/population_freeze.json"
JANUARY = ROOT / "reports/selection_authority_protocol_v1_january_2026_historical_holdout/realized_population_manifest.json"
JANUARY_POST = ROOT / "reports/selection_authority_protocol_v1_january_2026_historical_holdout/post/post_manifest.json"
DECEMBER_POST = ROOT / "reports/december_2025_one_shot_post/SUCCESS"
COHORT_META = ROOT / "reports/pl_current_race_selection_dev_diagnostic_v1/diagnostic_metadata.json"
PRE_ONLY_ROOT = ROOT / "reports/full_field_redesign_iter0_v1_retry6/pre_only_regeneration/shards"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    if path.exists():
        raise RuntimeError(f"STOP_EXISTING_PHASE2_ARTIFACT:{path.name}")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def save_json(path: Path, obj: object) -> None:
    if path.exists():
        raise RuntimeError(f"STOP_EXISTING_PHASE2_ARTIFACT:{path.name}")
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def program_type(text: str) -> str:
    if "障害" in text or "ジャンプステークス" in text or "ジャンプS" in text:
        return "OBSTACLE"
    if "新馬" in text:
        return "NEWCOMER"
    if "未勝利" in text:
        return "MAIDEN"
    if not text:
        return "UNKNOWN_PROGRAM_TYPE"
    return "ONE_WIN_PLUS_OR_OTHER"


def clean_name(text: str) -> str:
    return text.strip().replace(" ", "").replace("　", "")


def role(date: str, source_exists: bool) -> tuple[str, str]:
    if date.startswith("202512"):
        return "CONSUMED_EXTERNAL_HOLDOUT", str(DECEMBER.relative_to(ROOT))
    if date.startswith("202601"):
        return "CONSUMED_HISTORICAL_HOLDOUT", str(JANUARY_POST.relative_to(ROOT))
    if "20260301" <= date <= "20260913" and source_exists:
        return "CONSUMED_DEVELOPMENT", str(COHORT_META.relative_to(ROOT))
    if date == "20260922":
        return "SOURCE_INCOMPLETE", "No DG/DE/DS; Result filename only, content unopened"
    if date in {"20260606", "20260607", "20260613", "20260614"}:
        return "SOURCE_INCOMPLETE", "JRA schedule exists; DG/DE/DS absent"
    if date.startswith("202602"):
        return "UNKNOWN_REQUIRES_REVIEW", "Training/budget presence does not establish diagnostic Result reuse role"
    if date >= "20260919":
        return "UNKNOWN_REQUIRES_REVIEW", "Prospective vs diagnostic/evidence date-specific authority not fully mapped"
    return "UNKNOWN_REQUIRES_REVIEW", "No exact evidence-role authority found"


def main() -> None:
    calendar = json.loads(CALENDAR.read_text(encoding="utf-8"))
    phase1 = list(csv.DictReader(PHASE1.open(encoding="utf-8-sig", newline="")))
    phase1_by_key = {(r["race_date"], r["venue"], int(r["race_number"])): r for r in phase1}
    dec = json.loads(DECEMBER.read_text(encoding="utf-8"))
    jan = json.loads(JANUARY.read_text(encoding="utf-8"))
    jan_post = json.loads(JANUARY_POST.read_text(encoding="utf-8"))
    cohort = json.loads(COHORT_META.read_text(encoding="utf-8"))
    if (len(phase1), dec["eligible_races"], jan["eligible_population_races"],
        jan_post["status"], DECEMBER_POST.exists(), cohort["races"], cohort["current_buy_races"]) != (
            1626, 146, 149, "COMPLETE", True, 951, 432):
        raise RuntimeError("STOP_PHASE1_OR_HOLDOUT_AUTHORITY_CHANGED")

    grouped = defaultdict(dict)
    for group in calendar["groups"]:
        key = (group["date"], group["venue"])
        if key in grouped:
            raise RuntimeError(f"STOP_DUPLICATE_CALENDAR_GROUP:{key}")
        grouped[key] = {int(x["n"]): x for x in group["races"]}
    calendar_rows = []
    for group in calendar["groups"]:
        for item in group["races"]:
            key = (group["date"], group["venue"], int(item["n"]))
            kind = program_type(item["t"])
            if key == ("20251227", "中山", 10) and not item["t"]:
                # The official program puts the race title on the next line:
                # 中山大障害（J・GⅠ） 障害3歳以上オープン.
                kind = "OBSTACLE"
            calendar_rows.append({"date": key[0], "venue": key[1], "race_number": key[2],
                                  "program_text": item["t"], "program_type": kind,
                                  "program_authority": "JRA_OFFICIAL_PROGRAM_NOT_FINAL_STARTER_LIST",
                                  "source_url": group["source_url"],
                                  "dg_observed": key in phase1_by_key})
    calendar_keys = {(r["date"], r["venue"], r["race_number"]) for r in calendar_rows}
    if len(calendar_rows) != len(calendar_keys):
        raise RuntimeError("STOP_DUPLICATE_CALENDAR_RACE")
    dg_only = sorted(set(phase1_by_key) - calendar_keys)
    # The 2026-09-21 TARGET source contains Nakayama rows although the
    # official 9/21 program lists only Hanshin. Keep this discrepancy visible;
    # never silently add source-only races to the official denominator.

    source_dates = sorted({r["race_date"] for r in phase1})
    ds_names: dict[str, set[str]] = {}
    de_by_race: dict[tuple, list[list[str]]] = defaultdict(list)
    source_hashes: dict[str, dict[str, str]] = {}
    for date in source_dates:
        paths = {kind: RAW / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}
        if not all(p.is_file() for p in paths.values()):
            raise RuntimeError(f"STOP_PHASE1_SOURCE_DISAPPEARED:{date}")
        source_hashes[date] = {k: sha(v) for k, v in paths.items()}
        de_rows = csv.reader(paths["DE"].open(encoding="cp932", newline=""))
        for row in de_rows:
            de_by_race[(date, row[1], int(row[2]))].append(row)
        ds_names[date] = {clean_name(row[16]) for row in csv.reader(paths["DS"].open(encoding="cp932", newline=""))}

    coverage = []
    for race in calendar_rows:
        date, venue, number = race["date"], race["venue"], race["race_number"]
        key = (date, venue, number)
        phase = phase1_by_key.get(key)
        official_type = race["program_type"]
        if not phase:
            status = ("OUT_OF_SCOPE_NEWCOMER" if official_type == "NEWCOMER" else
                      "OUT_OF_SCOPE_OBSTACLE" if official_type == "OBSTACLE" else
                      "OUT_OF_SCOPE_MAIDEN" if official_type == "MAIDEN" else
                      "DG_MISSING")
            de_status = ds_status = "NOT_APPLICABLE_DG_MISSING"
            missing_names = ""
            headcount_match = "NOT_APPLICABLE"
        else:
            status = "DG_PRESENT"
            de_rows = de_by_race.get(key, [])
            expected = int(phase["dg_field_size"])
            headcount_match = len(de_rows) == expected
            de_status = "DG_DE_COMPLETE" if headcount_match else "DG_DE_MISMATCH"
            names = {clean_name(row[7]) for row in de_rows}
            missing = sorted(names - ds_names[date])
            missing_names = "|".join(missing)
            ds_status = "DE_DS_COMPLETE" if not missing else "DE_DS_MISSING_HISTORY"
            if date == "20251213" and venue == "阪神" and number == 8 and missing == ["マーブルヘイロー"]:
                ds_status = "FIRST_START_NO_DS_APPROVED_RACE_EXCLUSION"
            elif date == "20261012" and venue == "京都" and number == 8 and missing == ["カドーダムール"]:
                ds_status = "FIRST_START_NO_DS_APPROVED_RACE_EXCLUSION"
            elif date == "20261025" and venue == "東京" and number == 12 and missing == ["ハギンス"]:
                ds_status = "FIRST_START_NO_DS_APPROVED_RACE_EXCLUSION"
        complete = status == "DG_PRESENT" and de_status == "DG_DE_COMPLETE" and ds_status == "DE_DS_COMPLETE"
        coverage.append({**race, "dg_status": status, "dg_de_status": de_status,
                         "de_ds_status": ds_status, "dg_headcount_match": headcount_match,
                         "missing_de_horse_names_in_ds": missing_names,
                         "source_complete_raw_strict": complete,
                         "phase1_race_id": phase["race_id"] if phase else "",
                         "iteration2_eval_951": phase["in_iteration2_eval_951"] if phase else "False",
                         "current_buy_432": phase["in_current_buy_432"] if phase else "False"})

    by_date = defaultdict(list)
    for row in coverage:
        by_date[row["date"]].append(row)
    date_roles = []
    for date, rows in sorted(by_date.items()):
        role_name, authority = role(date, date in source_dates)
        date_roles.append({"date": date, "primary_role": role_name, "authority": authority,
                           "expected_jra_races": len(rows), "dg_races": sum(r["dg_status"] == "DG_PRESENT" for r in rows),
                           "source_complete_raw_strict": sum(r["source_complete_raw_strict"] for r in rows),
                           "dg_present": date in source_dates, "de_present": date in source_dates,
                           "ds_present": date in source_dates,
                           "current_pre_exact_race_coverage": "NOT_PROVEN",
                           "pl_compatible_input": "PRESENT_FOR_DG_SCOPE" if date in source_dates else "NO_SOURCE",
                           "result_content_opened": False})

    # PRE-only regenerated snapshots are useful for technical field presence,
    # but their PIT/semantic equivalence is not an authority for Current BUY.
    pre_fields: dict[str, set[str]] = defaultdict(set)
    pre_state: dict[str, set[str]] = defaultdict(set)
    pre_races: set[str] = set()
    for path in sorted(PRE_ONLY_ROOT.glob("run_c_*/runtime_pre_only_output.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for row in blob["generated_rows"]:
            race_id = row["race_id"]
            pre_races.add(race_id)
            pre_fields[race_id].update(row["values"])
            pre_fields[race_id].update({"rank", "top5"})
            pre_state[race_id].add(str(row["values"].get("race_state", "")))
    eval_ids = {r["phase1_race_id"] for r in coverage if r["iteration2_eval_951"] == "True"}
    if len(eval_ids) != 951:
        raise RuntimeError(f"STOP_EVAL_951_LOST:{len(eval_ids)}")
    if not eval_ids <= pre_races:
        raise RuntimeError(f"STOP_PRE_ONLY_REGEN_MISSING_EVAL:{len(eval_ids - pre_races)}")
    if any(len(pre_state[r]) != 1 for r in eval_ids):
        raise RuntimeError("STOP_PRE_ONLY_RACE_STATE_INCONSISTENT")
    state_counts = Counter(next(iter(pre_state[r])) for r in eval_ids)
    field_rows = []
    for row in coverage:
        if row["iteration2_eval_951"] != "True":
            continue
        race_id = row["phase1_race_id"]
        fields = pre_fields.get(race_id, set())
        field_rows.append({"date": row["date"], "race_id": race_id,
                           "current_buy_existing_consumed_diagnostic": True,
                           "current_score_preonly": "adjusted_score" in fields,
                           "current_candidate_set_preonly": "top5" in fields,
                           "candidate_count_explicit": "candidate_count" in fields,
                           "play_state_preonly": "race_state" in fields,
                           "convergence_explicit": "convergence_state" in fields,
                           "play_unconverged_4plus_preonly": "race_state" in fields,
                           "per_race_k_explicit": "target_k" in fields or "per_race_k" in fields,
                           "frozen_pl_rank_existing_consumed_diagnostic": True,
                           "result_previously_consumed": True,
                           "preonly_semantic_equivalence": "NOT_PROVEN"})

    exclusions = []
    proposal = []
    for row in coverage:
        date = row["date"]
        role_name, _ = role(date, date in source_dates)
        include = row["iteration2_eval_951"] == "True"
        if include:
            proposal.append({"date": date, "venue": row["venue"], "race_number": row["race_number"],
                             "race_id": row["phase1_race_id"], "current_buy_positive": row["current_buy_432"] == "True",
                             "current_buy_zero": row["current_buy_432"] != "True",
                             "source_complete_raw_strict": row["source_complete_raw_strict"],
                             "proposal_role": "SAFE_CONSUMED_DEVELOPMENT_DIAGNOSTIC_SCOPE",
                             "k_play_technical_readiness": "NOT_PROVEN"})
            continue
        t = row["program_type"]
        reason = ("OBSTACLE" if t == "OBSTACLE" else
                  "NEWCOMER" if t == "NEWCOMER" else
                  "OTHER_REVIEW_REQUIRED" if t == "MAIDEN" else
                  "SOURCE_MISSING" if row["dg_status"] != "DG_PRESENT" else
                  "DATA_INTEGRITY_FAILURE" if not row["source_complete_raw_strict"] else
                  "PROTECTED_HOLDOUT" if role_name in {"CONSUMED_EXTERNAL_HOLDOUT", "CONSUMED_HISTORICAL_HOLDOUT"} else
                  "FORMAL_EVIDENCE_PROTECTION" if date >= "20260919" else
                  "CURRENT_ARTIFACT_UNAVAILABLE" if date.startswith("202602") else
                  "OTHER_REVIEW_REQUIRED")
        exclusions.append({"date": date, "venue": row["venue"], "race_number": row["race_number"],
                           "race_id": row["phase1_race_id"], "reason": reason,
                           "detail": "Maiden is outside the 1-win+ Current scope" if t == "MAIDEN" else "",
                           "evidence_role": role_name, "dg_status": row["dg_status"]})

    months = ["202512"] + [f"2026{i:02d}" for i in range(1, 11)]
    monthly = []
    for month in months:
        rows = [r for r in coverage if r["date"].startswith(month)]
        monthly.append({"month": month, "expected_jra_program_races": len(rows),
                        "dg_covered": sum(r["dg_status"] == "DG_PRESENT" for r in rows),
                        "source_complete_raw_strict": sum(r["source_complete_raw_strict"] for r in rows),
                        "confirmed_protected_unused_holdout": 0,
                        "consumed_historical_holdout": sum(role(r["date"], True)[0] in {"CONSUMED_EXTERNAL_HOLDOUT", "CONSUMED_HISTORICAL_HOLDOUT"} for r in rows),
                        "safe_consumed_development": sum(r["iteration2_eval_951"] == "True" for r in rows),
                        "proposed_current_diagnostic": sum(r["iteration2_eval_951"] == "True" for r in rows),
                        "unknown_role_races": sum(role(r["date"], r["date"] in source_dates)[0] == "UNKNOWN_REQUIRES_REVIEW" for r in rows)})

    counts = Counter(r["dg_status"] for r in coverage)
    ds_counts = Counter(r["de_ds_status"] for r in coverage if r["dg_status"] == "DG_PRESENT")
    unknown_types = [r for r in coverage if r["program_type"] == "UNKNOWN_PROGRAM_TYPE"]
    source_complete = sum(r["source_complete_raw_strict"] for r in coverage)
    buy_positive = sum(r["current_buy_positive"] for r in proposal)
    summary = {
        "status": "REVIEW_REQUIRED", "full_date_range": ["2025-12-01", "2026-10-25"],
        "official_program_date_count": len(by_date), "official_program_race_count": len(coverage),
        "calendar_authority_limit": "Official daily pages are program metadata, not immutable final starter/result records; cancellations/changes may occur",
        "dg_covered_races": counts["DG_PRESENT"], "dg_source_total_races": len(phase1),
        "dg_source_only_not_in_official_program": len(dg_only),
        "dg_source_only_races": [{"date": d, "venue": v, "race_number": n} for d, v, n in dg_only],
        "dg_missing_or_out_of_scope_races": len(coverage) - counts["DG_PRESENT"],
        "dg_status_counts": dict(counts), "source_complete_raw_strict_races": source_complete,
        "de_ds_counts": dict(ds_counts), "program_type_unknown_races": len(unknown_types),
        "consumed_december_holdout_races": 146, "consumed_january_holdout_races": 149,
        "confirmed_protected_unused_holdout_races": 0,
        "unresolved_evidence_role_races": sum(r["primary_role"] == "UNKNOWN_REQUIRES_REVIEW" for r in date_roles for _ in range(r["expected_jra_races"])),
        "safe_consumed_development_races": len(proposal),
        "proposed_current_diagnostic_races": len(proposal),
        "proposed_current_diagnostic_dates": len({r["date"] for r in proposal}),
        "current_buy_positive_races": buy_positive, "current_buy_zero_races": len(proposal)-buy_positive,
        "current_buy_zero_included": len(proposal)-buy_positive > 0,
        "preonly_race_state_counts_on_951_not_current_authority": dict(state_counts),
        "field_availability_on_951": {
            "current_buy": sum(r["current_buy_existing_consumed_diagnostic"] for r in field_rows),
            "current_score_preonly": sum(r["current_score_preonly"] for r in field_rows),
            "candidate_count_explicit": sum(r["candidate_count_explicit"] for r in field_rows),
            "play_state_preonly": sum(r["play_state_preonly"] for r in field_rows),
            "convergence_explicit": sum(r["convergence_explicit"] for r in field_rows),
            "per_race_k_explicit": sum(r["per_race_k_explicit"] for r in field_rows),
            "frozen_pl": sum(r["frozen_pl_rank_existing_consumed_diagnostic"] for r in field_rows),
            "previously_consumed_result": sum(r["result_previously_consumed"] for r in field_rows),
        },
        "unexplained_source_gaps": sum(r["dg_status"] == "DG_MISSING" for r in coverage),
        "unexplained_diagnostic_exclusions": 0,
        "new_result_content_accesses": 0, "current_k_play_diagnostic_technically_ready": False,
        "reason_not_ready": "Explicit candidate_count, convergence and per-race k are absent in PRE-only rows; PRE-only PIT/Current semantic equivalence not proven; unknown date roles remain",
        "iteration2_432_status": "CURRENT_BUY_SUBSET_CONFIRMED",
        "no_model_change": True, "no_retraining": True, "no_production_change": True,
        "no_new_evidence_promotion": True, "no_holdout_consumption": True,
        "exp024_block001_state": "UNCHANGED",
        "population_audit_phase2_verdict": "REVIEW_REQUIRED",
        "ready_to_return_to_primary_roadmap": False,
        "ready_for_current_k_play_diagnostic_design": False,
        "source_sha": {"calendar_metadata": sha(CALENDAR), "phase1_inventory": sha(PHASE1),
                       "december_population_freeze": sha(DECEMBER), "january_population_manifest": sha(JANUARY),
                       "january_post_manifest": sha(JANUARY_POST), "cohort_metadata": sha(COHORT_META)},
    }
    save_csv(OUT / "calendar_population.csv", calendar_rows, list(calendar_rows[0]))
    save_csv(OUT / "source_coverage.csv", coverage, list(coverage[0]))
    save_csv(OUT / "dg_only_not_in_official_program_phase2.csv",
             [{"date": d, "venue": v, "race_number": n,
               "race_id": phase1_by_key[(d, v, n)]["race_id"],
               "classification": "SOURCE_ONLY_OFFICIAL_PROGRAM_CONFLICT_REVIEW_REQUIRED"}
              for d, v, n in dg_only],
             ["date", "venue", "race_number", "race_id", "classification"])
    save_csv(OUT / "date_evidence_roles_phase2.csv", date_roles, list(date_roles[0]))
    save_csv(OUT / "diagnostic_field_availability.csv", field_rows, list(field_rows[0]))
    save_csv(OUT / "diagnostic_population_final_proposal.csv", proposal, list(proposal[0]))
    save_csv(OUT / "excluded_races_with_reason.csv", exclusions, list(exclusions[0]))
    save_csv(OUT / "monthly_coverage_final.csv", monthly, list(monthly[0]))
    save_json(OUT / "population_audit_phase2.json", summary)
    report = [
        "# CURRENT_DEVELOPMENT_POPULATION_AUDIT_V1 Phase 2",
        "", "STATUS: REVIEW_REQUIRED", "",
        f"Official JRA daily program metadata: {len(by_date)} dates / {len(coverage)} race slots.",
        f"DG matches {counts['DG_PRESENT']} official slots ({counts['DG_PRESENT']/len(coverage):.2%}); raw DG has {len(phase1)} rows because six 2026-09-21 Nakayama rows are source-only against the official cancellation program. Raw-strict DG/DE/DS complete: {source_complete} official races.",
        f"Official-slot DG absences: {counts['OUT_OF_SCOPE_MAIDEN']} maiden, {counts['OUT_OF_SCOPE_NEWCOMER']} newcomer, {counts['OUT_OF_SCOPE_OBSTACLE']} obstacle, {counts['DG_MISSING']} remaining source gaps.",
        f"Confirmed consumed rolling-OOS Development: {len(proposal)} races / {len({r['date'] for r in proposal})} dates, including {len(proposal)-buy_positive} Current BUY=0 races.",
        f"PRE-only race-state distribution on those 951 races (not contemporaneous Current authority): {dict(state_counts)}.",
        "", "## Evidence boundary", "",
        "December one-shot (146 races, 2025-12-06/07/13/14/20/21/27/28) and January historical holdout (149 races, 2026-01-04/05/10/11/12/17/18/24/25/31) have POST completion authority. They are consumed holdouts, not untouched Development data.",
        "No protected unused holdout is confirmed by this audit; unknown-role dates are not opened or promoted.",
        "No Result CSV or outcome-bearing rows were opened. New Result content access = 0.",
        "", "## Temporal gaps", "",
        "2025-12 and 2026-01 are already-consumed holdout periods, not rolling Development dates. 2026-02 is the rolling-origin training/budget period; exact diagnostic Result reuse is not ratified here.",
        "2026-06-06/07/13/14 have official race programs but no DG/DE/DS. 2026-09-21 Nakayama was cancelled on the official program and moved to 2026-09-22; six Nakayama rows remain dated 9/21 in local DG while 9/22 has no DG/DE/DS.",
        "2026-10-01 through 10-25 has source/PRE activity but is not within the 53-date rolling-OOS Development cohort; date-specific prospective/evidence role reconciliation remains open.",
        "", "## Why this is not a PASS", "",
        "The JRA program pages are official schedule metadata and explicitly allow date/race-order changes and cancellation. They are not a final starter authority for every past date.",
        "DG is a scoped KeibaAI feed, not the complete JRA calendar; maiden, newcomer, obstacle and other missing races remain separated in source_coverage.csv.",
        "The PRE-only 62-date regeneration contains scores and race_state for all 951 Development races, but explicit candidate_count, convergence and per-race k are absent, and semantic/PIT equivalence to the contemporaneous Current path is not proven.",
        "Five official DG races fail raw-strict DE/DS: 2025-12-13 Hanshin 8R, 2026-08-23 Niigata 7R, 2026-09-06 Hanshin 11R, 2026-10-12 Kyoto 8R, and 2026-10-25 Tokyo 12R. Approved race-specific handling exists for the first, fourth and fifth; the 8/23 and 9/6 cases have separate prior authority and are not reinterpreted here.",
        "The 951-race scope is safe as a consumed Development diagnostic *population proposal*, not authorization to run Current k/PLAY diagnosis until field authority is established.",
        "", "## Key files", "",
        "- calendar_population.csv: official date/venue/R program skeleton",
        "- source_coverage.csv: per-race DG/DE/DS and type status",
        "- date_evidence_roles_phase2.csv: one primary date role; original Phase 1 file preserved",
        "- diagnostic_field_availability.csv: PRE-only field presence on 951 Development races",
        "- diagnostic_population_final_proposal.csv: 951-race consumed Development proposal",
        "- excluded_races_with_reason.csv: one reason for every other calendar race",
        "", "No model, Production, formal evidence, or EXP-024 state was changed.", "",
    ]
    report_path = OUT / "audit_report_phase2.md"
    if report_path.exists():
        raise RuntimeError("STOP_EXISTING_PHASE2_REPORT")
    report_path.write_text("\n".join(report), encoding="utf-8")
    names = ["jra_official_program_metadata_phase2.json", "calendar_population.csv", "source_coverage.csv",
             "dg_only_not_in_official_program_phase2.csv",
             "date_evidence_roles_phase2.csv", "diagnostic_field_availability.csv",
             "diagnostic_population_final_proposal.csv", "excluded_races_with_reason.csv",
             "monthly_coverage_final.csv", "population_audit_phase2.json", "audit_report_phase2.md"]
    save_json(OUT / "artifact_hashes_phase2.json", {name: sha(OUT / name) for name in names})
    print(json.dumps({k: summary[k] for k in ("official_program_date_count", "official_program_race_count",
                                            "dg_covered_races", "source_complete_raw_strict_races",
                                            "safe_consumed_development_races", "current_buy_zero_races",
                                            "unexplained_source_gaps")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
