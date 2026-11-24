"""Verify only prior-date Result source hashes for the seven V5 research folds."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from review.historical_lane_coverage_registry_v1 import CoverageStop, sha
from review.historical_v5_chronological_phase1_v1 import DATASET, MONTHS, ROOT, _prior_training_rows


def audit_training_sources(selection_path: Path, output: Path) -> dict:
    if output.exists():
        raise CoverageStop("STOP_OUTPUT_EXISTS")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection.get("schema_version") != "HISTORICAL_V5_CHRONOLOGICAL_PHASE1_V1":
        raise CoverageStop("STOP_V5_SELECTION_ROLE")
    if selection.get("evaluation_result_label_access") != 0 or selection.get("training_dataset_sha256") != sha(DATASET):
        raise CoverageStop("STOP_V5_SELECTION_SOURCE")
    by_month = []
    for month in MONTHS:
        rows, dates = _prior_training_rows(month)
        expected = defaultdict(set)
        for row in rows:
            expected[row["date"]].add(row["source_result_artifact_sha256"])
        if any(len(hashes) != 1 for hashes in expected.values()):
            raise CoverageStop("STOP_TRAIN_RESULT_SHA_AMBIGUOUS:" + month)
        entries = []
        for date in dates:
            candidates = list((ROOT / "data/raw/target/daily_result_list").glob("*_" + date + ".csv"))
            matches = [path for path in candidates if sha(path) in expected[date]]
            if len(matches) != 1:
                raise CoverageStop("STOP_TRAIN_RESULT_SOURCE_SHA:" + date)
            entries.append({"training_date": date, "result_path": str(matches[0].resolve()),
                            "result_sha256": sha(matches[0])})
        if max(dates) >= month or dates != selection["folds"][MONTHS.index(month)]["training_dates"]:
            raise CoverageStop("STOP_TRAIN_RESULT_TEMPORAL_SCOPE")
        by_month.append({"evaluation_month": month, "training_result_sources": entries})
    result = {"schema_version": "HISTORICAL_V5_TRAINING_SOURCE_AUDIT_V1",
              "recorded_at": datetime.now(timezone.utc).astimezone().isoformat(),
              "training_source_read_purpose": "SHA_VERIFICATION_OF_PRIOR_DATES_ONLY",
              "evaluation_result_file_access": 0,
              "selection_path": str(selection_path.resolve()), "selection_sha256": sha(selection_path),
              "dataset_sha256": sha(DATASET), "audit_code_sha256": sha(Path(__file__)),
              "folds": by_month}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    return result
