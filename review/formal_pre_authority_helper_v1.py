"""Result-blind 2026-11-07 Formal PRE authority operations.

Only the evidence/recording gaps are implemented here. Prediction and lane
selection remain in their frozen runners. No operation reads a Result path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATE = "20261107"
JST = timezone(timedelta(hours=9))
VENUES = {"京都", "東京", "福島"}
EXP024_DEADLINE = datetime(2026, 11, 7, 9, 0, tzinfo=JST)
CALENDAR = Path("C:/Users/hikar/.codex/worktrees/rolling-learning-v1/keiba AI/docs/JRA_OFFICIAL_SEASON_CALENDAR_2026.json")
CALENDAR_SHA = "33cfa46d92a7ed3e6a5e96054503fcea69c487786eb37e369419d23917a5ee19"
SNAPSHOT_MANIFEST = ROOT / "docs/KeibaAI_JOCKEY_FORMAL_PRE_SNAPSHOT_MANIFEST_V1.json"
FIRST_START = ROOT / f"reports/exp024_pl_same_volume/authority/first_start_{DATE}.json"
CURRENT = ROOT / f"reports/prospective_prediction_{DATE}_formal_trace_v1"
EXP024 = ROOT / f"reports/exp024_pl_same_volume/{DATE}_pre"
RANK1 = ROOT / f"reports/current_rank1_prospective_shadow_v2/{DATE}_pre"
PLJ = ROOT / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{DATE}_pre"
INDEPENDENT = ROOT / f"reports/independent_race_selection_prospective/{DATE}_pre"
ANEW = Path("C:/Users/hikar/.codex/worktrees/a-new-prospective-shadow-v1/keiba AI")
E1 = Path("C:/Users/hikar/.codex/worktrees/e1-full-field-allocation-prospective-shadow-v1/keiba AI")
V3 = Path("C:/Users/hikar/.codex/worktrees/rolling-learning-v1/keiba AI")


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def load(path: Path) -> dict:
    if not path.is_file():
        raise Stop("STOP_REQUIRED_ARTIFACT_MISSING:" + str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def moment(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise Stop("STOP_NAIVE_AUTHORITY_TIME")
    return parsed


def exclusive_json(path: Path, value: dict) -> str:
    if path.exists():
        raise Stop("STOP_OUTPUT_EXISTS:" + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    return sha(path)


def relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise Stop("STOP_NONCANONICAL_ARTIFACT_PATH:" + str(path)) from error


def normalized_input_path(value: object) -> str:
    """Accept runner-relative Windows/POSIX spelling, never basename matching."""
    if not isinstance(value, str):
        raise Stop("STOP_CURRENT_INPUT_PATH_INVALID")
    normalized = value.replace("\\", "/")
    if (not normalized or normalized.startswith("/") or ":" in normalized or
            any(part in ("", ".", "..") for part in normalized.split("/"))):
        raise Stop("STOP_CURRENT_INPUT_PATH_INVALID")
    return normalized


def official_snapshot_path(root: Path, path: Path) -> str:
    name = relative(root, path)
    parts = {part.lower() for part in Path(name).parts}
    if any("result" in part or "odds" in part or "popularity" in part for part in parts):
        raise Stop("STOP_FORBIDDEN_SNAPSHOT_PATH")
    return name


def verify_calendar(root: Path = ROOT) -> None:
    path = CALENDAR if root.resolve() == ROOT.resolve() else root / "docs/JRA_OFFICIAL_SEASON_CALENDAR_2026.json"
    if sha(path) != CALENDAR_SHA:
        raise Stop("STOP_CALENDAR_SHA")
    calendar = load(path)
    if DATE not in calendar.get("scheduled_dates", []) or set(calendar.get("scheduled_venues", {}).get(DATE, [])) != VENUES:
        raise Stop("STOP_CALENDAR_VENUE_SCOPE")


def first_start_evidence(path: Path, *, root: Path = ROOT) -> dict:
    evidence = load(path)
    if evidence.get("date") != DATE or evidence.get("operator_verified") is not True or evidence.get("result_access") != 0:
        raise Stop("STOP_FIRST_START_AUTHORITY")
    first = moment(evidence["first_start_at"])
    if first.astimezone(JST).date().strftime("%Y%m%d") != DATE:
        raise Stop("STOP_FIRST_START_DATE")
    snapshots = evidence.get("source_snapshots")
    if not isinstance(snapshots, list) or len(snapshots) < 2:
        raise Stop("STOP_OFFICIAL_SNAPSHOTS_MISSING")
    for item in snapshots:
        source = root / item["path"]
        if official_snapshot_path(root, source) != item["path"]:
            raise Stop("STOP_NONCANONICAL_SNAPSHOT_PATH")
        if not source.is_file() or sha(source) != item["sha256"] or moment(item["observed_at"]) >= first:
            raise Stop("STOP_OFFICIAL_SNAPSHOT_SHA_OR_TIME")
        if item.get("observed_at_semantics") != "HELPER_LOCAL_FILE_INSPECTION_NOT_SOURCE_RETRIEVAL":
            raise Stop("STOP_SNAPSHOT_TIME_SEMANTICS")
        if item.get("source_retrieval_at") is not None:
            raise Stop("STOP_UNVERIFIED_SOURCE_RETRIEVAL_TIME")
        if moment(item["file_mtime_utc"]) != datetime.fromtimestamp(source.stat().st_mtime, timezone.utc):
            raise Stop("STOP_OFFICIAL_SNAPSHOT_MTIME_CHANGED")
    return evidence


def create_first_start(*, root: Path, snapshot_paths: list[Path], first_start_at: str,
                       first_race: str, schedule_url: str, entry_page_url: str,
                       operator_verified: bool) -> str:
    """Human-supplied official facts; no inferred first race or implicit approval."""
    verify_calendar(root)
    if operator_verified is not True or len(snapshot_paths) < 2:
        raise Stop("STOP_HUMAN_VERIFICATION_OR_SNAPSHOTS_MISSING")
    if not schedule_url.startswith("https://www.jra.go.jp/") or not entry_page_url.startswith("https://www.jra.go.jp/"):
        raise Stop("STOP_NON_OFFICIAL_SCHEDULE_URL")
    observed = now_utc()
    first = moment(first_start_at)
    if first.astimezone(JST).date().strftime("%Y%m%d") != DATE or observed >= first:
        raise Stop("STOP_FIRST_START_DATE_OR_TIME")
    snapshots = []
    for path in snapshot_paths:
        snapshot_name = official_snapshot_path(root, path)
        if not path.is_file() or not path.stat().st_size:
            raise Stop("STOP_OFFICIAL_SNAPSHOT_MISSING")
        snapshots.append({"path": snapshot_name, "sha256": sha(path),
                          "observed_at": observed.isoformat(),
                          "observed_at_semantics": "HELPER_LOCAL_FILE_INSPECTION_NOT_SOURCE_RETRIEVAL",
                          "source_retrieval_at": None,
                          "file_mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
    evidence = {"date": DATE, "first_start_at": first_start_at, "first_race": first_race,
                "authority": "JRA official race schedule and first-race entry page",
                "schedule_url": schedule_url, "entry_page_url": entry_page_url,
                "observed_at_utc": observed.isoformat(), "operator_verified": True,
                "source_snapshots": snapshots, "result_access": 0,
                "odds_used_as_input": False, "popularity_used_as_input": False}
    path = root / f"reports/exp024_pl_same_volume/authority/first_start_{DATE}.json"
    digest = exclusive_json(path, evidence)
    first_start_evidence(path, root=root)
    return digest


def current_authority(root: Path, current: Path) -> tuple[dict, dict, list[dict]]:
    if current.resolve() != (root / f"reports/prospective_prediction_{DATE}_formal_trace_v1").resolve():
        raise Stop("STOP_CURRENT_ROOT")
    manifest = load(current / "prediction_manifest.json")
    listed = manifest.get("files")
    if not isinstance(listed, list) or not listed:
        raise Stop("STOP_PREDICTION_MANIFEST_SCHEMA")
    names = [item.get("relative_path") for item in listed]
    if (any(not isinstance(name, str) or Path(name).is_absolute() or len(Path(name).parts) != 1
            or ":" in name or name in {".", ".."}
            for name in names) or len(names) != len(set(names))):
        raise Stop("STOP_PREDICTION_MANIFEST_PATH_SCOPE")
    for item in listed:
        artifact = current / item["relative_path"]
        if not artifact.is_file() or sha(artifact) != item["sha256"]:
            raise Stop("STOP_PREDICTION_MANIFEST_SHA")
    input_manifest = load(current / "input_manifest.json")
    provenance = load(current / "provenance.json")
    if input_manifest.get("date") != DATE or provenance.get("target_date") != DATE or provenance.get("result_data_access_count") != 0:
        raise Stop("STOP_CURRENT_DATE_OR_RESULT_ACCESS")
    for kind in ("DG", "DE", "DS"):
        item = input_manifest.get("sources", {}).get(kind, {})
        source = root / f"data/raw/prediction_input/{kind}{DATE[2:]}.CSV"
        if (not source.is_file() or relative(root, source) != normalized_input_path(item.get("path")) or
                sha(source) != item.get("sha256")):
            raise Stop("STOP_CURRENT_INPUT_SHA:" + kind)
    index = load(current / "race_index.json").get("race_index")
    if not isinstance(index, list) or not index or len({r["race_id"] for r in index}) != len(index):
        raise Stop("STOP_RACE_INDEX_SCHEMA")
    if next((x["sha256"] for x in listed if x["relative_path"] == "race_index.json"), None) != sha(current / "race_index.json"):
        raise Stop("STOP_RACE_INDEX_SHA")
    if {name for name in names if name.endswith("_prediction.json")} != {r["artifact"] for r in index}:
        raise Stop("STOP_PREDICTION_MANIFEST_RACE_SET")
    venues = {r["race_id"].split("_")[2] for r in index}
    if venues != {"kyoto", "tokyo", "fukushima"}:
        raise Stop("STOP_THREE_VENUES_MISSING_OR_EXTRA")
    if any(not r["race_id"].startswith("race_" + DATE + "_") or not r["artifact"].endswith("_prediction.json")
           for r in index):
        raise Stop("STOP_RACE_ID_SCOPE")
    check_source_scope(root, index)
    return manifest, input_manifest, index


def check_source_scope(root: Path, index: list[dict]) -> None:
    """Reuse the Current adapter and population guard; never infer exclusions."""
    from review.prospective_prediction_runner_v1 import _assert_population
    from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1

    raw = root / "data/raw/prediction_input"
    bundle = TargetBulkPredictionInputAdapterV1().load(
        raw / f"DG{DATE[2:]}.CSV", raw / f"DE{DATE[2:]}.CSV", raw / f"DS{DATE[2:]}.CSV")
    if bundle.date != DATE:
        raise Stop("STOP_ADAPTER_DATE_SCOPE")
    _assert_population(bundle)
    if set(bundle.races) != {item["race_id"] for item in index}:
        raise Stop("STOP_ADAPTER_RACE_SET_MISMATCH")


def freeze_current(*, root: Path, current: Path, evidence_path: Path) -> str:
    verify_calendar(root)
    evidence = first_start_evidence(evidence_path, root=root)
    _, _, _ = current_authority(root, current)
    freeze = now_utc()
    first = moment(evidence["first_start_at"])
    if freeze >= first:
        raise Stop("STOP_FREEZE_AFTER_FIRST_START")
    attestation = {"date": DATE, "role": "CURRENT_FORMAL_PRE_FREEZE_ATTESTATION",
                   "prediction_manifest_sha256": sha(current / "prediction_manifest.json"),
                   "freeze_timestamp_utc": freeze.isoformat(), "first_start_at": evidence["first_start_at"],
                   "first_start_evidence_path": relative(root, evidence_path),
                   "first_start_evidence_sha256": sha(evidence_path), "result_access_count": 0,
                   "odds_used_as_model_input": False, "popularity_used_as_model_input": False,
                   "pre_selection_changed_after_freeze": False}
    return exclusive_json(current / "formal_freeze_attestation.json", attestation)


def append_snapshot(*, root: Path, current: Path, manifest_path: Path) -> str:
    """Append one dated entry with the frozen manifest's existing canonical chain."""
    from review import frozen_pl_v1_jockey_offset_provisional_v1 as plj

    _, input_manifest, _ = current_authority(root, current)
    attestation = load(current / "formal_freeze_attestation.json")
    evidence_path = root / attestation["first_start_evidence_path"]
    evidence = first_start_evidence(evidence_path, root=root)
    if (attestation.get("date") != DATE or attestation.get("result_access_count") != 0 or
            attestation.get("prediction_manifest_sha256") != sha(current / "prediction_manifest.json") or
            attestation.get("first_start_evidence_sha256") != sha(evidence_path) or
            attestation.get("first_start_at") != evidence["first_start_at"] or
            moment(attestation["freeze_timestamp_utc"]) >= moment(evidence["first_start_at"])):
        raise Stop("STOP_CURRENT_ATTESTATION_INVALID")
    before = manifest_path.read_bytes()
    old = json.loads(before)
    plj.validate_formal_manifest(DATE, require_target_entry=False, value=old)
    if DATE in old["expected_formal_pre_dates"] or any(row["date"] == DATE for row in old["entries"]):
        raise Stop("STOP_DUPLICATE_SNAPSHOT_DATE")
    if old["expected_formal_pre_dates"] and old["expected_formal_pre_dates"][-1] >= DATE:
        raise Stop("STOP_SNAPSHOT_DATE_ORDER")
    ds = root / f"data/raw/prediction_input/DS{DATE[2:]}.CSV"
    if input_manifest["sources"]["DS"]["sha256"] != sha(ds):
        raise Stop("STOP_DS_SNAPSHOT_SHA")
    entry = {"date": DATE, "current_pre_path": relative(root, current / "prediction_manifest.json"),
             "current_pre_sha256": sha(current / "prediction_manifest.json"),
             "ds_snapshot_path": relative(root, ds), "ds_snapshot_sha256": sha(ds),
             "input_manifest_path": relative(root, current / "input_manifest.json"),
             "input_manifest_sha256": sha(current / "input_manifest.json"),
             "freeze_timestamp": attestation["freeze_timestamp_utc"],
             "previous_entries_sha256": hashlib.sha256(plj.canonical(old["entries"])).hexdigest(),
             "status": "FROZEN_PRE_SOURCE"}
    updated = {**old, "expected_formal_pre_dates": [*old["expected_formal_pre_dates"], DATE],
               "entries": [*old["entries"], entry]}
    plj.validate_formal_manifest(DATE, value=updated)
    if manifest_path.read_bytes() != before:
        raise Stop("STOP_SNAPSHOT_MANIFEST_CONCURRENT_CHANGE")
    # Retain the established human-readable layout when present; preserve all
    # prior entry text, adding only the date and a new final entry.
    old_text = before.decode("utf-8")
    dates_match = re.search(r'("expected_formal_pre_dates"\s*:\s*\[)([^\]]*)(\])', old_text)
    entries_match = re.search(r'("entries"\s*:\s*\[)(.*?)(\n  \])', old_text, re.S)
    if dates_match and entries_match and "\n" in entries_match.group(2):
        new_date_text = dates_match.group(1) + dates_match.group(2).rstrip() + ', "' + DATE + '"' + dates_match.group(3)
        entry_text = json.dumps(entry, ensure_ascii=False, indent=2)
        entry_text = "\n".join("    " + line for line in entry_text.splitlines())
        new_entries_text = (entries_match.group(1) + entries_match.group(2).rstrip() +
                            ",\n" + entry_text + entries_match.group(3))
        replacement = old_text[:entries_match.start()] + new_entries_text + old_text[entries_match.end():]
        replacement = replacement[:dates_match.start()] + new_date_text + replacement[dates_match.end():]
        new_bytes = replacement.encode("utf-8")
        if json.loads(new_bytes) != updated:
            raise Stop("STOP_SNAPSHOT_FORMAT_PRESERVATION")
    else:
        new_bytes = canonical(updated)
    descriptor, name = tempfile.mkstemp(prefix=".formal_pre_", suffix=".json", dir=manifest_path.parent)
    temp = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(new_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, manifest_path)
    finally:
        if temp.exists():
            temp.unlink()
    after = load(manifest_path)
    if after["entries"][:-1] != old["entries"] or after["expected_formal_pre_dates"][:-1] != old["expected_formal_pre_dates"]:
        raise Stop("STOP_SNAPSHOT_HISTORY_CHANGED")
    return sha(manifest_path)


