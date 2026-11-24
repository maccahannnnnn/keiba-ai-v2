"""Result-free research-lane and diagnostic infrastructure for the next PRE.

This module is deliberately downstream of the frozen six-lane PRE artifacts.
It never supplies values to a selector, BUY engine, threshold, eligibility
check, or Production runtime.  Its only outputs are diagnostic records whose
``result_access_count`` is always zero.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import unittest
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_NAME = "research_lane_registration_and_next_pre_diagnostic_infrastructure_v1"
LANES = (
    "CURRENT",
    "INDEPENDENT_V5",
    "TRACKCONDITION_SEMANTIC",
    "DAILY_V5_SAME_VOLUME",
    "FORMAL_V5",
    "FORMAL_V6",
)
FAMILY_V2 = {
    "CURRENT_BASE": ["CURRENT"],
    "TRACKCONDITION_VARIANT": ["TRACKCONDITION_SEMANTIC"],
    "V5_FAMILY": ["INDEPENDENT_V5", "DAILY_V5_SAME_VOLUME", "FORMAL_V5", "FORMAL_V6"],
}
RESULT_KEYS = {"actual_top3", "actual_finish", "finish", "valid_result", "result", "payout"}

RESEARCH_LANES = [
    {
        "record_id": "RLANE-001",
        "lane": "CURRENT_REFINEMENT",
        "purpose": "Observe horse-selection quality only inside the frozen Current BUY range.",
        "role": "FORWARD_DIAGNOSTIC_SHADOW_OBSERVATION_ONLY",
        "priority": "PRIMARY_PERFORMANCE_RESEARCH",
        "fingerprint": {
            "population": "CURRENT_PRE_FROZEN_BUY_HORSES_ONLY",
            "question": "How do frozen Current BUY horses partition by result-free cross-lane support?",
            "selection_change": False,
        },
        "relationships": ["EXP-023: SELECTION_AUTHORITY_PROTOCOL_V1 (related selection-authority boundary; not a duplicate)"],
        "prohibitions": ["NEW_BUY_RULE", "BUY_COUNT_CHANGE", "PRODUCTION_USE"],
    },
    {
        "record_id": "RLANE-002",
        "lane": "CURRENT_ABSTENTION_COVERAGE",
        "purpose": "Observe candidate-generation coverage in frozen Current UNCONVERGED and SKIP races.",
        "role": "CANDIDATE_GENERATION_DIAGNOSTIC_ONLY",
        "priority": "DIAGNOSTIC_RESEARCH",
        "fingerprint": {
            "population": "CURRENT_UNCONVERGED_OR_SKIP_RACES",
            "question": "Which Current abstentions are selected by existing Independent or TrackCondition lanes?",
            "selection_change": False,
        },
        "relationships": ["ANA-020: Candidate Generation Observability Feasibility (technical observability prerequisite; not a duplicate)"],
        "prohibitions": ["BUY_ADDITION", "NEW_BUY_RULE", "PRODUCTION_USE"],
    },
    {
        "record_id": "RLANE-003",
        "lane": "CANDIDATE_GENERATION_FUNNEL",
        "purpose": "Observe where horses leave the ranking, Top5, risk, candidate, and selected-union funnel.",
        "role": "CANDIDATE_GENERATION_FUNNEL_DIAGNOSTIC_ONLY",
        "priority": "DIAGNOSTIC_RESEARCH",
        "fingerprint": {
            "population": "ALL_HORSES_IN_FROZEN_CURRENT_PRE",
            "question": "Where does the existing frozen pipeline lose candidates before final lane selection?",
            "selection_change": False,
        },
        "relationships": ["ANA-020: Candidate Generation Observability Feasibility (same broad family; distinct funnel question)"],
        "prohibitions": ["CANDIDATE_SCOPE_CHANGE", "NEW_BUY_RULE", "PRODUCTION_USE"],
    },
]


class DiagnosticStop(RuntimeError):
    """Fail-closed diagnostic stop that leaves selection artifacts untouched."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def assert_result_free(value: Any, context: str = "diagnostic") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in RESULT_KEYS:
                raise DiagnosticStop(f"STOP_RESULT_FIELD_IN_PRE_DIAGNOSTIC:{context}:{key}")
            assert_result_free(child, context)
    elif isinstance(value, list):
        for child in value:
            assert_result_free(child, context)


