"""Freeze the 2026-10-25 PRE lanes, family table, G1 view, and manual packet."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/20261025_pre_v1"
DATE = "20261025"
VENUES = {"kyoto": "京都", "tokyo": "東京", "niigata": "新潟"}
V5 = ("INDEPENDENT_V5", "TRACKCONDITION_SEMANTIC", "DAILY_V5_SAME_VOLUME", "FORMAL_V5", "FORMAL_V6")
RAW_LANES = ("CURRENT", *V5, "EXP024_PL_SAME_VOLUME")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def horse_key(rid: str, number: int):
    return (rid, int(number))


def main():
    if (OUT / "20261025_pre_manifest.json").exists():
        raise RuntimeError("PRE_ALREADY_FROZEN")
    filtered = OUT / "filtered_source"
    paths = {k: filtered / f"{k}261025.CSV" for k in ("DG", "DE", "DS")}
    manifest = load(OUT / "filtered_source_manifest.json")
    for kind, path in paths.items():
        if sha(path) != manifest["filtered_source"][kind]["sha256"]:
            raise RuntimeError(f"FILTERED_SOURCE_SHA_MISMATCH:{kind}")
    bundle = TargetBulkPredictionInputAdapterV1().load(paths["DG"], paths["DE"], paths["DS"])
    if len(bundle.races) != 20 or sum(len(r.today_entries) for r in bundle.races.values()) != 269:
        raise RuntimeError("FILTERED_POPULATION_MISMATCH")
    with paths["DE"].open(encoding="cp932", newline="") as f:
        de = list(csv.reader(f))
    de_map = {(r[1].strip(), int(r[2]), int(r[3])): r for r in de}
    current_root = OUT / "current_frozen"
    current_index = load(current_root / "race_index.json")["race_index"]
    if len(current_index) != 20 or sum(x["horse_count"] for x in current_index) != 269:
        raise RuntimeError("CURRENT_SCOPE_MISMATCH")
    payloads = {x["race_id"]: load(current_root / x["artifact"]) for x in current_index}
    independent = load(OUT / "independent_v5/selection_manifest.json")
    tc = load(OUT / "trackcondition_semantic/horse_level_trace.json")
    daily = load(OUT / "daily_v5_same_volume/selection.json")
    formal = load(OUT / "formal_v5_v6/20261025/dual_pre_semantic.json")
    pl = load(OUT / "pl_forward_prediction.json")
    exp = load(OUT / "exp024_analysis/selection.json")
    aj = load(OUT / "adaptive_pl_jockey_research/prediction.json")
    if len(pl["horses"]) != 269 or len(aj["horses"]) != 269:
        raise RuntimeError("PL_SCOPE_MISMATCH")
    selected = {lane: set() for lane in RAW_LANES}
    for rid, payload in payloads.items():
        for h in payload["buys"]:
            selected["CURRENT"].add(horse_key(rid, h["horse_number"]))
    independent_by_race = {r["race_id"]: r for r in independent["races"]}
    for race in independent["races"]:
        for h in race["selected_horses"]:
            selected["INDEPENDENT_V5"].add(horse_key(race["race_id"], h["horse_number"]))
    tc_by_race = defaultdict(list)
    for h in tc["rows"]:
        tc_by_race[h["race_id"]].append(h)
        if h["shadow_selected"]:
            selected["TRACKCONDITION_SEMANTIC"].add(horse_key(h["race_id"], h["horse_number"]))
    daily_by_race = {r["race_id"]: r for r in daily["races"]}
    for race in daily["races"]:
        for h in race["selected_horses"]:
            selected["DAILY_V5_SAME_VOLUME"].add(horse_key(race["race_id"], h["horse_number"]))
    formal_by_race = {}
    for race in formal["races"]:
        rid = race["v5"]["race_id"]
        formal_by_race[rid] = race
        for lane, field in (("FORMAL_V5", "v5"), ("FORMAL_V6", "v6")):
            for h in race[field]["horses"]:
                if h["selected_by_protocol"]:
                    selected[lane].add(horse_key(rid, h["horse_number"]))
    exp_by_race = {r["race_id"]: r for r in exp["races"]}
    for race in exp["races"]:
        for number in race["treatment_selected_horses"]:
            selected["EXP024_PL_SAME_VOLUME"].add(horse_key(race["race_id"], number))
    pl_map = {horse_key(h["race_id"], h["horse_number"]): h for h in pl["horses"]}
    aj_map = {horse_key(h["race_id"], h["horse_number"]): h for h in aj["horses"]}
    rows = []
    for rid, race in sorted(bundle.races.items()):
        venue_key = rid.split("_")[2]
        venue = VENUES[venue_key]
        number = int(rid.split("_")[-1][:-1])
        current_rank = {int(h["horse_number"]): h["rank"] for h in payloads[rid]["ranked_results"]}
        for entry in sorted(race.today_entries, key=lambda h: h.horse_number):
            key = horse_key(rid, entry.horse_number)
            if key not in pl_map or key not in aj_map:
                raise RuntimeError(f"PL_HORSE_IDENTITY_MISSING:{key}")
            raw = de_map[(venue, number, entry.horse_number)]
            if raw[7].strip() != entry.horse_name or pl_map[key]["horse_name"] != entry.horse_name or aj_map[key]["horse_name"] != entry.horse_name:
                raise RuntimeError(f"HORSE_NAME_CONFLICT:{key}")
            support = {lane: key in selected[lane] for lane in RAW_LANES}
            family = {"CURRENT": support["CURRENT"], "V5": any(support[lane] for lane in V5),
                      "PL": support["EXP024_PL_SAME_VOLUME"]}
            p, a = pl_map[key], aj_map[key]
            rows.append(dict(date="2026-10-25", venue=venue, race_number=number, race_id=rid,
                horse_number=entry.horse_number, horse_name=entry.horse_name,
                registration_id=raw[18].strip(), jockey=entry.jockey, trainer=raw[12].strip() or None,
                age=int(raw[9]) if raw[9].strip().isdigit() else None, sex=raw[8].strip() or None,
                assigned_weight=entry.weight, current_rank=current_rank[entry.horse_number],
                current_buy=support["CURRENT"], independent_v5_selected=support["INDEPENDENT_V5"],
                trackcondition_selected=support["TRACKCONDITION_SEMANTIC"],
                daily_v5_selected=support["DAILY_V5_SAME_VOLUME"],
                formal_v5_selected=support["FORMAL_V5"], formal_v6_selected=support["FORMAL_V6"],
                exp024_selected=support["EXP024_PL_SAME_VOLUME"], v5_member_support_count=sum(support[l] for l in V5),
                v5_member_lanes_supporting=[l for l in V5 if support[l]],
                frozen_pl_rank=p["pl_race_rank"], frozen_pl_p_top3=p["pl_top3_probability"],
                adaptive_pl_rank=a["adaptive_rank"], adaptive_pl_p_top3=a["adaptive_p_top3"],
                adaptive_pl_jockey_rank=a["integrated_rank"], adaptive_pl_jockey_p_top3=a["integrated_p_top3"],
                jockey_rank_change=a["rank_change_vs_adaptive"], jockey_top3_lift=a["jockey_top3_lift"],
                family_support=family, family_votes=sum(family.values()),
                raw_lane_support_count=sum(support.values())))
    if len(rows) != 269 or len({horse_key(x["race_id"], x["horse_number"]) for x in rows}) != 269:
        raise RuntimeError("UNIFIED_POPULATION_INVALID")
    # The PL family is the frozen EXP024 same-volume selection, not a union of ranking-only Top3s.
    unified = OUT / "unified_pre_horses.json"
    dump(unified, {"role": "PRE_ONLY", "date": "2026-10-25", "family_semantics": "CURRENT BUY / any five V5 member lanes / EXP024 selected; one vote per family",
                   "max_family_votes": 3, "raw_lane_semantics": list(RAW_LANES), "horses": rows,
                   "result_access_count": 0})
    family_counts = Counter(x["family_votes"] for x in rows)
    by_race = defaultdict(list)
    for r in rows:
        by_race[r["race_id"]].append(r)
    tier_a = {r["race_id"] for r in rows if r["family_votes"] == 3} | {"race_20261025_kyoto_11R"}
    tier_b = {r["race_id"] for r in rows if r["family_votes"] == 2 and r["family_support"]["PL"]} - tier_a
    tier_c = set()
    for rid, horses in by_race.items():
        frozen_rank1 = next(r["horse_number"] for r in horses if r["frozen_pl_rank"] == 1)
        adaptive_rank1 = next(r["horse_number"] for r in horses if r["adaptive_pl_rank"] == 1)
        jockey_rank1 = next(r["horse_number"] for r in horses if r["adaptive_pl_jockey_rank"] == 1)
        if adaptive_rank1 != jockey_rank1 or frozen_rank1 != jockey_rank1:
            tier_c.add(rid)
    tier_c -= tier_a | tier_b
    family_path = OUT / "family_consensus.json"
    dump(family_path, {"date": DATE, "unified_pre_horses_sha256": sha(unified),
         "counts": {f"{n}F": family_counts[n] for n in (3, 2, 1, 0)},
         "three_family_horses": [r for r in rows if r["family_votes"] == 3],
         "two_family_horses": [r for r in rows if r["family_votes"] == 2],
         "raw_lane_support_summary": dict(sorted(Counter(r["raw_lane_support_count"] for r in rows).items())),
         "manual_review_tiers": {"TIER_A": sorted(tier_a), "TIER_B": sorted(tier_b), "TIER_C": sorted(tier_c)},
         "result_access_count": 0})
    g1 = "race_20261025_kyoto_11R"
    if g1 not in by_race:
        raise RuntimeError("MANDATORY_G1_MISSING")
    g1_rows = by_race[g1]
    def top_from_rank(field):
        best = min(r[field] for r in g1_rows)
        return [{"horse_number": r["horse_number"], "horse_name": r["horse_name"]} for r in g1_rows if r[field] == best]
    def top_from_score(score_map):
        if not score_map:
            return []
        best = max(score_map.values())
        return [{"horse_number": r["horse_number"], "horse_name": r["horse_name"]} for r in g1_rows if score_map.get(r["horse_number"]) == best]
    independent_score = {int(h["horse_number"]): float(h["p_top3"]) for h in independent_by_race[g1]["candidate_horses"]}
    tc_rank = {int(h["horse_number"]): int(h["shadow_rank"]) for h in tc_by_race[g1]}
    tc_min = min(tc_rank.values())
    g1_rank1 = {
        "CURRENT_TOP_RANKED_HORSE": top_from_rank("current_rank"),
        "INDEPENDENT_V5_TOP_RANKED_HORSE": top_from_score(independent_score),
        "TRACKCONDITION_TOP_RANKED_HORSE": [{"horse_number": r["horse_number"], "horse_name": r["horse_name"]} for r in g1_rows if tc_rank[r["horse_number"]] == tc_min],
        "DAILY_V5_TOP_RANKED_HORSE": None,
        "FORMAL_V5_TOP_RANKED_HORSE": None, "FORMAL_V6_TOP_RANKED_HORSE": None,
        "FROZEN_PL_RANK1": top_from_rank("frozen_pl_rank"),
        "ADAPTIVE_PL_RANK1": top_from_rank("adaptive_pl_rank"),
        "ADAPTIVE_PL_JOCKEY_RANK1": top_from_rank("adaptive_pl_jockey_rank"),
        "EXP024_TOP_SELECTION": [dict(horse_number=r["horse_number"], horse_name=r["horse_name"]) for r in g1_rows if r["exp024_selected"]],
        "FAMILY_HIGHEST_SUPPORTED_HORSE": [dict(horse_number=r["horse_number"], horse_name=r["horse_name"]) for r in g1_rows if r["family_votes"] == max(h["family_votes"] for h in g1_rows)],
        "RAW_LANE_SUPPORT_MAX_HORSE": [dict(horse_number=r["horse_number"], horse_name=r["horse_name"]) for r in g1_rows if r["raw_lane_support_count"] == max(h["raw_lane_support_count"] for h in g1_rows)],
    }
    dump(OUT / "kyoto11_g1_rank1.json", {"race_id": g1, "rank1": g1_rank1,
         "unavailable_reason": {"DAILY_V5": daily_by_race[g1]["scope_status"],
                                "FORMAL_V5": formal_by_race[g1]["v5"]["not_run_reason"],
                                "FORMAL_V6": formal_by_race[g1]["v6"]["not_run_reason"]},
         "full_field_comparison": g1_rows, "result_access_count": 0})
    manual_races = sorted(tier_a | tier_b | tier_c)
    adapter = TargetBulkPredictionInputAdapterV1()
    packet_races, missing = [], Counter()
    for rid in manual_races:
        race = bundle.races[rid]
        refs = {r["horse_number"]: r for r in by_race[rid]}
        horses = []
        for entry in sorted(race.today_entries, key=lambda x: x.horse_number):
            raw = de_map[(VENUES[rid.split("_")[2]], int(rid.split("_")[-1][:-1]), entry.horse_number)]
            history = adapter._past_races(race.history_rows_by_horse[entry.horse_name])[:5]
            past = [dict(race_date=p.race_date.date().isoformat(), venue=p.race_id.split("_")[2],
                         surface=p.surface, distance=p.distance, class_or_race_level=p.class_level,
                         finish=p.finish_position, margin=p.margin, running_positions=p.corner_positions or None,
                         final_3f=p.last_3f, body_weight=p.body_weight, body_weight_change=p.body_weight_diff,
                         track_condition=p.track_condition, race_time=None, pace_or_lap=None,
                         race_first_half=None, race_second_half=None, carried_weight=None) for p in history]
            missing.update({field: len(past) for field in ("race_time", "pace_or_lap", "race_first_half", "race_second_half", "carried_weight")})
            missing["current_body_weight"] += 1
            horses.append(dict(horse_number=entry.horse_number, horse_name=entry.horse_name,
                registration_id=raw[18].strip(), age=refs[entry.horse_number]["age"], sex=refs[entry.horse_number]["sex"],
                assigned_weight=entry.weight, jockey=entry.jockey, trainer=raw[12].strip() or None,
                pedigree_sire=raw[16].strip() or None, pedigree_maternal_grandsire=raw[20].strip() or None,
                pedigree_dam=None, current_body_weight=None, past_runs=past,
                ai_pre_context=refs[entry.horse_number]))
        missing["pedigree_dam"] += len(horses)
        packet_races.append(dict(race_id=rid, venue=VENUES[rid.split("_")[2]],
            race_number=int(rid.split("_")[-1][:-1]), race_name=race.dg_row[6].strip(),
            class_level=race.dg_row[5].strip(), surface=race.dg_row[7].strip(),
            distance=int(race.dg_row[8]), field_size=len(horses), full_field_horses=horses))
    pack_path = OUT / "manual_analysis_pack.json"
    dump(pack_path, {"date": "2026-10-25", "role": "PRE_ONLY_MANUAL_ANALYSIS_DATA_PACK",
         "result_access_count": 0, "odds_included": False, "popularity_included": False, "marks_included": False,
         "manual_review_tiers": {"TIER_A": sorted(tier_a), "TIER_B": sorted(tier_b), "TIER_C": sorted(tier_c)},
         "races": packet_races, "missing_fields_summary": dict(missing),
         "source_sha256": {k: sha(v) for k, v in paths.items()},
         "unified_pre_horses_sha256": sha(unified)})
    manual_root = ROOT / "reports/20261025_manual_pre"
    if manual_root.exists():
        raise RuntimeError("MANUAL_TEMPLATE_ROOT_ALREADY_EXISTS")
    manual_root.mkdir()
    template_path = manual_root / "manual_pre_labels_TEMPLATE.json"
    dump(template_path, {"date": "2026-10-25", "role": "PRE_MANUAL_LABEL_TEMPLATE_UNFILLED",
        "allowed_manual_stance": ["STRONG_SUPPORT", "SUPPORT", "SUPPORTED_WITH_EXPLICIT_CAUTION",
            "NEXT_CANDIDATE_WITH_CAUTION", "EXPLICIT_DISCOUNT", "NOT_FORMALLY_CLASSIFIED"],
        "ai_context_snapshot_sha": sha(unified), "result_access_count": 0,
        "entries": [dict(date="2026-10-25", race_id=r["race_id"], horse_number=r["horse_number"],
            horse_name=r["horse_name"], manual_shortlist_included=None, manual_stance=None,
            manual_reason=None, ai_context_snapshot_sha=sha(unified))
            for r in rows if r["race_id"] in manual_races]})
    lane_files = {"CURRENT": current_root / "prediction_manifest.json",
                  "INDEPENDENT_V5": OUT / "independent_v5/selection_manifest.json",
                  "TRACKCONDITION_SEMANTIC": OUT / "trackcondition_semantic/horse_level_trace.json",
                  "DAILY_V5_SAME_VOLUME": OUT / "daily_v5_same_volume/selection.json",
                  "FORMAL_V5_FORMAL_V6": OUT / "formal_v5_v6/20261025/dual_pre_semantic.json",
                  "FROZEN_PL_FORWARD": OUT / "pl_forward_prediction.json",
                  "EXP024_PL_SAME_VOLUME": OUT / "exp024_analysis/selection.json",
                  "ADAPTIVE_PL_AND_JOCKEY_RESEARCH": OUT / "adaptive_pl_jockey_research/prediction.json"}
    for name, path in lane_files.items():
        if not path.is_file():
            raise RuntimeError(f"LANE_ARTIFACT_MISSING:{name}")
    lane_counts = {lane: {"selected_horses": len(values), "selected_races": len({x[0] for x in values})}
                   for lane, values in selected.items()}
    dump(OUT / "20261025_pre_manifest.json", {
        "date": DATE, "status": "PRE_FROZEN_WITH_HUMAN_APPROVED_SINGLE_RACE_EXCLUSION",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "exclusion_record_sha256": sha(OUT / "exclusion_record.json"),
        "source_sha256": {k: {"original": manifest["original_source"][k]["sha256"],
                             "filtered": manifest["filtered_source"][k]["sha256"]} for k in paths},
        "ai_artifact_sha256": {k: {"path": str(v.relative_to(ROOT)), "sha256": sha(v)} for k, v in lane_files.items()},
        "unified_pre_horses_sha256": sha(unified), "family_consensus_sha256": sha(family_path),
        "kyoto11_g1_sha256": sha(OUT / "kyoto11_g1_rank1.json"), "manual_pack_sha256": sha(pack_path),
        "manual_label_template_sha256": sha(template_path),
        "population": {"source_races": 21, "excluded_races": 1, "eligible_races": 20,
                       "source_de_horses": 282, "excluded_de_horses": 13, "eligible_de_horses": 269},
        "lane_counts": lane_counts, "family_counts": {f"{n}F": family_counts[n] for n in (3, 2, 1, 0)},
        "result_access_count": 0, "odds_access_count": 0, "popularity_access_count": 0,
        "model_change": False, "retrain_from_1024_result": False, "production_change": False,
        "adaptive_research_model_reused_cutoff": "2026-10-18", "formal_prospective_evidence_credit_for_adaptive_jockey": 0})
    print(json.dumps({"status": "COMPLETE", "lane_counts": lane_counts,
                      "family_counts": {f"{n}F": family_counts[n] for n in (3, 2, 1, 0)},
                      "manual_races": len(manual_races), "manual_horses": sum(len(x["full_field_horses"]) for x in packet_races),
                      "pre_manifest_sha256": sha(OUT / "20261025_pre_manifest.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
