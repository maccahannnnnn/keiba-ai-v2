"""Actual-shape fixtures for the WS2 v2 canonical compatibility layer.

Fixtures contain only structural representative values.  They are not a
dataset, a prediction run, or a performance fixture.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import unittest
import csv
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from review.ws2_data_integrity_preflight_v2 import DataIntegrityStop
import review.ws2_data_integrity_preflight_v2_source_bound as source_bound
from review.ws2_data_integrity_preflight_v2_source_bound import (
    CanonicalSourceMaterializer, _columns, materialize_prediction_rows,
    _strict_label_boolean, audit_ds_chronology, reconcile_pipeline,
    rolling_origin_folds, run_preflight, resolve_canonical_dataset_target,
    derive_iteration_readiness,
)

ROOT = Path(__file__).parents[1]
POLICY = json.loads((ROOT / "docs/ws2_v5_feature_source_policy_v3.json").read_text(encoding="utf-8"))
ACTUAL_HEADER = [
    "row_id", "date", "race_id", "target_race_key", "horse_number", "horse_name", "shadow_ai_rank", "decision_score", "final_score", "adjusted_score", "absolute_quality_pass", "relative_advantage_pass", "effective_reliability_pass", "risk_guard_pass", "consensus_positive_count", "consensus_negative_count", "risk_count", "conflict_count", "race_state", "Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle", "adjusted_score_gap_to_top", "current_buy", "current_top5", "selection_error_category", "actual_top3", "actual_finish", "valid_result", "source_prediction_artifact_path", "source_prediction_artifact_sha256", "source_result_artifact_path", "source_result_artifact_sha256", "source_block", "evidence_role_note", "dataset_version", "split_role",
]


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_docs(root: Path) -> None:
    for relative in (
        "docs/ws2_v5_feature_source_policy_v3.json",
        "docs/ws2_data_integrity_preflight_v2_contract_revision_8.json",
        "docs/ws2_v5_feature_source_policy_v4.json",
        "docs/ws2_data_integrity_preflight_v2_contract_revision_9.json",
        "docs/ws2_v5_feature_source_policy_v5.json",
        "docs/ws2_data_integrity_preflight_v2_contract_revision_10.json",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())


def trace_race() -> dict:
    snapshot = {name: 1.0 for name in ("Ability", "PastPerformance", "Distance", "CourseShape", "LapSuitability", "RaceShape", "PaceStyle")}
    trace = {"horse_number": 1, "shadow_ai_rank": 1, "decision_score": 1.0, "final_score": 2.0, "adjusted_score": 3.0, "absolute_quality_pass": True, "relative_advantage_pass": True, "effective_reliability_pass": True, "risk_guard_pass": True, "positive_count": 2, "negative_count": 0, "evaluator_score_snapshot": snapshot}
    ranked = {"horse_number": 1, "horse_name": "fixture", "rank": 1, "decision_score": 1.0, "final_score": 2.0, "adjusted_score": 3.0, "consensus_positive_count": 2, "consensus_negative_count": 0, "risk_count": 0, "conflict_count": 0, "buy_v1_rc1_race_state": "PLAY"}
    return {"race_id": "race_20260401_tokyo_1R", "buy_gate_trace": {"horses": [trace]}, "ranked_results": [ranked]}


def index(root: Path, names: list[str]) -> None:
    dump(root / "artifact_hash_index.json", {"indexed_artifacts": {name: digest(root / name) for name in names}})


def target_rows(date: str, races: list[tuple[int, str]]) -> tuple[list[list[str]], list[list[str]], list[list[str]], list[list[str]]]:
    dg, de, ds, result = [], [], [], []
    for number, horse in races:
        d = [""] * 11; d[0:5] = [date[:4], str(int(date[4:6])), str(int(date[6:])), "東京", str(number)]; d[7:10] = ["芝", "1600", "1"]; dg.append(d)
        e = [""] * 33; e[0:5] = [date[2:], "東京", str(number), "1", "1勝"]; e[7], e[10], e[11], e[16], e[18], e[20], e[22], e[32] = horse, "j", "55", "s", f"20{number:06d}", "d", "1", f"05{date[2:6]}{number:02d}01"; de.append(e)
        s = [""] * 50; s[0:3] = ["25", "1", "1"]; s[4], s[6], s[8], s[12], s[14], s[15], s[16], s[21], s[23] = "東京", "1", "1勝", "芝", "1600", "良", horse, "1", "1"; ds.append(s)
        result.append([f"{date}{number:08d}", "東京", str(number), "fixture", "", "", "", "", "", "1", "", "", "1"])
    return dg, de, ds, result


def write_csv(path: Path, rows: list[list[str]], encoding: str = "cp932") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=encoding, newline="") as handle: csv.writer(handle).writerows(rows)


class SourceBoundFixtureMixin:
    RUNTIME_MODULES = (
        "review/target_bulk_prediction_input_shadow_v1.py",
        "review/ml_v4_buy_selection_dataset_build_v5_1.py",
        "review/ws2_data_integrity_preflight_v2_source_bound.py",
    )

    def install_runtime_fixture_modules(self) -> None:
        for relative in self.RUNTIME_MODULES:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())

    def setUp(self) -> None:
        self.root = ROOT / ".tmp" / f"ws2_actual_shape_{uuid4().hex}"
        self.root.mkdir(parents=True)
        install_docs(self.root)
        # The source-bound validator statically inspects these approved
        # producer modules.  Copying them into the isolated fixture does not
        # execute them or touch production artifacts.
        self.install_runtime_fixture_modules()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def materializer(self) -> CanonicalSourceMaterializer:
        return CanonicalSourceMaterializer(self.root)

    def refresh_policy_v5_overlay(self) -> Path:
        """Keep the fixture-only additive policy chain hash-pinned."""
        v4 = self.root / "docs/ws2_v5_feature_source_policy_v4.json"
        v5 = self.root / "docs/ws2_v5_feature_source_policy_v5.json"
        value = json.loads(v5.read_text(encoding="utf-8"))
        value["base_policy_sha256"] = digest(v4)
        dump(v5, value)
        return v5

    def lineage_overlay_fixture(self, mutation: str | None = None) -> dict[str, object]:
        """Build only the four authorities required by the fixed April overlay."""
        date, kinds = "20260418", ("DE", "DG", "DS")
        raw = self.root / "data/raw/prediction_input"
        old_dg, _, _, _ = target_rows(date, [(number, f"old{number}") for number in range(1, 21)])
        obstacle = [""] * 11
        obstacle[0:5] = ["2026", "4", "18", "中山", "11"]
        obstacle[5:10] = ["中山グランドジャンプ", "障害", "障害", "4260", "10"]
        old_dg.append(obstacle)
        new_dg, _, _, _ = target_rows(date, [(number, f"new{number}") for number in range(1, 21)])
        old_paths = {"DG": raw / "DG260418.CSV", "DE": raw / "DE260418.CSV", "DS": raw / "DS260418.CSV"}
        new_paths = {"DG": raw / "DG260418v2.CSV", "DE": raw / "DE260418v2.CSV", "DS": raw / "DS260418v2.CSV"}
        write_csv(old_paths["DG"], old_dg)
        write_csv(new_paths["DG"], new_dg)
        for kind in ("DE", "DS"):
            old_paths[kind].parent.mkdir(parents=True, exist_ok=True)
            old_paths[kind].write_bytes(f"old-{kind}".encode())
            new_paths[kind].write_bytes(f"new-{kind}".encode())
        result_path = raw / "result.csv"; result_path.write_bytes(b"structural-only")
        old = {kind: {"path": str(path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(path)} for kind, path in old_paths.items()}
        corrected = {kind: {"path": str(path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(path)} for kind, path in new_paths.items()}
        data = self.root / "reports/ml_v4_buy_selection_dataset_v5"; data.mkdir(parents=True, exist_ok=True)
        manifest = {"sources": [{"date": date, "files": {**{kind: dict(value) for kind, value in old.items()}, "result_primary": {"path": str(result_path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(result_path)}}}, {"date": "20260419", "files": {**{kind: dict(value) for kind, value in old.items()}, "result_primary": {"path": str(result_path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(result_path)}}}], "additive_prediction_sources": [{"date": date, "prediction_root": "reports/pre/20260418"}, {"date": "20260419", "prediction_root": "reports/pre/20260419"}]}
        manifest_path = data / "source_date_manifest.json"; dump(manifest_path, manifest)
        active_path = self.root / "reports/april_2026_source_recovery_20260418_v1_completion_v1_recovery_v2/april_active_source_set_manifest.json"
        prediction_path = self.root / "reports/april_2026_retrospective_external_holdout_v2/pre_execution_full_8date_v1/prediction/20260418/input_manifest.json"
        recovery_path = self.root / "reports/april_2026_source_recovery_20260418_v1_completion_v1_recovery_v2/recovery_completion_status.json"
        dump(active_path, {"active_dates": [{"date": date, "source_version": "CORRECTED_PRE_SOURCE_VERSION", "sources": corrected}]})
        dump(prediction_path, {"date": date, "sources": corrected})
        dump(recovery_path, {"corrected_source_status": "CORRECTED_PRE_SOURCE_ACCEPTED", "active_source_set_manifest": str(active_path.relative_to(self.root)).replace("/", "\\")})
        record_path = self.root / "reports/ml_v4_buy_selection_dataset_v5_source_lineage_correction_20260418_v1/correction.json"
        correction = {"repair_type": "SOURCE_LINEAGE_INTEGRITY_REPAIR", "target_date": date, "scope": list(kinds), "corrected_role": "AUTHORITATIVE_APRIL_PRE_SOURCE", "old_sources": old, "corrected_sources": corrected, "authority_references": {"april_active_source_set_manifest": {"path": str(active_path.relative_to(self.root)).replace("\\", "/")}, "recovery_completion_status": {"path": str(recovery_path.relative_to(self.root)).replace("\\", "/")}, "frozen_prediction_input_manifest": {"path": str(prediction_path.relative_to(self.root)).replace("\\", "/")}}}

        def write_record() -> str:
            for value in correction["authority_references"].values():
                source = self.root / value["path"]
                value["sha256"] = digest(source)
            dump(record_path, correction)
            return digest(record_path)

        if mutation in {"old_dg", "old_de", "old_ds"}:
            kind = mutation.removeprefix("old_").upper()
            manifest["sources"][0]["files"][kind]["sha256"] = "0" * 64; dump(manifest_path, manifest)
        if mutation == "v2_actual_dg":
            new_paths["DG"].write_bytes(b"tampered-v2-dg")
        if mutation == "active_dg":
            active = json.loads(active_path.read_text(encoding="utf-8")); active["active_dates"][0]["sources"]["DG"]["sha256"] = "0" * 64; dump(active_path, active)
        if mutation == "prediction_dg":
            prediction = json.loads(prediction_path.read_text(encoding="utf-8")); prediction["sources"]["DG"]["sha256"] = "0" * 64; dump(prediction_path, prediction)
        if mutation == "partial_ds":
            active = json.loads(active_path.read_text(encoding="utf-8")); active["active_dates"][0]["sources"].pop("DS"); dump(active_path, active)
        return {"manifest": manifest_path, "record": record_path, "old": old, "corrected": corrected, "write_record": write_record}

    def corrected_sources(self, fixture: dict[str, object]) -> list[dict[str, object]]:
        digest_value = fixture["write_record"]()
        with patch("review.ws2_data_integrity_preflight_v2_source_bound.SOURCE_LINEAGE_CORRECTION_SHA256", digest_value):
            return self.materializer().source_manifest(self.root / "reports/ml_v4_buy_selection_dataset_v5")

    def known_exclusion_bridge_fixture(self, mutation: str | None = None) -> dict[str, object]:
        """Build exact 20260823 bridge authorities with no Result fixture."""
        date = "20260823"
        raw = self.root / "data/raw/prediction_input"
        dg, de, ds, _ = target_rows(date, [(7, "マインドフルネス"), (8, "remaining")])
        for row in dg:
            row[3] = "新潟"
        for row in de:
            row[1] = "新潟"
            row[32] = f"04fixture{int(row[2]):02d}{int(row[3]):02d}"
        de[0][3], de[0][18], de[0][32] = "6", "24103226", "04fixture0706"
        ds = [row for row in ds if row[16] != "マインドフルネス"]
        paths = {kind: raw / f"{kind}260823.CSV" for kind in ("DG", "DE", "DS")}
        for kind, rows in (("DG", dg), ("DE", de), ("DS", ds)):
            write_csv(paths[kind], rows)
        sources = {kind: {"path": str(path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(path)} for kind, path in paths.items()}
        excluded = {
            "race_id": "race_20260823_niigata_7R", "venue": "新潟", "race_number": 7,
            "affected_horse_number": 6, "affected_horse_name": "マインドフルネス",
            "reason": "DE_DS_HORSE_SET_MISMATCH", "reason_status": "SOURCE_DATA_INTEGRITY_UNRESOLVED",
            "evaluation_status": "NOT_EVALUATED", "authority": "HUMAN_TEMPORARY_RACE_LEVEL_EXCLUSION_20260823_ONLY",
        }
        exclusion_path = self.root / "reports/prospective_prediction_20260823_v1/exclusion_record.json"
        input_path = self.root / "reports/prospective_prediction_20260823_v1/input_manifest.json"
        provenance_path = self.root / "reports/prospective_prediction_20260823_v1/provenance.json"
        runner_path = self.root / "review/prospective_prediction_20260823_human_exclusion_runner.py"
        dump(exclusion_path, {"excluded_races": [excluded], "no_other_automatic_exclusion": True})
        dump(input_path, {"date": date, "sources": sources, "temporary_filtered_input": {"raw_modified": False, "exclusion": excluded}})
        dump(provenance_path, {"human_exclusion": excluded, "result_data_access_count": 0})
        runner_path.parent.mkdir(parents=True, exist_ok=True); runner_path.write_text("# date-specific fixture\n", encoding="utf-8")
        authorities = {
            "exclusion_record": {"path": str(exclusion_path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(exclusion_path), "role": "HUMAN_APPROVED_RACE_EXCLUSION_RECORD"},
            "input_manifest": {"path": str(input_path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(input_path), "role": "FROZEN_INPUT_PROVENANCE"},
            "provenance": {"path": str(provenance_path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(provenance_path), "role": "FROZEN_PRE_RUN_PROVENANCE"},
            "historical_runner": {"path": str(runner_path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(runner_path), "role": "DATE_SPECIFIC_TEMPORARY_FILTER_IMPLEMENTATION"},
        }
        record = {
            "schema_version": "ws2_known_data_integrity_exclusion_bridge_20260823_v1",
            "bridge_type": "KNOWN_HUMAN_APPROVED_DATE_SPECIFIC_RACE_EXCLUSION",
            "role": "HUMAN_APPROVED_DATE_SPECIFIC_RACE_LEVEL_EXCLUSION",
            "target_date": date,
            "target_race": {"race_id": "race_20260823_niigata_7R", "venue": "新潟", "race_number": 7},
            "affected_horse": {"horse_number": 6, "horse_name": "マインドフルネス", "registration_id": "24103226"},
            "reason": "DE_DS_HORSE_SET_MISMATCH", "reason_status": "SOURCE_DATA_INTEGRITY_UNRESOLVED",
            "approval_basis": "ZERO_HISTORY_HORSE_PRE_RESULT_RACE_EXCLUSION", "exclusion_scope": "WHOLE_RACE",
            "generalizable": False, "adapter_validation_rule_changed": False, "population_rule_changed": False,
            "raw_source_modified": False, "prior_authorities": authorities, "current_raw_sources": sources,
        }
        record_path = self.root / "reports/ws2_known_data_integrity_exclusion_bridge_20260823_v1/exclusion_bridge.json"
        if mutation == "record_schema":
            record["exclusion_scope"] = "HORSE"
        if mutation == "authority_content":
            dump(exclusion_path, {"excluded_races": [], "no_other_automatic_exclusion": True})
        if mutation == "de_source":
            paths["DE"].write_bytes(paths["DE"].read_bytes() + b"\r\n")
        if mutation == "ds_present":
            restored = target_rows(date, [(7, "マインドフルネス")])[2][0]
            restored[4] = "新潟"; ds.append(restored); write_csv(paths["DS"], ds)
        if mutation == "de_identity":
            de[0][18] = "99999999"; write_csv(paths["DE"], de)
        dump(record_path, record)
        return {"record": record_path, "record_sha": digest(record_path), "files": sources, "paths": paths}

    def load_known_exclusion_bridge(self, fixture: dict[str, object]) -> dict[str, object]:
        with patch("review.ws2_data_integrity_preflight_v2_source_bound.KNOWN_EXCLUSION_BRIDGE_SHA256", fixture["record_sha"]):
            bridge = self.materializer()._known_data_integrity_exclusion_bridge("20260823", fixture["files"])
        # The fixture dynamically pins its local record only for authentication.
        # Exercise the runtime scope guard with the production constant it would
        # receive after that authentication succeeds.
        bridge["bridge_sha256"] = "c905411baf3499647a57a77ed21ad996ba3051d0c644f025c263f8726ff0fd3a"
        return bridge

    def existing_adapter_reuse_fixture(self, mutation: str | None = None) -> dict[str, object]:
        """Build only the frozen authority needed to opt in to Adapter 9/6."""
        date, name, short = "20260906", "ファストネットワーク", "ファストネットワー"
        raw = self.root / "data/raw/prediction_input"
        dg, de, ds, _ = target_rows(date, [(11, name)])
        dg[0][3] = "阪神"
        de[0][1], de[0][2], de[0][3], de[0][7], de[0][18], de[0][32] = "阪神", "11", "8", name, "20190007", "09fixture1108"
        ds[0][4], ds[0][16], ds[0][17], ds[0][46] = "阪神", short, de[0][8], de[0][20]
        paths = {kind: raw / f"{kind}260906.CSV" for kind in ("DG", "DE", "DS")}
        for kind, rows in (("DG", dg), ("DE", de), ("DS", ds)):
            write_csv(paths[kind], rows)
        sources = {kind: {"path": str(path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(path)} for kind, path in paths.items()}
        required = {"state": "HUMAN_APPROVED_EXACT_COMPATIBILITY_MAPPING", "mapping_count": 1, "scope": "2026-09-06 / hanshin11R / exact-name-pair-only", "source_sha_guard": "PASS", "exact_scope_guard": "PASS", "general_truncation_rule": "REJECT", "de_exact_name": name, "ds_exact_name": short}
        input_path = self.root / "reports/prospective_prediction_20260906_v1/input_manifest.json"
        prediction_path = self.root / "reports/prospective_prediction_20260906_v1/prediction_manifest.json"
        adapter_path = self.root / "review/target_bulk_prediction_input_adapter_v1.py"
        dump(input_path, {"date": date, "input_exception": required, "sources": sources})
        dump(prediction_path, {"files": [{"relative_path": "input_manifest.json", "sha256": digest(input_path)}]})
        adapter_path.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / "review/target_bulk_prediction_input_adapter_v1.py", adapter_path)
        authorities = {
            "prediction_manifest": {"path": str(prediction_path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(prediction_path)},
            "input_manifest": {"path": str(input_path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(input_path)},
            "adapter_implementation": {"path": str(adapter_path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(adapter_path)},
        }
        record = {"schema_version": "ws2_existing_adapter_compatibility_reuse_20260906_v1", "reuse_type": "EXISTING_ADAPTER_AUTHORITY", "role": "PREVIOUSLY_APPROVED_COMPATIBILITY_MAPPING_REUSE", "target_date": date, "adapter_exception_constant": "HUMAN_APPROVED_20260906_EXACT_EXCEPTION", "adapter_change_required": False, "whole_race_exclusion_required": False, "general_normalization_rule_change": False, "target_scope": {"race_id": "race_20260906_hanshin_11R", "venue": "阪神", "race_number": 11, "horse_number": 8, "de_horse_name": name, "ds_horse_name": short, "registration_id": "20190007", "scope": required["scope"]}, "required_input_exception": required, "frozen_authorities": authorities, "current_raw_sources": sources}
        if mutation == "record_scope": record["target_scope"]["race_number"] = 10
        if mutation == "input_state":
            altered = json.loads(input_path.read_text(encoding="utf-8")); altered["input_exception"]["state"] = "OTHER"; dump(input_path, altered); authorities["input_manifest"]["sha256"] = digest(input_path); dump(prediction_path, {"files": [{"relative_path": "input_manifest.json", "sha256": digest(input_path)}]}); authorities["prediction_manifest"]["sha256"] = digest(prediction_path)
        if mutation == "input_sha":
            input_path.write_text(input_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        if mutation == "dg_sha": paths["DG"].write_bytes(paths["DG"].read_bytes() + b"\r\n")
        if mutation == "de_sha": paths["DE"].write_bytes(paths["DE"].read_bytes() + b"\r\n")
        if mutation == "ds_sha": paths["DS"].write_bytes(paths["DS"].read_bytes() + b"\r\n")
        record_path = self.root / "reports/ws2_existing_adapter_compatibility_reuse_20260906_v1/compatibility_reuse.json"
        dump(record_path, record)
        return {"record": record_path, "record_sha": digest(record_path), "files": sources, "paths": paths, "required": required}

    def load_existing_adapter_reuse(self, fixture: dict[str, object]) -> dict[str, object]:
        with patch("review.ws2_data_integrity_preflight_v2_source_bound.KNOWN_ADAPTER_COMPATIBILITY_REUSE_SHA256", fixture["record_sha"]):
            return self.materializer()._existing_adapter_compatibility_reuse("20260906", fixture["files"])

    def _canonical_test_source_lineage_overlay_applies_only_all_three_verified_sources(self) -> None:
        fixture = self.lineage_overlay_fixture()
        sources = self.corrected_sources(fixture)
        april = next(item for item in sources if item["date"] == "20260418")
        self.assertEqual(april["files"], fixture["corrected"] | {"result_primary": april["files"]["result_primary"]})
        self.assertEqual(april["source_lineage_overlay"]["scope"], ["DE", "DG", "DS"])

    def _canonical_test_source_lineage_overlay_rejects_old_dg_mismatch(self) -> None:
        fixture = self.lineage_overlay_fixture("old_dg")
        with self.assertRaisesRegex(DataIntegrityStop, "DG_OLD_SHA_MISMATCH"):
            self.corrected_sources(fixture)

    def _canonical_test_source_lineage_overlay_rejects_old_de_mismatch(self) -> None:
        fixture = self.lineage_overlay_fixture("old_de")
        with self.assertRaisesRegex(DataIntegrityStop, "DE_OLD_SHA_MISMATCH"):
            self.corrected_sources(fixture)

    def _canonical_test_source_lineage_overlay_rejects_old_ds_mismatch(self) -> None:
        fixture = self.lineage_overlay_fixture("old_ds")
        with self.assertRaisesRegex(DataIntegrityStop, "DS_OLD_SHA_MISMATCH"):
            self.corrected_sources(fixture)

    def _canonical_test_source_lineage_overlay_rejects_v2_actual_mismatch(self) -> None:
        fixture = self.lineage_overlay_fixture("v2_actual_dg")
        with self.assertRaisesRegex(DataIntegrityStop, "DG_V2_ACTUAL_SHA_MISMATCH"):
            self.corrected_sources(fixture)

    def _canonical_test_source_lineage_overlay_rejects_active_authority_mismatch(self) -> None:
        fixture = self.lineage_overlay_fixture("active_dg")
        with self.assertRaisesRegex(DataIntegrityStop, "DG_ACTIVE_SOURCE_MISMATCH"):
            self.corrected_sources(fixture)

    def _canonical_test_source_lineage_overlay_rejects_prediction_authority_mismatch(self) -> None:
        fixture = self.lineage_overlay_fixture("prediction_dg")
        with self.assertRaisesRegex(DataIntegrityStop, "DG_PREDICTION_INPUT_MISMATCH"):
            self.corrected_sources(fixture)

    def _canonical_test_source_lineage_overlay_rejects_partial_three_source_validation(self) -> None:
        fixture = self.lineage_overlay_fixture("partial_ds")
        with self.assertRaisesRegex(DataIntegrityStop, "DS_ACTIVE_SOURCE_MISMATCH"):
            self.corrected_sources(fixture)

    def _canonical_test_source_lineage_overlay_rejects_record_tamper(self) -> None:
        fixture = self.lineage_overlay_fixture()
        original = fixture["write_record"]()
        fixture["record"].write_text(fixture["record"].read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with patch("review.ws2_data_integrity_preflight_v2_source_bound.SOURCE_LINEAGE_CORRECTION_SHA256", original):
            with self.assertRaisesRegex(DataIntegrityStop, "CORRECTION_RECORD_HASH_MISMATCH"):
                self.materializer().source_manifest(self.root / "reports/ml_v4_buy_selection_dataset_v5")

    def _canonical_test_source_lineage_overlay_leaves_other_dates_unchanged(self) -> None:
        fixture = self.lineage_overlay_fixture()
        sources = self.corrected_sources(fixture)
        other = next(item for item in sources if item["date"] == "20260419")
        self.assertIsNone(other["source_lineage_overlay"])
        self.assertEqual(other["files"]["DG"], fixture["old"]["DG"])

    def _canonical_test_source_lineage_overlay_uses_corrected_dg_without_obstacle_row(self) -> None:
        fixture = self.lineage_overlay_fixture()
        sources = self.corrected_sources(fixture)
        april = next(item for item in sources if item["date"] == "20260418")
        dg = self.root / april["files"]["DG"]["path"]
        with dg.open("r", encoding="cp932", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(len(rows), 20)
        self.assertNotIn("障害", {row[7] for row in rows})

    def _canonical_test_known_exclusion_bridge_applies_exactly_one_authenticated_race(self) -> None:
        fixture = self.known_exclusion_bridge_fixture()
        bridge = self.load_known_exclusion_bridge(fixture)
        self.assertEqual(bridge["race_id"], "race_20260823_niigata_7R")
        self.assertEqual(bridge["excluded_horse_names"], ["マインドフルネス"])

    def _canonical_test_known_exclusion_bridge_is_not_discovered_for_any_other_date(self) -> None:
        fixture = self.known_exclusion_bridge_fixture()
        with patch("review.ws2_data_integrity_preflight_v2_source_bound.KNOWN_EXCLUSION_BRIDGE_SHA256", fixture["record_sha"]):
            self.assertIsNone(self.materializer()._known_data_integrity_exclusion_bridge("20260824", fixture["files"]))

    def _canonical_test_known_exclusion_bridge_rejects_non_whole_race_record(self) -> None:
        fixture = self.known_exclusion_bridge_fixture("record_schema")
        with self.assertRaisesRegex(DataIntegrityStop, "BRIDGE_RECORD_SCHEMA"):
            self.load_known_exclusion_bridge(fixture)

    def _canonical_test_known_exclusion_bridge_rejects_authority_mutation(self) -> None:
        fixture = self.known_exclusion_bridge_fixture("authority_content")
        with self.assertRaisesRegex(DataIntegrityStop, "BRIDGE_AUTHORITY_HASH_MISMATCH"):
            self.load_known_exclusion_bridge(fixture)

    def _canonical_test_known_exclusion_bridge_rejects_current_de_source_mutation(self) -> None:
        fixture = self.known_exclusion_bridge_fixture("de_source")
        with self.assertRaisesRegex(DataIntegrityStop, "BRIDGE_DE_SOURCE_HASH_MISMATCH"):
            self.load_known_exclusion_bridge(fixture)

    def _canonical_test_known_exclusion_bridge_rejects_when_ds_now_contains_affected_horse(self) -> None:
        fixture = self.known_exclusion_bridge_fixture("ds_present")
        with self.assertRaisesRegex(DataIntegrityStop, "BRIDGE_DS_SOURCE_HASH_MISMATCH"):
            self.load_known_exclusion_bridge(fixture)

    def _canonical_test_known_exclusion_bridge_rejects_de_identity_drift(self) -> None:
        fixture = self.known_exclusion_bridge_fixture("de_identity")
        with self.assertRaisesRegex(DataIntegrityStop, "BRIDGE_DE_SOURCE_HASH_MISMATCH"):
            self.load_known_exclusion_bridge(fixture)

    def _canonical_test_known_exclusion_bridge_uses_unchanged_adapter_after_full_race_filter(self) -> None:
        fixture = self.known_exclusion_bridge_fixture()
        bridge = self.load_known_exclusion_bridge(fixture)
        source_hashes = {kind: digest(path) for kind, path in fixture["paths"].items()}
        paths = {kind: self.root / value["path"] for kind, value in fixture["files"].items()}
        bundle = self.materializer()._load_with_known_whole_race_exclusion(paths, bridge)
        self.assertEqual(set(bundle.races), {"race_20260823_niigata_8R"})
        self.assertEqual(sum(len(race.today_entries) for race in bundle.races.values()), 1)
        self.assertEqual(source_hashes, {kind: digest(path) for kind, path in fixture["paths"].items()})

    def _canonical_test_known_exclusion_bridge_does_not_filter_an_unrelated_remaining_mismatch(self) -> None:
        fixture = self.known_exclusion_bridge_fixture()
        ds_path = fixture["paths"]["DS"]
        unrelated = [""] * 50
        unrelated[0:3] = ["25", "1", "1"]
        unrelated[4], unrelated[6], unrelated[8], unrelated[12], unrelated[14], unrelated[15], unrelated[16], unrelated[21], unrelated[23] = "新潟", "1", "1勝", "芝", "1600", "良", "unrelated", "1", "1"
        write_csv(ds_path, [unrelated])
        with self.assertRaisesRegex(DataIntegrityStop, "BRIDGE_DS_SOURCE_HASH_MISMATCH"):
            self.load_known_exclusion_bridge(fixture)

    def _canonical_test_known_exclusion_bridge_filtered_workspace_is_removed(self) -> None:
        fixture = self.known_exclusion_bridge_fixture()
        bridge = self.load_known_exclusion_bridge(fixture)
        paths = {kind: self.root / value["path"] for kind, value in fixture["files"].items()}
        self.materializer()._load_with_known_whole_race_exclusion(paths, bridge)
        sandbox_parent = self.root / ".tmp"
        self.assertFalse(sandbox_parent.exists() and any(sandbox_parent.iterdir()))

    def _canonical_test_existing_adapter_reuse_authenticates_exact_frozen_authority(self) -> None:
        fixture = self.existing_adapter_reuse_fixture()
        reuse = self.load_existing_adapter_reuse(fixture)
        self.assertEqual(reuse["race_id"], "race_20260906_hanshin_11R")
        self.assertEqual(reuse["required_input_exception"], fixture["required"])

    def _canonical_test_existing_adapter_reuse_rejects_frozen_input_manifest_hash_mismatch(self) -> None:
        fixture = self.existing_adapter_reuse_fixture("input_sha")
        with self.assertRaisesRegex(DataIntegrityStop, "REUSE_AUTHORITY_HASH_MISMATCH"):
            self.load_existing_adapter_reuse(fixture)

    def _canonical_test_existing_adapter_reuse_rejects_input_exception_state_mismatch(self) -> None:
        fixture = self.existing_adapter_reuse_fixture("input_state")
        with self.assertRaisesRegex(DataIntegrityStop, "REUSE_INPUT_EXCEPTION_MISMATCH"):
            self.load_existing_adapter_reuse(fixture)

    def _canonical_test_existing_adapter_reuse_rejects_scope_mismatch(self) -> None:
        fixture = self.existing_adapter_reuse_fixture("record_scope")
        with self.assertRaisesRegex(DataIntegrityStop, "REUSE_RECORD_SCHEMA"):
            self.load_existing_adapter_reuse(fixture)

    def _canonical_test_existing_adapter_reuse_rejects_dg_source_mismatch(self) -> None:
        fixture = self.existing_adapter_reuse_fixture("dg_sha")
        with self.assertRaisesRegex(DataIntegrityStop, "REUSE_DG_SOURCE_HASH_MISMATCH"):
            self.load_existing_adapter_reuse(fixture)

    def _canonical_test_existing_adapter_reuse_rejects_de_source_mismatch(self) -> None:
        fixture = self.existing_adapter_reuse_fixture("de_sha")
        with self.assertRaisesRegex(DataIntegrityStop, "REUSE_DE_SOURCE_HASH_MISMATCH"):
            self.load_existing_adapter_reuse(fixture)

    def _canonical_test_existing_adapter_reuse_rejects_ds_source_mismatch(self) -> None:
        fixture = self.existing_adapter_reuse_fixture("ds_sha")
        with self.assertRaisesRegex(DataIntegrityStop, "REUSE_DS_SOURCE_HASH_MISMATCH"):
            self.load_existing_adapter_reuse(fixture)

    def _canonical_test_existing_adapter_reuse_is_not_available_for_a_different_date(self) -> None:
        fixture = self.existing_adapter_reuse_fixture()
        with patch("review.ws2_data_integrity_preflight_v2_source_bound.KNOWN_ADAPTER_COMPATIBILITY_REUSE_SHA256", fixture["record_sha"]):
            self.assertIsNone(self.materializer()._existing_adapter_compatibility_reuse("20260907", fixture["files"]))

    def _canonical_test_existing_adapter_reuse_propagates_adapter_input_exception(self) -> None:
        fixture = self.existing_adapter_reuse_fixture()
        reuse = self.load_existing_adapter_reuse(fixture)
        source = {"files": fixture["files"], "known_data_integrity_exclusion_bridge": None, "existing_adapter_compatibility_reuse": reuse}
        from review import target_bulk_prediction_input_adapter_v1 as adapter_module
        with patch.object(adapter_module, "HUMAN_APPROVED_20260906_SOURCE_SHA256", {kind: value["sha256"] for kind, value in fixture["files"].items()}):
            bundle = self.materializer().target_prediction_bundle(source)
        self.assertEqual(bundle.preflight["input_exception"], fixture["required"])

    def _canonical_test_generic_similar_truncation_on_another_date_remains_fail_closed(self) -> None:
        fixture = self.existing_adapter_reuse_fixture()
        de_path, ds_path = fixture["paths"]["DE"], fixture["paths"]["DS"]
        de_rows = list(csv.reader(de_path.read_bytes().decode("cp932").splitlines()))
        ds_rows = list(csv.reader(ds_path.read_bytes().decode("cp932").splitlines()))
        for row in de_rows: row[0] = "260907"
        for row in ds_rows: row[0:3] = ["25", "1", "1"]
        other_dg = fixture["paths"]["DG"].with_name("DG260907.CSV")
        other_de, other_ds = de_path.with_name("DE260907.CSV"), ds_path.with_name("DS260907.CSV")
        dg_rows = list(csv.reader(fixture["paths"]["DG"].read_bytes().decode("cp932").splitlines()))
        for row in dg_rows: row[0:3] = ["2026", "9", "7"]
        write_csv(other_dg, dg_rows); write_csv(other_de, de_rows); write_csv(other_ds, ds_rows)
        from review.target_bulk_prediction_input_adapter_v1 import PredictionInputValidationError, TargetBulkPredictionInputAdapterV1
        with self.assertRaisesRegex(PredictionInputValidationError, "DE_DS_HORSE_SET_MISMATCH"):
            TargetBulkPredictionInputAdapterV1().load(other_dg, other_de, other_ds)

    def _canonical_test_existing_adapter_reuse_pins_adapter_implementation_identity(self) -> None:
        fixture = self.existing_adapter_reuse_fixture()
        reuse = self.load_existing_adapter_reuse(fixture)
        self.assertEqual(reuse["adapter_implementation_sha256"], digest(ROOT / "review/target_bulk_prediction_input_adapter_v1.py"))

    def _canonical_test_existing_adapter_reuse_remains_separate_from_20260823_bridge(self) -> None:
        fixture = self.known_exclusion_bridge_fixture()
        bridge = self.load_known_exclusion_bridge(fixture)
        self.assertEqual(bridge["role"], "HUMAN_APPROVED_DATE_SPECIFIC_RACE_LEVEL_EXCLUSION")

    def e2e_fixture(self, mutation: str | None = None) -> None:
        """Minimal actual-shape repository: direct A/D, inherited C, raw-only B."""
        data = self.root / "reports/ml_v4_buy_selection_dataset_v5_1"; model = self.root / "reports/ml_v4_buy_selection_model_v5"
        data.mkdir(parents=True, exist_ok=True)
        date_a, date_c = "20260401", "20260501"
        artifacts = {}
        for date, races in ((date_a, [(1, "A"), (2, "D")]), (date_c, [(1, "C")])):
            root = self.root / "reports/pre" / date; root.mkdir(parents=True)
            files = []
            for number, horse in races:
                value = trace_race(); value["race_id"] = f"race_{date}_tokyo_{number}R"; value["buy_gate_trace"]["horses"][0]["horse_number"] = 1; value["ranked_results"][0]["horse_number"] = 1; value["ranked_results"][0]["horse_name"] = horse
                path = root / f"race_{date}_tokyo_{number}R_prediction.json"; dump(path, value); files.append({"relative_path": path.name, "sha256": digest(path)}); artifacts[(date, number)] = path
            # These are authentic manifest members but never race payloads.
            non_race = {
                "input_manifest.json": {"date": date},
                "provenance.json": {"fixture": True},
                "race_index.json": {"race_index": [{"race_id": f"race_{date}_tokyo_{number}R", "artifact": f"race_{date}_tokyo_{number}R_prediction.json"} for number, _ in races]},
                "exclusion_record.json": {"automatic_exclusions": ([{"race_id": f"race_{date}_tokyo_3R", "reason": "FIXTURE_SCOPE_EXCLUSION"}] if date == date_a else [])},
            }
            for name, value in non_race.items():
                dump(root / name, value); files.append({"relative_path": name, "sha256": digest(root / name)})
            (root / "report.md").write_text("fixture\n", encoding="utf-8"); files.append({"relative_path": "report.md", "sha256": digest(root / "report.md")})
            dump(root / "prediction_manifest.json", {"files": files})
        source_entries = []
        for date, races in ((date_a, [(1, "A"), (2, "D"), (3, "B")]), (date_c, [(1, "C")])):
            raw = self.root / "raw" / date; dg, de, ds, result = target_rows(date, races)
            paths = {"DG": raw / "DG.CSV", "DE": raw / "DE.CSV", "DS": raw / "DS.CSV", "result_primary": raw / "result.csv"}
            if mutation == "de_horse_mismatch" and date == date_a:
                de[0][3] = "2"
                de[0][32] = f"05{date[2:6]}0102"
            for key, rows in (("DG", dg), ("DE", de), ("DS", ds), ("result_primary", result)): write_csv(paths[key], rows)
            if mutation == "future_ds" and date == date_a: ds[0][0:3] = ["26", "4", "1"]; write_csv(paths["DS"], ds)
            source_entries.append({"date": date, "source_races": len(races), "files": {key: {"path": str(path.relative_to(self.root)).replace("\\", "/"), "sha256": digest(path)} for key, path in paths.items()}})
        rows = []
        for date, number in ((date_a, 1), (date_c, 1)):
            artifact = artifacts[(date, number)]; obj = json.loads(artifact.read_text(encoding="utf-8")); gate, ranked = obj["buy_gate_trace"]["horses"][0], obj["ranked_results"][0]
            row = {key: "" for key in ACTUAL_HEADER}; row.update({"row_id": date, "date": date, "race_id": obj["race_id"], "target_race_key": f"{date}{number:08d}", "horse_number": "1", "horse_name": ranked["horse_name"], "current_buy": "false", "current_top5": "true", "actual_top3": "1", "actual_finish": "1", "valid_result": "true", "source_prediction_artifact_path": str(artifact.relative_to(self.root)).replace("\\", "/"), "source_prediction_artifact_sha256": digest(artifact), "source_result_artifact_path": "raw/result.csv", "source_result_artifact_sha256": "x", "source_block": "fixture", "evidence_role_note": "TRAINING", "dataset_version": "v5", "split_role": "TRAINING"})
            for key in POLICY["required_v5_features"]:
                value = gate.get(key, ranked.get(key, gate.get("evaluator_score_snapshot", {}).get(key)))
                if key == "consensus_positive_count": value = gate["positive_count"]
                if key == "consensus_negative_count": value = gate["negative_count"]
                if key == "adjusted_score_gap_to_top": value = 0
                if key == "race_state": value = ranked["buy_v1_rc1_race_state"]
                row[key] = str(value)
            rows.append(row)
        if mutation == "feature_value": rows[0]["Ability"] = "999"
        if mutation == "label_mismatch": rows[0]["actual_top3"] = "0"
        if mutation == "missing_parent": rows[1]["source_prediction_artifact_path"] = ""
        with (data / "dataset.csv").open("w", encoding="utf-8", newline="") as handle: writer = csv.DictWriter(handle, fieldnames=ACTUAL_HEADER); writer.writeheader(); writer.writerows(rows)
        dump(data / "feature_schema.json", {"dataset_version": "ML_V4_TRAIN_DATASET_V5_1_CORRECTED", "semantic_feature_order": POLICY["required_v5_features"]}); dump(data / "training_manifest.json", {"dataset_sha256": digest(data / "dataset.csv"), "feature_count": 21})
        additive = [{"date": date_a, "prediction_root": "reports/pre/20260401"}]
        dump(data / "source_date_manifest.json", {"sources": source_entries, "additive_prediction_sources": additive})
        dump(data / "exclusion_manifest.json", {"integrity_excluded_source_races": [{"race_id": "race_20260401_tokyo_2R", "reason": "FIXTURE_EXCLUSION"}]})
        dump(data / "lineage.json", {"parent": "ML_V4_TRAIN_DATASET_V4", "february_prior_role": "TRAINING"})
        dump(data / "dataset_manifest.json", {"dataset_version": "ML_V4_TRAIN_DATASET_V5_1_CORRECTED", "dataset_sha256": digest(data / "dataset.csv"), "row_count": len(rows), "feature_count": 21})
        index(data, ["dataset.csv", "dataset_manifest.json", "feature_schema.json", "training_manifest.json", "source_date_manifest.json", "exclusion_manifest.json", "lineage.json"])
        parent = self.root / "reports/ml_v4_buy_selection_dataset_v4"; dump(parent / "lineage.json", {})
        (model / "model.joblib").parent.mkdir(parents=True, exist_ok=True); (model / "model.joblib").write_bytes(b"m"); (model / "scaler.joblib").write_bytes(b"s")
        regeneration = {} if mutation == "missing_regeneration_identity" else {"code_sha256": "c" * 64, "knowledge_snapshot_sha256": "k" * 64}
        dump(model / "model_metadata.json", {"model_sha256": digest(model / "model.joblib"), "scaler_sha256": digest(model / "scaler.joblib"), "training_population": "v5"}); dump(model / "training_manifest.json", {"dataset_sha256": digest(data / "dataset.csv"), "feature_count": 21, "regeneration_identity": regeneration}); dump(model / "training_recipe.json", {"C": 1, "base_recipe": "v4", "class_weight": None, "penalty": "l2", "pipeline": ["StandardScaler", "LogisticRegression"], "solver": "lbfgs"}); dump(model / "deterministic_reproduction.json", {"status": "PASS"}); dump(model / "activation_record.json", {}); dump(model / "runtime_environment.json", {"python": "fixture"}); index(model, ["model.joblib", "scaler.joblib", "model_metadata.json", "training_manifest.json", "training_recipe.json", "deterministic_reproduction.json", "runtime_environment.json"])
        authority = self.root / "reports/ws2_model_activation_authority_v1/activation_record_authority.json"
        dump(authority, {"activation_record": {"path": "reports/ml_v4_buy_selection_model_v5/activation_record.json", "sha256": digest(model / "activation_record.json"), "included_in_frozen_model_hash_index": False}, "validation_authority": "INDEPENDENT_SHA_PINNED_EVIDENCE", "authority_evidence": []})
        policy_v4 = self.root / "docs/ws2_v5_feature_source_policy_v4.json"; value = json.loads(policy_v4.read_text(encoding="utf-8")); value["model_activation_record_authority_sha256"] = digest(authority); dump(policy_v4, value)
        role_c = "PROSPECTIVE" if mutation == "protected_role" else "TRAINING"
        dump(self.root / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json", {"authoritative_additive_entries": [{"month": "202604", "evidence_role": "TRAINING"}, {"month": "202605", "evidence_role": role_c}]})
        for relative in ("engine/decision_engine.py", "engine/race_decision_engine.py", "analyzer/score_calculator.py"):
            body = "X=1\n"
            if mutation == "learning_string": body = 'open("learning/improvement_candidates.json")\n'
            if mutation == "variable_knowledge_path": body = 'from pathlib import Path\nBASE = Path("knowledge")\nvalue = BASE / name\n'
            if mutation == "dynamic_import": body = 'import importlib\nimportlib.import_module(name)\n'
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(body, encoding="utf-8")
        if mutation in {"learning_string", "variable_knowledge_path", "dynamic_import"}:
            scanned = self.root / "review/target_bulk_prediction_input_shadow_v1.py"
            extra = {
                "learning_string": 'open("learning/improvement_candidates.json")\n',
                "variable_knowledge_path": 'from pathlib import Path\nBASE = Path("knowledge")\nvalue = BASE / name\n',
                "dynamic_import": 'import importlib\nimportlib.import_module(name)\n',
            }[mutation]
            scanned.write_text(scanned.read_text(encoding="utf-8") + "\n" + extra, encoding="utf-8")
        if mutation == "artifact_tamper":
            artifacts[(date_a, 1)].write_text("{}\n", encoding="utf-8")

    def run_fixture_preflight(self) -> Path:
        """Run a minimal V5.1-pinned fixture without relaxing production pins."""
        data = self.root / "reports/ml_v4_buy_selection_dataset_v5_1"
        policy_path = self.refresh_policy_v5_overlay()
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["canonical_dataset_identity"] = {
            "path": "reports/ml_v4_buy_selection_dataset_v5_1",
            "dataset_csv_sha256": digest(data / "dataset.csv"),
            "dataset_manifest_sha256": digest(data / "dataset_manifest.json"),
            "artifact_hash_index_sha256": digest(data / "artifact_hash_index.json"),
            "dataset_version": "ML_V4_TRAIN_DATASET_V5_1_CORRECTED",
            "row_count": 2,
            "feature_count": 21,
        }
        dump(policy_path, policy)
        with patch.multiple(
            source_bound,
            POLICY_SHA256=digest(policy_path),
            CONTRACT_SHA256=digest(self.root / "docs/ws2_data_integrity_preflight_v2_contract_revision_10.json"),
            CANONICAL_DATASET_CSV_SHA256=digest(data / "dataset.csv"),
            CANONICAL_DATASET_MANIFEST_SHA256=digest(data / "dataset_manifest.json"),
            CANONICAL_DATASET_HASH_INDEX_SHA256=digest(data / "artifact_hash_index.json"),
            CANONICAL_DATASET_ROW_COUNT=2,
        ):
            return run_preflight(self.root, self.root / "out")

class CanonicalFormatTests(SourceBoundFixtureMixin, unittest.TestCase):
    def test_a_actual_41_column_header_is_registered(self) -> None:
        classified = _columns(POLICY, ACTUAL_HEADER)
        self.assertEqual(len(classified), 41)

    def test_b_policy_only_forbidden_patterns_need_not_be_columns(self) -> None:
        self.assertNotIn("payout", ACTUAL_HEADER)
        self.assertEqual(len(_columns(POLICY, ACTUAL_HEADER)), 41)

    def test_c_actual_source_manifest_discovers_additive_prediction_root(self) -> None:
        root = self.root / "reports/ml_v4_buy_selection_dataset_v5"
        dump(root / "source_date_manifest.json", {"additive_prediction_sources": [{"date": "20260401", "prediction_root": "reports/pre/20260401"}], "sources": [{"date": "20260401", "files": {key: {"path": "raw/x", "sha256": "a"*64} for key in ("DG", "DE", "DS", "result_primary")}}]})
        self.assertEqual(self.materializer().source_manifest(root)[0]["prediction_root"], "reports/pre/20260401")

    def test_d_e_actual_race_prediction_trace_and_snapshot_materialize(self) -> None:
        rows, races = materialize_prediction_rows([trace_race()], "20260401")
        values = rows[("race_20260401_tokyo_1R", "1")]["values"]
        self.assertEqual(races, {"race_20260401_tokyo_1R"})
        self.assertEqual(values["Ability"], 1.0)
        self.assertEqual(values["decision_score"], 1.0)

    def test_adjusted_gap_uses_horse_minus_top_and_rejects_reverse_sign(self) -> None:
        artifact = trace_race()
        artifact["buy_gate_trace"]["horses"][0]["adjusted_score"] = 5.0
        artifact["ranked_results"][0]["adjusted_score"] = 5.0
        second_trace = dict(artifact["buy_gate_trace"]["horses"][0]); second_trace["horse_number"] = 2; second_trace["adjusted_score"] = 4.2
        second_ranked = dict(artifact["ranked_results"][0]); second_ranked.update({"horse_number": 2, "horse_name": "below", "rank": 2, "adjusted_score": 4.2})
        artifact["buy_gate_trace"]["horses"].append(second_trace); artifact["ranked_results"].append(second_ranked)
        values, _ = materialize_prediction_rows([artifact], "20260401")
        self.assertAlmostEqual(values[(artifact["race_id"], "2")]["values"]["adjusted_score_gap_to_top"], -0.8)
        self.assertNotEqual(values[(artifact["race_id"], "2")]["values"]["adjusted_score_gap_to_top"], 0.8)

    def test_adjusted_gap_uses_current_top5_not_a_higher_full_field_horse(self) -> None:
        artifact = trace_race()
        outside_trace = dict(artifact["buy_gate_trace"]["horses"][0]); outside_trace.update({"horse_number": 6, "adjusted_score": 99.0})
        outside_ranked = dict(artifact["ranked_results"][0]); outside_ranked.update({"horse_number": 6, "horse_name": "outside", "rank": 6, "adjusted_score": 99.0})
        artifact["buy_gate_trace"]["horses"].append(outside_trace)
        artifact["ranked_results"].append(outside_ranked)
        values, _ = materialize_prediction_rows([artifact], "20260401")
        self.assertEqual(values[(artifact["race_id"], "1")]["values"]["adjusted_score_gap_to_top"], 0.0)

    def test_rolling_origin_valid_minimum_and_rejections(self) -> None:
        valid = rolling_origin_folds({"202601": ["TRAINING"], "202602": ["TRAINING"], "202603": ["TRAINING"], "202604": ["TRAINING"]})
        self.assertEqual(valid["status"], "PASS")
        self.assertEqual(valid["folds"][0]["train_months"], ["202601", "202602", "202603"])
        short = rolling_origin_folds({"202601": ["TRAINING"], "202602": ["TRAINING"], "202603": ["TRAINING"]})
        self.assertEqual(short["status"], "NO_VALID_FOLD")
        protected = rolling_origin_folds({"202601": ["TRAINING"], "202602": ["TRAINING"], "202603": ["TRAINING"], "202604": ["PROSPECTIVE"]})
        self.assertEqual(protected["rejected"][-1]["exclusion_reason"], "PROTECTED_VALIDATION_MONTH")

    def test_f_g_target_shape_is_delegated_to_existing_parser(self) -> None:
        # Fixed-width headerless DG/DE/DS validation comes from the existing
        # TARGET adapter; this test deliberately does not create English CSV.
        from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
        adapter = TargetBulkPredictionInputAdapterV1()
        adapter._read_fixed_rows_for_test([["0"] * 11], "DG")
        adapter._read_fixed_rows_for_test([["0"] * 33], "DE")
        adapter._read_fixed_rows_for_test([["0"] * 50], "DS")

    def test_h_result_shape_is_delegated_to_existing_parser(self) -> None:
        raw = self.root / "result.csv"
        row = ["2026040100000001", "東京", "1", "fixture", "", "", "", "", "", "1", "", "", "1"]
        raw.write_text(",".join(row)+"\n", encoding="cp932")
        source = {"date": "20260401", "files": {"result_primary": {"path": "result.csv", "sha256": digest(raw)}}}
        labels = self.materializer().target_result_labels(source)
        self.assertEqual(labels[("race_20260401_tokyo_1R", "1")], {"valid_result": True, "actual_top3": True, "target_race_key": "2026040100000001"})

    def test_i_actual_recipe_fields_are_accepted_without_random_seed(self) -> None:
        recipe = {"C": 1.0, "base_recipe": "V4 Model v4", "class_weight": None, "penalty": "l2", "pipeline": ["StandardScaler", "LogisticRegression"], "solver": "lbfgs"}
        self.assertEqual(set(recipe), {"C", "base_recipe", "class_weight", "penalty", "pipeline", "solver"})

    def test_j_nested_hash_index_tamper_is_not_accepted(self) -> None:
        root = self.root / "reports/ml_v4_buy_selection_dataset_v5"
        root.mkdir(parents=True)
        for name in ("dataset.csv", "feature_schema.json", "training_manifest.json", "source_date_manifest.json", "exclusion_manifest.json", "lineage.json"):
            (root / name).write_text("x", encoding="utf-8")
        dump(root / "artifact_hash_index.json", {"indexed_artifacts": {"dataset.csv": "0"*64}})
        with self.assertRaisesRegex(DataIntegrityStop, "STOP_SOURCE_HASH_MISMATCH"):
            self.materializer().package("reports/ml_v4_buy_selection_dataset_v5", ("dataset.csv", "artifact_hash_index.json"))

    def test_k_path_binop_is_unresolved_runtime_dependency(self) -> None:
        self._dependency_fixture('from pathlib import Path\nP = Path("knowledge") / "meeting_bias"\n')
        materializer = self.materializer(); materializer.policy["feature_sources"] = {"fixture": {"module": "engine/decision_engine.py"}}
        self.assertEqual(materializer.dependency_scan()["status"], "UNRESOLVED")

    def test_l_dynamic_import_is_unresolved_runtime_dependency(self) -> None:
        self._dependency_fixture('import importlib\nvalue = importlib.import_module(name)\n')
        materializer = self.materializer(); materializer.policy["feature_sources"] = {"fixture": {"module": "engine/decision_engine.py"}}
        self.assertEqual(materializer.dependency_scan()["status"], "UNRESOLVED")

    def test_literal_and_variable_path_dependencies_are_unresolved(self) -> None:
        self._dependency_fixture('open("learning/improvement_candidates.json")\n')
        materializer = self.materializer(); materializer.policy["feature_sources"] = {"fixture": {"module": "engine/decision_engine.py"}}
        self.assertEqual(materializer.dependency_scan()["status"], "UNRESOLVED")
        self._dependency_fixture('from pathlib import Path\nBASE = Path("knowledge")\nvalue = BASE / name\n')
        materializer = self.materializer(); materializer.policy["feature_sources"] = {"fixture": {"module": "engine/decision_engine.py"}}
        self.assertEqual(materializer.dependency_scan()["status"], "UNRESOLVED")

    def test_m_explicit_machine_readable_role_record_is_parsed(self) -> None:
        dump(self.root / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json", {"authoritative_additive_entries": [{"month": "202604", "evidence_role": "TRAINING"}]})
        self.assertEqual(self.materializer().canonical_roles({"202604"})["202604"], ["TRAINING"])

    def test_required_sha_missing_stops(self) -> None:
        with self.assertRaisesRegex(DataIntegrityStop, "STOP_REQUIRED_SOURCE_SHA_MISSING"):
            self.materializer().source_file({"path": "missing", "sha256": None}, "DE")

    def test_pipeline_all_drops_have_authoritative_reason(self) -> None:
        values = reconcile_pipeline({"kept", "excluded"}, [{"race_id": "kept"}], {"integrity_excluded_source_races": [{"race_id": "excluded", "reason": "INPUT_INTEGRITY"}]})
        self.assertEqual(values["excluded"], "EXPLICIT_INTEGRITY_EXCLUSION:INPUT_INTEGRITY")

    def test_pipeline_unexplained_drop_stops(self) -> None:
        with self.assertRaisesRegex(DataIntegrityStop, "STOP_UNEXPLAINED_SOURCE_RACE_EXCLUSION"):
            reconcile_pipeline({"unexplained"}, [], {"integrity_excluded_source_races": []})

    def test_raw_to_prediction_drop_requires_authoritative_reason(self) -> None:
        from review.ws2_data_integrity_preflight_v2_source_bound import pipeline_stage_ledger
        with self.assertRaisesRegex(DataIntegrityStop, "STOP_UNEXPLAINED_RAW_TO_PREDICTION_ELIGIBILITY_DROP"):
            pipeline_stage_ledger({"raw", "missing"}, {"raw"}, {"raw"}, [{"race_id": "raw"}], {"integrity_excluded_source_races": []}, {})
        ledger = pipeline_stage_ledger({"raw", "excluded"}, {"raw"}, {"raw"}, [{"race_id": "raw"}], {"integrity_excluded_source_races": []}, {"excluded": "FIXTURE_SCOPE_EXCLUSION"})
        self.assertEqual(ledger["raw_to_prediction_eligibility"]["excluded"], "PREDICTION_INELIGIBLE_FIXTURE_SCOPE_EXCLUSION")

    def test_end_to_end_actual_shape_fixture_calls_public_api(self) -> None:
        self.e2e_fixture()
        output = self.run_fixture_preflight()
        value = json.loads(output.read_text(encoding="utf-8"))
        self.assertNotEqual(value["overall_status"], "STOP")
        self.assertGreaterEqual(len(value["canonical_source_status"]["authenticated_non_race_manifest_artifacts"]), 5)

    def test_end_to_end_feature_value_mutation_stops(self) -> None:
        self.e2e_fixture("feature_value")
        value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
        self.assertEqual(value["checks"][0]["reason_code"], "STOP_FEATURE_SOURCE_VALUE_MISMATCH")
        context = value["checks"][0]["diagnostic_context"]
        self.assertEqual(context["dataset_row_index"], 0)
        self.assertEqual(context["date"], "20260401")
        self.assertEqual(context["race_id"], "race_20260401_tokyo_1R")
        self.assertEqual(context["horse_number"], "1")
        self.assertEqual(context["feature"], "Ability")
        self.assertEqual(context["dataset_value"], "999")
        self.assertEqual(context["canonical_value"], 1.0)
        self.assertIn("source_prediction_artifact_path", context)
        self.assertIn("source_prediction_artifact_sha256", context)

    def test_end_to_end_future_ds_mutation_stops(self) -> None:
        self.e2e_fixture("future_ds")
        value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
        self.assertIn("DS_FUTURE_OR_SAME_DAY_RUN", value["checks"][0]["reason_code"])

    def test_end_to_end_prediction_artifact_sha_mutation_stops(self) -> None:
        self.e2e_fixture("artifact_tamper")
        value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
        self.assertIn("PREDICTION_ARTIFACT_HASH_MISMATCH", value["checks"][0]["reason_code"])

    def test_end_to_end_missing_inherited_parent_source_stops(self) -> None:
        self.e2e_fixture("missing_parent")
        value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
        self.assertIn("SOURCE_MANIFEST_SCHEMA", value["checks"][0]["reason_code"])

    def test_end_to_end_de_horse_set_mutation_stops(self) -> None:
        self.e2e_fixture("de_horse_mismatch")
        value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
        self.assertIn("PREDICTION_DE_HORSE_SET_MISMATCH", value["checks"][0]["reason_code"])

    def test_end_to_end_label_mutation_stops(self) -> None:
        self.e2e_fixture("label_mismatch")
        value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
        self.assertEqual(value["checks"][0]["reason_code"], "STOP_LABEL_INTEGRITY_MISMATCH")

    def test_end_to_end_missing_regeneration_identity_blocks_not_format_stops(self) -> None:
        self.e2e_fixture("missing_regeneration_identity")
        value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
        self.assertEqual(value["overall_status"], "BLOCKED")
        self.assertEqual(value["canonical_source_status"]["PIT"], "PIT_UNPROVEN")

    def test_end_to_end_protected_role_rejects_fold(self) -> None:
        self.e2e_fixture("protected_role")
        value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
        self.assertEqual(value["canonical_source_status"]["rolling_origin_folds"]["status"], "NO_VALID_FOLD")
        self.assertEqual(value["canonical_source_status"]["rolling_origin_folds"]["rejected"][-1]["exclusion_reason"], "PROTECTED_VALIDATION_MONTH")

    def test_end_to_end_dependency_mutations_are_unresolved(self) -> None:
        for mutation in ("learning_string", "variable_knowledge_path", "dynamic_import"):
            with self.subTest(mutation=mutation):
                self.e2e_fixture(mutation)
                value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
                self.assertEqual(value["canonical_source_status"]["dependency"]["status"], "UNRESOLVED")
                shutil.rmtree(self.root, ignore_errors=True)
                self.root.mkdir(parents=True)
                install_docs(self.root)
                self.install_runtime_fixture_modules()

    def test_parsed_zero_history_is_distinct_from_unavailable(self) -> None:
        class Entry:
            past_races = []
            horse_name = "zero"
        class Race:
            today_entries = [Entry()]
            history_rows_by_horse = {"zero": []}
            past_races = []
        class Bundle:
            races = {"fixture": Race()}
        audit = audit_ds_chronology(Bundle(), "20260401")
        self.assertEqual(audit["legitimate_zero_history_horses"], 1)

    def _dependency_fixture(self, body: str) -> None:
        for relative in ("engine/decision_engine.py", "engine/race_decision_engine.py", "analyzer/score_calculator.py"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")


# Keep fixture mixins helper-only: expose canonical tests exactly once on their
# designated unittest class after its complete class body has been defined.
for _name, _value in vars(SourceBoundFixtureMixin).items():
    if _name.startswith("_canonical_test_"):
        setattr(CanonicalFormatTests, _name.replace("_canonical_", "", 1), _value)


class FormalReadinessGateCorrectionTests(SourceBoundFixtureMixin, unittest.TestCase):
    def _pit_provenance(self, *, result_access: int = 0) -> dict[str, object]:
        return {
            "git_head": "a" * 40,
            "run_new_module": "review/run_new.py",
            "run_new_module_sha256": "1" * 64,
            "runner_path": "review/runner.py",
            "runner_sha256": "2" * 64,
            "shadow_buy_engine_sha256": "3" * 64,
            "knowledge_code_sha256": {"knowledge/bloodline.py": "4" * 64},
            "result_data_access_count": result_access,
        }

    def _pit_source(self) -> dict[str, str]:
        root = self.root / "reports/pre/20260401"
        dump(root / "provenance.json", self._pit_provenance())
        return {"date": "20260401", "prediction_root": "reports/pre/20260401"}

    def test_per_prediction_provenance_and_historical_git_identity_prove_pit(self) -> None:
        source = self._pit_source()
        with patch.object(source_bound, "_git_blob_sha256", side_effect=["1" * 64, "2" * 64, "3" * 64, "4" * 64]):
            evidence = self.materializer().prediction_pit_evidence(source)
        self.assertEqual(evidence["status"], "PIT_PROVEN")
        self.assertEqual(evidence["result_data_access_count"], 0)

    def test_missing_provenance_or_invalid_git_never_falls_back_to_worktree(self) -> None:
        source = {"date": "20260401", "prediction_root": "reports/pre/20260401"}
        self.assertEqual(self.materializer().prediction_pit_evidence(source)["status"], "PIT_UNPROVEN")
        source = self._pit_source()
        with patch.object(source_bound, "_git_blob_sha256", return_value=None):
            evidence = self.materializer().prediction_pit_evidence(source)
        self.assertEqual(evidence["status"], "PIT_UNPROVEN")
        self.assertTrue(any(reason.startswith("GENERATOR_IDENTITY_UNPROVEN") for reason in evidence["reasons"]))

    def test_knowledge_code_requires_historical_git_identity(self) -> None:
        source = self._pit_source()
        with patch.object(source_bound, "_git_blob_sha256", side_effect=["1" * 64, "2" * 64, "3" * 64, None]):
            evidence = self.materializer().prediction_pit_evidence(source)
        self.assertEqual(evidence["status"], "PIT_UNPROVEN")
        self.assertIn("KNOWLEDGE_GIT_IDENTITY_UNPROVEN:knowledge/bloodline.py", evidence["reasons"])

    def test_docstring_literal_is_not_runtime_dependency_but_static_import_is_recorded(self) -> None:
        module = self.root / "review/fixture_runtime.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text('"""knowledge/bloodline.py appears only in prose."""\nfrom knowledge.bloodline import score\n', encoding="utf-8")
        knowledge = self.root / "knowledge/bloodline.py"
        knowledge.parent.mkdir(parents=True, exist_ok=True)
        knowledge.write_text("def score():\n    return 1\n", encoding="utf-8")
        materializer = self.materializer()
        materializer.policy["feature_sources"] = {"fixture": {"module": "review/fixture_runtime.py"}}
        dependency = materializer.dependency_scan()
        self.assertEqual(dependency["status"], "PASS")
        self.assertIn("knowledge/bloodline.py", dependency["code_dependencies"])

    def test_utf8_bom_source_is_scanned_normally(self) -> None:
        module = self.root / "review/fixture_runtime.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text('"""knowledge/bloodline.py is documentation only."""\nVALUE = 1\n', encoding="utf-8-sig")
        materializer = self.materializer()
        materializer.policy["feature_sources"] = {"fixture": {"module": "review/fixture_runtime.py"}}
        self.assertEqual(materializer.dependency_scan()["status"], "PASS")

    def test_runtime_file_read_remains_unresolved(self) -> None:
        module = self.root / "review/fixture_runtime.py"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text('open("learning/improvement_candidates.json")\n', encoding="utf-8")
        materializer = self.materializer()
        materializer.policy["feature_sources"] = {"fixture": {"module": "review/fixture_runtime.py"}}
        self.assertEqual(materializer.dependency_scan()["status"], "UNRESOLVED")

    def test_all_21_features_have_explicit_static_provenance_mapping(self) -> None:
        materializer = CanonicalSourceMaterializer(ROOT)
        pit = [{
            "status": "PIT_PROVEN",
            "generator_identities": [
                {"provenance_field": "run_new_module_sha256", "verified": True},
                {"provenance_field": "shadow_buy_engine_sha256", "verified": True},
            ],
        }]
        result = materializer.feature_producer_provenance(pit)
        self.assertEqual(len(result["records"]), 21)
        self.assertEqual(result["unresolved_features"], [])
        self.assertEqual(result["mapping_status"], "PASS")
        self.assertEqual(result["status"], "PASS")

    def test_iteration_one_cannot_bypass_shared_safety_gates(self) -> None:
        blocked = derive_iteration_readiness(
            shared={"status": "BLOCKED"}, recipe_status="PASS",
            outside_top5_present=True, outside_top5_complete=True,
        )
        self.assertEqual(blocked["iteration_0"], "BLOCKED")
        self.assertEqual(blocked["iteration_1"], "BLOCKED")
        ready = derive_iteration_readiness(
            shared={"status": "PASS"}, recipe_status="PASS",
            outside_top5_present=True, outside_top5_complete=True,
        )
        self.assertEqual(ready["iteration_0"], "READY_FOR_PREREGISTRATION_ONLY")
        self.assertEqual(ready["iteration_1"], "DATA_READY_PREREG_REQUIRED")

    def test_each_unresolved_shared_prerequisite_blocks_iteration_one(self) -> None:
        for prerequisite in ("pit", "dependency", "code_provenance"):
            with self.subTest(prerequisite=prerequisite):
                shared = {"status": "BLOCKED", "unresolved_prerequisites": [prerequisite]}
                decision = derive_iteration_readiness(
                    shared=shared, recipe_status="PASS",
                    outside_top5_present=True, outside_top5_complete=True,
                )
                self.assertEqual(decision["iteration_1"], "BLOCKED")


class HashValidationNegativeCoverageTests(SourceBoundFixtureMixin, unittest.TestCase):
    """Exercise the non-indexed activation authority and missing-index split."""

    def test_realistic_nonindexed_activation_with_independent_authority_passes(self) -> None:
        self.e2e_fixture()
        value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
        self.assertNotEqual(value["overall_status"], "STOP")

    def test_activation_record_actual_hash_mismatch_has_context(self) -> None:
        self.e2e_fixture()
        (self.root / "reports/ml_v4_buy_selection_model_v5/activation_record.json").write_text('{"tampered":true}\n', encoding="utf-8")
        value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
        check = value["checks"][0]
        self.assertEqual(check["reason_code"], "STOP_SOURCE_HASH_MISMATCH")
        context = check["diagnostic_context"]
        self.assertEqual(context["validation_stage"], "activation_record_independent_validation")
        self.assertIsNotNone(context["expected_sha256"])
        self.assertIsNotNone(context["actual_sha256"])
        self.assertTrue(context["expected_sha_authority_path"])

    def test_missing_required_index_entry_is_distinct_and_has_null_expected_sha(self) -> None:
        self.e2e_fixture()
        index_path = self.root / "reports/ml_v4_buy_selection_model_v5/artifact_hash_index.json"
        index_value = json.loads(index_path.read_text(encoding="utf-8")); del index_value["indexed_artifacts"]["training_recipe.json"]; dump(index_path, index_value)
        value = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))
        check = value["checks"][0]
        self.assertEqual(check["reason_code"], "STOP_ARTIFACT_HASH_INDEX_REQUIRED_ENTRY_MISSING")
        self.assertIsNone(check["diagnostic_context"]["expected_sha256"])
        self.assertTrue(check["diagnostic_context"]["package_hash_index_path"])

    def test_require_hash_missing_never_returns_empty_string(self) -> None:
        with self.assertRaisesRegex(DataIntegrityStop, "STOP_REQUIRED_SOURCE_SHA_MISSING"):
            self.materializer()._require_hash(None, "package")

    def test_activation_authority_sha_mismatch_stops_with_context(self) -> None:
        self.e2e_fixture()
        policy = self.root / "docs/ws2_v5_feature_source_policy_v4.json"; value = json.loads(policy.read_text(encoding="utf-8")); value["model_activation_record_authority_sha256"] = "0" * 64; dump(policy, value)
        check = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))["checks"][0]
        self.assertEqual(check["reason_code"], "STOP_ACTIVATION_RECORD_AUTHORITY_HASH_MISMATCH")
        self.assertEqual(check["diagnostic_context"]["expected_sha256"], "0" * 64)

    def test_authority_evidence_wrong_content_stops(self) -> None:
        self.e2e_fixture()
        evidence = self.root / "evidence.json"; dump(evidence, {"activation_record_sha256": "0" * 64})
        authority = self.root / "reports/ws2_model_activation_authority_v1/activation_record_authority.json"; record = json.loads(authority.read_text(encoding="utf-8")); record["authority_evidence"] = [{"path": "evidence.json", "sha256": digest(evidence)}]; dump(authority, record)
        policy = self.root / "docs/ws2_v5_feature_source_policy_v4.json"; value = json.loads(policy.read_text(encoding="utf-8")); value["model_activation_record_authority_sha256"] = digest(authority); dump(policy, value)
        check = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))["checks"][0]
        self.assertEqual(check["reason_code"], "STOP_ACTIVATION_RECORD_AUTHORITY_EVIDENCE_MISMATCH")

    def test_authority_evidence_missing_path_stops(self) -> None:
        self.e2e_fixture()
        authority = self.root / "reports/ws2_model_activation_authority_v1/activation_record_authority.json"; record = json.loads(authority.read_text(encoding="utf-8")); record["authority_evidence"] = [{"path": "missing.json", "sha256": "0" * 64}]; dump(authority, record)
        policy = self.root / "docs/ws2_v5_feature_source_policy_v4.json"; value = json.loads(policy.read_text(encoding="utf-8")); value["model_activation_record_authority_sha256"] = digest(authority); dump(policy, value)
        check = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))["checks"][0]
        self.assertEqual(check["reason_code"], "STOP_ACTIVATION_RECORD_AUTHORITY_EVIDENCE_MISMATCH")

    def test_generic_missing_sha_authority_has_null_expected_context(self) -> None:
        self.e2e_fixture()
        manifest = self.root / "reports/ml_v4_buy_selection_dataset_v5_1/source_date_manifest.json"; value = json.loads(manifest.read_text(encoding="utf-8")); del value["sources"][0]["files"]["DG"]["sha256"]; dump(manifest, value)
        index_path = self.root / "reports/ml_v4_buy_selection_dataset_v5_1/artifact_hash_index.json"; index_value = json.loads(index_path.read_text(encoding="utf-8")); index_value["indexed_artifacts"]["source_date_manifest.json"] = digest(manifest); dump(index_path, index_value)
        check = json.loads(self.run_fixture_preflight().read_text(encoding="utf-8"))["checks"][0]
        self.assertEqual(check["reason_code"], "STOP_REQUIRED_SOURCE_SHA_MISSING")
        self.assertIsNone(check["diagnostic_context"]["expected_sha256"])
        self.assertEqual(check["diagnostic_context"]["validation_stage"], "raw_source_sha_authority")

    def test_real_repository_fixed_activation_and_model_index_identities(self) -> None:
        self.assertEqual(digest(ROOT / "reports/ml_v4_buy_selection_model_v5/activation_record.json"), "d7a39be276deb53809f067559a63ec4afb30f04d0dbb384259325bb144dd1f5e")
        self.assertEqual(digest(ROOT / "reports/ml_v4_buy_selection_model_v5/artifact_hash_index.json"), "4c7a04c2a0c89174cfd39584b03d4714dd17aa93d5cddad3a41e608f5842b67e")


class StrictLabelBooleanNormalizationTests(unittest.TestCase):
    def assert_unsupported(self, value: object) -> None:
        with self.assertRaisesRegex(DataIntegrityStop, "STOP_LABEL_BOOLEAN_REPRESENTATION_UNSUPPORTED"):
            _strict_label_boolean(value)

    def test_dataset_one_equals_result_true(self) -> None:
        self.assertIs(_strict_label_boolean("1"), _strict_label_boolean(True))

    def test_20260201_kokura_10r_horse_3_real_numeric_label_regression(self) -> None:
        # Frozen real-data regression: dataset "1" and Result-derived True
        # represent the same semantic label for this previously false-stopped row.
        self.assertIs(_strict_label_boolean("1"), _strict_label_boolean(True))

    def test_dataset_zero_equals_result_false(self) -> None:
        self.assertIs(_strict_label_boolean("0"), _strict_label_boolean(False))

    def test_dataset_one_and_result_false_are_distinct(self) -> None:
        self.assertNotEqual(_strict_label_boolean("1"), _strict_label_boolean(False))

    def test_dataset_zero_and_result_true_are_distinct(self) -> None:
        self.assertNotEqual(_strict_label_boolean("0"), _strict_label_boolean(True))

    def test_boolean_and_true_false_strings_have_same_semantics(self) -> None:
        self.assertIs(_strict_label_boolean(True), _strict_label_boolean(" TrUe "))
        self.assertIs(_strict_label_boolean(False), _strict_label_boolean(" false "))

    def test_integer_one_and_zero_are_the_only_numeric_representations(self) -> None:
        self.assertTrue(_strict_label_boolean(1))
        self.assertFalse(_strict_label_boolean(0))
        self.assert_unsupported(2)
        self.assert_unsupported(-1)
        self.assert_unsupported(1.0)

    def test_unsupported_string_representations_fail_closed(self) -> None:
        for value in ("2", "", "yes", "no", "TRUEE", "  "):
            with self.subTest(value=value):
                self.assert_unsupported(value)

    def test_none_fails_closed(self) -> None:
        self.assert_unsupported(None)

    def test_zero_string_is_never_python_truthiness(self) -> None:
        self.assertFalse(_strict_label_boolean("0"))

    def test_valid_result_uses_the_same_strict_normalization(self) -> None:
        self.assertIs(_strict_label_boolean("TRUE"), _strict_label_boolean(True))
        self.assertIs(_strict_label_boolean("0"), _strict_label_boolean(False))


class CanonicalDatasetTargetMigrationTests(unittest.TestCase):
    """Read-only checks for the V5.1-only WS2 target resolver."""

    def test_v5_1_is_the_exact_canonical_target_despite_inherited_row_metadata(self) -> None:
        resolved = resolve_canonical_dataset_target(ROOT)
        self.assertEqual(resolved["dataset_package"], "reports/ml_v4_buy_selection_dataset_v5_1")
        self.assertEqual(resolved["dataset_version"], "ML_V4_TRAIN_DATASET_V5_1_CORRECTED")
        self.assertEqual(resolved["row_count"], 5530)
        self.assertEqual(resolved["feature_count"], 21)
        with (ROOT / "reports/ml_v4_buy_selection_dataset_v5_1/dataset.csv").open(encoding="utf-8", newline="") as handle:
            first_row = next(csv.DictReader(handle))
        self.assertEqual(first_row["dataset_version"], "ML_V4_TRAIN_DATASET_V5")

    def test_legacy_or_arbitrary_package_request_is_rejected_without_fallback(self) -> None:
        for requested in ("reports/ml_v4_buy_selection_dataset_v5", "reports/ml_v4_buy_selection_dataset_v5_*", "reports/other"):
            with self.subTest(requested=requested), self.assertRaisesRegex(DataIntegrityStop, "STOP_NONCANONICAL_DATASET_PACKAGE_REQUESTED"):
                resolve_canonical_dataset_target(ROOT, requested)

    def test_pinned_dataset_manifest_and_index_mismatches_stop(self) -> None:
        cases = ("CANONICAL_DATASET_CSV_SHA256", "CANONICAL_DATASET_MANIFEST_SHA256", "CANONICAL_DATASET_HASH_INDEX_SHA256", "CONTRACT_SHA256")
        for constant in cases:
            with self.subTest(constant=constant), patch.object(source_bound, constant, "0" * 64), self.assertRaises(DataIntegrityStop):
                resolve_canonical_dataset_target(ROOT)

    def test_implementation_or_policy_cannot_revert_to_v5(self) -> None:
        with patch.object(source_bound, "DATASET_ROOT", "reports/ml_v4_buy_selection_dataset_v5"), self.assertRaisesRegex(DataIntegrityStop, "STOP_FIXED_POLICY_OR_CONTRACT_INVALID"):
            resolve_canonical_dataset_target(ROOT)

    def test_frozen_v5_and_v5_1_datasets_are_byte_stable(self) -> None:
        self.assertEqual(digest(ROOT / "reports/ml_v4_buy_selection_dataset_v5/dataset.csv"), "15c77e5c13ccbff2255912fa5440e68baf43e0df753218d84420d4bf29da3b3a")
        self.assertEqual(digest(ROOT / "reports/ml_v4_buy_selection_dataset_v5_1/dataset.csv"), "ac0a73b36ea6c2e03a2f9df41417ea81561a2de9c55e392e71a0e73448a7e2b7")


if __name__ == "__main__":
    unittest.main()
