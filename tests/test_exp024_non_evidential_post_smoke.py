"""Checks the isolated, already-sealed development smoke; no source Result reads."""
import json
import unittest
from datetime import datetime
from pathlib import Path
from review import pl_same_volume_reselection_shadow_v1 as s

ROOT=s.ROOT/'reports/exp024_20261018_non_evidential_smoke_v3'


class NonEvidentialSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.selection=json.loads((ROOT/'selection_non_evidential.json').read_text(encoding='utf8'))
        cls.seal=json.loads((ROOT/'selection_sha_non_evidential.json').read_text(encoding='utf8'))
        cls.post=json.loads((ROOT/'post_non_evidential.json').read_text(encoding='utf8'))
        cls.summary=json.loads((ROOT/'daily_summary_non_evidential.json').read_text(encoding='utf8'))

    def test_selection_sealed_before_result_and_non_evidential(self):
        self.assertEqual(self.seal['sha256'],s.sha(ROOT/'selection_non_evidential.json'))
        self.assertFalse(self.seal['formal_freeze']);self.assertEqual(self.seal['evidence_count'],0)
        self.assertEqual(self.post['role'],'NON_EVIDENTIAL_END_TO_END_SMOKE')
        self.assertLess(datetime.fromisoformat(self.seal['recorded_at']),datetime.fromisoformat(self.post['result_read_timestamp']))

    def test_same_volume_unique_joins_and_pair_metrics(self):
        races=self.selection['races'];self.assertEqual(len(races),21)
        self.assertEqual(sum(r['current_buy_count'] for r in races),12)
        self.assertEqual(sum(r['treatment_buy_count'] for r in races),12)
        rows=self.post['races'];self.assertEqual(len({r['race_id'] for r in rows}),len(rows))
        for row in rows:
            results={int(k):v for k,v in row['results'].items()}
            recalc=s.paired_race(row['race_trace'],results)
            for field in ('pair_valid','current','treatment','race_top3_delta','sensitivity_delta_invalid_as_miss'):
                self.assertEqual(row[field],recalc[field])
        self.assertEqual(self.summary['observed']['pair_valid_races'],len(rows))
        self.assertEqual(self.post['pl_inference_coverage']['rate'],1.)

    def test_invalid_semantics_and_sensitivity(self):
        race={'race_id':'fixture','current_selected_horses':[1,2],'treatment_selected_horses':[2,3],'pl_inference_status':'AVAILABLE'}
        result={1:{'valid_result':True,'actual_top3':True},2:{'valid_result':True,'actual_top3':False},
                3:{'valid_result':False,'actual_top3':False}}
        row=s.paired_race(race,result)
        self.assertFalse(row['pair_valid']);self.assertEqual(row['reason'],'VALID_SELECTED_COUNT_MISMATCH')
        self.assertEqual(row['current']['valid_count'],2);self.assertEqual(row['treatment']['valid_count'],1)
        self.assertEqual(row['sensitivity_delta_invalid_as_miss'],-1)
