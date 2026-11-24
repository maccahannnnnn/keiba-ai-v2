"""Result-blind technical E1/B1-style inference from a frozen Rolling V3 candidate.

No PRE freeze, model fit, Production switch, or existing lane mutation occurs here.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from review import b1_prospective_diagnostic_v1 as b1
from review import exp025_offset_pl_raw_history_v1 as top3
from review import frozen_pl_v1_jockey_offset_provisional_v1 as old_plj
from review import pl_forward_shadow_v1 as forward


SOURCE_ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = Path("C:/Users/hikar/.codex/worktrees/rolling-learning-v1/keiba AI")
EXPECTED_FIRST_MODEL_SHA = "15b9ebdd491400bfe09be39798cdb628dd69d7f9c6329bf3a00775b1ea3fe3ce"
LANES = ("E1_ROLLING_V3", "B1_ROLLING_V3")


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    if not path.is_file():
        raise Stop("STOP_MISSING:" + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Stop("STOP_JSON:" + str(path)) from error


def model_snapshot(target_date: str, state_root: Path = STATE_ROOT) -> dict:
    """Bind a single Registry/current version before any probability is calculated."""
    base = state_root / "models/rolling_pl_jockey_v3"
    pointer = read(base / "current.json")
    registry_path = state_root / "reports/rolling_learning_v3/candidate_registry.jsonl"
    try:
        entries = [json.loads(line) for line in registry_path.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, ValueError) as error:
        raise Stop("STOP_REGISTRY") from error
    if not entries or entries[-1].get("event") != "CANDIDATE_ACTIVATED":
        raise Stop("STOP_REGISTRY")
    latest = entries[-1]
    if any(pointer.get(key) != latest.get(key) for key in ("version", "model_sha256", "manifest_sha256", "training_end")):
        raise Stop("STOP_POINTER_REGISTRY_MISMATCH")
    if pointer.get("procedure_id") != "ROLLING_PL_JOCKEY_V3" or target_date <= pointer["training_end"]:
        raise Stop("STOP_MODEL_PIT_OR_PROCEDURE")
    folder = base / "versions" / pointer["version"]
    model_path, manifest_path = folder / "model.json", folder / "manifest.json"
    if sha(model_path) != pointer["model_sha256"] or sha(manifest_path) != pointer["manifest_sha256"]:
        raise Stop("STOP_MODEL_OR_MANIFEST_SHA")
    model, manifest = read(model_path), read(manifest_path)
    if (manifest.get("model_sha256") != pointer["model_sha256"] or
            model.get("training_end") != pointer["training_end"] or
            model.get("procedure_id") != pointer["procedure_id"] or
            model.get("feature_names") != list(forward.FEATURE_NAMES) or
            model.get("trainer_included") is not False):
        raise Stop("STOP_MODEL_SEMANTICS")
    mean = np.asarray(model["scaler_mean"], dtype=float)
    scale = np.asarray(model["scaler_scale"], dtype=float)
    coefficients = np.asarray(model["pl_coefficients"], dtype=float)
    beta = float(model["jockey_beta"])
    if (mean.shape != (21,) or scale.shape != (21,) or coefficients.shape != (19,) or
            not np.isfinite(mean).all() or not np.isfinite(scale).all() or
            not np.isfinite(coefficients).all() or not math.isfinite(beta) or np.any(scale <= 0)):
        raise Stop("STOP_MODEL_NUMERICS")
    return {"version": pointer["version"], "model_sha256": pointer["model_sha256"],
            "manifest_sha256": pointer["manifest_sha256"], "training_end": pointer["training_end"],
            "mean": mean, "scale": scale, "coefficients": coefficients, "jockey_beta": beta}


def probabilities_for_race(payload: dict, lifts_by_horse: dict[int, float], snapshot: dict) -> list[dict]:
    """Use the Rolling V3 21-column scaler, 19 PL coefficients, then optional J."""
    records = forward._payload_records(payload, payload["race_id"].split("_")[1])
    if set(lifts_by_horse) != {r["horse_number"] for r in records}:
        raise Stop("STOP_JOCKEY_HORSE_SET")
    matrix = np.vstack([r["vector"] for r in records])
    utility = ((matrix - snapshot["mean"]) / snapshot["scale"])[:, :19] @ snapshot["coefficients"]
    lifts = np.asarray([lifts_by_horse[r["horse_number"]] for r in records], dtype=float)
    if not np.isfinite(lifts).all():
        raise Stop("STOP_JOCKEY_NONFINITE")
    e1, e1_mass = top3._top3_from_utility(utility)
    b1_probability, b1_mass = top3._top3_from_utility(utility + snapshot["jockey_beta"] * lifts)
    if abs(e1_mass - 3) > 1e-8 or abs(b1_mass - 3) > 1e-8:
        raise Stop("STOP_TOP3_MASS")
    return [{"race_id": payload["race_id"], "horse_number": row["horse_number"],
             "horse_name": row["horse_name"], "jockey_top3_lift": float(lifts[i]),
             "e1_rolling_p_top3": float(e1[i]), "b1_rolling_p_top3": float(b1_probability[i])}
            for i, row in enumerate(records)]


def technical_date(date: str, *, source_root: Path = SOURCE_ROOT, state_root: Path = STATE_ROOT,
                   historical_comparison: bool = False, verify_jockey: bool = True) -> dict:
    """Return two independent selections; historical comparison never earns evidence."""
    if historical_comparison and date not in {"20261114", "20261115"}:
        raise Stop("STOP_HISTORICAL_DATE_SCOPE")
    model = model_snapshot("99999999" if historical_comparison else date, state_root)
    current = source_root / f"reports/prospective_prediction_{date}_formal_trace_v1"
    current_manifest_path = current / "prediction_manifest.json"
    current_manifest = read(current_manifest_path)
    entries = current_manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise Stop("STOP_CURRENT_MANIFEST")
    listed = set()
    for entry in entries:
        name = entry.get("relative_path") if isinstance(entry, dict) else None
        path = (current / name).resolve() if isinstance(name, str) else current.parent
        if name in listed or path.parent != current.resolve() or sha(path) != entry.get("sha256"):
            raise Stop("STOP_CURRENT_PAYLOAD_SHA")
        listed.add(name)
    index = read(current / "race_index.json")["race_index"]
    if "race_index.json" not in listed or "input_manifest.json" not in listed:
        raise Stop("STOP_CURRENT_MANIFEST")
    input_manifest = read(current / "input_manifest.json")
    sources = b1.verified_input_sources(current, input_manifest)
    if input_manifest.get("date") != date or read(current / "provenance.json").get("result_data_access_count") != 0:
        raise Stop("STOP_CURRENT_SOURCE")
    frozen = source_root / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{date}_pre"
    old = read(frozen / "selection.json")
    audit = read(frozen / "provisional_audit.json")
    if (old.get("date") != date or audit.get("selection_sha256") != sha(frozen / "selection.json") or
            old.get("current_pre_sha256") != sha(current_manifest_path) or
            old.get("current_input_manifest_sha256") != sha(current / "input_manifest.json") or
            old.get("jockey_feature_sha256") != old_plj.FEATURE_SHA or
            old.get("fallback_race_count") != 0 or old.get("result_access_count") != 0 or
            audit.get("result_access_count") != 0):
        raise Stop("STOP_FROZEN_JOCKEY_AUTHORITY")
    if verify_jockey:
        rebuilt = old_plj.build_pre(current, source_root / f"reports/pl_forward_shadow_v1/{date}_pre/prediction.json",
                                    Path(sources["DE"]["path"]), Path(sources["DS"]["path"]))
        left = {(r["race_id"], int(h["horse_number"])): float(h["jockey_top3_lift"])
                for r in old["races"] for h in r["horses"]}
        right = {(r["race_id"], int(h["horse_number"])): float(h["jockey_top3_lift"])
                 for r in rebuilt["races"] for h in r["horses"]}
        if left.keys() != right.keys() or any(abs(left[key] - right[key]) > 1e-12 for key in left):
            raise Stop("STOP_JOCKEY_FEATURE_MISMATCH")
    old_races = {r["race_id"]: r for r in old["races"]}
    if len(index) != len(old_races) or {r["race_id"] for r in index} != set(old_races):
        raise Stop("STOP_RACE_SET")
    by_lane = {lane: [] for lane in LANES}
    daily_n = 0
    for item in index:
        if item["artifact"] not in listed:
            raise Stop("STOP_CURRENT_MANIFEST")
        payload = read(current / item["artifact"])
        race_id = item["race_id"]
        frozen_race = old_races[race_id]
        if payload.get("race_id") != race_id or item["buy_count"] != frozen_race["current_k"]:
            raise Stop("STOP_CURRENT_RACE_OR_K")
        lifts = {int(h["horse_number"]): float(h["jockey_top3_lift"]) for h in frozen_race["horses"]}
        rows = probabilities_for_race(payload, lifts, model)
        if (len(rows) != item["horse_count"] or
                {(h["horse_number"], h["horse_name"]) for h in rows} !=
                {(int(h["horse_number"]), h["horse_name"]) for h in frozen_race["horses"]}):
            raise Stop("STOP_HORSE_SET")
        daily_n += item["buy_count"]
        for lane, field in ((LANES[0], "e1_rolling_p_top3"), (LANES[1], "b1_rolling_p_top3")):
            by_lane[lane].append({"race_id": race_id, "current_k": item["buy_count"],
                                  "horses": [{"horse_number": h["horse_number"], "horse_name": h["horse_name"],
                                              "candidate_p_top3": h[field]} for h in rows]})
    selections = {lane: b1.select_b1(races, daily_n) for lane, races in by_lane.items()}
    return {"date": date, "role": "HISTORICAL_TECHNICAL_ONLY" if historical_comparison else "SHADOW_CALCULATION_ONLY",
            "prospective_evidence_credit": 0, "result_access_count": 0,
            "model_version": model["version"], "model_sha256": model["model_sha256"],
            "model_manifest_sha256": model["manifest_sha256"], "training_end": model["training_end"],
            "jockey_beta": model["jockey_beta"], "jockey_source_selection_sha256": sha(frozen / "selection.json"),
            "current_manifest_sha256": sha(current_manifest_path), "input_sha256": {k: v["sha256"] for k, v in sources.items()},
            "race_count": len(index), "horse_count": sum(len(r["horses"]) for r in by_lane[LANES[0]]),
            "daily_current_n": daily_n, "races": by_lane, "selected": selections}


def compare_frozen_date(date: str, *, source_root: Path = SOURCE_ROOT, state_root: Path = STATE_ROOT) -> dict:
    """Read-only new/old selection and probability deltas on training-period dates."""
    data = technical_date(date, source_root=source_root, state_root=state_root,
                          historical_comparison=True, verify_jockey=True)
    if data["model_sha256"] != EXPECTED_FIRST_MODEL_SHA:
        raise Stop("STOP_HISTORICAL_COMPARISON_MODEL_VERSION")
    summary = read(source_root / f"reports/formal_pre_daily/{date}/summary.json")
    old_pl = read(source_root / f"reports/pl_forward_shadow_v1/{date}_pre/prediction.json")
    old_plj = read(source_root / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{date}_pre/selection.json")
    old_b1 = read(source_root / f"reports/formal_pre_daily/{date}/b1_diagnostic/selection.json")
    old_b1_freeze = read(source_root / f"reports/formal_pre_daily/{date}/b1_diagnostic/freeze_manifest.json")
    if (summary.get("status") != "COMPLETE" or old_b1_freeze.get("selection_sha256") !=
            sha(source_root / f"reports/formal_pre_daily/{date}/b1_diagnostic/selection.json")):
        raise Stop("STOP_OLD_LANE_AUTHORITY")
    probability = {lane: { (r["race_id"], int(h["horse_number"])): float(h["candidate_p_top3"])
                           for r in races for h in r["horses"]}
                   for lane, races in data["races"].items()}
    old_e1_probability = {(h["race_id"], int(h["horse_number"])): float(h["pl_top3_probability"])
                          for h in old_pl["horses"]}
    old_b1_probability = {(r["race_id"], int(h["horse_number"])): float(h["candidate_p_top3"])
                          for r in old_plj["races"] for h in r["horses"]}
    if (probability[LANES[0]].keys() != old_e1_probability.keys() or
            probability[LANES[1]].keys() != old_b1_probability.keys()):
        raise Stop("STOP_OLD_NEW_HORSE_POPULATION")
    def identity(rows):
        return {(h["race_id"], int(h["horse_number"])) for h in rows}
    old_e1 = identity(summary["lanes"]["E1"]["selected_horses"])
    old_b1_set = identity(old_b1["selected_horses"])
    new_e1, new_b1 = (identity(data["selected"][lane]) for lane in LANES)
    e1_deltas = [abs(probability[LANES[0]][key] - value) for key, value in old_e1_probability.items()]
    b1_deltas = [abs(probability[LANES[1]][key] - value) for key, value in old_b1_probability.items()]
    return {"date": date, "role": "HISTORICAL_TECHNICAL_ONLY", "model_sha256": data["model_sha256"],
            "race_count": data["race_count"], "horse_count": data["horse_count"],
            "current_n": data["daily_current_n"],
            "e1": {"old_count": len(old_e1), "new_count": len(new_e1), "overlap": len(old_e1 & new_e1),
                   "mean_abs_probability_delta": sum(e1_deltas) / len(e1_deltas),
                   "max_abs_probability_delta": max(e1_deltas)},
            "b1": {"old_count": len(old_b1_set), "new_count": len(new_b1), "overlap": len(old_b1_set & new_b1),
                   "mean_abs_probability_delta": sum(b1_deltas) / len(b1_deltas),
                   "max_abs_probability_delta": max(b1_deltas)},
            "jockey_feature_rows_matched": len(old_b1_probability), "jockey_feature_max_abs_delta": 0.0,
            "result_access_count": 0, "prospective_evidence_credit": 0}
