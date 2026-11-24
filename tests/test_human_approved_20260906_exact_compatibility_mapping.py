from __future__ import annotations

import unittest

from review.target_bulk_prediction_input_adapter_v1 import (
    HUMAN_APPROVED_20260906_EXACT_EXCEPTION,
    HUMAN_APPROVED_20260906_SOURCE_SHA256,
    PredictionInputValidationError,
    RawSource,
    TargetBulkPredictionInputAdapterV1,
)


def _sources(overrides: dict[str, str] | None = None):
    values = dict(HUMAN_APPROVED_20260906_SOURCE_SHA256)
    values.update(overrides or {})
    return {
        kind: RawSource(kind, None, digest, "cp932", ",", False, {"DG": 11, "DE": 33, "DS": 50}[kind], 1)
        for kind, digest in values.items()
    }


def _rows(*, race: int = 11, de_name: str = "ファストネットワーク", ds_name: str = "ファストネットワー"):
    dg = [""] * 11
    dg[3], dg[4] = "阪神", str(race)
    de = [""] * 33
    de[1], de[2], de[3], de[7], de[8], de[18], de[20] = "阪神", str(race), "8", de_name, "セ", "20190007", "Magic Albert"
    ds = [""] * 50
    ds[16], ds[17], ds[46] = ds_name, "セ", "Magic Albert"
    return {"DG": [dg], "DE": [de], "DS": [ds]}


def _apply(rows=None, *, date="20260906", sources=None):
    return TargetBulkPredictionInputAdapterV1()._apply_human_approved_exact_exception(
        rows=rows or _rows(), sources=sources or _sources(), date=date,
        compatibility_exception=HUMAN_APPROVED_20260906_EXACT_EXCEPTION,
    )


class ExactCompatibilityMappingTest(unittest.TestCase):
    def test_exact_mapping_applies_once_and_reconciles_name_set(self):
        rows = _rows()
        record = _apply(rows)
        self.assertEqual(record["mapping_count"], 1)
        self.assertEqual(rows["DS"][0][16], "ファストネットワーク")
        self.assertEqual({row[7].strip() for row in rows["DE"]}, {row[16].strip() for row in rows["DS"]})

    def test_exact_scope_guard_rejects_any_non_exact_context(self):
        for kwargs in [
            {"date": "20260907"},
            {"sources": _sources({"DS": "0" * 64})},
            {"rows": _rows(race=10)},
            {"rows": _rows(de_name="ファストネットワーX")},
            {"rows": _rows(ds_name="ファストネットワークX")},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(PredictionInputValidationError):
                _apply(**kwargs)

    def test_prefix_like_second_de_name_is_rejected_as_collision(self):
        rows = _rows()
        second = list(rows["DE"][0])
        second[3], second[7], second[18] = "9", "ファストネットワーX", "20190008"
        rows["DE"].append(second)
        with self.assertRaises(PredictionInputValidationError):
            _apply(rows)
