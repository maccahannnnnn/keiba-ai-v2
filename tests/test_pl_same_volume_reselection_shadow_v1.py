import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from review import pl_same_volume_reselection_shadow_v1 as shadow


def fixture(k=2):
    horses=[{'horse_number':n,'horse_name':f'H{n}','rank':n,'past_race_count':n,'warnings':[],'risks':[]} for n in range(1,7)]
    traces=[{'horse_number':n,'absolute_quality_pass':True,'relative_advantage_pass':True,'effective_reliability_pass':True,'risk_guard_pass':n!=6} for n in range(1,7)]
    payload={'race_id':'race_20300101_tokyo_1R','ranked_results':horses,'top5':horses[:5],
             'buys':horses[:k],'buy_count':k,'buy_gate_trace':{'horses':traces,'race':{'shadow_race_state':'PLAY_CONVERGED'}}}
    # rank 1 is outside Current Top5 and fails the Current risk guard.
    order=[6,5,4,3,2,1];probs=[.75,.65,.55,.45,.35,.25]
    ph=[{'horse_number':n,'pl_top3_probability':p,'pl_race_rank':i} for i,(n,p) in enumerate(zip(order,probs),1)]
    return payload,{'race_id':payload['race_id'],'inference_status':'AVAILABLE','pl_probability_sum':3.0},ph


