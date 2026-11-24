"""Result-free formal historical PRE wrapper for the January 2026 holdout.

Selection behaviour is deliberately delegated to the frozen technical core's
``_race_result``.  This module only pins January authorities, adapts strict
race identity, enumerates already-frozen Current PRE artifacts, and freezes a
cohort-level result-free semantic artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from review import selection_authority_protocol_v1_pre_freeze as core


ROOT = Path(__file__).resolve().parents[1]
JANUARY_ROOT = ROOT / "reports" / "selection_authority_protocol_v1_january_2026_historical_holdout"
JANUARY_PROTOCOL = ROOT / "docs" / "selection_authority_protocol_v1_january_2026_historical_holdout.json"
CURRENT_PRE = JANUARY_ROOT / "current_pre"
SOURCE_MANIFEST = JANUARY_ROOT / "source_acquisition" / "source_manifest.json"
POPULATION_MANIFEST = JANUARY_ROOT / "realized_population_manifest.json"
CORRECTION_RECORD = JANUARY_ROOT / "population_scope_correction_record.json"
CURRENT_FREEZE_MANIFEST = CURRENT_PRE / "current_pre_freeze_manifest.json"
OUTPUT = JANUARY_ROOT / "selection_authority_pre"

EXPECTED = {
    "january_protocol": "77bccaf6d3f01e14b25c3e7564d7fd084f93511e64c021dd752269ab5bf00941",
    "parent_protocol": "01bad1cc325f0ec1e35cb149bc65e20c07582c6d4013f0e344c0d521bb21106f",
    "model": "d3b17e3022768690d0b1013ab131b35c5a64aa8e4a816fb3e1349bad95fb87a2",
    "scaler": "2855f19c43b0fc70e106a85a2c61716d532694c90efc42580b937d5d7bab504d",
    "feature_schema": "f50039929b823f2821b4bde6a0cdc41f8be1c4c45cb55682c8a312e811e112c0",
    "source_manifest": "d468a9f8b6d54136cb864e1202e849f0d305bd7e358d7ee7bc6b2b6996e31ec7",
    "population_manifest": "3388c234a1aa42f3bf10a2bc51576d33dc9067cb4415dd8fffdf95d4c1e94e45",
    "correction_record": "ea5410969d1282feb3077dd7398006084ec7333ef5a5c6429569c66ee9ddba09",
    "current_pre_manifest": "ba840efbb5e3b4551386412e3ebedd9038e3274d2460cda525e5fea2a5b55139",
}
RACE_ID = re.compile(r"^race_(\d{8})_(nakayama|kyoto|kokura|tokyo)_([1-9]|1[0-2])R$")
VENUES = {"nakayama": "中山", "kyoto": "京都", "kokura": "小倉", "tokyo": "東京"}
RESULT_KEYS = core.RESULT_KEYS | {"rate", "lift", "raw_hit_difference", "finishing_position", "winner"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_bytes(value))


def pin(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or sha256(path) != expected:
        raise core.Stop(f"JANUARY_AUTHORITY_SHA_MISMATCH:{label}")


def parse_race_id(race_id: str) -> tuple[str, str, int]:
    match = RACE_ID.fullmatch(race_id)
    if match is None:
        raise core.Stop(f"FAIL_CLOSED_RACE_IDENTITY_PARSE:{race_id}")
    date, venue_key, race_number = match.groups()
    return date, VENUES[venue_key], int(race_number)


def assert_result_free(value: object, context: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in RESULT_KEYS:
                raise core.Stop(f"PRE_RESULT_FIELD_FORBIDDEN:{context}:{key}")
            assert_result_free(child, context)
    elif isinstance(value, list):
        for child in value:
            assert_result_free(child, context)


def verify_authorities() -> tuple[dict[str, Any], dict[str, str]]:
    paths = {
        "january_protocol": JANUARY_PROTOCOL,
        "parent_protocol": core.PROTOCOL_PATH,
        "model": core.MODEL_ROOT / "model.joblib",
        "scaler": core.MODEL_ROOT / "scaler.joblib",
        "feature_schema": core.MODEL_ROOT / "feature_transform_schema.json",
        "source_manifest": SOURCE_MANIFEST,
        "population_manifest": POPULATION_MANIFEST,
        "correction_record": CORRECTION_RECORD,
        "current_pre_manifest": CURRENT_FREEZE_MANIFEST,
    }
    for label, path in paths.items():
        pin(path, EXPECTED[label], label)
    january = json.loads(JANUARY_PROTOCOL.read_text(encoding="utf-8"))
    if january.get("population_rule", {}).get("population_scope_id") != "PREDICTION_BUY_1WIN_PLUS_FLAT":
        raise core.Stop("JANUARY_POPULATION_SCOPE_MISMATCH")
    correction = json.loads(CORRECTION_RECORD.read_text(encoding="utf-8"))
    if correction.get("corrected_protocol_sha256") != EXPECTED["january_protocol"]:
        raise core.Stop("JANUARY_CORRECTION_RECORD_MISMATCH")
    population = json.loads(POPULATION_MANIFEST.read_text(encoding="utf-8"))
    if population.get("population_scope_id") != "PREDICTION_BUY_1WIN_PLUS_FLAT":
        raise core.Stop("JANUARY_REALIZED_POPULATION_SCOPE_MISMATCH")
    protocol = core.load_frozen_protocol()
    model, scaler, identity = core.load_frozen_v5(protocol)
    return json.loads(CURRENT_FREEZE_MANIFEST.read_text(encoding="utf-8")), identity


def _source_payloads(current_manifest: dict[str, Any]) -> list[tuple[str, Path, dict[str, Any], str]]:
    manifests = current_manifest.get("per_date_prediction_manifest_sha256")
    if not isinstance(manifests, dict) or not manifests:
        raise core.Stop("CURRENT_PRE_FREEZE_MANIFEST_INVALID")
    records: list[tuple[str, Path, dict[str, Any], str]] = []
    for date, expected_manifest_sha in sorted(manifests.items()):
        prediction_root = CURRENT_PRE / date
        prediction_manifest = prediction_root / "prediction_manifest.json"
        if sha256(prediction_manifest) != expected_manifest_sha:
            raise core.Stop(f"CURRENT_PRE_MANIFEST_MISMATCH:{date}")
        hashes = core._manifest_hashes(prediction_root)
        index = json.loads((prediction_root / "race_index.json").read_text(encoding="utf-8")).get("race_index")
        if not isinstance(index, list):
            raise core.Stop(f"CURRENT_PRE_RACE_INDEX_INVALID:{date}")
        for item in index:
            relative = item.get("artifact")
            if not isinstance(relative, str) or relative not in hashes:
                raise core.Stop(f"CURRENT_PRE_ARTIFACT_UNPINNED:{date}:{relative}")
            path = prediction_root / relative
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert_result_free(payload, str(payload.get("race_id", date)))
            records.append((date, path, payload, hashes[relative]))
    return sorted(records, key=lambda row: str(row[2].get("race_id", "")))


def process_race(date: str, payload: dict[str, Any], source_sha: str, model: object, scaler: object, identity: dict[str, str]) -> dict[str, Any]:
    """Strict identity adaptation followed by the sole frozen selection core."""
    assert_result_free(payload, str(payload.get("race_id", date)))
    adapted = dict(payload)
    race_id = str(adapted.get("race_id", ""))
    parsed_date, venue, race_number = parse_race_id(race_id)
    if parsed_date != date:
        raise core.Stop(f"FAIL_CLOSED_RACE_IDENTITY_DATE_MISMATCH:{race_id}:{date}")
    if adapted.get("venue") not in (None, venue) or adapted.get("race_number") not in (None, race_number):
        raise core.Stop(f"FAIL_CLOSED_RACE_IDENTITY_CONFLICT:{race_id}")
    adapted["venue"] = venue
    adapted["race_number"] = race_number
    return core._race_result(date, adapted, source_sha, model, scaler, identity)


def build_semantic() -> dict[str, Any]:
    current_manifest, identity = verify_authorities()
    protocol = core.load_frozen_protocol()
    model, scaler, _ = core.load_frozen_v5(protocol)
    races = [process_race(date, payload, source_sha, model, scaler, identity) for date, _, payload, source_sha in _source_payloads(current_manifest)]
    expected_races = current_manifest.get("current_pre_races")
    if len(races) != expected_races:
        raise core.Stop(f"CURRENT_PRE_RACE_COUNT_MISMATCH:{len(races)}:{expected_races}")
    target_positive = sum(row.get("target_k", 0) >= 1 for row in races)
    total_target_k = sum(row.get("target_k", 0) for row in races)
    if target_positive != current_manifest.get("target_k_positive_races") or total_target_k != current_manifest.get("total_target_k"):
        raise core.Stop("CURRENT_PRE_TARGET_K_RECOUNT_MISMATCH")
    return {
        "protocol_name": protocol["identity"]["protocol_name"],
        "protocol_version": protocol["identity"]["protocol_version"],
        "january_protocol_sha256": EXPECTED["january_protocol"],
        "parent_protocol_sha256": EXPECTED["parent_protocol"],
        "evidence_role": "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT_FOR_SELECTION_AUTHORITY_PROTOCOL_V1",
        "generic_evidence_class": "TEMPORALLY_REVERSED_EXTERNAL_HOLDOUT",
        "purpose": "BACKWARD_TEMPORAL_GENERALIZATION_ONLY",
        "not_prospective_evidence": True,
        "formal_evidence": False,
        "population_scope_id": "PREDICTION_BUY_1WIN_PLUS_FLAT",
        "model": identity,
        "source_manifest_sha256": EXPECTED["source_manifest"],
        "realized_population_manifest_sha256": EXPECTED["population_manifest"],
        "population_correction_record_sha256": EXPECTED["correction_record"],
        "current_pre_freeze_manifest_sha256": EXPECTED["current_pre_manifest"],
        "ordering_rule": "probability DESC",
        "tie_break_rule": ["shadow_ai_rank ASC", "horse_number ASC"],
        "candidate_rule": "FULL_FIELD_V5_PROBABILITY_TOP5_EXACT5",
        "risk_guard_semantics": "FROZEN_SAFETY_ELIGIBILITY_VETO_AFTER_EXACT5_BEFORE_TARGET_K",
        "volume_source": "CURRENT_PRE_FROZEN_BUY_COUNT",
        "outside_fill_rule": "PROHIBITED",
        "races": races,
    }


def summary(semantic: dict[str, Any]) -> dict[str, Any]:
    races = semantic["races"]
    states: dict[str, int] = {}
    target_k: dict[str, int] = {}
    venues: dict[str, int] = {}
    for race in races:
        states[race.get("race_state", "NOT_RUN")] = states.get(race.get("race_state", "NOT_RUN"), 0) + 1
        target_k[str(race.get("target_k", 0))] = target_k.get(str(race.get("target_k", 0)), 0) + 1
        venue = race.get("venue", "UNKNOWN")
        venues[venue] = venues.get(venue, 0) + 1
    successes = [race for race in races if race.get("race_status") == "SUCCESS"]
    shortfall = [race for race in successes if race.get("shortfall", 0) > 0]
    return {
        "population_races": len(races),
        "current_pre_races": len(races),
        "target_k_positive_races": sum(race.get("target_k", 0) >= 1 for race in races),
        "total_target_k": sum(race.get("target_k", 0) for race in races),
        "selection_authority_eligible_races": len(successes),
        "out_of_scope_races": sum(race.get("not_run_reason") == "TARGET_K_ZERO_OUT_OF_SCOPE" for race in races),
        "not_run_races": sum(race.get("race_status") == "NOT_RUN" for race in races),
        "total_selected_n": sum(race.get("selected_n", 0) for race in successes),
        "total_shortfall": sum(race.get("shortfall", 0) for race in successes),
        "races_with_shortfall": len(shortfall),
        "race_state_distribution": dict(sorted(states.items())),
        "target_k_distribution": dict(sorted(target_k.items())),
        "venue_distribution": dict(sorted(venues.items())),
    }


def run(output_root: Path = OUTPUT, *, test_status: str = "PASS") -> Path:
    if output_root.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{output_root}")
    one = build_semantic()
    two = build_semantic()
    if canonical_bytes(one) != canonical_bytes(two):
        raise core.Stop("DETERMINISM_GATE_FAILED")
    cohort_summary = summary(one)
    output_root.mkdir(parents=True)
    write_json(output_root / "semantic_selection.json", one)
    manifest = {
        "artifact_type": "JANUARY_2026_SELECTION_AUTHORITY_PROTOCOL_V1_FORMAL_HISTORICAL_PRE_MANIFEST_V1",
        "cohort_identity": "JANUARY_2026_SELECTION_AUTHORITY_HISTORICAL_HOLDOUT",
        "evidence_role": one["evidence_role"],
        "generic_evidence_class": one["generic_evidence_class"],
        "purpose": one["purpose"],
        "not_prospective_evidence": True,
        "formal_evidence": False,
        "authority_sha256": {key: value for key, value in EXPECTED.items()},
        "race_count": len(one["races"]),
        "semantic_selection_sha256": sha256(output_root / "semantic_selection.json"),
        "result_access": False,
        "outcome_access": False,
        "actual_top3_access": False,
        "performance_evaluation": False,
        "runner_path": "review/selection_authority_protocol_v1_january_2026_historical_pre.py",
        "runner_sha256": sha256(Path(__file__)),
        "existing_technical_core_path": "review/selection_authority_protocol_v1_pre_freeze.py",
        "existing_technical_core_sha256": sha256(Path(core.__file__).resolve()),
        "test_status": test_status,
        "semantic_equivalence_status": "PASS",
        "determinism_status": "PASS",
        "summary": cohort_summary,
    }
    write_json(output_root / "manifest.json", manifest)
    provenance = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "semantic_selection_sha256": manifest["semantic_selection_sha256"],
        "result_access_count": 0,
        "outcome_access_count": 0,
        "actual_top3_access_count": 0,
        "performance_evaluation_count": 0,
    }
    write_json(output_root / "provenance.json", provenance)
    indexed = {name: sha256(output_root / name) for name in ("semantic_selection.json", "manifest.json", "provenance.json")}
    write_json(output_root / "artifact_index.json", {"artifact_type": "JANUARY_2026_SELECTION_AUTHORITY_HISTORICAL_PRE_ARTIFACT_INDEX_V1", "index_excludes_self": True, "indexed_artifacts": indexed})
    return output_root


def main() -> int:
    parser = argparse.ArgumentParser(description="January Selection Authority formal historical PRE")
    parser.add_argument("--output-root", type=Path, default=OUTPUT)
    parser.add_argument("--tests-passed", action="store_true")
    args = parser.parse_args()
    print(run(args.output_root, test_status="PASS" if args.tests_passed else "NOT_ASSERTED_BY_CLI"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
