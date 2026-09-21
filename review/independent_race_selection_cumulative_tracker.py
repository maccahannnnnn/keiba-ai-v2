"""Pure cumulative decision rule for frozen Independent Race Selection blocks."""
from __future__ import annotations
def decision(blocks:list[dict])->str:
    dates={d for b in blocks for d in b["race_dates"]}; selected=sum(b["selected_races"] for b in blocks)
    if len(blocks)<2 or len(dates)<4 or selected<60: return "HOLD_ACCUMULATE"
    independent_hits=sum(b["independent_hits"] for b in blocks); current_hits=sum(b["current_hits"] for b in blocks)
    independent_valid=sum(b["independent_valid"] for b in blocks); current_valid=sum(b["current_valid"] for b in blocks)
    ir=independent_hits/independent_valid if independent_valid else 0; cr=current_hits/current_valid if current_valid else 0
    nonnegative=sum((b["independent_hits"]/b["independent_valid"] if b["independent_valid"] else 0)>=(b["current_hits"]/b["current_valid"] if b["current_valid"] else 0) for b in blocks)
    if ir>=cr and independent_hits>=current_hits and nonnegative>=2: return "CONTROLLED_TRIAL_DISCUSSION_ACCEPT"
    if ir<cr and independent_hits<=current_hits: return "REJECT_CONTROLLED_TRIAL"
    return "HOLD_EXTEND_WITHOUT_RETUNE"
