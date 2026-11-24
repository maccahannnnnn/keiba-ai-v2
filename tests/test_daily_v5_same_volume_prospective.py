import json
from pathlib import Path
import shutil
import unittest
import uuid

from review.daily_v5_same_volume_cumulative_tracker import evaluate
from review.daily_v5_same_volume_prospective_post import run as post_run, summarize_frozen_race
from review.daily_v5_same_volume_prospective_pre import assert_current_pre_target_date, load_assets, sha
from review.v4_model_v3_formal_prospective_day1_pre_v1 import _v4_record

ROOT = Path(__file__).resolve().parents[1]
CURRENT_0921 = ROOT / "reports/daily_pre_analysis_20260921/current_frozen"

class DailyV5SameVolumeProspectiveTest(unittest.TestCase):
    def test_current_pre_target_date_exact_match_and_mismatch(self):
        assert_current_pre_target_date("20260921", CURRENT_0921)
        with self.assertRaisesRegex(RuntimeError, "STOP_CURRENT_PRE_TARGET_DATE_MISMATCH"):
            assert_current_pre_target_date("20260926", CURRENT_0921)

    def test_daily_v5_parity_with_frozen_20260921_reference(self):
        model, scaler, _ = load_assets()
        reference = json.loads((ROOT / "reports/daily_pre_analysis_20260921/current_cf_v5_reference/v4_active_model_selection_manifest.json").read_text(encoding="utf-8"))
        expected = {item["race_id"]: item for item in reference["races"]}
        for item in json.loads((CURRENT_0921 / "race_index.json").read_text(encoding="utf-8"))["race_index"]:
            payload = json.loads((CURRENT_0921 / item["artifact"]).read_text(encoding="utf-8"))
            actual = _v4_record(date="20260921", payload=payload, model=model, scaler=scaler)
            if item["race_id"] in expected:
                self.assertEqual([x["horse_number"] for x in actual["selected_horses"]], [x["horse_number"] for x in expected[item["race_id"]]["selected_horses"]])

    def test_post_smoke_uses_frozen_difference_trace_and_invalid_semantics(self):
        race = {"race_id": "r", "field_size": 3, "scope_status": "ELIGIBLE", "difference_trace": {"current_selected": [1, 2], "daily_v5_selected": [1, 3]}}
        result = summarize_frozen_race(race, {1: "1", 2: "中止", 3: "3"})
        self.assertEqual(result["current"]["valid_selected_count"], 1)
        self.assertEqual(result["current"]["top3_count"], 1)
        self.assertEqual(result["daily_v5"]["top3_count"], 2)

    def test_post_runner_smoke_with_existing_non_20260926_fixture(self):
        model, scaler, protocol = load_assets()
        artifact = "race_20260921_hanshin_10R_prediction.json"
        payload = json.loads((CURRENT_0921 / artifact).read_text(encoding="utf-8"))
        race = _v4_record(date="20260921", payload=payload, model=model, scaler=scaler)
        race["field_size"] = len(payload["ranked_results"])
        current = [x["horse_number"] for x in payload["ranked_results"] if x.get("buy")]
        daily = [x["horse_number"] for x in race["selected_horses"]]
        race["difference_trace"] = {"current_selected": current, "daily_v5_selected": daily,
                                    "common": sorted(set(current) & set(daily)), "current_only": sorted(set(current) - set(daily)),
                                    "daily_v5_only": sorted(set(daily) - set(current))}
        selection = {"status": "SUCCESS", "date": "20260921", "protocol_sha256": sha(ROOT / "docs/daily_v5_same_volume_prospective_protocol_v1.json"),
                     "source_current_pre_manifest_sha256": sha(CURRENT_0921 / "prediction_manifest.json"), "races": [race]}
        result_root = ROOT / "data/raw/target/daily_result_list"
        tmp_root = ROOT / ".tmp" / f"daily_v5_post_smoke_{uuid.uuid4().hex}"
        try:
            tmp_root.mkdir(parents=True)
            pre_root = tmp_root / "daily_v5_pre"; pre_root.mkdir()
            (pre_root / "selection.json").write_text(json.dumps(selection), encoding="utf-8")
            output = post_run("20260921", pre_root, CURRENT_0921,
                              result_root / "馬番順着順_20260921.csv", result_root / "着順馬番_20260921.csv", tmp_root / "post")
            self.assertEqual(json.loads((output / "post.json").read_text(encoding="utf-8"))["status"], "SUCCESS")
        finally:
            if tmp_root.exists():
                shutil.rmtree(tmp_root)

    def test_tracker_excludes_pre_start_and_holds_before_minimum(self):
        with self.assertRaisesRegex(RuntimeError, "STOP_EVIDENCE_START_BOUNDARY"):
            evaluate([{"date": "20260921", "combined": {"current": {"valid_selected_count": 1, "top3_count": 1}, "daily_v5": {"valid_selected_count": 1, "top3_count": 1}}}])
        output = evaluate([{"date": "20260926", "eligible_selected_races": 1, "combined": {"current": {"valid_selected_count": 1, "top3_count": 1}, "daily_v5": {"valid_selected_count": 1, "top3_count": 1}}}])
        self.assertEqual(output["decision"], "HOLD")
        self.assertFalse(output["production_authorization"])
