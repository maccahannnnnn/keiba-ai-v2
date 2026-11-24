"""Frozen, result-free April eight-date PRE orchestration."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.april_pre_execution_v1 import phase0_code_state
from review.cf_top3_rank_anchored_shadow_v1 import select_pre
from review.learned_convergence_selector_v3_pre_v1 import load_frozen_v3_model, select_v3_pre
from review.prospective_prediction_runner_v1 import (
    POPULATION_SCOPE_ID, SCHEMA_VERSION, _assert_population, _canonical_write,
    _project_race, _sha256, _write_report,
)
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new


SOURCE_SET = ROOT / "reports" / "april_2026_source_recovery_20260418_v1_completion_v1_recovery_v2" / "april_active_source_set_manifest.json"
SOURCE_SET_SHA = "325c90baa44399ab033a27af447e93bf2acd1167d069b7200028cda28d29899a"
APRIL_PROTOCOL = ROOT / "reports" / "april_2026_retrospective_external_holdout_v2" / "protocol.md"
OUT = ROOT / "reports" / "april_2026_retrospective_external_holdout_v2" / "pre_execution_full_8date_v1"
DATES = ("20260404", "20260405", "20260411", "20260412", "20260418", "20260419", "20260425", "20260426")


class Stop(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}:{detail}")
        self.code, self.detail = code, detail


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def active_sources() -> tuple[dict, dict[str, dict[str, Path]]]:
    if not SOURCE_SET.is_file() or sha(SOURCE_SET) != SOURCE_SET_SHA:
        raise Stop("APRIL_PRE_ACTIVE_SOURCE_SET_MISMATCH", "SOURCE_SET_SHA")
    manifest = json.loads(SOURCE_SET.read_text(encoding="utf-8"))
    if manifest.get("status") != "APRIL_SOURCE_RECOVERY_READY_FOR_PRE_EXECUTION":
        raise Stop("APRIL_PRE_ACTIVE_SOURCE_SET_MISMATCH", "SOURCE_SET_STATUS")
    paths: dict[str, dict[str, Path]] = {}
    for record in manifest.get("active_dates", []):
        date = record.get("date")
        if date not in DATES or date in paths:
            raise Stop("APRIL_PRE_ACTIVE_SOURCE_SET_MISMATCH", f"DATE:{date}")
        current = {}
        for kind in ("DG", "DE", "DS"):
            item = record.get("sources", {}).get(kind, {})
            path = ROOT / str(item.get("path", ""))
            if not path.is_file() or sha(path) != item.get("sha256"):
                raise Stop("APRIL_PRE_ACTIVE_SOURCE_SET_MISMATCH", f"{date}:{kind}")
            current[kind] = path
        paths[date] = current
    if set(paths) != set(DATES):
        raise Stop("APRIL_PRE_ACTIVE_SOURCE_SET_MISMATCH", "DATE_SET")
    return manifest, paths


def preflight(paths: dict[str, dict[str, Path]]) -> tuple[dict[str, object], dict[str, object]]:
    adapter = TargetBulkPredictionInputAdapterV1()
    bundles, records = {}, {}
    for date in DATES:
        try:
            bundle = adapter.load(paths[date]["DG"], paths[date]["DE"], paths[date]["DS"])
            if bundle.date != date:
                raise ValueError(f"TARGET_DATE_MISMATCH:{bundle.date}")
            _assert_population(bundle)
            raw, _ = adapter._read_fixed(paths[date]["DG"], "DG")
            counts = {"new_race_count": sum("新馬" in adapter._text(row[5]) for row in raw),
                      "maiden_race_count": sum("未勝利" in adapter._text(row[5]) for row in raw),
                      "jump_race_count": sum(adapter._text(row[7]) == "障害" for row in raw)}
            if any(counts.values()):
                raise ValueError(f"UNEXPECTED_PREDICTION_POPULATION_RACE:{date}")
            bundles[date] = bundle
            records[date] = {"status": "PASS", "population_counts": counts, "preflight": bundle.preflight,
                             "race_ids": sorted(bundle.races), "race_count": len(bundle.races),
                             "horse_count": sum(len(r.today_entries) for r in bundle.races.values())}
        except Exception as exc:
            code = str(exc).split(":", 1)[0]
            if code == "UNEXPECTED_PREDICTION_POPULATION_RACE":
                raise Stop("APRIL_PRE_UNEXPECTED_PREDICTION_POPULATION_RACE", f"{date}:{exc}") from exc
            raise Stop("APRIL_PRE_UNRECOGNIZED_INTEGRITY_FAILURE", f"{date}:{exc}") from exc
    return bundles, records


def predict_one(date: str, bundle, root: Path) -> dict:
    if root.exists():
        raise Stop("APRIL_PRE_GENERATION_BLOCKED_CODE_CHANGE_REQUIRED", f"OUTPUT_EXISTS:{root}")
    root.mkdir(parents=True)
    artifacts, index = [], []
    for race_id, race in sorted(bundle.races.items()):
        output = run_new(race_id, race, trace=True)
        artifact = _project_race(race_id, output)
        artifact["buy_gate_trace"] = output["buy_gate_trace"]
        artifact["trace_status"] = "NOT_FORMALLY_FROZEN_TRACE"
        filename = f"{race_id}_prediction.json" if race_id.startswith("race_") else f"race_{race_id}_prediction.json"
        _canonical_write(root / filename, artifact)
        artifacts.append(filename)
        index.append({"race_id": race_id, "artifact": filename, "horse_count": len(artifact["ranked_results"]), "buy_count": artifact["buy_count"], "race_decision": artifact["race_decision"]})
    _canonical_write(root / "race_index.json", {"schema_version": SCHEMA_VERSION, "race_index": index})
    _canonical_write(root / "input_manifest.json", {"date": date, "population_scope_id": POPULATION_SCOPE_ID,
        "sources": {kind: {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)} for kind, path in ACTIVE_PATHS[date].items()}})
    provenance = {"target_date": date, "population_scope_id": POPULATION_SCOPE_ID, "schema_version": SCHEMA_VERSION,
                  "generated_at": datetime.now(timezone.utc).isoformat(), "trace_mode": True,
                  "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "runner_path": "review/prospective_prediction_runner_v1.py", "runner_sha256": sha(ROOT / "review" / "prospective_prediction_runner_v1.py"),
                  "orchestration_path": "review/april_pre_full_8date_execution_v1.py", "orchestration_sha256": sha(Path(__file__)),
                  "run_new_module": "review/target_bulk_prediction_input_shadow_v1.py", "run_new_module_sha256": sha(ROOT / "review" / "target_bulk_prediction_input_shadow_v1.py"),
                  "shadow_buy_engine_sha256": sha(ROOT / "engine" / "shadow_buy_decision_engine.py"),
                  "buy_gate_trace_schema_path": "docs/buy_gate_trace_schema_v1_1.json", "buy_gate_trace_schema_sha256": sha(ROOT / "docs" / "buy_gate_trace_schema_v1_1.json"),
                  "result_data_access_count": 0}
    _canonical_write(root / "provenance.json", provenance)
    _canonical_write(root / "summary.json", {"schema_version": SCHEMA_VERSION, "date": date, "race_count": len(index), "horse_count": sum(row["horse_count"] for row in index), "buy_count": sum(row["buy_count"] for row in index), "trace_mode": True})
    _write_report(root / "report.md", date=date, trace=True, race_count=len(index), horse_count=sum(row["horse_count"] for row in index), buy_count=sum(row["buy_count"] for row in index))
    files = artifacts + ["race_index.json", "input_manifest.json", "provenance.json", "summary.json", "report.md"]
    _canonical_write(root / "prediction_manifest.json", {"schema_version": SCHEMA_VERSION, "excludes": ["prediction_manifest.json"], "files": [{"relative_path": name, "sha256": sha(root / name)} for name in files]})
    return {"root": root, "index": index}


def venue_and_number(race_id: str) -> tuple[str, int]:
    parts = race_id.split("_")
    if len(parts) != 4 or not parts[3].endswith("R") or not parts[3][:-1].isdigit():
        raise Stop("APRIL_PRE_UNRECOGNIZED_INTEGRITY_FAILURE", f"RACE_ID:{race_id}")
    return parts[2], int(parts[3][:-1])


def selectors(predictions: dict[str, dict]) -> tuple[dict, dict, dict]:
    model = load_frozen_v3_model()
    v3_records, cf_records, trace_records = [], [], []
    for date, data in predictions.items():
        for item in data["index"]:
            path = data["root"] / item["artifact"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            venue, number = venue_and_number(payload["race_id"])
            v3 = select_v3_pre(payload, pipeline=model)
            cf = select_pre(date=date, venue=venue, race_number=number, race_id=payload["race_id"], buy_gate_trace=payload["buy_gate_trace"], ranked_results=payload["ranked_results"])
            snapshots = {row["shadow_ai_rank"]: row["evaluator_score_snapshot"] for row in payload["buy_gate_trace"]["horses"] if row.get("shadow_buy_candidate") is True}
            for row in v3["all_candidates"]:
                row["frozen_feature_snapshot"] = snapshots[row["shadow_ai_rank"]]
                row["selected"] = any(row["horse_number"] == selected["horse_number"] for selected in v3["selected"])
            for row in cf["candidate_horses"]:
                row["selected"] = any(row["horse_number"] == selected["horse_number"] for selected in cf["cf_selected_horses"])
            v3_pool = sorted((row["horse_number"], row["shadow_ai_rank"]) for row in v3["all_candidates"])
            cf_pool = sorted((row["horse_number"], row["shadow_ai_rank"]) for row in cf["candidate_horses"])
            if v3["eligible"] != (cf["shadow_eligibility"] == "ELIGIBLE") or v3_pool != cf_pool:
                raise Stop("APRIL_PRE_V3_CF_POPULATION_IDENTITY_FAILURE", payload["race_id"])
            v3_records.append({"date": date, **v3, "prediction_artifact": str(path.relative_to(ROOT)), "prediction_artifact_sha256": sha(path)})
            cf_records.append({"date": date, **cf, "prediction_artifact": str(path.relative_to(ROOT)), "prediction_artifact_sha256": sha(path)})
            trace_records.append({"date": date, "race_id": payload["race_id"], "prediction_artifact": str(path.relative_to(ROOT)), "prediction_artifact_sha256": sha(path), "buy_gate_trace": payload["buy_gate_trace"]})
    return ({"schema_version": "APRIL_V3_PRE_SELECTION_V1", "records": v3_records}, {"schema_version": "APRIL_CF_PRE_SELECTION_V1", "records": cf_records}, {"schema_version": "APRIL_BUY_GATE_TRACE_V1_1", "records": trace_records})


def stop(code: str, detail: str, state: dict | None = None) -> None:
    write(OUT / "pre_manifest.json", {"status": "STOP_WITH_REASON", "reason_code": code, "detail": detail, "preconditions": state,
          "access_counts": {"result_access": 0, "outcome_access": 0, "current_race_result_fields_accessed": 0, "may_access": 0},
          "changes": {"production": 0, "v3_semantics": 0, "cf_semantics": 0}})


ACTIVE_PATHS: dict[str, dict[str, Path]] = {}


def run() -> Path:
    global ACTIVE_PATHS
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    state = None
    try:
        state = phase0_code_state()
        if not APRIL_PROTOCOL.is_file() or sha(APRIL_PROTOCOL) != "d0c24e6e1a74b1b7c83e6bda5dd49d7eeb89c6079dedd30e934886e52e7e98b0":
            raise Stop("APRIL_PRE_FROZEN_CODE_STATE_MISMATCH", "APRIL_PROTOCOL_SHA")
        source_set, ACTIVE_PATHS = active_sources()
        bundles, preflight_records = preflight(ACTIVE_PATHS)
        predictions = {date: predict_one(date, bundles[date], OUT / "prediction" / date) for date in DATES}
        v3, cf, traces = selectors(predictions)
        write(OUT / "final_preflight.json", {"status": "PASS", "records": preflight_records})
        write(OUT / "buy_gate_trace.json", traces)
        write(OUT / "v3_pre_selections.json", v3)
        write(OUT / "cf_pre_selections.json", cf)
        artifact_summary = []
        for date, data in predictions.items():
            for item in data["index"]:
                path = data["root"] / item["artifact"]
                artifact_summary.append({"date": date, "race_id": item["race_id"], "path": str(path.relative_to(ROOT)), "sha256": sha(path)})
        v3_eligible = [row for row in v3["records"] if row["eligible"]]
        cf_eligible = [row for row in cf["records"] if row["shadow_eligibility"] == "ELIGIBLE"]
        manifest = {"status": "APRIL_PRE_FROZEN", "execution_type": "FULL_8_DATE_NEW_EXECUTION", "april_protocol": {"path": str(APRIL_PROTOCOL.relative_to(ROOT)), "sha256": sha(APRIL_PROTOCOL)}, "phase0_code_freeze": state,
                    "active_source_set": {"path": str(SOURCE_SET.relative_to(ROOT)), "sha256": sha(SOURCE_SET), "lineage": source_set.get("replacement_lineage")},
                    "source_dates": list(DATES), "active_sources": source_set["active_dates"], "final_preflight": preflight_records,
                    "prediction": {"dates": list(DATES), "race_count": sum(record["race_count"] for record in preflight_records.values()), "horse_count": sum(record["horse_count"] for record in preflight_records.values()), "per_date": {date: {"race_count": record["race_count"], "horse_count": record["horse_count"]} for date, record in preflight_records.items()}, "artifacts": artifact_summary},
                    "gate_and_convergence": {"buy_gate_trace": {"path": "buy_gate_trace.json", "sha256": sha(OUT / "buy_gate_trace.json")}, "play_unconverged_4plus_race_set": [row["race_id"] for row in v3_eligible], "eligible_race_count": len(v3_eligible), "gate_eligible_candidate_count": sum(row["gate_eligible_count"] for row in v3_eligible)},
                    "v3": {"selection_artifact": {"path": "v3_pre_selections.json", "sha256": sha(OUT / "v3_pre_selections.json")}, "eligible_race_count": len(v3_eligible), "selected_count": sum(len(row["selected"]) for row in v3_eligible)},
                    "cf": {"selection_artifact": {"path": "cf_pre_selections.json", "sha256": sha(OUT / "cf_pre_selections.json")}, "eligible_race_count": len(cf_eligible), "selected_count": sum(row["cf_selected_count"] for row in cf_eligible)},
                    "v3_cf_population_identity": "PASS", "execution_timestamp": datetime.now(timezone.utc).isoformat(), "prediction_rerun_count": 1,
                    "access_counts": {"result_access": 0, "outcome_access": 0, "current_race_result_fields_accessed": 0, "may_access": 0}, "changes": {"production": 0, "v3_semantics": 0, "cf_semantics": 0}}
        write(OUT / "pre_manifest.json", manifest)
        report = "# April 2026 PRE Freeze\n\n- Status: `APRIL_PRE_FROZEN`\n- PRE-only execution; Result/Outcome/May access: 0\n- All eight approved active source dates passed final preflight.\n"
        (OUT / "report.md").write_text(report, encoding="utf-8")
        hashes = {str(path.relative_to(OUT)): sha(path) for path in sorted(OUT.rglob("*")) if path.is_file()}
        write(OUT / "artifact_hashes.json", {"indexed_artifacts": hashes, "self_hash_excluded": True})
        indexed = json.loads((OUT / "artifact_hashes.json").read_text(encoding="utf-8"))["indexed_artifacts"]
        if any(sha(OUT / path) != expected for path, expected in indexed.items()):
            raise Stop("APRIL_PRE_ARTIFACT_HASH_FAILURE", "HASH_INDEX")
        return OUT
    except Stop as exc:
        stop(exc.code, exc.detail, state)
        return OUT


if __name__ == "__main__":
    print(run())
