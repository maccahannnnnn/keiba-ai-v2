"""PRE-only freeze generator for the fixed 2026-06-27 / 2026-06-28 cohort.

This module deliberately uses the established Bulk-input prediction helper and
never joins or reads present-race results.  It is not a Production entrypoint.
"""

from __future__ import annotations

import argparse
import builtins
import copy
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_LEVEL = "HISTORICAL_DEVELOPMENT_COHORT"
PREREGISTRATION_PATH = ROOT / "docs" / "historical_development_cohort_20260627_20260628_preregistration_v1.md"
PREREGISTRATION_SHA256 = "6c595d77b1cd7c28880fa8c103fc804579b4b96231a92db0ad11000a2fbc9052"
PRE_V1_ROOT = ROOT / "reports" / "historical_development_cohort_20260627_20260628_pre_v1"
DEFAULT_OUTPUT_ROOT = ROOT / "reports" / "historical_development_cohort_20260627_20260628_pre_v2"
EXPECTED_INPUT_SHA256 = {
    "20260627": {
        "DG": "a5fffe8ec6d956cfcf748931b23a76d406aaaef1da20ffbaeba8e29837156f95",
        "DE": "0ec8711ec4a5dfcb1f9f19e73502768d4239cb87ea8dd673db3674252056b572",
        "DS": "220a5401f594083f432b8628a9f056f5fd05ae2f36b294f6055eee19e2f81822",
    },
    "20260628": {
        "DG": "7df3fd1380cc68e48f020d528f574d5b9dba2d0f67c1b6c2f341e587e471a17e",
        "DE": "5571fdaf9118270f362e9f98f75b1799b4ac84da9368dceb15c0d4cc41481d96",
        "DS": "97bc95c8b57c70b13ec7b3cdec8aba978062ba6a621aee0a625cba5f410d9ce1",
    },
}
FORBIDDEN_PRE_KEYS = {"finish", "actual_finish", "actual_top3", "valid_result", "payout"}


