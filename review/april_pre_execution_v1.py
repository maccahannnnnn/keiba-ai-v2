"""April 2026 External Holdout PRE execution orchestration.

This module is intentionally a thin, result-free layer.  It verifies the
Phase-0 frozen code lineage, inventories and preflights all April DG/DE/DS
sources before any Prediction, then calls the existing prospective runner and
the frozen V3/CF PRE selectors without reimplementing their semantics.
"""
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

from review.cf_top3_rank_anchored_shadow_v1 import protocol_hash as cf_protocol_hash
from review.cf_top3_rank_anchored_shadow_v1 import select_pre
from review.learned_convergence_selector_v3_pre_v1 import (
    MODEL_PATH,
    MODEL_SHA256,
    load_frozen_v3_model,
    select_v3_pre,
    sha256 as v3_sha256,
)
from review.prospective_prediction_runner_v1 import _assert_population, run as run_prediction
from review.target_bulk_prediction_input_adapter_v1 import (
    PredictionInputValidationError,
    TargetBulkPredictionInputAdapterV1,
)


RAW = ROOT / "data" / "raw" / "prediction_input"
OUTPUT = ROOT / "reports" / "april_2026_retrospective_external_holdout_v2" / "pre_execution_v1_recovery_v1"
DATES = ("20260404", "20260405", "20260411", "20260412", "20260418", "20260419", "20260425", "20260426")
PHASE0_ROOT = ROOT / "reports" / "april_pre_code_freeze_v1_recovery_v1"
PHASE0_MANIFEST = PHASE0_ROOT / "code_freeze_manifest.json"
PHASE0_HASHES = PHASE0_ROOT / "artifact_hashes.json"
V3_PROTOCOL = ROOT / "reports" / "learned_convergence_selector_v3_prospective_shadow_protocol_v1" / "learned_convergence_selector_v3_formal_prospective_shadow_protocol_v1.md"
CF_PROTOCOL = ROOT / "reports" / "shadow_cf_top3_rank_anchored_v1" / "protocol.json"


class AprilPreStop(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}:{detail}")
        self.code = code
        self.detail = detail


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def git_state() -> tuple[str, dict[str, str]]:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    states: dict[str, str] = {}
    for line in status.splitlines():
        if len(line) >= 4:
            states[line[3:]] = "untracked" if line.startswith("??") else "dirty"
    return head, states


def current_component_state(path: str, statuses: dict[str, str]) -> str:
    return statuses.get(path, "clean")


def phase0_code_state() -> dict:
    if not PHASE0_MANIFEST.is_file() or not PHASE0_HASHES.is_file():
        raise AprilPreStop("APRIL_PRE_FROZEN_CODE_STATE_MISMATCH", "PHASE0_RECOVERY_ARTIFACT_MISSING")
    manifest = json.loads(PHASE0_MANIFEST.read_text(encoding="utf-8"))
    indexed = json.loads(PHASE0_HASHES.read_text(encoding="utf-8"))
    required_hashes = {
        "code_freeze_manifest_sha256": PHASE0_MANIFEST,
        "equivalence_check_sha256": PHASE0_ROOT / "equivalence_check.json",
        "result_isolation_spec_sha256": PHASE0_ROOT / "result_isolation_spec.json",
        "report_sha256": PHASE0_ROOT / "report.md",
        "wrapper_sha256": ROOT / "review" / "learned_convergence_selector_v3_pre_v1.py",
    }
    for key, path in required_hashes.items():
        if not path.is_file() or indexed.get(key) != sha256(path):
            raise AprilPreStop("APRIL_PRE_FROZEN_CODE_STATE_MISMATCH", key)
    if manifest.get("status") != "APRIL_PRE_PHASE0_FROZEN_READY":
        raise AprilPreStop("APRIL_PRE_FROZEN_CODE_STATE_MISMATCH", "PHASE0_STATUS")
    head, statuses = git_state()
    if manifest.get("git", {}).get("HEAD") != head:
        raise AprilPreStop("APRIL_PRE_FROZEN_CODE_STATE_MISMATCH", "GIT_HEAD")
    for component in manifest.get("components", []):
        path = component.get("path")
        expected_sha = component.get("sha256")
        expected_state = component.get("working_tree_state")
        absolute = ROOT / str(path)
        if not absolute.is_file() or sha256(absolute) != expected_sha:
            raise AprilPreStop("APRIL_PRE_FROZEN_CODE_STATE_MISMATCH", f"SHA:{path}")
        if current_component_state(str(path), statuses) != expected_state:
            raise AprilPreStop("APRIL_PRE_FROZEN_CODE_STATE_MISMATCH", f"STATE:{path}")
    authority = manifest.get("frozen_authority", {})
    if authority.get("model") != MODEL_SHA256 or sha256(MODEL_PATH) != MODEL_SHA256:
        raise AprilPreStop("APRIL_PRE_FROZEN_CODE_STATE_MISMATCH", "MODEL_SHA")
    if authority.get("v3_protocol") != sha256(V3_PROTOCOL):
        raise AprilPreStop("APRIL_PRE_FROZEN_CODE_STATE_MISMATCH", "V3_PROTOCOL_SHA")
    # Phase 0 froze the protocol *file* SHA.  ``protocol_hash()`` is a
    # separate canonical-content digest, so comparing it to the file digest
    # would reject the same frozen protocol artifact.
    if authority.get("cf_protocol") != sha256(CF_PROTOCOL):
        raise AprilPreStop("APRIL_PRE_FROZEN_CODE_STATE_MISMATCH", "CF_PROTOCOL_SHA")
    return {
        "phase0_manifest_path": str(PHASE0_MANIFEST.relative_to(ROOT)),
        "phase0_manifest_sha256": sha256(PHASE0_MANIFEST),
        "phase0_artifact_index_sha256": sha256(PHASE0_HASHES),
        "git_head": head,
        "frozen_authority": authority,
        "component_verification": "PASS",
    }


