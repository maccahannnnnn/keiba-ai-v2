"""April holdout Phase A recovery plus the single authorised atomic Phase B POST."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review import april_one_shot_post_evaluation_v1 as base
from review.target_bulk_prediction_input_adapter_v1 import COURSE_KEYS
from review.target_daily_result_list_schema_v2_validator import validate_source_pair


ROOT = base.ROOT
PRE = base.PRE
RAW = base.RAW
DATES = base.DATES
PHASE_A = ROOT / "reports" / "april_2026_retrospective_external_holdout_v2" / "phase_a_recovery_finalization_v3"
OUT = ROOT / "reports" / "april_2026_retrospective_external_holdout_v2" / "one_shot_post_evaluation_v4"
V3_AUXILIARY_SHA256 = "c9dfee5dd348390459be33d7dd68f16acd6acee5ef833015e5e22347e0b6c9d9"


class Stop(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}:{detail}")
        self.code, self.detail = code, detail


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(root: Path, name: str, value: object) -> Path:
    path = root / name
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def active_paths(date: str) -> tuple[Path, Path]:
    primary = RAW / f"馬番順着順_{date}.csv"
    auxiliary = RAW / ("着順馬番_20260405_v3.csv" if date == "20260405" else f"着順馬番_{date}.csv")
    return primary, auxiliary


def phase_a_recovery() -> tuple[dict, dict[str, dict], dict]:
    if PHASE_A.exists():
        raise FileExistsError(f"PHASE_A_OUTPUT_EXISTS:{PHASE_A}")
    PHASE_A.mkdir(parents=True)
    frozen = base.pre_immutable()
    old = RAW / "着順馬番_20260405.csv"
    v2 = RAW / "着順馬番_20260405_v2.csv"
    v3 = RAW / "着順馬番_20260405_v3.csv"
    if not all(path.is_file() for path in (old, v2, v3)):
        raise Stop("RESULT_SOURCE_RECOVERY_MISSING", "20260405_AUXILIARY_LINEAGE")
    if sha(v3) != V3_AUXILIARY_SHA256 or v2.read_bytes() != v3.read_bytes():
        raise Stop("RESULT_SOURCE_RECOVERY_INTEGRITY_FAILURE", "20260405_AUXILIARY_V2_V3")
    recovery = {
        "record_id": "RESULT_SOURCE_RECOVERY_20260405_AUXILIARY_V3",
        "status": "PASS",
        "old_file": {"path": str(old.relative_to(ROOT)), "sha256": sha(old), "retained_immutable": True},
        "v2_file": {"path": str(v2.relative_to(ROOT)), "sha256": sha(v2), "retained_immutable": True},
        "v3_file": {"path": str(v3.relative_to(ROOT)), "sha256": sha(v3), "retained_immutable": True},
        "v2_v3_byte_identical": True,
        "original_failure_reason": "placeholder_like_1_2_3_content_in_old_FINISH_ORDER_HORSE_NUMBER_variant",
        "recovery_reason": "HUMAN_APPROVED_AUXILIARY_RECOVERY_WITH_REVIEWED_BYTE_IDENTICAL_V2_V3",
        "lineage": "old retained; v2 retained; v3 selected as active lineage version; no overwrite or deletion",
        "active_version": "v3",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "executor": "Codex",
    }
    labels = {
        "record_id": "RESULT_SOURCE_LABEL_CORRECTION",
        "status": "PASS",
        "primary": "HORSE_NUMBER_ORDER_FINISH_STATUS",
        "auxiliary": "FINISH_ORDER_HORSE_NUMBER",
        "correction": "Previous Source C/D terminology was reversed or ambiguous. Historical artifacts are not rewritten; this additive record governs this execution only.",
    }
    records, lookup = [], {}
    for date in DATES:
        primary, auxiliary = active_paths(date)
        if not primary.is_file() or not auxiliary.is_file():
            raise Stop("APRIL_POST_RESULT_INVENTORY_FAILURE", f"MISSING:{date}")
        try:
            structural = validate_source_pair(primary, auxiliary, date)
        except Exception as exc:
            raise Stop("APRIL_POST_RESULT_INVENTORY_FAILURE", f"SCHEMA:{date}:{exc}") from exc
        primary_rows, auxiliary_rows = base.read_rows(primary), base.read_rows(auxiliary)
        primary_by_key = {row[0]: row for row in primary_rows}
        auxiliary_by_key = {row[0]: row for row in auxiliary_rows}
        if len(primary_rows) != len(primary_by_key) or len(auxiliary_rows) != len(auxiliary_by_key):
            raise Stop("APRIL_POST_RESULT_INVENTORY_FAILURE", f"DUPLICATE_RACE:{date}")
        record = {
            "date": date,
            "primary": {"variant": "HORSE_NUMBER_ORDER_FINISH_STATUS", "path": str(primary.relative_to(ROOT)), "sha256": sha(primary)},
            "auxiliary": {"variant": "FINISH_ORDER_HORSE_NUMBER", "path": str(auxiliary.relative_to(ROOT)), "sha256": sha(auxiliary)},
            "schema_v2_structural": structural,
        }
        records.append(record)
        lookup[date] = {"primary": primary_by_key, "auxiliary": auxiliary_by_key}
    active_set = {"manifest_id": "APRIL_2026_ACTIVE_RESULT_SOURCE_SET_V2", "status": "PASS", "active_file_count": 16, "records": records}
    rule = """# One-Shot Immutability Rule v2\n\nRESULT_STAGE_RELAXATION_POLICY = HUMAN_APPROVED\n\n## AGGREGATE_PERFORMANCE_DISCLOSURE_BOUNDARY\n\nPhase A permits only mechanical and structural Result-ingestion recovery aligned with a pre-existing approved specification, with immutable lineage and review, before any aggregate performance is computed or disclosed.\n\nPhase B begins at semantic outcome evaluation and runs atomically through its final frozen report. After aggregate performance is computed or disclosed, any repaired rerun of the same cohort is CONTAMINATED_REEXECUTION_DIAGNOSTIC_ONLY.\n"""
    rule_path = PHASE_A / "one_shot_immutability_rule_v2.md"
    rule_path.write_text(rule, encoding="utf-8")
    write_json(PHASE_A, "result_source_recovery_20260405_auxiliary_v3.json", recovery)
    write_json(PHASE_A, "result_source_label_correction.json", labels)
    write_json(PHASE_A, "active_result_source_set_v2.json", active_set)
    write_json(PHASE_A, "result_inventory.json", {"status": "PASS", "date_count": 8, "active_file_count": 16, "aggregate_performance_computed": False})
    return frozen, lookup, {"recovery": recovery, "labels": labels, "active_set": active_set, "rule_path": rule_path, "rule_sha256": sha(rule_path)}


