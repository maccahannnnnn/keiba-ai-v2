"""Create the declared review-state freeze for the future April PRE path.

Only non-April frozen Prediction/Trace artifacts and the frozen August V2 PRE
manifest are read.  No raw input, result source, outcome field, or April/May
file is opened.
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import runpy
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.learned_convergence_selector_v3_pre_v1 import FEATURES, MODEL_PATH, MODEL_SHA256, load_frozen_v3_model, select_v3_pre


OUT = ROOT / "reports" / "april_pre_code_freeze_v1"
TRAIN_MANIFEST = ROOT / "reports" / "low_capacity_top3_selector_v2_train_v1_retry2" / "train_candidate_manifest.csv"
ENVIRONMENT_MANIFEST = ROOT / "reports" / "low_capacity_top3_selector_v2_train_v1_retry2" / "environment_manifest.json"
V3_PROTOCOL = ROOT / "reports" / "learned_convergence_selector_v3_prospective_shadow_protocol_v1" / "learned_convergence_selector_v3_formal_prospective_shadow_protocol_v1.md"
CF_PROTOCOL = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1" / "protocol.json"
V2_AUGUST_PRE = ROOT / "reports" / "low_capacity_top3_selector_v2_august_validation_v1" / "validation_pre_outcome_manifest.csv"
TRAIN_SHA = "16764801c20b99a3c06d4478241c572cb6b78294f30b7bc37c08b08c7f5dc59a"
ENV_SHA = "12c63de76bbed1f4da97bdff115e2f865f05a4846a88c64d7a58717d3a821b02"
V3_SHA = "afeeb97a603c1477974a72821e9b9be5506797183c1f53d65f6198d7d4891087"
JUNE = ("20260620", "20260621", "20260627", "20260628")
JULY_H1 = ("20260704", "20260705", "20260711", "20260712")
JULY_H2 = ("20260718", "20260719", "20260725", "20260726")
AUGUST = ("20260801", "20260802", "20260808", "20260809", "20260815", "20260816")
ROOTS = {
    **{d: ROOT / "reports" / "h5_temporal_june_block1_v1" / f"prediction_{d}" for d in JUNE},
    **{d: ROOT / "reports" / "cand_h5_001_july_4day_validation_v1" / f"prediction_{d}" for d in JULY_H1},
    **{d: ROOT / "reports" / "h5_temporal_july_h2_v1" / f"prediction_{d}" for d in JULY_H2},
    **{d: ROOT / "reports" / "buy_improvement_trace_6day_v1" / f"prediction_{d}" for d in AUGUST},
}
COMPONENTS = (
    "engine/shadow_buy_decision_engine.py", "engine/buy_specification.py", "review/prospective_prediction_runner_v1.py",
    "review/target_bulk_prediction_input_adapter_v1.py", "review/target_bulk_prediction_input_shadow_v1.py",
    "review/cf_top3_rank_anchored_shadow_v1.py", "review/learned_convergence_selector_v3_pre_v1.py",
    "importer/target_column_mapping.py", "analyzer/schemas.py", "docs/buy_gate_trace_schema_v1_1.json",
)


def fail(code: str) -> None:
    raise RuntimeError(code)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def column_maps() -> tuple[dict, dict]:
    """Load static maps without importing the package's runtime graph."""
    values = runpy.run_path(str(ROOT / "importer" / "target_column_mapping.py"))
    entry = values.get("TARGET_ENTRY_COLUMN_MAP")
    history = values.get("TARGET_HISTORY_COLUMN_MAP")
    if not isinstance(entry, dict) or not isinstance(history, dict):
        fail("APRIL_PRE_PHASE0_RESULT_ISOLATION_FAILURE:COLUMN_MAP_LOAD")
    return entry, history


def write_json(name: str, value: object) -> Path:
    path = OUT / name
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def git_status() -> tuple[str, dict[str, str]]:
    process = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=True)
    mapping: dict[str, str] = {}
    for line in process.stdout.splitlines():
        if len(line) >= 4:
            mapping[line[3:].replace("\\", "/")] = line[:2]
    return process.stdout, mapping


def component_state(path: str, status: dict[str, str]) -> str:
    if path in status:
        return "untracked" if status[path] == "??" else "dirty"
    return "clean"