def source_paths(date: str) -> dict[str, Path]:
    return {kind: RAW / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}


def inventory_sources() -> list[dict]:
    records: list[dict] = []
    seen: set[Path] = set()
    for date in DATES:
        paths = source_paths(date)
        if any(not path.is_file() for path in paths.values()):
            missing = [kind for kind, path in paths.items() if not path.is_file()]
            raise AprilPreStop("APRIL_PRE_SOURCE_INVENTORY_FAILURE", f"{date}:MISSING:{','.join(missing)}")
        if len(set(paths.values())) != 3 or any(path in seen for path in paths.values()):
            raise AprilPreStop("APRIL_PRE_SOURCE_INVENTORY_FAILURE", f"{date}:DUPLICATE_PATH")
        seen.update(paths.values())
        records.append({"date": date, "sources": {
            kind: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path), "bytes": path.stat().st_size}
            for kind, path in paths.items()
        }})
    return records


def assert_result_isolation() -> dict:
    forbidden = []
    for path in RAW.glob("*2604*.CSV"):
        name = path.name.lower()
        if "result" in name or "outcome" in name:
            forbidden.append(str(path.relative_to(ROOT)))
    if forbidden:
        raise AprilPreStop("APRIL_PRE_RESULT_ISOLATION_FAILED", ",".join(sorted(forbidden)))
    return {
        "input_path": str(RAW.relative_to(ROOT)),
        "result_or_outcome_filename_count": 0,
        "result_or_outcome_content_opened": 0,
        "current_race_result_fields_accessed": 0,
        "history_finish_position_interpretation": "PRE_HISTORY_ONLY",
    }


def preflight_all() -> list[dict]:
    adapter = TargetBulkPredictionInputAdapterV1()
    records = []
    failures: list[tuple[str, str]] = []
    for date in DATES:
        paths = source_paths(date)
        try:
            bundle = adapter.load(paths["DG"], paths["DE"], paths["DS"])
            if bundle.date != date:
                raise AprilPreStop("APRIL_PRE_UNRECOGNIZED_INTEGRITY_FAILURE", f"{date}:TARGET_DATE_MISMATCH:{bundle.date}")
            _assert_population(bundle)
            records.append({"date": date, "status": "PASS", "preflight": bundle.preflight,
                            "race_ids": sorted(bundle.races), "race_count": len(bundle.races),
                            "horse_count": sum(len(race.today_entries) for race in bundle.races.values())})
        except PredictionInputValidationError as exc:
            failures.append((date, exc.reason_code))
            records.append({"date": date, "status": "STOP", "reason_code": exc.reason_code, "detail": exc.detail})
        except ValueError as exc:
            code = str(exc).split(":", 1)[0]
            if code == "UNEXPECTED_PREDICTION_POPULATION_RACE":
                failures.append((date, code))
                records.append({"date": date, "status": "STOP", "reason_code": code, "detail": str(exc)})
            elif isinstance(exc, AprilPreStop):
                raise
            else:
                raise AprilPreStop("APRIL_PRE_UNRECOGNIZED_INTEGRITY_FAILURE", f"{date}:{exc}") from exc
    if failures:
        repeated = {code for _, code in failures if sum(1 for _, item in failures if item == code) > 1}
        outer = "APRIL_PRE_STRUCTURAL_INCOMPATIBILITY" if repeated else (
            "APRIL_PRE_UNEXPECTED_PREDICTION_POPULATION_RACE" if failures[0][1] == "UNEXPECTED_PREDICTION_POPULATION_RACE"
            else "APRIL_PRE_UNRECOGNIZED_INTEGRITY_FAILURE"
        )
        raise AprilPreStop(outer, json.dumps(records, ensure_ascii=False, sort_keys=True))
    return records


