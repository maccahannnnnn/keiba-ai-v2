"""Frozen-protocol Independent Race Selection PRE shadow; never alters Current AI."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

from review import prospective_three_system_pre_freeze_v1 as daily

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "independent_race_selection_prospective_protocol_v1.json"
MODEL_ROOT = ROOT / "reports" / "ml_v4_buy_selection_model_v5"
JST = timezone(timedelta(hours=9))
RESULT_KEYS = {"actual_finish", "actual_top3", "valid_result", "finish", "result", "payout"}


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_protocol() -> dict:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol["tau"] != 0.3796765822155326 or protocol["tau_037"]["accepted"] is not False:
        raise Stop("STOP_FROZEN_TAU_INVALID")
    model = protocol["model"]
    expected = {"model.joblib": model["model_sha256"], "scaler.joblib": model["scaler_sha256"],
                "feature_schema.json": model["feature_schema_sha256"], "feature_transform_schema.json": model["feature_transform_schema_sha256"]}
    if any(not (MODEL_ROOT / name).is_file() or sha(MODEL_ROOT / name) != digest for name, digest in expected.items()):
        raise Stop("STOP_MODEL_IDENTITY_MISMATCH")
    return protocol


def assert_result_free(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in RESULT_KEYS:
                raise Stop("STOP_RESULT_LEAKAGE")
            assert_result_free(child)
    elif isinstance(value, list):
        for child in value:
            assert_result_free(child)


def select_rows(rows: list[dict], tau: float) -> list[dict]:
    """Pure frozen selection: pool boundary, deterministic order, then cap three."""
    pool = [row for row in rows if row["current_top5"] and row["shadow_ai_rank"] <= 5 and row["risk_guard_pass"] is True and row["p_top3"] >= tau]
    return sorted(pool, key=lambda row: (-row["p_top3"], row["shadow_ai_rank"], row["horse_number"]))[:3]


def _identity(payload: dict) -> tuple[str, int]:
    bits = payload["race_id"].split("_")
    return bits[-2], int(bits[-1].removesuffix("R"))


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def run(target_date: str, current_pre_root: Path, output_root: Path, *, clock_utc: datetime | None = None) -> Path:
    protocol = load_protocol()
    if output_root.exists():
        raise Stop("STOP_OUTPUT_EXISTS")
    instant = datetime.now(timezone.utc) if clock_utc is None else clock_utc.astimezone(timezone.utc)
    execution_date = instant.astimezone(JST).strftime("%Y%m%d")
    if target_date < protocol["human_approval_date"]:
        raise Stop("STOP_START_BOUNDARY_G1")
    if target_date < execution_date:
        raise Stop("STOP_START_BOUNDARY_G2")
    summary = json.loads((current_pre_root / "summary.json").read_text(encoding="utf-8"))
    provenance = json.loads((current_pre_root / "provenance.json").read_text(encoding="utf-8"))
    if summary.get("date") != target_date or provenance.get("target_date") != target_date:
        raise Stop("STOP_START_BOUNDARY_G4")
    generated = datetime.fromisoformat(provenance["generated_at"].replace("Z", "+00:00")).astimezone(JST).strftime("%Y%m%d")
    if generated < protocol["human_approval_date"]:
        raise Stop("STOP_START_BOUNDARY_G3")
    manifest = json.loads((current_pre_root / "prediction_manifest.json").read_text(encoding="utf-8"))
    if any(sha(current_pre_root / e["relative_path"]) != e["sha256"] for e in manifest["files"]):
        raise Stop("STOP_CURRENT_PRE_HASH_MISMATCH")
    model, scaler, model_identity, _ = daily.load_active_daily_v4()
    if model_identity["model_sha256"] != protocol["model"]["model_sha256"]:
        raise Stop("STOP_MODEL_IDENTITY_MISMATCH")
    records, current = [], []
    index = json.loads((current_pre_root / "race_index.json").read_text(encoding="utf-8"))["race_index"]
    for item in index:
        payload = json.loads((current_pre_root / item["artifact"]).read_text(encoding="utf-8"))
        assert_result_free(payload)
        race = payload["buy_gate_trace"]["race"]
        state = race["shadow_race_state"]
        trace = {int(x["horse_number"]): x for x in payload["buy_gate_trace"]["horses"]}
        candidates = []
        for horse in payload["top5"]:
            number = int(horse["horse_number"]); t = trace[number]
            feature = daily.vector(horse, t, state, f"{payload['race_id']}:{number}")
            probability = float(model.predict_proba(scaler.transform(np.asarray([feature], dtype=float)))[0, 1])
            candidates.append({"horse_number": number, "horse_name": horse.get("horse_name"), "current_top5": True,
                               "shadow_ai_rank": daily.safe_rank(t["shadow_ai_rank"], payload["race_id"]), "risk_guard_pass": t["risk_guard_pass"], "p_top3": probability})
        selected = select_rows(candidates, protocol["tau"])
        venue, race_number = _identity(payload)
        records.append({"date": target_date, "race_id": payload["race_id"], "venue": venue, "race_number": race_number,
                        "current_race_state": state, "tau": protocol["tau"], "candidate_horses": candidates,
                        "selected_horses": selected, "race_selected": bool(selected),
                        "selection_reason": "P_TOP3_GTE_TAU_WITHIN_CURRENT_TOP5_RISK_GUARD_VETO" if selected else "NO_CANDIDATE_PASSED_FROZEN_TAU"})
        current.append({"race_id": payload["race_id"], "current_buy_horses": [{"horse_number": int(x["horse_number"]), "horse_name": x.get("horse_name")} for x in payload["ranked_results"] if x.get("buy") is True]})
    output_root.mkdir(parents=True)
    _write(output_root / "selection_manifest.json", {"date": target_date, "protocol_sha256": sha(PROTOCOL), "protocol_role": protocol["role"], "production_authorization": False,
                                                        "source_current_pre": str(current_pre_root.relative_to(ROOT)), "source_prediction_manifest_sha256": sha(current_pre_root / "prediction_manifest.json"),
                                                        "races": records, "current_comparator": current, "result_data_access_count": 0})
    _write(output_root / "summary.json", {"date": target_date, "eligible_races": len(records), "selected_races": sum(x["race_selected"] for x in records),
                                            "selected_horses": sum(len(x["selected_horses"]) for x in records), "natural_volume": True, "result_data_access_count": 0, "production_change": 0})
    _write(output_root / "provenance.json", {"target_date": target_date, "generated_at": instant.isoformat(), "runner": "review/independent_race_selection_prospective_pre.py",
                                               "runner_sha256": sha(Path(__file__)), "protocol_sha256": sha(PROTOCOL), "model_identity": model_identity, "start_boundary": {"G1": "PASS", "G2": "PASS", "G3": "PASS", "G4": "PASS"}})
    files = [p for p in output_root.iterdir() if p.is_file()]
    _write(output_root / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": {p.name: sha(p) for p in files}})
    return output_root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--date", required=True); parser.add_argument("--current-pre", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); print(run(args.date, args.current_pre, args.output))
