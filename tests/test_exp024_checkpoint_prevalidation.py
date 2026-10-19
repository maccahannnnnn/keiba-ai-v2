"""Synthetic protocol checkpoints; no historical or prospective Results."""
import unittest
from unittest.mock import patch
from review import pl_same_volume_reselection_shadow_v1 as s


def posts(days, races, current_hit, treatment_hit):
    out=[]
    for day in range(days):
        n=races//days+(day<races%days)
        rows=[{'date':f'203001{day+1:02}', 'race_id':f'r{day}_{i}', 'pair_valid':True,
               'current':{'hits':current_hit,'valid_count':1},
               'treatment':{'hits':treatment_hit,'valid_count':1},
               'race_top3_delta':treatment_hit-current_hit,
               'sensitivity_delta_invalid_as_miss':treatment_hit-current_hit} for i in range(n)]
        out.append({'date':f'203001{day+1:02}','block_fingerprint_sha256':'one','races':rows})
    return out


class CheckpointTests(unittest.TestCase):
    def evaluate(self, days,races,c,t,lower,mean):
        fake={'ci_lower':lower,'ci_upper':1.,'mean_delta':mean,'cluster':'DATE','iterations':10000,'seed':20261018}
        with patch.object(s,'date_cluster_bootstrap',return_value=fake),patch.object(s,'secondary_metrics',return_value={}):
            return s.summarize_block(posts(days,races,c,t))

    def test_01_11_days_100_races_no_checkpoint(self):self.assertIsNone(self.evaluate(11,100,0,1,1,1)['checkpoint_1'])
    def test_02_12_days_59_races_no_checkpoint(self):self.assertIsNone(self.evaluate(12,59,0,1,1,1)['checkpoint_1'])
    def test_03_first_checkpoint_exactly_once(self):
        x=self.evaluate(13,65,0,1,1,1);self.assertEqual(x['checkpoint_1']['dates'],12);self.assertIsNone(x['checkpoint_2_final'])
    def test_04_day8_never_passes_early(self):self.assertIsNone(self.evaluate(8,80,0,1,1,1)['checkpoint_1'])
    def test_05_kpi_pass_superiority_fail_extends(self):
        with patch.object(s,'secondary_metrics',return_value={}):x=s.summarize_block(posts(12,60,1,1))['checkpoint_1']
        self.assertTrue(x['kpi_gate']);self.assertFalse(x['superiority_gate']);self.assertEqual(x['verdict'],'NOT_PASSED')
    def test_06_kpi_fail_superiority_pass_extends(self):
        data=posts(12,60,0,1)
        for p in data:
            for r in p['races'][1:]:
                r['pair_valid']=False;r['reason']='VALID_SELECTED_COUNT_MISMATCH'
                r['treatment']['hits']=0;r['race_top3_delta']=0;r['sensitivity_delta_invalid_as_miss']=0
        with patch.object(s,'secondary_metrics',return_value={}):x=s.summarize_block(data)['checkpoint_1']
        self.assertFalse(x['kpi_gate']);self.assertTrue(x['superiority_gate']);self.assertEqual(x['verdict'],'NOT_PASSED')
    def test_07_both_pass(self):self.assertEqual(self.evaluate(12,60,0,1,1,1)['checkpoint_1']['verdict'],'SHADOW_CANDIDATE_PASS')
    def test_08_futility_warns_without_hold(self):
        x=self.evaluate(12,60,1,0,-1,-1)['checkpoint_1'];self.assertTrue(x['futility_warning']);self.assertEqual(x['verdict'],'NOT_PASSED')
    def test_09_23_dates_120_no_final(self):self.assertIsNone(self.evaluate(23,120,0,0,0,0)['checkpoint_2_final'])
    def test_10_24_dates_119_no_final(self):self.assertIsNone(self.evaluate(24,119,0,0,0,0)['checkpoint_2_final'])
    def test_11_cp2_both_pass_after_cp1_failure(self):
        rows=posts(24,120,0,1)
        for p in rows[:12]:
            for r in p['races']:r['treatment']['hits']=0;r['race_top3_delta']=0;r['sensitivity_delta_invalid_as_miss']=0
        def boot(rs):
            mean=sum(x['race_top3_delta'] for x in rs)/len(rs) if rs else 0
            return {'ci_lower':mean,'ci_upper':mean,'mean_delta':mean}
        with patch.object(s,'date_cluster_bootstrap',side_effect=boot),patch.object(s,'secondary_metrics',return_value={}):x=s.summarize_block(rows)
        self.assertEqual(x['checkpoint_1']['verdict'],'NOT_PASSED');self.assertEqual(x['checkpoint_2_final']['verdict'],'SHADOW_CANDIDATE_PASS')
    def test_12_cp2_fail_is_hold(self):self.assertEqual(self.evaluate(24,120,0,0,0,0)['checkpoint_2_final']['verdict'],'HOLD_NO_GO')
    def test_13_no_third_checkpoint(self):
        x=self.evaluate(25,125,0,0,0,0);self.assertEqual(x['checkpoint_2_final']['dates'],24);self.assertNotIn('checkpoint_3',x)
    def test_14_plus6_does_not_override_gate(self):
        x=self.evaluate(12,60,0,1,0,1)['checkpoint_1'];self.assertTrue(x['target_plus_6pt_reference']);self.assertEqual(x['verdict'],'NOT_PASSED')
    def test_15_plus6_not_required(self):
        data=posts(12,240,1,1)
        for p in data:
            r=p['races'][0];r['current']['hits']=0;r['race_top3_delta']=1;r['sensitivity_delta_invalid_as_miss']=1
        with patch.object(s,'secondary_metrics',return_value={}):x=s.summarize_block(data)['checkpoint_1']
        self.assertAlmostEqual(x['rate_difference'],.05);self.assertFalse(x['target_plus_6pt_reference']);self.assertEqual(x['verdict'],'SHADOW_CANDIDATE_PASS')
    def test_cross_block_rejected(self):
        x=posts(2,2,0,1);x[1]['block_fingerprint_sha256']='two'
        with self.assertRaisesRegex(s.Stop,'CROSS_BLOCK'):s.summarize_block(x)
    def test_sensitivity_opposite_sign_disables_pass(self):
        x=posts(12,60,0,1);x[0]['races'][0]['sensitivity_delta_invalid_as_miss']=-100
        with patch.object(s,'date_cluster_bootstrap',return_value={'ci_lower':1,'ci_upper':1,'mean_delta':1}),patch.object(s,'secondary_metrics',return_value={}):result=s.summarize_block(x)['checkpoint_1']
        self.assertTrue(result['human_review_required']);self.assertNotEqual(result['verdict'],'SHADOW_CANDIDATE_PASS')
    def test_date_cluster_bootstrap_protocol(self):
        rows=posts(3,6,0,1);rows=[r for p in rows for r in p['races']]
        a=s.date_cluster_bootstrap(rows);b=s.date_cluster_bootstrap(rows)
        self.assertEqual(a,b);self.assertEqual(a['cluster'],'DATE');self.assertEqual(a['iterations'],10000);self.assertEqual(a['seed'],20261018)
        self.assertEqual((a['mean_delta'],a['ci_lower'],a['ci_upper']),(1.,1.,1.))
