"""Read-only 2026-10-12 POST and 9/26--10/12 complementarity update.

Selection is always loaded from frozen PRE artifacts before any result source is
opened.  This is a diagnostic/reporting runner; it never invokes prediction.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from review.target_daily_result_list_schema_v2_validator import validate_source_pair
from review.all_active_systems_post_diagnostic_v1 import _crosscheck_finish_order
from review.prospective_multilane_complementarity_diagnostic_v1 import (
    DATES as V1_DATES, JA, K, LANES as BASE_LANES, ROOT, S, frozen, met,
    results, sha, load, dump, union,
)

DATE = "20261012"
PRE = ROOT / "reports" / "20261012_official_pre_v1_retry4"
POST = ROOT / "reports" / "20261012_official_post_result_review_v1"
V2 = ROOT / "reports" / "20260926_20261012_multilane_complementarity_diagnostic_v2"
LANES = ("CURRENT", "INDEPENDENT_V5", "TRACKCONDITION_SEMANTIC",
         "DAILY_V5_SAME_VOLUME", "FORMAL_V5", "FORMAL_V6")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row}) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def verify_current_manifest(root: Path) -> None:
    manifest = load(root / "prediction_manifest.json")
    for item in manifest["files"]:
        path = root / item["relative_path"]
        if not path.is_file() or sha(path) != item["sha256"]:
            raise RuntimeError(f"STOP_CURRENT_PRE_MANIFEST:{path}")


def frozen_1012() -> dict[str, Any]:
    current = PRE / "current_frozen"
    verify_current_manifest(current)
    population = load(PRE / "population_freeze.json")
    exclusion = population.get("exclusions", [])
    if len(exclusion) != 1 or exclusion[0].get("race_id") != "race_20261012_kyoto_8R":
        raise RuntimeError("STOP_EXCLUSION_FREEZE_MISMATCH")
    records: dict[str, dict[str, Any]] = {}
    selection = {lane: defaultdict(set) for lane in LANES}
    for item in load(current / "race_index.json")["race_index"]:
        payload = load(current / item["artifact"])
        ranked = payload["ranked_results"]
        race_id = payload["race_id"]
        records[race_id] = {
            "venue": str(ranked[0].get("venue") or race_id.split("_")[-2]),
            "race_number": int(ranked[0].get("race_number") or race_id.split("_")[-1][:-1]),
            "ranked": ranked,
            "names": {str(h["horse_number"]): h["horse_name"] for h in ranked},
            "state": payload.get("buy_gate_trace", {}).get("race", {}).get("shadow_race_state"),
            "payload": payload,
        }
        selection["CURRENT"][race_id] = {str(h["horse_number"]) for h in payload.get("buys", [])}
    independent = load(PRE / "independent_v5" / "selection_manifest.json")
    independent_races = {x["race_id"]: x for x in independent["races"]}
    for rid, row in independent_races.items():
        selection["INDEPENDENT_V5"][rid] = {str(h["horse_number"]) for h in row.get("selected_horses", [])}
    daily = load(PRE / "daily_v5_same_volume" / "selection.json")
    for row in daily["races"]:
        selection["DAILY_V5_SAME_VOLUME"][row["race_id"]] = {str(h["horse_number"]) for h in row.get("selected_horses", [])}
    tc = load(PRE / "trackcondition_semantic" / "horse_level_trace.json")["rows"]
    for row in tc:
        if row.get("shadow_selected"):
            selection["TRACKCONDITION_SEMANTIC"][row["race_id"]].add(str(row["horse_number"]))
    formal = load(PRE / "formal_v5_v6" / DATE / "dual_pre_semantic.json")["races"]
    for row in formal:
        rid = row["v5"]["race_id"]
        for version, lane in (("v5", "FORMAL_V5"), ("v6", "FORMAL_V6")):
            selection[lane][rid] = {str(h["horse_number"]) for h in row[version].get("horses", []) if h.get("selected_by_protocol")}
    ids = set(records)
    if len(records) != 11 or sum(len(x["ranked"]) for x in records.values()) != 153:
        raise RuntimeError("STOP_POPULATION_FREEZE_COUNT_MISMATCH")
    for lane in LANES:
        for rid in ids:
            selection[lane][rid]
        if set(selection[lane]) != ids:
            raise RuntimeError(f"STOP_LANE_RACE_SET:{lane}")
    if selection["FORMAL_V5"] != selection["FORMAL_V6"]:
        raise RuntimeError("STOP_FORMAL_V5_V6_SELECTION_MISMATCH")
    return {
        "records": records, "selection": selection, "population": population,
        "independent": independent_races, "tc": tc,
        "artifact_paths": {
            "CURRENT": current / "prediction_manifest.json",
            "INDEPENDENT_V5": PRE / "independent_v5" / "selection_manifest.json",
            "TRACKCONDITION_SEMANTIC": PRE / "trackcondition_semantic" / "horse_level_trace.json",
            "DAILY_V5_SAME_VOLUME": PRE / "daily_v5_same_volume" / "selection.json",
            "FORMAL_V5": PRE / "formal_v5_v6" / DATE / "dual_pre_semantic.json",
            "FORMAL_V6": PRE / "formal_v5_v6" / DATE / "dual_pre_semantic.json",
        },
    }


def result_1012(pre: dict[str, Any]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    raw = ROOT / "data" / "raw" / "target" / "daily_result_list"
    primary, auxiliary = raw / f"馬番順着順_{DATE}.csv", raw / f"着順馬番_{DATE}.csv"
    pair = validate_source_pair(primary, auxiliary, DATE)
    if pair.get("status") != "PASS":
        raise RuntimeError("STOP_RESULT_PAIR_VALIDATION")
    with primary.open(encoding="cp932", newline="") as f:
        primary_rows = {row[0]: row for row in csv.reader(f)}
    with auxiliary.open(encoding="cp932", newline="") as f:
        auxiliary_rows = {row[0]: row for row in csv.reader(f)}
    if set(primary_rows) != set(auxiliary_rows):
        raise RuntimeError("STOP_RESULT_VARIANT_RACE_SET_MISMATCH")
    index = pair["source_d_primary"]["race_index"]
    consistency = _crosscheck_finish_order(primary_rows, auxiliary_rows, index)
    if consistency.get("status") != "PASS":
        raise RuntimeError("STOP_RESULT_FINISH_RECONCILIATION")
    by_identity = {(x["venue_name"], int(x["race_number"])): key for key, x in index.items()}
    outcomes: dict[tuple[str, str], dict[str, Any]] = {}
    for rid, record in pre["records"].items():
        key = by_identity.get((JA[record["venue"]], record["race_number"]))
        if key is None or int(index[key]["head_count"]) != len(record["ranked"]):
            raise RuntimeError(f"STOP_RESULT_PRE_IDENTITY_MISMATCH:{rid}")
        row = primary_rows[key]
        for no in record["names"]:
            raw_finish = row[11 + int(no)].strip()
            valid = raw_finish.isdigit() and int(raw_finish) > 0
            outcomes[K(rid, no)] = {
                "finish": int(raw_finish) if valid else None,
                "valid_result": valid,
                "actual_top3": bool(valid and int(raw_finish) <= 3),
                "raw_result": raw_finish,
            }
    meta = {"primary_path": str(primary.relative_to(ROOT)), "auxiliary_path": str(auxiliary.relative_to(ROOT)),
            "primary_sha256": sha(primary), "auxiliary_sha256": sha(auxiliary),
            "result_race_count": len(index), "result_horse_count": sum(int(x["head_count"]) for x in index.values()),
            "pair_status": pair["status"], "finish_consistency": consistency}
    return outcomes, meta


def metric(keys, outcomes):
    valid = [k for k in keys if outcomes[k]["valid_result"]]
    hits = [k for k in valid if outcomes[k]["actual_top3"]]
    races = {k[0] for k in keys}
    success = {k[0] for k in hits}
    return {"selected_N": len(keys), "valid_N": len(valid), "invalid_N": len(keys) - len(valid),
            "Top3_hits": len(hits), "BUY_TOP3_RATE": len(hits) / len(valid) if valid else None,
            "selected_races": len(races), "race_success_count": len(success),
            "race_success_rate": len(success) / len(races) if races else None}


def manual_selection(pre: dict[str, Any]) -> dict[str, set[str]]:
    data = {
        "kyoto_7R": (12, 16, 15), "kyoto_9R": (3, 4, 1), "kyoto_10R": (5, 2, 7),
        "kyoto_11R": (13, 1, 9), "kyoto_12R": (14, 1, 16), "tokyo_7R": (8, 15),
        "tokyo_8R": (4, 2), "tokyo_9R": (8, 11, 10), "tokyo_10R": (11, 1, 2),
        "tokyo_11R": (1, 7, 2), "tokyo_12R": (1, 11, 8),
    }
    out = {}
    for suffix, values in data.items():
        rid = f"race_{DATE}_{suffix}"
        if rid not in pre["records"] or not all(str(n) in pre["records"][rid]["names"] for n in values):
            raise RuntimeError(f"STOP_MANUAL_PRE_IDENTITY_MISMATCH:{rid}")
        out[rid] = {str(n) for n in values}
    return out


def skip_review(pre, outcomes):
    tc_map = {(r["race_id"], str(r["horse_number"])): r for r in pre["tc"]}
    rows, counts = [], defaultdict(int)
    for race in (7, 8, 10, 11, 12):
        rid = f"race_{DATE}_tokyo_{race}R"; record = pre["records"][rid]
        independent = {str(x["horse_number"]): x for x in pre["independent"][rid].get("candidate_horses", [])}
        trace = record["payload"].get("buy_gate_trace", {}).get("horses", [])
        by_no = {str(x["horse_number"]): x for x in trace}
        for no, name in record["names"].items():
            outcome = outcomes[K(rid, no)]
            if not outcome["actual_top3"]:
                continue
            info, ind, t = by_no.get(no, {}), independent.get(no), tc_map.get((rid, no), {})
            top5 = int(info.get("rank", 999)) <= 5
            reliability = info.get("reliability_pass", info.get("effective_reliability_pass", "NOT_RECORDED_IN_ARTIFACT"))
            absolute = info.get("absolute_quality_pass", "NOT_RECORDED_IN_ARTIFACT")
            risk = info.get("risk_guard_pass", "NOT_RECORDED_IN_ARTIFACT")
            shadow = info.get("shadow_buy_candidate", "NOT_RECORDED_IN_ARTIFACT")
            reliability_only = reliability is False and absolute is True and risk is True
            risk_fail = risk is False
            counts["top3"] += 1; counts["top5"] += int(top5); counts["reliability_only"] += int(reliability_only); counts["risk_guard"] += int(risk_fail)
            rows.append({"venue": "東京", "race": race, "race_id": rid, "horse_number": int(no), "horse_name": name,
                         "finish": outcome["finish"], "current_top5": top5, "shadow_buy_candidate": shadow,
                         "reliability_pass": reliability, "absolute_quality_pass": absolute, "risk_guard_pass": risk,
                         "failed_reliability_only": reliability_only, "failed_risk_guard": risk_fail,
                         "independent_probability": ind.get("p_top3", "NOT_RECORDED_IN_ARTIFACT") if ind else "NOT_RECORDED_IN_ARTIFACT",
                         "independent_risk_guard_pass": ind.get("risk_guard_pass", "NOT_RECORDED_IN_ARTIFACT") if ind else "NOT_RECORDED_IN_ARTIFACT",
                         "tc_risk_guard_pass": t.get("risk_guard_pass", "NOT_RECORDED_IN_ARTIFACT") if t else "NOT_RECORDED_IN_ARTIFACT"})
    return rows, counts


def hash_index(root: Path):
    index = {p.name: sha(p) for p in root.iterdir() if p.is_file() and p.name != "artifact_hashes.json"}
    dump(root / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": index})
    if any(sha(root / n) != h for n, h in index.items()):
        raise RuntimeError(f"STOP_ARTIFACT_HASH_MISMATCH:{root}")


def run_post(pre, outcomes, result_meta):
    if POST.exists():
        raise RuntimeError("STOP_POST_OUTPUT_ALREADY_EXISTS")
    POST.mkdir(parents=True)
    lane_rows, metrics = [], {}
    for lane in LANES:
        keys = {(rid, no) for rid, ns in pre["selection"][lane].items() for no in ns}
        metrics[lane] = metric(keys, outcomes)
        lane_rows.append({"lane": lane, **metrics[lane]})
    manual = manual_selection(pre)
    manual_keys = {(rid, no) for rid, ns in manual.items() for no in ns}
    metrics["CHATGPT_AI_REVIEW_PRE"] = metric(manual_keys, outcomes)
    lane_rows.append({"lane": "CHATGPT_AI_REVIEW_PRE", "role": "MANUAL_EXPLORATORY_PRE_TRACK", **metrics["CHATGPT_AI_REVIEW_PRE"]})
    selected_rows, race_rows = [], []
    for rid, record in sorted(pre["records"].items()):
        race_row = {"venue": JA[record["venue"]], "race": record["race_number"], "race_id": rid, "current_state": record["state"]}
        for lane in LANES:
            values = []
            for no in sorted(pre["selection"][lane][rid], key=int):
                o = outcomes[K(rid, no)]
                selected_rows.append({"venue": JA[record["venue"]], "race": record["race_number"], "race_id": rid, "lane": lane,
                                      "horse_number": int(no), "horse_name": record["names"][no], **o})
                values.append(f"#{no} {record['names'][no]} ({o['finish'] if o['valid_result'] else 'INVALID'})")
            race_row[lane] = " / ".join(values) if values else "NONE"
        race_rows.append(race_row)
    manual_rows = []
    for rid, nos in manual.items():
        r = pre["records"][rid]
        for no in sorted(nos, key=int):
            manual_rows.append({"role": "MANUAL_EXPLORATORY_PRE_TRACK", "venue": JA[r["venue"]], "race": r["race_number"], "race_id": rid,
                                "horse_number": int(no), "horse_name": r["names"][no], **outcomes[K(rid, no)]})
    skip_rows, skip_counts = skip_review(pre, outcomes)
    write_csv(POST / "lane_metrics.csv", lane_rows); write_csv(POST / "selected_horse_results.csv", selected_rows)
    write_csv(POST / "race_level_comparison.csv", race_rows); write_csv(POST / "tokyo_skip_result_review.csv", skip_rows)
    write_csv(POST / "chatgpt_ai_review_results.csv", manual_rows)
    lines = ["# 2026-10-12 Official POST Result Review", "", "`PRE_RERUN_AFTER_FREEZE = FALSE`", "`PRE_SELECTION_CHANGED = FALSE`", "`KYOTO_8R = NOT_EVALUATED`", "", "## Lane metrics", "", "| Lane | Hits / valid N | Rate | Race success |", "|---|---:|---:|---:|"]
    lines += [f"| {lane} | {m['Top3_hits']} / {m['valid_N']} | {m['BUY_TOP3_RATE']:.2%} | {m['race_success_count']} / {m['selected_races']} |" for lane, m in metrics.items()]
    lines += ["", "## Tokyo Current SKIP", "", f"- Top3 horses: {skip_counts['top3']}", f"- In Current Top5: {skip_counts['top5']}", f"- Reliability-only failure: {skip_counts['reliability_only']}", f"- Risk-guard failure: {skip_counts['risk_guard']}", "", "Result join used the official two-file result pair after validation. This is a retrospective diagnostic only."]
    (POST / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hash_index(POST)
    return metrics, skip_counts


def run_v2(pre_1012, out_1012):
    if V2.exists():
        raise RuntimeError("STOP_V2_OUTPUT_ALREADY_EXISTS")
    V2.mkdir(parents=True)
    dates = tuple(V1_DATES) + (DATE,)
    pres = {d: frozen(d) for d in V1_DATES}; pres[DATE] = pre_1012
    outs, metas = {}, {}
    for d in V1_DATES:
        outs[d], metas[d] = results(d, pres[d])
    outs[DATE] = out_1012
    daily, unions, increments, states, recovered, inputs = [], [], [], [], [], []
    base = ("CURRENT", "DAILY_V5_SAME_VOLUME", "INDEPENDENT_V5")
    combos = {"CURRENT_UNION_DAILY": ("CURRENT", "DAILY_V5_SAME_VOLUME"), "CURRENT_UNION_INDEPENDENT": ("CURRENT", "INDEPENDENT_V5"), "DAILY_UNION_INDEPENDENT": ("DAILY_V5_SAME_VOLUME", "INDEPENDENT_V5"), "CURRENT_UNION_DAILY_UNION_INDEPENDENT": base}
    for d in dates:
        p, o = pres[d], outs[d]
        inputs.append({"date": d, "canonical_pre_artifacts": {k: str(v.relative_to(ROOT)) for k, v in p["artifact_paths"].items()}, "official_1012": d == DATE})
        for lane in base:
            daily.append({"date": d, "lane": lane, **metric(S(p, lane), o)})
        for name, lanes in combos.items():
            unions.append({"date": d, "combination": name, **metric(union(p, lanes), o)})
        current = S(p, "CURRENT")
        for name, lane in (("CURRENT_PLUS_DAILY", "DAILY_V5_SAME_VOLUME"), ("CURRENT_PLUS_INDEPENDENT", "INDEPENDENT_V5")):
            added = S(p, lane) - current; m = metric(added, o)
            increments.append({"date": d, "comparison": name, "source_lane": lane, "incremental_selected_N": len(added), "incremental_Top3_hits": m["Top3_hits"], "incremental_rate": m["BUY_TOP3_RATE"]})
        for state in ("PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"):
            rids = [rid for rid, r in p["records"].items() if r["state"] == state]
            miss = {(rid, no) for rid in rids for no in p["records"][rid]["names"] if no not in p["selection"]["CURRENT"][rid] and o[K(rid, no)]["valid_result"] and o[K(rid, no)]["actual_top3"]}
            added = {(rid, no) for rid in rids for no in p["selection"]["INDEPENDENT_V5"][rid] if no not in p["selection"]["CURRENT"][rid]}
            hit = miss & added
            states.append({"date": d, "current_state": state, "races": len(rids), "current_nonselected_top3_N": len(miss), "independent_additional_N": len(added), "recovered_top3_hits": len(hit), "recovery_rate": len(hit) / len(miss) if miss else None})
            for rid, no in sorted(hit):
                r = p["records"][rid]; recovered.append({"date": d, "venue": JA[r["venue"]], "race": r["race_number"], "race_id": rid, "horse_number": int(no), "horse_name": r["names"][no], "current_state": state})
    pooled_outcomes = {k: v for d in dates for k, v in outs[d].items()}
    for lane in base:
        daily.append({"date": "POOLED", "lane": lane, **metric(set().union(*(S(pres[d], lane) for d in dates)), pooled_outcomes)})
    for name, lanes in combos.items():
        unions.append({"date": "POOLED", "combination": name, **metric(set().union(*(union(pres[d], lanes) for d in dates)), pooled_outcomes)})
    for name, lane in (("CURRENT_PLUS_DAILY", "DAILY_V5_SAME_VOLUME"), ("CURRENT_PLUS_INDEPENDENT", "INDEPENDENT_V5")):
        cur = set().union(*(S(pres[d], "CURRENT") for d in dates)); add = set().union(*(S(pres[d], lane) for d in dates)) - cur; m = metric(add, pooled_outcomes)
        increments.append({"date": "POOLED", "comparison": name, "source_lane": lane, "incremental_selected_N": len(add), "incremental_Top3_hits": m["Top3_hits"], "incremental_rate": m["BUY_TOP3_RATE"]})
    for state in ("PLAY_CONVERGED", "PLAY_UNCONVERGED_4PLUS", "SKIP"):
        rows = [row for row in states if row["current_state"] == state]
        misses = sum(row["current_nonselected_top3_N"] for row in rows)
        recovered_n = sum(row["recovered_top3_hits"] for row in rows)
        states.append({"date": "POOLED", "current_state": state, "races": sum(row["races"] for row in rows),
                       "current_nonselected_top3_N": misses, "independent_additional_N": sum(row["independent_additional_N"] for row in rows),
                       "recovered_top3_hits": recovered_n, "recovery_rate": recovered_n / misses if misses else None})
    write_csv(V2 / "daily_lane_metrics.csv", daily); write_csv(V2 / "pooled_lane_metrics.csv", [x for x in daily if x["date"] == "POOLED"])
    write_csv(V2 / "union_metrics.csv", unions); write_csv(V2 / "incremental_contribution.csv", increments); write_csv(V2 / "current_state_recovery.csv", states); write_csv(V2 / "recovered_top3_horses.csv", recovered)
    dump(V2 / "canonical_input_index.json", {"role": "RESULT_DRIVEN_RETROSPECTIVE_DIAGNOSTIC_ONLY", "dates": list(dates), "inputs": inputs, "pre_selection_changed": False, "prediction_rerun": False, "training": False, "production_changed": False})
    pool = {x["lane"]: x for x in daily if x["date"] == "POOLED"}; inc = {x["comparison"]: x for x in increments if x["date"] == "POOLED"}
    lines = ["# Prospective Multi-Lane Complementarity Diagnostic v2", "", "`ANALYSIS_ROLE = RESULT_DRIVEN_RETROSPECTIVE_DIAGNOSTIC_ONLY`", "`DATE_SCOPE = 2026-09-26 to 2026-10-12`", "", "## Pooled base lanes", "", "| Lane | Hits / valid N | Rate |", "|---|---:|---:|"]
    lines += [f"| {lane} | {pool[lane]['Top3_hits']} / {pool[lane]['valid_N']} | {pool[lane]['BUY_TOP3_RATE']:.2%} |" for lane in base]
    lines += ["", "## Current incremental", "", "| Comparison | Added hits / N | Rate |", "|---|---:|---:|"]
    lines += [f"| {name} | {x['incremental_Top3_hits']} / {x['incremental_selected_N']} | {x['incremental_rate']:.2%} |" for name, x in inc.items()]
    lines += ["", "`NO_NEW_BUY_RULE_AUTHORIZED = TRUE`"]
    (V2 / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hash_index(V2)
    return pool, inc, states


def main():
    pre = frozen_1012()  # Freeze and selection validation precede every result read.
    outcomes, result_meta = result_1012(pre)
    metrics, skip = run_post(pre, outcomes, result_meta)
    pool, inc, states = run_v2(pre, outcomes)
    print(json.dumps({"official_post": "COMPLETE", "result_validation": result_meta, "lane_metrics": metrics, "tokyo_skip": dict(skip), "updated": {"lanes": pool, "incremental": inc}, "safety": {"pre_changed": False, "prediction_rerun": False, "training": False, "production_changed": False}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
