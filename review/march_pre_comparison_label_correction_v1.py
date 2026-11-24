"""Additive, result-free correction for March PRE comparison labels only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "reports" / "march_2026_historical_holdout_pre"
OUT = ROOT / "reports" / "march_2026_historical_holdout_pre_correction_v1"
CLAUDE_MANIFEST = PRE / "pre_independent_review_manifest.json"
CLAUDE_SHA = "046dbba4ae70aff422c6135eeccd09d486c1dcead87b3b5e1ad6f30b5ee1c8de"
AFFECTED = {"race_20260328_hanshin_7R", "race_20260329_hanshin_9R", "race_20260329_nakayama_9R"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def selection_label(current: list[int], v4: list[int], race_state: str) -> str:
    """Compare membership only: display/order must not affect equivalence."""
    if race_state != "PLAY_CONVERGED":
        return "OUT_OF_SCOPE_RACE_STATE"
    return "MATCH" if set(current) == set(v4) else "DIVERGENT"


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    if not CLAUDE_MANIFEST.is_file() or sha(CLAUDE_MANIFEST) != CLAUDE_SHA:
        raise RuntimeError("CLAUDE_MANIFEST_INTEGRITY_FAILURE")
    original = PRE / "same_volume_selection.json"
    current_path = PRE / "current_ai_prediction.json"
    v4_path = PRE / "v4_model_v3_prediction.json"
    population_path = PRE / "population_manifest.json"
    for path in (original, current_path, v4_path, population_path):
        if not path.is_file():
            raise RuntimeError(f"FROZEN_CORE_MISSING:{path.name}")
    original_sha = {path.name: sha(path) for path in (original, current_path, v4_path, population_path)}
    old = json.loads(original.read_text(encoding="utf-8"))
    rows = old.get("races")
    if not isinstance(rows, list) or len(rows) != 173:
        raise RuntimeError("FROZEN_COMPARISON_POPULATION_INVALID")
    corrected, affected = [], []
    for row in rows:
        current = list(row["current_horse_numbers"])
        v4 = list(row["v4_horse_numbers"])
        state = row["race_state"]
        label = selection_label(current, v4, state)
        replacement_depth = len(set(current) - set(v4)) if state == "PLAY_CONVERGED" else None
        record = {**row, "previous_comparison": row["comparison"], "corrected_comparison": label,
                  "comparison_method": "HORSE_NUMBER_SET_EQUIVALENCE", "replacement_depth": replacement_depth}
        corrected.append(record)
        if row["race_id"] in AFFECTED:
            affected.append(record)
    if {row["race_id"] for row in affected} != AFFECTED or any(x["corrected_comparison"] != "MATCH" for x in affected):
        raise RuntimeError("AFFECTED_RACE_CORRECTION_FAILURE")
    counts = {label: sum(row["corrected_comparison"] == label for row in corrected) for label in ("MATCH", "DIVERGENT", "OUT_OF_SCOPE_RACE_STATE")}
    if counts != {"MATCH": 16, "DIVERGENT": 55, "OUT_OF_SCOPE_RACE_STATE": 102}:
        raise RuntimeError(f"CORRECTED_CLASSIFICATION_MISMATCH:{counts}")
    eligible = [row for row in corrected if row["corrected_comparison"] != "OUT_OF_SCOPE_RACE_STATE"]
    current_selected = { (row["race_id"], item) for row in eligible for item in row["current_horse_numbers"] }
    v4_selected = { (row["race_id"], item) for row in eligible for item in row["v4_horse_numbers"] }
    both, current_only, v4_only = len(current_selected & v4_selected), len(current_selected-v4_selected), len(v4_selected-current_selected)
    if (len(current_selected), len(v4_selected), both, current_only, v4_only) != (118, 118, 56, 62, 62):
        raise RuntimeError("HORSE_LEVEL_OVERLAP_MISMATCH")
    overall = {depth: sum(row["replacement_depth"] == depth for row in eligible) for depth in range(4)}
    by_volume = {str(volume): {depth: sum(row["current_buy_count"] == volume and row["replacement_depth"] == depth for row in eligible) for depth in range(4)} for volume in (1, 2, 3)}
    if overall != {0: 16, 1: 48, 2: 7, 3: 0} or by_volume != {"1": {0: 7, 1: 29, 2: 0, 3: 0}, "2": {0: 4, 1: 13, 2: 6, 3: 0}, "3": {0: 5, 1: 6, 2: 1, 3: 0}}:
        raise RuntimeError("REPLACEMENT_DEPTH_MISMATCH")
    OUT.mkdir(parents=True)
    write(OUT / "comparison_label_correction.json", {"correction_scope": "DERIVED_COMPARISON_LABEL_ONLY", "old_method": "ORDERED_LIST_EQUALITY", "new_method": "HORSE_NUMBER_SET_EQUIVALENCE", "races": corrected})
    write(OUT / "corrected_comparison_summary.json", {"total_races": 173, "comparison_eligible_races": 71, "out_of_scope_races": counts["OUT_OF_SCOPE_RACE_STATE"], "match_races": counts["MATCH"], "divergent_races": counts["DIVERGENT"], "horse_level_overlap": {"current_selected": 118, "v4_selected": 118, "both": both, "current_only": current_only, "v4_only": v4_only, "overlap_rate": both / 118}})
    write(OUT / "affected_races.json", {"affected_races": affected, "count": len(affected), "all_corrected_to_match": True})
    write(OUT / "replacement_depth_summary.json", {"comparison_eligible_races": 71, "overall": {str(k): v for k, v in overall.items()}, "by_current_buy_volume": {volume: {str(k): v for k, v in values.items()} for volume, values in by_volume.items()}})
    write(OUT / "safety.json", {"status": "PASS", "prediction_rerun_count": 0, "model_inference_count": 0, "result_access_count": 0, "result_import_count": 0, "result_join_count": 0, "actual_top3_access_count": 0, "performance_calculation_count": 0, "lift_calculation_count": 0, "gate_evaluation_count": 0, "frozen_core_overwrite_count": 0, "production_change_count": 0, "cf_change_count": 0, "frozen_core_sha_before_after": {name: {"before": digest, "after": sha(PRE / name), "unchanged": digest == sha(PRE / name)} for name, digest in original_sha.items()}, "claude_manifest": {"path": str(CLAUDE_MANIFEST.relative_to(ROOT)), "sha256": sha(CLAUDE_MANIFEST), "unchanged": sha(CLAUDE_MANIFEST) == CLAUDE_SHA}})
    report = ["# March PRE Derived Comparison Label Correction", "", "- Scope: derived labels and counts only", "- Old comparison: ordered list equality", "- Corrected comparison: horse-number set equivalence", "- MATCH / DIVERGENT / out-of-scope: 16 / 55 / 102", "- Result access: 0", "- Frozen Current/V4 selections: unchanged", "- Claude manifest: unchanged"]
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    hashes = {path.name: sha(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json"}
    write(OUT / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": hashes})
    if any(sha(OUT / name) != digest for name, digest in hashes.items()):
        raise RuntimeError("CORRECTION_ARTIFACT_HASH_MISMATCH")
    print("MARCH_PRE_COMPARISON_LABEL_CORRECTION=COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