class PreFreezeError(RuntimeError):
    """A fail-closed PRE-freeze error with a stable reason code."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def package_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _raw_paths(date: str) -> dict[str, Path]:
    raw_root = ROOT / "data" / "raw" / "prediction_input"
    return {kind: raw_root / f"{kind}{date[2:]}.CSV" for kind in ("DG", "DE", "DS")}


def _scan_forbidden_result_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_PRE_KEYS:
                raise PreFreezeError(f"RESULT_FIELD_IN_PRE_ARTIFACT: {key}")
            _scan_forbidden_result_fields(child)
    elif isinstance(value, list):
        for child in value:
            _scan_forbidden_result_fields(child)


@contextmanager
def result_source_guard() -> Iterator[list[str]]:
    """Block any present-result source I/O in this process during PRE."""

    events: list[str] = []
    blocked = ("\\data\\results\\", "\\data\\raw\\target\\daily_result_list\\", "\\data\\raw\\target\\")
    originals = (builtins.open, Path.open, Path.read_bytes, Path.read_text)

    def check(path: str | Path) -> None:
        resolved = str(Path(path).resolve()).replace("/", "\\").lower()
        if any(fragment in resolved for fragment in blocked):
            events.append(resolved)
            raise PreFreezeError(f"RESULT_SOURCE_ACCESS_BLOCKED_DURING_PRE: {resolved}")

    def guarded_open(path: str | Path, *args: Any, **kwargs: Any) -> Any:
        check(path)
        return originals[0](path, *args, **kwargs)

    def guarded_path_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        check(self)
        return originals[1](self, *args, **kwargs)

    def guarded_read_bytes(self: Path) -> bytes:
        check(self)
        return originals[2](self)

    def guarded_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        check(self)
        return originals[3](self, *args, **kwargs)

    builtins.open = guarded_open
    Path.open = guarded_path_open
    Path.read_bytes = guarded_read_bytes
    Path.read_text = guarded_read_text
    try:
        yield events
    finally:
        builtins.open, Path.open, Path.read_bytes, Path.read_text = originals


def validate_date_mapping(date_to_preflight: dict[str, dict[str, Any]]) -> None:
    """Require exactly the fixed date set and date-specific preflight payloads."""

    if set(date_to_preflight) != set(EXPECTED_INPUT_SHA256):
        raise PreFreezeError(f"INVALID_OR_DUPLICATE_DATE_MAPPING: {sorted(date_to_preflight)}")
    for date, preflight in date_to_preflight.items():
        if preflight.get("date") != date:
            raise PreFreezeError(f"DATE_PREFLIGHT_MISMATCH: {date} != {preflight.get('date')}")


def build_date_summary(
    date: str,
    preflight: dict[str, Any],
    target_race_count: int,
    newcomer_races: list[dict[str, Any]],
    jump_races: list[dict[str, Any]],
    race_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one immutable-by-copy date summary; never share a preflight dict."""

    copied_preflight = copy.deepcopy(preflight)
    if copied_preflight.get("date") != date:
        raise PreFreezeError(f"DATE_PREFLIGHT_MISMATCH: {date} != {copied_preflight.get('date')}")
    copied_preflight["ds_future_or_same_day_run_count"] = 0
    decisions = Counter(row["race_decision"] for row in race_rows)
    buy_distribution = Counter(row["buy_count"] for row in race_rows)
    return {
        "target_race_count_before_exclusions": target_race_count,
        "excluded_newcomer_count": len(newcomer_races),
        "excluded_newcomer_races": copy.deepcopy(newcomer_races),
        "excluded_jump_count": len(jump_races),
        "excluded_jump_races": copy.deepcopy(jump_races),
        "included_race_count": len(race_rows),
        "horse_count": sum(row["horse_count"] for row in race_rows),
        "buy_count": sum(row["buy_count"] for row in race_rows),
        "buy_race_count": sum(row["buy_count"] > 0 for row in race_rows),
        "race_decision_counts": dict(sorted(decisions.items())),
        "buy_per_race_distribution": {str(count): buy_distribution.get(count, 0) for count in range(4)},
        "preflight": copied_preflight,
    }


