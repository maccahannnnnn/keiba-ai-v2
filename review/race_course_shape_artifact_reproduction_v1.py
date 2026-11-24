"""Isolated CURRENT_AI_ARTIFACT_REPRODUCTION for Race/Course Shape tracing.

This utility intentionally uses only frozen PRE artifacts and their recorded
DG/DE/DS sources.  It neither imports Result adapters nor writes to an
existing prediction root.  Its output is mechanism-development evidence only.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from review.prospective_prediction_runner_v1 import _project_race
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "race_course_shape_replay_v1"
CLASSIFICATION = ROOT / "reports" / "failed_buy_root_cause_v1" / "failed_buy_classification.csv"
TRACE_FIELDS = (
    "pace_prediction",
    "pace_style",
    "course_profile_matched",
    "race_shape_adjustment_id",
)
BLOCK_ROOTS = {
    "JUNE_BLOCK_1": ROOT / "reports" / "h5_temporal_june_block1_v1",
    "JULY_H1": ROOT / "reports" / "cand_h5_001_july_4day_validation_v1",
    "JULY_H2": ROOT / "reports" / "h5_temporal_july_h2_v1",
    "AUGUST_DEVELOPMENT": ROOT / "reports" / "buy_improvement_trace_6day_v1",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def load_population() -> list[dict]:
    with CLASSIFICATION.open(encoding="utf-8-sig", newline="") as source:
        rows = [row for row in csv.DictReader(source) if row["category"] == "BUY_SELECTION_FAILURE"]
    if len(rows) != 54:
        raise RuntimeError(f"TARGET_RACE_COUNT_INVALID:{len(rows)}")
    if len({row["race_id"] for row in rows}) != len(rows):
        raise RuntimeError("TARGET_RACE_ID_DUPLICATE")
    if set(row["block"] for row in rows) != set(BLOCK_ROOTS):
        raise RuntimeError("TARGET_TEMPORAL_BLOCKS_INVALID")
    return sorted(rows, key=lambda row: (row["block"], row["date"], row["race_id"]))


def original_root(row: dict) -> Path:
    return BLOCK_ROOTS[row["block"]] / f"prediction_{row['date']}"


def original_artifact(row: dict) -> Path:
    path = original_root(row) / f"{row['race_id']}_prediction.json"
    if not path.is_file():
        raise RuntimeError(f"ORIGINAL_ARTIFACT_MISSING:{path}")
    return path


def source_manifest(row: dict) -> tuple[Path, dict]:
    path = original_root(row) / "input_manifest.json"
    if not path.is_file():
        raise RuntimeError(f"ORIGINAL_INPUT_MANIFEST_MISSING:{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("date") != row["date"]:
        raise RuntimeError(f"ORIGINAL_INPUT_MANIFEST_DATE_MISMATCH:{row['race_id']}")
    sources = payload.get("sources")
    if not isinstance(sources, dict) or set(sources) != {"DG", "DE", "DS"}:
        raise RuntimeError(f"ORIGINAL_INPUT_MANIFEST_STRUCTURE_INVALID:{row['race_id']}")
    return path, sources


def verify_input(row: dict) -> dict:
    manifest_path, sources = source_manifest(row)
    checks = {}
    for kind in ("DG", "DE", "DS"):
        record = sources[kind]
        relative = record.get("path")
        expected = record.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise RuntimeError(f"ORIGINAL_INPUT_PROVENANCE_INVALID:{row['race_id']}:{kind}")
        path = ROOT / relative
        actual = sha256(path) if path.is_file() else None
        checks[kind] = {
            "path": relative.replace("\\", "/"),
            "expected_sha256": expected,
            "actual_sha256": actual,
            "match": actual == expected,
        }
    return {
        "race_id": row["race_id"],
        "date": row["date"],
        "temporal_block": row["block"],
        "original_input_manifest": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "inputs": checks,
        "all_match": all(item["match"] for item in checks.values()),
    }


def select_preflight(population: list[dict]) -> list[dict]:
    selected = []
    for block in BLOCK_ROOTS:
        rows = [row for row in population if row["block"] == block]
        selected.append(min(rows, key=lambda row: (row["date"], row["race_id"])))
    return selected


def reproduce(row: dict, bundles: dict) -> dict:
    date = row["date"]
    if date not in bundles:
        _, sources = source_manifest(row)
        bundles[date] = TargetBulkPredictionInputAdapterV1().load(
            ROOT / sources["DG"]["path"],
            ROOT / sources["DE"]["path"],
            ROOT / sources["DS"]["path"],
        )
    bundle = bundles[date]
    if bundle.date != date:
        raise RuntimeError(f"REPRODUCTION_TARGET_DATE_MISMATCH:{row['race_id']}:{bundle.date}")
    race = bundle.races.get(row["race_id"])
    if race is None:
        raise RuntimeError(f"REPRODUCTION_TARGET_RACE_MISSING:{row['race_id']}")
    output = run_new(row["race_id"], race, trace=True)
    artifact = _project_race(row["race_id"], output)
    artifact["buy_gate_trace"] = output["buy_gate_trace"]
    artifact["trace_status"] = "NOT_FORMALLY_FROZEN_TRACE"
    return artifact


def legacy_trace_projection(value: dict) -> dict:
    normalized = json.loads(json.dumps(value, ensure_ascii=False))
    for horse in normalized.get("horses", []):
        if isinstance(horse, dict):
            for field in TRACE_FIELDS:
                horse.pop(field, None)
    return normalized


def compare(row: dict, original: dict, reproduced: dict) -> dict:
    original_rows = {item.get("horse_number"): item for item in original.get("ranked_results", [])}
    reproduced_rows = {item.get("horse_number"): item for item in reproduced.get("ranked_results", [])}
    original_trace = {item.get("horse_number"): item for item in original.get("buy_gate_trace", {}).get("horses", [])}
    reproduced_trace = {item.get("horse_number"): item for item in reproduced.get("buy_gate_trace", {}).get("horses", [])}
    horse_set_match = set(original_rows) == set(reproduced_rows)
    evaluator_score_mismatch = 0
    aggregate_score_mismatch = 0
    rank_mismatch = 0
    buy_mismatch = 0
    trace_identity_mismatch = 0
    for number in set(original_rows) & set(reproduced_rows):
        left, right = original_rows[number], reproduced_rows[number]
        if canonical((original_trace.get(number) or {}).get("evaluator_score_snapshot")) != canonical((reproduced_trace.get(number) or {}).get("evaluator_score_snapshot")):
            evaluator_score_mismatch += 1
        if any(left.get(field) != right.get(field) for field in ("decision_score", "final_score", "adjusted_score")):
            aggregate_score_mismatch += 1
        if left.get("rank") != right.get("rank") or (original_trace.get(number) or {}).get("shadow_ai_rank") != (reproduced_trace.get(number) or {}).get("shadow_ai_rank"):
            rank_mismatch += 1
        if left.get("buy") != right.get("buy") or (original_trace.get(number) or {}).get("shadow_buy") != (reproduced_trace.get(number) or {}).get("shadow_buy"):
            buy_mismatch += 1
        if number not in original_trace or number not in reproduced_trace:
            trace_identity_mismatch += 1
    race_state_mismatch = int(canonical(original.get("buy_gate_trace", {}).get("race")) != canonical(reproduced.get("buy_gate_trace", {}).get("race")))
    legacy_exact_match = canonical(original) == canonical({
        **reproduced,
        "buy_gate_trace": legacy_trace_projection(reproduced.get("buy_gate_trace", {})),
    })
    return {
        "race_id": row["race_id"],
        "date": row["date"],
        "temporal_block": row["block"],
        "original_artifact": str(original_artifact(row).relative_to(ROOT)).replace("\\", "/"),
        "original_artifact_sha256": sha256(original_artifact(row)),
        "reproduced_horse_count": len(reproduced_rows),
        "original_horse_count": len(original_rows),
        "horse_set_mismatch": not horse_set_match,
        "evaluator_score_mismatch": evaluator_score_mismatch,
        "aggregate_score_mismatch": aggregate_score_mismatch,
        "rank_mismatch": rank_mismatch,
        "buy_mismatch": buy_mismatch,
        "race_state_mismatch": race_state_mismatch,
        "trace_identity_mismatch": trace_identity_mismatch,
        "legacy_semantics_exact_match": legacy_exact_match,
        "status": "EXACT_MATCH" if horse_set_match and evaluator_score_mismatch == aggregate_score_mismatch == rank_mismatch == buy_mismatch == race_state_mismatch == trace_identity_mismatch == 0 and legacy_exact_match else "MISMATCH",
    }


def write_reproduced_prediction(row: dict, artifact: dict) -> Path:
    path = OUT / "reproduced_predictions" / f"{row['race_id']}_prediction.json"
    dump(path, artifact)
    return path


def original_integrity(population: list[dict]) -> dict:
    return {
        str(original_artifact(row).relative_to(ROOT)).replace("\\", "/"): sha256(original_artifact(row))
        for row in population
    }


def build_manifest() -> None:
    files = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "replay_manifest.json":
            files.append({"relative_path": str(path.relative_to(OUT)).replace("\\", "/"), "sha256": sha256(path)})
    dump(OUT / "replay_manifest.json", {
        "schema_version": "RACE_COURSE_SHAPE_REPLAY_MANIFEST_V1",
        "reproduction_class": "CURRENT_AI_ARTIFACT_REPRODUCTION",
        "evidence_label": "RACE_COURSE_SHAPE_MECHANISM_DEVELOPMENT_EVIDENCE",
        "excludes": ["replay_manifest.json"],
        "files": files,
    })


def main() -> str:
    if OUT.exists():
        raise RuntimeError(f"OUTPUT_ROOT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    population = load_population()
    preflight_rows = select_preflight(population)
    source_hash_before = original_integrity(population)
    dump(OUT / "replay_protocol.json", {
        "reproduction_class": "CURRENT_AI_ARTIFACT_REPRODUCTION",
        "evidence_label": "RACE_COURSE_SHAPE_MECHANISM_DEVELOPMENT_EVIDENCE",
        "target_race_count": 54,
        "result_data_access_count": 0,
        "historical_code_claim": "NOT_EXACT_HISTORICAL_REPLAY",
        "trace_fields": list(TRACE_FIELDS),
        "trace_schema_version": "BUY_GATE_TRACE_SCHEMA_V1_1",
        "trace_schema_path": "docs/buy_gate_trace_schema_v1_1.json",
        "trace_schema_sha256": sha256(ROOT / "docs" / "buy_gate_trace_schema_v1_1.json"),
    })
    dump(OUT / "target_population.json", {
        "classification_source": str(CLASSIFICATION.relative_to(ROOT)).replace("\\", "/"),
        "classification_source_sha256": sha256(CLASSIFICATION),
        "target_race_count": len(population),
        "target_races": population,
    })
    dump(OUT / "preflight" / "target_selection.json", {
        "selection_rule": "lexicographically first fixed BUY_SELECTION_FAILURE race by date/race_id within each pre-existing temporal block; no Result outcome used for selection",
        "preflight_race_count": len(preflight_rows),
        "temporal_blocks": [row["block"] for row in preflight_rows],
        "selected_races": preflight_rows,
    })
    preflight_inputs = [verify_input(row) for row in preflight_rows]
    dump(OUT / "preflight" / "input_integrity.json", {"checks": preflight_inputs, "all_match": all(row["all_match"] for row in preflight_inputs)})
    dump(OUT / "preflight" / "result_isolation.json", {"result_data_access_count": 0, "result_file_loaded": False, "post_artifact_dependency": False, "actual_top3_dependency": False})
    if not all(row["all_match"] for row in preflight_inputs):
        dump(OUT / "preflight" / "reproducibility_comparison.json", {"status": "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE", "reason": "INPUT_SHA_MISMATCH", "comparisons": []})
        dump(OUT / "implementation_summary.json", {"status": "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE", "phase": "PREFLIGHT", "full_run_executed": False, "result_data_access_count": 0})
        (OUT / "preflight" / "preflight_report.md").write_text("# Preflight\n\nStatus: `RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE` due to input SHA mismatch. No reproduction was run.\n", encoding="utf-8")
        build_manifest()
        return "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE"

    bundles, preflight_comparisons = {}, []
    for row in preflight_rows:
        original = json.loads(original_artifact(row).read_text(encoding="utf-8"))
        reproduced = reproduce(row, bundles)
        comparison = compare(row, original, reproduced)
        preflight_comparisons.append(comparison)
    preflight_pass = all(row["status"] == "EXACT_MATCH" for row in preflight_comparisons)
    dump(OUT / "preflight" / "reproducibility_comparison.json", {"status": "REPLAY_REPRODUCIBILITY_PASS" if preflight_pass else "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE", "comparisons": preflight_comparisons})
    dump(OUT / "preflight" / "preflight_manifest.json", {"reproduction_class": "CURRENT_AI_ARTIFACT_REPRODUCTION", "preflight_race_count": len(preflight_rows), "all_temporal_blocks_covered": len(preflight_rows) == 4, "input_sha_match": True, "deterministic_semantics_match": preflight_pass, "result_data_access_count": 0})
    (OUT / "preflight" / "preflight_report.md").write_text(f"# Preflight\n\nStatus: `{'REPLAY_REPRODUCIBILITY_PASS' if preflight_pass else 'RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE'}`. Result access: 0.\n", encoding="utf-8")
    if not preflight_pass:
        dump(OUT / "implementation_summary.json", {"status": "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE", "phase": "PREFLIGHT", "full_run_executed": False, "result_data_access_count": 0})
        build_manifest()
        return "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE"

    all_inputs = [verify_input(row) for row in population]
    dump(OUT / "input_provenance.json", {"checks": all_inputs, "all_match": all(row["all_match"] for row in all_inputs)})
    if not all(row["all_match"] for row in all_inputs):
        dump(OUT / "full_reproduction_comparison.json", {"status": "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE", "reason": "INPUT_SHA_MISMATCH", "comparisons": []})
        dump(OUT / "implementation_summary.json", {"status": "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE", "phase": "FULL_INPUT_INTEGRITY", "full_run_executed": False, "result_data_access_count": 0})
        build_manifest()
        return "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE"

    comparisons = []
    for row in population:
        original = json.loads(original_artifact(row).read_text(encoding="utf-8"))
        reproduced = reproduce(row, bundles)
        prediction_path = write_reproduced_prediction(row, reproduced)
        comparison = compare(row, original, reproduced)
        comparison["reproduced_artifact"] = str(prediction_path.relative_to(ROOT)).replace("\\", "/")
        comparisons.append(comparison)
        if comparison["status"] != "EXACT_MATCH":
            break
    mismatch_categories = {
        "horse_set_mismatch": sum(row["horse_set_mismatch"] for row in comparisons),
        "evaluator_score_mismatch": sum(row["evaluator_score_mismatch"] for row in comparisons),
        "aggregate_score_mismatch": sum(row["aggregate_score_mismatch"] for row in comparisons),
        "rank_mismatch": sum(row["rank_mismatch"] for row in comparisons),
        "buy_mismatch": sum(row["buy_mismatch"] for row in comparisons),
        "race_state_mismatch": sum(row["race_state_mismatch"] for row in comparisons),
        "input_sha_mismatch": sum(not row["all_match"] for row in all_inputs),
        "result_access_violation": 0,
    }
    full_pass = len(comparisons) == len(population) and all(row["status"] == "EXACT_MATCH" for row in comparisons)
    dump(OUT / "full_reproduction_comparison.json", {
        "status": "CURRENT_AI_ARTIFACT_REPRODUCTION_PASS" if full_pass else "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE",
        "total_target_races": len(population), "reproduced_races": len(comparisons),
        "exact_match_races": sum(row["status"] == "EXACT_MATCH" for row in comparisons),
        "mismatch_races": sum(row["status"] != "EXACT_MATCH" for row in comparisons),
        "total_horses": sum(row["reproduced_horse_count"] for row in comparisons),
        "mismatch_categories": mismatch_categories,
        "comparisons": comparisons,
    })
    source_hash_after = original_integrity(population)
    dump(OUT / "original_artifact_integrity.json", {"referenced_artifact_count": len(source_hash_before), "unchanged": source_hash_before == source_hash_after, "before": source_hash_before, "after": source_hash_after})
    dump(OUT / "result_isolation.json", {"result_data_access_count": 0, "result_file_loaded": False, "post_artifact_dependency": False, "actual_top3_dependency": False})
    dump(OUT / "implementation_summary.json", {"status": "CURRENT_AI_ARTIFACT_REPRODUCTION_PASS" if full_pass else "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE", "full_run_executed": True, "target_race_count": len(population), "reproduced_race_count": len(comparisons), "four_trace_fields_persisted": full_pass, "pair_mechanism_input_created": False, "result_data_access_count": 0, "original_artifacts_unchanged": source_hash_before == source_hash_after})
    (OUT / "report.md").write_text(f"# Current AI Artifact Reproduction v1\n\nStatus: `{'CURRENT_AI_ARTIFACT_REPRODUCTION_PASS' if full_pass else 'RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE'}`. This is CURRENT_AI_ARTIFACT_REPRODUCTION mechanism-development evidence, not exact historical replay, Prospective evidence, Baseline, or CF Shadow evidence.\n", encoding="utf-8")
    build_manifest()
    return "CURRENT_AI_ARTIFACT_REPRODUCTION_PASS" if full_pass else "RETROSPECTIVE_REPLAY_NOT_REPRODUCIBLE"


if __name__ == "__main__":
    print(main())
