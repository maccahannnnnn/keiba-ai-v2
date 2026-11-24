"""Focused Result-free tests for Selection Composition Policy v2."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.candidate_generation_stage_b_shadow_v1 import CandidateGenerationStageBShadow, EXACT5_TIE_BREAK_ID
from review.selection_composition_policy_v2_shadow_v1 import SelectionCompositionPolicyV2Shadow


def horses():
    return [{"horse_number":i,"horse_name":f"Horse{i}","rank":i,"shadow_ai_rank":i,"adjusted_score":100-i,"final_score":100-i,"decision_score":.8,"total_score":130,"past_performance_score":60,"distance_score":35,"course_shape_score":8,"lap_score":1,"shape_score":1,"pace_style_score":15,"warnings":[],"final_risks":[],"conflict_factors":[],"consistency_score":.8,"consistency_level":"high"} for i in range(1,7)]


def context(): return {"race_id":"race_20990101_tokyo_1R","date":"20990101","venue":"tokyo","race_number":1,"race_structure":{},"structure_flags":{}}


def packet(stage, rows):
    snapshot=stage.race_context_snapshot(rows,context())
    return {"race_id":snapshot["race_id"],"race_context_snapshot_hash":snapshot["snapshot_hash"],"generator_id":"GENERIC","generator_version_hash":"v","generator_recipe_freeze_hash":"r","tie_break_id":EXACT5_TIE_BREAK_ID,"exact5":[{"horse_number":i,"horse_name":f"Horse{i}","candidate_rank":i,"candidate_probability":1-i/10,"shadow_ai_rank":i} for i in range(1,6)]}


def vector(row, state): return [float(i) for i in range(21)]


class Scaler:
    def transform(self, values): return values


class Model:
    def predict_proba(self, values):
        p=np.asarray([.10,.50,.40,.30,.20]); return np.column_stack((1-p,p))


def execute(k=0, stage=None):
    rows=horses(); stage=stage or CandidateGenerationStageBShadow(); policy=SelectionCompositionPolicyV2Shadow(stage)
    return rows, packet(stage,rows), policy.run(packet(stage,rows),rows,context(),model=Model(),scaler=Scaler(),feature_vector=vector,race_state="PLAY_CONVERGED",current_k_metadata=k)


def test_exact5_candidate_and_rank_provenance_preserved():
    rows=horses(); stage=CandidateGenerationStageBShadow(); pkt=packet(stage,rows); before=deepcopy(pkt)
    out=SelectionCompositionPolicyV2Shadow(stage).run(pkt,rows,context(),model=Model(),scaler=Scaler(),feature_vector=vector,race_state="PLAY_CONVERGED",current_k_metadata=0)
    assert out["status"]=="COMMITTED" and pkt==before
    candidate={x["horse_number"]:x for x in out["stage_b_result"]["horses"] if x["candidate_rank"] is not None}
    assert set(candidate)=={1,2,3,4,5} and [candidate[i]["candidate_rank"] for i in range(1,6)]==[1,2,3,4,5]


def test_v4_rank_override_exact_permutation_no_999():
    _,_,out=execute(0)
    assert set(out["v4_rank"].values())=={1,2,3,4,5}
    assert out["decision_rank_override"]==out["v4_rank"] and 999 not in out["decision_rank_override"].values()
    by={x["horse_number"]:x for x in out["stage_b_result"]["horses"]}
    assert all(by[n]["decision_rank"]==out["v4_rank"][n] for n in range(1,6))


def test_k0_reaches_stage_b_and_k_is_decision_independent():
    _,_,zero=execute(0); _,_,five=execute(5)
    assert zero["status"]=="COMMITTED" and zero["policy_metadata"]["operational_k_dependency_count"]==0
    assert zero["v4_rank"]==five["v4_rank"] and zero["decision_rank_override"]==five["decision_rank_override"]
    z=[(x["horse_number"],x["decision"]) for x in zero["stage_b_result"]["horses"]]
    f=[(x["horse_number"],x["decision"]) for x in five["stage_b_result"]["horses"]]
    assert z==f


def test_true_noncandidate_invariant_real_engine():
    _,_,out=execute(0)
    sixth=[x for x in out["stage_b_result"]["horses"] if x["horse_number"]==6][0]
    assert sixth["candidate_rank"] is None and sixth["decision_rank"]==999 and sixth["decision"]!="BUY"


def test_identity_fail_closed_duplicate_ambiguous_unmatched():
    for mutate,reason in (
        (lambda p,r:r.append(deepcopy(r[0])),"STOP_POLICY_V2_IDENTITY_DUPLICATE"),
        (lambda p,r:p["exact5"].__setitem__(4,deepcopy(p["exact5"][0])),"STOP_POLICY_V2_IDENTITY_AMBIGUOUS"),
        (lambda p,r:p["exact5"][4].update({"horse_number":99}),"STOP_POLICY_V2_IDENTITY_UNMATCHED"),
    ):
        rows=horses(); stage=CandidateGenerationStageBShadow(); pkt=packet(stage,rows); mutate(pkt,rows)
        out=SelectionCompositionPolicyV2Shadow(stage).run(pkt,rows,context(),model=Model(),scaler=Scaler(),feature_vector=vector,race_state="PLAY_CONVERGED")
        assert out["status"]=="STOP" and out["failure_state"]==reason and out["valid_policy_v2_buy_artifact"] is False


def test_transaction_failure_has_no_partial_commit():
    rows=horses(); original=deepcopy(rows); stage=CandidateGenerationStageBShadow(); pkt=packet(stage,rows)
    out=SelectionCompositionPolicyV2Shadow(stage).run(pkt,rows,context(),model=Model(),scaler=Scaler(),feature_vector=lambda row,state:[0.0]*20,race_state="PLAY_CONVERGED")
    assert out["status"]=="STOP" and rows==original and out["valid_policy_v2_buy_artifact"] is False


if __name__ == "__main__":
    tests=[value for name,value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests: test()
    print(f"selection_composition_policy_v2_tests_passed={len(tests)}")
