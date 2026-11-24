"""Reusable semantic comparison for Historical Replay run roots."""
from __future__ import annotations
import csv,json
from pathlib import Path

HORSE_FIELDS=("horse_name","horse_number","final_score","adjusted_score","ai_rank","decision","race_decision","confidence_level","confidence_score","buy_v1_rc1_buy","buy_v1_rc1_decision","buy_v1_rc1_race_state")
LEDGER_FIELDS=("race_id","horse_count","provenance_complete_count","trace_count","top5_boundary_tie_count","status","error")
def _json(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def _evaluator_rows(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as handle:rows=list(csv.DictReader(handle))
    return sorted(({k:v for k,v in row.items() if k not in ("source_file","source_sha256")} for row in rows),key=lambda x:(x["race_id"],x["horse_number"],x["evaluator_name"]))
def _add(diffs,race_id,horse,field,left,right,kind="SEMANTIC"):
    if left!=right:diffs.append({"race_id":race_id,"horse_name":horse,"field":field,"left":left,"right":right,"classification":kind})
def compare(left_root,right_root):
    left=Path(left_root);right=Path(right_root);diffs=[];metadata=[]
    lp={x.parents[1].name:x for x in left.glob("*/race_*/analysis/pre_analysis.json")};rp={x.parents[1].name:x for x in right.glob("*/race_*/analysis/pre_analysis.json")}
    _add(diffs,"","","race_id_set",sorted(lp),sorted(rp))
    for race_id in sorted(set(lp)&set(rp)):
        la=_json(lp[race_id]);ra=_json(rp[race_id]);lh={str(x.get("horse_number")):x for x in la["horses"]};rh={str(x.get("horse_number")):x for x in ra["horses"]};_add(diffs,race_id,"","horse_set",sorted(lh),sorted(rh))
        for number in sorted(set(lh)&set(rh),key=lambda x:int(x) if x.isdigit() else x):
            for field in HORSE_FIELDS:_add(diffs,race_id,lh[number].get("horse_name",""),field,lh[number].get(field),rh[number].get(field))
        le=next((lp[race_id].parents[1]/"ranking_provenance/pre_race").glob("*evaluator_long.csv"));re=next((rp[race_id].parents[1]/"ranking_provenance/pre_race").glob("*evaluator_long.csv"));_add(diffs,race_id,"","evaluator_provenance",_evaluator_rows(le),_evaluator_rows(re))
        post_fields=("horse_number","actual_finish","actual_top3","actual_top5","valid_result");lpost=_json(lp[race_id].parents[1]/"post_race/post_joined.json");rpost=_json(rp[race_id].parents[1]/"post_race/post_joined.json");_add(diffs,race_id,"","result_join",[{k:x.get(k) for k in post_fields} for x in lpost["horses"]],[{k:x.get(k) for k in post_fields} for x in rpost["horses"]])
    ll=_json(left/"ledger.json");rl=_json(right/"ledger.json");_add(diffs,"","","ledger",[{k:x.get(k) for k in LEDGER_FIELDS} for x in ll["entries"]],[{k:x.get(k) for k in LEDGER_FIELDS} for x in rl["entries"]])
    for field in ("run_id","generated_at"):
        lv=_json(left/"run_manifest.json").get(field);rv=_json(right/"run_manifest.json").get(field)
        if lv!=rv:metadata.append({"field":field,"left":lv,"right":rv})
    judgment="SEMANTIC_DIFF_FOUND" if diffs else ("SEMANTIC_MATCH_WITH_METADATA_DIFF" if metadata else "SEMANTIC_EXACT_MATCH")
    return {"judgment":judgment,"semantic_difference_count":len(diffs),"metadata_difference_count":len(metadata),"differences":diffs,"metadata_differences":metadata}
def write_csv(result,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise FileExistsError(path)
    with path.open("w",encoding="utf-8-sig",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=("race_id","horse_name","field","left","right","classification"));writer.writeheader();writer.writerows(result["differences"])
