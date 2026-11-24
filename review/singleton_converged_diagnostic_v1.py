"""Bounded historical outcome diagnostic for existing singleton CONVERGED BUYs.

The runner reconstructs the specified 18-date population exclusively from
frozen PRE prediction artifacts.  It writes and hashes the complete primary
PRE manifest before opening the already-existing result export.  It neither
predicts, trains, scores, nor changes any KeibaAI rule.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "singleton_converged_diagnostic_v1"
RESULT_EXPORT = ROOT / "reports" / "failed_buy_root_cause_v1" / "top5_result_export.csv"
GATES = ("absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass")
BLOCKS = {
    "JUNE": ("20260620", "20260621", "20260627", "20260628"),
    "JULY_H1": ("20260704", "20260705", "20260711", "20260712"),
    "JULY_H2": ("20260718", "20260719", "20260725", "20260726"),
    "AUGUST": ("20260801", "20260802", "20260808", "20260809", "20260815", "20260816"),
}
PREDICTION_ROOTS = {
    **{d: ROOT / "reports" / "h5_temporal_june_block1_v1" / f"prediction_{d}" for d in BLOCKS["JUNE"]},
    **{d: ROOT / "reports" / "cand_h5_001_july_4day_validation_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H1"]},
    **{d: ROOT / "reports" / "h5_temporal_july_h2_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H2"]},
    **{d: ROOT / "reports" / "buy_improvement_trace_6day_v1" / f"prediction_{d}" for d in BLOCKS["AUGUST"]},
}
EXPECTED_SINGLETON_RACES = 74
EXPECTED_SECONDARY_RACES = {2: 38, 3: 21}
RESULT_HEADER = ["block", "date", "race_id", "rank", "horse_number", "is_buy", "valid_result", "actual_top3", "raw_result"]


def fail(code: str) -> None:
    raise RuntimeError(code)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name: str, value: object) -> Path:
    path = OUT / name
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def write_csv(name: str, rows: list[dict], fields: list[str]) -> Path:
    path = OUT / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    return path


def truth(value: object, field: str, key: str) -> bool:
    if not isinstance(value, bool):
        fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:NON_BOOLEAN_{field}:{key}")
    return value


def block_for(date: str) -> str:
    for block, dates in BLOCKS.items():
        if date in dates:
            return block
    fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:UNEXPECTED_DATE:{date}")


def pre_outcome_population() -> tuple[list[dict], list[dict], dict, list[dict]]:
    """Read frozen prediction/trace artifacts only; never read outcome sources."""
    primary: list[dict] = []
    secondary: list[dict] = []
    source_artifacts: list[dict] = []
    singleton_races: set[str] = set()
    all_races: set[str] = set()
    seen_ids: set[tuple[str, int]] = set()
    counts_by_block: dict[str, int] = {block: 0 for block in BLOCKS}
    secondary_races: dict[int, set[str]] = {2: set(), 3: set()}

    for date, root in PREDICTION_ROOTS.items():
        paths = sorted(root.glob("race_*_prediction.json"))
        if not paths:
            fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:MISSING_PREDICTION_ARTIFACTS:{date}")
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            race_id = payload.get("race_id")
            trace = payload.get("buy_gate_trace")
            race = trace.get("race") if isinstance(trace, dict) else None
            horses = trace.get("horses") if isinstance(trace, dict) else None
            ranked = payload.get("ranked_results")
            if not isinstance(race_id, str) or race_id in all_races or not isinstance(race, dict) or not isinstance(horses, list) or not isinstance(ranked, list):
                fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:TRACE_STRUCTURE:{path}")
            all_races.add(race_id)
            if race.get("shadow_race_state") != "PLAY_CONVERGED":
                continue

            ranked_by_number: dict[int, dict] = {}
            for item in ranked:
                number = item.get("horse_number")
                if not isinstance(number, int) or number in ranked_by_number:
                    fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:RANKED_IDENTITY:{race_id}:{number}")
                ranked_by_number[number] = item

            candidates: list[tuple[int, dict, dict]] = []
            comparators: list[tuple[int, dict, dict]] = []
            for index, horse in enumerate(horses):
                number = horse.get("horse_number")
                key = f"{race_id}:{number}"
                if not isinstance(number, int) or (race_id, number) in seen_ids or number not in ranked_by_number:
                    fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:HORSE_IDENTITY:{key}")
                seen_ids.add((race_id, number))
                gate_pass = all(truth(horse.get(gate), gate, key) for gate in GATES)
                candidate = truth(horse.get("shadow_buy_candidate"), "shadow_buy_candidate", key)
                current_buy = truth(horse.get("shadow_buy"), "shadow_buy", key)
                if candidate != gate_pass:
                    fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:GATE_EQUIVALENCE:{key}")
                result = ranked_by_number[number]
                rank = horse.get("shadow_ai_rank")
                if isinstance(rank, bool) or not isinstance(rank, (int, float)):
                    fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:SAFE_SHADOW_RANK:{key}")
                if candidate:
                    candidates.append((index, horse, result))
                elif float(rank) <= 5:
                    comparators.append((index, horse, result))

            candidate_count = len(candidates)
            if candidate_count == 1:
                if len(candidates) != 1 or not truth(candidates[0][1].get("shadow_buy"), "shadow_buy", f"{race_id}:{candidates[0][1].get('horse_number')}"):
                    fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:CURRENT_BUY_SEMANTICS:{race_id}")
                if not comparators:
                    fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:NO_SAME_RACE_COMPARATOR:{race_id}")
                singleton_races.add(race_id)
                block = block_for(date)
                counts_by_block[block] += 1
                for role, values in (("SINGLETON_BUY", candidates), ("GATE_FAILED_TOP5_COMPARATOR", comparators)):
                    for index, horse, result in values:
                        number = horse["horse_number"]
                        primary.append({
                            "date": date,
                            "temporal_block": block,
                            "race_id": race_id,
                            "horse_number": number,
                            "horse_name": result.get("horse_name"),
                            "registration_id": result.get("registration_id"),
                            "role": role,
                            "shadow_buy_candidate": bool(horse["shadow_buy_candidate"]),
                            "current_buy": bool(horse["shadow_buy"]),
                            "shadow_ai_rank": float(horse["shadow_ai_rank"]),
                            "source_artifact_identifier": str(path.relative_to(ROOT)),
                            "source_row_identifier": f"buy_gate_trace.horses[{index}]",
                        })
            if candidate_count in secondary_races:
                secondary_races[candidate_count].add(race_id)
                for index, horse, result in candidates:
                    secondary.append({
                        "date": date,
                        "temporal_block": block_for(date),
                        "race_id": race_id,
                        "horse_number": horse["horse_number"],
                        "horse_name": result.get("horse_name"),
                        "current_buy": bool(horse["shadow_buy"]),
                        "candidate_count": candidate_count,
                        "source_artifact_identifier": str(path.relative_to(ROOT)),
                        "source_row_identifier": f"buy_gate_trace.horses[{index}]",
                    })
            source_artifacts.append({"path": str(path.relative_to(ROOT)), "sha256": sha256(path)})

    if len(singleton_races) != EXPECTED_SINGLETON_RACES:
        fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:EXPECTED_SINGLETON_RACES={EXPECTED_SINGLETON_RACES}:ACTUAL={len(singleton_races)}")
    for count, expected in EXPECTED_SECONDARY_RACES.items():
        actual = len(secondary_races[count])
        if actual != expected:
            fail(f"SINGLETON_POPULATION_INTEGRITY_FAILURE:EXPECTED_BUY_COUNT_{count}_RACES={expected}:ACTUAL={actual}")
    if sum(row["role"] == "SINGLETON_BUY" for row in primary) != EXPECTED_SINGLETON_RACES:
        fail("SINGLETON_POPULATION_INTEGRITY_FAILURE:SINGLETON_HORSE_COUNT")
    pre_summary = {
        "SINGLETON_CONVERGED_RACES": len(singleton_races),
        "singleton_race_counts_by_block": counts_by_block,
        "primary_manifest_rows": len(primary),
        "singleton_buy_rows": sum(row["role"] == "SINGLETON_BUY" for row in primary),
        "comparator_rows": sum(row["role"] == "GATE_FAILED_TOP5_COMPARATOR" for row in primary),
        "secondary_race_counts": {str(key): len(value) for key, value in secondary_races.items()},
        "historical_prediction_race_count": len(all_races),
    }
    return primary, secondary, pre_summary, source_artifacts


def outcomes_after_pre_freeze() -> dict[tuple[str, int], dict]:
    """Read only the pre-existing top5 result export after PRE manifest freeze."""
    outcomes: dict[tuple[str, int], dict] = {}
    with RESULT_EXPORT.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != RESULT_HEADER:
            fail("RESULT_IDENTITY_FAILURE:RESULT_EXPORT_HEADER")
        for row in reader:
            date = row.get("date")
            if date not in PREDICTION_ROOTS:
                continue
            number_text = row.get("horse_number")
            if number_text is None or not number_text.isdigit():
                fail(f"RESULT_IDENTITY_FAILURE:HORSE_NUMBER:{row}")
            key = (str(row.get("race_id")), int(number_text))
            if key in outcomes:
                fail(f"RESULT_IDENTITY_FAILURE:DUPLICATE:{key}")
            if row.get("is_buy") not in {"True", "False"} or row.get("valid_result") not in {"True", "False"} or row.get("actual_top3") not in {"True", "False"}:
                fail(f"RESULT_IDENTITY_FAILURE:BOOLEAN_SEMANTICS:{key}")
            outcomes[key] = {
                "date": date,
                "valid_result": row["valid_result"] == "True",
                "actual_top3": row["actual_top3"] == "True",
                "current_buy_from_result": row["is_buy"] == "True",
                "raw_result": row["raw_result"],
            }
    return outcomes


def rate(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"]]
    top3 = sum(row["actual_top3"] for row in valid)
    return {"valid_horses": len(valid), "top3_true": top3, "top3_rate": top3 / len(valid) if valid else None,
            "invalid_result_excluded": len(rows) - len(valid)}


def run() -> None:
    if OUT.exists():
        fail("PROTOCOL_INTEGRITY_FAILURE:OUTPUT_EXISTS")
    OUT.mkdir(parents=True)

    # PRE-only stage.  No result source is opened by any function above.
    primary, secondary, pre_summary, artifacts = pre_outcome_population()
    pre_fields = ["date", "temporal_block", "race_id", "horse_number", "horse_name", "registration_id", "role", "shadow_buy_candidate", "current_buy", "shadow_ai_rank", "source_artifact_identifier", "source_row_identifier"]
    pre_path = write_csv("singleton_converged_pre_outcome_manifest.csv", primary, pre_fields)
    pre_sha = sha256(pre_path)
    write_json("pre_outcome_freeze.json", {
        "status": "PASS", "SINGLETON_CONVERGED_RACES": pre_summary["SINGLETON_CONVERGED_RACES"],
        "RESULT_ACCESS_BEFORE_PRE_FREEZE": 0, "pre_manifest_path": str(pre_path.relative_to(ROOT)),
        "pre_manifest_sha256": pre_sha,
    })
    write_json("source_provenance.json", {
        "historical_dates": {block: list(dates) for block, dates in BLOCKS.items()},
        "prediction_artifact_count": len(artifacts), "prediction_artifacts": artifacts,
        "result_export_path": str(RESULT_EXPORT.relative_to(ROOT)),
        "result_export_access": "AFTER_PRE_OUTCOME_FREEZE_ONLY",
        "result_access_before_pre_freeze": 0,
        "V3_CHANGE": 0, "CF_CHANGE": 0, "PRODUCTION_CHANGE": 0, "MODEL_CHANGE": 0, "GATE_CHANGE": 0,
    })

    # Outcome stage begins only after the PRE file and its hash exist.
    outcomes = outcomes_after_pre_freeze()
    joined: list[dict] = []
    for row in primary:
        key = (row["race_id"], row["horse_number"])
        outcome = outcomes.get(key)
        if outcome is None or outcome["date"] != row["date"]:
            fail(f"RESULT_IDENTITY_FAILURE:MISSING_OR_DATE:{key}")
        if row["role"] == "SINGLETON_BUY" and outcome["current_buy_from_result"] != row["current_buy"]:
            fail(f"RESULT_IDENTITY_FAILURE:CURRENT_BUY_ALIGNMENT:{key}")
        joined.append({**row, "valid_result": outcome["valid_result"], "actual_top3": outcome["actual_top3"], "raw_result": outcome["raw_result"]})
    join_fields = pre_fields + ["valid_result", "actual_top3", "raw_result"]
    write_csv("singleton_converged_outcome_join.csv", joined, join_fields)

    singleton = [row for row in joined if row["role"] == "SINGLETON_BUY"]
    comparator = [row for row in joined if row["role"] == "GATE_FAILED_TOP5_COMPARATOR"]
    singleton_metrics, comparator_metrics = rate(singleton), rate(comparator)
    lift = None if singleton_metrics["top3_rate"] is None or comparator_metrics["top3_rate"] is None else singleton_metrics["top3_rate"] - comparator_metrics["top3_rate"]
    pooled = {
        "SINGLETON_BUY": singleton_metrics, "COMPARATOR": comparator_metrics,
        "SINGLETON_SELECTION_LIFT": lift,
        "independent_singleton_race_count": EXPECTED_SINGLETON_RACES,
        "POOLED_EVIDENCE_BAND": "STRONG_RETROSPECTIVE_EVIDENCE",
    }
    write_json("pooled_metrics.json", pooled)

    temporal: dict[str, dict] = {}
    n_plus = n_minus = 0
    formal_blocks: list[str] = []
    too_small: list[str] = []
    for block in BLOCKS:
        block_singleton = [row for row in singleton if row["temporal_block"] == block]
        block_comparator = [row for row in comparator if row["temporal_block"] == block]
        s, c = rate(block_singleton), rate(block_comparator)
        block_lift = None if s["top3_rate"] is None or c["top3_rate"] is None else s["top3_rate"] - c["top3_rate"]
        eligible = len({row["race_id"] for row in block_singleton}) >= 10
        if eligible:
            formal_blocks.append(block)
            if block_lift is not None and block_lift > 0:
                n_plus += 1
            elif block_lift is not None and block_lift < 0:
                n_minus += 1
        else:
            too_small.append(block)
        temporal[block] = {
            "singleton_race_count": len({row["race_id"] for row in block_singleton}),
            "Evidence_Band": "FORMAL_SIGN_ELIGIBLE" if eligible else "TOO_SMALL",
            "SINGLETON_BUY": s, "COMPARATOR": c, "BLOCK_SINGLETON_SELECTION_LIFT": block_lift,
        }
    temporal["formal_sign_summary"] = {"N_PLUS": n_plus, "N_MINUS": n_minus, "FORMAL_SIGN_ELIGIBLE_BLOCKS": formal_blocks, "TOO_SMALL_BLOCKS": too_small}
    write_json("temporal_block_metrics.json", temporal)

    secondary_rows: dict[int, list[dict]] = defaultdict(list)
    for row in secondary:
        key = (row["race_id"], row["horse_number"])
        outcome = outcomes.get(key)
        if outcome is None or outcome["date"] != row["date"]:
            fail(f"RESULT_IDENTITY_FAILURE:SECONDARY_MISSING_OR_DATE:{key}")
        if outcome["current_buy_from_result"] != row["current_buy"]:
            fail(f"RESULT_IDENTITY_FAILURE:SECONDARY_BUY_ALIGNMENT:{key}")
        secondary_rows[row["candidate_count"]].append({**row, "valid_result": outcome["valid_result"], "actual_top3": outcome["actual_top3"]})
    secondary_metrics = {}
    for count in (2, 3):
        rows = secondary_rows[count]
        buy_rows = [row for row in rows if row["current_buy"]]
        metrics = rate(buy_rows)
        secondary_metrics[f"BUY_COUNT_{count}"] = {
            "race_count": len({row["race_id"] for row in rows}), "valid_BUY_horse_count": metrics["valid_horses"],
            "BUY_Top3_true": metrics["top3_true"], "BUY_TOP3_RATE": metrics["top3_rate"],
            "invalid_BUY_excluded_count": metrics["invalid_result_excluded"], "descriptive_only": True,
        }
    write_json("secondary_buy_count_2_3_metrics.json", secondary_metrics)

    if lift is not None and lift > 0 and n_minus == 0:
        classification, final_state = "A", "CURRENT_CONVERGED_REVIEW_CLOSE"
    elif lift is not None and lift <= 0 and n_plus == 0:
        classification, final_state = "B", "SINGLETON_ABSOLUTE_BUY_QUALIFICATION_REVIEW_REQUIRED"
    else:
        classification, final_state = "C", "SINGLETON_DIRECTION_TEMPORALLY_UNSTABLE"
    classification_data = {"FORMAL_CLASSIFICATION": classification, "FINAL_STATE": final_state, "N_PLUS": n_plus, "N_MINUS": n_minus,
                           "pooled_lift_sign": "P_POSITIVE" if lift is not None and lift > 0 else "P_NONPOSITIVE",
                           "classification_rule": "A/B/C only; mutually exclusive and collectively exhaustive"}
    write_json("classification.json", classification_data)

    summary = {
        "state": final_state, "SINGLETON_POPULATION_REPRODUCTION": "PASS", **pre_summary,
        "PRE_OUTCOME_FREEZE": "PASS", "RESULT_ACCESS_BEFORE_PRE_FREEZE": 0,
        "PRE_MANIFEST_PATH": str(pre_path.relative_to(ROOT)), "PRE_MANIFEST_SHA256": pre_sha,
        "POOLED_METRICS": pooled, "TEMPORAL_BLOCKS": temporal, "SECONDARY": secondary_metrics,
        "CLASSIFICATION": classification_data,
        "V3_CHANGE": 0, "CF_CHANGE": 0, "PRODUCTION_CHANGE": 0, "MODEL_CHANGE": 0, "GATE_CHANGE": 0, "POST_OUTCOME_TUNING": 0,
        "formal_label": "HISTORICAL_OUTCOME_DIAGNOSTIC",
    }
    summary_path = write_json("summary.json", summary)
    summary_sha = sha256(summary_path)
    report = "\n".join([
        "# Singleton CONVERGED Diagnostic v1", "",
        f"Final state: `{final_state}` (formal classification `{classification}`).", "",
        "## Population and freeze", "",
        f"- Singleton CONVERGED races: {EXPECTED_SINGLETON_RACES}",
        f"- PRE manifest SHA256: `{pre_sha}`", "- Result access before PRE freeze: 0", "",
        "## Pooled diagnostic", "",
        f"- Singleton BUY: {singleton_metrics['top3_true']} / {singleton_metrics['valid_horses']} ({singleton_metrics['top3_rate']:.4%})",
        f"- Same-race Gate-failed Top5 comparator: {comparator_metrics['top3_true']} / {comparator_metrics['valid_horses']} ({comparator_metrics['top3_rate']:.4%})",
        f"- Singleton selection lift: {lift:+.4%}", "",
        "## Guardrails", "",
        "- This is a bounded historical outcome diagnostic of existing CONVERGED BUY semantics.",
        "- No V3/CF/Production/model/Gate change or post-outcome tuning was performed.",
        "- Secondary BUY-count 2/3 metrics are descriptive only and do not affect A/B/C.",
    ]) + "\n"
    report_path = OUT / "report.md"
    report_path.write_text(report, encoding="utf-8")
    write_json("artifact_hashes.json", {"pre_manifest_sha256": pre_sha, "summary_sha256": summary_sha, "report_sha256": sha256(report_path)})


if __name__ == "__main__":
    run()
