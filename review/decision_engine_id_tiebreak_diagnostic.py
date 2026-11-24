"""Non-gating diagnostic for the known DecisionEngine id(row) nondeterminism."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "prediction_input"
KNOWN_RACES = (
    ("260627", "race_20260627_hakodate_7R"),
    ("260628", "race_20260628_fukushima_9R"),
    ("260816", "race_20260816_sapporo_10R"),
)


def _fingerprint(output: dict) -> str:
    """Fingerprint only the five previously-approved nondeterministic fields."""

    fields = []
    for row in output.get("ranked_results", []):
        diagnostics = row.get("decision_diagnostics") or {}
        trace = diagnostics.get("decision_trace") or []
        decision_result = row.get("decision_result") or {}
        nested = decision_result.get("decision_diagnostics") or {}
        fields.append({
            "diagnostics_ai_rank": diagnostics.get("ai_rank"),
            "trace_2_value": trace[2].get("value") if len(trace) > 2 and isinstance(trace[2], dict) else None,
            "trace_10_ai_rank": trace[10].get("ai_rank") if len(trace) > 10 and isinstance(trace[10], dict) else None,
            "decision_result_ai_rank": decision_result.get("ai_rank"),
            "decision_result_diagnostics_ai_rank": nested.get("ai_rank"),
        })
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def run_diagnostic(run_count: int = 20) -> dict:
    """Read frozen prediction input only; never gate a test outcome on manifestation."""

    if run_count < 1:
        raise ValueError("run_count must be positive")
    results = []
    for date, race_id in KNOWN_RACES:
        fingerprints = set()
        for _ in range(run_count):
            bundle = TargetBulkPredictionInputAdapterV1().load(
                RAW / f"DG{date}.CSV", RAW / f"DE{date}.CSV", RAW / f"DS{date}.CSV"
            )
            fingerprints.add(_fingerprint(run_new(race_id, bundle.races[race_id])))
        results.append({
            "race_id": race_id,
            "runs": run_count,
            "distinct_fingerprint_count": len(fingerprints),
            "status": "NONDETERMINISM_REPRODUCED" if len(fingerprints) >= 2 else "NONDETERMINISM_NOT_OBSERVED_IN_THIS_RUN",
        })
    return {"diagnostic": "PRE_EXISTING_PREDICTION_NONDETERMINISM", "gating": False, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(run_diagnostic(args.runs), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