def freeze_exp024(*, current: Path, evidence: Path, approval: Path, output: Path,
                  root: Path = ROOT) -> str:
    from review import pl_same_volume_reselection_shadow_v1 as exp024
    from review import frozen_pl_v1_jockey_offset_provisional_v1 as plj

    first_start_evidence(evidence, root=root)
    if not (current / "formal_freeze_attestation.json").is_file():
        raise Stop("STOP_CURRENT_FORMAL_FREEZE_MISSING")
    if now_utc() >= EXP024_DEADLINE.astimezone(timezone.utc):
        raise Stop("STOP_EXP024_0900_JST_DEADLINE")
    plj.validate_formal_manifest(DATE)
    if output.exists():
        raise Stop("STOP_OUTPUT_EXISTS")
    previous = previous_exp024_fingerprint(root)
    selection = exp024.build_pre(current, root / "knowledge",
                                 previous_environment_fingerprint=previous)
    current_fingerprint = selection.get("current_environment_fingerprint")
    if (selection.get("previous_environment_fingerprint") != previous or
            not isinstance(current_fingerprint, str) or
            selection.get("change_detected") is not (current_fingerprint != previous)):
        raise Stop("STOP_EXP024_ENVIRONMENT_CHAIN")
    if now_utc() >= EXP024_DEADLINE.astimezone(timezone.utc):
        raise Stop("STOP_EXP024_0900_JST_DEADLINE")
    exp024.freeze_pre(selection, output, first_start_evidence=evidence,
                      first_start_evidence_sha=sha(evidence), authorization=approval,
                      authorization_sha=sha(approval))
    if moment(load(output / "selection_freeze.json")["selection_freeze_timestamp"]) >= EXP024_DEADLINE:
        raise Stop("STOP_EXP024_0900_JST_DEADLINE")
    return sha(output / "selection_freeze.json")


