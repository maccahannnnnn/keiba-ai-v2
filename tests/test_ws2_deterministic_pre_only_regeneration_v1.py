from __future__ import annotations

from pathlib import Path

import pytest

from review.ws2_deterministic_pre_only_regeneration_v1 import (
    PreOnlyBoundary,
    RuntimeTrace,
    StopPreOnlyBoundary,
    compare_rows,
    feature_values_from_runtime,
)


def test_result_open_is_fail_closed(tmp_path: Path) -> None:
    trace = RuntimeTrace()
    with PreOnlyBoundary(allowed_reads=set(), output_root=tmp_path, trace=trace):
        with pytest.raises(StopPreOnlyBoundary, match="STOP_PRE_ONLY_BOUNDARY_VIOLATION"):
            Path("data/results/example.csv").read_text(encoding="utf-8")
    assert trace.violations[0]["operation"].startswith("file_open")


def test_learning_open_is_fail_closed(tmp_path: Path) -> None:
    trace = RuntimeTrace()
    with PreOnlyBoundary(allowed_reads=set(), output_root=tmp_path, trace=trace):
        with pytest.raises(StopPreOnlyBoundary):
            Path("learning/state.json").read_text(encoding="utf-8")
    assert trace.violations[0]["resource"].replace("\\", "/").endswith("learning/state.json")


def test_runtime_payload_derives_gap_from_pre_top5() -> None:
    payload = {
        "race_id": "race_20260101_tokyo_1R",
        "ranked_results": [
            {"horse_number": 1, "horse_name": "A", "rank": 1, "adjusted_score": 10.0, "decision_score": 1, "final_score": 2, "risk_count": 0, "conflict_count": 0, "buy_v1_rc1_race_state": "PLAY"},
            {"horse_number": 2, "horse_name": "B", "rank": 2, "adjusted_score": 8.5, "decision_score": 1, "final_score": 2, "risk_count": 0, "conflict_count": 0, "buy_v1_rc1_race_state": "PLAY"},
        ],
        "buy_gate_trace": {"horses": [
            {"horse_number": 1, "shadow_ai_rank": 1, "evaluator_score_snapshot": {}},
            {"horse_number": 2, "shadow_ai_rank": 2, "evaluator_score_snapshot": {}},
        ]},
    }
    rows, _ = feature_values_from_runtime(payload, "20260101")
    assert rows[("race_20260101_tokyo_1R", "1")]["values"]["adjusted_score_gap_to_top"] == 0.0
    assert rows[("race_20260101_tokyo_1R", "2")]["values"]["adjusted_score_gap_to_top"] == -1.5


def test_single_feature_difference_fails_comparison() -> None:
    reference = {"20260101:race_20260101_tokyo_1R:1": {"row_id": "20260101:race_20260101_tokyo_1R:1", "date": "20260101", "race_id": "race_20260101_tokyo_1R", "horse_number": "1", "features": {"final_score": "2.0"}}}
    generated = {("race_20260101_tokyo_1R", "1"): {"date": "20260101", "race_id": "race_20260101_tokyo_1R", "horse_number": "1", "top5": True, "values": {"final_score": 3.0}}}
    report = compare_rows(reference, ["final_score"], generated)
    assert report["status"] == "FAIL"
    assert report["mismatches"][0]["type"] == "FEATURE_VALUE"
