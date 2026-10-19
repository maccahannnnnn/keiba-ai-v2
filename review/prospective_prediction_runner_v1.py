"""Persistent, prediction-only runner for prospective JRA DG/DE/DS input."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new
from review.current_environment_tree_hash_v1 import tree_hash


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "prediction_input"
SCHEMA_VERSION = "prospective_prediction_schema_v1"
POPULATION_SCOPE_ID = "PREDICTION_BUY_1WIN_PLUS_FLAT"
FORBIDDEN_POPULATION_TOKENS = ("新馬", "未勝利", "障害", "newcomer", "maiden", "jump")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_report(path: Path, *, date: str, trace: bool, race_count: int, horse_count: int, buy_count: int) -> None:
    """Write the human-readable, prediction-only run note.

    The report deliberately contains no result-derived values and is not a
    replacement for a formal Trace Freeze record.
    """
    lines = [
        "# Prospective Prediction",
        "",
        f"- Target date: {date}",
        f"- Population scope: `{POPULATION_SCOPE_ID}`",
        f"- Schema: `{SCHEMA_VERSION}`",
        f"- Races: {race_count}",
        f"- Horses: {horse_count}",
        f"- BUY count: {buy_count}",
        f"- Trace mode: {'ON — NOT_FORMALLY_FROZEN_TRACE' if trace else 'OFF'}",
        "- Result-data access: 0",
        "",
        "This artifact is prediction-only. It does not perform a Result Review or formal Trace Freeze.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


COMMON_SEMANTIC_HORSE_FIELDS = (
    "rank", "horse_number", "horse_name", "final_score", "decision", "buy",
    "confidence", "past_race_count", "explain_summary", "warnings",
)


def common_semantic_projection(payload: dict) -> dict:
    """Project both legacy and v1 artifacts to the preregistered common contract."""
    rows = []
    for row in payload.get("ranked_results", []):
        confidence = row.get("confidence", row.get("confidence_level"))
        past_race_count = row.get("past_race_count", row.get("history_count"))
        decision = row.get("decision")
        rows.append({
            "rank": row.get("rank"), "horse_number": row.get("horse_number"),
            "horse_name": row.get("horse_name"), "final_score": row.get("final_score"),
            "decision": decision, "buy": row.get("buy", decision == "BUY"),
            "confidence": confidence, "past_race_count": past_race_count,
            "explain_summary": row.get("explain_summary", ""), "warnings": row.get("warnings", []),
        })
    return {
        "race_id": payload.get("race_id"), "race_decision": payload.get("race_decision"),
        "race_confidence": payload.get("race_confidence"), "buy_count": payload.get("buy_count"),
        "ranked_results": rows,
    }


def _assert_population(bundle) -> None:
    for race_id, race in bundle.races.items():
        for entry in race.today_entries:
            values = " ".join(str(getattr(entry, field, "") or "") for field in ("class_level", "surface", "race_name"))
            if any(token.lower() in values.lower() for token in FORBIDDEN_POPULATION_TOKENS):
                raise ValueError(f"UNEXPECTED_PREDICTION_POPULATION_RACE:{race_id}")


def _project_race(race_id: str, output: dict) -> dict:
    ranked = []
    for row in output["ranked_results"]:
        risks = row.get("decision_risks") or row.get("risk_factors") or []
        if not isinstance(risks, list):
            risks = [risks]
        ranked.append({
            "horse_number": row.get("horse_number"), "horse_name": row.get("horse_name"),
            "rank": row.get("rank"), "final_score": row.get("final_score"),
            "decision": row.get("decision"), "buy": row.get("decision") == "BUY",
            "confidence": row.get("confidence_level"), "past_race_count": row.get("history_count"),
            "decision_score": row.get("decision_score"), "adjusted_score": row.get("adjusted_score"),
            "consensus_positive_count": row.get("consensus_positive_count"),
            "consensus_negative_count": row.get("consensus_negative_count"),
            "explain_summary": row.get("explain_summary", ""), "warnings": row.get("warnings", []),
            "risks": risks, "risk_count": row.get("risk_count", len(risks)),
            "conflict_count": row.get("conflict_count", len(row.get("conflict_factors") or [])),
            "buy_v1_rc1_status": row.get("buy_v1_rc1_status"),
            "buy_v1_rc1_candidate": row.get("buy_v1_rc1_candidate"),
            "buy_v1_rc1_race_state": row.get("buy_v1_rc1_race_state"),
            "buy_v1_rc1_reason": row.get("buy_v1_rc1_reason"),
        })
    buys = [row for row in ranked if row["buy"]]
    return {"schema_version": SCHEMA_VERSION, "race_id": race_id,
            "race_decision": output.get("race_decision"), "race_confidence": output.get("race_confidence"),
            "buy_count": len(buys), "top5": [dict(row) for row in ranked[:5]], "buys": [dict(row) for row in buys],
            "ranked_results": ranked}


def run(date: str, trace: bool = False, output_root: Path | None = None, *, compatibility_exception: str | None = None) -> Path:
    if len(date) != 8 or not date.isdigit():
        raise ValueError("date must be YYYYMMDD")
    adapter_path = ROOT / "review/target_bulk_prediction_input_adapter_v1.py"
    adapter_sha = _sha256(adapter_path)
    paths = {kind: RAW / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}
    bundle = TargetBulkPredictionInputAdapterV1().load(paths["DG"], paths["DE"], paths["DS"], compatibility_exception=compatibility_exception)
    if bundle.date != date:
        raise ValueError(f"TARGET_DATE_MISMATCH:{bundle.date}:{date}")
    _assert_population(bundle)
    trees = {f"{name}_tree_sha256": tree_hash(ROOT / name) for name in ("engine", "evaluation", "knowledge")}
    root = output_root or ROOT / "reports" / f"prospective_prediction_{date}_v1"
    if root.exists():
        raise FileExistsError(f"OUTPUT_ROOT_EXISTS:{root}")
    root.mkdir(parents=True)
    generated = datetime.now(timezone.utc).isoformat()
    artifacts, index = [], []
    for race_id, race in sorted(bundle.races.items()):
        output = run_new(race_id, race, trace=trace)
        artifact = _project_race(race_id, output)
        if trace:
            artifact["buy_gate_trace"] = output["buy_gate_trace"]
            artifact["trace_status"] = "NOT_FORMALLY_FROZEN_TRACE"
        filename = f"{race_id}_prediction.json" if race_id.startswith("race_") else f"race_{race_id}_prediction.json"
        _canonical_write(root / filename, artifact)
        artifacts.append(filename)
        index.append({"race_id": race_id, "artifact": filename, "horse_count": len(artifact["ranked_results"]),
                      "buy_count": artifact["buy_count"], "race_decision": artifact["race_decision"]})
    _canonical_write(root / "race_index.json", {"schema_version": SCHEMA_VERSION, "race_index": index})
    _canonical_write(root / "input_manifest.json", {"date": date, "population_scope_id": POPULATION_SCOPE_ID,
        "sources": {kind: {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)} for kind, path in paths.items()},
        "input_exception": bundle.preflight.get("input_exception")})
    runner = Path(__file__)
    if _sha256(adapter_path) != adapter_sha:
        raise RuntimeError("CURRENT_PRE_ADAPTER_CHANGED_DURING_RUN")
    if trees != {f"{name}_tree_sha256": tree_hash(ROOT / name) for name in ("engine", "evaluation", "knowledge")}:
        raise RuntimeError("CURRENT_PRE_ENVIRONMENT_TREE_CHANGED_DURING_RUN")
    provenance = {"target_date": date, "population_scope_id": POPULATION_SCOPE_ID, "schema_version": SCHEMA_VERSION,
        "generated_at": generated, "trace_mode": trace, "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "runner_path": str(runner.relative_to(ROOT)), "runner_sha256": _sha256(runner),
        "run_new_module": "review/target_bulk_prediction_input_shadow_v1.py", "run_new_module_sha256": _sha256(ROOT / "review/target_bulk_prediction_input_shadow_v1.py"),
        "shadow_buy_engine_sha256": _sha256(ROOT / "engine/shadow_buy_decision_engine.py"),
        "known_limitations": [],
        "target_bulk_prediction_input_adapter_sha256": adapter_sha,
        "result_data_access_count": 0, **trees}
    if trace:
        trace_schema = ROOT / "docs" / "buy_gate_trace_schema_v1_1.json"
        provenance["buy_gate_trace_schema_version"] = "BUY_GATE_TRACE_SCHEMA_V1_1"
        provenance["buy_gate_trace_schema_path"] = str(trace_schema.relative_to(ROOT))
        provenance["buy_gate_trace_schema_sha256"] = _sha256(trace_schema)
    _canonical_write(root / "provenance.json", provenance)
    _canonical_write(root / "summary.json", {"schema_version": SCHEMA_VERSION, "date": date, "race_count": len(index),
        "horse_count": sum(row["horse_count"] for row in index), "buy_count": sum(row["buy_count"] for row in index), "trace_mode": trace})
    _write_report(root / "report.md", date=date, trace=trace, race_count=len(index),
                  horse_count=sum(row["horse_count"] for row in index),
                  buy_count=sum(row["buy_count"] for row in index))
    manifest_files = artifacts + ["race_index.json", "input_manifest.json", "provenance.json", "summary.json", "report.md"]
    _canonical_write(root / "prediction_manifest.json", {"schema_version": SCHEMA_VERSION, "excludes": ["prediction_manifest.json"],
        "files": [{"relative_path": name, "sha256": _sha256(root / name)} for name in manifest_files]})
    return root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    print(run(args.date, trace=args.trace))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