def previous_exp024_fingerprint(root: Path) -> str:
    """Read the frozen 11/01 selection and its freeze index as the sole authority."""
    previous_root = root / "reports/exp024_pl_same_volume/20261101_pre"
    selection_path = previous_root / "selection.json"
    freeze = load(previous_root / "selection_freeze.json")
    if freeze.get("selection_sha256") != sha(selection_path):
        raise Stop("STOP_EXP024_PREVIOUS_SELECTION_SHA")
    selection = load(selection_path)
    previous = selection.get("current_environment_fingerprint")
    if (selection.get("date") != "20261101" or not isinstance(previous, str) or
            re.fullmatch(r"[0-9a-f]{64}", previous) is None or
            selection.get("current_environment", {}).get("block_fingerprint_sha256") != previous):
        raise Stop("STOP_EXP024_PREVIOUS_FINGERPRINT")
    return previous


def freeze_pl_jockey(*, current: Path, pl_prediction: Path, evidence: Path,
                     de: Path, ds: Path, output: Path, root: Path = ROOT) -> str:
    from review import frozen_pl_v1_jockey_offset_provisional_v1 as plj

    first_start_evidence(evidence, root=root)
    if output.exists():
        raise Stop("STOP_OUTPUT_EXISTS")
    plj.validate_formal_manifest(DATE)
    selection = plj.build_pre(current, pl_prediction, de, ds)
    plj.freeze_pre(selection, output, first_race_authority_path=evidence)
    return sha(output / "provisional_audit.json")


