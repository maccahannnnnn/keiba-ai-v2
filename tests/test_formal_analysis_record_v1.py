"""Isolated, synthetic tests for the non-evidential analysis recorder."""
import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from review import b1_prospective_diagnostic_v1 as b1
from review import formal_analysis_record_v1 as subject


DATE = "20261114"
RACE = "race_20261114_tokyo_1R"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FormalAnalysisRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = self.root / f"reports/prospective_prediction_{DATE}_formal_trace_v1"
        self.current.mkdir(parents=True)
        self.horses = [
            {"horse_number": 1, "horse_name": "A", "candidate_p_top3": 0.2},
            {"horse_number": 2, "horse_name": "B", "candidate_p_top3": 0.8},
            {"horse_number": 3, "horse_name": "C", "candidate_p_top3": 0.5},
        ]
        payload = {"race_id": RACE, "ranked_results": self.horses,
                   "buys": [self.horses[0]]}
        self.artifact = self.current / f"{RACE}_prediction.json"
        write_json(self.artifact, payload)
        self.index = [{"race_id": RACE, "artifact": self.artifact.name,
                       "horse_count": 3, "buy_count": 1}]
        write_json(self.current / "provenance.json",
                   {"target_date": DATE, "result_data_access_count": 0,
                    "generated_at": "2026-11-13T14:00:00+00:00"})
        write_json(self.current / "prediction_manifest.json", {"files": []})
        self.sources = {}
        for kind in ("DG", "DE", "DS"):
            path = self.root / f"data/raw/prediction_input/{kind}261114.CSV"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(kind.encode())
            self.sources[kind] = {"path": str(path.relative_to(self.root)), "sha256": sha(path)}
        self.inputs = {"date": DATE, "sources": self.sources}
        write_json(self.current / "input_manifest.json", self.inputs)
        auth = self.root / "docs/KeibaAI_B1_PROSPECTIVE_EVIDENCE_AUTHORIZATION_V1.md"
        auth.parent.mkdir(parents=True)
        auth.write_text(f"| B1 implementation | `{sha(Path(b1.__file__))}` |\n", encoding="utf-8")
        self.helper = SimpleNamespace(current_authority=lambda root, current:
                                      ({"files": []}, self.inputs, self.index))
        self.patcher = patch.object(subject.formal, "helper", return_value=self.helper)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.clock = patch.object(subject, "_now", return_value=datetime(2026, 11, 13, 14, tzinfo=timezone.utc))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def plj(self):
        path = self.root / "plj.json"
        write_json(path, {"date": DATE, "result_access_count": 0,
                         "current_pre_sha256": sha(self.current / "prediction_manifest.json"),
                         "model_sha256": b1.PL_MODEL_SHA,
                         "beta_source_sha256": b1.JOCKEY_BETA_SHA,
                         "jockey_feature_sha256": b1.JOCKEY_FEATURE_SHA,
                         "beta": b1.JOCKEY_BETA,
                         "races": [{"race_id": RACE, "current_k": 1, "horses": self.horses}]})
        return path

    def test_current_record_is_immutable_and_not_evidence(self):
        result = subject.record_current(DATE, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["selected_horses"], [{"race_id": RACE, "horse_number": 1, "horse_name": "A"}])
        self.assertEqual(record["prospective_evidence_credit"], 0)
        self.assertEqual(record["prospective_evidence_status"], "NOT_ASSESSED")
        self.assertEqual(record["timing_classification"], "BEFORE_TARGET_DATE_ANALYSIS")
        self.assertIsNone(record["original_freeze_at_utc"])
        self.assertEqual(record["original_freeze_time_source"], "NO_FORMAL_FREEZE")
        self.assertEqual(record["execution_time_source"], "SELF_REPORTED_PROVENANCE_GENERATED_AT")
        self.assertEqual(record["target_input_sha256"], {k: v["sha256"] for k, v in self.sources.items()})
        with self.assertRaises(subject.Stop):
            subject.record_current(DATE, root=self.root)
        self.assertEqual(result["sha256"], sha(Path(result["path"])))

    def test_input_sha_mismatch_stops_without_record(self):
        (self.root / self.sources["DS"]["path"]).write_bytes(b"changed")
        with self.assertRaises(b1.Stop):
            subject.record_current(DATE, root=self.root)
        self.assertFalse((self.root / "reports/formal_analysis_v1" / DATE / "current.json").exists())

    def test_current_freeze_attestation_is_verified(self):
        write_json(self.current / "formal_freeze_attestation.json",
                   {"date": DATE, "role": "CURRENT_FORMAL_PRE_FREEZE_ATTESTATION",
                    "prediction_manifest_sha256": sha(self.current / "prediction_manifest.json"),
                    "freeze_timestamp_utc": "2026-11-13T14:00:00+00:00",
                    "result_access_count": 0, "pre_selection_changed_after_freeze": False})
        result = subject.record_current(DATE, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["original_freeze_time_source"], "FORMAL_FREEZE_ATTESTATION")
        self.assertEqual(record["original_freeze_at_utc"], "2026-11-13T14:00:00+00:00")

    def test_current_freeze_manifest_mismatch_stops(self):
        write_json(self.current / "formal_freeze_attestation.json",
                   {"date": DATE, "role": "CURRENT_FORMAL_PRE_FREEZE_ATTESTATION",
                    "prediction_manifest_sha256": "0" * 64, "result_access_count": 0})
        with self.assertRaises(subject.Stop):
            subject.record_current(DATE, root=self.root)

    def test_naive_current_provenance_timestamp_stops(self):
        path = self.current / "provenance.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["generated_at"] = "2026-11-13T14:00:00"
        write_json(path, value)
        with self.assertRaises(subject.Stop):
            subject.record_current(DATE, root=self.root)

    def test_b1_uses_existing_selector_exactly(self):
        path = self.plj()
        result = subject.record_b1(DATE, plj_path=path, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        expected = b1.select_b1([{"race_id": RACE, "current_k": 1, "horses": self.horses}], 1)
        self.assertEqual(record["selected_horses"], expected)
        self.assertEqual(record["prospective_evidence_credit"], 0)
        self.assertEqual(record["selected_horses"][0]["horse_number"], 2)
        self.assertFalse(record["pl_jockey_input_frozen"])

    def test_b1_freeze_selection_sha_is_verified(self):
        path = self.plj()
        write_json(path.with_name("provisional_audit.json"),
                   {"date": DATE, "selection_sha256": sha(path),
                    "result_access_count": 0, "semantic_validation_result": "PASS",
                    "freeze_timestamp": "2026-11-13T14:00:00+00:00"})
        result = subject.record_b1(DATE, plj_path=path, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertTrue(record["pl_jockey_input_frozen"])
        self.assertEqual(record["pl_jockey_freeze_audit_sha256"], sha(path.with_name("provisional_audit.json")))

    def test_b1_freeze_sha_mismatch_stops(self):
        path = self.plj()
        write_json(path.with_name("provisional_audit.json"),
                   {"date": DATE, "selection_sha256": "0" * 64,
                    "result_access_count": 0, "semantic_validation_result": "PASS",
                    "freeze_timestamp": "2026-11-13T14:00:00+00:00"})
        with self.assertRaises(subject.Stop):
            subject.record_b1(DATE, plj_path=path, root=self.root)

    def test_b1_authorized_implementation_sha_mismatch_stops(self):
        path = self.plj()
        auth = self.root / "docs/KeibaAI_B1_PROSPECTIVE_EVIDENCE_AUTHORIZATION_V1.md"
        auth.write_text(f"| B1 implementation | `{'0' * 64}` |\n", encoding="utf-8")
        with self.assertRaises(subject.Stop):
            subject.record_b1(DATE, plj_path=path, root=self.root)

    def test_b1_rejects_wrong_model_without_record(self):
        path = self.plj()
        value = json.loads(path.read_text(encoding="utf-8"))
        value["model_sha256"] = "0" * 64
        write_json(path, value)
        with self.assertRaises(subject.Stop):
            subject.record_b1(DATE, plj_path=path, root=self.root)
        self.assertFalse((self.root / "reports/formal_analysis_v1" / DATE / "b1.json").exists())

    def test_late_record_keeps_original_prediction_time(self):
        with patch.object(subject, "_now", return_value=datetime(2026, 11, 15, tzinfo=timezone.utc)):
            result = subject.record_current(DATE, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["analysis_executed_at_utc"], "2026-11-13T14:00:00+00:00")
        self.assertEqual(record["timing_classification"], "BEFORE_TARGET_DATE_ANALYSIS")
        self.assertEqual(record["prospective_evidence_credit"], 0)

    def test_after_target_date_b1_is_not_mislabeled_prospective(self):
        path = self.plj()
        with patch.object(subject, "_now", return_value=datetime(2026, 11, 15, tzinfo=timezone.utc)):
            result = subject.record_b1(DATE, plj_path=path, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["timing_classification"], "AFTER_TARGET_DATE_ANALYSIS")
        self.assertEqual(record["prospective_evidence_credit"], 0)

    def test_exp024_existing_build_is_recorded_without_freeze(self):
        output = {"date": DATE, "current_prediction_sha256": sha(self.current / "prediction_manifest.json"),
                  "races": [{"race_id": RACE, "treatment_selected_horses": [2]}]}
        with (patch.object(subject, "ROOT", self.root),
              patch.object(subject, "_previous_exp024_fingerprint", return_value=(None, "READ_ONLY")),
              patch.object(subject.exp024, "build_pre", return_value=output) as build):
            result = subject.record_exp024(DATE, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["selected_horses"][0]["horse_number"], 2)
        self.assertFalse(record["environment_chain_advanced"])
        self.assertEqual(record["prospective_evidence_credit"], 0)
        build.assert_called_once()

    def test_pl_jockey_existing_build_is_recorded_without_freeze(self):
        pl_path = self.root / "pl.json"
        write_json(pl_path, {"date": DATE})
        output = {"date": DATE, "result_access_count": 0,
                  "current_pre_sha256": sha(self.current / "prediction_manifest.json"),
                  "pl_prediction_sha256": sha(pl_path),
                  "races": [{"race_id": RACE, "candidate_selected_horses": [3],
                             "candidate_k": 1, "provisional_fallback_race": False,
                             "horses": [{"candidate_p_top3": 0.7},
                                        {"candidate_p_top3": 0.2}]}]}
        output["formal_snapshot_authority_manifest_sha256"] = "a" * 64
        fake_private = SimpleNamespace(build_pre=lambda *args: output,
                                       FORMAL_SNAPSHOT_MANIFEST=self.root / "formal.json",
                                       HISTORY_MANIFEST=self.root / "history.json")
        (self.root / "formal.json").write_bytes(b"formal")
        (self.root / "history.json").write_bytes(b"history")
        scope = {"formal_target_snapshot_registered": False,
                 "formal_snapshot_manifest_sha256": sha(self.root / "formal.json")}
        output["formal_snapshot_authority_manifest_sha256"] = scope["formal_snapshot_manifest_sha256"]
        with (patch.object(subject, "ROOT", self.root),
              patch.object(subject, "_private_plj_for_analysis", return_value=(fake_private, scope)) as build):
            result = subject.record_pl_jockey(DATE, pl_prediction_path=pl_path, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["selected_horses"][0]["horse_number"], 3)
        self.assertEqual(record["record_class"], "ANALYSIS_ONLY")
        self.assertFalse(record["formal_target_snapshot_registered"])
        self.assertEqual(record["jockey_history_pool"], "PRIOR_FORMAL_ENTRIES_PLUS_CURRENT_INPUT")
        build.assert_called_once()

    def _private_plj_fixture(self, entries):
        protocol = self.root / "docs/KeibaAI_FROZEN_PL_V1_JOCKEY_OFFSET_PROVISIONAL_PROTOCOL_V1.md"
        protocol.write_text("\n".join((b1.PL_MODEL_SHA, b1.JOCKEY_BETA_SHA,
                                       b1.JOCKEY_FEATURE_SHA)), encoding="utf-8")
        auth = self.root / "docs/KeibaAI_B1_PROSPECTIVE_EVIDENCE_AUTHORIZATION_V1.md"
        auth.write_text(f"| Frozen PL+Jockey parent protocol | `{sha(protocol)}` |\n", encoding="utf-8")
        manifest = self.root / "formal_manifest.json"
        write_json(manifest, {"entries": entries})
        history = self.root / "history_manifest.json"
        write_json(history, {"entries": []})
        source = self.root / "private_plj_source.py"
        source.write_text(
            "import json\nfrom pathlib import Path\n"
            f"FORMAL_SNAPSHOT_MANIFEST = Path({str(manifest)!r})\n"
            f"HISTORY_MANIFEST = Path({str(history)!r})\n"
            "def validate_formal_manifest(date, *, require_target_entry=True, value=None):\n"
            "    entries = json.loads(FORMAL_SNAPSHOT_MANIFEST.read_text())['entries']\n"
            "    prior = [e for e in entries if e['date'] < date]\n"
            "    if require_target_entry and sum(e['date'] == date for e in entries) != 1:\n"
            "        raise RuntimeError('TARGET_NOT_REGISTERED')\n"
            "    if any(e.get('chain_sha256') != 'valid' for e in prior):\n"
            "        raise RuntimeError('BROKEN_PRIOR_CHAIN')\n"
            "    return prior\n", encoding="utf-8")
        fake_shared = SimpleNamespace(__file__=str(source), MODEL_SHA=b1.PL_MODEL_SHA,
                                      BETA_SHA=b1.JOCKEY_BETA_SHA,
                                      FEATURE_SHA=b1.JOCKEY_FEATURE_SHA,
                                      verify_identity=lambda: None)
        return fake_shared, source

    def test_private_plj_target_registration_and_module_isolation(self):
        prior = {"date": "20261107", "chain_sha256": "valid"}
        shared, source = self._private_plj_fixture([prior])
        with (patch.object(subject, "ROOT", self.root),
              patch.object(subject, "plj_module", shared),
              patch.object(subject, "PLJ_SOURCE_SHA256", sha(source))):
            private, scope = subject._private_plj_for_analysis(DATE, self.current, self.inputs)
            self.assertFalse(scope["formal_target_snapshot_registered"])
            self.assertEqual(scope["prior_formal_snapshot_dates"], ["20261107"])
            self.assertIsNot(private, shared)
            self.assertFalse(hasattr(shared, "validate_formal_manifest"))
            self.assertEqual(private.validate_formal_manifest(DATE), [prior])
            entry = {"date": DATE, "current_pre_sha256": sha(self.current / "prediction_manifest.json"),
                     "input_manifest_sha256": sha(self.current / "input_manifest.json"),
                     "ds_snapshot_sha256": self.sources["DS"]["sha256"],
                     "current_pre_path": str((self.current / "prediction_manifest.json").relative_to(self.root)),
                     "input_manifest_path": str((self.current / "input_manifest.json").relative_to(self.root))}
            write_json(self.root / "formal_manifest.json", {"entries": [prior, entry]})
            _, scope = subject._private_plj_for_analysis(DATE, self.current, self.inputs)
            self.assertTrue(scope["formal_target_snapshot_registered"])
            entry["current_pre_sha256"] = "0" * 64
            write_json(self.root / "formal_manifest.json", {"entries": [prior, entry]})
            with self.assertRaises(subject.Stop):
                subject._private_plj_for_analysis(DATE, self.current, self.inputs)
            write_json(self.root / "formal_manifest.json", {"entries": [prior, entry, entry]})
            with self.assertRaises(subject.Stop):
                subject._private_plj_for_analysis(DATE, self.current, self.inputs)
            write_json(self.root / "formal_manifest.json",
                       {"entries": [{"date": "20261107", "chain_sha256": "broken"}]})
            with self.assertRaises(RuntimeError):
                subject._private_plj_for_analysis(DATE, self.current, self.inputs)
            self.assertFalse(hasattr(shared, "validate_formal_manifest"))

    def test_analysis_only_current_input_sha_mismatch_stops(self):
        analysis = self.root / "reports/analysis_only/current"
        analysis.mkdir(parents=True)
        write_json(analysis / "input_manifest.json", self.inputs)
        write_json(analysis / "race_index.json", {"race_index": self.index})
        (self.root / self.sources["DE"]["path"]).write_bytes(b"changed")
        rows = [{"race_id": RACE, "horse_number": n} for n in (1, 2, 3)]
        source = {"prediction_manifest_sha256": "0" * 64}
        with patch.object(subject.rank1_source, "load_frozen_current", return_value=(rows, source)):
            with self.assertRaises(subject.Stop):
                subject._analysis_current(DATE, analysis, self.root)

    def test_rank1_existing_selection_is_recorded_without_run(self):
        output = {"target_date": DATE, "result_access_count": 0,
                  "input_pre_sha256": sha(self.current / "prediction_manifest.json"),
                  "eligible_races": 1,
                  "selections": [{"race_id": RACE, "selected_horse_number": 1,
                                  "selected_horse_name": "A", "stored_rank": 1}]}
        with (patch.object(subject, "ROOT", self.root),
              patch.object(subject.rank1_module, "build_selection", return_value=output) as build):
            result = subject.record_current_rank1(DATE, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["selected_horses"][0]["rank"], 1)
        self.assertEqual(record["prospective_evidence_credit"], 0)
        build.assert_called_once()

    def test_e1_analysis_record_isolated_worker_result(self):
        (self.root / "review").mkdir()
        shutil.copyfile(Path(subject.__file__).with_name("formal_analysis_external_worker_v1.py"),
                        self.root / "review/formal_analysis_external_worker_v1.py")
        current_sha = sha(self.current / "prediction_manifest.json")
        exp_record = self._upstream_record("EXP024", {"date": DATE,
            "current_prediction_sha256": current_sha, "races": []}, [])
        output = {"date": DATE, "daily_n": 1, "result_access_count": 0,
                  "selected_horses": [{"race_id": RACE, "horse_number": 2, "horse_name": "B"}]}
        with (patch.object(subject, "ROOT", self.root),
              patch.object(subject, "_external", return_value=(output, "a" * 64)) as worker):
            result = subject.record_e1(DATE, exp024_record_path=exp_record, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["selected_count"], 1)
        self.assertEqual(record["prospective_evidence_credit"], 0)
        worker.assert_called_once()

    def test_a_new_analysis_record_isolated_worker_result(self):
        (self.root / "review").mkdir()
        shutil.copyfile(Path(subject.__file__).with_name("formal_analysis_external_worker_v1.py"),
                        self.root / "review/formal_analysis_external_worker_v1.py")
        current_sha = sha(self.current / "prediction_manifest.json")
        plj_record = self._upstream_record("PL_JOCKEY", {"date": DATE,
            "current_pre_sha256": current_sha, "races": []}, [])
        output = {"date": DATE, "result_access_count": 0, "selected_count": 1,
                  "races": [{"race_id": RACE, "a_new_selected_horses": [3]}]}
        with (patch.object(subject, "ROOT", self.root),
              patch.object(subject, "_external", return_value=(output, "a" * 64)) as worker):
            result = subject.record_a_new(DATE, pl_jockey_record_path=plj_record, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["selected_horses"][0]["horse_name"], "C")
        self.assertEqual(record["prospective_evidence_credit"], 0)
        worker.assert_called_once()

    def test_upstream_record_output_tampering_stops(self):
        path = self._upstream_record("E1", {"date": DATE}, [])
        data = json.loads(path.read_text(encoding="utf-8"))
        data["calculation_output"]["date"] = "20261115"
        write_json(path, data)
        with self.assertRaises(subject.Stop):
            subject._verified_record(path, "E1", DATE, root=self.root)

    def test_upstream_record_canonical_path_and_fixed_sha(self):
        path = self._upstream_record("EXP024", {"date": DATE}, [])
        value, digest = subject._verified_record(path, "EXP024", DATE, root=self.root)
        self.assertEqual(value["lane"], "EXP024")
        self.assertEqual(digest, sha(path))

    def test_upstream_record_rejects_noncanonical_path(self):
        path = self._upstream_record("EXP024", {"date": DATE}, [])
        copy = self.root / "other/exp024.json"
        copy.parent.mkdir()
        shutil.copyfile(path, copy)
        with self.assertRaisesRegex(subject.Stop, "RECORD_PATH"):
            subject._verified_record(copy, "EXP024", DATE, root=self.root)

    def test_upstream_record_rejects_calculation_sha_mismatch(self):
        path = self._upstream_record("EXP024", {"date": DATE}, [])
        value = json.loads(path.read_text(encoding="utf-8"))
        value["calculation_function_sha256"] = "0" * 64
        write_json(path, value)
        with self.assertRaisesRegex(subject.Stop, "CALCULATION_SHA"):
            subject._verified_record(path, "EXP024", DATE, root=self.root)

    def test_upstream_record_rejects_plj_source_sha_mismatch(self):
        path = self._upstream_record("PL_JOCKEY", {"date": DATE}, [])
        value = json.loads(path.read_text(encoding="utf-8"))
        value["pl_jockey_source_module_sha256"] = "0" * 64
        write_json(path, value)
        with self.assertRaisesRegex(subject.Stop, "PLJ_SOURCE_SHA"):
            subject._verified_record(path, "PL_JOCKEY", DATE, root=self.root)

    def test_upstream_record_rejects_lane_or_date_mismatch(self):
        path = self._upstream_record("EXP024", {"date": DATE}, [])
        with self.assertRaises(subject.Stop):
            subject._verified_record(path, "E1", DATE, root=self.root)
        with self.assertRaises(subject.Stop):
            subject._verified_record(path, "EXP024", "20261115", root=self.root)

    def test_rehashed_wrong_exp024_selection_stops_e1(self):
        current_sha = sha(self.current / "prediction_manifest.json")
        output = {"date": DATE, "current_prediction_sha256": current_sha,
                  "races": [{"race_id": RACE, "treatment_selected_horses": [2]}]}
        path = self._upstream_record("EXP024", output,
                                     [{"race_id": RACE, "horse_number": 3, "horse_name": "C"}])
        with patch.object(subject, "ROOT", self.root):
            with self.assertRaisesRegex(subject.Stop, "EXP024_CURRENT_SOURCE"):
                subject.record_e1(DATE, exp024_record_path=path, root=self.root)

    def test_four_calculation_code_sha_authorities(self):
        self.assertEqual(sha(subject.E1_SOURCE), subject.E1_SOURCE_SHA256)
        self.assertEqual(sha(subject.A_NEW_SOURCE), subject.A_NEW_SOURCE_SHA256)
        self.assertEqual(sha(Path(subject.independent_v5.__file__)), subject.V5_SOURCE_SHA256)
        self.assertEqual(sha(Path(subject.__file__).with_name("formal_analysis_external_worker_v1.py")),
                         subject.EXTERNAL_WORKER_SHA256)

    def test_e1_source_sha_mismatch_stops_before_calculation(self):
        with (patch.object(subject, "ROOT", self.root),
              patch.object(subject, "E1_SOURCE_SHA256", "0" * 64)):
            with self.assertRaisesRegex(subject.Stop, "E1_SOURCE_SHA"):
                subject.record_e1(DATE, exp024_record_path=self.root / "missing", root=self.root)

    def test_a_new_source_sha_mismatch_stops_before_calculation(self):
        with (patch.object(subject, "ROOT", self.root),
              patch.object(subject, "A_NEW_SOURCE_SHA256", "0" * 64)):
            with self.assertRaisesRegex(subject.Stop, "A_NEW_SOURCE_SHA"):
                subject.record_a_new(DATE, pl_jockey_record_path=self.root / "missing", root=self.root)

    def test_v5_source_sha_mismatch_stops_before_calculation(self):
        with (patch.object(subject, "ROOT", self.root),
              patch.object(subject, "V5_SOURCE_SHA256", "0" * 64)):
            with self.assertRaisesRegex(subject.Stop, "V5_SOURCE_SHA"):
                subject.record_independent_v5(DATE, root=self.root)

    def test_external_worker_sha_mismatch_stops_before_process(self):
        worker = self.root / "review/formal_analysis_external_worker_v1.py"
        worker.parent.mkdir()
        shutil.copyfile(Path(subject.__file__).with_name(worker.name), worker)
        with patch.object(subject, "EXTERNAL_WORKER_SHA256", "0" * 64):
            with self.assertRaisesRegex(subject.Stop, "WORKER_SHA"):
                subject._external("e1", {"date": DATE}, self.root)

    def _upstream_record(self, lane, output, selected):
        path = self.root / f"reports/formal_analysis_v1/{DATE}/{lane.lower()}.json"
        if lane == "E1":
            worker = self.root / "review/formal_analysis_external_worker_v1.py"
            worker.parent.mkdir(parents=True, exist_ok=True)
            if not worker.exists():
                shutil.copyfile(Path(subject.__file__).with_name(worker.name), worker)
        code_sha = {"EXP024": subject.EXP024_SOURCE_SHA256,
                    "PL_JOCKEY": subject.PLJ_SOURCE_SHA256,
                    "E1": subject.EXTERNAL_WORKER_SHA256}[lane]
        write_json(path, {"date": DATE, "lane": lane, "record_class": "ANALYSIS_ONLY",
                          "prospective_evidence_credit": 0, "result_access_count_in_source": 0,
                          "selected_count": len(selected), "selected_horses": selected,
                          "selected_horses_sha256": hashlib.sha256(b1.canonical(selected)).hexdigest(),
                          "calculation_output": output,
                          "calculation_output_sha256": hashlib.sha256(b1.canonical(output)).hexdigest(),
                          "calculation_function_sha256": code_sha,
                          "pl_jockey_source_module_sha256": subject.PLJ_SOURCE_SHA256 if lane == "PL_JOCKEY" else None,
                          "e1_source_module_sha256": subject.E1_SOURCE_SHA256 if lane == "E1" else None,
                          "input_sha256": {"prediction_manifest": sha(self.current / "prediction_manifest.json"),
                                           **{k: v["sha256"] for k, v in self.sources.items()}}})
        return path

    def test_b1_analysis_adapter_uses_unchanged_selector(self):
        source = [{"race_id": RACE, "horse_number": 1, "horse_name": "A"}]
        current_record = self.root / f"reports/formal_analysis_v1/{DATE}/current.json"
        write_json(current_record, {"date": DATE, "lane": "CURRENT",
                                    "record_class": "ANALYSIS_ONLY", "prospective_evidence_credit": 0,
                                    "result_access_count_in_source": 0,
                                    "selected_horses": source,
                                    "selected_horses_sha256": hashlib.sha256(b1.canonical(source)).hexdigest(),
                                    "source_current_path": str(self.current),
                                    "prediction_manifest_sha256": sha(self.current / "prediction_manifest.json"),
                                    "input_manifest_sha256": sha(self.current / "input_manifest.json"),
                                    "source_provenance_sha256": sha(self.current / "provenance.json"),
                                    "target_input_sha256": {k: v["sha256"] for k, v in self.sources.items()}})
        plj_output = {"date": DATE, "result_access_count": 0,
                      "current_pre_sha256": sha(self.current / "prediction_manifest.json"),
                      "model_sha256": b1.PL_MODEL_SHA,
                      "beta_source_sha256": b1.JOCKEY_BETA_SHA,
                      "jockey_feature_sha256": b1.JOCKEY_FEATURE_SHA, "beta": b1.JOCKEY_BETA,
                      "races": [{"race_id": RACE, "current_k": 1,
                                 "candidate_selected_horses": [2], "horses": self.horses}]}
        plj_selected = [{"race_id": RACE, "horse_number": 2, "horse_name": "B"}]
        plj_record = self._upstream_record("PL_JOCKEY", plj_output, plj_selected)
        e1_selected = [{"race_id": RACE, "horse_number": 2, "horse_name": "B"}]
        e1_output = {"date": DATE, "result_access_count": 0,
                     "frozen_pl_model_sha256": b1.PL_MODEL_SHA,
                     "daily_n": 1, "eligible_races": [RACE], "selected_horses": e1_selected}
        e1_record = self._upstream_record("E1", e1_output, e1_selected)
        verified = {k: {"path": str(self.root / v["path"]), "sha256": v["sha256"]}
                    for k, v in self.sources.items()}
        with (patch.object(subject, "ROOT", self.root),
              patch.object(subject, "_analysis_current", return_value=(self.inputs, self.index, verified))):
            result = subject.record_b1_from_analysis(
                DATE, current_record_path=current_record, pl_jockey_record_path=plj_record,
                e1_record_path=e1_record, root=self.root)
        record = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(record["selected_horses"][0]["horse_number"], 2)
        self.assertEqual(record["prospective_evidence_credit"], 0)
        self.assertFalse(record["upstream_formal_freeze_required"])

    def test_b1_analysis_adapter_rejects_pre_effective_date(self):
        with self.assertRaises(subject.Stop):
            subject.record_b1_from_analysis("20261107", current_record_path=self.root / "x",
                                            pl_jockey_record_path=self.root / "y",
                                            e1_record_path=self.root / "z", root=self.root)


if __name__ == "__main__":
    unittest.main()