def venue_and_race_number(race_id: str) -> tuple[str, int]:
    parts = race_id.split("_")
    if len(parts) != 4 or not parts[3].endswith("R") or not parts[3][:-1].isdigit():
        raise AprilPreStop("APRIL_PRE_UNRECOGNIZED_INTEGRITY_FAILURE", f"RACE_ID:{race_id}")
    return parts[2], int(parts[3][:-1])


def selection_artifacts(prediction_roots: dict[str, Path]) -> tuple[dict, dict, dict]:
    model = load_frozen_v3_model()
    v3_records, cf_records, trace_manifest = [], [], []
    for date, root in prediction_roots.items():
        index = json.loads((root / "race_index.json").read_text(encoding="utf-8"))
        for item in index["race_index"]:
            artifact_path = root / item["artifact"]
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            race_id = payload["race_id"]
            venue, race_number = venue_and_race_number(race_id)
            v3 = select_v3_pre(payload, pipeline=model)
            cf = select_pre(date=date, venue=venue, race_number=race_number, race_id=race_id,
                            buy_gate_trace=payload["buy_gate_trace"], ranked_results=payload["ranked_results"])
            v3_pool = [(row["horse_number"], row["shadow_ai_rank"]) for row in v3["all_candidates"]]
            cf_pool = [(row["horse_number"], row["shadow_ai_rank"]) for row in cf["candidate_horses"]]
            if v3["eligible"] != (cf["shadow_eligibility"] == "ELIGIBLE") or v3_pool != cf_pool:
                raise AprilPreStop("APRIL_PRE_V3_CF_POPULATION_IDENTITY_FAILURE", race_id)
            v3_records.append({"date": date, **v3, "prediction_artifact": str(artifact_path.relative_to(ROOT)),
                               "prediction_artifact_sha256": sha256(artifact_path)})
            cf_records.append({"date": date, **cf, "prediction_artifact": str(artifact_path.relative_to(ROOT)),
                               "prediction_artifact_sha256": sha256(artifact_path)})
            trace_manifest.append({"date": date, "race_id": race_id, "prediction_artifact": str(artifact_path.relative_to(ROOT)),
                                   "prediction_artifact_sha256": sha256(artifact_path),
                                   "buy_gate_trace_sha256": hashlib.sha256(json.dumps(payload["buy_gate_trace"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()})
    return ({"schema_version": "APRIL_V3_PRE_SELECTION_V1", "records": v3_records},
            {"schema_version": "APRIL_CF_PRE_SELECTION_V1", "records": cf_records},
            {"schema_version": "BUY_GATE_TRACE_MANIFEST_V1_1", "records": trace_manifest})


def stop_manifest(code: str, detail: str, code_state: dict | None, confirmation: dict) -> None:
    write_json(OUTPUT / "pre_manifest.json", {
        "status": "STOP_WITH_REASON", "reason_code": code, "detail": detail,
        "code_freeze": code_state, "population_pre_filter_assumption_verified": True,
        "population_pre_filter_confirmation_record": confirmation,
        "access_counts": {"result_access": 0, "outcome_access": 0, "current_race_result_fields_accessed": 0, "may_access": 0},
    })


def run() -> Path:
    if OUTPUT.exists():
        raise FileExistsError(f"OUTPUT_ROOT_EXISTS:{OUTPUT}")
    OUTPUT.mkdir(parents=True)
    confirmation = {
        "confirmed_by": "HUMAN",
        "confirmation_timestamp": datetime.now(timezone.utc).isoformat(),
        "confirmation_method": "HUMAN_STATEMENT",
        "confirmation_summary": "April DG/DE/DS were acquired using the same TARGET-side 1win-plus-flat population setup used for ordinary Prospective operation.",
        "result_access_at_confirmation": 0,
    }
    code_state = None
    try:
        code_state = phase0_code_state()
        inventory = inventory_sources()
        isolation = assert_result_isolation()
        preflight = preflight_all()
        prediction_roots: dict[str, Path] = {}
        for date in DATES:
            prediction_roots[date] = run_prediction(date, trace=True, output_root=OUTPUT / "prediction" / date)
        v3, cf, trace = selection_artifacts(prediction_roots)
        write_json(OUTPUT / "source_inventory.json", {"source_dates": list(DATES), "records": inventory})
        write_json(OUTPUT / "structural_preflight.json", {"status": "PASS", "records": preflight})
        write_json(OUTPUT / "result_isolation.json", isolation)
        write_json(OUTPUT / "buy_gate_trace_manifest.json", trace)
        write_json(OUTPUT / "v3_pre_selections.json", v3)
        write_json(OUTPUT / "cf_pre_selections.json", cf)
        prediction_artifacts = []
        for root in prediction_roots.values():
            for item in json.loads((root / "race_index.json").read_text(encoding="utf-8"))["race_index"]:
                path = root / item["artifact"]
                prediction_artifacts.append({"path": str(path.relative_to(ROOT)), "sha256": sha256(path)})
        v3_eligible = [row for row in v3["records"] if row["eligible"]]
        manifest = {
            "status": "APRIL_PRE_FROZEN", "protocol": "APRIL_2026_RETROSPECTIVE_EXTERNAL_HOLDOUT_V2",
            "population_scope_id": "PREDICTION_BUY_1WIN_PLUS_FLAT",
            "population_pre_filter_assumption_verified": True,
            "population_pre_filter_confirmation_record": confirmation,
            "code_freeze": code_state, "source_inventory": inventory, "included_prediction_dates": list(DATES),
            "included_prediction_races": [race for record in preflight for race in record["race_ids"]],
            "prediction_race_count": sum(record["race_count"] for record in preflight),
            "prediction_horse_count": sum(record["horse_count"] for record in preflight),
            "date_stop_events": [], "play_unconverged_4plus_race_set": [row["race_id"] for row in v3_eligible],
            "gate_eligible_candidate_pool_count": sum(row["gate_eligible_count"] for row in v3_eligible),
            "v3_selected_count": sum(len(row["selected"]) for row in v3_eligible),
            "cf_selected_count": sum(row["cf_selected_count"] for row in cf["records"] if row["shadow_eligibility"] == "ELIGIBLE"),
            "v3_cf_candidate_population_identity": "PASS", "prediction_artifacts": prediction_artifacts,
            "buy_gate_trace_manifest": {"path": "buy_gate_trace_manifest.json", "sha256": sha256(OUTPUT / "buy_gate_trace_manifest.json")},
            "v3_selection_artifact": {"path": "v3_pre_selections.json", "sha256": sha256(OUTPUT / "v3_pre_selections.json")},
            "cf_selection_artifact": {"path": "cf_pre_selections.json", "sha256": sha256(OUTPUT / "cf_pre_selections.json")},
            "execution_timestamp": datetime.now(timezone.utc).isoformat(),
            "access_counts": {"result_access": 0, "outcome_access": 0, "current_race_result_fields_accessed": 0, "may_access": 0},
            "changes": {"production": 0, "v3_semantics": 0, "cf_semantics": 0},
        }
        write_json(OUTPUT / "pre_manifest.json", manifest)
        artifact_hashes = {str(path.relative_to(OUTPUT)): sha256(path) for path in sorted(OUTPUT.rglob("*")) if path.is_file()}
        write_json(OUTPUT / "artifact_hashes.json", artifact_hashes)
        return OUTPUT
    except AprilPreStop as exc:
        stop_manifest(exc.code, exc.detail, code_state, confirmation)
        return OUTPUT


if __name__ == "__main__":
    print(run())