def create_a_new_completion(*, root: Path, current: Path, exp024: Path, rank1: Path,
                            plj: Path, output: Path) -> str:
    current_authority(root, current)
    attest = load(current / "formal_freeze_attestation.json")
    evidence = first_start_evidence(root / attest["first_start_evidence_path"], root=root)
    artifacts = [("CURRENT", current / "prediction_manifest.json"),
                 ("EXP024", exp024 / "selection_freeze.json"),
                 ("CURRENT_RANK1_PRIOR_DAY_PRE_V2", rank1 / "freeze_manifest.json"),
                 ("FROZEN_PL_V1_JOCKEY_OFFSET", plj / "provisional_audit.json")]
    frozen_at = [moment(attest["freeze_timestamp_utc"])]
    for lane, path in artifacts[1:]:
        record = load(path)
        if lane == "EXP024":
            exp_freeze = moment(record["selection_freeze_timestamp"])
            if exp_freeze >= EXP024_DEADLINE:
                raise Stop("STOP_EXP024_0900_JST_DEADLINE")
            frozen_at.append(exp_freeze)
        elif lane == "CURRENT_RANK1_PRIOR_DAY_PRE_V2":
            frozen_at.append(moment(record["freeze_timestamp_jst"]))
        else:
            frozen_at.append(moment(record["freeze_timestamp"]))
    if any(t >= moment(evidence["first_start_at"]) for t in frozen_at):
        raise Stop("STOP_FORMAL_LANE_LATE_FREEZE")
    value = {"date": DATE, "all_existing_formal_pre_complete": True, "result_access_count": 0,
             "artifacts": [{"lane": lane, "path": str(path.resolve()), "sha256": sha(path)}
                           for lane, path in artifacts]}
    return exclusive_json(output, value)


