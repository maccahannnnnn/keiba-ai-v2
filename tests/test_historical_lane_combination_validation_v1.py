import json
from pathlib import Path

import pytest

from review.historical_lane_coverage_registry_v1 import CoverageStop, LANES, sha
from review.historical_lane_combination_validation_v1 import (
    PAIRS, SPEC, block_for_date, evaluate_phase2, prepare_phase1, verify_phase1,
)


def _approval(phase):
    return {"human_approved": True, "phase": phase,
            "approval_id": "SYNTHETIC_TEST_ONLY", "approved_at": "TEST"}


def _fixture(tmp_path):
    date = "20260301"
    rid = "race_20260301_tokyo_1R"
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    spec["diagnostic_pre_root"] = "diag"
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    current = tmp_path / "current_pre.json"
    current.write_text(json.dumps({"predictions": [{"race_id": rid}], "selected": [[rid, 1]]}))
    plj = tmp_path / "selection.json"
    plj.write_text(json.dumps({"races": [{"race_id": rid, "candidate_selected_horses": [1],
                                          "horses": [{"horse_number": 1, "candidate_rank": 1,
                                                      "candidate_p_top3": 0.6}]}]}))
    folder = tmp_path / "diag"
    folder.mkdir()
    a = folder / spec["diagnostic_a"]
    b = folder / spec["diagnostic_b"]
    selection = {"date": date, "race_id": rid, "horse_number": 1, "p": 0.6}
    a.write_text(json.dumps({"dates": [date], "result_access_during_selection": 0,
                             "same_race_pl": [selection], "cap3_global_pl": [selection]}))
    b.write_text(json.dumps({"usable_dates": [], "result_access_during_selection": 0,
                             "exp024_shaped_pl": [], "e1_cap3": []}))
    (folder / spec["diagnostic_pre_freeze"]).write_text(json.dumps({
        "a_pre_selection_sha256": sha(a), "b_pre_selection_sha256": sha(b),
        "result_access_before_freeze": 0, "new_inference": False}))
    rows = []
    for lane in LANES:
        source = current if lane == "CURRENT" else plj if lane == "PL_JOCKEY" else None
        rows.append({"date": date, "race_id": rid, "lane": lane,
                     "technical_predictable": source is not None,
                     "technical_reason": None if source else "PREDICTION_NOT_SAVED",
                     "prediction_path": str(source) if source else None,
                     "prediction_sha256": sha(source) if source else None,
                     "source_role": "SAVED_PRE_ONLY" if source else "PREDICTION_NOT_SAVED",
                     "model_version": None, "model_sha256": None})
    registry = tmp_path / "phase0.json"
    registry.write_text(json.dumps({"approval": _approval(0), "registry": {
        "schema_version": "HISTORICAL_LANE_COVERAGE_REGISTRY_V1",
        "new_panel_evidence_credit": 0, "rows": rows}}))
    return registry, spec_path, rid


def test_blocks_28_pairs_and_discovery_dates_excluded(tmp_path):
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert len(PAIRS) == 28
    assert block_for_date("20260301", spec) == "H1"
    assert block_for_date("20260919", spec) == "H2"
    assert block_for_date("20261107", spec) == "P"
    assert block_for_date("20261114", spec) is None


def test_phase1_saved_sources_only_and_pending_lanes(tmp_path):
    registry, spec, rid = _fixture(tmp_path)
    out = tmp_path / "phase1.json"
    result = prepare_phase1(registry, _approval(1), out, root=tmp_path, spec_path=spec)
    assert result["result_access_count"] == 0
    assert result["pair_count"] == 28
    assert {row["lane"] for row in result["selected_horses"]} == {"CURRENT", "PL_JOCKEY", "EXP024", "E1"}
    assert result["source_status_by_date"]["20260301"]["B1"] == "PENDING_OR_UNAVAILABLE"
    assert all(row["race_id"] == rid for row in result["selected_horses"])
    with pytest.raises(CoverageStop, match="OUTPUT_EXISTS"):
        prepare_phase1(registry, _approval(1), out, root=tmp_path, spec_path=spec)


def test_phase2_requires_separate_approval_and_emits_28_by_4(tmp_path):
    registry, spec, rid = _fixture(tmp_path)
    phase1 = tmp_path / "phase1.json"
    prepare_phase1(registry, _approval(1), phase1, root=tmp_path, spec_path=spec)
    calls = []
    with pytest.raises(CoverageStop, match="HUMAN_PHASE_APPROVAL"):
        evaluate_phase2(phase1, {}, tmp_path / "phase2.json",
                        label_provider=lambda *args: calls.append(args))
    assert calls == []
    approval = {**_approval(2), "phase1_sha256": sha(phase1), "authorized_dates": ["20260301"]}
    result = evaluate_phase2(phase1, approval, tmp_path / "phase2.json",
                             label_provider=lambda date, keys: {(rid, 1): (True, 2, True)})
    assert len(result["daily_28_pair_modes"]) == 112
    assert result["evidence_credit"] == 0
    and_row = next(row for row in result["daily_28_pair_modes"]
                   if row["lane_a"] == "EXP024" and row["lane_b"] == "E1" and row["mode"] == "AND")
    assert and_row["hits"] == 1
    assert and_row["same_volume_parent"]["E1"]["status"] == "COMPARABLE_PARENT_SELECTED_POOL"


def test_phase1_tamper_stops_before_result_loader(tmp_path):
    registry, spec, _ = _fixture(tmp_path)
    phase1 = tmp_path / "phase1.json"
    prepare_phase1(registry, _approval(1), phase1, root=tmp_path, spec_path=spec)
    approved = sha(phase1)
    phase1.write_text(phase1.read_text() + " ")
    with pytest.raises(CoverageStop, match="PHASE1_SHA_MISMATCH"):
        verify_phase1(phase1, approved)


def test_saved_source_drift_stops_verification(tmp_path):
    registry, spec, _ = _fixture(tmp_path)
    phase1 = tmp_path / "phase1.json"
    prepare_phase1(registry, _approval(1), phase1, root=tmp_path, spec_path=spec)
    (tmp_path / "current_pre.json").write_text((tmp_path / "current_pre.json").read_text() + " ")
    with pytest.raises(CoverageStop, match="SOURCE_SHA_DRIFT"):
        verify_phase1(phase1, sha(phase1))


def test_diagnostic_pre_result_label_is_not_accepted(tmp_path):
    registry, spec_path, _ = _fixture(tmp_path)
    spec = json.loads(spec_path.read_text())
    folder = tmp_path / "diag"
    source = folder / spec["diagnostic_a"]
    value = json.loads(source.read_text())
    value["cap3_global_pl"][0]["actual_top3"] = True
    source.write_text(json.dumps(value))
    freeze_path = folder / spec["diagnostic_pre_freeze"]
    freeze = json.loads(freeze_path.read_text())
    freeze["a_pre_selection_sha256"] = sha(source)
    freeze_path.write_text(json.dumps(freeze))
    with pytest.raises(CoverageStop, match="RESULT_FIELD_IN_PREDICTION"):
        prepare_phase1(registry, _approval(1), tmp_path / "phase1.json", root=tmp_path, spec_path=spec_path)
