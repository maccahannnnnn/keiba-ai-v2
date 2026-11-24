from __future__ import annotations

import hashlib
import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from review import full_field_redesign_iteration2_corrected_aggregation_v3 as v3

SANDBOX = ROOT / ".tmp" / "iteration2_v3_synthetic"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def row(*, date="20260301", race_id="race_20260301_tokyo_10R", horse=1, p_v5=.5, p_hgb=.2, p_pl=.3, shadow=1):
    return {"date": date, "race_id": race_id, "horse_number": horse, "p_v5": p_v5,
            "p_hgb": p_hgb, "p_pl": p_pl, "shadow_ai_rank": shadow}


class V3Tests(unittest.TestCase):
    def setUp(self):
        SANDBOX.mkdir(parents=True, exist_ok=True)
        self.dir = SANDBOX / self.id().split(".")[-1]
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_japanese_venue_canonical_join_and_outcome(self):
        calls = []
        def source(day):
            calls.append(day)
            return {("東京", 10): ["x"] * 12 + ["1", "取消"]}
        def outcome(raw, number):
            return (raw[11 + number].isdigit(), int(raw[11 + number]) if raw[11 + number].isdigit() else None,
                    raw[11 + number] in {"1", "2", "3"} if raw[11 + number].isdigit() else None)
        labels = v3.canonical_result_loader([row()], result_rows_fn=source, outcome_fn=outcome,
            parse_race_id_fn=lambda _: ("20260301", "tokyo", 10), japanese_venue={"tokyo": "東京"})
        label = labels[v3.ident(row())]
        self.assertEqual(calls, ["20260301"]); self.assertEqual(label["official_venue"], "東京")
        self.assertTrue(label["valid_result"]); self.assertTrue(label["actual_top3"])

    def test_wrong_date_stops_before_loader(self):
        calls = []
        with self.assertRaisesRegex(v3.Stop, "STOP_RESULT_DATE_MISMATCH"):
            v3.canonical_result_loader([row()], result_rows_fn=lambda _: calls.append(1), outcome_fn=lambda *_: (True, 1, True),
                parse_race_id_fn=lambda _: ("20260302", "tokyo", 10), japanese_venue={"tokyo": "東京"})
        self.assertEqual(calls, [])

    def test_wrong_venue_and_race_stop(self):
        with self.assertRaisesRegex(v3.Stop, "STOP_RESULT_VENUE_MISMATCH"):
            v3.canonical_result_loader([row()], result_rows_fn=lambda _: {}, outcome_fn=lambda *_: (True, 1, True),
                parse_race_id_fn=lambda _: ("20260301", "bad", 10), japanese_venue={"tokyo": "東京"})
        with self.assertRaisesRegex(v3.Stop, "STOP_RESULT_RACE_MISMATCH"):
            v3.canonical_result_loader([row()], result_rows_fn=lambda _: {("東京", 9): []}, outcome_fn=lambda *_: (True, 1, True),
                parse_race_id_fn=lambda _: ("20260301", "tokyo", 10), japanese_venue={"tokyo": "東京"})

    def test_v5_rank_tie_uses_inverse_shadow_rank(self):
        high_no_low_shadow = row(horse=9, p_v5=.5, shadow=1)
        low_no_high_shadow = row(horse=1, p_v5=.5, shadow=99)
        self.assertLess(v3.rank1_key(high_no_low_shadow, "V5_FULL_FIELD_TRAINED"),
                        v3.rank1_key(low_no_high_shadow, "V5_FULL_FIELD_TRAINED"))

    def test_daily_lexical_race_id_tie(self):
        ten = row(race_id="race_20260301_tokyo_10R", p_hgb=.5)
        two = row(race_id="race_20260301_tokyo_2R", p_hgb=.5)
        self.assertLess(v3.daily_key(ten, "CORRECTED_PLACKETT_LUCE"), v3.daily_key(two, "CORRECTED_PLACKETT_LUCE"))

    def test_v5_top5_missing_is_fail_closed(self):
        with self.assertRaisesRegex(v3.Stop, "STOP_V5_TOP5_REFERENCE_HORSE_MISSING"):
            v3.v5_top5_reference([v3.ident(row())], {})

    def test_evaluation_months_are_data_derived(self):
        rows = [row(date=f"20260{month}01") for month in range(3, 10)]
        self.assertEqual(v3.evaluation_months(rows), tuple(f"20260{month}" for month in range(3, 10)))
        with self.assertRaisesRegex(v3.Stop, "STOP_EVALUATION_MONTH_COUNT_UNEXPECTED"):
            v3.evaluation_months(rows[:-1])

    def test_prepare_manifest_once_and_no_result_parser(self):
        results = self.dir / "results"; results.mkdir()
        for name in ("馬番順着順_20260301.csv", "着順馬番_20260301.csv"):
            (results / name).write_bytes(b"identity-only")
        destination = self.dir / "identity.json"
        manifest = v3.prepare_result_identity_manifest([row()], destination=destination, result_root=results)
        self.assertFalse(manifest["PERFORMANCE_ROWS_PARSED"]); self.assertEqual(len(manifest["manifest_sha256"]), 64)
        with self.assertRaisesRegex(v3.Stop, "STOP_RESULT_SOURCE_MANIFEST_ALREADY_EXISTS"):
            v3.prepare_result_identity_manifest([row()], destination=destination, result_root=results)

    def test_approved_manifest_and_source_mutation_gate_before_loader(self):
        source = self.dir / "source.csv"; source.write_bytes(b"a")
        manifest = self.dir / "identity.json"
        v3._atomic_json(manifest, {"canonical_result_loader": v3.CANONICAL_RESULT_LOADER, "PERFORMANCE_ROWS_PARSED": False,
            "sources": [{"path": str(source), "filename": source.name, "bytes": 1, "sha256": digest(b"a")} ]})
        calls = []
        with self.assertRaisesRegex(v3.Stop, "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE"):
            v3.execute_atomic([row()], manifest_path=manifest, approved_sha="0" * 64,
                final_root=self.dir / "out0", temporary_root=self.dir / "tmp0", result_loader=lambda x: calls.append(x))
        self.assertEqual(calls, [])
        source.write_bytes(b"changed")
        with self.assertRaisesRegex(v3.Stop, "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE"):
            v3.execute_atomic([row()], manifest_path=manifest, approved_sha=v3.sha(manifest),
                final_root=self.dir / "out1", temporary_root=self.dir / "tmp1", result_loader=lambda x: calls.append(x))
        self.assertEqual(calls, [])

    def test_execute_never_rewrites_manifest_and_output_is_atomic(self):
        source = self.dir / "source.csv"; source.write_bytes(b"a")
        manifest = self.dir / "identity.json"
        v3._atomic_json(manifest, {"canonical_result_loader": v3.CANONICAL_RESULT_LOADER, "PERFORMANCE_ROWS_PARSED": False,
            "sources": [{"path": str(source), "filename": source.name, "bytes": 1, "sha256": digest(b"a")} ]})
        before = manifest.read_bytes()
        with self.assertRaises(ValueError):
            v3.execute_atomic([row()], manifest_path=manifest, approved_sha=v3.sha(manifest),
                final_root=self.dir / "fail", temporary_root=self.dir / "failtmp", result_loader=lambda _: (_ for _ in ()).throw(ValueError("boom")))
        self.assertFalse((self.dir / "fail").exists()); self.assertFalse((self.dir / "failtmp").exists()); self.assertEqual(before, manifest.read_bytes())
        output = v3.execute_atomic([row()], manifest_path=manifest, approved_sha=v3.sha(manifest),
            final_root=self.dir / "ok", temporary_root=self.dir / "oktmp", result_loader=lambda _: {v3.ident(row()): {"valid_result": True}})
        self.assertIn(v3.ident(row()), output); self.assertTrue((self.dir / "ok").is_dir()); self.assertFalse((self.dir / "oktmp").exists())

    def test_common_rank1_set(self):
        one = row(horse=1, p_v5=.9, p_hgb=.9, p_pl=.2, shadow=2)
        two = row(horse=2, p_v5=.8, p_hgb=.1, p_pl=.8, shadow=1)
        labels = {v3.ident(one): {"valid_result": True}, v3.ident(two): {"valid_result": True}}
        result = v3.full_race_rank1([one, two], labels)
        self.assertEqual({len(x) for x in result.values()}, {1})

    def test_model_probability_mapping_is_frozen(self):
        value = row(p_hgb=.11, p_pl=.88)
        self.assertEqual(v3.score(value, "CORRECTED_PLACKETT_LUCE"), .11)
        self.assertEqual(v3.score(value, "CORRECTED_HIST_GRADIENT_BOOSTING"), .88)

    def test_non_v5_rank_tie_uses_horse_number(self):
        self.assertLess(v3.rank1_key(row(horse=1, p_hgb=.5), "CORRECTED_PLACKETT_LUCE"),
                        v3.rank1_key(row(horse=9, p_hgb=.5), "CORRECTED_PLACKETT_LUCE"))

    def test_result_invalid_semantics_are_preserved_from_canonical_callback(self):
        labels = v3.canonical_result_loader([row()], result_rows_fn=lambda _: {("東京", 10): ["x"]},
            outcome_fn=lambda *_: (False, None, None), parse_race_id_fn=lambda _: ("20260301", "tokyo", 10),
            japanese_venue={"tokyo": "東京"})
        self.assertEqual(labels[v3.ident(row())]["valid_result"], False)
        self.assertIsNone(labels[v3.ident(row())]["actual_top3"])

    def test_manifest_requires_approved_sha(self):
        source = self.dir / "source.csv"; source.write_bytes(b"a")
        manifest = self.dir / "identity.json"
        v3._atomic_json(manifest, {"canonical_result_loader": v3.CANONICAL_RESULT_LOADER,
            "PERFORMANCE_ROWS_PARSED": False, "sources": []})
        with self.assertRaisesRegex(v3.Stop, "STOP_APPROVED_RESULT_MANIFEST_SHA_REQUIRED"):
            v3.verify_result_identity(manifest, None)

    def test_manifest_rejects_wrong_loader_identifier(self):
        manifest = self.dir / "identity.json"
        v3._atomic_json(manifest, {"canonical_result_loader": "wrong", "PERFORMANCE_ROWS_PARSED": False, "sources": []})
        with self.assertRaisesRegex(v3.Stop, "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE"):
            v3.verify_result_identity(manifest, v3.sha(manifest))

    def test_manifest_rejects_parsed_performance_claim(self):
        manifest = self.dir / "identity.json"
        v3._atomic_json(manifest, {"canonical_result_loader": v3.CANONICAL_RESULT_LOADER,
            "PERFORMANCE_ROWS_PARSED": True, "sources": []})
        with self.assertRaisesRegex(v3.Stop, "STOP_RESULT_SOURCE_CONFORMANCE_FAILURE"):
            v3.verify_result_identity(manifest, v3.sha(manifest))

    def test_final_and_temporary_roots_are_fail_closed(self):
        manifest = self.dir / "identity.json"
        v3._atomic_json(manifest, {"canonical_result_loader": v3.CANONICAL_RESULT_LOADER,
            "PERFORMANCE_ROWS_PARSED": False, "sources": []})
        final = self.dir / "final"; final.mkdir()
        with self.assertRaisesRegex(v3.Stop, "STOP_FINAL_OUTPUT_ALREADY_EXISTS"):
            v3.execute_atomic([row()], manifest_path=manifest, approved_sha=v3.sha(manifest), final_root=final,
                temporary_root=self.dir / "temp", result_loader=lambda _: {})
        shutil.rmtree(final)
        temporary = self.dir / "temp"; temporary.mkdir()
        with self.assertRaisesRegex(v3.Stop, "STOP_TEMP_OUTPUT_ALREADY_EXISTS"):
            v3.execute_atomic([row()], manifest_path=manifest, approved_sha=v3.sha(manifest), final_root=final,
                temporary_root=temporary, result_loader=lambda _: {})

    def test_success_snapshot_is_pre_result_and_hashed(self):
        root = self.dir / "snapshot"
        v3._write_snapshot(root, [row()])
        manifest = json.loads((root / "pre_result_selection_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["RESULT_ACCESS_COUNT_AT_FREEZE"], 0)
        self.assertEqual(manifest["selection_csv_sha256"], v3.sha(root / "pre_result_selected_horses.csv"))

    def test_common_rank1_excludes_invalid_race_for_every_model(self):
        valid = row(race_id="race_20260301_tokyo_1R")
        invalid = row(race_id="race_20260301_tokyo_2R")
        labels = {v3.ident(valid): {"valid_result": True}, v3.ident(invalid): {"valid_result": False}}
        ranked = v3.full_race_rank1([valid, invalid], labels)
        self.assertEqual({key for key in ranked["V5_FULL_FIELD_TRAINED"]}, {(valid["date"], valid["race_id"])})

    def test_frozen_gate_byte_identity_failure(self):
        prereg = self.dir / "p"; rat = self.dir / "r"; inp = self.dir / "input"; inp.mkdir()
        prereg.write_bytes(b"p"); rat.write_bytes(b"r"); (inp / "run_a_frozen.json").write_bytes(b"x"); (inp / "run_b_frozen.json").write_bytes(b"y")
        with self.assertRaisesRegex(v3.Stop, "STOP_RUN_B_SHA_MISMATCH"):
            v3.frozen_gate(inp, prereg=prereg, ratification=rat, expected_prereg=digest(b"p"),
                           expected_ratification=digest(b"r"), expected_run=digest(b"x"))

    def test_frozen_gate_budget_artifact_mismatch(self):
        prereg = self.dir / "p"; rat = self.dir / "r"; inp = self.dir / "input"; inp.mkdir(); budget = self.dir / "budget"
        prereg.write_bytes(b"p"); rat.write_bytes(b"r"); budget.write_bytes(b"budget")
        (inp / "run_a_frozen.json").write_bytes(b"x"); (inp / "run_b_frozen.json").write_bytes(b"x")
        with self.assertRaisesRegex(v3.Stop, "STOP_BUDGET_ARTIFACT_SHA_MISMATCH"):
            v3.frozen_gate(inp, prereg=prereg, ratification=rat, expected_prereg=digest(b"p"),
                           expected_ratification=digest(b"r"), expected_run=digest(b"x"), budget_artifact=budget,
                           expected_budget_sha="0" * 64)

    def test_prepare_manifest_records_only_identity_metadata(self):
        results = self.dir / "results"; results.mkdir()
        for name in ("馬番順着順_20260301.csv", "着順馬番_20260301.csv"):
            (results / name).write_bytes(b"one,two")
        output = v3.prepare_result_identity_manifest([row()], destination=self.dir / "manifest.json", result_root=results)
        self.assertEqual({"date", "path", "filename", "bytes", "sha256"}, set(output["sources"][0]))
        self.assertNotIn("rows", output["sources"][0])

    def test_verify_result_identity_accepts_unchanged_source(self):
        source = self.dir / "source.csv"; source.write_bytes(b"a")
        manifest = self.dir / "identity.json"
        v3._atomic_json(manifest, {"canonical_result_loader": v3.CANONICAL_RESULT_LOADER,
            "PERFORMANCE_ROWS_PARSED": False, "sources": [{"path": str(source), "filename": source.name,
            "bytes": 1, "sha256": digest(b"a")} ]})
        self.assertEqual(v3.verify_result_identity(manifest, v3.sha(manifest))["sources"][0]["sha256"], digest(b"a"))

    def test_frozen_gate_real_function_stops_before_result_loader(self):
        # Calls the real v3 gate, but uses synthetic frozen files and never a Result loader.
        prereg = self.dir / "p"; rat = self.dir / "r"; inp = self.dir / "input"; inp.mkdir()
        prereg.write_bytes(b"p"); rat.write_bytes(b"r"); (inp / "run_a_frozen.json").write_bytes(b"x"); (inp / "run_b_frozen.json").write_bytes(b"x")
        cases = [("prereg", "bad", digest(b"r"), digest(b"x")), ("rat", digest(b"p"), "bad", digest(b"x")),
                 ("run", digest(b"p"), digest(b"r"), "bad")]
        for _, psha, rsha, xsha in cases:
            with self.assertRaises(v3.Stop):
                v3.frozen_gate(inp, prereg=prereg, ratification=rat, expected_prereg=psha, expected_ratification=rsha, expected_run=xsha)


if __name__ == "__main__":
    unittest.main()
