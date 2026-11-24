from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from review import selection_authority_protocol_v1_january_2026_historical_pre as sut
from review import selection_authority_protocol_v1_pre_freeze as core


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_ROOT = ROOT / "reports" / "selection_authority_protocol_v1_january_2026_historical_holdout" / "current_pre"


def converged_payload() -> tuple[str, dict]:
    for day in sorted(PAYLOAD_ROOT.iterdir()):
        if not day.is_dir():
            continue
        index = json.loads((day / "race_index.json").read_text(encoding="utf-8"))["race_index"]
        for item in index:
            payload = json.loads((day / item["artifact"]).read_text(encoding="utf-8"))
            if payload["buy_gate_trace"]["race"]["shadow_race_state"] == "PLAY_CONVERGED":
                return day.name, payload
    raise AssertionError("PLAY_CONVERGED fixture not found")


class EqualProbabilityModel:
    def predict_proba(self, values):
        return np.asarray([[0.5, 0.5] for _ in values], dtype=float)


class IdentityScaler:
    def transform(self, values):
        return values


class JanuaryHistoricalPreTests(TestCase):
    def setUp(self):
        self.date, self.payload = converged_payload()
        protocol = core.load_frozen_protocol()
        self.model, self.scaler, self.identity = core.load_frozen_v5(protocol)

    def _payload_for_target_k(self, target_k: int, *, risk_fail: bool = False) -> dict:
        payload = copy.deepcopy(self.payload)
        for row in payload["ranked_results"]:
            row["buy"] = False
        for row in payload["ranked_results"][:target_k]:
            row["buy"] = True
        if risk_fail:
            for row in payload["buy_gate_trace"]["horses"]:
                row["risk_guard_pass"] = False
        return payload

    def _direct_adapted(self, payload: dict, model=None, scaler=None, source_sha: str = "1" * 64):
        adapted = copy.deepcopy(payload)
        date, venue, race_number = sut.parse_race_id(adapted["race_id"])
        adapted["venue"] = venue
        adapted["race_number"] = race_number
        return core._race_result(date, adapted, source_sha, model or self.model, scaler or self.scaler, self.identity)

    def test_race_identity_adapter_accepts_all_january_venues_and_rejects_invalid_forms(self):
        self.assertEqual(sut.parse_race_id("race_20260104_kyoto_7R"), ("20260104", "京都", 7))
        self.assertEqual(sut.parse_race_id("race_20260104_nakayama_7R"), ("20260104", "中山", 7))
        self.assertEqual(sut.parse_race_id("race_20260104_kokura_7R"), ("20260104", "小倉", 7))
        self.assertEqual(sut.parse_race_id("race_20260104_tokyo_7R"), ("20260104", "東京", 7))
        for race_id in ("race_20260104_kyoto_07R", "race_20260104_osaka_7R", "race_20260104_kyoto_7R_extra"):
            with self.assertRaisesRegex(core.Stop, "FAIL_CLOSED_RACE_IDENTITY_PARSE"):
                sut.parse_race_id(race_id)

    def test_semantic_equivalence_target_k_zero_one_two_three_and_risk_shortfall(self):
        for target_k, risk_fail in ((0, False), (1, False), (2, False), (3, False), (2, True)):
            with self.subTest(target_k=target_k, risk_fail=risk_fail):
                payload = self._payload_for_target_k(target_k, risk_fail=risk_fail)
                direct = self._direct_adapted(payload)
                actual = sut.process_race(self.date, payload, "1" * 64, self.model, self.scaler, self.identity)
                self.assertEqual(actual, direct)
                self.assertEqual(actual["shortfall"], max(0, target_k - actual["selected_n"]))

    def test_semantic_equivalence_tie_break_uses_shadow_rank_then_horse_number(self):
        payload = self._payload_for_target_k(3)
        model, scaler = EqualProbabilityModel(), IdentityScaler()
        direct = self._direct_adapted(payload, model=model, scaler=scaler, source_sha="2" * 64)
        actual = sut.process_race(self.date, payload, "2" * 64, model, scaler, self.identity)
        self.assertEqual(actual, direct)
        ordered = actual["horses"]
        expected = sorted(ordered, key=lambda row: (row["shadow_ai_rank"], row["horse_number"]))
        self.assertEqual([row["horse_number"] for row in ordered], [row["horse_number"] for row in expected])

    def test_result_field_injection_fails_closed(self):
        payload = self._payload_for_target_k(1)
        payload["finish"] = 1
        with self.assertRaisesRegex(core.Stop, "PRE_RESULT_FIELD_FORBIDDEN"):
            sut.process_race(self.date, payload, "3" * 64, self.model, self.scaler, self.identity)

    def test_authority_sha_mismatches_fail_closed_for_each_pinned_authority(self):
        for label in sut.EXPECTED:
            with self.subTest(label=label):
                expected = dict(sut.EXPECTED)
                expected[label] = "0" * 64
                with patch.object(sut, "EXPECTED", expected):
                    with self.assertRaisesRegex(core.Stop, f"JANUARY_AUTHORITY_SHA_MISMATCH:{label}"):
                        sut.verify_authorities()

    def test_model_version_mismatch_fails_closed(self):
        protocol = core.load_frozen_protocol()
        contract = protocol["model_contract"]
        metadata = {"version": "not-frozen"}
        with self.assertRaisesRegex(core.Stop, "MODEL_VERSION_MISMATCH"):
            core._validated_model_version(metadata, contract)

    def test_semantic_builder_is_byte_deterministic_and_result_free(self):
        one = sut.build_semantic()
        two = sut.build_semantic()
        self.assertEqual(sut.canonical_bytes(one), sut.canonical_bytes(two))
        self.assertIs(one["formal_evidence"], False)
        self.assertIs(one["not_prospective_evidence"], True)
        self.assertEqual(len(one["races"]), 149)
        self.assertEqual(sum(row["target_k"] for row in one["races"]), 141)

    def test_target_k_positive_requires_play_converged(self):
        payload = self._payload_for_target_k(1)
        payload["buy_gate_trace"]["race"]["shadow_race_state"] = "SKIP"
        result = sut.process_race(self.date, payload, "4" * 64, self.model, self.scaler, self.identity)
        self.assertEqual(result["race_status"], "NOT_RUN")
        self.assertEqual(result["not_run_reason"], "BUY_COUNT_GTE_1_BUT_RACE_STATE_NOT_PLAY_CONVERGED")
        self.assertEqual(result["horses"], [])
