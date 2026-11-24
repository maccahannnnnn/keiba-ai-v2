"""Frozen-artifact-only Candidate / Selection responsibility diagnostic."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/candidate_selection_responsibility_decomposition_v1"
DATES = ("20260829", "20260830", "20260905", "20260906")
V4_DATES = ("20260830", "20260905", "20260906")
VENUES = {"chuukyou": "中京", "hanshin": "阪神", "nakayama": "中山", "niigata": "新潟", "sapporo": "札幌"}
ABNORMAL = {"中止", "除外", "取消", "失格"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def rate(n: float, d: float) -> float | None:
    return n / d if d else None


def frozen_root(date: str) -> Path:
    return ROOT / f"reports/prospective_prediction_{date}_v1"


def result_outcome(row: list[str], horse_number: int) -> dict:
    raw = row[11 + horse_number].strip()
    if raw.isdigit():
        finish = int(raw)
        valid = finish > 0
    elif raw in ABNORMAL:
        finish, valid = 0, False
    else:
        raise RuntimeError(f"INVALID_RESULT_SEMANTICS:{raw}")
    return {"finish": finish, "raw_finish": raw, "valid_result": valid, "actual_top3": bool(valid and finish <= 3)}


def race_parts(race_id: str) -> tuple[str, int]:
    parts = race_id.split("_")
    return parts[-2], int(parts[-1].removesuffix("R"))


def verify_prediction_manifest(date: str) -> dict:
    root = frozen_root(date)
    manifest = json.loads((root / "prediction_manifest.json").read_text(encoding="utf-8"))
    bad = [entry["relative_path"] for entry in manifest["files"] if not (root / entry["relative_path"]).is_file() or sha(root / entry["relative_path"]) != entry["sha256"]]
    if bad:
        raise RuntimeError(f"FROZEN_PRE_MANIFEST_MISMATCH:{date}:{bad}")
    return {"date": date, "prediction_root": str(root.relative_to(ROOT)), "manifest_sha256": sha(root / "prediction_manifest.json"), "files_verified": len(manifest["files"])}


def load_results(date: str) -> tuple[dict, dict]:
    raw = ROOT / "data/raw/target/daily_result_list"
    primary = raw / f"馬番順着順_{date}.csv"
    auxiliary = raw / f"着順馬番_{date}.csv"
    validation = validate_source_pair(primary, auxiliary, date)
    with primary.open(encoding="cp932", newline="") as handle:
        rows = list(csv.reader(handle))
    index = {(row[1], int(row[2])): row for row in rows}
    if len(index) != len(rows):
        raise RuntimeError(f"RESULT_DUPLICATE_RACE:{date}")
    return validation, index


def metric(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(row["actual_top3"] for row in valid)
    return {"selected": len(rows), "valid": len(valid), "invalid": len(rows) - len(valid), "hits": hits, "rate": rate(hits, len(valid))}


def reconstruct_date(date: str) -> tuple[list[dict], list[dict], dict, dict]:
    provenance = verify_prediction_manifest(date)
    validation, results = load_results(date)
    root = frozen_root(date)
    race_index = json.loads((root / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    all_races, primary = [], []
    for item in race_index:
        payload = json.loads((root / item["artifact"]).read_text(encoding="utf-8"))
        venue_key, race_number = race_parts(payload["race_id"])
        venue = VENUES.get(venue_key)
        result = results.get((venue, race_number))
        if result is None:
            raise RuntimeError(f"RESULT_RACE_MISSING:{date}:{payload['race_id']}")
        joined = [{"horse_number": int(horse["horse_number"]), "horse_name": horse["horse_name"], "current_rank": int(horse["rank"]), "frozen_buy": bool(horse["buy"]), **result_outcome(result, int(horse["horse_number"]))} for horse in payload["ranked_results"]]
        if len(joined) != int(result[9]):
            raise RuntimeError(f"PRE_RESULT_HORSE_SET_MISMATCH:{date}:{payload['race_id']}")
        by_number = {horse["horse_number"]: horse for horse in joined}
        top5_numbers = [int(horse["horse_number"]) for horse in payload["top5"]]
        if len(top5_numbers) != len(set(top5_numbers)) or any(number not in by_number for number in top5_numbers):
            raise RuntimeError(f"FROZEN_TOP5_INVALID:{date}:{payload['race_id']}")
        buys = [horse for horse in joined if horse["frozen_buy"]]
        actual_top3 = [horse for horse in joined if horse["actual_top3"]]
        valid_field_size = sum(horse["valid_result"] for horse in joined)
        a_value = sum(horse["actual_top3"] for horse in actual_top3 if horse["horse_number"] in top5_numbers)
        record = {"date": date, "race_id": payload["race_id"], "venue": venue, "venue_key": venue_key, "race_number": race_number,
                  "valid_field_size": valid_field_size, "frozen_top5": [by_number[number] for number in top5_numbers],
                  "frozen_buy": buys, "actual_top3": actual_top3, "A_top5_actual_top3": a_value}
        all_races.append(record)
        if buys:
            k_value = len(buys); m_value = min(k_value, a_value); h_value = sum(horse["actual_top3"] for horse in buys)
            assertions = {
                "K_equals_frozen_buy_count": k_value == len(buys),
                "all_buy_rank_le_5": all(horse["current_rank"] <= 5 for horse in buys),
                "A_in_bounds": 0 <= a_value <= min(3, valid_field_size),
                "M_equals_min_K_A": m_value == min(k_value, a_value),
                "H_le_M": h_value <= m_value,
                "H_le_K": h_value <= k_value,
                "BUY_subset_of_frozen_Top5": all(horse["horse_number"] in top5_numbers for horse in buys),
            }
            if not all(assertions.values()):
                raise RuntimeError(f"PRIMARY_DECOMPOSITION_ASSERTION_FAILURE:{date}:{payload['race_id']}:{assertions}")
            primary.append({**record, "K": k_value, "A": a_value, "M": m_value, "H_current": h_value,
                            "candidate_limited_miss": k_value - m_value, "selection_limited_miss": m_value - h_value,
                            "assertions": assertions})
    return all_races, primary, provenance, validation


def aggregate(records: list[dict]) -> dict:
    totals = {key: sum(record[key] for record in records) for key in ("K", "M", "H_current", "candidate_limited_miss", "selection_limited_miss")}
    total_miss = totals["K"] - totals["H_current"]
    if total_miss:
        candidate_share, selection_share = rate(totals["candidate_limited_miss"], total_miss), rate(totals["selection_limited_miss"], total_miss)
        if abs((candidate_share + selection_share) - 1.0) > 1e-12:
            raise RuntimeError("MISS_SHARE_SUM_INVALID")
    else:
        candidate_share = selection_share = "N/A_NO_MISSES"
    return {"BUY_races": len(records), "SUM_K": totals["K"], "SUM_M": totals["M"], "SUM_H_CURRENT": totals["H_current"],
            "SUM_CANDIDATE_LIMITED_MISS": totals["candidate_limited_miss"], "SUM_SELECTION_LIMITED_MISS": totals["selection_limited_miss"],
            "TOTAL_MISS": total_miss, "CANDIDATE_CEILING_RATE": rate(totals["M"], totals["K"]),
            "CURRENT_SELECTION_EFFICIENCY": rate(totals["H_current"], totals["M"]), "CURRENT_BUY_TOP3_RATE": rate(totals["H_current"], totals["K"]),
            "CANDIDATE_LIMITED_MISS_SHARE": candidate_share, "SELECTION_LIMITED_MISS_SHARE": selection_share}


def v4_selection(date: str) -> dict[str, list[int]]:
    root = ROOT / f"reports/v4_model_v3_formal_prospective/{date}_pre"
    if date == "20260830":
        data = json.loads((root / "v4_prediction.json").read_text(encoding="utf-8"))["races"]
        return {row["race_id"]: [int(horse["horse_number"]) for horse in row["selected_horses"]] for row in data if row["scope_status"] == "ELIGIBLE"}
    data = json.loads((root / "v4_selection.json").read_text(encoding="utf-8"))["races"]
    if date == "20260905":
        return {row["race_id"]: [int(horse[0]) for horse in row["v4_selected"]] for row in data}
    return {row["race_id"]: [int(horse["horse_number"]) for horse in row["selected_horses"]] for row in data if row["scope_status"] == "ELIGIBLE"}


def v4_matched(primary_by_date: dict[str, list[dict]]) -> tuple[dict, list[dict]]:
    matched, per_race = [], []
    for date in V4_DATES:
        frozen = v4_selection(date)
        primary = {row["race_id"]: row for row in primary_by_date[date]}
        if set(frozen) != set(primary):
            raise RuntimeError(f"V4_CURRENT_ELIGIBLE_RACE_SET_MISMATCH:{date}:{set(frozen)^set(primary)}")
        for race_id, numbers in frozen.items():
            record = primary[race_id]
            top5 = {horse["horse_number"] for horse in record["frozen_top5"]}
            current = record["frozen_buy"]
            lookup = {horse["horse_number"]: horse for horse in record["frozen_top5"]}
            if len(current) != record["K"] or len(numbers) != record["K"] or any(number not in top5 for number in numbers):
                raise RuntimeError(f"V4_VOLUME_OR_CANDIDATE_UNIVERSE_MISMATCH:{date}:{race_id}")
            v4 = [lookup[number] for number in numbers]
            current_valid, v4_valid = sum(horse["valid_result"] for horse in current), sum(horse["valid_result"] for horse in v4)
            if current_valid != v4_valid:
                raise RuntimeError(f"VALID_SELECTION_VOLUME_MISMATCH:{date}:{race_id}")
            h_v4 = sum(horse["actual_top3"] for horse in v4 if horse["valid_result"])
            per_race.append({"date": date, "race_id": race_id, "venue": record["venue"], "race_number": record["race_number"],
                             "K": record["K"], "A": record["A"], "M": record["M"], "H_current": record["H_current"], "H_v4": h_v4,
                             "current_selected_numbers": [horse["horse_number"] for horse in current], "v4_selected_numbers": numbers,
                             "valid_selection_volume": current_valid})
            matched.append(per_race[-1])
    total_k, total_m = sum(row["K"] for row in matched), sum(row["M"] for row in matched)
    current_hits, v4_hits = sum(row["H_current"] for row in matched), sum(row["H_v4"] for row in matched)
    return {"dates": list(V4_DATES), "races": len(matched), "SUM_K": total_k, "SUM_M_MATCHED": total_m,
            "SUM_H_CURRENT_MATCHED": current_hits, "SUM_H_V4": v4_hits,
            "CURRENT_MATCHED_SELECTION_EFFICIENCY": rate(current_hits, total_m), "V4_SELECTION_EFFICIENCY": rate(v4_hits, total_m),
            "CURRENT_MATCHED_SELECTION_LIMITED_MISS": total_m - current_hits, "V4_SELECTION_LIMITED_MISS": total_m - v4_hits}, per_race


def normalized_capture(all_races: list[dict]) -> tuple[list[dict], dict, dict, dict]:
    rows = []
    for record in all_races:
        n_value, t_value, observed = record["valid_field_size"], len(record["actual_top3"]), record["A_top5_actual_top3"]
        kc = min(5, n_value)
        expected = t_value * kc / n_value if n_value else None
        if n_value <= 5: position, status = None, "N/A_FULL_FIELD_EQUALS_TOP5"
        elif t_value == 0: position, status = None, "N/A_NO_VALID_TOP3"
        else: position, status = (observed / t_value - kc / n_value) / (1 - kc / n_value), "EVALUABLE"
        bucket = "N<=5" if n_value <= 5 else ("7-9" if n_value <= 9 else ("10-12" if n_value <= 12 else ("13-15" if n_value <= 15 else "16+")))
        rows.append({"date": record["date"], "race_id": record["race_id"], "venue": record["venue"], "race_number": record["race_number"], "valid_field_size_N": n_value,
                     "valid_actual_top3_T": t_value, "Kc": kc, "A_top5": observed, "random_expected_E": expected,
                     "observed_capture_rate": rate(observed, t_value), "random_expected_rate": rate(kc, n_value),
                     "normalized_capture_position": position, "status": status, "field_size_bucket": bucket})
    def rollup(group: list[dict]) -> dict:
        observed, expected, oracle = sum(row["A_top5"] for row in group), sum(row["random_expected_E"] or 0 for row in group), sum(row["valid_actual_top3_T"] for row in group)
        return {"race_count": len(group), "top3_total": oracle, "observed_capture": observed, "random_expected_capture": expected,
                "observed_rate": rate(observed, oracle), "random_expected_rate": rate(expected, oracle),
                "weighted_normalized_capture_position": rate(observed - expected, oracle - expected)}
    daily = {date: rollup([row for row in rows if row["date"] == date]) for date in DATES}
    buckets = {bucket: rollup([row for row in rows if row["field_size_bucket"] == bucket]) for bucket in ("N<=5", "7-9", "10-12", "13-15", "16+") if any(row["field_size_bucket"] == bucket for row in rows)}
    return rows, rollup(rows), daily, buckets


def write_csv(path: Path, rows: list[dict]) -> None:
    keys = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader(); writer.writerows(rows)


def pct(value: float | str | None) -> str:
    return "N/A" if not isinstance(value, (int, float)) else f"{100 * value:.2f}%"


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    ledger = ROOT / "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md"
    fingerprint = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json"
    if not ledger.is_file() or not fingerprint.is_file():
        raise RuntimeError("DUPLICATE_PRECHECK_AUTHORITY_MISSING")
    duplicate = {"status": "PASS", "canonical_name": "CANDIDATE_SELECTION_RESPONSIBILITY_DECOMPOSITION_V1",
                 "evidence_role": "NON_EVIDENTIAL_DEVELOPMENT_DIAGNOSTIC", "formal_gate": "NO", "production_gate": "NO",
                 "authorities": {"ledger": {"path": str(ledger.relative_to(ROOT)), "sha256": sha(ledger)}, "fingerprint_index": {"path": str(fingerprint.relative_to(ROOT)), "sha256": sha(fingerprint)}},
                 "compared_entries": {"ANA-001": "BUY precision aggregate; different unit/metric.", "ANA-002": "failed-BUY-race categorical root cause; different denominator/unit/question.", "ANA-020": "full-field observability feasibility; no slot-level outcome decomposition."},
                 "non_duplicate_question": "All Current BUY races, BUY-slot exact M=min(K,A) decomposition of frozen Top5 ceiling versus frozen BUY selection loss."}
    all_by_date, primary_by_date, provenance, validations = {}, {}, [], {}
    for date in DATES:
        races, primary, pre, validation = reconstruct_date(date)
        all_by_date[date], primary_by_date[date] = races, primary
        provenance.append(pre)
        validations[date] = validation
    all_races = [race for date in DATES for race in all_by_date[date]]
    primary = [race for date in DATES for race in primary_by_date[date]]
    aggregate_all = aggregate(primary)
    daily = {date: aggregate(primary_by_date[date]) for date in DATES}
    v4, v4_rows = v4_matched(primary_by_date)
    capture_rows, capture_aggregate, capture_daily, capture_buckets = normalized_capture(all_races)
    assertion_rows = [{"date": row["date"], "race_id": row["race_id"], "all_pass": all(row["assertions"].values()), **row["assertions"]} for row in primary]
    if not all(row["all_pass"] for row in assertion_rows):
        raise RuntimeError("ASSERTION_AUDIT_FAILURE")
    OUT.mkdir(parents=True)
    protocol = {"canonical_name": duplicate["canonical_name"], "evidence_role": duplicate["evidence_role"], "dates": list(DATES), "primary_unit": "BUY slot within frozen Current BUY-positive race", "definitions": {"K": "Frozen Current BUY count", "A": "valid Actual Top3 inside Frozen Current Top5", "M": "min(K,A)", "candidate_limited_miss": "K-M", "selection_limited_miss": "M-H_current"}, "formal_gate": "NO", "production_gate": "NO", "prohibitions": ["Prediction rerun", "V4 rerun/retrain", "threshold search", "Candidate Generation implementation", "Production change"]}
    dump(OUT / "protocol.json", protocol); dump(OUT / "duplicate_precheck.json", duplicate)
    dump(OUT / "date_inventory.json", {"dates": list(DATES), "consumed_development_diagnostic_data": True, "frozen_pre_provenance": provenance, "result_validation": validations, "untouched_holdout_access_count": 0})
    csv_rows = [{"date": row["date"], "race_id": row["race_id"], "venue": row["venue"], "race_number": row["race_number"], "valid_field_size": row["valid_field_size"], "K": row["K"], "A": row["A"], "M": row["M"], "H_current": row["H_current"], "candidate_limited_miss": row["candidate_limited_miss"], "selection_limited_miss": row["selection_limited_miss"], "buy_numbers": ",".join(str(h["horse_number"]) for h in row["frozen_buy"]), "top5_numbers": ",".join(str(h["horse_number"]) for h in row["frozen_top5"])} for row in primary]
    write_csv(OUT / "race_level_decomposition.csv", csv_rows); dump(OUT / "aggregate_decomposition.json", aggregate_all); dump(OUT / "daily_decomposition.json", daily)
    dump(OUT / "v4_matched_subset.json", {"summary": v4, "races": v4_rows}); write_csv(OUT / "field_size_normalized_capture.csv", capture_rows); dump(OUT / "field_size_bucket_summary.json", capture_buckets); dump(OUT / "top5_normalized_daily.json", {"aggregate": capture_aggregate, "daily": capture_daily}); dump(OUT / "assertion_audit.json", {"status": "PASS", "race_count": len(assertion_rows), "races": assertion_rows})
    safety = {"status": "PASS", "result_source": "CONSUMED_DATES_ONLY", "untouched_holdout_access": 0, "prediction_rerun": 0, "v4_rerun": 0, "v4_retrain": 0, "cf_execution": 0, "model_change": 0, "production_change": 0, "threshold_change": 0, "candidate_generation_implementation": 0, "ledger_change": 0}
    dump(OUT / "safety.json", safety)
    report = f"""# Candidate / Selection Responsibility Diagnostic — 完了