class ShadowTests(unittest.TestCase):
    def test_zero_and_one_two_three(self):
        for k in range(4):
            with self.subTest(k=k):
                p,r,h=fixture(k);result=shadow.build_race(p,r,h)
                self.assertEqual(result['treatment_buy_count'],k)
                self.assertEqual(result['treatment_selected_horses'],[6,5,4][:k])

    def test_full_field_outside_top5_and_risk_guard(self):
        p,r,h=fixture(1);out=shadow.build_race(p,r,h)
        row=next(x for x in out['horses'] if x['horse_number']==6)
        self.assertEqual(out['treatment_selected_horses'],[6]);self.assertFalse(row['current_top5_flag']);self.assertFalse(row['gate_statuses']['risk_guard_pass'])

    def test_inference_failure_no_fallback(self):
        p,r,h=fixture(2);r.update(inference_status='INFERENCE_UNAVAILABLE',reason='MISSING_REQUIRED_FEATURE')
        for x in h:x.update(pl_top3_probability=None,pl_race_rank=None)
        out=shadow.build_race(p,r,h);self.assertIsNone(out['treatment_selected_horses']);self.assertEqual(out['pl_inference_status'],'PL_INFERENCE_FAILED')
        p,r,h=fixture(0);r.update(inference_status='INFERENCE_UNAVAILABLE',reason='MISSING_REQUIRED_FEATURE')
        for x in h:x.update(pl_top3_probability=None,pl_race_rank=None)
        out=shadow.build_race(p,r,h);self.assertEqual(out['treatment_buy_count'],0);self.assertEqual(out['treatment_selected_horses'],[])

    def test_result_free_deterministic_and_complete(self):
        p,r,h=fixture(2);before=copy.deepcopy(p)
        with patch('pathlib.Path.read_bytes',side_effect=AssertionError('unexpected file read')):
            a=shadow.build_race(p,r,h);b=shadow.build_race(p,r,h)
        self.assertEqual(a,b);self.assertEqual(p,before)
        self.assertTrue({'race_state','pl_probability_sum','tie_exists','tie_break_rule','tie_break_values','horses'}<=a.keys())
        self.assertTrue({'current_top5_flag','gate_statuses','past_race_count','low_history_flags','pl_probability','pl_rank'}<=a['horses'][0].keys())

    def test_rank_or_probability_tamper_fails(self):
        p,r,h=fixture();h[0]['pl_race_rank']=4
        with self.assertRaisesRegex(shadow.Stop,'RANKING_MISMATCH'):shadow.build_race(p,r,h)

    def test_model_sha_check_fails_closed(self):
        with patch.object(shadow,'MODEL_SHA','0'*64):
            with self.assertRaisesRegex(shadow.Stop,'AUTHORITY_MISMATCH'):shadow.verify_authority()

    def test_pair_valid_and_invalid_sensitivity(self):
        p,r,h=fixture(2);race=shadow.build_race(p,r,h)
        results={n:{'valid_result':True,'actual_top3':n in (1,5,6)} for n in range(1,7)}
        row=shadow.paired_race(race,results);self.assertTrue(row['pair_valid']);self.assertEqual(row['race_top3_delta'],1)
        results[6]={'valid_result':False,'actual_top3':False};row=shadow.paired_race(race,results)
        self.assertFalse(row['pair_valid']);self.assertEqual(row['reason'],'VALID_SELECTED_COUNT_MISMATCH');self.assertEqual(row['sensitivity_delta_invalid_as_miss'],0)

    def test_environment_change_splits_block(self):
        a='a'*64;b='b'*64
        block=shadow.environment_block({'current_environment_fingerprint':b},a)
        self.assertTrue(block['change_detected']);self.assertEqual(block['previous_environment_fingerprint'],a)
        with self.assertRaisesRegex(shadow.Stop,'CROSS_BLOCK'):shadow.summarize_block([{'date':'1','block_fingerprint_sha256':a},{'date':'2','block_fingerprint_sha256':b}])

    def test_missing_trace_stops(self):
        p,r,h=fixture();del p['ranked_results'][0]['past_race_count']
        with self.assertRaisesRegex(shadow.Stop,'REQUIRED_TRACE'):shadow.build_race(p,r,h)

    def test_existing_production_and_current_are_not_mutated(self):
        paths=[shadow.DECISION,shadow.pl.MODEL_ROOT/shadow.pl.MODEL_FILE]
        before=[shadow.sha(x) for x in paths];p,r,h=fixture();old=copy.deepcopy(p)
        shadow.build_race(p,r,h);self.assertEqual(before,[shadow.sha(x) for x in paths]);self.assertEqual(old,p)

    def test_frozen_authority_and_selection_sha(self):
        shadow.verify_authority();p,r,h=fixture();out=shadow.build_race(p,r,h)
        self.assertEqual(shadow.canonical(out),shadow.canonical(shadow.build_race(p,r,h)))

    def test_timestamp_requires_timezone(self):
        with self.assertRaisesRegex(shadow.Stop,'TIMEZONE'):shadow.timestamp('2030-01-01T00:00:00')

    def test_cluster_bootstrap_reproducible(self):
        rows=[{'date':'1','pair_valid':True,'race_top3_delta':1},{'date':'2','pair_valid':True,'race_top3_delta':-1}]
        self.assertEqual(shadow.date_cluster_bootstrap(rows),shadow.date_cluster_bootstrap(rows))

    def test_no_evidence_without_approval(self):
        p,r,h=fixture();selection={'date':'20300101','races':[shadow.build_race(p,r,h)]}
        base=Path('no_output_should_be_created');auth=base/'authorization.json'
        with patch.object(shadow,'verify_authority'),patch.object(shadow,'sha',return_value='identity'),patch.object(Path,'read_text',return_value='{}'):
            with self.assertRaisesRegex(shadow.Stop,'NOT_AUTHORIZED'):
                shadow.freeze_pre(selection,base/'new',first_start_evidence=base/'schedule.json',first_start_evidence_sha='',authorization=auth,authorization_sha='identity')

    def test_post_rejects_freeze_hash_before_result_read(self):
        with patch.object(shadow,'verify_authority'),patch.object(shadow,'sha',return_value='actual'),patch('builtins.open',side_effect=AssertionError('must not open Result')):
            with self.assertRaisesRegex(shadow.Stop,'FREEZE_AUTHORITY_SHA'):
                shadow.post_from_frozen(Path('pre'),Path('result-a'),Path('result-b'),Path('new'),expected_freeze_sha256='wrong')

    def test_tie_rule_uses_horse_number(self):
        p,r,h=fixture(2)
        h[0]['pl_top3_probability']=h[1]['pl_top3_probability']=.7
        h[0]['pl_race_rank']=2;h[1]['pl_race_rank']=1
        x=shadow.build_race(p,r,h);self.assertEqual(x['treatment_selected_horses'],[5,6]);self.assertTrue(x['tie_exists'])

    def test_paired_exclusion_and_sensitivity_sign_warning(self):
        p,r,h=fixture(2);trace=shadow.build_race(p,r,h)
        positive={n:{'valid_result':True,'actual_top3':n in (1,5,6)} for n in range(1,7)}
        negative={n:{'valid_result':True,'actual_top3':n in (1,2)} for n in range(1,7)}
        negative[6]={'valid_result':False,'actual_top3':False}
        rows=[]
        for d,result in [('20300101',positive),('20300102',negative)]:
            row=shadow.paired_race(trace,result);row.update(date=d,results=result,race_trace=trace);rows.append(row)
        posts=[{'date':row['date'],'block_fingerprint_sha256':'one','races':[row]} for row in rows]
        summary=shadow.summarize_block(posts)
        self.assertEqual(summary['observed']['pair_valid_races'],1)
        self.assertEqual(summary['observed']['excluded_races'][0]['reason'],'VALID_SELECTED_COUNT_MISMATCH')
        self.assertEqual(summary['observed']['sensitivity_all_races_delta'],-1)
        self.assertTrue(summary['observed']['human_review_required'])
        rows[1]['sensitivity_delta_invalid_as_miss']=-1
        summary=shadow.summarize_block(posts)
        self.assertEqual(summary['observed']['sensitivity_all_races_delta'],0)
        self.assertTrue(summary['observed']['human_review_required'])

if __name__=='__main__':unittest.main()
