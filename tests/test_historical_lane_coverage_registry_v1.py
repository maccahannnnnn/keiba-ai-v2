import json
from pathlib import Path

import pytest

from review.historical_lane_coverage_registry_v1 import (
    CoverageStop, LANES, assert_prediction_result_free, build_registry, discover_dates, load_source_map, read_prediction,
    safe_prediction_path, write_phase0,
)


def _config():
    config = load_source_map()
    config["formal_summary_pattern"] = "missing/{date}.json"
    config["historical_sources"] = {}
    config["approved_input_version"] = {}
    for lane in LANES:
        config["lanes"][lane]["patterns"] = [f"saved/{{date}}/{lane}/selection.json"]
    return config


def _inputs(folder, date):
    folder.mkdir(parents=True, exist_ok=True)
    for kind in ("DG", "DE", "DS"):
        (folder / f"{kind}{date[2:]}.CSV").write_bytes(kind.encode())


def _parse(date, files):
    return [{"race_id": f"race_{date}_tokyo_1R", "horse_count": 2}], None


def test_date_discovery_is_dynamic_and_full_race_lane_matrix(tmp_path):
    inputs = tmp_path / "inputs"
    _inputs(inputs, "20260201")
    first = build_registry(inputs, tmp_path, _config(), parse_day=_parse)
    assert first["counts"]["dates"] == 1
    assert first["counts"]["race_lane_rows"] == len(LANES)
    assert all(not row["technical_predictable"] for row in first["rows"])
    _inputs(inputs, "20260207")
    second = build_registry(inputs, tmp_path, _config(), parse_day=_parse)
    assert second["counts"]["dates"] == 2
    assert second["counts"]["race_lane_rows"] == 2 * len(LANES)
    assert second["new_panel_evidence_credit"] == 0


def test_partial_triplet_keeps_discovered_date(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "DG260201.CSV").write_bytes(b"DG")
    assert list(discover_dates(inputs)) == ["20260201"]
    def partial(date, files):
        return [{"race_id": f"race_{date}_tokyo_1R", "horse_count": None}], "INPUT_TRIPLET_MISSING"
    result = build_registry(inputs, tmp_path, _config(), parse_day=partial)
    assert len(result["rows"]) == len(LANES)
    assert all(row["technical_reason"] == "INPUT_INVALID_OR_INCOMPLETE" for row in result["rows"])


def test_duplicate_race_stops(tmp_path):
    inputs = tmp_path / "inputs"
    _inputs(inputs, "20260201")
    def duplicate(date, files):
        race = {"race_id": f"race_{date}_tokyo_1R", "horse_count": 2}
        return [race, race], None
    with pytest.raises(CoverageStop, match="DUPLICATE_OR_INVALID_RACE"):
        build_registry(inputs, tmp_path, _config(), parse_day=duplicate)


def test_training_overlap_and_b1_effective_date_are_non_evidential(tmp_path):
    inputs = tmp_path / "inputs"
    _inputs(inputs, "20260201")
    config = _config()
    path = tmp_path / "saved/20260201/PL_JOCKEY/selection.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"model_sha256": "a" * 64, "training_start": "20260203", "training_cutoff": "2026-02-07",
                                "races": [{"race_id": "race_20260201_tokyo_1R", "candidate_selected_horses": [1]}]}))
    result = build_registry(inputs, tmp_path, config, parse_day=_parse)
    plj = next(row for row in result["rows"] if row["lane"] == "PL_JOCKEY")
    b1 = next(row for row in result["rows"] if row["lane"] == "B1")
    assert plj["training_overlap"] == "TIME_REVERSED"
    assert plj["evidence_role"] == "TIME_REVERSED_NON_EVIDENTIAL"
    assert b1["technical_reason"] == "BEFORE_B1_EFFECTIVE_FROM"


def test_phase0_requires_separate_approval_and_writes_exclusively(tmp_path):
    path = tmp_path / "phase0.json"
    with pytest.raises(CoverageStop, match="HUMAN_PHASE_APPROVAL"):
        write_phase0({}, path, {})
    approval = {"human_approved": True, "phase": 0, "approval_id": "SYNTHETIC_TEST", "approved_at": "TEST"}
    write_phase0({"new_panel_evidence_credit": 0}, path, approval)
    with pytest.raises(CoverageStop, match="OUTPUT_EXISTS"):
        write_phase0({}, path, approval)