def run_a_new_existing(*, completion: Path, current: Path, formal: Path,
                       approval: Path, worktree: Path = ANEW) -> None:
    """Use the approved script path, never ``python -m`` or a new model path."""
    record = load(completion)
    if record.get("date") != DATE or record.get("all_existing_formal_pre_complete") is not True:
        raise Stop("STOP_A_NEW_FORMAL_COMPLETION")
    for item in record.get("artifacts", []):
        if sha(Path(item["path"])) != item["sha256"]:
            raise Stop("STOP_A_NEW_COMPLETION_SHA")
    if len(record.get("artifacts", [])) != 4 or {item.get("lane") for item in record.get("artifacts", [])} != {
            "CURRENT", "EXP024", "CURRENT_RANK1_PRIOR_DAY_PRE_V2", "FROZEN_PL_V1_JOCKEY_OFFSET"}:
        raise Stop("STOP_A_NEW_COMPLETION_ARTIFACTS")
    script = worktree / "review/a_new_prospective_shadow_v1.py"
    if not script.is_file():
        raise Stop("STOP_A_NEW_RUNNER_MISSING")
    subprocess.run([sys.executable, str(script), "--build-pre", "--date", DATE,
                    "--current-root", str(current), "--formal-root", str(formal),
                    "--formal-completion", str(completion), "--implementation-approval", str(approval)],
                   cwd=worktree, check=True)


