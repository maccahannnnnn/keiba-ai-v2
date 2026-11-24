"""Date-parameterized formal POST coordinator; never predicts or refits.

`--check` is read-only. `--execute` is intentionally gated by explicit Human
Result finality and post-review approval. Candidate POST calculations remain in
their frozen lane runners; this module only validates and coordinates them.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from review.candidate_generation_training_dataset_readiness_v1 import result_rows
from review.formal_post_backfill_20261031_20261101 import (
    ROOT, E1, ANEW, canonical, joined, load, metrics, sha, stamp,
)
from review.pl_jockey_decision_addendum_v1 import ordinary_rate, rule_a_hits
from review.pl_jockey_step1_operations_v1 import (
    advance_state, credit_class, eligible_races_from_pre, normalize_date,
)
from review.target_daily_result_list_schema_v2_validator import validate_source_pair

LANES = ("CURRENT", "EXP024", "CURRENT_RANK1", "PL_JOCKEY", "A_NEW", "E1", "INDEPENDENT_V5")
RESULT_ROOT = ROOT / "data/raw/target/daily_result_list"
OUT = ROOT / "reports/formal_post_daily_v1"
STATE_ROOT = ROOT / "reports/pl_jockey_decision_addendum_v1/formal_state"
FORWARD_ROLE = "FORMAL_POST_FORWARD_PROSPECTIVE"
FORWARD_PROTOCOLS = {
    "PL_JOCKEY": ROOT / "docs/KeibaAI_FROZEN_PL_V1_JOCKEY_OFFSET_PROVISIONAL_PROTOCOL_V1.md",
    "CURRENT_RANK1": ROOT / "docs/KeibaAI_CURRENT_UNCONVERGED_RANK1_PROSPECTIVE_SHADOW_V1_PROTOCOL.md",
}


class Stop(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise Stop(code)


def read_json(path: Path) -> dict:
    require(path.is_file(), "STOP_SOURCE_MISSING:" + str(path))
    return load(path)


def validated_pre(date: str) -> dict:
    """Generalize the old backfill's SHA/time/cross-PRE validation, not its counts."""
    specs = {
        "CURRENT": (ROOT / f"reports/prospective_prediction_{date}_formal_trace_v1/prediction_manifest.json",
                    ROOT / f"reports/prospective_prediction_{date}_formal_trace_v1/formal_freeze_attestation.json",
                    "prediction_manifest_sha256", "freeze_timestamp_utc", "result_access_count"),
        "EXP024": (ROOT / f"reports/exp024_pl_same_volume/{date}_pre/selection.json",
                   ROOT / f"reports/exp024_pl_same_volume/{date}_pre/selection_freeze.json",
                   "selection_sha256", "selection_freeze_timestamp", "result_access_before_freeze"),
        "PL_JOCKEY": (ROOT / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{date}_pre/selection.json",
                      ROOT / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{date}_pre/provisional_audit.json",
                      "selection_sha256", "freeze_timestamp", "result_access_count"),
        "CURRENT_RANK1": (ROOT / f"reports/current_rank1_prospective_shadow_v2/{date}_pre/pre_selection.json",
                          ROOT / f"reports/current_rank1_prospective_shadow_v2/{date}_pre/freeze_manifest.json",
                          "selection_sha256", "freeze_timestamp_jst", "result_access"),
    }
    values = {}
    for lane, (path, freeze_path, digest_key, time_key, result_key) in specs.items():
        frozen = read_json(freeze_path)
        read_json(path)
        require(frozen.get(digest_key) == sha(path), f"STOP_PRE_FREEZE_AUTHORITY:{lane}")
        require(frozen.get(result_key) in (0, False), f"STOP_PRE_RESULT_ACCESS:{lane}")
        first = frozen.get("first_start_at") or frozen.get("first_race_timestamp")
        require(first is not None and stamp(frozen[time_key]) < stamp(first), f"STOP_PRE_FREEZE_TIMING:{lane}")
        require(frozen.get("date", frozen.get("target_date", date)) == date, f"STOP_PRE_DATE:{lane}")
        values[lane] = {"path": str(path), "sha256": sha(path), "freeze_path": str(freeze_path),
                        "freeze_sha256": sha(freeze_path), "freeze_timestamp": frozen[time_key]}
    current = read_json(specs["CURRENT"][1])
    exp = read_json(specs["EXP024"][1])
    plj = read_json(specs["PL_JOCKEY"][1])
    rank = read_json(specs["CURRENT_RANK1"][1])
    require(current["prediction_manifest_sha256"] == values["CURRENT"]["sha256"] and
            exp["selection_sha256"] == values["EXP024"]["sha256"] and
            plj["current_pre_sha256"] == values["CURRENT"]["sha256"] and
            rank["current_manifest_sha256"] == values["CURRENT"]["sha256"] and
            rank["exp024_freeze_sha256"] == values["EXP024"]["freeze_sha256"], "STOP_CROSS_PRE_AUTHORITY")
    plj_selection = read_json(specs["PL_JOCKEY"][0])
    rank_selection = read_json(specs["CURRENT_RANK1"][0])
    exp_selection = read_json(specs["EXP024"][0])
    require(plj_selection["date"] == rank_selection["target_date"] == exp_selection["date"] == date,
            "STOP_PRE_SELECTION_DATE")
    require(plj_selection["result_access_count"] == rank_selection["result_access_count"] == 0 and
            exp_selection["protocol_sha256"] == exp["protocol_sha256"],
            "STOP_PRE_SELECTION_RESULT_OR_PROTOCOL")
    counts = {"PL_JOCKEY": sum(len(r["candidate_selected_horses"]) for r in plj_selection["races"]),
              "CURRENT_RANK1": len(rank_selection["selections"]),
              "EXP024": sum(len(r["treatment_selected_horses"]) for r in exp_selection["races"])}
    require(counts["PL_JOCKEY"] == plj_selection["candidate_selected_horse_count"] and
            counts["CURRENT_RANK1"] == len(rank["selected_horses"]), "STOP_PRE_SELECTION_COUNT")
    for lane, count in counts.items():
        values[lane]["selection_count"] = count
    return values


def result_sources(date: str) -> tuple[dict, dict]:
    primary = RESULT_ROOT / f"馬番順着順_{date}.csv"
    auxiliary = RESULT_ROOT / f"着順馬番_{date}.csv"
    require(primary.is_file() and auxiliary.is_file(), "STOP_RESULT_PAIR_MISSING")
    require(validate_source_pair(primary, auxiliary, date)["status"] == "PASS", "STOP_RESULT_PAIR_INVALID")
    sources = result_rows(date)
    digests = {"horse_order": sha(primary), "finish_order": sha(auxiliary)}
    return sources, digests


