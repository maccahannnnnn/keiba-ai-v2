"""One-date, result-blind analysis adapter. Never creates formal PRE authority."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import review
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from review import frozen_pl_v1_jockey_offset_provisional_v1 as j
from review import pl_same_volume_reselection_shadow_v1 as exp
from review.formal_pre_authority_helper_v2 import previous_exp024_fingerprint

ROOT = Path(__file__).resolve().parents[1]
DATE = "20261108"
OUT = ROOT / "reports/20261108_analysis_only_v1"
CURRENT = OUT / "current"
PL = OUT / "pl_forward_prediction.json"
DE = ROOT / "data/raw/prediction_input/DE261108.CSV"
DS = ROOT / "data/raw/prediction_input/DS261108.CSV"
E1_MODULE = Path("C:/Users/hikar/.codex/worktrees/e1-full-field-allocation-prospective-shadow-v1/keiba AI/review/e1_full_field_allocation_prospective_shadow_v1.py")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_new(path: Path, value):
    if path.exists():
        raise RuntimeError("STOP_OUTPUT_EXISTS:" + str(path))
    path.write_bytes(j.canonical(value))


def main():
    if any((OUT / name).exists() for name in ("pl_jockey_analysis_only.json", "e1_analysis_only.json")):
        raise RuntimeError("STOP_ANALYSIS_OUTPUT_EXISTS")
    model, beta = j.verify_identity()
    cm_path = CURRENT / "prediction_manifest.json"
    cm = load(cm_path)
    for row in cm["files"]:
        if sha(CURRENT / row["relative_path"]) != row["sha256"]:
            raise RuntimeError("STOP_CURRENT_SHA")
    im_path = CURRENT / "input_manifest.json"
    im = load(im_path)
    for kind, path in (("DE", DE), ("DS", DS)):
        source = im["sources"][kind]
        if (ROOT / str(source["path"]).replace("\\", "/")).resolve() != path.resolve() or sha(path) != source["sha256"]:
            raise RuntimeError("STOP_INPUT_SHA:" + kind)
    if load(CURRENT / "provenance.json").get("result_data_access_count") != 0:
        raise RuntimeError("STOP_CURRENT_RESULT_ACCESS")
    payloads = [load(CURRENT / x["artifact"]) for x in load(CURRENT / "race_index.json")["race_index"]]
    if len(payloads) != 21 or any(p["race_id"].split("_")[1] != DATE for p in payloads):
        raise RuntimeError("STOP_RACE_SET")
    expected = {(p["race_id"], int(h["horse_number"])) for p in payloads for h in p["ranked_results"]}
    if len(expected) != 300:
        raise RuntimeError("STOP_HORSE_SET")
    pl = load(PL)
    if pl.get("model_sha256") != j.MODEL_SHA or pl.get("input_pre_artifact_sha256") != sha(cm_path) or pl.get("result_fields_used") is not False:
        raise RuntimeError("STOP_PL_AUTHORITY")
    if {r["race_id"] for r in pl["races"]} != {p["race_id"] for p in payloads} or any(r["inference_status"] != "AVAILABLE" for r in pl["races"]):
        raise RuntimeError("STOP_PL_RACE_SET")
    by_pl = defaultdict(list)
    for h in pl["horses"]:
        by_pl[h["race_id"]].append(h)
    if {(rid, int(h["horse_number"])) for rid, rows in by_pl.items() for h in rows} != expected:
        raise RuntimeError("STOP_PL_HORSE_SET")
    prior = j.validate_formal_manifest(DATE, require_target_entry=False)
    targets, today = j._snapshot_records(DATE, DE, DS, expected)
    _, history, _ = j.historical.history_pool()
    history = {d: rows for d, rows in history.items() if d <= DATE}
    for entry in prior:
        prior_date = entry["date"]
        prior_root = (ROOT / entry["current_pre_path"]).parent
        prior_source = load(ROOT / entry["input_manifest_path"])["sources"]["DE"]
        prior_de = ROOT / str(prior_source["path"]).replace("\\", "/")
        if sha(prior_de) != prior_source["sha256"]:
            raise RuntimeError("STOP_PRIOR_DE_SHA:" + prior_date)
        scope = {(x["race_id"], int(h["horse_number"])) for x in load(prior_root / "race_index.json")["race_index"]
                 for h in load(prior_root / x["artifact"])["ranked_results"]}
        _, records = j._snapshot_records(prior_date, prior_de, ROOT / entry["ds_snapshot_path"], scope)
        history[prior_date] = records
    history[DATE] = today
    features = j.jockey.feature_map_asof(targets, history)
    if set(features) != {(DATE, rid, num) for rid, num in expected}:
        raise RuntimeError("STOP_JOCKEY_FEATURE_COVERAGE")
    plj_races = [j.selection_for_race(p, by_pl[p["race_id"]], features, model, beta)
                 for p in sorted(payloads, key=lambda p: p["race_id"])]
    if any(r["candidate_k"] != r["current_k"] for r in plj_races):
        raise RuntimeError("STOP_PLJ_K")
    plj = {"date": DATE, "role": "ANALYSIS_ONLY", "formal_evidence": False,
           "target_ds_role": "UNFROZEN_ANALYSIS_INPUT", "result_access_count": 0,
           "current_manifest_sha256": sha(cm_path), "pl_prediction_sha256": sha(PL),
           "de_sha256": sha(DE), "ds_sha256": sha(DS), "model_sha256": j.MODEL_SHA,
           "jockey_beta_sha256": j.BETA_SHA, "jockey_beta": beta,
           "formal_prior_snapshot_manifest_sha256": sha(j.FORMAL_SNAPSHOT_MANIFEST),
           "prior_registered_dates": [x["date"] for x in prior], "races": plj_races}

    exp_selection = exp.build_pre(CURRENT, ROOT / "knowledge", previous_environment_fingerprint=previous_exp024_fingerprint(DATE))
    spec = importlib.util.spec_from_file_location("analysis_only_e1_frozen", E1_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("STOP_E1_MODULE")
    review.__path__.append(str(E1_MODULE.parent))
    e1 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e1)
    e1.verify_frozen_authorities()
    horses, comparator, n = e1.exp024_inputs(exp_selection, DATE)
    selected = e1.allocate(horses, n)
    if n != sum(len(p["buys"]) for p in payloads):
        raise RuntimeError("STOP_E1_N")
    e1_result = {"date": DATE, "role": "ANALYSIS_ONLY", "formal_evidence": False,
                 "result_access_count": 0, "current_manifest_sha256": sha(cm_path),
                 "pl_prediction_sha256": sha(PL), "exp024_calculation_role": "IN_MEMORY_ANALYSIS_ONLY",
                 "e1_runner_sha256": sha(E1_MODULE), "selected_n": n,
                 "comparator": comparator, "selected": selected,
                 "selection_reason": "Frozen E1 global PL probability order, max 3 per race, daily N equal Current BUY count"}
    now = datetime.now(timezone(timedelta(hours=9)))
    timing = {"analysis_execution_time_jst": now.isoformat(),
              "first_start_reference": "2026-11-08T09:45:00+09:00",
              "first_start_reference_role": "HUMAN_STATED_NOT_FORMAL_SNAPSHOT_VERIFIED",
              "before_stated_first_start": now < datetime(2026, 11, 8, 9, 45, tzinfo=timezone(timedelta(hours=9)))}
    plj.update(timing)
    e1_result.update(timing)
    save_new(OUT / "pl_jockey_analysis_only.json", plj)
    save_new(OUT / "e1_analysis_only.json", e1_result)
    print(json.dumps({"pl_jockey_selected": sum(r["candidate_k"] for r in plj_races),
                      "pl_jockey_fallback_races": [r["race_id"] for r in plj_races if r["provisional_fallback_race"]],
                      "e1_selected": len(selected), "analysis_execution_time_jst": now.isoformat(),
                      "before_stated_first_start": timing["before_stated_first_start"],
                      "pl_jockey_sha256": sha(OUT / "pl_jockey_analysis_only.json"),
                      "e1_sha256": sha(OUT / "e1_analysis_only.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
