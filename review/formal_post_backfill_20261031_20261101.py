"""Backfill missing formal POST records from sealed PRE and official Results only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from review.candidate_generation_training_dataset_readiness_v1 import (
    JAPANESE_VENUE, outcome, parse_race_id, result_rows,
)

ROOT = Path(__file__).resolve().parents[1]
E1 = Path("C:/Users/hikar/.codex/worktrees/e1-full-field-allocation-prospective-shadow-v1/keiba AI")
ANEW = Path("C:/Users/hikar/.codex/worktrees/a-new-prospective-shadow-v1/keiba AI")
DATES = ("20261031", "20261101")
OUT = ROOT / "reports/formal_post_backfill_20261031_20261101"
EXPECTED = {
    "20261031": {"EXP024": (15, 15, 0, 6), "PL_JOCKEY": (15, 15, 0, 8), "CURRENT_RANK1": (1, 1, 0, 0)},
    "20261101": {"EXP024": (14, 13, 1, 5), "PL_JOCKEY": (14, 13, 1, 7), "CURRENT_RANK1": (3, 3, 0, 1)},
}


def load(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError("STOP_SOURCE_MISSING:" + str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def stamp(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise RuntimeError("STOP_NAIVE_TIMESTAMP")
    return dt.astimezone(timezone.utc)


def metrics(rows: list[dict]) -> dict:
    valid = sum(row["valid_result"] for row in rows)
    hits = sum(row["actual_top3"] for row in rows)
    return {"selected": len(rows), "valid": valid, "invalid": len(rows) - valid,
            "hits": hits, "rate": hits / valid if valid else None}


def validated_pre(date: str) -> dict:
    current = ROOT / f"reports/prospective_prediction_{date}_formal_trace_v1"
    exp = ROOT / f"reports/exp024_pl_same_volume/{date}_pre"
    plj = ROOT / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{date}_pre"
    rank = ROOT / f"reports/current_rank1_prospective_shadow_v2/{date}_pre"
    specs = {
        "CURRENT": (current / "prediction_manifest.json", current / "formal_freeze_attestation.json",
                    "prediction_manifest_sha256", "freeze_timestamp_utc", "result_access_count"),
        "EXP024": (exp / "selection.json", exp / "selection_freeze.json",
                   "selection_sha256", "selection_freeze_timestamp", "result_access_before_freeze"),
        "PL_JOCKEY": (plj / "selection.json", plj / "provisional_audit.json",
                      "selection_sha256", "freeze_timestamp", "result_access_count"),
        "CURRENT_RANK1": (rank / "pre_selection.json", rank / "freeze_manifest.json",
                          "selection_sha256", "freeze_timestamp_jst", "result_access"),
    }
    values = {}
    for lane, (path, freeze_path, sha_field, time_field, result_field) in specs.items():
        frozen = load(freeze_path)
        selection_sha = sha(path)
        if frozen.get(sha_field) != selection_sha or bool(frozen.get(result_field)):
            raise RuntimeError(f"STOP_PRE_FREEZE_AUTHORITY:{date}:{lane}")
        first = frozen.get("first_start_at") or frozen.get("first_race_timestamp")
        if first is None or stamp(frozen[time_field]) >= stamp(first):
            raise RuntimeError(f"STOP_PRE_FREEZE_TIMING:{date}:{lane}")
        if frozen.get("date", frozen.get("target_date", date)) != date:
            raise RuntimeError(f"STOP_PRE_FREEZE_DATE:{date}:{lane}")
        values[lane] = {"path": str(path), "sha256": selection_sha, "freeze_path": str(freeze_path),
                        "freeze_sha256": sha(freeze_path), "freeze_timestamp": frozen[time_field],
                        "first_start_at": first, "result_access_at_pre": 0}
    current_frozen = load(specs["CURRENT"][1])
    exp_frozen = load(specs["EXP024"][1])
    plj_frozen = load(specs["PL_JOCKEY"][1])
    rank_frozen = load(specs["CURRENT_RANK1"][1])
    if (plj_frozen["current_pre_sha256"] != values["CURRENT"]["sha256"] or
            rank_frozen["current_manifest_sha256"] != values["CURRENT"]["sha256"] or
            rank_frozen["exp024_freeze_sha256"] != values["EXP024"]["freeze_sha256"] or
            current_frozen["prediction_manifest_sha256"] != values["CURRENT"]["sha256"] or
            exp_frozen["selection_sha256"] != values["EXP024"]["sha256"]):
        raise RuntimeError("STOP_CROSS_PRE_AUTHORITY:" + date)
    plj_selection = load(specs["PL_JOCKEY"][0])
    rank_selection = load(specs["CURRENT_RANK1"][0])
    exp_selection = load(specs["EXP024"][0])
    if (plj_selection["date"] != date or rank_selection["target_date"] != date or exp_selection["date"] != date or
            plj_selection["result_access_count"] != 0 or rank_selection["result_access_count"] != 0):
        raise RuntimeError("STOP_PRE_SELECTION_DATE_OR_RESULT_ACCESS:" + date)
    plj_count = sum(len(r["candidate_selected_horses"]) for r in plj_selection["races"])
    rank_count = len(rank_selection["selections"])
    exp_count = sum(len(r["treatment_selected_horses"]) for r in exp_selection["races"])
    if (plj_count, rank_count, exp_count) != (EXPECTED[date]["PL_JOCKEY"][0],
                                              EXPECTED[date]["CURRENT_RANK1"][0],
                                              EXPECTED[date]["EXP024"][0]):
        raise RuntimeError("STOP_PRE_SELECTION_COUNT:" + date)
    values["PL_JOCKEY"]["selection_count"] = plj_count
    values["CURRENT_RANK1"]["selection_count"] = rank_count
    values["EXP024"]["selection_count"] = exp_count
    return values


def selected_horses(date: str, lane: str, pre: dict) -> list[dict]:
    selection = load(Path(pre[lane]["path"]))
    result = []
    if lane == "PL_JOCKEY":
        for race in selection["races"]:
            names = {int(h["horse_number"]): h["horse_name"] for h in race["horses"]}
            for number in race["candidate_selected_horses"]:
                result.append({"race_id": race["race_id"], "horse_number": int(number),
                               "horse_name": names[int(number)]})
    elif lane == "CURRENT_RANK1":
        for row in selection["selections"]:
            result.append({"race_id": row["race_id"], "horse_number": int(row["selected_horse_number"]),
                           "horse_name": row["selected_horse_name"]})
    else:
        raise RuntimeError("STOP_UNSUPPORTED_LANE")
    keys = {(r["race_id"], r["horse_number"]) for r in result}
    if len(keys) != len(result) or len(result) != pre[lane]["selection_count"]:
        raise RuntimeError(f"STOP_DUPLICATE_OR_MISSING_PRE_SELECTION:{date}:{lane}")
    return sorted(result, key=lambda r: (r["race_id"], r["horse_number"]))


def joined(date: str, lane: str, pre: dict, sources: dict) -> list[dict]:
    rows = []
    for selected in selected_horses(date, lane, pre):
        rid, no = selected["race_id"], selected["horse_number"]
        found_date, venue_key, race_no = parse_race_id(rid)
        if found_date != date:
            raise RuntimeError("STOP_PRE_RACE_DATE:" + rid)
        source = sources[(JAPANESE_VENUE[venue_key], race_no)]
        if no < 1 or no > int(source[9]):
            raise RuntimeError("STOP_RESULT_HORSE_NUMBER:" + rid)
        valid, finish, top3 = outcome(source, no)
        rows.append({**selected, "venue": JAPANESE_VENUE[venue_key], "race_number": race_no,
                     "valid_result": valid, "finish": finish,
                     "result_status": "VALID" if valid else source[11 + no].strip(),
                     "actual_top3": bool(top3) if valid else False})
    return rows


def exp024_metrics(date: str, pre: dict, result_sha: dict) -> tuple[dict, dict, Path]:
    path = ROOT / f"reports/exp024_pl_same_volume/{date}_post/post.json"
    post = load(path)
    if (post["date"] != date or post["role"] != "PROSPECTIVE_OBSERVATION_ONLY" or
            post["selection_sha256"] != pre["EXP024"]["sha256"] or
            post["result_source_sha256"] != {"primary": result_sha["horse_order"], "auxiliary": result_sha["finish_order"]}):
        raise RuntimeError("STOP_EXP024_POST_AUTHORITY:" + date)
    arms = {}
    for arm in ("current", "treatment"):
        selected = sum(r[arm]["prediction_count"] for r in post["races"])
        valid = sum(r[arm]["valid_count"] for r in post["races"])
        hits = sum(r[arm]["hits"] for r in post["races"])
        arms[arm] = {"selected": selected, "valid": valid, "invalid": selected - valid,
                     "hits": hits, "rate": hits / valid if valid else None}
    return arms["treatment"], arms["current"], path


def independent_metric(date: str, lane: str) -> dict:
    path = ROOT / f"reports/{date}_full_post_evaluation_v1/post_evaluation_{date}.json"
    return load(path)["lane_performance"][lane]


def matching(actual: dict, expected: tuple[int, int, int, int], independent: dict) -> bool:
    return ((actual["selected"], actual["valid"], actual["invalid"], actual["hits"]) == expected ==
            (independent["selected"], independent["valid"], independent["invalid"], independent["hits"]))


def preflight() -> dict:
    audit = {}
    for date in DATES:
        pre = validated_pre(date)
        raw = ROOT / "data/raw/target/daily_result_list"
        result_paths = {"horse_order": raw / f"馬番順着順_{date}.csv",
                        "finish_order": raw / f"着順馬番_{date}.csv"}
        if not all(p.is_file() for p in result_paths.values()):
            raise RuntimeError("STOP_RESULT_SOURCE_MISSING:" + date)
        # The established source-pair validator is called by result_rows.
        sources = result_rows(date)
        result_sha = {kind: sha(path) for kind, path in result_paths.items()}
        exp_metric, exp_current, exp_post_path = exp024_metrics(date, pre, result_sha)
        horse_rows = {lane: joined(date, lane, pre, sources) for lane in ("PL_JOCKEY", "CURRENT_RANK1")}
        lane_metrics = {"EXP024": exp_metric, **{lane: metrics(rows) for lane, rows in horse_rows.items()}}
        mismatches = [lane for lane, actual in lane_metrics.items()
                      if not matching(actual, EXPECTED[date][lane], independent_metric(date, lane))]
        if mismatches:
            raise RuntimeError("STOP_POST_BACKFILL_MISMATCH:" + date + ":" + ",".join(mismatches))
        e1_selection = load(E1 / f"reports/e1_full_field_allocation_prospective_shadow_v1/daily_pre/{date}/selection.json")
        e1_post = load(E1 / f"reports/e1_full_field_allocation_prospective_shadow_v1/daily_post/{date}/post.json")
        if (e1_selection["exp024_sealed_selection_sha256"] != pre["EXP024"]["sha256"] or
                any(e1_post["exp024"][field] != exp_metric[field] for field in ("selected", "valid", "invalid", "hits"))):
            raise RuntimeError("STOP_E1_EXP024_CROSSCHECK:" + date)
        audit[date] = {"pre_authority": pre,
                       "result": {"source_paths": {k: str(v) for k, v in result_paths.items()},
                                  "source_sha256": result_sha, "race_count": len(sources),
                                  "horse_slots": sum(int(r[9]) for r in sources.values())},
                       "exp024_post_path": str(exp_post_path), "exp024_post_sha256": sha(exp_post_path),
                       "exp024_current": exp_current, "metrics": lane_metrics, "horse_rows": horse_rows,
                       "crosscheck_status": "PASS"}
    return audit


def write_post(date: str, lane: str, audit: dict) -> tuple[str, Path]:
    root_name = "frozen_pl_v1_jockey_offset_provisional_v1" if lane == "PL_JOCKEY" else "current_rank1_prospective_shadow_v2"
    folder = ROOT / "reports" / root_name / f"{date}_post"
    path = folder / "post.json"
    if path.exists():
        existing = load(path)
        if (existing.get("pre_selection_sha256") != audit["pre_authority"][lane]["sha256"] or
                existing.get("result_source_sha256") != audit["result"]["source_sha256"] or
                existing.get("metrics") != audit["metrics"][lane]):
            raise RuntimeError("STOP_EXISTING_POST_CONFLICT:" + str(path))
        return "ALREADY_EXISTS", path
    if folder.exists():
        raise RuntimeError("STOP_POST_FOLDER_EXISTS:" + str(folder))
    payload = {"date": date, "lane": lane, "role": "FORMAL_POST_ARTIFACT_BACKFILL_NO_EVIDENCE_STATUS_CHANGE",
               "pre_selection_path": audit["pre_authority"][lane]["path"],
               "pre_selection_sha256": audit["pre_authority"][lane]["sha256"],
               "pre_freeze_path": audit["pre_authority"][lane]["freeze_path"],
               "pre_freeze_sha256": audit["pre_authority"][lane]["freeze_sha256"],
               "pre_freeze_timestamp": audit["pre_authority"][lane]["freeze_timestamp"],
               "result_source_sha256": audit["result"]["source_sha256"],
               "execution_timestamp_utc": datetime.now(timezone.utc).isoformat(),
               "metrics": audit["metrics"][lane], "selected_horse_outcomes": audit["horse_rows"][lane],
               "crosscheck_status": "PASS", "pre_selection_changed": False,
               "formal_evidence_changed": False}
    folder.mkdir(parents=True, exist_ok=False)
    with path.open("xb") as stream:
        stream.write(canonical(payload))
    return "CREATED", path


def write_audit(audit: dict, statuses: dict) -> dict:
    if OUT.exists():
        raise RuntimeError("STOP_AUDIT_OUTPUT_EXISTS")
    before = {"e1_" + date: sha(E1 / f"reports/e1_full_field_allocation_prospective_shadow_v1/daily_post/{date}/post.json")
              for date in DATES}
    before["a_new_20261101"] = sha(ANEW / "reports/a_new_prospective_shadow_v1/daily_post/20261101/post.json")
    index = []
    for date in DATES:
        for lane in ("EXP024", "PL_JOCKEY", "CURRENT_RANK1"):
            item = audit[date]
            path = (Path(item["exp024_post_path"]) if lane == "EXP024" else Path(statuses[(date, lane)][1]))
            m = item["metrics"][lane]
            index.append({"date": date, "lane": lane, "post_status": "CREATED" if lane == "EXP024" else statuses[(date, lane)][0],
                          "pre_path": item["pre_authority"][lane]["path"],
                          "pre_sha256": item["pre_authority"][lane]["sha256"],
                          "freeze_timestamp": item["pre_authority"][lane]["freeze_timestamp"],
                          "pre_result_access": 0, "result_horse_order_sha256": item["result"]["source_sha256"]["horse_order"],
                          "result_finish_order_sha256": item["result"]["source_sha256"]["finish_order"],
                          "post_path": str(path), "post_sha256": sha(path),
                          **m, "crosscheck_status": "PASS"})
    after = {"e1_" + date: sha(E1 / f"reports/e1_full_field_allocation_prospective_shadow_v1/daily_post/{date}/post.json")
             for date in DATES}
    after["a_new_20261101"] = sha(ANEW / "reports/a_new_prospective_shadow_v1/daily_post/20261101/post.json")
    if before != after:
        raise RuntimeError("STOP_EXISTING_POST_CHANGED")
    OUT.mkdir(parents=True, exist_ok=False)
    csv_path = OUT / "formal_post_artifact_index.csv"
    with csv_path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(index[0]))
        writer.writeheader()
        writer.writerows(index)
    manifest = {"status": "COMPLETE", "dates": list(DATES), "role": "FORMAL_POST_ARTIFACT_BACKFILL",
                "audit": {date: {key: value for key, value in audit[date].items() if key != "horse_rows"} for date in DATES},
                "artifact_index": index, "artifact_index_sha256": sha(csv_path),
                "e1_exp024_post_crosscheck_source_available": True,
                "existing_post_sha256_before": before, "existing_post_sha256_after": after,
                "existing_post_changed": False, "pre_artifact_changed": False,
                "model_changed": False, "buy_rule_changed": False, "prediction_rerun": False,
                "training_executed": False, "formal_evidence_changed": False}
    manifest_path = OUT / "formal_post_backfill_manifest.json"
    manifest_path.write_bytes(canonical(manifest))
    lines = ["# Formal POST artifact backfill: 2026-10-31 / 2026-11-01", "",
             "Frozen PRE selections were joined with the official validated Result pair. Existing PRE/POST and Evidence states were not changed.", "",
             "| Date | Lane | Selected | Valid | Invalid | Top3 | Rate | Cross-check |",
             "|---|---|---:|---:|---:|---:|---:|---|"]
    for row in index:
        lines.append(f"| {row['date']} | {row['lane']} | {row['selected']} | {row['valid']} | {row['invalid']} | {row['hits']} | {row['rate']:.2%} | PASS |")
    lines += ["", "EXP024 POST uses the existing post_from_frozen function and contains same-race/same-k Current and treatment arms.",
              "PL_JOCKEY and CURRENT_RANK1 POST records contain horse-level outcomes from their sealed selections only; no selection or score was regenerated.",
              "Both EXP024 POST files pass the existing E1 cross-check against the frozen E1 comparator totals. E1 POST itself was not rerun or rewritten.", "",
              "See formal_post_backfill_manifest.json for all PRE/freeze/Result/POST paths, SHA256, timestamps, counts and existing-POST hash invariance."]
    (OUT / "formal_post_backfill_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"index": index, "manifest_sha256": sha(manifest_path), "index_sha256": sha(csv_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.check == args.write:
        raise RuntimeError("STOP_SELECT_ONE_MODE")
    audit = preflight()
    if args.check:
        print(json.dumps({date: {"result": audit[date]["result"], "metrics": audit[date]["metrics"]} for date in DATES},
                         ensure_ascii=False, indent=2))
        return
    statuses = {(date, lane): write_post(date, lane, audit[date])
                for date in DATES for lane in ("PL_JOCKEY", "CURRENT_RANK1")}
    final = write_audit(audit, statuses)
    print(json.dumps({"status": "COMPLETE", "statuses": {f"{date}_{lane}": status for (date, lane), (status, _) in statuses.items()},
                      "manifest_sha256": final["manifest_sha256"], "index_sha256": final["index_sha256"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
