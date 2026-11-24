"""Frozen one-shot fine-grain draw-position residual diagnostic.

The result boundary is explicit: all assigned-field-size provenance and every
lane/group assignment are written and hashed before any result helper is
called.  The script is additive and does not alter prediction/runtime code.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from scipy.stats import chi2_contingency

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.candidate_generation_training_dataset_readiness_v1 import (
    JAPANESE_VENUE,
    outcome,
    parse_race_id,
    result_rows,
)
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


OUT = ROOT / "reports/fine_grain_draw_position_residual_diagnostic_v1"
FOLD = ROOT / "reports/candidate_generation_stage_a_paired_population_expanded_v1/expanded_stage_a_fold_manifest.json"
NATURAL_ROOT = ROOT / "reports/selection_composition_policy_v2_shadow_phase1_v1"
RETRY5 = ROOT / "reports/candidate_generation_stage_b_fast_route_b4_buy_performance_v1_retry5"
NATURAL = {
    "baseline": NATURAL_ROOT / "baseline_policy_v2_natural_buy.csv",
    "treatment": NATURAL_ROOT / "treatment_policy_v2_natural_buy.csv",
}
RETRY5_NATURAL = {
    "baseline": RETRY5 / "baseline_stage_b_natural_buy.csv",
    "treatment": RETRY5 / "treatment_stage_b_natural_buy.csv",
}
EXPECTED_N = {"baseline": 679, "treatment": 720}
FEBRUARY = {"20260201", "20260207", "20260208", "20260210", "20260214", "20260215", "20260221", "20260222", "20260228"}
PROTECTED = (
    "engine/decision_engine.py",
    "engine/race_decision_engine.py",
    "engine/shadow_buy_decision_engine.py",
    "review/candidate_generation_stage_b_shadow_v1.py",
    "review/selection_composition_policy_v2_shadow_v1.py",
    "review/target_bulk_prediction_input_adapter_v1.py",
    "reports/candidate_generation_stage_a_paired_population_expanded_v1/expanded_stage_a_fold_manifest.json",
    "reports/selection_composition_policy_v2_shadow_phase1_v1/baseline_policy_v2_natural_buy.csv",
    "reports/selection_composition_policy_v2_shadow_phase1_v1/treatment_policy_v2_natural_buy.csv",
)


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(name: str, value: object) -> Path:
    path = OUT / name
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def write_csv(name: str, rows: list[dict], fields: list[str]) -> Path:
    path = OUT / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def git_value(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else f"UNAVAILABLE:{proc.returncode}"


def eval_dates() -> list[str]:
    payload = json.loads(FOLD.read_text(encoding="utf-8"))
    dates = sorted({date for fold in payload["folds"] for date in fold["eval_dates"]})
    if len(dates) != 45 or set(dates) & FEBRUARY or payload.get("evaluation_race_total") != 828:
        raise Stop("FROZEN_SCOPE_INVALID")
    return dates


def source_paths(date: str) -> tuple[Path, Path]:
    suffix = date[2:]
    version = "v2" if date == "20260418" else ""
    return (
        ROOT / f"data/raw/prediction_input/DG{suffix}{version}.CSV",
        ROOT / f"data/raw/prediction_input/DE{suffix}{version}.CSV",
    )


def frozen_prediction_sources(dates: list[str]) -> dict[str, list[Path]]:
    """Resolve only the frozen 45 evaluation dates; never enumerate February."""
    mapping: dict[str, list[Path]] = {}
    additional = json.loads((ROOT / "reports/candidate_generation_22date_full_field_readiness_v1/provenance_audit.json").read_text(encoding="utf-8"))
    for date in dates:
        if date.startswith("202603"):
            root = ROOT / "reports/march_2026_historical_holdout_pre/current_ai" / date
            paths = sorted(root.glob("race_*_prediction.json"))
        elif date.startswith("202605"):
            root = ROOT / "reports/may_2026_multi_system_oos_v1/pre_retry_v5/current_ai" / date
            paths = sorted(root.glob("race_*_prediction.json"))
        elif date in {"20260829", "20260830", "20260905", "20260906"}:
            root = ROOT / f"reports/prospective_prediction_{date}_v1"
            index = json.loads((root / "race_index.json").read_text(encoding="utf-8"))["race_index"]
            paths = [root / item["artifact"] for item in index]
        else:
            if date not in additional:
                raise Stop(f"FROZEN_PREDICTION_PROVENANCE_MISSING:{date}")
            root = ROOT / additional[date]["prediction_source"]
            paths = sorted(root.glob("race_*_prediction.json"))
        if not paths or any(not path.is_file() for path in paths):
            raise Stop(f"FROZEN_PREDICTION_SOURCE_MISSING:{date}")
        mapping[date] = paths
    return mapping


def load_natural(path: Path, dates: set[str]) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["date"] in dates]
    for row in rows:
        row["horse_number"] = int(row["horse_number"])
        row["race_number"] = int(row["race_number"])
    return rows


def identities(path: Path, dates: set[str]) -> set[tuple[str, str, int]]:
    return {(row["date"], row["race_id"], int(row["horse_number"])) for row in load_natural(path, dates)}


def group_for(horse_number: int, field_size: int) -> str:
    first = math.ceil(field_size / 3)
    second = math.ceil(2 * field_size / 3)
    if horse_number <= first:
        return "INNER"
    if horse_number <= second:
        return "MIDDLE"
    return "OUTER"


def phase0(dates: list[str]) -> tuple[list[dict], dict[tuple[str, str], dict], dict[str, str]]:
    adapter = TargetBulkPredictionInputAdapterV1()
    predictions = frozen_prediction_sources(dates)
    race_authority: dict[tuple[str, str], dict] = {}
    audit: list[dict] = []
    source_hashes: dict[str, str] = {}

    for date in dates:
        dg_path, de_path = source_paths(date)
        dg_rows, dg_source = adapter._read_fixed(dg_path, "DG")
        de_rows, de_source = adapter._read_fixed(de_path, "DE")
        derived_date = adapter._validate_dates({"DG": dg_rows, "DE": de_rows})
        dg = adapter._validate_dg(dg_rows, derived_date)
        de, _, _ = adapter._validate_de(de_rows, derived_date)
        adapter._validate_dg_de(dg, de)
        source_hashes[str(dg_path.relative_to(ROOT))] = dg_source.sha256
        source_hashes[str(de_path.relative_to(ROOT))] = de_source.sha256

        frozen_ids = set()
        for artifact in predictions[date]:
            payload = json.loads(artifact.read_text(encoding="utf-8"))
            frozen_ids.add(payload["race_id"])
        if len(frozen_ids) != len(predictions[date]):
            raise Stop(f"DUPLICATE_FROZEN_RACE:{date}")

        for race_id in sorted(frozen_ids):
            actual_date, venue_key, race_number = parse_race_id(race_id)
            venue = JAPANESE_VENUE[venue_key]
            key = (venue, race_number)
            if actual_date != date or key not in dg or key not in de:
                raise Stop(f"PRE_RACE_AUTHORITY_UNMATCHED:{race_id}")
            dg_row = dg[key]
            n = adapter._int(dg_row[9], "DG_FIELD_SIZE_INVALID")
            de_numbers = sorted(adapter._int(row[3], "DE_HORSE_NUMBER_INVALID") for row in de[key])
            if len(de_numbers) != n or len(set(de_numbers)) != n or any(h < 1 or h > n for h in de_numbers):
                raise Stop(f"ASSIGNED_NUMBER_RANGE_INVALID:{race_id}:{n}:{de_numbers}")
            names = {adapter._int(row[3], "DE_HORSE_NUMBER_INVALID"): adapter._clean_name(row[7]) for row in de[key]}
            gaps = sorted(set(range(1, n + 1)) - set(de_numbers))
            record = {
                "race_id": race_id,
                "date": date,
                "venue": venue,
                "race_number": race_number,
                "assigned_field_size": n,
                "source_field": "DG column 10 (zero-based index 9): declared field_size",
                "source_file": str(dg_path.relative_to(ROOT)),
                "source_sha256": dg_source.sha256,
                "de_source_file": str(de_path.relative_to(ROOT)),
                "de_source_sha256": de_source.sha256,
                "provenance_method": "explicit PRE-race DG declared field size; existing Adapter DG/DE head-count validation",
                "min_assigned_horse_number": min(de_numbers),
                "max_assigned_horse_number": max(de_numbers),
                "detected_horse_number_gaps": "|".join(map(str, gaps)),
                "provenance_pass": True,
            }
            audit.append(record)
            race_authority[(date, race_id)] = {**record, "de_names": names, "de_numbers": de_numbers}

    if len(audit) != 828 or len(race_authority) != 828:
        raise Stop(f"ASSIGNED_FIELD_SIZE_RACE_COUNT:{len(audit)}")
    return audit, race_authority, source_hashes


def grouping(dates: list[str], authority: dict[tuple[str, str], dict]) -> tuple[list[dict], dict]:
    manifest: list[dict] = []
    summary: dict[str, dict] = {}
    date_set = set(dates)
    for lane, path in NATURAL.items():
        rows = load_natural(path, date_set)
        if len(rows) != EXPECTED_N[lane]:
            raise Stop(f"NATURAL_BUY_COUNT_INVALID:{lane}:{len(rows)}")
        if identities(path, date_set) != identities(RETRY5_NATURAL[lane], date_set):
            raise Stop(f"NATURAL_BUY_AUTHORITY_DIVERGENCE:{lane}")
        seen = set()
        counts = Counter()
        for row in rows:
            identity = (row["date"], row["race_id"], row["horse_number"])
            if identity in seen:
                raise Stop(f"DUPLICATE_NATURAL_BUY:{lane}:{identity}")
            seen.add(identity)
            race = authority.get((row["date"], row["race_id"]))
            if race is None:
                raise Stop(f"NATURAL_BUY_RACE_UNMATCHED:{lane}:{identity}")
            h, n = row["horse_number"], race["assigned_field_size"]
            if h not in race["de_names"] or race["de_names"][h] != row["horse_name"]:
                raise Stop(f"NATURAL_BUY_HORSE_UNMATCHED:{lane}:{identity}")
            group = group_for(h, n)
            counts[group] += 1
            manifest.append({
                "lane": lane.upper(), "date": row["date"], "race_id": row["race_id"],
                "venue": row["venue"], "race_number": row["race_number"],
                "horse_number": h, "horse_name": row["horse_name"],
                "assigned_field_size": n, "draw_position_group": group,
                "field_size_source": race["source_file"], "field_size_source_sha256": race["source_sha256"],
            })
        summary[lane] = {"natural_buy_n": len(rows), "group_n": dict(counts), "grouping_pass": True}
    return manifest, summary


def contingency(lane_rows: list[dict]) -> dict:
    groups = ("INNER", "MIDDLE", "OUTER")
    cells = []
    descriptive = {}
    valid_n = sum(row["valid_result"] for row in lane_rows)
    invalid_n = len(lane_rows) - valid_n
    for group in groups:
        valid = [row for row in lane_rows if row["draw_position_group"] == group and row["valid_result"]]
        hits = sum(row["actual_top3"] for row in valid)
        misses = len(valid) - hits
        cells.append([hits, misses])
        descriptive[group] = {"N": len(valid), "Top3_Hits": hits, "Top3_Rate": hits / len(valid) if valid else None}
    chi2, p_value, df, expected = chi2_contingency(cells, correction=False)
    expected_min = float(expected.min())
    rates = {group: descriptive[group]["Top3_Rate"] for group in groups}
    high = max(rates, key=rates.get)
    low = min(rates, key=rates.get)
    return {
        "natural_buy_pre_result_n": len(lane_rows), "valid_n": valid_n, "invalid_n": invalid_n,
        "actual_top3_hits": sum(row["actual_top3"] for row in lane_rows if row["valid_result"]),
        "table_rows": groups, "table_columns": ("actual_top3_yes", "actual_top3_no"),
        "observed": cells, "expected": expected.tolist(), "expected_cell_min": expected_min,
        "chi_square": float(chi2), "df": int(df), "p_value": float(p_value),
        "cramers_v": math.sqrt(float(chi2) / valid_n),
        "lane_diagnostic": "INCONCLUSIVE" if expected_min < 5 else ("SIGNIFICANT" if p_value < 0.05 else "NOT_SIGNIFICANT"),
        "groups": descriptive, "highest_rate_group": high, "lowest_rate_group": low,
        "max_rate_spread_percentage_points": (rates[high] - rates[low]) * 100,
    }


def final_label(baseline: dict, treatment: dict) -> str:
    if baseline["lane_diagnostic"] == "INCONCLUSIVE" or treatment["lane_diagnostic"] == "INCONCLUSIVE":
        return "INCONCLUSIVE"
    significant = sum(item["p_value"] < 0.05 for item in (baseline, treatment))
    return ("RESIDUAL_INFORMATION_ESTABLISHED" if significant == 2 else
            "SINGLE_LANE_SIGNAL" if significant == 1 else
            "NO_RESIDUAL_INFORMATION_ESTABLISHED")


def main() -> int:
    if OUT.exists():
        raise Stop(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    OUT.mkdir(parents=True)
    before = {name: sha(ROOT / name) for name in PROTECTED}
    head_before = git_value("rev-parse", "HEAD")
    result_access_started = False
    try:
        dates = eval_dates()
        phase0_rows, authority, source_hashes = phase0(dates)
        write_csv("phase0_assigned_field_size_audit.csv", phase0_rows, [
            "race_id", "date", "venue", "race_number", "assigned_field_size", "source_field", "source_file",
            "source_sha256", "de_source_file", "de_source_sha256", "provenance_method",
            "min_assigned_horse_number", "max_assigned_horse_number", "detected_horse_number_gaps", "provenance_pass",
        ])
        dump("phase0_provenance.json", {
            "DRAW_POSITION_PHASE0_PROVENANCE_GATE": "PASS", "ASSIGNED_FIELD_SIZE_RESOLVED_RACES": 828,
            "ASSIGNED_FIELD_SIZE_UNRESOLVED_RACES": 0, "RESULT_ACCESS_DURING_PHASE0": 0,
            "authority": "DG explicit declared field_size at column 10 (index 9)",
            "supporting_integrity": "Existing Adapter fixed-schema, date, DG race, DE identity, and DG/DE head-count validators",
            "adapter_path": "review/target_bulk_prediction_input_adapter_v1.py", "adapter_sha256": sha(ROOT / "review/target_bulk_prediction_input_adapter_v1.py"),
            "source_hashes": source_hashes,
        })
        manifest, group_summary = grouping(dates, authority)
        manifest_path = write_csv("pre_result_draw_manifest.csv", manifest, [
            "lane", "date", "race_id", "venue", "race_number", "horse_number", "horse_name",
            "assigned_field_size", "draw_position_group", "field_size_source", "field_size_source_sha256",
        ])
        dump("grouping_summary_pre_result.json", {
            "DRAW_POSITION_PRE_RESULT_GROUPING_GATE": "PASS", "lanes": group_summary,
            "RESULT_FILE_ACCESS_BEFORE_PRE_FREEZE": 0,
        })
        freeze = {
            "axis_name": "INCREMENTAL_FINE_GRAIN_DRAW_POSITION", "raw_field": "assigned horse_number",
            "denominator_source": "OFFICIAL_ASSIGNED_FIELD_SIZE_AT_DRAW_FREEZE from DG field_size index 9",
            "grouping_formula": {"INNER": "h <= ceil(N/3)", "MIDDLE": "ceil(N/3) < h <= ceil(2N/3)", "OUTER": "h > ceil(2N/3)"},
            "scope_dates": dates, "scope_date_count": 45, "scope_race_ids": sorted(row["race_id"] for row in phase0_rows),
            "scope_race_count": 828, "february_used": 0,
            "natural_buy_identifiers": {lane: [f'{row["date"]}|{row["race_id"]}|{row["horse_number"]}' for row in manifest if row["lane"] == lane.upper()] for lane in ("baseline", "treatment")},
            "pre_result_draw_manifest_sha256": sha(manifest_path),
            "test": "Pearson chi-square test of independence; 3 draw groups x 2 actual_top3 outcomes; no Yates correction",
            "alpha": 0.05, "expected_cell_rule": "Any expected cell < 5 makes that lane INCONCLUSIVE; no substitute test",
            "cross_lane_contract": {"both_significant": "RESIDUAL_INFORMATION_ESTABLISHED", "exactly_one": "SINGLE_LANE_SIGNAL", "neither": "NO_RESIDUAL_INFORMATION_ESTABLISHED", "expected_cell_failure": "INCONCLUSIVE", "integrity_failure": "INVALID"},
            "evidence_role": "NON_EVIDENTIAL_DEVELOPMENT_DIAGNOSTIC_ONLY",
            "result_access_before_freeze": 0,
        }
        freeze_path = dump("pre_result_freeze.json", freeze)
        pre_result_freeze_sha = sha(freeze_path)

        # Result boundary: no result helper or result file was touched above.
        result_access_started = True
        results = {date: result_rows(date) for date in dates}
        joined = []
        invalid_rows = []
        for row in manifest:
            _, venue_key, race_number = parse_race_id(row["race_id"])
            result = results[row["date"]].get((JAPANESE_VENUE[venue_key], race_number))
            if result is None:
                raise Stop(f"RESULT_RACE_UNMATCHED:{row['race_id']}")
            valid, finish, top3 = outcome(result, row["horse_number"])
            joined_row = {**row, "valid_result": valid, "actual_top3": bool(top3) if valid else None}
            joined.append(joined_row)
            if not valid:
                invalid_rows.append({k: joined_row[k] for k in ("lane", "date", "race_id", "horse_number", "horse_name", "draw_position_group", "valid_result", "actual_top3")})

        baseline = contingency([row for row in joined if row["lane"] == "BASELINE"])
        treatment = contingency([row for row in joined if row["lane"] == "TREATMENT"])
        label = final_label(baseline, treatment)
        dump("baseline_contingency.json", baseline)
        dump("treatment_contingency.json", treatment)
        dump("statistical_results.json", {
            "alpha": 0.05, "baseline": baseline, "treatment": treatment,
            "FINE_GRAIN_DRAW_POSITION_DIAGNOSTIC": label,
            "CROSS_LANE_PATTERN_DESCRIPTION": f"Baseline highest/lowest={baseline['highest_rate_group']}/{baseline['lowest_rate_group']}; Treatment highest/lowest={treatment['highest_rate_group']}/{treatment['lowest_rate_group']}",
            "EVIDENCE_ROLE": "NON_EVIDENTIAL_DEVELOPMENT_DIAGNOSTIC_ONLY",
        })
        dump("invalid_result_audit.json", {"invalid_selection_count": len(invalid_rows), "invalid_selections": invalid_rows, "counted_as_failure": False})
        dump("result_access_audit.json", {
            "RESULT_FILE_ACCESS_BEFORE_PHASE0_PASS": 0, "RESULT_FILE_ACCESS_BEFORE_PRE_FREEZE": 0,
            "RESULT_FILE_ACCESS_COUNT": len(dates) * 2, "RESULT_SOURCE_PAIR_COUNT": len(dates),
            "ACTUAL_TOP3_ACCESS_COUNT": len(joined), "consumed_fields": ["valid_result", "actual_top3"],
        })
        after = {name: sha(ROOT / name) for name in PROTECTED}
        source_after = {name: sha(ROOT / name) for name in source_hashes}
        safety = {
            "status": "PASS" if before == after and source_hashes == source_after else "FAIL",
            "protected_hashes_before": before, "protected_hashes_after": after,
            "source_hashes_unchanged": source_hashes == source_after, "git_head_before": head_before,
            "git_head_after": git_value("rev-parse", "HEAD"), "FEBRUARY_USED": 0,
            "THRESHOLD_SEARCH_PERFORMED": 0, "SUBGROUP_SEARCH_PERFORMED": 0,
            "MODEL_TRAINING_PERFORMED": 0, "BUY_POLICY_CHANGE": 0, "ENGINE_CHANGE": 0,
            "STAGE_B_CHANGE": 0, "CANDIDATE_GENERATOR_CHANGE": 0, "V4_CHANGE": 0,
            "PRODUCTION_CHANGE": 0, "LEDGER_CHANGE": 0, "FINGERPRINT_CHANGE": 0,
            "PRODUCTION_IMPLEMENTATION_AUTHORIZED": "NO",
        }
        dump("safety.json", safety)
        report = [
            "# Fine-Grain Draw Position Residual Diagnostic V1", "",
            "`DRAW_POSITION_PHASE0_PROVENANCE_GATE = PASS`", "",
            "- Assigned field size resolved/unresolved: `828 / 0`", "- Scope: `45 dates / 828 races`; February used: `0`",
            f"- PRE_RESULT_FREEZE_SHA256: `{pre_result_freeze_sha}`", "",
            "`DRAW_POSITION_PRE_RESULT_GROUPING_GATE = PASS`", "",
            f"- Baseline pre-result N: `{EXPECTED_N['baseline']}`; INNER/MIDDLE/OUTER: `{group_summary['baseline']['group_n'].get('INNER',0)} / {group_summary['baseline']['group_n'].get('MIDDLE',0)} / {group_summary['baseline']['group_n'].get('OUTER',0)}`",
            f"- Treatment pre-result N: `{EXPECTED_N['treatment']}`; INNER/MIDDLE/OUTER: `{group_summary['treatment']['group_n'].get('INNER',0)} / {group_summary['treatment']['group_n'].get('MIDDLE',0)} / {group_summary['treatment']['group_n'].get('OUTER',0)}`", "",
        ]
        for name, value in (("Baseline", baseline), ("Treatment", treatment)):
            report += [f"## {name}", "", f"- valid / invalid: `{value['valid_n']} / {value['invalid_n']}`"]
            for group in ("INNER", "MIDDLE", "OUTER"):
                item = value["groups"][group]
                report.append(f"- {group}: N `{item['N']}`, Top3 `{item['Top3_Hits']}`, rate `{item['Top3_Rate']:.6%}`")
            report += [f"- chi-square `{value['chi_square']:.12g}`, df `{value['df']}`, p `{value['p_value']:.12g}`",
                       f"- Cramer's V `{value['cramers_v']:.12g}`, expected-cell min `{value['expected_cell_min']:.12g}`",
                       f"- highest / lowest / spread pt: `{value['highest_rate_group']} / {value['lowest_rate_group']} / {value['max_rate_spread_percentage_points']:.6f}`", ""]
        report += [f"`FINE_GRAIN_DRAW_POSITION_DIAGNOSTIC = {label}`", "",
                   "`EVIDENCE_ROLE = NON_EVIDENTIAL_DEVELOPMENT_DIAGNOSTIC_ONLY`", "",
                   "Production implementation is not authorized.", "",
                   "`NEXT = CHATGPT_HUMAN_FINE_GRAIN_DRAW_POSITION_RESULT_REVIEW`", ""]
        (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
        dump("artifact_hash_index.json", {"self_hash_excluded": True, "indexed_artifacts": {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "artifact_hash_index.json"}})
        print(json.dumps({"status": label, "pre_result_freeze_sha256": pre_result_freeze_sha, "baseline": baseline, "treatment": treatment}, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        status = "INVALID" if result_access_started else "STOP_ASSIGNED_FIELD_SIZE_PROVENANCE_FAILURE"
        dump("safety.json", {"status": "STOP", "reason": str(error), "result_access_started": result_access_started, "PRODUCTION_CHANGE": 0, "ENGINE_CHANGE": 0})
        dump("report.md", {"DRAW_POSITION_DIAGNOSTIC": status, "reason": str(error), "RESULT_ACCESS_DURING_PHASE0": 0 if not result_access_started else "NOT_APPLICABLE"})
        dump("artifact_hash_index.json", {"self_hash_excluded": True, "indexed_artifacts": {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "artifact_hash_index.json"}})
        print(f"{status}: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
