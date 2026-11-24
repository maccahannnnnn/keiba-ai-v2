"""Synthetic tests use only a temporary directory; never access the A_new worktree."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from review import b1_prospective_diagnostic_v1 as b1
from review import formal_post_daily_v1 as post_daily
from review import formal_pre_authority_helper_v2 as pre_helper

ROOT = Path(__file__).resolve().parents[1]

class B1DiagnosticTest(unittest.TestCase):
    def _put(self, path: Path, value: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        return path

    def _fixture(self, root: Path):
        date = "20261114"
        current = root / "reports/current"
        current.mkdir(parents=True)
        source_map = {}
        for kind in ("DG", "DE", "DS"):
            source = root / "data/raw/prediction_input" / f"{kind}261114.CSV"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(kind, encoding="ascii")
            source_map[kind] = {"path": str(source.relative_to(root)), "sha256": b1.sha(source)}
        self._put(current / "input_manifest.json", {"date": date, "sources": source_map})
        self._put(current / "prediction_manifest.json", {"date": date, "files": []})
        self._put(current / "formal_freeze_attestation.json", {
            "prediction_manifest_sha256": b1.sha(current / "prediction_manifest.json"),
            "freeze_timestamp_utc": "2026-11-13T10:00:00+00:00", "result_access_count": 0})
        race_list = []
        for race_id, k in ((f"race_{date}_tokyo_1R", 3), (f"race_{date}_kyoto_2R", 1)):
            horses = [{"horse_number": n, "horse_name": f"h{n}",
                       "candidate_p_top3": 0.9 - n * 0.05, "jockey_top3_lift": 0.1}
                      for n in (1, 2, 3, 4)]
            race_list.append({"race_id": race_id, "current_k": k, "horses": horses})
        index = []
        for race in race_list:
            filename = race["race_id"] + ".json"
            self._put(current / filename, {"race_id": race["race_id"], "ranked_results": [
                {"horse_number": h["horse_number"], "horse_name": h["horse_name"]} for h in race["horses"]]})
            index.append({"race_id": race["race_id"], "artifact": filename,
                          "horse_count": len(race["horses"]), "buy_count": race["current_k"]})
        self._put(current / "race_index.json", {"race_index": index})
        plj_path = self._put(root / "reports/plj/selection.json", {
            "date": date, "result_access_count": 0, "current_pre_sha256": b1.sha(current / "prediction_manifest.json"),
            "pl_prediction_sha256": "f" * 64, "model_sha256": b1.PL_MODEL_SHA,
            "beta_source_sha256": b1.JOCKEY_BETA_SHA, "jockey_feature_sha256": b1.JOCKEY_FEATURE_SHA,
            "beta": b1.JOCKEY_BETA, "races": race_list})
        plj_freeze = self._put(root / "reports/plj/provisional_audit.json", {
            "selection_sha256": b1.sha(plj_path), "freeze_timestamp": "2026-11-13T10:01:00+00:00",
            "result_access_count": 0})
        e1_path = self._put(root / "reports/e1/selection.json", {
            "date": date, "result_access_count_at_pre_freeze": 0,
            "current_formal_pre_sha256": b1.sha(current / "prediction_manifest.json"),
            "daily_n": 4, "eligible_races": [r["race_id"] for r in race_list], "selected_horses": []})
        e1_freeze = self._put(root / "reports/e1/freeze_manifest.json", {
            "selection_sha256": b1.sha(e1_path), "e1_freeze_timestamp": "2026-11-13T10:02:00+00:00",
            "result_access_count": 0})
        first = self._put(root / "reports/first_start.json", {
            "date": date, "authority_kind": "KEIBAAI_0900_JST_OPERATIONAL_CUTOFF_V1",
            "operational_cutoff_at": "2026-11-14T09:00:00+09:00", "official_time_verified": False,
            "result_access": 0})
        out = root / f"reports/formal_pre_daily/{date}/b1_diagnostic"
        return date, current, plj_path, plj_freeze, e1_path, e1_freeze, first, out

    def test_global_tie_break_and_max_three(self):
        races = [
            {"race_id": "race_20261114_tokyo_2R", "current_k": 2, "horses": [
                {"horse_number": n, "horse_name": f"t{n}", "candidate_p_top3": .8} for n in (1, 2, 3, 4)]},
            {"race_id": "race_20261114_tokyo_10R", "current_k": 2, "horses": [
                {"horse_number": n, "horse_name": f"r{n}", "candidate_p_top3": .8} for n in (1, 2, 3, 4)]},
        ]
        chosen = b1.select_b1(races, 4)
        self.assertEqual([(h["race_id"], h["horse_number"]) for h in chosen], [
            ("race_20261114_tokyo_10R", 1), ("race_20261114_tokyo_10R", 2),
            ("race_20261114_tokyo_10R", 3), ("race_20261114_tokyo_2R", 1)])
        self.assertLessEqual(max(sum(h["race_id"] == race["race_id"] for h in chosen) for race in races), 3)

    def test_daily_volume_mismatch_and_shortfall_fail_closed(self):
        race = {"race_id": "race_20261114_tokyo_1R", "current_k": 4,
                "horses": [{"horse_number": n, "horse_name": str(n), "candidate_p_top3": .8} for n in (1, 2, 3, 4)]}
        with self.assertRaisesRegex(b1.Stop, "STOP_B1_DAILY_N_MISMATCH"):
            b1.select_b1([race], 3)
        with self.assertRaisesRegex(b1.Stop, "STOP_B1_DAILY_ALLOCATION_SHORTFALL"):
            b1.select_b1([race], 4)

    def test_freeze_is_sha_bound_result_blind_and_reusable_in_temp_root(self):
        temp_root = ROOT / ".tmp/b1_prospective_diagnostic_tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            root = Path(tmp)
            date, current, plj, plseal, e1, e1seal, first, out = self._fixture(root)
            now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
            record = b1.freeze_pre(date, current_root=current, plj_path=plj, plj_freeze=plseal,
                                   e1_path=e1, e1_freeze=e1seal, first_start_path=first,
                                   output_root=out, now=now)
            self.assertEqual(record["status"], "FROZEN")
            selection = json.loads((out / "selection.json").read_text(encoding="utf-8"))
            seal = json.loads((out / "freeze_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(selection["result_access_count"], 0)
            self.assertEqual(seal["selection_sha256"], b1.sha(out / "selection.json"))
            self.assertTrue((out / "selection.json").resolve().is_relative_to(root.resolve()))
            reused = b1.freeze_pre(date, current_root=current, plj_path=plj, plj_freeze=plseal,
                                   e1_path=e1, e1_freeze=e1seal, first_start_path=first,
                                   output_root=out, now=now)
            self.assertEqual(reused["status"], "REUSED_VERIFIED")

    def test_after_cutoff_and_existing_result_do_not_write(self):
        temp_root = ROOT / ".tmp/b1_prospective_diagnostic_tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            root = Path(tmp)
            date, current, plj, plseal, e1, e1seal, first, out = self._fixture(root)
            with self.assertRaisesRegex(b1.Stop, "STOP_B1_CUTOFF_OR_AUTHORITY"):
                b1.freeze_pre(date, current_root=current, plj_path=plj, plj_freeze=plseal,
                              e1_path=e1, e1_freeze=e1seal, first_start_path=first,
                              output_root=out, now=datetime(2026, 11, 14, 0, 1, tzinfo=timezone.utc))
            result_dir = root / "data/raw/target/daily_result_list"
            result_dir.mkdir(parents=True)
            (result_dir / f"馬番順着順_{date}.csv").write_text("result", encoding="utf-8")
            with self.assertRaisesRegex(b1.Stop, "STOP_B1_RESULT_ALREADY_PRESENT"):
                b1.freeze_pre(date, current_root=current, plj_path=plj, plj_freeze=plseal,
                              e1_path=e1, e1_freeze=e1seal, first_start_path=first,
                              output_root=out, now=datetime(2026, 11, 13, 12, tzinfo=timezone.utc))
            self.assertFalse(out.exists())

    def test_target_input_hash_change_stops_without_writing(self):
        temp_root = ROOT / ".tmp/b1_prospective_diagnostic_tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            root = Path(tmp)
            date, current, plj, plseal, e1, e1seal, first, out = self._fixture(root)
            source = root / "data/raw/prediction_input/DG261114.CSV"
            source.write_text("tampered", encoding="ascii")
            with self.assertRaisesRegex(b1.Stop, "STOP_B1_INPUT_SOURCE_SHA_MISMATCH:DG"):
                b1.freeze_pre(date, current_root=current, plj_path=plj, plj_freeze=plseal,
                              e1_path=e1, e1_freeze=e1seal, first_start_path=first,
                              output_root=out, now=datetime(2026, 11, 13, 12, tzinfo=timezone.utc))
            self.assertFalse(out.exists())

    def test_b1_exception_boundary_preserves_seven_lane_artifacts_in_isolation(self):
        cases = (b1.Stop("B1_STOP"), ValueError("bad JSON"), FileExistsError("collision"))
        temp_root = ROOT / ".tmp/b1_prospective_diagnostic_tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            root = Path(tmp)
            pre_summary = root / "reports/formal_pre_daily/20261114/summary.json"
            post_complete = root / "reports/formal_post_daily/20261114/complete.json"
            lane_authority = root / "frozen_seven_lane_authority.json"
            lane_authority.write_text('{"status":"SEVEN_LANES_COMPLETE"}\n', encoding="utf-8")
            lane_authority_sha = b1.sha(lane_authority)
            for boundary in (pre_helper._run_b1_boundary, post_daily._run_b1_boundary):
                for index, error in enumerate(cases):
                    record = boundary(lambda error=error: (_ for _ in ()).throw(error))
                    self.assertEqual(record["status"], "STOPPED")
                    self.assertEqual(record["exception_type"], type(error).__name__)
                    self.assertEqual(record["exception_message"], str(error))
                    self.assertFalse(record["formal_lanes_affected"])
                    self.assertNotEqual(record["status"], "COMPLETE")
                    # The callers continue after this record and persist their
                    # normal seven-lane summary/complete artifact.
                    pre_summary.parent.mkdir(parents=True, exist_ok=True)
                    post_complete.parent.mkdir(parents=True, exist_ok=True)
                    pre_summary.write_text(json.dumps({"b1_diagnostic": record}), encoding="utf-8")
                    post_complete.write_text(json.dumps({"status": "COMPLETE", "b1_diagnostic": record}),
                                             encoding="utf-8")
                    self.assertTrue(pre_summary.is_file())
                    self.assertTrue(post_complete.is_file())
                    self.assertEqual(b1.sha(lane_authority), lane_authority_sha)
                    if index < len(cases) - 1:
                        pre_summary.unlink()
                        post_complete.unlink()
        for error in (KeyboardInterrupt(), SystemExit(1)):
            for boundary in (pre_helper._run_b1_boundary, post_daily._run_b1_boundary):
                with self.assertRaises(type(error)):
                    boundary(lambda error=error: (_ for _ in ()).throw(error))


if __name__ == "__main__":
    unittest.main()
