import json
import unittest
import uuid
from pathlib import Path

from review.date_exclusivity_validator_v1 import collect_evidence_dates, validate


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class DateExclusivityValidatorV1Tests(unittest.TestCase):
    def build_authorities(self, root: Path) -> None:
        write_json(root / "reports/ml_v4_buy_selection_dataset_v2/source_date_inventory.json", {"v1_dates": ["20260620"]})
        write_json(root / "reports/may_2026_multi_system_oos_v1/pre_retry_v5/source_manifest.json", {"sources": [{"date": "20260502"}]})
        (root / "reports/april_2026_retrospective_external_holdout_v2/pre_execution_full_8date_v1/prediction/20260404").mkdir(parents=True)
        write_json(root / "reports/shadow_cf_top3_rank_anchored_v1/protocol.json", {"pre_protocol_context_dates": ["20260822", "20260823"]})
        write_json(root / "reports/prospective_three_system_20260829_v1_retry2/cf_selection_manifest.json", {"date": "20260829", "evidence_role": "FORMAL_PROSPECTIVE_SHADOW"})
        write_json(root / "reports/prospective_three_system_20260829_v1_retry2/v4_model_v3_reference_selection_manifest.json", {"date": "20260829", "evidence_role": "REFERENCE_SHADOW_ONLY_PENDING_HISTORICAL_GATE"})

    def test_context_dates_are_collected_and_march_is_clean(self) -> None:
        root = Path("tests/.date_exclusivity_validator_tmp") / uuid.uuid4().hex
        try:
            self.build_authorities(root)
            result = validate(["20260301", "20260307"], collect_evidence_dates(root))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["overlap_count"], 0)
            self.assertEqual(result["used_target_date_sets"]["prospective_shadow"], ["20260822", "20260823", "20260829"])
            self.assertEqual(result["used_target_date_sets"]["reference_shadow_only"], ["20260829"])
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)

    def test_known_prospective_shadow_overlap_fails(self) -> None:
        root = Path("tests/.date_exclusivity_validator_tmp") / uuid.uuid4().hex
        try:
            self.build_authorities(root)
            result = validate(["20260822"], collect_evidence_dates(root))
            self.assertEqual(result["status"], "FAIL_DATE_EXCLUSIVITY_CONFLICT")
            self.assertEqual(result["overlap_dates"], ["20260822"])
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)