def preflight(date: str) -> dict:
    require(bool(re.fullmatch(r"20\d{6}", date)), "STOP_INVALID_DATE")
    pre = validated_pre(date)
    sources, result_sha = result_sources(date)
    e1_authority = e1_result_authority()
    e1_result = prepare_e1_result_pair(date, result_sha, e1_authority, copy_missing=False)
    index = read_json(ROOT / f"reports/prospective_prediction_{date}_formal_trace_v1/race_index.json")["race_index"]
    current_root = ROOT / f"reports/prospective_prediction_{date}_formal_trace_v1"
    manifest = read_json(current_root / "prediction_manifest.json")
    for item in manifest["files"]:
        require(sha(current_root / item["relative_path"]) == item["sha256"],
                "STOP_CURRENT_PREDICTION_MANIFEST_DRIFT")
    from review.candidate_generation_training_dataset_readiness_v1 import JAPANESE_VENUE, outcome, parse_race_id
    require(len({r["race_id"] for r in index}) == len(index), "STOP_DUPLICATE_PRE_RACE")
    for race in index:
        d, venue, number = parse_race_id(race["race_id"])
        require(d == date and (JAPANESE_VENUE[venue], number) in sources, "STOP_RESULT_RACE_MISSING")
        require(int(sources[JAPANESE_VENUE[venue], number][9]) == race["horse_count"], "STOP_RESULT_HEADCOUNT")
        for horse_number in range(1, int(race["horse_count"]) + 1):
            outcome(sources[JAPANESE_VENUE[venue], number], horse_number)
    require({r["race_id"] for r in index} ==
            {r["race_id"] for r in read_json(Path(pre["PL_JOCKEY"]["path"]))["races"]},
            "STOP_PRE_RACE_SET")
    race_set = {r["race_id"] for r in index}
    require({r["race_id"] for r in read_json(Path(pre["EXP024"]["path"]))["races"]} == race_set,
            "STOP_EXP024_RACE_SET")
    for lane, root, stamp_key, result_key, first_key in (
        ("A_NEW", ANEW / f"reports/a_new_prospective_shadow_v1/daily_pre/{date}",
         "freeze_timestamp_utc", "result_access_count_at_freeze", "first_race_timestamp"),
        ("E1", E1 / f"reports/e1_full_field_allocation_prospective_shadow_v1/daily_pre/{date}",
         "e1_freeze_timestamp", "result_access_count", "first_race_timestamp"),
    ):
        freeze = read_json(root / "freeze_manifest.json")
        selected = root / "selection.json"
        require(freeze["date"] == date and sha(selected) == freeze["selection_sha256"] and
                freeze[result_key] == 0 and stamp(freeze[stamp_key]) < stamp(freeze[first_key]),
                "STOP_CANDIDATE_PRE_AUTHORITY:" + lane)
        selection = read_json(selected)
        require(selection["date"] == date and
                selection["current_pre_sha256" if lane == "A_NEW" else "current_formal_pre_sha256"] ==
                pre["CURRENT"]["sha256"], "STOP_CANDIDATE_CURRENT_AUTHORITY:" + lane)
        if lane == "E1":
            require(selection["exp024_sealed_selection_sha256"] == pre["EXP024"]["sha256"],
                    "STOP_E1_EXP024_PRE_AUTHORITY")
        actual_races = ({r["race_id"] for r in selection["races"]} if lane == "A_NEW"
                        else set(selection["eligible_races"]))
        require(actual_races == race_set, "STOP_CANDIDATE_RACE_SET:" + lane)
        pre[lane] = {"path": str(selected), "sha256": sha(selected),
                     "freeze_path": str(root / "freeze_manifest.json"),
                     "freeze_sha256": sha(root / "freeze_manifest.json")}
    independent_root = ROOT / f"reports/independent_race_selection_prospective/{date}_pre"
    independent_index = read_json(independent_root / "artifact_hashes.json")["indexed_artifacts"]
    for relative, expected in independent_index.items():
        require(sha(independent_root / relative) == expected, "STOP_INDEPENDENT_PRE_HASH")
    independent = read_json(independent_root / "selection_manifest.json")
    require(independent["date"] == date and independent["result_data_access_count"] == 0 and
            independent["source_prediction_manifest_sha256"] == pre["CURRENT"]["sha256"],
            "STOP_INDEPENDENT_PRE_AUTHORITY")
    pre["INDEPENDENT_V5"] = {"path": str(independent_root / "selection_manifest.json"),
                             "sha256": sha(independent_root / "selection_manifest.json"),
                             "freeze_path": str(independent_root / "artifact_hashes.json"),
                             "freeze_sha256": sha(independent_root / "artifact_hashes.json")}
    for script in (ROOT / "review/pl_same_volume_reselection_shadow_v1.py",
                   ROOT / "review/independent_race_selection_prospective_post.py",
                   ANEW / "review/a_new_prospective_evidence_v1.py",
                   E1 / "review/e1_full_field_allocation_evidence_v1.py"):
        require(script.is_file(), "STOP_LANE_RUNNER_MISSING:" + str(script))
    # Existing backfill join semantics validate all PL+J / Rank1 selected keys.
    joined(date, "PL_JOCKEY", pre, sources)
    joined(date, "CURRENT_RANK1", pre, sources)
    return {"date": date, "pre": pre, "result_sha256": result_sha,
            "result_race_count": len(sources), "eligible_races": len(index),
            "eligible_horses": sum(r["horse_count"] for r in index),
            "e1_result_authority": e1_authority, "e1_result_preparation": e1_result}


def e1_result_authority(e1_root: Path = E1) -> dict:
    """Ask the real E1 import graph where its result_rows function reads."""
    script = e1_root / "review/e1_full_field_allocation_evidence_v1.py"
    require(script.is_file(), "STOP_E1_RUNNER_MISSING")
    probe = (
        "import json,sys; from pathlib import Path; "
        "sys.path.insert(0,sys.argv[1]); "
        "import review.e1_full_field_allocation_evidence_v1 as m; "
        "f=m.result_rows; "
        "print(json.dumps({'loader_file':f.__code__.co_filename,"
        "'loader_root':str(f.__globals__['ROOT']),'main_declared':str(m.MAIN)}))"
    )
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    child = subprocess.run([sys.executable, "-c", probe, str(e1_root)], cwd=e1_root,
                           env=env, capture_output=True, text=True)
    require(child.returncode == 0, "STOP_E1_IMPORT_PROBE_FAILED:" + child.stderr[-500:])
    try:
        data = json.loads(child.stdout.strip())
        loader_root = Path(data["loader_root"]).resolve()
        loader_file = Path(data["loader_file"]).resolve()
        require(loader_file == (loader_root / "review/candidate_generation_training_dataset_readiness_v1.py").resolve(),
                "STOP_E1_LOADER_FILE_UNEXPECTED")
        require(loader_root == e1_root.resolve(), "STOP_E1_LOADER_ROOT_UNEXPECTED")
        require(Path(data["main_declared"]).resolve() == ROOT.resolve(), "STOP_E1_MAIN_DECLARATION_DRIFT")
    except (KeyError, ValueError, json.JSONDecodeError) as error:
        raise Stop("STOP_E1_IMPORT_PROBE_SCHEMA") from error
    return {"actual_loader_file": str(loader_file), "actual_loader_root": str(loader_root),
            "main_declared": data["main_declared"],
            "actual_result_root": str(loader_root / "data/raw/target/daily_result_list")}


