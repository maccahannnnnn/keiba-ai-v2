"""Create a result-free, append-only 2026-10-04 ensemble observation plan.

This utility reads frozen PRE analysis artifacts only.  It does not run a
prediction lane, read any Result artifact, or change a selection.  The output
is a pre-registration for later descriptive observation, not a BUY rule or
Formal Evidence.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATE = "20261004"
LANES = (
    "CURRENT",
    "INDEPENDENT_V5",
    "TRACKCONDITION_SEMANTIC",
    "DAILY_V5_SAME_VOLUME",
    "FORMAL_V5",
    "FORMAL_V6",
)
EXPECTED_UNION_SHA = "9e3b3f78c500d6ea55a6c87ea1fc144e20aedfd0c8adf1e49729c17f38804b64"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _write_exclusive_sha(path: Path, digest: str, artifact_name: str) -> None:
    with path.open("x", encoding="ascii", newline="\n") as handle:
        handle.write(f"{digest}  {artifact_name}\n")


def _source_artifacts() -> list[dict[str, str]]:
    current_root = REPORTS / f"daily_pre_analysis_{DATE}" / "current_frozen"
    index_path = current_root / "race_index.json"
    index = _load(index_path)["race_index"]
    paths = [
        index_path,
        REPORTS / "independent_race_selection_prospective" / f"{DATE}_pre" / "selection_manifest.json",
        REPORTS / "track_condition_semantic_shadow_prospective" / f"{DATE}_pre" / "horse_level_trace.json",
        REPORTS / "track_condition_semantic_shadow_prospective" / f"{DATE}_pre" / "race_level_trace.json",
        REPORTS / "daily_v5_same_volume_prospective" / f"{DATE}_pre" / "selection.json",
        REPORTS / "selection_authority_protocol_v1_v6_forward_shadow" / "pre" / DATE / "dual_pre_semantic.json",
        REPORTS / f"{DATE}_all_active_systems_pre.json",
        REPORTS / f"{DATE}_all_active_systems_horse_analysis.csv",
        REPORTS / f"{DATE}_all_active_systems_union_phase_a_selection.json",
    ]
    paths.extend(current_root / str(row["artifact"]) for row in index)
    if any(not path.is_file() for path in paths):
        missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
        raise RuntimeError(f"STOP_SOURCE_PRE_ARTIFACT_MISSING:{missing}")
    return [
        {
            "relative_path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(path),
        }
        for path in paths
    ]


def _selected(rows: list[dict[str, str]], field: str) -> bool:
    return str(rows[0].get(field, "")).strip().lower() == "true"


def _daily_pairs(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_race: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_race.setdefault(row["race_id"], []).append(row)
    pairs: list[dict[str, Any]] = []
    for race_id, race_rows in sorted(by_race.items()):
        removed = [row for row in race_rows if _selected([row], "current_buy") and not _selected([row], "daily_v5_selected")]
        added = [row for row in race_rows if not _selected([row], "current_buy") and _selected([row], "daily_v5_selected")]
        if not removed and not added:
            continue
        if len(removed) != 1 or len(added) != 1:
            raise RuntimeError(f"STOP_DAILY_V5_PAIR_NOT_ONE_TO_ONE:{race_id}")
        pairs.append(
            {
                "race_id": race_id,
                "venue": removed[0]["venue"],
                "race_number": removed[0]["race_number"],
                "current_removed": {
                    "horse_number": int(removed[0]["horse_number"]),
                    "horse_name": removed[0]["horse_name"],
                },
                "daily_added": {
                    "horse_number": int(added[0]["horse_number"]),
                    "horse_name": added[0]["horse_name"],
                },
                "post_result_fields_to_record": ["valid_result", "finish", "actual_top3"],
            }
        )
    return pairs


def build() -> dict[str, Path]:
    output = REPORTS / "20261004_ensemble_hypothesis_preregistration_v1.json"
    output_sha = REPORTS / "20261004_ensemble_hypothesis_preregistration_v1.sha256"
    correction = REPORTS / "20261003_union_timing_correction_v1.json"
    if output.exists() or output_sha.exists() or correction.exists():
        raise RuntimeError("STOP_PREREGISTRATION_OUTPUT_ALREADY_EXISTS")

    pre_path = REPORTS / f"{DATE}_all_active_systems_pre.json"
    union_path = REPORTS / f"{DATE}_all_active_systems_union_phase_a_selection.json"
    horse_path = REPORTS / f"{DATE}_all_active_systems_horse_analysis.csv"
    pre = _load(pre_path)
    union = _load(union_path)
    if (
        pre.get("date") != DATE
        or pre.get("input_preflight", {}).get("result_access_count") != 0
        or pre.get("execution_safety", {}).get("result_access_count") != 0
        or union.get("result_access_count") != 0
        or union.get("selection_sha256") != EXPECTED_UNION_SHA
        or union.get("formal_evidence") is not False
    ):
        raise RuntimeError("STOP_FROZEN_PRE_OR_UNION_INTEGRITY")

    rows = list(csv.DictReader(horse_path.open(encoding="utf-8-sig", newline="")))
    if len(rows) != 217:
        raise RuntimeError("STOP_HORSE_ANALYSIS_ROW_COUNT")
    members = union.get("canonical_selection", {}).get("members", [])
    if len(members) != 28 or union.get("union_unique_count") != 28:
        raise RuntimeError("STOP_UNION_MEMBER_COUNT")

    h1 = [
        member for member in members
        if member["race_id"] == "race_20261004_tokyo_11R" and str(member["horse_no"]) == "16"
    ]
    if len(h1) != 1 or h1[0]["support_structure"] != "CURRENT_ONLY":
        raise RuntimeError("STOP_H1_PRE_FIXED_MEMBER_MISMATCH")

    h2_rows = [
        row for row in rows
        if row["current_race_state"] == "PLAY_UNCONVERGED_4PLUS"
        and _selected([row], "independent_v5_selected")
    ]
    if len(h2_rows) != 12:
        raise RuntimeError("STOP_H2_PRE_FIXED_COUNT_MISMATCH")

    current_rows = [row for row in rows if _selected([row], "current_buy")]
    h3_agree = [row for row in current_rows if _selected([row], "trackcondition_selected")]
    h3_not_agree = [row for row in current_rows if not _selected([row], "trackcondition_selected")]
    if len(current_rows) != 7 or len(h3_agree) != 2 or len(h3_not_agree) != 5:
        raise RuntimeError("STOP_H3_PRE_FIXED_COUNT_MISMATCH")

    pairs = _daily_pairs(rows)
    if len(pairs) != 4:
        raise RuntimeError("STOP_H4_PRE_FIXED_PAIR_COUNT_MISMATCH")

    support_structures = (
        "CURRENT_PLUS_V5",
        "CURRENT_PLUS_TC",
        "CURRENT_PLUS_TC_PLUS_V5",
        "V5_FAMILY_ONLY",
        "TC_ONLY",
        "TC_PLUS_V5",
    )
    support_counts = {
        structure: sum(1 for member in members if member["support_structure"] == structure)
        for structure in support_structures
    }
    if support_counts != {
        "CURRENT_PLUS_V5": 4,
        "CURRENT_PLUS_TC": 0,
        "CURRENT_PLUS_TC_PLUS_V5": 2,
        "V5_FAMILY_ONLY": 15,
        "TC_ONLY": 4,
        "TC_PLUS_V5": 2,
    }:
        raise RuntimeError("STOP_SUPPORT_STRUCTURE_COUNT_MISMATCH")

    payload = {
        "schema_version": "ensemble_hypothesis_preregistration_v1",
        "date": DATE,
        "role": "POST_RESULT_RETROSPECTIVE_ENSEMBLE_DIAGNOSTIC_ONLY",
        "formal_evidence": False,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "result_free_preconditions": {
            "result_access_count": 0,
            "pre_selection_changed": False,
            "union_changed": False,
            "new_buy_rule_created": False,
            "production_change": False,
        },
        "source_pre_artifacts": _source_artifacts(),
        "source_union": {
            "relative_path": str(union_path.relative_to(ROOT)).replace("\\", "/"),
            "file_sha256": _sha256(union_path),
            "selection_sha256": union["selection_sha256"],
            "role": union["role"],
            "union_unique_count": union["union_unique_count"],
            "selection_is_not_changed_by_this_preregistration": True,
        },
        "family_definition_v2": {
            "CURRENT_BASE": ["CURRENT"],
            "TRACKCONDITION_VARIANT": ["TRACKCONDITION_SEMANTIC"],
            "V5_FAMILY": ["INDEPENDENT_V5", "DAILY_V5_SAME_VOLUME", "FORMAL_V5", "FORMAL_V6"],
            "formal_v6_is_not_a_separate_family": True,
            "trackcondition_is_not_claimed_as_fully_independent_from_current": True,
            "family_definition_changed": False,
        },
        "hypotheses": {
            "H1_CURRENT_ONLY": {
                "hypothesis": "Current-only selection may be weaker.",
                "pre_fixed_population": h1,
                "observation_fields_after_result_open": ["raw_n", "valid_n", "top3_hits", "top3_rate"],
                "single_day_decision_prohibited": True,
            },
            "H2_INDEPENDENT_IN_CURRENT_UNCONVERGED": {
                "hypothesis": "Independent V5 may recover candidates in Current PLAY_UNCONVERGED_4PLUS races.",
                "scope": "Independent selections only in Current PLAY_UNCONVERGED_4PLUS races; distinct from Current converged races.",
                "pre_fixed_n": len(h2_rows),
                "pre_fixed_members": [
                    {key: row[key] for key in ("race_id", "venue", "race_number", "horse_number", "horse_name", "current_race_state")}
                    for row in h2_rows
                ],
                "observation_fields_after_result_open": ["raw_n", "valid_n", "top3_hits", "top3_rate"],
            },
            "H3_TC_AGREEMENT_WITHIN_CURRENT": {
                "hypothesis": "TC agreement may distinguish quality inside Current BUY.",
                "group_a_current_and_tc": {"pre_fixed_n": len(h3_agree), "members": [
                    {key: row[key] for key in ("race_id", "venue", "race_number", "horse_number", "horse_name")}
                    for row in h3_agree
                ]},
                "group_b_current_not_tc": {"pre_fixed_n": len(h3_not_agree), "members": [
                    {key: row[key] for key in ("race_id", "venue", "race_number", "horse_number", "horse_name")}
                    for row in h3_not_agree
                ]},
                "observation_fields_after_result_open": ["raw_n", "valid_n", "top3_hits", "top3_rate"],
            },
            "H4_DAILY_V5_SAME_VOLUME_RESELECTION": {
                "hypothesis": "Daily V5 same-volume reselection may improve Current horse selection.",
                "current_selected_count": 7,
                "daily_selected_count": 7,
                "pre_fixed_replacement_pairs": pairs,
                "pair_definition_must_not_change_after_result_open": True,
            },
            "H5_ALL_LANES_UNRECOVERED_TOP3": {
                "hypothesis": "A large share of actual Top3 horses may remain unselected by every active lane.",
                "post_result_categories": {
                    "A_CURRENT_SELECTED": "actual_top3=true AND CURRENT selected=true",
                    "B_CURRENT_FALSE_OTHER_LANE_SELECTED": "actual_top3=true AND CURRENT selected=false AND any non-CURRENT lane selected=true",
                    "C_ALL_LANES_UNSELECTED": "actual_top3=true AND all six lane selections=false",
                },
                "required_metrics": [
                    "total_actual_top3", "current_captured", "other_lane_recovery",
                    "all_lanes_unrecovered", "unrecovered_share",
                ],
                "selection_change_prohibited": True,
            },
        },
        "additional_pre_fixed_structures": {
            "counts": support_counts,
            "observation_fields_after_result_open": ["raw_n", "valid_n", "top3_hits", "top3_rate"],
            "performance_rule_adoption_prohibited": True,
        },
        "historical_timing_boundary": {
            "statement": "For 2026-09-26, 2026-09-27, and 2026-10-03, lane selections were frozen before Result access. UNION aggregation and Family Definition V2 were retrospective diagnostics constructed after Results were known.",
            "historical_artifacts_not_modified": True,
            "correction_record": "reports/20261003_union_timing_correction_v1.json",
        },
        "post_result_boundary": {
            "allowed": "Join this pre-fixed population to Results and calculate the listed descriptive metrics.",
            "prohibited": [
                "selection reconstruction from Results", "new threshold", "new BUY rule", "family definition change",
                "model change", "production change", "Formal Evidence conversion",
            ],
        },
    }
    _write_exclusive_json(output, payload)
    _write_exclusive_sha(output_sha, _sha256(output), output.name)

    prior_union = REPORTS / "20261003_all_active_systems_union_phase_a_selection.json"
    correction_payload = {
        "schema_version": "union_timing_correction_v1",
        "role": "APPEND_ONLY_TIMING_CORRECTION",
        "formal_evidence": False,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "corrected_artifact": {
            "relative_path": str(prior_union.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(prior_union),
            "selection_sha256": _load(prior_union)["selection_sha256"],
            "immutable": True,
            "modified_by_this_record": False,
        },
        "correction": {
            "field": "generated_before_result",
            "existing_value": True,
            "corrected_interpretation": "The underlying lane selections were frozen pre-Result, but the UNION aggregation and Family Definition V2 are retrospective diagnostic constructs. Therefore this artifact must not be used as evidence that the UNION aggregation itself was generated before Result access.",
            "selection_content_changed": False,
            "union_content_changed": False,
            "result_access_by_correction_record": 0,
        },
    }
    _write_exclusive_json(correction, correction_payload)
    return {"preregistration": output, "sha256": output_sha, "timing_correction": correction}


if __name__ == "__main__":
    for name, path in build().items():
        print(f"{name}={path}")
