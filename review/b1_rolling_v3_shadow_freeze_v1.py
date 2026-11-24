"""Independent, result-blind Rolling V3 Shadow freeze and frozen-only POST.

Never invoked by formal run-all. No fit, deployment, or parent writes.
Existing freezes bind their original Candidate even after the weekly pointer moves.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

from review import b1_rolling_v3_shadow_v1 as calculation
from review import b1_prospective_diagnostic_v1 as b1
from review import candidate_generation_training_dataset_readiness_v1 as baseline
from review import small_field_place_h1_diagnostic_v2 as place
from review import small_field_place_h1_diagnostic_v1 as statistics
from review import target_daily_result_list_schema_v2_validator as schema

ROOT = calculation.SOURCE_ROOT
STATE_ROOT = calculation.STATE_ROOT
REPORT = "reports/b1_rolling_v3_shadow_freeze_v1"
LANES = calculation.LANES
COMPARATORS = ("CURRENT", "B1")
JST = timezone(timedelta(hours=9))
ROLE = "ROLLING_V3_SHADOW_ONLY"
Stop = calculation.Stop


def now():
    return datetime.now(timezone.utc)


def require(ok, reason):
    if not ok:
        raise Stop(reason)


def checked_date(value):
    require(isinstance(value, str) and len(value) == 8 and value.isascii() and value.isdigit(), "STOP_DATE")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise Stop("STOP_DATE") from error
    return value


def moment(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(stamp.tzinfo is not None and stamp.utcoffset() is not None, "STOP_TIMEZONE")
        return stamp
    except (ValueError, AttributeError) as error:
        raise Stop("STOP_TIMESTAMP") from error


def sha(path):
    return calculation.sha(Path(path))


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def key(row):
    return row["race_id"], int(row["horse_number"])


def load(path, sources=None):
    path = Path(path).resolve()
    digest = sha(path)
    value = calculation.read(path)
    require(sha(path) == digest, "STOP_SOURCE_CHANGED_DURING_READ")
    if sources is not None:
        sources[str(path)] = digest
    return value


def unchanged(sources):
    for path, digest in sources.items():
        require(sha(path) == digest, "STOP_SOURCE_SHA:" + path)


def folder(root, phase, date):
    return Path(root) / REPORT / phase / date


def result_paths(root, date):
    raw = Path(root) / "data/raw/target/daily_result_list"
    return tuple(raw / f"{prefix}_{date}.csv" for prefix in ("馬番順着順", "着順馬番"))


def no_result(root, date):
    # Presence checks only. No target Result content is opened in PRE.
    require(not any(p.exists() for p in result_paths(root, date)), "STOP_RESULT_ALREADY_PRESENT")


def code_sources():
    modules = (calculation, b1, baseline, place, statistics, schema,
               calculation.forward, calculation.old_plj, calculation.top3)
    paths = {Path(m.__file__).resolve() for m in modules} | {Path(__file__).resolve()}
    return {str(p): sha(p) for p in paths}


def authority(date, root):
    """Read frozen formal sources only; no inference or Result access."""
    root = Path(root).resolve()
    sources = code_sources()
    current = root / f"reports/prospective_prediction_{date}_formal_trace_v1"
    summary = load(root / f"reports/formal_pre_daily/{date}/summary.json", sources)
    manifest_path = current / "prediction_manifest.json"
    manifest = load(manifest_path, sources)
    seal_path = current / "formal_freeze_attestation.json"
    seal = load(seal_path, sources)
    require(summary.get("date") == date and summary.get("status") == "COMPLETE" and
            summary.get("result_access_count") == 0, "STOP_FORMAL_PRE_STATUS")
    require(seal.get("date") == date and seal.get("prediction_manifest_sha256") == sha(manifest_path) and
            seal.get("result_access_count") == 0, "STOP_CURRENT_FREEZE")
    first_path = (root / seal["first_start_evidence_path"]).resolve()
    require(first_path.is_relative_to(root), "STOP_FIRST_START_PATH")
    first = load(first_path, sources)
    deadline = moment(seal["first_start_at"])
    require(first.get("date") == date and moment(first["first_start_at"]) == deadline and
            deadline.astimezone(JST).strftime("%Y%m%d") == date and
            sha(first_path) == seal.get("first_start_evidence_sha256") == summary.get("first_start_authority_sha256") and
            moment(seal["freeze_timestamp_utc"]) < deadline, "STOP_FIRST_START_AUTHORITY")
    listed = set()
    for item in manifest.get("files", []):
        name = item["relative_path"]
        path = (current / name).resolve()
        require(path.parent == current and name not in listed and sha(path) == item["sha256"], "STOP_CURRENT_MANIFEST")
        if path.suffix == ".json":
            load(path, sources)
        else:
            sources[str(path)] = item["sha256"]
        listed.add(name)
    require({"input_manifest.json", "race_index.json"} <= listed, "STOP_CURRENT_MANIFEST")
    provenance = load(current / "provenance.json", sources)
    require(provenance.get("result_data_access_count") == 0, "STOP_PRE_RESULT_ACCESS")
    inputs = load(current / "input_manifest.json", sources)
    verified = b1.verified_input_sources(current, inputs)
    require(inputs.get("date") == date and summary.get("input_sha256") ==
            {k: v["sha256"] for k, v in verified.items()}, "STOP_INPUT_SHA")
    for entry in verified.values():
        sources[str(Path(entry["path"]).resolve())] = entry["sha256"]
    plj_dir = root / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{date}_pre"
    plj = load(plj_dir / "selection.json", sources)
    plj_seal = load(plj_dir / "provisional_audit.json", sources)
    require(plj.get("date") == date and plj_seal.get("selection_sha256") == sha(plj_dir / "selection.json") and
            plj.get("result_access_count") == plj_seal.get("result_access_count") == 0 and
            plj.get("fallback_race_count") == 0 and
            moment(plj_seal["freeze_timestamp"]) < deadline, "STOP_PLJ_FREEZE")
    for lane, selection, frozen in (("CURRENT", manifest_path, seal_path),
                                    ("PL_JOCKEY", plj_dir / "selection.json", plj_dir / "provisional_audit.json")):
        item = summary["lanes"][lane]
        require(item["selection_sha256"] == sha(selection) and item["authority_sha256"] == sha(frozen), "STOP_SUMMARY_SHA")
    pl_path = root / f"reports/pl_forward_shadow_v1/{date}_pre/prediction.json"
    load(pl_path, sources)
    require(plj.get("pl_prediction_sha256") == sha(pl_path), "STOP_PL_SOURCE_SHA")
    for item in plj.get("jockey_snapshot_manifest", []):
        if item.get("included"):
            path = (root / item["path"]).resolve()
            require(sha(path) == item["sha256"], "STOP_JOCKEY_SNAPSHOT_SHA")
            sources[str(path)] = item["sha256"]
    for name, digest in plj.get("runtime_dependency_sha256", {}).items():
        path = (root / name).resolve()
        require(sha(path) == digest, "STOP_JOCKEY_CODE_SHA")
        sources[str(path)] = digest
    bdir = root / f"reports/formal_pre_daily/{date}/b1_diagnostic"
    frozen_b1 = load(bdir / "selection.json", sources)
    bseal = load(bdir / "freeze_manifest.json", sources)
    require(frozen_b1.get("date") == bseal.get("date") == date and
            bseal.get("selection_sha256") == sha(bdir / "selection.json") and bseal.get("result_access_count") == 0 and
            moment(bseal["freeze_timestamp_utc"]) < deadline and
            frozen_b1.get("current_prediction_sha256") == sha(manifest_path) and
            frozen_b1.get("pl_jockey_selection_sha256") == sha(plj_dir / "selection.json"), "STOP_B1_AUTHORITY")
    fields, current_selected, counts = {}, [], {}
    index = load(current / "race_index.json", sources)["race_index"]
    for item in index:
        rid = item["race_id"]
        require(rid.startswith(f"race_{date}_") and rid not in fields and item["artifact"] in listed, "STOP_RACE_IDENTITY")
        payload = load(current / item["artifact"], sources)
        horses = payload["ranked_results"]
        field = {int(h["horse_number"]): h for h in horses}
        require(payload.get("race_id") == rid and len(horses) == len(field) == item["horse_count"] and
                set(field) == set(range(1, len(field) + 1)) and len(payload["buys"]) == item["buy_count"], "STOP_CURRENT_IDENTITY")
        fields[rid] = field
        counts[rid] = item["buy_count"]
        current_selected.extend(dict(h, race_id=rid) for h in payload["buys"])
    require(len(fields) == summary["race_count"] and sum(map(len, fields.values())) == summary["horse_count"], "STOP_PRE_POPULATION")
    n = len(current_selected)
    require(frozen_b1.get("selected_count") == frozen_b1.get("daily_current_buy_n") == n and
            len(frozen_b1["selected_horses"]) == n, "STOP_PARENT_DAILY_N")
    return {"sources": sources, "deadline": deadline, "fields": fields, "counts": counts,
            "daily_n": n, "comparators": {"CURRENT": current_selected, "B1": frozen_b1["selected_horses"]}}


def validate_record(record):
    date = checked_date(record.get("date"))
    require(record.get("role") == ROLE and record.get("status") == "FROZEN_SHADOW_PRE" and
            record.get("evidence_credit") == record.get("b1_adoption_evidence_credit") == 0 and
            record.get("result_access_count") == 0, "STOP_PRE_SEMANTICS")
    require(moment(record["freeze_timestamp_utc"]) < moment(record["freeze_deadline"]), "STOP_PRE_TIMING")
    candidate = record["candidate"]
    require(checked_date(candidate["training_end"]) < date, "STOP_MODEL_PIT")
    n = record["daily_selected_count"]
    require(type(n) is int and n >= 0 and set(record["races"]) == set(LANES), "STOP_PRE_LANES")
    fields = record["fields"]
    expected = {(rid, int(number)) for rid, horses in fields.items() for number in horses}
    for lane in LANES:
        actual = {}
        for race in record["races"][lane]:
            rid = race["race_id"]
            require(rid in fields and rid.startswith(f"race_{date}_"), "STOP_PRE_RACE")
            horses = race["horses"]
            ranked = sorted(horses, key=lambda h: (-h["candidate_p_top3"], int(h["horse_number"])))
            for rank, h in enumerate(ranked, 1):
                p = h["candidate_p_top3"]
                k = key(dict(h, race_id=rid))
                require(k not in actual and math.isfinite(p) and 0 <= p <= 1 and h["race_rank"] == rank, "STOP_PROBABILITY_OR_RANK")
                require(fields[rid].get(str(k[1])) == h["horse_name"], "STOP_HORSE_IDENTITY")
                actual[k] = h
            require(abs(sum(h["candidate_p_top3"] for h in horses) - 3) < 1e-8, "STOP_TOP3_MASS")
        require(set(actual) == expected, "STOP_PRE_FULL_FIELD")
        for h in record["selected"][lane]:
            require(key(h) in actual and actual[key(h)]["candidate_p_top3"] == h["pl_jockey_p_top3"], "STOP_SELECTED_PROBABILITY")
    require(set(record["selected"]) == set(LANES) | set(COMPARATORS), "STOP_SELECTION_LANES")
    for lane, rows in record["selected"].items():
        keys = [key(h) for h in rows]
        require(len(rows) == len(set(keys)) == n and max(Counter(k[0] for k in keys).values(), default=0) <= 3, "STOP_SELECTION_COUNT")
        for h in rows:
            require(fields.get(h["race_id"], {}).get(str(h["horse_number"])) == h["horse_name"], "STOP_SELECTED_IDENTITY")


def verify_pre(date, *, root=ROOT):
    checked_date(date)
    out = folder(root, "daily_pre", date)
    record = load(out / "selection.json")
    seal = load(out / "freeze_manifest.json")
    require(record.get("date") == seal.get("date") == date and
            seal.get("selection_sha256") == sha(out / "selection.json") and
            seal.get("candidate") == record.get("candidate") and
            seal.get("freeze_timestamp_utc") == record.get("freeze_timestamp_utc") and
            seal.get("result_access_count") == 0 and seal.get("evidence_credit") == 0, "STOP_FREEZE_SHA")
    validate_record(record)
    # Only frozen PRE inputs/code, never the mutable latest Candidate pointer.
    unchanged(record["source_artifacts_sha256"])
    return record


def freeze_pre(date, *, root=ROOT, state_root=STATE_ROOT, test_only=False):
    checked_date(date)
    root, state_root = Path(root).resolve(), Path(state_root).resolve()
    require(not test_only or (root != ROOT.resolve() and state_root != STATE_ROOT.resolve()), "STOP_TEST_LIVE_ROOT")
    out = folder(root, "daily_pre", date)
    if out.exists():
        record = verify_pre(date, root=root)
        require(record.get("test_only") == test_only, "STOP_TEST_ROLE_MISMATCH")
        return {"status": "ALREADY_FROZEN_UNCHANGED", "path": str(out / "selection.json"), "sha256": sha(out / "selection.json")}
    no_result(root, date)
    auth = authority(date, root)
    require(now() < auth["deadline"], "STOP_CUTOFF")
    snapshot = calculation.model_snapshot(date, state_root)
    model_dir = state_root / "models/rolling_pl_jockey_v3/versions" / snapshot["version"]
    binding = {str(state_root / "models/rolling_pl_jockey_v3/current.json"): sha(state_root / "models/rolling_pl_jockey_v3/current.json"),
               str(state_root / "reports/rolling_learning_v3/candidate_registry.jsonl"): sha(state_root / "reports/rolling_learning_v3/candidate_registry.jsonl")}
    candidate_files = {str(model_dir / name): sha(model_dir / name) for name in ("model.json", "manifest.json")}
    calculated = calculation.technical_date(date, source_root=root, state_root=state_root, verify_jockey=True)
    candidate = {k: snapshot[k] for k in ("version", "model_sha256", "manifest_sha256", "training_end", "jockey_beta")}
    require(all(calculated[k] == snapshot[v] for k, v in (("model_version", "version"), ("model_sha256", "model_sha256"),
                ("model_manifest_sha256", "manifest_sha256"), ("training_end", "training_end"))) and
            calculated.get("result_access_count") == 0 and calculated["daily_current_n"] == auth["daily_n"], "STOP_CALCULATION_BINDING")
    unchanged(binding)
    unchanged(candidate_files)
    unchanged(auth["sources"])
    races = calculated["races"]
    for lane in LANES:
        for race in races[lane]:
            for rank, h in enumerate(sorted(race["horses"], key=lambda h: (-h["candidate_p_top3"], int(h["horse_number"]))), 1):
                h["race_rank"] = rank
    record = {"date": date, "status": "FROZEN_SHADOW_PRE", "role": ROLE, "test_only": test_only,
              "evidence_credit": 0, "b1_adoption_evidence_credit": 0, "result_access_count": 0,
              "freeze_timestamp_utc": now().isoformat(), "freeze_deadline": auth["deadline"].isoformat(),
              "candidate": candidate, "candidate_artifacts_sha256_at_freeze": candidate_files,
              "candidate_binding_sha256_at_freeze": binding, "source_artifacts_sha256": auth["sources"],
              "selection_method": "EXISTING_B1_SELECT_B1_DAILY_CURRENT_N_CAP3",
              "rank_semantics": "Race probability descending, horse number ascending on ties; global_rank is the existing select_b1 order.",
              "daily_selected_count": auth["daily_n"],
              "fields": {rid: {str(n): h["horse_name"] for n, h in horses.items()} for rid, horses in auth["fields"].items()},
              "races": races, "selected": {**calculated["selected"], **auth["comparators"]}}
    validate_record(record)
    no_result(root, date)
    require(now() < auth["deadline"], "STOP_CUTOFF")
    out.mkdir(parents=True, exist_ok=False)
    with (out / "selection.json").open("xb") as stream:
        stream.write(canonical(record))
    no_result(root, date)
    require(now() < auth["deadline"], "STOP_CUTOFF_PARTIAL_OUTPUT")
    seal = {"date": date, "selection_sha256": sha(out / "selection.json"), "candidate": candidate,
            "freeze_timestamp_utc": record["freeze_timestamp_utc"], "result_access_count": 0, "evidence_credit": 0}
    with (out / "freeze_manifest.json").open("xb") as stream:
        stream.write(canonical(seal))
    require(now() < auth["deadline"], "STOP_CUTOFF_PARTIAL_OUTPUT")
    verify_pre(date, root=root)
    return {"status": "FROZEN_SHADOW_PRE", "path": str(out / "selection.json"), "sha256": sha(out / "selection.json")}


def verify_post(date, *, root=ROOT):
    pre = verify_pre(date, root=root)
    out = folder(root, "daily_post", date)
    report, complete = load(out / "post_summary.json"), load(out / "complete.json")
    require(report.get("date") == complete.get("date") == date and report.get("status") == "COMPLETE" and
            complete.get("post_sha256") == sha(out / "post_summary.json") and report.get("candidate") == pre["candidate"] and
            report.get("pre_selection_sha256") == sha(folder(root, "daily_pre", date) / "selection.json") and
            report.get("pre_freeze_sha256") == sha(folder(root, "daily_pre", date) / "freeze_manifest.json") and
            report.get("evidence_credit") == report.get("b1_adoption_evidence_credit") == 0, "STOP_POST_COMPLETE_SHA")
    unchanged(report["result_sources_sha256"])
    return report


def post(date, *, root=ROOT, human_final_result_confirmed=False):
    checked_date(date)
    require(human_final_result_confirmed, "STOP_RESULT_FINALITY_CONFIRMATION_REQUIRED")
    pre = verify_pre(date, root=root)
    out = folder(root, "daily_post", date)
    if out.exists():
        verify_post(date, root=root)
        return {"status": "ALREADY_COMPLETE_UNCHANGED", "path": str(out / "post_summary.json"), "sha256": sha(out / "post_summary.json")}
    primary, auxiliary = result_paths(root, date)
    hashes = {str(p.resolve()): sha(p) for p in (primary, auxiliary)}
    schema.validate_source_pair(primary, auxiliary, date)
    # Use the existing Baseline result loader with this explicit source root.
    import csv
    with primary.open(encoding="cp932", newline="") as stream:
        raw = list(csv.reader(stream))
    results = {(r[1], int(r[2])): r for r in raw}
    require(len(results) == len(raw), "STOP_DUPLICATE_RESULT_RACE")
    result_for = {}
    for rid, horses in pre["fields"].items():
        d, venue, number = baseline.parse_race_id(rid)
        require(d == date and (baseline.JAPANESE_VENUE[venue], number) in results, "STOP_RESULT_RACE_MISSING")
        row = results[baseline.JAPANESE_VENUE[venue], number]
        require(int(row[9]) == len(horses), "STOP_RESULT_ROSTER")
        for horse in horses:
            baseline.outcome(row, int(horse))
        result_for[rid] = row
    outcomes = {}
    for lane, selected in pre["selected"].items():
        rows = []
        for h in selected:
            rid, number = key(h)
            result = result_for[rid]
            size = len(pre["fields"][rid])
            starters = sum(result[11 + n].strip() not in ("取消", "除外") for n in range(1, size + 1))
            valid, finish, hit = baseline.outcome(result, number)
            raw_status = result[11 + number].strip()
            rows.append(dict(h, raw_result=raw_status, valid_result=valid, finish=finish, actual_top3=bool(hit) if valid else False,
                             ticket_status=place.ticket(raw_status, starters, size), actual_starters=starters,
                             pre_field_size=size, place_terms_basis="PRE_ROSTER_BOUND_AND_ACTUAL_STARTERS"))
        outcomes[lane] = rows
    metrics = {lane: dict(statistics.metric(rows), selected_races=len({h["race_id"] for h in rows}),
                         result_status_counts=dict(Counter(h["raw_result"] for h in rows if not h["valid_result"])))
               for lane, rows in outcomes.items()}
    def difference(left, right):
        a, b = metrics[left], metrics[right]
        return {"selected_difference": a["selected"] - b["selected"], "valid_difference": a["valid"] - b["valid"],
                "top3_hit_difference": a["top3_hits"] - b["top3_hits"],
                "top3_rate_difference": a["top3_rate"] - b["top3_rate"] if a["valid"] and b["valid"] else None,
                "place_hit_difference": a["place_hits_confirmed"] - b["place_hits_confirmed"] if a["place_unknown"] == b["place_unknown"] == 0 else None,
                "place_rate_difference": a["place_rate_all_nonrefund_exact"] - b["place_rate_all_nonrefund_exact"]
                    if a["place_rate_all_nonrefund_exact"] is not None and b["place_rate_all_nonrefund_exact"] is not None else None}
    report = {"date": date, "status": "COMPLETE", "role": ROLE, "test_only": pre["test_only"],
              "evidence_credit": 0, "b1_adoption_evidence_credit": 0, "candidate": pre["candidate"],
              "pre_selection_sha256": sha(folder(root, "daily_pre", date) / "selection.json"),
              "pre_freeze_sha256": sha(folder(root, "daily_pre", date) / "freeze_manifest.json"),
              "result_sources_sha256": hashes, "post_code_sha256": sha(Path(__file__)),
              "human_final_result_confirmed": True, "post_timestamp_utc": now().isoformat(),
              "candidate_reloaded_in_post": False, "predictions_recomputed_in_post": False,
              "metrics": metrics, "outcomes": outcomes,
              "comparisons": {lane + "_minus_" + other: difference(lane, other)
                              for lane in LANES for other in COMPARATORS + (LANES[0],) if lane != other}}
    unchanged(hashes)
    verify_pre(date, root=root)
    out.mkdir(parents=True, exist_ok=False)
    with (out / "post_summary.json").open("xb") as stream:
        stream.write(canonical(report))
    with (out / "complete.json").open("xb") as stream:
        stream.write(canonical({"date": date, "post_sha256": sha(out / "post_summary.json")}))
    verify_post(date, root=root)
    return {"status": "COMPLETE", "path": str(out / "post_summary.json"), "sha256": sha(out / "post_summary.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("freeze-pre", "post", "verify-pre", "verify-post"))
    parser.add_argument("--date", required=True)
    parser.add_argument("--human-final-result-confirmed", action="store_true")
    args = parser.parse_args()
    try:
        if args.step == "freeze-pre":
            require(not args.human_final_result_confirmed, "STOP_POST_ONLY_ARGUMENT")
            result = freeze_pre(args.date)
        elif args.step == "post":
            result = post(args.date, human_final_result_confirmed=args.human_final_result_confirmed)
        else:
            checked = verify_pre(args.date) if args.step == "verify-pre" else verify_post(args.date)
            result = {"date": args.date, "status": "VERIFIED", "candidate": checked["candidate"]}
        print(json.dumps(result, ensure_ascii=False))
    except (Stop, b1.Stop, ValueError, KeyError, OSError) as error:
        print(json.dumps({"status": "STOP", "reason": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
