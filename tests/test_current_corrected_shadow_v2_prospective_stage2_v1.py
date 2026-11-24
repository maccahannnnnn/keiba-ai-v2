"""TECHNICAL_TEST_ONLY coverage for Stage 2 POST/CUMULATE state authority."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import review.current_corrected_shadow_v2_prospective_formal_pre_v1 as formal_pre
import review.current_corrected_shadow_v2_prospective_protocol_v1 as protocol_module
import review.current_corrected_shadow_v2_prospective_cumulative_v1 as cumulative_module
from review.current_corrected_shadow_v2_prospective_cumulative_v1 import _run_formal_cumulate_for_test
from review.current_corrected_shadow_v2_prospective_post_v1 import _run_formal_post_for_test
from review.current_corrected_shadow_v2_prospective_protocol_v1 import ROOT, Stop, sha
from review.current_corrected_shadow_v2_prospective_runtime_binding_v1 import FORMAL_RUNTIME_MODULES
from review.current_corrected_shadow_v2_prospective_protocol_v1 import verdict
from review.current_corrected_shadow_v2_prospective_state_v1 import CumulativeStateTransitions, PreStateTransitions, StateReader, protocol_state_from_cumulative_events
from review.current_corrected_shadow_v2_prospective_cumulative_fold_v1 import fold_cumulative_evidence


SANDBOX = ROOT / "reports" / "_current_corrected_shadow_v2_stage2_technical_test_only"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _tree_sha(root: Path) -> str:
    value = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            value.update(str(path.relative_to(root)).replace("\\", "/").encode())
            value.update(path.read_bytes())
    return value.hexdigest()


def _build_pre(target_date: str, root: Path, *, races: int = 5) -> Path:
    pre = root / "pre"
    pre.mkdir(parents=True)
    race_ids = [f"race_{target_date}_tokyo_{index}R" for index in range(1, races + 1)]
    _write(pre / "population.json", {"target_date": target_date, "races": [{"race_id": race_id, "target_k": 1, "primary_eligible": True} for race_id in race_ids]})
    _write(pre / "current_comparator.json", {"frozen_current_buy_rows": [{"race_id": race_id, "horse_number": 1} for race_id in race_ids]})
    _write(pre / "primary_selection.json", {"rows": [{"race_id": race_id, "horse_number": 2} for race_id in race_ids]})
    _write(pre / "natural_buy.json", {"rows": []})
    _write(pre / "integrity_check.json", {"result_data_access_count": 0})
    _write(pre / "exclusion_record.json", {"automatic_exclusions": []})
    _write(pre / "provenance.json", {"target_date": target_date, "attempt_id": f"{target_date}:technical", "protocol_identity": "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_PROTOCOL_V1", "authorization_id": "TECHNICAL_TEST_ONLY", "result_data_access_count": 0})
    _write(pre / "summary.json", {"status": "PRE_FROZEN", "target_date": target_date, "central_jra_meeting_week_id": f"block-{target_date}"})
    _write(pre / "safety.json", {"result_data_access_count": 0})
    (pre / "report.md").write_text("technical test\n", encoding="utf-8")
    indexed = {str(path.relative_to(pre)).replace("\\", "/"): sha(path) for path in pre.rglob("*") if path.is_file()}
    _write(pre / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": indexed})
    _write(pre / "pre_freeze_manifest.json", {"status": "PRE_FROZEN", "target_date": target_date, "attempt_id": f"{target_date}:technical", "protocol_identity": "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_PROTOCOL_V1", "authorization_id": "TECHNICAL_TEST_ONLY", "artifact_hashes_sha256": sha(pre / "artifact_hashes.json")})
    return pre


def _claim_pre(target_date: str, event_root: Path, pre: Path) -> None:
    state = PreStateTransitions(event_root)
    state.claim_date(target_date, attempt_id=f"{target_date}:technical", metadata={"authorization_id": "TECHNICAL_TEST_ONLY"})
    state.mark_pre_frozen_from_artifact(target_date, attempt_id=f"{target_date}:technical", pre_directory=pre)


def _loader(_date: str, pre: Path):
    rows = []
    for payload, horse in ((json.loads((pre / "current_comparator.json").read_text(encoding="utf-8")), 1), (json.loads((pre / "primary_selection.json").read_text(encoding="utf-8")), 2)):
        source = payload.get("frozen_current_buy_rows", payload.get("rows", []))
        for row in source:
            # Deliberately disjoint selections: counted semantics must be arm-level.
            rows.append({"race_id": row["race_id"], "horse_number": horse, "valid_result": True, "actual_top3": horse == 1})
    return rows, {"target_date": _date, "primary": "TECHNICAL_TEST_ONLY", "auxiliary": "TECHNICAL_TEST_ONLY", "primary_sha256": "a" * 64, "auxiliary_sha256": "b" * 64, "schema": {"technical_test_only": True}}


def _root() -> Path:
    if SANDBOX.exists():
        raise AssertionError("Stage 2 technical sandbox already exists")
    SANDBOX.mkdir(parents=True)
    return SANDBOX


def _technical_authorization(root: Path, target_date: str) -> Path:
    """Create a disposable, full-hash synthetic authorization/freeze fixture."""
    freeze = root / "current_corrected_shadow_v2_prospective_protocol_v1_freeze_technical"
    for module in FORMAL_RUNTIME_MODULES:
        destination = freeze / module.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(module, destination)
    _write(freeze / "freeze_record.json", {"role": "TECHNICAL_TEST_ONLY"})
    indexed = {str(path.relative_to(freeze)).replace("\\", "/"): sha(path) for path in freeze.rglob("*") if path.is_file()}
    _write(freeze / "artifact_hashes.json", {"indexed_artifacts": indexed})
    _write(freeze / "root_manifest.json", {"freeze_record_sha256": sha(freeze / "freeze_record.json"), "artifact_hashes_sha256": sha(freeze / "artifact_hashes.json")})
    (freeze / "root_manifest.sha256").write_text(sha(freeze / "root_manifest.json"), encoding="utf-8")
    artifact = root / "technical_authorization.json"
    protocol = protocol_module.load_protocol()
    _write(artifact, {"authorization_id": "TECHNICAL_TEST_ONLY", "protocol_name": protocol["protocol_name"], "protocol_version": protocol["protocol_version"], "protocol_sha256": sha(ROOT / "docs" / "current_corrected_shadow_v2_prospective_protocol_v1.json"), "authoritative_freeze_path": str(freeze.relative_to(ROOT)).replace("\\", "/"), "freeze_record_sha256": sha(freeze / "freeze_record.json"), "root_manifest_sha256": sha(freeze / "root_manifest.json"), "v2_freeze_identity": "CURRENT_CORRECTED_SHADOW_V2_FREEZE_V6", "v2_freeze_sha256": sha(protocol_module.FREEZE), "human_decision": "authorized", "authorization_status": "AUTHORIZED", "authorized_at": "2026-09-25T00:00:00+00:00", "authorization_date": "20260925", "production_authorization": False, "earliest_formal_target_date": target_date, "evidence_boundary": "TECHNICAL_TEST_ONLY", "retroactive_backfill_allowed": False, "artifact_provenance": "synthetic", "independent_review_status": "ACCEPT", "external_sha256_record": "TECHNICAL_TEST_ONLY", "human_action_artifact_store_schema": "CURRENT_CORRECTED_SHADOW_V2_HUMAN_ACTION_ARTIFACT_STORE", "human_action_artifact_store_version": "v1", "human_action_artifact_root": "reports/_technical_human_action_store"})
    artifact.with_name(artifact.name + ".sha256").write_text(sha(artifact), encoding="utf-8")
    return artifact


def test_post_requires_pre_frozen() -> None:
    root = _root()
    try:
        try:
            _run_formal_post_for_test("20270101", event_root=root / "state", output_root=root / "post", result_loader=_loader)
        except Stop as exc:
            assert str(exc) == "STOP_POST_REQUIRES_PRE_FROZEN"
        else:
            raise AssertionError("POST accepted UNCLAIMED")
    finally:
        shutil.rmtree(root)


def test_n1_actual_run_formal_pre_pipeline_technical_only() -> None:
    """Exercise the real public entry and real PRE body without Formal registry use.

    The consumed 9/26 fixture predates the frozen protocol, so only the G1
    date-boundary check is temporarily replaced in this disposable test.  All
    authorization/freeze hash verification, adapter loading and PRE pipeline
    code remain real.  This is not Formal evidence.
    """
    root = _root(); target_date = "20260926"; state_root = root / "isolated_state"
    original_factory, original_formal_start, original_protocol_start, original_gate, original_clock = formal_pre.PreStateTransitions, formal_pre.validate_start, protocol_module.validate_start, formal_pre.require_governance_allows_operation, formal_pre._now_utc
    try:
        authorization = _technical_authorization(root, target_date)
        formal_pre.PreStateTransitions = lambda: original_factory(state_root)  # type: ignore[assignment]
        formal_pre.validate_start = lambda *_args, **_kwargs: None  # type: ignore[assignment]
        protocol_module.validate_start = lambda *_args, **_kwargs: None  # type: ignore[assignment]
        formal_pre.require_governance_allows_operation = lambda *_args, **_kwargs: {"current_ledger_head_sha256": None}  # type: ignore[assignment]
        formal_pre._now_utc = lambda: __import__('datetime').datetime(2026, 9, 26, tzinfo=__import__('datetime').timezone.utc)  # type: ignore[assignment]
        output = root / "actual_pre"
        result = formal_pre.run_formal_pre(target_date, ROOT / "data/raw/prediction_input/DG260926.CSV", ROOT / "data/raw/prediction_input/DE260926.CSV", ROOT / "data/raw/prediction_input/DS260926.CSV", output, authorization_path=authorization)
        assert result.pre_directory == output and (output / "pre_freeze_manifest.json").is_file()
        assert StateReader(state_root).get_date_state(target_date) == "PRE_FROZEN"
        try:
            formal_pre.run_formal_pre(target_date, ROOT / "data/raw/prediction_input/DG260926.CSV", ROOT / "data/raw/prediction_input/DE260926.CSV", ROOT / "data/raw/prediction_input/DS260926.CSV", root / "second", authorization_path=authorization)
        except Stop as exc:
            assert str(exc) == "STOP_FORMAL_DATE_ALREADY_ATTEMPTED"
        else:
            raise AssertionError("second technical claim accepted")
    finally:
        formal_pre.PreStateTransitions, formal_pre.validate_start, protocol_module.validate_start, formal_pre.require_governance_allows_operation, formal_pre._now_utc = original_factory, original_formal_start, original_protocol_start, original_gate, original_clock
        shutil.rmtree(root)


def test_post_immutable_and_disjoint_arm_counted() -> None:
    root = _root()
    try:
        date, state_root = "20270101", root / "state"
        pre = _build_pre(date, root / date); _claim_pre(date, state_root, pre)
        post = _run_formal_post_for_test(date, event_root=state_root, output_root=root / date / "post", result_loader=_loader)
        before = _tree_sha(post)
        event = _run_formal_cumulate_for_test(date, event_root=state_root)
        assert event.is_file() and before == _tree_sha(post)
        metrics = json.loads((post / "race_metrics.json").read_text(encoding="utf-8"))["races"]
        assert len(metrics) == 5 and all(item["counted"] for item in metrics)
        assert StateReader(state_root).get_date_state(date) == "CUMULATED"
    finally:
        shutil.rmtree(root)


def test_twelve_date_event_ledger_reaches_single_terminal_verdict() -> None:
    root = _root()
    try:
        state_root = root / "state"
        dates = [f"202701{index:02d}" for index in range(1, 13)]
        for date in dates:
            pre = _build_pre(date, root / date); _claim_pre(date, state_root, pre)
            _run_formal_post_for_test(date, event_root=state_root, output_root=root / date / "post", result_loader=_loader)
            _run_formal_cumulate_for_test(date, event_root=state_root)
        final = json.loads((state_root / "cumulative_events" / f"{dates[-1]}.json").read_text(encoding="utf-8"))
        assert final["accumulated_races_after_append"] == 60 and final["accumulated_dates_after_append"] == 12
        assert final["evaluation_point_consumed"] is True
        assert final["protocol_state_after"] == "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_REJECT"
        extra = "20270113"; pre = _build_pre(extra, root / extra)
        try:
            _claim_pre(extra, state_root, pre)
        except Stop as exc:
            assert str(exc) == "STOP_EVALUATION_POINT_CONSUMED"
        else:
            raise AssertionError("terminal protocol accepted new PRE")
    finally:
        shutil.rmtree(root)


def test_canonical_verdict_boundaries() -> None:
    assert verdict(59, 12, 0, 1).startswith("HOLD")
    assert verdict(60, 11, 0, 1).startswith("HOLD")
    assert verdict(60, 12, 1, 1) == "HOLD_VOLUME_CONFOUNDED"
    assert verdict(60, 12, 0, -0.001).endswith("REJECT")
    assert verdict(60, 12, 0, 0).endswith("ACCEPT")
    assert verdict(60, 12, 0, 0.001).endswith("ACCEPT")


def test_post_and_cumulate_fail_closed_matrix() -> None:
    root = _root()
    try:
        state_root = root / "state"
        # A tampered PRE cannot start POST, and duplicate result identity is rejected.
        date = "20270201"; pre = _build_pre(date, root / "tampered"); _claim_pre(date, state_root, pre)
        (pre / "summary.json").write_text("{}", encoding="utf-8")
        try:
            _run_formal_post_for_test(date, event_root=state_root, output_root=root / "tampered_post", result_loader=_loader)
        except Stop as exc: assert str(exc) == "STOP_PRE_FREEZE_INTEGRITY_FAILURE"
        else: raise AssertionError("tampered PRE accepted")
        first, second = "20270102", "20270103"
        for value in (first, second):
            pre = _build_pre(value, root / value); _claim_pre(value, state_root, pre)
            _run_formal_post_for_test(value, event_root=state_root, output_root=root / value / "post", result_loader=_loader)
        try:
            _run_formal_cumulate_for_test(second, event_root=state_root)
        except Stop as exc: assert str(exc) == "STOP_EARLIER_FORMAL_DATE_PENDING"
        else: raise AssertionError("out-of-order cumulative accepted")
        _run_formal_cumulate_for_test(first, event_root=state_root)
        _run_formal_cumulate_for_test(second, event_root=state_root)
        try:
            _run_formal_post_for_test(second, event_root=state_root, output_root=root / second / "again", result_loader=_loader)
        except Stop as exc: assert str(exc) == "STOP_POST_REQUIRES_PRE_FROZEN"
        else: raise AssertionError("second POST accepted")
    finally:
        shutil.rmtree(root)


def _crashed_cumulative_event(root: Path, label: str, date: str = "20270301") -> tuple[Path, Path]:
    """Write one canonical event, then simulate the pre-state-write crash window."""
    state_root = root / label / "state"
    pre = _build_pre(date, root / label / date)
    _claim_pre(date, state_root, pre)
    _run_formal_post_for_test(date, event_root=state_root, output_root=root / label / date / "post", result_loader=_loader)
    original = CumulativeStateTransitions.mark_cumulated_from_event
    def crash(*_args, **_kwargs):
        raise RuntimeError("TECHNICAL_TEST_ONLY_CRASH_AFTER_EVENT_WRITE")
    CumulativeStateTransitions.mark_cumulated_from_event = crash  # type: ignore[assignment]
    try:
        try:
            _run_formal_cumulate_for_test(date, event_root=state_root)
        except RuntimeError as exc:
            assert str(exc) == "TECHNICAL_TEST_ONLY_CRASH_AFTER_EVENT_WRITE"
        else:
            raise AssertionError("crash window was not reached")
    finally:
        CumulativeStateTransitions.mark_cumulated_from_event = original  # type: ignore[assignment]
    event = state_root / "cumulative_events" / f"{date}.json"
    assert event.is_file() and StateReader(state_root).get_date_state(date) == "POST_FROZEN"
    return state_root, event


def test_cumulative_tamper_matrix_direct_writer_and_recovery() -> None:
    """Every stored cumulative semantic is independently rejected in both paths."""
    root = _root()
    try:
        # Same suite's unmodified control: only this event is permitted.
        control_state, control_event = _crashed_cumulative_event(root, "tamper_valid_control", "20270228")
        CumulativeStateTransitions(control_state).mark_cumulated_from_event("20270228", event_path=control_event)
        assert StateReader(control_state).get_date_state("20270228") == "CUMULATED"
        variants = {
            "counted_race_rows": lambda value: value.__setitem__("counted_race_rows", []),
            "fabricated_60_rows": lambda value: value.__setitem__("counted_race_rows", value["counted_race_rows"] * 12),
            "accumulated_races": lambda value: value.__setitem__("accumulated_races_after_append", 60),
            "accumulated_dates": lambda value: value.__setitem__("accumulated_dates_after_append", 12),
            "accumulated_blocks": lambda value: value.__setitem__("accumulated_blocks_after_append", 60),
            "comparator": lambda value: value["comparator"].__setitem__("hits", 99),
            "primary": lambda value: value["primary"].__setitem__("hits", 99),
            "secondary": lambda value: value["secondary"].__setitem__("hits", 99),
            "shortfall": lambda value: value.__setitem__("shortfall", 99),
            "lift": lambda value: value.__setitem__("pooled_lift_pt", 99.0),
            "protocol_before": lambda value: value.__setitem__("protocol_state_before", "RUNNING"),
            "protocol_after": lambda value: value.__setitem__("protocol_state_after", "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_ACCEPT"),
            "evaluation_flag": lambda value: value.__setitem__("evaluation_point_consumed", True),
            "terminal": lambda value: value.__setitem__("terminal_verdict", "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_ACCEPT"),
            "candidate_label": lambda value: value.__setitem__("candidate_label", "PRODUCTION_DESIGN_REVIEW_ELIGIBLE"),
            "zero_row_accept": lambda value: (value.__setitem__("counted_race_rows", []), value.__setitem__("protocol_state_after", "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_ACCEPT")),
        }
        post_row_cases = {"counted_race_rows", "fabricated_60_rows", "zero_row_accept"}
        for index, (name, mutate) in enumerate(variants.items(), start=1):
            date = f"202703{index:02d}"
            state_root, event_path = _crashed_cumulative_event(root, f"tamper_{index}", date)
            value = json.loads(event_path.read_text(encoding="utf-8")); mutate(value); _write(event_path, value)
            for path in ("direct", "recovery"):
                try:
                    if path == "direct":
                        CumulativeStateTransitions(state_root).mark_cumulated_from_event(date, event_path=event_path)
                    else:
                        _run_formal_cumulate_for_test(date, event_root=state_root)
                except Stop as exc:
                    expected = "STOP_CUMULATIVE_EVENT_INTEGRITY" if path == "recovery" and name in post_row_cases else "STOP_CUMULATIVE_EVENT_CONTENT_MISMATCH"
                    assert str(exc) == expected, (name, path, str(exc), expected)
                else:
                    raise AssertionError(f"tamper accepted: {index}/{path}")
        # A later canonical date is an explicit monotonicity violation, not a
        # generic content error.
        state_root, event_path = _crashed_cumulative_event(root, "monotonic", "20270401")
        _write(state_root / "cumulative_events" / "20270402.json", {"target_date": "20270402"})
        try:
            CumulativeStateTransitions(state_root).mark_cumulated_from_event("20270401", event_path=event_path)
        except Stop as exc:
            assert str(exc) == "STOP_NON_MONOTONIC_CUMULATIVE_DATE"
        else:
            raise AssertionError("later ledger date accepted")
    finally:
        shutil.rmtree(root)


def test_cumulative_crash_recovery_matrix() -> None:
    root = _root()
    try:
        # A: canonical event exists but CUMULATED transition did not happen.
        state_root, event = _crashed_cumulative_event(root, "recover_a", "20270501")
        assert _run_formal_cumulate_for_test("20270501", event_root=state_root) == event
        assert StateReader(state_root).get_date_state("20270501") == "CUMULATED"
        # B: no event exists; normal append succeeds.
        state_root = root / "recover_b" / "state"; pre = _build_pre("20270502", root / "recover_b" / "date")
        _claim_pre("20270502", state_root, pre); _run_formal_post_for_test("20270502", event_root=state_root, output_root=root / "recover_b" / "post", result_loader=_loader)
        assert _run_formal_cumulate_for_test("20270502", event_root=state_root).is_file()
        # C: recovery cannot create a second 004 state event.
        try:
            _run_formal_cumulate_for_test("20270501", event_root=root / "recover_a" / "state")
        except Stop as exc:
            assert str(exc) == "STOP_CUMULATE_REQUIRES_POST_FROZEN"
        else:
            raise AssertionError("duplicate recovery accepted")
    finally:
        shutil.rmtree(root)


def _fold_fixture(*, dates: int, rows_per_date: int, comparator_hits: int, primary_hits: int, shortfall: int = 0, invalid_primary: bool = False) -> list[dict]:
    events = []
    for day in range(1, dates + 1):
        date = f"202706{day:02d}"
        rows = []
        for row in range(rows_per_date):
            rows.append({"target_date": date, "race_id": f"{date}-{row}", "block_id": f"block-{date}", "shortfall": shortfall, "comparator": {"valid_selected_n": 1, "hits": comparator_hits}, "primary": {"valid_selected_n": 1, "hits": primary_hits, "invalid_n": 1 if invalid_primary and day == 1 and row == 0 else 0}, "secondary": {"valid_selected_n": 0, "hits": 0}})
        events.append({"target_date": date, "counted_race_rows": rows})
    return events


def test_verdict_lifecycle_and_fold_boundaries() -> None:
    accept = fold_cumulative_evidence(_fold_fixture(dates=12, rows_per_date=5, comparator_hits=0, primary_hits=1, invalid_primary=True))
    assert accept["protocol_state_after"].endswith("ACCEPT") and accept["evaluation_point_consumed"] is True
    hold = fold_cumulative_evidence(_fold_fixture(dates=12, rows_per_date=5, comparator_hits=0, primary_hits=1, shortfall=1))
    assert hold["protocol_state_after"] == "HOLD_VOLUME_CONFOUNDED" and hold["evaluation_point_consumed"] is True
    reject = fold_cumulative_evidence(_fold_fixture(dates=12, rows_per_date=5, comparator_hits=1, primary_hits=0))
    assert reject["protocol_state_after"].endswith("REJECT") and reject["evaluation_point_consumed"] is True
    assert fold_cumulative_evidence(_fold_fixture(dates=12, rows_per_date=5, comparator_hits=0, primary_hits=1)[:-1] + [{"target_date": "20270612", "counted_race_rows": _fold_fixture(dates=1, rows_per_date=4, comparator_hits=0, primary_hits=1)[0]["counted_race_rows"]}])["protocol_state_after"] == "HOLD:EVIDENCE_QUANTITY"
    assert fold_cumulative_evidence(_fold_fixture(dates=11, rows_per_date=5, comparator_hits=0, primary_hits=1) + [{"target_date": "20270612", "counted_race_rows": _fold_fixture(dates=1, rows_per_date=5, comparator_hits=0, primary_hits=1)[0]["counted_race_rows"]}])["protocol_state_after"] == "HOLD:EVIDENCE_QUANTITY"


def test_chronology_pre_post_no_pre_and_terminal_claim() -> None:
    root = _root()
    try:
        state_root = root / "state"; state = PreStateTransitions(state_root)
        state.claim_date("20270701", attempt_id="no-pre", metadata={"authorization_id": "TECHNICAL_TEST_ONLY"})
        state.mark_no_pre("20270701", reason="TECHNICAL_TEST_ONLY")
        assert StateReader(state_root).get_date_state("20270701") == "NO_PRE"
        try:
            _run_formal_cumulate_for_test("20270701", event_root=state_root)
        except Stop as exc:
            assert str(exc) == "STOP_CUMULATE_REQUIRES_POST_FROZEN"
        else:
            raise AssertionError("NO_PRE entered CUMULATE")
    finally:
        shutil.rmtree(root)


def _build_pre_k2(target_date: str, root: Path, *, races: int, shortfall_races: set[int] | None = None) -> Path:
    """A PRE fixture whose raw selections—not result validity—define B1."""
    pre = root / "pre"; pre.mkdir(parents=True)
    shortfall_races = shortfall_races or set()
    race_ids = [f"race_{target_date}_tokyo_{index}R" for index in range(1, races + 1)]
    population = [{"race_id": race_id, "target_k": 2, "primary_eligible": True} for race_id in race_ids]
    current = [{"race_id": race_id, "horse_number": horse} for race_id in race_ids for horse in (1, 2)]
    primary = [{"race_id": race_id, "horse_number": 3} for race_id in race_ids]
    primary += [{"race_id": race_id, "horse_number": 4} for index, race_id in enumerate(race_ids, start=1) if index not in shortfall_races]
    _write(pre / "population.json", {"target_date": target_date, "races": population})
    _write(pre / "current_comparator.json", {"frozen_current_buy_rows": current})
    _write(pre / "primary_selection.json", {"rows": primary})
    _write(pre / "natural_buy.json", {"rows": []})
    _write(pre / "integrity_check.json", {"result_data_access_count": 0})
    _write(pre / "exclusion_record.json", {"automatic_exclusions": []})
    _write(pre / "provenance.json", {"target_date": target_date, "attempt_id": f"{target_date}:technical", "protocol_identity": "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_PROTOCOL_V1", "authorization_id": "TECHNICAL_TEST_ONLY", "result_data_access_count": 0})
    _write(pre / "summary.json", {"status": "PRE_FROZEN", "target_date": target_date, "central_jra_meeting_week_id": f"block-{target_date}"})
    _write(pre / "safety.json", {"result_data_access_count": 0}); (pre / "report.md").write_text("technical lifecycle\n", encoding="utf-8")
    indexed = {str(path.relative_to(pre)).replace("\\", "/"): sha(path) for path in pre.rglob("*") if path.is_file()}
    _write(pre / "artifact_hashes.json", {"self_hash_excluded": True, "indexed_artifacts": indexed})
    _write(pre / "pre_freeze_manifest.json", {"status": "PRE_FROZEN", "target_date": target_date, "attempt_id": f"{target_date}:technical", "protocol_identity": "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_PROTOCOL_V1", "authorization_id": "TECHNICAL_TEST_ONLY", "artifact_hashes_sha256": sha(pre / "artifact_hashes.json")})
    return pre


def _k2_loader(*, invalid_primary: tuple[str, int] | None = None, primary_hit: bool = True, comparator_hit: bool = False):
    def loader(date: str, pre: Path):
        rows = []
        for row in json.loads((pre / "current_comparator.json").read_text(encoding="utf-8"))["frozen_current_buy_rows"]:
            rows.append({"race_id": row["race_id"], "horse_number": row["horse_number"], "valid_result": True, "actual_top3": comparator_hit})
        for row in json.loads((pre / "primary_selection.json").read_text(encoding="utf-8"))["rows"]:
            key = (row["race_id"], row["horse_number"])
            valid = key != invalid_primary
            rows.append({"race_id": row["race_id"], "horse_number": row["horse_number"], "valid_result": valid, "actual_top3": bool(primary_hit and valid and row["horse_number"] == 3)})
        return rows, {"target_date": date, "primary": "TECHNICAL_TEST_ONLY", "auxiliary": "TECHNICAL_TEST_ONLY", "primary_sha256": "c" * 64, "auxiliary_sha256": "d" * 64, "schema": {"technical_test_only": True}}
    return loader


def _run_k2_lifecycle(root: Path, *, dates: list[str], race_counts: list[int] | None = None, shortfall_dates: set[str] | None = None, loader=None) -> tuple[Path, list[dict]]:
    state_root = root / "state"; race_counts = race_counts or [5] * len(dates); shortfall_dates = shortfall_dates or set(); loader = loader or _k2_loader()
    for date, races in zip(dates, race_counts):
        pre = _build_pre_k2(date, root / date, races=races, shortfall_races={1} if date in shortfall_dates else set())
        _claim_pre(date, state_root, pre)
        _run_formal_post_for_test(date, event_root=state_root, output_root=root / date / "post", result_loader=loader)
        _run_formal_cumulate_for_test(date, event_root=state_root)
    events = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((state_root / "cumulative_events").glob("*.json"))]
    return state_root, events


def _assert_fold_gate_stored_equality(state_root: Path, events: list[dict]) -> dict:
    folded = fold_cumulative_evidence(events); latest = events[-1]
    assert protocol_state_from_cumulative_events(state_root) == folded["protocol_state_after"]
    assert latest["protocol_state_before"] == ("NOT_STARTED" if len(events) == 1 else fold_cumulative_evidence(events[:-1])["protocol_state_after"])
    mapping = {"accumulated_races_after_append": "counted_races", "accumulated_dates_after_append": "counted_dates", "accumulated_blocks_after_append": "accumulated_blocks", "comparator": "comparator", "primary": "primary", "secondary": "secondary", "pooled_lift_pt": "pooled_lift_pt", "shortfall": "shortfall", "protocol_state_after": "protocol_state_after", "evaluation_point_consumed": "evaluation_point_consumed", "terminal_verdict": "terminal_verdict", "candidate_label": "candidate_label"}
    for stored, folded_key in mapping.items(): assert latest[stored] == folded[folded_key], (stored, latest[stored], folded[folded_key])
    return folded


def test_b1_real_post_lifecycle_invalid_result_accept() -> None:
    root = _root()
    try:
        dates = [f"202708{day:02d}" for day in range(1, 13)]
        invalid_key = ("race_20270801_tokyo_1R", 4)
        state_root, events = _run_k2_lifecycle(root, dates=dates, loader=_k2_loader(invalid_primary=invalid_key))
        first_post = json.loads((root / dates[0] / "post" / "race_metrics.json").read_text(encoding="utf-8"))["races"][0]
        assert first_post["primary"] == {"selected_n_raw": 2, "invalid_n": 1, "valid_selected_n": 1, "hits": 1}
        assert first_post["shortfall"] == 0
        folded = _assert_fold_gate_stored_equality(state_root, events)
        assert folded["counted_races"] >= 60 and folded["protocol_state_after"].endswith("ACCEPT")
        assert folded["candidate_label"] == "PRODUCTION_DESIGN_REVIEW_ELIGIBLE" and folded["evaluation_point_consumed"] is True
    finally:
        shutil.rmtree(root)


def test_hold_volume_full_lifecycle_and_terminal_behavior() -> None:
    root = _root()
    try:
        dates = [f"202709{day:02d}" for day in range(1, 13)]
        state_root, events = _run_k2_lifecycle(root, dates=dates, shortfall_dates=set(dates))
        folded = _assert_fold_gate_stored_equality(state_root, events)
        assert folded["protocol_state_after"] == "HOLD_VOLUME_CONFOUNDED" and folded["evaluation_point_consumed"] is True
        state = PreStateTransitions(state_root)
        try: state.claim_date("20270913", attempt_id="late", metadata={"authorization_id": "TECHNICAL_TEST_ONLY"})
        except Stop as exc: assert str(exc) == "STOP_EVALUATION_POINT_CONSUMED"
        else: raise AssertionError("terminal protocol accepted a claim")
    finally:
        shutil.rmtree(root)


def test_full_lifecycle_boundaries_and_fold_gate_stored_equality() -> None:
    root = _root()
    try:
        cases = [
            ("r59d12", [f"202710{day:02d}" for day in range(1, 13)], [5] * 11 + [4], "HOLD:EVIDENCE_QUANTITY", False, False, True),
            ("r60d11", [f"202711{day:02d}" for day in range(1, 12)], [5] * 10 + [10], "HOLD:EVIDENCE_QUANTITY", False, False, True),
            ("reject", [f"202712{day:02d}" for day in range(1, 13)], [5] * 12, "CURRENT_CORRECTED_SHADOW_V2_PROSPECTIVE_REJECT", True, True, False),
        ]
        for label, dates, counts, expected, consumed, comparator_hit, primary_hit in cases:
            state_root, events = _run_k2_lifecycle(root / label, dates=dates, race_counts=counts, loader=_k2_loader(comparator_hit=comparator_hit, primary_hit=primary_hit))
            folded = _assert_fold_gate_stored_equality(state_root, events)
            assert folded["protocol_state_after"] == expected and folded["evaluation_point_consumed"] is consumed
    finally:
        shutil.rmtree(root)


def test_chronology_full_matrix_and_verdict_reversal_regression() -> None:
    root = _root()
    try:
        # A/B/C: create later waiting PRE/POST states before the 60th race
        # consumes the evaluation point.
        terminal_root = root / "terminal"; state_root, _ = _run_k2_lifecycle(terminal_root, dates=[f"202801{day:02d}" for day in range(1, 12)])
        date12, date13, date14 = "20280112", "20280113", "20280114"
        for date, post in ((date12, True), (date13, True), (date14, False)):
            pre = _build_pre_k2(date, terminal_root / date, races=5); _claim_pre(date, state_root, pre)
            if post: _run_formal_post_for_test(date, event_root=state_root, output_root=terminal_root / date / "post", result_loader=_k2_loader())
        _run_formal_cumulate_for_test(date12, event_root=state_root)
        try: PreStateTransitions(state_root).claim_date("20280115", attempt_id="after-terminal", metadata={"authorization_id": "TECHNICAL_TEST_ONLY"})
        except Stop as exc: assert str(exc) == "STOP_EVALUATION_POINT_CONSUMED"
        else: raise AssertionError("new claim after terminal accepted")
        try: _run_formal_post_for_test(date14, event_root=state_root, output_root=terminal_root / date14 / "post", result_loader=_k2_loader())
        except Stop as exc: assert str(exc) == "STOP_EVALUATION_POINT_CONSUMED"
        else: raise AssertionError("waiting PRE POST accepted")
        try: _run_formal_cumulate_for_test(date13, event_root=state_root)
        except Stop as exc: assert str(exc) == "STOP_EVALUATION_POINT_CONSUMED"
        else: raise AssertionError("waiting POST CUMULATE accepted")

        # An older PRE is a blocker, whereas an older NO_PRE is not.
        blocked = root / "blocked" / "state"; old = _build_pre_k2("20280201", root / "blocked" / "old", races=5); _claim_pre("20280201", blocked, old)
        later = _build_pre_k2("20280202", root / "blocked" / "later", races=5); _claim_pre("20280202", blocked, later); _run_formal_post_for_test("20280202", event_root=blocked, output_root=root / "blocked" / "later_post", result_loader=_k2_loader())
        try: _run_formal_cumulate_for_test("20280202", event_root=blocked)
        except Stop as exc: assert str(exc) == "STOP_EARLIER_FORMAL_DATE_PENDING"
        else: raise AssertionError("older PRE did not block later CUMULATE")
        no_pre = root / "no_pre" / "state"; state = PreStateTransitions(no_pre); state.claim_date("20280301", attempt_id="no-pre", metadata={"authorization_id": "TECHNICAL_TEST_ONLY"}); state.mark_no_pre("20280301", reason="TECHNICAL_TEST_ONLY")
        pre = _build_pre_k2("20280302", root / "no_pre" / "later", races=5); _claim_pre("20280302", no_pre, pre); _run_formal_post_for_test("20280302", event_root=no_pre, output_root=root / "no_pre" / "post", result_loader=_k2_loader()); assert _run_formal_cumulate_for_test("20280302", event_root=no_pre).is_file()

        # Formal public entry is routed to an injected technical root solely to
        # verify its monotonic-date guard; authorization is outside this test.
        public_project = root / "public"; public_state = public_project / "reports" / "current_corrected_shadow_v2_prospective_state_v1"
        public_project.mkdir(parents=True, exist_ok=True); (public_project / "technical.json").write_text("{}", encoding="utf-8")
        for date in ("20280402",):
            pre = _build_pre_k2(date, public_project / date, races=5); _claim_pre(date, public_state, pre); _run_formal_post_for_test(date, event_root=public_state, output_root=public_project / date / "post", result_loader=_k2_loader())
        _run_formal_cumulate_for_test("20280402", event_root=public_state)
        pre = _build_pre_k2("20280401", public_project / "20280401", races=5); _claim_pre("20280401", public_state, pre); _run_formal_post_for_test("20280401", event_root=public_state, output_root=public_project / "20280401" / "post", result_loader=_k2_loader())
        old_root, old_load, old_auth, old_bind = cumulative_module.ROOT, cumulative_module.load_protocol, cumulative_module.validate_authorization_artifact, cumulative_module.validate_runtime_freeze_binding
        try:
            cumulative_module.ROOT = public_project
            (public_project / "human_store").mkdir()
            cumulative_module.load_protocol = lambda: {"execution_authorization": {"artifact_path": "technical.json"}}  # type: ignore[assignment]
            cumulative_module.validate_authorization_artifact = lambda *_args, **_kwargs: {"authoritative_freeze_path": "technical-freeze", "authorization_id": "TECHNICAL_TEST_ONLY", "human_action_artifact_store_schema": "CURRENT_CORRECTED_SHADOW_V2_HUMAN_ACTION_ARTIFACT_STORE", "human_action_artifact_store_version": "v1", "human_action_artifact_root": str(public_project / "human_store")}  # type: ignore[assignment]
            cumulative_module.validate_runtime_freeze_binding = lambda *_args, **_kwargs: None  # type: ignore[assignment]
            try: cumulative_module.run_formal_cumulate("20280401")
            except Stop as exc: assert str(exc) == "STOP_NON_MONOTONIC_CUMULATIVE_DATE"
            else: raise AssertionError("public non-monotonic CUMULATE accepted")
        finally:
            cumulative_module.ROOT, cumulative_module.load_protocol, cumulative_module.validate_authorization_artifact, cumulative_module.validate_runtime_freeze_binding = old_root, old_load, old_auth, old_bind

        # Reversal: append 2/2..2/12, leave 2/13 POST_FROZEN, then reject a
        # later attempt to insert 2/1 without changing the canonical ledger.
        reversal_root = root / "reversal"; reversal_state, _ = _run_k2_lifecycle(reversal_root, dates=[f"202702{day:02d}" for day in range(2, 13)])
        for date in ("20270213", "20270201"):
            pre = _build_pre_k2(date, reversal_root / date, races=5); _claim_pre(date, reversal_state, pre); _run_formal_post_for_test(date, event_root=reversal_state, output_root=reversal_root / date / "post", result_loader=_k2_loader())
        before_events = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((reversal_state / "cumulative_events").glob("*.json"))]
        before_fold = fold_cumulative_evidence(before_events); before_state = protocol_state_from_cumulative_events(reversal_state)
        try: _run_formal_cumulate_for_test("20270201", event_root=reversal_state)
        except Stop as exc: assert str(exc) == "STOP_NON_MONOTONIC_CUMULATIVE_DATE"
        else: raise AssertionError("out-of-order reversal accepted")
        after_events = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((reversal_state / "cumulative_events").glob("*.json"))]
        assert before_events == after_events and before_fold == fold_cumulative_evidence(after_events) and before_state == protocol_state_from_cumulative_events(reversal_state)
    finally:
        shutil.rmtree(root)