def prepare_e1_result_pair(date: str, expected: dict, authority: dict, *, copy_missing: bool) -> dict:
    destination = Path(authority["actual_result_root"])
    paths = {kind: (RESULT_ROOT / f"{prefix}_{date}.csv", destination / f"{prefix}_{date}.csv")
             for kind, prefix in (("horse_order", "馬番順着順"), ("finish_order", "着順馬番"))}
    # Validate every existing destination before copying either file.
    for kind, (source, target) in paths.items():
        require(source.is_file() and sha(source) == expected[kind], "STOP_MAIN_RESULT_SHA:" + kind)
        if target.exists():
            require(sha(target) == expected[kind], "STOP_E1_EXISTING_RESULT_SHA:" + kind)
    missing = [kind for kind, (_, target) in paths.items() if not target.exists()]
    if missing and copy_missing:
        destination.mkdir(parents=True, exist_ok=True)
        for kind in missing:
            source, target = paths[kind]
            with source.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
            require(sha(target) == expected[kind], "STOP_E1_COPIED_RESULT_SHA:" + kind)
    status = "COPY_REQUIRED" if missing and not copy_missing else ("COPIED" if missing else "REUSED_MATCHING")
    return {"status": status, "actual_loader_file": authority["actual_loader_file"],
            "actual_result_root": str(destination),
            "sources": {kind: {"source": str(source), "destination": str(target),
                               "sha256": expected[kind], "present": target.is_file()}
                        for kind, (source, target) in paths.items()},
            "checked_at_utc": datetime.now(timezone.utc).isoformat()}


def verify_e1_result_content(date: str, expected: dict, authority: dict) -> None:
    target = Path(authority["actual_result_root"])
    for kind, prefix in (("horse_order", "馬番順着順"), ("finish_order", "着順馬番")):
        source = RESULT_ROOT / f"{prefix}_{date}.csv"
        copied = target / source.name
        require(copied.is_file() and sha(copied) == sha(source) == expected[kind],
                "STOP_E1_RESULT_CONTENT_SHA:" + kind)
        with source.open(encoding="cp932", newline="") as a, copied.open(encoding="cp932", newline="") as b:
            require(list(csv.reader(a)) == list(csv.reader(b)), "STOP_E1_RESULT_ROWS:" + kind)
    validate_source_pair(target / f"馬番順着順_{date}.csv", target / f"着順馬番_{date}.csv", date)


def verified_day(date: str, pre: dict, plj_rows: list[dict], current_rows: list[dict],
                 result_sha: dict, *, parent_suspended: bool) -> dict:
    selection = read_json(Path(pre["PL_JOCKEY"]["path"]))
    index = read_json(ROOT / f"reports/prospective_prediction_{date}_formal_trace_v1/race_index.json")["race_index"]
    current_counts = {row["race_id"]: row["buy_count"] for row in index}
    races, slots = eligible_races_from_pre(selection["races"], current_counts)
    require(len(plj_rows) == len(current_rows) == slots, "STOP_ADDENDUM_SLOT_IDENTITY")
    plj_metric = ordinary_rate(plj_rows)
    current_metric = ordinary_rate(current_rows)
    return {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "role": "PROSPECTIVE_ELIGIBLE",
            "pre_frozen_before_result": True, "result_join_verified": True,
            "pre_races": selection["races"], "current_buy_counts": current_counts,
            "eligible_races": races, "plj_slots": slots, "current_slots": slots,
            "plj_valid_n": plj_metric["valid"], "plj_valid_hits": plj_metric["hits"],
            "current_valid_n": current_metric["valid"], "current_valid_hits": current_metric["hits"],
            "plj_rule_a_hits": rule_a_hits(plj_rows), "current_rule_a_hits": rule_a_hits(current_rows),
            "delta_hits": rule_a_hits(plj_rows) - rule_a_hits(current_rows),
            "result_source_sha256": result_sha, "parent_suspended": parent_suspended,
            "evidence_role": "PL_JOCKEY_DECISION_ADDENDUM_NEW_GATE"}


def forward_post_payload(date: str, lane: str, audit: dict, rows: list[dict]) -> dict:
    require(lane in FORWARD_PROTOCOLS, "STOP_UNSUPPORTED_FORWARD_POST_LANE")
    protocol = FORWARD_PROTOCOLS[lane]
    require(protocol.is_file(), "STOP_FORWARD_PROTOCOL_MISSING:" + lane)
    pre = audit["pre"][lane]
    sources, result_sha = result_sources(date)
    require(result_sha == audit["result_sha256"], "STOP_RESULT_CHANGED_DURING_EXECUTION")
    independently_joined = joined(date, lane, audit["pre"], sources)
    require(rows == independently_joined, "STOP_FORWARD_POST_CROSSCHECK:" + lane)
    result = {"date": date, "lane": lane, "role": FORWARD_ROLE,
              "post_kind": "FORWARD", "evidence_authority": {"path": str(protocol), "sha256": sha(protocol)},
              "pre_selection_path": pre["path"], "pre_selection_sha256": pre["sha256"],
              "pre_freeze_path": pre["freeze_path"], "pre_freeze_sha256": pre["freeze_sha256"],
              "pre_freeze_timestamp": pre["freeze_timestamp"], "result_source_sha256": result_sha,
              "metrics": metrics(rows), "selected_horse_outcomes": rows,
              "crosscheck_status": "PASS", "pre_selection_changed": False}
    if lane == "PL_JOCKEY":
        result["addendum_credit_class"] = credit_class(
            date, "PROSPECTIVE_ELIGIBLE", pre_frozen_before_result=True)
    return result


