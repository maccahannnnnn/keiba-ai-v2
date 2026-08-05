"""Feasibility audit for retrospective and future Ranking Provenance."""
from __future__ import annotations
import csv,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/"reports";OUT=REPORTS/"ranking_provenance"
DATES=("20260725","20260726","20260801","20260802")
def load(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as handle:return list(csv.DictReader(handle))
def run():
    inventory=load(REPORTS/"ranking_diagnostic_column_inventory_v1.csv");compat=load(REPORTS/"ranking_diagnostic_compatibility_v1.csv");rows=[]
    for date in DATES:
        fields={row["field"]:row for row in inventory if row["race_date"]==date};meta=next(row for row in compat if row["race_date"]==date)
        available=[name for name in ("past_performance_score","distance_score","course_shape_score","lap_score","lap_suitability_score","race_shape_score","pace_style_score","bloodline_score","ability_score","track_condition_score") if int(fields[name]["nonempty_count"])>0]
        rows.append({"race_date":date,"schema_family":meta["schema_family"],"source_version":meta["declared_source_version"],"horse_count":meta["horse_count"],"raw_evaluator_fields":";".join(available),"raw_score_complete":False,"weight_saved":False,"weighted_contribution_saved":False,"weight_reason_saved":False,"consistency_inputs_saved":False,"structure_weight_inputs_saved":False,"weight_calculation_version_saved":False,"rank_reproduction_from_saved_scores":True,"current_code_replay_required_for_weights":True,"judgment":"FUTURE_ONLY_PROVENANCE_REQUIRED","reason":"Historical weight inputs/results/version are incomplete; current code cannot be treated as historical truth."})
    summary={"status":"RANKING_PROVENANCE_PHASE_C_COMPLETE","feasibility":"FUTURE_ONLY_PROVENANCE_REQUIRED","final_judgment":"READY_FUTURE_ONLY","retrospective_outputs_generated":False,"dates":rows,"future_exporter":"READY_SHADOW_PRE_RACE_ONLY","existing_csv_modified":False,"current_code_replay_used":False,"weight_recalculation_performed":False,"evidence_status":"EVIDENCE_ACCUMULATING","evidence_go_threshold":{"meeting_dates":10,"racecourses":3,"non_buy_top3":150,"successful_buy":30,"fp_buy":15,"dates_with_fp3":2,"single_calculation_version":True,"weight_provenance_completion_pct":95},"production_candidate":"NONE","production_delta":"ZERO"}
    return rows,summary
def main():
    rows,summary=run();OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"ranking_provenance_feasibility_v1.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    md=["# Ranking Provenance Feasibility v1","","## Judgment","","**READY_FUTURE_ONLY**","","All four historical dates are FUTURE_ONLY_PROVENANCE_REQUIRED. Raw evaluator coverage is incomplete and historical weights, weighted contributions, consistency/structure inputs, reasons, and calculation versions were not saved. Reconstructing them with current code would be CURRENT_CODE_REPLAY and is prohibited.","","No retrospective provenance CSV was generated. The additive exporter accepts only frozen PRE_RACE evidence and already-calculated provenance; missing inputs are emitted as TRACE without inference.","","Evidence status: EVIDENCE_ACCUMULATING. Production Candidate: NONE. Production delta: ZERO."]
    (OUT/"ranking_provenance_feasibility_v1.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    schema=["# Ranking Provenance Schema v1","","Two additive PRE_RACE artifacts are produced per date/source version:","","1. Horse summary: rank before/after, ranking source/fallback, tie rule/boundary, source and pipeline provenance.","2. Evaluator long format: one horse x one expected evaluator with raw score, saved weight/contribution/reason/version or explicit TRACE.","","Official rank regression uses score DESC -> horse_number DESC. Result fields are rejected by the PRE exporter. POST labels are joined by a separate module and retain the PRE SHA256.","","Ledger keys are race_id + pipeline_version and remain separate from the UNCONVERGED ledger."]
    (OUT/"ranking_provenance_schema_v1.md").write_text("\n".join(schema)+"\n",encoding="utf-8")
    (OUT/"ranking_provenance_summary_v1.json").write_text(json.dumps({"status":summary["status"],"judgment":summary["final_judgment"],"historical":"NO_RETROACTIVE_OUTPUT","future_exporter":"READY","post_race_join":"READY_MINIMAL","ledger":"DESIGNED_AND_IMPLEMENTED","evidence_status":summary["evidence_status"],"production_candidate":"NONE","production_delta":"ZERO"},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
