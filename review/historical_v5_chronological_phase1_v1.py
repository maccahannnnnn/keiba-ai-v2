"""Chronological research V5 folds; evaluation features come only from saved PRE rows."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

from review import ml_v4_buy_selection_model_train_v4 as core
from review import prospective_three_system_pre_freeze_v1 as daily
from review.independent_race_selection_prospective_pre import load_protocol, select_rows
from review.historical_lane_coverage_registry_v1 import CoverageStop, sha

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "reports/ml_v4_buy_selection_dataset_v5/dataset.csv"
MONTHS = tuple(f"2026{month:02d}" for month in range(3, 10))


def _prior_training_rows(month: str) -> tuple[list[dict], list[str]]:
    """Inspect only the date prefix of other rows; parse labels only before month."""
    rows = []
    dates = set()
    with DATASET.open("r", encoding="utf-8", newline="") as stream:
        header = next(stream).rstrip("\r\n")
        fields = next(csv.reader([header]))
        if fields[:2] != ["row_id", "date"] or "actual_top3" not in fields:
            raise CoverageStop("STOP_V5_DATASET_SCHEMA")
        for line in stream:
            date = line.split(",", 2)[1]
            if date >= month:
                continue
            cells = next(csv.reader([line]))
            if len(cells) != len(fields):
                raise CoverageStop("STOP_V5_TRAIN_ROW_SCHEMA")
            row = dict(zip(fields, cells, strict=True))
            if row["date"] != date or not ("20260201" <= date <= "20260913"):
                raise CoverageStop("STOP_V5_TRAIN_DATE")
            if row["valid_result"] != "True" or row["current_top5"] != "True":
                raise CoverageStop("STOP_V5_TRAIN_POPULATION")
            rows.append(row)
            dates.add(date)
    if not rows or max(dates) >= month or len({row["row_id"] for row in rows}) != len(rows):
        raise CoverageStop("STOP_V5_TRAIN_TEMPORAL_OR_IDENTITY")
    return rows, sorted(dates)


def _eval_rows(month: str, sources: list[dict], columns: list[str]) -> tuple[list[dict], list[dict]]:
    rows = []
    source_records = []
    for source in sources:
        if not source["date"].startswith(month):
            continue
        path = Path(source["path"])
        if sha(path) != source["sha256"]:
            raise CoverageStop("STOP_V5_PRE_SOURCE_SHA")
        value = json.loads(path.read_text(encoding="utf-8"))
        if set(value) == {"generated_rows", "race_index"}:
            for item in value["generated_rows"]:
                if item["date"] != source["date"] or not item["top5"]:
                    continue
                values = item["values"]
                row = {key: str(values[key]) for key in core.SEMANTIC}
                row.update({"row_id": item["date"] + ":" + item["race_id"] + ":" + str(item["horse_number"]),
                            "date": item["date"], "race_id": item["race_id"],
                            "horse_number": str(item["horse_number"]), "horse_name": item["horse_name"],
                            "current_top5": "True", "valid_result": "True",
                            "actual_top3": "0", "adjusted_score_gap_to_top": str(values["adjusted_score_gap_to_top"])})
                vector, _ = core.matrix([row], columns)
                row["_feature_vector"] = vector[0]
                rows.append(row)
        elif set(value) == {"excludes", "files", "schema_version"}:
            for entry in value["files"]:
                race_path = path.parent / entry["relative_path"]
                if sha(race_path) != entry["sha256"]:
                    raise CoverageStop("STOP_V5_RACE_SOURCE_SHA")
                if not race_path.name.startswith("race_") or not race_path.name.endswith("_prediction.json"):
                    continue
                race = json.loads(race_path.read_text(encoding="utf-8"))
                rid = race["race_id"]
                if not rid.startswith("race_" + source["date"] + "_"):
                    raise CoverageStop("STOP_V5_RACE_DATE")
                trace = {int(item["horse_number"]): item for item in race["buy_gate_trace"]["horses"]}
                state = race["buy_gate_trace"]["race"]["shadow_race_state"]
                for horse in race["top5"]:
                    number = int(horse["horse_number"])
                    t = trace[number]
                    rows.append({"row_id": source["date"] + ":" + rid + ":" + str(number),
                                 "date": source["date"], "race_id": rid,
                                 "horse_number": str(number), "horse_name": horse["horse_name"],
                                 "shadow_ai_rank": str(t["shadow_ai_rank"]),
                                 "risk_guard_pass": str(t["risk_guard_pass"]),
                                 "_feature_vector": np.asarray(daily.vector(horse, t, state, rid + ":" + str(number)), dtype=float)})
        else:
            raise CoverageStop("STOP_V5_PRE_SOURCE_SCHEMA")
        source_records.append({"date": source["date"], "path": str(path.resolve()), "sha256": source["sha256"]})
    if len({row["row_id"] for row in rows}) != len(rows):
        raise CoverageStop("STOP_V5_EVAL_DUPLICATE")
    return rows, source_records


def train_h1_v5(phase1_path: Path, output_dir: Path) -> dict:
    if output_dir.exists():
        raise CoverageStop("STOP_OUTPUT_EXISTS")
    phase1 = json.loads(phase1_path.read_text(encoding="utf-8"))
    if phase1.get("result_access_count") != 0 or phase1.get("evidence_credit") != 0:
        raise CoverageStop("STOP_PHASE1_ROLE")
    protocol = load_protocol()
    dataset_sha = sha(DATASET)
    expected_dataset_sha = json.loads((DATASET.parent / "training_manifest.json").read_text(encoding="utf-8"))["dataset_sha256"]
    if dataset_sha != expected_dataset_sha:
        raise CoverageStop("STOP_V5_DATASET_SHA")
    current_sources = [row for row in phase1["sources"] if row["block"] == "H1" and row["lane"] == "CURRENT"]
    if len(current_sources) != 53:
        raise CoverageStop("STOP_V5_CURRENT_SOURCE_DATES")
    columns = core.transformed_columns()
    prepared = []
    for month in MONTHS:
        train, train_dates = _prior_training_rows(month)
        ev, sources = _eval_rows(month, current_sources, columns)
        if not ev or any(row["date"][:6] != month for row in ev):
            raise CoverageStop("STOP_V5_EVAL_SCOPE:" + month)
        prepared.append((month, train, train_dates, ev, sources))
    output_dir.mkdir(parents=True, exist_ok=False)
    selected = []
    folds = []
    for month, train, train_dates, ev, sources in prepared:
        scaler, model, _ = core.fit(train, columns)
        x = np.asarray([row["_feature_vector"] for row in ev], dtype=float)
        probabilities = model.predict_proba(scaler.transform(x))[:, 1]
        by_race = defaultdict(list)
        for row, probability in zip(ev, probabilities, strict=True):
            by_race[row["race_id"]].append({"horse_number": int(row["horse_number"]),
                                            "horse_name": row["horse_name"],
                                            "current_top5": True,
                                            "shadow_ai_rank": float(row["shadow_ai_rank"]),
                                            "risk_guard_pass": row["risk_guard_pass"] == "True",
                                            "p_top3": float(probability)})
        count = 0
        for rid, horses in sorted(by_race.items()):
            date = rid.split("_")[1]
            for horse in select_rows(horses, protocol["tau"]):
                selected.append({"block": "H1", "lane": "INDEPENDENT_V5", "date": date,
                                 "race_id": rid, "horse_number": horse["horse_number"],
                                 "horse_name": horse["horse_name"], "p_top3": horse["p_top3"],
                                 "model_version": "RESEARCH_CHRONOLOGICAL_" + month,
                                 "source_role": "RESEARCH_WALK_FORWARD_NON_EVIDENTIAL"})
                count += 1
        model_path = output_dir / (month + "_model.joblib")
        scaler_path = output_dir / (month + "_scaler.joblib")
        joblib.dump(model, model_path)
        joblib.dump(scaler, scaler_path)
        folds.append({"evaluation_month": month, "training_dates": train_dates,
                      "training_end": max(train_dates), "training_rows": len(train),
                      "evaluation_rows": len(ev), "evaluation_races": len(by_race),
                      "selected_count": count, "pre_sources": sources,
                      "model_path": str(model_path.resolve()), "model_sha256": sha(model_path),
                      "scaler_path": str(scaler_path.resolve()), "scaler_sha256": sha(scaler_path)})
    result = {"schema_version": "HISTORICAL_V5_CHRONOLOGICAL_PHASE1_V1",
              "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
              "role": "DEVELOPMENT_ONLY_NON_EVIDENTIAL", "evidence_credit": 0,
              "evaluation_result_label_access": 0, "training_label_source": str(DATASET.resolve()),
              "training_dataset_sha256": dataset_sha, "phase1_sha256": sha(phase1_path),
              "code_sha256": sha(Path(__file__)), "core_fit_sha256": sha(Path(core.__file__)),
              "selection_code_sha256": sha(Path(select_rows.__code__.co_filename)),
              "protocol_sha256": sha(ROOT / "docs/independent_race_selection_prospective_protocol_v1.json"),
              "fixed_tau": protocol["tau"], "folds": folds,
              "selected_count": len(selected), "selected_horses": selected,
              "phase2_status": "NOT_AUTHORIZED"}
    with (output_dir / "selection.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    return result
