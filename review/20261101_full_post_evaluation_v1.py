"""POST-only 2026-11-01 evaluation of frozen seven-lane PRE selections."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from review.candidate_generation_training_dataset_readiness_v1 import (
    JAPANESE_VENUE, outcome, parse_race_id, result_rows,
)

ROOT = Path(__file__).resolve().parents[1]
E1_ROOT = Path("C:/Users/hikar/.codex/worktrees/e1-full-field-allocation-prospective-shadow-v1/keiba AI")
ANEW_ROOT = Path("C:/Users/hikar/.codex/worktrees/a-new-prospective-shadow-v1/keiba AI")
OUT = ROOT / "reports/20261101_full_post_evaluation_v1"
DATE = "20261101"
LANES = ("CURRENT", "EXP024", "CURRENT_RANK1", "PL_JOCKEY", "A_NEW", "E1", "INDEPENDENT_V5")
TIERS = {
    ("tokyo", 8, 1): "S", ("tokyo", 12, 8): "S",
    ("kyoto", 9, 8): "S-A",
    ("tokyo", 7, 4): "A", ("tokyo", 8, 2): "A",
    ("kyoto", 12, 2): "A-", ("kyoto", 9, 6): "A-", ("tokyo", 10, 9): "A-",
    ("tokyo", 12, 13): "B+",
    ("tokyo", 7, 11): "B", ("kyoto", 10, 2): "B",
    ("tokyo", 6, 1): "C+", ("kyoto", 10, 1): "C",
}
PRIORITY_FIVE = [("tokyo", 8, 1), ("tokyo", 12, 8), ("kyoto", 9, 8),
                 ("tokyo", 7, 4), ("kyoto", 12, 2)]
OVERLAP_SEVEN = [("tokyo", 6, 1), ("tokyo", 7, 4), ("tokyo", 7, 11),
                 ("tokyo", 8, 1), ("tokyo", 8, 2), ("tokyo", 12, 8), ("tokyo", 12, 13)]
E1_NON_PLJ_FIVE = [("kyoto", 9, 6), ("kyoto", 9, 8), ("kyoto", 10, 1),
                   ("kyoto", 10, 2), ("tokyo", 10, 9)]
RANK1_THREE = [("kyoto", 11, 8), ("kyoto", 12, 2), ("tokyo", 9, 3)]
CURRENT_NONBUY_FOUR = [("tokyo", 6, 1), ("tokyo", 7, 4), ("tokyo", 8, 1), ("tokyo", 8, 2)]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def k(rid: str, no: int) -> tuple[str, int]:
    return rid, int(no)


def specified_key(item: tuple[str, int, int]) -> tuple[str, int]:
    venue, race, no = item
    return f"race_{DATE}_{venue}_{race}R", no


def metrics(rows: list[dict]) -> dict:
    valid = [r for r in rows if r["valid_result"]]
    hits = sum(r["actual_top3"] for r in valid)
    return {"selected": len(rows), "valid": len(valid), "invalid": len(rows) - len(valid),
            "hits": hits, "rate": hits / len(valid) if valid else None}


def fmt(m: dict) -> str:
    rate = m.get("rate", m.get("buy_top3_rate"))
    return f"{m['hits']}/{m['valid']} ({rate:.2%})" if rate is not None else "0/0 (N/A)"


def write_csv(name: str, columns: list[str], rows: list[dict]) -> None:
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def detail(r: dict) -> str:
    suffix = "INVALID" if not r["valid_result"] else f"{r['finish']}着/{'○' if r['actual_top3'] else '×'}"
    return f"#{r['horse_number']} {r['horse_name']} ({suffix})"


def main() -> dict:
    expected_files = {"lane_performance_20261101.csv", "pl_jockey_e1_post_20261101.csv",
                      "e1_non_plj_post_20261101.csv", "human_pre_analysis_post_20261101.csv",
                      "race_by_race_post_20261101.md", "post_evaluation_summary_20261101.md",
                      "post_evaluation_20261101.json"}
    if OUT.exists() and {p.name for p in OUT.iterdir()} - expected_files:
        raise RuntimeError("STOP_UNEXPECTED_OUTPUT_FILE")
    pre_path = ROOT / "reports/20261101_multi_lane_pre_v1/consensus_20261101.json"
    pre = load(pre_path)
    if pre["target_date"] != "2026-11-01" or pre["result_access"] != 0:
        raise RuntimeError("STOP_PRE_STATUS")
    pre_horses = pre["horses"]
    if len(pre_horses) != 174 or len({k(h["race_id"], h["horse_number"]) for h in pre_horses}) != 174:
        raise RuntimeError("STOP_PRE_POPULATION")
    if len({h["race_id"] for h in pre_horses}) != 13:
        raise RuntimeError("STOP_PRE_RACE_COUNT")
    for name, source in pre["source_paths"].items():
        if sha(Path(source)) != pre["source_sha256"][name]:
            raise RuntimeError("STOP_PRE_SHA_DRIFT:" + name)
    for name, expected in pre["output_sha256"].items():
        if sha(pre_path.parent / name) != expected:
            raise RuntimeError("STOP_PRE_OUTPUT_SHA_DRIFT:" + name)

    paths = {name: Path(path) for name, path in pre["source_paths"].items()}
    direct = {lane: set() for lane in LANES}
    current_root = paths["current_manifest"].parent
    current_index = load(current_root / "race_index.json")["race_index"]
    assert len(current_index) == 13
    for item in current_index:
        race = load(current_root / item["artifact"])
        direct["CURRENT"].update(k(race["race_id"], h["horse_number"]) for h in race["buys"])
    for race in load(paths["exp024_selection"])["races"]:
        direct["EXP024"].update(k(race["race_id"], n) for n in race["treatment_selected_horses"])
    for row in load(paths["rank1_selection"])["selections"]:
        direct["CURRENT_RANK1"].add(k(row["race_id"], row["selected_horse_number"]))
    for race in load(paths["pl_jockey_selection"])["races"]:
        direct["PL_JOCKEY"].update(k(race["race_id"], n) for n in race["candidate_selected_horses"])
    for race in load(paths["a_new_selection"])["races"]:
        direct["A_NEW"].update(k(race["race_id"], n) for n in race["a_new_selected_horses"])
    direct["E1"].update(k(h["race_id"], h["horse_number"]) for h in load(paths["e1_selection"])["selected_horses"])
    for race in load(paths["independent_selection"])["races"]:
        direct["INDEPENDENT_V5"].update(k(race["race_id"], h["horse_number"]) for h in race["selected_horses"])
    mismatch = sum(bool(h[lane]) != (k(h["race_id"], h["horse_number"]) in direct[lane])
                   for h in pre_horses for lane in LANES)
    if mismatch:
        raise RuntimeError(f"STOP_PRE_LANE_MISMATCH:{mismatch}")
    pre_by = {k(h["race_id"], h["horse_number"]): h for h in pre_horses}

    result_paths = {"horse_order": ROOT / "data/raw/target/daily_result_list/馬番順着順_20261101.csv",
                    "finish_order": ROOT / "data/raw/target/daily_result_list/着順馬番_20261101.csv"}
    if not all(p.is_file() for p in result_paths.values()):
        raise RuntimeError("STOP_RESULT_SOURCE_MISSING")
    results = result_rows(DATE)  # Existing pair validator + official outcome semantics.
    result_shas = {name: sha(path) for name, path in result_paths.items()}
    by_key = {}
    for horse in pre_horses:
        rid, no = k(horse["race_id"], horse["horse_number"])
        date, venue_key, race_no = parse_race_id(rid)
        if date != DATE:
            raise RuntimeError("STOP_RACE_DATE")
        source = results.get((JAPANESE_VENUE[venue_key], race_no))
        if source is None or no > int(source[9]):
            raise RuntimeError(f"STOP_RESULT_HORSE_UNMATCHED:{rid}:{no}")
        valid, finish, top3 = outcome(source, no)
        by_key[(rid, no)] = {"date": "2026-11-01", "race_id": rid,
                             "venue": JAPANESE_VENUE[venue_key], "race_number": race_no,
                             "horse_number": no, "horse_name": horse["horse_name"],
                             "finish": finish, "result_status": "VALID" if valid else source[11 + no].strip(),
                             "valid_result": valid, "actual_top3": bool(top3) if valid else False,
                             **{lane: horse[lane] for lane in LANES},
                             "pl_jockey_rank": horse.get("pl_jockey_rank"),
                             "a_new_rank": horse.get("a_new_rank"),
                             "e1_global_allocation_rank": horse.get("e1_global_allocation_rank"),
                             "current_rank": horse.get("current_rank")}
    for rid in {h["race_id"] for h in pre_horses}:
        date, venue_key, race_no = parse_race_id(rid)
        if sum(key[0] == rid for key in by_key) != int(results[(JAPANESE_VENUE[venue_key], race_no)][9]):
            raise RuntimeError("STOP_RESULT_RACE_FIELD_SIZE:" + rid)
    all_rows = list(by_key.values())
    lane_stats = {lane: metrics([r for r in all_rows if r[lane]]) for lane in LANES}

    e1_post_path = E1_ROOT / "reports/e1_full_field_allocation_prospective_shadow_v1/daily_post/20261101/post.json"
    e1_transient_pending_path = E1_ROOT / "reports/e1_full_field_allocation_prospective_shadow_v1/date_status/20261101/post_pending_result.json"
    anew_post_path = ANEW_ROOT / "reports/a_new_prospective_shadow_v1/daily_post/20261101/post.json"
    e1_post, anew_post = load(e1_post_path), load(anew_post_path)
    if (not e1_post["evidence_date"] or not anew_post["evidence_date"] or
            e1_post["result_source_sha256"] != result_shas or anew_post["result_source_sha256"] != result_shas or
            any(e1_post["e1"][field] != lane_stats["E1"][field] for field in ("selected", "valid", "invalid", "hits")) or
            any(e1_post["exp024"][field] != lane_stats["EXP024"][field] for field in ("selected", "valid", "invalid", "hits")) or
            any(anew_post["arm_totals"]["a_new"][field] != lane_stats["A_NEW"][field] for field in ("selected", "valid", "invalid", "hits"))):
        raise RuntimeError("STOP_FORMAL_POST_RECONCILIATION")
    overlap = [by_key[specified_key(item)] for item in OVERLAP_SEVEN]
    e1_non = [by_key[specified_key(item)] for item in E1_NON_PLJ_FIVE]
    e1_minus_plj = [r for r in all_rows if r["E1"] and not r["PL_JOCKEY"]]
    rank1 = [by_key[specified_key(item)] for item in RANK1_THREE]
    nonbuy = [by_key[specified_key(item)] for item in CURRENT_NONBUY_FOUR]
    if not all(r["PL_JOCKEY"] and r["E1"] and r["A_NEW"] and r["EXP024"] for r in overlap):
        raise RuntimeError("STOP_OVERLAP_PRE_SET")
    if not all(r["E1"] and not r["PL_JOCKEY"] for r in e1_non):
        raise RuntimeError("STOP_E1_NON_PLJ_PRE_SET")
    if len(e1_minus_plj) != 7 or not {k(r["race_id"], r["horse_number"]) for r in e1_non} <= {k(r["race_id"], r["horse_number"]) for r in e1_minus_plj}:
        raise RuntimeError("STOP_E1_MINUS_PLJ_SCOPE")
    if not all(r["CURRENT_RANK1"] and r["INDEPENDENT_V5"] for r in rank1):
        raise RuntimeError("STOP_RANK1_V5_PRE_SET")
    if not all(not r["CURRENT"] and r["PL_JOCKEY"] and r["E1"] for r in nonbuy):
        raise RuntimeError("STOP_CURRENT_NONBUY_PRE_SET")
    if len({r["race_id"] for r in nonbuy}) != 3:
        raise RuntimeError("STOP_NONBUY_RACE_SET")
    # The request says four horses in four races, but Tokyo 8R contributes two.
    current_same_races = [r for r in all_rows if r["CURRENT"] and r["race_id"] in {x["race_id"] for x in nonbuy}]
    human = []
    for item, tier in TIERS.items():
        r = by_key[specified_key(item)]
        human.append({**r, "human_pre_tier": tier})
    human_by_tier = {tier: metrics([r for r in human if r["human_pre_tier"] == tier])
                     for tier in ("S", "S-A", "A", "A-", "B+", "B", "C+", "C")}
    priority = [by_key[specified_key(item)] for item in PRIORITY_FIVE]
    human_high = [r for r in human if r["human_pre_tier"] in {"S", "S-A"}]

    prior_pre = load(ROOT / "reports/20261031_multi_lane_consensus_v2/multi_lane_consensus_20261031.json")
    prior_overlap = [h for h in prior_pre["horses"] if h["PL_JOCKEY_selected"] and h["E1_selected"]]
    prior_results = result_rows("20261031")
    prior_outcomes = []
    for h in prior_overlap:
        date, venue_key, race_no = parse_race_id(h["race_id"])
        if date != "20261031":
            raise RuntimeError("STOP_PRIOR_DATE")
        prior_outcomes.append(outcome(prior_results[(JAPANESE_VENUE[venue_key], race_no)], int(h["horse_number"])))
    prior_valid = sum(v for v, _, _ in prior_outcomes)
    prior_hits = sum(bool(t) for v, _, t in prior_outcomes if v)
    if (len(prior_overlap), prior_valid, prior_hits) != (6, 6, 4):
        raise RuntimeError("STOP_PRIOR_OVERLAP_REPRODUCTION")
    cumulative_overlap = {"selected": 6 + len(overlap), "valid": prior_valid + metrics(overlap)["valid"],
                          "hits": prior_hits + metrics(overlap)["hits"]}
    cumulative_overlap["rate"] = cumulative_overlap["hits"] / cumulative_overlap["valid"]
    prior_e1_post = load(E1_ROOT / "reports/e1_full_field_allocation_prospective_shadow_v1/daily_post/20261031/post.json")
    e1_cumulative = {arm: {field: prior_e1_post[arm][field] + e1_post[arm][field]
                           for field in ("selected", "valid", "invalid", "hits")}
                     for arm in ("e1", "exp024")}
    for arm in e1_cumulative.values():
        arm["rate"] = arm["hits"] / arm["valid"] if arm["valid"] else None
    e1_cumulative["delta_hits_rule_a"] = e1_cumulative["e1"]["hits"] - e1_cumulative["exp024"]["hits"]
    e1_selected_races = {r["race_id"] for r in all_rows if r["E1"]}
    exp024_selected_races = {r["race_id"] for r in all_rows if r["EXP024"]}
    plj_selected_races = {r["race_id"] for r in all_rows if r["PL_JOCKEY"]}
    newly_opened_vs_exp024 = sorted(e1_selected_races - exp024_selected_races)
    newly_opened_vs_plj = sorted(e1_selected_races - plj_selected_races)
    if len(newly_opened_vs_exp024) != 4 or newly_opened_vs_exp024 != newly_opened_vs_plj:
        raise RuntimeError("STOP_OPENED_RACE_SCOPE")
    e1_post_ancillary_opened = e1_post["allocation_diagnostics"]["newly_opened_races"]

    OUT.mkdir(parents=True, exist_ok=True)
    write_csv("lane_performance_20261101.csv", ["lane", "selected", "valid", "invalid", "hits", "rate", "evidence_role"],
              [{"lane": lane, **lane_stats[lane], "evidence_role": "PROSPECTIVE_EVIDENCE" if lane in {"A_NEW", "E1"} else "POST_DIAGNOSTIC"} for lane in LANES])
    horse_fields = ["date", "venue", "race_number", "race_id", "horse_number", "horse_name", "finish",
                    "result_status", "valid_result", "actual_top3", *LANES, "pl_jockey_rank", "a_new_rank",
                    "e1_global_allocation_rank", "current_rank"]
    write_csv("pl_jockey_e1_post_20261101.csv", horse_fields, overlap)
    write_csv("e1_non_plj_post_20261101.csv", horse_fields, e1_non)
    write_csv("human_pre_analysis_post_20261101.csv", ["human_pre_tier", *horse_fields], human)

    race_groups = defaultdict(list)
    for r in all_rows:
        race_groups[r["race_id"]].append(r)
    race_lines = ["# 2026-11-01 race-by-race POST", "", "Selections are the pre-result frozen seven-lane sets. INVALID is excluded from denominators.", "",
                  "| Race | CURRENT | EXP024 | CURRENT_RANK1 | PL_JOCKEY | A_NEW | E1 | INDEPENDENT_V5 |",
                  "|---|---|---|---|---|---|---|---|"]
    for rid, rows in sorted(race_groups.items()):
        label = f"{rows[0]['venue']}{rows[0]['race_number']}R"
        cells = [" / ".join(detail(r) for r in sorted(rows, key=lambda r: r["horse_number"]) if r[lane]) or "NONE"
                 for lane in LANES]
        race_lines.append(f"| {label} | " + " | ".join(cells) + " |")
    (OUT / "race_by_race_post_20261101.md").write_text("\n".join(race_lines) + "\n", encoding="utf-8")

    special = {"pl_jockey_e1": metrics(overlap), "pl_jockey_e1_cumulative_1031_1101": cumulative_overlap,
               "e1_non_plj_requested_five": metrics(e1_non), "e1_minus_plj_all_seven": metrics(e1_minus_plj),
               "current_nonbuy_plj_e1": metrics(nonbuy),
               "rank1_v5": metrics(rank1), "human_priority_five": metrics(priority),
               "human_s_and_sa": metrics(human_high), "current_same_races": metrics(current_same_races)}
    def table(rows: list[dict]) -> list[str]:
        return [f"| {r['venue']}{r['race_number']}R | #{r['horse_number']} {r['horse_name']} | {r['finish'] if r['valid_result'] else r['result_status']} | {'YES' if r['actual_top3'] else 'NO' if r['valid_result'] else 'INVALID'} |"
                for r in rows]
    summary = ["# 2026-11-01 full POST evaluation", "",
               "13 races / 174 PRE horses. Result pair validated through the existing KeibaAI validator; 24 Result races / 318 horse slots in the source.",
               "Frozen PRE source hashes and 1,218 lane cells match the source selections (mismatch 0).", "",
               "| Lane | Selected | Valid | Invalid | Top3 | Rate |", "|---|---:|---:|---:|---:|---:|"]
    for lane, m in lane_stats.items():
        summary.append(f"| {lane} | {m['selected']} | {m['valid']} | {m['invalid']} | {m['hits']} | {m['rate']:.2%} |")
    summary += ["", "PL_JOCKEY, A_NEW, E1 and EXP024 are related PL_V1-family variants, not four independent votes.", "",
                "## Pre-fixed groups", "",
                "| Group | Selected | Valid | Invalid | Top3 | Rate |", "|---|---:|---:|---:|---:|---:|"]
    for label in ("pl_jockey_e1", "e1_non_plj_requested_five", "e1_minus_plj_all_seven", "current_nonbuy_plj_e1", "rank1_v5", "human_priority_five", "human_s_and_sa"):
        m = special[label]
        summary.append(f"| {label} | {m['selected']} | {m['valid']} | {m['invalid']} | {m['hits']} | {m['rate']:.2%} |")
    summary += ["", f"10/31 + 11/01 PL_JOCKEY ∩ E1: {fmt(cumulative_overlap)} (13 selected, small-sample diagnostic only).", "",
                "The five user-specified E1_NON_PLJ horses are a subset of seven horses in the literal E1 minus PL_JOCKEY set. The two others are Kyoto 12R #2 and Tokyo 8R #6. E1 allocation does not imply low PL model rank.", "",
                f"E1 opened four selection races versus both sealed EXP024 and PL_JOCKEY: {', '.join(newly_opened_vs_exp024)}. The frozen E1 POST allocation_diagnostics reports newly_opened_races={e1_post_ancillary_opened}; that ancillary field is inconsistent with the PRE set, while Rule A horse outcomes and totals reconcile. The frozen E1 POST artifact is unchanged.", "",
                "## PL_JOCKEY ∩ E1 (seven pre-fixed horses)", "", "| Race | Horse | Finish | Top3 |", "|---|---|---:|---|"]
    summary += table(overlap)
    summary += ["", "## E1 outside PL_JOCKEY (five pre-fixed horses)", "", "| Race | Horse | Finish | Top3 |", "|---|---|---:|---|"]
    summary += table(e1_non)
    summary += ["", "Full E1 minus PL_JOCKEY set (seven PRE-selected horses):", "", "| Race | Horse | Finish | Top3 |", "|---|---|---:|---|"]
    summary += table(e1_minus_plj)
    summary += ["", "## Current non-BUY horses in PL_JOCKEY ∩ E1", "",
                "Four horses occupy three races (Tokyo 6R, 7R, and 8R); the request's 'four races' wording is not supported by the frozen keys.", "",
                "| Race | Horse | Finish | Top3 |", "|---|---|---:|---|"]
    summary += table(nonbuy)
    summary += ["", f"Same three races' Current-selected horses: {fmt(special['current_same_races'])}.", "",
                "| Race | Horse | Finish | Top3 |", "|---|---|---:|---|"]
    summary += table(current_same_races)
    summary += ["", "## Rank1 ∩ V5", "", "| Race | Horse | Finish | Top3 |", "|---|---|---:|---|"]
    summary += table(rank1)
    summary += ["", f"Kyoto 12R #2: {detail(by_key[specified_key(('kyoto', 12, 2))])}; Current BUY=NO, Rank1=YES, E1=YES, V5=YES, PL_JOCKEY selected=NO (internal rank 1).", "",
                "## Human PRE ratings", "", "Human tiers are user-supplied as pre-result labels; this POST report does not independently attest their original timestamp. Diagnostic only, not formal evidence.", "",
                "| Tier | Selected | Valid | Top3 | Rate |", "|---|---:|---:|---:|---:|"]
    for tier, m in human_by_tier.items():
        summary.append(f"| {tier} | {m['selected']} | {m['valid']} | {m['hits']} | {m['rate']:.2%} |")
    summary += ["", "All 13 user-supplied Human PRE tiers and outcomes:", "",
                "| Tier | Race | Horse | Finish | Top3 |", "|---|---|---|---:|---|"]
    for r in human:
        summary.append(f"| {r['human_pre_tier']} | {r['venue']}{r['race_number']}R | #{r['horse_number']} {r['horse_name']} | {r['finish'] if r['valid_result'] else r['result_status']} | {'YES' if r['actual_top3'] else 'NO' if r['valid_result'] else 'INVALID'} |")
    summary += ["", "Priority five:", "", "| Race | Horse | Finish | Top3 |", "|---|---|---:|---|"]
    summary += table(priority)
    summary += ["", "## Formal prospective Rule A", "",
                f"E1: {fmt(e1_post['e1'])}; sealed EXP024: {fmt(e1_post['exp024'])}; ΔHits={e1_post['delta_hits_rule_a']:+d}; rate difference={(e1_post['e1']['buy_top3_rate'] - e1_post['exp024']['buy_top3_rate'])*100:+.2f}pt; evidence dates=2; cumulative ΔHits={e1_cumulative['delta_hits_rule_a']:+d}. State COLLECTING.", "",
                f"A_new: {fmt(anew_post['arm_totals']['a_new'])}; frozen A0 baseline: {fmt(anew_post['arm_totals']['a0'])}; ΔHits={anew_post['delta_hits_rule_a']:+d}; rate difference={(anew_post['arm_totals']['a_new']['buy_top3_rate'] - anew_post['arm_totals']['a0']['buy_top3_rate'])*100:+.2f}pt; evidence dates=1. 10/31 non-evidential recovery excluded. State COLLECTING.", "",
                "E1 execution note: an initial invocation looked for Result under the isolated E1 worktree and wrote POST_PENDING_RESULT. The official Result files are under main; the same official importer, pointed at main at runtime without source/code changes, subsequently produced POST_FROZEN. The transient pending record remains as an audit trail and is not the final state.", "",
                "Observed differences do not establish a cause or authorize a new BUY rule. No post-result selection change, prediction rerun, model/training/threshold/Production change, odds, or popularity analysis."]
    # Formal POST arm objects use buy_top3_rate instead of rate.
    summary = [line.replace("None", "N/A") for line in summary]
    (OUT / "post_evaluation_summary_20261101.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    report = {"status": "COMPLETE", "date": "2026-11-01", "role": "POST_RESULT_DIAGNOSTIC_WITH_FORMAL_E1_A_NEW_POST",
              "pre": {"path": str(pre_path), "sha256": sha(pre_path), "races": 13, "horses": 174,
                      "lane_cells": 1218, "mismatch_count": mismatch,
                      "source_sha256": pre["source_sha256"]},
              "result": {"validation": "PASS", "races": len(results), "horse_slots": sum(int(r[9]) for r in results.values()),
                         "source_sha256": result_shas},
              "lane_performance": lane_stats, "groups": special, "human_tiers": human_by_tier,
              "overlap_horses": overlap, "e1_non_plj_requested_five_horses": e1_non,
              "e1_minus_plj_all_seven_horses": e1_minus_plj,
              "e1_newly_opened_races_vs_exp024": newly_opened_vs_exp024,
              "e1_newly_opened_races_vs_pl_jockey": newly_opened_vs_plj,
              "e1_post_ancillary_newly_opened_races": e1_post_ancillary_opened,
              "e1_post_ancillary_opened_races_reconciles": e1_post_ancillary_opened == len(newly_opened_vs_exp024),
              "rank1_v5_horses": rank1,
              "current_nonbuy_plj_e1_horses": nonbuy, "current_same_races_horses": current_same_races,
              "human_horses": human, "priority_five": priority,
              "e1_formal": {"post_path": str(e1_post_path), "post_sha256": sha(e1_post_path),
                            "transient_pending_result_path": str(e1_transient_pending_path) if e1_transient_pending_path.is_file() else None,
                            "evidence_date_count": 2, "daily": {"e1": e1_post["e1"], "exp024": e1_post["exp024"],
                            "delta_hits_rule_a": e1_post["delta_hits_rule_a"]}, "cumulative": e1_cumulative,
                            "state": "COLLECTING"},
              "a_new_formal": {"post_path": str(anew_post_path), "post_sha256": sha(anew_post_path),
                               "evidence_date_count": 1, "a_new": anew_post["arm_totals"]["a_new"],
                               "a0": anew_post["arm_totals"]["a0"], "delta_hits_rule_a": anew_post["delta_hits_rule_a"],
                               "state": "COLLECTING"},
              "pre_selection_changed": False, "prediction_rerun": False, "model_changed": False,
              "buy_rule_changed": False, "training_executed": False, "production_changed": False}
    (OUT / "post_evaluation_20261101.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return {"lanes": lane_stats, "groups": {name: special[name] for name in special},
            "e1_delta": e1_post["delta_hits_rule_a"], "a_new_delta": anew_post["delta_hits_rule_a"],
            "out": str(OUT)}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
