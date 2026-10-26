"""PRE-only adapter for the approved, fixed-k1 Current unconverged selector.

This module never imports or opens a Result source. It delegates the selection
rule to the reviewed development selector, without changing its semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from review.current_environment_tree_hash_v1 import tree_hash
from review.current_unconverged_rank1_resolution_shadow_v1 import select

ROOT = Path(__file__).resolve().parents[1]
APPROVAL = ROOT / "docs/KeibaAI_CURRENT_UNCONVERGED_RANK1_PROSPECTIVE_SHADOW_V1_HUMAN_APPROVAL.json"
APPROVAL_SHA = "0192c05d9244a7e4dcc78a4bdfa2e976b7229dc727e34dfda7ab7c706962ad03"
PROTOCOL = ROOT / "docs/KeibaAI_CURRENT_UNCONVERGED_RANK1_PROSPECTIVE_SHADOW_V1_PROTOCOL.md"
PROTOCOL_SHA = "358fa915c21692ea1af9ac49f5e67dc92e12a989e7de0571a6cf505f4028389b"
IMPLEMENTATION = ROOT / "review/current_unconverged_rank1_resolution_shadow_v1.py"
IMPLEMENTATION_SHA = "023f059240f051f199a4a594825c43bb2bea2ff2f552010f5e24cf8d335dfadb"
CURRENT_RUNNER_SHA = "4e7728e8f131e29f488ab33050c20938e8aa271a6dd5753b085daa462c5e1eea"
CURRENT_ADAPTER_SHA = "82419ae7591e6bd550932e464886d81347ee91f6bce38402f0ec28e96707c9d0"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_authority() -> None:
    for path, expected in ((APPROVAL, APPROVAL_SHA), (PROTOCOL, PROTOCOL_SHA),
                           (IMPLEMENTATION, IMPLEMENTATION_SHA),
                           (ROOT / "review/prospective_prediction_runner_v1.py", CURRENT_RUNNER_SHA),
                           (ROOT / "review/target_bulk_prediction_input_adapter_v1.py", CURRENT_ADAPTER_SHA)):
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError("STOP_SHADOW_AUTHORITY_SHA_MISMATCH:" + str(path))


def load_frozen_current(pre_root: Path, target_date: str) -> tuple[list[dict], dict]:
    """Verify a frozen Current PRE manifest, then adapt its complete race rows."""
    verify_authority()
    if not target_date.isdigit() or len(target_date) != 8:
        raise RuntimeError("STOP_TARGET_DATE_FORMAT")
    manifest_path = pre_root / "prediction_manifest.json"
    manifest = _json(manifest_path)
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("STOP_CURRENT_PRE_MANIFEST_EMPTY")
    names = set()
    for entry in entries:
        name = entry["relative_path"]
        if name in names or Path(name).is_absolute() or ".." in Path(name).parts or Path(name).name != name:
            raise RuntimeError("STOP_CURRENT_PRE_MANIFEST_PATH")
        names.add(name)
        if sha(pre_root / name) != entry["sha256"]:
            raise RuntimeError("STOP_CURRENT_PRE_FILE_SHA:" + name)
    if not {"race_index.json", "input_manifest.json", "provenance.json"} <= names:
        raise RuntimeError("STOP_CURRENT_PRE_MANIFEST_REQUIRED_FILES")
    provenance = _json(pre_root / "provenance.json")
    if (provenance.get("target_date") != target_date or
            provenance.get("result_data_access_count") != 0 or
            provenance.get("runner_sha256") != CURRENT_RUNNER_SHA or
            provenance.get("target_bulk_prediction_input_adapter_sha256") != CURRENT_ADAPTER_SHA):
        raise RuntimeError("STOP_CURRENT_PRE_PROVENANCE")
    for area in ("engine", "evaluation", "knowledge"):
        if provenance.get(area + "_tree_sha256") != tree_hash(ROOT / area):
            raise RuntimeError("STOP_CURRENT_PRE_TREE_PROVENANCE:" + area)
    index = _json(pre_root / "race_index.json")["race_index"]
    if not index or len({row["race_id"] for row in index}) != len(index):
        raise RuntimeError("STOP_CURRENT_PRE_RACE_INDEX")
    if names.intersection({"prediction_manifest.json"}):
        raise RuntimeError("STOP_SELF_REFERENTIAL_MANIFEST")
    prediction_files = {name for name in names if name.endswith("_prediction.json")}
    if prediction_files != {row["artifact"] for row in index}:
        raise RuntimeError("STOP_CURRENT_PRE_PREDICTION_FILE_SET")
    rows = []
    for race in index:
        race_id = race["race_id"]
        if not race_id.startswith("race_" + target_date + "_") or race["artifact"] not in names:
            raise RuntimeError("STOP_CURRENT_PRE_RACE_ID")
        prediction = _json(pre_root / race["artifact"])
        field = prediction.get("ranked_results")
        if prediction.get("race_id") != race_id or not isinstance(field, list) or len(field) != race["horse_count"]:
            raise RuntimeError("STOP_CURRENT_PRE_RACE_FIELD")
        for horse in field:
            required = ("horse_number", "horse_name", "rank", "adjusted_score", "decision",
                        "buy_v1_rc1_candidate", "buy_v1_rc1_race_state")
            if any(key not in horse for key in required) or not isinstance(horse["buy_v1_rc1_candidate"], bool):
                raise RuntimeError("STOP_CURRENT_PRE_SELECTOR_INPUT_MISSING:" + race_id)
            rows.append({"date": target_date, "race_id": race_id,
                         "horse_number": horse["horse_number"], "horse_name": horse["horse_name"],
                         "rank": horse["rank"], "values": {
                             "race_state": horse["buy_v1_rc1_race_state"],
                             "shadow_buy_candidate": horse["buy_v1_rc1_candidate"],
                             "adjusted_score": horse["adjusted_score"],
                             "post_rc1_decision": horse["decision"]}})
    return rows, {"prediction_manifest_sha256": sha(manifest_path),
                  "input_manifest_sha256": sha(pre_root / "input_manifest.json"),
                  "provenance_sha256": sha(pre_root / "provenance.json"),
                  "race_count": len(index), "horse_count": len(rows)}


def build_pre(pre_root: Path, target_date: str) -> dict:
    rows, source = load_frozen_current(pre_root, target_date)
    selected, meta = select(rows, source["race_count"])
    additions = [row for row in selected if row["shadow_addition"]]
    eligible = [race_id for race_id, state in ((rid, next(row["race_state"] for row in selected if row["race_id"] == rid))
                                                for rid in sorted({row["race_id"] for row in selected}))
                if state == "PLAY_UNCONVERGED_4PLUS"]
    if len(additions) != len(eligible) or len({row["race_id"] for row in additions}) != len(eligible):
        raise RuntimeError("STOP_SHADOW_K1_INVARIANT")
    output = []
    for row in additions:
        venue_slug, race_number = row["race_id"].removeprefix("race_" + target_date + "_").rsplit("_", 1)
        output.append({"date": target_date, "venue": venue_slug, "race_id": row["race_id"],
                       "race_number": race_number, "race_state": row["race_state"],
                       "candidate_count": row["candidate_count"],
                       "selected_horse_number": row["horse_number"],
                       "selected_horse_name": row["horse_name"],
                       "stored_rank": row["current_rank"], "adjusted_score": row["adjusted_score"],
                       "shadow_k": 1, "selection_reason": row["resolution_reason"]})
    return {"target_date": target_date, "role": "PROSPECTIVE_SHADOW_PRE_ONLY",
            "approval_sha256": APPROVAL_SHA, "protocol_sha256": PROTOCOL_SHA,
            "implementation_sha256": IMPLEMENTATION_SHA,
            "prospective_runner_sha256": sha(Path(__file__)),
            "input_pre_sha256": source["prediction_manifest_sha256"],
            "input_pre": source, "eligible_races": len(eligible), "selections": output,
            "selector_meta": meta, "result_access_count": 0}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-pre-root", required=True, type=Path)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    if args.target_date != now_jst.strftime("%Y%m%d"):
        raise RuntimeError("STOP_NOT_TARGET_PRE_DATE")
    if args.output_root.exists():
        raise RuntimeError("STOP_OUTPUT_EXISTS_NO_OVERWRITE")
    artifact = build_pre(args.current_pre_root, args.target_date)
    artifact["generated_at_jst"] = now_jst.isoformat()
    args.output_root.mkdir(parents=True, exist_ok=False)
    output = args.output_root / "pre_selection.json"
    output.write_text(json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "sha256": sha(output), "eligible_races": artifact["eligible_races"]}))


if __name__ == "__main__":
    main()
