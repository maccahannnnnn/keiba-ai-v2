"""Build V4 TRAIN Dataset v6: frozen v5 rows plus January 2026 label-only reuse."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.ml_v4_buy_selection_dataset_build_v1 import category, csv_write
from review.ml_v4_buy_selection_dataset_build_v4 import FEATURES, primary_feature_values, top5_and_buy
from review.ml_v4_buy_selection_dataset_inventory_v2 import Stop, outcome, result_for_race, result_rows, sha

PARENT = ROOT / "reports" / "ml_v4_buy_selection_dataset_v5"
OUT = ROOT / "reports" / "ml_v4_buy_selection_dataset_v6"
JAN_ROOT = ROOT / "reports" / "selection_authority_protocol_v1_january_2026_historical_holdout"
JAN_PRE = JAN_ROOT / "current_pre"
JAN_DATES = tuple(sorted(p.name for p in JAN_PRE.iterdir() if p.is_dir() and p.name.isdigit()))
EXPECTED = {"source_races": 149, "raw_top5": 745, "invalid": 4, "trainable": 741, "positive": 234,
            "negative": 507, "categories": {"TRUE_BUY_ABSTENTION": 418, "TOP5_NONBUY_MISSED": 183,
            "BUY_FALSE_POSITIVE": 89, "TRUE_BUY_SUCCESS": 51}}
JAN_AUTHORITY = {
    "protocol": (ROOT / "docs" / "selection_authority_protocol_v1_january_2026_historical_holdout.json", "77bccaf6d3f01e14b25c3e7564d7fd084f93511e64c021dd752269ab5bf00941"),
    "source_manifest": (JAN_ROOT / "source_acquisition" / "source_manifest.json", "d468a9f8b6d54136cb864e1202e849f0d305bd7e358d7ee7bc6b2b6996e31ec7"),
    "realized_population": (JAN_ROOT / "realized_population_manifest.json", "3388c234a1aa42f3bf10a2bc51576d33dc9067cb4415dd8fffdf95d4c1e94e45"),
    "current_pre": (JAN_PRE / "current_pre_freeze_manifest.json", "ba840efbb5e3b4551386412e3ebedd9038e3274d2460cda525e5fea2a5b55139"),
    "result_source_manifest": (JAN_ROOT / "post" / "result_source_manifest.json", "777216a9b26da55325102d82ed29dbb14df2390fbe5dc5de7ff033dc5051f458"),
}

def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()

def digest_rows(rows, fields):
    h = hashlib.sha256()
    for row in sorted(rows, key=lambda x: x["row_id"]):
        h.update(json.dumps({k: row.get(k) for k in fields}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
        h.update(b"\n")
    return h.hexdigest()

def checked_authority():
    got = {}
    for name, (path, expected) in JAN_AUTHORITY.items():
        if not path.is_file() or sha(path) != expected:
            raise Stop(f"JANUARY_AUTHORITY_SHA_MISMATCH:{name}")
        got[name] = {"path": path.relative_to(ROOT).as_posix(), "sha256": expected}
    return got

def parent_rows():
    with (PARENT / "dataset.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows, fields = list(reader), list(reader.fieldnames or [])
    manifest = json.loads((PARENT / "training_manifest.json").read_text(encoding="utf-8"))
    validation = json.loads((PARENT / "validation.json").read_text(encoding="utf-8"))
    if validation.get("status") != "PASS" or len(rows) != manifest.get("trainable_rows") or len(rows) != 5530:
        raise Stop("PARENT_V5_DATASET_INVALID")
    if len({r["row_id"] for r in rows}) != len(rows):
        raise Stop("PARENT_V5_DUPLICATE_ROW_ID")
    return rows, fields, manifest

def january_rows(fields, occupied):
    rows, invalid, per_date = [], [], []
    source_races = source_horses = raw_top5 = 0
    for date in JAN_DATES:
        root = JAN_PRE / date
        paths = sorted(root.glob("race_*_prediction.json"))
        if not paths:
            raise Stop(f"JANUARY_PREDICTION_SOURCE_MISSING:{date}")
        source_races += len(paths)
        with (ROOT / "data" / "raw" / "prediction_input" / f"DE{date[2:]}.CSV").open(encoding="cp932", newline="") as handle:
            source_horses += sum(1 for _ in csv.reader(handle))
        results = result_rows(date)
        date_raw = date_invalid = 0
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            race_id = payload["race_id"]
            top, buys, _ = top5_and_buy(payload, path)
            raw_top5 += len(top); date_raw += len(top)
            traces = {int(x["horse_number"]): x for x in payload.get("buy_gate_trace", {}).get("horses", [])}
            race_trace = payload.get("buy_gate_trace", {}).get("race", {})
            target_key, race_result = result_for_race(race_id, results)
            maximum = max(float(x["adjusted_score"]) for x in top)
            for horse in top:
                number = int(horse["horse_number"])
                label = outcome(race_result, number)
                row_id = f"{date}:{race_id}:{number}"
                if row_id in occupied:
                    raise Stop(f"PARENT_JANUARY_DUPLICATE_ROW:{row_id}")
                occupied.add(row_id)
                if not label["valid_result"]:
                    invalid.append({"date": date, "race_id": race_id, "horse_number": number, "horse_name": horse.get("horse_name"), "raw_status": label.get("raw_status")})
                    date_invalid += 1
                    continue
                values = primary_feature_values(horse, traces.get(number), race_trace, float(horse["adjusted_score"]) - maximum)
                if any(v is None or (isinstance(v, float) and not math.isfinite(v)) for v in values.values()):
                    raise Stop(f"JANUARY_FEATURE_MISSING_OR_NONFINITE:{row_id}")
                record = {"row_id": row_id, "date": date, "race_id": race_id, "target_race_key": target_key,
                          "horse_number": number, "horse_name": horse.get("horse_name"), **values,
                          "current_buy": number in buys, "current_top5": True,
                          "selection_error_category": category(number in buys, bool(label["actual_top3"])),
                          "actual_top3": int(bool(label["actual_top3"])), "actual_finish": label.get("actual_finish"),
                          "valid_result": True, "source_prediction_artifact_path": path.relative_to(ROOT).as_posix(),
                          "source_prediction_artifact_sha256": sha(path),
                          "source_result_artifact_path": f"data/raw/target/daily_result_list/馬番順着順_{date}.csv",
                          "source_result_artifact_sha256": sha(ROOT / "data" / "raw" / "target" / "daily_result_list" / f"馬番順着順_{date}.csv"),
                          "source_block": "CONSUMED_JANUARY_TRAIN_REUSE_V6",
                          "evidence_role_note": "FROZEN_PRE_FEATURES_POST_RESULT_LABEL_ONLY; JANUARY_FUTURE_ROLE=TRAINING_ALLOWED_EVALUATION_PROHIBITED",
                          "dataset_version": "ML_V4_TRAIN_DATASET_V6", "split_role": "TRAIN"}
                if set(record) != set(fields):
                    raise Stop(f"JANUARY_SCHEMA_MISMATCH:{row_id}")
                rows.append(record)
        per_date.append({"date": date, "prediction_races": len(paths), "raw_top5_rows": date_raw,
                         "invalid_result_excluded": date_invalid, "trainable_rows": date_raw - date_invalid,
                         "prediction_root": root.relative_to(ROOT).as_posix()})
    return rows, invalid, per_date, source_races, source_horses, raw_top5

def main():
    if OUT.exists():
        raise FileExistsError(f"OUTPUT_EXISTS:{OUT}")
    authorities = checked_authority()
    protected = [PARENT, ROOT / "reports" / "ml_v4_buy_selection_model_v5", JAN_ROOT,
                 ROOT / "review" / "ml_v4_buy_selection_dataset_build_v5.py", ROOT / "review" / "ml_v4_buy_selection_model_train_v5.py"]
    before = {p.relative_to(ROOT).as_posix(): sha(p) if p.is_file() else hashlib.sha256("".join(sorted(str(x.relative_to(p))+sha(x) for x in p.rglob("*") if x.is_file())).encode()).hexdigest() for p in protected}
    head, status = git("rev-parse", "HEAD"), git("status", "--porcelain")
    parent, fields, parent_manifest = parent_rows()
    parent_counts = {k: parent_manifest.get(k) for k in ("source_dates", "source_races", "source_horses", "trainable_rows")}
    if parent_counts != {"source_dates":62, "source_races":2094, "source_horses":14890, "trainable_rows":5530}:
        raise Stop(f"PARENT_V5_MANIFEST_COUNTS_MISMATCH:{parent_counts}")
    parent_digest = digest_rows(parent, fields)
    dates = {r["date"] for r in parent}
    added, invalid, per_date, source_races, source_horses, raw_top5 = january_rows(fields, {r["row_id"] for r in parent})
    category_counts = dict(Counter(r["selection_error_category"] for r in added)); pos = sum(int(r["actual_top3"]) for r in added)
    actual = {"source_races": source_races, "raw_top5": raw_top5, "invalid": len(invalid), "trainable": len(added), "positive": pos, "negative": len(added)-pos, "categories": category_counts}
    if actual != EXPECTED:
        raise Stop(f"JANUARY_RECOUNT_MISMATCH:{actual}")
    if source_horses != 2045:
        raise Stop(f"JANUARY_SOURCE_HORSE_RECOUNT_MISMATCH:{source_horses}")
    if dates & set(JAN_DATES) or len(dates) != 62 or len(dates | set(JAN_DATES)) != 72:
        raise Stop("DATE_COMPOSITION_MISMATCH")
    all_rows = sorted(parent + added, key=lambda r: (r["date"], r["race_id"], int(r["horse_number"])))
    if len(all_rows) != 6271 or len({r["row_id"] for r in all_rows}) != len(all_rows):
        raise Stop("V6_TOTAL_OR_DUPLICATE_MISMATCH")
    OUT.mkdir(parents=True)
    csv_write(OUT / "dataset.csv", fields, all_rows)
    csv_write(OUT / "feature_matrix.csv", ["row_id", *FEATURES], [{"row_id": r["row_id"], **{k:r[k] for k in FEATURES}} for r in all_rows])
    csv_write(OUT / "target.csv", ["row_id", "actual_top3"], [{"row_id":r["row_id"], "actual_top3":r["actual_top3"]} for r in all_rows])
    dataset_sha = sha(OUT / "dataset.csv")
    dump("january_added_rows_manifest.json", {"dates": list(JAN_DATES), "source_races": source_races, "source_horses": source_horses, "raw_top5_rows": raw_top5, "invalid_result_excluded": len(invalid), "trainable_rows": len(added), "positive": pos, "negative": len(added)-pos, "category_counts": category_counts, "row_id_sha256": digest_rows(added, ["row_id"]), "row_semantic_sha256": digest_rows(added, fields), "per_date": per_date, "invalid_rows": invalid, "frozen_authorities": authorities})
    dump("source_date_manifest.json", {"source_date_count":len(dates | set(JAN_DATES)), "parent_source_dates":parent_counts["source_dates"], "january_source_dates":len(JAN_DATES), "source_races":parent_counts["source_races"] + source_races, "source_horses":parent_counts["source_horses"] + source_horses, "january_dates":list(JAN_DATES), "parent_manifest_sha256":sha(PARENT / "source_date_manifest.json"), "january_per_date":per_date})
    dump("feature_schema.json", {"dataset_version":"ML_V4_TRAIN_DATASET_V6", "semantic_feature_order":list(FEATURES), "semantic_feature_count":20, "parent_v5_feature_schema_sha256":sha(PARENT / "feature_schema.json"), "feature_schema_equal_v5": True})
    dump("training_recipe.json", {"row_generation_authority":"V5 existing helpers imported without modification", "top5_semantics":"top5_and_buy", "feature_generation":"primary_feature_values", "target":"outcome/result_for_race actual_top3", "category":"category", "invalid_result_semantics":"EXCLUDED", "change_class":"DATASET_EXPANSION_ONLY"})
    dump("lineage.json", {"dataset":"ML_V4_TRAIN_DATASET_V6", "parent":"ML_V4_TRAIN_DATASET_V5", "parent_dataset_sha256":sha(PARENT / "dataset.csv"), "parent_rows":len(parent), "parent_row_semantic_sha256":parent_digest, "january_added_rows":len(added), "january_future_role":"TRAINING_ALLOWED_EVALUATION_PROHIBITED", "v5_historical_evidence_immutable":True, "change_class":"DATASET_EXPANSION_ONLY"})
    dump("dataset_manifest.json", {"status":"FROZEN_TRAINING_DATASET", "dataset":"ML_V4_TRAIN_DATASET_V6", "dataset_sha256":dataset_sha, "trainable_rows":len(all_rows), "positive":sum(int(r["actual_top3"]) for r in all_rows), "negative":sum(1-int(r["actual_top3"]) for r in all_rows), "source_dates":len(dates | set(JAN_DATES)), "source_races":parent_counts["source_races"] + source_races, "source_horses":parent_counts["source_horses"] + source_horses, "parent_rows":len(parent), "january_added_rows":len(added), "role":"DEVELOPMENT_CANDIDATE_ONLY"})
    dump("validation.json", {"status":"PASS", "parent_v5_rows":len(parent), "parent_row_id_set_equal":True, "parent_row_semantic_delta":0, "parent_row_semantic_sha256":parent_digest, "january_recount":actual, "parent_january_duplicate_rows":0, "total_rows":len(all_rows), "feature_columns_exact":list(FEATURES), "invalid_result_contamination":0})
    after = {p.relative_to(ROOT).as_posix(): sha(p) if p.is_file() else hashlib.sha256("".join(sorted(str(x.relative_to(p))+sha(x) for x in p.rglob("*") if x.is_file())).encode()).hexdigest() for p in protected}
    if before != after or git("rev-parse", "HEAD") != head:
        raise Stop("PROTECTED_ZERO_DELTA_FAILED")
    dump("safety.json", {"status":"PASS", "protected_before":before, "protected_after":after, "git_head_before":head, "git_head_after":git("rev-parse","HEAD"), "git_status_before":status, "v5_dataset_change":0, "v5_model_change":0, "january_evidence_change":0, "production_change":0, "performance_evaluation":0})
    (OUT / "report.md").write_text(f"# V4 TRAIN Dataset v6\n\nFrozen V5の{len(parent)}行を再計算せずそのまま保持し、January 2026の{len(added)}行を既存V5 helperで追加しました。JanuaryはTRAINING_ALLOWED_EVALUATION_PROHIBITEDです。\n", encoding="utf-8")
    dump("artifact_index.json", {"self_hash_excluded":True, "indexed_artifacts":{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "artifact_index.json"}})
    return OUT

if __name__ == "__main__":
    print(main())
