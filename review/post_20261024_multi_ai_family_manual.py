"""2026-10-24 frozen-PRE-first POST diagnostic; no inference or model changes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from review.candidate_generation_training_dataset_readiness_v1 import outcome, result_rows


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/20261024_multi_ai_family_manual_post_v1"
DATE = "20261024"
P = {
    "CURRENT": ("reports/prospective_prediction_20261024_v1/prediction_manifest.json", "b1dd9caf677e86d64b401930b2c23748e229f9135862565622a70671a19dd6d2"),
    "INDEPENDENT_V5": ("reports/independent_race_selection_prospective/20261024_pre_retry1/selection_manifest.json", "7c48c559e276c195d12ca2d9866d8eee977ca9a58123b649b930161da57b6fb1"),
    "TRACKCONDITION": ("reports/trackcondition_semantic_prospective/20261024_pre/horse_level_trace.json", "e9064950eddf7d86ce97d9209c3fc78cefa0c8b6c488af1505f1c9e8856a49d0"),
    "DAILY_V5_SAME_VOLUME": ("reports/daily_v5_same_volume_prospective/20261024_pre/selection.json", "22e824acc4dff2084489c79c805a1237b0fc68aaa296054e356f91aacebe2cd6"),
    "FORMAL_V5_V6": ("reports/selection_authority_protocol_v1_v6_forward_shadow/pre/20261024/dual_pre_semantic.json", "fb4a67dbf0031a06d54bb158be24fb278ffffe169d04112dc4c36df4bc56ae4f"),
    "V5_FAMILY": ("reports/20261024_v5_family_support_pre/support.json", "d507e76bb3811226f26423a2fc23e411ce957cc7502980e8763af2d1dfffd2ad"),
    "FROZEN_PL_FORWARD": ("reports/pl_forward_shadow_v1/20261024_pre/prediction.json", "5163a156dd3d0eb768c0a5a047b5f96541e08bd26dd2078853f116c51a7b0359"),
    "EXP024": ("reports/exp024_pl_same_volume/20261024_pre_analysis/selection.json", "ec7b8c9ed7476473f0b6a0a88fe23b8816edc6b8d42a724a14a623a91b6b7ff1"),
    "ADAPTIVE_PL_JOCKEY": ("reports/adaptive_pl_jockey_research_v1/20261024_pre/prediction.json", "30e726a2cc82d2d6e4d324b41a7d5e6df7071edaf4efb989dfcf0c01139f00cf"),
}
V5 = ("INDEPENDENT_V5", "TRACKCONDITION", "DAILY_V5_SAME_VOLUME", "FORMAL_V5", "FORMAL_V6")
VENUE = {"kyoto": "京都", "tokyo": "東京", "niigata": "新潟"}
MANUAL = {
    "kyoto_6R": [1, 12, 9], "kyoto_7R": [10, 7, 4], "kyoto_8R": [4, 7, 3],
    "kyoto_12R": [2, 1, 6], "tokyo_10R": [12, 10], "niigata_6R": [3, 8, 12],
    "niigata_10R": [11, 6, 2], "niigata_12R": [16, 1, 12],
}
EXPECTED_3F = {("kyoto_6R", 1), ("kyoto_6R", 12), ("kyoto_6R", 9),
               ("tokyo_10R", 12), ("niigata_10R", 6),
               ("niigata_12R", 16), ("niigata_12R", 12)}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def key(race_id: str, number: int) -> str:
    return f"{race_id}#{int(number)}"


def phase_a():
    if OUT.exists() and any(OUT.iterdir()):
        raise RuntimeError("OUTPUT_NOT_EMPTY")
    sources = {}
    for lane, (name, expected) in P.items():
        path = ROOT / name
        if sha(path) != expected:
            raise RuntimeError(f"PRE_SHA_MISMATCH:{lane}")
        sources[lane] = load(path)
    current_root = ROOT / "reports/prospective_prediction_20261024_v1"
    index = load(current_root / "race_index.json")["race_index"]
    horses = {}
    race_files = {}
    for entry in index:
        path = current_root / entry["artifact"]
        race_files[entry["race_id"]] = sha(path)
        race = load(path)
        for h in race["ranked_results"]:
            k = key(entry["race_id"], h["horse_number"])
            if k in horses:
                raise RuntimeError(f"DUPLICATE_PRE:{k}")
            horses[k] = {"date": "2026-10-24", "race_id": entry["race_id"],
                         "horse_number": int(h["horse_number"]), "horse_name": h["horse_name"],
                         "current_buy": bool(h["buy"]), "lanes": {}, "rank": {}, "probability": {}}
    def select(lane, race_id, number):
        k = key(race_id, number)
        if k not in horses:
            raise RuntimeError(f"SELECTED_NOT_IN_CURRENT_POPULATION:{lane}:{k}")
        horses[k]["lanes"][lane] = True
    for r in sources["INDEPENDENT_V5"]["races"]:
        for h in r["selected_horses"]:
            select("INDEPENDENT_V5", r["race_id"], h["horse_number"])
    for h in sources["TRACKCONDITION"]["rows"]:
        if h["shadow_selected"]:
            select("TRACKCONDITION", h["race_id"], h["horse_number"])
    for r in sources["DAILY_V5_SAME_VOLUME"]["races"]:
        for h in r["selected_horses"]:
            select("DAILY_V5_SAME_VOLUME", r["race_id"], h["horse_number"])
    for r in sources["FORMAL_V5_V6"]["races"]:
        for lane, field in (("FORMAL_V5", "v5"), ("FORMAL_V6", "v6")):
            for h in r[field]["horses"]:
                if h["selected_by_protocol"]:
                    select(lane, r[field]["race_id"], h["horse_number"])
    for r in sources["EXP024"]["races"]:
        for number in r["treatment_selected_horses"]:
            select("EXP024", r["race_id"], number)
    for h in sources["V5_FAMILY"]["horses"]:
        k = key(h["race_id"], h["horse_number"])
        if k not in horses:
            raise RuntimeError(f"V5_POPULATION_MISMATCH:{k}")
        actual = sorted(l for l in V5 if horses[k]["lanes"].get(l))
        frozen = sorted("TRACKCONDITION" if lane == "TRACKCONDITION_SEMANTIC" else lane
                        for lane in h["v5_member_lanes_supporting"])
        if actual != frozen or bool(actual) != h["v5_family_high"]:
            raise RuntimeError(f"V5_SUPPORT_MISMATCH:{k}:{actual}:{frozen}")
    for h in sources["FROZEN_PL_FORWARD"]["horses"]:
        k = key(h["race_id"], h["horse_number"])
        horses[k]["rank"]["FROZEN_PL_FORWARD"] = h["pl_race_rank"]
        horses[k]["probability"]["FROZEN_PL_FORWARD"] = h["pl_top3_probability"]
    for h in sources["ADAPTIVE_PL_JOCKEY"]["horses"]:
        k = key(h["race_id"], h["horse_number"])
        horses[k]["rank"].update(ADAPTIVE_PL=h["adaptive_rank"], ADAPTIVE_PL_JOCKEY=h["integrated_rank"])
        horses[k]["probability"].update(ADAPTIVE_PL=h["adaptive_p_top3"], ADAPTIVE_PL_JOCKEY=h["integrated_p_top3"])
        horses[k]["jockey_top3_lift"] = h["jockey_top3_lift"]
        horses[k]["jockey_rank_change"] = h["rank_change_vs_adaptive"]
    for h in horses.values():
        h["lanes"]["CURRENT"] = h["current_buy"]
        h["family"] = {"CURRENT": h["current_buy"], "V5": any(h["lanes"].get(l, False) for l in V5),
                       "PL": h["lanes"].get("EXP024", False)}
        h["family_votes"] = sum(h["family"].values())
        h["v5_member_support_count"] = sum(h["lanes"].get(l, False) for l in V5)
        h["raw_lane_support_count"] = sum(h["lanes"].get(l, False) for l in ("CURRENT", *V5, "EXP024"))
        short = h["race_id"].removeprefix("race_20261024_")
        h["manual_shortlist"] = h["horse_number"] in MANUAL.get(short, [])
    counts = Counter(h["family_votes"] for h in horses.values())
    three = {(h["race_id"].removeprefix("race_20261024_"), h["horse_number"])
             for h in horses.values() if h["family_votes"] == 3}
    if len(index) != 21 or len(horses) != 269 or counts != {0: 223, 1: 25, 2: 14, 3: 7} or three != EXPECTED_3F:
        raise RuntimeError(f"FROZEN_CONSENSUS_RECONCILIATION_FAIL:{counts}:{three}")
    OUT.mkdir(parents=True)
    dump(OUT / "pre_selection_snapshot.json", {"date": DATE, "role": "FROZEN_PRE_RECONSTRUCTION_BEFORE_RESULT_ACCESS",
         "family_semantics": "CURRENT=current BUY; V5=any of five frozen member lanes; PL=EXP024 treatment selected",
         "source_sha256": {name: expected for name, (_, expected) in P.items()}, "race_file_sha256": race_files,
         "family_counts": dict(counts), "horses": [horses[k] for k in sorted(horses)]})
    print(f"PRE_FREEZE_SHA256={sha(OUT / 'pre_selection_snapshot.json')}")


def metrics(rows):
    rows = list(rows)
    valid = [r for r in rows if r["valid_result"]]
    hits = sum(r["actual_top3"] for r in valid)
    return {"raw_n": len(rows), "invalid_n": len(rows) - len(valid), "valid_n": len(valid),
            "top3_hits": hits, "top3_rate": hits / len(valid) if valid else None,
            "races": len({r["race_id"] for r in rows}),
            "races_with_hit": len({r["race_id"] for r in valid if r["actual_top3"]})}


def phase_b():
    pre_path = OUT / "pre_selection_snapshot.json"
    pre_sha = sha(pre_path)
    pre = load(pre_path)
    if pre["date"] != DATE or len(pre["horses"]) != 269:
        raise RuntimeError("PRE_SNAPSHOT_INVALID")
    raw_root = ROOT / "data/raw/target/daily_result_list"
    result_sources = {}
    for stem in ("馬番順着順", "着順馬番"):
        p = raw_root / f"{stem}_{DATE}.csv"
        with p.open(encoding="cp932", newline="") as f:
            rows = list(csv.reader(f))
        if any(not r[0].startswith(DATE) for r in rows):
            raise RuntimeError(f"RESULT_DATE_MISMATCH:{stem}")
        result_sources[stem] = {"path": str(p.relative_to(ROOT)), "sha256": sha(p), "rows": len(rows)}
    results = result_rows(DATE)
    joined = []
    for h in pre["horses"]:
        parts = h["race_id"].split("_")
        rk = (VENUE[parts[-2]], int(parts[-1][:-1]))
        if rk not in results:
            raise RuntimeError(f"RESULT_RACE_MISSING:{h['race_id']}")
        r = dict(h)
        r["valid_result"], r["finish"], r["actual_top3"] = outcome(results[rk], h["horse_number"])
        joined.append(r)
    if len(joined) != 269:
        raise RuntimeError("RESULT_JOIN_COUNT_FAIL")
    lane_names = ("CURRENT", *V5, "EXP024")
    lanes = {lane: metrics(r for r in joined if r["lanes"].get(lane, False)) for lane in lane_names}
    rankings = {}
    for lane in ("FROZEN_PL_FORWARD", "ADAPTIVE_PL", "ADAPTIVE_PL_JOCKEY"):
        rankings[lane] = {"rank1": metrics(r for r in joined if r["rank"].get(lane) == 1),
                          "rank1_to_3": metrics(r for r in joined if r["rank"].get(lane, 999) <= 3)}
        for label, predicate in (("hits", lambda r: r["actual_top3"]), ("misses", lambda r: not r["actual_top3"])):
            ps = [r["probability"][lane] for r in joined if r["valid_result"] and predicate(r)]
            rankings[lane][f"mean_p_top3_{label}"] = sum(ps) / len(ps) if ps else None
    v5_support = {str(n): metrics(r for r in joined if r["v5_member_support_count"] == n) for n in range(1, 6)}
    families = {f: metrics(r for r in joined if r["family"][f]) for f in ("CURRENT", "V5", "PL")}
    combinations = {}
    for bits in range(8):
        label = "+".join(f for i, f in enumerate(("CURRENT", "V5", "PL")) if bits & (1 << i)) or "0F"
        combinations[label] = metrics(r for r in joined if tuple(r["family"][f] for f in ("CURRENT", "V5", "PL")) == tuple(bool(bits & (1 << i)) for i in range(3)))
    raw_support = {str(n): metrics(r for r in joined if r["raw_lane_support_count"] == n) for n in range(1, 8)}
    rank_move = {name: metrics(r for r in joined if ("PROMOTED" if r["rank"]["ADAPTIVE_PL_JOCKEY"] < r["rank"]["ADAPTIVE_PL"] else "DEMOTED" if r["rank"]["ADAPTIVE_PL_JOCKEY"] > r["rank"]["ADAPTIVE_PL"] else "UNCHANGED") == name) for name in ("PROMOTED", "UNCHANGED", "DEMOTED")}
    transitions = {}
    for label, pred in {
        "ENTER_RANK1": lambda a, j: a != 1 and j == 1, "EXIT_RANK1": lambda a, j: a == 1 and j != 1,
        "ENTER_TOP3": lambda a, j: a > 3 and j <= 3, "EXIT_TOP3": lambda a, j: a <= 3 and j > 3,
    }.items():
        transitions[label] = metrics(r for r in joined if pred(r["rank"]["ADAPTIVE_PL"], r["rank"]["ADAPTIVE_PL_JOCKEY"]))
    manual = metrics(r for r in joined if r["manual_shortlist"])
    manual_combos = {"3F": metrics(r for r in joined if r["family_votes"] == 3),
                     "3F_AND_MANUAL_SHORTLIST": metrics(r for r in joined if r["family_votes"] == 3 and r["manual_shortlist"]),
                     "2F_AND_MANUAL_SHORTLIST": metrics(r for r in joined if r["family_votes"] == 2 and r["manual_shortlist"]),
                     "1F_OR_0F_AND_MANUAL_SHORTLIST": metrics(r for r in joined if r["family_votes"] < 2 and r["manual_shortlist"]),
                     "AJ_RANK1_AND_MANUAL_SHORTLIST": metrics(r for r in joined if r["rank"]["ADAPTIVE_PL_JOCKEY"] == 1 and r["manual_shortlist"]),
                     "AJ_TOP3_AND_MANUAL_SHORTLIST": metrics(r for r in joined if r["rank"]["ADAPTIVE_PL_JOCKEY"] <= 3 and r["manual_shortlist"])}
    by_race = defaultdict(list)
    for r in joined:
        by_race[r["race_id"]].append(r)
    race_review = []
    for short in MANUAL:
        race_id = f"race_{DATE}_{short}"
        rr = by_race[race_id]
        top3 = sorted((r for r in rr if r["valid_result"] and r["actual_top3"]), key=lambda r: r["finish"])
        race_review.append({"race_id": race_id,
                            "actual_top3": [{"horse_number": r["horse_number"], "horse_name": r["horse_name"]} for r in top3],
                            "current_buy": [r["horse_number"] for r in rr if r["current_buy"]],
                            "v5_supported": [r["horse_number"] for r in rr if r["family"]["V5"]],
                            "pl_supported": [r["horse_number"] for r in rr if r["family"]["PL"]],
                            "three_family": [r["horse_number"] for r in rr if r["family_votes"] == 3],
                            "two_family": [r["horse_number"] for r in rr if r["family_votes"] == 2],
                            "aj_top3": [r["horse_number"] for r in rr if r["rank"]["ADAPTIVE_PL_JOCKEY"] <= 3],
                            "manual_candidates": MANUAL[short],
                            "hit_type_by_top3": {str(r["horse_number"]): ("AI_AND_MANUAL_SUCCESS" if r["family_votes"] > 0 and r["manual_shortlist"] else
                                "AI_ONLY_SUCCESS" if r["family_votes"] > 0 else "MANUAL_ONLY_SUCCESS" if r["manual_shortlist"] else "BOTH_MISSED") for r in top3}})
    disagreements = []
    for short in ("kyoto_7R", "kyoto_12R", "niigata_10R", "niigata_12R"):
        rr = by_race[f"race_{DATE}_{short}"]
        k = sum(r["lanes"].get("EXP024", False) for r in rr)
        frozen = [r for r in rr if r["lanes"].get("EXP024", False)]
        aj = sorted(rr, key=lambda r: r["rank"]["ADAPTIVE_PL_JOCKEY"])[:k]
        disagreements.append({"race_id": f"race_{DATE}_{short}", "k": k,
                              "exp024_horses": [{"horse_number": r["horse_number"], "finish": r["finish"], "actual_top3": r["actual_top3"]} for r in frozen],
                              "aj_hypothetical_same_k": [{"horse_number": r["horse_number"], "finish": r["finish"], "actual_top3": r["actual_top3"]} for r in aj],
                              "exp024_hits": sum(r["actual_top3"] is True for r in frozen),
                              "aj_hits": sum(r["actual_top3"] is True for r in aj)})
    key_horses = {
        "niigata_10R": [6, 11, 2], "niigata_12R": [16, 1, 12], "kyoto_12R": [2, 5],
        "niigata_6R": [3, 12], "tokyo_10R": [12, 10], "kyoto_8R": [4],
    }
    key_review = [r for r in joined if r["horse_number"] in key_horses.get(r["race_id"].removeprefix(f"race_{DATE}_"), [])]
    all_result_horses = sum(int(row[9]) for row in results.values())
    if all_result_horses < 269:
        raise RuntimeError("RESULT_HORSE_COUNT_TOO_SMALL")
    report = {"role": "POST_REVIEW_ONLY", "pre_snapshot_sha256": pre_sha, "result_sources": result_sources,
              "result_reconciliation": {"result_races_all_card": len(results), "result_horses_all_card": all_result_horses, "pre_races": 21,
                                        "joined_races": len({r["race_id"] for r in joined}), "joined_horses": len(joined),
                                        "invalid_pre_rows": sum(not r["valid_result"] for r in joined),
                                        "unmatched_pre_rows": 0, "out_of_scope_result_races": len(results) - 21,
                                        "out_of_scope_result_horses": all_result_horses - 269},
              "individual_lanes": lanes, "rankings": rankings, "v5_member_support": v5_support,
              "families": families, "family_combinations": combinations, "raw_lane_support": raw_support,
              "adaptive_vs_jockey": {"rank_move": rank_move, "transitions": transitions},
              "manual_shortlist": manual, "manual_combinations": manual_combos,
              "race_level_review": race_review, "pl_internal_disagreement": disagreements,
              "key_disagreement_horses": key_review,
              "manual_support_discount_status": "NOT_RECONSTRUCTABLE_FROM_PROVIDED_PRE_NOTES; shortlist membership reported, but support/discount category not inferred",
              "three_family_horses": [r for r in joined if r["family_votes"] == 3],
              "manual_horses": [r for r in joined if r["manual_shortlist"]],
              "no_model_change": True, "formal_prospective_evidence_credit_for_adaptive_jockey": 0}
    dump(OUT / "post_diagnostic.json", report)
    lines = ["# 2026-10-24 POST multi-AI diagnostic", "", "Role: POST_REVIEW_ONLY. PRE snapshot was frozen before Result access.",
             f"PRE snapshot SHA256: `{pre_sha}`", "", f"Result source SHA256: `{result_sources['馬番順着順']['sha256']}` / `{result_sources['着順馬番']['sha256']}`", "",
             "## Individual lanes", "", "| Lane | Hits / valid N | Rate |", "|---|---:|---:|"]
    def fmt(m):
        return f"{m['top3_hits']}/{m['valid_n']} = {m['top3_rate']:.2%}" if m["top3_rate"] is not None else "0/0 = N/A"
    for name, m in lanes.items():
        lines.append(f"| {name} | {m['top3_hits']}/{m['valid_n']} | {m['top3_rate']:.2%} |")
    lines += ["", "## Family combinations", "", "| Group | Raw N | Valid N | Hits | Rate |", "|---|---:|---:|---:|---:|"]
    for name, m in combinations.items():
        lines.append(f"| {name} | {m['raw_n']} | {m['valid_n']} | {m['top3_hits']} | {m['top3_rate']:.2%} |" if m["top3_rate"] is not None else f"| {name} | 0 | 0 | 0 | N/A |")
    lines += ["", "## Rank-only models", "", "| Model | Rank1 | Rank1-3 |", "|---|---:|---:|"]
    for name, m in rankings.items():
        lines.append(f"| {name} | {fmt(m['rank1'])} | {fmt(m['rank1_to_3'])} |")
    lines += ["", "## V5 member support", "", "| Member lanes | Hits / valid N | Rate |", "|---:|---:|---:|"]
    for name, m in v5_support.items():
        lines.append(f"| {name} | {fmt(m)} | {m['top3_rate']:.2%} |")
    lines += ["", "## Raw lane support", "", "| Raw lanes | Hits / valid N | Rate |", "|---:|---:|---:|"]
    for name, m in raw_support.items():
        lines.append(f"| {name} | {fmt(m)} | {m['top3_rate']:.2%} |")
    lines += ["", "## Seven frozen 3F horses", "", "| Race | Horse | Finish | Raw support | V5 support | Adaptive rank | AJ rank | Frozen rank |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in report["three_family_horses"]:
        lines.append(f"| {r['race_id']} | #{r['horse_number']} {r['horse_name']} | {r['finish']} | {r['raw_lane_support_count']} | {r['v5_member_support_count']} | {r['rank']['ADAPTIVE_PL']} | {r['rank']['ADAPTIVE_PL_JOCKEY']} | {r['rank']['FROZEN_PL_FORWARD']} |")
    lines += ["", "## Adaptive vs Adaptive+Jockey", "", "| Movement | Hits / valid N | Rate |", "|---|---:|---:|"]
    for name, m in rank_move.items():
        lines.append(f"| {name} | {fmt(m)} | {m['top3_rate']:.2%} |")
    for name, m in transitions.items():
        lines.append(f"| {name} | {fmt(m)} | {m['top3_rate']:.2%} |")
    lines += ["", "## Four PL internal disagreement races", "", "| Race | EXP024 | AJ hypothetical same-k | Hits EXP024 / AJ |", "|---|---|---|---:|"]
    for d in disagreements:
        exp = ", ".join(f"#{h['horse_number']}({h['finish'] if h['finish'] is not None else 'INVALID'})" for h in d["exp024_horses"])
        aj = ", ".join(f"#{h['horse_number']}({h['finish'] if h['finish'] is not None else 'INVALID'})" for h in d["aj_hypothetical_same_k"])
        lines.append(f"| {d['race_id']} | {exp} | {aj} | {d['exp024_hits']} / {d['aj_hits']} |")
    lines += ["", "## Frozen manual shortlist", "", f"23 candidates: {fmt(manual)} (1 invalid excluded).",
              "", "Manual-supported/discounted subgroups are not calculated: a complete pre-Result support/discount mapping was not supplied. Shortlist membership is not silently equated with endorsement.",
              "", "This is descriptive POST review, not formal prospective evidence or a new BUY rule."]
    lines += ["", "## Eight reviewed races", "", "| Race | Actual Top3 | Current BUY | V5 | PL | 3F | 2F | AJ Top3 | Manual shortlist |", "|---|---|---|---|---|---|---|---|---|"]
    for r in race_review:
        top = ", ".join(f"#{h['horse_number']} {h['horse_name']}" for h in r["actual_top3"])
        nums = lambda name: ", ".join(f"#{n}" for n in r[name]) or "-"
        lines.append(f"| {r['race_id']} | {top} | {nums('current_buy')} | {nums('v5_supported')} | {nums('pl_supported')} | {nums('three_family')} | {nums('two_family')} | {nums('aj_top3')} | {nums('manual_candidates')} |")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (OUT / "joined_horses.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=("race_id", "horse_number", "horse_name", "valid_result", "finish", "actual_top3", "family_votes", "v5_member_support_count", "raw_lane_support_count", "manual_shortlist", "adaptive_rank", "adaptive_jockey_rank", "frozen_pl_rank"))
        w.writeheader()
        for r in joined:
            w.writerow({"race_id": r["race_id"], "horse_number": r["horse_number"], "horse_name": r["horse_name"],
                        "valid_result": r["valid_result"], "finish": r["finish"], "actual_top3": r["actual_top3"],
                        "family_votes": r["family_votes"], "v5_member_support_count": r["v5_member_support_count"],
                        "raw_lane_support_count": r["raw_lane_support_count"], "manual_shortlist": r["manual_shortlist"],
                        "adaptive_rank": r["rank"]["ADAPTIVE_PL"], "adaptive_jockey_rank": r["rank"]["ADAPTIVE_PL_JOCKEY"],
                        "frozen_pl_rank": r["rank"]["FROZEN_PL_FORWARD"]})
    dump(OUT / "artifact_hashes.json", {p.name: sha(p) for p in OUT.iterdir() if p.is_file() and p.name != "artifact_hashes.json"})
    print(json.dumps({"lanes": lanes, "families": families, "combinations": combinations,
                      "rankings": rankings, "manual": manual, "result_reconciliation": report["result_reconciliation"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("pre", "post"))
    args = parser.parse_args()
    phase_a() if args.phase == "pre" else phase_b()
