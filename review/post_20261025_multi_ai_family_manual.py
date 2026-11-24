"""One-date frozen-PRE-first POST diagnostic; no inference or model mutation."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from review.candidate_generation_training_dataset_readiness_v1 import outcome, result_rows

ROOT = Path(__file__).resolve().parents[1]
PRE = ROOT / "reports/20261025_pre_v1"
OUT = ROOT / "reports/20261025_post_review_v1"
DATE = "20261025"
EXPECTED = {
    "20261025_pre_manifest.json": "a2749bf74b752226e89639053ef6259094093466937befb75692ba51ad57573f",
    "exclusion_record.json": "53885fdbafb9103f9708ee45348da4ae516ded5225f0bb916df6c89afce23a16",
    "manual_analysis_pack.json": "85fd0a8d386d6395d746bf6ee2d6a9d48467d291aced8511a2766d1b88b3c236",
}
VENUE = {"kyoto": "京都", "tokyo": "東京", "niigata": "新潟"}
LANES = {
    "CURRENT": "current_buy", "INDEPENDENT_V5": "independent_v5_selected",
    "TRACKCONDITION_SEMANTIC": "trackcondition_selected",
    "DAILY_V5_SAME_VOLUME": "daily_v5_selected", "FORMAL_V5": "formal_v5_selected",
    "FORMAL_V6": "formal_v6_selected", "EXP024_PL_SAME_VOLUME": "exp024_selected",
}
RANKS = {
    "FROZEN_PL_FORWARD": ("frozen_pl_rank", "frozen_pl_p_top3"),
    "ADAPTIVE_PL": ("adaptive_pl_rank", "adaptive_pl_p_top3"),
    "ADAPTIVE_PL_JOCKEY_RESEARCH_V1": ("adaptive_pl_jockey_rank", "adaptive_pl_jockey_p_top3"),
}
MANUAL = {8: "STRONG_SUPPORT", 9: "SUPPORT", 5: "SUPPORT",
          14: "SUPPORTED_WITH_EXPLICIT_CAUTION", 15: "MANUAL_INTEREST",
          10: "MANUAL_INTEREST"}
KEY_DISAGREEMENTS = {
    "niigata_12R": (1, 10), "kyoto_8R": (9,), "kyoto_11R": (9, 14, 8, 10, 15),
    "kyoto_6R": (11, 1), "niigata_10R": (12,),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def metrics(rows):
    rows = list(rows)
    valid = [r for r in rows if r["valid_result"]]
    hits = sum(r["actual_top3"] for r in valid)
    return {"selected_n": len(rows), "invalid_n": len(rows) - len(valid), "valid_n": len(valid),
            "top3_hits": hits, "top3_rate": hits / len(valid) if valid else None,
            "selected_races": len({r["race_id"] for r in rows}),
            "races_with_at_least_one_top3": len({r["race_id"] for r in valid if r["actual_top3"]})}


def run():
    if OUT.exists():
        raise RuntimeError("POST_OUTPUT_ALREADY_EXISTS")
    for name, expected in EXPECTED.items():
        if sha(PRE / name) != expected:
            raise RuntimeError(f"PRE_FREEZE_SHA_MISMATCH:{name}")
    manifest = load(PRE / "20261025_pre_manifest.json")
    if manifest["population"] != {"source_races": 21, "excluded_races": 1, "eligible_races": 20,
                                   "source_de_horses": 282, "excluded_de_horses": 13,
                                   "eligible_de_horses": 269}:
        raise RuntimeError("PRE_POPULATION_DRIFT")
    pre_path = PRE / "unified_pre_horses.json"
    if sha(pre_path) != manifest["unified_pre_horses_sha256"]:
        raise RuntimeError("PRE_HORSE_SNAPSHOT_SHA_MISMATCH")
    pre = load(pre_path)
    horses = pre["horses"]
    keys = [(h["race_id"], int(h["horse_number"])) for h in horses]
    if len(horses) != 269 or len(set(keys)) != 269 or any("tokyo_12R" in rid for rid, _ in keys):
        raise RuntimeError("PRE_HORSE_POPULATION_INVALID")
    pre_races = {h["race_id"] for h in horses}
    if len(pre_races) != 20:
        raise RuntimeError("PRE_RACE_COUNT_INVALID")
    result_root = ROOT / "data/raw/target/daily_result_list"
    sources = {}
    for stem in ("馬番順着順", "着順馬番"):
        path = result_root / f"{stem}_{DATE}.csv"
        with path.open(encoding="cp932", newline="") as f:
            source_rows = list(csv.reader(f))
        if any(not row[0].startswith(DATE) for row in source_rows):
            raise RuntimeError(f"RESULT_DATE_MISMATCH:{stem}")
        sources[stem] = {"path": str(path.relative_to(ROOT)), "sha256": sha(path),
                         "row_count": len(source_rows),
                         "horse_count_from_field_size": sum(int(row[9]) for row in source_rows)}
    results = result_rows(DATE)  # Existing paired-source schema and ordering validator.
    joined = []
    matched_result_keys = set()
    for h in horses:
        parts = h["race_id"].split("_")
        result_key = (VENUE[parts[2]], int(parts[3][:-1]))
        if result_key not in results:
            raise RuntimeError(f"RESULT_RACE_MISSING:{h['race_id']}")
        valid, finish, top3 = outcome(results[result_key], int(h["horse_number"]))
        joined.append({**h, "valid_result": valid, "actual_finish": finish,
                       "actual_top3": top3})
        matched_result_keys.add(result_key)
    if len(matched_result_keys) != 20 or len(joined) != 269:
        raise RuntimeError("RESULT_JOIN_COUNT_MISMATCH")
    # Verify every in-scope horse number is represented in the Result source.
    by_race = defaultdict(list)
    for row in joined:
        by_race[row["race_id"]].append(row)
    for rid, rr in by_race.items():
        parts = rid.split("_")
        source = results[(VENUE[parts[2]], int(parts[3][:-1]))]
        numbers = {n for n in range(1, 19) if 11 + n < len(source) and source[11 + n].strip()}
        if numbers != {int(r["horse_number"]) for r in rr}:
            raise RuntimeError(f"RESULT_HORSE_SET_MISMATCH:{rid}")
    lanes = {name: metrics(r for r in joined if r[field]) for name, field in LANES.items()}
    rankings = {}
    for name, (rank, prob) in RANKS.items():
        valid = [r for r in joined if r["valid_result"]]
        rankings[name] = {
            "rank1": metrics(r for r in joined if r[rank] == 1),
            "rank1_to_3": metrics(r for r in joined if r[rank] <= 3),
            "mean_p_top3_actual_top3": sum(r[prob] for r in valid if r["actual_top3"]) / sum(r["actual_top3"] for r in valid),
            "mean_p_top3_non_top3": sum(r[prob] for r in valid if not r["actual_top3"]) / sum(not r["actual_top3"] for r in valid),
        }
    families = {str(n) + "F": metrics(r for r in joined if r["family_votes"] == n)
                for n in (3, 2, 1, 0)}
    if {k: v["selected_n"] for k, v in families.items()} != manifest["family_counts"]:
        raise RuntimeError("FAMILY_PRE_COUNT_DRIFT")
    three = [r for r in joined if r["family_votes"] == 3]
    two = [r for r in joined if r["family_votes"] == 2]
    expected_three = {("race_20261025_niigata_4R", 4), ("race_20261025_tokyo_11R", 2),
                      ("race_20261025_niigata_12R", 1), ("race_20261025_niigata_12R", 10)}
    if {(r["race_id"], r["horse_number"]) for r in three} != expected_three or len(two) != 9:
        raise RuntimeError("FROZEN_3F_2F_IDENTITY_DRIFT")
    two_groups = {"+".join(k for k, v in sorted(r["family_support"].items()) if v):
                  None for r in two}
    two_groups = {name: {"metrics": metrics(r for r in two if "+".join(k for k, v in sorted(r["family_support"].items()) if v) == name),
                         "horses": [r for r in two if "+".join(k for k, v in sorted(r["family_support"].items()) if v) == name]}
                  for name in sorted(two_groups | {"CURRENT+PL": None})}
    raw_support = {str(n): metrics(r for r in joined if r["raw_lane_support_count"] == n)
                   for n in range(7)}
    if {k: v["selected_n"] for k, v in raw_support.items()} != manifest["family_counts"] and sum(v["selected_n"] for v in raw_support.values()) != 269:
        raise RuntimeError("RAW_SUPPORT_ACCOUNTING_DRIFT")
    changed = []
    for rid, rr in sorted(by_race.items()):
        a = next(r for r in rr if r["adaptive_pl_rank"] == 1)
        j = next(r for r in rr if r["adaptive_pl_jockey_rank"] == 1)
        if a["horse_number"] != j["horse_number"]:
            changed.append({"race_id": rid, "adaptive_rank1": a, "aj_rank1": j})
    if len(changed) != 11:
        raise RuntimeError(f"PRE_RANK1_DISAGREEMENT_COUNT_DRIFT:{len(changed)}")
    entering = [r for r in joined if r["adaptive_pl_rank"] > 3 and r["adaptive_pl_jockey_rank"] <= 3]
    leaving = [r for r in joined if r["adaptive_pl_rank"] <= 3 and r["adaptive_pl_jockey_rank"] > 3]
    boundary = {"entering": {"metrics": metrics(entering), "horses": entering},
                "leaving": {"metrics": metrics(leaving), "horses": leaving}}
    g1 = sorted(by_race["race_20261025_kyoto_11R"], key=lambda r: r["horse_number"])
    if len(g1) != 18 or any(r["current_buy"] for r in g1):
        raise RuntimeError("KYOTO11_PRE_SCOPE_DRIFT")
    manual_horses = [{**r, "manual_pre_stance_user_asserted": MANUAL.get(r["horse_number"])}
                     for r in g1 if r["horse_number"] in MANUAL]
    manual_shortlist = [r for r in manual_horses if r["horse_number"] in (8, 9, 5, 14)]
    key_disagreements = [r for r in joined if r["horse_number"] in KEY_DISAGREEMENTS.get(
        r["race_id"].removeprefix("race_20261025_"), ())]
    out_of_scope_races = sorted(k for k in results if k not in matched_result_keys)
    report = {
        "status": "COMPLETE", "date": "2026-10-25",
        "classification": "2026-10-25 ONE-DATE POST DIAGNOSTIC",
        "pre_provenance_sha256": {name: sha(PRE / name) for name in EXPECTED},
        "result_sources": sources,
        "result_reconciliation": {"result_source_races": len(results), "pre_races": 20,
                                  "joined_races": len(matched_result_keys),
                                  "result_source_horses": sources["馬番順着順"]["horse_count_from_field_size"],
                                  "pre_horses": 269, "joined_horses": len(joined),
                                  "invalid_results": sum(not r["valid_result"] for r in joined),
                                  "unmatched_pre": 0, "unmatched_result_in_scope": 0,
                                  "out_of_scope_result_races": out_of_scope_races,
                                  "duplicates": 0, "excluded_race": "race_20261025_tokyo_12R"},
        "individual_ai_result_table": lanes, "ranking_model_result_table": rankings,
        "family_result_table": families, "three_family_detailed_table": three,
        "two_family_result_table": two_groups, "raw_support_result_table": raw_support,
        "adaptive_vs_jockey_rank1_result": {"changed_races": changed,
              "adaptive_rank1": rankings["ADAPTIVE_PL"]["rank1"],
              "aj_rank1": rankings["ADAPTIVE_PL_JOCKEY_RESEARCH_V1"]["rank1"],
              "raw_hit_difference": rankings["ADAPTIVE_PL_JOCKEY_RESEARCH_V1"]["rank1"]["top3_hits"] - rankings["ADAPTIVE_PL"]["rank1"]["top3_hits"],
              "rate_difference": rankings["ADAPTIVE_PL_JOCKEY_RESEARCH_V1"]["rank1"]["top3_rate"] - rankings["ADAPTIVE_PL"]["rank1"]["top3_rate"],
              "aj_promoted_top3": sum(r["aj_rank1"]["actual_top3"] is True for r in changed),
              "aj_promoted_misses": sum(r["aj_rank1"]["actual_top3"] is False for r in changed),
              "aj_demoted_top3": sum(r["adaptive_rank1"]["actual_top3"] is True for r in changed),
              "aj_demoted_misses": sum(r["adaptive_rank1"]["actual_top3"] is False for r in changed)},
        "adaptive_vs_jockey_top3_boundary_result": boundary,
        "kyoto11_g1_full_post_table": g1,
        "kyoto11_g1_special_comparison": manual_horses,
        "kyoto11_manual_post_result": {"scope": "京都11R ONLY", "evidence_role": "ONE_RACE_MANUAL_DIAGNOSTIC_ONLY",
                                        "provenance_boundary": "Labels are asserted in the human POST request; repository-frozen filled manual label artifact was not located.",
                                        "manual_horses": manual_horses, "primary_shortlist": metrics(manual_shortlist)},
        "key_disagreement_horses": key_disagreements,
        "formal_prospective_evidence_credit_for_adaptive_jockey": 0,
        "no_model_change": True, "no_retraining": True, "no_production_change": True,
    }
    OUT.mkdir(parents=True)
    path = OUT / "post_review.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path), "sha256": sha(path),
                      "result_reconciliation": report["result_reconciliation"],
                      "lane_metrics": lanes, "ranking_metrics": rankings,
                      "family_metrics": families, "raw_support_metrics": raw_support,
                      "manual_shortlist": report["kyoto11_manual_post_result"]["primary_shortlist"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    run()
