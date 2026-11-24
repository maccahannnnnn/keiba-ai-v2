"""One-date POST adapter for the frozen 2026-09-20 PRE artifacts only."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

DATE = "20260920"
RAW = ROOT / "data" / "raw" / "target" / "daily_result_list"
OUT = ROOT / "reports" / "post_20260920_minimal_retry1"
CURRENT = ROOT / "reports" / "daily_pre_prediction_20260920" / "current_frozen"
DAILY = ROOT / "reports" / "daily_pre_prediction_20260920" / "current_cf_v4_reference"
FORMAL = ROOT / "reports" / "selection_authority_protocol_v1_v6_forward_shadow" / "pre" / DATE
NINETEEN = ROOT / "reports" / "post_20260919_minimal" / "summary.json"
VENUE = {"hanshin": "阪神", "nakayama": "中山"}
ABNORMAL = {"中止", "除外", "取消", "失格"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, payload: object) -> None:
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def identity(race_id: str) -> tuple[str, int]:
    bits = race_id.split("_")
    return VENUE[bits[-2]], int(bits[-1].removesuffix("R"))


def outcome(result_row: list[str], horse_number: int) -> dict:
    value = result_row[11 + horse_number].strip()
    if value.isdigit() and int(value) > 0:
        finish = int(value)
        return {"actual_finish": finish, "valid_result": True, "actual_top3": finish <= 3}
    if value in ABNORMAL:
        return {"actual_finish": None, "valid_result": False, "actual_top3": False}
    raise RuntimeError(f"STOP_UNKNOWN_RESULT_SEMANTICS:{value}")


def metrics(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    hits = sum(row["actual_top3"] for row in valid)
    return {"natural_n": len(rows), "invalid_n": len(rows) - len(valid), "valid_n": len(valid), "hits": hits,
            "buy_top3_rate": hits / len(valid) if valid else None}


def run() -> None:
    if OUT.exists():
        raise RuntimeError("STOP_OUTPUT_ALREADY_EXISTS")

    current_manifest = CURRENT / "prediction_manifest.json"
    manifest = json.loads(current_manifest.read_text(encoding="utf-8"))
    if not all(sha(CURRENT / entry["relative_path"]) == entry["sha256"] for entry in manifest["files"]):
        raise RuntimeError("STOP_PRE_IDENTITY_MISMATCH")
    daily_index = json.loads((DAILY / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
    if not all(sha(DAILY / name) == digest for name, digest in daily_index.items()):
        raise RuntimeError("STOP_PRE_IDENTITY_MISMATCH")
    formal_index = json.loads((FORMAL / "artifact_index.json").read_text(encoding="utf-8"))["indexed_artifacts"]
    if not all(sha(FORMAL / name) == digest for name, digest in formal_index.items()):
        raise RuntimeError("STOP_PRE_IDENTITY_MISMATCH")

    primary = RAW / f"馬番順着順_{DATE}.csv"
    auxiliary = RAW / f"着順馬番_{DATE}.csv"
    schema = validate_source_pair(primary, auxiliary, DATE)
    if schema.get("status") != "PASS":
        raise RuntimeError("STOP_RESULT_SOURCE")
    with primary.open(encoding="cp932", newline="") as source:
        result_rows = list(csv.reader(source))
    results = {(row[1], int(row[2])): row for row in result_rows}
    if len(results) != len(result_rows):
        raise RuntimeError("STOP_RESULT_DUPLICATE_RACE")

    races: dict[str, dict] = {}
    current: list[dict] = []
    traces: dict[tuple[str, int], dict] = {}
    for item in json.loads((CURRENT / "race_index.json").read_text(encoding="utf-8"))["race_index"]:
        payload = json.loads((CURRENT / item["artifact"]).read_text(encoding="utf-8"))
        venue, number = identity(payload["race_id"])
        result = results.get((venue, number))
        if result is None:
            raise RuntimeError("STOP_RESULT_RACE_MISSING")
        ranked = {int(row["horse_number"]): row for row in payload["ranked_results"]}
        if len(ranked) != int(result[9]):
            raise RuntimeError("STOP_HEADCOUNT_MISMATCH")
        races[payload["race_id"]] = {"venue": venue, "number": number, "result": result, "ranked": ranked}
        traces.update({(payload["race_id"], int(row["horse_number"])): row for row in payload["buy_gate_trace"]["horses"]})
        for row in ranked.values():
            if row.get("buy") is True:
                current.append({"lane": "CURRENT", "race_id": payload["race_id"], "venue": venue, "race_number": number,
                                "horse_number": int(row["horse_number"]), "horse_name": row.get("horse_name"), **outcome(result, int(row["horse_number"]))})

    def join(records: list[dict], lane: str, key: str = "selected_horses") -> list[dict]:
        rows: list[dict] = []
        for record in records:
            race = races.get(record["race_id"])
            for horse in record.get(key, []):
                number = int(horse["horse_number"])
                if race is None or number not in race["ranked"]:
                    raise RuntimeError("STOP_FROZEN_SELECTION_IDENTITY")
                rows.append({"lane": lane, "race_id": record["race_id"], "venue": race["venue"], "race_number": race["number"],
                             "horse_number": number, "horse_name": horse.get("horse_name") or race["ranked"][number].get("horse_name"),
                             **outcome(race["result"], number)})
        return rows

    cf_records = json.loads((DAILY / "cf_selection_manifest.json").read_text(encoding="utf-8"))["all_race_records"]
    cf = join([row for row in cf_records if row["shadow_eligibility"] == "ELIGIBLE"], "CF", "cf_selected_horses")
    v5_records = json.loads((DAILY / "v4_active_model_selection_manifest.json").read_text(encoding="utf-8"))["races"]
    daily = join([row for row in v5_records if row["scope_status"] == "ELIGIBLE_PLAY_CONVERGED"], "DAILY_V5")
    semantic = json.loads((FORMAL / "dual_pre_semantic.json").read_text(encoding="utf-8"))["races"]

    def formal(version: str) -> list[dict]:
        selected = []
        for outer in semantic:
            if outer["eligible_evidence_race"]:
                record = dict(outer[version])
                record["selected_horses"] = [horse for horse in record["horses"] if horse["selected_by_protocol"]]
                selected.append(record)
        return join(selected, f"FORMAL_{version.upper()}")

    formal_v5, formal_v6 = formal("v5"), formal("v6")
    if sorted((row["race_id"], row["horse_number"], row["actual_finish"]) for row in formal_v5) != sorted((row["race_id"], row["horse_number"], row["actual_finish"]) for row in formal_v6):
        raise RuntimeError("STOP_FORMAL_V5_V6_RESULT_MISMATCH")

    cf_diagnostic = [row for row in cf if row["race_id"] in {f"race_{DATE}_nakayama_8R", f"race_{DATE}_nakayama_10R"}]
    agreement_keys = {(f"race_{DATE}_hanshin_7R", 8), (f"race_{DATE}_hanshin_7R", 3),
                      (f"race_{DATE}_hanshin_12R", 3), (f"race_{DATE}_hanshin_12R", 5),
                      (f"race_{DATE}_nakayama_6R", 7), (f"race_{DATE}_nakayama_7R", 4),
                      (f"race_{DATE}_nakayama_9R", 9)}
    agreement = [row for row in current if (row["race_id"], row["horse_number"]) in agreement_keys]
    daily_diff = [row for row in daily if (row["race_id"], row["horse_number"]) not in {(x["race_id"], x["horse_number"]) for x in current}]
    guard_group = []
    for row in daily_diff:
        trace = traces[(row["race_id"], row["horse_number"])]
        if trace.get("risk_guard_pass") is not False:
            raise RuntimeError("STOP_DAILY_V5_RISK_GUARD_DIAGNOSTIC_MISMATCH")
        guard_group.append(row)

    previous = json.loads(NINETEEN.read_text(encoding="utf-8"))
    lanes = {"current": current, "cf": cf, "daily_v5": daily, "formal_v5": formal_v5, "formal_v6": formal_v6}
    two_day = {}
    for name, rows in lanes.items():
        older, newer = previous[name], metrics(rows)
        valid = older["valid_n"] + newer["valid_n"]
        hits = older["hits"] + newer["hits"]
        two_day[name] = {"natural_n": older["natural_n"] + newer["natural_n"], "invalid_n": older["invalid_n"] + newer["invalid_n"],
                         "valid_n": valid, "hits": hits, "buy_top3_rate": hits / valid if valid else None}

    OUT.mkdir(parents=True)
    rows = current + cf + daily + formal_v5 + formal_v6
    with (OUT / "race_level.csv").open("w", encoding="utf-8", newline="") as target:
        fields = ["lane", "venue", "race_number", "race_id", "horse_number", "horse_name", "actual_finish", "valid_result", "actual_top3"]
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    summary = {"status": "COMPLETE", "result_source": "PASS", "current_pre_identity": "PASS", "daily_pre_identity": "PASS", "formal_pre_identity": "PASS",
               "current": metrics(current), "cf": metrics(cf), "daily_v5": metrics(daily), "formal_v5": metrics(formal_v5), "formal_v6": metrics(formal_v6),
               "formal_v5_v6_result_equality": "PASS", "current_buy_races": len({row["race_id"] for row in current}),
               "current_successful_buy_races": len({row["race_id"] for row in current if row["valid_result"] and row["actual_top3"]}),
               "current_non_buy_cf_diagnostic": {"rows": cf_diagnostic, "metrics": metrics(cf_diagnostic), "excluded_from_current_kpi": True},
               "multi_system_agreement_horses": {"rows": agreement, "metrics": metrics(agreement), "formal_kpi": False},
               "risk_guard_failed_daily_v5_group": {"rows": guard_group, "metrics": metrics(guard_group), "daily_v5_kpi": False},
               "two_day_diagnostic_0919_0920": {"role": "TWO_DAY_DIAGNOSTIC_ONLY", "lanes": two_day},
               "model_change": 0, "tau_change": 0, "production_change": 0, "independent_race_selection_rule_change": 0, "pre_mutation": 0, "git_commit": 0, "git_push": 0}
    write("summary.json", summary)
    write("source_manifest.json", {"primary": str(primary.relative_to(ROOT)), "primary_sha256": sha(primary), "auxiliary": str(auxiliary.relative_to(ROOT)), "auxiliary_sha256": sha(auxiliary), "schema_validation": schema,
                                     "current_manifest_sha256": sha(current_manifest), "daily_index_sha256": sha(DAILY / "artifact_hashes.json"), "formal_index_sha256": sha(FORMAL / "artifact_index.json")})
    write("run_metadata.json", {"date": DATE, "runner": "review/post_20260920_minimal.py", "result_access": 1, "prediction_rerun": 0, "model_fit": 0, "scaler_fit": 0})
    write("artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": {path.name: sha(path) for path in OUT.iterdir() if path.is_file() and path.name != "artifact_hashes.json"}})


if __name__ == "__main__":
    run()
