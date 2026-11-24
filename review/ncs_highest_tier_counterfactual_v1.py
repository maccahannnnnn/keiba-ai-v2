"""Frozen one-shot NCS highest-tier retrospective counterfactual.

This is a read-only analysis runner.  It consumes only frozen Prediction /
trace artifacts and their already-saved BUY outcome rows.  The PRE-only
selection is constructed and integrity-checked before any outcome source is
opened.  It never invokes a prediction engine or writes outside its new,
exclusive report root.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "ncs_highest_tier_counterfactual_v1"
BLOCKS = {
    "JUNE_BLOCK_1": ("20260620", "20260621", "20260627", "20260628"),
    "JULY_H1": ("20260704", "20260705", "20260711", "20260712"),
    "JULY_H2": ("20260718", "20260719", "20260725", "20260726"),
    "AUGUST_DEVELOPMENT": ("20260801", "20260802", "20260808", "20260809", "20260815", "20260816"),
}
PREDICTION_ROOTS = {
    **{d: ROOT / "reports" / "h5_temporal_june_block1_v1" / f"prediction_{d}" for d in BLOCKS["JUNE_BLOCK_1"]},
    **{d: ROOT / "reports" / "cand_h5_001_july_4day_validation_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H1"]},
    **{d: ROOT / "reports" / "h5_temporal_july_h2_v1" / f"prediction_{d}" for d in BLOCKS["JULY_H2"]},
    **{d: ROOT / "reports" / "buy_improvement_trace_6day_v1" / f"prediction_{d}" for d in BLOCKS["AUGUST_DEVELOPMENT"]},
}
RESULT_CSVS = {
    "JUNE_BLOCK_1": ROOT / "reports" / "h5_temporal_june_block1_v1" / "h5_buy_rows.csv",
    "JULY_H1": ROOT / "reports" / "cand_h5_001_july_4day_validation_v1" / "h5_buy_rows.csv",
    "JULY_H2": ROOT / "reports" / "h5_temporal_july_h2_v1" / "h5_buy_rows.csv",
    "AUGUST_DEVELOPMENT": ROOT / "reports" / "buy_improvement_historical_6day_v1" / "buy_success_failure_analysis.csv",
}
EXPECTED = {
    "prediction_races": 307,
    "prediction_horses": 3925,
    "buy_positive_races": 133,
    "buy_horses": 213,
    "correct_buy": 71,
    "buy_count_2_races": 38,
    "buy_count_3_races": 21,
    "multi_buy_races": 59,
    "multi_buy_horses": 139,
    "retained": 169,
    "downgraded": 44,
    "races_with_downgrade": 36,
    "fully_unchanged": 97,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def boolean(value: object) -> bool:
    return value is True or str(value).lower() == "true"


def write_json(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(name: str, rows: list[dict], fieldnames: list[str]) -> None:
    with (OUT / name).open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def fail(code: str) -> None:
    raise RuntimeError(code)


def tier_rows(buys: list[dict]) -> list[dict]:
    """Return frozen contiguous tiers, without any result fields."""
    ordered = sorted(buys, key=lambda row: (-row["net_consensus_score"], row["horse_number"]))
    tier = 1
    prior = None
    for row in ordered:
        if prior is not None and prior - row["net_consensus_score"] >= 1.0:
            tier += 1
        row["ncs_tier"] = tier
        prior = row["net_consensus_score"]
    highest = 1
    for row in ordered:
        row["counterfactual_status"] = "RETAINED_BUY" if row["ncs_tier"] == highest else "COUNTERFACTUAL_NON_BUY"
    return ordered


def build_pre_only() -> tuple[list[dict], dict]:
    """Build and validate the action strictly before opening result sources."""
    all_buys: list[dict] = []
    seen_races: set[str] = set()
    seen_horses: set[tuple[str, int]] = set()
    trace_horses = 0
    source_paths: list[Path] = []
    for block, dates in BLOCKS.items():
        for date in dates:
            paths = sorted(PREDICTION_ROOTS[date].glob("race_*_prediction.json"))
            if not paths:
                fail(f"INPUT_INTEGRITY_FAILURE:MISSING_PREDICTION:{date}")
            source_paths.extend(paths)
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8"))
                race_id = str(payload.get("race_id") or "")
                if not race_id or race_id in seen_races:
                    fail(f"INPUT_INTEGRITY_FAILURE:DUPLICATE_OR_MISSING_RACE:{path}")
                seen_races.add(race_id)
                trace = payload.get("buy_gate_trace")
                ranked = payload.get("ranked_results")
                if not isinstance(trace, dict) or not isinstance(trace.get("horses"), list) or not isinstance(ranked, list):
                    fail(f"INPUT_INTEGRITY_FAILURE:TRACE_OR_RANKING_MISSING:{race_id}")
                trace_by_number: dict[int, float] = {}
                for horse in trace["horses"]:
                    number = horse.get("horse_number")
                    score = horse.get("net_consensus_score")
                    if number is None or not isinstance(score, (int, float)):
                        fail(f"INPUT_INTEGRITY_FAILURE:NCS_MISSING_OR_NON_NUMERIC:{race_id}:{number}")
                    number = int(number)
                    if number in trace_by_number:
                        fail(f"INPUT_INTEGRITY_FAILURE:DUPLICATE_TRACE_KEY:{race_id}:{number}")
                    trace_by_number[number] = float(score)
                trace_horses += len(trace_by_number)
                buy_rows: list[dict] = []
                for horse in ranked:
                    is_buy = horse.get("decision") == "BUY" or boolean(horse.get("buy"))
                    if not is_buy:
                        continue
                    number = horse.get("horse_number")
                    if number is None:
                        fail(f"INPUT_INTEGRITY_FAILURE:BUY_NUMBER_MISSING:{race_id}")
                    number = int(number)
                    key = (race_id, number)
                    if key in seen_horses:
                        fail(f"INPUT_INTEGRITY_FAILURE:DUPLICATE_HORSE_KEY:{race_id}:{number}")
                    seen_horses.add(key)
                    if number not in trace_by_number:
                        fail(f"INPUT_INTEGRITY_FAILURE:BUY_TRACE_MAPPING_MISSING:{race_id}:{number}")
                    buy_rows.append({
                        "date": date, "temporal_block": block, "race_id": race_id,
                        "horse_number": number, "horse_name": horse.get("horse_name") or horse.get("name") or "",
                        "buy_count": int(payload.get("buy_count", 0)),
                        "net_consensus_score": trace_by_number[number],
                    })
                actual_buy_count = len(buy_rows)
                if actual_buy_count != int(payload.get("buy_count", 0)) or actual_buy_count not in (0, 1, 2, 3):
                    fail(f"INPUT_INTEGRITY_FAILURE:BUY_COUNT_MISMATCH:{race_id}")
                if actual_buy_count:
                    all_buys.extend(tier_rows(buy_rows))

    buy_positive_races = {row["race_id"] for row in all_buys}
    counts = Counter(row["buy_count"] for row in all_buys)
    count2_races = len({row["race_id"] for row in all_buys if row["buy_count"] == 2})
    count3_races = len({row["race_id"] for row in all_buys if row["buy_count"] == 3})
    summary = {
        "prediction_races": len(seen_races), "prediction_horses": trace_horses,
        "buy_positive_races": len(buy_positive_races), "buy_horses": len(all_buys),
        "buy_count_2_races": count2_races, "buy_count_3_races": count3_races,
        "multi_buy_races": count2_races + count3_races,
        "multi_buy_horses": counts[2] + counts[3],
        "source_prediction_artifact_count": len(source_paths),
    }
    for key in ("prediction_races", "prediction_horses", "buy_positive_races", "buy_horses", "buy_count_2_races", "buy_count_3_races", "multi_buy_races", "multi_buy_horses"):
        if summary[key] != EXPECTED[key]:
            fail(f"POPULATION_INTEGRITY_FAILURE:{key}:{summary[key]}!={EXPECTED[key]}")

    retained = [row for row in all_buys if row["counterfactual_status"] == "RETAINED_BUY"]
    downgraded = [row for row in all_buys if row["counterfactual_status"] == "COUNTERFACTUAL_NON_BUY"]
    footprint = {
        "TOTAL_BUY_POSITIVE_RACES": len(buy_positive_races), "TOTAL_BUY_HORSES": len(all_buys),
        "RETAINED_BUY_HORSES": len(retained), "DOWNGRADED_BUY_HORSES": len(downgraded),
        "RACES_WITH_AT_LEAST_ONE_DOWNGRADE": len({row["race_id"] for row in downgraded}),
        "RACES_FULLY_UNCHANGED": len(buy_positive_races - {row["race_id"] for row in downgraded}),
        "HORSE_COVERAGE": len(retained) / len(all_buys), "RACE_COVERAGE": len({row["race_id"] for row in retained}) / len(buy_positive_races),
    }
    for key, expected_key in (("RETAINED_BUY_HORSES", "retained"), ("DOWNGRADED_BUY_HORSES", "downgraded"),
                              ("RACES_WITH_AT_LEAST_ONE_DOWNGRADE", "races_with_downgrade"), ("RACES_FULLY_UNCHANGED", "fully_unchanged")):
        if footprint[key] != EXPECTED[expected_key]:
            fail(f"NCS_ACTION_FOOTPRINT_MISMATCH:{key}:{footprint[key]}!={EXPECTED[expected_key]}")
    if abs(footprint["HORSE_COVERAGE"] - 169 / 213) > 1e-12 or footprint["RACE_COVERAGE"] != 1.0:
        fail("NCS_ACTION_FOOTPRINT_MISMATCH:COVERAGE")
    return all_buys, {"population": summary, "footprint": footprint, "sources": source_paths}


def load_outcomes() -> dict[tuple[str, int], dict]:
    """This is the first outcome-accessing function and is called only after freeze."""
    outcomes: dict[tuple[str, int], dict] = {}
    for block, path in RESULT_CSVS.items():
        with path.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                key = (row["race_id"], int(row["horse_number"]))
                if key in outcomes:
                    fail(f"INPUT_INTEGRITY_FAILURE:DUPLICATE_OUTCOME_KEY:{key}")
                outcomes[key] = {"valid_result": boolean(row["valid_result"]), "actual_top3": boolean(row["actual_top3"]), "source_block": block}
    return outcomes


def metrics(rows: list[dict], selected: str) -> dict:
    retained = [row for row in rows if row[selected]]
    correct = sum(row["actual_top3"] for row in retained)
    return {"BUY_POSITIVE_RACES": len({row["race_id"] for row in retained}), "BUY_HORSES": len(retained),
            "CORRECT_BUY": correct, "BUY_TOP3_RATE": correct / len(retained) if retained else None}


def pattern(row: dict) -> str:
    if row["buy_count"] == 2:
        return "BUY_COUNT_2"
    tiers = row["tiers_in_race"]
    sizes = [tiers.count(tier) for tier in sorted(set(tiers))]
    return { (1, 2): "BUY_COUNT_3_PATTERN_B_TOP_SEPARATED_ONLY", (2, 1): "BUY_COUNT_3_PATTERN_C_BOTTOM_SEPARATED_ONLY", (1, 1, 1): "BUY_COUNT_3_PATTERN_D_BOTH_BOUNDARIES" }.get(tuple(sizes), "BUY_COUNT_3_NO_DOWNGRADE")


def main() -> None:
    if OUT.exists():
        fail("OUTPUT_EXISTS")
    OUT.mkdir(parents=True)
    try:
        # Sections 1, 2, 4, and 7: PRE-only. No result source has been opened.
        selection, pre = build_pre_only()
        for row in selection:
            row["tiers_in_race"] = []
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in selection:
            grouped[row["race_id"]].append(row)
        for race_rows in grouped.values():
            tiers = [row["ncs_tier"] for row in race_rows]
            for row in race_rows:
                row["tiers_in_race"] = tiers
                row["downgrade_pattern"] = pattern(row)
        pre_selection = [{key: value for key, value in row.items() if key not in {"actual_top3", "valid_result"}} for row in selection]
        write_json("source_population_pre_only.json", pre["population"])
        write_json("pre_only_footprint.json", pre["footprint"])
        write_csv("ncs_tier_assignment.csv", pre_selection, list(pre_selection[0]))
        write_json("frozen_counterfactual_selection.json", {
            "selection_frozen_before_outcome_access": True,
            "result_data_access_before_freeze": 0,
            "rule": "KEEP_ONLY_HIGHEST_NCS_TIER", "boundary": "adjacent_higher_minus_lower_gte_1.0",
            "formula": "saved net_consensus_score only; no recomputation", "selection_rows": len(selection),
        })

        # Outcome access begins here, after all frozen PRE-only checks have passed.
        outcomes = load_outcomes()
        for row in selection:
            key = (row["race_id"], row["horse_number"])
            if key not in outcomes:
                fail(f"INPUT_INTEGRITY_FAILURE:OUTCOME_MAPPING_MISSING:{key}")
            outcome = outcomes[key]
            if not outcome["valid_result"]:
                fail(f"INPUT_INTEGRITY_FAILURE:UNEXPECTED_INVALID_BUY_OUTCOME:{key}")
            row["valid_result"] = outcome["valid_result"]
            row["actual_top3"] = outcome["actual_top3"]
            row["current_buy"] = True
            row["modified_buy"] = row["counterfactual_status"] == "RETAINED_BUY"

        current = metrics(selection, "current_buy")
        modified = metrics(selection, "modified_buy")
        if current["BUY_HORSES"] != EXPECTED["buy_horses"] or current["CORRECT_BUY"] != EXPECTED["correct_buy"]:
            fail(f"INPUT_INTEGRITY_FAILURE:BASELINE:{current}")
        downgrade = [row for row in selection if not row["modified_buy"]]
        discarded_correct = sum(row["actual_top3"] for row in downgrade)
        temporal = {}
        for block in BLOCKS:
            rows = [row for row in selection if row["temporal_block"] == block]
            block_current = metrics(rows, "current_buy")
            block_modified = metrics(rows, "modified_buy")
            temporal[block] = {"CURRENT": block_current, "MODIFIED": block_modified,
                               "BLOCK_KPI_CHANGE_PT": (block_modified["BUY_TOP3_RATE"] - block_current["BUY_TOP3_RATE"]) * 100}
        breakdown = {}
        for category in ("BUY_COUNT_2", "BUY_COUNT_3_PATTERN_B_TOP_SEPARATED_ONLY", "BUY_COUNT_3_PATTERN_C_BOTTOM_SEPARATED_ONLY", "BUY_COUNT_3_PATTERN_D_BOTH_BOUNDARIES"):
            rows = [row for row in downgrade if row["downgrade_pattern"] == category]
            breakdown[category] = {"downgraded_buy_horses": len(rows), "discarded_correct_buy": sum(row["actual_top3"] for row in rows),
                                   "independent_races": len({row["race_id"] for row in rows})}
        result = {
            "CURRENT": current, "MODIFIED": modified,
            "ABSOLUTE_KPI_CHANGE_PT": (modified["BUY_TOP3_RATE"] - current["BUY_TOP3_RATE"]) * 100,
            "RACE_COVERAGE": pre["footprint"]["RACE_COVERAGE"], "HORSE_COVERAGE": pre["footprint"]["HORSE_COVERAGE"],
            "DOWNGRADED_BUY_HORSES": len(downgrade), "DISCARDED_CORRECT_BUY": discarded_correct,
            "DISCARDED_CORRECT_SHARE": discarded_correct / EXPECTED["correct_buy"],
        }
        gates = {
            "A_WHOLE_SYSTEM_EFFECT": result["ABSOLUTE_KPI_CHANGE_PT"] >= 3.0,
            "B_HORSE_COVERAGE": result["HORSE_COVERAGE"] >= .70,
            "C_RACE_COVERAGE": result["RACE_COVERAGE"] >= .95,
            "D_CORRECT_BUY_LOSS": result["DISCARDED_CORRECT_SHARE"] < .10,
            "E_TEMPORAL_STABILITY": sum(v["BLOCK_KPI_CHANGE_PT"] > 0 for v in temporal.values()) >= 3 and all(v["BLOCK_KPI_CHANGE_PT"] > -3.0 for v in temporal.values()),
        }
        decision = "NCS_TIER_COUNTERFACTUAL_GO" if all(gates.values()) else "NCS_TIER_COUNTERFACTUAL_REJECT"
        write_csv("outcome_join.csv", selection, list(selection[0]))
        write_json("whole_system_metrics.json", result)
        write_json("temporal_metrics.json", temporal)
        write_json("downgrade_breakdown.json", breakdown)
        write_json("go_gate.json", {"gates": gates, "decision": decision})
        summary = {
            "status": decision, "baseline_reproduction": "PASS", "identity_integrity": "PASS",
            "population_reproduction": "PASS", "pre_only_footprint_reproduction": "PASS",
            "result_data_access_before_freeze": 0, "protocol_integrity_issue": "NO",
            "metrics": result, "temporal": temporal, "downgrade_breakdown": breakdown, "go_gates": gates,
            "production_changes": 0, "cf_changes": 0, "threshold_tuning": False, "alternative_rule_evaluations": 0,
        }
        write_json("summary.json", summary)
        sources = [*pre["sources"], *RESULT_CSVS.values()]
        manifest = {"schema_version": "NCS_HIGHEST_TIER_COUNTERFACTUAL_V1", "generated_at": datetime.now(timezone.utc).isoformat(),
                    "source_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in sources},
                    "artifacts": {path.name: sha256(path) for path in sorted(OUT.iterdir()) if path.is_file()}}
        write_json("manifest.json", manifest)
        lines = [
            "# NCS Highest-Tier BUY Selection V1", "",
            f"Final decision: `{decision}`.", "",
            "## Frozen pre-outcome checks", "",
            "- Baseline / identity / population / footprint reproduction: PASS",
            "- Result-data access before selection freeze: 0",
            f"- Frozen action: retained {pre['footprint']['RETAINED_BUY_HORSES']} / {pre['footprint']['TOTAL_BUY_HORSES']}; downgraded {pre['footprint']['DOWNGRADED_BUY_HORSES']}", "",
            "## Outcome metrics", "",
            f"- Current: {current['CORRECT_BUY']} / {current['BUY_HORSES']} ({current['BUY_TOP3_RATE']:.4%})",
            f"- Modified: {modified['CORRECT_BUY']} / {modified['BUY_HORSES']} ({modified['BUY_TOP3_RATE']:.4%})",
            f"- Absolute KPI change: {result['ABSOLUTE_KPI_CHANGE_PT']:+.4f}pt",
            f"- Discarded correct BUY: {discarded_correct} / 71 ({result['DISCARDED_CORRECT_SHARE']:.4%})", "",
            "## Frozen GO gates", "",
            *[f"- {name}: {'PASS' if passed else 'FAIL'}" for name, passed in gates.items()], "",
            "No Production, CF, threshold, or alternative-rule change was made.",
        ]
        (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        # Preserve a stopped run only if no outcome source was reached; avoid partial outcome artifacts.
        raise


if __name__ == "__main__":
    main()
