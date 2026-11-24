"""Recover the fixed 111 pair identities from repository-canonical artifacts.

This is a mechanical join only.  It reads the frozen 54-race classification,
its saved Top5 result-label export, and frozen PRE trace snapshots.  It never
opens raw Result files and never runs Prediction.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "race_course_shape_pair_definition_v1"
CLASSIFICATION = ROOT / "reports" / "failed_buy_root_cause_v1" / "failed_buy_classification.csv"
TOP5_EXPORT = ROOT / "reports" / "failed_buy_root_cause_v1" / "top5_result_export.csv"
BLOCK_ROOTS = {
    "JUNE_BLOCK_1": ROOT / "reports" / "h5_temporal_june_block1_v1",
    "JULY_H1": ROOT / "reports" / "cand_h5_001_july_4day_validation_v1",
    "JULY_H2": ROOT / "reports" / "h5_temporal_july_h2_v1",
    "AUGUST_DEVELOPMENT": ROOT / "reports" / "buy_improvement_trace_6day_v1",
}
EVALUATORS = ("Ability", "PastPerformance", "Distance", "LapSuitability", "PaceStyle", "CourseShape", "RaceShape")
EXPECTED_MEANS = {
    "Ability": 0.2072, "PastPerformance": 0.6757, "Distance": -0.8739,
    "LapSuitability": -0.3604, "PaceStyle": 1.8288, "CourseShape": -2.6126,
    "RaceShape": -7.0090,
}
EXPECTED_ROUNDED = {
    "Ability": 0.21, "PastPerformance": 0.68, "Distance": -0.87,
    "LapSuitability": -0.36, "PaceStyle": 1.83, "CourseShape": -2.61,
    "RaceShape": -7.01,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def prediction_path(row: dict) -> Path:
    return BLOCK_ROOTS[row["block"]] / f"prediction_{row['date']}" / f"{row['race_id']}_prediction.json"


def manifest_path(row: dict) -> Path:
    return BLOCK_ROOTS[row["block"]] / f"prediction_{row['date']}" / "prediction_manifest.json"


def load_fixed_population() -> list[dict]:
    rows = [row for row in read_csv(CLASSIFICATION) if row.get("category") == "BUY_SELECTION_FAILURE"]
    if len(rows) != 54 or len({row["race_id"] for row in rows}) != 54:
        raise RuntimeError("PAIR_DEFINITION_RECOVERY_SOURCE_UNRESOLVED:FIXED_54_RACE_POPULATION")
    if set(row["block"] for row in rows) != set(BLOCK_ROOTS):
        raise RuntimeError("PAIR_DEFINITION_RECOVERY_SOURCE_UNRESOLVED:TEMPORAL_BLOCKS")
    return sorted(rows, key=lambda row: (row["date"], row["race_id"]))


def source_hashes(population: list[dict]) -> dict:
    prediction_artifacts = {str(prediction_path(row).relative_to(ROOT)).replace("\\", "/"): sha256(prediction_path(row)) for row in population}
    manifests = {str(manifest_path(row).relative_to(ROOT)).replace("\\", "/"): sha256(manifest_path(row)) for row in population}
    return {
        "classification": sha256(CLASSIFICATION),
        "top5_export": sha256(TOP5_EXPORT),
        "prediction_artifacts": prediction_artifacts,
        "prediction_manifests": manifests,
    }


def frozen_horse_index(population: list[dict]) -> tuple[dict, int, int]:
    result, unresolved, ambiguous = {}, 0, 0
    for population_row in population:
        race_id = population_row["race_id"]
        path = prediction_path(population_row)
        if not path.is_file():
            raise RuntimeError(f"PAIR_DEFINITION_RECOVERY_SOURCE_UNRESOLVED:PREDICTION_ARTIFACT:{race_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        traces = payload.get("buy_gate_trace", {}).get("horses")
        ranked = payload.get("ranked_results")
        if not isinstance(traces, list) or not isinstance(ranked, list):
            raise RuntimeError(f"PAIR_DEFINITION_RECOVERY_SOURCE_UNRESOLVED:TRACE_STRUCTURE:{race_id}")
        trace_by_number, ranked_by_number = {}, {}
        for trace in traces:
            number = str(trace.get("horse_number"))
            if number in trace_by_number:
                ambiguous += 1
            trace_by_number[number] = trace
        for horse in ranked:
            number = str(horse.get("horse_number"))
            if number in ranked_by_number:
                ambiguous += 1
            ranked_by_number[number] = horse
        if set(trace_by_number) != set(ranked_by_number):
            unresolved += len(set(trace_by_number) ^ set(ranked_by_number))
        result[race_id] = {
            number: {"trace": trace, "ranked": ranked_by_number[number]}
            for number, trace in trace_by_number.items() if number in ranked_by_number
        }
    return result, unresolved, ambiguous


def source_rows(population: list[dict]) -> dict[str, list[dict]]:
    targets = {row["race_id"] for row in population}
    rows = [row for row in read_csv(TOP5_EXPORT) if row.get("race_id") in targets]
    by_race = {race_id: [] for race_id in targets}
    for row in rows:
        by_race[row["race_id"]].append(row)
    if set(by_race) != targets or any(not rows for rows in by_race.values()):
        raise RuntimeError("PAIR_DEFINITION_RECOVERY_SOURCE_UNRESOLVED:TOP5_COVERAGE")
    return by_race


def value_bool(row: dict, field: str) -> bool:
    value = row.get(field)
    if value not in {"True", "False"}:
        raise RuntimeError(f"PAIR_DEFINITION_RECOVERY_SOURCE_UNRESOLVED:INVALID_BOOLEAN:{field}:{value}")
    return value == "True"


def build_pairs(population: list[dict], labels: dict[str, list[dict]], horses: dict) -> tuple[list[dict], dict]:
    population_by_race = {row["race_id"]: row for row in population}
    output, unresolved, ambiguous = [], 0, 0
    for race_id in sorted(population_by_race):
        population_row = population_by_race[race_id]
        correct = [row for row in labels[race_id] if not value_bool(row, "is_buy") and value_bool(row, "actual_top3")]
        incorrect = [row for row in labels[race_id] if value_bool(row, "is_buy") and not value_bool(row, "actual_top3")]
        if not correct or not incorrect:
            raise RuntimeError(f"PAIR_DEFINITION_RECOVERY_COUNT_MISMATCH:EMPTY_SIDE:{race_id}")
        for correct_row in correct:
            correct_number = str(correct_row["horse_number"])
            correct_source = horses[race_id].get(correct_number)
            if correct_source is None:
                unresolved += 1
                continue
            for incorrect_row in incorrect:
                incorrect_number = str(incorrect_row["horse_number"])
                incorrect_source = horses[race_id].get(incorrect_number)
                if incorrect_source is None:
                    unresolved += 1
                    continue
                correct_scores = correct_source["trace"].get("evaluator_score_snapshot")
                incorrect_scores = incorrect_source["trace"].get("evaluator_score_snapshot")
                if not isinstance(correct_scores, dict) or not isinstance(incorrect_scores, dict) or any(field not in correct_scores or field not in incorrect_scores for field in EVALUATORS):
                    raise RuntimeError(f"PAIR_DEFINITION_RECOVERY_SOURCE_UNRESOLVED:EVALUATOR_SNAPSHOT:{race_id}")
                pieces = race_id.split("_")
                pair_id = f"{race_id}__correct_{correct_number}__incorrect_{incorrect_number}"
                row = {
                    "pair_id": pair_id,
                    "date": population_row["date"],
                    "temporal_block": population_row["block"],
                    "venue": pieces[-2],
                    "race_number": pieces[-1],
                    "race_id": race_id,
                    "correct_horse_number": correct_number,
                    "correct_horse_name": correct_source["ranked"].get("horse_name"),
                    "correct_registration_id": None,
                    "incorrect_buy_horse_number": incorrect_number,
                    "incorrect_buy_horse_name": incorrect_source["ranked"].get("horse_name"),
                    "incorrect_buy_registration_id": None,
                }
                for field in EVALUATORS:
                    row[f"correct_{field}_score"] = correct_scores[field]
                    row[f"incorrect_{field}_score"] = incorrect_scores[field]
                output.append(row)
    duplicate_pair_id = len(output) - len({row["pair_id"] for row in output})
    if unresolved or ambiguous:
        raise RuntimeError(f"PAIR_DEFINITION_RECOVERY_JOIN_FAILURE:{unresolved}:{ambiguous}")
    return output, {"unresolved_horses": unresolved, "ambiguous_horses": ambiguous, "duplicate_pair_id": duplicate_pair_id}


def fingerprint(pairs: list[dict]) -> dict:
    observed = {}
    for field in EVALUATORS:
        values = [float(row[f"correct_{field}_score"]) - float(row[f"incorrect_{field}_score"]) for row in pairs]
        mean = sum(values) / len(values)
        observed[field] = {
            "mean": mean,
            "rounded": round(mean, 2),
            "expected_mean": EXPECTED_MEANS[field],
            "expected_rounded": EXPECTED_ROUNDED[field],
            "absolute_difference": abs(mean - EXPECTED_MEANS[field]),
            "mean_match": abs(mean - EXPECTED_MEANS[field]) <= 0.0001,
            "rounded_match": round(mean, 2) == EXPECTED_ROUNDED[field],
        }
    return {"evaluators": observed, "all_match": all(item["mean_match"] and item["rounded_match"] for item in observed.values())}


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise RuntimeError("PAIR_DEFINITION_RECOVERY_COUNT_MISMATCH:ZERO_ROWS")
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> str:
    if OUT.exists():
        raise RuntimeError(f"OUTPUT_ROOT_EXISTS:{OUT}")
    population = load_fixed_population()
    before = source_hashes(population)
    labels = source_rows(population)
    horses, structure_unresolved, structure_ambiguous = frozen_horse_index(population)
    if structure_unresolved or structure_ambiguous:
        raise RuntimeError(f"PAIR_DEFINITION_RECOVERY_JOIN_FAILURE:{structure_unresolved}:{structure_ambiguous}")
    pairs, join = build_pairs(population, labels, horses)
    if len(pairs) != 111:
        raise RuntimeError(f"PAIR_DEFINITION_RECOVERY_COUNT_MISMATCH:{len(pairs)}")
    if join["duplicate_pair_id"]:
        raise RuntimeError(f"PAIR_DEFINITION_RECOVERY_JOIN_FAILURE:DUPLICATE_PAIR_ID:{join['duplicate_pair_id']}")
    fingerprints = fingerprint(pairs)
    if not fingerprints["all_match"]:
        raise RuntimeError("PAIR_DEFINITION_RECOVERY_FINGERPRINT_MISMATCH")

    OUT.mkdir(parents=True)
    csv_path = OUT / "pair_definition.csv"
    write_csv(csv_path, pairs)
    after = source_hashes(population)
    source_unchanged = before == after
    if not source_unchanged:
        raise RuntimeError("PAIR_DEFINITION_RECOVERY_SOURCE_MUTATION_DETECTED")
    dump(OUT / "source_provenance.json", {
        "recovery_class": "PAIR_IDENTITY_RECOVERED_FROM_DETERMINISTIC_RULE",
        "provenance_confidence": "HIGH_BUT_INFERENTIAL",
        "claude_scratchpad_used": False,
        "raw_per_race_result_accessed": False,
        "result_usage_boundary": "Existing repository-canonical top5_result_export.csv labels only.",
        "fixed_54_race_source": {"path": str(CLASSIFICATION.relative_to(ROOT)).replace("\\", "/"), "sha256": before["classification"]},
        "post_label_source": {"path": str(TOP5_EXPORT.relative_to(ROOT)).replace("\\", "/"), "sha256": before["top5_export"]},
        "prediction_artifacts": before["prediction_artifacts"],
        "prediction_manifests": before["prediction_manifests"],
        "field_mapping": {
            "race_id": "fixed classification race_id / top5_result_export race_id / frozen artifact race_id",
            "horse_identity": "race_id + horse_number; unique in each frozen artifact and stronger than name-only matching",
            "is_buy": "top5_result_export.is_buy",
            "actual_top3": "top5_result_export.actual_top3",
            "evaluator_score_snapshot": "frozen artifact buy_gate_trace.horses[].evaluator_score_snapshot"
        },
        "source_hashes_unchanged_after_recovery": source_unchanged,
    })
    dump(OUT / "race_population_integrity.json", {
        "expected_race_count": 54, "fixed_race_count": len(population),
        "all_target_races_present": set(labels) == {row["race_id"] for row in population},
        "extra_races": 0, "missing_races": 0,
        "temporal_blocks": sorted({row["block"] for row in population}),
    })
    dump(OUT / "horse_join_integrity.json", {
        "stable_join_method": "race_id + horse_number",
        "registration_id_available": False,
        "unresolved_horses": join["unresolved_horses"],
        "ambiguous_horses": join["ambiguous_horses"],
        "duplicate_pair_id": join["duplicate_pair_id"],
    })
    dump(OUT / "pair_generation_integrity.json", {
        "pairing_rule": "For each fixed race, CartesianProduct(is_buy=False AND actual_top3=True, is_buy=True AND actual_top3=False)",
        "expected_pair_count": 111, "generated_pair_count": len(pairs),
        "independent_race_count": len({row["race_id"] for row in pairs}),
        "no_discretionary_selection": True,
    })
    dump(OUT / "evaluator_fingerprint.json", fingerprints)
    report = "\n".join([
        "# Pair Definition Recovery v1", "",
        "Status: `PAIR_IDENTITY_RECOVERED`.", "",
        "This artifact recovers pair identity by the approved deterministic Cartesian-product rule from repository-canonical saved labels and frozen PRE evaluator snapshots. It makes no mechanism interpretation.", "",
        "- Fixed races: 54", "- Generated pairs: 111", "- Stable join: race_id + horse_number", "- Unresolved / ambiguous: 0 / 0", "- Seven-component fingerprint: PASS", "- Claude scratchpad: not used", "- Raw per-race Result: not accessed", "",
        "Recovery class: `PAIR_IDENTITY_RECOVERED_FROM_DETERMINISTIC_RULE`.",
        "Provenance confidence: `HIGH_BUT_INFERENTIAL`.",
    ]) + "\n"
    (OUT / "report.md").write_text(report, encoding="utf-8")
    files = ["source_provenance.json", "race_population_integrity.json", "horse_join_integrity.json", "pair_generation_integrity.json", "evaluator_fingerprint.json", "pair_definition.csv", "report.md"]
    dump(OUT / "pair_definition_manifest.json", {
        "status": "PAIR_IDENTITY_RECOVERED", "excludes": ["pair_definition_manifest.json"],
        "files": [{"relative_path": name, "sha256": sha256(OUT / name)} for name in files],
        "pair_definition_csv_sha256": sha256(csv_path),
    })
    return "PAIR_IDENTITY_RECOVERED"


if __name__ == "__main__":
    print(main())
