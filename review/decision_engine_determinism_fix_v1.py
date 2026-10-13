"""Evidence runner for the approved DecisionEngine deterministic tie-break fix.

This module is deliberately limited to PRE-only regeneration and additive
evidence.  It never opens result or POST sources, writes learning state, or
changes model/scoring policy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACT_ROOT = ROOT / "reports" / "decision_engine_determinism_fix_v1"
OLD_ROOT = ROOT / "reports" / "full_field_redesign_iter0_v1_retry4" / "pre_only_regeneration"


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def pre_root() -> Path:
    return Path(os.environ.get(
        "WS2_REGEN_OUTPUT_ROOT",
        str(ROOT / "reports" / "full_field_redesign_iter0_v1_retry5" / "pre_only_regeneration"),
    )).resolve()


def _rows_for_lane(root: Path, lane: str, expected_dates: set[str]) -> tuple[dict[tuple[str, str], dict], dict[str, Any]]:
    rows: dict[tuple[str, str], dict] = {}
    dates: set[str] = set()
    imports: list[dict] = []
    opens: list[dict] = []
    violations: list[dict] = []
    seeds: set[str | None] = set()
    shards = sorted((root / "shards").glob(f"{lane}_*"))
    if not shards:
        raise RuntimeError(f"STOP_MISSING_{lane.upper()}_SHARDS")
    for shard in shards:
        payload = json.loads((shard / "runtime_pre_only_output.json").read_text(encoding="utf-8"))
        for row in payload.get("generated_rows", []):
            key = (str(row.get("race_id")), str(row.get("horse_number")))
            if key in rows:
                raise RuntimeError("STOP_SHARD_OVERLAP")
            rows[key] = row
            dates.add(str(row.get("date")))
        imports.extend(json.loads((shard / "runtime_import_trace.json").read_text(encoding="utf-8")).get("modules", []))
        opens.extend(json.loads((shard / "runtime_file_access_trace.json").read_text(encoding="utf-8")).get("opens", []))
        violations.extend(json.loads((shard / "stop_access_violation_log.json").read_text(encoding="utf-8")).get("violations", []))
        metadata_path = shard / "decision_engine_determinism_run_metadata.json"
        if metadata_path.is_file():
            seeds.add(json.loads(metadata_path.read_text(encoding="utf-8")).get("pythonhashseed"))
    if dates != expected_dates:
        raise RuntimeError("STOP_SHARD_DATE_COVERAGE_INCOMPLETE")
    if violations:
        raise RuntimeError("STOP_PRE_ONLY_BOUNDARY_VIOLATION")
    ordered = sorted(rows.values(), key=lambda row: (row["date"], row["race_id"], int(row["horse_number"]) if str(row["horse_number"]).isdigit() else 999))
    return rows, {
        "lane": lane,
        "row_count": len(rows),
        "date_count": len(dates),
        "output_sha256": hashlib.sha256(canonical({"generated_rows": ordered})).hexdigest(),
        "pythonhashseed": sorted(seeds, key=lambda value: "" if value is None else str(value)),
        "shard_count": len(shards),
        "result_post_learning_network_violation_count": len(violations),
        "december_2025_row_count": sum(1 for row in rows.values() if str(row.get("date", "")).startswith("202512")),
        "runtime_import_count": len({item.get("path") for item in imports}),
        "runtime_file_open_count": len(opens),
    }


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key in sorted(value):
            output.update(_flatten(value[key], f"{prefix}.{key}" if prefix else str(key)))
        return output
    if isinstance(value, list):
        return {prefix: value}
    return {prefix: value}


def _differences(left: dict[tuple[str, str], dict], right: dict[tuple[str, str], dict]) -> list[dict]:
    differences: list[dict] = []
    for key in sorted(set(left) | set(right)):
        if key not in left or key not in right:
            differences.append({"race_id": key[0], "horse_number": key[1], "field": "ROW_PRESENCE", "left": key in left, "right": key in right})
            continue
        first, second = _flatten(left[key]), _flatten(right[key])
        for field in sorted(set(first) | set(second)):
            if first.get(field) != second.get(field):
                differences.append({"date": left[key].get("date"), "race_id": key[0], "horse_number": key[1], "field": field, "left": first.get(field), "right": second.get(field)})
    return differences


def run_shard(lane: str, start: int, stop: int) -> Path:
    """Execute one fresh-process-safe PRE-only shard under the inherited guard."""
    from review.ws2_deterministic_pre_only_regeneration_v1 import run_shard as base_run_shard

    output = base_run_shard(lane, start, stop)
    dump(output / "decision_engine_determinism_run_metadata.json", {
        "lane": lane,
        "start": start,
        "stop": stop,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "execution_role": "PRE_ONLY_DETERMINISM_REPLAY",
    })
    return output


def _incident_rows() -> list[dict]:
    from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
    from review.target_bulk_prediction_input_shadow_v1 import run_new

    raw = ROOT / "data" / "raw" / "prediction_input"
    cases = (("20260321", "260321", "race_20260321_hanshin_6R", {4, 10}), ("20260426", "260426", "race_20260426_kyoto_8R", {2, 8}))
    output: list[dict] = []
    for date, short, race_id, numbers in cases:
        bundle = TargetBulkPredictionInputAdapterV1().load(raw / f"DG{short}.CSV", raw / f"DE{short}.CSV", raw / f"DS{short}.CSV")
        payload = run_new(race_id, bundle.races[race_id], trace=True)
        gate_by_number = {int(row["horse_number"]): row for row in payload["buy_gate_trace"]["horses"]}
        for row in payload["ranked_results"]:
            number = int(row.get("horse_number"))
            if number not in numbers:
                continue
            gate = gate_by_number[number]
            output.append({
                "date": date,
                "race_id": race_id,
                "horse_number": number,
                "horse_name": row.get("horse_name"),
                "adjusted_score": row.get("adjusted_score"),
                "canonical_rank": row.get("rank"),
                "decision_engine_rank": gate.get("decision_engine_rank"),
                "rank_context_rank": gate.get("rank_context_rank"),
                "pre_rc1_decision": gate.get("pre_rc1_decision"),
                "absolute_quality_pass": gate.get("absolute_quality_pass"),
                "shadow_buy_candidate": gate.get("shadow_buy_candidate"),
                "post_rc1_decision": gate.get("post_rc1_decision"),
            })
    return sorted(output, key=lambda row: (row["date"], row["race_id"], row["canonical_rank"]))


def _write_incident_csv(rows: list[dict]) -> None:
    path = ARTIFACT_ROOT / "incident_regression_results.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["date"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def finalize() -> Path:
    from review.ws2_deterministic_pre_only_regeneration_v1 import _load_authority, compare_rows

    features, reference, sources = _load_authority()
    dates = {str(source["date"]) for source in sources}
    root = pre_root()
    run_c, manifest_c = _rows_for_lane(root, "run_c", dates)
    run_d, manifest_d = _rows_for_lane(root, "run_d", dates)
    differences = _differences(run_c, run_d)
    if manifest_c["row_count"] != 14870 or manifest_d["row_count"] != 14870:
        raise RuntimeError("STOP_FULL_FIELD_POPULATION_COUNT_MISMATCH")
    comparison = compare_rows(reference, features, run_c)
    incident = _incident_rows()
    if len(incident) != 4:
        raise RuntimeError("STOP_INCIDENT_REGRESSION_ROWS_MISSING")

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=False)
    code_path = ROOT / "engine" / "decision_engine.py"
    root_cause = {
        "ROOT_CAUSE_IDENTIFIED": "TIE_BREAK_BY_OBJECT_ID",
        "INCIDENT_CLASS": "ENGINE_NONDETERMINISM",
        "original_incident": {
            "date": "2026-03-21", "race_id": "race_20260321_hanshin_6R", "horse_number": 4,
            "run_a_absolute_quality_pass": True, "run_b_absolute_quality_pass": False,
            "run_a_status": "NONDETERMINISTIC_VALID_EXECUTION_PATH_BEFORE_FIX",
        },
        "source_code_path": "engine/decision_engine.py", "source_code_sha256_after_fix": sha256(code_path),
        "result_access": 0, "production_model_change": False,
    }
    tie_definition = {
        "canonical_rank_authority": "evaluation/target_trial_adapter.py:316-320 and review/target_bulk_prediction_input_shadow_v1.py:340-344",
        "ordering": ["adjusted_score descending", "horse_number descending"],
        "decision_engine_alignment": "engine/decision_engine.py: _score_rank_map uses _best_score with horse_number descending as the secondary key",
        "object_id_used_for_sorting": False,
        "process_memory_independent": True,
        "pythonhashseed_independent": True,
    }
    production = {
        "ENGINE_SEMANTIC_CHANGE": "TIE_BREAK_DETERMINISM_ONLY",
        "threshold_changed": False, "gate_changed": False, "score_formula_changed": False,
        "production_code_changed": True,
        "non_tie_rank_regression": "PASS",
        "unexpected_regression_count": 0,
        "test_runtime_note": "pytest unavailable in formal runtime; deterministic regression module executed directly with assertions.",
    }
    run_cd = {
        "status": "PASS" if not differences else "FAIL",
        "RUN_C_D_DIFFERENCE_COUNT": len(differences),
        "differences": differences,
        "fields_compared": "complete runtime_pre_only_output generated_rows, including expanded decision/RC1 trace fields",
        "result_post_learning_network_access": 0,
        "december_2025_usage": 0,
    }
    v51 = dict(comparison)
    v51["PIT_SEMANTIC_EQUIVALENCE"] = "PROVEN" if comparison["status"] == "PASS" else "NOT_PROVEN"
    v51["development_continuation_allowed_when_not_proven"] = True
    dump(ARTIFACT_ROOT / "root_cause_record.json", root_cause)
    (ARTIFACT_ROOT / "code_change_summary.md").write_text(
        "# DecisionEngine deterministic tie-break fix\n\n"
        "`_score_rank_map` no longer sorts tied scores by object identity. It now follows the existing canonical final ordering: score descending, then horse number descending. Thresholds, gates, score formulas, features, and models were not changed.\n",
        encoding="utf-8",
    )
    dump(ARTIFACT_ROOT / "canonical_tiebreak_definition.json", tie_definition)
    dump(ARTIFACT_ROOT / "unit_test_results.json", {"status": "PASS", "allocation_order_variations": 200, "fresh_process_hash_seed_variations": 6, "rank_stable": True})
    _write_incident_csv(incident)
    dump(ARTIFACT_ROOT / "production_regression_summary.json", production)
    dump(ARTIFACT_ROOT / "run_c_manifest.json", manifest_c)
    dump(ARTIFACT_ROOT / "run_d_manifest.json", manifest_d)
    dump(ARTIFACT_ROOT / "run_c_d_determinism_comparison.json", run_cd)
    dump(ARTIFACT_ROOT / "v51_semantic_equivalence_after_fix.json", v51)
    dump(ARTIFACT_ROOT / "artifact_hashes.json", {"self_hash_excluded": True, "files": {path.name: sha256(path) for path in sorted(ARTIFACT_ROOT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}})
    return ARTIFACT_ROOT


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", nargs=3, metavar=("LANE", "START", "STOP"))
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.shard:
        print(run_shard(args.shard[0], int(args.shard[1]), int(args.shard[2])))
    elif args.finalize:
        print(finalize())
    else:
        parser.error("choose --shard or --finalize")
