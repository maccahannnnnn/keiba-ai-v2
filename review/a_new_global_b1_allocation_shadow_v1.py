"""Independent A_new probability / B1 allocation PRE shadow; no model fit or Result read."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from review import b1_prospective_diagnostic_v1 as b1


ROOT = Path(__file__).resolve().parents[1]
ANEW_ROOT = Path("C:/Users/hikar/.codex/worktrees/a-new-prospective-shadow-v1/keiba AI")
LANE = "A_NEW_GLOBAL_B1_ALLOCATION_SHADOW"
MODEL_SHA = "730449f2eda2f03e4fe8c6e4450bc772aea1baf4df842b21e71b3666df08d775"
ANEW_RUNNER_SHA = "ec5d53cecf354abcc092196b2b38c6d1373ac2bb98bfe549e4d512c06734ab92"
ANEW_FEATURE_SHA = "8c3afd880ff0a8ed17deb26bd6cf98c8e529f6ffe93c829fa73d75d46abb7d1c"
B1_CODE_SHA = "04432c46a723bab462937eb42e130d159aacf02109d47872fc3a671b8b152eb3"
TRAINING_ROWS_SHA = "f804c686396e6e606280e75886d854c344978a508fc1f75e1b1146af4c0eff4f"


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    if not path.is_file():
        raise Stop("STOP_REQUIRED_FILE_MISSING:" + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Stop("STOP_REQUIRED_JSON:" + str(path)) from error


def canonical(value: object) -> bytes:
    return b1.canonical(value)


def moment(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise Stop("STOP_FREEZE_TIME_SCHEMA") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise Stop("STOP_FREEZE_TIME_UNZONED")
    return result


def model_authority(a_root: Path) -> dict:
    model_path = a_root / "models/a_new_prospective_shadow_v1/a_new_final_model.json"
    manifest_path = a_root / "reports/a_new_prospective_shadow_v1/a_new_model_manifest.json"
    feature_path = a_root / "review/a_new_s_b_features_v1.py"
    runner_path = a_root / "review/a_new_prospective_shadow_v1.py"
    if (sha(model_path) != MODEL_SHA or sha(feature_path) != ANEW_FEATURE_SHA or
            sha(runner_path) != ANEW_RUNNER_SHA or sha(Path(b1.__file__)) != B1_CODE_SHA):
        raise Stop("STOP_FROZEN_CODE_OR_MODEL_SHA")
    model, manifest = read(model_path), read(manifest_path)
    if (manifest.get("model_sha256") != MODEL_SHA or model.get("model") != "A_NEW_FINAL" or
            model.get("training_cutoff") != "2026-09-13" or
            model.get("training_rows_sha256") != TRAINING_ROWS_SHA or
            model.get("feature_names", [])[19:] != ["PRIZE_LOG_MEAN5", "PRIZE_LOG_MAX5", "REST_LOG_DAYS",
                                                  "CARRIED_DIFF", "SEX_FEMALE", "SEX_GELDING", "AGE"]):
        raise Stop("STOP_A_NEW_MODEL_AUTHORITY")
    return {"model_sha256": MODEL_SHA, "model_manifest_sha256": sha(manifest_path),
            "feature_semantics_sha256": model["feature_semantics_sha256"],
            "feature_generation_code_sha256": ANEW_FEATURE_SHA,
            "training_rows_sha256": TRAINING_ROWS_SHA, "training_cutoff": model["training_cutoff"],
            "training_valid_rows": model["scaler"]["valid_training_rows"]}


def derive(date: str, *, root: Path = ROOT, a_root: Path = ANEW_ROOT) -> dict:
    """Validate both frozen PRE sources and reuse select_b1 without modifying a lane."""
    if not re.fullmatch(r"20\d{6}", date) or date < "20261121":
        raise Stop("STOP_SHADOW_DATE_SCOPE")
    model = model_authority(a_root)
    current = root / f"reports/prospective_prediction_{date}_formal_trace_v1"
    anew = a_root / f"reports/a_new_prospective_shadow_v1/daily_pre/{date}"
    current_manifest_path = current / "prediction_manifest.json"
    current_input_path = current / "input_manifest.json"
    current_freeze_path = current / "formal_freeze_attestation.json"
    current_index_path = current / "race_index.json"
    a_selection_path = anew / "selection.json"
    a_freeze_path = anew / "freeze_manifest.json"
    current_manifest = read(current_manifest_path)
    listed = current_manifest.get("files")
    if not isinstance(listed, list) or not listed:
        raise Stop("STOP_CURRENT_PREDICTION_MANIFEST")
    listed_names = set()
    for item in listed:
        name = item.get("relative_path") if isinstance(item, dict) else None
        path = (current / name).resolve() if isinstance(name, str) else current.parent
        if name in listed_names or path.parent != current.resolve() or sha(path) != item.get("sha256"):
            raise Stop("STOP_CURRENT_PREDICTION_PAYLOAD_SHA")
        listed_names.add(name)
    if not {"input_manifest.json", "race_index.json"}.issubset(listed_names):
        raise Stop("STOP_CURRENT_PREDICTION_MANIFEST")
    input_manifest = read(current_input_path)
    current_freeze = read(current_freeze_path)
    index = read(current_index_path).get("race_index")
    a_selection, a_freeze = read(a_selection_path), read(a_freeze_path)
    if input_manifest.get("date") != date or not isinstance(index, list) or not index:
        raise Stop("STOP_CURRENT_INPUT_OR_RACE_INDEX")
    sources = b1.verified_input_sources(current, input_manifest)
    first_relative = current_freeze.get("first_start_evidence_path")
    first_path = (root / first_relative).resolve() if isinstance(first_relative, str) else root.parent
    if not first_path.is_relative_to(root.resolve()):
        raise Stop("STOP_FIRST_START_PATH_SCOPE")
    first = read(first_path)
    cutoff = moment(first.get("first_start_at"))
    if (first.get("date") != date or first.get("result_access", 0) != 0 or
            current_freeze.get("date") != date or current_freeze.get("result_access_count") != 0 or
            current_freeze.get("prediction_manifest_sha256") != sha(current_manifest_path) or
            current_freeze.get("first_start_evidence_sha256") != sha(first_path) or
            current_freeze.get("first_start_at") != first.get("first_start_at") or
            moment(current_freeze.get("freeze_timestamp_utc")) >= cutoff):
        raise Stop("STOP_CURRENT_FREEZE_AUTHORITY")
    if (a_selection.get("date") != date or a_selection.get("a_new_model_sha256") != MODEL_SHA or
            a_selection.get("feature_generation_code_sha256") != ANEW_FEATURE_SHA or
            a_selection.get("training_rows_sha256") != TRAINING_ROWS_SHA or
            a_selection.get("current_pre_sha256") != sha(current_manifest_path) or
            a_selection.get("current_input_manifest_sha256") != sha(current_input_path) or
            a_selection.get("result_access_count_at_pre_freeze") != 0 or
            a_selection.get("evidence_date") is not True or a_selection.get("fallback_race_count") != 0 or
            a_freeze.get("date") != date or a_freeze.get("status") != "FROZEN_PRE" or
            a_freeze.get("selection_sha256") != sha(a_selection_path) or
            a_freeze.get("result_access_count_at_freeze") != 0 or
            moment(a_freeze.get("freeze_timestamp_utc")) >= cutoff):
        raise Stop("STOP_A_NEW_FROZEN_AUTHORITY")
    input_shas = {kind: item["sha256"] for kind, item in sources.items()}
    observed = {item.get("kind"): item.get("sha256") for item in a_selection.get("source_identity", [])}
    if len(a_selection.get("source_identity", [])) != 3 or observed != input_shas:
        raise Stop("STOP_A_NEW_INPUT_IDENTITY")
    current_by_id = {row.get("race_id"): row for row in index if isinstance(row, dict)}
    a_races = a_selection.get("races")
    if (len(current_by_id) != len(index) or not isinstance(a_races, list) or
            len(a_races) != len(index) or a_selection.get("race_count") != len(index)):
        raise Stop("STOP_RACE_POPULATION_MISMATCH")
    b1_races = []
    horse_count = 0
    for race in a_races:
        race_id, horses = race.get("race_id"), race.get("horses")
        indexed = current_by_id.get(race_id)
        if indexed is None or not isinstance(horses, list):
            raise Stop("STOP_RACE_POPULATION_MISMATCH")
        if indexed.get("artifact") not in listed_names:
            raise Stop("STOP_CURRENT_PREDICTION_MANIFEST")
        payload = read(current / indexed["artifact"])
        current_horses = {(int(h["horse_number"]), h["horse_name"]) for h in payload["ranked_results"]}
        a_horses = {(int(h["horse_number"]), h["horse_name"]) for h in horses}
        if (payload.get("race_id") != race_id or len(a_horses) != len(horses) or
                a_horses != current_horses or len(a_horses) != int(indexed["horse_count"]) or
                int(race.get("current_k", -1)) != int(indexed["buy_count"])):
            raise Stop("STOP_HORSE_OR_CURRENT_K_MISMATCH:" + str(race_id))
        horse_count += len(horses)
        b1_races.append({"race_id": race_id, "current_k": int(indexed["buy_count"]),
                         "horses": [{"horse_number": h["horse_number"], "horse_name": h["horse_name"],
                                     "candidate_p_top3": h["a_new_p_top3"]} for h in horses]})
    if set(current_by_id) != {race["race_id"] for race in b1_races}:
        raise Stop("STOP_RACE_POPULATION_MISMATCH")
    daily_n = sum(race["current_k"] for race in b1_races)
    selected = b1.select_b1(b1_races, daily_n)
    if len(selected) != daily_n or max(Counter(h["race_id"] for h in selected).values(), default=0) > 3:
        raise Stop("STOP_ALLOCATION_INVARIANT")
    return {"date": date, "lane": LANE, "role": "PROSPECTIVE_SHADOW_PRE_PENDING_FINAL_APPROVAL",
            "prospective_evidence_credit": 0, "formal_buy_authority": False,
            "allocation_rule": "EXISTING_B1_SELECT_B1", "b1_code_sha256": B1_CODE_SHA,
            "tie_break": ["a_new_p_top3_desc", "canonical_race_id_string_asc", "horse_number_integer_asc"],
            "daily_current_buy_n": daily_n, "selected_count": len(selected), "max_selected_per_race": 3,
            "race_count": len(index), "horse_count": horse_count,
            "selected_horses": [{"race_id": h["race_id"], "horse_number": h["horse_number"],
                                 "horse_name": h["horse_name"], "a_new_p_top3": h["pl_jockey_p_top3"],
                                 "global_rank": h["global_rank"], "selection_order": h["selection_order"],
                                 "field_size": h["field_size"]} for h in selected],
            "a_new_model": model, "a_new_runner_sha256": ANEW_RUNNER_SHA,
            "b1_reference_model_sha256": b1.PL_MODEL_SHA,
            "b1_reference_jockey_beta_sha256": b1.JOCKEY_BETA_SHA,
            "input_sha256": input_shas, "current_manifest_sha256": sha(current_manifest_path),
            "current_input_manifest_sha256": sha(current_input_path),
            "current_freeze_sha256": sha(current_freeze_path),
            "a_new_selection_sha256": sha(a_selection_path), "a_new_freeze_sha256": sha(a_freeze_path),
            "first_start_authority_sha256": sha(first_path), "freeze_deadline": cutoff.isoformat(),
            "official_time_verified": first.get("official_time_verified", False),
            "result_access_count": 0, "odds_used": False, "popularity_used": False}


def freeze_pre(date: str, *, root: Path = ROOT, a_root: Path = ANEW_ROOT,
               now: datetime | None = None) -> dict:
    selection = derive(date, root=root, a_root=a_root)
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed >= moment(selection["freeze_deadline"]):
        raise Stop("STOP_SHADOW_AFTER_FREEZE_DEADLINE")
    result_dir = root / "data/raw/target/daily_result_list"
    if any((result_dir / f"{prefix}_{date}.csv").exists() for prefix in ("馬番順着順", "着順馬番")):
        raise Stop("STOP_SHADOW_RESULT_ALREADY_PRESENT")
    output = root / f"reports/a_new_global_b1_allocation_shadow_v1/daily_pre/{date}"
    if output.exists():
        raise Stop("STOP_SHADOW_OUTPUT_EXISTS")
    output.mkdir(parents=True, exist_ok=False)
    selection_path, freeze_path = output / "selection.json", output / "freeze_manifest.json"
    selection["generated_at_utc"] = observed.astimezone(timezone.utc).isoformat()
    with selection_path.open("xb") as stream:
        stream.write(canonical(selection))
    sealed_at = now or datetime.now(timezone.utc)
    if sealed_at >= moment(selection["freeze_deadline"]):
        raise Stop("STOP_SHADOW_FREEZE_DEADLINE_CROSSED")
    seal = {"date": date, "lane": LANE, "role": selection["role"],
            "selection_sha256": sha(selection_path), "freeze_timestamp_utc": sealed_at.astimezone(timezone.utc).isoformat(),
            "freeze_deadline": selection["freeze_deadline"], "a_new_model_sha256": MODEL_SHA,
            "b1_code_sha256": B1_CODE_SHA, "result_access_count": 0,
            "prospective_evidence_credit": 0, "formal_buy_authority": False}
    with freeze_path.open("xb") as stream:
        stream.write(canonical(seal))
    return {"status": "FROZEN_SHADOW_PRE", "selection_path": str(selection_path),
            "selection_sha256": sha(selection_path), "freeze_path": str(freeze_path),
            "freeze_sha256": sha(freeze_path), "selected_count": len(selection["selected_horses"])}


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent A_new × B1 allocation shadow PRE")
    parser.add_argument("step", choices=("freeze-pre",))
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    print(json.dumps(freeze_pre(args.date), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
