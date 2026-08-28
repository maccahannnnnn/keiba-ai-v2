"""Atomic May 2026 POST evaluation of immutable Current/CF/V4/P50 PRE selections."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PRE = ROOT / "reports" / "may_2026_multi_system_oos_v1" / "pre_retry_v5"
RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
OUT = ROOT / "reports" / "may_2026_multi_system_oos_v1" / "post_v1"
DATES = ("20260502", "20260503", "20260509", "20260510", "20260516", "20260517", "20260523", "20260524", "20260530", "20260531")
EXPECTED_PRE = {"race_count": 192, "horse_count": 2645, "current_buy_count": 181, "cf_race_count": 54, "cf_selected_count": 162, "converged_race_count": 100}

from review import april_one_shot_post_evaluation_v1 as april
from review.target_bulk_prediction_input_adapter_v1 import COURSE_KEYS
from review.target_daily_result_list_schema_v2_validator import validate_source_pair


class Stop(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}:{detail}")
        self.code, self.detail = code, detail


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)).replace("\\", "/"): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def metric(rows: list[dict]) -> dict[str, object]:
    valid = [row for row in rows if row["valid_result"]]
    top3 = [row for row in valid if row["actual_top3"]]
    return {"selected_count": len(rows), "valid_selected_count": len(valid), "top3_count": len(top3), "invalid_result_count": len(rows) - len(valid), "top3_rate": len(top3) / len(valid) if valid else None}


def rate_lift(left: dict, right: dict) -> float | None:
    if left["top3_rate"] is None or right["top3_rate"] is None:
        return None
    return left["top3_rate"] - right["top3_rate"]


def race_result(primary: dict[str, list[str]], race_id: str) -> tuple[str, list[str]]:
    parts = race_id.split("_")
    if len(parts) != 4 or not parts[3].endswith("R"):
        raise Stop("PRE_RACE_ID_INVALID", race_id)
    venue_key, race_number = parts[2], int(parts[3][:-1])
    venue = next((name for name, key in COURSE_KEYS.items() if key == venue_key), None)
    matches = [(key, row) for key, row in primary.items() if row[1] == venue and int(row[2]) == race_number]
    if len(matches) != 1:
        raise Stop("PRE_RESULT_JOIN_FAILURE", f"{race_id}:{len(matches)}")
    return matches[0]


def outcome(row: list[str], horse_number: int) -> dict[str, object]:
    return april.source_c_outcome(row, horse_number)


def inventory_and_crosscheck() -> tuple[dict, dict[str, dict], dict]:
    records, lookup, cross_records = [], {}, []
    for date in DATES:
        primary_path = RAW / f"馬番順着順_{date}.csv"
        auxiliary_path = RAW / f"着順馬番_{date}.csv"
        if not primary_path.is_file() or not auxiliary_path.is_file():
            raise Stop("RESULT_SOURCE_INVENTORY_FAILURE", f"MISSING:{date}")
        try:
            structural = validate_source_pair(primary_path, auxiliary_path, date)
        except Exception as exc:
            raise Stop("RESULT_SOURCE_INVENTORY_FAILURE", f"SCHEMA:{date}:{exc}") from exc
        primary_rows, auxiliary_rows = april.read_rows(primary_path), april.read_rows(auxiliary_path)
        primary, auxiliary = {row[0]: row for row in primary_rows}, {row[0]: row for row in auxiliary_rows}
        if len(primary) != len(primary_rows) or len(auxiliary) != len(auxiliary_rows):
            raise Stop("RESULT_SOURCE_INVENTORY_FAILURE", f"DUPLICATE_RACE:{date}")
        if set(primary) != set(auxiliary):
            raise Stop("RESULT_CROSSCHECK_STOP", f"RACE_SET:{date}")
        per_date = []
        for race_key in sorted(primary):
            try:
                per_date.append(april.crosscheck_one(primary[race_key], auxiliary[race_key], race_key))
            except Exception as exc:
                raise Stop("RESULT_CROSSCHECK_STOP", f"{date}:{exc}") from exc
        records.append({"date": date, "primary": {"role": "HORSE_NUMBER_ORDER_FINISH_STATUS", "path": str(primary_path.relative_to(ROOT)), "sha256": sha(primary_path)}, "auxiliary": {"role": "FINISH_ORDER_HORSE_NUMBER_CROSSCHECK_ONLY", "path": str(auxiliary_path.relative_to(ROOT)), "sha256": sha(auxiliary_path)}, "schema_validation": structural})
        lookup[date] = {"primary": primary, "auxiliary": auxiliary}
        cross_records.extend({"date": date, **record} for record in per_date)
    return ({"status": "PASS", "date_count": len(DATES), "file_count": len(DATES) * 2, "records": records}, lookup, {"status": "PASS", "race_count": len(cross_records), "records": cross_records})


def join_pre(lookup: dict[str, dict]) -> tuple[list[dict], dict[str, dict]]:
    current = json.loads((PRE / "current_ai_pre.json").read_text(encoding="utf-8"))["races"]
    if len(current) != EXPECTED_PRE["race_count"] or len({row["race_id"] for row in current}) != len(current):
        raise Stop("PRE_IDENTITY_FAILURE", "CURRENT_AI_RACE_SET")
    all_horses, by_race = [], {}
    for row in current:
        race_id, date = row["race_id"], row["date"]
        race_key, source = race_result(lookup[date]["primary"], race_id)
        horses = []
        buy = set(row["current_buy"])
        for number in row["horse_numbers"]:
            number = int(number)
            joined = {"date": date, "race_id": race_id, "target_race_key": race_key, "horse_number": number, "current_buy": number in buy, "race_state": row["race_state"], **outcome(source, number)}
            horses.append(joined)
            all_horses.append(joined)
        by_race[race_id] = {"pre": row, "horses": horses}
    identities = {(row["race_id"], row["horse_number"]) for row in all_horses}
    if len(all_horses) != EXPECTED_PRE["horse_count"] or len(identities) != len(all_horses):
        raise Stop("PRE_RESULT_JOIN_FAILURE", f"HORSE_IDENTITY:{len(all_horses)}:{len(identities)}")
    return all_horses, by_race


def selected_outcomes(by_race: dict[str, dict], selections: list[dict]) -> list[dict]:
    result = []
    for selection in selections:
        race = by_race.get(selection["race_id"])
        if race is None:
            raise Stop("PRE_RESULT_JOIN_FAILURE", f"SELECTION_RACE:{selection['race_id']}")
        number = int(selection["horse_number"])
        matches = [row for row in race["horses"] if row["horse_number"] == number]
        if len(matches) != 1:
            raise Stop("PRE_RESULT_JOIN_FAILURE", f"SELECTION_HORSE:{selection['race_id']}:{number}")
        result.append({**matches[0], **selection})
    return result


def lodo(records: list[dict]) -> tuple[list[dict], bool]:
    result, negative = [], False
    for held_out in sorted({row["date"] for row in records}):
        remaining = [row for row in records if row["date"] != held_out]
        current_rows = [horse for row in remaining for horse in row["current"]]
        v4_rows = [horse for row in remaining for horse in row["v4"]]
        lift = rate_lift(metric(v4_rows), metric(current_rows))
        negative = negative or (lift is not None and lift < 0)
        result.append({"held_out_date": held_out, "remaining_date_count": len({row["date"] for row in remaining}), "current": metric(current_rows), "v4": metric(v4_rows), "v4_selection_lift": lift, "v4_selection_lift_percentage_points": None if lift is None else lift * 100})
    return result, negative


def main() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    pre_before = tree_hashes(PRE)
    try:
        frozen = json.loads((PRE / "pre_freeze_manifest.json").read_text(encoding="utf-8"))
        if frozen.get("final_status") != "MAY_2026_CURRENT_CF_V4_PRE_FROZEN":
            raise Stop("PRE_FREEZE_AUTHORITY_INVALID", str(frozen.get("final_status")))
        inventory, lookup, crosscheck = inventory_and_crosscheck()
        all_horses, by_race = join_pre(lookup)
        outcomes = {(row["race_id"], row["horse_number"]): row for row in all_horses}

        current_buy = [row for row in all_horses if row["current_buy"]]
        if len(current_buy) != EXPECTED_PRE["current_buy_count"]:
            raise Stop("PRE_SELECTION_IDENTITY_FAILURE", f"CURRENT_BUY:{len(current_buy)}")
        current_by_date = {date: metric([row for row in current_buy if row["date"] == date]) for date in DATES}

        cf_pre = json.loads((PRE / "cf_pre_selection.json").read_text(encoding="utf-8"))["selections"]
        if len(cf_pre) != EXPECTED_PRE["cf_race_count"]:
            raise Stop("PRE_SELECTION_IDENTITY_FAILURE", f"CF_RACES:{len(cf_pre)}")
        cf_selected, cf_pool = [], []
        for record in cf_pre:
            race_id = record["race_id"]
            if by_race[race_id]["pre"]["race_state"] != "PLAY_UNCONVERGED_4PLUS":
                raise Stop("PRE_SELECTION_IDENTITY_FAILURE", f"CF_STATE:{race_id}")
            cf_selected.extend(selected_outcomes(by_race, [{"race_id": race_id, "horse_number": n} for n in record["selected"]]))
            cf_pool.extend(selected_outcomes(by_race, [{"race_id": race_id, "horse_number": row["horse_number"]} for row in record["candidate_pool"]]))
        if len(cf_selected) != EXPECTED_PRE["cf_selected_count"]:
            raise Stop("PRE_SELECTION_IDENTITY_FAILURE", f"CF_SELECTED:{len(cf_selected)}")
        cf_metrics, cf_pool_metrics = metric(cf_selected), metric(cf_pool)
        cf_lift = rate_lift(cf_metrics, cf_pool_metrics)

        v4_pre = json.loads((PRE / "v4_reselection_pre.json").read_text(encoding="utf-8"))["selections"]
        eligible_records = []
        for record in v4_pre:
            race_id = record["race_id"]
            pre = by_race[race_id]["pre"]
            current = [row for row in by_race[race_id]["horses"] if row["current_buy"]]
            v4 = selected_outcomes(by_race, [{"race_id": race_id, "horse_number": n} for n in record["selected"]])
            if pre["race_state"] != "PLAY_CONVERGED" or len(current) != int(record["current_buy_count"]) or len(v4) != len(current):
                raise Stop("PRE_SELECTION_IDENTITY_FAILURE", f"V4_VOLUME:{race_id}")
            if any(row["valid_result"] for row in current) and any(row["valid_result"] for row in v4):
                eligible_records.append({"date": record["date"], "race_id": race_id, "current": current, "v4": v4})
        current_v4 = [horse for record in eligible_records for horse in record["current"]]
        v4_selected = [horse for record in eligible_records for horse in record["v4"]]
        v4_current_metrics, v4_metrics = metric(current_v4), metric(v4_selected)
        v4_lift = rate_lift(v4_metrics, v4_current_metrics)
        lodo_records, lodo_negative = lodo(eligible_records)
        temporal_fragility = bool(v4_lift is not None and v4_lift >= 0 and lodo_negative)
        gates = {"race_count": len(eligible_records) >= 20, "date_count": len({row["date"] for row in eligible_records}) >= 4, "lift": v4_lift is not None and v4_lift >= 0}
        verdict = "V4_MODEL_OOS_REJECT" if not all(gates.values()) else ("V4_MODEL_OOS_ACCEPT_WITH_TEMPORAL_FRAGILITY_FLAG" if temporal_fragility else "V4_MODEL_OOS_ACCEPT")

        p50_pre = json.loads((PRE / "p50_reference_pre.json").read_text(encoding="utf-8"))["selections"]
        p50_selected = [horse for record in p50_pre for horse in selected_outcomes(by_race, [{"race_id": record["race_id"], "horse_number": n} for n in record["selected"]])]
        p50_races = {record["race_id"] for record in p50_pre if record["selected"]}
        p50_zero = sum(not record["selected"] for record in p50_pre)
        p50_current = [horse for record in p50_pre for horse in by_race[record["race_id"]]["horses"] if horse["current_buy"]]
        p50_metrics, p50_current_metrics = metric(p50_selected), metric(p50_current)
        p50_difference = rate_lift(p50_metrics, p50_current_metrics)

        top5 = [row for row in all_horses if row["horse_number"] in set(by_race[row["race_id"]]["pre"]["top5"])]
        errors = Counter(
            "TRUE_BUY_SUCCESS" if row["current_buy"] and row["actual_top3"] else
            "BUY_FALSE_POSITIVE" if row["current_buy"] else
            "TOP5_NONBUY_MISSED" if row["actual_top3"] else "TRUE_BUY_ABSTENTION"
            for row in top5 if row["valid_result"]
        )
        v4_identity = {(row["race_id"], row["horse_number"]) for row in v4_selected}
        fp_demoted = sum(1 for row in top5 if row["valid_result"] and row["current_buy"] and not row["actual_top3"] and (row["race_id"], row["horse_number"]) not in v4_identity)
        missed_recovered = sum(1 for row in top5 if row["valid_result"] and not row["current_buy"] and row["actual_top3"] and (row["race_id"], row["horse_number"]) in v4_identity)
        state_summary = {}
        for state in ("PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"):
            rows = [row for row in all_horses if row["race_state"] == state and row["current_buy"]]
            state_summary[state] = {"race_count": sum(1 for row in by_race.values() if row["pre"]["race_state"] == state), **metric(rows)}

        if tree_hashes(PRE) != pre_before:
            raise Stop("PRE_IMMUTABILITY_FAILURE", "PRE_ARTIFACT_HASH_CHANGED")

        write("result_source_manifest.json", inventory)
        write("result_crosscheck_validation.json", crosscheck)
        write("result_join_manifest.json", {"status": "PASS", "matched_horse_count": len(all_horses), "race_mapping_count": len(by_race), "missing_count": 0, "ambiguous_count": 0, "primary_semantic_authority": "HORSE_NUMBER_ORDER_FINISH_STATUS", "auxiliary_semantic_authority": "CROSSCHECK_ONLY"})
        write("current_ai_evaluation.json", {"frozen_current_buy_count": len(current_buy), **metric(current_buy), "date_breakdown": current_by_date})
        write("cf_evaluation.json", {"eligible_race_count": len(cf_pre), "selected": metric(cf_selected), "pool": metric(cf_pool), "cf_selected_vs_pool_lift": cf_lift, "cf_selected_vs_pool_lift_percentage_points": None if cf_lift is None else cf_lift * 100, "date_breakdown": {date: {"selected": metric([row for row in cf_selected if row["date"] == date]), "pool": metric([row for row in cf_pool if row["date"] == date])} for date in DATES}})
        write("v4_primary_evaluation.json", {"formal_name": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "eligible_independent_race_count": len(eligible_records), "eligible_date_count": len({row["date"] for row in eligible_records}), "current": v4_current_metrics, "v4": v4_metrics, "v4_selection_lift": v4_lift, "v4_selection_lift_percentage_points": None if v4_lift is None else v4_lift * 100})
        write("v4_lodo_diagnostic.json", {"status": "PREREGISTERED_DIAGNOSTIC", "records": lodo_records, "temporal_fragility": temporal_fragility})
        write("p50_reference_evaluation.json", {"formal_name": "P50_REFERENCE_CLASSIFIER_DIAGNOSTIC", "P50_IS_NOT_BUY_POLICY": True, "selected_race_count": len(p50_races), "zero_selection_race_count": p50_zero, "p50": p50_metrics, "current_same_scope": p50_current_metrics, "rate_difference_vs_current": p50_difference, "rate_difference_vs_current_percentage_points": None if p50_difference is None else p50_difference * 100, "volume_difference_vs_current": len(p50_selected) - len(p50_current)})
        write("selection_error_diagnostic.json", {"scope": "SECONDARY_DIAGNOSTIC_PLAY_CONVERGED_TOP5_VALID_POPULATION", "categories": dict(errors), "v4_buy_false_positive_demoted": fp_demoted, "v4_top5_nonbuy_missed_recovered": missed_recovered})
        write("race_state_summary.json", state_summary)
        write("v4_gate_decision.json", {"gate_race_count": {"threshold": 20, "pass": gates["race_count"]}, "gate_date_count": {"threshold": 4, "pass": gates["date_count"]}, "gate_lift": {"threshold_percentage_points": 0.0, "pass": gates["lift"]}, "lodo_temporal_fragility": temporal_fragility, "formal_verdict": verdict})
        write("may_oos_consumption_record.json", {"status": "CONSUMED_INDEPENDENT_OOS_FOR_V4_MODEL_V2", "restriction": "May may not be reused as independent OOS for a changed V4 feature, algorithm, C, threshold, or selection policy."})
        safety = {"status": "PASS", "PRE_SELECTION_MODIFICATION_COUNT": 0, "MODEL_FIT_COUNT": 0, "SCALER_FIT_COUNT": 0, "THRESHOLD_CHANGE_COUNT": 0, "CF_RULE_CHANGE_COUNT": 0, "BUY_RULE_CHANGE_COUNT": 0, "PRODUCTION_CHANGE_COUNT": 0, "POST_RETRY_COUNT": 0, "pre_artifact_hashes_unchanged": True}
        write("safety.json", safety)
        final = {"POST_STATUS": "PASS", "current_ai": metric(current_buy), "cf": {"eligible_race_count": len(cf_pre), "selected": metric(cf_selected), "pool": metric(cf_pool), "lift": cf_lift}, "v4": {"eligible_race_count": len(eligible_records), "eligible_date_count": len({row["date"] for row in eligible_records}), "current": v4_current_metrics, "selected": v4_metrics, "lift": v4_lift, "verdict": verdict}, "p50": {"selected_race_count": len(p50_races), "zero_selection_race_count": p50_zero, **p50_metrics, "rate_difference_vs_current": p50_difference, "volume_difference_vs_current": len(p50_selected) - len(p50_current)}, "MAY_OOS_STATUS": "CONSUMED_INDEPENDENT_OOS_FOR_V4_MODEL_V2", "blocking": [], "major": [], "minor": []}
        write("final_report.json", final)
        report = "# May 2026 Independent OOS — POST Result Evaluation v1\n\n"
        report += f"`MAY_2026_CURRENT_CF_V4_POST_EVALUATION_COMPLETE`\n\n## Current AI\n\nValid BUY: {final['current_ai']['valid_selected_count']} / {len(current_buy)}  \nTop3: {final['current_ai']['top3_count']}  \nBUY_TOP3_RATE: {final['current_ai']['top3_rate']:.2%}\n\n"
        report += f"## CF\n\nEligible races: {len(cf_pre)}  \nValid selected: {cf_metrics['valid_selected_count']} / {len(cf_selected)}  \nTop3: {cf_metrics['top3_count']}  \nCF TOP3 rate: {cf_metrics['top3_rate']:.2%}  \nPool rate: {cf_pool_metrics['top3_rate']:.2%}  \nLift: {cf_lift * 100:+.2f}pt\n\n"
        report += f"## V4 Primary\n\nEligible races/dates: {len(eligible_records)} / {len({row['date'] for row in eligible_records})}  \nCurrent same-volume: {v4_current_metrics['top3_rate']:.2%}  \nV4 same-volume: {v4_metrics['top3_rate']:.2%}  \nLift: {v4_lift * 100:+.2f}pt  \nVerdict: `{verdict}`\n\n"
        report += f"## P50\n\nP50 IS NOT BUY POLICY. Selected horses: {len(p50_selected)}; selected races: {len(p50_races)}; zero-selection races: {p50_zero}; valid: {p50_metrics['valid_selected_count']}; Top3: {p50_metrics['top3_count']}; rate: {p50_metrics['top3_rate']:.2%}.\n"
        (OUT / "final_report.md").write_text(report, encoding="utf-8")
        write("artifact_hashes.json", {"indexed_artifacts": {path.name: sha(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}, "self_hash_excluded": True})
        return OUT
    except Stop as exc:
        write("final_report.json", {"POST_STATUS": "FAIL", "final_status": "MAY_2026_POST_EVALUATION_FAILED", "reason_code": exc.code, "detail": exc.detail, "aggregate_performance_disclosed": False})
        return OUT


if __name__ == "__main__":
    print(main())
