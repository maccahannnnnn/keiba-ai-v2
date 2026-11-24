"""One-date Human-approved input-integrity exclusion runner for 2026-08-23.

This is an operational wrapper, not a Production input-policy change.  It
creates temporary filtered copies only for the explicitly authorized 新潟7R,
runs the unchanged Adapter and current-AI projection, and removes the temporary
files before returning.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from review.prospective_prediction_runner_v1 import (
    POPULATION_SCOPE_ID, SCHEMA_VERSION, _assert_population, _canonical_write,
    _project_race, _sha256, _write_report,
)
from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
from review.target_bulk_prediction_input_shadow_v1 import run_new


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "prediction_input"
DATE = "20260823"
OUT = ROOT / "reports" / "prospective_prediction_20260823_v1"
EXCLUSION = {
    "race_id": "race_20260823_niigata_7R",
    "venue": "新潟",
    "race_number": 7,
    "affected_horse_number": 6,
    "affected_horse_name": "マインドフルネス",
    "reason": "DE_DS_HORSE_SET_MISMATCH",
    "reason_status": "SOURCE_DATA_INTEGRITY_UNRESOLVED",
    "evaluation_status": "NOT_EVALUATED",
    "authority": "HUMAN_TEMPORARY_RACE_LEVEL_EXCLUSION_20260823_ONLY",
}
TEMP_WORKSPACE = ROOT / "reports" / ".runtime_20260823_human_exclusion_tmp"


class ExistingWorkspaceTemp:
    """Use only a pre-created, caller-cleaned workspace directory."""

    def __enter__(self) -> str:
        if not TEMP_WORKSPACE.is_dir():
            raise RuntimeError("TEMP_WORKSPACE_NOT_PRECREATED")
        return str(TEMP_WORKSPACE)

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False


def read_rows(path: Path, expected_columns: int) -> list[list[str]]:
    with path.open("r", encoding="cp932", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows or any(len(row) != expected_columns for row in rows):
        raise RuntimeError(f"INPUT_SCHEMA_INVALID:{path.name}")
    return rows


def write_rows(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="cp932", newline="") as handle:
        csv.writer(handle, lineterminator="\r\n").writerows(rows)


def is_excluded_dg(row: list[str]) -> bool:
    return row[3].strip() == EXCLUSION["venue"] and int(row[4]) == EXCLUSION["race_number"]


def is_excluded_de(row: list[str]) -> bool:
    return row[1].strip() == EXCLUSION["venue"] and int(row[2]) == EXCLUSION["race_number"]


def review_frozen_output() -> None:
    review = OUT / "pre_race_review"
    if review.exists():
        raise RuntimeError("PRE_RACE_REVIEW_OUTPUT_EXISTS")
    manifest = json.loads((OUT / "prediction_manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        path = OUT / item["relative_path"]
        if not path.exists() or _sha256(path) != item["sha256"]:
            raise RuntimeError(f"FROZEN_MANIFEST_MISMATCH:{item['relative_path']}")
    index = json.loads((OUT / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    races, buys, no_buys, unconverged, skips = [], [], [], [], []
    for item in sorted(index, key=lambda value: value["race_id"]):
        payload = json.loads((OUT / item["artifact"]).read_text(encoding="utf-8"))
        trace = payload["buy_gate_trace"]
        race_trace, horse_trace = trace["race"], trace["horses"]
        race = {
            "race_id": payload["race_id"], "race_decision": payload["race_decision"],
            "race_confidence": payload["race_confidence"], "field_size": len(payload["ranked_results"]),
            "buy_count": payload["buy_count"], "shadow_race_state": race_trace["shadow_race_state"],
            "shadow_candidate_count": race_trace["shadow_candidate_count"], "top5": payload["top5"],
        }
        races.append(race)
        for buy in payload["buys"]:
            buys.append({"race_id": payload["race_id"], "race_buy_count": payload["buy_count"], **buy})
        if payload["buy_count"] == 0:
            no_buys.append(race)
        if race_trace["shadow_race_state"] == "PLAY_UNCONVERGED_4PLUS":
            candidates = [
                {"horse_number": horse["horse_number"], "shadow_ai_rank": horse["shadow_ai_rank"]}
                for horse in horse_trace if horse["shadow_buy_candidate"] is True
            ]
            candidates.sort(key=lambda horse: horse["shadow_ai_rank"])
            if len(candidates) != race_trace["shadow_candidate_count"]:
                raise RuntimeError(f"TRACE_CANDIDATE_COUNT_MISMATCH:{payload['race_id']}")
            unconverged.append({**race, "frozen_candidate_order": candidates})
        if race_trace["shadow_race_state"] == "SKIP":
            skips.append(race)
    for item in manifest["files"]:
        if _sha256(OUT / item["relative_path"]) != item["sha256"]:
            raise RuntimeError(f"FROZEN_SOURCE_MUTATED:{item['relative_path']}")
    review.mkdir()
    payload = {
        "source": "frozen prospective_prediction_20260823_v1", "result_data_access_count": 0,
        "evaluated_races": races, "frozen_buy_horses": buys, "buy_zero_races": no_buys,
        "unconverged_races": unconverged, "skip_races": skips,
        "not_evaluated_races": [EXCLUSION],
    }
    _canonical_write(review / "race_summary.json", {key: payload[key] for key in ("source", "result_data_access_count", "evaluated_races", "not_evaluated_races")})
    _canonical_write(review / "buy_summary.json", {"source": payload["source"], "result_data_access_count": 0, "buy_horse_count": len(buys), "buys": buys})
    _canonical_write(review / "no_buy_races.json", {"source": payload["source"], "result_data_access_count": 0, "races": no_buys})
    _canonical_write(review / "convergence_observation.json", {"source": payload["source"], "result_data_access_count": 0, "unconverged_races": unconverged, "skip_races": skips, "boundary": "PRE-only observation. CF_TOP3_RANK_ANCHORED was not applied."})
    lines = ["# 2026-08-23 Prospective PRE-RACE Review", "", "- Result-data access: 0", "- Frozen manifest integrity: PASS", f"- NOT_EVALUATED: 新潟7R — {EXCLUSION['reason_status']}", f"- Evaluated races: {len(races)}; evaluated horses: {sum(r['field_size'] for r in races)}; frozen BUY horses: {len(buys)}", "", "## BUY by race", "", "| Race | BUY count | Horses |", "|---|---:|---|"]
    for race_id in sorted({buy["race_id"] for buy in buys}):
        race_buys = [buy for buy in buys if buy["race_id"] == race_id]
        names = ", ".join(f"{buy['horse_number']} {buy['horse_name']}" for buy in race_buys)
        lines.append(f"| {race_id} | {len(race_buys)} | {names} |")
    lines += ["", "## UNCONVERGED PRE-only observation", ""]
    if unconverged:
        for race in unconverged:
            order = ", ".join(f"{horse['horse_number']} (rank {horse['shadow_ai_rank']})" for horse in race["frozen_candidate_order"])
            lines.append(f"- {race['race_id']}: {race['shadow_candidate_count']} candidates — {order}")
    else:
        lines.append("- none")
    lines += ["", "## SKIP races", ""] + [f"- {race['race_id']}" for race in skips]
    (review / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if OUT.exists():
        raise RuntimeError("OUTPUT_ROOT_EXISTS")
    source_paths = {kind: RAW / f"{kind}{DATE[2:]}.CSV" for kind in ("DG", "DE", "DS")}
    dg, de, ds = read_rows(source_paths["DG"], 11), read_rows(source_paths["DE"], 33), read_rows(source_paths["DS"], 50)
    excluded_dg = [row for row in dg if is_excluded_dg(row)]
    excluded_de = [row for row in de if is_excluded_de(row)]
    if len(excluded_dg) != 1 or not excluded_de:
        raise RuntimeError("HUMAN_EXCLUSION_TARGET_NOT_UNIQUE")
    target_entries = [row for row in excluded_de if int(row[3]) == EXCLUSION["affected_horse_number"] and row[7].strip() == EXCLUSION["affected_horse_name"]]
    if len(target_entries) != 1:
        raise RuntimeError("HUMAN_EXCLUSION_AFFECTED_HORSE_NOT_FOUND")
    filtered = {"DG": [row for row in dg if not is_excluded_dg(row)], "DE": [row for row in de if not is_excluded_de(row)]}
    cleaner = TargetBulkPredictionInputAdapterV1()._clean_name
    remaining_names = {cleaner(row[7]) for row in filtered["DE"]}
    filtered["DS"] = [row for row in ds if cleaner(row[16]) in remaining_names]
    if len(dg) - len(filtered["DG"]) != 1 or len(de) - len(filtered["DE"]) != len(excluded_de):
        raise RuntimeError("UNAUTHORIZED_ADDITIONAL_EXCLUSION")

    # The caller creates/removes this exact workspace directory. This avoids
    # the ACL behaviour of Python-created temporary directories on this host.
    with ExistingWorkspaceTemp() as temp_name:
        temp = Path(temp_name)
        paths = {kind: temp / f"{kind}{DATE[2:]}.CSV" for kind in ("DG", "DE", "DS")}
        for kind, path in paths.items():
            write_rows(path, filtered[kind])
        bundle = TargetBulkPredictionInputAdapterV1().load(paths["DG"], paths["DE"], paths["DS"])
        if bundle.date != DATE:
            raise RuntimeError(f"TARGET_DATE_MISMATCH:{bundle.date}")
        _assert_population(bundle)
        if EXCLUSION["race_id"] in bundle.races:
            raise RuntimeError("EXCLUDED_RACE_REMAINS_IN_BUNDLE")
        if len(bundle.races) != len(filtered["DG"]):
            raise RuntimeError("REMAINING_RACE_COUNT_MISMATCH")

        OUT.mkdir(parents=True)
        generated_at = datetime.now(timezone.utc).isoformat()
        artifacts, index = [], []
        for race_id, race in sorted(bundle.races.items()):
            output = run_new(race_id, race, trace=True)
            artifact = _project_race(race_id, output)
            artifact["buy_gate_trace"] = output["buy_gate_trace"]
            artifact["trace_status"] = "NOT_FORMALLY_FROZEN_TRACE"
            filename = f"{race_id}_prediction.json"
            _canonical_write(OUT / filename, artifact)
            artifacts.append(filename)
            index.append({"race_id": race_id, "artifact": filename, "horse_count": len(artifact["ranked_results"]), "buy_count": artifact["buy_count"], "race_decision": artifact["race_decision"]})
        _canonical_write(OUT / "race_index.json", {"schema_version": SCHEMA_VERSION, "race_index": index})
        _canonical_write(OUT / "exclusion_record.json", {"total_source_races": len(dg), "excluded_input_integrity_races": 1, "evaluated_races": len(index), "excluded_races": [EXCLUSION], "no_other_automatic_exclusion": True})
        _canonical_write(OUT / "input_manifest.json", {"date": DATE, "population_scope_id": POPULATION_SCOPE_ID, "sources": {kind: {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)} for kind, path in source_paths.items()}, "temporary_filtered_input": {"used": True, "raw_modified": False, "exclusion": EXCLUSION, "filtered_row_counts": {kind: len(rows) for kind, rows in filtered.items()}}})
        _canonical_write(OUT / "provenance.json", {"target_date": DATE, "schema_version": SCHEMA_VERSION, "population_scope_id": POPULATION_SCOPE_ID, "generated_at": generated_at, "trace_mode": True, "result_data_access_count": 0, "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "runner_path": str(Path(__file__).relative_to(ROOT)), "runner_sha256": _sha256(Path(__file__)), "current_ai_runner_sha256": _sha256(ROOT / "review" / "prospective_prediction_runner_v1.py"), "run_new_module_sha256": _sha256(ROOT / "review" / "target_bulk_prediction_input_shadow_v1.py"), "human_exclusion": EXCLUSION, "production_change": False, "buy_rule_change": False, "convergence_rule_change": False, "shadow_implementation": False})
        _canonical_write(OUT / "summary.json", {"schema_version": SCHEMA_VERSION, "date": DATE, "total_source_races": len(dg), "excluded_input_integrity_races": 1, "evaluated_races": len(index), "evaluated_horses": sum(item["horse_count"] for item in index), "buy_count": sum(item["buy_count"] for item in index), "trace_mode": True, "result_data_access_count": 0, "not_evaluated": [EXCLUSION]})
        _write_report(OUT / "report.md", date=DATE, trace=True, race_count=len(index), horse_count=sum(item["horse_count"] for item in index), buy_count=sum(item["buy_count"] for item in index))
        files = artifacts + ["race_index.json", "exclusion_record.json", "input_manifest.json", "provenance.json", "summary.json", "report.md"]
        _canonical_write(OUT / "prediction_manifest.json", {"schema_version": SCHEMA_VERSION, "excludes": ["prediction_manifest.json", "pre_race_review/**"], "files": [{"relative_path": name, "sha256": _sha256(OUT / name)} for name in files]})
    review_frozen_output()
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
