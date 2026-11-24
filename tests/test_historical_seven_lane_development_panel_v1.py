import json

import pytest

from review.historical_lane_coverage_registry_v1 import (
    CoverageStop, LANES, build_registry, load_source_map, sha, write_phase0,
)
from review.historical_seven_lane_development_panel_v1 import _selection_keys, prepare_phase1, evaluate_phase2


def _approval(phase):
    return {"human_approved": True, "phase": phase, "approval_id": "SYNTHETIC_TEST", "approved_at": "TEST",
            "authorized_dates": ["20260207"] if phase == 2 else []}


def _prepared(tmp_path, date="20260207"):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for kind in ("DG", "DE", "DS"):
        (inputs / f"{kind}{date[2:]}.CSV").write_bytes(kind.encode())
    config = load_source_map()
    config["formal_summary_pattern"] = "missing/{date}.json"
    for lane in LANES:
        config["lanes"][lane]["patterns"] = [f"saved/{{date}}/{lane}/selection.json"]
    rid = f"race_{date}_tokyo_1R"
    path = tmp_path / f"saved/{date}/PL_JOCKEY/selection.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"races": [{"race_id": rid, "candidate_selected_horses": [1]}]}))
    registry = build_registry(inputs, tmp_path, config,
                              parse_day=lambda day, files: ([{"race_id": rid, "horse_count": 2}], None))
    phase0 = tmp_path / "phase0.json"
    write_phase0(registry, phase0, _approval(0))
    return phase0, path, rid


def test_phase1_locks_saved_identity_without_result(tmp_path):
    phase0, source, rid = _prepared(tmp_path)
    out = tmp_path / "phase1.json"
    result = prepare_phase1(phase0, _approval(1), out)
    assert result["result_access_count"] == 0
    assert result["new_panel_evidence_credit"] == 0
    assert [(x["race_id"], x["horse_number"], x["lane"]) for x in result["selected_horses"]] == [(rid, 1, "PL_JOCKEY")]
    assert source.exists()
    with pytest.raises(CoverageStop, match="OUTPUT_EXISTS"):
        prepare_phase1(phase0, _approval(1), out)


def test_phase1_rejects_saved_prediction_sha_drift(tmp_path):
    phase0, source, _ = _prepared(tmp_path)
    source.write_text(source.read_text() + " ")
    with pytest.raises(CoverageStop, match="SOURCE_DRIFT"):
        prepare_phase1(phase0, _approval(1), tmp_path / "phase1.json")


def test_phase2_denies_consumed_holdout_before_result_loader(tmp_path):
    phase0, _, _ = _prepared(tmp_path, "20251207")
    phase1 = tmp_path / "phase1.json"
    prepare_phase1(phase0, _approval(1), phase1)
    called = []
    approval = _approval(2)
    approval["authorized_dates"] = ["20251207"]
    approval["phase1_sha256"] = sha(phase1)
    with pytest.raises(CoverageStop, match="RESULT_PERIOD_NOT_AUTHORIZED"):
        evaluate_phase2(phase1, approval, tmp_path / "phase2.json",
                        label_provider=lambda *args: called.append(args))
    assert called == []


def test_phase2_holds_september_to_october_role_review(tmp_path):
    phase0, _, _ = _prepared(tmp_path, "20260919")
    phase1 = tmp_path / "phase1.json"
    prepare_phase1(phase0, _approval(1), phase1)
    called = []
    approval = _approval(2)
    approval["authorized_dates"] = ["20260919"]
    approval["phase1_sha256"] = sha(phase1)
    with pytest.raises(CoverageStop, match="RESULT_PERIOD_NOT_AUTHORIZED"):
        evaluate_phase2(phase1, approval, tmp_path / "phase2.json",
                        label_provider=lambda *args: called.append(args))
    assert called == []


def test_phase2_synthetic_labels_only_with_separate_approval(tmp_path):
    phase0, _, rid = _prepared(tmp_path)
    phase1 = tmp_path / "phase1.json"
    prepare_phase1(phase0, _approval(1), phase1)
    with pytest.raises(CoverageStop, match="HUMAN_PHASE_APPROVAL"):
        evaluate_phase2(phase1, {}, tmp_path / "phase2.json",
                        label_provider=lambda *_: {})
    approval = _approval(2)
    approval["phase1_sha256"] = sha(phase1)
    result = evaluate_phase2(phase1, approval, tmp_path / "phase2.json",
                             label_provider=lambda date, keys: {(rid, 1): (True, 2, True)})
    assert result["lane_totals"]["PL_JOCKEY"] == {"selected": 1, "valid": 1, "invalid": 0, "hits": 1, "rate": 1.0}
    assert result["new_panel_evidence_credit"] == 0
    assert sha(phase0) == json.loads(phase1.read_text())["phase0_sha256"]