`CANDIDATE_SELECTION_RESPONSIBILITY_DECOMPOSITION_V1 = COMPLETE`

## Current decomposition

- 対象: {aggregate_all['BUY_races']} BUY-positive races / ΣK={aggregate_all['SUM_K']}
- ΣM={aggregate_all['SUM_M']}, ΣH_current={aggregate_all['SUM_H_CURRENT']}
- Candidate-limited miss={aggregate_all['SUM_CANDIDATE_LIMITED_MISS']} ({pct(aggregate_all['CANDIDATE_LIMITED_MISS_SHARE'])})
- Selection-limited miss={aggregate_all['SUM_SELECTION_LIMITED_MISS']} ({pct(aggregate_all['SELECTION_LIMITED_MISS_SHARE'])})
- Candidate Ceiling Rate={pct(aggregate_all['CANDIDATE_CEILING_RATE'])}; Current Selection Efficiency={pct(aggregate_all['CURRENT_SELECTION_EFFICIENCY'])}; BUY Top3 Rate={pct(aggregate_all['CURRENT_BUY_TOP3_RATE'])}

## V4 matched subset

- {v4['races']} races, ΣK={v4['SUM_K']}, ΣM={v4['SUM_M_MATCHED']}
- Current {v4['SUM_H_CURRENT_MATCHED']} / V4 {v4['SUM_H_V4']}
- Current selection efficiency={pct(v4['CURRENT_MATCHED_SELECTION_EFFICIENCY'])}; V4 selection efficiency={pct(v4['V4_SELECTION_EFFICIENCY'])}

## Field-size normalized Current Top5 capture

- Observed={capture_aggregate['observed_capture']}; random expected={capture_aggregate['random_expected_capture']:.3f}; oracle={capture_aggregate['top3_total']}
- Weighted Normalized Capture Position={capture_aggregate['weighted_normalized_capture_position']:.4f}

これは `NON_EVIDENTIAL_DEVELOPMENT_DIAGNOSTIC` であり、Formal Gate・Production Gate・実装承認を発生させない。
"""
    (OUT / "report.md").write_text(report, encoding="utf-8")
    hashes = {path.name: sha(path) for path in OUT.iterdir() if path.is_file() and path.name != "artifact_hash_index.json"}
    dump(OUT / "artifact_hash_index.json", {"self_hash_excluded": True, "hashes": hashes})
    print("CANDIDATE_SELECTION_RESPONSIBILITY_DECOMPOSITION_V1=COMPLETE")


if __name__ == "__main__":
    main()