def write_forward_post(date: str, lane: str, audit: dict, rows: list[dict], path: Path) -> str:
    expected = forward_post_payload(date, lane, audit, rows)
    if path.exists():
        actual = read_json(path)
        for key, value in expected.items():
            require(actual.get(key) == value, "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":" + key)
        require(actual.get("execution_timestamp_utc") is not None,
                "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":timestamp")
        return "REUSED_VERIFIED"
    require(not path.parent.exists(), "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":partial_folder")
    expected["execution_timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=False)
    with path.open("xb") as stream:
        stream.write(canonical(expected))
    return "CREATED"


def run_existing(script: Path, *args: str) -> None:
    require(script.is_file(), "STOP_LANE_RUNNER_MISSING:" + str(script))
    subprocess.run([sys.executable, str(script), *args], cwd=script.parent.parent, check=True)


def current_rows_from_exp024(post: dict, plj_selection: dict) -> list[dict]:
    """Consume EXP-024's already joined Current arm, retaining horse identity."""
    required = {(r["race_id"], int(n)) for r in plj_selection["races"]
                for n in r["current_selected_horses"]}
    rows = []
    for race in post["races"]:
        trace = race["race_trace"]
        by_no = {int(h["horse_number"]): h["horse_name"] for h in trace["horses"]}
        for number in trace["current_selected_horses"]:
            number = int(number)
            outcome = race["results"][str(number)]
            rows.append({"race_id": race["race_id"], "horse_number": number,
                         "horse_name": by_no[number], "valid_result": bool(outcome["valid_result"]),
                         "finish": outcome["actual_finish"],
                         "actual_top3": bool(outcome["actual_top3"])})
    require(len(rows) == len(required) and
            {(r["race_id"], r["horse_number"]) for r in rows} == required,
            "STOP_CURRENT_EXP024_PLJ_IDENTITY")
    return sorted(rows, key=lambda r: (r["race_id"], r["horse_number"]))


def selected_rows_from_post(lane: str, post: dict, selection: dict | None = None) -> list[dict]:
    """Project existing lane POST horse outcomes into a common display schema."""
    rows = []
    if lane == "EXP024":
        for race in post["races"]:
            names = {int(h["horse_number"]): h["horse_name"] for h in race["race_trace"]["horses"]}
            for number in race["race_trace"]["treatment_selected_horses"]:
                number = int(number)
                result = race["results"][str(number)]
                rows.append({"race_id": race["race_id"], "horse_number": number, "horse_name": names[number],
                             "finish": result["actual_finish"], "valid_result": result["valid_result"],
                             "actual_top3": bool(result["actual_top3"]) if result["valid_result"] else False})
    elif lane in ("A_NEW", "E1"):
        require(selection is not None, "STOP_SELECTION_REQUIRED")
        if lane == "A_NEW":
            names = {(race["race_id"], int(h["horse_number"])): h["horse_name"]
                     for race in selection["races"] for h in race["horses"]}
            flag = "a_new_selected"
        else:
            names = {(h["race_id"], int(h["horse_number"])): h["horse_name"]
                     for h in selection["selected_horses"]}
            flag = "e1_selected"
        for race in post["races"]:
            for item in race["selected_outcomes"]:
                if item[flag]:
                    number = int(item["horse_number"])
                    rows.append({"race_id": race["race_id"], "horse_number": number,
                                 "horse_name": names[(race["race_id"], number)],
                                 "finish": item["finish"], "valid_result": item["valid_result"],
                                 "actual_top3": bool(item["actual_top3"]) if item["valid_result"] else False})
    elif lane == "INDEPENDENT_V5":
        require(selection is not None, "STOP_SELECTION_REQUIRED")
        names = {(race["race_id"], int(h["horse_number"])): h["horse_name"]
                 for race in selection["races"] for h in race["selected_horses"]}
        for item in post["result_rows"]["independent"]:
            number = int(item["horse_number"])
            rows.append({"race_id": item["race_id"], "horse_number": number,
                         "horse_name": names[(item["race_id"], number)],
                         "finish": item["actual_finish"], "valid_result": item["valid_result"],
                         "actual_top3": bool(item["actual_top3"]) if item["valid_result"] else False})
    else:
        raise Stop("STOP_UNSUPPORTED_POST_PROJECTION:" + lane)
    require(len({(r["race_id"], r["horse_number"]) for r in rows}) == len(rows),
            "STOP_DUPLICATE_SELECTED_POST:" + lane)
    require(all(r["valid_result"] or not r["actual_top3"] for r in rows),
            "STOP_INVALID_RESULT_TOP3:" + lane)
    return sorted(rows, key=lambda r: (r["race_id"], r["horse_number"]))


def lane_report(rows: list[dict], authority_metric: dict) -> dict:
    own = metrics(rows)
    for key, expected in (("selected", authority_metric.get("selected", authority_metric.get("natural_n"))),
                          ("valid", authority_metric.get("valid", authority_metric.get("valid_n"))),
                          ("hits", authority_metric["hits"])):
        require(own[key] == expected, "STOP_LANE_POST_METRIC_MISMATCH:" + key)
    return {**own, "win_count": sum(r["valid_result"] and r["finish"] == 1 for r in rows),
            "selected_races": len({r["race_id"] for r in rows})}


def write_or_verify(path: Path, payload: object) -> None:
    data = canonical(payload)
    if path.exists():
        require(path.read_bytes() == data, "STOP_RESUME_ARTIFACT_MISMATCH:" + str(path))
        return
    with path.open("xb") as stream:
        stream.write(data)


def verify_completed(folder: Path, audit: dict) -> dict:
    manifest = read_json(folder / "complete.json")
    require(manifest["date"] == audit["date"] and
            manifest["result_sha256"] == audit["result_sha256"], "STOP_EXISTING_POST_INPUT_CONFLICT")
    for lane, item in manifest["lane_artifacts"].items():
        require(lane in LANES and sha(Path(item["path"])) == item["sha256"],
                "STOP_EXISTING_POST_ARTIFACT_CONFLICT:" + lane)
    require(set(manifest["lane_artifacts"]) == set(LANES) - {"CURRENT"},
            "STOP_EXISTING_POST_LANE_SET")
    for lane, item in audit["pre"].items():
        require(manifest["pre_sha256"][lane] == item["sha256"],
                "STOP_EXISTING_POST_PRE_CONFLICT:" + lane)
    require(sha(Path(manifest["addendum_next_state_path"])) == manifest["addendum_next_state_sha256"] and
            sha(Path(manifest["addendum_verified_day_path"])) == manifest["addendum_verified_day_sha256"] and
            sha(folder / "selected_horse_outcomes.json") == manifest["selected_horse_outcomes_sha256"] and
            sha(folder / "lane_summary.json") == manifest["lane_summary_sha256"],
            "STOP_EXISTING_ADDENDUM_CONFLICT")
    b1 = manifest.get("b1_diagnostic")
    if isinstance(b1, dict) and b1.get("status") == "COMPLETE":
        require(sha(Path(b1["path"])) == b1["sha256"], "STOP_EXISTING_B1_DIAGNOSTIC_CONFLICT")
    sources, result_sha = result_sources(audit["date"])
    require(result_sha == audit["result_sha256"], "STOP_EXISTING_POST_RESULT_CHANGED")
    for lane, path in lane_post_paths(audit["date"]).items():
        require(str(path) == manifest["lane_artifacts"][lane]["path"],
                "STOP_EXISTING_POST_LANE_PATH:" + lane)
        verify_lane_post(lane, audit["date"], path, audit, sources)
    return {"status": "ALREADY_COMPLETE_UNCHANGED", "manifest_sha256": sha(folder / "complete.json")}


def state_chain_preflight(state_root: Path, date: str, *, allow_existing: bool = False) -> tuple[Path | None, Path]:
    """Validate the immutable event chain, including SUSPEND and terminal dates."""
    require(state_root.resolve() == STATE_ROOT.resolve(), "STOP_ADDENDUM_STATE_ROOT_AUTHORITY")
    paths = sorted(state_root.glob("*_state.json")) if state_root.is_dir() else []
    events = sorted(list(state_root.glob("*_verified_day.json")) + list(state_root.glob("*_not_eligible.json"))) if state_root.is_dir() else []
    require({p.name[:8] for p in events} == {p.name[:8] for p in paths} and len(events) == len(paths),
            "STOP_ADDENDUM_ORPHAN_OR_BRANCH")
    previous = None
    dates = []
    for path in paths:
        require(bool(re.fullmatch(r"20\d{6}_state\.json", path.name)), "STOP_ADDENDUM_STATE_NAME")
        current = path.name[:8]
        recorded = read_json(path)
        require(recorded.get("event_date") == current, "STOP_ADDENDUM_STATE_DATE")
        require(recorded.get("previous_state_sha256") == (sha(previous) if previous else None),
                "STOP_ADDENDUM_PARENT_SHA")
        require(not dates or current > dates[-1], "STOP_ADDENDUM_BRANCH_OR_REORDER")
        kind = recorded.get("event_kind")
        event_path = state_root / f"{current}_{'verified_day' if kind == 'VERIFIED_DAY' else 'not_eligible'}.json"
        require(kind in ("VERIFIED_DAY", "NOT_ELIGIBLE") and event_path.is_file(),
                "STOP_ADDENDUM_EVENT_MISSING")
        digest_key = "verified_day_sha256" if kind == "VERIFIED_DAY" else "not_eligible_sha256"
        require(recorded.get(digest_key) == sha(event_path), "STOP_ADDENDUM_EVENT_SHA")
        event = read_json(event_path)
        require(normalize_date(event["date"]) == normalize_date(current), "STOP_ADDENDUM_EVENT_DATE")
        if kind == "NOT_ELIGIBLE":
            authority_path = Path(event.get("authority_path", ""))
            require(event.get("role") == "NOT_ELIGIBLE" and event.get("reason") and
                    authority_path.is_file() and sha(authority_path) == event.get("authority_sha256"),
                    "STOP_NOT_ELIGIBLE_AUTHORITY_MISSING")
        previous_days = read_json(previous).get("formal_days", []) if previous else []
        current_days = recorded.get("formal_days", [])
        require(current_days[:len(previous_days)] == previous_days and
                len(current_days) <= len(previous_days) + 1, "STOP_ADDENDUM_STATE_BRANCH")
        if len(current_days) > len(previous_days):
            require(kind == "VERIFIED_DAY" and current_days[-1]["date"] == normalize_date(current),
                    "STOP_ADDENDUM_DOUBLE_COUNT")
        dates.append(current)
        previous = path
    if date in dates:
        require(allow_existing and date == dates[-1], "STOP_DUPLICATE_OR_OUT_OF_ORDER_ADDENDUM_DATE")
        return paths[-2] if len(paths) > 1 else None, paths[-1]
    require(not dates or date > dates[-1], "STOP_DUPLICATE_OR_OUT_OF_ORDER_ADDENDUM_DATE")
    if date == "20261107":
        require(not dates, "STOP_1107_MUST_BE_FIRST_ADDENDUM_STATE")
    start = dates[-1] if dates else "20261103"
    pre_root = ROOT / "reports/frozen_pl_v1_jockey_offset_provisional_v1"
    for path in pre_root.glob("*_pre/selection.json"):
        intervening = path.parent.name[:8]
        if start < intervening < date and credit_class(intervening, "PROSPECTIVE_ELIGIBLE",
                                                       pre_frozen_before_result=True) == "FORMAL_NEW_GATE_ELIGIBLE":
            raise Stop("STOP_SKIPPED_ELIGIBLE_ADDENDUM_DATE:" + intervening)
    return previous, state_root / f"{date}_state.json"


def write_state_event(date: str, state_root: Path, previous: Path | None, day: dict,
                      *, not_eligible: dict | None = None) -> tuple[Path, Path]:
    """Append a verified or formally justified non-eligible event, never infer one."""
    require(state_root.resolve() == STATE_ROOT.resolve(), "STOP_ADDENDUM_STATE_ROOT_AUTHORITY")
    kind = "NOT_ELIGIBLE" if not_eligible is not None else "VERIFIED_DAY"
    event = not_eligible if not_eligible is not None else day
    if kind == "NOT_ELIGIBLE":
        require(event.get("authority_path") and event.get("authority_sha256") and
                sha(Path(event["authority_path"])) == event["authority_sha256"] and event.get("reason") and
                event.get("role") == "NOT_ELIGIBLE" and event.get("pre_frozen_before_result") is False,
                "STOP_NOT_ELIGIBLE_AUTHORITY_MISSING")
    require(normalize_date(event["date"]) == normalize_date(date), "STOP_ADDENDUM_EVENT_DATE")
    event_path = state_root / f"{date}_{'not_eligible' if not_eligible is not None else 'verified_day'}.json"
    state_path = state_root / f"{date}_state.json"
    require(not event_path.exists() and not state_path.exists(), "STOP_DUPLICATE_ADDENDUM_EVENT")
    prior = read_json(previous) if previous else {}
    next_state = advance_state(prior, event)
    next_state["event_date"] = date
    next_state["event_kind"] = kind
    next_state["previous_state_sha256"] = sha(previous) if previous else None
    next_state["verified_day_sha256" if kind == "VERIFIED_DAY" else "not_eligible_sha256"] = hashlib.sha256(canonical(event)).hexdigest()
    state_root.mkdir(parents=True, exist_ok=True)
    with event_path.open("xb") as stream:
        stream.write(canonical(event))
    with state_path.open("xb") as stream:
        stream.write(canonical(next_state))
    return event_path, state_path


STATE_CHAIN_FIELDS = frozenset({"event_date", "event_kind", "previous_state_sha256",
                                "verified_day_sha256", "not_eligible_sha256"})


def verify_existing_state(date: str, previous_state: Path | None, verified_path: Path,
                          next_state: Path, day: dict) -> None:
    """Recompute evaluation values; verify each provenance field independently."""
    require(verified_path.is_file() and verified_path.read_bytes() == canonical(day),
            "STOP_RESUME_ARTIFACT_MISMATCH:addendum_day")
    previous = read_json(previous_state) if previous_state else {}
    expected_evaluation = advance_state(previous, day)
    actual = read_json(next_state)
    evaluation = {key: value for key, value in actual.items() if key not in STATE_CHAIN_FIELDS}
    recomputed = {key: value for key, value in expected_evaluation.items()
                  if key not in STATE_CHAIN_FIELDS}
    require(evaluation == recomputed, "STOP_RESUME_ARTIFACT_MISMATCH:addendum_evaluation")
    expected_chain = {"event_date": date, "event_kind": "VERIFIED_DAY",
                      "previous_state_sha256": sha(previous_state) if previous_state else None,
                      "verified_day_sha256": sha(verified_path)}
    if "not_eligible_sha256" in previous:
        expected_chain["not_eligible_sha256"] = previous["not_eligible_sha256"]
    actual_chain = {key: value for key, value in actual.items() if key in STATE_CHAIN_FIELDS}
    for key in STATE_CHAIN_FIELDS:
        require((key in actual_chain) == (key in expected_chain) and
                (key not in expected_chain or actual_chain[key] == expected_chain[key]),
                "STOP_RESUME_ARTIFACT_MISMATCH:addendum_chain:" + key)


def lane_post_paths(date: str) -> dict[str, Path]:
    return {
        "EXP024": ROOT / f"reports/exp024_pl_same_volume/{date}_post/post.json",
        "PL_JOCKEY": ROOT / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{date}_post/post.json",
        "CURRENT_RANK1": ROOT / f"reports/current_rank1_prospective_shadow_v2/{date}_post/post.json",
        "A_NEW": ANEW / f"reports/a_new_prospective_shadow_v1/daily_post/{date}/post.json",
        "E1": E1 / f"reports/e1_full_field_allocation_prospective_shadow_v1/daily_post/{date}/post.json",
        "INDEPENDENT_V5": ROOT / f"reports/independent_race_selection_prospective/{date}_post/summary.json",
    }


def _pre_selected_keys(lane: str, selection: dict) -> set[tuple[str, int]]:
    if lane == "EXP024":
        return {(r["race_id"], int(n)) for r in selection["races"]
                for n in r["treatment_selected_horses"]}
    if lane == "A_NEW":
        return {(r["race_id"], int(n)) for r in selection["races"]
                for n in r["a_new_selected_horses"]}
    if lane == "E1":
        return {(h["race_id"], int(h["horse_number"])) for h in selection["selected_horses"]}
    if lane == "INDEPENDENT_V5":
        return {(r["race_id"], int(h["horse_number"])) for r in selection["races"]
                for h in r["selected_horses"]}
    raise Stop("STOP_UNSUPPORTED_POST_SELECTION:" + lane)


def _verify_candidate_chain(lane: str, date: str, path: Path) -> None:
    chain_path = path.parent / "chain.json"
    chain = read_json(chain_path)
    require(chain.get("date") == date and chain.get("post_sha256") == sha(path),
            "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":chain")
    prior = sorted(p for p in path.parent.parent.iterdir()
                   if p.is_dir() and p.name < date and (p / "chain.json").is_file())
    genesis = b"FROZEN_A_NEW_POST_CHAIN\n" if lane == "A_NEW" else b"E1_POST_CHAIN\n"
    parent = sha(prior[-1] / "chain.json") if prior else hashlib.sha256(genesis).hexdigest()
    require(chain.get("parent_sha256") == parent, "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":parent")


def verify_lane_post(lane: str, date: str, path: Path, audit: dict, sources: dict) -> dict:
    """Recompute identity and outcome from frozen PRE and main Result before reuse."""
    require(path.is_file(), "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":missing")
    post = read_json(path)
    pre = audit["pre"]
    result_sha = audit["result_sha256"]
    require(post.get("date") == date, "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":date")
    if lane in FORWARD_PROTOCOLS:
        rows = joined(date, lane, pre, sources)
        expected = forward_post_payload(date, lane, audit, rows)
        for key, value in expected.items():
            require(post.get(key) == value, "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":" + key)
        return post
    if lane == "EXP024":
        exp_selection = read_json(Path(pre[lane]["path"]))
        exp_freeze = read_json(Path(pre[lane]["freeze_path"]))
        require(post.get("role") == "PROSPECTIVE_OBSERVATION_ONLY" and
                post.get("selection_sha256") == pre[lane]["sha256"] and
                post.get("selection_freeze_timestamp") == exp_freeze["selection_freeze_timestamp"] and
                post.get("block_fingerprint_sha256") == exp_selection["current_environment"]["block_fingerprint_sha256"] and
                post.get("result_source_sha256") == {"primary": result_sha["horse_order"],
                                                     "auxiliary": result_sha["finish_order"]},
                "STOP_RESUME_ARTIFACT_MISMATCH:EXP024:authority")
        require({r["race_id"] for r in post["races"]} ==
                {r["race_id"] for r in exp_selection["races"] if r["current_buy_count"] > 0},
                "STOP_RESUME_ARTIFACT_MISMATCH:EXP024:race_set")
    elif lane in ("A_NEW", "E1"):
        require(post.get("result_source_sha256") == result_sha and
                post.get("pre_selection_sha256") == pre[lane]["sha256"] and
                post.get("pre_freeze_manifest_sha256" if lane == "A_NEW" else "pre_freeze_sha256") ==
                pre[lane]["freeze_sha256"],
                "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":authority")
        if lane == "A_NEW":
            require(post.get("role") == "PROSPECTIVE_SHADOW_EVIDENCE",
                    "STOP_RESUME_ARTIFACT_MISMATCH:A_NEW:role")
        else:
            require(post.get("evidence_date") is True,
                    "STOP_RESUME_ARTIFACT_MISMATCH:E1:evidence_role")
            allowed = ("PASS",) if date >= "20261107" else (
                "PASS", "NOT_APPLICABLE_COMPARATOR_SERVICE", "NOT_AVAILABLE")
            require(post.get("exp024_post_crosscheck", {}).get("status") in allowed,
                    "STOP_RESUME_ARTIFACT_MISMATCH:E1:crosscheck")
        _verify_candidate_chain(lane, date, path)
    elif lane == "INDEPENDENT_V5":
        require(post.get("date") == date, "STOP_RESUME_ARTIFACT_MISMATCH:INDEPENDENT_V5:date")
    else:
        raise Stop("STOP_UNSUPPORTED_LANE:" + lane)
    selection = read_json(Path(pre[lane]["path"]))
    if lane in ("A_NEW", "E1"):
        expected_races = ({r["race_id"] for r in selection["races"]} if lane == "A_NEW"
                          else set(selection["eligible_races"]))
        require({r["race_id"] for r in post["races"]} == expected_races,
                "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":race_set")
    rows = selected_rows_from_post(lane, post, selection)
    keys = {(r["race_id"], r["horse_number"]) for r in rows}
    require(len(rows) == len(keys) and keys == _pre_selected_keys(lane, selection),
            "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":selection")
    from review.candidate_generation_training_dataset_readiness_v1 import JAPANESE_VENUE, outcome, parse_race_id
    for row in rows:
        d, venue, number = parse_race_id(row["race_id"])
        require(d == date, "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":race")
        valid, finish, top3 = outcome(sources[JAPANESE_VENUE[venue], number], row["horse_number"])
        require((row["valid_result"], row["finish"], row["actual_top3"]) ==
                (valid, finish, bool(top3) if valid else False),
                "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":outcome")
    if lane == "INDEPENDENT_V5":
        require(post["independent"] == {
            "natural_n": len(rows), "invalid_n": sum(not r["valid_result"] for r in rows),
            "valid_n": sum(r["valid_result"] for r in rows),
            "hits": sum(r["actual_top3"] for r in rows),
            "rate": sum(r["actual_top3"] for r in rows) / sum(r["valid_result"] for r in rows)
            if any(r["valid_result"] for r in rows) else None},
            "STOP_RESUME_ARTIFACT_MISMATCH:INDEPENDENT_V5:metrics")
    return post


def _run_b1_boundary(operation) -> dict:
    """Capture ordinary B1-only errors after the seven-lane POST is built."""
    try:
        return operation()
    except Exception as error:
        return {"status": "STOPPED", "reason": str(error),
                "exception_type": type(error).__name__, "exception_message": str(error),
                "formal_lanes_affected": False}


def execute(date: str, audit: dict, previous_state: Path | None, next_state: Path,
            *, parent_status: str) -> dict:
    folder = OUT / date
    if (folder / "complete.json").exists():
        return verify_completed(folder, audit)
    if previous_state is not None:
        prior = read_json(previous_state)
        require(not any(row["date"] == f"{date[:4]}-{date[4:6]}-{date[6:]}"
                        for row in prior.get("formal_days", [])), "STOP_DUPLICATE_ADDENDUM_DAY")
    require(credit_class(date, "PROSPECTIVE_ELIGIBLE", pre_frozen_before_result=True) ==
            "FORMAL_NEW_GATE_ELIGIBLE", "STOP_ADDENDUM_EVIDENCE_ROLE")
    sources, current_result_sha = result_sources(date)
    require(current_result_sha == audit["result_sha256"], "STOP_RESULT_CHANGED_DURING_EXECUTION")
    lane_paths = lane_post_paths(date)
    # Validate every existing artifact before writing even the E1 Result copy.
    for lane, path in lane_paths.items():
        if path.exists():
            verify_lane_post(lane, date, path, audit, sources)
        else:
            require(not path.parent.exists(), "STOP_RESUME_ARTIFACT_MISMATCH:" + lane + ":partial_folder")
    if folder.exists():
        allowed = {"selected_horse_outcomes.json", "lane_summary.json"}
        require({path.name for path in folder.iterdir()} <= allowed,
                "STOP_RESUME_ARTIFACT_MISMATCH:coordinator_partial")
    e1_receipt = prepare_e1_result_pair(date, current_result_sha, audit["e1_result_authority"],
                                         copy_missing=True)
    verify_e1_result_content(date, current_result_sha, audit["e1_result_authority"])
    pre = audit["pre"]
    primary = RESULT_ROOT / f"馬番順着順_{date}.csv"
    auxiliary = RESULT_ROOT / f"着順馬番_{date}.csv"
    exp_pre = ROOT / f"reports/exp024_pl_same_volume/{date}_pre"
    exp_post_path = lane_paths["EXP024"]
    from review.pl_same_volume_reselection_shadow_v1 import post_from_frozen
    if not exp_post_path.exists():
        post_from_frozen(exp_pre, primary, auxiliary, exp_post_path.parent,
                         expected_freeze_sha256=pre["EXP024"]["freeze_sha256"])
    exp_post = read_json(exp_post_path)
    verify_lane_post("EXP024", date, exp_post_path, audit, sources)
    require(exp_post["result_source_sha256"] ==
            {"primary": current_result_sha["horse_order"], "auxiliary": current_result_sha["finish_order"]},
            "STOP_EXP024_RESULT_SHA")
    plj_selection = read_json(Path(pre["PL_JOCKEY"]["path"]))
    current_rows = current_rows_from_exp024(exp_post, plj_selection)
    horse_rows = {lane: joined(date, lane, pre, sources) for lane in ("PL_JOCKEY", "CURRENT_RANK1")}
    lane_metrics = {"CURRENT": metrics(current_rows),
                    "PL_JOCKEY": metrics(horse_rows["PL_JOCKEY"]),
                    "CURRENT_RANK1": metrics(horse_rows["CURRENT_RANK1"])}
    for lane in ("PL_JOCKEY", "CURRENT_RANK1"):
        write_forward_post(date, lane, audit, horse_rows[lane], lane_paths[lane])
    # Candidate runners retain their own Result semantics and evidence chains.
    if not lane_paths["A_NEW"].exists():
        run_existing(ANEW / "review/a_new_prospective_evidence_v1.py", "--post-date", date)
    if not lane_paths["E1"].exists():
        run_existing(E1 / "review/e1_full_field_allocation_evidence_v1.py",
                     "--post-date", date, "--exp024-post", str(exp_post_path))
    verify_e1_result_content(date, current_result_sha, audit["e1_result_authority"])
    from review.independent_race_selection_prospective_post import evaluate
    independent_pre = ROOT / f"reports/independent_race_selection_prospective/{date}_pre"
    independent_out = lane_paths["INDEPENDENT_V5"].parent
    if not lane_paths["INDEPENDENT_V5"].exists():
        evaluate(independent_pre, primary, auxiliary, independent_out)
    for lane, path in lane_paths.items():
        verify_lane_post(lane, date, path, audit, sources)
    day = verified_day(date, pre, horse_rows["PL_JOCKEY"], current_rows, current_result_sha,
                       parent_suspended=parent_status == "SUSPENDED")
    require(day["plj_slots"] == lane_metrics["CURRENT"]["selected"], "STOP_CURRENT_PLJ_VOLUME")
    require(all(path.is_file() for path in lane_paths.values()), "STOP_LANE_POST_MISSING")
    for lane in ("A_NEW", "E1"):
        post = read_json(lane_paths[lane])
        require(post["result_source_sha256"] == current_result_sha and
                post["pre_selection_sha256"] == pre[lane]["sha256"],
                "STOP_LANE_INPUT_SHA:" + lane)
        if lane == "A_NEW":
            require(post["pre_freeze_manifest_sha256"] == pre[lane]["freeze_sha256"],
                    "STOP_A_NEW_FREEZE_SHA")
        else:
            require(post["pre_freeze_sha256"] == pre[lane]["freeze_sha256"] and
                    post["exp024_post_crosscheck"]["status"] in
                    ("PASS", "NOT_APPLICABLE_COMPARATOR_SERVICE"), "STOP_E1_CROSSCHECK")
    require(result_sources(date)[1] == current_result_sha, "STOP_RESULT_CHANGED_DURING_EXECUTION")
    a_new_post = read_json(lane_paths["A_NEW"])
    e1_post = read_json(lane_paths["E1"])
    independent_post = read_json(lane_paths["INDEPENDENT_V5"])
    all_rows = {
        "CURRENT": current_rows,
        "EXP024": selected_rows_from_post("EXP024", exp_post),
        "CURRENT_RANK1": horse_rows["CURRENT_RANK1"],
        "PL_JOCKEY": horse_rows["PL_JOCKEY"],
        "A_NEW": selected_rows_from_post("A_NEW", a_new_post, read_json(Path(pre["A_NEW"]["path"]))),
        "E1": selected_rows_from_post("E1", e1_post, read_json(Path(pre["E1"]["path"]))),
        "INDEPENDENT_V5": selected_rows_from_post(
            "INDEPENDENT_V5", independent_post, read_json(Path(pre["INDEPENDENT_V5"]["path"]))),
    }
    # A_new/E1 PRE name strings can contain replacement characters. For the
    # human-facing table only, use the same-date full-field PL+J PRE identity;
    # retain the lane's original string and never alter its selected key.
    canonical_names = {(race["race_id"], int(h["horse_number"])): h["horse_name"]
                       for race in plj_selection["races"] for h in race["horses"]}
    for rows in all_rows.values():
        for row in rows:
            name = canonical_names.get((row["race_id"], row["horse_number"]))
            require(name is not None, "STOP_POST_HORSE_IDENTITY_NOT_IN_PRE")
            if row["horse_name"] != name:
                require("\ufffd" in row["horse_name"], "STOP_POST_HORSE_NAME_CONFLICT")
                row["lane_pre_horse_name"] = row["horse_name"]
                row["horse_name"] = name
    def arm_total(arm: str) -> dict:
        return {"selected": sum(r[arm]["prediction_count"] for r in exp_post["races"]),
                "valid": sum(r[arm]["valid_count"] for r in exp_post["races"]),
                "hits": sum(r[arm]["hits"] for r in exp_post["races"])}
    authority_metrics = {"CURRENT": arm_total("current"), "EXP024": arm_total("treatment"),
                         "CURRENT_RANK1": lane_metrics["CURRENT_RANK1"],
                         "PL_JOCKEY": lane_metrics["PL_JOCKEY"],
                         "A_NEW": a_new_post["arm_totals"]["a_new"], "E1": e1_post["e1"],
                         "INDEPENDENT_V5": independent_post["independent"]}
    final_metrics = {lane: lane_report(all_rows[lane], authority_metrics[lane]) for lane in LANES}
    selected_total = sum(item["selected"] for item in final_metrics.values())
    require(selected_total == sum(len(rows) for rows in all_rows.values()), "STOP_TOTAL_SELECTION_COUNT")
    folder.mkdir(parents=True, exist_ok=True)
    detail_path = folder / "selected_horse_outcomes.json"
    write_or_verify(detail_path, [{"lane": lane, **row} for lane in LANES for row in all_rows[lane]])
    summary_path = folder / "lane_summary.json"
    write_or_verify(summary_path, {"date": date, "lane_metrics": final_metrics,
                                   "selected_rows": selected_total,
                                   "unique_horses": len({(r["race_id"], r["horse_number"])
                                                        for rows in all_rows.values() for r in rows}),
                                   "result_source_sha256": current_result_sha})
    state_root = next_state.parent
    verified_path = state_root / f"{date}_verified_day.json"
    if next_state.exists():
        verify_existing_state(date, previous_state, verified_path, next_state, day)
    else:
        verified_path, next_state = write_state_event(date, state_root, previous_state, day)
    manifest = {"date": date, "status": "COMPLETE", "execution_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "result_finality_human_confirmed": True, "result_sha256": current_result_sha,
                "parent_status_confirmed": parent_status,
                "pre_sha256": {lane: item["sha256"] for lane, item in pre.items()},
                "lane_artifacts": {lane: {"path": str(path), "sha256": sha(path)} for lane, path in lane_paths.items()},
                "current_from_exp024": {"path": str(exp_post_path), "sha256": sha(exp_post_path),
                                        "metrics": lane_metrics["CURRENT"]},
                "addendum_verified_day_path": str(verified_path),
                "addendum_verified_day_sha256": sha(verified_path),
                "addendum_next_state_path": str(next_state), "addendum_next_state_sha256": sha(next_state),
                "selected_horse_outcomes_sha256": sha(detail_path), "lane_summary_sha256": sha(summary_path),
                "e1_result_handling": e1_receipt}
    if date >= "20261114":
        from review import b1_prospective_diagnostic_v1 as b1
        # B1 is outside the seven Formal POST lanes. Ordinary B1 exceptions
        # become STOPPED metadata; the seven-lane complete artifact is still
        # persisted below. KeyboardInterrupt/SystemExit are not swallowed.
        manifest["b1_diagnostic"] = _run_b1_boundary(lambda: b1.evaluate_post(date, root=ROOT))
    with (folder / "complete.json").open("xb") as stream:
        stream.write(canonical(manifest))
    return {"status": "COMPLETE", "manifest_sha256": sha(folder / "complete.json")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("date")
    parser.add_argument("--mode", choices=("check", "execute"), required=True)
    parser.add_argument("--human-final-result-confirmed", action="store_true")
    parser.add_argument("--post-review-human-approved", action="store_true")
    parser.add_argument("--parent-status", choices=("ACTIVE", "SUSPENDED"))
    args = parser.parse_args()
    require(args.human_final_result_confirmed, "STOP_HUMAN_RESULT_FINALITY_CONFIRMATION_REQUIRED")
    if args.mode == "execute":
        require(args.post_review_human_approved, "STOP_FORMAL_POST_EXECUTION_NOT_AUTHORIZED")
        require(args.parent_status is not None, "STOP_PARENT_STATUS_AUTHORITY_REQUIRED")
    audit = preflight(args.date)
    if args.mode == "check":
        print(json.dumps(audit, ensure_ascii=False, sort_keys=True, indent=2))
        return
    previous_state, next_state = state_chain_preflight(STATE_ROOT, args.date, allow_existing=True)
    print(json.dumps(execute(args.date, audit, previous_state, next_state,
                             parent_status=args.parent_status),
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