def test_rank1_eligible_count_and_result_path_guard(tmp_path):
    inputs = tmp_path / "inputs"
    _inputs(inputs, "20260207")
    config = _config()
    path = tmp_path / "saved/20260207/CURRENT_RANK1/selection.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"eligible_races": 1, "selections": [
        {"race_id": "race_20260207_tokyo_1R", "selected_horse_number": 1}]}))
    registry = build_registry(inputs, tmp_path, config, parse_day=_parse)
    rank1 = next(row for row in registry["rows"] if row["lane"] == "CURRENT_RANK1")
    assert rank1["technical_predictable"] is True
    with pytest.raises(CoverageStop, match="NON_PREDICTION_SOURCE_PATH"):
        safe_prediction_path(tmp_path / "daily_result_list/selection.json")


def test_approved_v2_discovery_and_unknown_version_stop(tmp_path):
    folder = tmp_path / "inputs"
    _inputs(folder, "20260418")
    for kind in ("DG", "DE", "DS"):
        (folder / f"{kind}260418v2.CSV").write_bytes(b"v2")
    assert all(path.name.endswith("v2.CSV") for path in discover_dates(folder)["20260418"].values())
    (folder / "DG260419v3.CSV").write_bytes(b"unknown")
    with pytest.raises(CoverageStop, match="UNKNOWN_INPUT_VERSION"):
        discover_dates(folder)
    (folder / "DG260419v3.CSV").unlink()
    (folder / "DG260419_custom.CSV").write_bytes(b"unknown")
    with pytest.raises(CoverageStop, match="UNKNOWN_INPUT_FILENAME"):
        discover_dates(folder)


def test_result_label_is_rejected_but_legitimate_pre_metadata_passes(tmp_path):
    assert_prediction_result_free({"result_access_count": 0, "training_result_dates": ["20260201"],
                                   "predicted_actual_top3_probability": 0.25})
    with pytest.raises(CoverageStop, match="RESULT_FIELD_IN_PREDICTION"):
        assert_prediction_result_free({"races": [{"actual_top3": True}]})


def test_approved_single_race_exception_preserves_other_race(tmp_path):
    inputs = tmp_path / "inputs"
    _inputs(inputs, "20260823")
    config = _config()
    authority = tmp_path / "exception.json"
    authority.write_text(json.dumps({"target_race": {"race_id": "race_20260823_niigata_7R"}}))
    from review.historical_lane_coverage_registry_v1 import sha
    config["approved_race_exceptions"] = {"20260823": {
        "race_id": "race_20260823_niigata_7R", "reason_code": "DE_DS_HORSE_SET_MISMATCH",
        "authority_path": "exception.json", "authority_sha256": sha(authority)}}
    def two_races(date, files):
        return ([{"race_id": "race_20260823_niigata_7R", "horse_count": 12},
                 {"race_id": "race_20260823_niigata_8R", "horse_count": 13}],
                "PredictionInputValidationError:DE_DS_HORSE_SET_MISMATCH")
    registry = build_registry(inputs, tmp_path, config, parse_day=two_races)
    assert registry["counts"]["races"] == 2
    assert all(row["input_validation"] == "PASS_WITH_APPROVED_RACE_EXCEPTION"
               for row in registry["rows"] if row["race_id"].endswith("8R"))
    assert all(row["technical_reason"] == "INPUT_INVALID_OR_INCOMPLETE"
               for row in registry["rows"] if row["race_id"].endswith("7R"))