def create_e1_completion(*, current: Path, exp024: Path, rank1: Path, plj: Path,
                         a_new_status: Path | None, a_new_freeze: Path | None,
                         authority_root: Path, exp024_progression_ceased: bool = False) -> str:
    """Five status records and one priority record, from already frozen artifacts."""
    if exp024_progression_ceased:
        raise Stop("STOP_EXP024_SERVICE_AUTHORITY_REQUIRED")
    if a_new_freeze is not None:
        freeze = load(a_new_freeze)
        if (freeze.get("date") != DATE or freeze.get("evidence_date") is not True or
                freeze.get("result_access_count_at_freeze") != 0 or
                freeze.get("selection_sha256") != sha(a_new_freeze.parent / "selection.json")):
            raise Stop("STOP_A_NEW_FREEZE_INVALID")
        a_new_role, a_new_source = "A_NEW", a_new_freeze
        a_new_state = "PRE_FROZEN"
    elif a_new_status is not None and load(a_new_status).get("status") == "NOT_COLLECTED":
        status = load(a_new_status)
        if status.get("date") != DATE or status.get("result_access_count") != 0:
            raise Stop("STOP_A_NEW_STATUS_INVALID")
        a_new_role, a_new_source = "A_NEW_FORMAL_STATUS", a_new_status
        a_new_state = "NOT_COLLECTED"
    else:
        raise Stop("STOP_A_NEW_STATUS_OR_FREEZE_MISSING")
    upstream = [("CURRENT", current / "prediction_manifest.json"),
                ("EXP024", exp024 / "selection_freeze.json"),
                ("CURRENT_RANK1", rank1 / "freeze_manifest.json"),
                ("FROZEN_PL_JOCKEY", plj / "provisional_audit.json"),
                (a_new_role, a_new_source)]
    if any(not p.is_file() for _, p in upstream):
        raise Stop("STOP_E1_UPSTREAM_MISSING")
    status_dir = authority_root / f"priority_{DATE}"
    completion_path = authority_root / f"priority_completion_{DATE}.json"
    if status_dir.exists() or completion_path.exists():
        raise Stop("STOP_OUTPUT_EXISTS")
    status_names = ("current", "exp024", "current_rank1", "frozen_pl_jockey", "a_new")
    status_map = {}
    for (lane, path), name in zip(upstream, status_names, strict=True):
        status_path = status_dir / (name + "_status.json")
        status_map["A_NEW" if name == "a_new" else lane] = {
            "status": a_new_state if name == "a_new" else "PRE_FROZEN",
            "status_path": str(status_path.resolve()),
            "status_sha256": hashlib.sha256(canonical({"date": DATE,
                "lane": "A_NEW" if name == "a_new" else lane,
                "status": a_new_state if name == "a_new" else "PRE_FROZEN",
                "authority_path": str(path.resolve()), "authority_sha256": sha(path),
                "result_access_count": 0})).hexdigest()}
    value = {"date": DATE, "role": "E1_DAILY_PRIORITY_COMPLETION_AUTHORITY",
             "result_access_count": 0, "exp024_progression_ceased": False,
             "artifacts": [{"lane": lane, "path": str(path.resolve()), "sha256": sha(path)}
                           for lane, path in upstream], "lane_status": status_map}
    status_dir.mkdir(parents=True, exist_ok=False)
    for (lane, path), name in zip(upstream, status_names, strict=True):
        exclusive_json(status_dir / (name + "_status.json"),
                       {"date": DATE, "lane": "A_NEW" if name == "a_new" else lane,
                        "status": a_new_state if name == "a_new" else "PRE_FROZEN",
                        "authority_path": str(path.resolve()), "authority_sha256": sha(path),
                        "result_access_count": 0})
    return exclusive_json(completion_path, value)


