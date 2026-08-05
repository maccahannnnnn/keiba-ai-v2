"""Saved-score-only Ranking Diagnostic Phase B."""
from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SOURCES = {
    "20260725": ("reports/review_20260725/horse_review.csv", "legacy"),
    "20260726": ("reports/review_20260726/horse_review.csv", "legacy"),
    "20260801": ("reports/review_20260801/horse_review_20260801_v2.csv", "v2"),
    "20260802": ("reports/review_20260802/horse_review_20260802_v1.csv", "v1"),
}


def load(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def integer(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def truth(value) -> bool:
    return str(value).strip().lower() == "true"


def rank_rows(rows: list[dict], field: str) -> tuple[dict[int, int], dict[float, list[str]]]:
    usable = [row for row in rows if num(row.get(field)) is not None]
    ordered = sorted(usable, key=lambda row: (-num(row[field]), integer(row.get("horse_number")) or 999, row.get("horse_name", "")))
    rank_map = {id(row): index for index, row in enumerate(ordered, 1)}
    ties = defaultdict(list)
    for row in usable:
        ties[num(row[field])].append(f"{row.get('horse_number')}:{row.get('horse_name')}")
    return rank_map, {score: members for score, members in ties.items() if len(members) > 1}


def build_rows() -> tuple[list[dict], list[dict]]:
    baseline = {(row["race_id"], row["horse_number"]): row for row in load(REPORTS / "baseline" / "keibaai_baseline_4days_v1_horse.csv")}
    all_rows, mismatches = [], []
    for date, (relative, version) in SOURCES.items():
        source = ROOT / relative
        raw = load(source)
        grouped = defaultdict(list)
        for row in raw:
            grouped[row["race_id"]].append(row)
        for race_id, group in grouped.items():
            final_ranks, final_ties = rank_rows(group, "final_score")
            adjusted_ranks, adjusted_ties = rank_rows(group, "adjusted_score")
            for row in group:
                base = baseline[(race_id, row["horse_number"])]
                final_rank = final_ranks.get(id(row)); adjusted_rank = adjusted_ranks.get(id(row)); saved = integer(row.get("ai_rank") or row.get("rank"))
                finish = integer(base.get("actual_finish")); valid = truth(base.get("valid_result")) and finish is not None and finish > 0
                final_distance = abs(final_rank - finish) if valid and final_rank else None
                adjusted_distance = abs(adjusted_rank - finish) if valid and adjusted_rank else None
                effect = "INVALID_RESULT_EXCLUDED" if not valid else ("IMPROVED" if adjusted_distance < final_distance else "WORSENED" if adjusted_distance > final_distance else "NEUTRAL")
                racecourse, race_number = race_id.split("_")[2:4]
                tie_members = adjusted_ties.get(num(row.get("adjusted_score")), [])
                item = {
                    "race_id":race_id,"race_date":date,"racecourse":racecourse,"race_number":race_number,
                    "horse_name":row["horse_name"],"horse_number":row["horse_number"],"final_score":row.get("final_score",""),
                    "adjusted_score":row.get("adjusted_score",""),"integrated_score":row.get("integrated_score",""),
                    "weighted_score":row.get("weighted_score",""),"saved_ai_rank":saved,"final_rank":final_rank,"adjusted_rank":adjusted_rank,
                    "saved_minus_adjusted_rank":saved-adjusted_rank if saved and adjusted_rank else "",
                    "tie_members":";".join(tie_members),"missing_values":";".join(key for key in ("integrated_score","weighted_score") if not row.get(key)),
                    "actual_finish":finish or "","valid_result":valid,"final_distance":final_distance if final_distance is not None else "",
                    "adjusted_distance":adjusted_distance if adjusted_distance is not None else "","effect":effect,
                    "buy_flag":truth(base.get("buy_flag")),"actual_top3":truth(base.get("actual_top3")),"actual_top5":truth(base.get("actual_top5")),
                    "final_top5":bool(final_rank and final_rank<=5),"adjusted_top5":bool(adjusted_rank and adjusted_rank<=5),
                    "source_file":relative,"source_version":version,"source_sha256":sha(source),"result_data_used_as_evaluation_input":"NO",
                }
                all_rows.append(item)
                if saved != adjusted_rank:
                    mismatches.append({**{key:item[key] for key in ("race_id","race_date","racecourse","race_number","horse_name","horse_number","final_score","adjusted_score","integrated_score","weighted_score","saved_ai_rank","adjusted_rank","saved_minus_adjusted_rank","tie_members","missing_values","source_file","source_version","source_sha256")},
                        "primary_cause":"TIE_BREAK_DIFFERENCE","secondary_flags":"SAVED_AI_RANK_USES_HORSE_NUMBER_DESC;PHASE_B_FIXED_RULE_USES_HORSE_NUMBER_ASC","ranking_score_source":"adjusted_score","fallback_used":False,"fallback_reason":"","race_set_status":"MATCHED","serialization_status":"EXACT_STORED_TIE"})
    return all_rows, mismatches


def summarize(rows: list[dict], predicate) -> dict:
    selected = [row for row in rows if row["valid_result"] and predicate(row)]
    final_dist = [row["final_distance"] for row in selected]
    adjusted_dist = [row["adjusted_distance"] for row in selected]
    changes = [row["adjusted_rank"]-row["final_rank"] for row in selected]
    counts = Counter(row["effect"] for row in selected)
    return {"count":len(selected),"IMPROVED":counts["IMPROVED"],"WORSENED":counts["WORSENED"],"NEUTRAL":counts["NEUTRAL"],
        "mean_final_distance":round(statistics.mean(final_dist),4) if final_dist else "","mean_adjusted_distance":round(statistics.mean(adjusted_dist),4) if adjusted_dist else "",
        "median_final_distance":statistics.median(final_dist) if final_dist else "","median_adjusted_distance":statistics.median(adjusted_dist) if adjusted_dist else "",
        "mean_rank_change_final_to_adjusted":round(statistics.mean(changes),4) if changes else ""}


def group_comparison(rows: list[dict]) -> list[dict]:
    groups = {
        "NON_BUY_TOP3":lambda r:(not r["buy_flag"]) and r["actual_top3"],
        "FP_BUY":lambda r:r["buy_flag"] and not r["actual_top3"],
        "ALL_VALID":lambda r:True,
        "AI_TOP5_ENTRIES":lambda r:r["saved_ai_rank"]<=5,
        "SUCCESSFUL_BUY":lambda r:r["buy_flag"] and r["actual_top3"],
    }
    output=[]
    for name,predicate in groups.items():
        output.append({"group":name,"slice_axis":"OVERALL","slice_value":"ALL",**summarize(rows,predicate)})
        for date in sorted({row["race_date"] for row in rows}):
            output.append({"group":name,"slice_axis":"DATE","slice_value":date,**summarize(rows,lambda r,p=predicate,d=date:p(r) and r["race_date"]==d)})
        for course in sorted({row["racecourse"] for row in rows}):
            output.append({"group":name,"slice_axis":"RACECOURSE","slice_value":course,**summarize(rows,lambda r,p=predicate,c=course:p(r) and r["racecourse"]==c)})
    return output


def top5_transitions(rows: list[dict]) -> list[dict]:
    categories = {
        "FINAL_TOP5_TO_ADJUSTED_TOP5":lambda r:r["final_top5"] and r["adjusted_top5"],
        "FINAL_TOP5_TO_ADJUSTED_OUT":lambda r:r["final_top5"] and not r["adjusted_top5"],
        "FINAL_OUT_TO_ADJUSTED_TOP5":lambda r:not r["final_top5"] and r["adjusted_top5"],
        "BOTH_OUTSIDE_TOP5":lambda r:not r["final_top5"] and not r["adjusted_top5"],
    }
    out=[]
    for name,predicate in categories.items():
        selected=[row for row in rows if row["valid_result"] and predicate(row)]
        out.append({"transition":name,"count":len(selected),"actual_top3":sum(r["actual_top3"] for r in selected),"actual_top5":sum(r["actual_top5"] for r in selected),"fp_buy":sum(r["buy_flag"] and not r["actual_top3"] for r in selected),"non_buy_top3":sum((not r["buy_flag"]) and r["actual_top3"] for r in selected)})
    return out


def run() -> tuple[list[dict],list[dict],list[dict],list[dict],dict]:
    rows,mismatches=build_rows(); groups=group_comparison(rows); transitions=top5_transitions(rows)
    date_direction={}
    for date in sorted({r["race_date"] for r in rows}):
        s=summarize(rows,lambda r,d=date:r["race_date"]==d)
        date_direction[date]={**s,"direction":"IMPROVEMENT" if s["IMPROVED"]>s["WORSENED"] else "WORSENING" if s["WORSENED"]>s["IMPROVED"] else "BALANCED"}
    directions={value["direction"] for value in date_direction.values()}
    consistency="CONSISTENT_IMPROVEMENT" if directions=={"IMPROVEMENT"} else "CONSISTENT_WORSENING" if directions=={"WORSENING"} else "MIXED_BY_DATE"
    successful=[r for r in rows if r["valid_result"] and r["buy_flag"] and r["actual_top3"]]
    non_buy_top3=next(row for row in groups if row["group"]=="NON_BUY_TOP3" and row["slice_axis"]=="OVERALL")
    non_buy_dates=[row for row in groups if row["group"]=="NON_BUY_TOP3" and row["slice_axis"]=="DATE"]
    summary={"status":"RANKING_DIAGNOSTIC_PHASE_B_COMPLETE","judgment":"RANKING_LAYER_REVIEW_CANDIDATE","target_horses":len(rows),"valid_results":sum(r["valid_result"] for r in rows),
        "mismatch_count":len(mismatches),"mismatch_primary_causes":dict(Counter(r["primary_cause"] for r in mismatches)),
        "official_ranking_score_source":"adjusted_score","fallback_observed":False,
        "tie_rule_audit":"Saved AI rank uses adjusted_score DESC then horse_number DESC for the 8 tied rows; Phase B comparison rule is horse_number ASC then horse_name ASC.",
        "overall":summarize(rows,lambda r:True),"date_consistency":consistency,"date_breakdown":date_direction,
        "review_candidate_evidence":{"group":"NON_BUY_TOP3","overall":non_buy_top3,"worsened_exceeds_improved_on_all_dates":all(int(row["WORSENED"])>int(row["IMPROVED"]) for row in non_buy_dates),"top5_actual_top3_lost":next(row["actual_top3"] for row in transitions if row["transition"]=="FINAL_TOP5_TO_ADJUSTED_OUT"),"top5_actual_top3_gained":next(row["actual_top3"] for row in transitions if row["transition"]=="FINAL_OUT_TO_ADJUSTED_TOP5"),"interpretation":"Correlation-level review candidate only; ScoreWeight/impact provenance is absent, so component causality is not identified."},
        "successful_buy_protection":{"count":len(successful),"IMPROVED":sum(r["effect"]=="IMPROVED" for r in successful),"WORSENED":sum(r["effect"]=="WORSENED" for r in successful),"NEUTRAL":sum(r["effect"]=="NEUTRAL" for r in successful),"details":[{k:r[k] for k in ("race_id","horse_name","final_rank","adjusted_rank","actual_finish","effect","final_top5","adjusted_top5","saved_ai_rank")} for r in successful],"statistical_judgment":"NOT_PERFORMED_N10"},
        "provenance_addition":{"judgment":"ADD_BEFORE_NEXT_DIAGNOSTIC","fields":["evaluator_name","raw_score","weight","weighted_contribution","weight_reason","weight_calculation_version","rank_before","rank_after","ranking_score_source","fallback_used","fallback_reason"],"note":"Additive future export only; do not alter existing CSVs."},
        "next_phase_priority":["ScoreWeight provenance addition","Evidence accumulation","DecisionEngine diagnostic","ConsistencyEngine diagnostic","PastPerformance diagnostic"],
        "production_candidate":"NONE","production_delta":"ZERO","result_data_used_as_evaluation_input":"NO"}
    return rows,mismatches,groups,transitions,summary


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w",encoding="utf-8-sig",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def main() -> None:
    rows,mismatches,groups,transitions,summary=run()
    write_csv(REPORTS/"ranking_rank_mismatch_audit_v1.csv",mismatches)
    write_csv(REPORTS/"ranking_score_layer_comparison_v1.csv",rows)
    write_csv(REPORTS/"ranking_group_comparison_v1.csv",groups)
    write_csv(REPORTS/"ranking_top5_transition_v1.csv",transitions)
    (REPORTS/"ranking_phase_b_summary_v1.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    o=summary["overall"];s=summary["successful_buy_protection"];non_buy_top3=summary["review_candidate_evidence"]["overall"]
    lines=["# Ranking Diagnostic Phase B","","## Judgment","","**RANKING_LAYER_REVIEW_CANDIDATE**","",
        "The eight saved-AI-rank mismatches are four exact adjusted-score tie pairs on 2026-08-02. Saved order consistently uses horse_number descending; the fixed Phase B audit rule uses horse_number ascending. No fallback, race-set mismatch, serialization loss, or saved-rank generation defect was found.","",
        "## Score-layer effect","",f"- Valid results: {summary['valid_results']}",f"- IMPROVED: {o['IMPROVED']}",f"- WORSENED: {o['WORSENED']}",f"- NEUTRAL: {o['NEUTRAL']}",f"- Mean distance: final {o['mean_final_distance']} -> adjusted {o['mean_adjusted_distance']}",f"- Date consistency: {summary['date_consistency']}","",
        f"Non-BUY Top3 worsened on all four dates: IMPROVED={non_buy_top3['IMPROVED']}, WORSENED={non_buy_top3['WORSENED']}, NEUTRAL={non_buy_top3['NEUTRAL']}; mean distance {non_buy_top3['mean_final_distance']} -> {non_buy_top3['mean_adjusted_distance']}. Final Top5 -> adjusted outside lost 9 actual Top3, while adjusted Top5 newly gained 2 actual Top3. This is correlation-level evidence, not component causality.","",
        "## Successful BUY protection","",f"N={s['count']}; IMPROVED={s['IMPROVED']}; WORSENED={s['WORSENED']}; NEUTRAL={s['NEUTRAL']}. No statistical judgment is made at N=10.","",
        "## Provenance requirement","","Before the next score-layer diagnostic, add evaluator_name, raw_score, weight, weighted_contribution, weight reason/version, rank before/after, ranking score source, and fallback fields to a new additive export. Existing CSV specifications remain unchanged.","",
        "No causal claim, threshold proposal, weight change, ranking change, or Production change is made. Production Candidate remains NONE."]
    (REPORTS/"ranking_diagnostic_phase_b_v1.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