def expected_august() -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    with V2_AUGUST_PRE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["convergence_state"] != "PLAY_UNCONVERGED_4PLUS":
                continue
            groups[row["race_id"]].append({
                "horse_number": int(row["horse_number"]), "shadow_ai_rank": int(float(row["shadow_ai_rank"])),
                "predicted_top3_probability": float(row["predicted_top3_probability"]),
            })
    return groups


def run() -> None:
    if OUT.exists():
        fail("APRIL_PRE_PHASE0_CODE_FREEZE_FAILURE:OUTPUT_EXISTS")
    OUT.mkdir(parents=True)
    for path in (MODEL_PATH, TRAIN_MANIFEST, ENVIRONMENT_MANIFEST, V3_PROTOCOL, CF_PROTOCOL, V2_AUGUST_PRE):
        if not path.is_file():
            fail(f"APRIL_PRE_PHASE0_CODE_FREEZE_FAILURE:MISSING:{path}")
    frozen = {"model": sha(MODEL_PATH), "train_manifest": sha(TRAIN_MANIFEST), "environment": sha(ENVIRONMENT_MANIFEST), "v3_protocol": sha(V3_PROTOCOL), "cf_protocol": sha(CF_PROTOCOL)}
    if frozen["model"] != MODEL_SHA256:
        fail("APRIL_PRE_PHASE0_MODEL_SHA_MISMATCH")
    if frozen["train_manifest"] != TRAIN_SHA or frozen["environment"] != ENV_SHA or frozen["v3_protocol"] != V3_SHA:
        fail("APRIL_PRE_PHASE0_ARTIFACT_HASH_FAILURE")
    pipeline = load_frozen_v3_model()

    expected = expected_august()
    actual_august: dict[str, dict] = {}
    all_artifacts: list[dict] = []
    total_artifacts = 0
    for date, root in ROOTS.items():
        paths = sorted(root.glob("race_*_prediction.json"))
        if not paths:
            fail(f"APRIL_PRE_PHASE0_CODE_FREEZE_FAILURE:MISSING_PRE_ARTIFACTS:{date}")
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            selection = select_v3_pre(payload, pipeline)
            total_artifacts += 1
            all_artifacts.append({"path": str(path.relative_to(ROOT)), "sha256": sha(path), "race_id": selection["race_id"], "race_state": selection["race_state"], "eligible": selection["eligible"]})
            if date in AUGUST and selection["eligible"]:
                actual_august[selection["race_id"]] = selection
    if set(actual_august) != set(expected):
        fail("APRIL_PRE_PHASE0_SELECTION_EQUIVALENCE_FAILURE:ELIGIBLE_RACE_SET")
    comparison_rows: list[dict] = []
    for race_id, reference in expected.items():
        selection = actual_august[race_id]
        actual = selection["all_candidates"]
        reference_by_rank = {row["shadow_ai_rank"]: row for row in reference}
        actual_by_rank = {row["shadow_ai_rank"]: row for row in actual}
        if set(actual_by_rank) != set(reference_by_rank):
            fail(f"APRIL_PRE_PHASE0_SELECTION_EQUIVALENCE_FAILURE:ELIGIBLE_SET:{race_id}")
        for rank in reference_by_rank:
            a, e = actual_by_rank[rank], reference_by_rank[rank]
            if a["horse_number"] != e["horse_number"] or a["predicted_top3_probability"] != e["predicted_top3_probability"]:
                fail(f"APRIL_PRE_PHASE0_SELECTION_EQUIVALENCE_FAILURE:PROBABILITY_OR_IDENTITY:{race_id}:{rank}")
            comparison_rows.append({"race_id": race_id, "shadow_ai_rank": rank, "horse_number": a["horse_number"], "probability_exact_match": True})
        reference_order = sorted(reference, key=lambda row: (-row["predicted_top3_probability"], row["shadow_ai_rank"], row["horse_number"]))[:3]
        actual_order = selection["selected"]
        if [(row["horse_number"], row["shadow_ai_rank"]) for row in actual_order] != [(row["horse_number"], row["shadow_ai_rank"]) for row in reference_order]:
            fail(f"APRIL_PRE_PHASE0_SELECTION_EQUIVALENCE_FAILURE:SELECTED_TRIPLE:{race_id}")
    status_text, status_map = git_status()
    components = []
    for name in COMPONENTS:
        path = ROOT / name
        if not path.is_file():
            fail(f"APRIL_PRE_PHASE0_CODE_FREEZE_FAILURE:COMPONENT_MISSING:{name}")
        components.append({"path": name, "sha256": sha(path), "working_tree_state": component_state(name, status_map)})
    entry_map, history_map = column_maps()
    entry_keys = {key.lower() for key in entry_map}
    if any("finish" in key or "outcome" in key for key in entry_keys):
        fail("APRIL_PRE_PHASE0_RESULT_ISOLATION_FAILURE:ENTRY_OUTCOME_FIELD")
    if "finish_position" not in history_map:
        fail("APRIL_PRE_PHASE0_RESULT_ISOLATION_FAILURE:HISTORY_FINISH_POSITION_MISSING")
    equivalence = {
        "status": "PASS", "classification": "CODE_EQUIVALENCE_CHECK_ONLY_DIAGNOSTIC_NOT_EVIDENCE",
        "non_april_input_set": {"all_18_day_frozen_pre_artifacts": total_artifacts, "august_reference_manifest": str(V2_AUGUST_PRE.relative_to(ROOT)), "august_unconverged_reference_races": len(expected)},
        "frozen_model_sha_match": True, "feature_order": list(FEATURES), "feature_order_match": True,
        "eligible_set_equivalence": "PASS", "ranking_equivalence": "PASS", "selected_horse_number_equivalence": "PASS",
        "tie_break_equivalence": "PASS", "probability_exact_match": "PASS", "max3_equivalence": "PASS",
        "comparison_rows": comparison_rows, "result_access": 0, "performance_access": 0,
    }
    write_json("equivalence_check.json", equivalence)
    write_json("result_isolation_spec.json", {
        "april_input_path_checked": False, "future_pre_requirement": "Confirm Result/outcome filenames and file types are absent from April PRE input path before execution.",
        "target_entry_current_race_finish_or_outcome_fields_present": False,
        "target_history_finish_position_present": True,
        "history_finish_position_interpretation": "Horse past-race result; legitimate PRE history input, not current-race Result leakage.",
        "april_source_access": 0, "april_result_access": 0,
    })
    manifest = {
        "protocol": "APRIL_PRE_CODE_FREEZE_V1", "status": "APRIL_PRE_PHASE0_FROZEN_READY", "generated_at": datetime.now(timezone.utc).isoformat(),
        "git": {"HEAD": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip(), "working_tree_dirty": bool(status_text.strip()), "status_short": status_text},
        "components": components, "frozen_authority": frozen, "execution_environment": {"python_executable": sys.executable, "python_version": sys.version, "implementation": platform.python_implementation()},
        "semantic_scope_review": {"wrapper_gate_reimplementation": False, "wrapper_eligibility_source": "shadow_buy_candidate only", "horse_number_authority": "ranked_results[].horse_number", "trace_horse_number_echo_dependency": False, "tie_break": ["predicted_top3_probability DESC", "safe shadow_ai_rank ASC", "horse_number ASC"], "candidate_semantics_change": 0},
        "equivalence_check": "equivalence_check.json", "result_isolation": "result_isolation_spec.json",
        "access_counts": {"april_source": 0, "april_result": 0, "result_performance": 0, "may": 0}, "changes": {"production": 0, "v3_candidate_semantics": 0, "cf_candidate_semantics": 0},
        "historical_replay_runner_relevance": "IRRELEVANT_TO_APRIL_PRE",
    }
    manifest_path = write_json("code_freeze_manifest.json", manifest)
    report_path = OUT / "report.md"
    report_path.write_text("# April PRE Phase 0 Code Freeze v1\n\n`APRIL_PRE_PHASE0_FROZEN_READY`. Generic V3 wrapper equivalence was checked against frozen non-April August PRE probabilities and selections. The 18-day PRE artifact family was read only for structural wrapper coverage. No April/May source, Result, or performance data was accessed. No Production, V3 semantic, or CF semantic change occurred.\n", encoding="utf-8")
    write_json("artifact_hashes.json", {"code_freeze_manifest_sha256": sha(manifest_path), "equivalence_check_sha256": sha(OUT / "equivalence_check.json"), "result_isolation_spec_sha256": sha(OUT / "result_isolation_spec.json"), "report_sha256": sha(report_path), "wrapper_sha256": sha(ROOT / "review" / "learned_convergence_selector_v3_pre_v1.py")})


if __name__ == "__main__":
    run()