def formal_crosscheck(primary: list[str], auxiliary: list[str], race_key: str) -> dict:
    head_count = int(primary[9])
    groups: dict[int, list[int]] = defaultdict(list)
    abnormal: set[int] = set()
    for number in range(1, head_count + 1):
        outcome = base.source_c_outcome(primary, number)
        if outcome["valid_result"]:
            groups[outcome["actual_finish"]].append(number)
        else:
            abnormal.add(number)
    ordered = [int(value) for value in auxiliary[12:12 + head_count]]
    offset = 0
    for finish in sorted(groups):
        expected = set(groups[finish])
        observed = set(ordered[offset:offset + len(expected)])
        if observed != expected:
            raise Stop("VARIANT_CROSSCHECK_STOP", json.dumps({"race_key": race_key, "failure_group": finish, "primary_finish_group_horses": sorted(expected), "auxiliary_group_horses": sorted(observed)}, ensure_ascii=False))
        offset += len(expected)
    observed_abnormal = set(ordered[offset:])
    if observed_abnormal != abnormal:
        raise Stop("VARIANT_CROSSCHECK_STOP", json.dumps({"race_key": race_key, "failure_group": "ABNORMAL_SUFFIX", "primary_abnormal_horses": sorted(abnormal), "auxiliary_suffix_horses": sorted(observed_abnormal)}, ensure_ascii=False))
    return {"target_race_key": race_key, "head_count": head_count, "finish_rank_groups": {str(rank): sorted(numbers) for rank, numbers in groups.items()}, "auxiliary_finish_order": ordered, "status": "PASS"}


