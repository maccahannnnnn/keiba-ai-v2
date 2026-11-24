"""Result-free analysis of the already-frozen December 2025 eight-system PRE."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMAL = ROOT / "reports" / "december_2025_three_lane_one_shot_holdout_pre"
DIAGNOSTIC = ROOT / "reports" / "december_2025_all_frozen_systems_diagnostic_pre"
OUTPUT = ROOT / "reports" / "december_2025_pre_result_selection_analysis"
EXPECTED = {
    "CURRENT": (75, 131), "INDEPENDENT_V5": (69, 108), "TRACKCONDITION_SEMANTIC": (53, 90),
    "FORMAL_V5": (72, 119), "FORMAL_V6": (73, 121), "CF_TOP3_RANK_ANCHORED": (30, 90),
    "DAILY_V5_REFERENCE": (75, 131), "V4_MODEL_V3_REFERENCE": (75, 131),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def identity_set(rows, system: str) -> set[tuple[str, int]]:
    return {(row["race_id"], int(row["horse_number"])) for row in rows if row["systems"][system] == "SELECTED"}


def race_set(rows, system: str) -> set[str]:
    return {race for race, _ in identity_set(rows, system)}


def compare(left: set, right: set) -> dict:
    common, left_only, right_only = left & right, left - right, right - left
    union = left | right
    return {"common": len(common), "left_only": len(left_only), "right_only": len(right_only), "union": len(union),
            "jaccard": len(common) / len(union) if union else 1.0,
            "overlap_coefficient": len(common) / min(len(left), len(right)) if left and right else 1.0}


def date_of(race_id: str) -> str:
    return race_id.split("_")[1]


def counts(rows, system: str) -> dict:
    horses, races = identity_set(rows, system), race_set(rows, system)
    by_date = {date: {"selected_races": len({r for r, _ in horses if date_of(r) == date}), "selected_horses": sum(1 for r, _ in horses if date_of(r) == date)} for date in sorted({date_of(r) for r, _ in horses})}
    distribution = Counter(sum(1 for r, _ in horses if r == race) for race in races)
    scope = {row["race_id"] for row in rows if row["systems"][system] != "NOT_IN_SCOPE"}
    return {"scope_races": len(scope), "selected_races": len(races), "selected_horses": len(horses), "selected_horses_per_race_distribution": dict(sorted(distribution.items())), "buy_zero_dates": sorted(set(date_of(r) for r in scope) - set(by_date)), "date_by_date": by_date}


def run() -> Path:
    if OUTPUT.exists():
        raise RuntimeError("STOP_OUTPUT_EXISTS")
    if sha(FORMAL / "artifact_hashes.json") != "228f9dd3e45a769054d3c3a25ea98c8777a19506bd6257d97b01d0645c9b09d5":
        raise RuntimeError("STOP_FORMAL_FREEZE_SHA_MISMATCH")
    if sha(DIAGNOSTIC / "artifact_hashes.json") != "d7cad92676d018b0715ac0d63a5312b73eed28759905eefa444b04260220932d":
        raise RuntimeError("STOP_DIAGNOSTIC_FREEZE_SHA_MISMATCH")
    bitmap = read(DIAGNOSTIC / "system_selection_bitmap.json")
    race_bitmap = read(DIAGNOSTIC / "race_selection_bitmap.json")
    pairwise = read(DIAGNOSTIC / "pairwise_overlap_28.json")
    systems = list(EXPECTED)
    basic = {system: counts(bitmap, system) for system in systems}
    if any((basic[s]["selected_races"], basic[s]["selected_horses"]) != EXPECTED[s] for s in systems):
        raise RuntimeError("STOP_FROZEN_SELECTION_COUNT_MISMATCH")
    current_h, current_r = identity_set(bitmap, "CURRENT"), race_set(bitmap, "CURRENT")
    versus = {s: {"horse": compare(current_h, identity_set(bitmap, s)), "race": compare(current_r, race_set(bitmap, s))} for s in systems if s != "CURRENT"}
    current_pre = read(FORMAL / "current_pre.json")
    state_by_race = {x["race_id"]: x["buy_gate_trace"]["race"]["shadow_race_state"] for x in current_pre["predictions"]}
    independent_only = identity_set(bitmap, "INDEPENDENT_V5") - current_h
    unconverged = {x for x in independent_only if state_by_race[x[0]].startswith("PLAY_UNCONVERGED")}
    skipped = {x for x in independent_only if state_by_race[x[0]] == "SKIP"}
    independent = {"vs_current": versus["INDEPENDENT_V5"], "common_with_current": len(current_h & identity_set(bitmap, "INDEPENDENT_V5")),
                   "added_from_UNCONVERGED": {"race_count": len({r for r,_ in unconverged}), "horse_count": len(unconverged)},
                   "added_from_SKIP": {"race_count": len({r for r,_ in skipped}), "horse_count": len(skipped)},
                   "current_selected_but_independent_dropped": {"race_count": len(current_r-race_set(bitmap,"INDEPENDENT_V5")), "horse_count": len(current_h-identity_set(bitmap,"INDEPENDENT_V5"))}}
    tc = {"vs_current": versus["TRACKCONDITION_SEMANTIC"], "common": compare(current_h, identity_set(bitmap, "TRACKCONDITION_SEMANTIC")), "tc_added": len(identity_set(bitmap,"TRACKCONDITION_SEMANTIC")-current_h), "tc_dropped": len(current_h-identity_set(bitmap,"TRACKCONDITION_SEMANTIC"))}
    v5, v6 = identity_set(bitmap,"FORMAL_V5"), identity_set(bitmap,"FORMAL_V6")
    same, partial, different = 0, 0, 0
    for race in race_set(bitmap,"FORMAL_V5") | race_set(bitmap,"FORMAL_V6"):
        a, b = {n for r,n in v5 if r==race}, {n for r,n in v6 if r==race}
        if a == b: same += 1
        elif a & b: partial += 1
        else: different += 1
    formal_v5_v6 = {"horse": compare(v5,v6), "race": compare(race_set(bitmap,"FORMAL_V5"),race_set(bitmap,"FORMAL_V6")), "same_race_selection": {"identical":same,"partial_overlap":partial,"disjoint":different}}
    daily, v3 = identity_set(bitmap,"DAILY_V5_REFERENCE"), identity_set(bitmap,"V4_MODEL_V3_REFERENCE")
    daily_v3 = {"relation":"IDENTICAL" if daily==v3 else "DIFFERENT", "horse":compare(daily,v3),"race":compare(race_set(bitmap,"DAILY_V5_REFERENCE"),race_set(bitmap,"V4_MODEL_V3_REFERENCE"))}
    daily_formal = {"horse":compare(daily,v5),"race":compare(race_set(bitmap,"DAILY_V5_REFERENCE"),race_set(bitmap,"FORMAL_V5"))}
    ind_cf = {"horse":compare(identity_set(bitmap,"INDEPENDENT_V5"),identity_set(bitmap,"CF_TOP3_RANK_ANCHORED")),"race":compare(race_set(bitmap,"INDEPENDENT_V5"),race_set(bitmap,"CF_TOP3_RANK_ANCHORED"))}
    unique = {}
    for s in systems:
        selected = identity_set(bitmap,s)
        unique_all = {(x["race_id"],int(x["horse_number"])) for x in bitmap if x["systems"][s]=="SELECTED" and x["unique_vs_all_systems"]}
        unique_current = {(x["race_id"],int(x["horse_number"])) for x in bitmap if x["systems"][s]=="SELECTED" and x["unique_vs_current"]}
        unique[s] = {"unique_vs_all_systems_horses":len(unique_all),"unique_vs_current_horses":len(unique_current),"unique_vs_all_systems_races":len({r for r,_ in unique_all}),"unique_vs_current_races":len({r for r,_ in unique_current})}
    agreement = {"system_selection_count":dict(sorted(Counter(x["system_selection_count"] for x in bitmap).items())),"unique_model_family_selection_count":dict(sorted(Counter(x["unique_model_family_selection_count"] for x in bitmap).items()))}
    questions = {"frozen_pre_result_questions":["Q1 Independent-only selections recover Current-unselected Top3?","Q2 Which of added_from_UNCONVERGED and added_from_SKIP has more Top3 recoveries?","Q3 Are TC-only selections different from Current-only selections in Top3 rate?","Q4 In Formal V5/V6 difference sets, which has more Top3?","Q5 Do Daily V5/V3 difference selections have different outcomes?","Q6 Do CF/Independent common and exclusive regions differ in outcome?","Q7 Which system uniquely recovers Current-missed Top3?","Q8 Do multi-system and one-system-only selections differ in Top3 rate?"],"result_free":True}
    OUTPUT.mkdir(parents=True)
    artifacts = {"basic_selection_counts.json":basic,"current_vs_systems.json":versus,"independent_structure.json":independent,"trackcondition_structure.json":tc,"formal_v5_v6_structure.json":formal_v5_v6,"daily_v5_v3_structure.json":daily_v3,"daily_v5_formal_v5_structure.json":daily_formal,"independent_cf_structure.json":ind_cf,"pairwise_28_structure.json":pairwise,"unique_selection_counts.json":unique,"agreement_structure.json":agreement,"pre_result_questions.json":questions}
    for name,value in artifacts.items(): dump(OUTPUT/name,value)
    (OUTPUT/"pre_result_selection_analysis.md").write_text("# December 2025 PRE-Result Selection Analysis\n\nResult-free frozen selection structure; no outcome fields were read.\n", encoding="utf-8")
    hashes={p.name:sha(p) for p in OUTPUT.iterdir() if p.is_file()}; dump(OUTPUT/"artifact_hashes.json",{"self_hash_excluded":True,"indexed_artifacts":hashes}); dump(OUTPUT/"SUCCESS",{"status":"SUCCESS","result_access_count":0,"formal_artifact_index_sha256":sha(FORMAL/"artifact_hashes.json"),"diagnostic_artifact_index_sha256":sha(DIAGNOSTIC/"artifact_hashes.json")})
    return OUTPUT


if __name__ == "__main__": print(run())