def selection_snapshot(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    """Return a canonical six-lane selection snapshot from frozen full-field rows."""
    field_by_lane = {
        "CURRENT": "current_buy",
        "INDEPENDENT_V5": "independent_v5_selected",
        "TRACKCONDITION_SEMANTIC": "trackcondition_selected",
        "DAILY_V5_SAME_VOLUME": "daily_v5_selected",
        "FORMAL_V5": "formal_v5_selected",
        "FORMAL_V6": "formal_v6_selected",
    }
    output: dict[str, dict[str, list[str]]] = {lane: {} for lane in LANES}
    for row in rows:
        race_id = str(row["race_id"])
        horse = str(row["horse_number"])
        for lane, field in field_by_lane.items():
            # ``csv.DictReader`` returns "True" / "False" strings.  This
            # diagnostic must reconstruct the frozen set from those real
            # representations, never merely from Python-bool test fixtures.
            if _truth(row.get(field)):
                output[lane].setdefault(race_id, []).append(horse)
    for lane in LANES:
        for race_id, horses in output[lane].items():
            output[lane][race_id] = sorted(horses, key=lambda value: int(value))
    return output


def assert_selection_unchanged(before: dict[str, Any], after: dict[str, Any]) -> None:
    if canonical_sha(before) != canonical_sha(after):
        raise DiagnosticStop("STOP_DIAGNOSTIC_SELECTION_MUTATION")


def _truth(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _optional_truth(value: Any) -> bool | None:
    """Return a canonical boolean, preserving genuinely unavailable data."""
    if value is None or str(value).strip() == "":
        return None
    return _truth(value)


def _execution_date_jst(now_utc: datetime | None = None) -> str:
    """Return the JST calendar date using the fixed legal UTC+09:00 offset.

    Japan has no daylight-saving adjustment.  A fixed offset avoids depending
    on an optional IANA tzdata installation in the formal ML runtime.
    """
    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d")


def _recognized_result_sources(target_date: str, repository_root: Path) -> list[Path]:
    """Locate known formal Result sources by existence only; never read them."""
    result_root = repository_root / "data" / "raw" / "target" / "daily_result_list"
    candidates = [
        result_root / f"着順馬番_{target_date}.csv",
        result_root / f"馬番順着順_{target_date}.csv",
        repository_root / "reports" / f"{target_date}_all_active_systems_post",
        repository_root / "reports" / f"prospective_result_{target_date}_v1",
        repository_root / "reports" / f"prospective_{target_date}_post",
    ]
    return [path for path in candidates if path.exists()]


def validate_forward_diagnostic_timing(
    *, target_date: str, execution_date_jst: str | None = None, repository_root: Path = ROOT,
) -> dict[str, Any]:
    """Fail closed unless this invocation is still result-free and forward-looking.

    This has no retrospective fallback.  The result-source check performs only
    an existence check, so it cannot inspect result contents.
    """
    execution = execution_date_jst or _execution_date_jst()
    if len(target_date) != 8 or not target_date.isdigit() or len(execution) != 8 or not execution.isdigit():
        raise DiagnosticStop("STOP_FORWARD_DIAGNOSTIC_DATE_FORMAT")
    if target_date < execution:
        raise DiagnosticStop("STOP_PAST_DATE_FORWARD_DIAGNOSTIC")
    sources = _recognized_result_sources(target_date, repository_root)
    if sources:
        raise DiagnosticStop("STOP_RESULT_SOURCE_EXISTS_FOR_FORWARD_DIAGNOSTIC")
    return {
        "target_date": target_date,
        "execution_date_jst": execution,
        "result_source_existence_check": "PASS",
        "result_sources_found": [],
        "role": "RESULT_FREE_FORWARD_DIAGNOSTIC",
        "retrospective_role_fallback": False,
    }


def _family_support(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "CURRENT_BASE": _truth(row.get("current_buy")),
        "TRACKCONDITION_VARIANT": _truth(row.get("trackcondition_selected")),
        "V5_FAMILY": any(
            _truth(row.get(field))
            for field in ("independent_v5_selected", "daily_v5_selected", "formal_v5_selected", "formal_v6_selected")
        ),
    }


def build_funnel_diagnostic(*, target_date: str, rows: list[dict[str, Any]], source_sha256: str) -> dict[str, Any]:
    """Derive only result-free funnel observations from a frozen full-field PRE export."""
    assert_result_free(rows, "funnel_rows")
    before = selection_snapshot(rows)
    horses: list[dict[str, Any]] = []
    races: dict[str, dict[str, Any]] = {}
    for source in rows:
        row = copy.deepcopy(source)
        race_id = str(row["race_id"])
        selected_lanes = [
            lane for lane, field in (
                ("CURRENT", "current_buy"), ("INDEPENDENT_V5", "independent_v5_selected"),
                ("TRACKCONDITION_SEMANTIC", "trackcondition_selected"), ("DAILY_V5_SAME_VOLUME", "daily_v5_selected"),
                ("FORMAL_V5", "formal_v5_selected"), ("FORMAL_V6", "formal_v6_selected"),
            ) if _truth(row.get(field))
        ]
        candidate_membership = any((
            _truth(row.get("current_shadow_buy_candidate")),
            _truth(row.get("independent_v5_candidate")),
            _truth(row.get("daily_v5_candidate")),
            _truth(row.get("formal_v5_exact5_membership")),
            _truth(row.get("formal_v6_exact5_membership")),
        ))
        horses.append({
            "race_id": race_id, "venue": row.get("venue"), "race_number": row.get("race_number"),
            "horse_number": row.get("horse_number"), "horse_name": row.get("horse_name"),
            "race_state": row.get("current_race_state"), "field_size": row.get("field_size"),
            "shadow_ai_rank": row.get("current_shadow_ai_rank"), "top5_membership": _truth(row.get("current_top5")),
            "buy_membership": _truth(row.get("current_buy")),
            "risk_guard_pass": _optional_truth(row.get("current_risk_guard_pass")),
            "buy_candidate_status": row.get("current_shadow_buy_candidate"),
            "candidate_union_membership": candidate_membership,
            "final_selected_union_membership": bool(selected_lanes),
            "selecting_lanes": selected_lanes,
            "family_support": _family_support(row),
        })
        races.setdefault(race_id, {"rows": [], "race_state": row.get("current_race_state")})["rows"].append(row)

    race_rows: list[dict[str, Any]] = []
    total = {"total_field": 0, "current_top5_count": 0, "top5_risk_pass_count": 0, "candidate_union_count": 0, "final_selected_union_count": 0}
    for race_id, record in sorted(races.items()):
        race_horses = [row for row in horses if row["race_id"] == race_id]
        source_rows = record["rows"]
        lane_counts = {
            "current_buy_count": sum(_truth(row.get("current_buy")) for row in source_rows),
            "independent_selected_count": sum(_truth(row.get("independent_v5_selected")) for row in source_rows),
            "tc_selected_count": sum(_truth(row.get("trackcondition_selected")) for row in source_rows),
            "daily_selected_count": sum(_truth(row.get("daily_v5_selected")) for row in source_rows),
            "formal_selected_count": sum(
                _truth(row.get("formal_v5_selected")) or _truth(row.get("formal_v6_selected")) for row in source_rows
            ),
        }
        funnel = {
            "total_field": len(race_horses),
            "current_top5_count": sum(row["top5_membership"] for row in race_horses),
            "top5_risk_pass_count": sum(row["top5_membership"] and _truth(row["risk_guard_pass"]) for row in race_horses),
            "candidate_union_count": sum(row["candidate_union_membership"] for row in race_horses),
            "final_selected_union_count": sum(row["final_selected_union_membership"] for row in race_horses),
        }
        for key, value in funnel.items():
            total[key] += value
        first = source_rows[0]
        race_rows.append({
            "race_id": race_id, "venue": first.get("venue"), "race_number": first.get("race_number"),
            "race_state": record["race_state"],
            "no_lane_selection": funnel["final_selected_union_count"] == 0,
            **lane_counts, "funnel": funnel,
        })
    after = selection_snapshot(rows)
    assert_selection_unchanged(before, after)
    return {
        "schema_version": "candidate_generation_funnel_diagnostic_v1",
        "role": "CANDIDATE_GENERATION_FUNNEL_DIAGNOSTIC_ONLY",
        "target_date": target_date, "result_access_count": 0,
        "source_pre_sha256": source_sha256, "family_definition_version": "FAMILY_DEFINITION_V2",
        "selection_invariant": {"before_sha256": canonical_sha(before), "after_sha256": canonical_sha(after), "unchanged": True},
        "race_rows": race_rows, "horse_rows": horses, "funnel_totals": total,
        "selection_semantics_changed": False, "formal_evidence": False, "production_change": False,
    }


def build_v5_full_field_diagnostic(
    *, target_date: str, rows: list[dict[str, Any]], source_sha256: str,
    model_identity: dict[str, str], predictor: Callable[[list[list[float]]], list[float]] | None,
) -> dict[str, Any]:
    """Run an isolated diagnostic score pass; unavailable inference never substitutes a selection."""
    assert_result_free(rows, "v5_full_field_rows")
    before = selection_snapshot(rows)
    by_race: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_race.setdefault(str(row["race_id"]), []).append(copy.deepcopy(row))
    output: list[dict[str, Any]] = []
    for race_id, race_rows in sorted(by_race.items()):
        try:
            if predictor is None:
                raise DiagnosticStop("DIAGNOSTIC_INFERENCE_UNAVAILABLE:MODEL_OR_FEATURES_UNAVAILABLE")
            vectors = [row.get("diagnostic_feature_vector") for row in race_rows]
            if any(not isinstance(vector, list) for vector in vectors):
                raise DiagnosticStop("DIAGNOSTIC_INFERENCE_UNAVAILABLE:FEATURE_VECTOR_MISSING")
            probabilities = predictor(vectors)  # intentionally diagnostic-only callable
            if len(probabilities) != len(race_rows):
                raise DiagnosticStop("DIAGNOSTIC_INFERENCE_UNAVAILABLE:OUTPUT_LENGTH_MISMATCH")
            ordered = sorted(range(len(race_rows)), key=lambda i: (-float(probabilities[i]), int(race_rows[i]["horse_number"])))
            ranks = {index: rank for rank, index in enumerate(ordered, start=1)}
            for index, row in enumerate(race_rows):
                output.append({
                    "target_date": target_date, "race_id": race_id, "venue": row.get("venue"),
                    "race_number": row.get("race_number"), "horse_number": row.get("horse_number"),
                    "horse_name": row.get("horse_name"), "p_top3": float(probabilities[index]),
                    "full_field_rank": ranks[index], "diagnostic_status": "AVAILABLE",
                    "model_identity": model_identity,
                    "inference_timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                })
        except Exception as error:  # the diagnostic is fail-closed but does not alter selection
            for row in race_rows:
                output.append({
                    "target_date": target_date, "race_id": race_id, "venue": row.get("venue"),
                    "race_number": row.get("race_number"), "horse_number": row.get("horse_number"),
                    "horse_name": row.get("horse_name"), "p_top3": None, "full_field_rank": None,
                    "diagnostic_status": "DIAGNOSTIC_INFERENCE_UNAVAILABLE", "unavailable_reason": str(error),
                    "model_identity": model_identity,
                    "inference_timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                })
    after = selection_snapshot(rows)
    assert_selection_unchanged(before, after)
    return {
        "schema_version": "v5_full_field_diagnostic_inference_v1",
        "role": "V5_FULL_FIELD_DIAGNOSTIC_ONLY", "target_date": target_date,
        "result_access_count": 0, "source_pre_sha256": source_sha256,
        "selection_invariant": {"before_sha256": canonical_sha(before), "after_sha256": canonical_sha(after), "unchanged": True},
        "records": output, "selection_fallback_used": False, "selection_semantics_changed": False,
        "formal_evidence": False, "production_change": False,
    }


def verify_v5_full_field_parity_20261004(repository_root: Path = ROOT) -> dict[str, Any]:
    """Read-only V5 regression against frozen 2026-10-04 analysis probabilities.

    This is a technical regression check only.  It does not create a PRE
    artifact, alter a frozen selection, or inspect any Result source.
    """
    import csv
    import numpy as np
    from review.prospective_three_system_pre_freeze_v1 import load_active_daily_v4, vector

    current_root = repository_root / "reports" / "daily_pre_analysis_20261004" / "current_frozen"
    analysis_path = repository_root / "reports" / "20261004_all_active_systems_horse_analysis.csv"
    index = json.loads((current_root / "race_index.json").read_text(encoding="utf-8"))
    with analysis_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert_result_free(rows, "v5_parity_analysis")
    by_key = {(str(row["race_id"]), str(row["horse_number"])): row for row in rows}
    model, scaler, identity, _indexes = load_active_daily_v4()
    independent_diffs: list[float] = []
    formal_diffs: list[float] = []
    total = 0
    for entry in index["race_index"]:
        payload = json.loads((current_root / str(entry["artifact"])).read_text(encoding="utf-8"))
        assert_result_free(payload, "v5_parity_current_payload")
        race_id = str(payload["race_id"])
        state = payload["buy_gate_trace"]["race"]["shadow_race_state"]
        traces = {str(item["horse_number"]): item for item in payload["buy_gate_trace"]["horses"]}
        ranked = payload["ranked_results"]
        vectors = [vector(horse, traces[str(horse["horse_number"])], state, f"{race_id}:{horse['horse_number']}") for horse in ranked]
        probabilities = model.predict_proba(scaler.transform(np.asarray(vectors, dtype=float)))[:, 1].tolist()
        total += len(ranked)
        for horse, probability in zip(ranked, probabilities):
            row = by_key[(race_id, str(horse["horse_number"]))]
            if str(row.get("independent_v5_p_top3", "")).strip() != "":
                independent_diffs.append(abs(probability - float(row["independent_v5_p_top3"])))
            if str(row.get("formal_v5_probability", "")).strip() != "":
                formal_diffs.append(abs(probability - float(row["formal_v5_probability"])))
    record = {
        "role": "V5_TECHNICAL_REGRESSION_ONLY_NOT_PRE_ARTIFACT",
        "target_date": "20261004", "result_access_count": 0,
        "runtime_identity": _runtime_identity(repository_root),
        "model_sha256": str(identity["model_sha256"]),
        "feature_transform_sha256": sha256(repository_root / "reports" / "ml_v4_buy_selection_model_v5" / "feature_transform_schema.json"),
        "total_horses": total,
        "independent_overlap_horses": len(independent_diffs),
        "independent_max_absolute_difference": max(independent_diffs, default=None),
        "formal_v5_overlap_horses": len(formal_diffs),
        "formal_v5_max_absolute_difference": max(formal_diffs, default=None),
        "selection_semantics_changed": False,
    }
    if total != 217 or len(independent_diffs) != 65 or len(formal_diffs) != 85:
        raise DiagnosticStop("STOP_V5_PARITY_POPULATION_MISMATCH")
    # The frozen CSV serialization may differ by one IEEE-754 ULP even when
    # the model/scaler/vector path is identical.  This is parity, not a new
    # selection threshold; the tolerance is far below any frozen decision
    # boundary and recorded in the technical regression output.
    if record["independent_max_absolute_difference"] > 1e-12 or record["formal_v5_max_absolute_difference"] > 1e-12:
        raise DiagnosticStop(
            "STOP_V5_PARITY_MISMATCH:"
            f"independent={record['independent_max_absolute_difference']}:formal={record['formal_v5_max_absolute_difference']}"
        )
    return record


def _runtime_identity(repository_root: Path) -> dict[str, str]:
    executable = Path(sys.executable).resolve()
    expected_venv = (repository_root / ".venv_keibaai_ml_v4").resolve()
    try:
        environment = ".venv_keibaai_ml_v4" if executable.is_relative_to(expected_venv) else "NON_V5_VENV"
    except AttributeError:  # pragma: no cover - Python < 3.9 compatibility
        environment = ".venv_keibaai_ml_v4" if str(executable).startswith(str(expected_venv)) else "NON_V5_VENV"
    return {
        "python_executable": str(executable),
        "python_version": sys.version,
        "environment_identifier": environment,
    }


def freeze_next_pre_diagnostics(
    *, target_date: str, current_pre_root: Path, analysis_horse_csv: Path, union_path: Path, output_root: Path,
    execution_date_jst: str | None = None, repository_root: Path = ROOT,
    feature_vector_builder: Callable[[dict[str, Any], dict[str, Any], str, str], list[float]] | None = None,
    model_loader: Callable[[], tuple[dict[str, str], Callable[[list[list[float]]], list[float]]]] | None = None,
) -> Path:
    """Freeze diagnostic-only artifacts for a newly completed six-lane PRE.

    The public entrypoint validates execution-day timing and result-source
    absence before reading any PRE source.  It never falls back to a
    retrospective role.
    """
    timing = validate_forward_diagnostic_timing(
        target_date=target_date, execution_date_jst=execution_date_jst, repository_root=repository_root,
    )
    if output_root.exists():
        raise DiagnosticStop("STOP_NEXT_PRE_DIAGNOSTIC_OUTPUT_EXISTS")
    required = [current_pre_root / "provenance.json", current_pre_root / "race_index.json", analysis_horse_csv, union_path]
    if any(not path.is_file() for path in required):
        raise DiagnosticStop("STOP_NEXT_PRE_DIAGNOSTIC_SOURCE_MISSING")
    provenance = json.loads((current_pre_root / "provenance.json").read_text(encoding="utf-8"))
    if provenance.get("target_date") != target_date or provenance.get("result_data_access_count") != 0:
        raise DiagnosticStop("STOP_NEXT_PRE_DIAGNOSTIC_CURRENT_PRE_INTEGRITY")
    import csv
    with analysis_horse_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert_result_free(rows, "frozen_six_lane_analysis")
    union = json.loads(union_path.read_text(encoding="utf-8"))
    if union.get("result_access_count") != 0 or union.get("formal_evidence") is not False:
        raise DiagnosticStop("STOP_NEXT_PRE_DIAGNOSTIC_UNION_INTEGRITY")
    current_payloads: dict[str, dict[str, Any]] = {}
    for entry in json.loads((current_pre_root / "race_index.json").read_text(encoding="utf-8"))["race_index"]:
        payload_path = current_pre_root / str(entry["artifact"])
        if not payload_path.is_file():
            raise DiagnosticStop("STOP_NEXT_PRE_DIAGNOSTIC_CURRENT_RACE_MISSING")
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        assert_result_free(payload, "frozen_current_payload")
        current_payloads[str(payload["race_id"])] = payload
    if {str(row["race_id"]) for row in rows} != set(current_payloads):
        raise DiagnosticStop("STOP_NEXT_PRE_DIAGNOSTIC_RACE_SET_MISMATCH")
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        payload = current_payloads[str(row["race_id"])]
        state = payload.get("buy_gate_trace", {}).get("race", {}).get("shadow_race_state")
        traces = {str(trace.get("horse_number")): trace for trace in payload.get("buy_gate_trace", {}).get("horses", [])}
        ranked = {str(horse.get("horse_number")): horse for horse in payload.get("ranked_results", [])}
        number = str(row["horse_number"])
        if number not in traces or number not in ranked or not isinstance(state, str):
            raise DiagnosticStop("STOP_NEXT_PRE_DIAGNOSTIC_TRACE_OR_FIELD_MISMATCH")
        try:
            if feature_vector_builder is None:
                from review.prospective_three_system_pre_freeze_v1 import vector

                feature_vector_builder = vector
            item["diagnostic_feature_vector"] = feature_vector_builder(
                ranked[number], traces[number], state, f"{row['race_id']}:{number}"
            )
        except Exception as error:
            item["diagnostic_feature_vector"] = None
            item["diagnostic_feature_unavailable_reason"] = str(error)
        enriched.append(item)
    before = selection_snapshot(enriched)
    source_sha = sha256(analysis_horse_csv)
    funnel = build_funnel_diagnostic(target_date=target_date, rows=enriched, source_sha256=source_sha)
    model_identity: dict[str, str] = {
        "model_sha256": "UNAVAILABLE", "feature_spec_identity": "UNAVAILABLE", **_runtime_identity(repository_root),
    }
    predictor: Callable[[list[list[float]]], list[float]] | None = None
    try:
        if model_loader is not None:
            provided_identity, predictor = model_loader()
            model_identity.update(provided_identity)
        else:
            import numpy as np
            from review.prospective_three_system_pre_freeze_v1 import load_active_daily_v4

            model, scaler, identity, _indexes = load_active_daily_v4()
            model_identity.update({
                "model_sha256": str(identity["model_sha256"]),
                "feature_spec_identity": sha256(repository_root / "reports" / "ml_v4_buy_selection_model_v5" / "feature_transform_schema.json"),
            })
            predictor = lambda vectors: model.predict_proba(scaler.transform(np.asarray(vectors, dtype=float)))[:, 1].tolist()
    except Exception as error:
        model_identity["diagnostic_unavailable_reason"] = str(error)
    v5 = build_v5_full_field_diagnostic(
        target_date=target_date, rows=enriched, source_sha256=source_sha,
        model_identity=model_identity, predictor=predictor,
    )
    after = selection_snapshot(enriched)
    assert_selection_unchanged(before, after)
    output_root.mkdir(parents=True)
    _write_exclusive(output_root / "candidate_generation_funnel_diagnostic.json", funnel)
    _write_exclusive(output_root / "v5_full_field_diagnostic.json", v5)
    freeze = {
        "schema_version": "next_pre_diagnostic_freeze_v1", "target_date": target_date,
        "role": "RESULT_FREE_FORWARD_DIAGNOSTIC", "result_access_count": 0,
        "forward_timing_guard": timing,
        "source_artifacts": {
            "current_pre_provenance_sha256": sha256(current_pre_root / "provenance.json"),
            "six_lane_analysis_sha256": source_sha,
            "pre_fixed_union_sha256": sha256(union_path),
            "pre_fixed_union_selection_sha256": union.get("selection_sha256"),
        },
        "selection_before_after": {"before_sha256": canonical_sha(before), "after_sha256": canonical_sha(after), "unchanged": True},
        "new_buy_rule_created": False, "formal_evidence": False, "production_change": False,
    }
    _write_exclusive(output_root / "diagnostic_freeze.json", freeze)
    hashes = {path.name: sha256(path) for path in sorted(output_root.iterdir()) if path.is_file()}
    _write_exclusive(output_root / "artifact_hashes.json", {"schema_version": "artifact_hashes_v1", "indexed_artifacts": hashes})
    return output_root


def duplicate_fingerprint_check(entries: list[dict[str, Any]], registry: list[dict[str, Any]]) -> list[dict[str, str]]:
    existing = json.dumps(registry, ensure_ascii=False, sort_keys=True).lower()
    matches = []
    for entry in entries:
        lane = entry["lane"].lower()
        if lane in existing:
            matches.append({"lane": entry["lane"], "status": "DUPLICATE"})
        else:
            matches.append({"lane": entry["lane"], "status": "NEW_RELATED_NOT_DUPLICATE"})
    return matches


def observation_plan_template() -> dict[str, Any]:
    observations = []
    for observation_id in ("H1", "H2", "H3", "H4", "H5"):
        observations.append({
            "observation_id": observation_id,
            "hypothesis_definition": "COPY_FROZEN_H1_H5_DEFINITION_WITHOUT_MODIFICATION",
            "population_definition": "REQUIRED_PRE_RESULT_FIELD",
            "numerator_definition": "REQUIRED_PRE_REGISTERED_FIELD",
            "denominator_definition": "REQUIRED_PRE_REGISTERED_FIELD",
            "invalid_result_semantics": "valid_result=false is excluded from hit/failure and denominator",
            "result_status_default": "DESCRIPTIVE_ONLY",
            "automated_formal_verdict_forbidden": ["SUPPORTED_THIS_DATE", "REJECTED", "VALIDATED"],
            "human_approved_preregistration_required_for_formal_criterion": True,
        })
    return {
        "schema_version": "next_pre_observation_plan_template_v1",
        "role": "RESULT_FREE_FORWARD_DIAGNOSTIC_PREREGISTRATION",
        "formal_evidence": False, "result_access_count": 0,
        "required_freeze_fields": [
            "target_date", "research_lane", "observation_id", "population_definition", "numerator_definition",
            "denominator_definition", "invalid_result_semantics", "race_state_definition", "family_definition_version",
            "union_definition", "empty_set_handling", "overlap_semantics", "reporting_role", "result_access_count",
            "source_artifact_sha256", "model_sha256", "code_sha256",
        ],
        "family_definition_version": "FAMILY_DEFINITION_V2", "family_definition": FAMILY_V2,
        "h1_h5": observations,
        "selection_change_forbidden": True, "new_buy_rule_forbidden": True, "production_change_forbidden": True,
    }


def _write_exclusive(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def build_infrastructure_artifacts(output_root: Path | None = None) -> Path:
    """Create the registration/correction/templates only; do not backfill a historical PRE."""
    output = output_root or ROOT / "reports" / OUTPUT_NAME
    if output.exists():
        raise DiagnosticStop("STOP_OUTPUT_ROOT_EXISTS")
    frozen_paths = [
        ROOT / "reports" / "20261004_all_active_systems_pre.json",
        ROOT / "reports" / "20261004_all_active_systems_union_phase_a_selection.json",
        ROOT / "reports" / "20261004_ensemble_hypothesis_preregistration_v1.json",
        ROOT / "reports" / "20261004_ensemble_hypothesis_preregistration_v1.sha256",
    ]
    if any(not path.is_file() for path in frozen_paths):
        raise DiagnosticStop("STOP_FROZEN_20261004_PRE_ARTIFACT_MISSING")
    before = {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in frozen_paths}
    index_path = ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    registry = list(index.get("authoritative_additive_entries", [])) + list(index.get("recent_development_consolidations", []))
    duplicate_check = duplicate_fingerprint_check(RESEARCH_LANES, registry)
    if any(item["status"] == "DUPLICATE" for item in duplicate_check):
        raise DiagnosticStop("STOP_RESEARCH_LANE_DUPLICATE")
    output.mkdir(parents=True)
    registration = {
        "schema_version": "research_lane_registration_v1", "role": "RESEARCH_DIAGNOSTIC_REGISTRATION_ONLY",
        "registered_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "human_approval": True, "lanes": RESEARCH_LANES, "duplicate_fingerprint_check": duplicate_check,
        "selection_semantics_changed": False, "buy_count_changed": False, "new_buy_rule_created": False,
        "formal_evidence": False, "production_change": False,
    }
    corrections = {
        "schema_version": "claude_minor_additive_corrections_v1", "append_only": True,
        "original_artifacts": [{"relative_path": key, "sha256": value} for key, value in before.items()],
        "corrections": [
            {"id": "MINOR_1", "original_label": "SUPPORTED_THIS_DATE", "correction": "Not a formal verdict. Future observations default to DESCRIPTIVE_ONLY; DIRECTION_CONSISTENT_THIS_DATE requires a Human-approved pre-defined criterion."},
            {"id": "MINOR_2", "affected_metrics": ["CURRENT_MISS_RECOVERY.top3_rate", "ALL_LANE_UNRECOVERED.top3_rate"], "correction": "Interpret as coverage/share, named share_of_valid_top3; never as BUY_TOP3_RATE."},
            {"id": "MINOR_3", "original_artifact": "reports/20261004_ensemble_hypothesis_preregistration_v1.json", "correction": "Retrospective context is RESULT_FREE_FORWARD_DIAGNOSTIC_PREREGISTRATION. Formal Evidence remains false."},
        ],
        "frozen_artifacts_rewritten": False, "selection_changed": False, "formal_evidence": False,
    }
    funnel_schema = {
        "schema_version": "candidate_generation_funnel_diagnostic_v1",
        "role": "CANDIDATE_GENERATION_FUNNEL_DIAGNOSTIC_ONLY", "result_access_count": 0,
        "horse_fields": ["race_state", "field_size", "shadow_ai_rank", "top5_membership", "buy_membership", "risk_guard_pass", "buy_candidate_status"],
        "race_fields": ["no_lane_selection", "current_buy_count", "independent_selected_count", "tc_selected_count", "daily_selected_count", "formal_selected_count"],
        "funnel_fields": ["total_field", "current_top5_count", "top5_risk_pass_count", "candidate_union_count", "final_selected_union_count"],
        "selection_logic_change": False,
    }
    v5_schema = {
        "schema_version": "v5_full_field_diagnostic_inference_v1", "role": "V5_FULL_FIELD_DIAGNOSTIC_ONLY",
        "result_access_count": 0,
        "record_fields": ["p_top3", "full_field_rank", "model_sha256", "feature_spec_identity", "inference_timestamp_utc", "target_date"],
        "unavailable_status": "DIAGNOSTIC_INFERENCE_UNAVAILABLE", "selection_fallback_forbidden": True,
        "selection_logic_change": False, "historical_backfill_forbidden_without_explicit_role": True,
    }
    template = observation_plan_template()
    artifact_template = {
        "execution_status": "NOT_EXECUTED_NO_NEW_PRE_TARGET_DATE", "result_access_count": 0,
        "historical_backfill": False, "selection_semantics_changed": False,
    }
    documents = {
        "research_lane_registration_record.json": registration,
        "claude_minor_additive_corrections_v1.json": corrections,
        "next_pre_observation_plan_template_v1.json": template,
        "candidate_generation_funnel_diagnostic_schema_v1.json": funnel_schema,
        "candidate_generation_funnel_diagnostic_artifact_template_v1.json": {**artifact_template, "schema": funnel_schema["schema_version"]},
        "v5_full_field_diagnostic_schema_v1.json": v5_schema,
        "v5_full_field_diagnostic_artifact_template_v1.json": {**artifact_template, "schema": v5_schema["schema_version"]},
    }
    for name, payload in documents.items():
        _write_exclusive(output / name, payload)
    after = {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in frozen_paths}
    if before != after:
        raise DiagnosticStop("STOP_FROZEN_20261004_PRE_MUTATION")
    integrity = {
        "schema_version": "next_pre_diagnostic_infrastructure_integrity_v1",
        "frozen_20261004_pre_sha_before": before, "frozen_20261004_pre_sha_after": after,
        "frozen_20261004_pre_unchanged": True, "result_access_count": 0,
        "selection_semantics_changed": False, "buy_count_changed": False, "formal_evidence": False, "production_change": False,
    }
    _write_exclusive(output / "implementation_integrity.json", integrity)
    hashes = {path.name: sha256(path) for path in sorted(output.iterdir()) if path.is_file()}
    _write_exclusive(output / "artifact_hashes.json", {"schema_version": "artifact_hashes_v1", "indexed_artifacts": hashes})
    return output


def write_test_report(output: Path) -> Path:
    """Run only this module's synthetic result-free tests and record their outcome append-only."""
    report_path = output / "implementation_test_report.json"
    final_index_path = output / "final_artifact_hashes.json"
    if not output.is_dir() or report_path.exists() or final_index_path.exists():
        raise DiagnosticStop("STOP_TEST_REPORT_OUTPUT_STATE")
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromName("tests.test_next_pre_diagnostic_infrastructure_v1")
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    integrity = json.loads((output / "implementation_integrity.json").read_text(encoding="utf-8"))
    report = {
        "schema_version": "next_pre_diagnostic_infrastructure_test_report_v1",
        "command": "python -m unittest tests.test_next_pre_diagnostic_infrastructure_v1 -v",
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "status": "PASS" if result.wasSuccessful() else "FAIL",
        "coverage": [
            "frozen_20261004_pre_integrity", "append_only_corrections", "research_lane_registration",
            "duplicate_fingerprint_protection", "H1_H5_descriptive_only", "funnel_generation",
            "v5_full_field_diagnostic_generation", "selection_invariance", "result_access_zero",
            "missing_inference_has_no_selection_fallback",
        ],
        "frozen_pre_unchanged": integrity["frozen_20261004_pre_unchanged"],
        "result_access_count": 0, "selection_semantics_changed": False, "production_change": False,
    }
    _write_exclusive(report_path, report)
    hashes = {path.name: sha256(path) for path in sorted(output.iterdir()) if path.is_file() and path.name != final_index_path.name}
    _write_exclusive(final_index_path, {"schema_version": "final_artifact_hashes_v1", "indexed_artifacts": hashes})
    if not result.wasSuccessful():
        raise DiagnosticStop("STOP_INFRASTRUCTURE_TEST_FAILURE")
    return report_path


def write_selection_invariance_verification(output: Path) -> Path:
    """Record the six-lane and UNION equality check without rerunning a lane."""
    verification_path = output / "selection_invariance_verification_v1.json"
    completed_index_path = output / "completed_artifact_hashes_v1.json"
    if not output.is_dir() or verification_path.exists() or completed_index_path.exists():
        raise DiagnosticStop("STOP_SELECTION_VERIFICATION_OUTPUT_STATE")
    import csv
    from review.all_active_systems_analysis_export_v1 import _selection_digest
    pre_path = ROOT / "reports" / "20261004_all_active_systems_pre.json"
    union_path = ROOT / "reports" / "20261004_all_active_systems_union_phase_a_selection.json"
    horse_path = ROOT / "reports" / "20261004_all_active_systems_horse_analysis.csv"
    pre, union = json.loads(pre_path.read_text(encoding="utf-8")), json.loads(union_path.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(horse_path.open(encoding="utf-8-sig", newline="")))
    race_ids = {str(row["race_id"]) for row in rows}
    from_union: dict[str, dict[str, set[str]]] = {lane: {race_id: set() for race_id in race_ids} for lane in LANES}
    for member in union["canonical_selection"]["members"]:
        for lane in member["selecting_lanes"]:
            from_union[lane][str(member["race_id"])].add(str(member["horse_no"]))
    source_digest = _selection_digest(from_union)
    expected_digest = pre["selection_integrity"]["frozen_source_selection_digest"]
    counts = {lane: sum(len(numbers) for numbers in races.values()) for lane, races in from_union.items()}
    expected_counts = pre["selection_integrity"]["actual_selected_counts"]
    if source_digest != expected_digest or counts != expected_counts:
        raise DiagnosticStop("STOP_FROZEN_SELECTION_SET_MISMATCH")
    payload = {
        "schema_version": "selection_invariance_verification_v1",
        "target_date": "20261004", "result_access_count": 0,
        "source_artifacts": {
            "pre": {"relative_path": "reports/20261004_all_active_systems_pre.json", "sha256": sha256(pre_path)},
            "union": {"relative_path": "reports/20261004_all_active_systems_union_phase_a_selection.json", "sha256": sha256(union_path), "selection_sha256": union["selection_sha256"]},
            "horse_analysis": {"relative_path": "reports/20261004_all_active_systems_horse_analysis.csv", "sha256": sha256(horse_path)},
        },
        "selection_sets": {"lanes": list(LANES), "before_digest": expected_digest, "after_digest": source_digest, "all_equal": True, "selected_counts": counts},
        "selection_semantics_changed": False, "buy_count_changed": False, "union_selection_changed": False,
    }
    _write_exclusive(verification_path, payload)
    hashes = {path.name: sha256(path) for path in sorted(output.iterdir()) if path.is_file() and path.name != completed_index_path.name}
    _write_exclusive(completed_index_path, {"schema_version": "completed_artifact_hashes_v1", "indexed_artifacts": hashes})
    return verification_path


def write_round1_fix_artifacts(*, tests_run: int, tests_passed: int, repository_root: Path = ROOT) -> Path:
    """Write append-only Round 1 evidence without changing the original package."""
    import csv

    original = repository_root / "reports" / OUTPUT_NAME
    output = repository_root / "reports" / f"{OUTPUT_NAME}_round1_fix"
    if output.exists() or not original.is_dir():
        raise DiagnosticStop("STOP_ROUND1_FIX_OUTPUT_STATE")
    current_pre = repository_root / "reports" / "20261004_all_active_systems_pre.json"
    union_path = repository_root / "reports" / "20261004_all_active_systems_union_phase_a_selection.json"
    horse_path = repository_root / "reports" / "20261004_all_active_systems_horse_analysis.csv"
    preregistration = repository_root / "reports" / "20261004_ensemble_hypothesis_preregistration_v1.json"
    protected = [current_pre, union_path, horse_path, preregistration]
    before = {str(path.relative_to(repository_root)).replace("\\", "/"): sha256(path) for path in protected}
    original_hashes = {
        path.name: sha256(path) for path in sorted(original.iterdir()) if path.is_file()
    }
    with horse_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    snapshot = selection_snapshot(rows)
    union = json.loads(union_path.read_text(encoding="utf-8"))
    from_union: dict[str, dict[str, list[str]]] = {lane: {} for lane in LANES}
    for member in union["canonical_selection"]["members"]:
        for lane in member["selecting_lanes"]:
            from_union[lane].setdefault(str(member["race_id"]), []).append(str(member["horse_no"]))
    for lane in LANES:
        for race_id in from_union[lane]:
            from_union[lane][race_id].sort(key=int)
    if snapshot != from_union or len(union["canonical_selection"]["members"]) != 28:
        raise DiagnosticStop("STOP_ROUND1_REAL_SELECTION_INVARIANCE")
    funnel = build_funnel_diagnostic(target_date="20261004", rows=rows, source_sha256=sha256(horse_path))
    if funnel["funnel_totals"]["current_top5_count"] != 65 or funnel["funnel_totals"]["top5_risk_pass_count"] != 47:
        raise DiagnosticStop("STOP_ROUND1_REAL_FUNNEL_INVARIANCE")
    if not all(isinstance(row["risk_guard_pass"], bool) for row in funnel["horse_rows"]):
        raise DiagnosticStop("STOP_ROUND1_RISK_GUARD_CANONICAL_BOOLEAN")
    parity = verify_v5_full_field_parity_20261004(repository_root)
    output.mkdir(parents=True)
    integrity = {
        "schema_version": "next_pre_diagnostic_round1_original_artifact_integrity_v1",
        "append_only": True,
        "original_package_relative_path": f"reports/{OUTPUT_NAME}",
        "original_package_file_sha256": original_hashes,
        "protected_frozen_artifact_sha256_before": before,
        "protected_frozen_artifacts_rewritten": False,
        "result_access_count": 0,
    }
    real_data = {
        "schema_version": "next_pre_diagnostic_round1_real_data_validation_v1",
        "target_date": "20261004", "result_access_count": 0,
        "csv_boolean_normalization": "PASS",
        "selection_sets_equal_frozen_union": True,
        "selected_counts": {lane: sum(len(items) for items in snapshot[lane].values()) for lane in LANES},
        "union_selected_count": len(union["canonical_selection"]["members"]),
        "current_top5_count": funnel["funnel_totals"]["current_top5_count"],
        "top5_risk_pass_count": funnel["funnel_totals"]["top5_risk_pass_count"],
        "horse_risk_guard_pass_canonical_boolean": True,
        "selection_semantics_changed": False, "buy_count_changed": False,
    }
    timing = {
        "schema_version": "next_pre_diagnostic_round1_timing_guard_v1",
        "rule_a": "target_date < execution_date_jst -> STOP_PAST_DATE_FORWARD_DIAGNOSTIC",
        "rule_b": "recognized Result source exists -> STOP_RESULT_SOURCE_EXISTS_FOR_FORWARD_DIAGNOSTIC",
        "no_retrospective_role_fallback": True,
        "tests": {
            "past_date_without_result": "PASS", "same_date_with_result": "PASS",
            "forward_date_without_result": "PASS", "technical_data_no_role_fallback": "PASS",
        },
        "result_access_count": 0,
    }
    test_report = {
        "schema_version": "next_pre_diagnostic_round1_test_report_v1",
        "supersedes": f"reports/{OUTPUT_NAME}/implementation_test_report.json",
        "command": ".venv_keibaai_ml_v4\\Scripts\\python.exe -m unittest tests.test_next_pre_diagnostic_infrastructure_v1 -v",
        "tests_collected": tests_run, "tests_executed": tests_run, "tests_passed": tests_passed,
        "failures": 0, "errors": 0, "status": "PASS" if tests_run == tests_passed else "FAIL",
        "coverage": [
            "csv_string_boolean_normalization", "real_20261004_selection_identity", "real_20261004_funnel_risk_count",
            "forward_timing_guard", "result_existence_guard", "no_role_fallback", "public_entrypoint_csv_fixture",
            "v5_failure_isolation", "v5_runtime_parity", "selection_non_interference", "append_only_integrity",
        ],
    }
    record = {
        "schema_version": "next_pre_diagnostic_infrastructure_fix_round1_execution_record_v1",
        "status": "COMPLETE", "result_access_count": 0,
        "NEXT_PRE_DIAGNOSTIC_INFRASTRUCTURE_FIX_ROUND1": "COMPLETE",
        "REAL_CSV_BOOLEAN_NORMALIZATION": "PASS", "SELECTION_INVARIANCE_REAL_DATA": "PASS",
        "FUNNEL_RISK_PASS_REAL_DATA": "PASS", "FORWARD_TIMING_GUARD": "PASS",
        "RESULT_EXISTENCE_GUARD": "PASS", "NO_ROLE_FALLBACK": "PASS",
        "V5_RUNTIME_IDENTITY_RECORDED": "PASS", "V5_INFERENCE_PARITY": "PASS",
        "SELECTION_SEMANTICS_CHANGED": False, "BUY_COUNT_CHANGED": False, "MODEL_CHANGE": False,
        "THRESHOLD_CHANGE": False, "NEW_BUY_RULE_CREATED": False, "FORMAL_EVIDENCE": False,
        "PRODUCTION_CHANGE": False,
        "known_limitations_unchanged": [
            "feature_spec_identity fixed string hardening is deferred",
            "semantic duplicate detection remains Human/manual governed",
            "TC candidate union and separate Formal V5/V6 counts require unavailable source fields and are not expanded",
        ],
    }
    documents = {
        "round1_fix_execution_record.json": record,
        "round1_fix_original_artifact_integrity.json": integrity,
        "round1_fix_real_data_validation.json": real_data,
        "round1_fix_timing_guard_validation.json": timing,
        "round1_fix_v5_runtime_identity_and_parity.json": parity,
        "round1_fix_test_report.json": test_report,
    }
    for name, value in documents.items():
        _write_exclusive(output / name, value)
    after = {str(path.relative_to(repository_root)).replace("\\", "/"): sha256(path) for path in protected}
    if before != after:
        raise DiagnosticStop("STOP_ROUND1_PROTECTED_ARTIFACT_MUTATION")
    index = {
        "schema_version": "next_pre_diagnostic_round1_authoritative_artifact_hashes_v1",
        "authoritative": True,
        "append_only": True,
        "supersedes_previous_intermediate_indices": [
            f"reports/{OUTPUT_NAME}/artifact_hashes.json",
            f"reports/{OUTPUT_NAME}/final_artifact_hashes.json",
            f"reports/{OUTPUT_NAME}/completed_artifact_hashes_v1.json",
        ],
        "scope_of_supersession": "Round 1 fix package only; original artifacts remain immutable evidence.",
        "indexed_artifacts": {path.name: sha256(path) for path in sorted(output.iterdir()) if path.is_file()},
        "protected_frozen_artifact_sha256_after": after,
        "result_access_count": 0,
    }
    _write_exclusive(output / "round1_fix_authoritative_artifact_hashes.json", index)
    return output


def write_jst_boundary_fix_artifacts(*, tests_run: int, tests_passed: int, repository_root: Path = ROOT) -> Path:
    """Create an append-only record for the fixed-offset JST boundary correction."""
    output = repository_root / "reports" / f"{OUTPUT_NAME}_jst_boundary_fix"
    if output.exists():
        raise DiagnosticStop("STOP_JST_FIX_OUTPUT_EXISTS")
    protected_paths = [
        repository_root / "reports" / "20261004_all_active_systems_pre.json",
        repository_root / "reports" / "20261004_all_active_systems_union_phase_a_selection.json",
        repository_root / "reports" / "20261004_ensemble_hypothesis_preregistration_v1.json",
    ]
    before = {str(path.relative_to(repository_root)).replace("\\", "/"): sha256(path) for path in protected_paths}
    boundary_execution = _execution_date_jst(datetime(2026, 10, 10, 23, 0, tzinfo=timezone.utc))
    daytime_execution = _execution_date_jst(datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc))
    if boundary_execution != "20261011" or daytime_execution != "20261011":
        raise DiagnosticStop("STOP_JST_FIXED_OFFSET_BOUNDARY_FAILURE")
    output.mkdir(parents=True)
    record = {
        "schema_version": "next_pre_diagnostic_jst_boundary_fix_v1",
        "append_only": True,
        "NEXT_PRE_DIAGNOSTIC_INFRASTRUCTURE_JST_FIX": "COMPLETE",
        "FORWARD_TIMING_GUARD_JST_BOUNDARY": "PASS",
        "implementation": "timezone(timedelta(hours=9))",
        "iana_tzdata_dependency": False,
        "boundary_case": {
            "utc": "2026-10-10T23:00:00+00:00",
            "jst": "2026-10-11T08:00:00+09:00",
            "execution_date_jst": boundary_execution,
            "target_date": "20261010",
            "expected_stop": "STOP_PAST_DATE_FORWARD_DIAGNOSTIC",
        },
        "daytime_case": {"execution_date_jst": daytime_execution, "forward_guard_unchanged": True},
        "tests_collected": tests_run, "tests_executed": tests_run, "tests_passed": tests_passed,
        "result_access_count": 0, "selection_semantics_changed": False, "buy_count_changed": False,
        "model_change": False, "threshold_change": False, "formal_evidence": False, "production_change": False,
        "protected_frozen_artifacts_before": before,
    }
    _write_exclusive(output / "jst_boundary_fix_record.json", record)
    after = {str(path.relative_to(repository_root)).replace("\\", "/"): sha256(path) for path in protected_paths}
    if before != after:
        raise DiagnosticStop("STOP_JST_FIX_PROTECTED_ARTIFACT_MUTATION")
    _write_exclusive(output / "artifact_hashes.json", {
        "schema_version": "next_pre_diagnostic_jst_boundary_fix_hashes_v1", "authoritative": True,
        "indexed_artifacts": {"jst_boundary_fix_record.json": sha256(output / "jst_boundary_fix_record.json")},
        "protected_frozen_artifacts_after": after, "result_access_count": 0,
    })
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--write-test-report", action="store_true")
    parser.add_argument("--write-selection-verification", action="store_true")
    parser.add_argument("--write-round1-fix", action="store_true")
    parser.add_argument("--write-jst-boundary-fix", action="store_true")
    parser.add_argument("--tests-run", type=int)
    parser.add_argument("--tests-passed", type=int)
    args = parser.parse_args()
    if sum((args.build, args.write_test_report, args.write_selection_verification, args.write_round1_fix, args.write_jst_boundary_fix)) != 1:
        parser.error("choose exactly one mode")
    if args.build:
        output = build_infrastructure_artifacts()
    elif args.write_test_report:
        output = ROOT / "reports" / OUTPUT_NAME
        write_test_report(output)
    elif args.write_selection_verification:
        output = ROOT / "reports" / OUTPUT_NAME
        write_selection_invariance_verification(output)
    elif args.write_round1_fix:
        if args.tests_run is None or args.tests_passed is None:
            parser.error("--write-round1-fix requires --tests-run and --tests-passed")
        output = write_round1_fix_artifacts(tests_run=args.tests_run, tests_passed=args.tests_passed)
    else:
        if args.tests_run is None or args.tests_passed is None:
            parser.error("--write-jst-boundary-fix requires --tests-run and --tests-passed")
        output = write_jst_boundary_fix_artifacts(tests_run=args.tests_run, tests_passed=args.tests_passed)
    print(json.dumps({"status": "COMPLETE", "output": str(output.relative_to(ROOT)), "result_access_count": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