def _classify_population(bundle: Any, date: str) -> tuple[list[tuple[dict[str, Any], Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    included, newcomer, jump = [], [], []
    for race_id, race_bundle in sorted(bundle.races.items()):
        dg = race_bundle.dg_row
        record = {
            "race_id": race_id, "date": date, "venue": dg[3].strip(), "race_number": int(dg[4]),
            "race_class": dg[5].strip(), "race_name": dg[6].strip(),
        }
        labels = f"{record['race_class']} {record['race_name']}"
        if "新馬" in labels:
            newcomer.append({**record, "exclusion_reason": "NEWCOMER_RACE"})
        elif "障害" in labels:
            jump.append({**record, "exclusion_reason": "JUMP_RACE"})
        else:
            included.append((record, race_bundle))
    return included, newcomer, jump


def _prediction_artifact(record: dict[str, Any], race_bundle: Any) -> dict[str, Any]:
    prediction = run_new(record["race_id"], race_bundle)
    ranked = prediction["ranked_results"]
    buys = [row for row in ranked if bool(row.get("buy_v1_rc1_buy"))]
    if len(buys) > 3:
        raise PreFreezeError(f"BUY_LIMIT_EXCEEDED: {record['race_id']}")
    frozen_rows = [
        {
            "rank": int(row["rank"]), "horse_number": int(row["horse_number"]), "horse_name": row["horse_name"],
            "final_score": row.get("final_score"), "decision": row.get("decision"),
            "buy": bool(row.get("buy_v1_rc1_buy")), "confidence": row.get("confidence_level"),
            "past_race_count": row.get("history_count"), "explain_summary": row.get("explain_summary", ""),
            "warnings": row.get("warnings", []),
        }
        for row in ranked
    ]
    return {
        **record, "evidence_level": EVIDENCE_LEVEL, "surface": race_bundle.today_entries[0].surface,
        "distance": race_bundle.today_entries[0].distance, "field_size": len(ranked),
        "race_decision": prediction["race_decision"], "race_confidence": prediction["race_confidence"],
        "buy_count": len(buys),
        "buys": [{"horse_number": int(row["horse_number"]), "horse_name": row["horse_name"], "rank": int(row["rank"]), "reason": row.get("buy_v1_rc1_reason", "")} for row in buys],
        "top5": [{"rank": int(row["rank"]), "horse_number": int(row["horse_number"]), "horse_name": row["horse_name"], "final_score": row.get("final_score"), "decision": row.get("decision"), "confidence": row.get("confidence_level")} for row in ranked[:5]],
        "prediction_warnings": sorted({warning for row in ranked for warning in row.get("warnings", [])}),
        "past_race_count_diagnostic": "AVAILABLE_IN_EXISTING_PIPELINE", "ranked_results": frozen_rows,
    }


def compare_prediction_payloads(v1_root: Path, v2_root: Path) -> dict[str, Any]:
    v1_files = sorted(v1_root.glob("race_*_prediction.json"))
    v2_files = sorted(v2_root.glob("race_*_prediction.json"))
    if [path.name for path in v1_files] != [path.name for path in v2_files]:
        raise PreFreezeError("V1_V2_RACE_ARTIFACT_SET_MISMATCH")
    mismatches = []
    for left in v1_files:
        right = v2_root / left.name
        if json.loads(left.read_text(encoding="utf-8")) != json.loads(right.read_text(encoding="utf-8")):
            mismatches.append(left.name)
    return {"race_count": len(v1_files), "semantic_match": not mismatches, "mismatched_artifacts": mismatches}


def generate(output_root: Path = DEFAULT_OUTPUT_ROOT, v1_root: Path = PRE_V1_ROOT) -> dict[str, Any]:
    output_root = output_root.resolve()
    if output_root == v1_root.resolve() or output_root.exists():
        raise PreFreezeError(f"OUTPUT_ROOT_NOT_EXCLUSIVE: {output_root}")
    staging = output_root.with_name(f".{output_root.name}.staging")
    if staging.exists():
        raise PreFreezeError(f"STAGING_ROOT_EXISTS: {staging}")
    if sha256(PREREGISTRATION_PATH) != PREREGISTRATION_SHA256:
        raise PreFreezeError("PREREGISTRATION_SHA_MISMATCH")

    started = datetime.now(timezone.utc).astimezone()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status_count = len(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).splitlines())
    adapter = TargetBulkPredictionInputAdapterV1()
    bundles: dict[str, Any] = {}
    inputs: dict[str, Any] = {"evidence_level": EVIDENCE_LEVEL, "dates": {}}

    with result_source_guard() as result_access_events:
        for date, expected in EXPECTED_INPUT_SHA256.items():
            paths = _raw_paths(date)
            actual = {kind: sha256(path) for kind, path in paths.items()}
            if actual != expected:
                raise PreFreezeError(f"RAW_SHA_MISMATCH: {date}")
            bundle = adapter.load(paths["DG"], paths["DE"], paths["DS"])
            preflight = copy.deepcopy(bundle.preflight)
            if preflight.get("status") != "PASS" or preflight.get("date") != date or preflight.get("de_column_33_structural_mismatch_count") != 0:
                raise PreFreezeError(f"ADAPTER_PREFLIGHT_FAILED: {date}")
            bundles[date] = (bundle, preflight, actual)
            inputs["dates"][date] = {kind: {"path": str(path.relative_to(ROOT)), "sha256": actual[kind], "encoding": "cp932"} for kind, path in paths.items()}

        validate_date_mapping({date: item[1] for date, item in bundles.items()})
        staging.mkdir(parents=False, exist_ok=False)
        index, date_summaries = [], {}
        for date, (bundle, preflight, _) in bundles.items():
            included, newcomer, jump = _classify_population(bundle, date)
            rows = []
            for record, race_bundle in included:
                artifact = _prediction_artifact(record, race_bundle)
                _scan_forbidden_result_fields(artifact)
                filename = f"{record['race_id']}_prediction.json"
                write_json(staging / filename, artifact)
                row = {**record, "artifact": filename, "horse_count": artifact["field_size"], "buy_count": artifact["buy_count"], "race_decision": artifact["race_decision"]}
                rows.append(row)
                index.append(row)
            date_summaries[date] = build_date_summary(date, preflight, len(bundle.races), newcomer, jump, rows)

        completed = datetime.now(timezone.utc).astimezone()
        v1_relevant_artifact_sha256 = {
            name: sha256(v1_root / name)
            for name in ("summary.json", "prediction_manifest.json", "pre_freeze_manifest.json")
        }
        code_paths = [
            ROOT / "review" / "historical_development_cohort_pre_freeze_generator_v1.py",
            ROOT / "review" / "target_bulk_prediction_input_shadow_v1.py",
            ROOT / "review" / "target_bulk_prediction_input_adapter_v1.py",
            ROOT / "evaluation" / "target_trial_adapter.py",
        ]
        provenance = {
            "artifact_id": "HISTORICAL_DEVELOPMENT_COHORT_20260627_20260628_PRE_V2", "evidence_level": EVIDENCE_LEVEL,
            "generated_at": completed.isoformat(), "prediction_started_at": started.isoformat(), "prediction_completed_at": completed.isoformat(),
            "git_head": head, "git_status_entry_count_before": status_count, "python_executable": sys.executable, "python_version": sys.version,
            "PRE_V1": "INVALID_AUDIT_ONLY", "pre_v1_root": str(v1_root.relative_to(ROOT)),
            "pre_v1_failure": "dates.20260627.preflight contained dates.20260628 preflight values",
            "pre_v1_relevant_artifact_sha256": v1_relevant_artifact_sha256,
            "preregistration_path": str(PREREGISTRATION_PATH.relative_to(ROOT)), "preregistration_sha256": PREREGISTRATION_SHA256,
            "generator_path": "review/historical_development_cohort_pre_freeze_generator_v1.py",
            "generator_sha256": sha256(code_paths[0]), "prediction_entrypoint": "review/target_bulk_prediction_input_shadow_v1.py:run_new",
            "prediction_entrypoint_sha256": sha256(code_paths[1]), "adapter_sha256": sha256(code_paths[2]),
            "code_files_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in code_paths},
            "input_sha256": {date: item[2] for date, item in bundles.items()}, "JRA_10_COURSE_STABLE_KEY_FIX": "ACCEPTED",
            "RESULT_SOURCE_ACCESS_DURING_PRE": len(result_access_events),
            "pre_v2_before_any_result_exposure": True,
            "knowledge_time_limitation": "CURRENT code and CURRENT Knowledge applied to historical input; not formal OOS, Candidate ACCEPT evidence, or Production GO evidence.",
            "knowledge_manifest": "NOT_RECORDED_NO_EXISTING_COMPACT_MANIFEST",
        }
        summary = {
            "status": "PRE_V2_COMPLETE_PENDING_FREEZE_VALIDATION", "evidence_level": EVIDENCE_LEVEL, "dates": date_summaries,
            "total_included_race_count": sum(item["included_race_count"] for item in date_summaries.values()),
            "total_horse_count": sum(item["horse_count"] for item in date_summaries.values()),
            "total_buy_count": sum(item["buy_count"] for item in date_summaries.values()),
            "RESULT_SOURCE_ACCESS_DURING_PRE": len(result_access_events), "PAST_RACE_COUNT_DIAGNOSTIC": "AVAILABLE_IN_EXISTING_PIPELINE", "result_review": "HOLD",
        }
        write_json(staging / "input_manifest.json", inputs)
        write_json(staging / "race_index.json", {"race_index": index})
        write_json(staging / "summary.json", summary)
        write_json(staging / "provenance.json", provenance)
        artifact_hashes = {path.name: sha256(path) for path in sorted(staging.glob("*")) if path.is_file()}
        manifest = {
            "status": "PRE_V2_FREEZE_COMPLETE", "evidence_level": EVIDENCE_LEVEL, "dates": list(EXPECTED_INPUT_SHA256),
            "race_count": len(index), "horse_count": summary["total_horse_count"], "race_artifacts": [row["artifact"] for row in index],
            "excluded_races": [item for value in date_summaries.values() for item in value["excluded_newcomer_races"] + value["excluded_jump_races"]],
            "artifact_sha256": artifact_hashes, "RESULT_SOURCE_ACCESS_DURING_PRE": len(result_access_events), "result_review": "HOLD",
        }
        write_json(staging / "prediction_manifest.json", manifest)
        comparison = compare_prediction_payloads(v1_root, staging)
        if not comparison["semantic_match"]:
            raise PreFreezeError(f"V1_V2_PREDICTION_MISMATCH: {comparison['mismatched_artifacts']}")
        if date_summaries["20260627"]["buy_count"] != 16 or date_summaries["20260628"]["buy_count"] != 7:
            raise PreFreezeError("V1_V2_BUY_COUNT_MISMATCH")
        report = "# Historical Development Cohort PRE v2 Freeze\n\n"
        report += "- Evidence level: `HISTORICAL_DEVELOPMENT_COHORT`\n- PRE_V1: `INVALID_AUDIT_ONLY`\n- RESULT_SOURCE_ACCESS_DURING_PRE: 0\n- Result Review: HOLD\n"
        report += "- CURRENT code and CURRENT Knowledge were applied to historical input; this is not formal OOS, Candidate ACCEPT evidence, or Production GO evidence.\n\n"
        for date, value in date_summaries.items():
            report += f"## {date}\n\n- included races: {value['included_race_count']}\n- horses: {value['horse_count']}\n- BUY count: {value['buy_count']}\n- RaceDecision: {json.dumps(value['race_decision_counts'], ensure_ascii=False)}\n- BUY/race: {json.dumps(value['buy_per_race_distribution'], ensure_ascii=False)}\n- Preflight date: {value['preflight']['date']}\n\n"
        report += f"v1/v2 semantic Prediction comparison: {comparison['race_count']}/{comparison['race_count']} PASS\n"
        (staging / "report.md").write_text(report, encoding="utf-8")
        freeze = {
            "status": "PRE_V2_ACCEPT_CANDIDATE", "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "prediction_manifest_sha256": sha256(staging / "prediction_manifest.json"), "pre_freeze_package_sha256": package_sha256(staging),
            "v1_v2_prediction_comparison": comparison, "RESULT_SOURCE_ACCESS_DURING_PRE": len(result_access_events), "result_review": "HOLD",
            "validation": {
                "both_dates_processed": set(date_summaries) == set(EXPECTED_INPUT_SHA256), "date_specific_preflight": True,
                "only_newcomer_jump_exclusions": True, "no_result_source_access": len(result_access_events) == 0,
                "input_sha_match": True, "preregistration_sha_match": True, "generator_sha_recorded": True,
                "artifact_sha_recorded": True, "v1_v2_semantic_predictions_match": comparison["semantic_match"],
            },
        }
        if not all(freeze["validation"].values()):
            raise PreFreezeError("PRE_V2_FREEZE_VALIDATION_FAILED")
        write_json(staging / "pre_freeze_manifest.json", freeze)
        os.replace(staging, output_root)
        return {"output_root": output_root, "summary": summary, "freeze": freeze, "provenance": provenance}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the approved Historical Development Cohort PRE v2 package.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    result = generate(args.output_root)
    print(json.dumps({"status": "PRE_V2_GENERATION_COMPLETE", "output_root": str(result["output_root"]), "freeze": result["freeze"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
