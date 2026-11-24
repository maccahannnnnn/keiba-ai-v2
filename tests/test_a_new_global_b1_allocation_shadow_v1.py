"""Isolated, Result-free checks for the independent A_new/B1 shadow."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from review import a_new_global_b1_allocation_shadow_v1 as subject
from review import b1_prospective_diagnostic_v1 as b1


DATE = "20261121"
TIME = datetime(2026, 11, 20, 1, tzinfo=timezone.utc)


def put(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(subject.canonical(payload))
    return subject.sha(path)


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "main"
        self.anew_root = Path(self.temp.name) / "anew"
        self.current = self.root / f"reports/prospective_prediction_{DATE}_formal_trace_v1"
        self.a_dir = self.anew_root / f"reports/a_new_prospective_shadow_v1/daily_pre/{DATE}"
        sources = {}
        for kind in ("DG", "DE", "DS"):
            path = self.root / f"data/raw/prediction_input/{kind}261121.CSV"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((kind + " synthetic input\n").encode())
            sources[kind] = {"path": str(path.relative_to(self.root)), "sha256": subject.sha(path)}
        input_sha = put(self.current / "input_manifest.json", {"date": DATE, "sources": sources})
        index, a_races, files = [], [], []
        for race_number, probabilities, buy_number in ((1, (.8, .7, .2), 1), (2, (.9, .6, .1), 1)):
            race_id = f"race_{DATE}_tokyo_{race_number}R"
            horses = [{"horse_number": number, "horse_name": f"馬{race_number}_{number}",
                       "a_new_p_top3": probability}
                      for number, probability in enumerate(probabilities, 1)]
            artifact = f"{race_id}_prediction.json"
            put(self.current / artifact, {"race_id": race_id, "ranked_results": [
                {"horse_number": h["horse_number"], "horse_name": h["horse_name"]} for h in horses]})
            files.append({"relative_path": artifact, "sha256": subject.sha(self.current / artifact)})
            index.append({"race_id": race_id, "artifact": artifact, "horse_count": 3, "buy_count": buy_number})
            a_races.append({"race_id": race_id, "current_k": buy_number, "horses": horses})
        put(self.current / "race_index.json", {"race_index": index})
        files += [{"relative_path": name, "sha256": subject.sha(self.current / name)}
                  for name in ("input_manifest.json", "race_index.json")]
        current_sha = put(self.current / "prediction_manifest.json", {"files": files})
        first_rel = f"reports/authority/first_start_{DATE}.json"
        first_sha = put(self.root / first_rel, {"date": DATE, "first_start_at": "2026-11-21T09:00:00+09:00",
                                                  "result_access": 0, "official_time_verified": False})
        put(self.current / "formal_freeze_attestation.json", {
            "date": DATE, "result_access_count": 0, "prediction_manifest_sha256": current_sha,
            "first_start_evidence_path": first_rel, "first_start_evidence_sha256": first_sha,
            "first_start_at": "2026-11-21T09:00:00+09:00",
            "freeze_timestamp_utc": "2026-11-20T00:00:00+00:00"})
        a_selection = {"date": DATE, "a_new_model_sha256": subject.MODEL_SHA,
                       "feature_generation_code_sha256": subject.ANEW_FEATURE_SHA,
                       "training_rows_sha256": subject.TRAINING_ROWS_SHA,
                       "current_pre_sha256": current_sha, "current_input_manifest_sha256": input_sha,
                       "result_access_count_at_pre_freeze": 0, "evidence_date": True,
                       "fallback_race_count": 0, "race_count": 2,
                       "source_identity": [{"kind": k, "sha256": v["sha256"]} for k, v in sources.items()],
                       "races": a_races}
        a_sha = put(self.a_dir / "selection.json", a_selection)
        put(self.a_dir / "freeze_manifest.json", {
            "date": DATE, "status": "FROZEN_PRE", "selection_sha256": a_sha,
            "result_access_count_at_freeze": 0, "freeze_timestamp_utc": "2026-11-20T00:01:00+00:00"})
        self.model_patch = patch.object(subject, "model_authority", return_value={"model_sha256": subject.MODEL_SHA})
        self.model_patch.start()
        self.addCleanup(self.model_patch.stop)

    def test_reuses_b1_global_allocation_and_is_deterministic(self):
        actual = subject.derive(DATE, root=self.root, a_root=self.anew_root)
        races = json.loads((self.a_dir / "selection.json").read_text(encoding="utf-8"))["races"]
        expected = b1.select_b1([{"race_id": r["race_id"], "current_k": r["current_k"],
                                  "horses": [{"horse_number": h["horse_number"], "horse_name": h["horse_name"],
                                              "candidate_p_top3": h["a_new_p_top3"]} for h in r["horses"]]}
                                 for r in races], 2)
        self.assertEqual([(h["race_id"], h["horse_number"]) for h in actual["selected_horses"]],
                         [(h["race_id"], h["horse_number"]) for h in expected])
        self.assertEqual(actual["selected_count"], 2)
        self.assertEqual(actual["result_access_count"], 0)
        self.assertEqual(actual, subject.derive(DATE, root=self.root, a_root=self.anew_root))

    def test_freeze_is_exclusive_and_sha_verified(self):
        result = subject.freeze_pre(DATE, root=self.root, a_root=self.anew_root, now=TIME)
        self.assertEqual(result["status"], "FROZEN_SHADOW_PRE")
        self.assertEqual(result["selection_sha256"], subject.sha(Path(result["selection_path"])))
        self.assertEqual(result["freeze_sha256"], subject.sha(Path(result["freeze_path"])))
        seal = json.loads(Path(result["freeze_path"]).read_text(encoding="utf-8"))
        self.assertEqual(seal["selection_sha256"], result["selection_sha256"])
        self.assertEqual(seal["prospective_evidence_credit"], 0)
        with self.assertRaisesRegex(subject.Stop, "STOP_SHADOW_OUTPUT_EXISTS"):
            subject.freeze_pre(DATE, root=self.root, a_root=self.anew_root, now=TIME)

    def test_after_cutoff_and_result_presence_stop_without_output(self):
        with self.assertRaisesRegex(subject.Stop, "STOP_SHADOW_AFTER_FREEZE_DEADLINE"):
            subject.freeze_pre(DATE, root=self.root, a_root=self.anew_root,
                               now=datetime(2026, 11, 21, 1, tzinfo=timezone.utc))
        self.assertFalse((self.root / f"reports/a_new_global_b1_allocation_shadow_v1/daily_pre/{DATE}").exists())
        result = self.root / f"data/raw/target/daily_result_list/着順馬番_{DATE}.csv"
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_bytes(b"synthetic result marker only")
        with self.assertRaisesRegex(subject.Stop, "STOP_SHADOW_RESULT_ALREADY_PRESENT"):
            subject.freeze_pre(DATE, root=self.root, a_root=self.anew_root, now=TIME)

    def test_frozen_source_tamper_stops(self):
        path = self.a_dir / "selection.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["races"][0]["horses"][0]["a_new_p_top3"] = .99
        put(path, payload)
        with self.assertRaisesRegex(subject.Stop, "STOP_A_NEW_FROZEN_AUTHORITY"):
            subject.derive(DATE, root=self.root, a_root=self.anew_root)

    def test_current_prediction_payload_tamper_stops(self):
        path = self.current / f"race_{DATE}_tokyo_1R_prediction.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["ranked_results"][0]["horse_name"] = "改変"
        put(path, payload)
        with self.assertRaisesRegex(subject.Stop, "STOP_CURRENT_PREDICTION_PAYLOAD_SHA"):
            subject.derive(DATE, root=self.root, a_root=self.anew_root)

    def test_source_code_and_model_shas_match_real_files(self):
        self.model_patch.stop()
        metadata = subject.model_authority(subject.ANEW_ROOT)
        self.assertEqual(metadata["model_sha256"], subject.MODEL_SHA)
        self.assertEqual(metadata["training_cutoff"], "2026-09-13")


if __name__ == "__main__":
    unittest.main()
