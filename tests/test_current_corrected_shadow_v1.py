from review.current_corrected_shadow_v1 import (
    CorrectionConfig, apply_corrected_shadow, assert_production_reproduction,
    dedupe_authority_risks, reliability_4_of_5,
)


def _row(**overrides):
    row = {
        "horse_number": 1, "rank": 1, "past_race_count": 3,
        "bloodline_score": 1, "past_performance_score": 2, "pace_style_score": 3,
        "distance_score": 4, "track_condition_score": 5, "lap_score": 6,
        "track_bias_score": 0, "impact_score": -999, "shape_score": -999,
        "course_shape_score": -999, "decision_score": 0.01,
        "evaluator_scores": {"bloodline": 1, "past_performance": 1, "pace_style": 1,
                             "distance": 1, "track_condition": -1},
    }
    row.update(overrides)
    return row


def test_off_mode_is_exact_identity_projection():
    source = [_row(), _row(horse_number=2, rank=2)]
    projected = apply_corrected_shadow(source, CorrectionConfig.production_defaults())
    assert projected == source and projected is not source
    assert assert_production_reproduction(source, projected) == 2


def test_semantic_dedupe_and_derived_message_do_not_block():
    risks = dedupe_authority_risks([
        {"semantic_reason_id": "distance", "text": "距離適性の不安"},
        {"semantic_reason_id": "distance", "text": "別経路の距離適性の不安"},
        {"semantic_reason_id": "derived_multiple_major_risks", "text": "重大リスクが複数"},
    ])
    assert [x["semantic_reason_id"] for x in risks] == ["distance"]


def test_impact_shape_pace_consistency_are_trace_only_and_unit_weights():
    first = _row()
    second = _row(impact_score=999, shape_score=999, course_shape_score=999,
                  race_pace_prediction="very_fast", consistency_score=-99,
                  conflict_factors=["x", "y"])
    a = apply_corrected_shadow([first], CorrectionConfig.corrected_shadow())[0]["corrected_shadow"]
    b = apply_corrected_shadow([second], CorrectionConfig.corrected_shadow())[0]["corrected_shadow"]
    assert a["integrated_score"] == b["integrated_score"] == 21
    assert a["adjusted_score"] == b["adjusted_score"] == 21
    assert set(a["score_weights"].values()) == {1.0}
    assert b["trace"]["pace_downstream_value"] == "average"


def test_low_history_uses_race_median_for_ranking_only_or_records_unavailable():
    low = _row(horse_number=1, past_race_count=1, past_performance_score=100)
    reference = _row(horse_number=2, past_race_count=2, past_performance_score=10)
    result = apply_corrected_shadow([low, reference], CorrectionConfig.corrected_shadow())
    shadow = result[0]["corrected_shadow"]
    assert shadow["score_components"]["past_performance"] == 10
    assert shadow["past_performance_vote_score"] == 100
    only = apply_corrected_shadow([low], CorrectionConfig.corrected_shadow())[0]["corrected_shadow"]
    assert only["imputation_unavailable"] is True
    assert only["score_components"]["past_performance"] == 100


def test_reliability_is_frozen_4_of_5_and_rank_is_authority_not_gap():
    r = reliability_4_of_5({"bloodline": 1, "past_performance": 1, "pace_style": 1,
                            "distance": 1, "track_condition": -1})
    assert r["pass"] is True
    one = apply_corrected_shadow([_row(rank=5, relative_score_gap=9999)], CorrectionConfig.corrected_shadow())[0]
    two = apply_corrected_shadow([_row(rank=5, relative_score_gap=-9999)], CorrectionConfig.corrected_shadow())[0]
    assert one["corrected_shadow"]["candidate"] == two["corrected_shadow"]["candidate"]


def test_one_underlying_cause_cannot_create_multiple_gate_blocks():
    row = _row(weaknesses=[{"semantic_reason_id": "distance", "text": "距離適性の不安"}],
               risk_factors=[{"semantic_reason_id": "distance", "text": "距離適性の不安"}],
               decision_risks=[{"semantic_reason_id": "derived_multiple_major_risks", "text": "重大リスクが複数"}])
    shadow = apply_corrected_shadow([row], CorrectionConfig.corrected_shadow())[0]["corrected_shadow"]
    assert len(shadow["authority_risks"]) == 1
    assert shadow["risk_guard_pass"] is True
