import unittest

from review.v4_model_v3_prospective_validator_v1 import (
    ProspectiveProtocolError, concentration, decision_state, phase_a_technical_correction_allowed, same_volume, selected_metric, validate_ledger,
)
from review.v4_model_v3_prospective_runner_v1 import select_same_volume


def horse(valid=True, top3=False): return {"valid_result": valid, "actual_top3": top3 if valid else False}
def rows(date, c, v): return {"date": date, "current": c, "v4": v}


class ProtocolTests(unittest.TestCase):
    def test_01_to_04_minimum(self):
        self.assertEqual("PASS", decision_state(60,12,.01,False,False)["gate"])
        self.assertEqual("NOT_EVALUATED", decision_state(59,12,.01,False,False)["gate"])
        self.assertEqual("NOT_EVALUATED", decision_state(60,11,.01,False,False)["gate"])
        self.assertEqual("NOT_EVALUATED", decision_state(100,10,.01,False,False)["gate"])
    def test_05_to_07_lift(self):
        self.assertEqual("PASS", decision_state(60,12,.01,False,False)["gate"])
        self.assertEqual("PASS", decision_state(60,12,0,False,False)["gate"])
        self.assertEqual("FAIL", decision_state(60,12,-.01,False,False)["gate"])
    def test_08_to_10_flags(self):
        self.assertIn("FRAGILITY", decision_state(60,12,.1,True,False)["state"])
        self.assertIn("CONCENTRATION", decision_state(60,12,.1,False,True)["state"])
        self.assertIn("FRAGILITY_AND_CONCENTRATION", decision_state(60,12,.1,True,True)["state"])
    def test_11_12_invalid_semantics(self):
        metric=selected_metric([horse(True,True),horse(False)])
        self.assertEqual((metric["valid_selected_count"],metric["invalid_selected_count"],metric["top3_hits"]),(1,1,1))
    def test_13_14_same_volume(self):
        same_volume({"r":[{}]}, {"r":[{}]})
        same_volume({"r":[]}, {"r":[]})
        with self.assertRaises(ProspectiveProtocolError): same_volume({"r":[]}, {"r":[{}]})
        selected = select_same_volume({"r":[{}], "z":[]}, {"r":[{"horse_number":2,"shadow_ai_rank":2,"predicted_actual_top3_probability":.5},{"horse_number":1,"shadow_ai_rank":1,"predicted_actual_top3_probability":.5}], "z":[{"horse_number":3,"shadow_ai_rank":1,"predicted_actual_top3_probability":.9}]})
        self.assertEqual((selected["r"][0]["horse_number"], selected["z"]), (1, []))
    def test_15_16_multi_shadow_no_cross_gate(self):
        self.assertNotIn("winner", __import__("review.v4_model_v3_prospective_validator_v1",fromlist=["*"]).__dict__)
    def test_17_18_quiet_stop(self):
        with self.assertRaises(ProspectiveProtocolError): validate_ledger({"evidence_role":"FORMAL_PROSPECTIVE_SHADOW_V4_MODEL_V3","state":"SUSPENDED","eligible_dates":[]})
    def test_19_20_decision_boundary(self):
        self.assertTrue(phase_a_technical_correction_allowed(aggregate_performance_disclosed=False,human_approved_scope=True,prediction_selection_semantics_unchanged=True))
        with self.assertRaises(ProspectiveProtocolError): phase_a_technical_correction_allowed(aggregate_performance_disclosed=True,human_approved_scope=True,prediction_selection_semantics_unchanged=True)
    def test_21_to_24_evidence_boundaries(self):
        with self.assertRaises(ProspectiveProtocolError): validate_ledger({"evidence_role":"FORMAL_PROSPECTIVE_SHADOW_V4_MODEL_V3","state":"NOT_STARTED","eligible_dates":["20260829"]})


if __name__ == "__main__": unittest.main()