def phase_a_crosscheck(frozen: dict, lookup: dict[str, dict], phase: dict) -> dict:
    records = []
    for artifact in frozen["prediction"]["artifacts"]:
        race_id = artifact["race_id"]
        date = race_id.split("_")[1]
        venue, number = base.venue_number(race_id)
        venue_name = next((name for name, key in COURSE_KEYS.items() if key == venue), None)
        matches = [(key, row) for key, row in lookup[date]["primary"].items() if row[1] == venue_name and int(row[2]) == number]
        if len(matches) != 1:
            raise Stop("VARIANT_CROSSCHECK_STOP", f"PRE_RACE_IDENTITY:{race_id}:{len(matches)}")
        key, primary = matches[0]
        auxiliary = lookup[date]["auxiliary"].get(key)
        if auxiliary is None:
            raise Stop("VARIANT_CROSSCHECK_STOP", f"AUXILIARY_RACE_MISSING:{key}")
        records.append(formal_crosscheck(primary, auxiliary, key))
    if len(records) != 152:
        raise Stop("APRIL_POST_POPULATION_IDENTITY_FAILURE", f"FORMAL_CROSSCHECK_COUNT:{len(records)}")
    result = {"status": "PASS", "method": "TARGET_DAILY_RESULT_LIST_SCHEMA_V1.variant_crosscheck.method", "stop_code": "VARIANT_CROSSCHECK_STOP", "scope": "FROZEN_PRE_152_PREDICTION_RACES_ONLY", "pass_count": len(records), "records": records}
    gate = {"status": "PHASE_A_RECOVERY_COMPLETE", "recovery_artifact": "PASS", "label_correction": "PASS", "active_result_source_set": "PASS", "inventory": "PASS", "formal_variant_crosscheck": "152/152 PASS", "frozen_pre_identity": "PASS", "pre_hashes_unchanged": "PASS", "result_stage_rule": {"path": str(phase["rule_path"].relative_to(ROOT)), "sha256": phase["rule_sha256"]}, "aggregate_performance_computed": False, "may_access": 0, "access_2025": 0}
    write_json(PHASE_A, "formal_variant_crosscheck_152r.json", result)
    write_json(PHASE_A, "phase_a_final_gate.json", gate)
    hashes = {path.name: sha(path) for path in PHASE_A.iterdir() if path.is_file()}
    write_json(PHASE_A, "artifact_hashes.json", {"indexed_artifacts": hashes, "self_hash_excluded": True})
    return result


