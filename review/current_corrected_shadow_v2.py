"""CURRENT_CORRECTED_SHADOW_V2 non-production correction semantics."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import median
from typing import Any

AUTHORITY_EVALUATORS = ("ability", "past_performance", "distance", "lap", "pace_style")
POSITIVE_THRESHOLDS = {"ability": 120.0, "past_performance": 55.0, "distance": 30.0, "lap": 0.0, "pace_style": 10.0}
STRONG_NEGATIVE_THRESHOLD = -5.0
RISK_FIELDS = ("weaknesses", "risk_factors", "decision_risks", "final_weaknesses", "final_risks")
AUTHORITY_RISK_CATEGORIES = {"GENUINE_INDEPENDENT_RISK", "TRUE_DATA_LIMITATION"}

@dataclass(frozen=True)
class CorrectionConfigV2:
    low_history_neutralization: bool = False
    reliability_correction: bool = False
    risk_semantic_dedupe: bool = False
    risk_authority_filter: bool = False
    severe_rule: bool = False
    neutral_pace: bool = False
    impact_trace_only: bool = False
    race_shape_trace_only: bool = False
    course_shape_trace_only: bool = False
    consistency_trace_only: bool = False
    decision_trace_only: bool = False
    absolute_quality_disable: bool = False
    score_gap_trace_only: bool = False
    competitive_skip_trace_only: bool = False
    consensus_rescue_disable: bool = False
    equal_component_weights: bool = False
    @classmethod
    def all_off(cls): return cls()
    @classmethod
    def all_on(cls): return cls(**{key: True for key in asdict(cls()).keys()})
    def enabled(self): return any(asdict(self).values())

def num(value: Any) -> float:
    try: return float(value or 0)
    except (TypeError, ValueError): return 0.0

def history_count(row: dict[str, Any]) -> int:
    return max(0, int(num(row.get("history_count"))))

def _norm(value: Any) -> str:
    return " ".join(str(value or "").replace("　", " ").split())

# Exact canonical vocabulary plus a numeric Low-Rank family. Unknown wording is fail-closed.
_RISK = {
"当日バイアス情報が限定的": ("OTHER_NON_AUTHORITY","same_day_bias_information_limited",False),
"展開面の不安": ("PACE_TRACE_ONLY","pace_uncertainty",False),
"ハイペースになると前半負荷が高い": ("PACE_TRACE_ONLY","high_pace_front_load",False),
"ラップ適性の不安": ("PACE_TRACE_ONLY","lap_uncertainty",False),
"展開不向き": ("PACE_TRACE_ONLY","pace_unsuitable",False),
"入力データに一部不足あり": ("OTHER_NON_AUTHORITY","input_data_incomplete",False),
"想定ラップへの上積みが限定的": ("PACE_TRACE_ONLY","lap_upside_limited",False),
"想定ラップと噛み合わない": ("PACE_TRACE_ONLY","lap_mismatch",False),
"重大リスクが複数": ("DERIVED_RISK","multiple_major_risks",False),
"構造一致度が低い": ("RACE_SHAPE_TRACE_ONLY","race_structure_low_match",False),
"コース形状とのズレ": ("COURSE_SHAPE_TRACE_ONLY","course_shape_mismatch",False),
"warningsあり": ("OTHER_NON_AUTHORITY","generic_warning",False),
"説明内に注意要素あり": ("OTHER_NON_AUTHORITY","explanation_warning",False),
"構造との矛盾あり": ("RACE_SHAPE_TRACE_ONLY","race_structure_contradiction",False),
"距離適性の不安": ("GENUINE_INDEPENDENT_RISK","distance_concern",False),
"距離適性に課題": ("GENUINE_INDEPENDENT_RISK","distance_concern",False),
"小回りで後方脚質": ("COURSE_SHAPE_TRACE_ONLY","course_shape_backrunner",False),
"コース形状と噛み合わない": ("COURSE_SHAPE_TRACE_ONLY","course_shape_mismatch",False),
"スローでは後方から届きにくい": ("PACE_TRACE_ONLY","slow_pace_backrunner",False),
"長い直線で逃げ粘りが課題": ("PACE_TRACE_ONLY","long_straight_front_runner",False),
"脚質判定に課題": ("PACE_TRACE_ONLY","pace_style_uncertain",False),
"近走内容に課題": ("GENUINE_INDEPENDENT_RISK","recent_form_concern",False),
"取消": ("GENUINE_INDEPENDENT_RISK","cancelled",True),
"除外": ("GENUINE_INDEPENDENT_RISK","excluded",True),
"出走不能": ("GENUINE_INDEPENDENT_RISK","unable_to_start",True),
"能力不足": ("GENUINE_INDEPENDENT_RISK","ability_insufficient",True),
"距離不適": ("GENUINE_INDEPENDENT_RISK","distance_unsuitable_current_keyword",True),
"データ不足が大きい": ("TRUE_DATA_LIMITATION","data_shortage",False),
"評価値が欠損": ("TRUE_DATA_LIMITATION","data_shortage",False),
"構造評価に必要な情報が不足": ("TRUE_DATA_LIMITATION","data_shortage",False),
}

def map_risk_text(raw: Any) -> dict[str, Any] | None:
    text = _norm(raw)
    mapped = ("DERIVED_RISK","low_rank_buy_guard",False) if text.startswith("Low Rank BUY Guard:") else _RISK.get(text)
    if mapped is None: return None
    category, cause, severe = mapped
    return {"raw_text":str(raw),"normalized_text":text,"category":category,"semantic_cause":cause,
            "authority":category in AUTHORITY_RISK_CATEGORIES,"severe":bool(severe)}

def row_risk_values(row: dict[str, Any]) -> list[Any]:
    return [item for field in RISK_FIELDS for item in ((row.get(field) or []) if isinstance(row.get(field) or [],list) else [row.get(field)])]

def map_risks(values: list[Any], *, dedupe: bool, authority_filter: bool) -> tuple[list[dict[str,Any]],list[str]]:
    mapped, unmapped, seen = [], [], set()
    for raw in values:
        item = map_risk_text(raw)
        if item is None: unmapped.append(_norm(raw)); continue
        if authority_filter and not item["authority"]: continue
        if dedupe and item["semantic_cause"] in seen: continue
        seen.add(item["semantic_cause"]); mapped.append(item)
    if unmapped: raise ValueError("UNMAPPED_RISK_TEXT:" + "|".join(sorted(set(unmapped))))
    return mapped, unmapped

def reliability_v2(row: dict[str,Any], original_pp: float) -> dict[str,Any]:
    scores={"ability":num(row.get("ability_score",row.get("total_score"))),"past_performance":original_pp,
            "distance":num(row.get("distance_score")),"lap":num(row.get("lap_score")),"pace_style":num(row.get("pace_style_score"))}
    positive=[key for key in AUTHORITY_EVALUATORS if scores[key]>=POSITIVE_THRESHOLDS[key]]
    negative=[key for key in AUTHORITY_EVALUATORS if scores[key]<=STRONG_NEGATIVE_THRESHOLD]
    return {"authority_evaluators":list(AUTHORITY_EVALUATORS),"scores":scores,"positive":positive,"negative":negative,
            "positive_count":len(positive),"negative_count":len(negative),"pass":len(positive)>=4 and len(negative)<=1}

def reliability_predicate(positive_count:int, negative_count:int) -> bool:
    """The final approved predicate, separately testable from score classification."""
    return positive_count >= 4 and negative_count <= 1

def risk_guard_detail(authority_risks:list[dict[str,Any]], severe_rule:bool) -> dict[str,Any]:
    severe=bool(severe_rule and any(r["severe"] for r in authority_risks))
    data_limitation=bool(any(r["category"]=="TRUE_DATA_LIMITATION" for r in authority_risks))
    risk_count_fail=len(authority_risks)>=6
    return {"severe":severe,"true_data_limitation":data_limitation,"authority_risk_count":len(authority_risks),"risk_count_fail":risk_count_fail,"pass":not(severe or data_limitation or risk_count_fail)}

def apply_corrected_shadow_v2(rows: list[dict[str,Any]], config: CorrectionConfigV2) -> list[dict[str,Any]]:
    refs=[num(row.get("past_performance_score")) for row in rows if history_count(row)>=2]
    race_median=float(median(refs)) if refs else None
    projected=[]
    for original in rows:
        row=dict(original); count=history_count(row); low=count<=1; pp_original=num(row.get("past_performance_score"))
        applied=bool(config.low_history_neutralization and low and race_median is not None)
        unavailable=bool(config.low_history_neutralization and low and race_median is None)
        pp_rank=race_median if applied else pp_original
        risk_family_active = config.risk_semantic_dedupe or config.risk_authority_filter or config.severe_rule
        if risk_family_active:
            risks,_=map_risks(row_risk_values(row),dedupe=config.risk_semantic_dedupe,
                              authority_filter=(config.risk_authority_filter or config.severe_rule))
            guard_detail=risk_guard_detail(risks,config.severe_rule)
        else:
            # All risk corrections OFF: do not add a Corrected-only gate.
            risks=[]; guard_detail={"severe":False,"true_data_limitation":False,"authority_risk_count":0,"risk_count_fail":False,"pass":True}
        reliability=reliability_v2(row,pp_original) if config.reliability_correction else {"authority_evaluators":list(AUTHORITY_EVALUATORS),"pass":True}
        components={"bloodline":num(row.get("bloodline_score")),"past_performance":pp_rank,"pace_style":num(row.get("pace_style_score")),"distance":num(row.get("distance_score")),"track_condition":num(row.get("track_condition_score")),"lap":num(row.get("lap_score")),"track_bias":num(row.get("track_bias_score"))}
        if not config.race_shape_trace_only: components["race_shape"]=num(row.get("shape_score"))
        if not config.course_shape_trace_only: components["course_shape"]=num(row.get("course_shape_score"))
        if not config.consistency_trace_only: components["consistency"]=num(row.get("consistency_score"))
        score=sum(components.values()) if config.equal_component_weights else num(row.get("adjusted_score",row.get("final_score")))
        row["corrected_shadow"]={"version":"CURRENT_CORRECTED_SHADOW_V2","integrated_score":score,"adjusted_score":score,"score_components":components,
          "low_history":low,"history_count":count,"imputation_applied":applied,"imputation_unavailable":unavailable,"past_performance_ranking_score":pp_rank,"past_performance_vote_score":pp_original,
          "reliability":reliability,"authority_risks":risks,"risk_guard":guard_detail["pass"],
          "risk_guard_detail":guard_detail,
          "trace":{"predicted_pace_original":row.get("race_pace_prediction"),"pace_authority_input":"average" if config.neutral_pace else row.get("race_pace_prediction"),"decision_score":row.get("decision_score"),"score_gap":row.get("score_gap"),"competitive_skip":row.get("competitive_skip"),"impact":row.get("impact_result"),"contradiction":row.get("conflict_factors"),"race_shape_score":row.get("shape_score"),"race_shape_table_key":(row.get("shape_result") or {}).get("race_shape_adjustment_id"),"course_shape":row.get("course_shape_result"),"lap":row.get("lap_result"),"consistency":row.get("consistency_result")}}
        projected.append(row)
    ranked=sorted(enumerate(projected),key=lambda it:(-num(it[1]["corrected_shadow"]["adjusted_score"]),it[0]))
    for rank,(_,row) in enumerate(ranked,1):
        shadow=row["corrected_shadow"]; shadow["rank"]=rank; shadow["candidate"]=bool(rank<=5 and shadow["reliability"]["pass"] and shadow["risk_guard"])
    n=sum(r["corrected_shadow"]["candidate"] for r in projected); state="SKIP" if n==0 else "PLAY_CONVERGED" if n<=3 else "PLAY_UNCONVERGED_4PLUS"
    for row in projected:
        shadow=row["corrected_shadow"]; shadow["race_state"]=state; shadow["buy"]=bool(shadow["candidate"] and state=="PLAY_CONVERGED")
    return projected
