"""Synthetic, isolated TEST-only PRE/POST; never writes real operational artifacts."""
from contextlib import ExitStack
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from review import b1_rolling_v3_shadow_freeze_v1 as subject


DATE = "20261128"
CLOCK = datetime(2026, 11, 27, 11, tzinfo=timezone.utc)
DEADLINE = "2026-11-28T09:00:00+09:00"


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        self.state = Path(self.temp.name) / "state"
        self.current = self.root / f"reports/prospective_prediction_{DATE}_formal_trace_v1"
        self.plj = self.root / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{DATE}_pre"

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(subject.canonical(value))

    def fixture(self, n=12, *, malformed_json=False):
        self.n = n
        ks = [3, 3, 3, 3] if n == 12 else [3, 2, 2, 2]
        self.sizes = [6, 8, 9, 10]
        index, races, files = [], [], []
        self.records = {}
        for rn, (size, k) in enumerate(zip(self.sizes, ks), 1):
            rid = f"race_{DATE}_tokyo_{rn}R"
            horses = [{"horse_number": i, "horse_name": f"TEST_{rn}_{i}", "rank": i} for i in range(1, size + 1)]
            payload = {"race_id": rid, "ranked_results": horses, "buys": horses[:k]}
            name = rid + "_prediction.json"
            self.write(self.current / name, payload)
            index.append({"race_id": rid, "horse_count": size, "buy_count": k, "artifact": name})
            files.append(name)
            races.append({"race_id": rid, "current_k": k, "candidate_k": k,
                          "current_selected_horses": list(range(1, k + 1)),
                          "candidate_selected_horses": list(range(1, k + 1)),
                          "horses": [{"horse_number": h["horse_number"], "horse_name": h["horse_name"],
                                      "candidate_p_top3": 3 / size, "jockey_top3_lift": (h["horse_number"] - 3) / 10}
                                     for h in horses]})
            self.records[rid] = [{"horse_number": h["horse_number"], "horse_name": h["horse_name"],
                                  "vector": np.asarray([float(h["horse_number"] + rn)] + [0.] * 20)} for h in horses]
        self.write(self.current / "race_index.json", {"race_index": index})
        sources = {}
        for kind in ("DG", "DE", "DS"):
            p = self.root / f"data/raw/prediction_input/{kind}261128.CSV"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(("TEST_ONLY_" + kind).encode())
            sources[kind] = {"path": p.relative_to(self.root).as_posix(), "sha256": subject.sha(p)}
        self.write(self.current / "input_manifest.json", {"date": DATE, "sources": sources})
        self.write(self.current / "provenance.json", {"result_data_access_count": 0})
        if malformed_json:
            (self.current / "provenance.json").write_bytes(b"not valid JSON")
        (self.current / "report.md").write_text("# TEST-only Current PRE report\n", encoding="utf-8")
        files += ["race_index.json", "input_manifest.json", "provenance.json", "report.md"]
        self.write(self.current / "prediction_manifest.json", {"files": [
            {"relative_path": name, "sha256": subject.sha(self.current / name)} for name in files]})
        evidence = self.root / f"reports/authority/{DATE}.json"
        self.write(evidence, {"date": DATE, "first_start_at": DEADLINE})
        self.write(self.current / "formal_freeze_attestation.json", {
            "date": DATE, "result_access_count": 0, "freeze_timestamp_utc": "2026-11-27T10:00:00+00:00",
            "first_start_at": DEADLINE, "first_start_evidence_path": evidence.relative_to(self.root).as_posix(),
            "first_start_evidence_sha256": subject.sha(evidence),
            "prediction_manifest_sha256": subject.sha(self.current / "prediction_manifest.json")})
        pl = self.root / f"reports/pl_forward_shadow_v1/{DATE}_pre/prediction.json"
        self.write(pl, {"horses": []})
        self.write(self.plj / "selection.json", {
            "date": DATE, "result_access_count": 0, "fallback_race_count": 0, "beta": 999.0,
            "current_pre_sha256": subject.sha(self.current / "prediction_manifest.json"),
            "current_input_manifest_sha256": subject.sha(self.current / "input_manifest.json"),
            "jockey_feature_sha256": subject.calculation.old_plj.FEATURE_SHA,
            "pl_prediction_sha256": subject.sha(pl), "jockey_snapshot_manifest": [],
            "runtime_dependency_sha256": {}, "races": races})
        self.write(self.plj / "provisional_audit.json", {
            "result_access_count": 0, "selection_sha256": subject.sha(self.plj / "selection.json"),
            "freeze_timestamp": "2026-11-27T10:01:00+00:00"})
        bdir = self.root / f"reports/formal_pre_daily/{DATE}/b1_diagnostic"
        self.write(bdir / "selection.json", {
            "date": DATE, "selected_count": n, "daily_current_buy_n": n,
            "current_prediction_sha256": subject.sha(self.current / "prediction_manifest.json"),
            "pl_jockey_selection_sha256": subject.sha(self.plj / "selection.json"),
            "selected_horses": subject.b1.select_b1(races, n)})
        self.write(bdir / "freeze_manifest.json", {
            "date": DATE, "result_access_count": 0, "selection_sha256": subject.sha(bdir / "selection.json"),
            "freeze_timestamp_utc": "2026-11-27T10:02:00+00:00"})
        self.write(bdir.parent / "summary.json", {
            "date": DATE, "status": "COMPLETE", "result_access_count": 0,
            "race_count": 4, "horse_count": sum(self.sizes), "first_start_authority_sha256": subject.sha(evidence),
            "input_sha256": {k: v["sha256"] for k, v in sources.items()},
            "lanes": {"CURRENT": {"selection_sha256": subject.sha(self.current / "prediction_manifest.json"),
                                   "authority_sha256": subject.sha(self.current / "formal_freeze_attestation.json")},
                      "PL_JOCKEY": {"selection_sha256": subject.sha(self.plj / "selection.json"),
                                    "authority_sha256": subject.sha(self.plj / "provisional_audit.json")}}})
        self.model = {"procedure_id": "ROLLING_PL_JOCKEY_V3", "training_end": "20261123",
                      "feature_names": list(subject.calculation.forward.FEATURE_NAMES), "trainer_included": False,
                      "scaler_mean": [0.] * 21, "scaler_scale": [1.] * 21,
                      "pl_coefficients": [.2] + [0.] * 18, "jockey_beta": .75}
        self.version = "20261123_TEST_ONLY"
        mdir = self.state / "models/rolling_pl_jockey_v3/versions" / self.version
        self.write(mdir / "model.json", self.model)
        self.write(mdir / "manifest.json", {"model_sha256": subject.sha(mdir / "model.json")})
        entry = {"event": "CANDIDATE_ACTIVATED", "version": self.version,
                 "training_end": "20261123", "model_sha256": subject.sha(mdir / "model.json"),
                 "manifest_sha256": subject.sha(mdir / "manifest.json")}
        self.write(self.state / "models/rolling_pl_jockey_v3/current.json", {**entry, "procedure_id": "ROLLING_PL_JOCKEY_V3"})
        self.write(self.state / "reports/rolling_learning_v3/candidate_registry.jsonl", entry)

    def calculation_context(self):
        stack = ExitStack()
        stack.enter_context(patch.object(subject, "now", return_value=CLOCK))
        stack.enter_context(patch.object(subject.calculation.forward, "_payload_records",
                                        side_effect=lambda payload, date: self.records[payload["race_id"]]))
        stack.enter_context(patch.object(subject.calculation.old_plj, "build_pre",
                                        side_effect=lambda *a, **k: subject.load(self.plj / "selection.json")))
        return stack

    def freeze(self):
        with self.calculation_context():
            return subject.freeze_pre(DATE, root=self.root, state_root=self.state, test_only=True)

    def record(self):
        return subject.verify_pre(DATE, root=self.root)

    def results(self, abnormal=False):
        primary, auxiliary = subject.result_paths(self.root, DATE)
        primary.parent.mkdir(parents=True, exist_ok=True)
        left, right = [], []
        for rn, size in enumerate(self.sizes, 1):
            slots = [str(n) for n in range(1, size + 1)]
            if abnormal and rn == 2:
                slots[:2] = ["取消", "除外"]  # 8 on PRE, 6 starters: third is UNKNOWN.
            if abnormal and rn == 4:
                slots[:3] = ["中止", "失格", "取消"]
            common = [DATE + "0505" + f"{rn:02d}" + "00", "東京", str(rn), "TEST_ONLY", "10:00", "", "芝", "1600", "良", str(size), "", ""]
            left.append(common + slots + [""] * (max(self.sizes) - size))
            order = sorted(range(1, size + 1), key=lambda n: (not slots[n-1].isdigit(), int(slots[n-1]) if slots[n-1].isdigit() else n))
            right.append(common + list(map(str, order)) + [""] * (max(self.sizes) - size))
        for path, rows in ((primary, left), (auxiliary, right)):
            with path.open("w", encoding="cp932", newline="") as stream:
                csv.writer(stream).writerows(rows)

    def test_manifest_report_is_hash_checked_and_recorded_without_json_parsing(self):
        self.fixture()
        auth = subject.authority(DATE, self.root)
        report = self.current / "report.md"
        self.assertEqual(auth["sources"][str(report.resolve())], subject.sha(report))

    def test_manifest_report_sha_mismatch_stops(self):
        self.fixture()
        (self.current / "report.md").write_text("changed report", encoding="utf-8")
        with self.assertRaisesRegex(subject.Stop, "STOP_CURRENT_MANIFEST"):
            subject.authority(DATE, self.root)

    def test_manifest_json_still_requires_valid_json_with_matching_sha(self):
        self.fixture(malformed_json=True)
        with self.assertRaisesRegex(subject.Stop, "STOP_JSON:.*provenance.json"):
            subject.authority(DATE, self.root)

    def test_actual_technical_calculation_dynamic_n_and_select_b1(self):
        for n in (9, 12):
            with self.subTest(n=n):
                self.root = Path(self.temp.name) / f"source_{n}"
                self.state = Path(self.temp.name) / f"state_{n}"
                self.current = self.root / f"reports/prospective_prediction_{DATE}_formal_trace_v1"
                self.plj = self.root / f"reports/frozen_pl_v1_jockey_offset_provisional_v1/{DATE}_pre"
                self.fixture(n)
                self.freeze()
                record = self.record()
                self.assertTrue(record["test_only"])
                self.assertEqual(record["daily_selected_count"], n)
                for lane in subject.LANES:
                    self.assertEqual(record["selected"][lane], subject.b1.select_b1(record["races"][lane], n))
                    self.assertEqual(len(record["selected"][lane]), n)
                    self.assertLessEqual(max(__import__('collections').Counter(h['race_id'] for h in record['selected'][lane]).values()), 3)

    def test_own_beta_once_not_frozen_beta(self):
        self.fixture()
        self.freeze()
        record = self.record()
        for er, br in zip(record["races"][subject.LANES[0]], record["races"][subject.LANES[1]]):
            vectors = self.records[er["race_id"]]
            utility = np.asarray([r["vector"][0] * .2 for r in vectors])
            lifts = np.asarray([(r["horse_number"] - 3) / 10 for r in vectors])
            e, _ = subject.calculation.top3._top3_from_utility(utility)
            b, _ = subject.calculation.top3._top3_from_utility(utility + .75 * lifts)
            np.testing.assert_allclose([h["candidate_p_top3"] for h in er["horses"]], e, atol=1e-12)
            np.testing.assert_allclose([h["candidate_p_top3"] for h in br["horses"]], b, atol=1e-12)
        self.assertEqual(record["candidate"]["jockey_beta"], .75)

    def test_model_sha_mismatch_stops(self):
        self.fixture()
        self.write(self.state / "models/rolling_pl_jockey_v3/versions" / self.version / "model.json", {})
        with self.calculation_context(), self.assertRaisesRegex(subject.Stop, "MODEL_OR_MANIFEST_SHA"):
            subject.freeze_pre(DATE, root=self.root, state_root=self.state, test_only=True)

    def test_training_end_not_before_target_stops(self):
        self.fixture()
        with self.assertRaisesRegex(subject.Stop, "MODEL_PIT_OR_PROCEDURE"):
            subject.calculation.model_snapshot("20261123", self.state)

    def test_invalid_date_before_any_read(self):
        for date in ("20260230", "2026112", "２０２６１１２８"):
            with patch.object(subject, "sha", side_effect=AssertionError("file access")), self.assertRaisesRegex(subject.Stop, "STOP_DATE"):
                subject.freeze_pre(date, root=self.root, state_root=self.state, test_only=True)

    def test_pre_result_content_reads_zero(self):
        self.fixture()
        original = Path.open
        def guarded(path, *a, **k):
            if path.name.startswith(("馬番順着順_", "着順馬番_")):
                raise AssertionError("target Result content opened in PRE")
            return original(path, *a, **k)
        with patch.object(Path, "open", guarded):
            self.freeze()
        self.assertEqual(self.record()["result_access_count"], 0)

    def test_existing_result_stops_without_read(self):
        self.fixture()
        self.results()
        with patch.object(subject, "authority", side_effect=AssertionError("late authority read")), self.assertRaisesRegex(subject.Stop, "RESULT_ALREADY_PRESENT"):
            subject.freeze_pre(DATE, root=self.root, state_root=self.state, test_only=True)

    def test_cutoff_stops(self):
        self.fixture()
        with patch.object(subject, "now", return_value=subject.moment(DEADLINE)), self.assertRaisesRegex(subject.Stop, "STOP_CUTOFF"):
            subject.freeze_pre(DATE, root=self.root, state_root=self.state, test_only=True)

    def test_cutoff_crossed_during_calculation_stops_before_write(self):
        self.fixture()
        with self.calculation_context(), patch.object(subject, "now", side_effect=[CLOCK, subject.moment(DEADLINE)]), self.assertRaisesRegex(subject.Stop, "PRE_TIMING"):
            subject.freeze_pre(DATE, root=self.root, state_root=self.state, test_only=True)
        self.assertFalse(subject.folder(self.root, "daily_pre", DATE).exists())

    def test_pre_repeat_verifies_only_after_pointer_change_and_result(self):
        self.fixture()
        self.freeze()
        path = subject.folder(self.root, "daily_pre", DATE) / "selection.json"
        before = path.read_bytes()
        self.write(self.state / "models/rolling_pl_jockey_v3/current.json", {"new_week": True})
        self.results()
        with patch.object(subject.calculation, "technical_date", side_effect=AssertionError("re-inference")):
            reply = subject.freeze_pre(DATE, root=self.root, state_root=self.state, test_only=True)
        self.assertEqual(reply["status"], "ALREADY_FROZEN_UNCHANGED")
        self.assertEqual(path.read_bytes(), before)

    def test_pre_tampering_and_partial_folder_stop(self):
        self.fixture()
        self.freeze()
        path = subject.folder(self.root, "daily_pre", DATE) / "selection.json"
        self.write(path, {})
        with self.assertRaisesRegex(subject.Stop, "FREEZE_SHA"):
            subject.verify_pre(DATE, root=self.root)
        seal = path.with_name("freeze_manifest.json")
        seal.unlink()  # Synthetic TEST artifact only.
        with self.assertRaises(subject.Stop):
            subject.freeze_pre(DATE, root=self.root, state_root=self.state, test_only=True)

    def test_post_never_reads_candidate_or_recalculates_and_repeat_is_readonly(self):
        self.fixture()
        self.freeze()
        candidate = self.record()["candidate"]
        self.results()
        original = Path.open
        def guarded(path, *a, **k):
            if path.is_relative_to(self.state):
                raise AssertionError("POST opened Candidate or Registry")
            return original(path, *a, **k)
        with patch.object(Path, "open", guarded), patch.object(subject.calculation, "technical_date", side_effect=AssertionError("re-inference")), patch.object(subject.b1, "select_b1", side_effect=AssertionError("re-selection")):
            first = subject.post(DATE, root=self.root, human_final_result_confirmed=True)
            report = subject.verify_post(DATE, root=self.root)
            path = Path(first["path"])
            before = path.read_bytes()
            second = subject.post(DATE, root=self.root, human_final_result_confirmed=True)
            self.assertEqual(second["status"], "ALREADY_COMPLETE_UNCHANGED")
            self.assertEqual(path.read_bytes(), before)
        self.assertEqual(report["candidate"], candidate)
        self.assertFalse(report["predictions_recomputed_in_post"])
        self.assertEqual(report["b1_adoption_evidence_credit"], 0)

    def test_post_baseline_vs_place_refund_dnf_dq_unknown(self):
        self.fixture()
        self.freeze()
        self.results(abnormal=True)
        subject.post(DATE, root=self.root, human_final_result_confirmed=True)
        report = subject.verify_post(DATE, root=self.root)
        for lane, rows in report["outcomes"].items():
            for h in rows:
                self.assertEqual(h["ticket_status"], subject.place.ticket(h["raw_result"], h["actual_starters"], h["pre_field_size"]))
            self.assertEqual(report["metrics"][lane]["selected"], self.n)
        current = report["outcomes"]["CURRENT"]
        small_third = next(h for h in current if h["race_id"].endswith('_1R') and h["horse_number"] == 3)
        self.assertTrue(small_third["actual_top3"])
        self.assertEqual(small_third["ticket_status"], "LOSS")
        uncertain = next(h for h in current if h["race_id"].endswith('_2R') and h["horse_number"] == 3)
        self.assertEqual(uncertain["ticket_status"], "UNKNOWN_SALE_OR_PLACE_TERMS")
        last = [h for h in current if h["race_id"].endswith('_4R')]
        self.assertEqual([h["ticket_status"] for h in last], ["LOSS", "LOSS", "REFUND"])
        self.assertTrue(all(not h["valid_result"] for h in last))

    def test_post_requires_finality_and_never_overwrites(self):
        self.fixture()
        self.freeze()
        with self.assertRaisesRegex(subject.Stop, "FINALITY"):
            subject.post(DATE, root=self.root)
        self.results()
        subject.post(DATE, root=self.root, human_final_result_confirmed=True)
        path = subject.folder(self.root, "daily_post", DATE) / "post_summary.json"
        self.write(path, {})
        with self.assertRaisesRegex(subject.Stop, "POST_COMPLETE_SHA"):
            subject.post(DATE, root=self.root, human_final_result_confirmed=True)
        self.assertEqual(subject.load(path), {})

    def test_parent_drift_stops_before_result_and_preserves_parent(self):
        self.fixture()
        self.freeze()
        self.write(self.current / "provenance.json", {"changed": True})
        with self.assertRaisesRegex(subject.Stop, "SOURCE_SHA"):
            subject.post(DATE, root=self.root, human_final_result_confirmed=True)

    def test_pre_and_post_do_not_modify_parent_artifacts(self):
        self.fixture()
        parents = {str(p): subject.sha(p) for base in (self.root, self.state) for p in base.rglob('*') if p.is_file()}
        self.freeze()
        self.results()
        subject.post(DATE, root=self.root, human_final_result_confirmed=True)
        for p, digest in parents.items():
            self.assertEqual(subject.sha(p), digest)


if __name__ == "__main__":
    unittest.main()