def run_e1_existing(*, priority: Path, exp024: Path, current: Path,
                    approval: Path, worktree: Path = E1) -> None:
    record = load(priority)
    if record.get("date") != DATE or record.get("result_access_count") != 0:
        raise Stop("STOP_E1_PRIORITY_COMPLETION")
    for item in record.get("artifacts", []):
        if sha(Path(item["path"])) != item["sha256"]:
            raise Stop("STOP_E1_PRIORITY_SHA")
    roles = {item.get("lane") for item in record.get("artifacts", [])}
    if len(record.get("artifacts", [])) != 5 or roles not in (
            {"CURRENT", "EXP024", "CURRENT_RANK1", "FROZEN_PL_JOCKEY", "A_NEW"},
            {"CURRENT", "EXP024", "CURRENT_RANK1", "FROZEN_PL_JOCKEY", "A_NEW_FORMAL_STATUS"}):
        raise Stop("STOP_E1_PRIORITY_ARTIFACTS")
    script = worktree / "review/e1_full_field_allocation_prospective_shadow_v1.py"
    if not script.is_file():
        raise Stop("STOP_E1_RUNNER_MISSING")
    subprocess.run([sys.executable, str(script), "--build-pre", "--date", DATE,
                    "--exp024-root", str(exp024), "--current-root", str(current),
                    "--priority-completion", str(priority), "--human-approval", str(approval)],
                   cwd=worktree, check=True)


def freeze_step1(*, plj_path: Path, e1_path: Path, current: Path,
                 evidence: Path, output: Path, root: Path = ROOT) -> str:
    from review import pl_jockey_step1_operations_v1 as step1

    first = first_start_evidence(evidence, root=root)["first_start_at"]
    _, _, index = current_authority(root, current)
    counts = {row["race_id"]: int(row["buy_count"]) for row in index}
    step1.freeze_pre(plj_path=plj_path, e1_path=e1_path,
                     current_manifest_path=current / "prediction_manifest.json",
                     current_buy_counts=counts, first_start_at=first, output_path=output)
    return sha(output)


def verify_v3_pre(root: Path, manifest_path: Path) -> None:
    """Run the frozen V3 PRE verifier in its own worktree, with bytecode writes off."""
    if not (V3 / "review/rolling_learning_v3.py").is_file():
        raise Stop("STOP_V3_VERIFIER_MISSING")
    code = ("from pathlib import Path; from review.rolling_learning_v3 import verify_pre; "
            "verify_pre(Path(__import__('sys').argv[1]), '20261107', Path(__import__('sys').argv[2]))")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-c", code, str(root), relative(root, manifest_path)],
                            cwd=V3, env=env, capture_output=True, text=True)
    if result.returncode:
        raise Stop("STOP_V3_VERIFY_PRE:" + result.stderr.strip()[-500:])


def audit(*, root: Path, current: Path, evidence: Path, manifest_path: Path,
          lane_artifacts: dict[str, Path] | None = None, step1_path: Path | None = None) -> dict:
    """PRE-only audit; no Result lookup or creation of missing evidence."""
    verify_calendar(root)
    first = first_start_evidence(evidence, root=root)
    if now_utc() >= moment(first["first_start_at"]):
        raise Stop("STOP_AUDIT_AFTER_FIRST_START")
    _, _, index = current_authority(root, current)
    attestation = load(current / "formal_freeze_attestation.json")
    snapshot = load(manifest_path)
    entries = [row for row in snapshot["entries"] if row["date"] == DATE]
    if (len(entries) != 1 or DATE not in snapshot["expected_formal_pre_dates"] or
            entries[0]["current_pre_sha256"] != sha(current / "prediction_manifest.json") or
            entries[0]["freeze_timestamp"] != attestation["freeze_timestamp_utc"] or
            attestation.get("result_access_count") != 0 or
            attestation["first_start_evidence_sha256"] != sha(evidence) or
            moment(attestation["freeze_timestamp_utc"]) >= moment(first["first_start_at"])):
        raise Stop("STOP_FORMAL_PRE_AUDIT")
    if lane_artifacts is None or set(lane_artifacts) != {"EXP024", "CURRENT_RANK1", "PL_JOCKEY", "A_NEW", "E1", "INDEPENDENT_V5"}:
        raise Stop("STOP_LANE_AUDIT_INCOMPLETE")
    for lane, path in lane_artifacts.items():
        item = load(path)
        if lane in {"EXP024", "CURRENT_RANK1", "PL_JOCKEY", "A_NEW", "E1"}:
            selection_name = "pre_selection.json" if lane == "CURRENT_RANK1" else "selection.json"
            if item.get("selection_sha256") != sha(path.parent / selection_name):
                raise Stop("STOP_LANE_SELECTION_SHA:" + lane)
        if lane == "A_NEW" and item.get("result_access_count_at_freeze") != 0:
            raise Stop("STOP_LANE_RESULT_ACCESS:" + lane)
        if lane == "E1" and item.get("result_access_count") != 0:
            raise Stop("STOP_LANE_RESULT_ACCESS:" + lane)
        if lane == "EXP024" and moment(item["selection_freeze_timestamp"]) >= EXP024_DEADLINE:
            raise Stop("STOP_EXP024_0900_JST_DEADLINE")
        stamp = next((item[k] for k in ("selection_freeze_timestamp", "freeze_timestamp_jst",
                                       "freeze_timestamp", "freeze_timestamp_utc",
                                       "e1_freeze_timestamp") if k in item), None)
        if stamp is not None and moment(stamp) >= moment(first["first_start_at"]):
            raise Stop("STOP_LANE_LATE_FREEZE:" + lane)
        if lane == "INDEPENDENT_V5":
            manifest = load(path.parent / "selection_manifest.json")
            if item["indexed_artifacts"]["selection_manifest.json"] != sha(path.parent / "selection_manifest.json") or manifest.get("date") != DATE:
                raise Stop("STOP_INDEPENDENT_HASH")
            for name, digest in item["indexed_artifacts"].items():
                if sha(path.parent / name) != digest:
                    raise Stop("STOP_INDEPENDENT_HASH:" + name)
    if step1_path is None or load(step1_path).get("result_access") != 0:
        raise Stop("STOP_STEP1_DERIVATION_MISSING")
    verify_v3_pre(root, manifest_path)
    return {"date": DATE, "venue_count": 3, "race_count": len(index), "result_access_count": 0,
            "prediction_manifest_sha256": sha(current / "prediction_manifest.json"),
            "attestation_sha256": sha(current / "formal_freeze_attestation.json"),
            "snapshot_manifest_sha256": sha(manifest_path), "status": "PASS"}


