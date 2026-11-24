"""One-shot August validation of the frozen LOW_CAPACITY_TOP3_SELECTOR_V2.

All selection is created from frozen August prediction artifacts and the
already-fitted pipeline before the historical result export is parsed.  The
runner never calls fit, fit_transform, or partial_fit.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "low_capacity_top3_selector_v2_august_validation_v1"
TRAIN_ROOT = ROOT / "reports" / "low_capacity_top3_selector_v2_train_v1_retry2"
MODEL_PATH = TRAIN_ROOT / "low_capacity_top3_selector_v2_pipeline.joblib"
TRAIN_MANIFEST = TRAIN_ROOT / "train_candidate_manifest.csv"
ENVIRONMENT_MANIFEST = TRAIN_ROOT / "environment_manifest.json"
RESULT_EXPORT = ROOT / "reports" / "failed_buy_root_cause_v1" / "top5_result_export.csv"
FEATURES = ("Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle")
GATES = ("absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass")
AUGUST_DATES = ("20260801", "20260802", "20260808", "20260809", "20260815", "20260816")
PREDICTION_ROOTS = {date: ROOT / "reports" / "buy_improvement_trace_6day_v1" / f"prediction_{date}" for date in AUGUST_DATES}
EXPECTED = {"races": 104, "candidates": 203, "candidate_races": 75}
FROZEN_SHA = {
    "model": "486a2af2c1d3e6426a5031c0bff7e926ccd2154a4d46176b7bd6b6a712820a8c",
    "train_manifest": "16764801c20b99a3c06d4478241c572cb6b78294f30b7bc37c08b08c7f5dc59a",
    "environment": "12c63de76bbed1f4da97bdff115e2f865f05a4846a88c64d7a58717d3a821b02",
}


def fail(code: str) -> None:
    raise RuntimeError(code)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def truth(value: object, field: str, key: str) -> bool:
    if not isinstance(value, bool):
        fail(f"VALIDATION_POPULATION_INTEGRITY_FAILURE:NON_BOOLEAN_{field}:{key}")
    return value


def write_json(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(name: str, rows: list[dict], fields: list[str]) -> None:
    with (OUT / name).open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def pre_outcome_selection() -> tuple[list[dict], dict, list[Path]]:
    rows: list[dict] = []
    races: set[str] = set()
    identities: set[tuple[str, int]] = set()
    candidate_races: set[str] = set()
    paths_all: list[Path] = []
    for date in AUGUST_DATES:
        paths = sorted(PREDICTION_ROOTS[date].glob("race_*_prediction.json"))
        if not paths:
            fail(f"VALIDATION_POPULATION_INTEGRITY_FAILURE:MISSING_PREDICTIONS:{date}")
        paths_all.extend(paths)
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            race_id = str(payload.get("race_id") or "")
            trace = payload.get("buy_gate_trace")
            race = trace.get("race") if isinstance(trace, dict) else None
            horses = trace.get("horses") if isinstance(trace, dict) else None
            if not race_id or race_id in races or not isinstance(race, dict) or not isinstance(horses, list):
                fail(f"VALIDATION_POPULATION_INTEGRITY_FAILURE:TRACE_STRUCTURE:{path}")
            races.add(race_id)
            convergence_state = race.get("shadow_race_state")
            if not isinstance(convergence_state, str):
                fail(f"VALIDATION_POPULATION_INTEGRITY_FAILURE:RACE_STATE:{race_id}")
            for index, horse in enumerate(horses):
                number = horse.get("horse_number")
                key_text = f"{race_id}:{number}"
                if not isinstance(number, int) or (race_id, number) in identities:
                    fail(f"VALIDATION_POPULATION_INTEGRITY_FAILURE:IDENTITY:{key_text}")
                identities.add((race_id, number))
                gate_eligible = all(truth(horse.get(gate), gate, key_text) for gate in GATES)
                candidate = truth(horse.get("shadow_buy_candidate"), "shadow_buy_candidate", key_text)
                if candidate != gate_eligible:
                    fail(f"VALIDATION_POPULATION_INTEGRITY_FAILURE:GATE_EQUIVALENCE:{key_text}")
                if not candidate:
                    continue
                snapshot = horse.get("evaluator_score_snapshot")
                if not isinstance(snapshot, dict):
                    fail(f"VALIDATION_POPULATION_INTEGRITY_FAILURE:FEATURE_SNAPSHOT:{key_text}")
                values = {}
                for feature in FEATURES:
                    value = snapshot.get(feature)
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                        fail(f"VALIDATION_POPULATION_INTEGRITY_FAILURE:FEATURE:{key_text}:{feature}")
                    values[feature] = float(value)
                shadow_rank = horse.get("shadow_ai_rank")
                if isinstance(shadow_rank, bool) or not isinstance(shadow_rank, (int, float)):
                    fail(f"VALIDATION_POPULATION_INTEGRITY_FAILURE:SAFE_SHADOW_RANK:{key_text}")
                rows.append({
                    "date": date, "race_id": race_id, "horse_number": number, "convergence_state": convergence_state,
                    "gate_eligible": True, "current_BUY": truth(horse.get("shadow_buy"), "shadow_buy", key_text),
                    "shadow_ai_rank": float(shadow_rank), "source_artifact_identifier": str(path.relative_to(ROOT)),
                    "source_row_identifier": f"buy_gate_trace.horses[{index}]", **values,
                })
                candidate_races.add(race_id)
    population = {"VALIDATION_PREDICTION_RACES": len(races), "VALIDATION_GATE_ELIGIBLE_CANDIDATES": len(rows),
                  "VALIDATION_RACES_WITH_GE1_ELIGIBLE": len(candidate_races), "unique_prediction_horse_identities": len(identities)}
    if population["VALIDATION_PREDICTION_RACES"] != EXPECTED["races"] or population["VALIDATION_GATE_ELIGIBLE_CANDIDATES"] != EXPECTED["candidates"] or population["VALIDATION_RACES_WITH_GE1_ELIGIBLE"] != EXPECTED["candidate_races"]:
        fail(f"VALIDATION_POPULATION_INTEGRITY_FAILURE:EXPECTED={EXPECTED}:ACTUAL={population}")
    return rows, population, paths_all


def apply_frozen_action(rows: list[dict], pipeline) -> None:
    X = np.asarray([[row[feature] for feature in FEATURES] for row in rows], dtype=float)
    probabilities = pipeline.predict_proba(X)
    if probabilities.shape != (len(rows), 2):
        fail(f"VALIDATION_PRE_FREEZE_FAILURE:PROBABILITY_SHAPE:{probabilities.shape}")
    by_race: dict[str, list[dict]] = defaultdict(list)
    for row, probability in zip(rows, probabilities[:, 1], strict=True):
        row["predicted_top3_probability"] = float(probability)
        row["V2_BUY"] = False
        row["selection_reason"] = "P_LT_0_50"
        by_race[row["race_id"]].append(row)
    for race_id, candidates in by_race.items():
        qualifying = [row for row in candidates if row["predicted_top3_probability"] >= .50]
        ordered = sorted(qualifying, key=lambda row: (-row["predicted_top3_probability"], row["shadow_ai_rank"], row["horse_number"]))
        retained = ordered[:3]
        retained_ids = {id(row) for row in retained}
        for row in qualifying:
            if id(row) in retained_ids:
                row["V2_BUY"] = True
                row["selection_reason"] = "P_GTE_0_50_RETAINED" if len(qualifying) <= 3 else "P_GTE_0_50_TOP3_CAP_RETAINED"
            else:
                row["selection_reason"] = "P_GTE_0_50_BUY_CAP_DROPPED"
        if len(qualifying) > 3 and len(retained) != 3:
            fail(f"VALIDATION_PRE_FREEZE_FAILURE:CAP:{race_id}")


def august_outcomes_after_freeze() -> dict[tuple[str, int], dict]:
    """Decode result fields only after the full selection manifest is frozen."""
    outcomes: dict[tuple[str, int], dict] = {}
    with RESULT_EXPORT.open("rb") as source:
        header = source.readline().decode("utf-8").rstrip("\r\n").split(",")
        required = ["block", "date", "race_id", "rank", "horse_number", "is_buy", "valid_result", "actual_top3", "raw_result"]
        if header != required:
            fail("VALIDATION_RESULT_IDENTITY_FAILURE:HEADER")
        for raw_line in source:
            prefix = raw_line.split(b",", 5)
            if len(prefix) != 6:
                fail("VALIDATION_RESULT_IDENTITY_FAILURE:PREFIX")
            block = prefix[0].decode("utf-8")
            date = prefix[1].decode("utf-8")
            if block != "AUGUST_DEVELOPMENT" or date not in AUGUST_DATES:
                continue
            row = next(csv.DictReader([raw_line.decode("utf-8")], fieldnames=header))
            key = (row["race_id"], int(row["horse_number"]))
            if key in outcomes:
                fail(f"VALIDATION_RESULT_IDENTITY_FAILURE:DUPLICATE:{key}")
            if row["is_buy"] not in {"True", "False"} or row["valid_result"] not in {"True", "False"} or row["actual_top3"] not in {"True", "False"}:
                fail(f"VALIDATION_RESULT_IDENTITY_FAILURE:BOOLEAN:{key}")
            outcomes[key] = {"current_BUY_from_result": row["is_buy"] == "True", "valid_result": row["valid_result"] == "True", "actual_top3": row["actual_top3"] == "True", "date": date}
    return outcomes


def score(rows: list[dict], flag: str) -> dict:
    selected = [row for row in rows if row[flag] and row["valid_result"]]
    correct = sum(row["actual_top3"] for row in selected)
    return {"BUY_positive_races": len({row["race_id"] for row in selected}), "BUY_horses": len(selected), "correct_BUY": correct,
            "BUY_TOP3_RATE": correct / len(selected) if selected else None}


def subgroup(rows: list[dict], state: str) -> dict:
    group = [row for row in rows if row["convergence_state"] == state]
    selected = [row for row in group if row["V2_BUY"] and row["valid_result"]]
    correct = sum(row["actual_top3"] for row in selected)
    return {"eligible_races": len({row["race_id"] for row in group}), "eligible_horses": len(group), "V2_BUY": len(selected),
            "correct_V2_BUY": correct, "V2_BUY_TOP3_RATE": correct / len(selected) if selected else None}


def main() -> None:
    if OUT.exists():
        fail("PROTOCOL_INTEGRITY_FAILURE:OUTPUT_EXISTS")
    OUT.mkdir(parents=True)
    integrity = {"model": sha256(MODEL_PATH), "train_manifest": sha256(TRAIN_MANIFEST), "environment": sha256(ENVIRONMENT_MANIFEST)}
    if integrity != FROZEN_SHA:
        fail(f"MODEL_FREEZE_INTEGRITY_FAILURE:{integrity}")
    write_json("model_freeze_integrity.json", {"status": "PASS", "sha256": integrity, "expected": FROZEN_SHA})

    # Entire population and V2 selection are generated before opening outcome fields.
    rows, population, prediction_paths = pre_outcome_selection()
    pipeline = joblib.load(MODEL_PATH)
    if [name for name, _ in pipeline.steps] != ["scaler", "logistic_regression"]:
        fail("MODEL_FREEZE_INTEGRITY_FAILURE:PIPELINE_STEPS")
    apply_frozen_action(rows, pipeline)
    if len(rows) != 203 or len({row["race_id"] for row in rows}) != 75:
        fail("VALIDATION_PRE_FREEZE_FAILURE:SELECTION_SCOPE")
    fields = ["date", "race_id", "horse_number", "convergence_state", "gate_eligible", *FEATURES,
              "predicted_top3_probability", "V2_BUY", "current_BUY", "shadow_ai_rank", "selection_reason",
              "source_artifact_identifier", "source_row_identifier"]
    write_csv("validation_pre_outcome_manifest.csv", rows, fields)
    pre_sha = sha256(OUT / "validation_pre_outcome_manifest.csv")
    write_json("pre_outcome_freeze.json", {"status": "PASS", "RESULT_ACCESS_BEFORE_VALIDATION_FREEZE": 0,
                                            "candidate_count": len(rows), "eligible_race_count": len({row["race_id"] for row in rows}),
                                            "validation_pre_outcome_manifest_sha256": pre_sha, "MODEL_REFIT": 0})
    write_json("source_model_provenance.json", {
        "model_path": str(MODEL_PATH.relative_to(ROOT)), "train_manifest_path": str(TRAIN_MANIFEST.relative_to(ROOT)),
        "environment_manifest_path": str(ENVIRONMENT_MANIFEST.relative_to(ROOT)), "frozen_sha256": integrity,
        "prediction_artifacts": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in prediction_paths],
        "model_refit": 0, "feature_order": list(FEATURES),
    })

    # Outcome access starts only here.
    outcomes = august_outcomes_after_freeze()
    for row in rows:
        key = (row["race_id"], row["horse_number"])
        outcome = outcomes.get(key)
        if outcome is None or outcome["date"] != row["date"]:
            fail(f"VALIDATION_RESULT_IDENTITY_FAILURE:MISSING_OR_DATE:{key}")
        if outcome["current_BUY_from_result"] != row["current_BUY"]:
            fail(f"CURRENT_BASELINE_REPRODUCTION_FAILURE:BUY_ALIGNMENT:{key}")
        row["valid_result"] = outcome["valid_result"]
        row["actual_top3"] = outcome["actual_top3"]
    current = score(rows, "current_BUY")
    if current != {"BUY_positive_races": 46, "BUY_horses": 71, "correct_BUY": 24, "BUY_TOP3_RATE": 24 / 71}:
        fail(f"CURRENT_BASELINE_REPRODUCTION_FAILURE:{current}")
    v2 = score(rows, "V2_BUY")
    invalid_impact = {"candidate_invalid_result_count": sum(not row["valid_result"] for row in rows),
                      "invalid_current_buy_count": sum((not row["valid_result"]) and row["current_BUY"] for row in rows),
                      "invalid_v2_buy_count": sum((not row["valid_result"]) and row["V2_BUY"] for row in rows)}
    transitions = {
        "CURRENT_BUY_RETAINED": sum(row["current_BUY"] and row["V2_BUY"] for row in rows),
        "CURRENT_BUY_DROPPED": sum(row["current_BUY"] and not row["V2_BUY"] for row in rows),
        "NEW_V2_BUY_FROM_CURRENT_NON_BUY": sum(not row["current_BUY"] and row["V2_BUY"] for row in rows),
        "CORRECT_CURRENT_BUY_RETAINED": sum(row["current_BUY"] and row["V2_BUY"] and row["valid_result"] and row["actual_top3"] for row in rows),
        "CORRECT_CURRENT_BUY_DROPPED": sum(row["current_BUY"] and not row["V2_BUY"] and row["valid_result"] and row["actual_top3"] for row in rows),
        "CORRECT_NEW_V2_BUY": sum(not row["current_BUY"] and row["V2_BUY"] and row["valid_result"] and row["actual_top3"] for row in rows),
        "INCORRECT_CURRENT_BUY_DROPPED": sum(row["current_BUY"] and not row["V2_BUY"] and row["valid_result"] and not row["actual_top3"] for row in rows),
        "INCORRECT_NEW_V2_BUY_ADDED": sum(not row["current_BUY"] and row["V2_BUY"] and row["valid_result"] and not row["actual_top3"] for row in rows),
    }
    date_breakdown = {}
    for date in AUGUST_DATES:
        group = [row for row in rows if row["date"] == date]
        cur, new = score(group, "current_BUY"), score(group, "V2_BUY")
        date_breakdown[date] = {"CURRENT": cur, "V2": new,
                                "difference_pt": None if cur["BUY_TOP3_RATE"] is None or new["BUY_TOP3_RATE"] is None else (new["BUY_TOP3_RATE"] - cur["BUY_TOP3_RATE"]) * 100}
    v2_by_race = Counter(sum(row["V2_BUY"] for row in rows if row["race_id"] == race_id) for race_id in {row["race_id"] for row in rows})
    absolute_change = (v2["BUY_TOP3_RATE"] - current["BUY_TOP3_RATE"]) * 100 if v2["BUY_TOP3_RATE"] is not None else None
    gates = {
        "A_PRIMARY_KPI": absolute_change is not None and absolute_change >= 3.0,
        "B_RACE_OPPORTUNITY_COVERAGE": v2["BUY_positive_races"] >= 46,
        "C_CORRECT_OPPORTUNITY_PRESERVATION": v2["correct_BUY"] >= 24,
        "D_VALIDATION_INTEGRITY": len(rows) == 203 and len({row["race_id"] for row in rows}) == 75,
        "E_GOVERNANCE_INTEGRITY": True,
    }
    decision = "V2_AUGUST_ONE_SHOT_VALIDATION_GO" if all(gates.values()) else "V2_AUGUST_ONE_SHOT_VALIDATION_REJECT"
    outcome_fields = fields + ["valid_result", "actual_top3"]
    write_csv("validation_outcome_join.csv", rows, outcome_fields)
    whole = {"CURRENT": current, "V2": v2, "ABSOLUTE_KPI_CHANGE_PT": absolute_change,
             "V2_BUY_HORSES_PER_203_ELIGIBLE_CANDIDATES": f"{v2['BUY_horses']}/203",
             "mean_V2_BUY_per_eligible_race": v2["BUY_horses"] / 75,
             "eligible_race_v2_buy_count_distribution": {str(i): v2_by_race[i] for i in range(4)}, "invalid_result_impact": invalid_impact}
    write_json("whole_system_metrics.json", whole)
    write_json("mechanism_breakdown.json", {"PLAY_CONVERGED": subgroup(rows, "PLAY_CONVERGED"),
                                               "PLAY_UNCONVERGED_4PLUS": subgroup(rows, "PLAY_UNCONVERGED_4PLUS"),
                                               "other_state_eligible_candidates": sum(row["convergence_state"] not in {"PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS"} for row in rows)})
    write_json("selection_transition_audit.json", transitions)
    write_json("date_breakdown.json", date_breakdown)
    write_json("gate_evaluation.json", {"gates": gates, "decision": decision, "MODEL_REFIT": 0, "MODEL_CHANGE": 0,
                                          "FEATURE_CHANGE": 0, "THRESHOLD_CHANGE": 0, "BUY_ACTION_CHANGE": 0, "GATE_CHANGE": 0,
                                          "CF_CHANGE": 0, "PRODUCTION_CHANGE": 0, "POST_OUTCOME_TUNING": 0})
    summary = {"state": decision, "VALIDATION_POPULATION_REPRODUCTION": "PASS", "population": population,
               "MODEL_FREEZE_INTEGRITY": "PASS", "sha256": integrity, "MODEL_REFIT": 0,
               "ALL_VALIDATION_CANDIDATES_SCORED": "PASS", "ALL_75_ELIGIBLE_RACES_PROCESSED": "PASS",
               "VALIDATION_PRE_OUTCOME_FREEZE": "PASS", "RESULT_ACCESS_BEFORE_VALIDATION_FREEZE": 0,
               "validation_pre_outcome_manifest_sha256": pre_sha, "CURRENT_BASELINE_REPRODUCTION": "PASS",
               "whole_system_metrics": whole, "mechanism_breakdown": {"PLAY_CONVERGED": subgroup(rows, "PLAY_CONVERGED"), "PLAY_UNCONVERGED_4PLUS": subgroup(rows, "PLAY_UNCONVERGED_4PLUS")},
               "selection_transition_audit": transitions, "date_breakdown": date_breakdown, "go_gates": gates,
               "CF_CHANGE": 0, "PRODUCTION_CHANGE": 0, "POST_OUTCOME_TUNING": 0, "alternative_validations": 0}
    write_json("summary.json", summary)
    report = ["# LOW_CAPACITY_TOP3_SELECTOR_V2 — August One-Shot Validation", "", f"Final decision: `{decision}`.", "",
              "## Integrity", "", "- Validation population: PASS (104 races, 203 candidates, 75 candidate races)",
              "- Frozen model / TRAIN manifest / environment SHA: PASS", "- Model refit: 0", "- Result access before validation-selection freeze: 0", "",
              "## Whole-system result", "", f"- Current: {current['correct_BUY']} / {current['BUY_horses']} ({current['BUY_TOP3_RATE']:.4%})",
              f"- V2: {v2['correct_BUY']} / {v2['BUY_horses']} ({v2['BUY_TOP3_RATE']:.4%})", f"- Absolute KPI change: {absolute_change:+.4f}pt", "",
              "## Formal gates", "", *[f"- {name}: {'PASS' if passed else 'FAIL'}" for name, passed in gates.items()], "",
              "No refit, tuning, CF change, or Production change was performed."]
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
