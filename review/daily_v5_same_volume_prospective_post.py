"""POST evaluator for the frozen Daily V5 same-volume shadow."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from review.target_daily_result_list_schema_v2_validator import validate_source_pair

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/daily_v5_same_volume_prospective_protocol_v1.json"
ABNORMAL = {"中止", "除外", "取消", "失格"}
VENUE_TO_JA = {"sapporo": "札幌", "hakodate": "函館", "fukushima": "福島", "niigata": "新潟", "tokyo": "東京", "nakayama": "中山", "chukyo": "中京", "kyoto": "京都", "hanshin": "阪神", "kokura": "小倉"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _current_pre_target_date(current_pre_root: Path) -> str:
    provenance = current_pre_root / "provenance.json"
    if not provenance.is_file():
        raise RuntimeError("STOP_CURRENT_PRE_TARGET_DATE_MISSING")
    value = json.loads(provenance.read_text(encoding="utf-8")).get("target_date")
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise RuntimeError("STOP_CURRENT_PRE_TARGET_DATE_MISSING")
    return value


def _metric(selected: set[int], finishes: dict[int, str]) -> dict:
    valid = [number for number in selected if finishes[number].isdigit() and int(finishes[number]) > 0]
    hits = [number for number in valid if int(finishes[number]) <= 3]
    return {"selected_count": len(selected), "valid_selected_count": len(valid),
            "invalid_selected_count": len(selected) - len(valid), "top3_count": len(hits),
            "buy_top3_rate": len(hits) / len(valid) if valid else None}


def summarize_frozen_race(race: dict, finishes: dict[int, str]) -> dict:
    """Pure result calculation used by the real runner and its smoke test."""
    current = set(race["difference_trace"]["current_selected"])
    daily_v5 = set(race["difference_trace"]["daily_v5_selected"])
    if set(finishes) != set(range(1, race["field_size"] + 1)):
        raise RuntimeError("STOP_RESULT_HORSE_IDENTITY_MISMATCH")
    for raw in finishes.values():
        if raw not in ABNORMAL and not (raw.isdigit() and int(raw) > 0):
            raise RuntimeError("STOP_UNKNOWN_RESULT_SEMANTICS")
    return {"race_id": race["race_id"], "scope_status": race["scope_status"],
            "current": _metric(current, finishes), "daily_v5": _metric(daily_v5, finishes),
            "common": sorted(current & daily_v5), "current_only": sorted(current - daily_v5),
            "daily_v5_only": sorted(daily_v5 - current)}


def _result_rows(primary_path: Path, auxiliary_path: Path, date: str) -> tuple[dict, dict]:
    pair = validate_source_pair(primary_path, auxiliary_path, date)
    with primary_path.open("r", encoding="cp932", newline="") as source:
        rows = {row[0]: row for row in csv.reader(source)}
    return rows, pair


def _result_key(index: dict, venue: str, race_number: int) -> str:
    candidates = [key for key, item in index.items() if item["venue_name"] == venue and item["race_number"] == race_number]
    if len(candidates) != 1:
        raise RuntimeError("STOP_RESULT_RACE_IDENTITY_MISMATCH")
    return candidates[0]


def run(date: str, daily_v5_pre_root: Path, current_pre_root: Path, primary_result_path: Path,
        auxiliary_result_path: Path, output_root: Path) -> Path:
    if output_root.exists():
        raise RuntimeError("STOP_OUTPUT_EXISTS")
    selection_path = daily_v5_pre_root / "selection.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection.get("status") != "SUCCESS" or selection.get("date") != date:
        raise RuntimeError("STOP_DAILY_V5_PRE_IDENTITY_MISMATCH")
    if _current_pre_target_date(current_pre_root) != date:
        raise RuntimeError("STOP_CURRENT_PRE_TARGET_DATE_MISMATCH")
    if selection.get("protocol_sha256") != sha(PROTOCOL):
        raise RuntimeError("STOP_PROTOCOL_SHA_MISMATCH")
    manifest_path = current_pre_root / "prediction_manifest.json"
    if selection.get("source_current_pre_manifest_sha256") != sha(manifest_path):
        raise RuntimeError("STOP_CURRENT_PRE_MANIFEST_MISMATCH")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for artifact in manifest["files"]:
        if sha(current_pre_root / artifact["relative_path"]) != artifact["sha256"]:
            raise RuntimeError("STOP_CURRENT_PRE_ARTIFACT_SHA_MISMATCH")
    rows, validation = _result_rows(primary_result_path, auxiliary_result_path, date)
    index = validation["source_d_primary"]["race_index"]
    reviewed = []
    for race in selection["races"]:
        if race["scope_status"] != "ELIGIBLE":
            continue
        venue = VENUE_TO_JA.get(race["venue"], race["venue"])
        key = _result_key(index, venue, int(race["race_number"]))
        row = rows[key]
        finishes = {number: row[11 + number] for number in range(1, int(index[key]["head_count"]) + 1)}
        if int(race["field_size"]) != int(index[key]["head_count"]):
            raise RuntimeError("STOP_RESULT_HORSE_IDENTITY_MISMATCH")
        reviewed.append(summarize_frozen_race(race, finishes))
    def combined(lane: str) -> dict:
        data = {"selected_count": sum(item[lane]["selected_count"] for item in reviewed),
                "valid_selected_count": sum(item[lane]["valid_selected_count"] for item in reviewed),
                "top3_count": sum(item[lane]["top3_count"] for item in reviewed)}
        data["buy_top3_rate"] = data["top3_count"] / data["valid_selected_count"] if data["valid_selected_count"] else None
        return data
    output_root.mkdir(parents=True)
    result = {"status": "SUCCESS", "date": date, "protocol_sha256": sha(PROTOCOL), "production_authorization": False,
              "source_daily_v5_selection_sha256": sha(selection_path), "source_current_pre_manifest_sha256": sha(manifest_path),
              "result_validation": validation, "races": reviewed, "combined": {"current": combined("current"), "daily_v5": combined("daily_v5")}}
    (output_root / "post.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_root / "SUCCESS").write_text(json.dumps({"status": "SUCCESS"}) + "\n", encoding="utf-8")
    return output_root