def test_monthly_fold_sha_and_iso_training_range(tmp_path):
    inputs = tmp_path / "inputs"
    _inputs(inputs, "20260404")
    config = _config()
    config["lanes"]["PL_JOCKEY"]["patterns"] = []
    config["lanes"]["A_NEW"]["patterns"] = []
    config["historical_sources"] = {"walk_forward_fold": str(tmp_path / "fold_{month}/pre_freeze.json")}
    path = tmp_path / "fold_202604/pre_freeze.json"
    path.parent.mkdir()
    rid = "race_20260404_tokyo_1R"
    path.write_text(json.dumps({"training_range": ["2026-02-01", "2026-03-29"],
                                "predictions": {"A0": [{"race_id": rid}], "A_new": [{"race_id": rid}]},
                                "selections": {"A0": [{"date": "20260404", "race_id": rid, "horse_number": 1}],
                                               "A_new": [{"date": "20260404", "race_id": rid, "horse_number": 2}]}}))
    from review.historical_lane_coverage_registry_v1 import sha
    (path.parent / "freeze_manifest.json").write_text(json.dumps({
        "month": "202604", "status": "PRE_FROZEN_BEFORE_SAME_MONTH_RESULT_ACCESS",
        "same_month_result_access_before_freeze": 0, "pre_freeze_sha256": sha(path)}))
    registry = build_registry(inputs, tmp_path, config, parse_day=_parse)
    for lane in ("PL_JOCKEY", "A_NEW"):
        row = next(row for row in registry["rows"] if row["lane"] == lane)
        assert row["technical_predictable"] is True
        assert row["training_cutoff"] == "20260329"
        assert row["training_overlap"] == "WALK_FORWARD_FOLD_OOS"


def test_saved_independent_v5_matrix_and_result_column_rejection(tmp_path):
    path = tmp_path / "prediction_matrix.csv"
    path.write_text("date,race_id,INDEPENDENT_V5\n20260926,race_20260926_tokyo_1R,\"#2 Horse A, #5 Horse B\"\n")
    value = read_prediction(path)
    assert [row["horse_number"] for row in value["races"][0]["selected_horses"]] == [2, 5]
    path.write_text("date,race_id,INDEPENDENT_V5,actual_top3\n20260926,race_20260926_tokyo_1R,#2 Horse A,1\n")
    with pytest.raises(CoverageStop, match="PREDICTION_MATRIX_COLUMNS"):
        read_prediction(path)


def test_run_c_saved_pre_only_source_connects_current(tmp_path):
    inputs = tmp_path / "inputs"
    _inputs(inputs, "20260201")
    config = _config()
    config["lanes"]["CURRENT"]["patterns"] = []
    config["lanes"]["CURRENT_RANK1"]["patterns"] = []
    config["historical_sources"] = {"run_c_shards": "shards/run_c_*/runtime_pre_only_output.json"}
    path = tmp_path / "shards/run_c_000_002/runtime_pre_only_output.json"
    path.parent.mkdir(parents=True)
    rid = "race_20260201_tokyo_1R"
    path.write_text(json.dumps({"race_index": [{"date": "20260201", "race_id": rid}],
                                "generated_rows": [{"date": "20260201", "race_id": rid,
                                                    "horse_number": 1, "rank": 1,
                                                    "values": {"post_rc1_decision": "BUY",
                                                               "race_state": "PLAY_UNCONVERGED_4PLUS"}}]}))
    result = build_registry(inputs, tmp_path, config, parse_day=_parse)
    current = next(row for row in result["rows"] if row["lane"] == "CURRENT")
    rank1 = next(row for row in result["rows"] if row["lane"] == "CURRENT_RANK1")
    assert current["technical_predictable"] is True
    assert rank1["technical_predictable"] is True
    assert current["source_role"] == "SAVED_RUN_C_PRE_ONLY"


def test_independent_v5_primary_selection_precedes_comparison_matrix(tmp_path):
    inputs = tmp_path / "inputs"
    _inputs(inputs, "20260926")
    config = _config()
    config["lanes"]["INDEPENDENT_V5"]["patterns"] = [
        "saved/{date}/selection_manifest.json", "saved/{date}/prediction_matrix.csv"]
    folder = tmp_path / "saved/20260926"
    folder.mkdir(parents=True)
    rid = "race_20260926_tokyo_1R"
    (folder / "selection_manifest.json").write_text(json.dumps({"races": [
        {"race_id": rid, "selected_horses": [{"horse_number": 1}]}]}))
    (folder / "prediction_matrix.csv").write_text(
        f"date,race_id,INDEPENDENT_V5\n20260926,{rid},#2 Horse\n")
    result = build_registry(inputs, tmp_path, config, parse_day=_parse)
    v5 = next(row for row in result["rows"] if row["lane"] == "INDEPENDENT_V5")
    assert v5["technical_predictable"] is True
    assert v5["prediction_path"].endswith("selection_manifest.json")
