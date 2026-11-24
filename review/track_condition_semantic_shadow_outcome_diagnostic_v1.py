"""Outcome-only diagnostic for the frozen May TrackCondition semantic shadow.

This script reads only already-consumed May PRE/POST and Shadow artifacts.  It
does not open raw result CSV files, run prediction, or alter selection sets.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.target_bulk_prediction_input_adapter_v1 import COURSE_CODES, COURSE_KEYS

SHADOW = ROOT / "reports" / "track_condition_semantic_shadow_v1"
POST = ROOT / "reports" / "may_2026_multi_system_oos_v1" / "post_v1"
OUT = ROOT / "reports" / "track_condition_semantic_shadow_v1_outcome_diagnostic"
EXPECTED = {"control": 181, "shadow": 133, "common": 66, "control_only": 115, "shadow_only": 67, "union": 248, "changed_races": 109}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def boolean(value: str | bool) -> bool:
    return value is True or str(value).lower() == "true"


def metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row["valid_result"]]
    hits = [row for row in valid if row["actual_top3"]]
    races = {row["race_id"] for row in rows}
    success_races = {row["race_id"] for row in hits}
    return {"N": len(rows), "invalid": len(rows) - len(valid), "valid": len(valid), "hits": len(hits),
            "rate": len(hits) / len(valid) if valid else None, "buy_races": len(races), "successful_buy_races": len(success_races)}


def rate_pt(value: float | None) -> float | None:
    return None if value is None else value * 100


def two_proportion(left: dict[str, Any], right: dict[str, Any]) -> dict[str, float | None]:
    n1, n2 = left["valid"], right["valid"]
    if not n1 or not n2:
        return {"z": None, "two_sided_p": None}
    pooled = (left["hits"] + right["hits"]) / (n1 + n2)
    denominator = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if denominator == 0:
        return {"z": None, "two_sided_p": None}
    z = (left["rate"] - right["rate"]) / denominator
    return {"z": z, "two_sided_p": math.erfc(abs(z) / math.sqrt(2))}


def outcome_index(crosscheck: dict[str, Any]) -> dict[tuple[str, str, int], dict[int, int]]:
    by_identity: dict[tuple[str, str, int], dict[int, int]] = {}
    for record in crosscheck.get("records", []):
        key = str(record.get("target_race_key", ""))
        date = str(record.get("date", ""))
        if len(key) < 12 or key[:8] != date or not key[-2:].isdigit():
            raise Stop(f"STOP_EXISTING_OUTCOME_MAPPING_INSUFFICIENT:BAD_RACE_KEY:{key}")
        course_code, number = key[8:10], int(key[-2:])
        groups = record.get("normal_finish_groups")
        if not isinstance(groups, dict):
            raise Stop(f"STOP_EXISTING_OUTCOME_MAPPING_INSUFFICIENT:NO_NORMAL_GROUPS:{key}")
        finishes: dict[int, int] = {}
        for finish, horses in groups.items():
            for horse in horses:
                horse = int(horse)
                if horse in finishes:
                    raise Stop(f"STOP_EXISTING_OUTCOME_MAPPING_INSUFFICIENT:DUPLICATE_HORSE:{key}:{horse}")
                finishes[horse] = int(finish)
        identity = (date, course_code, number)
        if identity in by_identity:
            raise Stop(f"STOP_EXISTING_OUTCOME_MAPPING_INSUFFICIENT:AMBIGUOUS_RACE:{identity}")
        by_identity[identity] = finishes
    return by_identity


def join_outcomes(horse_rows: list[dict[str, str]], crosscheck: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    course_by_key = {value: key for key, value in COURSE_KEYS.items()}
    indexed = outcome_index(crosscheck)
    joined, missing = [], []
    for row in horse_rows:
        control, shadow = boolean(row["control_buy"]), boolean(row["shadow_buy"])
        if not control and not shadow:
            continue
        identity = (row["date"], COURSE_CODES[course_by_key[row["venue"]]], int(row["race_number"]))
        number = int(row["horse_number"])
        finishes = indexed.get(identity)
        if finishes is None or number not in finishes:
            missing.append(f"{row['race_id']}#{number}")
            continue
        finish = finishes[number]
        group = "COMMON_BUY" if control and shadow else "CONTROL_ONLY_BUY" if control else "SHADOW_ONLY_BUY"
        joined.append({
            **row, "horse_number": number, "control_buy": control, "shadow_buy": shadow, "group": group,
            "target_race_key_identity": "-".join(map(str, identity)), "valid_result": True,
            "actual_finish": finish, "actual_top3": finish <= 3,
            "final_score_delta_shadow_minus_control": float(row["shadow_final_score"]) - float(row["control_final_score"]),
            "rank_delta_shadow_minus_control": int(row["shadow_rank"]) - int(row["control_rank"]),
        })
    return joined, missing


def averages(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [row["final_score_delta_shadow_minus_control"] for row in rows]
    ranks = [row["rank_delta_shadow_minus_control"] for row in rows]
    return {"N": len(rows), "final_score_delta_mean": statistics.mean(scores) if scores else None,
            "final_score_delta_median": statistics.median(scores) if scores else None,
            "rank_delta_mean": statistics.mean(ranks) if ranks else None,
            "rank_delta_median": statistics.median(ranks) if ranks else None}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0]) if rows else ["empty"]
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def execute() -> dict[str, Any]:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    required = [SHADOW / "horse_level.csv", SHADOW / "race_level.csv", SHADOW / "artifact_hashes.json", SHADOW / "summary.json",
                POST / "result_crosscheck_validation.json", POST / "result_join_manifest.json", POST / "current_ai_evaluation.json", POST / "artifact_hashes.json"]
    if any(not path.is_file() for path in required):
        raise Stop("STOP_EXISTING_OUTCOME_MAPPING_INSUFFICIENT:REQUIRED_ARTIFACT_MISSING")
    shadow_hashes = json.loads((SHADOW / "artifact_hashes.json").read_text(encoding="utf-8"))["artifacts"]
    if any(sha(SHADOW / name) != digest for name, digest in shadow_hashes.items()):
        raise Stop("SHADOW_ARTIFACT_HASH_MISMATCH")
    post_hashes = json.loads((POST / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
    for name in ("result_crosscheck_validation.json", "result_join_manifest.json", "current_ai_evaluation.json"):
        if sha(POST / name) != post_hashes[name]:
            raise Stop(f"POST_ARTIFACT_HASH_MISMATCH:{name}")
    shadow_summary = json.loads((SHADOW / "summary.json").read_text(encoding="utf-8"))
    if shadow_summary.get("actual") != shadow_summary.get("expected"):
        raise Stop("FROZEN_SHADOW_REPRODUCTION_NOT_CONFIRMED")
    anchor = json.loads((POST / "current_ai_evaluation.json").read_text(encoding="utf-8"))
    if (anchor.get("selected_count"), anchor.get("valid_selected_count"), anchor.get("top3_count")) != (181, 181, 59):
        raise Stop("STOP_CONTROL_OUTCOME_REPRODUCTION_FAILURE:POST_ANCHOR")
    horses = load_csv(SHADOW / "horse_level.csv")
    races = load_csv(SHADOW / "race_level.csv")
    joined, missing = join_outcomes(horses, json.loads((POST / "result_crosscheck_validation.json").read_text(encoding="utf-8")))
    if missing:
        raise Stop("STOP_EXISTING_OUTCOME_MAPPING_INSUFFICIENT:MISSING=" + ",".join(missing))
    control = [row for row in joined if row["control_buy"]]
    shadow = [row for row in joined if row["shadow_buy"]]
    common = [row for row in joined if row["group"] == "COMMON_BUY"]
    removed = [row for row in joined if row["group"] == "CONTROL_ONLY_BUY"]
    added = [row for row in joined if row["group"] == "SHADOW_ONLY_BUY"]
    if (len(control), len(shadow), len(common), len(removed), len(added), len(joined)) != tuple(EXPECTED[key] for key in ("control", "shadow", "common", "control_only", "shadow_only", "union")):
        raise Stop("FROZEN_SELECTION_SET_MISMATCH")
    control_metric, shadow_metric = metric(control), metric(shadow)
    if (control_metric["valid"], control_metric["hits"], control_metric["rate"]) != (181, 59, 59 / 181):
        raise Stop("STOP_CONTROL_OUTCOME_REPRODUCTION_FAILURE:JOIN")
    changed_races = [row for row in races if boolean(row["buy_set_changed"])]
    if len(changed_races) != EXPECTED["changed_races"]:
        raise Stop("BUY_CHANGED_RACE_COUNT_MISMATCH")
    joined_by_race: dict[str, list[dict[str, Any]]] = {}
    for row in joined:
        joined_by_race.setdefault(row["race_id"], []).append(row)
    race_output = []
    for race in changed_races:
        members = joined_by_race.get(race["race_id"], [])
        c, s = [x for x in members if x["control_buy"]], [x for x in members if x["shadow_buy"]]
        c_hits, s_hits = sum(x["actual_top3"] for x in c), sum(x["actual_top3"] for x in s)
        transition = ("BET" if c else "ABSTAIN") + " -> " + ("BET" if s else "ABSTAIN")
        race_output.append({**race, "common_buy_count": sum(x["group"] == "COMMON_BUY" for x in members),
                            "removed_buy_count": sum(x["group"] == "CONTROL_ONLY_BUY" for x in members),
                            "added_buy_count": sum(x["group"] == "SHADOW_ONLY_BUY" for x in members),
                            "control_hits": c_hits, "shadow_hits": s_hits, "control_success": c_hits > 0,
                            "shadow_success": s_hits > 0, "race_transition": transition})
    removed_metric, added_metric, common_metric = metric(removed), metric(added), metric(common)
    hit_delta = shadow_metric["hits"] - control_metric["hits"]
    rate_delta = rate_pt(shadow_metric["rate"] - control_metric["rate"])
    if shadow_metric["rate"] > control_metric["rate"] and shadow_metric["hits"] >= control_metric["hits"]:
        state, recommendation = "STRONG_HISTORICAL_SIGNAL", "YES"
    elif shadow_metric["rate"] > control_metric["rate"]:
        state, recommendation = "RATE_UP_VOLUME_HIT_TRADEOFF", "HOLD"
    else:
        state, recommendation = "NO_HISTORICAL_PERFORMANCE_SUPPORT", "NO"
    transition_counts = Counter(row["race_transition"] for row in race_output)
    sources = {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path) for path in required}
    summary = {
        "final_status": "TRACK_CONDITION_SHADOW_OUTCOME_DIAGNOSTIC_COMPLETE", "development_diagnostic_only": True,
        "existing_outcome_mapping": "COMPLETE", "union_buy_horses": len(joined), "outcome_mapping_missing": [],
        "control": control_metric, "shadow": shadow_metric, "common_group": common_metric,
        "control_only_group": removed_metric, "shadow_only_group": added_metric,
        "hit_delta": hit_delta, "valid_N_delta": shadow_metric["valid"] - control_metric["valid"], "rate_delta_pt": rate_delta,
        "buy_horse_volume_ratio": shadow_metric["N"] / control_metric["N"],
        "buy_race_volume_ratio": shadow_metric["buy_races"] / control_metric["buy_races"],
        "removed_hits": removed_metric["hits"], "removed_misses": removed_metric["valid"] - removed_metric["hits"],
        "added_hits": added_metric["hits"], "added_misses": added_metric["valid"] - added_metric["hits"],
        "net_hit_change": hit_delta, "buy_changed_races": len(changed_races),
        "control_buy_races": control_metric["buy_races"], "shadow_buy_races": shadow_metric["buy_races"],
        "race_transition_counts": dict(transition_counts), "mechanism_score_delta": {"removed": averages(removed), "added": averages(added)},
        "two_proportion_reference": two_proportion(shadow_metric, control_metric), "independence_assumption_limitation": True,
        "volume_change_warning": True, "diagnostic_state": state, "prospective_shadow_recommendation": recommendation,
        "production_accept": False, "track_bias_changed": False, "independent_race_selection_changed": False,
        "real_20260926_pre_executed": False, "result_data_access_count": 0, "prediction_execution_count": 0,
        "code_change": "DIAGNOSTIC_ONLY", "production_change": 0, "model_change": 0, "buy_rule_change": 0,
        "track_condition_production_change": 0, "track_bias_change": 0, "tau_change": 0, "git_commit": 0, "git_push": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    OUT.mkdir(parents=True)
    write_csv(OUT / "horse_set_decomposition.csv", joined)
    write_csv(OUT / "race_level.csv", race_output)
    dump(OUT / "summary.json", summary)
    dump(OUT / "source_manifest.json", {"sources": sources, "script": str(Path(__file__).relative_to(ROOT)).replace("\\", "/"), "script_sha256": sha(Path(__file__)), "raw_result_csv_access": False})
    report = "\n".join([
        "# TrackCondition Semantic Shadow v1 — Historical Outcome Diagnostic", "",
        "- 開発診断のみ。既消費May POST成果物を利用し、raw Result CSVは再読込していません。",
        f"- Control: {control_metric['hits']}/{control_metric['valid']} ({rate_pt(control_metric['rate']):.6f}%)。",
        f"- Shadow: {shadow_metric['hits']}/{shadow_metric['valid']} ({rate_pt(shadow_metric['rate']):.6f}%)。",
        f"- 差分: hit {hit_delta:+d}、valid N {summary['valid_N_delta']:+d}、rate {rate_delta:+.6f}pt。",
        f"- Current-only: {removed_metric['hits']}/{removed_metric['valid']}、Shadow-only: {added_metric['hits']}/{added_metric['valid']}。",
        f"- 判定: `{state}`。Prospective Shadow推奨: `{recommendation}`。Production採用: `NO`。",
        "- BUY数の自然減少を伴うため `VOLUME_CHANGE_WARNING = YES`。matched-volume操作は行っていません。", "",
    ])
    (OUT / "report.md").write_text(report, encoding="utf-8")
    hashes = {path.name: sha(path) for path in sorted(OUT.iterdir()) if path.name != "artifact_hashes.json"}
    dump(OUT / "artifact_hashes.json", {"algorithm": "SHA256", "artifacts": hashes, "self_hash_excluded": True})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    if not parser.parse_args().execute:
        parser.error("--execute is required")
    print(json.dumps(execute(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
