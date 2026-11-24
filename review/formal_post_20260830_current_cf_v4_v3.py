"""Atomic POST evaluation for the frozen 2026-08-30 Current/CF/V4-v3 PRE.

This is a post-only, additive report generator.  It never invokes prediction,
modifies a frozen PRE artifact, or changes any production selection rule.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from review.cf_top3_rank_anchored_shadow_v1 import append_formal_post_evidence
from review.target_daily_result_list_schema_v2_validator import validate_source_pair
from review.v4_model_v3_prospective_validator_v1 import (
    ROLE,
    decision_state,
    lift,
    selected_metric,
    same_volume,
    uncertainty,
    validate_ledger,
)


ROOT = Path(__file__).resolve().parents[1]
DATE = "20260830"
PRE_ROOT = ROOT / "reports" / "prospective_prediction_20260830_v1"
V4_PRE_ROOT = ROOT / "reports" / "v4_model_v3_formal_prospective" / "20260830_pre"
V4_OUT = ROOT / "reports" / "v4_model_v3_formal_prospective" / "20260830_post"
CF_ROOT = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1"
CF_OUT = CF_ROOT / "formal_post_20260830"
CF_20260829_POST = ROOT / "reports" / "prospective_20260829_post" / "cf_formal_prospective_post.json"
RAW_ROOT = ROOT / "data" / "raw" / "target" / "daily_result_list"
PRIMARY = RAW_ROOT / "馬番順着順_20260830.csv"
AUXILIARY = RAW_ROOT / "着順馬番_20260830.csv"
VENUES = {"sapporo": "札幌", "niigata": "新潟", "chuukyou": "中京"}
ABNORMAL = {"中止", "除外", "取消", "失格"}

EXPECTED_CURRENT = {
    ("chuukyou", 6): [12], ("chuukyou", 12): [3], ("niigata", 6): [1],
    ("niigata", 8): [2, 5], ("niigata", 9): [12], ("niigata", 12): [5, 8, 13],
}
EXPECTED_CF = {
    ("chuukyou", 5): [8, 2, 3], ("niigata", 7): [10, 3, 2],
    ("niigata", 11): [2, 10, 12], ("sapporo", 6): [2, 7, 12],
    ("sapporo", 10): [4, 16, 10], ("sapporo", 12): [1, 13, 14],
}
EXPECTED_V4 = {
    ("chuukyou", 6): [15], ("chuukyou", 12): [3], ("niigata", 6): [11],
    ("niigata", 8): [5, 8], ("niigata", 9): [8], ("niigata", 12): [6, 8, 13],
}
EXPECTED_PRE_REVIEW_SHA = "8ef4915b12ab0391b0eeb2bef8f76c62930baacd18a87d075c5b0998e7ba2816"
EXPECTED_MODEL_SHA = "7f06d9e3ba2f330b6f42d699ee25ea64d83a5287c3b7f72fb0233e14c755312d"
EXPECTED_SCALER_SHA = "800a0d54307e0caafef7b8efd131f5ab60f1d75d1e021dae7627d690187d103c"
EXPECTED_PROTOCOL_SHA = "2e18aaf5795faf47997b2ed38e5aab5a09d718049be438139bdb0b37e3b2885e"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(root: Path, name: str, value: Any) -> None:
    (root / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def rate(hits: int, valid: int) -> float | None:
    return hits / valid if valid else None


def race_parts(race_id: str) -> tuple[str, int]:
    tokens = race_id.split("_")
    return tokens[-2], int(tokens[-1].removesuffix("R"))


def fmt(row: dict[str, Any]) -> str:
    state = "INVALID" if not row["valid_result"] else ("Top3" if row["actual_top3"] else "MISS")
    return f"#{row['horse_number']} {row['horse_name']} → {row['actual_finish']}着 [{state}]"


def verify_frozen_pre() -> dict[str, Any]:
    manifest_path = PRE_ROOT / "prediction_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches = []
    for item in manifest["files"]:
        path = PRE_ROOT / item["relative_path"]
        if not path.is_file() or sha(path) != item["sha256"]:
            mismatches.append(item["relative_path"])
    if mismatches:
        raise RuntimeError(f"FROZEN_PRE_MANIFEST_MISMATCH:{mismatches}")
    review = V4_PRE_ROOT / "pre_independent_review_manifest.json"
    if sha(review) != EXPECTED_PRE_REVIEW_SHA:
        raise RuntimeError("PRE_INDEPENDENT_REVIEW_MANIFEST_MISMATCH")
    v4_pre_hashes = json.loads((V4_PRE_ROOT / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
    for name, expected in v4_pre_hashes.items():
        path = V4_PRE_ROOT / name
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"V4_PRE_ARTIFACT_MISMATCH:{name}")
    if sha(ROOT / "reports/ml_v4_buy_selection_model_v3/model.joblib") != EXPECTED_MODEL_SHA:
        raise RuntimeError("MODEL_V3_SHA_MISMATCH")
    if sha(ROOT / "reports/ml_v4_buy_selection_model_v3/scaler.joblib") != EXPECTED_SCALER_SHA:
        raise RuntimeError("SCALER_V3_SHA_MISMATCH")
    if sha(ROOT / "reports/v4_model_v3_prospective_protocol_v1/protocol.json") != EXPECTED_PROTOCOL_SHA:
        raise RuntimeError("V4_PROTOCOL_SHA_MISMATCH")
    return {"prediction_manifest_sha256": sha(manifest_path), "prediction_files_verified": len(manifest["files"]), "v4_pre_files_verified": len(v4_pre_hashes), "claude_independent_review_sha256": sha(review)}


def source_integrity() -> tuple[dict[str, Any], dict[tuple[str, int], list[str]]]:
    if not PRIMARY.is_file() or not AUXILIARY.is_file():
        raise RuntimeError("RESULT_SOURCE_MISSING")
    validation = validate_source_pair(PRIMARY, AUXILIARY, DATE)
    with PRIMARY.open(encoding="cp932", newline="") as handle:
        primary_rows = list(csv.reader(handle))
    with AUXILIARY.open(encoding="cp932", newline="") as handle:
        auxiliary_rows = list(csv.reader(handle))
    primary_index = {(row[1], int(row[2])): row for row in primary_rows}
    auxiliary_index = {(row[1], int(row[2])): row for row in auxiliary_rows}
    if len(primary_index) != len(primary_rows) or len(auxiliary_index) != len(auxiliary_rows):
        raise RuntimeError("DUPLICATE_RESULT_RACE")
    if set(primary_index) != set(auxiliary_index):
        raise RuntimeError("RESULT_RACE_IDENTITY_UNRESOLVED")
    disagreements: list[str] = []
    for key, row in primary_index.items():
        head = int(row[9])
        shown = auxiliary_index[key][12:12 + head]
        if sorted(int(x) for x in shown) != list(range(1, head + 1)):
            disagreements.append(f"{key}:AUX_HORSE_SET")
            continue
        for finish_position, horse_no in enumerate(shown, start=1):
            raw = row[11 + int(horse_no)].strip()
            if raw.isdigit() and int(raw) > 0 and int(raw) != finish_position:
                disagreements.append(f"{key}:horse={horse_no}")
    if disagreements:
        raise RuntimeError(f"RESULT_SOURCE_HORSE_CONSISTENCY_MISMATCH:{disagreements}")
    validation.update({
        "source_horse_consistency": "PASS", "duplicate_race_count": 0,
        "unresolved_identity_count": 0, "source_disagreement_count": 0,
        "primary_sha256": sha(PRIMARY), "auxiliary_sha256": sha(AUXILIARY),
    })
    return validation, primary_index


def cf_prior_formal_ledger() -> dict[str, Any]:
    """Use the frozen 8/29 formal-post derivative, never mutate CF's seed ledger."""
    index = json.loads((CF_20260829_POST.parent / "artifact_hashes.json").read_text(encoding="utf-8"))
    expected = index["hashes"].get(CF_20260829_POST.name)
    if expected is None or sha(CF_20260829_POST) != expected:
        raise RuntimeError("CF_20260829_FORMAL_POST_HASH_MISMATCH")
    ledger = json.loads(CF_20260829_POST.read_text(encoding="utf-8"))["cumulative_ledger_after_20260829"]
    if ledger.get("formal_independent_date_count") != 1 or [x.get("date") for x in ledger.get("formal_evidence", [])] != ["20260829"]:
        raise RuntimeError("CF_20260829_FORMAL_LEDGER_MISMATCH")
    return ledger


