from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.candidate_generation_stage_b_shadow_v1 import (
    CandidateGenerationStageBShadow, EXACT5_TIE_BREAK_ID,
    NON_CANDIDATE_DECISION_RANK_SENTINEL,
)


class DecisionSpy:
    def __init__(self): self.calls=[]
    def decide(self, horse, rank_context):
        self.calls.append((horse["horse_number"], dict(rank_context)))
        return {"decision":"BUY" if rank_context["rank"] <= 5 else "CAUTION", "decision_score":0.8, "final_score":horse["final_score"], "adjusted_score":horse["adjusted_score"]}
    def decide_many(self, *_): raise AssertionError("decide_many must not be used")


class RaceSpy:
    def __init__(self): self.counts=[]
    def decide(self, context, horses): self.counts.append(len(horses)); return {"race_decision":"PASS", "race_confidence":0.5}


class RC1Spy:
    def __init__(self, corrupt=None): self.corrupt=corrupt
    def evaluate(self, race, horses):
        shadow=[]; records=[]
        for h in horses:
            name = self.corrupt(h) if self.corrupt else h["horse_name"]
            shadow.append({"horse_number":h["horse_number"],"horse_name":name})
            records.append({"horse_name":name,"rc1_decision":"BUY" if h["rank"] <= 5 else "CAUTION","rc1_buy":h["rank"] <= 5})
        return {"enabled":True,"shadow_result":{"horse_records":shadow},"horse_records":records,"race_state":"PLAY_CONVERGED"}
    def apply_to_horses(self, horses, result):
        by={r["horse_name"]:r for r in result["horse_records"]}
        for h in horses:
            if h["horse_name"] in by: h["decision"]=by[h["horse_name"]]["rc1_decision"]
        return horses


class SyncSpy:
    def synchronize(self, race, horses, rc1):
        buys=[h["horse_name"] for h in horses if h["decision"]=="BUY"]
        return {"race_decision_original":race["race_decision"],"race_decision_final":"PLAY" if buys else race["race_decision"],"final_buy_horses":buys}


def horses():
    return [{"horse_number":i,"horse_name":f"Horse{i}","rank":i,"shadow_ai_rank":i,"adjusted_score":100-i,"final_score":100-i,"decision_score":0.7,"warnings":[],"final_risks":[],"conflict_factors":[]} for i in range(1,7)]


def context(): return {"race_id":"race_20990101_tokyo_1R","date":"20990101","venue":"tokyo","race_number":1,"race_structure":{},"structure_flags":{}}


def packet(orchestrator, rows, exact=(1,2,3,4,5), generator="GEN_A"):
    snap=orchestrator.race_context_snapshot(rows,context())
    return {"race_id":snap["race_id"],"race_context_snapshot_hash":snap["snapshot_hash"],"generator_id":generator,"generator_version_hash":"v","generator_recipe_freeze_hash":"r","tie_break_id":EXACT5_TIE_BREAK_ID,"exact5":[{"horse_number":n,"horse_name":f"Horse{n}","candidate_rank":i,"candidate_probability":1-i/10,"shadow_ai_rank":n} for i,n in enumerate(exact,1)]}


def test_stage_b_explicit_rank_full_field_identity_and_transaction():
    dec, race = DecisionSpy(), RaceSpy(); stage=CandidateGenerationStageBShadow(dec,race,RC1Spy(),SyncSpy()); source=horses(); result=stage.run(packet(stage,source),source,context())
    assert result["status"]=="COMMITTED" and source==horses() and race.counts==[6]
    assert [c[1]["rank"] for c in dec.calls]==[1,2,3,4,5,NON_CANDIDATE_DECISION_RANK_SENTINEL]
    assert all(h["decision"]!="BUY" for h in result["horses"] if h["horse_number"]==6)
    assert {h["decision_rank"] for h in result["trace"]["horses"]}=={1,2,3,4,5,NON_CANDIDATE_DECISION_RANK_SENTINEL}


def test_generator_independence_snapshot_and_determinism():
    stage=CandidateGenerationStageBShadow(DecisionSpy(),RaceSpy(),RC1Spy(),SyncSpy()); rows=horses(); a=packet(stage,rows,(1,2,3,4,5),"GEN_A"); b=packet(stage,rows,(2,3,4,5,6),"GEN_B")
    assert a["race_context_snapshot_hash"]==b["race_context_snapshot_hash"]
    assert stage.run(a,rows,context())["trace"]==stage.run(a,rows,context())["trace"]
    assert stage.run(b,rows,context())["status"]=="COMMITTED"


def test_identity_failures_are_fail_closed_and_do_not_mutate_input():
    rows=horses(); stage=CandidateGenerationStageBShadow(DecisionSpy(),RaceSpy(),RC1Spy(lambda h: "truncated" if h["horse_number"]==1 else h["horse_name"]),SyncSpy()); source=deepcopy(rows); result=stage.run(packet(stage,rows),rows,context())
    assert result["status"]=="STOP" and result["failure_state"]=="STOP_NUMBER_NAME_MISMATCH" and result["valid_stage_b_buy_artifact"] is False and rows==source
    duplicate=horses(); duplicate[1]["horse_name"]="Horse1"; assert CandidateGenerationStageBShadow().run({},duplicate,context())["failure_state"]=="STOP_DUPLICATE_NAME"


if __name__ == "__main__":
    tests = [
        test_stage_b_explicit_rank_full_field_identity_and_transaction,
        test_generator_independence_snapshot_and_determinism,
        test_identity_failures_are_fail_closed_and_do_not_mutate_input,
    ]
    for test in tests:
        test()
    print(f"synthetic_stage_b_tests_passed={len(tests)}")