def evaluate_phase_b(frozen: dict, lookup: dict[str, dict], phase: dict, cross: dict) -> Path:
    if OUT.exists():
        raise FileExistsError(f"POST_OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        v3 = json.loads((PRE / "v3_pre_selections.json").read_text(encoding="utf-8"))["records"]
        cf = json.loads((PRE / "cf_pre_selections.json").read_text(encoding="utf-8"))["records"]
        if len(v3) != 152 or len(cf) != 152:
            raise Stop("APRIL_POST_POPULATION_IDENTITY_FAILURE", "SELECTION_RACE_COUNT")
        pre_horses, pool, v3_selected, cf_selected, current_unconverged = [], [], [], [], []
        race_keys = {}
        for artifact in frozen["prediction"]["artifacts"]:
            payload = json.loads((ROOT / artifact["path"]).read_text(encoding="utf-8"))
            race_id = payload["race_id"]
            date = race_id.split("_")[1]
            venue, number = base.venue_number(race_id)
            venue_name = next((name for name, key in COURSE_KEYS.items() if key == venue), None)
            matches = [(key, row) for key, row in lookup[date]["primary"].items() if row[1] == venue_name and int(row[2]) == number]
            if len(matches) != 1:
                raise Stop("APRIL_POST_RESULT_JOIN_FAILURE", f"RACE:{race_id}:{len(matches)}")
            key, primary = matches[0]
            race_keys[race_id] = key
            for horse in payload["ranked_results"]:
                number_horse = int(horse["horse_number"])
                pre_horses.append({"race_id": race_id, "target_race_key": key, "horse_number": number_horse, "horse_name": horse.get("horse_name"), "rank": horse.get("rank"), "current_buy": bool(horse.get("buy")), **base.source_c_outcome(primary, number_horse)})
        if len(pre_horses) != 2035 or len({(r["race_id"], r["horse_number"]) for r in pre_horses}) != 2035:
            raise Stop("APRIL_POST_RESULT_JOIN_FAILURE", "FROZEN_HORSE_IDENTITY")
        outcomes = {(r["race_id"], r["horse_number"]): r for r in pre_horses}
        v3_e = [r for r in v3 if r["eligible"]]
        cf_e = [r for r in cf if r["shadow_eligibility"] == "ELIGIBLE"]
        if len(v3_e) != 35 or len(cf_e) != 35 or {r["race_id"] for r in v3_e} != {r["race_id"] for r in cf_e}:
            raise Stop("APRIL_POST_POPULATION_IDENTITY_FAILURE", "ELIGIBLE_RACE_SET")
        for vrow, crow in zip(sorted(v3_e, key=lambda r: r["race_id"]), sorted(cf_e, key=lambda r: r["race_id"])):
            vp = {(r["horse_number"], r["shadow_ai_rank"]) for r in vrow["all_candidates"]}
            cp = {(r["horse_number"], r["shadow_ai_rank"]) for r in crow["candidate_horses"]}
            if vp != cp or len(vp) < 4:
                raise Stop("APRIL_POST_POPULATION_IDENTITY_FAILURE", vrow["race_id"])
            pool.extend({**outcomes[(vrow["race_id"], h)], "shadow_ai_rank": rank} for h, rank in sorted(vp))
            v3_selected.extend({**outcomes[(vrow["race_id"], r["horse_number"])], "shadow_ai_rank": r["shadow_ai_rank"], "predicted_top3_probability": r["predicted_top3_probability"]} for r in vrow["selected"])
            cf_selected.extend({**outcomes[(crow["race_id"], r["horse_number"])], "shadow_ai_rank": r["shadow_ai_rank"]} for r in crow["cf_selected_horses"])
            current_unconverged.extend(r for r in pre_horses if r["race_id"] == vrow["race_id"] and r["current_buy"])
        if (len(pool), len(v3_selected), len(cf_selected)) != (162, 105, 105):
            raise Stop("APRIL_POST_POPULATION_IDENTITY_FAILURE", "FROZEN_COUNTS")
        pm, vm, cm = base.metric(pool), base.metric(v3_selected), base.metric(cf_selected)
        vlift = None if pm["top3_rate"] is None or vm["top3_rate"] is None else vm["top3_rate"] - pm["top3_rate"]
        clift = None if pm["top3_rate"] is None or cm["top3_rate"] is None else cm["top3_rate"] - pm["top3_rate"]
        current_all = [r for r in pre_horses if r["current_buy"]]
        c35, c152 = base.metric(current_unconverged), base.metric(current_all)
        whole = {"scope": "SECONDARY_ONLY_35_PLAY_UNCONVERGED_4PLUS_RACES", "current": {"selection_volume": len(current_unconverged), **c35}, "v3_counterfactual": {"selection_volume": len(v3_selected), **vm}, "cf_counterfactual": {"selection_volume": len(cf_selected), **cm}}
        v3_eval = {"scope": "PRIMARY_SELECTOR_EVALUATION_SCOPE_35_PLAY_UNCONVERGED_4PLUS_RACES", "selected_horses": v3_selected, **vm, "selection_lift": vlift, "selection_lift_percentage_points": None if vlift is None else vlift * 100, "april_classification": base.classify(vlift, 35), "temporal_interpretation": "RETROSPECTIVE_EXTERNAL_HOLDOUT"}
        cf_eval = {"scope": "PRIMARY_SELECTOR_EVALUATION_SCOPE_35_PLAY_UNCONVERGED_4PLUS_RACES", "selected_horses": cf_selected, **cm, "selection_lift": clift, "selection_lift_percentage_points": None if clift is None else clift * 100, "april_classification": base.classify(clift, 35), "april_plus3_interpretation": "APRIL_COMMON_REPORTING_SCALE_ONLY_NOT_CF_PROSPECTIVE_ACCEPT_REJECT"}
        payloads = [base.schema_payload(v3_eval), base.schema_payload(cf_eval), base.schema_payload(whole)]
        if not all(base.schema_valid(payload) for payload in payloads):
            raise Stop("APRIL_POST_EVIDENCE_SCHEMA_FAILURE", "SCHEMA_CONSTANTS")
        write_json(OUT, "result_inventory.json", phase["active_set"])
        write_json(OUT, "result_pair_reconciliation.json", cross)
        write_json(OUT, "result_join_manifest.json", {"status": "PASS", "matched_horse_count": len(pre_horses), "missing_count": 0, "ambiguous_count": 0, "race_mapping_count": len(race_keys), "primary_semantic_authority": "HORSE_NUMBER_ORDER_FINISH_STATUS", "auxiliary_semantics_used": False})
        write_json(OUT, "valid_result_manifest.json", {"horses": pre_horses, "invalid_result_count": sum(not r["valid_result"] for r in pre_horses)})
        write_json(OUT, "candidate_pool_evaluation.json", {"scope": "PRIMARY_SELECTOR_EVALUATION_SCOPE_35_PLAY_UNCONVERGED_4PLUS_RACES", "eligible_race_count": 35, "candidate_pool": pool, **pm})
        write_json(OUT, "v3_post_evaluation.json", payloads[0])
        write_json(OUT, "cf_post_evaluation.json", payloads[1])
        write_json(OUT, "whole_system_counterfactual.json", payloads[2])
        write_json(OUT, "current_system_reference_152r.json", {"scope": "CURRENT_SYSTEM_REFERENCE_SCOPE_152_APRIL_PREDICTION_RACES", "current_buy_count": len(current_all), **c152})
        manifest = {"status": "APRIL_ONE_SHOT_POST_EVALUATION_COMPLETE", "phase_a_recovery_reference": str(PHASE_A.relative_to(ROOT)), "result_stage_rule_reference": {"path": str(phase["rule_path"].relative_to(ROOT)), "sha256": phase["rule_sha256"]}, "pre_immutability": "PASS", "pre_root": str(PRE.relative_to(ROOT)), "pre_hashes": base.EXPECTED, "formal_variant_crosscheck": "152/152 PASS", "result_join": {"status": "PASS", "matched_horse_count": len(pre_horses), "missing_count": 0, "ambiguous_count": 0}, "primary_population": {"eligible_races": 35, "candidate_horses": 162, "v3_selected": 105, "cf_selected": 105}, "evidence_band": "RETROSPECTIVE_EXTERNAL_HOLDOUT", "phase_b_atomic": True, "generated_at": datetime.now(timezone.utc).isoformat(), "access_and_change_counts": {"prediction_rerun": 0, "pre_modification": 0, "v3_semantic_change": 0, "cf_semantic_change": 0, "production_change": 0, "may_access": 0, "access_2025": 0}}
        write_json(OUT, "post_evaluation_manifest.json", manifest)
        report = "# April 2026 Retrospective External Holdout — One-Shot POST Evaluation v2\n\n`APRIL_ONE_SHOT_POST_EVALUATION_COMPLETE`\n\nPhase Aの復旧後、Phase Bは中間の成績出力なしに原子的に完了した。詳細はJSON成果物を参照。\n"
        (OUT / "report.md").write_text(report, encoding="utf-8")
        hashes = {p.name: sha(p) for p in OUT.iterdir() if p.is_file()}
        write_json(OUT, "artifact_hashes.json", {"indexed_artifacts": hashes, "self_hash_excluded": True})
        return OUT
    except Stop as exc:
        write_json(OUT, "post_evaluation_manifest.json", {"status": "STOP_WITH_REASON", "reason_code": exc.code, "detail": exc.detail, "phase_b_atomic": True, "access_and_change_counts": {"prediction_rerun": 0, "pre_modification": 0, "v3_semantic_change": 0, "cf_semantic_change": 0, "production_change": 0, "may_access": 0, "access_2025": 0}})
        return OUT


def run() -> Path:
    try:
        frozen, lookup, phase = phase_a_recovery()
        cross = phase_a_crosscheck(frozen, lookup, phase)
    except Stop as exc:
        if PHASE_A.exists():
            write_json(PHASE_A, "phase_a_final_gate.json", {"status": "STOP_WITH_REASON", "reason_code": exc.code, "detail": exc.detail, "aggregate_performance_computed": False})
        return PHASE_A
    return evaluate_phase_b(frozen, lookup, phase, cross)


if __name__ == "__main__":
    print(run())
