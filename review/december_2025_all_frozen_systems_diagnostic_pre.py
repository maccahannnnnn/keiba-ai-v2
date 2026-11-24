"""Result-free Option-B diagnostic panel, separate from December Formal Phase A."""
from __future__ import annotations

import hashlib
import json
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FORMAL = ROOT / "reports" / "december_2025_three_lane_one_shot_holdout_pre"
OUTPUT = ROOT / "reports" / "december_2025_all_frozen_systems_diagnostic_pre"
MANIFEST = ROOT / "docs" / "december_2025_all_frozen_systems_comparison_manifest_v1.json"
RESULT_KEYS = {"actual_top3", "actual_finish", "finish", "result", "payout", "valid_result", "odds"}


class Stop(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def assert_result_free(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in RESULT_KEYS:
                raise Stop("STOP_DIAGNOSTIC_RESULT_LEAKAGE")
            assert_result_free(child)
    elif isinstance(value, list):
        for child in value:
            assert_result_free(child)


def load_manifest() -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    order, systems = manifest.get("fixed_display_order", []), manifest.get("systems", [])
    if len(order) != 8 or [item.get("system_id") for item in systems] != order:
        raise Stop("STOP_DIAGNOSTIC_MANIFEST_IDENTITY_INVALID")
    if {item.get("class") for item in systems} != {"FORMAL", "DIAGNOSTIC"}:
        raise Stop("STOP_DIAGNOSTIC_MANIFEST_CLASS_INVALID")
    assert_result_free(manifest)
    return manifest


def _ratio(numerator: int, denominator: int) -> dict[str, int | float | str]:
    return {"numerator": numerator, "denominator": denominator, "value": numerator / denominator if denominator else "NOT_APPLICABLE"}


def selection_bitmap(population: list[tuple[str, int]], selections: dict[str, set[tuple[str, int]]], order: list[str], families: dict[str, str], scopes: dict[str, set[str]] | None = None) -> list[dict[str, Any]]:
    scopes = scopes or {system: {race for race, _ in population} for system in order}
    rows = []
    for race_id, horse_number in sorted(population):
        flags = {system: "NOT_IN_SCOPE" if race_id not in scopes.get(system, set()) else "SELECTED" if (race_id, horse_number) in selections.get(system, set()) else "NOT_SELECTED" for system in order}
        selected = [system for system, state in flags.items() if state == "SELECTED"]
        rows.append({"race_id": race_id, "horse_number": horse_number, "systems": flags, "system_selection_count": len(selected), "unique_model_family_selection_count": len({families[system] for system in selected}), "unique_vs_all_systems": len(selected) == 1, "unique_vs_current": flags.get("CURRENT") != "SELECTED" and bool(selected)})
    return rows


def race_bitmap(horse_bitmap: list[dict[str, Any]], order: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, str]] = {}
    for row in horse_bitmap:
        states = grouped.setdefault(row["race_id"], {system: "NOT_IN_SCOPE" for system in order})
        for system, state in row["systems"].items():
            if state == "SELECTED": states[system] = "SELECTED"
            elif state == "NOT_SELECTED" and states[system] == "NOT_IN_SCOPE": states[system] = "NOT_SELECTED"
    return [{"race_id": race_id, "systems": states} for race_id, states in sorted(grouped.items())]


def pairwise_overlaps(selections: dict[str, set[tuple[str, int]]], order: list[str]) -> dict[str, dict[str, Any]]:
    result = {}
    for left_name, right_name in combinations(order, 2):
        left, right = selections.get(left_name, set()), selections.get(right_name, set())
        left_races, right_races = {race for race, _ in left}, {race for race, _ in right}
        result[f"{left_name}__{right_name}"] = {"horse_jaccard": _ratio(len(left & right), len(left | right)), "horse_overlap_coefficient": _ratio(len(left & right), min(len(left), len(right))), "race_jaccard": _ratio(len(left_races & right_races), len(left_races | right_races)), "race_overlap_coefficient": _ratio(len(left_races & right_races), min(len(left_races), len(right_races)))}
    if len(result) != 28: raise Stop("STOP_DIAGNOSTIC_PAIRWISE_COUNT_INVALID")
    return result


def _formal_anchor() -> tuple[dict[str, Any], dict[str, str]]:
    if not (FORMAL / "SUCCESS").is_file(): raise Stop("STOP_FORMAL_PHASE_A_SUCCESS_REQUIRED")
    hashes_path, population_path = FORMAL / "artifact_hashes.json", FORMAL / "population_freeze.json"
    if not hashes_path.is_file() or not population_path.is_file(): raise Stop("STOP_FORMAL_PHASE_A_ANCHOR_MISSING")
    indexed = json.loads(hashes_path.read_text(encoding="utf-8")).get("indexed_artifacts", {})
    if indexed.get("population_freeze.json") != sha256(population_path): raise Stop("STOP_FORMAL_POPULATION_SHA_MISMATCH")
    population = json.loads(population_path.read_text(encoding="utf-8")); assert_result_free(population)
    return population, {"population_freeze.json": sha256(population_path), "artifact_hashes.json": sha256(hashes_path), "SUCCESS": sha256(FORMAL / "SUCCESS")}


def _formal_inputs() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    population, hashes = _formal_anchor()
    payload_path = FORMAL / "current_prediction_payload.json"
    index = json.loads((FORMAL / "artifact_hashes.json").read_text(encoding="utf-8")).get("indexed_artifacts", {})
    if index.get("current_prediction_payload.json") != sha256(payload_path):
        raise Stop("STOP_FORMAL_CURRENT_PAYLOAD_SHA_MISMATCH")
    payload = json.loads(payload_path.read_text(encoding="utf-8")); assert_result_free(payload)
    if payload.get("population_freeze_sha256") != hashes["population_freeze.json"]:
        raise Stop("STOP_DIAGNOSTIC_POPULATION_MISMATCH")
    races = payload.get("races")
    if not isinstance(races, list): raise Stop("STOP_FORMAL_CURRENT_PAYLOAD_INVALID")
    expected = {row["race_id"]: set(row.get("horse_numbers") or []) for row in population.get("source_records", [])}
    seen = set()
    for race in races:
        race_id = race.get("race_id"); ranked = race.get("prediction", race).get("ranked_results", race.get("ranked_results", []))
        if race_id in seen or race_id not in expected or {int(row["horse_number"]) for row in ranked} != expected[race_id]:
            raise Stop("STOP_DIAGNOSTIC_POPULATION_MISMATCH")
        seen.add(race_id)
    if set(expected) != seen: raise Stop("STOP_DIAGNOSTIC_POPULATION_MISMATCH")
    return population, races, hashes


def _cf_wrapper(races: list[dict[str, Any]]) -> tuple[set[tuple[str, int]], set[str], list[dict[str, Any]]]:
    from review.cf_top3_rank_anchored_shadow_v1 import protocol_hash, select_pre
    if protocol_hash() != "7ffd638277efe4dda615821e15d24bcbaafe8750436899f1157bafc1ea172521":
        raise Stop("STOP_CF_PROTOCOL_IDENTITY_MISMATCH")
    selected, scope, records = set(), set(), []
    for race in races:
        prediction = race.get("prediction", race); race_id = prediction["race_id"]
        record = select_pre(date=race["date"], venue=prediction["venue"], race_number=int(prediction["race_number"]), race_id=race_id, buy_gate_trace=prediction["buy_gate_trace"], ranked_results=prediction["ranked_results"])
        records.append(record)
        if record["shadow_eligibility"] == "ELIGIBLE":
            scope.add(race_id); selected.update((race_id, int(row["horse_number"])) for row in record["cf_selected_horses"])
    return selected, scope, records


def _v4_wrapper(races: list[dict[str, Any]], *, system_id: str) -> tuple[set[tuple[str, int]], set[str], list[dict[str, Any]]]:
    from review.v4_model_v3_formal_prospective_day1_pre_v1 import _v4_record
    if system_id == "DAILY_V5_REFERENCE":
        from review.prospective_three_system_pre_freeze_v1 import load_active_daily_v4
        model, scaler, _identity, _protocol = load_active_daily_v4()
    elif system_id == "V4_MODEL_V3_REFERENCE":
        import joblib
        model_root = ROOT / "reports" / "ml_v4_buy_selection_model_v3"
        expected = "7f06d9e3ba2f330b6f42d699ee25ea64d83a5287c3b7f72fb0233e14c755312d"
        if sha256(model_root / "model.joblib") != expected: raise Stop("STOP_V3_MODEL_IDENTITY_MISMATCH")
        model, scaler = joblib.load(model_root / "model.joblib"), joblib.load(model_root / "scaler.joblib")
    else: raise Stop("STOP_DIAGNOSTIC_SYSTEM_UNKNOWN")
    selected, scope, records = set(), set(), []
    for race in races:
        prediction = race.get("prediction", race)
        state = prediction.get("buy_gate_trace", {}).get("race", {}).get("shadow_race_state")
        if state == "PLAY_CONVERGED": scope.add(prediction["race_id"])
        record = _v4_record(date=race["date"], payload=prediction, model=model, scaler=scaler)
        records.append(record)
        selected.update((prediction["race_id"], int(row["horse_number"])) for row in record.get("selected_horses", []))
    return selected, scope, records


def _run_from_formal_test_only(*, selections: dict[str, set[tuple[str, int]]], population: list[tuple[str, int]], output: Path, scopes: dict[str, set[str]] | None = None, wrapper_records: dict[str, list[dict[str, Any]]] | None = None) -> Path:
    """Private synthetic seam; public execution has fixed roots and no inputs."""
    if output.exists() or output.with_name(output.name + ".staging").exists(): raise Stop("STOP_DIAGNOSTIC_ALREADY_ATTEMPTED")
    manifest = load_manifest(); order = manifest["fixed_display_order"]
    families = {item["system_id"]: item["model_family_id"] for item in manifest["systems"]}
    if scopes is None: raise Stop("STOP_DIAGNOSTIC_SCOPE_REQUIRED")
    horse = selection_bitmap(population, selections, order, families, scopes)
    artifacts = {"comparison_manifest_reference.json": {"path": MANIFEST.relative_to(ROOT).as_posix(), "sha256": sha256(MANIFEST)}, "system_selection_bitmap.json": horse, "race_selection_bitmap.json": race_bitmap(horse, order), "pairwise_overlap_28.json": pairwise_overlaps(selections, order), "selection_counts.json": {system: len(selections.get(system, set())) for system in order}, "diagnostic_wrapper_records.json": wrapper_records or {}, "evidence_boundary.json": {"result_access_count": 0, "source_content_access_count": 0, "current_rerun": False, "no_performance_ranking": True}}
    assert_result_free(artifacts)
    stage = output.with_name(output.name + ".staging"); stage.mkdir(parents=True)
    for name, value in artifacts.items(): (stage / name).write_bytes(canonical(value))
    hashes = {path.name: sha256(path) for path in sorted(stage.iterdir()) if path.is_file()}
    (stage / "artifact_hashes.json").write_bytes(canonical({"self_hash_excluded": True, "indexed_artifacts": hashes}))
    (stage / "SUCCESS").write_bytes(canonical({"status": "SUCCESS", "result_access_count": 0, "formal_phase_a_success_required": True}))
    stage.replace(output); return output


def run_real_diagnostic_panel() -> Path:
    """Fixed-root public entry; it never re-reads December TARGET source files."""
    population, races, _hashes = _formal_inputs()
    if OUTPUT.exists() or OUTPUT.with_name(OUTPUT.name + ".staging").exists(): raise Stop("STOP_DIAGNOSTIC_ALREADY_ATTEMPTED")
    cf, cf_scope, cf_records = _cf_wrapper(races)
    daily, daily_scope, daily_records = _v4_wrapper(races, system_id="DAILY_V5_REFERENCE")
    v3, v3_scope, v3_records = _v4_wrapper(races, system_id="V4_MODEL_V3_REFERENCE")
    formal_sets = {}
    for system, filename, key in (("CURRENT", "current_pre.json", "selected"), ("INDEPENDENT_V5", "independent_pre.json", "selected"), ("TRACKCONDITION_SEMANTIC", "trackcondition_pre.json", "selected"), ("FORMAL_V5", "v5_v6_pre.json", "v5_selected"), ("FORMAL_V6", "v5_v6_pre.json", "v6_selected")):
        rows = json.loads((FORMAL / filename).read_text(encoding="utf-8")).get(key, [])
        formal_sets[system] = {(str(row[0]), int(row[1])) for row in rows}
    selections = {**formal_sets, "CF_TOP3_RANK_ANCHORED": cf, "DAILY_V5_REFERENCE": daily, "V4_MODEL_V3_REFERENCE": v3}
    scopes = {system: {race["race_id"] for race in races} for system in formal_sets}
    scopes.update({"CF_TOP3_RANK_ANCHORED": cf_scope, "DAILY_V5_REFERENCE": daily_scope, "V4_MODEL_V3_REFERENCE": v3_scope})
    population_keys = [(row["race_id"], int(number)) for row in population["source_records"] for number in row.get("horse_numbers", [])]
    return _run_from_formal_test_only(selections=selections, population=population_keys, output=OUTPUT, scopes=scopes, wrapper_records={"cf": cf_records, "daily_v5": daily_records, "v3": v3_records})
