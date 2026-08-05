import unittest
from pathlib import Path

from review.diagnostic_safety_validator import ROOT, snapshot, validate

FIXTURES=ROOT/"reports"/"ranking_provenance"/"safety_fix_fixtures"


class DiagnosticSafetyValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FIXTURES.mkdir(parents=True,exist_ok=True)

    def fixture(self,name,source):
        path=FIXTURES/name;path.write_text(source,encoding="utf-8");return path

    def scan(self,path,**kwargs):
        return validate([path],before_hashes=snapshot(),require_operational_caller=False,**kwargs)

    def test_learning_write_detected(self):
        r=self.scan(self.fixture("learning_write.py",'from pathlib import Path\nPath("learning/x.json").write_text("x")\n'));self.assertEqual(r["learning_write_count"],1);self.assertEqual(r["status"],"FAIL")
    def test_human_review_write_detected(self):
        r=self.scan(self.fixture("human_write.py",'from pathlib import Path\nPath("reports/horse_review.csv").write_text("x")\n'));self.assertEqual(r["human_review_write_count"],1)
    def test_shadow_write_detected(self):
        r=self.scan(self.fixture("shadow_write.py",'from pathlib import Path\nPath("reports/shadow_validation/x.json").write_text("x")\n'));self.assertEqual(r["shadow_project_write_count"],1)
    def test_knowledge_write_detected(self):
        r=self.scan(self.fixture("knowledge_write.py",'from pathlib import Path\nPath("knowledge/meeting_bias/x.json").write_text("x")\n'));self.assertEqual(r["knowledge_write_count"],1)
    def test_target_trial_run_detected(self):
        r=self.scan(self.fixture("adapter_run.py",'from evaluation.target_trial_adapter import TargetTrialAdapter\nTargetTrialAdapter().run("a","b")\n'));self.assertEqual(r["diagnostic_target_trial_adapter_run_count"],1)
    def test_dangerous_import_detected(self):
        r=self.scan(self.fixture("dangerous_import.py",'from evaluation.target_trial_adapter import TargetTrialAdapter\n'));self.assertEqual(r["dangerous_diagnostic_import_count"],1)
    def test_post_writer_call_detected(self):
        r=self.scan(self.fixture("ranking_provenance_post_race_evaluator.py",'def f():\n write_weight_source([])\n'));self.assertEqual(r["post_path_writer_call_count"],1)
    def test_production_overwrite_detected(self):
        r=self.scan(self.fixture("overwrite.py",'from pathlib import Path\nPath("reports/pre_race/final_score.csv").write_text("x")\n'));self.assertEqual(r["existing_production_artifact_overwrite_count"],1)
    def test_main_execution_detected(self):
        r=self.scan(self.fixture("main_run.py",'import subprocess\nsubprocess.run(["python","main.py"])\n'));self.assertEqual(r["production_calculation_change_count"],1)
    def test_safe_fixture_passes(self):
        r=self.scan(self.fixture("safe.py",'value = 1\n'));self.assertEqual(r["status"],"PASS")
    def test_allowed_reports_write_passes(self):
        r=self.scan(self.fixture("allowed_write.py",'from pathlib import Path\nPath("reports/ranking_provenance/new.json").write_text("x")\n'));self.assertEqual(r["status"],"PASS")
    def test_unapproved_write_fails(self):
        r=self.scan(self.fixture("unapproved_write.py",'from pathlib import Path\nPath("data/unapproved.json").write_text("x")\n'));self.assertEqual(r["unauthorized_write_count"],1);self.assertEqual(r["status"],"FAIL")
    def test_adapter_variable_run_detected(self):
        r=self.scan(self.fixture("adapter_variable_run.py",'from evaluation.target_trial_adapter import TargetTrialAdapter\nadapter=TargetTrialAdapter()\nadapter.run("a","b")\n'));self.assertEqual(r["diagnostic_target_trial_adapter_run_count"],1)
    def test_zero_scan_targets_fail(self):
        r=validate([],before_hashes=snapshot(),require_operational_caller=False);self.assertEqual(r["status"],"FAIL")
    def test_missing_scan_target_fails(self):
        r=validate([FIXTURES/"absent.py"],before_hashes=snapshot(),require_operational_caller=False);self.assertEqual(r["status"],"FAIL")
    def test_hash_change_fails(self):
        before=snapshot();before["main.py"]="0"*64;r=validate([self.fixture("hash.py","x=1\n")],before_hashes=before,require_operational_caller=False);self.assertTrue(r["hash_changed"]);self.assertEqual(r["status"],"FAIL")
    def test_missing_protected_target_fails(self):
        r=validate([self.fixture("missing_protected.py","x=1\n")],before_hashes={"missing.txt":"MISSING"},protected_files=("missing.txt",),require_operational_caller=False);self.assertEqual(r["status"],"FAIL")
    def test_all_checks_have_evidence_fields(self):
        r=self.scan(self.fixture("fields.py","x=1\n"));self.assertTrue(all({"checked","method","target_count","finding_count","status","error"}<=set(x) for x in r["checks"]))
    def test_no_literal_zero_assignments(self):
        source=(ROOT/"review/diagnostic_safety_validator.py").read_text(encoding="utf-8");self.assertNotIn('"learning_write_count": 0',source)
    def test_real_phase_c2_revalidation_passes(self):self.assertEqual(validate(before_hashes=snapshot())["status"],"PASS")


if __name__=="__main__":unittest.main()
