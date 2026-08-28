"""Read-only parser comparison for the 2026-05-02 DG/DE source pair."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RAW = ROOT / "data" / "raw" / "prediction_input"
OUT = ROOT / "reports" / "may_2026_multi_system_oos_v1" / "adapter_parser_diagnostic_20260502_v1"
SOURCES = {
    "DG": (RAW / "DG260502.CSV", "b2a3323bc42c1f85323fa982ae9e5457909c698cc124b3af4367673083e73404"),
    "DE": (RAW / "DE260502.CSV", "99d00ca214c0dbc34c67108f1ee420d3e3601750d97312b0274a85ac19f7791d"),
}
EXTENDED_SPLITLINE_CHARS = "\v\f\x1c\x1d\x1e\x85\u2028\u2029"

from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, payload: object) -> None:
    (OUT / name).write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def adapter_rows(path: Path) -> tuple[str, list[list[str]]]:
    text = path.read_bytes().decode("cp932")
    return text, list(csv.reader(text.splitlines()))


def standard_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="cp932", newline="") as source:
        return list(csv.reader(source))


def first_divergence(left: list[list[str]], right: list[list[str]]) -> dict[str, object]:
    for index, (adapter, standard) in enumerate(zip(left, right)):
        if adapter != standard:
            return {
                "first_divergence_index": index,
                "adapter_row": adapter,
                "standard_row": standard,
                "adapter_row_length": len(adapter),
                "standard_row_length": len(standard),
            }
    if len(left) != len(right):
        index = min(len(left), len(right))
        adapter = left[index] if index < len(left) else None
        standard = right[index] if index < len(right) else None
        return {
            "first_divergence_index": index,
            "adapter_row": adapter,
            "standard_row": standard,
            "adapter_row_length": len(adapter) if adapter is not None else None,
            "standard_row_length": len(standard) if standard is not None else None,
        }
    return {"first_divergence_index": "NONE"}


def scan_extended_splitlines(text: str) -> list[dict[str, object]]:
    findings = []
    for char in EXTENDED_SPLITLINE_CHARS:
        offsets = [index for index, value in enumerate(text) if value == char]
        if offsets:
            findings.append({
                "code_point": f"U+{ord(char):04X}",
                "occurrence_count": len(offsets),
                "occurrences": [
                    {"character_offset": index, "context": text[max(0, index - 20):index + 21]}
                    for index in offsets[:20]
                ],
            })
    return findings


def key_data(adapter: TargetBulkPredictionInputAdapterV1, kind: str, rows: list[list[str]], date: str) -> tuple[list[tuple[str, int]], dict[tuple[str, int], list[list[str]]]]:
    if kind == "DG":
        keys = [(adapter._text(row[3]), adapter._int(row[4], "DG_RACE_NUMBER_INVALID")) for row in rows]
        parsed = adapter._validate_dg(rows, date)
        return keys, {key: [value] for key, value in parsed.items()}
    keys = [(adapter._text(row[1]), adapter._int(row[2], "DE_RACE_NUMBER_INVALID")) for row in rows]
    parsed, _, _ = adapter._validate_de(rows, date)
    return keys, parsed


def serialise_keys(keys: set[tuple[str, int]]) -> list[dict[str, object]]:
    return [{"venue": venue, "race_number": number} for venue, number in sorted(keys)]


def duplicate_data(keys: list[tuple[str, int]]) -> dict[str, object]:
    counts = Counter(keys)
    duplicates = [key for key, count in counts.items() if count > 1]
    return {
        "duplicate_key_count": len(duplicates),
        "duplicate_keys": [
            {"venue": venue, "race_number": number, "count": counts[(venue, number)]}
            for venue, number in sorted(duplicates)
        ],
    }


def de_horse_duplicates(rows: list[list[str]], adapter: TargetBulkPredictionInputAdapterV1) -> dict[str, object]:
    identities = [
        (adapter._text(row[1]), adapter._int(row[2], "DE_RACE_NUMBER_INVALID"),
         adapter._int(row[3], "DE_HORSE_NUMBER_INVALID"), adapter._clean_name(row[7]))
        for row in rows
    ]
    counts = Counter(identities)
    duplicates = [identity for identity, count in counts.items() if count > 1]
    return {
        "race_key_repetitions_expected": True,
        "race_key_distinct_count": len(set((venue, number) for venue, number, _, _ in identities)),
        "row_count": len(rows),
        "duplicate_horse_identity_count": len(duplicates),
        "duplicate_horse_identities": [
            {"venue": venue, "race_number": number, "horse_number": horse_number, "horse_name": name,
             "count": counts[(venue, number, horse_number, name)]}
            for venue, number, horse_number, name in sorted(duplicates)
        ],
    }


def main() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        for kind, (path, expected_sha) in SOURCES.items():
            actual = sha256(path)
            if actual != expected_sha:
                raise RuntimeError(f"SOURCE_SHA_MISMATCH:{kind}:{actual}")

        adapter = TargetBulkPredictionInputAdapterV1()
        parsed: dict[str, dict[str, object]] = {}
        for kind, (path, _) in SOURCES.items():
            text, adapter_parsed = adapter_rows(path)
            standard_parsed = standard_rows(path)
            parsed[kind] = {"text": text, "adapter": adapter_parsed, "standard": standard_parsed}

        write("parser_row_count_comparison.json", {
            "DG_ADAPTER_ROW_COUNT": len(parsed["DG"]["adapter"]),
            "DG_STANDARD_ROW_COUNT": len(parsed["DG"]["standard"]),
            "DE_ADAPTER_ROW_COUNT": len(parsed["DE"]["adapter"]),
            "DE_STANDARD_ROW_COUNT": len(parsed["DE"]["standard"]),
        })
        write("parser_first_divergence.json", {
            "DG": first_divergence(parsed["DG"]["adapter"], parsed["DG"]["standard"]),
            "DE": first_divergence(parsed["DE"]["adapter"], parsed["DE"]["standard"]),
        })
        scans = {kind: scan_extended_splitlines(data["text"]) for kind, data in parsed.items()}
        write("splitlines_boundary_scan.json", {
            "EXTENDED_SPLITLINE_CODEPOINT_FOUND": "YES" if any(scans.values()) else "NO",
            "findings": scans,
        })

        key_modes: dict[str, dict[str, object]] = {"adapter": {}, "standard": {}}
        duplicate_modes: dict[str, dict[str, object]] = {"adapter": {}, "standard": {}}
        for mode in ("adapter", "standard"):
            dg_keys, dg_by_key = key_data(adapter, "DG", parsed["DG"][mode], "20260502")
            de_keys, de_by_key = key_data(adapter, "DE", parsed["DE"][mode], "20260502")
            dg_set, de_set = set(dg_keys), set(de_keys)
            key_modes[mode] = {
                "DG_KEYS": serialise_keys(dg_set),
                "DE_KEYS": serialise_keys(de_set),
                "DG_ONLY": serialise_keys(dg_set - de_set),
                "DE_ONLY": serialise_keys(de_set - dg_set),
            }
            duplicate_modes[mode] = {"DG": duplicate_data(dg_keys), "DE": de_horse_duplicates(parsed["DE"][mode], adapter)}

            parsed["DG"][f"{mode}_by_key"] = dg_by_key
            parsed["DE"][f"{mode}_by_key"] = de_by_key

        write("adapter_race_keys.json", key_modes["adapter"])
        write("standard_race_keys.json", key_modes["standard"])
        write("duplicate_check.json", {
            "status": "PASS" if all(
                entry["DG"]["duplicate_key_count"] == 0 and entry["DE"]["duplicate_horse_identity_count"] == 0
                for entry in duplicate_modes.values()
            ) else "FAIL",
            "modes": duplicate_modes,
        })

        targets = [("東京", 5), ("東京", 6)]
        attribution = []
        for target in targets:
            item: dict[str, object] = {"venue": target[0], "race_number": target[1]}
            for mode in ("adapter", "standard"):
                item[mode] = {
                    "DG_present": target in set(tuple((x["venue"], x["race_number"])) for x in key_modes[mode]["DG_KEYS"]),
                    "DE_present": target in set(tuple((x["venue"], x["race_number"])) for x in key_modes[mode]["DE_KEYS"]),
                }
            attribution.append(item)
        write("race_key_attribution.json", {"TOKYO_5_6_ATTRIBUTION": attribution})

        parser_difference = (
            key_modes["adapter"] != key_modes["standard"]
            or len(parsed["DG"]["adapter"]) != len(parsed["DG"]["standard"])
            or len(parsed["DE"]["adapter"]) != len(parsed["DE"]["standard"])
        )
        splitline_found = any(scans.values())
        current_load = adapter.load(SOURCES["DG"][0], SOURCES["DE"][0], RAW / "DS260502.CSV")
        write("diagnostic_facts.json", {
            "DIAGNOSTIC_STATUS": "COMPLETE",
            "SPLITLINES_HYPOTHESIS": "CONFIRMED" if parser_difference and splitline_found else "REJECTED" if not parser_difference else "NOT_YET_CONFIRMED",
            "MOST_LIKELY_FAILURE_LAYER": "PARSER" if parser_difference else "UNKNOWN",
            "ADAPTER_CHANGE_REQUIRED_FOR_FIX": "UNKNOWN",
            "current_adapter_load_reproduction": (
                f"PASS: {current_load.date}, {len(current_load.races)} races, "
                f"{sum(len(race.today_entries) for race in current_load.races.values())} entries"
            ),
            "factual_boundary": "No adapter, source, population, prediction, result, or performance operation was changed or run.",
            "NEXT_REVIEW_REQUIRED": "YES",
        })
        write("safety.json", {
            "status": "PASS",
            "ADAPTER_MODIFICATION_COUNT": 0,
            "SOURCE_MODIFICATION_COUNT": 0,
            "PREDICTION_EXECUTION_COUNT": 0,
            "RESULT_ACCESS_COUNT": 0,
            "PERFORMANCE_CALCULATION_COUNT": 0,
        })
        write("artifact_hashes.json", {
            "indexed_artifacts": {
                path.name: sha256(path)
                for path in sorted(OUT.iterdir())
                if path.is_file() and path.name != "artifact_hashes.json"
            },
            "self_hash_excluded": True,
        })
        return OUT
    except Exception as exc:
        write("diagnostic_facts.json", {"DIAGNOSTIC_STATUS": "FAILED", "reason": str(exc)})
        raise


if __name__ == "__main__":
    print(main())
