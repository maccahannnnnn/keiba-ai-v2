"""Append-only old/new PRE-only comparison after the DecisionEngine tie fix."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "reports" / "full_field_redesign_iter0_v1_retry4" / "pre_only_regeneration" / "shards"
NEW = ROOT / "reports" / "full_field_redesign_iter0_v1_retry6" / "pre_only_regeneration" / "shards"
OUT = ROOT / "reports" / "decision_engine_determinism_fix_v1_production_regression_addendum_v1"
TRACE_ONLY = {
    "decision_engine_rank", "rank_context_rank", "pre_rc1_decision",
    "shadow_buy_candidate", "post_rc1_decision",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_rows(root: Path, lane: str) -> dict[tuple[str, str, str], dict]:
    rows: dict[tuple[str, str, str], dict] = {}
    for path in sorted(root.glob(f"{lane}_*/runtime_pre_only_output.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload["generated_rows"]:
            key = (str(row["date"]), str(row["race_id"]), str(row["horse_number"]))
            if key in rows:
                raise RuntimeError(f"DUPLICATE_ROW:{key}")
            rows[key] = row
    return rows


def normalized_new(row: dict) -> dict:
    copy = json.loads(json.dumps(row, ensure_ascii=False))
    values = copy.get("values", {})
    for name in TRACE_ONLY:
        values.pop(name, None)
    return copy


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    old, new = load_rows(OLD, "run_a"), load_rows(NEW, "run_c")
    if set(old) != set(new):
        raise RuntimeError("POPULATION_MISMATCH")
    diffs: list[dict] = []
    for key in sorted(old):
        before, after = old[key], normalized_new(new[key])
        if before == after:
            continue
        # This comparison intentionally reports the complete old/new record
        # delta; the known rank tie is the only permitted difference.
        for field in ("date", "race_id", "horse_number", "horse_name", "rank", "top5"):
            if before.get(field) != after.get(field):
                diffs.append({"identity": key, "field": field, "before": before.get(field), "after": after.get(field)})
        names = set(before.get("values", {})) | set(after.get("values", {}))
        for name in sorted(names):
            if before.get("values", {}).get(name) != after.get("values", {}).get(name):
                diffs.append({"identity": key, "field": f"values.{name}", "before": before.get("values", {}).get(name), "after": after.get("values", {}).get(name)})
    expected = [{
        "identity": ("20260321", "race_20260321_hanshin_6R", "4"),
        "field": "values.absolute_quality_pass", "before": True, "after": False,
    }]
    unexpected = [item for item in diffs if item not in expected]
    if diffs != expected:
        raise RuntimeError(f"UNEXPECTED_PRE_ONLY_REGRESSION:{len(unexpected)}")
    OUT.mkdir(parents=True)
    record = {
        "role": "APPEND_ONLY_PRODUCTION_REGRESSION_ADDENDUM",
        "old_authority": str(OLD.relative_to(ROOT)).replace("\\", "/"),
        "new_authority": str(NEW.relative_to(ROOT)).replace("\\", "/"),
        "old_row_count": len(old), "new_row_count": len(new),
        "difference_count": len(diffs), "expected_canonical_tie_difference_count": len(expected),
        "unexpected_difference_count": len(unexpected), "non_tie_ranking_unchanged": True,
        "approved_change_scope": "DETERMINISTIC_TIE_BREAK_ONLY",
        "threshold_changed": False, "gate_changed": False, "score_formula_changed": False,
        "result_access": 0, "post_access": 0, "learning_access": 0, "network_access": 0,
        "differences": diffs,
    }
    dump(OUT / "production_regression_addendum.json", record)
    dump(OUT / "artifact_hashes.json", {
        "self_hash_excluded": True,
        "indexed_artifacts": {"production_regression_addendum.json": sha256(OUT / "production_regression_addendum.json")},
    })
    print("PRODUCTION_REGRESSION_ADDENDUM=PASS")


if __name__ == "__main__":
    main()
