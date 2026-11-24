"""Frozen-only 2026-09-06 Current/V4/CF POST and a 9/5–9/6 diagnostic.

The module joins Daily Result List data only after checking all frozen PRE
authorities.  It never invokes prediction, V4 inference, or CF selection.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from review.cf_top3_rank_anchored_shadow_v1 import append_formal_post_evidence
from review.target_daily_result_list_schema_v2_validator import validate_source_pair


ROOT = Path(__file__).resolve().parents[1]
DATE = "20260906"
PRE = ROOT / f"reports/prospective_prediction_{DATE}_v1"
V4PRE = ROOT / f"reports/v4_model_v3_formal_prospective/{DATE}_pre"
V4OUT = ROOT / f"reports/v4_model_v3_formal_prospective/{DATE}_post_retry1"
CFROOT = ROOT / "reports/shadow_cf_top3_rank_anchored_v1"
CFOUT = CFROOT / f"formal_post_{DATE}_retry1"
CURRENT_OUT = ROOT / f"reports/prospective_result_{DATE}_v1_retry1"
TWO_DAY_OUT = ROOT / "reports/current_vs_v4_two_day_diagnostic_20260905_20260906_v1_retry1"
RAW = ROOT / "data/raw/target/daily_result_list"
PRIMARY = RAW / f"馬番順着順_{DATE}.csv"
AUX = RAW / f"着順馬番_{DATE}.csv"
VENUE = {"阪神": "hanshin", "中山": "nakayama", "札幌": "sapporo"}
ABNORMAL = {"中止", "除外", "取消", "失格"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def metric(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(row["actual_top3"] for row in valid)
    return {"selected": len(rows), "invalid": len(rows) - len(valid), "valid": len(valid), "hits": hits,
            "rate": hits / len(valid) if valid else None}


def rate_text(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.2f}%"


def outcome(result_row: list[str], horse_number: int) -> dict:
    raw = result_row[11 + horse_number].strip()
    if raw.isdigit():
        finish = int(raw)
        valid = finish > 0
    elif raw in ABNORMAL:
        finish, valid = 0, False
    else:
        raise RuntimeError(f"INVALID_RESULT_SEMANTICS:{raw}")
    return {"actual_finish": finish, "raw_finish": raw, "valid_result": valid,
            "actual_top3": bool(valid and finish <= 3)}


def parts(race_id: str) -> tuple[str, int]:
    split = race_id.split("_")
    return split[-2], int(split[-1].removesuffix("R"))


def verify_manifest(root: Path, manifest_name: str, key: str) -> tuple[str, int]:
    manifest = json.loads((root / manifest_name).read_text(encoding="utf-8"))
    files = manifest[key]
    failures = [entry["relative_path"] for entry in files
                if not (root / entry["relative_path"]).is_file() or sha(root / entry["relative_path"]) != entry["sha256"]]
    if failures:
        raise RuntimeError(f"FROZEN_MANIFEST_INTEGRITY_FAILURE:{root}:{failures}")
    return sha(root / manifest_name), len(files)


def verify_frozen_pre() -> dict:
    current_sha, current_count = verify_manifest(PRE, "prediction_manifest.json", "files")
    index = json.loads((V4PRE / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
    v4_bad = [name for name, expected in index.items() if not (V4PRE / name).is_file() or sha(V4PRE / name) != expected]
    cf_pre = CFROOT / f"formal_pre_{DATE}.json"
    exception = V4PRE / "exception_provenance.json"
    if v4_bad or not cf_pre.is_file() or not exception.is_file():
        raise RuntimeError(f"FROZEN_PRE_INTEGRITY_FAILURE:{v4_bad}:cf={cf_pre.is_file()}:exception={exception.is_file()}")
    exception_value = json.loads(exception.read_text(encoding="utf-8"))
    input_manifest = json.loads((PRE / "input_manifest.json").read_text(encoding="utf-8"))
    if exception_value.get("input_exception_count") != 1 or input_manifest.get("input_exception", {}).get("mapping_count") != 1:
        raise RuntimeError("INPUT_EXCEPTION_PROVENANCE_INVALID")
    return {"current_manifest_sha256": current_sha, "current_files_verified": current_count,
            "v4_pre_files_verified": len(index), "v4_pre_hash_index_sha256": sha(V4PRE / "artifact_hashes.json"),
            "cf_pre_sha256": sha(cf_pre), "input_exception_sha256": sha(exception),
            "input_exception_mapping_count": 1}


def load_result_rows() -> tuple[dict, dict]:
    validation = validate_source_pair(PRIMARY, AUX, DATE)
    with PRIMARY.open(encoding="cp932", newline="") as handle:
        rows = list(csv.reader(handle))
    index = {(row[1], int(row[2])): row for row in rows}
    if len(index) != len(rows):
        raise RuntimeError("DUPLICATE_RESULT_RACE")
    return validation, index


def frozen_current_join(result_index: dict) -> tuple[dict[str, list[dict]], list[dict], list[dict], list[dict]]:
    race_index = json.loads((PRE / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    by_race, all_rows, top5, race_top3 = {}, [], [], []
    for item in race_index:
        payload = json.loads((PRE / item["artifact"]).read_text(encoding="utf-8"))
        venue_key, race_number = parts(payload["race_id"])
        venue = next((jp for jp, key in VENUE.items() if key == venue_key), None)
        result_row = result_index.get((venue, race_number))
        if result_row is None:
            raise RuntimeError(f"RESULT_RACE_MISSING:{payload['race_id']}")
        joined = []
        for horse in payload["ranked_results"]:
            record = {"race_id": payload["race_id"], "venue": venue, "venue_key": venue_key,
                      "race_number": race_number, "horse_number": int(horse["horse_number"]),
                      "horse_name": horse["horse_name"], "current_rank": horse.get("rank"),
                      "frozen_buy": bool(horse.get("buy")), "frozen_pre": horse, **outcome(result_row, int(horse["horse_number"]))}
            joined.append(record)
            all_rows.append(record)
        if len(joined) != int(result_row[9]):
            raise RuntimeError(f"PRE_RESULT_HORSE_SET_MISMATCH:{payload['race_id']}")
        by_race[payload["race_id"]] = joined
        lookup = {record["horse_number"]: record for record in joined}
        top5.extend(lookup[int(horse["horse_number"])] for horse in payload["top5"])
        race_top3.append({"race_id": payload["race_id"], "venue": venue, "race_number": race_number,
                          "actual_top3": [record for record in joined if record["actual_top3"]],
                          "top5": [lookup[int(horse["horse_number"])] for horse in payload["top5"]]})
    return by_race, all_rows, top5, race_top3


def selected_v4(by_race: dict[str, list[dict]]) -> tuple[list[dict], list[dict]]:
    frozen = json.loads((V4PRE / "v4_selection.json").read_text(encoding="utf-8"))
    all_selected, comparisons = [], []
    for race in frozen["races"]:
        if race.get("scope_status") != "ELIGIBLE":
            continue
        lookup = {record["horse_number"]: record for record in by_race[race["race_id"]]}
        v4 = [{**lookup[int(horse["horse_number"])],
               "v4_probability_frozen": horse["predicted_actual_top3_probability"],
               "shadow_ai_rank": horse["shadow_ai_rank"]}
              for horse in race["selected_horses"]]
        current = [record for record in by_race[race["race_id"]] if record["frozen_buy"]]
        current_metric, v4_metric = metric(current), metric(v4)
        comparison = "EQUAL" if current_metric["hits"] == v4_metric["hits"] else (
            "CURRENT_SUPERIOR" if current_metric["hits"] > v4_metric["hits"] else "V4_SUPERIOR")
        all_selected.extend(v4)
        comparisons.append({"race_id": race["race_id"], "venue": race["venue"], "race_number": race["race_number"],
                            "current": current, "v4": v4, "current_metrics": current_metric,
                            "v4_metrics": v4_metric, "comparison": comparison,
                            "raw_hit_difference": v4_metric["hits"] - current_metric["hits"]})
    return all_selected, comparisons


def selected_cf(by_race: dict[str, list[dict]]) -> tuple[list[dict], list[dict]]:
    frozen = json.loads((CFROOT / f"formal_pre_{DATE}.json").read_text(encoding="utf-8"))
    selected_all, records = [], []
    for race in frozen["eligible_races"]:
        lookup = {record["horse_number"]: record for record in by_race[race["race_id"]]}
        selected = [{**lookup[int(horse["horse_number"])], "shadow_ai_rank": horse["shadow_ai_rank"]}
                    for horse in race["cf_selected_horses"]]
        pool = [{**lookup[int(horse["horse_number"])], "shadow_ai_rank": horse["shadow_ai_rank"]}
                for horse in race["candidate_horses"]]
        selected_all.extend(selected)
        selected_metric, pool_metric = metric(selected), metric(pool)
        records.append({"race_id": race["race_id"], "venue": race["venue"], "race_number": race["race_number"],
                        "selected": selected, "pool": pool, "selected_metrics": selected_metric,
                        "pool_metrics": pool_metric,
                        "difference": None if selected_metric["rate"] is None or pool_metric["rate"] is None else selected_metric["rate"] - pool_metric["rate"]})
    return selected_all, records


def top5_capture(races: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    buckets = {str(index): 0 for index in range(4)}
    capture, misses = [], []
    for race in races:
        inside = [horse for horse in race["actual_top3"] if horse["horse_number"] in {x["horse_number"] for x in race["top5"]}]
        outside = [horse for horse in race["actual_top3"] if horse["horse_number"] not in {x["horse_number"] for x in race["top5"]}]
        buckets[str(len(inside))] += 1
        record = {**race, "inside": inside, "outside": outside, "TOP5_GENERATION_MISS": bool(outside)}
        capture.append(record)
        if outside:
            misses.append(record)
    summary = {"races": len(capture), "valid_actual_top3_total": sum(len(row["actual_top3"]) for row in capture),
               "top5_inside": sum(len(row["inside"]) for row in capture), "top5_outside": sum(len(row["outside"]) for row in capture),
               "capture_buckets": buckets, "at_least_one": sum(count for key, count in buckets.items() if int(key) >= 1),
               "all_three": buckets["3"], "miss_race_count": len(misses),
               "status": "CURRENT_TOP5_CAPTURE_20260906_DEVELOPMENT_DIAGNOSTIC"}
    return summary, capture, misses


def update_v4_cumulative(current_metric: dict, v4_metric: dict, race_count: int) -> dict:
    prior = json.loads((ROOT / "reports/v4_model_v3_formal_prospective/20260905_post/v4_cumulative_derived.json").read_text(encoding="utf-8"))
    result = {"completed_formal_dates": prior["completed_formal_dates"] + 1,
              "eligible_dates": prior["eligible_dates"] + [DATE], "eligible_race_count": prior["eligible_race_count"] + race_count,
              "minimum": {"dates": 12, "races": 60}, "current": {}, "v4": {}}
    for target, daily in (("current", current_metric), ("v4", v4_metric)):
        old = prior[target]
        result[target] = {"selected": old["selected"] + daily["selected"], "valid": old["valid"] + daily["valid"],
                          "hits": old["hits"] + daily["hits"]}
        result[target]["invalid"] = result[target]["selected"] - result[target]["valid"]
        result[target]["rate"] = result[target]["hits"] / result[target]["valid"] if result[target]["valid"] else None
    result["raw_hit_difference"] = result["v4"]["hits"] - result["current"]["hits"]
    result["lift"] = result["v4"]["rate"] - result["current"]["rate"]
    result["uncertainty"] = {"assessment": "NOT_EVALUABLE_INSUFFICIENT_INDEPENDENT_DATES", "completed_dates": result["completed_formal_dates"], "required_dates": 12}
    result["leave_one_date_out"] = dict(result["uncertainty"])
    result["temporal_concentration"] = dict(result["uncertainty"])
    result["state"] = "SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE"
    return result


def replacement_type(comparison: dict) -> str:
    current = {row["horse_number"] for row in comparison["current"]}
    v4 = {row["horse_number"] for row in comparison["v4"]}
    return "EXACT" if current == v4 else ("COMPLETE" if not current.intersection(v4) else "PARTIAL")


def compact_pre(row: dict) -> dict:
    source = row["frozen_pre"]
    return {key: source.get(key) for key in ("rank", "adjusted_score", "decision_score", "final_score", "confidence",
                                               "past_race_count", "consensus_positive_count", "consensus_negative_count",
                                               "conflict_count", "risk_count", "risks", "warnings")}


def hydrate_frozen_pre(comparisons: list[dict], date: str) -> list[dict]:
    """Attach only the already-frozen primary-prediction fields to POST rows."""
    prediction_root = ROOT / f"reports/prospective_prediction_{date}_v1"
    index = json.loads((prediction_root / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    snapshots = {}
    for item in index:
        payload = json.loads((prediction_root / item["artifact"]).read_text(encoding="utf-8"))
        snapshots[payload["race_id"]] = {int(row["horse_number"]): row for row in payload["ranked_results"]}
    for comparison in comparisons:
        for key in ("current", "v4"):
            for row in comparison[key]:
                snapshot = snapshots.get(row["race_id"], {}).get(row["horse_number"])
                if snapshot is None:
                    raise RuntimeError(f"FROZEN_PRE_SNAPSHOT_MISSING:{date}:{row['race_id']}:{row['horse_number']}")
                row["frozen_pre"] = snapshot
    return comparisons


def observed_feature_summary(rows: list[dict]) -> dict:
    numeric = ("rank", "adjusted_score", "decision_score", "final_score", "past_race_count", "consensus_positive_count",
               "consensus_negative_count", "conflict_count", "risk_count")
    output = {"classification": "NOT_OBSERVABLE_FROM_FROZEN_PRE" if not rows else "REPEATED_DIRECTIONAL_OBSERVATION_ONLY",
              "pairing_note": "群平均の比較であり、同一race内の馬を因果的に一対一対応させない。新規ruleには使用しない。", "by_date": {}}
    for date in sorted({row["date"] for row in rows}):
        group = [row for row in rows if row["date"] == date]
        out_values = [row["current_out_pre"] for row in group]
        in_values = [row["v4_in_pre"] for row in group]
        output["by_date"][date] = {key: {"current_out_mean": sum(x[key] for x in out_values if isinstance(x[key], (int, float))) / sum(isinstance(x[key], (int, float)) for x in out_values),
                                          "v4_in_mean": sum(x[key] for x in in_values if isinstance(x[key], (int, float))) / sum(isinstance(x[key], (int, float)) for x in in_values)}
                                  for key in numeric}
        for value in output["by_date"][date].values(): value["v4_minus_current_out"] = value["v4_in_mean"] - value["current_out_mean"]
    output["sample_n"] = len(rows)
    return output


def two_day_diagnostic(today: list[dict]) -> dict:
    prior = json.loads((ROOT / "reports/v4_model_v3_formal_prospective/20260905_post/v4_post.json").read_text(encoding="utf-8"))["comparisons"]
    prior = hydrate_frozen_pre(prior, "20260905")
    today = hydrate_frozen_pre(today, DATE)
    daily = {"20260905": prior, DATE: today}
    summary, horse_changes = {}, []
    for date, comparisons in daily.items():
        complete = [row for row in comparisons if replacement_type(row) == "COMPLETE"]
        partial = [row for row in comparisons if replacement_type(row) == "PARTIAL"]
        exact = [row for row in comparisons if replacement_type(row) == "EXACT"]
        all_current = [horse for row in comparisons for horse in row["current"]]
        all_v4 = [horse for row in comparisons for horse in row["v4"]]
        shared = [horse for row in partial for horse in row["current"] if horse["horse_number"] in {x["horse_number"] for x in row["v4"]}]
        current_out, v4_in = [], []
        for row in comparisons:
            current_numbers = {horse["horse_number"] for horse in row["current"]}
            v4_numbers = {horse["horse_number"] for horse in row["v4"]}
            current_out.extend(horse for horse in row["current"] if horse["horse_number"] not in v4_numbers)
            v4_in.extend(horse for horse in row["v4"] if horse["horse_number"] not in current_numbers)
        for out, incoming in zip(current_out, v4_in):
            if not out["valid_result"] or not incoming["valid_result"]: winner = "INVALID"
            elif out["actual_top3"] and incoming["actual_top3"]: winner = "BOTH_TOP3"
            elif out["actual_top3"]: winner = "CURRENT_OUT"
            elif incoming["actual_top3"]: winner = "V4_IN"
            else: winner = "NEITHER_TOP3"
            horse_changes.append({"date": date, "venue": out["venue"], "race_number": out["race_number"], "race_id": out["race_id"],
                                  "current_out": {"horse_number": out["horse_number"], "horse_name": out["horse_name"], "finish": out["actual_finish"]},
                                  "v4_in": {"horse_number": incoming["horse_number"], "horse_name": incoming["horse_name"], "finish": incoming["actual_finish"]},
                                  "winner": winner, "current_out_pre": compact_pre(out), "v4_in_pre": compact_pre(incoming)})
        summary[date] = {"current": metric(all_current), "v4": metric(all_v4), "raw_advantage": metric(all_v4)["hits"] - metric(all_current)["hits"],
                         "race_comparison_counts": {label: sum(row["comparison"] == label for row in comparisons) for label in ("V4_SUPERIOR", "EQUAL", "CURRENT_SUPERIOR")},
                         "complete_replacement": {"races": len(complete), "current": metric([horse for row in complete for horse in row["current"]]), "v4": metric([horse for row in complete for horse in row["v4"]]), "raw_difference": sum(row["raw_hit_difference"] for row in complete)},
                         "partial_replacement": {"races": len(partial), "shared": metric(shared), "current_only": metric([horse for row in partial for horse in row["current"] if horse["horse_number"] not in {x["horse_number"] for x in row["v4"]}]), "v4_only": metric([horse for row in partial for horse in row["v4"] if horse["horse_number"] not in {x["horse_number"] for x in row["current"]}]), "raw_difference": sum(row["raw_hit_difference"] for row in partial)},
                         "exact_match_races": len(exact)}
    pooled_current = {key: sum(summary[d]["current"][key] for d in summary) for key in ("selected", "invalid", "valid", "hits")}
    pooled_v4 = {key: sum(summary[d]["v4"][key] for d in summary) for key in ("selected", "invalid", "valid", "hits")}
    pooled_current["rate"] = pooled_current["hits"] / pooled_current["valid"] if pooled_current["valid"] else None
    pooled_v4["rate"] = pooled_v4["hits"] / pooled_v4["valid"] if pooled_v4["valid"] else None
    return {"classification": "DEVELOPMENT_DIAGNOSTIC_ONLY", "daily": summary,
            "pooled": {"current": pooled_current, "v4": pooled_v4, "raw_hit_difference": pooled_v4["hits"] - pooled_current["hits"], "rate_points": 100 * (pooled_v4["rate"] - pooled_current["rate"])},
            "mechanism": {"complete_replacement_raw_difference": sum(summary[d]["complete_replacement"]["raw_difference"] for d in summary), "partial_replacement_raw_difference": sum(summary[d]["partial_replacement"]["raw_difference"] for d in summary), "exact_match_raw_difference": 0},
            "current_out_vs_v4_in": horse_changes, "observable_pre_result_feature_summary": observed_feature_summary(horse_changes),
            "v4_full_rank_probability": "NOT_OBSERVABLE_FROM_FROZEN_PRE", "no_rule_change": True}


def markdown_current(metrics: dict, horses: list[dict]) -> str:
    lines = ["# KeibaAI 2026-09-06 Current AI POST", "", "| 場 | R | 馬番 | 馬名 | 着順 | Top3 |", "| --- | ---: | ---: | --- | ---: | --- |"]
    lines += [f"| {h['venue']} | {h['race_number']} | {h['horse_number']} | {h['horse_name']} | {h['raw_finish']} | {'YES' if h['actual_top3'] else 'NO'} |" for h in horses]
    lines += ["", f"selected={metrics['selected']}, invalid={metrics['invalid']}, valid N={metrics['valid']}, Top3 hits={metrics['hits']}, BUY_TOP3_RATE={rate_text(metrics['rate'])}", "", "Frozen PREを再実行・変更せず、正式Daily Result Listとのjoinだけを行った。"]
    return "\n".join(lines) + "\n"


def main() -> None:
    outputs = (CURRENT_OUT, V4OUT, CFOUT, TWO_DAY_OUT)
    if any(path.exists() for path in outputs):
        raise RuntimeError(f"EXCLUSIVE_CREATE_REQUIRED:{[str(path) for path in outputs if path.exists()]}")
    integrity = verify_frozen_pre()
    validation, result_index = load_result_rows()
    by_race, all_rows, _top5, top3_races = frozen_current_join(result_index)
    current = [row for row in all_rows if row["frozen_buy"]]
    current_metric = metric(current)
    v4, comparisons = selected_v4(by_race)
    v4_metric = metric(v4)
    cf, cf_records = selected_cf(by_race)
    cf_metric, pool_metric = metric(cf), metric([horse for row in cf_records for horse in row["pool"]])
    capture_summary, capture_races, misses = top5_capture(top3_races)
    cumulative_v4 = update_v4_cumulative(current_metric, v4_metric, len(comparisons))
    prior_cf = json.loads((CFROOT / "formal_post_20260905/cumulative_evidence_derived.json").read_text(encoding="utf-8"))
    activation = json.loads((CFROOT / "activation_record.json").read_text(encoding="utf-8"))
    post_records = [{"race_id": row["race_id"], "selected_valid_count": row["selected_metrics"]["valid"], "selected_top3_count": row["selected_metrics"]["hits"], "candidate_pool_valid_count": row["pool_metrics"]["valid"], "candidate_pool_top3_count": row["pool_metrics"]["hits"]} for row in cf_records]
    cumulative_cf = append_formal_post_evidence(ledger=prior_cf, date=DATE, activation_record=activation, post_records=post_records, independent_race_count=len(post_records))
    cf_state = "SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE"
    safety = {"status": "PASS", "prediction_rerun": 0, "v4_rerun": 0, "v4_retrain": 0, "cf_reselection": 0,
              "pre_modification": 0, "production_change": 0, "protocol_change": 0, "candidate_generation_change": 0,
              "result_access": "POST_ONLY", "ledger_mutation": 0}
    TWO_DAY_OUT.mkdir(parents=True); CURRENT_OUT.mkdir(parents=True); V4OUT.mkdir(parents=True); CFOUT.mkdir(parents=True)
    dump(CURRENT_OUT / "result_validation.json", validation)
    dump(CURRENT_OUT / "horse_result_mapping.json", {"races": len(by_race), "horses": len(all_rows), "rows": all_rows})
    dump(CURRENT_OUT / "buy_results.json", {"metrics": current_metric, "horses": current, "race_success_count": sum(metric([x for x in rows if x["frozen_buy"]])["hits"] > 0 for rows in by_race.values())})
    dump(CURRENT_OUT / "summary.json", {"status": "KEIBAAI_POST_20260906=COMPLETE", "current": current_metric, "pre_integrity": integrity, "safety": safety})
    (CURRENT_OUT / "report.md").write_text(markdown_current(current_metric, current), encoding="utf-8")
    dump(V4OUT / "pre_integrity.json", integrity); dump(V4OUT / "result_reconciliation.json", validation)
    dump(V4OUT / "current_post.json", {"metrics": current_metric, "horses": current})
    dump(V4OUT / "v4_post.json", {"metrics": v4_metric, "comparisons": comparisons, "difference": {"raw_hits": v4_metric["hits"] - current_metric["hits"], "rate_points": 100 * (v4_metric["rate"] - current_metric["rate"])}})
    dump(V4OUT / "v4_cumulative_derived.json", cumulative_v4)
    dump(V4OUT / "current_top5_capture_diagnostic.json", {"summary": capture_summary, "races": capture_races, "misses": misses, "v4_full_ranking": "NOT_OBSERVABLE_FROM_FROZEN_PRE"})
    dump(V4OUT / "safety.json", safety)
    (V4OUT / "report.md").write_text(f"# KeibaAI 2026-09-06 V4 Formal POST\n\nCurrent {current_metric['hits']}/{current_metric['valid']} ({rate_text(current_metric['rate'])}); V4 {v4_metric['hits']}/{v4_metric['valid']} ({rate_text(v4_metric['rate'])}).\n\nFormal state: `{cumulative_v4['state']}`.\n", encoding="utf-8")
    dump(CFOUT / "cf_post.json", {"selected_metrics": cf_metric, "pool_metrics": pool_metric, "difference": None if cf_metric["rate"] is None or pool_metric["rate"] is None else cf_metric["rate"] - pool_metric["rate"], "races": cf_records})
    dump(CFOUT / "cumulative_evidence_derived.json", cumulative_cf)
    dump(CFOUT / "formal_status.json", {"state": cf_state, "dates": cumulative_cf["formal_independent_date_count"], "races": cumulative_cf["formal_independent_race_count"], "minimum": {"dates": 4, "races": 20}})
    dump(CFOUT / "safety.json", safety)
    (CFOUT / "report.md").write_text(f"# CF 2026-09-06 Formal POST\n\nselected {cf_metric['hits']}/{cf_metric['valid']} ({rate_text(cf_metric['rate'])}); pool {pool_metric['hits']}/{pool_metric['valid']} ({rate_text(pool_metric['rate'])}).\n\nState: `{cf_state}`.\n", encoding="utf-8")
    diagnostic = two_day_diagnostic(comparisons)
    dump(TWO_DAY_OUT / "two_day_diagnostic.json", diagnostic)
    dump(TWO_DAY_OUT / "safety.json", safety)
    (TWO_DAY_OUT / "report.md").write_text(f"# 2026-09-05 / 2026-09-06 Current vs V4 Development Diagnostic\n\n2日合計: Current {diagnostic['pooled']['current']['hits']}/{diagnostic['pooled']['current']['valid']} ({rate_text(diagnostic['pooled']['current']['rate'])}), V4 {diagnostic['pooled']['v4']['hits']}/{diagnostic['pooled']['v4']['valid']} ({rate_text(diagnostic['pooled']['v4']['rate'])}).\n\nこれはDevelopment Diagnosticであり、新規Formal Gateまたはrule変更ではない。\n", encoding="utf-8")
    for root in outputs:
        hashes = {path.name: sha(path) for path in root.iterdir() if path.is_file() and path.name != "artifact_hashes.json"}
        dump(root / "artifact_hashes.json", {"self_hash_excluded": True, "hashes": hashes})
    print("KEIBAAI_POST_20260906=COMPLETE")


if __name__ == "__main__":
    main()
