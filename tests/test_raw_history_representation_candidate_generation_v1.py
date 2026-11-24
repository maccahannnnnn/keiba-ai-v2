import unittest

from review.raw_history_representation_candidate_generation_v1 import (
    CLASSIFICATIONS, HISTORY_DEPTH, INCLUDED_NUMERIC, clean_name, history_vector,
    exact5_order_key, optional_number, raw_feature_names, vector,
)
import review.candidate_generation_stage_a_paired_population_expanded_v1 as stage_a


def row(date=(25,1,1), abnormal="0", finish="1"):
    value=[""]*50
    value[0],value[1],value[2]=map(str,date); value[14]="1200"; value[16]=" Horse "; value[20]="55.0"
    value[21]="16"; value[23]=finish; value[25]=abnormal; value[26]="0.3"; value[27]="2"
    value[28]="70.1"; value[30]="95"; value[31:35]=["1","2","3","4"]; value[35]="34.2"
    value[36]="35.0"; value[37]="480"; value[38]="+2"; value[41]="500"; value[48]="51.2"; value[49]="49.8"
    return value


class RawHistoryTests(unittest.TestCase):
    def test_01_depth(self): self.assertEqual(HISTORY_DEPTH,10)
    def test_02_feature_order(self): self.assertEqual(raw_feature_names()[0],"HIST_01_PRESENT")
    def test_03_feature_count(self): self.assertEqual(len(raw_feature_names()),10*(1+2*len(INCLUDED_NUMERIC)))
    def test_04_all_columns_classified(self): self.assertEqual(set(CLASSIFICATIONS),set(range(50)))
    def test_05_person_excluded(self): self.assertEqual(CLASSIFICATIONS[19],"PERSON_OR_PEDIGREE_EXCLUDE")
    def test_06_identifier_excluded(self): self.assertEqual(CLASSIFICATIONS[16],"IDENTIFIER_ONLY_EXCLUDE")
    def test_07_date_not_predictor(self): self.assertNotIn(0,{x[1] for x in INCLUDED_NUMERIC})
    def test_08_optional_missing(self): self.assertEqual(optional_number("-"),(0.0,1.0))
    def test_09_optional_plus(self): self.assertEqual(optional_number("+2"),(2.0,0.0))
    def test_10_name_normalization(self): self.assertEqual(clean_name(" 馬　名 "),"馬名")
    def test_11_history_recent_first(self):
        values,stats=history_vector([row((24,1,1)),row((25,1,1))],"20260101")
        self.assertEqual(stats["used"],2); self.assertEqual(values[1],1200.0)
    def test_12_missing_slot_zero(self):
        values,stats=history_vector([],"20260101")
        self.assertEqual(stats["used"],0); self.assertTrue(all(x==0 for x in values))
    def test_13_same_day_rejected(self):
        _values,stats=history_vector([row((26,1,1))],"20260101")
        self.assertEqual(stats["date_rejected"],1)
    def test_14_abnormal_not_eligible(self):
        _values,stats=history_vector([row((25,1,1),"中止","0")],"20260101")
        self.assertEqual(stats["eligible"],0)
    def test_15_present_indicator(self):
        values,_=history_vector([row((25,1,1))],"20260101")
        self.assertEqual(values[0],1.0)
    def test_16_tie_probability_then_shadow_rank(self):
        rows=[{"probability":.5,"shadow_ai_rank":2,"horse_number":1},{"probability":.5,"shadow_ai_rank":1,"horse_number":9}]
        self.assertEqual(sorted(rows,key=exact5_order_key)[0]["horse_number"],9)
    def test_17_tie_horse_number_last(self):
        rows=[{"probability":.5,"shadow_ai_rank":1,"horse_number":2},{"probability":.5,"shadow_ai_rank":1,"horse_number":1}]
        self.assertEqual(sorted(rows,key=exact5_order_key)[0]["horse_number"],1)
    def test_18_fold_train_eval_disjoint(self):
        for _name,train,eval_ in stage_a.FOLD_SPEC:
            train_dates={d for m in train for d in stage_a.MONTHS[m]}; eval_dates={d for m in eval_ for d in stage_a.MONTHS[m]}
            self.assertFalse(train_dates & eval_dates)
    def test_19_rich_appends_to_existing_twenty_semantics(self):
        item={name:(True if name in stage_a.GATES else 1.0) for name in stage_a.FEATURES[:-1]}
        item["race_state"]="PLAY_CONVERGED"; item["raw_history_vector"]=[0.0]*len(raw_feature_names())
        self.assertEqual(len(vector(item,True)),21+len(raw_feature_names()))
    def test_20_control_stays_base_only(self):
        item={name:(True if name in stage_a.GATES else 1.0) for name in stage_a.FEATURES[:-1]}
        item["race_state"]="PLAY_CONVERGED"; item["raw_history_vector"]=[9.0]*len(raw_feature_names())
        self.assertEqual(len(vector(item,False)),21)
    def test_21_first_five_not_duplicated_into_empty_slots(self):
        values,_=history_vector([row((25,1,1))],"20260101")
        per_slot=1+2*len(INCLUDED_NUMERIC)
        self.assertTrue(all(x==0 for x in values[per_slot:]))
    def test_22_history_vector_deterministic(self):
        rows=[row((25,1,2)),row((25,1,1))]
        self.assertEqual(history_vector(rows,"20260101")[0],history_vector(rows,"20260101")[0])


if __name__ == "__main__": unittest.main()
