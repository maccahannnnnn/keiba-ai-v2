from __future__ import annotations

import hashlib
import json
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path

from review import selection_authority_protocol_v1_v6_forward_shadow_pre_freeze as subject


ROOT = Path(__file__).resolve().parents[1]


class V6ForwardShadowTest(unittest.TestCase):
    def _rehash_manifest_file(self, root: Path, relative_path: str) -> None:
        manifest_path = root / "prediction_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            if entry["relative_path"] == relative_path:
                entry["sha256"] = hashlib.sha256((root / relative_path).read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _future_current_pre_fixture(self, parent: Path, *, target_date: str = "20260919", generated_at: str = "2026-09-18T15:00:00+00:00", provenance_target_date: str | None = None) -> Path:
        source = ROOT / "reports" / "selection_authority_protocol_v1_january_2026_historical_holdout" / "current_pre" / "20260104"
        copied = parent / "current_pre"; shutil.copytree(source, copied)
        summary_path = copied / "summary.json"; summary = json.loads(summary_path.read_text(encoding="utf-8")); summary["date"] = target_date; summary_path.write_text(json.dumps(summary), encoding="utf-8")
        provenance_path = copied / "provenance.json"; provenance = json.loads(provenance_path.read_text(encoding="utf-8")); provenance["target_date"] = provenance_target_date or target_date; provenance["generated_at"] = generated_at; provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
        self._rehash_manifest_file(copied, "summary.json")
        self._rehash_manifest_file(copied, "provenance.json")
        return copied
    def test_protocol_and_v6_identity_are_pinned(self):
        protocol = subject.load_protocol()
        _, _, identity = subject.load_frozen_v6(protocol)
        self.assertEqual(identity["role"], "DEVELOPMENT_CANDIDATE_ONLY")
        self.assertEqual(identity["model_sha256"], "68af6d39647e46a9f7104f648c32b1db8dca46fed979bbfd4d25bf9ca4c1a152")
        self.assertEqual(identity["dataset_sha256"], "b92b0c448dcd074b17105cf1860818d621a12447c095814e630b48ab5fff75ef")

    def test_result_free_technical_fixture_has_shared_population_and_arm_invariants(self):
        source = ROOT / "reports" / "selection_authority_protocol_v1_january_2026_historical_holdout" / "current_pre" / "20260104"
        temp = ROOT / "reports" / "_v6_forward_shadow_technical_test_tmp"
        self.assertFalse(temp.exists(), "stale test fixture directory")
        temp.mkdir()
        try:
            output = temp / "output"
            subject.run_technical_fixture("20260104", source, output)
            semantic = json.loads((output / "dual_pre_semantic.json").read_text(encoding="utf-8"))
            manifest = json.loads((output / "dual_pre_manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(semantic["formal_evidence"])
            self.assertTrue(semantic["technical_wiring_only"])
            self.assertEqual(manifest["result_access"], 0)
            self.assertEqual(manifest["actual_top3_access"], 0)
            self.assertFalse(semantic["evidence_denominator_depends_on_selected_n"])
            for race in semantic["races"]:
                self.assertEqual(race["v5"]["race_id"], race["v6"]["race_id"])
                self.assertEqual(race["v5"].get("target_k"), race["v6"].get("target_k"))
                if race["eligible_evidence_race"]:
                    for arm in (race["v5"], race["v6"]):
                        exact5 = [x for x in arm["horses"] if x["exact5_membership"]]
                        self.assertEqual(len(exact5), 5)
                        self.assertEqual(arm["shortfall"], max(arm["target_k"] - arm["selected_n"], 0))
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def test_protocol_bytes_are_stable(self):
        self.assertEqual(hashlib.sha256(subject.PROTOCOL_PATH.read_bytes()).hexdigest(), subject.FROZEN_PROTOCOL_SHA256)

    def test_population_mismatch_fails_closed(self):
        with self.assertRaisesRegex(subject.Stop, "STOP_V5_V6_POPULATION_MISMATCH"):
            subject._validate_arm_population({"horses":[{"horse_number":1}]}, {"horses":[{"horse_number":2}]})

    def test_duplicate_horse_number_fails_closed(self):
        source = ROOT / "reports" / "selection_authority_protocol_v1_january_2026_historical_holdout" / "current_pre" / "20260104"
        payload = json.loads(next(source.glob("race_*_prediction.json")).read_text(encoding="utf-8"))
        payload["ranked_results"].append(dict(payload["ranked_results"][0]))
        protocol = subject.load_protocol()
        with self.assertRaisesRegex(subject.Stop, "STOP_V5_V6_POPULATION_MISMATCH"):
            subject._dual_race("20260914", payload, "fixture", subject._v5(protocol), subject.load_frozen_v6(protocol))

    def test_selected_zero_remains_eligible_evidence_race(self):
        source = ROOT / "reports" / "selection_authority_protocol_v1_january_2026_historical_holdout" / "current_pre" / "20260104"
        payload = next(json.loads(path.read_text(encoding="utf-8")) for path in source.glob("race_*_prediction.json") if any(row.get("buy") is True for row in json.loads(path.read_text(encoding="utf-8"))["ranked_results"]))
        for trace in payload["buy_gate_trace"]["horses"]:
            trace["risk_guard_pass"] = False
        protocol = subject.load_protocol()
        result = subject._dual_race("20260914", payload, "fixture", subject._v5(protocol), subject.load_frozen_v6(protocol))
        self.assertTrue(result["eligible_evidence_race"])
        self.assertEqual(result["v5"]["selected_n"], 0)
        self.assertEqual(result["v6"]["selected_n"], 0)

    def test_real_entrypoint_guards_and_deterministic_isolated_output(self):
        temp = ROOT / "reports" / "_v6_real_pre_entrypoint_test_tmp"
        self.assertFalse(temp.exists(), "stale real PRE test directory")
        temp.mkdir()
        try:
            copied = self._future_current_pre_fixture(temp)
            fixed_clock = datetime(2026, 9, 19, 3, tzinfo=timezone.utc)
            with self.assertRaisesRegex(subject.Stop, "STOP_BEFORE_FORMAL_EVIDENCE_START"):
                subject.run_real_formal_pre("20260917", copied, temp / "before", clock_utc=fixed_clock)
            with self.assertRaisesRegex(subject.Stop, "STOP_CURRENT_PRE_NOT_FOUND"):
                subject.run_real_formal_pre("20260919", temp / "missing", temp / "missing_out", clock_utc=fixed_clock)
            self.assertFalse((temp / "before" / "20260917").exists())
            one = subject.run_real_formal_pre("20260919", copied, temp / "one", clock_utc=fixed_clock)
            two = subject.run_real_formal_pre("20260919", copied, temp / "two", clock_utc=fixed_clock)
            self.assertTrue(json.loads((one / "dual_pre_semantic.json").read_text(encoding="utf-8"))["formal_evidence"])
            self.assertEqual((one / "dual_pre_semantic.json").read_bytes(), (two / "dual_pre_semantic.json").read_bytes())
            with self.assertRaisesRegex(subject.Stop, "STOP_REAL_PRE_ALREADY_EXISTS"):
                subject.run_real_formal_pre("20260919", copied, temp / "one", clock_utc=fixed_clock)
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def test_start_boundary_g2_g3_g4_and_manifest_tamper_fail_closed(self):
        temp = ROOT / "reports" / "_v6_start_boundary_test_tmp"; self.assertFalse(temp.exists(), "stale start-boundary test directory"); temp.mkdir()
        try:
            copied = self._future_current_pre_fixture(temp)
            with self.assertRaisesRegex(subject.Stop, "STOP_RETROACTIVE_V6_FORMAL_PRE_PROHIBITED"):
                subject.run_real_formal_pre("20260919", copied, temp / "g2", clock_utc=datetime(2026, 9, 20, 3, tzinfo=timezone.utc))
            old = self._future_current_pre_fixture(temp / "old", generated_at="2026-09-17T14:00:00+00:00")
            with self.assertRaisesRegex(subject.Stop, "STOP_CURRENT_PRE_PREDATES_FORMAL_EVIDENCE_START"):
                subject.run_real_formal_pre("20260919", old, temp / "g3", clock_utc=datetime(2026, 9, 19, 3, tzinfo=timezone.utc))
            mismatch = self._future_current_pre_fixture(temp / "mismatch", provenance_target_date="20260920")
            with self.assertRaisesRegex(subject.Stop, "STOP_CURRENT_PRE_AMBIGUOUS"):
                subject.run_real_formal_pre("20260919", mismatch, temp / "g4", clock_utc=datetime(2026, 9, 19, 3, tzinfo=timezone.utc))
            tampered = self._future_current_pre_fixture(temp / "tampered")
            provenance_path = tampered / "provenance.json"; provenance = json.loads(provenance_path.read_text(encoding="utf-8")); provenance["generated_at"] = "2026-09-17T00:00:00+00:00"; provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "SOURCE_PREDICTION_SHA_MISMATCH"):
                subject.run_real_formal_pre("20260919", tampered, temp / "tamper", clock_utc=datetime(2026, 9, 19, 3, tzinfo=timezone.utc))
            future = self._future_current_pre_fixture(temp / "future", target_date="20260920", generated_at="2026-09-18T15:00:00+00:00")
            output = subject.run_real_formal_pre("20260920", future, temp / "future_out", clock_utc=datetime(2026, 9, 18, 3, tzinfo=timezone.utc))
            self.assertTrue((output / "dual_pre_semantic.json").is_file())
            self.assertFalse((temp / "g2" / "20260919").exists()); self.assertFalse((temp / "g3" / "20260919").exists()); self.assertFalse((temp / "g4" / "20260919").exists())
        finally:
            shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
