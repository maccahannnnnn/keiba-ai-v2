"""Mechanical trace join for recovered RaceShape/CourseShape pair identities."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "race_course_shape_pair_mechanism_v1_1"
PAIR_ROOT = ROOT / "reports" / "race_course_shape_pair_definition_v1"
REPLAY_ROOT = ROOT / "reports" / "race_course_shape_replay_v1"
PAIR_CSV = PAIR_ROOT / "pair_definition.csv"
PAIR_MANIFEST = PAIR_ROOT / "pair_definition_manifest.json"
REPLAY_MANIFEST = REPLAY_ROOT / "replay_manifest.json"
TRACE_FIELDS = ("pace_prediction", "pace_style", "course_profile_matched", "race_shape_adjustment_id")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader.fieldnames or []), list(reader)


def verify_manifest(root: Path, manifest_path: Path) -> bool:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return all(sha256(root / item["relative_path"]) == item["sha256"] for item in manifest.get("files", []))


def pair_authority() -> tuple[list[str], list[dict]]:
    columns, rows = load_csv(PAIR_CSV)
    if len(rows) != 111 or len({row.get("pair_id") for row in rows}) != 111 or len({row.get("race_id") for row in rows}) != 54:
        raise RuntimeError("PAIR_MECHANISM_INPUT_PAIR_AUTHORITY_INVALID")
    required = {"pair_id", "race_id", "correct_horse_number", "incorrect_buy_horse_number"}
    if not required.issubset(columns):
        raise RuntimeError("PAIR_MECHANISM_INPUT_PAIR_AUTHORITY_INVALID")
    return columns, rows


def trace_index() -> tuple[dict, dict]:
    manifest = json.loads(REPLAY_MANIFEST.read_text(encoding="utf-8"))
    listed = {item["relative_path"] for item in manifest.get("files", [])}
    artifacts = sorted((REPLAY_ROOT / "reproduced_predictions").glob("race_*_prediction.json"))
    index, hashes = {}, {}
    for path in artifacts:
        relative = str(path.relative_to(REPLAY_ROOT)).replace("\\", "/")
        if relative not in listed:
            raise RuntimeError(f"PAIR_MECHANISM_INPUT_INTEGRITY_FAILURE:REPLAY_ARTIFACT_NOT_MANIFESTED:{relative}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        race_id = payload.get("race_id")
        traces = payload.get("buy_gate_trace", {}).get("horses")
        if not isinstance(race_id, str) or not isinstance(traces, list) or race_id in index:
            raise RuntimeError("PAIR_MECHANISM_INPUT_INTEGRITY_FAILURE:TRACE_SOURCE_STRUCTURE")
        by_number = {}
        for trace in traces:
            number = str(trace.get("horse_number"))
            if number in by_number:
                raise RuntimeError(f"PAIR_MECHANISM_INPUT_INTEGRITY_FAILURE:AMBIGUOUS_TRACE:{race_id}:{number}")
            if any(field not in trace for field in TRACE_FIELDS):
                raise RuntimeError(f"PAIR_MECHANISM_INPUT_INTEGRITY_FAILURE:TRACE_FIELD_ABSENT:{race_id}:{number}")
            by_number[number] = trace
        index[race_id] = by_number
        hashes[relative] = sha256(path)
    if len(index) != 54:
        raise RuntimeError(f"PAIR_MECHANISM_INPUT_INTEGRITY_FAILURE:REPLAY_RACE_COUNT:{len(index)}")
    return index, hashes


def trace_flags(value) -> tuple[bool, bool]:
    return value is None, isinstance(value, str) and value == ""


def join_rows(columns: list[str], authority_rows: list[dict], traces: dict) -> tuple[list[str], list[dict], dict]:
    extras = []
    for prefix in ("correct", "incorrect"):
        for field in TRACE_FIELDS:
            extras.extend([f"{prefix}_{field}", f"{prefix}_{field}_is_null", f"{prefix}_{field}_is_empty_string"])
    extras.extend([
        "same_pace_prediction", "same_pace_style", "same_course_profile_matched", "same_race_shape_adjustment_id",
        "RaceShape_score_difference", "CourseShape_score_difference",
    ])
    output, unresolved_correct, unresolved_incorrect = [], 0, 0
    for authority in authority_rows:
        row = dict(authority)
        race_traces = traces.get(authority["race_id"])
        correct = race_traces.get(str(authority["correct_horse_number"])) if race_traces else None
        incorrect = race_traces.get(str(authority["incorrect_buy_horse_number"])) if race_traces else None
        if correct is None:
            unresolved_correct += 1
        if incorrect is None:
            unresolved_incorrect += 1
        if correct is None or incorrect is None:
            continue
        for prefix, trace in (("correct", correct), ("incorrect", incorrect)):
            for field in TRACE_FIELDS:
                value = trace[field]
                is_null, is_empty = trace_flags(value)
                row[f"{prefix}_{field}"] = value
                row[f"{prefix}_{field}_is_null"] = is_null
                row[f"{prefix}_{field}_is_empty_string"] = is_empty
        for field in TRACE_FIELDS:
            row[f"same_{field}"] = correct[field] == incorrect[field]
        row["RaceShape_score_difference"] = float(authority["correct_RaceShape_score"]) - float(authority["incorrect_RaceShape_score"])
        row["CourseShape_score_difference"] = float(authority["correct_CourseShape_score"]) - float(authority["incorrect_CourseShape_score"])
        output.append(row)
    if unresolved_correct or unresolved_incorrect or len(output) != len(authority_rows):
        raise RuntimeError(f"PAIR_MECHANISM_INPUT_INTEGRITY_FAILURE:{unresolved_correct}:{unresolved_incorrect}:{len(output)}")
    return columns + extras, output, {
        "unresolved_correct_horses": unresolved_correct,
        "unresolved_incorrect_horses": unresolved_incorrect,
        "ambiguous_correct_horses": 0,
        "ambiguous_incorrect_horses": 0,
        "duplicate_pair_ids": len(output) - len({row["pair_id"] for row in output}),
    }


def all_trace_completeness(traces: dict) -> dict:
    horses = [horse for by_number in traces.values() for horse in by_number.values()]
    return {
        "reproduced_race_count": len(traces), "reproduced_horse_count": len(horses),
        **{f"{field}_missing_count": sum(horse[field] is None for horse in horses) for field in TRACE_FIELDS},
        "race_shape_adjustment_id_empty_string_count": sum(horse["race_shape_adjustment_id"] == "" for horse in horses),
        "null_and_empty_string_distinguished": True,
    }


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> str:
    if OUT.exists():
        raise RuntimeError(f"OUTPUT_ROOT_EXISTS:{OUT}")
    if not verify_manifest(PAIR_ROOT, PAIR_MANIFEST) or not verify_manifest(REPLAY_ROOT, REPLAY_MANIFEST):
        raise RuntimeError("PAIR_MECHANISM_INPUT_INTEGRITY_FAILURE:SOURCE_MANIFEST_INVALID")
    authority_columns, authority_rows = pair_authority()
    traces, replay_hashes_before = trace_index()
    output_columns, output_rows, integrity = join_rows(authority_columns, authority_rows, traces)
    if integrity["duplicate_pair_ids"]:
        raise RuntimeError("PAIR_MECHANISM_INPUT_INTEGRITY_FAILURE:DUPLICATE_PAIR_ID")
    if len({row["race_id"] for row in output_rows}) != 54:
        raise RuntimeError("PAIR_MECHANISM_INPUT_INTEGRITY_FAILURE:RACE_COUNT")
    OUT.mkdir(parents=True)
    csv_path = OUT / "pair_mechanism_input.csv"
    write_csv(csv_path, output_columns, output_rows)
    replay_hashes_after = {relative: sha256(REPLAY_ROOT / relative) for relative in replay_hashes_before}
    if replay_hashes_before != replay_hashes_after or not verify_manifest(PAIR_ROOT, PAIR_MANIFEST) or not verify_manifest(REPLAY_ROOT, REPLAY_MANIFEST):
        raise RuntimeError("PAIR_MECHANISM_INPUT_INTEGRITY_FAILURE:SOURCE_MUTATION")
    dump(OUT / "source_provenance.json", {
        "pair_authority": "PAIR_IDENTITY_RECOVERED_FROM_DETERMINISTIC_RULE",
        "pair_provenance_confidence": "HIGH_BUT_INFERENTIAL",
        "reproduction_class": "CURRENT_AI_ARTIFACT_REPRODUCTION",
        "evidence_class": "RACE_COURSE_SHAPE_MECHANISM_DEVELOPMENT_EVIDENCE",
        "pair_definition_csv": {"path": str(PAIR_CSV.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(PAIR_CSV)},
        "pair_definition_manifest": {"path": str(PAIR_MANIFEST.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(PAIR_MANIFEST)},
        "reproduction_manifest": {"path": str(REPLAY_MANIFEST.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(REPLAY_MANIFEST)},
        "reproduction_prediction_artifacts": replay_hashes_before,
        "raw_result_access_count": 0,
        "prediction_rerun_count": 0,
    })
    dump(OUT / "pair_authority_integrity.json", {
        "expected_pairs": 111, "authority_pairs": len(authority_rows),
        "expected_races": 54, "authority_races": len({row["race_id"] for row in authority_rows}),
        "duplicate_pair_ids": len(authority_rows) - len({row["pair_id"] for row in authority_rows}),
        "all_original_pair_definition_columns_preserved": output_columns[:len(authority_columns)] == authority_columns,
        "seven_evaluator_components_preserved": all(f"correct_{name}_score" in output_columns and f"incorrect_{name}_score" in output_columns for name in ("Ability", "PastPerformance", "Distance", "LapSuitability", "PaceStyle", "CourseShape", "RaceShape")),
    })
    dump(OUT / "trace_source_integrity.json", all_trace_completeness(traces))
    dump(OUT / "join_integrity.json", {
        "join_key": "race_id + horse_number", "created_pairs": len(output_rows),
        "created_races": len({row["race_id"] for row in output_rows}), **integrity,
        "trace_fields_preserved_exactly": list(TRACE_FIELDS),
        "raw_result_access_count": 0, "prediction_rerun_count": 0,
    })
    report = "\n".join([
        "# Pair Mechanism Input v1.1", "",
        "Status: `PAIR_MECHANISM_INPUT_READY`.", "",
        "This is a mechanical join of the recovered canonical pair authority and CURRENT_AI_ARTIFACT_REPRODUCTION trace values. It contains no mechanism interpretation, score calculation, Prediction rerun, or Result access.", "",
        "- Pairs / races: 111 / 54", "- Join key: race_id + horse_number", "- Unresolved / ambiguous / duplicate: 0 / 0 / 0", "- Raw Result access / Prediction rerun: 0 / 0", "- Null and empty-string states: preserved", "",
        "Next action: `CLAUDE_INDEPENDENT_PAIR_MECHANISM_INPUT_REVIEW`.",
    ]) + "\n"
    (OUT / "report.md").write_text(report, encoding="utf-8")
    files = ["source_provenance.json", "pair_authority_integrity.json", "trace_source_integrity.json", "join_integrity.json", "pair_mechanism_input.csv", "report.md"]
    dump(OUT / "pair_mechanism_input_manifest.json", {
        "status": "PAIR_MECHANISM_INPUT_READY", "excludes": ["pair_mechanism_input_manifest.json"],
        "files": [{"relative_path": name, "sha256": sha256(OUT / name)} for name in files],
        "pair_mechanism_input_csv_sha256": sha256(csv_path),
    })
    return "PAIR_MECHANISM_INPUT_READY"


if __name__ == "__main__":
    print(main())
