"""Isolated, Result-blind authority-helper tests; no real 2026-11-07 writes."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from review import formal_pre_authority_helper_v1 as helper


class FormalPreAuthorityHelperTest(unittest.TestCase):
    def setUp(self):
        base = helper.ROOT / ".tmp/formal_pre_authority_helper_v1_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="isolated_", dir=base)
        self.root = Path(self.temporary.name)
        calendar = self.root / "docs/JRA_OFFICIAL_SEASON_CALENDAR_2026.json"
        calendar.parent.mkdir(parents=True)
        shutil.copyfile(helper.CALENDAR, calendar)
        self.current = self.root / f"reports/prospective_prediction_{helper.DATE}_formal_trace_v1"
        self.current.mkdir(parents=True)
        self.source = self.root / "data/raw/prediction_input"
        self.source.mkdir(parents=True)
        sources = {}
        for kind in ("DG", "DE", "DS"):
            path = self.source / f"{kind}{helper.DATE[2:]}.CSV"
            path.write_bytes((kind + " synthetic PRE only").encode())
            sources[kind] = {"path": helper.relative(self.root, path), "sha256": helper.sha(path)}
        helper.exclusive_json(self.current / "input_manifest.json", {"date": helper.DATE, "sources": sources})
        helper.exclusive_json(self.current / "provenance.json", {"target_date": helper.DATE,
                                                                  "result_data_access_count": 0})
        self.races = [f"race_{helper.DATE}_{venue}_1R" for venue in ("kyoto", "tokyo", "fukushima")]
        index = []
        for race in self.races:
            name = race + "_prediction.json"
            helper.exclusive_json(self.current / name, {"race_id": race, "buys": []})
            index.append({"race_id": race, "artifact": name, "buy_count": 0})
        helper.exclusive_json(self.current / "race_index.json", {"race_index": index})
        files = [*([r + "_prediction.json" for r in self.races]), "race_index.json",
                 "input_manifest.json", "provenance.json"]
        helper.exclusive_json(self.current / "prediction_manifest.json",
                              {"files": [{"relative_path": name, "sha256": helper.sha(self.current / name)}
                                         for name in files]})
        self.evidence = self.root / f"reports/exp024_pl_same_volume/authority/first_start_{helper.DATE}.json"
        self.snapshots = [self.root / "official/schedule.html", self.root / "official/first_race.html"]
        for path in self.snapshots:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic official-page fixture", encoding="utf-8")
        self.pre_clock = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
        self.source_guard = patch.object(helper, "check_source_scope", return_value=None)
        self.source_guard.start()

    def tearDown(self):
        self.source_guard.stop()
        self.temporary.cleanup()

    def create_evidence(self):
        with patch.object(helper, "now_utc", return_value=self.pre_clock):
            return helper.create_first_start(root=self.root, snapshot_paths=self.snapshots,
                                             first_start_at="2026-11-07T09:45:00+09:00",
                                             first_race="福島1R",
                                             schedule_url="https://www.jra.go.jp/keiba/calendar2026/2026/11/1107.html",
                                             entry_page_url="https://www.jra.go.jp/JRADB/accessD.html?fixture",
                                             operator_verified=True)

    def attest(self):
        self.create_evidence()
        with patch.object(helper, "now_utc", return_value=self.pre_clock):
            return helper.freeze_current(root=self.root, current=self.current, evidence_path=self.evidence)

    def previous_exp024(self, fingerprint="a" * 64):
        prior = self.root / "reports/exp024_pl_same_volume/20261101_pre"
        selection = prior / "selection.json"
        helper.exclusive_json(selection, {"date": "20261101", "current_environment_fingerprint": fingerprint,
                                          "current_environment": {"block_fingerprint_sha256": fingerprint}})
        helper.exclusive_json(prior / "selection_freeze.json", {"selection_sha256": helper.sha(selection)})
        return fingerprint

    def test_normal_first_start_attestation_and_sha(self):
        digest = self.attest()
        evidence = helper.first_start_evidence(self.evidence, root=self.root)
        self.assertTrue(evidence["operator_verified"])
        self.assertEqual(len(evidence["source_snapshots"]), 2)
        self.assertIsNone(evidence["source_snapshots"][0]["source_retrieval_at"])
        self.assertEqual(evidence["source_snapshots"][0]["observed_at_semantics"],
                         "HELPER_LOCAL_FILE_INSPECTION_NOT_SOURCE_RETRIEVAL")
        self.assertIn("file_mtime_utc", evidence["source_snapshots"][0])
        self.assertEqual(digest, helper.sha(self.current / "formal_freeze_attestation.json"))
        attest = helper.load(self.current / "formal_freeze_attestation.json")
        self.assertEqual(attest["prediction_manifest_sha256"], helper.sha(self.current / "prediction_manifest.json"))
        self.assertEqual(attest["result_access_count"], 0)

    def test_no_human_confirmation_and_snapshot_tamper_stop(self):
        with patch.object(helper, "now_utc", return_value=self.pre_clock):
            with self.assertRaisesRegex(helper.Stop, "STOP_HUMAN_VERIFICATION"):
                helper.create_first_start(root=self.root, snapshot_paths=self.snapshots,
                                          first_start_at="2026-11-07T09:45:00+09:00",
                                          first_race="福島1R", schedule_url="https://www.jra.go.jp/a",
                                          entry_page_url="https://www.jra.go.jp/b", operator_verified=False)
        self.create_evidence()
        self.snapshots[0].write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(helper.Stop, "STOP_OFFICIAL_SNAPSHOT_SHA"):
            helper.first_start_evidence(self.evidence, root=self.root)

    def test_missing_venue_and_manifest_sha_stop(self):
        self.create_evidence()
        index = helper.load(self.current / "race_index.json")
        index["race_index"] = index["race_index"][:-1]
        (self.current / "race_index.json").write_bytes(helper.canonical(index))
        with self.assertRaisesRegex(helper.Stop, "STOP_PREDICTION_MANIFEST_SHA"):
            helper.freeze_current(root=self.root, current=self.current, evidence_path=self.evidence)
        manifest = helper.load(self.current / "prediction_manifest.json")
        manifest["files"] = [row for row in manifest["files"]
                             if row["relative_path"] != self.races[-1] + "_prediction.json"]
        for row in manifest["files"]:
            if row["relative_path"] == "race_index.json":
                row["sha256"] = helper.sha(self.current / "race_index.json")
        (self.current / "prediction_manifest.json").write_bytes(helper.canonical(manifest))
        with self.assertRaisesRegex(helper.Stop, "STOP_THREE_VENUES"):
            helper.freeze_current(root=self.root, current=self.current, evidence_path=self.evidence)

    def test_existing_output_and_late_freeze_stop(self):
        self.attest()
        before = (self.current / "formal_freeze_attestation.json").read_bytes()
        with self.assertRaisesRegex(helper.Stop, "STOP_OUTPUT_EXISTS"):
            helper.freeze_current(root=self.root, current=self.current, evidence_path=self.evidence)
        self.assertEqual((self.current / "formal_freeze_attestation.json").read_bytes(), before)
        (self.current / "formal_freeze_attestation.json").unlink()
        late = datetime(2026, 11, 7, 1, tzinfo=timezone.utc)
        with patch.object(helper, "now_utc", return_value=late):
            with self.assertRaisesRegex(helper.Stop, "STOP_FREEZE_AFTER_FIRST_START"):
                helper.freeze_current(root=self.root, current=self.current, evidence_path=self.evidence)

    def test_snapshot_append_preserves_history_and_rejects_duplicate(self):
        self.attest()
        from review import frozen_pl_v1_jockey_offset_provisional_v1 as plj

        path = self.root / "docs/KeibaAI_JOCKEY_FORMAL_PRE_SNAPSHOT_MANIFEST_V1.json"
        previous_dates = ("20261024", "20261025", "20261031", "20261101")
        entries = []
        for day in previous_dates:
            prior = self.root / f"reports/prior_{day}"
            ds = self.root / f"data/raw/prediction_input/DS{day[2:]}.CSV"
            ds.write_bytes(day.encode())
            helper.exclusive_json(prior / "input_manifest.json", {"date": day,
                "sources": {"DS": {"path": helper.relative(self.root, ds), "sha256": helper.sha(ds)}}})
            helper.exclusive_json(prior / "prediction_manifest.json", {"date": day})
            entry = {"date": day, "current_pre_path": helper.relative(self.root, prior / "prediction_manifest.json"),
                     "current_pre_sha256": helper.sha(prior / "prediction_manifest.json"),
                     "ds_snapshot_path": helper.relative(self.root, ds), "ds_snapshot_sha256": helper.sha(ds),
                     "input_manifest_path": helper.relative(self.root, prior / "input_manifest.json"),
                     "input_manifest_sha256": helper.sha(prior / "input_manifest.json"),
                     "status": "FROZEN_PRE_SOURCE"}
            if len(entries) >= 2:
                entry["previous_entries_sha256"] = __import__("hashlib").sha256(plj.canonical(entries)).hexdigest()
            entries.append(entry)
        old = {"manifest_version": 1, "expected_formal_pre_dates": list(previous_dates), "entries": entries}
        helper.exclusive_json(path, old)
        prefix_sha = __import__("hashlib").sha256(plj.canonical(list(previous_dates[:3]))).hexdigest()
        genesis_sha = __import__("hashlib").sha256(plj.canonical(entries[:2])).hexdigest()
        with patch.object(plj, "ROOT", self.root), \
             patch.object(plj, "FORMAL_EXPECTED_PREFIX_SHA", prefix_sha), \
             patch.object(plj, "FORMAL_GENESIS_ENTRIES_SHA", genesis_sha):
            digest = helper.append_snapshot(root=self.root, current=self.current, manifest_path=path)
            after = helper.load(path)
            self.assertEqual(after["entries"][:-1], old["entries"])
            self.assertEqual(after["expected_formal_pre_dates"][:-1], old["expected_formal_pre_dates"])
            self.assertEqual(after["entries"][-1]["previous_entries_sha256"],
                             __import__("hashlib").sha256(helper.canonical(old["entries"])).hexdigest())
            self.assertEqual(digest, helper.sha(path))
            before = path.read_bytes()
            with self.assertRaisesRegex(helper.Stop, "STOP_DUPLICATE_SNAPSHOT_DATE"):
                helper.append_snapshot(root=self.root, current=self.current, manifest_path=path)
            self.assertEqual(path.read_bytes(), before)

    def test_snapshot_append_retains_existing_pretty_format(self):
        self.attest()
        path = self.root / "docs/KeibaAI_JOCKEY_FORMAL_PRE_SNAPSHOT_MANIFEST_V1.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(helper.SNAPSHOT_MANIFEST, path)
        original = path.read_text(encoding="utf-8")
        original_first_entry = original.split('    {', 1)[1].split('    },', 1)[0]
        with patch("review.frozen_pl_v1_jockey_offset_provisional_v1.validate_formal_manifest", return_value=[]):
            helper.append_snapshot(root=self.root, current=self.current, manifest_path=path)
        updated = path.read_text(encoding="utf-8")
        self.assertIn(original_first_entry, updated)
        self.assertIn('"expected_formal_pre_dates": ["20261024", "20261025", "20261031", "20261101", "20261107"]', updated)
        self.assertEqual(len(helper.load(path)["entries"]), len(helper.load(helper.SNAPSHOT_MANIFEST)["entries"]) + 1)

    def test_exp024_deadline_and_existing_api_connection(self):
        self.attest()
        previous = self.previous_exp024()
        from review import pl_same_volume_reselection_shadow_v1 as exp024
        from review import frozen_pl_v1_jockey_offset_provisional_v1 as plj

        output = self.root / "reports/exp024_pre"
        approval = self.root / "approval.json"
        approval.write_text("{}", encoding="utf-8")
        late = datetime(2026, 11, 7, 0, 1, tzinfo=timezone.utc)
        with patch.object(helper, "now_utc", return_value=late):
            with self.assertRaisesRegex(helper.Stop, "STOP_EXP024_0900_JST_DEADLINE"):
                helper.freeze_exp024(current=self.current, evidence=self.evidence, approval=approval,
                                     output=output, root=self.root)
        self.assertFalse(output.exists())
        calls = []
        def fake_freeze(selection, output_root, **kwargs):
            calls.append("freeze")
            helper.exclusive_json(output_root / "selection_freeze.json",
                                  {"selection_freeze_timestamp": self.pre_clock.isoformat()})
        with patch.object(helper, "now_utc", return_value=self.pre_clock), \
             patch.object(plj, "validate_formal_manifest", return_value=[]), \
              patch.object(exp024, "build_pre", side_effect=lambda *a, **k: calls.append(("build", k)) or
                           {"previous_environment_fingerprint": k["previous_environment_fingerprint"],
                            "current_environment_fingerprint": "b" * 64, "change_detected": True}), \
             patch.object(exp024, "freeze_pre", side_effect=fake_freeze):
            helper.freeze_exp024(current=self.current, evidence=self.evidence,
                                 approval=approval, output=output, root=self.root)
        self.assertEqual(calls, [("build", {"previous_environment_fingerprint": previous}), "freeze"])

    def test_current_manifest_windows_posix_and_wrong_path(self):
        original = helper.load(self.current / "input_manifest.json")
        real_schema = helper.load(helper.ROOT / "reports/prospective_prediction_20261101_formal_trace_v1/input_manifest.json")
        for kind in ("DG", "DE", "DS"):
            self.assertEqual(helper.normalized_input_path(real_schema["sources"][kind]["path"]),
                             f"data/raw/prediction_input/{kind}261101.CSV")
        for windows in (True, False):
            value = json.loads(json.dumps(original))
            if windows:
                for item in value["sources"].values():
                    item["path"] = item["path"].replace("/", "\\")
            (self.current / "input_manifest.json").write_bytes(helper.canonical(value))
            manifest = helper.load(self.current / "prediction_manifest.json")
            for item in manifest["files"]:
                if item["relative_path"] == "input_manifest.json":
                    item["sha256"] = helper.sha(self.current / "input_manifest.json")
            (self.current / "prediction_manifest.json").write_bytes(helper.canonical(manifest))
            helper.current_authority(self.root, self.current)
        value["sources"]["DG"]["path"] = "wrong/data/raw/prediction_input/DG261107.CSV"
        (self.current / "input_manifest.json").write_bytes(helper.canonical(value))
        manifest["files"] = [{**item, "sha256": helper.sha(self.current / "input_manifest.json")}
                             if item["relative_path"] == "input_manifest.json" else item for item in manifest["files"]]
        (self.current / "prediction_manifest.json").write_bytes(helper.canonical(manifest))
        with self.assertRaisesRegex(helper.Stop, "STOP_CURRENT_INPUT_SHA:DG"):
            helper.current_authority(self.root, self.current)
        with self.assertRaisesRegex(helper.Stop, "STOP_CURRENT_INPUT_PATH_INVALID"):
            helper.normalized_input_path("../data/raw/prediction_input/DG261107.CSV")

    def test_real_previous_exp024_fingerprint_and_sha_tamper(self):
        actual = helper.previous_exp024_fingerprint(helper.ROOT)
        selection = helper.load(helper.ROOT / "reports/exp024_pl_same_volume/20261101_pre/selection.json")
        self.assertEqual(actual, selection["current_environment_fingerprint"])
        self.assertEqual(len(actual), 64)
        self.previous_exp024()
        prior = self.root / "reports/exp024_pl_same_volume/20261101_pre/selection.json"
        prior.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(helper.Stop, "STOP_EXP024_PREVIOUS_SELECTION_SHA"):
            helper.previous_exp024_fingerprint(self.root)

    def test_exp024_change_detected_must_reflect_fingerprint_difference(self):
        self.attest()
        self.previous_exp024()
        from review import pl_same_volume_reselection_shadow_v1 as exp024
        from review import frozen_pl_v1_jockey_offset_provisional_v1 as plj
        approval = self.root / "approval.json"
        approval.write_text("{}", encoding="utf-8")
        with patch.object(helper, "now_utc", return_value=self.pre_clock), \
             patch.object(plj, "validate_formal_manifest", return_value=[]), \
             patch.object(exp024, "build_pre", return_value={"previous_environment_fingerprint": "a" * 64,
                                                             "current_environment_fingerprint": "b" * 64,
                                                             "change_detected": False}):
            with self.assertRaisesRegex(helper.Stop, "STOP_EXP024_ENVIRONMENT_CHAIN"):
                helper.freeze_exp024(current=self.current, evidence=self.evidence,
                                     approval=approval, output=self.root / "exp", root=self.root)
        self.assertFalse((self.root / "exp").exists())

    def test_execution_order_missing_predecessors_stop(self):
        self.create_evidence()
        approval = self.root / "approval.json"
        approval.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(helper.Stop, "STOP_CURRENT_FORMAL_FREEZE_MISSING"):
            helper.freeze_exp024(current=self.current, evidence=self.evidence, approval=approval,
                                 output=self.root / "exp", root=self.root)
        with self.assertRaises(helper.Stop):
            helper.create_a_new_completion(root=self.root, current=self.current,
                                           exp024=self.root / "missing_exp", rank1=self.root / "missing_rank",
                                           plj=self.root / "missing_plj", output=self.root / "completion.json")
        self.assertFalse((self.root / "completion.json").exists())

    def test_completion_records_and_order(self):
        self.attest()
        exp = self.root / "exp/selection_freeze.json"
        rank = self.root / "rank/freeze_manifest.json"
        plj = self.root / "plj/provisional_audit.json"
        for path, field in ((exp, "selection_freeze_timestamp"), (rank, "freeze_timestamp_jst"),
                            (plj, "freeze_timestamp")):
            helper.exclusive_json(path, {field: self.pre_clock.isoformat()})
        completion = self.root / "a_new/formal_completion_20261107.json"
        helper.create_a_new_completion(root=self.root, current=self.current, exp024=exp.parent,
                                       rank1=rank.parent, plj=plj.parent, output=completion)
        self.assertEqual(len(helper.load(completion)["artifacts"]), 4)
        a_new = self.root / "a_new/daily_pre/20261107/freeze_manifest.json"
        selection = a_new.parent / "selection.json"
        helper.exclusive_json(selection, {"date": helper.DATE})
        helper.exclusive_json(a_new, {"date": helper.DATE, "evidence_date": True,
                                      "result_access_count_at_freeze": 0,
                                      "selection_sha256": helper.sha(selection)})
        authority = self.root / "e1/authority"
        helper.create_e1_completion(current=self.current, exp024=exp.parent, rank1=rank.parent,
                                    plj=plj.parent, a_new_status=None, a_new_freeze=a_new,
                                    authority_root=authority)
        priority = helper.load(authority / "priority_completion_20261107.json")
        self.assertEqual(len(priority["lane_status"]), 5)
        self.assertEqual(priority["lane_status"]["A_NEW"]["status"], "PRE_FROZEN")
        for item in priority["lane_status"].values():
            self.assertEqual(helper.sha(Path(item["status_path"])), item["status_sha256"])
        with self.assertRaisesRegex(helper.Stop, "STOP_OUTPUT_EXISTS"):
            helper.create_e1_completion(current=self.current, exp024=exp.parent, rank1=rank.parent,
                                        plj=plj.parent, a_new_status=None, a_new_freeze=a_new,
                                        authority_root=authority)

    def test_pl_jockey_and_step1_use_existing_freeze_apis(self):
        self.attest()
        from review import frozen_pl_v1_jockey_offset_provisional_v1 as plj
        from review import pl_jockey_step1_operations_v1 as step1

        calls = []
        pl_output = self.root / "pl_prediction.json"
        pl_output.write_text("{}", encoding="utf-8")
        def fake_plj_freeze(selection, output_root, **kwargs):
            calls.append("plj_freeze")
            helper.exclusive_json(output_root / "provisional_audit.json", {"date": helper.DATE})
        with patch.object(plj, "validate_formal_manifest", side_effect=lambda *a, **k: calls.append("manifest")), \
             patch.object(plj, "build_pre", side_effect=lambda *a: calls.append("plj_build") or {}), \
             patch.object(plj, "freeze_pre", side_effect=fake_plj_freeze):
            helper.freeze_pl_jockey(current=self.current, pl_prediction=pl_output,
                                    evidence=self.evidence, de=self.source / "DE261107.CSV",
                                    ds=self.source / "DS261107.CSV", output=self.root / "plj",
                                    root=self.root)
        self.assertEqual(calls, ["manifest", "plj_build", "plj_freeze"])
        def fake_step1_freeze(**kwargs):
            calls.append("step1_freeze")
            helper.exclusive_json(kwargs["output_path"], {"result_access": 0})
        with patch.object(step1, "freeze_pre", side_effect=fake_step1_freeze):
            helper.freeze_step1(plj_path=self.root / "plj/selection.json",
                                e1_path=self.root / "e1/selection.json", current=self.current,
                                evidence=self.evidence, output=self.root / "step1.json", root=self.root)
        self.assertEqual(calls[-1], "step1_freeze")

    def test_a_new_e1_use_existing_script_paths_not_module_execution(self):
        artifact = self.current / "prediction_manifest.json"
        completion = self.root / "formal_completion.json"
        helper.exclusive_json(completion, {"date": helper.DATE,
                                           "all_existing_formal_pre_complete": True,
                                           "artifacts": [{"lane": lane, "path": str(artifact), "sha256": helper.sha(artifact)}
                                                         for lane in ("CURRENT", "EXP024", "CURRENT_RANK1_PRIOR_DAY_PRE_V2",
                                                                      "FROZEN_PL_V1_JOCKEY_OFFSET")]})
        priority = self.root / "priority_completion.json"
        helper.exclusive_json(priority, {"date": helper.DATE, "result_access_count": 0,
                                         "artifacts": [{"lane": lane, "path": str(artifact), "sha256": helper.sha(artifact)}
                                                       for lane in ("CURRENT", "EXP024", "CURRENT_RANK1",
                                                                    "FROZEN_PL_JOCKEY", "A_NEW")]})
        a_new_root = self.root / "a_new_worktree"
        e1_root = self.root / "e1_worktree"
        for path in (a_new_root / "review/a_new_prospective_shadow_v1.py",
                     e1_root / "review/e1_full_field_allocation_prospective_shadow_v1.py"):
            path.parent.mkdir(parents=True)
            path.write_text("# synthetic runner fixture", encoding="utf-8")
        approval = self.root / "approval.json"
        approval.write_text("{}", encoding="utf-8")
        with patch.object(helper.subprocess, "run") as run:
            helper.run_a_new_existing(completion=completion, current=self.current, formal=self.root / "plj",
                                      approval=approval, worktree=a_new_root)
            helper.run_e1_existing(priority=priority, exp024=self.root / "exp", current=self.current,
                                   approval=approval, worktree=e1_root)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            command = call.args[0]
            self.assertNotIn("-m", command)
            self.assertTrue(Path(command[1]).is_file())
            self.assertIn("--build-pre", command)

    def test_e1_not_collected_a_new_precedent(self):
        upstream = {}
        for lane in ("current", "exp", "rank", "plj"):
            path = self.root / lane / ({"current": "prediction_manifest.json",
                                        "exp": "selection_freeze.json",
                                        "rank": "freeze_manifest.json",
                                        "plj": "provisional_audit.json"}[lane])
            helper.exclusive_json(path, {"date": helper.DATE})
            upstream[lane] = path.parent
        status = self.root / "a_new/date_status/20261107/status.json"
        helper.exclusive_json(status, {"date": helper.DATE, "status": "NOT_COLLECTED",
                                       "result_access_count": 0})
        authority = self.root / "e1/authority"
        helper.create_e1_completion(current=upstream["current"], exp024=upstream["exp"],
                                    rank1=upstream["rank"], plj=upstream["plj"],
                                    a_new_status=status, a_new_freeze=None, authority_root=authority)
        priority = helper.load(authority / "priority_completion_20261107.json")
        self.assertEqual(priority["lane_status"]["A_NEW"]["status"], "NOT_COLLECTED")
        self.assertEqual(priority["artifacts"][-1]["lane"], "A_NEW_FORMAL_STATUS")

    def test_final_audit_all_lane_hashes_and_v3_boundary(self):
        self.attest()
        snapshot = self.root / "docs/KeibaAI_JOCKEY_FORMAL_PRE_SNAPSHOT_MANIFEST_V1.json"
        shutil.copyfile(helper.SNAPSHOT_MANIFEST, snapshot)
        with patch("review.frozen_pl_v1_jockey_offset_provisional_v1.validate_formal_manifest", return_value=[]):
            helper.append_snapshot(root=self.root, current=self.current, manifest_path=snapshot)
        lanes = {}
        frozen = self.pre_clock.isoformat()
        for lane, timestamp_key in (("EXP024", "selection_freeze_timestamp"),
                                    ("CURRENT_RANK1", "freeze_timestamp_jst"),
                                    ("PL_JOCKEY", "freeze_timestamp"),
                                    ("A_NEW", "freeze_timestamp_utc"),
                                    ("E1", "e1_freeze_timestamp")):
            directory = self.root / "lanes" / lane
            selection_name = "pre_selection.json" if lane == "CURRENT_RANK1" else "selection.json"
            selection = directory / selection_name
            helper.exclusive_json(selection, {"date": helper.DATE, "lane": lane})
            freeze_name = "provisional_audit.json" if lane == "PL_JOCKEY" else "selection_freeze.json" if lane == "EXP024" else "freeze_manifest.json"
            record = {timestamp_key: frozen, "selection_sha256": helper.sha(selection)}
            if lane == "A_NEW":
                record["result_access_count_at_freeze"] = 0
            if lane == "E1":
                record["result_access_count"] = 0
            helper.exclusive_json(directory / freeze_name, record)
            lanes[lane] = directory / freeze_name
        independent = self.root / "lanes/INDEPENDENT_V5"
        helper.exclusive_json(independent / "selection_manifest.json", {"date": helper.DATE})
        helper.exclusive_json(independent / "artifact_hashes.json",
                              {"indexed_artifacts": {"selection_manifest.json":
                                                     helper.sha(independent / "selection_manifest.json")}})
        lanes["INDEPENDENT_V5"] = independent / "artifact_hashes.json"
        step1 = self.root / "step1.json"
        helper.exclusive_json(step1, {"result_access": 0})
        with patch.object(helper, "verify_v3_pre") as v3_check:
            report = helper.audit(root=self.root, current=self.current, evidence=self.evidence,
                                  manifest_path=snapshot, lane_artifacts=lanes, step1_path=step1)
            v3_check.assert_called_once_with(self.root, snapshot)
        self.assertEqual(report["status"], "PASS")
        late = datetime(2026, 11, 7, 1, tzinfo=timezone.utc)
        with patch.object(helper, "now_utc", return_value=late):
            with self.assertRaisesRegex(helper.Stop, "STOP_AUDIT_AFTER_FIRST_START"):
                helper.audit(root=self.root, current=self.current, evidence=self.evidence,
                             manifest_path=snapshot, lane_artifacts=lanes, step1_path=step1)
        (lanes["A_NEW"].parent / "selection.json").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(helper.Stop, "STOP_LANE_SELECTION_SHA:A_NEW"):
            helper.audit(root=self.root, current=self.current, evidence=self.evidence,
                         manifest_path=snapshot, lane_artifacts=lanes, step1_path=step1)

    def test_result_paths_not_consulted(self):
        self.assertNotIn("daily_result_list", Path(helper.__file__).read_text(encoding="utf-8"))
        self.assertFalse(any(self.root.rglob("*result*")))
        forbidden = self.root / "data/raw/target/daily_result_list/official.html"
        with self.assertRaisesRegex(helper.Stop, "STOP_FORBIDDEN_SNAPSHOT_PATH"):
            helper.official_snapshot_path(self.root, forbidden)

    def test_prediction_manifest_traversal_rejected_before_read(self):
        self.create_evidence()
        manifest_path = self.current / "prediction_manifest.json"
        manifest = helper.load(manifest_path)
        manifest["files"].append({"relative_path": "../Result.csv", "sha256": "0" * 64})
        manifest_path.write_bytes(helper.canonical(manifest))
        with self.assertRaisesRegex(helper.Stop, "STOP_PREDICTION_MANIFEST_PATH_SCOPE"):
            helper.freeze_current(root=self.root, current=self.current, evidence_path=self.evidence)


if __name__ == "__main__":
    unittest.main()
