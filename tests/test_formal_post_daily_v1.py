"""No live POST writes: coordinator regression and fail-closed tests."""

import unittest
import tempfile
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from review import formal_post_daily_v1 as daily
from review import formal_post_backfill_20261031_20261101 as old


class FormalPostDailyTests(unittest.TestCase):
    def test_historical_backfill_regression(self):
        audit = old.preflight()
        for date in old.DATES:
            self.assertEqual(audit[date]["crosscheck_status"], "PASS")
            pre = daily.validated_pre(date)
            sources, digests = daily.result_sources(date)
            self.assertEqual(digests, audit[date]["result"]["source_sha256"])
            for lane in ("PL_JOCKEY", "CURRENT_RANK1"):
                self.assertEqual(daily.metrics(daily.joined(date, lane, pre, sources)),
                                 audit[date]["metrics"][lane])

    def test_1101_current_from_exp024_matches_frozen_selection(self):
        date = "20261101"
        pre = daily.validated_pre(date)
        exp = daily.read_json(daily.ROOT / f"reports/exp024_pl_same_volume/{date}_post/post.json")
        plj = daily.read_json(Path(pre["PL_JOCKEY"]["path"]))
        rows = daily.current_rows_from_exp024(exp, plj)
        self.assertEqual(daily.metrics(rows), old.preflight()[date]["exp024_current"])
        sources, digests = daily.result_sources(date)
        plj_rows = daily.joined(date, "PL_JOCKEY", pre, sources)
        day = daily.verified_day(date, pre, plj_rows, rows, digests, parent_suspended=False)
        self.assertEqual(day["plj_slots"], day["current_slots"])
        self.assertEqual(day["delta_hits"], day["plj_rule_a_hits"] - day["current_rule_a_hits"])

    def test_1101_candidate_post_projection_matches_existing_daily_values(self):
        date = "20261101"
        expected = daily.read_json(daily.ROOT / "reports/20261101_full_post_evaluation_v1/post_evaluation_20261101.json")
        roots = {
            "EXP024": (daily.ROOT / f"reports/exp024_pl_same_volume/{date}_post/post.json",
                       daily.ROOT / f"reports/exp024_pl_same_volume/{date}_pre/selection.json"),
            "A_NEW": (daily.ANEW / f"reports/a_new_prospective_shadow_v1/daily_post/{date}/post.json",
                      daily.ANEW / f"reports/a_new_prospective_shadow_v1/daily_pre/{date}/selection.json"),
            "E1": (daily.E1 / f"reports/e1_full_field_allocation_prospective_shadow_v1/daily_post/{date}/post.json",
                   daily.E1 / f"reports/e1_full_field_allocation_prospective_shadow_v1/daily_pre/{date}/selection.json"),
        }
        for lane, (post, pre) in roots.items():
            rows = daily.selected_rows_from_post(lane, daily.read_json(post), daily.read_json(pre))
            self.assertEqual(daily.metrics(rows), expected["lane_performance"][lane])

    def test_1101_full_seven_lane_preflight(self):
        audit = daily.preflight("20261101")
        self.assertEqual(set(audit["pre"]), set(daily.LANES))
        self.assertEqual((audit["eligible_races"], audit["eligible_horses"]), (13, 174))

    def test_1107_prewrite_preflight_covers_seven_lanes_and_detects_e1_copy_need(self):
        audit = daily.preflight("20261107")
        self.assertEqual(set(audit["pre"]), set(daily.LANES))
        self.assertEqual((audit["eligible_races"], audit["eligible_horses"]), (19, 275))
        self.assertEqual(audit["e1_result_preparation"]["status"], "COPY_REQUIRED")

    def test_1031_missing_a_new_is_not_synthesized(self):
        with self.assertRaisesRegex(daily.Stop, "STOP_SOURCE_MISSING"):
            daily.preflight("20261031")

    def test_e1_runtime_loader_is_worktree_not_main(self):
        authority = daily.e1_result_authority()
        self.assertEqual(Path(authority["actual_loader_root"]), daily.E1.resolve())
        self.assertNotEqual(Path(authority["actual_loader_root"]), daily.ROOT.resolve())
        self.assertEqual(Path(authority["main_declared"]), daily.ROOT.resolve())

    def test_e1_result_copy_and_matching_reuse_is_non_overwriting(self):
        with tempfile.TemporaryDirectory(dir=daily.ROOT) as temp:
            source = Path(temp) / "source"
            dest = Path(temp) / "dest"
            source.mkdir()
            expected = {}
            for kind, prefix in (("horse_order", "馬番順着順"), ("finish_order", "着順馬番")):
                path = source / f"{prefix}_20261201.csv"
                path.write_bytes(kind.encode("ascii"))
                expected[kind] = hashlib.sha256(path.read_bytes()).hexdigest()
            authority = {"actual_result_root": str(dest), "actual_loader_file": "fixture"}
            with patch.object(daily, "RESULT_ROOT", source):
                self.assertEqual(daily.prepare_e1_result_pair("20261201", expected, authority,
                                                              copy_missing=False)["status"], "COPY_REQUIRED")
                self.assertEqual(daily.prepare_e1_result_pair("20261201", expected, authority,
                                                              copy_missing=True)["status"], "COPIED")
                self.assertEqual(daily.prepare_e1_result_pair("20261201", expected, authority,
                                                              copy_missing=True)["status"], "REUSED_MATCHING")
                (dest / "馬番順着順_20261201.csv").write_bytes(b"changed")
                with self.assertRaisesRegex(daily.Stop, "STOP_E1_EXISTING_RESULT_SHA"):
                    daily.prepare_e1_result_pair("20261201", expected, authority, copy_missing=True)

    def test_1107_real_result_pair_is_identical_in_isolated_e1_destination(self):
        with tempfile.TemporaryDirectory(dir=daily.ROOT) as temp:
            authority = {"actual_result_root": temp, "actual_loader_file": "isolated-fixture"}
            _, digests = daily.result_sources("20261107")
            receipt = daily.prepare_e1_result_pair("20261107", digests, authority, copy_missing=True)
            self.assertEqual(receipt["status"], "COPIED")
            daily.verify_e1_result_content("20261107", digests, authority)

    def test_1107_isolated_seven_lane_post_and_safe_reexecution(self):
        date = "20261107"
        audit = daily.preflight(date)
        with tempfile.TemporaryDirectory(dir=daily.ROOT) as temp:
            base = Path(temp)
            a_out = base / "a_new"
            e_out = base / "e1"
            shutil.copytree(daily.ANEW / "reports/a_new_prospective_shadow_v1", a_out)
            shutil.copytree(daily.E1 / "reports/e1_full_field_allocation_prospective_shadow_v1", e_out)
            result_root = base / "e1_source/data/raw/target/daily_result_list"
            authority = {"actual_result_root": str(result_root), "actual_loader_file": "isolated-e1-loader"}
            self.assertEqual(daily.prepare_e1_result_pair(date, audit["result_sha256"], authority,
                                                           copy_missing=False)["status"], "COPY_REQUIRED")
            daily.prepare_e1_result_pair(date, audit["result_sha256"], authority, copy_missing=True)
            daily.verify_e1_result_content(date, audit["result_sha256"], authority)
            audit["e1_result_authority"] = authority
            exp_post = base / "exp024/post.json"
            from review.pl_same_volume_reselection_shadow_v1 import post_from_frozen
            post_from_frozen(daily.ROOT / f"reports/exp024_pl_same_volume/{date}_pre",
                             daily.RESULT_ROOT / f"馬番順着順_{date}.csv",
                             daily.RESULT_ROOT / f"着順馬番_{date}.csv", exp_post.parent,
                             expected_freeze_sha256=audit["pre"]["EXP024"]["freeze_sha256"])
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            for worktree, script_name, output, extra in (
                (daily.ANEW, "a_new_prospective_evidence_v1.py", a_out, ""),
                (daily.E1, "e1_full_field_allocation_evidence_v1.py", e_out, str(exp_post)),
            ):
                code = (
                    "import importlib.util,sys; from pathlib import Path; "
                    "p=Path(sys.argv[1]); s=importlib.util.spec_from_file_location('isolated_lane',p); "
                    "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                    "m.OUT=Path(sys.argv[2]); "
                    "m.result_rows.__globals__['ROOT']=Path(sys.argv[3]) if sys.argv[4] else m.result_rows.__globals__['ROOT']; "
                    "m.post_date('20261107',exp024_post_path=Path(sys.argv[4])) if sys.argv[4] else m.post_date('20261107')"
                )
                result = subprocess.run([sys.executable, "-c", code, str(worktree / "review" / script_name),
                                         str(output), str(base / "e1_source"), extra],
                                        cwd=worktree, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr[-1500:])
            lane_paths = {
                "EXP024": exp_post,
                "PL_JOCKEY": base / "plj/post.json",
                "CURRENT_RANK1": base / "rank1/post.json",
                "A_NEW": a_out / f"daily_post/{date}/post.json",
                "E1": e_out / f"daily_post/{date}/post.json",
                "INDEPENDENT_V5": base / "independent/summary.json",
            }
            with patch.object(daily, "OUT", base / "formal"), \
                 patch.object(daily, "STATE_ROOT", base / "formal_state"), \
                 patch.object(daily, "lane_post_paths", return_value=lane_paths):
                previous, state = daily.state_chain_preflight(base / "formal_state", date)
                actual_write = daily.write_forward_post
                def interrupted_write(write_date, lane, write_audit, rows, path):
                    if lane == "CURRENT_RANK1":
                        raise RuntimeError("SIMULATED_INTERRUPTION")
                    return actual_write(write_date, lane, write_audit, rows, path)
                with patch.object(daily, "write_forward_post", side_effect=interrupted_write):
                    with self.assertRaisesRegex(RuntimeError, "SIMULATED_INTERRUPTION"):
                        daily.execute(date, audit, previous, state, parent_status="ACTIVE")
                self.assertTrue(lane_paths["PL_JOCKEY"].is_file())
                self.assertFalse((base / f"formal/{date}/complete.json").exists())
                original_forward = lane_paths["PL_JOCKEY"].read_bytes()
                tampered = json.loads(original_forward)
                tampered["role"] = "WRONG_ROLE"
                lane_paths["PL_JOCKEY"].write_text(json.dumps(tampered), encoding="utf-8")
                with self.assertRaisesRegex(daily.Stop, "STOP_RESUME_ARTIFACT_MISMATCH"):
                    daily.execute(date, audit, previous, state, parent_status="ACTIVE")
                self.assertFalse(lane_paths["CURRENT_RANK1"].exists())
                lane_paths["PL_JOCKEY"].write_bytes(original_forward)
                completed = daily.execute(date, audit, previous, state, parent_status="ACTIVE")
                self.assertEqual(completed["status"], "COMPLETE")
                summary = daily.read_json(base / f"formal/{date}/lane_summary.json")
                self.assertEqual((len(summary["lane_metrics"]), summary["selected_rows"]), (7, 64))
                self.assertEqual((audit["eligible_races"], audit["eligible_horses"]), (19, 275))
                self.assertTrue((base / f"formal_state/{date}_verified_day.json").is_file())
                previous, state = daily.state_chain_preflight(base / "formal_state", date,
                                                               allow_existing=True)
                self.assertEqual(daily.execute(date, audit, previous, state,
                                               parent_status="ACTIVE")["status"],
                                 "ALREADY_COMPLETE_UNCHANGED")
                for pre in audit["pre"].values():
                    self.assertEqual(daily.sha(Path(pre["path"])), pre["sha256"])
                self.assertEqual(daily.result_sources(date)[1], audit["result_sha256"])
                # A synthetic earlier verified day makes the same frozen 11/07
                # inputs exercise the second-day parent-inheritance path.
                second_root = base / "second_day_state"
                with patch.object(daily, "STATE_ROOT", second_root), \
                     patch.object(daily, "OUT", base / "second_day_formal"):
                    prior_race = "race_20261106_tokyo_1R"
                    prior_day = {"date": "2026-11-06", "role": "PROSPECTIVE_ELIGIBLE",
                                 "pre_frozen_before_result": True, "result_join_verified": True,
                                 "parent_suspended": False,
                                 "pre_races": [{"race_id": prior_race, "current_k": 1,
                                                "candidate_k": 1, "candidate_selected_horses": [1],
                                                "current_selected_horses": [1]}],
                                 "current_buy_counts": {prior_race: 1}, "plj_slots": 1,
                                 "current_slots": 1, "plj_valid_n": 1,
                                 "plj_valid_hits": 1, "delta_hits": 0}
                    _, prior_state = daily.write_state_event("20261106", second_root, None, prior_day)
                    second_state = second_root / f"{date}_state.json"
                    complete_path = base / f"second_day_formal/{date}/complete.json"
                    original_open = Path.open
                    def fail_complete_open(path, *args, **kwargs):
                        if path == complete_path and args and args[0] == "xb":
                            raise RuntimeError("SIMULATED_AFTER_STATE_BEFORE_COMPLETE")
                        return original_open(path, *args, **kwargs)
                    with patch.object(Path, "open", new=fail_complete_open):
                        with self.assertRaisesRegex(RuntimeError, "SIMULATED_AFTER_STATE_BEFORE_COMPLETE"):
                            daily.execute(date, audit, prior_state, second_state,
                                          parent_status="ACTIVE")
                    self.assertTrue(second_state.is_file())
                    self.assertFalse(complete_path.exists())
                    state_sha_before = daily.sha(second_state)
                    self.assertEqual(daily.execute(date, audit, prior_state, second_state,
                                                   parent_status="ACTIVE")["status"], "COMPLETE")
                    self.assertEqual(daily.sha(second_state), state_sha_before)
                    self.assertEqual(len(daily.read_json(second_state)["formal_days"]), 2)

    def test_addendum_state_first_day_parent_chain_and_duplicate(self):
        with tempfile.TemporaryDirectory(dir=daily.ROOT) as temp:
            root = Path(temp)
            with patch.object(daily, "STATE_ROOT", root):
                prior, next_path = daily.state_chain_preflight(root, "20261107")
                self.assertIsNone(prior)
                self.assertEqual(next_path.name, "20261107_state.json")
                race = "race_20261107_tokyo_1R"
                day = {"date": "2026-11-07", "role": "PROSPECTIVE_ELIGIBLE",
                       "pre_frozen_before_result": True, "result_join_verified": True,
                       "parent_suspended": False,
                       "pre_races": [{"race_id": race, "current_k": 1, "candidate_k": 1,
                                      "candidate_selected_horses": [1], "current_selected_horses": [1]}],
                       "current_buy_counts": {race: 1}, "plj_slots": 1, "current_slots": 1,
                       "plj_valid_n": 1, "plj_valid_hits": 1, "delta_hits": 0}
                event, first = daily.write_state_event("20261107", root, None, day)
                self.assertTrue(event.is_file())
                with self.assertRaisesRegex(daily.Stop, "STOP_DUPLICATE_OR_OUT_OF_ORDER"):
                    daily.state_chain_preflight(root, "20261107")
                previous, target = daily.state_chain_preflight(root, "20261108")
                self.assertEqual(previous, first)
                self.assertEqual(target.name, "20261108_state.json")
                day["date"] = "2026-11-08"
                day["parent_suspended"] = True
                _, second = daily.write_state_event("20261108", root, first, day)
                self.assertEqual(daily.read_json(second)["terminal_status"], "PARENT_SUSPEND_HUMAN_REVIEW")
                self.assertEqual(len(daily.read_json(second)["formal_days"]), 1)
                daily.state_chain_preflight(root, "20261114")
                changed = daily.read_json(second)
                changed["previous_state_sha256"] = "wrong"
                second.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(daily.Stop, "STOP_ADDENDUM_PARENT_SHA"):
                    daily.state_chain_preflight(root, "20261114")

    def test_second_day_state_resume_after_state_before_complete_and_tamper_guards(self):
        with tempfile.TemporaryDirectory(dir=daily.ROOT) as temp:
            root = Path(temp) / "formal_state"
            def day(date):
                race = f"race_{date}_tokyo_1R"
                return {"date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
                        "role": "PROSPECTIVE_ELIGIBLE", "pre_frozen_before_result": True,
                        "result_join_verified": True, "parent_suspended": False,
                        "pre_races": [{"race_id": race, "current_k": 1, "candidate_k": 1,
                                       "candidate_selected_horses": [1], "current_selected_horses": [1]}],
                        "current_buy_counts": {race: 1}, "plj_slots": 1, "current_slots": 1,
                        "plj_valid_n": 1, "plj_valid_hits": 1, "delta_hits": 0}
            with patch.object(daily, "STATE_ROOT", root):
                first_event, first_state = daily.write_state_event("20261107", root, None,
                                                                    day("20261107"))
                daily.verify_existing_state("20261107", None, first_event, first_state,
                                            day("20261107"))
                second_day = day("20261108")
                second_event, second_state = daily.write_state_event("20261108", root,
                                                                      first_state, second_day)
                complete = Path(temp) / "complete.json"
                self.assertFalse(complete.exists())  # simulated interruption after state write
                previous, existing = daily.state_chain_preflight(root, "20261108",
                                                                  allow_existing=True)
                self.assertEqual((previous, existing), (first_state, second_state))
                before_sha = daily.sha(second_state)
                daily.verify_existing_state("20261108", previous, second_event, existing,
                                            second_day)
                daily.write_or_verify(complete, {"status": "COMPLETE"})
                self.assertEqual(daily.sha(second_state), before_sha)
                self.assertEqual(len(daily.read_json(second_state)["formal_days"]), 2)
                daily.verify_existing_state("20261108", previous, second_event, existing,
                                            second_day)
                self.assertEqual(len(daily.read_json(second_state)["formal_days"]), 2)
                with self.assertRaisesRegex(daily.Stop, "STOP_DUPLICATE_ADDENDUM_EVENT"):
                    daily.write_state_event("20261108", root, first_state, second_day)
                original = second_state.read_bytes()
                for key, wrong in (("event_date", "20261109"),
                                   ("previous_state_sha256", "wrong"),
                                   ("verified_day_sha256", "wrong"),
                                   ("formal_evidence_dates", 99)):
                    altered = json.loads(original)
                    altered[key] = wrong
                    second_state.write_text(json.dumps(altered), encoding="utf-8")
                    with self.assertRaisesRegex(daily.Stop, "STOP_RESUME_ARTIFACT_MISMATCH"):
                        daily.verify_existing_state("20261108", first_state, second_event,
                                                    second_state, second_day)
                second_state.write_bytes(original)

    def test_existing_1101_exp024_post_can_be_verified_for_resume(self):
        date = "20261101"
        audit = daily.preflight(date)
        sources, _ = daily.result_sources(date)
        for lane in ("EXP024", "A_NEW", "E1"):
            path = daily.lane_post_paths(date)[lane]
            self.assertEqual(daily.verify_lane_post(lane, date, path, audit, sources)["date"], date)

    def test_state_terminal_and_authorized_not_eligible_do_not_double_count(self):
        with tempfile.TemporaryDirectory(dir=daily.ROOT) as temp:
            root = Path(temp)
            authority = root / "authority.json"
            authority.write_text("{}", encoding="utf-8")
            prior_day = {"date": "2026-11-07", "role": "PROSPECTIVE_ELIGIBLE",
                         "pre_frozen_before_result": True, "result_join_verified": True,
                         "parent_suspended": True}
            with patch.object(daily, "STATE_ROOT", root):
                _, first = daily.write_state_event("20261107", root, None, prior_day)
                self.assertEqual(daily.read_json(first)["terminal_status"], "PARENT_SUSPEND_HUMAN_REVIEW")
                ineligible = {"date": "2026-11-08", "role": "NOT_ELIGIBLE",
                              "pre_frozen_before_result": False, "reason": "OFFICIAL_CANCELLED",
                              "authority_path": str(authority), "authority_sha256": daily.sha(authority)}
                event, second = daily.write_state_event("20261108", root, first, ineligible,
                                                        not_eligible=ineligible)
                self.assertTrue(event.name.endswith("not_eligible.json"))
                self.assertEqual(daily.read_json(second).get("formal_days", []), [])
                daily.state_chain_preflight(root, "20261114")
                self.assertEqual(daily.read_json(second)["previous_state_sha256"], daily.sha(first))
                with self.assertRaisesRegex(daily.Stop, "STOP_DUPLICATE"):
                    daily.write_state_event("20261108", root, first, ineligible, not_eligible=ineligible)
                authority.write_text("changed", encoding="utf-8")
                with self.assertRaisesRegex(daily.Stop, "STOP_NOT_ELIGIBLE_AUTHORITY_MISSING"):
                    daily.write_state_event("20261115", root, second,
                                            {**ineligible, "date": "2026-11-15"},
                                            not_eligible={**ineligible, "date": "2026-11-15"})

    def test_state_gap_detects_intervening_frozen_pre_without_result(self):
        with tempfile.TemporaryDirectory(dir=daily.ROOT) as temp:
            base = Path(temp)
            root = base / "formal_state"
            root.mkdir()
            selection = base / "reports/frozen_pl_v1_jockey_offset_provisional_v1/20261108_pre/selection.json"
            selection.parent.mkdir(parents=True)
            selection.write_text("{}", encoding="utf-8")
            with patch.object(daily, "ROOT", base), patch.object(daily, "STATE_ROOT", root):
                with self.assertRaisesRegex(daily.Stop, "STOP_SKIPPED_ELIGIBLE_ADDENDUM_DATE:20261108"):
                    daily.state_chain_preflight(root, "20261114")

    def test_bad_date_stops(self):
        with self.assertRaisesRegex(daily.Stop, "STOP_INVALID_DATE"):
            daily.preflight("2026-11-07")

    def test_cli_requires_human_result_finality_before_result_read(self):
        with patch("sys.argv", ["formal_post_daily_v1", "20261201", "--mode", "check"]), \
             patch.object(daily, "preflight") as preflight:
            with self.assertRaisesRegex(daily.Stop, "STOP_HUMAN_RESULT_FINALITY"):
                daily.main()
            preflight.assert_not_called()

    def test_cli_requires_delta_approval_before_result_read(self):
        with patch("sys.argv", ["formal_post_daily_v1", "20261201", "--mode", "execute",
                                 "--human-final-result-confirmed"]), \
             patch.object(daily, "preflight") as preflight:
            with self.assertRaisesRegex(daily.Stop, "STOP_FORMAL_POST_EXECUTION_NOT_AUTHORIZED"):
                daily.main()
            preflight.assert_not_called()

    def test_forward_role_and_backfill_distinction_and_nonoverwrite(self):
        date = "20261107"
        audit = daily.preflight(date)
        sources, _ = daily.result_sources(date)
        for lane in ("PL_JOCKEY", "CURRENT_RANK1"):
            rows = daily.joined(date, lane, audit["pre"], sources)
            payload = daily.forward_post_payload(date, lane, audit, rows)
            self.assertEqual(payload["role"], "FORMAL_POST_FORWARD_PROSPECTIVE")
            self.assertEqual(payload["post_kind"], "FORWARD")
            self.assertEqual(payload["crosscheck_status"], "PASS")
            self.assertNotIn("formal_evidence_changed", payload)
            self.assertNotEqual(payload["role"], "FORMAL_POST_ARTIFACT_BACKFILL_NO_EVIDENCE_STATUS_CHANGE")
            with tempfile.TemporaryDirectory(dir=daily.ROOT) as temp:
                path = Path(temp) / "post" / "post.json"
                self.assertEqual(daily.write_forward_post(date, lane, audit, rows, path), "CREATED")
                original_sha = daily.sha(path)
                self.assertEqual(daily.write_forward_post(date, lane, audit, rows, path), "REUSED_VERIFIED")
                self.assertEqual(daily.sha(path), original_sha)
                changed = daily.read_json(path)
                changed["role"] = "BAD"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(daily.Stop, "STOP_RESUME_ARTIFACT_MISMATCH"):
                    daily.write_forward_post(date, lane, audit, rows, path)

    def test_current_identity_uses_exp024_frozen_trace(self):
        race = {"race_id": "race_20261201_tokyo_1R",
                "race_trace": {"current_selected_horses": [2],
                               "horses": [{"horse_number": 2, "horse_name": "H"}]},
                "results": {"2": {"valid_result": True, "actual_finish": 3, "actual_top3": True}}}
        selection = {"races": [{"race_id": race["race_id"], "current_selected_horses": [2]}]}
        rows = daily.current_rows_from_exp024({"races": [race]}, selection)
        self.assertEqual((len(rows), rows[0]["finish"], rows[0]["actual_top3"]), (1, 3, True))
        selection["races"][0]["current_selected_horses"] = [1]
        with self.assertRaisesRegex(daily.Stop, "STOP_CURRENT_EXP024_PLJ_IDENTITY"):
            daily.current_rows_from_exp024({"races": [race]}, selection)

    def test_candidate_post_projection_preserves_invalid_and_checks_metric(self):
        rid = "race_20261201_tokyo_1R"
        selected = {"race_id": rid, "horse_number": 3, "horse_name": "H"}
        item = {"horse_number": 3, "finish": None, "valid_result": False,
                "actual_top3": None, "e1_selected": True, "a_new_selected": True}
        post = {"races": [{"race_id": rid, "selected_outcomes": [item]}]}
        e1 = daily.selected_rows_from_post("E1", post, {"selected_horses": [selected]})
        a_new = daily.selected_rows_from_post("A_NEW", post,
                                              {"races": [{"race_id": rid, "horses": [selected]}]})
        self.assertEqual(e1, a_new)
        self.assertEqual(daily.lane_report(e1, {"selected": 1, "valid": 0, "hits": 0})["invalid"], 1)
        with self.assertRaisesRegex(daily.Stop, "STOP_LANE_POST_METRIC_MISMATCH"):
            daily.lane_report(e1, {"selected": 1, "valid": 1, "hits": 0})

    def test_exp024_post_projection_uses_treatment_not_current(self):
        rid = "race_20261201_tokyo_1R"
        post = {"races": [{"race_id": rid,
                           "race_trace": {"horses": [{"horse_number": 1, "horse_name": "A"},
                                                       {"horse_number": 2, "horse_name": "B"}],
                                          "current_selected_horses": [1],
                                          "treatment_selected_horses": [2]},
                           "results": {"2": {"actual_finish": 1, "valid_result": True, "actual_top3": True}}}]}
        rows = daily.selected_rows_from_post("EXP024", post)
        self.assertEqual((rows[0]["horse_number"], rows[0]["horse_name"], rows[0]["finish"]), (2, "B", 1))

    def test_addendum_invalid_is_excluded_from_ordinary_but_not_rule_a_slot(self):
        rid = "race_20261201_tokyo_1R"
        selection = {"races": [{"race_id": rid, "current_k": 1, "candidate_k": 1,
                                 "candidate_selected_horses": [1], "current_selected_horses": [2]}]}
        index = {"race_index": [{"race_id": rid, "buy_count": 1}]}
        pre = {"PL_JOCKEY": {"path": "plj.json"}}
        invalid = {"race_id": rid, "horse_number": 1, "valid_result": False, "actual_top3": False}
        hit = {"race_id": rid, "horse_number": 2, "valid_result": True, "actual_top3": True}
        with patch.object(daily, "read_json", side_effect=[selection, index]):
            day = daily.verified_day("20261201", pre, [invalid], [hit],
                                     {"horse_order": "a", "finish_order": "b"}, parent_suspended=False)
        self.assertEqual((day["plj_slots"], day["plj_valid_n"], day["plj_rule_a_hits"], day["delta_hits"]),
                         (1, 0, 0, -1))

    def test_completed_reexecution_is_read_only_and_conflict_stops(self):
        root = Path("unused")
        artifact = root / "lane.json"
        audit = {"date": "20261201", "result_sha256": {"horse_order": "h", "finish_order": "f"},
                 "pre": {"CURRENT": {"sha256": "p"}}}
        complete = {"date": audit["date"], "result_sha256": audit["result_sha256"],
                    "pre_sha256": {"CURRENT": "p"},
                    "lane_artifacts": {lane: {"path": str(artifact), "sha256": "correct"}
                                       for lane in daily.LANES if lane != "CURRENT"},
                    "addendum_next_state_path": "state.json", "addendum_next_state_sha256": "correct",
                    "addendum_verified_day_path": "verified.json", "addendum_verified_day_sha256": "correct",
                    "selected_horse_outcomes_sha256": "correct", "lane_summary_sha256": "correct"}
        with patch.object(daily, "read_json", return_value=complete), \
             patch.object(daily, "sha", return_value="correct"), \
             patch.object(daily, "result_sources", return_value=({}, audit["result_sha256"])), \
             patch.object(daily, "lane_post_paths", return_value={lane: artifact for lane in daily.LANES if lane != "CURRENT"}), \
             patch.object(daily, "verify_lane_post"):
            self.assertEqual(daily.verify_completed(root, audit)["status"], "ALREADY_COMPLETE_UNCHANGED")
        with patch.object(daily, "read_json", return_value=complete), patch.object(daily, "sha", return_value="changed"):
            with self.assertRaisesRegex(daily.Stop, "STOP_EXISTING_POST_ARTIFACT_CONFLICT"):
                daily.verify_completed(root, audit)


if __name__ == "__main__":
    unittest.main()