def test_all_eight_selection_shapes_are_distinct_and_result_columns_ignored(tmp_path):
    rid = "race_20260207_tokyo_1R"
    shapes = {
        "EXP024": {"races": [{"race_id": rid, "treatment_selected_horses": [1]}]},
        "CURRENT_RANK1": {"selections": [{"race_id": rid, "selected_horse_number": 1}]},
        "PL_JOCKEY": {"races": [{"race_id": rid, "candidate_selected_horses": [1]}]},
        "A_NEW": {"races": [{"race_id": rid, "a_new_selected_horses": [1]}]},
        "E1": {"selected_horses": [{"race_id": rid, "horse_number": 1}]},
        "INDEPENDENT_V5": {"races": [{"race_id": rid, "selected_horses": [{"horse_number": 1}]}]},
        "B1": {"selected_horses": [{"race_id": rid, "horse_number": 1}]},
    }
    for lane, value in shapes.items():
        value["result_label_must_not_be_read"] = "SENTINEL"
        assert _selection_keys(lane, tmp_path / "selection.json", value) == {(rid, 1)}
    current = tmp_path / "prediction_manifest.json"
    (tmp_path / "race_index.json").write_text(json.dumps({"race_index": [
        {"race_id": rid, "artifact": "race.json"}]}))
    (tmp_path / "race.json").write_text(json.dumps({"buys": [{"horse_number": 1}],
                                                  "result_label_must_not_be_read": "SENTINEL"}))
    assert _selection_keys("CURRENT", current, {}) == {(rid, 1)}


def test_partial_rank1_lane_does_not_stop_other_comparisons(tmp_path):
    phase0, _, rid = _prepared(tmp_path)
    payload = json.loads(phase0.read_text())
    other = "race_20260207_tokyo_2R"
    extra = []
    for row in payload["registry"]["rows"]:
        clone = dict(row)
        clone["race_id"] = other
        clone["race_number"] = 2
        clone["technical_predictable"] = False
        clone["technical_reason"] = "NOT_APPLICABLE_BY_LANE_DESIGN"
        extra.append(clone)
    payload["registry"]["rows"].extend(extra)
    phase0.write_text(json.dumps(payload))
    result = prepare_phase1(phase0, _approval(1), tmp_path / "phase1.json")
    assert [(row["race_id"], row["lane"]) for row in result["selected_horses"]] == [(rid, "PL_JOCKEY")]


def test_phase2_rejects_modified_phase1_even_with_old_approval(tmp_path):
    phase0, _, _ = _prepared(tmp_path)
    phase1 = tmp_path / "phase1.json"
    prepare_phase1(phase0, _approval(1), phase1)
    approval = _approval(2)
    approval["phase1_sha256"] = sha(phase1)
    phase1.write_text(phase1.read_text() + " ")
    called = []
    with pytest.raises(CoverageStop, match="PHASE1_APPROVED_SHA_MISMATCH"):
        evaluate_phase2(phase1, approval, tmp_path / "phase2.json",
                        label_provider=lambda *args: called.append(args))
    assert called == []


def test_run_c_and_fold_sources_filter_by_target_date(tmp_path):
    rid = "race_20260404_tokyo_1R"
    other = "race_20260405_tokyo_1R"
    pre = tmp_path / "runtime_pre_only_output.json"
    run_c = {"generated_rows": [
        {"date": "20260404", "race_id": rid, "horse_number": 1,
         "values": {"post_rc1_decision": "BUY"}},
        {"date": "20260405", "race_id": other, "horse_number": 2,
         "values": {"post_rc1_decision": "BUY"}}]}
    assert _selection_keys("CURRENT", pre, run_c, "20260404") == {(rid, 1)}
    fold = tmp_path / "pre_freeze.json"
    value = {"selections": {"A0": [{"date": "20260404", "race_id": rid, "horse_number": 3},
                                  {"date": "20260405", "race_id": other, "horse_number": 4}],
                            "A_new": [{"date": "20260404", "race_id": rid, "horse_number": 5}]}}
    assert _selection_keys("PL_JOCKEY", fold, value, "20260404") == {(rid, 3)}
    assert _selection_keys("A_NEW", fold, value, "20260404") == {(rid, 5)}


def test_e1_b1_same_daily_n_does_not_filter_to_same_race(tmp_path):
    phase0, _, first = _prepared(tmp_path)
    second = "race_20260207_tokyo_2R"
    raw = json.loads(phase0.read_text())
    clones = []
    for row in raw["registry"]["rows"]:
        clone = dict(row)
        clone["race_id"] = second
        clone["race_number"] = 2
        clones.append(clone)
    raw["registry"]["rows"].extend(clones)
    phase0.write_text(json.dumps(raw))
    phase1 = tmp_path / "phase1.json"
    phase1.write_text(json.dumps({"phase0_path": str(phase0), "phase0_sha256": sha(phase0),
                                  "new_panel_evidence_credit": 0, "result_access_count": 0,
                                  "ranking_rows": [{"date": "20260207", "race_id": first, "horse_number": 1,
                                                    "lane": "CURRENT", "rank": 1, "buy_gate": "BUY"}],
                                  "selected_horses": [
                                      {"date": "20260207", "race_id": first, "horse_number": 1, "lane": "E1"},
                                      {"date": "20260207", "race_id": second, "horse_number": 2, "lane": "B1"}]}))
    approval = _approval(2)
    approval["phase1_sha256"] = sha(phase1)
    def labels(date, keys):
        return {(first, 1): (True, 1, True), (second, 2): (True, 4, False)}
    result = evaluate_phase2(phase1, approval, tmp_path / "phase2.json", label_provider=labels)
    assert result["same_daily_n"]["20260207"]["comparable"] is True
    assert "E1__B1" not in result["pairwise_same_k"]
    assert result["combinations"]["20260207__E1__B1__OR"]["selected"] == 2
    assert result["ranking_totals"]["CURRENT__RANK1"]["hits"] == 1
    assert result["current_buy_gate_totals"]["BUY"]["hits"] == 1
