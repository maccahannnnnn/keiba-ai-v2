"""I/O-free canonical fold for Formal cumulative evidence."""
from __future__ import annotations
from typing import Any
from review.current_corrected_shadow_v2_prospective_protocol_v1 import verdict

def fold_cumulative_evidence(events: list[dict[str, Any]]) -> dict[str, Any]:
    races=[row for event in events for row in event.get('counted_race_rows',[])]
    cv=sum(int(row['comparator']['valid_selected_n']) for row in races); ch=sum(int(row['comparator']['hits']) for row in races)
    pv=sum(int(row['primary']['valid_selected_n']) for row in races); ph=sum(int(row['primary']['hits']) for row in races)
    sv=sum(int(row['secondary']['valid_selected_n']) for row in races); sh=sum(int(row['secondary']['hits']) for row in races)
    lift=None if not cv or not pv else ((ph/pv)-(ch/cv))*100
    races_n=len(races); dates_n=len({row['target_date'] for row in races}); blocks=sorted({row['block_id'] for row in races}); shortfall=sum(int(row['shortfall']) for row in races)
    if races_n < 60 or dates_n < 12: state,consumed,terminal,label='HOLD:EVIDENCE_QUANTITY',False,None,None
    else:
        state=verdict(races_n,dates_n,shortfall,lift if lift is not None else 0.0); consumed=True
        terminal=state if state.endswith('ACCEPT') or state.endswith('REJECT') else None
        label='PRODUCTION_DESIGN_REVIEW_ELIGIBLE' if state.endswith('ACCEPT') else None
    return {'counted_races':races_n,'counted_dates':dates_n,'blocks':blocks,'accumulated_blocks':len(blocks),'comparator':{'valid_selected_n':cv,'hits':ch,'rate':None if not cv else ch/cv},'primary':{'valid_selected_n':pv,'hits':ph,'rate':None if not pv else ph/pv},'secondary':{'valid_selected_n':sv,'hits':sh,'rate':None if not sv else sh/sv},'raw_hit_difference':ph-ch,'shortfall':shortfall,'pooled_lift_pt':lift,'minimum_reached':races_n>=60 and dates_n>=12,'protocol_state_after':state,'evaluation_point_consumed':consumed,'terminal_verdict':terminal,'candidate_label':label}
