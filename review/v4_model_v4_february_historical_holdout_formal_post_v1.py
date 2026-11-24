"""Atomic Formal POST for the frozen February 2026 V4 Model v4 holdout.

The script is deliberately post-only: it validates frozen PRE authority,
reconciles all frozen daily-result source pairs, joins only already-frozen
selections, then writes a new immutable POST evidence root.  It never invokes
prediction or model inference and never mutates PRE, model, dataset, or raw
sources.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.historical_replay_post_race import result_semantics
from review.target_bulk_prediction_input_adapter_v1 import COURSE_KEYS
from review.target_daily_result_list_schema_v2_validator import validate_source_pair


RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
PRE = ROOT / "reports" / "v4_model_v4_february_historical_holdout" / "formal_pre"
OUT = ROOT / "reports" / "v4_model_v4_february_historical_holdout" / "formal_post"
MODEL = ROOT / "reports" / "ml_v4_buy_selection_model_v4"
DATASET = ROOT / "reports" / "ml_v4_buy_selection_dataset_v4"
DATES = ["20260201", "20260207", "20260208", "20260210", "20260214", "20260215", "20260221", "20260222", "20260228"]
CLAUDE_MANIFEST = PRE / "pre_independent_review_manifest.json"
CLAUDE_SHA = "c3ea3ecc2f8faec8fe7361f4f0c6354ca5471ee36a498e439140a7db00f9f412"
MODEL_SHA = "58d3977d0f44eab325a2b384f0c17b66ddc276fff6370f6e05b7a1680642d74f"
SCALER_SHA = "3d18757f4991c21a4a645f92ca26361d88c030a4097696d2cc4a6c86d3767b90"
DATASET_SHA = "b02bb4b59b5f297e60964f96050890dbf32a7ac3b5a9ef93424b9d612e3ae80a"
ABNORMAL = {"中止", "除外", "取消", "失格"}
ROLE = "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_V4_MODEL_V4"
CONSUMED_ROLE = "CONSUMED_TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_V4_MODEL_V4"


class Stop(RuntimeError):
    """Fail-closed integrity failure."""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stop(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="cp932", newline="") as handle:
        return list(csv.reader(handle))


def verify_index(path: Path) -> int:
    payload = read_json(path)
    indexed = payload.get("indexed_artifacts", payload.get("hashes"))
    if not isinstance(indexed, dict):
        raise Stop(f"ARTIFACT_HASH_INDEX_INVALID:{path}")
    for relative, digest in indexed.items():
        target = path.parent / relative
        if not isinstance(digest, str) or not target.is_file() or sha(target) != digest:
            raise Stop(f"ARTIFACT_HASH_INDEX_MISMATCH:{path.name}:{relative}")
    return len(indexed)


def outcome(primary_row: list[str], horse_number: int) -> dict[str, Any]:
    raw = primary_row[11 + horse_number].strip()
    if raw.isdigit() and int(raw) > 0:
        semantic = {"馬番": str(horse_number), "確定着順": raw, "異常コード": "0"}
    elif raw in ABNORMAL or raw == "0":
        semantic = {"馬番": str(horse_number), "確定着順": "0", "異常コード": raw if raw else "0"}
    else:
        raise Stop(f"RESULT_SEMANTICS_UNRESOLVED:{raw!r}")
    return {"raw_result_value": raw, **result_semantics(semantic)}


def crosscheck(primary: list[str], auxiliary: list[str], race_key: str) -> dict[str, Any]:
    head = int(primary[9])
    valid_by_finish: dict[int, set[int]] = defaultdict(set)
    invalid: set[int] = set()
    for horse_number in range(1, head + 1):
        result = outcome(primary, horse_number)
        if result["valid_result"]:
            valid_by_finish[int(result["actual_finish"])].add(horse_number)
        else:
            invalid.add(horse_number)
    shown = [int(value) for value in auxiliary[12:12 + head]]
    offset = 0
    for finish in sorted(valid_by_finish):
        expected = valid_by_finish[finish]
        observed = set(shown[offset:offset + len(expected)])
        if expected != observed:
            raise Stop(f"RESULT_SOURCE_DISAGREEMENT:{race_key}:FINISH_{finish}")
        offset += len(expected)
    if set(shown[offset:]) != invalid:
        raise Stop(f"RESULT_SOURCE_DISAGREEMENT:{race_key}:ABNORMAL_SUFFIX")
    return {
        "target_race_key": race_key,
        "head_count": head,
        "status": "PASS",
        "finish_groups": {str(key): sorted(value) for key, value in sorted(valid_by_finish.items())},
        "invalid_horse_numbers": sorted(invalid),
    }


def metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(bool(row["actual_top3"]) for row in valid)
    return {
        "selected_count": len(rows),
        "valid_selected_count": len(valid),
        "invalid_selected_count": len(rows) - len(valid),
        "top3_hits": hits,
        "buy_top3_rate": hits / len(valid) if valid else None,
    }


def comparison(current: dict[str, Any], v4: dict[str, Any]) -> dict[str, Any]:
    if current["buy_top3_rate"] is None or v4["buy_top3_rate"] is None:
        raise Stop("EMPTY_VALID_SELECTION_DENOMINATOR")
    lift = v4["buy_top3_rate"] - current["buy_top3_rate"]
    return {
        "raw_hit_difference": v4["top3_hits"] - current["top3_hits"],
        "lift": lift,
        "lift_percentage_points": lift * 100,
    }


def race_parts(race_id: str) -> tuple[str, str, int]:
    parts = race_id.split("_")
    if len(parts) != 4 or not parts[3].endswith("R"):
        raise Stop(f"FROZEN_RACE_ID_INVALID:{race_id}")
    return parts[1], parts[2], int(parts[3][:-1])


def venue_name(venue_key: str) -> str:
    value = next((name for name, key in COURSE_KEYS.items() if key == venue_key), None)
    if value is None:
        raise Stop(f"FROZEN_VENUE_KEY_UNKNOWN:{venue_key}")
    return value


def verify_pre_and_authorities() -> dict[str, Any]:
    if not CLAUDE_MANIFEST.is_file() or sha(CLAUDE_MANIFEST) != CLAUDE_SHA:
        raise Stop("CLAUDE_PRE_REVIEW_MANIFEST_MISMATCH")
    pre_files = verify_index(PRE / "artifact_hashes.json")
    model_files = verify_index(MODEL / "artifact_hashes.json")
    dataset_files = verify_index(DATASET / "artifact_hashes.json")
    if sha(MODEL / "model.joblib") != MODEL_SHA:
        raise Stop("MODEL_V4_SHA_MISMATCH")
    if sha(MODEL / "scaler.joblib") != SCALER_SHA:
        raise Stop("SCALER_V4_SHA_MISMATCH")
    if sha(DATASET / "dataset.csv") != DATASET_SHA:
        raise Stop("DATASET_V4_SHA_MISMATCH")
    manifest = read_json(PRE / "pre_freeze_manifest.json")
    eligible = read_json(PRE / "formal_eligible_population.json")
    current = read_json(PRE / "current_prediction.json")
    same_volume = read_json(PRE / "same_volume_audit.json")
    replacement = read_json(PRE / "replacement_depth_preregistration.json")
    volume = read_json(PRE / "buy_volume_preregistration.json")
    expected = (
        manifest.get("candidate_dates") == DATES
        and manifest.get("source_population") == {"races": 160, "horses": 2209}
        and current.get("race_state_counts") == {"PLAY_CONVERGED": 81, "PLAY_UNCONVERGED_4PLUS": 30, "SKIP": 49}
        and current.get("current_buy_horse_count") == 133
        and eligible.get("eligible_race_count") == 81
        and eligible.get("eligible_date_count") == 9
        and same_volume.get("current_selected_total") == 133
        and same_volume.get("v4_selected_total") == 133
        and replacement.get("distribution") == {"0": 19, "1": 51, "2": 11, "3": 0}
        and volume.get("distribution") == {"1": 41, "2": 28, "3": 12}
    )
    if not expected:
        raise Stop("FROZEN_PRE_POPULATION_OR_SELECTION_MUTATION")
    return {
        "claude_manifest_sha256": sha(CLAUDE_MANIFEST),
        "pre_artifacts_verified": pre_files,
        "model_artifacts_verified": model_files,
        "dataset_artifacts_verified": dataset_files,
        "pre_index_sha256": sha(PRE / "artifact_hashes.json"),
        "model_index_sha256": sha(MODEL / "artifact_hashes.json"),
        "dataset_index_sha256": sha(DATASET / "artifact_hashes.json"),
    }


def result_inventory_and_lookup() -> tuple[list[dict[str, Any]], dict[str, dict[str, list[str]]], list[dict[str, Any]], list[dict[str, Any]]]:
    inventory: list[dict[str, Any]] = []
    lookup: dict[str, dict[str, list[str]]] = {}
    validations: list[dict[str, Any]] = []
    crosschecks: list[dict[str, Any]] = []
    for date in DATES:
        primary = RAW / f"馬番順着順_{date}.csv"
        auxiliary = RAW / f"着順馬番_{date}.csv"
        if not primary.is_file() or not auxiliary.is_file():
            raise Stop(f"RESULT_FILE_MISSING:{date}")
        validations.append(validate_source_pair(primary, auxiliary, date))
        primary_rows, auxiliary_rows = read_rows(primary), read_rows(auxiliary)
        primary_by_key = {row[0]: row for row in primary_rows}
        auxiliary_by_key = {row[0]: row for row in auxiliary_rows}
        if len(primary_by_key) != len(primary_rows) or len(auxiliary_by_key) != len(auxiliary_rows):
            raise Stop(f"RESULT_DUPLICATE_RACE:{date}")
        if set(primary_by_key) != set(auxiliary_by_key):
            raise Stop(f"RESULT_MISSING_OR_UNRESOLVED_RACE:{date}")
        crosschecks.extend(crosscheck(primary_by_key[key], auxiliary_by_key[key], key) for key in sorted(primary_by_key))
        inventory.extend([
            {"date": date, "source_role": "PRIMARY_HORSE_NUMBER_ORDER_FINISH", "filename": primary.name, "path": str(primary.relative_to(ROOT)), "byte_size": primary.stat().st_size, "sha256": sha(primary)},
            {"date": date, "source_role": "AUXILIARY_FINISH_ORDER_HORSE_NUMBER", "filename": auxiliary.name, "path": str(auxiliary.relative_to(ROOT)), "byte_size": auxiliary.stat().st_size, "sha256": sha(auxiliary)},
        ])
        lookup[date] = primary_by_key
    return inventory, lookup, validations, crosschecks


def selection_join(lookup: dict[str, dict[str, list[str]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    eligible = read_json(PRE / "formal_eligible_population.json")["eligible_races"]
    if not isinstance(eligible, list) or len(eligible) != 81:
        raise Stop("FORMAL_ELIGIBLE_POPULATION_INVALID")
    current_rows: list[dict[str, Any]] = []
    v4_rows: list[dict[str, Any]] = []
    race_rows: list[dict[str, Any]] = []
    for item in eligible:
        race_id = item["race_id"]
        date, venue_key, number = race_parts(race_id)
        matches = [(key, row) for key, row in lookup[date].items() if row[1] == venue_name(venue_key) and int(row[2]) == number]
        if len(matches) != 1:
            raise Stop(f"RESULT_JOIN_RACE_AMBIGUITY:{race_id}:{len(matches)}")
        result_key, result_row = matches[0]
        def join(horse: dict[str, Any], system: str) -> dict[str, Any]:
            horse_number = int(horse["horse_number"])
            if horse_number < 1 or horse_number > int(result_row[9]):
                raise Stop(f"RESULT_JOIN_HORSE_AMBIGUITY:{race_id}:{horse_number}")
            return {
                "date": date, "race_id": race_id, "result_race_key": result_key,
                "venue": venue_key, "race_number": number, "horse_number": horse_number,
                "horse_name": horse["horse_name"], "selection_system": system,
                **outcome(result_row, horse_number),
            }
        current = [join(horse, "CURRENT") for horse in item["current_selected_horses"]]
        v4 = [join(horse, "V4_MODEL_V4") for horse in item["v4_selected_horses"]]
        if len(current) != item["current_buy_count"] or len(v4) != item["same_volume_count"] or len(current) != len(v4):
            raise Stop(f"FROZEN_SAME_VOLUME_MUTATION:{race_id}")
        current_rows.extend(current)
        v4_rows.extend(v4)
        current_metric, v4_metric = metric(current), metric(v4)
        race_rows.append({
            "date": date, "race_id": race_id, "venue": venue_key, "race_number": number,
            "replacement_depth": item["replacement_depth"], "buy_volume": item["current_buy_count"],
            "current_selections": current, "v4_selections": v4,
            "current": current_metric, "v4": v4_metric,
            "race_contribution": v4_metric["top3_hits"] - current_metric["top3_hits"],
        })
    if len(current_rows) != 133 or len(v4_rows) != 133:
        raise Stop("FROZEN_SELECTION_TOTAL_MUTATION")
    return current_rows, v4_rows, race_rows


def diagnostic_by_bin(rows: list[dict[str, Any]], key: str, values: list[int]) -> list[dict[str, Any]]:
    answer = []
    for value in values:
        matches = [row for row in rows if row[key] == value]
        current = [horse for row in matches for horse in row["current_selections"]]
        v4 = [horse for row in matches for horse in row["v4_selections"]]
        cm, vm = metric(current), metric(v4)
        answer.append({"bin": value, "race_count": len(matches), "current": cm, "v4": vm, **(comparison(cm, vm) if current and v4 else {"raw_hit_difference": 0, "lift": None, "lift_percentage_points": None})})
    return answer


def statistical_uncertainty(current: dict[str, Any], v4: dict[str, Any], pooled: dict[str, Any]) -> dict[str, Any]:
    n1, n2 = current["valid_selected_count"], v4["valid_selected_count"]
    p1, p2 = current["buy_top3_rate"], v4["buy_top3_rate"]
    if not n1 or not n2 or p1 is None or p2 is None:
        raise Stop("STATISTICAL_UNCERTAINTY_EMPTY_DENOMINATOR")
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    z = (p2 - p1) / se if se else None
    p_value = math.erfc(abs(z) / math.sqrt(2)) if z is not None else None
    return {
        "label": "APPROXIMATE_DIAGNOSTIC_ONLY",
        "dependence_caveat": "RACE_WITHIN_SELECTION_DEPENDENCE_NOT_MODELED",
        "current": current, "v4": v4, "raw_hit_difference": pooled["raw_hit_difference"],
        "pooled_lift_percentage_points": pooled["lift_percentage_points"], "approximate_z": z,
        "approximate_two_sided_p_value": p_value,
    }


def write_human_summary(path: Path, current: dict[str, Any], v4: dict[str, Any], pooled: dict[str, Any], daily: list[dict[str, Any]], depth: list[dict[str, Any]], volume: list[dict[str, Any]], gate: str) -> None:
    lines = ["# February 2026 V4 Model v4 Historical Holdout — Formal POST", "", "## Overall", "", f"- Current: **{current['top3_hits']} / {current['valid_selected_count']} = {current['buy_top3_rate']:.2%}**", f"- V4 Model v4: **{v4['top3_hits']} / {v4['valid_selected_count']} = {v4['buy_top3_rate']:.2%}**", f"- Difference: **{pooled['raw_hit_difference']:+d} hits / {pooled['lift_percentage_points']:+.2f}pt**", f"- Historical Gate: **{gate}**", "", "## By Date", "", "| Date | Races | Current | V4 | Raw hit difference | Lift |", "|---|---:|---:|---:|---:|---:|"]
    for row in daily:
        c, v = row["current"], row["v4"]
        lines.append(f"| {row['date']} | {row['eligible_races']} | {c['top3_hits']}/{c['valid_selected_count']} ({c['buy_top3_rate']:.2%}) | {v['top3_hits']}/{v['valid_selected_count']} ({v['buy_top3_rate']:.2%}) | {row['raw_hit_difference']:+d} | {row['lift_percentage_points']:+.2f}pt |")
    for title, rows in [("replacement_depth (non-gate)", depth), ("BUY volume (non-gate)", volume)]:
        lines.extend(["", f"## By {title}", "", "| Bin | Races | Current | V4 | Raw hit difference | Lift |", "|---:|---:|---:|---:|---:|---:|"])
        for row in rows:
            c, v = row["current"], row["v4"]
            cr = "N/A" if c["buy_top3_rate"] is None else f"{c['top3_hits']}/{c['valid_selected_count']} ({c['buy_top3_rate']:.2%})"
            vr = "N/A" if v["buy_top3_rate"] is None else f"{v['top3_hits']}/{v['valid_selected_count']} ({v['buy_top3_rate']:.2%})"
            lf = "N/A" if row["lift_percentage_points"] is None else f"{row['lift_percentage_points']:+.2f}pt"
            lines.append(f"| {row['bin']} | {row['race_count']} | {cr} | {vr} | {row['raw_hit_difference']:+d} | {lf} |")
    lines.extend(["", "## Evidence boundary", "", f"- Role after disclosure: `{CONSUMED_ROLE}`", "- This is a temporally reversed external holdout, not Prospective evidence and not Production GO.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    integrity_before = verify_pre_and_authorities()
    inventory, lookup, source_validations, crosschecks = result_inventory_and_lookup()
    current_selected, v4_selected, race_rows = selection_join(lookup)
    current_metric, v4_metric = metric(current_selected), metric(v4_selected)
    pooled = {"comparison": "CURRENT_BUY_RACE_RESELECTION_BENCHMARK", "eligible_races": 81, "independent_dates": 9, "current": current_metric, "v4_model_v4": v4_metric, **comparison(current_metric, v4_metric)}
    daily = []
    for date in DATES:
        cr = [row for row in current_selected if row["date"] == date]
        vr = [row for row in v4_selected if row["date"] == date]
        cm, vm = metric(cr), metric(vr)
        daily.append({"date": date, "eligible_races": sum(row["date"] == date for row in race_rows), "current": cm, "v4": vm, **comparison(cm, vm)})
    depth = diagnostic_by_bin(race_rows, "replacement_depth", [0, 1, 2, 3])
    volume = diagnostic_by_bin(race_rows, "buy_volume", [1, 2, 3])
    if [row["race_count"] for row in depth] != [19, 51, 11, 0] or [row["race_count"] for row in volume] != [41, 28, 12]:
        raise Stop("PREREGISTERED_DIAGNOSTIC_BIN_MUTATION")
    lodo = []
    for date in DATES:
        cm, vm = metric([row for row in current_selected if row["date"] != date]), metric([row for row in v4_selected if row["date"] != date])
        lodo.append({"excluded_date": date, "remaining_dates": 8, "current": cm, "v4": vm, **comparison(cm, vm)})
    contributions = sorted(({"date": row["date"], "hit_contribution": row["raw_hit_difference"]} for row in daily), key=lambda row: (-row["hit_contribution"], row["date"]))
    excluded_dates = [row["date"] for row in contributions[:3]]
    cm_stress = metric([row for row in current_selected if row["date"] not in excluded_dates])
    vm_stress = metric([row for row in v4_selected if row["date"] not in excluded_dates])
    stress = {"rule": "date contribution DESC then date ASC; remove ceil(9/3)=3", "date_contributions": contributions, "removed_dates": excluded_dates, "remaining_current": cm_stress, "remaining_v4": vm_stress, **comparison(cm_stress, vm_stress)}
    stress["temporal_concentration_flag"] = stress["lift_percentage_points"] <= 0 < pooled["lift_percentage_points"]
    stats = statistical_uncertainty(current_metric, v4_metric, pooled)
    invalid = {"current_invalid_selected_count": current_metric["invalid_selected_count"], "v4_invalid_selected_count": v4_metric["invalid_selected_count"], "current_invalid_selected": [row for row in current_selected if not row["valid_result"]], "v4_invalid_selected": [row for row in v4_selected if not row["valid_result"]]}
    gate_checks = {"eligible_races_ge_20": True, "independent_dates_ge_4": True, "pooled_same_volume_lift_ge_0pt": pooled["lift_percentage_points"] >= 0.0}
    gate = "PASS" if all(gate_checks.values()) else "FAIL"
    integrity_after = verify_pre_and_authorities()
    if integrity_before != integrity_after:
        raise Stop("PRE_OR_MODEL_AUTHORITY_MUTATION_DURING_POST")

    OUT.mkdir(parents=True)
    dump(OUT / "result_source_inventory.json", {"status": "PASS", "expected_file_count": 18, "actual_file_count": len(inventory), "files": inventory})
    dump(OUT / "result_reconciliation.json", {"status": "PASS", "date_count": 9, "source_validations": source_validations, "crosschecked_race_count": len(crosschecks), "crosschecks": crosschecks, "duplicate_race_count": 0, "missing_race_count": 0, "source_disagreement_count": 0, "unresolved_identity_count": 0})
    dump(OUT / "selection_result_join.json", {"status": "PASS", "formal_eligible_race_count": 81, "current_selected_count": len(current_selected), "v4_selected_count": len(v4_selected), "result_join_ambiguity_count": 0, "current_selected": current_selected, "v4_selected": v4_selected})
    dump(OUT / "current_post.json", {"system": "CURRENT", "evidence_role": ROLE, "records": current_selected, "metrics": current_metric})
    dump(OUT / "v4_post.json", {"system": "V4_MODEL_V4", "evidence_role": ROLE, "records": v4_selected, "metrics": v4_metric})
    dump(OUT / "overall_metrics.json", pooled)
    dump(OUT / "daily_metrics.json", {"dates": daily})
    dump(OUT / "race_level_comparison.json", {"eligible_race_count": 81, "races": race_rows})
    dump(OUT / "replacement_depth_diagnostic.json", {"status": "PREREGISTERED_DIAGNOSTIC_NON_GATE", "definition": "replacement_depth", "bins": depth, "answers": {"replacement_depth_1_outperformed_current": depth[1]["lift_percentage_points"] > 0 if depth[1]["lift_percentage_points"] is not None else None, "replacement_depth_2_outperformed_current": depth[2]["lift_percentage_points"] > 0 if depth[2]["lift_percentage_points"] is not None else None}})
    dump(OUT / "buy_volume_diagnostic.json", {"status": "PREREGISTERED_DIAGNOSTIC_NON_GATE", "definition": "Current BUY count per formal eligible race", "bins": volume})
    dump(OUT / "lodo_diagnostic.json", {"cases": lodo, "minimum_lift_percentage_points": min(row["lift_percentage_points"] for row in lodo), "maximum_lift_percentage_points": max(row["lift_percentage_points"] for row in lodo), "positive_count": sum(row["lift_percentage_points"] > 0 for row in lodo), "zero_count": sum(row["lift_percentage_points"] == 0 for row in lodo), "negative_count": sum(row["lift_percentage_points"] < 0 for row in lodo)})
    dump(OUT / "temporal_concentration_diagnostic.json", stress)
    dump(OUT / "statistical_uncertainty.json", stats)
    dump(OUT / "invalid_result_summary.json", invalid)
    dump(OUT / "historical_gate_result.json", {"gate": "V4_MODEL_V4_FEBRUARY_HISTORICAL_GATE", "checks": gate_checks, "result": gate, "not_production_go": True, "not_prospective_evidence": True})
    dump(OUT / "evidence_consumption_record.json", {"status": "CONSUMED", "prior_evidence_role": ROLE, "evidence_role_after_disclosure": CONSUMED_ROLE, "consumed_dates": DATES, "may_reuse_as_independent_validation": False})
    dump(OUT / "evidence_boundary.json", {"evidence_role": ROLE, "not_prospective": True, "not_production_go": True, "post_disclosure_rule": "No reselection, model fix, threshold change, gate adjustment, subgroup-bin adjustment, or silent replacement rerun.", "future_independent_holdout_reuse": "PROHIBITED"})
    safety = {"status": "PASS", "production_change_count": 0, "current_ai_change_count": 0, "buy_gate_change_count": 0, "decision_engine_change_count": 0, "model_v4_change_count": 0, "scaler_change_count": 0, "dataset_v4_change_count": 0, "selected_feature_change_count": 0, "cf_change_count": 0, "formal_prospective_change_count": 0, "pre_selection_change_count": 0, "prediction_rerun_count": 0, "model_inference_rerun_count": 0, "february_result_access_count": 18, "result_import_execution_count": 0, "pre_integrity_before_after": integrity_after, "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    dump(OUT / "safety.json", safety)
    write_human_summary(OUT / "human_readable_result_summary.md", current_metric, v4_metric, pooled, daily, depth, volume, gate)
    report = ["# February 2026 Historical Holdout Formal POST", "", "- Final execution status: `FEBRUARY_2026_HISTORICAL_HOLDOUT_POST = COMPLETE`", f"- Formal Historical Gate: `V4_MODEL_V4_FEBRUARY_HISTORICAL_GATE = {gate}`", f"- Current: `{current_metric['top3_hits']}/{current_metric['valid_selected_count']} = {current_metric['buy_top3_rate']:.4%}`", f"- V4 Model v4: `{v4_metric['top3_hits']}/{v4_metric['valid_selected_count']} = {v4_metric['buy_top3_rate']:.4%}`", f"- Same-volume lift: `{pooled['lift_percentage_points']:+.4f}pt`", f"- Evidence role after disclosure: `{CONSUMED_ROLE}`", "- Claude independent February POST review required: `YES`", ""]
    (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
    hashes = {path.name: sha(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}
    dump(OUT / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": hashes})
    if any(sha(OUT / name) != digest for name, digest in hashes.items()):
        raise Stop("POST_ARTIFACT_FREEZE_HASH_MISMATCH")
    print(f"FEBRUARY_2026_HISTORICAL_HOLDOUT_POST=COMPLETE;V4_MODEL_V4_FEBRUARY_HISTORICAL_GATE={gate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
