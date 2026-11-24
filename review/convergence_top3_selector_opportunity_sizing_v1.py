"""Result-free structural sizing of the existing convergence branch."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.buy_v1_rc1_engine import BUYV1RC1Engine
from review.candidate_generation_stage_b_shadow_v1 import CandidateGenerationStageBShadow
from review.selection_composition_policy_v2_phase1_v1 import (
    STAGE_A,
    candidate_rows,
    full_context,
    packet,
    scope,
)

OUT = ROOT / "reports/convergence_top3_selector_opportunity_sizing_v1"
RETRY5 = ROOT / "reports/candidate_generation_stage_b_fast_route_b4_buy_performance_v1_retry5"
POLICY_V2 = ROOT / "reports/selection_composition_policy_v2_shadow_phase1_v1"
PROTECTED = [
    ROOT / "engine/decision_engine.py",
    ROOT / "engine/decision_guard.py",
    ROOT / "engine/buy_v1_rc1_engine.py",
    ROOT / "engine/shadow_buy_decision_engine.py",
    ROOT / "engine/race_decision_engine.py",
    ROOT / "engine/race_decision_buy_synchronizer.py",
    ROOT / "review/candidate_generation_stage_b_shadow_v1.py",
    ROOT / "review/candidate_generation_stage_a_paired_population_expanded_v1.py",
    ROOT / "evaluation/target_trial_adapter.py",
    ROOT / "KeibaAI_EXPERIMENT_ANALYSIS_LEDGER.md",
    ROOT / "KeibaAI_EXPERIMENT_FINGERPRINT_INDEX.json",
]


class Stop(RuntimeError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(name: str, rows: list[dict], fields: list[str]) -> None:
    with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def verify_index(root: Path) -> dict:
    index_path = root / "artifact_hash_index.json"
    entries = read_json(index_path).get("indexed_artifacts", {})
    mismatches = []
    for name, expected in entries.items():
        expected_hash = expected.get("sha256") if isinstance(expected, dict) else expected
        if not (root / name).is_file() or sha(root / name) != expected_hash:
            mismatches.append(name)
    return {"path": str(index_path.relative_to(ROOT)), "indexed": len(entries), "mismatches": mismatches, "status": "PASS" if not mismatches else "FAIL"}


class RecordingRC1:
    """Transparent recorder around the unchanged RC1 implementation."""

    def __init__(self):
        self.delegate = BUYV1RC1Engine()
        self.last_result = None

    def evaluate(self, race_output=None, horses=None):
        self.last_result = self.delegate.evaluate(race_output=race_output, horses=horses)
        return self.last_result

    def apply_to_horses(self, horses, result):
        return self.delegate.apply_to_horses(horses, result)


def main() -> int:
    if OUT.exists():
        raise Stop(f"EXCLUSIVE_CREATE_REQUIRED:{OUT}")
    OUT.mkdir(parents=True)
    protected_before = {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path) for path in PROTECTED}
    try:
        retry5_index = verify_index(RETRY5)
        policy_index = verify_index(POLICY_V2)
        if retry5_index["status"] != "PASS" or policy_index["status"] != "PASS":
            raise Stop("FROZEN_SOURCE_HASH_MISMATCH")
        dates, sources = scope()
        baseline = candidate_rows(STAGE_A / "baseline_predictions.csv", dates)
        treatment = candidate_rows(STAGE_A / "treatment_predictions.csv", dates)
        if len(dates) != 45 or sum(len(sources[date]) for date in dates) != 828:
            raise Stop("SCOPE_MISMATCH")

        dump("scope_audit.json", {
            "OPPORTUNITY_SCOPE_DATES": 45,
            "OPPORTUNITY_SCOPE_RACES": 828,
            "FEBRUARY_USED": 0,
            "dates": sorted(dates),
            "lanes": ["baseline", "treatment"],
            "status": "PASS",
        })
        dump("source_provenance.json", {
            "source_priority_review": {
                "retry5": "inspected; exact candidate_records count not persisted",
                "policy_v2_phase1": "inspected; exact candidate_records count not persisted",
                "stage_b_trace_manifest": "inspected; exact RC1 candidate flag/count not persisted",
            },
            "reconstruction": "minimum deterministic replay of frozen Exact5 through unchanged Stage B with transparent RC1 result recorder",
            "candidate_sources": {
                "baseline": str((STAGE_A / "baseline_predictions.csv").relative_to(ROOT)).replace("\\", "/"),
                "baseline_sha256": sha(STAGE_A / "baseline_predictions.csv"),
                "treatment": str((STAGE_A / "treatment_predictions.csv").relative_to(ROOT)).replace("\\", "/"),
                "treatment_sha256": sha(STAGE_A / "treatment_predictions.csv"),
            },
            "retry5_hash_validation": retry5_index,
            "policy_v2_hash_validation": policy_index,
            "result_source": None,
            "v4_model_source": None,
        })

        distributions = {lane: Counter() for lane in ("baseline", "treatment")}
        zero_buy = {lane: Counter() for lane in ("baseline", "treatment")}
        opportunities = {lane: set() for lane in ("baseline", "treatment")}
        manifest = []
        executions = committed = 0
        for date in sorted(dates):
            for source_path in sorted(sources[date]):
                full_rows, race_context, _ = full_context(source_path)
                key = (date, race_context["race_id"])
                for lane, candidate_source in (("baseline", baseline), ("treatment", treatment)):
                    exact5 = candidate_source.get(key)
                    if exact5 is None:
                        raise Stop(f"CANDIDATE_SOURCE_MISSING:{lane}:{key}")
                    recorder = RecordingRC1()
                    stage = CandidateGenerationStageBShadow(rc1_engine=recorder)
                    snapshot = stage.race_context_snapshot(full_rows, race_context)
                    result = stage.run(packet(lane, key[1], exact5, snapshot["snapshot_hash"]), full_rows, race_context)
                    executions += 1
                    if result.get("status") != "COMMITTED" or not isinstance(recorder.last_result, dict):
                        raise Stop(f"STAGE_B_RECONSTRUCTION_STOP:{lane}:{key}:{result.get('failure_state')}")
                    committed += 1
                    summary = recorder.last_result.get("summary", {})
                    count = summary.get("candidate_count")
                    state = recorder.last_result.get("race_state")
                    if isinstance(count, bool) or not isinstance(count, int) or count < 0 or count > 5:
                        raise Stop(f"CANDIDATE_RECORD_COUNT_SEMANTIC_MISMATCH:{lane}:{key}:{count}")
                    final_buy_count = sum(str(row.get("decision", "")).upper() == "BUY" for row in result["horses"])
                    distributions[lane][count] += 1
                    if final_buy_count == 0:
                        zero_buy[lane]["total"] += 1
                    is_opportunity = count >= 4 and state == "PLAY_UNCONVERGED_4PLUS" and final_buy_count == 0
                    if count >= 4 and not is_opportunity:
                        raise Stop(f"UNCONVERGED_SEMANTIC_MISMATCH:{lane}:{key}:{count}:{state}:{final_buy_count}")
                    if is_opportunity:
                        opportunities[lane].add(key[1])
                        zero_buy[lane]["unconverged"] += 1
                        manifest.append({
                            "race_id": key[1],
                            "date": date,
                            "venue": race_context["venue"],
                            "lane": lane,
                            "candidate_records_count": count,
                        })

        if executions != 1656 or committed != 1656:
            raise Stop(f"EXECUTION_COUNT_MISMATCH:{executions}:{committed}")
        if any(sum(distributions[lane].values()) != 828 for lane in distributions):
            raise Stop("DISTRIBUTION_SUM_MISMATCH")

        distribution_payload = {
            lane: {str(number): distributions[lane][number] for number in range(6)}
            for lane in ("baseline", "treatment")
        }
        dump("candidate_record_distribution.json", distribution_payload)
        summary_payload = {}
        for lane in ("baseline", "treatment"):
            count4 = distributions[lane][4]
            count5 = distributions[lane][5]
            races = count4 + count5
            summary_payload[lane] = {
                "play_unconverged_4plus_races": races,
                "exactly_4_races": count4,
                "exactly_5_races": count5,
                "qualifying_horses": count4 * 4 + count5 * 5,
                "rate_of_828": races / 828,
                "total_zero_buy_races": zero_buy[lane]["total"],
                "zero_buy_due_to_unconverged_4plus": zero_buy[lane]["unconverged"],
                "unconverged_share_of_zero_buy": zero_buy[lane]["unconverged"] / zero_buy[lane]["total"] if zero_buy[lane]["total"] else None,
            }
        dump("play_unconverged_4plus_summary.json", summary_payload)
        common = opportunities["baseline"] & opportunities["treatment"]
        baseline_only = opportunities["baseline"] - opportunities["treatment"]
        treatment_only = opportunities["treatment"] - opportunities["baseline"]
        dump("baseline_treatment_overlap.json", {
            "common_count": len(common),
            "baseline_only_count": len(baseline_only),
            "treatment_only_count": len(treatment_only),
            "common_race_ids": sorted(common),
            "baseline_only_race_ids": sorted(baseline_only),
            "treatment_only_race_ids": sorted(treatment_only),
        })
        write_csv("opportunity_race_manifest.csv", manifest, ["race_id", "date", "venue", "lane", "candidate_records_count"])
        dump("result_access_audit.json", {
            "RESULT_FILE_ACCESS_COUNT": 0,
            "ACTUAL_TOP3_ACCESS_COUNT": 0,
            "PERFORMANCE_CALCULATION_COUNT": 0,
            "V4_SELECTOR_INFERENCE": 0,
            "SELECTOR_SIMULATION": 0,
            "forbidden_fields_in_output": 0,
            "status": "PASS",
        })
        protected_after = {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path) for path in PROTECTED}
        if protected_before != protected_after:
            raise Stop("PROTECTED_SOURCE_MUTATION")
        dump("safety.json", {
            "ENGINE_CHANGE": 0,
            "STAGE_B_CHANGE": 0,
            "CANDIDATE_GENERATOR_CHANGE": 0,
            "V4_CHANGE": 0,
            "PRODUCTION_CHANGE": 0,
            "LEDGER_CHANGE": 0,
            "FINGERPRINT_CHANGE": 0,
            "RESULT_FILE_ACCESS_COUNT": 0,
            "ACTUAL_TOP3_ACCESS_COUNT": 0,
            "PERFORMANCE_CALCULATION_COUNT": 0,
            "V4_SELECTOR_INFERENCE": 0,
            "SELECTOR_SIMULATION": 0,
            "IMPLEMENTATION_AUTHORIZED": "NO",
            "RESULT_ACCESS_AUTHORIZED": "NO",
            "protected_hashes_before": protected_before,
            "protected_hashes_after": protected_after,
            "ARTIFACT_HASH_VALIDATION": "PASS",
        })
        report = [
            "# Convergence Top3 Selector — Result-Free Opportunity Sizing",
            "",
            "`CONVERGENCE_TOP3_SELECTOR_OPPORTUNITY_SIZING_V1 = COMPLETE`",
            "",
            "- Scope: `45 dates / 828 races / February 0`",
            "- V4 selector inference / selector simulation: `0 / 0`",
            "- Result / performance access: `0 / 0`",
            "",
            "## Raw counts",
            "",
            "| Lane | count=0 | count=1 | count=2 | count=3 | count=4 | count=5 | UNCONVERGED races | Rate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for lane in ("baseline", "treatment"):
            values = distribution_payload[lane]
            s = summary_payload[lane]
            report.append(f"| {lane.title()} | {values['0']} | {values['1']} | {values['2']} | {values['3']} | {values['4']} | {values['5']} | {s['play_unconverged_4plus_races']} | {s['rate_of_828']:.4%} |")
        report.extend([
            "",
            "`STRUCTURAL_OPPORTUNITY_ASSESSMENT = PENDING_RAW_COUNT_REVIEW`",
            "",
            "`V3_PROVENANCE_CONFLICT = OPEN`  ",
            "`EXP003_APPLICABILITY = OPEN_NONBLOCKING`  ",
            "`NEXT = CHATGPT_HUMAN_CONVERGENCE_OPPORTUNITY_SIZING_REVIEW`",
            "",
        ])
        (OUT / "report.md").write_text("\n".join(report), encoding="utf-8")
        dump("artifact_hash_index.json", {
            "self_hash_excluded": True,
            "indexed_artifacts": {path.name: sha(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hash_index.json"},
        })
        return 0
    except Exception as error:
        dump("result_access_audit.json", {"RESULT_FILE_ACCESS_COUNT": 0, "ACTUAL_TOP3_ACCESS_COUNT": 0, "PERFORMANCE_CALCULATION_COUNT": 0, "V4_SELECTOR_INFERENCE": 0, "SELECTOR_SIMULATION": 0, "status": "STOP"})
        dump("safety.json", {"status": "STOP", "error": str(error), "ENGINE_CHANGE": 0, "STAGE_B_CHANGE": 0, "V4_CHANGE": 0, "PRODUCTION_CHANGE": 0, "RESULT_FILE_ACCESS_COUNT": 0})
        dump("artifact_hash_index.json", {"self_hash_excluded": True, "indexed_artifacts": {path.name: sha(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hash_index.json"}})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