def outcome(result_row: list[str], horse_number: int) -> dict[str, Any]:
    raw = result_row[11 + horse_number].strip()
    if raw.isdigit():
        finish = int(raw)
        valid = finish > 0
    elif raw in ABNORMAL:
        finish, valid = 0, False
    else:
        raise RuntimeError(f"INVALID_RESULT_SEMANTICS_REQUIRED:{raw}")
    return {"actual_finish": finish, "raw_finish": raw, "valid_result": valid, "actual_top3": bool(valid and finish <= 3)}


def current_join(results: dict[tuple[str, int], list[str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    index = json.loads((PRE_ROOT / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    if len(index) != 19:
        raise RuntimeError("FROZEN_RACE_COUNT_MISMATCH")
    all_horses, buys, by_race = [], [], {}
    for item in index:
        payload = json.loads((PRE_ROOT / item["artifact"]).read_text(encoding="utf-8"))
        venue_key, number = race_parts(payload["race_id"])
        row = results.get((VENUES[venue_key], number))
        if row is None:
            raise RuntimeError(f"FROZEN_RACE_RESULT_MISSING:{payload['race_id']}")
        joined = []
        for horse in payload["ranked_results"]:
            result = {"race_id": payload["race_id"], "venue_key": venue_key, "venue": VENUES[venue_key], "race_number": number,
                      "horse_number": int(horse["horse_number"]), "horse_name": horse["horse_name"], "current_ai_rank": horse.get("rank"),
                      "frozen_buy": bool(horse.get("buy", horse.get("decision") == "BUY")), **outcome(row, int(horse["horse_number"]))}
            joined.append(result); all_horses.append(result)
            if result["frozen_buy"]: buys.append(result)
        by_race[payload["race_id"]] = joined
    actual = {
        (rows[0]["venue_key"], rows[0]["race_number"]): sorted(row["horse_number"] for row in rows if row["frozen_buy"])
        for rows in by_race.values() if any(row["frozen_buy"] for row in rows)
    }
    if len(all_horses) != 255 or len(buys) != 9 or actual != {key: sorted(value) for key, value in EXPECTED_CURRENT.items()}:
        raise RuntimeError("FROZEN_CURRENT_SELECTION_MISMATCH")
    return all_horses, buys, by_race


def select_join(records: list[dict[str, Any]], by_race: dict[str, list[dict[str, Any]]], selected_key: str, pool_key: str | None = None) -> list[dict[str, Any]]:
    joined = []
    for record in records:
        lookup = {row["horse_number"]: row for row in by_race.get(record["race_id"], [])}
        if not lookup:
            raise RuntimeError(f"FROZEN_SELECTION_RACE_MISSING:{record['race_id']}")
        def collect(key: str) -> list[dict[str, Any]]:
            rows = []
            for horse in record[key]:
                number = int(horse["horse_number"])
                if number not in lookup:
                    raise RuntimeError(f"FROZEN_SELECTION_HORSE_MISSING:{record['race_id']}:{number}")
                rows.append({**lookup[number], "shadow_ai_rank": horse.get("shadow_ai_rank")})
            return rows
        joined.append({"race_id": record["race_id"], "venue_key": record["venue"], "venue": VENUES[record["venue"]],
                       "race_number": record["race_number"], "selected": collect(selected_key),
                       "candidate_pool": collect(pool_key) if pool_key else []})
    return joined


def flat(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [horse for row in records for horse in row[key]]


def count(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metric = selected_metric(rows)
    return {"selected": metric["selected_count"], "valid": metric["valid_selected_count"], "invalid": metric["invalid_selected_count"],
            "hits": metric["top3_hits"], "rate": metric["buy_top3_rate"]}


def v4_ledger(current: list[dict[str, Any]], v4: list[dict[str, Any]]) -> dict[str, Any]:
    current_metric, v4_metric = selected_metric(current), selected_metric(v4)
    comparison = lift(current_metric, v4_metric)
    state = decision_state(6, 1, comparison["lift_percentage_points"], False, False)
    ledger = {"schema_version": "V4_MODEL_V3_FORMAL_PROSPECTIVE_LEDGER_V1", "evidence_role": ROLE, "state": "RUNNING",
              "eligible_dates": [DATE], "eligible_race_count": 6, "completed_formal_dates": 1,
              "current": current_metric, "v4": v4_metric, **comparison, "formal_status": state,
              "excluded_evidence": ["20260829 V4 Reference", "March Historical", "May OOS", "April", "CF evidence"]}
    validate_ledger(ledger)
    return ledger


def write_md(v4: dict[str, Any], cf: dict[str, Any], current: dict[str, Any], comparison: list[dict[str, Any]]) -> None:
    lines = ["# 2026-08-30 Formal POST", "", "## Comparative summary", "",
             f"- Current BUY: {current['metrics']['hits']}/{current['metrics']['valid']} ({current['metrics']['rate']:.2%})",
             f"- CF selected: {cf['selected_metrics']['hits']}/{cf['selected_metrics']['valid']} ({cf['selected_metrics']['rate']:.2%}); candidate pool {cf['pool_metrics']['hits']}/{cf['pool_metrics']['valid']} ({cf['pool_metrics']['rate']:.2%})",
             f"- V4 Model v3: {v4['metrics']['hits']}/{v4['metrics']['valid']} ({v4['metrics']['rate']:.2%})",
             f"- V4 vs Current: raw hit difference {v4['comparison']['raw_hit_difference']:+d}; lift {v4['comparison']['lift_percentage_points']:+.2f}pt.",
             "- Interpretation: 8/30単日だけでV4/CFの採否判断はしない。", "", "## Current BUY results", ""]
    for row in current["horses"]: lines.append(f"- {row['venue']} {row['race_number']}R: {fmt(row)}")
    lines += ["", "## CF 2026-08-30 Result", ""]
    for venue in ("中京", "新潟", "札幌"):
        lines += [f"### {venue}", ""]
        for row in cf["races"]:
            if row["venue"] == venue:
                lines.append(f"- {row['race_number']}R: " + " / ".join(fmt(x) for x in row["selected_horses"]))
        lines.append("")
    lines += ["## V4 Model v3 2026-08-30 Result", ""]
    for row in v4["races"]: lines.append(f"- {row['venue']} {row['race_number']}R: " + " / ".join(fmt(x) for x in row["selected_horses"]))
    lines += ["", "## V4 race-by-race comparison", "", "| 場 | R | Current selections/results | V4 selections/results | Current hits | V4 hits | raw diff |", "|---|---:|---|---|---:|---:|---:|"]
    for row in comparison:
        lines.append(f"| {row['venue']} | {row['race_number']} | {' / '.join(fmt(x) for x in row['current_horses'])} | {' / '.join(fmt(x) for x in row['v4_horses'])} | {row['current_hits']} | {row['v4_hits']} | {row['raw_hit_difference']:+d} |")
    (V4_OUT / "human_readable_result_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def hash_index(root: Path) -> dict[str, Any]:
    return {"hashes": {p.name: sha(p) for p in sorted(root.iterdir()) if p.is_file() and p.name != "artifact_hashes.json"}, "self_hash_excluded": True}


def main() -> None:
    if V4_OUT.exists() or CF_OUT.exists():
        raise RuntimeError("POST_OUTPUT_ALREADY_EXISTS")
    pre_freeze = verify_frozen_pre()
    reconciliation, results = source_integrity()
    all_horses, current_buys, by_race = current_join(results)
    current_metrics = count(current_buys)
    current_payload = {"system": "Current BUY", "frozen_selected_count": len(current_buys), "horses": current_buys, "metrics": current_metrics,
                       "buy_positive_races": 6, "buy_successful_races": sum(count([x for x in rows if x["frozen_buy"]])["hits"] > 0 for rows in by_race.values())}

    cf_pre = json.loads((CF_ROOT / "formal_pre_20260830.json").read_text(encoding="utf-8"))
    cf_records = cf_pre["eligible_races"]
    cf_joined = select_join(cf_records, by_race, "cf_selected_horses", "candidate_horses")
    cf_actual = {(row["venue_key"], row["race_number"]): [x["horse_number"] for x in row["selected"]] for row in cf_joined}
    if len(cf_joined) != 6 or sum(len(x["selected"]) for x in cf_joined) != 18 or cf_actual != EXPECTED_CF:
        raise RuntimeError("FROZEN_CF_SELECTION_MISMATCH")
    cf_post_records = []
    for record in cf_joined:
        sm, pm = count(record["selected"]), count(record["candidate_pool"])
        cf_post_records.append({"race_id": record["race_id"], "venue": record["venue"], "race_number": record["race_number"],
            "selected_horses": record["selected"], "candidate_pool_horses": record["candidate_pool"],
            "selected_valid_count": sm["valid"], "selected_top3_count": sm["hits"], "SHADOW_SELECTED_TOP3_RATE": sm["rate"],
            "candidate_pool_size": pm["selected"], "candidate_pool_valid_count": pm["valid"], "candidate_pool_top3_count": pm["hits"],
            "candidate_pool_top3_rate": pm["rate"], "difference": None if sm["rate"] is None or pm["rate"] is None else sm["rate"] - pm["rate"]})
    cf_selected, cf_pool = flat(cf_joined, "selected"), flat(cf_joined, "candidate_pool")
    cf_selected_metrics, cf_pool_metrics = count(cf_selected), count(cf_pool)
    cf_base_ledger = cf_prior_formal_ledger()
    activation = json.loads((CF_ROOT / "activation_record.json").read_text(encoding="utf-8"))
    cf_ledger = append_formal_post_evidence(ledger=cf_base_ledger, date=DATE, activation_record=activation, post_records=cf_post_records, independent_race_count=6)
    cf_cumulative = cf_ledger["formal_evidence"]
    cf_payload = {"candidate": "CF_TOP3_RANK_ANCHORED", "evidence_role": "FORMAL_PROSPECTIVE_SHADOW", "races": cf_post_records,
                  "eligible_races": 6, "selected_metrics": cf_selected_metrics, "pool_metrics": cf_pool_metrics,
                  "daily_lift": None if cf_selected_metrics["rate"] is None or cf_pool_metrics["rate"] is None else cf_selected_metrics["rate"] - cf_pool_metrics["rate"],
                  "cumulative_evidence": cf_ledger, "formal_status": "SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE"}

    v4_pre = json.loads((V4_PRE_ROOT / "v4_prediction.json").read_text(encoding="utf-8"))
    v4_records = [row for row in v4_pre["races"] if row["scope_status"] == "ELIGIBLE"]
    v4_joined = select_join(v4_records, by_race, "selected_horses")
    v4_actual = {(row["venue_key"], row["race_number"]): [x["horse_number"] for x in row["selected"]] for row in v4_joined}
    if len(v4_joined) != 6 or sum(len(x["selected"]) for x in v4_joined) != 9 or v4_actual != EXPECTED_V4:
        raise RuntimeError("FROZEN_V4_SELECTION_MISMATCH")
    current_by_race = {row["race_id"]: [x for x in by_race[row["race_id"]] if x["frozen_buy"]] for row in v4_joined}
    v4_by_race = {row["race_id"]: row["selected"] for row in v4_joined}
    same_volume(current_by_race, v4_by_race)
    comparisons = []
    for record in v4_joined:
        cur = current_by_race[record["race_id"]]; vm, cm = count(record["selected"]), count(cur)
        comparisons.append({"race_id": record["race_id"], "venue": record["venue"], "race_number": record["race_number"], "current_horses": cur, "v4_horses": record["selected"], "current_valid": cm["valid"], "v4_valid": vm["valid"], "current_hits": cm["hits"], "v4_hits": vm["hits"], "current_rate": cm["rate"], "v4_rate": vm["rate"], "raw_hit_difference": vm["hits"] - cm["hits"], "race_level_contribution": vm["hits"] - cm["hits"]})
    v4_selected = flat(v4_joined, "selected")
    v4_metrics = count(v4_selected)
    v4_compare = lift(selected_metric(flat([{"current": v} for v in []], "current")) if False else selected_metric([x for v in current_by_race.values() for x in v]), selected_metric(v4_selected))
    v4_payload = {"model": "V4_MODEL_V3", "evidence_role": ROLE, "races": [{"race_id": x["race_id"], "venue": x["venue"], "race_number": x["race_number"], "selected_horses": x["selected"]} for x in v4_joined], "metrics": v4_metrics, "comparison": v4_compare}
    ledger = v4_ledger([x for v in current_by_race.values() for x in v], v4_selected)
    temporal = {"LODO": {"status": "NOT_EVALUABLE_INSUFFICIENT_INDEPENDENT_DATES", "completed_dates": 1}, "temporal_concentration": {"status": "NOT_EVALUABLE_INSUFFICIENT_INDEPENDENT_DATES", "completed_dates": 1}}
    stats = uncertainty(selected_metric([x for v in current_by_race.values() for x in v]), selected_metric(v4_selected), [], temporal)
    safety = {"status": "PASS", "production_change": 0, "current_ai_rule_change": 0, "buy_gate_change": 0, "decision_engine_change": 0, "cf_protocol_change": 0, "v4_model_v3_change": 0, "v4_formal_protocol_change": 0, "v4_pre_change": 0, "model_v4_change": 0, "dataset_v4_change": 0, "prediction_rerun": 0, "february_access": 0, "result_data_access_authorized_for_date": DATE}
    inventory = {"date": DATE, "primary": {"path": str(PRIMARY.relative_to(ROOT)), "sha256": sha(PRIMARY)}, "auxiliary": {"path": str(AUXILIARY.relative_to(ROOT)), "sha256": sha(AUXILIARY)}, "result_access_authorized": True}

    # Reverify frozen PRE immediately before the only writes.
    verify_frozen_pre()
    V4_OUT.mkdir(parents=True); CF_OUT.mkdir(parents=True)
    dump(V4_OUT, "result_source_inventory.json", inventory)
    dump(V4_OUT, "result_reconciliation.json", reconciliation)
    dump(V4_OUT, "current_post.json", current_payload)
    dump(V4_OUT, "v4_post.json", v4_payload)
    dump(V4_OUT, "race_level_comparison.json", {"eligible_races": 6, "comparisons": comparisons})
    dump(V4_OUT, "daily_metrics.json", {"date": DATE, "current": current_metrics, "v4": v4_metrics, **v4_compare, "formal_eligible_races": 6})
    dump(V4_OUT, "statistical_uncertainty.json", stats)
    dump(V4_OUT, "temporal_diagnostics.json", temporal)
    dump(V4_OUT, "evidence_ledger_update.json", ledger)
    dump(V4_OUT, "safety.json", safety)
    write_md(v4_payload, cf_payload, current_payload, comparisons)
    (V4_OUT / "report.md").write_text(
        "# 2026-08-30 V4 Model v3 Formal Prospective POST\n\n"
        "- Status: `PROSPECTIVE_POST_20260830 = COMPLETE`\n"
        "- V4 status: `V4_MODEL_V3_FORMAL_PROSPECTIVE_POST_20260830 = COMPLETE`\n"
        "- Completed formal prospective dates: `1`\n"
        "- Formal status: `SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE`\n"
        "- 8/30単日だけでV4/CFの採否判断はしない。\n",
        encoding="utf-8",
    )

    dump(CF_OUT, "result_reconciliation_reference.json", {"v4_post_result_reconciliation": str((V4_OUT / "result_reconciliation.json").relative_to(ROOT)), "result_source_inventory": inventory})
    dump(CF_OUT, "candidate_pool_outcome.json", {"races": [{"race_id": x["race_id"], "venue": x["venue"], "race_number": x["race_number"], "candidate_pool_horses": x["candidate_pool_horses"]} for x in cf_post_records], "metrics": cf_pool_metrics})
    dump(CF_OUT, "selected_outcome.json", {"races": [{"race_id": x["race_id"], "venue": x["venue"], "race_number": x["race_number"], "selected_horses": x["selected_horses"]} for x in cf_post_records], "metrics": cf_selected_metrics})
    dump(CF_OUT, "daily_metrics.json", {"date": DATE, "eligible_races": 6, "candidate_pool": cf_pool_metrics, "selected": cf_selected_metrics, "lift": cf_payload["daily_lift"]})
    dump(CF_OUT, "cumulative_evidence.json", cf_ledger)
    dump(CF_OUT, "formal_status.json", {"status": "SHADOW_HOLD_INSUFFICIENT_MINIMUM_EVIDENCE", "completed_dates": [x["date"] for x in cf_cumulative], "minimum": {"independent_dates": 4, "independent_races": 20}, "minimum_reached": False})
    dump(CF_OUT, "safety.json", safety)
    dump(CF_OUT, "artifact_hashes.json", hash_index(CF_OUT))
    dump(V4_OUT, "artifact_hashes.json", hash_index(V4_OUT))


if __name__ == "__main__":
    main()
