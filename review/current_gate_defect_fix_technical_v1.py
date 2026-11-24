"""Result-free technical comparison of the four A1/A2 configurations.

This is a development diagnostic, not a formal PRE or performance evaluation.
It reads only official prediction inputs and frozen Current prediction payloads.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

from review.current_gate_defect_fix_shadow_v1 import GateFixConfig, run_race
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1

ROOT = Path(__file__).resolve().parents[1]
DATE = "20261114"
INPUT = ROOT / "data" / "raw" / "prediction_input"
FROZEN = ROOT / "reports" / "prospective_prediction_20261114_formal_trace_v1"
OUT = ROOT / "reports" / "current_gate_defect_fix_technical_v1"
JST = timezone(timedelta(hours=9))
SIGNATURE_FIELDS = (
    "decision", "decision_score", "decision_risks", "risk_score", "risk_count",
    "final_score", "adjusted_score", "rank", "buy_v1_rc1_candidate",
    "buy_v1_rc1_status", "buy_v1_rc1_race_state", "buy_v1_rc1_buy",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def saved_row_match(live, saved):
    # The formal payload is a projection, not the full in-memory row.
    for key, value in saved.items():
        if key in live and live[key] != value:
            return False, key
    return True, None


def identity(row):
    return (int(row["horse_number"]), str(row["horse_name"]))


def race_snapshot(rows):
    buys = [identity(r) for r in rows if r.get("decision") == "BUY"]
    states = Counter(str(r.get("buy_v1_rc1_race_state")) for r in rows)
    return {"buy_horses": buys, "buy_count": len(buys), "race_state": next(iter(states)) if len(states) == 1 else "MIXED"}


def main():
    if OUT.exists():
        raise RuntimeError("STOP_EXISTING_OUTPUT")
    inputs = {kind: INPUT / f"{kind}{DATE[2:]}.CSV" for kind in ("DG", "DE", "DS")}
    for path in inputs.values():
        if not path.is_file():
            raise RuntimeError(f"STOP_INPUT_MISSING:{path}")
    formal_files = sorted(FROZEN.glob("*_prediction.json"))
    if not formal_files:
        raise RuntimeError("STOP_FROZEN_CURRENT_MISSING")
    before = {str(p.relative_to(ROOT)): sha(p) for p in sorted(FROZEN.iterdir()) if p.is_file()}
    daily = TargetBulkPredictionInputAdapterV1().load(inputs["DG"], inputs["DE"], inputs["DS"])
    configs = {
        "OFF_OFF": GateFixConfig(),
        "A1_ONLY": GateFixConfig(True, False),
        "A2_ONLY": GateFixConfig(False, True),
        "A1_A2": GateFixConfig(True, True),
    }
    formal_ids = {p.name.removesuffix("_prediction.json") for p in formal_files}
    if formal_ids != set(daily.races):
        raise RuntimeError("STOP_RACE_SET_MISMATCH")
    changed = []
    metrics = {name: Counter() for name in configs}
    a1b = Counter()
    baseline_matches = 0
    for race_id in sorted(formal_ids):
        saved = json.loads((FROZEN / f"{race_id}_prediction.json").read_text(encoding="utf-8"))
        variants = {name: run_race(race_id, daily.races[race_id], config)
                    for name, config in configs.items()}
        baseline = variants["OFF_OFF"]
        saved_rows = {identity(r): r for r in saved["ranked_results"]}
        current_rows = {identity(r): r for r in baseline["ranked_results"]}
        if set(saved_rows) != set(current_rows):
            raise RuntimeError(f"STOP_FROZEN_HORSE_SET_MISMATCH:{race_id}")
        for key in saved_rows:
            ok, field = saved_row_match(current_rows[key], saved_rows[key])
            if not ok:
                raise RuntimeError(f"STOP_FROZEN_CURRENT_MISMATCH:{race_id}:{key}:{field}")
            baseline_matches += 1
        if race_snapshot(baseline["ranked_results"])["buy_count"] != saved["buy_count"]:
            raise RuntimeError(f"STOP_FROZEN_BUY_COUNT_MISMATCH:{race_id}")
        for name, output in variants.items():
            rows = {identity(r): r for r in output["ranked_results"]}
            if set(rows) != set(current_rows):
                raise RuntimeError(f"STOP_VARIANT_HORSE_SET_MISMATCH:{race_id}:{name}")
            shot = race_snapshot(output["ranked_results"])
            metrics[name]["horses"] += len(rows)
            metrics[name]["buy_horses"] += shot["buy_count"]
            metrics[name]["buy_races"] += bool(shot["buy_count"])
            metrics[name]["race_state_" + shot["race_state"]] += 1
            for key, row in rows.items():
                base = current_rows[key]
                if name != "OFF_OFF":
                    diff = {field: {"current": base.get(field), "shadow": row.get(field)}
                            for field in SIGNATURE_FIELDS if base.get(field) != row.get(field)}
                    if diff:
                        changed.append({"race_id": race_id, "horse_number": key[0],
                                        "horse_name": key[1], "configuration": name,
                                        "pace_style": row.get("pace_style"), "changes": diff})
                        for field in diff:
                            metrics[name]["changed_" + field] += 1
                risks = row.get("decision_risks") or []
                if "展開不向き" in risks and "展開面の不安" in risks:
                    a1b[name] += 1
    after = {str(p.relative_to(ROOT)): sha(p) for p in sorted(FROZEN.iterdir()) if p.is_file()}
    if before != after:
        raise RuntimeError("STOP_FROZEN_ARTIFACT_CHANGED")
    report = {
        "schema_version": "CURRENT_GATE_DEFECT_FIX_TECHNICAL_V1",
        "execution_time_jst": datetime.now(JST).isoformat(),
        "role": "RESULT_FREE_DEVELOPMENT_TECHNICAL_VALIDATION",
        "target_date": DATE,
        "source_races": len(formal_ids), "baseline_horses_matching_frozen": baseline_matches,
        "input_sha256": {kind: sha(path) for kind, path in inputs.items()},
        "frozen_current_file_sha256": before,
        "metrics": {name: dict(counts) for name, counts in metrics.items()},
        "a1b_both_texts_count": dict(a1b),
        "a1b_causal_attribution": "UNKNOWN",
        "result_access_count": 0, "performance_evaluation_count": 0,
        "formal_pre_executed": False, "prospective_evidence_credit": 0,
        "changed_horses": changed,
        "limitations": ["Current comparison uses the frozen projection's common fields; unpersisted in-memory fields cannot be independently authenticated.",
                        "No Result or POST data was read; no accuracy conclusion is possible."],
    }
    OUT.mkdir(parents=True, exist_ok=False)
    with (OUT / "technical_validation.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return report


if __name__ == "__main__":
    result = main()
    print(json.dumps({key: result[key] for key in ("source_races", "baseline_horses_matching_frozen", "metrics", "a1b_both_texts_count", "result_access_count")}, ensure_ascii=False))