def main() -> None:
    parser = argparse.ArgumentParser(description="2026-11-07 Formal PRE authority helper; no prediction")
    parser.add_argument("step", choices=("first-start", "attest", "register", "a-new-completion", "e1-completion", "audit"))
    parser.add_argument("--snapshot", type=Path, action="append", default=[])
    parser.add_argument("--first-start-at")
    parser.add_argument("--first-race")
    parser.add_argument("--schedule-url")
    parser.add_argument("--entry-page-url")
    parser.add_argument("--operator-verified", action="store_true")
    parser.add_argument("--step1-artifact", type=Path)
    args = parser.parse_args()
    if args.step == "first-start":
        if not all((args.first_start_at, args.first_race, args.schedule_url, args.entry_page_url)):
            raise Stop("STOP_FIRST_START_ARGUMENTS")
        result = create_first_start(root=ROOT, snapshot_paths=args.snapshot,
                                    first_start_at=args.first_start_at, first_race=args.first_race,
                                    schedule_url=args.schedule_url, entry_page_url=args.entry_page_url,
                                    operator_verified=args.operator_verified)
    elif args.step == "attest":
        result = freeze_current(root=ROOT, current=CURRENT, evidence_path=FIRST_START)
    elif args.step == "register":
        result = append_snapshot(root=ROOT, current=CURRENT, manifest_path=SNAPSHOT_MANIFEST)
    elif args.step == "a-new-completion":
        result = create_a_new_completion(root=ROOT, current=CURRENT, exp024=EXP024, rank1=RANK1, plj=PLJ,
                                         output=ANEW / f"reports/a_new_prospective_shadow_v1/formal_completion_{DATE}.json")
    elif args.step == "e1-completion":
        a_new_root = ANEW / "reports/a_new_prospective_shadow_v1"
        a_new_freeze = a_new_root / f"daily_pre/{DATE}/freeze_manifest.json"
        a_new_status = a_new_root / f"date_status/{DATE}/status.json"
        result = create_e1_completion(current=CURRENT, exp024=EXP024, rank1=RANK1, plj=PLJ,
                                      a_new_status=a_new_status if a_new_status.is_file() else None,
                                      a_new_freeze=a_new_freeze if a_new_freeze.is_file() else None,
                                      authority_root=E1 / "reports/e1_full_field_allocation_prospective_shadow_v1/authority")
    else:
        result = audit(root=ROOT, current=CURRENT, evidence=FIRST_START, manifest_path=SNAPSHOT_MANIFEST,
                       lane_artifacts={
                           "EXP024": EXP024 / "selection_freeze.json",
                           "CURRENT_RANK1": RANK1 / "freeze_manifest.json",
                           "PL_JOCKEY": PLJ / "provisional_audit.json",
                           "A_NEW": ANEW / f"reports/a_new_prospective_shadow_v1/daily_pre/{DATE}/freeze_manifest.json",
                           "E1": E1 / f"reports/e1_full_field_allocation_prospective_shadow_v1/daily_pre/{DATE}/freeze_manifest.json",
                           "INDEPENDENT_V5": INDEPENDENT / "artifact_hashes.json"},
                       step1_path=args.step1_artifact)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
