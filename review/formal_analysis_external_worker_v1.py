"""Read-only calculation worker for isolated E1 and A_new analysis.

Only called in a child process. It writes JSON to stdout, never to a PRE path.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


E1_ROOT = Path("C:/Users/hikar/.codex/worktrees/e1-full-field-allocation-prospective-shadow-v1/keiba AI")
A_NEW_ROOT = Path("C:/Users/hikar/.codex/worktrees/a-new-prospective-shadow-v1/keiba AI")


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("STOP_EXTERNAL_MODULE_LOAD:" + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def calculate_e1(payload: dict) -> dict:
    module = _module(E1_ROOT / "review/e1_full_field_allocation_prospective_shadow_v1.py", "_e1_analysis_worker")
    module.verify_frozen_authorities()
    date = payload["date"]
    horses, comparator, n = module.exp024_inputs(payload["exp024"], date)
    if n != payload["current_n"] or len(horses) != payload["horse_count"]:
        raise RuntimeError("STOP_E1_ANALYSIS_POPULATION")
    selected = module.allocate(horses, n)
    if len(selected) != n or any(sum(x["race_id"] == rid for x in selected) > 3
                                 for rid in {x["race_id"] for x in selected}):
        raise RuntimeError("STOP_E1_ANALYSIS_ALLOCATION")
    return {"date": date, "lane": "E1", "role": "ANALYSIS_ONLY",
            "daily_n": n, "eligible_races": sorted({x["race_id"] for x in horses}),
            "selected_horses": selected, "exp024_comparator_horses": comparator,
            "frozen_pl_model_sha256": module.FROZEN_PL_SHA,
            "result_access_count": 0}


def calculate_a_new(payload: dict) -> dict:
    import numpy as np

    module = _module(A_NEW_ROOT / "review/a_new_prospective_shadow_v1.py", "_a_new_analysis_worker")
    date = payload["date"]
    model, model_sha = module._model_authority()
    feature = module._feature_module()
    current_root = Path(payload["current_root"])
    current_payloads, _ = module._current_payloads(current_root, date)
    plj = payload["pl_jockey"]
    if (plj.get("date") != date or plj.get("result_access_count") != 0 or
            plj.get("current_pre_sha256") != module.sha(current_root / "prediction_manifest.json") or
            plj.get("model_sha256") != module.FROZEN_MODEL_SHA or
            plj.get("beta") != module.BETA or
            plj.get("beta_source_sha256") != module.BETA_SHA):
        raise RuntimeError("STOP_A_NEW_PL_JOCKEY_AUTHORITY")
    formal_races = {r["race_id"]: r for r in plj["races"]}
    by_payload = {r["race_id"]: r for r in current_payloads}
    if (len(formal_races) != len(plj["races"]) or
            len(by_payload) != len(current_payloads) or set(formal_races) != set(by_payload)):
        raise RuntimeError("STOP_A_NEW_RACE_SET")
    records_by_race = {rid: module.forward._payload_records(row, date)
                       for rid, row in by_payload.items()}
    target_rows = [{"date": date, "race_id": rid,
                    "horse_number": row["horse_number"], "horse_name": row["horse_name"]}
                   for rid, records in records_by_race.items() for row in records]
    s_b, feature_audit = feature.generate(target_rows)
    if feature_audit.get("result_access_count") != 0:
        raise RuntimeError("STOP_A_NEW_FEATURE_RESULT_ACCESS")
    mean = np.asarray(model["scaler"]["base_mean"] + model["scaler"]["S_B_mean"], dtype=float)
    scale = np.asarray(model["scaler"]["base_scale"] + model["scaler"]["S_B_std"], dtype=float)
    coefficients = np.asarray(model["coefficients"], dtype=float)
    output_races = []
    for rid in sorted(formal_races):
        formal = formal_races[rid]
        records = records_by_race[rid]
        current = sorted(int(row["horse_number"]) for row in by_payload[rid]["buys"])
        k = len(current)
        if (formal["current_k"] != k or formal["candidate_k"] != k or
                sorted(formal["current_selected_horses"]) != current):
            raise RuntimeError("STOP_A_NEW_CURRENT_VOLUME")
        if formal["provisional_fallback_race"]:
            selected = list(current)
            horse_rows = []
        else:
            formal_horses = {int(h["horse_number"]): h for h in formal["horses"]}
            if set(formal_horses) != {int(r["horse_number"]) for r in records}:
                raise RuntimeError("STOP_A_NEW_JOCKEY_FIELD")
            raw_matrix = np.asarray([list(r["vector"][:19]) + s_b[(date, rid, int(r["horse_number"]))]
                                     for r in records], dtype=object)
            numerical = np.asarray([[np.nan if v is None else float(v) for v in row]
                                    for row in raw_matrix], dtype=float)
            x = np.nan_to_num((numerical - mean) / scale, nan=0.0)
            if x.shape[1] != 26 or not np.all(np.isfinite(x)):
                raise RuntimeError("STOP_A_NEW_FEATURE_MATRIX")
            lifts = np.asarray([float(formal_horses[int(r["horse_number"])]["jockey_top3_lift"])
                                for r in records])
            if not np.all(np.isfinite(lifts)):
                raise RuntimeError("STOP_A_NEW_JOCKEY_LIFT")
            utility = x @ coefficients + module.BETA * lifts
            probabilities, mass = module.history._top3_from_utility(utility)
            if abs(mass - 3) > 1e-8:
                raise RuntimeError("STOP_A_NEW_PROBABILITY_MASS")
            ordered = sorted(range(len(records)),
                             key=lambda i: (-float(probabilities[i]), int(records[i]["horse_number"])))
            selected = [int(records[i]["horse_number"]) for i in ordered[:k]]
            horse_rows = [{"horse_number": int(r["horse_number"]), "horse_name": r["horse_name"],
                           "a_new_p_top3": float(probabilities[i]), "a_new_rank": ordered.index(i) + 1,
                           "a_new_utility": float(utility[i]), "formal_jockey_top3_lift": float(lifts[i])}
                          for i, r in enumerate(records)]
        output_races.append({"race_id": rid, "current_k": k,
                             "a0_selected_horses": list(formal["candidate_selected_horses"]),
                             "a_new_selected_horses": selected,
                             "fallback": bool(formal["provisional_fallback_race"]),
                             "a0_horses": list(formal["horses"]), "horses": horse_rows})
    selected_count = sum(len(r["a_new_selected_horses"]) for r in output_races)
    if selected_count != plj["candidate_selected_horse_count"]:
        raise RuntimeError("STOP_A_NEW_SELECTED_COUNT")
    return {"date": date, "lane": "A_NEW", "role": "ANALYSIS_ONLY",
            "a_new_model_sha256": model_sha,
            "feature_generation_code_sha256": module.FEATURE_SHA,
            "jockey_authority_sha256": module.BETA_SHA,
            "source_identity": feature_audit["source"],
            "selected_count": selected_count, "races": output_races,
            "result_access_count": 0}


def main() -> None:
    payload = json.load(sys.stdin)
    mode = payload.get("mode")
    if mode == "e1":
        result = calculate_e1(payload)
    elif mode == "a_new":
        result = calculate_a_new(payload)
    else:
        raise RuntimeError("STOP_UNKNOWN_ANALYSIS_WORKER_MODE")
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
