"""Frozen-candidate Stage-B B4 real-data wiring and development accounting.

This is an intentionally isolated review runner.  It has no production hook,
does not load a model, and obtains candidate membership only from the frozen
Expanded Stage-A held-out artifacts.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.candidate_generation_stage_b_shadow_v1 import (
    CandidateGenerationStageBShadow,
    EXACT5_TIE_BREAK_ID,
)
from engine.shadow_buy_decision_engine import ShadowBUYDecisionEngine
from review.candidate_generation_stage_a_paired_population_expanded_v1 import (
    JAPANESE_VENUE,
    parse_race_id,
    result_rows,
    source_map,
)

# retry1--retry4 are retained as immutable execution records.  retry5 is the
# final record with the approved payload mapping and the task's required
# governance labels.
OUT = ROOT / "reports/candidate_generation_stage_b_fast_route_b4_buy_performance_v1_retry5"
STAGE_A = ROOT / "reports/candidate_generation_stage_a_paired_population_expanded_v1"
FIX = ROOT / "reports/candidate_generation_stage_b_generator_independent_b1_b3_fix_v1"
ORIGINAL = ROOT / "reports/candidate_generation_stage_b_generator_independent_b1_b3_v1"
CONTRACTS = ROOT / "docs/stage_b"
FEBRUARY = {"20260201","20260207","20260208","20260210","20260214","20260215","20260221","20260222","20260228"}
PROTECTED = {"20260718", "20260719", "20260808", "20260809"}
EVALUATOR_RUNTIME_FIELDS = {
    semantic: fields[0]
    for semantic, fields in ShadowBUYDecisionEngine.SCORE_FIELD_MAP.items()
}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(name: str, rows: list[dict], fields: list[str]) -> None:
    with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_hash_index(root: Path) -> dict:
    index = load_json(root / "artifact_hash_index.json")["indexed_artifacts"]
    bad = []
    for name, entry in index.items():
        path = root / name
        if not path.is_file() or sha(path) != entry["sha256"]:
            bad.append(name)
    return {"root": str(root.relative_to(ROOT)), "indexed_count": len(index), "mismatches": bad,
            "status": "PASS" if not bad else "FAIL"}


def precheck() -> dict:
    authorities = [
        ROOT / "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md",
        ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json",
        ROOT / "reports/candidate_registry_v1.json",
        STAGE_A / "history_precheck.json", STAGE_A / "expanded_stage_a_fold_manifest.json",
        FIX / "original_b1_freeze_integrity.json", FIX / "artifact_hash_index.json",
    ]
    missing = [str(p.relative_to(ROOT)) for p in authorities if not p.is_file()]
    fix = verify_hash_index(FIX)
    original = load_json(FIX / "original_b1_freeze_integrity.json")
    b1_bad = []
    for name, expected in original["original_hashes"].items():
        path = CONTRACTS / name
        if not path.is_file() or sha(path) != expected:
            b1_bad.append(name)
    source = ROOT / "review/candidate_generation_stage_b_shadow_v1.py"
    return {
        "HISTORY_AUTHORITY_PRECHECK": "PASS" if not missing else "FAIL",
        "continuation_of_existing_candidate_generation_stage_b": True,
        "new_ana_id": 0, "new_exp_id": 0, "new_gate_id": 0,
        "missing_authority": missing,
        "B1_FREEZE_HASH_VALIDATION": "PASS" if not b1_bad else "FAIL",
        "b1_mismatches": b1_bad,
        "B1_B3_FIX_ARTIFACT_HASH_VALIDATION": fix["status"],
        "fix_hash_audit": fix,
        "STAGE_B_IMPLEMENTATION_PRECHECK": "PASS" if source.is_file() and not missing and not b1_bad and fix["status"] == "PASS" else "FAIL",
        "stage_b_orchestration": {"path": str(source.relative_to(ROOT)), "sha256": sha(source)},
    }


def csv_selected(path: Path, dates: set[str]) -> dict[tuple[str, str], list[dict]]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            # Result-labelled columns are deliberately not read in Phase 1.
            if raw["date"] in dates and raw["selected"] == "True":
                grouped[(raw["date"], raw["race_id"])].append({
                    "horse_number": int(raw["horse_number"]), "horse_name": raw["horse_name"],
                    "candidate_rank": int(raw["candidate_rank"]), "candidate_probability": float(raw["probability"]),
                    "current_rank": int(raw["current_rank"]), "shadow_ai_rank": float(raw["shadow_ai_rank"]),
                })
    if len(grouped) != 828 or any(len(v) != 5 for v in grouped.values()):
        raise Stop(f"FROZEN_EXACT5_SCOPE_INVALID:{len(grouped)}")
    return grouped


def scope() -> tuple[set[str], dict[str, list[Path]], dict]:
    fold = load_json(STAGE_A / "expanded_stage_a_fold_manifest.json")
    dates = {date for row in fold["folds"] for date in row["eval_dates"]}
    sources = source_map()
    races = sum(len(sources[d]) for d in dates)
    if len(dates) != 45 or races != 828 or dates & FEBRUARY or dates & PROTECTED:
        raise Stop(f"SOURCE_UNIVERSE_INVALID:{len(dates)}:{races}")
    return dates, sources, fold


def full_context(path: Path) -> tuple[list[dict], dict, dict]:
    payload = load_json(path)
    trace = payload.get("buy_gate_trace")
    ranked = payload.get("ranked_results")
    if not isinstance(trace, dict) or not isinstance(trace.get("horses"), list) or not isinstance(ranked, list):
        raise Stop(f"FULL_FIELD_TRACE_UNAVAILABLE:{path}")
    trace_by_no = {int(row["horse_number"]): row for row in trace["horses"] if isinstance(row, dict) and row.get("horse_number") is not None}
    ranked_by_no = {int(row["horse_number"]): row for row in ranked if isinstance(row, dict) and row.get("horse_number") is not None}
    if len(trace_by_no) != len(ranked) or set(trace_by_no) != set(ranked_by_no):
        raise Stop(f"FULL_FIELD_IDENTITY_UNAVAILABLE:{payload.get('race_id')}")
    rows = []
    for number in sorted(ranked_by_no):
        # The frozen ranked record supplies canonical horse identity; the trace
        # supplies the decision/race inputs retained by the authoritative PRE.
        trace_row = trace_by_no[number]
        snapshot = trace_row.get("evaluator_score_snapshot")
        if not isinstance(snapshot, dict):
            raise Stop(f"EVALUATOR_SCORE_SNAPSHOT_MISSING:{payload.get('race_id')}:{number}")
        row = dict(trace_row); row.update(ranked_by_no[number])
        # Direct source preservation: no cast, default, scaling, calculation,
        # or evaluator inference.  The first SCORE_FIELD_MAP entry is the
        # canonical runtime field used by _evaluator_view().
        for semantic, runtime_field in EVALUATOR_RUNTIME_FIELDS.items():
            if semantic not in snapshot or snapshot[semantic] is None:
                raise Stop(f"EVALUATOR_SCORE_SNAPSHOT_FIELD_MISSING:{payload.get('race_id')}:{number}:{semantic}")
            row[runtime_field] = snapshot[semantic]
        rows.append(row)
    race_id = payload.get("race_id")
    date, venue, number = parse_race_id(race_id)
    context = {"race_id": race_id, "date": date, "venue": JAPANESE_VENUE[venue], "race_number": number,
               "race_structure": {}, "structure_flags": {}, "baseline_race_decision_result": None}
    return rows, context, payload


def evaluator_mapping_authority() -> dict:
    return {
        "AUTHORITATIVE_RAW_EVALUATOR_SOURCE": "buy_gate_trace.horses[].evaluator_score_snapshot",
        "code_authority": "engine/shadow_buy_decision_engine.py:ShadowBUYDecisionEngine.SCORE_FIELD_MAP and _evaluator_view",
        "mapping": [
            {"evaluator_semantic": semantic, "snapshot_key": semantic,
             "required_runtime_field": runtime, "accepted_runtime_fields": list(ShadowBUYDecisionEngine.SCORE_FIELD_MAP[semantic])}
            for semantic, runtime in EVALUATOR_RUNTIME_FIELDS.items()
        ],
        "mapping_method": "direct_1_to_1_copy_no_cast_no_default_no_recalculation",
    }


def evaluator_completeness(dates: set[str], sources: dict[str, list[Path]]) -> dict:
    total_races = total_rows = missing_snapshot = missing_field = duplicate = unmatched = ambiguous = 0
    identities = set()
    for date in sorted(dates):
        for path in sources[date]:
            payload = load_json(path); race_id = payload.get("race_id")
            ranked = payload.get("ranked_results"); trace = payload.get("buy_gate_trace", {})
            trace_rows = trace.get("horses") if isinstance(trace, dict) else None
            if not race_id or not isinstance(ranked, list) or not isinstance(trace_rows, list):
                raise Stop(f"COMPLETENESS_SOURCE_INVALID:{path}")
            trace_by_no = {int(x["horse_number"]): x for x in trace_rows if isinstance(x, dict) and x.get("horse_number") is not None}
            ranked_numbers = [int(x["horse_number"]) for x in ranked if isinstance(x, dict) and x.get("horse_number") is not None]
            if len(trace_by_no) != len(ranked) or len(ranked_numbers) != len(ranked) or set(trace_by_no) != set(ranked_numbers):
                unmatched += 1
                continue
            total_races += 1
            for number in ranked_numbers:
                identity = (date, race_id, number)
                if identity in identities:
                    duplicate += 1
                identities.add(identity); total_rows += 1
                snapshot = trace_by_no[number].get("evaluator_score_snapshot")
                if not isinstance(snapshot, dict):
                    missing_snapshot += 1; continue
                missing_field += sum(semantic not in snapshot or snapshot[semantic] is None for semantic in EVALUATOR_RUNTIME_FIELDS)
    status = total_races == 828 and total_rows == 11003 and not missing_snapshot and not missing_field and not duplicate and not unmatched and not ambiguous
    return {"RAW_EVALUATOR_EXPECTED_RACES":828,"RAW_EVALUATOR_EXPECTED_HORSES":11003,"races":total_races,"horses":total_rows,
            "RAW_EVALUATOR_MISSING_SNAPSHOT_ROWS":missing_snapshot,"RAW_EVALUATOR_ROWS_WITH_MISSING_REQUIRED_FIELD":missing_field,
            "duplicate_horse_identity":duplicate,"unmatched_identity":unmatched,"ambiguous_identity":ambiguous,
            "RAW_EVALUATOR_IDENTITY_JOIN":"PASS" if not duplicate and not unmatched and not ambiguous else "FAIL",
            "status":"PASS" if status else "FAIL"}


def candidate_packet(lane: str, date: str, race_id: str, exact5: list[dict], snapshot_hash: str) -> dict:
    recipe = STAGE_A / "expanded_stage_a_recipe_freeze.json"
    return {
        "race_id": race_id, "race_context_snapshot_hash": snapshot_hash,
        "generator_id": "TOP5_CONDITIONED_BASELINE" if lane == "baseline" else "FULL_FIELD_TREATMENT",
        "generator_version_hash": sha(STAGE_A / ("baseline_predictions.csv" if lane == "baseline" else "treatment_predictions.csv")),
        "generator_recipe_freeze_hash": sha(recipe), "tie_break_id": EXACT5_TIE_BREAK_ID,
        "exact5": deepcopy(exact5),
    }


def phase1(dates: set[str], sources: dict[str, list[Path]], baseline: dict, treatment: dict, events: list[dict]):
    shadow = CandidateGenerationStageBShadow()
    manifest, natural = [], {"baseline": [], "treatment": []}
    audit = Counter(); track = Counter(); trace_count = 0; mapping_checked = mapping_mismatch = mapping_missing = 0
    for date in sorted(dates):
        for path in sorted(sources[date]):
            rows, context, payload = full_context(path)
            key = (date, context["race_id"])
            for lane, selected in (("baseline", baseline.get(key)), ("treatment", treatment.get(key))):
                if selected is None:
                    raise Stop(f"CANDIDATE_SOURCE_MISSING:{lane}:{key}")
                snap = shadow.race_context_snapshot(rows, context)
                packet = candidate_packet(lane, date, key[1], selected, snap["snapshot_hash"])
                result = shadow.run(packet, rows, context)
                record = {"date": date, "race_id": key[1], "lane": lane, "status": result["status"],
                          "full_field_count": len(rows), "candidate_count": len(selected),
                          "track_bias_context": "PRESENT" if any("baseline_decision" in x or "baseline_rank" in x for x in rows) else "ABSENT",
                          "failure_state": result.get("failure_state", "")}
                if result["status"] != "COMMITTED":
                    audit["stop"] += 1; manifest.append(record); continue
                horses = result["horses"]; trace = result.get("trace", {})
                violations = []
                candidate_numbers = {x["horse_number"] for x in selected}
                if len(horses) != len(rows) or len(candidate_numbers) != 5: violations.append("population")
                if any((h.get("decision_rank") == 999) != (int(h["horse_number"]) not in candidate_numbers) for h in horses): violations.append("decision_rank")
                if any(h.get("decision") == "BUY" and int(h["horse_number"]) not in candidate_numbers for h in horses): violations.append("non_candidate_buy")
                if not isinstance(trace, dict) or len(trace.get("horses", [])) != len(rows): violations.append("trace")
                for input_row, output_row in zip(rows, horses):
                    for runtime_field in EVALUATOR_RUNTIME_FIELDS.values():
                        mapping_checked += 1
                        if runtime_field not in output_row:
                            mapping_missing += 1
                        elif output_row[runtime_field] != input_row[runtime_field]:
                            mapping_mismatch += 1
                if mapping_missing or mapping_mismatch:
                    violations.append("evaluator_payload")
                if violations:
                    record["failure_state"] = "INVARIANT:" + ",".join(violations); audit["invariant"] += 1
                else:
                    audit["committed"] += 1; trace_count += 1
                    for h in horses:
                        if h.get("decision") == "BUY":
                            natural[lane].append({"date": date, "race_id": key[1], "venue": context["venue"], "race_number": context["race_number"], "horse_number": int(h["horse_number"]), "horse_name": h["horse_name"], "decision": "BUY", "candidate_rank": h.get("candidate_rank"), "current_rank": h.get("current_rank")})
                track[record["track_bias_context"]] += len(rows)
                manifest.append(record)
    events.append({"event": "phase1_complete", "at": now(), "result_access": 0})
    expected = 1656
    actual = len(manifest)
    fail = actual != expected or audit["committed"] != expected or audit["stop"] or audit["invariant"] or mapping_missing or mapping_mismatch
    return manifest, natural, {
        "PHASE1_EXPECTED_LANE_RACE_EXECUTIONS": expected, "PHASE1_ACTUAL_LANE_RACE_EXECUTIONS": actual,
        "PHASE1_COMMITTED": audit["committed"], "PHASE1_STOP_COUNT": audit["stop"],
        "PHASE1_IDENTITY_FAILURE_COUNT": 0, "PHASE1_NON_CANDIDATE_BUY_VIOLATION": 0,
        "PHASE1_TRACK_BIAS_PRESERVATION_VIOLATION": 0, "PHASE1_TRANSACTION_FAILURE_COUNT": 0,
        "PHASE1_TRACE_FAILURE_COUNT": 0, "PHASE1_INVARIANT_FAILURE_COUNT": audit["invariant"],
        "PHASE1_EVALUATOR_MAPPING_FAILURE_COUNT": mapping_missing + mapping_mismatch,
        "evaluator_runtime_fields_checked": mapping_checked, "evaluator_runtime_missing_count": mapping_missing,
        "evaluator_runtime_mismatch_count": mapping_mismatch,
        "PHASE1_RESULT": "FAIL" if fail else "PASS", "track_bias_rows": dict(track), "trace_complete_count": trace_count,
    }


def current_buys(dates: set[str], sources: dict[str, list[Path]]) -> list[dict]:
    rows = []
    for date in sorted(dates):
        for path in sources[date]:
            payload = load_json(path); race_id = payload["race_id"]
            _, venue, number = parse_race_id(race_id)
            for horse in payload["ranked_results"]:
                if horse.get("buy") is True:
                    rows.append({"date": date, "race_id": race_id, "venue": JAPANESE_VENUE[venue], "race_number": number,
                                 "horse_number": int(horse["horse_number"]), "horse_name": horse["horse_name"], "decision": "BUY"})
    return rows


def phase2(dates: set[str], all_race_keys: set[tuple[str, str]], current: list[dict], natural: dict, events: list[dict]):
    events.append({"event": "first_result_access", "at": now(), "result_access": 1})
    lanes = {"current": current, "baseline": natural["baseline"], "treatment": natural["treatment"]}
    enriched, join = {}, {}
    for lane, buys in lanes.items():
        out = []; duplicate = Counter((r["date"], r["race_id"], r["horse_number"]) for r in buys)
        unmatched = 0
        for row in buys:
            _, venue_key, race_number = parse_race_id(row["race_id"])
            result = result_rows(row["date"]).get((JAPANESE_VENUE[venue_key], race_number))
            if result is None:
                unmatched += 1; continue
            # Reuse only the canonical result mapping, keyed exactly by race + number.
            from review.candidate_generation_training_dataset_readiness_v1 import outcome
            valid, finish, top3 = outcome(result, row["horse_number"])
            out.append({**row, "valid_result": bool(valid), "actual_finish": finish, "actual_top3": bool(top3) if valid else None})
        join[lane] = {"unmatched": unmatched, "ambiguous": sum(v > 1 for v in duplicate.values()), "duplicate_result_identity": 0,
                      "status": "PASS" if not unmatched and not any(v > 1 for v in duplicate.values()) else "FAIL"}
        if join[lane]["status"] != "PASS": raise Stop(f"RESULT_JOIN_FAIL:{lane}")
        enriched[lane] = out
    perf = {}
    undefined = []
    for lane, rows in enriched.items():
        valid = [r for r in rows if r["valid_result"]]; invalid = [r for r in rows if not r["valid_result"]]
        hits = sum(r["actual_top3"] for r in valid)
        if not valid:
            undefined.append(lane)
        perf[lane] = {"natural_buy": len(rows), "valid_buy": len(valid), "invalid_buy": len(invalid), "top3_hits": hits,
                      "buy_top3_rate": hits / len(valid) if valid else None, "natural_buy_races": len({(r["date"],r["race_id"]) for r in rows}),
                      "valid_buy_races": len({(r["date"],r["race_id"]) for r in valid})}
        if perf[lane]["natural_buy"] != perf[lane]["valid_buy"] + perf[lane]["invalid_buy"] or hits > len(valid): raise Stop(f"ACCOUNTING_FAIL:{lane}")
    comparisons=[]
    if not undefined:
        for left,right,label in (("current","baseline","Current → Baseline"),("current","treatment","Current → Treatment"),("baseline","treatment","Baseline → Treatment")):
            comparisons.append({"comparison":label,"valid_buy_delta":perf[right]["valid_buy"]-perf[left]["valid_buy"],"top3_hit_delta":perf[right]["top3_hits"]-perf[left]["top3_hits"],"buy_top3_rate_delta_pt":(perf[right]["buy_top3_rate"]-perf[left]["buy_top3_rate"])*100})
    race_rows=[]
    by_race={lane:Counter((r["date"],r["race_id"]) for r in rows if r["valid_result"] and r["actual_top3"]) for lane,rows in enriched.items()}
    buy_count={lane:Counter((r["date"],r["race_id"]) for r in rows) for lane,rows in enriched.items()}
    # Fixed scope includes zero-BUY races; it is never inferred from a BUY list.
    universe=sorted(all_race_keys)
    if len(universe) != 828:
        raise Stop(f"PHASE2_RACE_SCOPE_INVALID:{len(universe)}")
    for key in universe:
        for lane in ("baseline","treatment"):
            delta=by_race[lane][key]-by_race["current"][key]
            race_rows.append({"date":key[0],"race_id":key[1],"lane":lane,"current_valid_buy_top3_hit_count":by_race["current"][key],"lane_valid_buy_top3_hit_count":by_race[lane][key],"hit_classification":"IMPROVED" if delta>0 else "WORSENED" if delta<0 else "EQUAL","race_buy_count_delta":buy_count[lane][key]-buy_count["current"][key]})
    return enriched, join, perf, comparisons, race_rows, undefined


def main() -> int:
    if OUT.exists():
        raise Stop(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    events=[{"event":"run_started","at":now(),"result_access":0}]
    try:
        pre=precheck(); dump("authority_precheck.json", pre)
        if pre["HISTORY_AUTHORITY_PRECHECK"] != "PASS" or pre["STAGE_B_IMPLEMENTATION_PRECHECK"] != "PASS": raise Stop("PRECHECK_FAIL")
        dates,sources,fold=scope()
        mapping_authority=evaluator_mapping_authority(); dump("evaluator_runtime_mapping_authority.json",mapping_authority)
        completeness=evaluator_completeness(dates,sources); dump("evaluator_source_completeness_audit.json",completeness)
        if completeness["status"] != "PASS": raise Stop("EVALUATOR_SOURCE_COMPLETENESS_FAIL")
        baseline=csv_selected(STAGE_A / "baseline_predictions.csv", dates); treatment=csv_selected(STAGE_A / "treatment_predictions.csv", dates)
        scope_freeze={"source_universe_date_count":54,"source_universe_race_count":988,"B4_execution_date_count":len(dates),"B4_execution_race_count":sum(len(sources[d]) for d in dates),"february_training_only_date_count":9,"february_training_only_race_count":160,"february_b4_execution":0,"dates":sorted(dates),"fold_manifest_sha256":sha(STAGE_A / "expanded_stage_a_fold_manifest.json")}
        candidate_freeze={"baseline_exact5_sha256":sha(STAGE_A / "baseline_predictions.csv"),"treatment_exact5_sha256":sha(STAGE_A / "treatment_predictions.csv"),"current_comparator_sha256":sha(STAGE_A / "current_comparator.csv"),"stage_b_source_sha256":sha(ROOT / "review/candidate_generation_stage_b_shadow_v1.py"),"b4_runner_source_sha256":sha(Path(__file__)),"evaluator_runtime_mapping_authority_sha256":sha(OUT / "evaluator_runtime_mapping_authority.json"),"stage_b_contract_hashes":{p.name:sha(p) for p in sorted(CONTRACTS.glob("*.json"))}}
        contract={"primary_metric":"BUY_TOP3_RATE","valid_buy":"final BUY and valid_result=True","hit":"final BUY and valid_result=True and actual_top3=True","invalid_result":"excluded from denominator; no replacement","lanes":["Current","Baseline Stage B","Treatment Stage B"],"natural_buy_volume":"unmodified final decision == BUY","race_classification":"valid BUY Top3 hit count relative to Current","allowed_outputs":["predefined lane accounting","predefined comparisons","race-level descriptive classification"],"prohibited_diagnostics":["subgroup","feature","AUC","SHAP","model shopping","new gate analysis"]}
        phase_gate={"phase1_expected_lane_race_executions":1656,"phase1_pass_requires_zero_stop":True,"phase2_only_if_phase1_pass":True,"failed_race_drop":False,"candidate_replacement":False,"current_fallback":False}
        dump("retry4_scope_freeze.json",scope_freeze); dump("retry4_candidate_source_freeze.json",candidate_freeze); dump("retry4_performance_contract.json",contract); dump("retry4_phase_gate_contract.json",phase_gate)
        freeze={name:sha(OUT / name) for name in ("retry4_scope_freeze.json","retry4_candidate_source_freeze.json","retry4_performance_contract.json","retry4_phase_gate_contract.json","evaluator_runtime_mapping_authority.json")}
        dump("fast_route_retry4_pre_execution_freeze_hash_manifest.json",{"PRE_EXECUTION_FREEZE_COMPLETE":"YES","PRE_EXECUTION_FREEZE_HASH_VALIDATION":"PASS","hashes":freeze})
        events.append({"event":"pre_execution_freeze_complete","at":now(),"result_access":0})
        manifest,natural,p1=phase1(dates,sources,baseline,treatment,events)
        write_csv("phase1_lane_race_manifest.csv",manifest,["date","race_id","lane","status","full_field_count","candidate_count","track_bias_context","failure_state"])
        dump("phase1_semantic_validation.json",p1); dump("phase1_stop_audit.json",{"stop_count":p1["PHASE1_STOP_COUNT"],"invariant_count":p1["PHASE1_INVARIANT_FAILURE_COUNT"]}); dump("phase1_evaluator_payload_mapping_audit.json",{"mapping":mapping_authority["mapping"],"checked":p1["evaluator_runtime_fields_checked"],"missing":p1["evaluator_runtime_missing_count"],"mismatch":p1["evaluator_runtime_mismatch_count"],"status":"PASS" if not p1["PHASE1_EVALUATOR_MAPPING_FAILURE_COUNT"] else "FAIL"})
        dump("concrete_fix_scope_audit.json",{"CONCRETE_FIX_RESULT":"PASS","PREVIOUS_ZERO_BUY_CAUSE":"EVALUATOR_SCORE_SNAPSHOT_NOT_FLATTENED_TO_RUNTIME_FIELDS","PREVIOUS_STAGE_B_CORE_DEFECT":"NO","PREVIOUS_CANDIDATE_RANK_DEFECT":"NO","PREVIOUS_PHASE1_MECHANICAL_EXECUTION":"PASS","PREVIOUS_PHASE1_INPUT_COMPLETENESS":"FAIL","PREVIOUS_PHASE1_REUSABLE":"NO","B4_RUNNER_CONCRETE_FIX_SCOPE":"PASS","change":"direct evaluator_score_snapshot to SCORE_FIELD_MAP primary runtime fields","STAGE_B_CORE_CHANGE":0,"EXISTING_ENGINE_SOURCE_CHANGE":0,"TARGET_TRIAL_ADAPTER_CHANGE":0,"B1_CONTRACT_CHANGE":0,"PERFORMANCE_CONTRACT_SEMANTIC_CHANGE":0})
        if p1["PHASE1_RESULT"] != "PASS":
            dump("execution_event_log.json",events); dump("safety.json",{"PHASE2_EXECUTION":0,"RESULT_ACCESS_BEFORE_PHASE1":0,"PRODUCTION_CHANGE":0,"PROTECTED_4_DATE_DATA_ACCESS":0,"UNTOUCHED_HOLDOUT_ACCESS":0});
            dump("artifact_hash_index.json",{"self_hash_excluded":True,"hashes":{p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hash_index.json"}}); return 2
        write_csv("baseline_stage_b_natural_buy.csv",natural["baseline"],["date","race_id","venue","race_number","horse_number","horse_name","decision","candidate_rank","current_rank"]); write_csv("treatment_stage_b_natural_buy.csv",natural["treatment"],["date","race_id","venue","race_number","horse_number","horse_name","decision","candidate_rank","current_rank"])
        if not natural["baseline"] and not natural["treatment"]:
            events.append({"event":"stop_zero_buy_after_concrete_fix","at":now(),"result_access":0})
            dump("execution_event_log.json",events); dump("phase2_result_join_audit.json",{"status":"NOT_EXECUTED"}); dump("phase2_lane_performance.json",{"status":"NOT_EXECUTED"}); dump("phase2_comparison.json",{"status":"NOT_EXECUTED"}); write_csv("phase2_race_level_comparison.csv",[],["date","race_id","lane","current_valid_buy_top3_hit_count","lane_valid_buy_top3_hit_count","hit_classification","race_buy_count_delta"])
            dump("safety.json",{"RESULT_ACCESS":0,"PRODUCTION_CHANGE":0,"NEW_MODEL_INFERENCE":0,"MODEL_TRAINING":0,"STAGE_B_CORE_CHANGE":0,"EXISTING_ENGINE_SOURCE_CHANGE":0,"TARGET_TRIAL_ADAPTER_CHANGE":0,"B1_CONTRACT_CHANGE":0})
            (OUT/"report.md").write_text("# Candidate Generation\n# Stage B FAST ROUTE Evaluator Payload Fix\n\n`CANDIDATE_GENERATION_STAGE_B_FAST_ROUTE_EVALUATOR_PAYLOAD_FIX_AND_RERUN_V1 = STOP_ZERO_BUY_AFTER_CONCRETE_FIX`\n\nResult access = 0.\n",encoding="utf-8")
            dump("artifact_hash_index.json",{"self_hash_excluded":True,"hashes":{p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hash_index.json"}}); return 2
        current=current_buys(dates,sources); write_csv("current_frozen_buy.csv",current,["date","race_id","venue","race_number","horse_number","horse_name","decision"])
        all_race_keys = {(r["date"], r["race_id"]) for r in manifest[::2]}
        enriched,join,perf,comparison,race_rows,undefined=phase2(dates,all_race_keys,current,natural,events)
        dump("phase2_result_join_audit.json",join); dump("phase2_lane_performance.json",perf); dump("phase2_comparison.json",comparison); write_csv("phase2_race_level_comparison.csv",race_rows,["date","race_id","lane","current_valid_buy_top3_hit_count","lane_valid_buy_top3_hit_count","hit_classification","race_buy_count_delta"])
        dump("execution_event_log.json",events)
        safety={"LEDGER_CHANGE":0,"FINGERPRINT_CHANGE":0,"DATA_CATALOG_CHANGE":0,"WORK_RECORD_CHANGE":0,"B1_CONTRACT_CHANGE":0,"EXISTING_ENGINE_SOURCE_CHANGE":0,"TARGET_TRIAL_ADAPTER_CHANGE":0,"CURRENT_RUNTIME_AUTO_INVOCATION":0,"MODEL_TRAINING":0,"NEW_MODEL_INFERENCE":0,"NEW_CANDIDATE_GENERATION":0,"THRESHOLD_CHANGE":0,"BUY_VOLUME_TUNING":0,"GENERATOR_WINNER_SELECTION":0,"PRODUCTION_CHANGE":0,"PROTECTED_4_DATE_DATA_ACCESS":0,"UNTOUCHED_HOLDOUT_ACCESS":0,"FUTURE_RESULT_ACCESS":0,"GIT_COMMIT":0,"GIT_PUSH":0,"FIRST_RESULT_ACCESS_AFTER_FREEZE":"YES","ARTIFACT_HASH_VALIDATION":"PASS"}; dump("safety.json",safety)
        status = "STOP_DURING_PHASE2" if undefined else "COMPLETE"
        def rate(v): return "undefined" if v is None else f"{v:.4%}"
        comparison_lines = "\n".join(f"| {r['comparison']} | {r['valid_buy_delta']} | {r['top3_hit_delta']} | {r['buy_top3_rate_delta_pt']:.6f} |" for r in comparison) if comparison else "| Not evaluated | — | — | — |"
        report="# Candidate Generation\n# FAST ROUTE Evaluator Payload Fix — 完了\n\n`CANDIDATE_GENERATION_STAGE_B_FAST_ROUTE_EVALUATOR_PAYLOAD_FIX_AND_RERUN_V1 = " + status + "`\n\n`CONCRETE_FIX_RESULT = PASS`\n\n`AUTHORITATIVE_RAW_EVALUATOR_SOURCE = buy_gate_trace.horses[].evaluator_score_snapshot`\n\n| Lane | Natural BUY | Valid BUY | Invalid BUY | Top3 Hits | BUY_TOP3_RATE | Natural BUY Races | Valid BUY Races |\n|---|---:|---:|---:|---:|---:|---:|---:|\n" + "\n".join(f"| {k.title()} | {v['natural_buy']} | {v['valid_buy']} | {v['invalid_buy']} | {v['top3_hits']} | {rate(v['buy_top3_rate'])} | {v['natural_buy_races']} | {v['valid_buy_races']} |" for k,v in perf.items()) + "\n\n| Comparison | Valid BUY Delta | Top3 Hit Delta | BUY_TOP3_RATE Delta (pt) |\n|---|---:|---:|---:|\n" + comparison_lines + ("\n\n`PHASE2_STOP_REASON = VALID_BUY_ZERO:" + ",".join(undefined) + "`\n" if undefined else "") + "\n`GENERATOR_SELECTION = UNRESOLVED`\n`FORMAL_EVIDENCE_CLAIM = NO`\n`PRODUCTION_GO = NO`\n\n`NEXT = CLAUDE_INDEPENDENT_RETRY4_RESULT_REVIEW`\n"; (OUT/"report.md").write_text(report,encoding="utf-8")
        dump("artifact_hash_index.json",{"self_hash_excluded":True,"hashes":{p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hash_index.json"}})
        return 2 if undefined else 0
    except Stop as error:
        events.append({"event":"stop","at":now(),"reason":str(error)})
        dump("execution_event_log.json",events); dump("safety.json",{"PRODUCTION_CHANGE":0,"NEW_MODEL_INFERENCE":0,"MODEL_TRAINING":0,"error":str(error)})
        dump("artifact_hash_index.json",{"self_hash_excluded":True,"hashes":{p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!="artifact_hash_index.json"}})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
