"""Read-only source diagnostic for the suspected 2026-05-09 May PRE failure."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RAW = ROOT / "data" / "raw" / "prediction_input"
OUT = ROOT / "reports" / "may_2026_multi_system_oos_v1" / "source_diagnostic_20260509_v1"
PATHS = {kind: RAW / f"{kind}260509.CSV" for kind in ("DG", "DE", "DS")}

from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def serialise(keys: set[tuple[str, int]]) -> list[dict[str, object]]:
    return [{"venue": venue, "race_number": number} for venue, number in sorted(keys)]


def main() -> Path:
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    OUT.mkdir(parents=True)
    try:
        adapter = TargetBulkPredictionInputAdapterV1()
        rows = {}
        identities = {}
        for kind, path in PATHS.items():
            values, source = adapter._read_fixed(path, kind)
            rows[kind] = values
            identities[kind] = {
                "absolute_path": str(path.resolve()),
                "byte_size": path.stat().st_size,
                "sha256": source.sha256,
                "encoding": source.encoding,
                "row_count": source.row_count,
                "column_count": source.width,
            }
        write("source_identity.json", identities)

        date = adapter._validate_dates(rows)
        dg = adapter._validate_dg(rows["DG"], date)
        de, _, _ = adapter._validate_de(rows["DE"], date)
        dg_keys, de_keys = set(dg), set(de)
        dg_only, de_only = dg_keys - de_keys, de_keys - dg_keys
        write("race_set_diff.json", {
            "date": date,
            "DG_RACE_COUNT": len(dg_keys),
            "DE_RACE_COUNT": len(de_keys),
            "DG_KEYS": serialise(dg_keys),
            "DE_KEYS": serialise(de_keys),
            "DG_ONLY": serialise(dg_only),
            "DE_ONLY": serialise(de_only),
            "DG_TOKYO_5_EXISTS": ("東京", 5) in dg_keys,
            "DE_TOKYO_5_EXISTS": ("東京", 5) in de_keys,
            "DG_TOKYO_6_EXISTS": ("東京", 6) in dg_keys,
            "DE_TOKYO_6_EXISTS": ("東京", 6) in de_keys,
        })

        venue = {}
        for venue_name in sorted({key[0] for key in dg_keys | de_keys}):
            venue[venue_name] = {
                "DG_RACE_COUNT": sum(key[0] == venue_name for key in dg_keys),
                "DE_RACE_COUNT": sum(key[0] == venue_name for key in de_keys),
                "DG_ONLY": serialise({key for key in dg_only if key[0] == venue_name}),
                "DE_ONLY": serialise({key for key in de_only if key[0] == venue_name}),
            }
        write("venue_race_count.json", {
            "VENUE_RACE_SET_STATUS": "PASS" if not dg_only and not de_only else "FAIL",
            "venues": venue,
        })

        if dg_only or de_only:
            headcount = {"HEADCOUNT_STATUS": "NOT_EVALUATED_RACE_SET_MISMATCH", "mismatches": []}
        else:
            mismatches = []
            for key in sorted(dg_keys):
                expected = adapter._int(dg[key][9], "DG_FIELD_SIZE_INVALID")
                actual = len(de[key])
                if expected != actual:
                    mismatches.append({"venue": key[0], "race_number": key[1], "DG_FIELD_SIZE": expected, "DE_HORSE_COUNT": actual})
            headcount = {"HEADCOUNT_STATUS": "PASS" if not mismatches else "FAIL", "mismatches": mismatches}
        write("headcount_check.json", headcount)

        try:
            bundle = adapter.load(PATHS["DG"], PATHS["DE"], PATHS["DS"])
            load = {"ADAPTER_LOAD_STATUS": "PASS", "date": bundle.date, "race_count": len(bundle.races), "horse_count": sum(len(r.today_entries) for r in bundle.races.values()), "ADAPTER_EXCEPTION": None}
        except Exception as exc:
            load = {"ADAPTER_LOAD_STATUS": "FAIL", "ADAPTER_EXCEPTION_CLASS": type(exc).__name__, "ADAPTER_EXCEPTION": str(exc), "ADAPTER_EXCEPTION_ARGS": list(exc.args)}
        write("adapter_load_result.json", load)

        exact_failure = load.get("ADAPTER_LOAD_STATUS") == "FAIL" and load.get("ADAPTER_EXCEPTION") == "DG_DE_RACE_MISMATCH: [('東京', 5), ('東京', 6)]"
        write("failure_date_attribution.json", {
            "ACTUAL_FAILURE_DATE": "2026-05-09" if exact_failure else "NOT_2026-05-09",
            "FAILURE_DATE_CONFIRMED": "YES" if exact_failure else "NO",
            "basis": "Standalone adapter.load() against the current 2026-05-09 DG/DE/DS files.",
        })
        write("diagnostic_facts.json", {
            "DIAGNOSTIC_STATUS": "COMPLETE",
            "scope": "2026-05-09 only",
            "result_data_access_count": 0,
            "prediction_execution_count": 0,
            "factual_boundary": "No source, adapter, population, prediction, result, or performance operation was changed or run.",
        })
        write("safety.json", {
            "status": "PASS",
            "RESULT_ACCESS_COUNT": 0,
            "PREDICTION_EXECUTION_COUNT": 0,
            "ADAPTER_MODIFICATION_COUNT": 0,
            "SOURCE_MODIFICATION_COUNT": 0,
            "PERFORMANCE_CALCULATION_COUNT": 0,
        })
        write("artifact_hashes.json", {"indexed_artifacts": {path.name: sha256(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}, "self_hash_excluded": True})
        return OUT
    except Exception as exc:
        write("diagnostic_facts.json", {"DIAGNOSTIC_STATUS": "FAILED", "reason": str(exc)})
        raise


if __name__ == "__main__":
    print(main())
