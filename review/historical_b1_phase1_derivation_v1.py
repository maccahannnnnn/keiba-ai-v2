"""Result-free historical B1 derivation from saved H1 A0 fold predictions."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from review.b1_prospective_diagnostic_v1 import select_b1
from review.historical_lane_coverage_registry_v1 import CoverageStop, sha

def derive_h1_b1(phase1_path: Path, output: Path) -> dict:
    if output.exists():
        raise CoverageStop("STOP_OUTPUT_EXISTS")
    phase1 = json.loads(phase1_path.read_text(encoding="utf-8"))
    if phase1.get("result_access_count") != 0 or phase1.get("evidence_credit") != 0:
        raise CoverageStop("STOP_PHASE1_ROLE")
    current = defaultdict(set)
    for row in phase1["selected_horses"]:
        if row["block"] == "H1" and row["lane"] == "CURRENT":
            if row["selection_eligibility"] != "TECHNICAL_SOURCE_PASS":
                raise CoverageStop("STOP_CURRENT_ELIGIBILITY")
            current[row["date"]].add((row["race_id"], row["horse_number"]))
    if len(current) != 53 or sum(map(len, current.values())) != 716:
        raise CoverageStop("STOP_CURRENT_H1_POPULATION")
    predictions = defaultdict(list)
    sources = []
    fold_paths = sorted({Path(source["path"]) for source in phase1["sources"]
                         if source["block"] == "H1" and source["lane"] == "PL_JOCKEY"})
    if len(fold_paths) != 7:
        raise CoverageStop("STOP_A0_FOLD_COUNT")
    for path in fold_paths:
        expected = {source["sha256"] for source in phase1["sources"]
                    if source["block"] == "H1" and source["lane"] == "PL_JOCKEY"
                    and source["path"] == str(path)}
        if len(expected) != 1 or sha(path) not in expected:
            raise CoverageStop("STOP_A0_SOURCE_SHA")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("validation_result_access_before_freeze") != 0:
            raise CoverageStop("STOP_FOLD_RESULT_ACCESS")
        sources.append({"path": str(path.resolve()), "sha256": sha(path), "month": path.parent.name})
        for row in value["predictions"]["A0"]:
            predictions[row["date"]].append(row)
    if set(predictions) != set(current) or sum(map(len, predictions.values())) != 12661:
        raise CoverageStop("STOP_A0_H1_POPULATION")
    selected = []
    for date, rows in sorted(predictions.items()):
        fold_current = {(r["race_id"], int(r["horse_number"])) for r in rows if r["current_buy"]}
        if fold_current != current[date]:
            raise CoverageStop("STOP_CURRENT_MISMATCH:" + date)
        by_race = defaultdict(list)
        for row in rows:
            by_race[row["race_id"]].append(row)
        races = []
        for rid, horses in sorted(by_race.items()):
            races.append({"race_id": rid, "current_k": sum(r["current_buy"] for r in horses),
                          "horses": [{"horse_number": int(r["horse_number"]),
                                      "horse_name": r["horse_name"],
                                      "candidate_p_top3": r["p_top3"],
                                      "jockey_top3_lift": r.get("jockey_lift")}
                                     for r in horses]})
        for row in select_b1(races, len(current[date])):
            selected.append({"date": date, "block": "H1", "lane": "B1", **row})
    if len(selected) != 716 or len({(r["date"], r["race_id"], r["horse_number"]) for r in selected}) != 716:
        raise CoverageStop("STOP_B1_SELECTION_COUNT")
    result = {"schema_version": "HISTORICAL_B1_PHASE1_DERIVATION_V1",
              "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
              "source_role": "H1_SAVED_A0_WALK_FORWARD_DEVELOPMENT",
              "evidence_credit": 0, "result_access_count": 0,
              "phase1_path": str(phase1_path.resolve()), "phase1_sha256": sha(phase1_path),
              "code_sha256": sha(Path(__file__)),
              "b1_selector_sha256": sha(Path(select_b1.__code__.co_filename)),
              "sources": sources, "dates": len(current), "races": len({r["race_id"] for rs in predictions.values() for r in rs}),
              "horses": sum(map(len, predictions.values())), "daily_current_identity_match": True,
              "selected_count": len(selected), "selected_horses": selected,
              "phase2_status": "NOT_AUTHORIZED"}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    return result


def derive_p_b1(phase1_path: Path, output: Path) -> dict:
    """Pre-effective-date B1 diagnostic only; never formal B1 Evidence."""
    if output.exists():
        raise CoverageStop("STOP_OUTPUT_EXISTS")
    phase1 = json.loads(phase1_path.read_text(encoding="utf-8"))
    if phase1.get("result_access_count") != 0 or phase1.get("evidence_credit") != 0:
        raise CoverageStop("STOP_PHASE1_ROLE")
    current = defaultdict(set)
    for row in phase1["selected_horses"]:
        if row["block"] == "P" and row["lane"] == "CURRENT":
            current[row["date"]].add((row["race_id"], row["horse_number"]))
    sources = [row for row in phase1["sources"] if row["block"] == "P" and row["lane"] == "PL_JOCKEY"]
    if len(sources) != 3 or {row["date"] for row in sources} != set(current):
        raise CoverageStop("STOP_P_SOURCE_SCOPE")
    selected = []
    source_records = []
    race_count = horse_count = 0
    for source in sorted(sources, key=lambda row: row["date"]):
        date = source["date"]
        path = Path(source["path"])
        if sha(path) != source["sha256"]:
            raise CoverageStop("STOP_P_PLJ_SHA:" + date)
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("result_access_count") != 0 or value.get("date") != date:
            raise CoverageStop("STOP_P_PLJ_ROLE:" + date)
        races = []
        for race in value["races"]:
            rid = race["race_id"]
            horses = race["horses"]
            races.append({"race_id": rid,
                          "current_k": sum(key[0] == rid for key in current[date]),
                          "horses": horses})
            horse_count += len(horses)
        race_count += len(races)
        if not current[date] <= {(race["race_id"], int(horse["horse_number"]))
                                 for race in races for horse in race["horses"]}:
            raise CoverageStop("STOP_P_CURRENT_UNIVERSE:" + date)
        for row in select_b1(races, len(current[date])):
            selected.append({"date": date, "block": "P", "lane": "B1", **row})
        source_records.append({"date": date, "path": str(path.resolve()), "sha256": source["sha256"]})
    if len(selected) != 38 or race_count != 45:
        raise CoverageStop("STOP_P_SELECTION_POPULATION")
    result = {"schema_version": "HISTORICAL_B1_PHASE1_DERIVATION_V1",
              "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
              "source_role": "P_PRE_EFFECTIVE_DIAGNOSTIC_ONLY",
              "effective_from": "20261114", "evidence_credit": 0, "result_access_count": 0,
              "phase1_path": str(phase1_path.resolve()), "phase1_sha256": sha(phase1_path),
              "code_sha256": sha(Path(__file__)),
              "b1_selector_sha256": sha(Path(select_b1.__code__.co_filename)),
              "sources": source_records, "dates": len(current), "races": race_count,
              "horses": horse_count, "selected_count": len(selected),
              "selected_horses": selected, "phase2_status": "NOT_AUTHORIZED"}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    return result
