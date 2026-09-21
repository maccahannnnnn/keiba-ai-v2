import csv
import json
import unittest
from pathlib import Path

from review import independent_race_selection_cumulative_tracker as tracker
from review import independent_race_selection_prospective_pre as pre
from review import independent_race_selection_prospective_post as post

ROOT=Path(__file__).resolve().parents[1]

class IndependentRaceSelectionTests(unittest.TestCase):
    def test_frozen_protocol_and_tau_rejection(self):
        protocol=pre.load_protocol()
        self.assertEqual(protocol['tau'],0.3796765822155326)
        self.assertNotEqual(protocol['tau'],0.37)
        self.assertFalse(protocol['tau_037']['accepted'])

    def test_pool_boundary_veto_state_and_max_three(self):
        rows=[{'horse_number':4,'current_top5':True,'shadow_ai_rank':2,'risk_guard_pass':True,'p_top3':.5},
              {'horse_number':3,'current_top5':True,'shadow_ai_rank':1,'risk_guard_pass':True,'p_top3':.5},
              {'horse_number':1,'current_top5':True,'shadow_ai_rank':1,'risk_guard_pass':False,'p_top3':.9},
              {'horse_number':5,'current_top5':False,'shadow_ai_rank':1,'risk_guard_pass':True,'p_top3':.9},
              {'horse_number':2,'current_top5':True,'shadow_ai_rank':3,'risk_guard_pass':True,'p_top3':.6},
              {'horse_number':6,'current_top5':True,'shadow_ai_rank':4,'risk_guard_pass':True,'p_top3':.7}]
        chosen=pre.select_rows(rows,.4)
        self.assertEqual([x['horse_number'] for x in chosen],[6,2,3])
        self.assertLessEqual(len(chosen),3)

    def test_result_leakage_guard(self):
        with self.assertRaises(pre.Stop): pre.assert_result_free({'actual_top3':True})

    def test_start_boundary_blocks_backfill(self):
        with self.assertRaises(pre.Stop) as stopped:
            pre.run('20260919',ROOT/'reports/daily_pre_prediction_20260920/current_frozen',ROOT/'reports/_test_independent_forbidden')
        self.assertEqual(str(stopped.exception),'STOP_START_BOUNDARY_G1')

    def test_invalid_result_is_excluded_without_substitution(self):
        row=['']*30; row[12]='取消'
        value=post.outcome(row,1)
        self.assertFalse(value['valid_result']); self.assertFalse(value['actual_top3']); self.assertIsNone(value['actual_finish'])

    def test_post_venue_map_supports_all_ten_jra_courses(self):
        expected={'sapporo':'札幌','hakodate':'函館','fukushima':'福島','niigata':'新潟','tokyo':'東京',
                  'nakayama':'中山','chuukyou':'中京','kyoto':'京都','hanshin':'阪神','kokura':'小倉'}
        self.assertEqual(post.VENUE,expected)
        for token,venue in expected.items():
            self.assertEqual(post.resolve_venue(token),venue)

    def test_post_race_id_parsing_for_required_venues(self):
        for token,venue in {'tokyo':'東京','kyoto':'京都','hanshin':'阪神','nakayama':'中山'}.items():
            self.assertEqual(post.race_result_key(f'race_20261003_{token}_12R'),(venue,12))

    def test_post_unknown_venue_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError,'STOP_UNKNOWN_VENUE_TOKEN:unknown'):
            post.resolve_venue('unknown')

    def test_historical_frozen_semantic_reproduction(self):
        path=ROOT/'reports/independent_race_selection_dev_diagnostic_v1/race_level_diagnostic.csv'
        with path.open(encoding='utf-8',newline='') as f: rows=list(csv.DictReader(f))
        chosen=[r for r in rows if r['model']=='v5' and r['selected']=='True']
        self.assertEqual(len({(r['date'],r['race_id']) for r in chosen}),492)
        self.assertEqual(len(chosen),791)
        self.assertEqual(sum(int(r['actual_top3']) for r in chosen),346)
        self.assertEqual(sum(int(r['actual_top3']) for r in chosen)/len(chosen),0.43742098609355246)

    def test_cumulative_boundaries_and_branches(self):
        base={'race_dates':['20260926','20260927'],'selected_races':30,'independent_hits':15,'independent_valid':30,'current_hits':12,'current_valid':30}
        self.assertEqual(tracker.decision([base]),'HOLD_ACCUMULATE')
        second={**base,'race_dates':['20261003','20261004'],'selected_races':29}
        self.assertEqual(tracker.decision([base,second]),'HOLD_ACCUMULATE')
        second['selected_races']=30
        self.assertEqual(tracker.decision([base,second]),'CONTROLLED_TRIAL_DISCUSSION_ACCEPT')
        bad={**second,'independent_hits':6,'current_hits':12}
        self.assertEqual(tracker.decision([base,bad]),'REJECT_CONTROLLED_TRIAL')

if __name__=='__main__': unittest.main()
