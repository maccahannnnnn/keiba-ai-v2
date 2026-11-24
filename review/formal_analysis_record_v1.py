"""Immutable, non-evidential analysis records for frozen calculation lanes.

This module never runs Formal PRE, reads Result, or grants prospective evidence.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import os
import subprocess
import sys
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

from review import b1_prospective_diagnostic_v1 as b1
from review import formal_pre_authority_helper_v2 as formal
from review import pl_same_volume_reselection_shadow_v1 as exp024
from review import frozen_pl_v1_jockey_offset_provisional_v1 as plj_module
from review import current_unconverged_rank1_prospective_shadow_v2 as rank1_module
from review import current_unconverged_rank1_prospective_shadow_v1 as rank1_source
from review import independent_race_selection_prospective_pre as independent_v5
from review import prospective_three_system_pre_freeze_v1 as daily_v5

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
PLJ_SOURCE_SHA256 = "f7597b1bb0681b21ac8c86ae82d026a7f426e7687bbaa27a0b5a614b68a9a0eb"
EXP024_SOURCE_SHA256 = "3c04dce476e925397dbb1f504657906100d7951b94858f4165b2f716d4340832"
E1_SOURCE_SHA256 = "b396898d37471419ac3db960387c4c0e47c31d19e792824c7c9d3ef34c73d9db"
A_NEW_SOURCE_SHA256 = "ec5d53cecf354abcc092196b2b38c6d1373ac2bb98bfe549e4d512c06734ab92"
V5_SOURCE_SHA256 = "e0304ac6a43c2b2407786adef691b38f9063b97f987d2a061d7b5b10206d4a8d"
EXTERNAL_WORKER_SHA256 = "754ea605282f93ab0dc79cd4876a0df7f9f579cc2d172c799080c1853ded447a"
E1_SOURCE = Path("C:/Users/hikar/.codex/worktrees/e1-full-field-allocation-prospective-shadow-v1/keiba AI/review/e1_full_field_allocation_prospective_shadow_v1.py")
A_NEW_SOURCE = Path("C:/Users/hikar/.codex/worktrees/a-new-prospective-shadow-v1/keiba AI/review/a_new_prospective_shadow_v1.py")


class Stop(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(path: Path) -> str:
    if not path.is_file():
        raise Stop("STOP_ANALYSIS_SOURCE_MISSING:" + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stop("STOP_ANALYSIS_SOURCE_SCHEMA:" + str(path))
    return value


def _moment(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise Stop("STOP_ANALYSIS_TIME_INVALID") from error
    if moment.tzinfo is None:
        raise Stop("STOP_ANALYSIS_TIME_NAIVE")
    return moment


def _current_freeze(current: Path, date: str, generated_at: datetime) -> dict:
    path = current / "formal_freeze_attestation.json"
    if not path.exists():
        return {"original_freeze_at_utc": None,
                "original_freeze_time_source": "NO_FORMAL_FREEZE",
                "original_freeze_attestation_sha256": None}
    audit = _read(path)
    manifest_sha = _sha(current / "prediction_manifest.json")
    if (audit.get("date") != date or
            audit.get("role") != "CURRENT_FORMAL_PRE_FREEZE_ATTESTATION" or
            audit.get("prediction_manifest_sha256") != manifest_sha or
            audit.get("result_access_count") != 0 or
            audit.get("pre_selection_changed_after_freeze") is not False):
        raise Stop("STOP_CURRENT_FREEZE_ATTESTATION_MISMATCH")
    frozen = _moment(audit.get("freeze_timestamp_utc"))
    if frozen < generated_at or frozen > _now():
        raise Stop("STOP_CURRENT_FREEZE_TIME_INCONSISTENT")
    return {"original_freeze_at_utc": frozen.astimezone(timezone.utc).isoformat(),
            "original_freeze_time_source": "FORMAL_FREEZE_ATTESTATION",
            "original_freeze_attestation_sha256": _sha(path)}


def _plj_freeze(plj_path: Path, date: str) -> dict:
    path = plj_path.with_name("provisional_audit.json")
    if not path.exists():
        return {"pl_jockey_input_frozen": False, "pl_jockey_freeze_at_utc": None,
                "pl_jockey_freeze_audit_sha256": None}
    audit = _read(path)
    if (audit.get("date") != date or audit.get("selection_sha256") != _sha(plj_path) or
            audit.get("result_access_count") != 0 or
            audit.get("semantic_validation_result") != "PASS"):
        raise Stop("STOP_PL_JOCKEY_FREEZE_AUDIT_MISMATCH")
    frozen = _moment(audit.get("freeze_timestamp"))
    if frozen > _now():
        raise Stop("STOP_PL_JOCKEY_FREEZE_TIME_INCONSISTENT")
    return {"pl_jockey_input_frozen": True,
            "pl_jockey_freeze_at_utc": frozen.astimezone(timezone.utc).isoformat(),
            "pl_jockey_freeze_audit_sha256": _sha(path)}


def _verify_b1_authorization(root: Path) -> str:
    path = root / "docs/KeibaAI_B1_PROSPECTIVE_EVIDENCE_AUTHORIZATION_V1.md"
    if not path.is_file():
        raise Stop("STOP_B1_AUTHORIZATION_MISSING")
    content = path.read_text(encoding="utf-8")
    match = re.search(r"\| B1 implementation \| `([0-9a-f]{64})` \|", content)
    if not match or match.group(1) != _sha(Path(b1.__file__)):
        raise Stop("STOP_B1_IMPLEMENTATION_SHA_AUTHORITY")
    return _sha(path)


def _record_time(date: str, *, analysis_at: datetime | None = None,
                 execution_time_source: str = "INDEPENDENT_CALCULATION_CLOCK") -> dict:
    formal.checked_date(date)
    observed = _now()
    if observed.tzinfo is None:
        raise Stop("STOP_ANALYSIS_CLOCK_NAIVE")
    executed = analysis_at or observed
    if executed.tzinfo is None or executed > observed:
        raise Stop("STOP_ANALYSIS_EXECUTION_TIME_INVALID")
    local = executed.astimezone(JST)
    if local.strftime("%Y%m%d") > date:
        timing = "AFTER_TARGET_DATE_ANALYSIS"
    elif local.strftime("%Y%m%d") < date:
        timing = "BEFORE_TARGET_DATE_ANALYSIS"
    else:
        timing = "SAME_DAY_FIRST_START_UNVERIFIED"
    return {"record_created_at_utc": observed.astimezone(timezone.utc).isoformat(),
            "analysis_executed_at_utc": executed.astimezone(timezone.utc).isoformat(),
            "execution_time_source": execution_time_source,
            "timing_classification": timing, "actual_first_start_verified": False,
            "prospective_evidence_status": "NOT_ASSESSED", "prospective_evidence_credit": 0}


def _current(date: str, root: Path, current_path: Path | None = None) -> tuple[Path, dict, dict, list[dict], list[dict], datetime]:
    current = current_path.resolve() if current_path is not None else root / f"reports/prospective_prediction_{date}_formal_trace_v1"
    if current_path is None:
        authority = formal.helper(date, root=root)
        manifest, inputs, index = authority.current_authority(root, current)
    else:
        inputs, index, _ = _analysis_current(date, current, root)
        manifest = _read(current / "prediction_manifest.json")
    if inputs.get("date") != date or not isinstance(index, list) or not index:
        raise Stop("STOP_CURRENT_ANALYSIS_POPULATION")
    provenance = _read(current / "provenance.json")
    if provenance.get("target_date") != date or provenance.get("result_data_access_count") != 0:
        raise Stop("STOP_CURRENT_ANALYSIS_RESULT_OR_DATE")
    try:
        generated_at = _moment(provenance["generated_at"])
    except (KeyError, TypeError, ValueError, Stop) as error:
        raise Stop("STOP_CURRENT_ANALYSIS_EXECUTION_TIME") from error
    selected = []
    for item in index:
        payload = _read(current / item["artifact"])
        if payload.get("race_id") != item["race_id"]:
            raise Stop("STOP_CURRENT_ANALYSIS_RACE_ID")
        field = {(int(h["horse_number"]), h["horse_name"]) for h in payload["ranked_results"]}
        buys = [(int(h["horse_number"]), h["horse_name"]) for h in payload["buys"]]
        if len(field) != int(item["horse_count"]) or len(buys) != int(item["buy_count"]) or len(buys) != len(set(buys)) or not set(buys) <= field:
            raise Stop("STOP_CURRENT_ANALYSIS_SELECTION_IDENTITY")
        selected.extend({"race_id": item["race_id"], "horse_number": number,
                         "horse_name": name} for number, name in buys)
    return current, manifest, inputs, index, sorted(selected, key=lambda h: (h["race_id"], h["horse_number"])), generated_at


def _save(date: str, lane: str, value: dict, root: Path) -> dict:
    output = root / "reports/formal_analysis_v1" / date / (lane.lower() + ".json")
    if output.exists():
        raise Stop("STOP_ANALYSIS_RECORD_EXISTS:" + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(b1.canonical(value))
    return {"status": "FORMAL_ANALYSIS_RECORD_SAVED", "path": str(output),
            "sha256": _sha(output), "prospective_evidence_credit": 0}


def record_current(date: str, *, root: Path = ROOT, current_path: Path | None = None) -> dict:
    """Record a previously calculated and authority-verified Current selection."""
    formal.checked_date(date)
    current, _, inputs, index, selected, generated_at = _current(date, root, current_path)
    source_sha = (b1.verified_input_sources(current, inputs) if current_path is None
                  else _analysis_current(date, current, root)[2])
    value = {"date": date, "lane": "CURRENT", "role": "FORMAL_ANALYSIS",
             "record_class": "ANALYSIS_ONLY",
             "calculation_status": "EXISTING_OUTPUT_VERIFIED_NOT_RECOMPUTED",
             "race_count": len(index), "horse_count": sum(int(x["horse_count"]) for x in index),
             "selected_count": len(selected), "selected_horses": selected,
             "selected_horses_sha256": hashlib.sha256(b1.canonical(selected)).hexdigest(),
             "prediction_manifest_sha256": _sha(current / "prediction_manifest.json"),
             "source_current_path": str(current),
             "input_manifest_sha256": _sha(current / "input_manifest.json"),
             "target_input_sha256": {kind: item["sha256"] for kind, item in source_sha.items()},
             "source_provenance_sha256": _sha(current / "provenance.json"),
             "result_access_count_in_source": 0,
             **_current_freeze(current, date, generated_at),
             **_record_time(date, analysis_at=generated_at,
                            execution_time_source="SELF_REPORTED_PROVENANCE_GENERATED_AT")}
    return _save(date, "CURRENT", value, root)


def record_b1(date: str, *, plj_path: Path, root: Path = ROOT) -> dict:
    """Use the exact existing B1 selector on an authority-bound PL+J full field."""
    formal.checked_date(date)
    if date < b1.EFFECTIVE_FROM:
        raise Stop("STOP_B1_ANALYSIS_NOT_EFFECTIVE")
    authorization_sha = _verify_b1_authorization(root)
    current, _, inputs, index, current_selected, _ = _current(date, root)
    source_sha = b1.verified_input_sources(current, inputs)
    plj = _read(plj_path)
    if (plj.get("date") != date or plj.get("result_access_count") != 0 or
            plj.get("current_pre_sha256") != _sha(current / "prediction_manifest.json") or
            plj.get("model_sha256") != b1.PL_MODEL_SHA or
            plj.get("beta_source_sha256") != b1.JOCKEY_BETA_SHA or
            plj.get("jockey_feature_sha256") != b1.JOCKEY_FEATURE_SHA or
            plj.get("beta") != b1.JOCKEY_BETA):
        raise Stop("STOP_B1_ANALYSIS_PLJ_AUTHORITY")
    races = plj.get("races")
    if not isinstance(races, list) or {r.get("race_id") for r in races} != {r["race_id"] for r in index} or len(races) != len(index):
        raise Stop("STOP_B1_ANALYSIS_RACE_SET")
    by_index = {r["race_id"]: r for r in index}
    for race in races:
        item = by_index[race["race_id"]]
        payload = _read(current / item["artifact"])
        expected = {(int(h["horse_number"]), h["horse_name"]) for h in payload["ranked_results"]}
        observed = {(int(h["horse_number"]), h["horse_name"]) for h in race["horses"]}
        if (len(observed) != len(race["horses"]) or observed != expected or
                race.get("current_k") != int(item["buy_count"])):
            raise Stop("STOP_B1_ANALYSIS_HORSE_OR_VOLUME")
    input_freeze = _plj_freeze(plj_path, date)
    selected = b1.select_b1(races, len(current_selected))
    value = {"date": date, "lane": "B1", "role": "FORMAL_ANALYSIS_DIAGNOSTIC_ONLY",
             "record_class": "ANALYSIS_ONLY",
             "selection_semantics": "PL_JOCKEY_GLOBAL_RANK_DIAGNOSTIC",
             "selection_function_sha256": _sha(Path(b1.__file__)),
             "b1_authorization_sha256": authorization_sha,
             "daily_current_buy_n": len(current_selected), "max_selected_per_race": 3,
             "selected_count": len(selected), "selected_horses": selected,
             "selected_horses_sha256": hashlib.sha256(b1.canonical(selected)).hexdigest(),
             "current_prediction_manifest_sha256": _sha(current / "prediction_manifest.json"),
             "pl_jockey_artifact_sha256": _sha(plj_path),
             "target_input_sha256": {kind: item["sha256"] for kind, item in source_sha.items()},
             "result_access_count_in_source": 0, **input_freeze, **_record_time(date)}
    return _save(date, "B1", value, root)


def _calculation_record(date: str, lane: str, output: dict, selected: list[dict],
                        source_sha: dict, calculation_path: Path, root: Path,
                        *, extra: dict | None = None) -> dict:
    if not isinstance(output, dict) or output.get("date", output.get("target_date")) != date:
        raise Stop("STOP_ANALYSIS_CALCULATION_DATE:" + lane)
    value = {"date": date, "lane": lane, "role": "FORMAL_ANALYSIS",
             "record_class": "ANALYSIS_ONLY", "calculation_status": "EXISTING_FUNCTION_EXECUTED",
             "calculation_function_sha256": _sha(calculation_path),
             "calculation_output_sha256": hashlib.sha256(b1.canonical(output)).hexdigest(),
             "calculation_output": output, "selected_count": len(selected),
             "selected_horses": selected, "input_sha256": source_sha,
             "selected_horses_sha256": hashlib.sha256(b1.canonical(selected)).hexdigest(),
             "result_access_count_in_source": 0,
             "original_freeze_at_utc": None,
             "original_freeze_time_source": "NO_FREEZE_PERFORMED",
             **(extra or {}), **_record_time(date)}
    return _save(date, lane, value, root)


def _names(current: Path, index: list[dict]) -> dict[tuple[str, int], str]:
    return {(item["race_id"], int(h["horse_number"])): h["horse_name"]
            for item in index
            for h in _read(current / item["artifact"])["ranked_results"]}


def _number_selections(races: list[dict], field: str, names: dict) -> list[dict]:
    selected = []
    for race in races:
        for number in race[field]:
            key = (race["race_id"], int(number))
            if key not in names:
                raise Stop("STOP_ANALYSIS_SELECTION_NOT_IN_CURRENT")
            selected.append({"race_id": key[0], "horse_number": key[1],
                             "horse_name": names[key]})
    if len(selected) != len({(x["race_id"], x["horse_number"]) for x in selected}):
        raise Stop("STOP_ANALYSIS_DUPLICATE_SELECTION")
    return selected


def _previous_exp024_fingerprint(date: str, root: Path) -> tuple[str | None, str]:
    old = root / f"reports/exp024_pl_same_volume/{date}_pre"
    selection_path = old / "selection.json"
    freeze_path = old / "selection_freeze.json"
    if selection_path.is_file() and freeze_path.is_file():
        selection = _read(selection_path)
        freeze = _read(freeze_path)
        if (selection.get("date") != date or
                freeze.get("selection_sha256") != _sha(selection_path)):
            raise Stop("STOP_EXP024_EXISTING_FREEZE_MISMATCH")
        return selection.get("previous_environment_fingerprint"), _sha(freeze_path)
    return formal.previous_exp024_fingerprint(date, root), "PRIOR_FORMAL_CHAIN_READ_ONLY"


def record_exp024(date: str, *, root: Path = ROOT,
                  current_path: Path | None = None) -> dict:
    """Run the existing EXP-024 build calculation, never its formal freeze."""
    if root.resolve() != ROOT.resolve():
        raise Stop("STOP_EXP024_NONCANONICAL_ROOT")
    if _sha(Path(exp024.__file__)) != EXP024_SOURCE_SHA256:
        raise Stop("STOP_EXP024_SOURCE_SHA")
    current, _, inputs, index, _, _ = _current(date, root, current_path)
    sources = (b1.verified_input_sources(current, inputs) if current_path is None
               else _analysis_current(date, current, root)[2])
    before = _sha(current / "prediction_manifest.json")
    previous_environment_fingerprint, chain_reference = _previous_exp024_fingerprint(date, root)
    output = exp024.build_pre(current, root / "knowledge",
                              previous_environment_fingerprint=previous_environment_fingerprint)
    if _sha(current / "prediction_manifest.json") != before or output.get("current_prediction_sha256") != before:
        raise Stop("STOP_EXP024_CURRENT_SOURCE_CHANGED")
    names = _names(current, index)
    selected = _number_selections(output["races"], "treatment_selected_horses", names)
    return _calculation_record(date, "EXP024", output, selected,
                               {**{k: x["sha256"] for k, x in sources.items()},
                                "prediction_manifest": before}, Path(exp024.__file__), root,
                               extra={"environment_chain_advanced": False,
                                      "environment_chain_reference": chain_reference,
                                      "previous_environment_fingerprint": previous_environment_fingerprint})


def _private_plj_for_analysis(date: str, current: Path, inputs: dict):
    """Bind only the target-entry switch in a private copy of the frozen module."""
    authorization = ROOT / "docs/KeibaAI_B1_PROSPECTIVE_EVIDENCE_AUTHORIZATION_V1.md"
    protocol = ROOT / "docs/KeibaAI_FROZEN_PL_V1_JOCKEY_OFFSET_PROVISIONAL_PROTOCOL_V1.md"
    text = authorization.read_text(encoding="utf-8")
    match = re.search(r"\| Frozen PL\+Jockey parent protocol \| `([0-9a-f]{64})` \|", text)
    if not match or _sha(protocol) != match.group(1):
        raise Stop("STOP_PL_JOCKEY_PROTOCOL_AUTHORITY_SHA")
    protocol_text = protocol.read_text(encoding="utf-8")
    for expected in (plj_module.MODEL_SHA, plj_module.BETA_SHA, plj_module.FEATURE_SHA):
        if expected not in protocol_text:
            raise Stop("STOP_PL_JOCKEY_COMPONENT_AUTHORITY_SHA")
    # The protocol pins model, beta and feature identities; the original
    # verifier checks those files and all runtime dependencies unchanged.
    plj_module.verify_identity()
    source = Path(plj_module.__file__)
    source_sha = _sha(source)
    if source_sha != PLJ_SOURCE_SHA256:
        raise Stop("STOP_PL_JOCKEY_SOURCE_MODULE_SHA")
    spec = importlib.util.spec_from_file_location("_plj_independent_analysis_" + date, source)
    if spec is None or spec.loader is None:
        raise Stop("STOP_PL_JOCKEY_PRIVATE_MODULE_LOAD")
    private = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(private)
    if _sha(source) != source_sha:
        raise Stop("STOP_PL_JOCKEY_MODULE_CHANGED_DURING_LOAD")
    original = private.validate_formal_manifest
    manifest_path = private.FORMAL_SNAPSHOT_MANIFEST
    manifest = _read(manifest_path)
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise Stop("STOP_PL_JOCKEY_FORMAL_MANIFEST_SCHEMA")
    matches = [entry for entry in entries if entry.get("date") == date]
    if len(matches) > 1:
        raise Stop("STOP_PL_JOCKEY_DUPLICATE_TARGET_ENTRY")
    prior = original(date, require_target_entry=False)
    if any(row["date"] >= date for row in prior):
        raise Stop("STOP_PL_JOCKEY_PRIOR_HISTORY_SCOPE")
    registered = bool(matches)
    if registered:
        original(date, require_target_entry=True)
        row = matches[0]
        if (row.get("current_pre_sha256") != _sha(current / "prediction_manifest.json") or
                row.get("input_manifest_sha256") != _sha(current / "input_manifest.json") or
                row.get("ds_snapshot_sha256") != inputs["sources"]["DS"]["sha256"] or
                (ROOT / row.get("current_pre_path", "")).resolve() != (current / "prediction_manifest.json").resolve() or
                (ROOT / row.get("input_manifest_path", "")).resolve() != (current / "input_manifest.json").resolve()):
            raise Stop("STOP_PL_JOCKEY_TARGET_FORMAL_ENTRY_MISMATCH")

    def analysis_validate(target_date: str, *, require_target_entry: bool = False,
                          value: dict | None = None):
        return original(target_date, require_target_entry=require_target_entry, value=value)

    private.validate_formal_manifest = analysis_validate
    return private, {"formal_target_snapshot_registered": registered,
                     "formal_snapshot_manifest_sha256": _sha(manifest_path),
                     "prior_formal_snapshot_dates": [row["date"] for row in prior],
                     "pl_jockey_protocol_sha256": _sha(protocol),
                     "pl_jockey_source_module_sha256": source_sha}


def _analysis_current(date: str, current: Path, root: Path) -> tuple[dict, list[dict], dict]:
    """Verify a non-formal Current source without fabricating a formal root."""
    if not current.resolve().is_relative_to((root / "reports").resolve()):
        raise Stop("STOP_ANALYSIS_CURRENT_PATH_SCOPE")
    rows, source = rank1_source.load_frozen_current(current, date)
    inputs = _read(current / "input_manifest.json")
    if inputs.get("date") != date or set(inputs.get("sources", {})) != {"DG", "DE", "DS"}:
        raise Stop("STOP_ANALYSIS_CURRENT_INPUT_MANIFEST")
    source_sha = {}
    for kind, item in inputs["sources"].items():
        expected = root / f"data/raw/prediction_input/{kind}{date[2:]}.CSV"
        path = (root / str(item.get("path", "")).replace("\\", "/")).resolve()
        if path != expected.resolve() or item.get("sha256") != _sha(path):
            raise Stop("STOP_ANALYSIS_CURRENT_INPUT_SHA:" + kind)
        source_sha[kind] = {"path": str(path), "sha256": item["sha256"]}
    from review.prospective_prediction_runner_v1 import _assert_population
    from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
    bundle = TargetBulkPredictionInputAdapterV1().load(
        *(Path(source_sha[kind]["path"]) for kind in ("DG", "DE", "DS")))
    _assert_population(bundle)
    index = _read(current / "race_index.json")["race_index"]
    if (bundle.date != date or set(bundle.races) != {r["race_id"] for r in index} or
            len(rows) != sum(int(r["horse_count"]) for r in index) or
            source["prediction_manifest_sha256"] != _sha(current / "prediction_manifest.json")):
        raise Stop("STOP_ANALYSIS_CURRENT_POPULATION")
    return inputs, index, source_sha


def record_pl_jockey(date: str, *, pl_prediction_path: Path,
                     root: Path = ROOT, current_path: Path | None = None) -> dict:
    """Run the existing PL+J build calculation without provisional freeze."""
    if root.resolve() != ROOT.resolve():
        raise Stop("STOP_PL_JOCKEY_NONCANONICAL_ROOT")
    if current_path is None:
        current, _, inputs, index, _, _ = _current(date, root)
        sources = b1.verified_input_sources(current, inputs)
    else:
        current = current_path.resolve()
        inputs, index, sources = _analysis_current(date, current, root)
    de = Path(sources["DE"]["path"])
    ds = Path(sources["DS"]["path"])
    pl_sha = _sha(pl_prediction_path)
    current_sha = _sha(current / "prediction_manifest.json")
    private, manifest_scope = _private_plj_for_analysis(date, current, inputs)
    output = private.build_pre(current, pl_prediction_path, de, ds)
    if (output.get("result_access_count") != 0 or
            output.get("current_pre_sha256") != current_sha or
            output.get("pl_prediction_sha256") != pl_sha or
            _sha(current / "prediction_manifest.json") != current_sha or
            any(_sha(Path(item["path"])) != item["sha256"] for item in sources.values()) or
            _sha(pl_prediction_path) != pl_sha or
            output.get("formal_snapshot_authority_manifest_sha256") != manifest_scope["formal_snapshot_manifest_sha256"] or
            _sha(private.FORMAL_SNAPSHOT_MANIFEST) != manifest_scope["formal_snapshot_manifest_sha256"]):
        raise Stop("STOP_PL_JOCKEY_CALCULATION_SOURCE_CHANGED")
    selected = _number_selections(output["races"], "candidate_selected_horses", _names(current, index))
    boundary_gaps = []
    for race in output["races"]:
        if race["provisional_fallback_race"] or race["candidate_k"] <= 0:
            continue
        ordered = sorted((float(h["candidate_p_top3"]) for h in race["horses"]), reverse=True)
        k = int(race["candidate_k"])
        if k < len(ordered):
            boundary_gaps.append(ordered[k - 1] - ordered[k])
    min_gap = min(boundary_gaps) if boundary_gaps else None
    provenance = _read(current / "provenance.json")
    current_created = _moment(provenance.get("generated_at")).astimezone(timezone.utc).isoformat()
    pl_created_raw = _read(pl_prediction_path).get("created_at")
    pl_created = (_moment(pl_created_raw).astimezone(timezone.utc).isoformat()
                  if pl_created_raw is not None else None)
    old_path = root / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{date}_pre/selection.json"
    old_ref = {"reference_formal_pl_jockey_selection_sha256": None,
               "reference_formal_pl_jockey_freeze_sha256": None,
               "reference_formal_pl_jockey_freeze_at_utc": None}
    if old_path.is_file():
        old = _read(old_path)
        frozen = _plj_freeze(old_path, date)
        if not frozen["pl_jockey_input_frozen"]:
            raise Stop("STOP_PL_JOCKEY_FORMAL_REFERENCE_NOT_FROZEN")
        if [r["race_id"] for r in output["races"]] != [r["race_id"] for r in old["races"]]:
            raise Stop("STOP_PL_JOCKEY_FORMAL_REFERENCE_RACE_SET")
        for generated_race, frozen_race in zip(output["races"], old["races"]):
            if (generated_race["candidate_selected_horses"] != frozen_race["candidate_selected_horses"] or
                    len(generated_race["horses"]) != len(frozen_race["horses"]) or
                    [int(h["horse_number"]) for h in generated_race["horses"]] !=
                    [int(h["horse_number"]) for h in frozen_race["horses"]] or
                    [h["candidate_rank"] for h in generated_race["horses"]] !=
                    [h["candidate_rank"] for h in frozen_race["horses"]] or
                    any(abs(float(h["candidate_p_top3"]) - float(f["candidate_p_top3"])) > 1e-12
                        for h, f in zip(generated_race["horses"], frozen_race["horses"]))):
                raise Stop("STOP_PL_JOCKEY_FORMAL_REFERENCE_SELECTION_MISMATCH")
        old_ref = {"reference_formal_pl_jockey_selection_sha256": _sha(old_path),
                   "reference_formal_pl_jockey_freeze_sha256": frozen["pl_jockey_freeze_audit_sha256"],
                   "reference_formal_pl_jockey_freeze_at_utc": frozen["pl_jockey_freeze_at_utc"]}
    return _calculation_record(date, "PL_JOCKEY", output, selected,
                               {**{k: x["sha256"] for k, x in sources.items()},
                                "prediction_manifest": current_sha,
                                "pl_prediction": pl_sha}, Path(plj_module.__file__), root,
                               extra={**manifest_scope,
                                      "jockey_history_pool": "PRIOR_FORMAL_ENTRIES_PLUS_CURRENT_INPUT",
                                      "jockey_history_manifest_sha256": _sha(private.HISTORY_MANIFEST),
                                      "jockey_snapshot_manifest_sha256": output.get("jockey_snapshot_manifest_sha256"),
                                      "current_prediction_created_at_utc": current_created,
                                      "pl_prediction_created_at_utc": pl_created,
                                      "selection_boundary_min_probability_gap": min_gap,
                                      "selection_boundary_near_tie_warning": min_gap is not None and min_gap < 1e-9,
                                      **old_ref})


def record_current_rank1(date: str, *, root: Path = ROOT,
                         current_path: Path | None = None) -> dict:
    """Run the existing Rank1 v2 selection calculation, never its run/freeze."""
    if root.resolve() != ROOT.resolve():
        raise Stop("STOP_RANK1_NONCANONICAL_ROOT")
    current, _, inputs, _, _, _ = _current(date, root, current_path)
    sources = (b1.verified_input_sources(current, inputs) if current_path is None
               else _analysis_current(date, current, root)[2])
    current_sha = _sha(current / "prediction_manifest.json")
    output = rank1_module.build_selection(current, date)
    if output.get("result_access_count") != 0 or output.get("input_pre_sha256") != current_sha:
        raise Stop("STOP_RANK1_CALCULATION_SOURCE_CHANGED")
    selected = [{"race_id": row["race_id"],
                 "horse_number": int(row["selected_horse_number"]),
                 "horse_name": row["selected_horse_name"],
                 "rank": row["stored_rank"]} for row in output["selections"]]
    if len(selected) != output.get("eligible_races"):
        raise Stop("STOP_RANK1_SELECTION_COUNT")
    return _calculation_record(date, "CURRENT_RANK1", output, selected,
                               {**{k: x["sha256"] for k, x in sources.items()},
                                "prediction_manifest": current_sha}, Path(rank1_module.__file__), root)


def _record_path(date: str, lane: str, root: Path) -> Path:
    formal.checked_date(date)
    if lane not in {"CURRENT", "EXP024", "PL_JOCKEY", "CURRENT_RANK1", "E1", "INDEPENDENT_V5", "A_NEW", "B1"}:
        raise Stop("STOP_ANALYSIS_RECORD_LANE")
    return (root / "reports/formal_analysis_v1" / date / f"{lane.lower()}.json").resolve()


def _fixed_calculation_source(lane: str, root: Path) -> tuple[Path, str]:
    sources = {
        "EXP024": (Path(exp024.__file__), EXP024_SOURCE_SHA256),
        "PL_JOCKEY": (Path(plj_module.__file__), PLJ_SOURCE_SHA256),
        "E1": (root / "review/formal_analysis_external_worker_v1.py", EXTERNAL_WORKER_SHA256),
        "A_NEW": (root / "review/formal_analysis_external_worker_v1.py", EXTERNAL_WORKER_SHA256),
        "INDEPENDENT_V5": (Path(independent_v5.__file__), V5_SOURCE_SHA256),
    }
    if lane not in sources:
        raise Stop("STOP_ANALYSIS_CALCULATION_LANE")
    return sources[lane]


def _verified_record(path: Path, lane: str, date: str, *, root: Path | None = None) -> tuple[dict, str]:
    trusted_root = root or ROOT
    if path.resolve() != _record_path(date, lane, trusted_root) or not path.is_file():
        raise Stop("STOP_ANALYSIS_UPSTREAM_RECORD_PATH:" + lane)
    value = _read(path)
    if (value.get("date") != date or value.get("lane") != lane or
            value.get("record_class") != "ANALYSIS_ONLY" or
            value.get("prospective_evidence_credit") != 0 or
            value.get("result_access_count_in_source") != 0):
        raise Stop("STOP_ANALYSIS_UPSTREAM_RECORD_AUTHORITY:" + lane)
    selected = value.get("selected_horses")
    if (not isinstance(selected, list) or
            value.get("selected_count") != len(selected) or
            value.get("selected_horses_sha256") != hashlib.sha256(b1.canonical(selected)).hexdigest()):
        raise Stop("STOP_ANALYSIS_UPSTREAM_SELECTION_SHA:" + lane)
    output = value.get("calculation_output")
    if (not isinstance(output, dict) or
            value.get("calculation_output_sha256") != hashlib.sha256(b1.canonical(output)).hexdigest()):
        raise Stop("STOP_ANALYSIS_UPSTREAM_OUTPUT_SHA:" + lane)
    source, expected_sha = _fixed_calculation_source(lane, trusted_root)
    if (value.get("calculation_function_sha256") != expected_sha or
            _sha(source) != expected_sha):
        raise Stop("STOP_ANALYSIS_UPSTREAM_CALCULATION_SHA:" + lane)
    if lane == "PL_JOCKEY" and value.get("pl_jockey_source_module_sha256") != PLJ_SOURCE_SHA256:
        raise Stop("STOP_ANALYSIS_UPSTREAM_PLJ_SOURCE_SHA")
    if lane == "E1" and (value.get("e1_source_module_sha256") != E1_SOURCE_SHA256 or
                         _sha(E1_SOURCE) != E1_SOURCE_SHA256):
        raise Stop("STOP_ANALYSIS_UPSTREAM_E1_SOURCE_SHA")
    if lane == "A_NEW" and (value.get("a_new_source_module_sha256") != A_NEW_SOURCE_SHA256 or
                            _sha(A_NEW_SOURCE) != A_NEW_SOURCE_SHA256):
        raise Stop("STOP_ANALYSIS_UPSTREAM_A_NEW_SOURCE_SHA")
    return value, _sha(path)


def _external(mode: str, payload: dict, root: Path) -> tuple[dict, str]:
    worker = root / "review/formal_analysis_external_worker_v1.py"
    worker_sha = _sha(worker)
    if worker_sha != EXTERNAL_WORKER_SHA256:
        raise Stop("STOP_EXTERNAL_ANALYSIS_WORKER_SHA")
    source, expected_source_sha = ((E1_SOURCE, E1_SOURCE_SHA256) if mode == "e1"
                                   else (A_NEW_SOURCE, A_NEW_SOURCE_SHA256) if mode == "a_new"
                                   else (None, None))
    if source is None or _sha(source) != expected_source_sha:
        raise Stop("STOP_EXTERNAL_ANALYSIS_SOURCE_SHA:" + mode)
    command = [sys.executable, "-I", "-c",
               "import importlib.util,sys;"
               "s=importlib.util.spec_from_file_location('_analysis_worker',sys.argv[1]);"
               "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.main()",
               str(worker)]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    process = subprocess.run(command, input=json.dumps({**payload, "mode": mode}, ensure_ascii=False),
                             text=True, capture_output=True, cwd=root, env=env, timeout=180)
    if process.returncode != 0:
        raise Stop("STOP_EXTERNAL_ANALYSIS_WORKER:" + mode + ":" + process.stderr[-700:])
    if _sha(worker) != worker_sha:
        raise Stop("STOP_ANALYSIS_WORKER_CHANGED_DURING_RUN")
    if _sha(source) != expected_source_sha:
        raise Stop("STOP_EXTERNAL_ANALYSIS_SOURCE_CHANGED_DURING_RUN:" + mode)
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise Stop("STOP_EXTERNAL_ANALYSIS_OUTPUT_JSON") from error
    if not isinstance(result, dict) or result.get("result_access_count") != 0:
        raise Stop("STOP_EXTERNAL_ANALYSIS_RESULT_ACCESS")
    return result, worker_sha


def record_e1(date: str, *, exp024_record_path: Path,
              root: Path = ROOT, current_path: Path | None = None) -> dict:
    """Apply the unchanged E1 exp024_inputs/allocate functions in a child process."""
    if root.resolve() != ROOT.resolve():
        raise Stop("STOP_E1_NONCANONICAL_ROOT")
    if _sha(E1_SOURCE) != E1_SOURCE_SHA256:
        raise Stop("STOP_E1_SOURCE_SHA")
    current, _, inputs, index, current_selected, _ = _current(date, root, current_path)
    sources = (b1.verified_input_sources(current, inputs) if current_path is None
               else _analysis_current(date, current, root)[2])
    exp_record, exp_record_sha = _verified_record(exp024_record_path, "EXP024", date, root=root)
    exp_output = exp_record["calculation_output"]
    if (exp_output.get("current_prediction_sha256") != _sha(current / "prediction_manifest.json") or
            exp_record.get("input_sha256", {}).get("prediction_manifest") != _sha(current / "prediction_manifest.json") or
            any(exp_record.get("input_sha256", {}).get(k) != v["sha256"] for k, v in sources.items()) or
            _number_selections(exp_output["races"], "treatment_selected_horses", _names(current, index)) != exp_record["selected_horses"]):
        raise Stop("STOP_E1_EXP024_CURRENT_SOURCE")
    output, worker_sha = _external("e1", {"date": date, "exp024": exp_output,
                                           "current_n": len(current_selected),
                                           "horse_count": sum(int(r["horse_count"]) for r in index)}, root)
    if output.get("daily_n") != len(current_selected) or len(output.get("selected_horses", [])) != len(current_selected):
        raise Stop("STOP_E1_ANALYSIS_VOLUME")
    selected = output["selected_horses"]
    return _calculation_record(date, "E1", output, selected,
                               {**{k: v["sha256"] for k, v in sources.items()},
                                "prediction_manifest": _sha(current / "prediction_manifest.json"),
                                "exp024_analysis_record": exp_record_sha},
                               root / "review/formal_analysis_external_worker_v1.py", root,
                               extra={"external_worker_sha256": worker_sha,
                                      "e1_source_module_sha256": _sha(E1_SOURCE),
                                      "parent_sys_path_unchanged_by_worker": True})


def record_independent_v5(date: str, *, root: Path = ROOT,
                          current_path: Path | None = None) -> dict:
    """Recompose the existing V5 PRE row generation, then call select_rows."""
    if root.resolve() != ROOT.resolve():
        raise Stop("STOP_V5_NONCANONICAL_ROOT")
    if _sha(Path(independent_v5.__file__)) != V5_SOURCE_SHA256:
        raise Stop("STOP_V5_SOURCE_SHA")
    current, _, inputs, index, _, generated_at = _current(date, root, current_path)
    sources = (b1.verified_input_sources(current, inputs) if current_path is None
               else _analysis_current(date, current, root)[2])
    protocol = independent_v5.load_protocol()
    if date < protocol["human_approval_date"] or generated_at.astimezone(JST).strftime("%Y%m%d") < protocol["human_approval_date"]:
        raise Stop("STOP_V5_APPROVAL_DATE")
    model, scaler, model_identity, _ = daily_v5.load_active_daily_v4()
    if model_identity["model_sha256"] != protocol["model"]["model_sha256"]:
        raise Stop("STOP_V5_MODEL_AUTHORITY")
    records = []
    selected = []
    for item in index:
        payload = _read(current / item["artifact"])
        independent_v5.assert_result_free(payload)
        race = payload["buy_gate_trace"]["race"]
        state = race["shadow_race_state"]
        trace = {int(x["horse_number"]): x for x in payload["buy_gate_trace"]["horses"]}
        candidates = []
        for horse in payload["top5"]:
            number = int(horse["horse_number"])
            item_trace = trace[number]
            feature = daily_v5.vector(horse, item_trace, state, f"{payload['race_id']}:{number}")
            probability = float(model.predict_proba(scaler.transform(np.asarray([feature], dtype=float)))[0, 1])
            candidates.append({"horse_number": number, "horse_name": horse.get("horse_name"),
                               "current_top5": True,
                               "shadow_ai_rank": daily_v5.safe_rank(item_trace["shadow_ai_rank"], payload["race_id"]),
                               "risk_guard_pass": item_trace["risk_guard_pass"], "p_top3": probability})
        choices = independent_v5.select_rows(candidates, protocol["tau"])
        records.append({"race_id": payload["race_id"], "candidate_horses": candidates,
                        "selected_horses": choices, "tau": protocol["tau"],
                        "current_race_state": state})
        selected.extend({"race_id": payload["race_id"], **row} for row in choices)
    output = {"date": date, "lane": "INDEPENDENT_V5", "role": "ANALYSIS_ONLY",
              "protocol_sha256": _sha(independent_v5.PROTOCOL),
              "model_identity": model_identity, "races": records,
              "selected_horses": selected, "result_access_count": 0}
    if _sha(Path(independent_v5.__file__)) != V5_SOURCE_SHA256:
        raise Stop("STOP_V5_SOURCE_CHANGED_DURING_RUN")
    return _calculation_record(date, "INDEPENDENT_V5", output, selected,
                               {**{k: v["sha256"] for k, v in sources.items()},
                                "prediction_manifest": _sha(current / "prediction_manifest.json")},
                               Path(independent_v5.__file__), root)


def record_a_new(date: str, *, pl_jockey_record_path: Path,
                 root: Path = ROOT, current_path: Path | None = None) -> dict:
    """Run frozen A_new model/feature/probability functions without formal state."""
    if root.resolve() != ROOT.resolve():
        raise Stop("STOP_A_NEW_NONCANONICAL_ROOT")
    if _sha(A_NEW_SOURCE) != A_NEW_SOURCE_SHA256:
        raise Stop("STOP_A_NEW_SOURCE_SHA")
    current, _, inputs, index, _, _ = _current(date, root, current_path)
    sources = (b1.verified_input_sources(current, inputs) if current_path is None
               else _analysis_current(date, current, root)[2])
    plj_record, plj_record_sha = _verified_record(pl_jockey_record_path, "PL_JOCKEY", date, root=root)
    plj_output = plj_record["calculation_output"]
    if (plj_output.get("current_pre_sha256") != _sha(current / "prediction_manifest.json") or
            plj_record.get("input_sha256", {}).get("prediction_manifest") != _sha(current / "prediction_manifest.json") or
            any(plj_record.get("input_sha256", {}).get(k) != v["sha256"] for k, v in sources.items()) or
            _number_selections(plj_output["races"], "candidate_selected_horses", _names(current, index)) != plj_record["selected_horses"]):
        raise Stop("STOP_A_NEW_PLJ_CURRENT_SOURCE")
    output, worker_sha = _external("a_new", {"date": date, "current_root": str(current),
                                              "pl_jockey": plj_output}, root)
    selected = _number_selections(output["races"], "a_new_selected_horses", _names(current, index))
    if len(selected) != output.get("selected_count"):
        raise Stop("STOP_A_NEW_ANALYSIS_SELECTED_COUNT")
    return _calculation_record(date, "A_NEW", output, selected,
                               {**{k: v["sha256"] for k, v in sources.items()},
                                "prediction_manifest": _sha(current / "prediction_manifest.json"),
                                "pl_jockey_analysis_record": plj_record_sha},
                               root / "review/formal_analysis_external_worker_v1.py", root,
                               extra={"external_worker_sha256": worker_sha,
                                      "a_new_source_module_sha256": _sha(A_NEW_SOURCE)})


def record_b1_from_analysis(date: str, *, current_record_path: Path,
                            pl_jockey_record_path: Path, e1_record_path: Path,
                            root: Path = ROOT) -> dict:
    """Feed verified analysis records to the unchanged B1 selector, never freeze_pre."""
    formal.checked_date(date)
    if date < b1.EFFECTIVE_FROM:
        raise Stop("STOP_B1_ANALYSIS_NOT_EFFECTIVE")
    if root.resolve() != ROOT.resolve():
        raise Stop("STOP_B1_NONCANONICAL_ROOT")
    authorization_sha = _verify_b1_authorization(root)
    if current_record_path.resolve() != _record_path(date, "CURRENT", root) or not current_record_path.is_file():
        raise Stop("STOP_B1_ANALYSIS_CURRENT_RECORD_PATH")
    current_record = _read(current_record_path)
    if (current_record.get("date") != date or current_record.get("lane") != "CURRENT" or
            current_record.get("record_class") != "ANALYSIS_ONLY" or
            current_record.get("prospective_evidence_credit") != 0 or
            current_record.get("result_access_count_in_source") != 0 or
            current_record.get("selected_horses_sha256") !=
            hashlib.sha256(b1.canonical(current_record.get("selected_horses"))).hexdigest()):
        raise Stop("STOP_B1_ANALYSIS_CURRENT_RECORD")
    current_path = Path(current_record["source_current_path"])
    current, _, inputs, index, current_selected, _ = _current(date, root, current_path)
    sources = _analysis_current(date, current, root)[2]
    current_sha = _sha(current / "prediction_manifest.json")
    if (current_record.get("prediction_manifest_sha256") != current_sha or
            current_record.get("input_manifest_sha256") != _sha(current / "input_manifest.json") or
            current_record.get("source_provenance_sha256") != _sha(current / "provenance.json") or
            current_record.get("target_input_sha256") !=
            {kind: row["sha256"] for kind, row in sources.items()} or
            current_record["selected_horses"] != current_selected):
        raise Stop("STOP_B1_ANALYSIS_CURRENT_AUTHORITY")
    plj_record, plj_record_sha = _verified_record(pl_jockey_record_path, "PL_JOCKEY", date, root=root)
    e1_record, e1_record_sha = _verified_record(e1_record_path, "E1", date, root=root)
    plj = plj_record["calculation_output"]
    e1 = e1_record["calculation_output"]
    if (plj.get("current_pre_sha256") != current_sha or
            plj.get("result_access_count") != 0 or
            plj.get("model_sha256") != b1.PL_MODEL_SHA or
            plj.get("beta_source_sha256") != b1.JOCKEY_BETA_SHA or
            plj.get("jockey_feature_sha256") != b1.JOCKEY_FEATURE_SHA or
            plj.get("beta") != b1.JOCKEY_BETA or
            e1.get("result_access_count") != 0 or
            e1.get("frozen_pl_model_sha256") != b1.PL_MODEL_SHA or
            e1_record.get("input_sha256", {}).get("prediction_manifest") != current_sha or
            any(plj_record.get("input_sha256", {}).get(k) != v["sha256"] or
                e1_record.get("input_sha256", {}).get(k) != v["sha256"]
                for k, v in sources.items()) or
            e1.get("daily_n") != len(current_selected) or
            e1.get("selected_horses") != e1_record.get("selected_horses")):
        raise Stop("STOP_B1_ANALYSIS_UPSTREAM_AUTHORITY")
    races = plj.get("races")
    if (not isinstance(races, list) or len(races) != len(index) or
            {r["race_id"] for r in races} != {r["race_id"] for r in index} or
            set(e1.get("eligible_races", [])) != {r["race_id"] for r in index}):
        raise Stop("STOP_B1_ANALYSIS_RACE_SET")
    by_index = {r["race_id"]: r for r in index}
    if _number_selections(races, "candidate_selected_horses", _names(current, index)) != plj_record.get("selected_horses"):
        raise Stop("STOP_B1_ANALYSIS_PLJ_SELECTION_RECORD")
    for race in races:
        item = by_index[race["race_id"]]
        field = {(int(h["horse_number"]), h["horse_name"])
                 for h in _read(current / item["artifact"])["ranked_results"]}
        observed = {(int(h["horse_number"]), h["horse_name"]) for h in race["horses"]}
        if (observed != field or len(observed) != len(race["horses"]) or
                int(race["current_k"]) != int(item["buy_count"]) or
                any(not math.isfinite(float(h["candidate_p_top3"])) or
                    not 0 <= float(h["candidate_p_top3"]) <= 1 for h in race["horses"])):
            raise Stop("STOP_B1_ANALYSIS_HORSE_PROBABILITY_OR_VOLUME")
    selected = b1.select_b1(races, len(current_selected))
    value = {"date": date, "lane": "B1", "role": "FORMAL_ANALYSIS_DIAGNOSTIC_ONLY",
             "record_class": "ANALYSIS_ONLY", "selection_semantics": "PL_JOCKEY_GLOBAL_RANK_DIAGNOSTIC",
             "selection_function_sha256": _sha(Path(b1.__file__)),
             "b1_authorization_sha256": authorization_sha,
             "daily_current_buy_n": len(current_selected), "max_selected_per_race": 3,
             "selected_count": len(selected), "selected_horses": selected,
             "selected_horses_sha256": hashlib.sha256(b1.canonical(selected)).hexdigest(),
             "current_analysis_record_sha256": _sha(current_record_path),
             "pl_jockey_analysis_record_sha256": plj_record_sha,
             "e1_analysis_record_sha256": e1_record_sha,
             "current_prediction_manifest_sha256": current_sha,
             "pl_jockey_calculation_output_sha256": plj_record["calculation_output_sha256"],
             "target_input_sha256": {kind: row["sha256"] for kind, row in sources.items()},
             "result_access_count_in_source": 0, "upstream_formal_freeze_required": False,
             **_record_time(date)}
    return _save(date, "B1", value, root)
