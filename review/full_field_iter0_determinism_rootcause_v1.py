"""Targeted, result-free diagnosis for the Iter0 PRE-only nondeterminism.

This utility deliberately runs only 2026-03-21 Hanshin 6R and records the
absolute-quality inputs for horse 4.  It neither opens any result source nor
performs a result join, training, or production mutation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import locale
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = Path(os.environ.get(
    "FULL_FIELD_ITER0_ROOTCAUSE_OUTPUT_ROOT",
    str(ROOT / "reports" / "full_field_redesign_iter0_determinism_rootcause_v1"),
)).resolve()
DATE = "20260321"
RACE_ID = "race_20260321_hanshin_6R"
HORSE_NUMBER = "4"
RUN_COUNT = 5
PRIOR_REPLAY_ROOT = ROOT / "reports" / "full_field_redesign_iter0_v1_retry4" / "pre_only_regeneration" / "shards"
RAW_SOURCE_PATHS = {
    "DG": ROOT / "data" / "raw" / "prediction_input" / "DG260321.CSV",
    "DE": ROOT / "data" / "raw" / "prediction_input" / "DE260321.CSV",
    "DS": ROOT / "data" / "raw" / "prediction_input" / "DS260321.CSV",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def csv_write(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def worker(output: Path) -> None:
    from engine.shadow_buy_decision_engine import ShadowBUYDecisionEngine
    from review.target_bulk_prediction_input_shadow_v1 import run_new
    from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
    from review.ws2_deterministic_pre_only_regeneration_v1 import POLICY_PATH, PreOnlyBoundary, RuntimeTrace

    paths = dict(RAW_SOURCE_PATHS)
    if not all(path.is_file() for path in paths.values()):
        raise RuntimeError("STOP_TARGET_RAW_SOURCE_MISSING")
    allowed = set(paths.values()) | {
        POLICY_PATH,
        ROOT / "reports" / "ws2_known_data_integrity_exclusion_bridge_20260823_v1" / "exclusion_bridge.json",
        ROOT / "reports" / "ws2_existing_adapter_compatibility_reuse_20260906_v1" / "compatibility_reuse.json",
        ROOT / "reports" / "ml_v4_buy_selection_dataset_v5_source_lineage_correction_20260418_v1" / "correction.json",
    }
    trace = RuntimeTrace()
    captured: list[dict[str, Any]] = []
    original = ShadowBUYDecisionEngine._horse_record

    def wrapped(self: ShadowBUYDecisionEngine, horse: dict[str, Any], ranked: list[dict[str, Any]]) -> dict[str, Any]:
        record = original(self, horse, ranked)
        if str(horse.get("horse_number")) == HORSE_NUMBER:
            relevant = {
                key: horse.get(key)
                for key in (
                    "horse_number", "horse_name", "registration_id", "registration_number", "decision", "rank", "final_rank", "score_rank",
                    "decision_score", "final_score", "adjusted_score", "integrated_score", "weighted_score",
                    "total_score", "ability_score", "past_performance_score", "distance_score",
                    "course_shape_score", "course_score", "lap_score", "lap_suitability_score",
                    "shape_score", "race_shape_score", "pace_style_score", "running_style_score",
                )
            }
            captured.append({
                "horse_input": relevant,
                "horse_input_repr": {key: repr(value) for key, value in relevant.items()},
                "record_before_projection": {
                    key: record.get(key)
                    for key in ("current_decision", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass")
                },
                "thresholds": {
                    "MIN_DECISION_SCORE": self.config.MIN_DECISION_SCORE,
                    "MIN_FINAL_SCORE": self.config.MIN_FINAL_SCORE,
                    "MIN_ADJUSTED_SCORE": self.config.MIN_ADJUSTED_SCORE,
                },
            })
        return record

    ShadowBUYDecisionEngine._horse_record = wrapped
    try:
        with PreOnlyBoundary(allowed_reads=allowed, output_root=output.parent, trace=trace):
            bundle = TargetBulkPredictionInputAdapterV1().load(paths["DG"], paths["DE"], paths["DS"])
            race = bundle.races.get(RACE_ID)
            if race is None:
                raise RuntimeError("STOP_TARGET_RACE_NOT_FOUND")
            payload = run_new(RACE_ID, race, trace=True)
    finally:
        ShadowBUYDecisionEngine._horse_record = original
    gate_rows = payload.get("buy_gate_trace", {}).get("horses", [])
    gate = next((item for item in gate_rows if str(item.get("horse_number")) == HORSE_NUMBER), None)
    ranked = next((item for item in payload.get("ranked_results", []) if str(item.get("horse_number")) == HORSE_NUMBER), None)
    if not isinstance(gate, dict) or not isinstance(ranked, dict) or len(captured) != 1:
        raise RuntimeError("STOP_TARGET_TRACE_CAPTURE_INVALID")
    trace.finalize_hashes()
    record = captured[0]
    value = number_or_none(record["horse_input"].get("decision_score"))
    final = number_or_none(record["horse_input"].get("final_score"))
    adjusted = number_or_none(record["horse_input"].get("adjusted_score"))
    thresholds = record["thresholds"]
    dump(output, {
        "date": DATE,
        "race_id": RACE_ID,
        "venue": "阪神",
        "race_number": 6,
        "source_files": {kind: {"path": str(path.relative_to(ROOT)).replace("\\\\", "/"), "sha256": sha256(path)} for kind, path in paths.items()},
        "identity": {
            "horse_number": HORSE_NUMBER,
            "horse_name": record["horse_input"].get("horse_name"),
            "registration_id": record["horse_input"].get("registration_id") or record["horse_input"].get("registration_number"),
        },
        "captured": record,
        "gate_trace": {key: gate.get(key) for key in ("horse_number", "horse_name", "current_decision", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass", "evaluator_score_snapshot", "positive_count", "negative_count")},
        "ranked_row": {key: ranked.get(key) for key in ("horse_number", "horse_name", "rank", "decision", "decision_score", "final_score", "adjusted_score")},
        "threshold_margins": {
            "decision_score_minus_threshold": None if value is None else value - thresholds["MIN_DECISION_SCORE"],
            "final_score_minus_threshold": None if final is None else final - thresholds["MIN_FINAL_SCORE"],
            "adjusted_score_minus_threshold": None if adjusted is None else adjusted - thresholds["MIN_ADJUSTED_SCORE"],
            "repr": {"decision_score": repr(value), "final_score": repr(final), "adjusted_score": repr(adjusted), "MIN_DECISION_SCORE": repr(thresholds["MIN_DECISION_SCORE"]), "MIN_FINAL_SCORE": repr(thresholds["MIN_FINAL_SCORE"]), "MIN_ADJUSTED_SCORE": repr(thresholds["MIN_ADJUSTED_SCORE"])},
        },
        "runtime": {"python": sys.version, "executable": sys.executable, "hash_seed": os.environ.get("PYTHONHASHSEED"), "locale": locale.setlocale(locale.LC_ALL, None), "platform": platform.platform()},
        "boundary": {"violations": trace.violations, "network_access_attempt_count": trace.network_attempts, "opened_file_count": len(trace.opens), "imports_count": len(trace.imports)},
    })


def code_sha(path: Path) -> str:
    return sha256(path)


def suspect_matrix() -> list[dict[str, str]]:
    rows = [
        ("Python set iteration", "PRESENT", "engine/shadow_buy_decision_engine.py:96-101 creates name sets after _horse_record; absolute computation itself is executed beforehand."),
        ("unordered dict construction", "NOT_RELEVANT", "The absolute predicate reads named horse fields directly at engine/shadow_buy_decision_engine.py:156-165."),
        ("glob/file iteration order", "NOT_RELEVANT", "Target run uses explicitly authenticated DG/DE/DS paths; no glob is in the absolute predicate path."),
        ("random", "ABSENT", "No random import/use in engine/shadow_buy_decision_engine.py or engine/buy_specification.py."),
        ("numpy random", "ABSENT", "No numpy import/use in the absolute predicate modules."),
        ("pandas unstable sort", "ABSENT", "No pandas import/use in the absolute predicate modules."),
        ("tie without secondary key", "PRESENT", "_with_ranks sorts by score then negative existing rank at engine/shadow_buy_decision_engine.py:419-426; it does not directly determine absolute_quality_pass."),
        ("hash()", "ABSENT", "No hash() use in the absolute predicate modules."),
        ("PYTHONHASHSEED", "NOT_RELEVANT", "Recorded per fresh worker; absolute predicate has no hash-derived input."),
        ("locale", "NOT_RELEVANT", "Recorded per fresh worker; numeric comparisons use float values and fixed numeric constants."),
        ("datetime now/today", "ABSENT", "No datetime/time dependency in the absolute predicate modules."),
        ("timezone", "NOT_RELEVANT", "No timezone dependency in the absolute predicate modules."),
        ("float boundary comparison", "PRESENT", "Three >= comparisons occur at engine/shadow_buy_decision_engine.py:160-164; margins are recorded per run."),
        ("multiprocessing/threading", "ABSENT", "No multiprocessing/threading use in the absolute predicate modules."),
        ("cached mutable state", "UNRESOLVED", "Fresh Python worker processes eliminate inter-run in-process cache carryover; input-to-decision mutation is checked from captured fields."),
        ("module-level mutable state", "UNRESOLVED", "Fresh Python worker processes eliminate persistence; code-level mutable-state cause requires later code review if reproduction occurs."),
    ]
    return [{"suspect": name, "status": status, "evidence": evidence} for name, status, evidence in rows]


def prior_replay_lineage() -> dict[str, Any]:
    """Read only source-open trace entries for the original run-A/B evidence."""
    expected = {"DG": "DG260321.CSV", "DE": "DE260321.CSV", "DS": "DS260321.CSV"}
    output: dict[str, dict[str, set[str]]] = {"run_a": {kind: set() for kind in expected}, "run_b": {kind: set() for kind in expected}}
    for lane in output:
        for trace_path in PRIOR_REPLAY_ROOT.glob(f"{lane}_*/runtime_file_access_trace.json"):
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            for item in trace.get("opens", []):
                path = str(item.get("path", "")).replace("\\", "/")
                for kind, filename in expected.items():
                    if path.endswith("/" + filename):
                        digest = item.get("sha256")
                        if isinstance(digest, str):
                            output[lane][kind].add(digest)
    normalized = {lane: {kind: sorted(values) for kind, values in parts.items()} for lane, parts in output.items()}
    complete = all(len(normalized[lane][kind]) == 1 for lane in normalized for kind in expected)
    same = complete and all(normalized["run_a"][kind] == normalized["run_b"][kind] for kind in expected)
    return {"status": "MATCH" if same else "UNRESOLVED", "complete": complete, "runs": normalized}


def main() -> Path:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    OUT.mkdir(parents=True)
    workers: list[dict[str, Any]] = []
    for index in range(1, RUN_COUNT + 1):
        path = OUT / f"worker_run_{index}.json"
        completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(path)], cwd=ROOT, capture_output=True, text=True)
        if completed.returncode != 0:
            dump(OUT / "worker_failure.json", {"run": index, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
            raise RuntimeError(f"STOP_TARGET_REPRODUCTION_WORKER_{index}")
        workers.append(json.loads(path.read_text(encoding="utf-8")))
    source_sets = [{kind: row["source_files"][kind]["sha256"] for kind in ("DG", "DE", "DS")} for row in workers]
    same_inputs = all(item == source_sets[0] for item in source_sets)
    decisions = [row["gate_trace"].get("absolute_quality_pass") for row in workers]
    captured_inputs = [row["captured"]["horse_input_repr"] for row in workers]
    exact_inputs = all(item == captured_inputs[0] for item in captured_inputs)
    variable = len(set(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in workers)) > 1
    reproduction = len(set(decisions)) > 1
    margins = [row["threshold_margins"] for row in workers]
    near = any(abs(float(margin[key])) < 1e-12 for margin in margins for key in ("decision_score_minus_threshold", "final_score_minus_threshold", "adjusted_score_minus_threshold") if margin[key] is not None)
    prior_lineage = prior_replay_lineage()
    root_class = "UNKNOWN"
    detail = "Five fresh-process runs produced a stable output. The prior A/B difference was not reproduced."
    if reproduction and not same_inputs:
        root_class, detail = "INPUT_NONDETERMINISM", "At least one DG/DE/DS SHA differs across target runs."
    elif reproduction and near:
        root_class, detail = "FLOAT_BOUNDARY", "The output varied and at least one direct threshold margin is at the float boundary."
    elif reproduction and same_inputs:
        root_class, detail = "COMPUTATION_NONDETERMINISM", "Identical input SHA with differing target output across fresh processes."
    elif not reproduction and same_inputs and exact_inputs and prior_lineage["status"] == "MATCH":
        root_class, detail = "COMPUTATION_NONDETERMINISM", "The prior run-A/B divergence used identical traced DG/DE/DS hashes, but five isolated fresh-process target reruns were stable. The non-determinism is therefore computation-path-localized only, not reproduced or pinpointed further."
    elif not reproduction and same_inputs and exact_inputs:
        root_class, detail = "UNKNOWN", "No target variation in five fresh-process reproductions; prior run A/B discrepancy is not reproduced by the isolated target path."
    rows = []
    for index, item in enumerate(workers, start=1):
        gate = item["gate_trace"]
        margin = item["threshold_margins"]
        rows.append({"run": index, "absolute_quality_pass": gate.get("absolute_quality_pass"), "current_decision": gate.get("current_decision"), "decision_score": gate.get("decision_score"), "final_score": gate.get("final_score"), "adjusted_score": gate.get("adjusted_score"), "decision_margin": margin.get("decision_score_minus_threshold"), "final_margin": margin.get("final_score_minus_threshold"), "adjusted_margin": margin.get("adjusted_score_minus_threshold"), "dg_sha256": item["source_files"]["DG"]["sha256"], "de_sha256": item["source_files"]["DE"]["sha256"], "ds_sha256": item["source_files"]["DS"]["sha256"], "boundary_violation_count": len(item["boundary"]["violations"]), "network_access_attempt_count": item["boundary"]["network_access_attempt_count"]})
    csv_write(OUT / "target_reproduction_runs.csv", rows, list(rows[0]))
    immediate_fields = sorted({key for item in workers for key in item["captured"]["horse_input_repr"]})
    input_rows = [{"field": field, **{f"run_{idx}": item["captured"]["horse_input_repr"].get(field) for idx, item in enumerate(workers, 1)}, "all_runs_identical": len({item["captured"]["horse_input_repr"].get(field) for item in workers}) == 1} for field in immediate_fields]
    csv_write(OUT / "immediate_input_comparison.csv", input_rows, list(input_rows[0]))
    trace = {"source_file": "engine/shadow_buy_decision_engine.py", "source_sha256": code_sha(ROOT / "engine" / "shadow_buy_decision_engine.py"), "function": "ShadowBUYDecisionEngine._horse_record", "line_range": "143-165", "formula": "current_decision == 'BUY' OR (decision_score >= MIN_DECISION_SCORE AND final_score >= MIN_FINAL_SCORE AND adjusted_score >= MIN_ADJUSTED_SCORE)", "threshold_source": "engine/buy_specification.py:92-94", "threshold_source_sha256": code_sha(ROOT / "engine" / "buy_specification.py"), "thresholds": workers[0]["captured"]["thresholds"], "preprocessing": "_number_or_none at engine/shadow_buy_decision_engine.py:597-603 converts non-empty non-bool values through float(); no rounding before >=.", "missing_handling": "None causes the corresponding conjunction term to fail.", "runs": [{"run": idx, "gate_trace": item["gate_trace"], "threshold_margins": item["threshold_margins"]} for idx, item in enumerate(workers, 1)]}
    dump(OUT / "absolute_quality_trace.json", trace)
    suspects = suspect_matrix(); csv_write(OUT / "determinism_suspect_matrix.csv", suspects, list(suspects[0]))
    lineage = {"status": "MATCH" if same_inputs else "MISMATCH", "classification": "SOURCE_SHA_MATCH" if same_inputs else "INPUT_NONDETERMINISM", "isolated_runs": [{"run": idx, "files": item["source_files"]} for idx, item in enumerate(workers, 1)], "prior_retry4_runs": prior_lineage}
    dump(OUT / "input_lineage_sha.json", lineage)
    root = {"reproduced": "YES" if reproduction else "NO", "root_cause_class": root_class, "root_cause_detail": detail, "fix_scope_estimate": "UNKNOWN", "safe_to_fix_without_model_semantic_change": "UNCERTAIN", "ready_for_claude_review": "YES", "float_boundary_sensitivity": near, "source_lineage": lineage["status"], "immediate_input_values_identical": exact_inputs, "prior_retry4_difference": {"date": DATE, "race_id": RACE_ID, "horse_number": HORSE_NUMBER, "field": "absolute_quality_pass", "run_a": True, "run_b": False}, "result_access": 0, "training": False, "production_changed": False}
    dump(OUT / "root_cause.json", root)
    summary = "# Iter0 PRE-only Determinism Root Cause\n\n対象は2026-03-21 阪神6R #4です。5回のfresh-process PRE-only再生成を行い、Result/POST/learningを開かずにabsolute_quality_passの入力と式を記録しました。\n\n" + f"- REPRODUCED: {root['reproduced']}\n- ROOT_CAUSE_CLASS: {root_class}\n- FLOAT_BOUNDARY_SENSITIVITY: {near}\n- INPUT_LINEAGE: {lineage['status']}\n- Result access: 0\n"
    (OUT / "summary.md").write_text(summary, encoding="utf-8")
    hashes = {path.name: sha256(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}
    dump(OUT / "artifact_hashes.json", {"indexed_artifacts": hashes, "self_hash_excluded": True, "generated_at": datetime.now(timezone.utc).isoformat()})
    return OUT


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
    else:
        print(main())
