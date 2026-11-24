"""Focused contract tests for Stage-B's generic decision-rank override."""
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review.candidate_generation_stage_b_shadow_v1 import CandidateGenerationStageBShadow, EXACT5_TIE_BREAK_ID


def horses():
    return [{"horse_number":i,"horse_name":f"Horse{i}","rank":i,"shadow_ai_rank":i,"adjusted_score":100-i,"final_score":100-i,"decision_score":.8,"total_score":130,"past_performance_score":60,"distance_score":35,"course_shape_score":8,"lap_score":1,"shape_score":1,"pace_style_score":15,"warnings":[],"final_risks":[],"conflict_factors":[],"consistency_score":.8,"consistency_level":"high"} for i in range(1,7)]


def context():
    return {"race_id":"race_20990101_tokyo_1R","date":"20990101","venue":"tokyo","race_number":1,"race_structure":{},"structure_flags":{}}


def packet(stage, rows):
    snapshot=stage.race_context_snapshot(rows,context())
    return {"race_id":snapshot["race_id"],"race_context_snapshot_hash":snapshot["snapshot_hash"],"generator_id":"GENERIC","generator_version_hash":"v","generator_recipe_freeze_hash":"r","tie_break_id":EXACT5_TIE_BREAK_ID,"exact5":[{"horse_number":i,"horse_name":f"Horse{i}","candidate_rank":i,"candidate_probability":1-i/10} for i in range(1,6)]}


class Decision:
    def decide(self, horse, rank_context):
        return {"decision":"BUY" if rank_context["rank"] <= 5 else "CAUTION","decision_score":.8,"adjusted_score":horse["adjusted_score"],"final_score":horse["final_score"]}


class Race:
    def decide(self, context, horses):
        return {"race_decision":"PASS","race_confidence":.5}


class RC1:
    def evaluate(self, race, horses):
        records=[{"horse_name":h["horse_name"],"rc1_decision":"BUY" if h["rank"] <= 5 else "CAUTION","rc1_buy":h["rank"] <= 5} for h in horses]
        return {"enabled":True,"shadow_result":{"horse_records":[{"horse_number":h["horse_number"],"horse_name":h["horse_name"]} for h in horses]},"horse_records":records,"race_state":"PLAY_CONVERGED"}
    def apply_to_horses(self, horses, result):
        by={r["horse_name"]:r for r in result["horse_records"]}
        for horse in horses: horse["decision"]=by[horse["horse_name"]]["rc1_decision"]


class Sync:
    def synchronize(self, race, horses, rc1):
        return {"race_decision_original":race["race_decision"],"race_decision_final":race["race_decision"]}


def spy_stage(): return CandidateGenerationStageBShadow(Decision(),Race(),RC1(),Sync())


def test_default_caller_non_regression():
    rows=horses(); stage=spy_stage(); out=stage.run(packet(stage,rows),rows,context())
    assert out["status"] == "COMMITTED"
    assert [(h["candidate_rank"],h["decision_rank"]) for h in out["horses"][:5]] == [(1,1),(2,2),(3,3),(4,4),(5,5)]
    assert out["horses"][5]["candidate_rank"] is None and out["horses"][5]["decision_rank"] == 999


def test_valid_override_and_candidate_provenance_preserved():
    rows=horses(); stage=spy_stage(); before=deepcopy(packet(stage,rows)); override={1:4,2:1,3:999,4:2,5:999}
    out=stage.run(before,rows,context(),decision_rank_override=override)
    assert out["status"] == "COMMITTED"
    got={h["horse_number"]:h for h in out["horses"]}
    assert {n:got[n]["decision_rank"] for n in range(1,6)} == override
    assert [got[n]["candidate_rank"] for n in range(1,6)] == [1,2,3,4,5]
    assert [h["horse_number"] for h in out["trace"]["horses"] if h["is_candidate_member"]] == [1,2,3,4,5]
    assert got[6]["decision_rank"] == 999


def assert_stop(override, expected):
    rows=horses(); original=deepcopy(rows); stage=spy_stage(); out=stage.run(packet(stage,rows),rows,context(),decision_rank_override=override)
    assert out["status"] == "STOP" and out["failure_state"] == expected and out["valid_stage_b_buy_artifact"] is False and rows == original


def test_outside_and_incomplete_override_stop():
    assert_stop({1:1,2:2,3:3,4:4,5:5,6:999},"STOP_OVERRIDE_OUTSIDE_CANDIDATE")
    assert_stop({1:1,2:2,3:3,4:4},"STOP_OVERRIDE_INCOMPLETE")


def test_duplicate_active_rank_and_invalid_type_range_stop():
    assert_stop({1:1,2:1,3:999,4:999,5:999},"STOP_OVERRIDE_DUPLICATE_ACTIVE_RANK")
    for value in (True, 1.0, "1", None, 0, 6, 1000):
        assert_stop({1:value,2:2,3:3,4:4,5:5},"STOP_OVERRIDE_INVALID_RANK")
    assert_stop([],"STOP_OVERRIDE_INVALID_TYPE")
    assert_stop({"1":1,2:2,3:3,4:4,5:5},"STOP_OVERRIDE_INVALID_HORSE_NUMBER")


def test_override_transaction_rollback():
    rows=horses(); original=deepcopy(rows); stage=spy_stage()
    out=stage.run(packet(stage,rows),rows,context(),decision_rank_override={1:1,2:2,3:3,4:4,5:6})
    assert out["failure_state"] == "STOP_OVERRIDE_INVALID_RANK" and rows == original and out["valid_stage_b_buy_artifact"] is False


def test_real_engine_sentinel_candidate_buy_block():
    rows=horses(); stage=CandidateGenerationStageBShadow(); out=stage.run(packet(stage,rows),rows,context(),decision_rank_override={1:1,2:2,3:3,4:4,5:999})
    assert out["status"] == "COMMITTED"
    by={h["horse_number"]:h for h in out["horses"]}
    assert by[5]["candidate_rank"] == 5 and by[5]["decision_rank"] == 999 and by[5]["decision"] != "BUY"


if __name__ == "__main__":
    tests=[value for name,value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests: test()
    print(f"stage_b_override_tests_passed={len(tests)}")
