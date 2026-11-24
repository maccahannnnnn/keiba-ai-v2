"""Result-blind, isolated tests for date-scoped Formal PRE recording."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from review import formal_pre_authority_helper_v2 as v2


class FormalPreV2Test(unittest.TestCase):
    def setUp(self):
        base = v2.ROOT / ".tmp/formal_pre_authority_helper_v2_tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="formal_pre_v2_", dir=base)
        self.root = Path(self.temp.name)
        cal = self.root / "docs/JRA_OFFICIAL_SEASON_CALENDAR_2026.json"
        cal.parent.mkdir(parents=True)
        shutil.copyfile(v2.CALENDAR, cal)
        self.calendar = cal
        self.date = "20261108"
        self.p = v2.Paths(self.date, self.root)
        self.h = v2.helper(self.date, root=self.root, calendar=cal)
        self.h.check_source_scope = lambda root, index: None
        self.clock = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def _snapshots(self):
        paths = [self.p.official_snapshots / "calendar.html", self.p.official_snapshots / "fukushima_1R.html"]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic official snapshot fixture", encoding="utf-8")
        return paths

    def _first(self, first="2026-11-08T09:45:00+09:00"):
        with patch.object(self.h, "now_utc", return_value=self.clock):
            return self.h.create_first_start(
                root=self.root, snapshot_paths=self._snapshots(), first_start_at=first,
                first_race="福島1R", schedule_url="https://www.jra.go.jp/keiba/calendar2026/",
                entry_page_url="https://www.jra.go.jp/JRADB/accessD.html?fixture", operator_verified=True)

    def _current(self):
        self.p.current.mkdir(parents=True)
        raw = self.root / "data/raw/prediction_input"
        raw.mkdir(parents=True)
        sources = {}
        for kind in ("DG", "DE", "DS"):
            source = raw / f"{kind}{self.date[2:]}.CSV"
            source.write_text(kind, encoding="utf-8")
            sources[kind] = {"path": self.h.relative(self.root, source), "sha256": self.h.sha(source)}
        self.h.exclusive_json(self.p.current / "input_manifest.json", {"date": self.date, "sources": sources})
        self.h.exclusive_json(self.p.current / "provenance.json", {"target_date": self.date, "result_data_access_count": 0})
        index = []
        for venue in ("tokyo", "kyoto", "fukushima"):
            race = f"race_{self.date}_{venue}_1R"
            name = race + "_prediction.json"
            self.h.exclusive_json(self.p.current / name, {"race_id": race, "buys": []})
            index.append({"race_id": race, "artifact": name, "buy_count": 0})
        self.h.exclusive_json(self.p.current / "race_index.json", {"race_index": index})
        names = [r["artifact"] for r in index] + ["input_manifest.json", "provenance.json", "race_index.json"]
        self.h.exclusive_json(self.p.current / "prediction_manifest.json", {"files": [
            {"relative_path": n, "sha256": self.h.sha(self.p.current / n)} for n in names]})

    def test_v1_sha_and_private_binding(self):
        self.assertEqual(v2.digest(v2.V1), v2.V1_SHA)
        from review import formal_pre_authority_helper_v1 as v1
        self.assertEqual(v1.DATE, "20261107")
        self.assertEqual(self.h.DATE, "20261108")
        self.assertEqual(self.h.EXP024_DEADLINE.isoformat(), "2026-11-08T09:00:00+09:00")

    def test_previous_day_pre_allowed_and_attested(self):
        self._first()
        self._current()
        with patch.object(self.h, "now_utc", return_value=self.clock):
            self.h.freeze_current(root=self.root, current=self.p.current, evidence_path=self.p.first_start)
        value = self.h.load(self.p.current / "formal_freeze_attestation.json")
        self.assertEqual(value["date"], self.date)
        self.assertEqual(value["result_access_count"], 0)
        self.assertEqual(value["first_start_evidence_sha256"], self.h.sha(self.p.first_start))

    def test_isolated_1108_first_start_attest_register_chain(self):
        from review import frozen_pl_v1_jockey_offset_provisional_v1 as plj
        self._first()
        self._current()
        previous = {"date": "20261107", "status": "FROZEN_PRE_SOURCE"}
        self.p.snapshot_manifest.parent.mkdir(parents=True, exist_ok=True)
        original = {"expected_formal_pre_dates": ["20261107"], "entries": [previous]}
        self.p.snapshot_manifest.write_bytes(self.h.canonical(original))
        with patch.object(self.h, "now_utc", return_value=self.clock):
            self.h.freeze_current(root=self.root, current=self.p.current, evidence_path=self.p.first_start)
        with patch.object(plj, "validate_formal_manifest", return_value=None):
            self.h.append_snapshot(root=self.root, current=self.p.current,
                                   manifest_path=self.p.snapshot_manifest)
        updated = self.h.load(self.p.snapshot_manifest)
        self.assertEqual(updated["entries"][:-1], original["entries"])
        self.assertEqual(updated["expected_formal_pre_dates"], ["20261107", "20261108"])
        self.assertEqual(updated["entries"][-1]["status"], "FROZEN_PRE_SOURCE")
        with patch.object(plj, "validate_formal_manifest", return_value=None):
            with self.assertRaises(self.h.Stop):
                self.h.append_snapshot(root=self.root, current=self.p.current,
                                       manifest_path=self.p.snapshot_manifest)
        frozen_at = "2026-11-07T12:10:00+00:00"
        lane_paths = {}
        for lane, base, manifest, extra in (
            ("EXP024", self.p.exp024, "selection_freeze.json", {"selection_freeze_timestamp": frozen_at}),
            ("CURRENT_RANK1", self.p.rank1, "freeze_manifest.json", {"freeze_timestamp_jst": frozen_at}),
            ("PL_JOCKEY", self.p.plj, "provisional_audit.json", {"freeze_timestamp": frozen_at}),
            ("A_NEW", self.root / f"a_new/daily_pre/{self.date}", "freeze_manifest.json",
             {"freeze_timestamp": frozen_at, "result_access_count_at_freeze": 0}),
            ("E1", self.root / f"e1/daily_pre/{self.date}", "freeze_manifest.json",
             {"e1_freeze_timestamp": frozen_at, "result_access_count": 0}),
        ):
            selection = "pre_selection.json" if lane == "CURRENT_RANK1" else "selection.json"
            self.h.exclusive_json(base / selection, {"date": self.date})
            self.h.exclusive_json(base / manifest,
                {"selection_sha256": self.h.sha(base / selection), **extra})
            lane_paths[lane] = base / manifest
        self.h.exclusive_json(self.p.independent / "selection_manifest.json", {"date": self.date})
        self.h.exclusive_json(self.p.independent / "artifact_hashes.json", {"indexed_artifacts": {
            "selection_manifest.json": self.h.sha(self.p.independent / "selection_manifest.json")}})
        lane_paths["INDEPENDENT_V5"] = self.p.independent / "artifact_hashes.json"
        step1 = self.root / "step1.json"
        self.h.exclusive_json(step1, {"result_access": 0})
        with patch.object(self.h, "now_utc", return_value=self.clock), patch.object(
                self.h, "verify_v3_pre", return_value=None):
            audit = self.h.audit(root=self.root, current=self.p.current,
                evidence=self.p.first_start, manifest_path=self.p.snapshot_manifest,
                lane_artifacts=lane_paths, step1_path=step1)
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["result_access_count"], 0)

    def test_before_midnight_and_earlier_pre_allowed(self):
        self.clock = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)
        self._first()
        self.assertTrue(self.p.first_start.is_file())

    def test_first_start_past_rejected_and_snapshot_tamper_rejected(self):
        with patch.object(self.h, "now_utc", return_value=datetime(2026, 11, 8, 1, tzinfo=timezone.utc)):
            with self.assertRaises(self.h.Stop):
                self.h.create_first_start(root=self.root, snapshot_paths=self._snapshots(),
                    first_start_at="2026-11-08T09:45:00+09:00", first_race="福島1R",
                    schedule_url="https://www.jra.go.jp/", entry_page_url="https://www.jra.go.jp/",
                    operator_verified=True)
        self.assertFalse(self.p.first_start.exists())
        self._first()
        (self.p.official_snapshots / "calendar.html").write_text("tampered", encoding="utf-8")
        with self.assertRaises(self.h.Stop):
            self.h.first_start_evidence(self.p.first_start, root=self.root)

    def test_latest_prior_fingerprint_and_sha(self):
        self.p.snapshot_manifest.parent.mkdir(parents=True, exist_ok=True)
        self.p.snapshot_manifest.write_text(json.dumps({"expected_formal_pre_dates": ["20261101", "20261107"],
            "entries": [{"date": "20261101", "status": "FROZEN_PRE_SOURCE"},
                        {"date": "20261107", "status": "FROZEN_PRE_SOURCE"}]}), encoding="utf-8")
        prev = self.root / "reports/exp024_pl_same_volume/20261107_pre"
        prev.mkdir(parents=True)
        self.h.exclusive_json(prev / "selection.json", {"date": "20261107",
            "current_environment_fingerprint": "a" * 64,
            "current_environment": {"block_fingerprint_sha256": "a" * 64}})
        self.h.exclusive_json(prev / "selection_freeze.json", {"selection_sha256": self.h.sha(prev / "selection.json")})
        before = self.p.snapshot_manifest.read_bytes()
        self.assertEqual(v2.previous_exp024_fingerprint(self.date, self.root, self.p.snapshot_manifest), "a" * 64)
        self.assertEqual(before, self.p.snapshot_manifest.read_bytes())
        (prev / "selection.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(v2.Stop):
            v2.previous_exp024_fingerprint(self.date, self.root, self.p.snapshot_manifest)

    def test_calendar_and_future_date(self):
        self.assertEqual(v2.calendar_venues("20261108"), frozenset({"東京", "京都", "福島"}))
        self.assertEqual(v2.calendar_venues("20261114"), frozenset({"東京", "京都", "福島"}))
        self.assertEqual(v2.helper("20261115").DATE, "20261115")
        with self.assertRaises(v2.Stop):
            v2.calendar_venues("20270102")
        with self.assertRaises(v2.Stop):
            v2.calendar_venues("20261109")

    def test_exp024_deadline_and_earlier_first_start(self):
        self._first()
        with patch.object(self.h, "now_utc", return_value=datetime(2026, 11, 8, 0, tzinfo=timezone.utc)):
            with self.assertRaisesRegex(v2.Stop, "STOP_EXP024_FORMAL_FREEZE_DEADLINE"):
                self.h.freeze_exp024(current=self.p.current, evidence=self.p.first_start,
                                     approval=self.root / "approval.json", output=self.p.exp024, root=self.root)
        # An earlier official first start outranks the normal 09:00 cutoff.
        earlier = self.h.load(self.p.first_start)
        earlier["first_start_at"] = "2026-11-08T08:30:00+09:00"
        self.p.first_start.write_bytes(self.h.canonical(earlier))
        with patch.object(self.h, "now_utc", return_value=datetime(2026, 11, 7, 23, 30, tzinfo=timezone.utc)):
            with self.assertRaisesRegex(v2.Stop, "STOP_EXP024_FORMAL_FREEZE_DEADLINE"):
                self.h.freeze_exp024(current=self.p.current, evidence=self.p.first_start,
                                     approval=self.root / "approval.json", output=self.p.exp024, root=self.root)

    def test_real_target_input_sha_and_population(self):
        from review.target_bulk_prediction_input_adapter_v1 import TargetBulkPredictionInputAdapterV1
        raw = v2.ROOT / "data/raw/prediction_input"
        expected = {"DG": "b16f3d78d42e4fd927d1d885c45d5a94639660ad43a99bda010fe4fca7de9d6c",
                    "DE": "2ec69cc3f2d06d3acf458615c062734d168607e6381f8c7c0578f52593485156",
                    "DS": "a5bf06e05ff5764e1f9c387809e22fb1fe00d3f567a8dd4139c9fd3a8a1f93ac"}
        for kind, sha in expected.items():
            self.assertEqual(v2.digest(raw / f"{kind}261108.CSV"), sha)
        bundle = TargetBulkPredictionInputAdapterV1().load(*(raw / f"{kind}261108.CSV" for kind in ("DG", "DE", "DS")))
        self.assertEqual(bundle.date, "20261108")
        self.assertEqual(len(bundle.races), 21)
        self.assertEqual(sum(len(r.today_entries) for r in bundle.races.values()), 300)

    def test_conservative_authority_without_html_on_previous_evening(self):
        date = "20261114"
        h = v2.helper(date, root=self.root, calendar=self.calendar)
        stamp = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        digest = v2.create_conservative_authority(date, root=self.root, calendar=self.calendar,
                                                   now_utc=stamp)
        path = v2.Paths(date, self.root).first_start
        value = h.first_start_evidence(path, root=self.root)
        self.assertEqual(v2.digest(path), digest)
        self.assertEqual(value["first_start_at"], "2026-11-14T09:00:00+09:00")
        self.assertEqual(value["first_start_at_semantics"], "CONSERVATIVE_OPERATIONAL_FREEZE_CUTOFF_NOT_OFFICIAL_START")
        self.assertFalse(value["official_time_verified"])
        self.assertFalse(value["operator_verified"])
        self.assertEqual(value["source_snapshots"], [])
        with patch.object(h, "now_utc", return_value=stamp):
            self.assertEqual(h.first_start_evidence(path, root=self.root), value)

    def test_isolated_current_attestation_without_html(self):
        self.date = "20261114"
        self.p = v2.Paths(self.date, self.root)
        self.h = v2.helper(self.date, root=self.root, calendar=self.calendar)
        self.h.check_source_scope = lambda root, index: None
        self._current()
        before = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        v2.create_conservative_authority(self.date, root=self.root, calendar=self.calendar, now_utc=before)
        with patch.object(self.h, "now_utc", return_value=before):
            self.h.freeze_current(root=self.root, current=self.p.current, evidence_path=self.p.first_start)
        attestation = self.h.load(self.p.current / "formal_freeze_attestation.json")
        self.assertEqual(attestation["first_start_at"], "2026-11-14T09:00:00+09:00")
        self.assertEqual(attestation["result_access_count"], 0)
        self.assertEqual(self.h.load(self.p.first_start)["source_snapshots"], [])

    def test_conservative_authority_cutoff_and_special_condition_stop(self):
        date = "20261114"
        late = datetime(2026, 11, 14, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(v2.Stop, "STOP_CONSERVATIVE_CUTOFF_PASSED"):
            v2.create_conservative_authority(date, root=self.root, calendar=self.calendar, now_utc=late)
        before = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        with self.assertRaisesRegex(v2.Stop, "STOP_SPECIAL_SCHEDULE_CONDITION"):
            v2.create_conservative_authority(date, root=self.root, calendar=self.calendar,
                                              special_condition=True, now_utc=before)
        with self.assertRaisesRegex(v2.Stop, "STOP_KNOWN_EARLY_OR_INVALID_FIRST_START"):
            v2.create_conservative_authority(date, root=self.root, calendar=self.calendar,
                                              known_first_start_at="2026-11-14T08:45:00+09:00", now_utc=before)
        with self.assertRaisesRegex(v2.Stop, "STOP_CONSERVATIVE_AUTHORITY_NOT_EFFECTIVE"):
            v2.create_conservative_authority("20261108", root=self.root, calendar=self.calendar,
                                              now_utc=before)

    def test_conservative_authority_tamper_and_legacy_read(self):
        date = "20261114"
        h = v2.helper(date, root=self.root, calendar=self.calendar)
        v2.create_conservative_authority(date, root=self.root, calendar=self.calendar,
            now_utc=datetime(2026, 11, 13, 12, tzinfo=timezone.utc))
        path = v2.Paths(date, self.root).first_start
        value = h.first_start_evidence(path, root=self.root)
        value["official_time_verified"] = True
        path.write_bytes(h.canonical(value))
        with self.assertRaisesRegex(v2.Stop, "STOP_CONSERVATIVE_AUTHORITY_INVALID"):
            h.first_start_evidence(path, root=self.root)
        self._first()
        legacy = self.h.first_start_evidence(self.p.first_start, root=self.root)
        self.assertTrue(legacy["operator_verified"])

    def test_resume_pair_reuses_only_exact_sha(self):
        selection = self.root / "selection.json"
        freeze = self.root / "freeze.json"
        selection.write_text(json.dumps({"date": "20261114"}), encoding="utf-8")
        freeze.write_text(json.dumps({"date": "20261114", "selection_sha256": v2.digest(selection)}), encoding="utf-8")
        self.assertEqual(v2._verified_selection(selection, freeze, date="20261114")["date"], "20261114")
        selection.write_text(json.dumps({"date": "20261114", "changed": True}), encoding="utf-8")
        with self.assertRaisesRegex(v2.Stop, "STOP_RESUME_SELECTION_SHA_OR_DATE"):
            v2._verified_selection(selection, freeze, date="20261114")
        freeze.unlink()
        with self.assertRaisesRegex(v2.Stop, "STOP_PARTIAL_LANE_ARTIFACT"):
            v2._verified_selection(selection, freeze, date="20261114")

    def test_real_1107_seven_lane_selection_summary_read_only(self):
        date = "20261107"
        paths = v2.Paths(date)
        h = v2.helper(date)
        a_pre = h.ANEW / "reports/a_new_prospective_shadow_v1/daily_pre" / date
        e_pre = h.E1 / "reports/e1_full_field_allocation_prospective_shadow_v1/daily_pre" / date
        result = v2._daily_summary(date, root=v2.ROOT, paths=paths,
            input_sha={k: v2.digest(v2.ROOT / f"data/raw/prediction_input/{k}261107.CSV") for k in ("DG", "DE", "DS")},
            race_count=19, horse_count=275, h=h, a_pre=a_pre, e_pre=e_pre)
        self.assertEqual({lane: item["selected_count"] for lane, item in result["lanes"].items()},
            {"CURRENT": 9, "EXP024": 9, "CURRENT_RANK1": 5, "PL_JOCKEY": 9,
             "A_NEW": 9, "E1": 9, "INDEPENDENT_V5": 14})
        self.assertEqual(result["result_access_count"], 0)
        self.assertEqual(len(result["lanes"]["CURRENT_RANK1"]["selected_horses"]), 5)

    def test_run_all_refuses_past_date_and_missing_input(self):
        with self.assertRaisesRegex(v2.Stop, "STOP_RUN_ALL_NOT_EFFECTIVE"):
            v2.run_all("20261108", root=self.root, calendar=self.calendar)
        with self.assertRaisesRegex(v2.Stop, "STOP_SPECIAL_SCHEDULE_CONDITION"):
            v2.run_all("20261114", root=self.root, calendar=self.calendar, special_condition=True)
        with self.assertRaisesRegex(v2.Stop, "STOP_KNOWN_EARLY_OR_INVALID_FIRST_START"):
            v2.run_all("20261114", root=self.root, calendar=self.calendar,
                       known_first_start_at="2026-11-14T08:45:00+09:00")
        with self.assertRaisesRegex(v2.Stop, "STOP_REQUIRED_ARTIFACT_MISSING"):
            v2.run_all("20261114", root=self.root, calendar=self.calendar)


if __name__ == "__main__":
    unittest.main()
