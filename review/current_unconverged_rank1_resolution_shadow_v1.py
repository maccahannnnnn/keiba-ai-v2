"""Fixed-k1 development-only shadow over frozen Current PRE output.

No Current/EXP-024/model inference is executed here. Outcome access occurs
only after the PRE-only selector's semantics and determinism are checked.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from review.candidate_generation_training_dataset_readiness_v1 import JAPANESE_VENUE, outcome, parse_race_id, result_rows
from review.current_environment_tree_hash_v1 import tree_hash

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/current_unconverged_rank1_resolution_shadow_v1"
PRE_ROOT = ROOT / "reports/full_field_redesign_iter0_v1_retry6/pre_only_regeneration/shards"
POP = ROOT / "reports/current_population_audit_v1/diagnostic_population_final_proposal.csv"
JOINED = ROOT / "reports/full_field_redesign_iteration2_recovery_inputs_v1/run_a_frozen.json"
SECONDARY = ROOT / "reports/consumed_holdout_bounded_reproduction_v1"
APPROVAL = ROOT / "docs/KeibaAI_CURRENT_UNCONVERGED_RANK1_RESOLUTION_SHADOW_V1_HUMAN_APPROVAL.json"
APPROVAL_SHA = "c9585bf4f7614abbf947446ecc9394502d17aa36b71e9d28fbebdb3c80eb3169"
JOINED_SHA = "48401e556f28f5625d85dfa315153a6dbba84e3114e3a9752e17b25e50f71c22"
PRIOR_FINDINGS = ROOT / "reports/current_k_play_failure_decomposition_v1/primary_findings_951_frozen.json"
PRIOR_FINDINGS_SHA = "39b9debf4db4f189488ac6a1ed92e70ac0a32a7c281a6144a7cd84786b88b4cd"
INDEPENDENT = ROOT / "reports/independent_race_selection_dev_diagnostic_v1/race_level_diagnostic.csv"
PROTECTED_FILES = [
    ROOT / "docs/KeibaAI_PL_SAME_VOLUME_RESELECTION_SHADOW_V1_PROTOCOL.md",
    ROOT / "review/pl_same_volume_reselection_shadow_v1.py",
    ROOT / "review/prospective_prediction_runner_v1.py",
    ROOT / "models/pl_forward_shadow_v1/pl_forward_shadow_v1_model.json",
]
PROTECTED_TREES = [ROOT / name for name in ("engine", "evaluation", "knowledge")]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def summary(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid_result"] is True]
    hits = sum(row["actual_top3"] is True for row in valid)
    return {"selected_raw": len(rows), "invalid_selected": len(rows) - len(valid),
            "selected_valid": len(valid), "top3_hits": hits,
            "top3_rate": hits / len(valid) if valid else None}


def protected_identity() -> dict:
    return {**{path.relative_to(ROOT).as_posix(): sha(path) for path in PROTECTED_FILES},
            **{path.relative_to(ROOT).as_posix() + "/": tree_hash(path) for path in PROTECTED_TREES}}


def load_primary_pre() -> tuple[list[dict], list[dict]]:
    population = list(csv.DictReader(POP.open(encoding="utf-8-sig", newline="")))
    race_ids = {row["race_id"] for row in population}
    if len(race_ids) != 951 or len(population) != 951:
        raise RuntimeError("STOP_PRIMARY_951_POPULATION")
    shards = sorted(PRE_ROOT.glob("run_c_*/runtime_pre_only_output.json"))
    if len(shards) != 31:
        raise RuntimeError("STOP_PRE_SHARD_COUNT")
    rows = [row for path in shards for row in json.loads(path.read_text(encoding="utf-8"))["generated_rows"] if row["race_id"] in race_ids]
    if len(rows) != 12661 or {row["race_id"] for row in rows} != race_ids:
        raise RuntimeError("STOP_PRE_PRIMARY_POPULATION")
    return rows, [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)} for path in shards]


def select(pre_rows: list[dict], expected_races: int) -> tuple[list[dict], dict]:
    """Use persisted score and final rank. Never derive a new tie-break."""
    by_race = defaultdict(list)
    keys = set()
    for row in pre_rows:
        key = (row["race_id"], int(row["horse_number"]))
        if key in keys:
            raise RuntimeError("STOP_DUPLICATE_PRE_HORSE:" + str(key))
        keys.add(key)
        by_race[row["race_id"]].append(row)
    if len(by_race) != expected_races:
        raise RuntimeError("STOP_PRE_RACE_COUNT")
    output = []
    violations = []
    rank_ties = []
    score_ties = []
    state_counts = Counter()
    for race_id, field in sorted(by_race.items()):
        states = {row["values"].get("race_state") for row in field}
        if len(states) != 1:
            violations.append({"race_id": race_id, "reason": "RACE_STATE_INCONSISTENT"})
            continue
        state = next(iter(states))
        state_counts[state] += 1
        ranks = [row.get("rank") for row in field]
        if any(not isinstance(rank, int) or isinstance(rank, bool) for rank in ranks) or sorted(ranks) != list(range(1, len(field) + 1)):
            rank_ties.append(race_id)
            continue
        sorted_field = sorted(field, key=lambda row: int(row["rank"]))
        scores = [row["values"].get("adjusted_score") for row in sorted_field]
        if any(not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) for score in scores):
            violations.append({"race_id": race_id, "reason": "SCORE_MISSING_OR_NONFINITE"})
            continue
        # This is a validation of the existing runner's tuple sort, not a
        # Shadow fallback: (adjusted_score, horse_number) descending.
        expected_order = sorted(field, key=lambda row: (row["values"]["adjusted_score"], int(row["horse_number"])), reverse=True)
        if [int(row["horse_number"]) for row in sorted_field] != [int(row["horse_number"]) for row in expected_order]:
            violations.append({"race_id": race_id, "reason": "FROZEN_RANK_VS_RUNNER_SORT_MISMATCH"})
            continue
        if len(set(scores)) < len(scores):
            score_ties.append(race_id)
        candidate = [row for row in field if row["values"].get("shadow_buy_candidate") is True]
        original_buy = [row for row in field if row["values"].get("post_rc1_decision") == "BUY"]
        if state == "PLAY_CONVERGED":
            good = 1 <= len(candidate) <= 3 and {int(row["horse_number"]) for row in candidate} == {int(row["horse_number"]) for row in original_buy}
        elif state == "PLAY_UNCONVERGED_4PLUS":
            good = len(candidate) >= 4 and not original_buy
        elif state == "SKIP":
            good = not original_buy
        else:
            good = False
        if not good:
            violations.append({"race_id": race_id, "reason": "FROZEN_STAGE_B_SEMANTICS"})
            continue
        winner = min(candidate, key=lambda row: int(row["rank"])) if state == "PLAY_UNCONVERGED_4PLUS" else None
        if winner is not None and sum(int(row["rank"]) == int(winner["rank"]) for row in candidate) != 1:
            rank_ties.append(race_id)
            continue
        for row in sorted_field:
            addition = winner is not None and row is winner
            buy = row["values"].get("post_rc1_decision") == "BUY"
            output.append({"date": row["date"], "race_id": race_id, "horse_number": int(row["horse_number"]),
                           "horse_name": row["horse_name"], "race_state": state,
                           "field_size": len(field), "candidate_count": len(candidate),
                           "current_rank": int(row["rank"]), "adjusted_score": row["values"]["adjusted_score"],
                           "current_candidate": row["values"].get("shadow_buy_candidate") is True,
                           "original_current_buy": buy, "shadow_decision": "BUY" if addition else "NO_ADDITION",
                           "shadow_k": 1 if addition else 0,
                           "shadow_addition": addition,
                           "resolution_reason": "CURRENT_SCORE_RANK1_FIXED_K1" if addition else "NOT_APPLICABLE",
                           "combined_current_plus_shadow_buy": buy or addition})
    meta = {"expected_races": expected_races, "observed_races": len(by_race), "state_counts": dict(state_counts),
            "score_tied_races_resolved_by_persisted_rank": len(score_ties),
            "score_tied_race_ids": score_ties, "unresolved_rank_tie_races": rank_ties,
            "semantic_violations": violations}
    if rank_ties or violations or len(output) != len(pre_rows):
        raise RuntimeError("CURRENT_RANK_AUTHORITY_NOT_REPRODUCIBLE:" + json.dumps(meta, ensure_ascii=False))
    return output, meta


def results_primary(selection: list[dict]) -> tuple[list[dict], dict]:
    if sha(JOINED) != JOINED_SHA or sha(PRIOR_FINDINGS) != PRIOR_FINDINGS_SHA:
        raise RuntimeError("STOP_PRIMARY_OUTCOME_AUTHORITY_SHA")
    joined = json.loads(JOINED.read_text(encoding="utf-8"))["rows"]
    result_by_key = {(row["race_id"], int(row["horse_number"])): row for row in joined}
    if len(result_by_key) != len(joined) or len(selection) != len(joined):
        raise RuntimeError("STOP_PRIMARY_JOIN_COUNT")
    annotated = []
    for row in selection:
        source = result_by_key.get((row["race_id"], row["horse_number"]))
        if source is None or bool(source["current_buy"]) != row["original_current_buy"] or int(source["current_rank"]) != row["current_rank"]:
            raise RuntimeError("STOP_PRIMARY_PRE_POST_PARITY")
        annotated.append({**row, "valid_result": source["valid_result"] is True, "actual_top3": source["actual_top3"] is True})
    return annotated, {"path": JOINED.relative_to(ROOT).as_posix(), "sha256": sha(JOINED)}


def results_secondary(selection: list[dict], dates: list[str]) -> tuple[list[dict], list[dict]]:
    result_by_date = {}
    sources = []
    for date in dates:
        for name in (f"馬番順着順_{date}.csv", f"着順馬番_{date}.csv"):
            path = ROOT / "data/raw/target/daily_result_list" / name
            if not path.is_file():
                raise RuntimeError("STOP_SECONDARY_RESULT_SOURCE_MISSING:" + str(path))
            sources.append({"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)})
        result_by_date[date] = result_rows(date)
    annotated = []
    for row in selection:
        date, venue, race_number = parse_race_id(row["race_id"])
        if date != row["date"] or date not in result_by_date or venue not in JAPANESE_VENUE:
            raise RuntimeError("STOP_SECONDARY_RACE_KEY")
        source = result_by_date[date].get((JAPANESE_VENUE[venue], race_number))
        if source is None:
            raise RuntimeError("STOP_SECONDARY_RACE_RESULT_MISSING:" + row["race_id"])
        valid, _finish, top3 = outcome(source, row["horse_number"])
        annotated.append({**row, "valid_result": valid, "actual_top3": top3 is True})
    return annotated, sources


def replay(rows: list[dict]) -> dict:
    original = summary([row for row in rows if row["original_current_buy"]])
    added = summary([row for row in rows if row["shadow_addition"]])
    combined = summary([row for row in rows if row["combined_current_plus_shadow_buy"]])
    if original["selected_raw"] + added["selected_raw"] != combined["selected_raw"]:
        raise RuntimeError("STOP_OVERLAP_OR_DOUBLE_COUNT")
    return {"original_current": original, "rank1_additions": added, "combined_current_plus_additions": combined,
            "raw_combined_lift_vs_current_pt": 100 * (combined["top3_rate"] - original["top3_rate"]) if original["top3_rate"] is not None else None,
            "role": "DEVELOPMENT_ONLY_COUNTERFACTUAL_NOT_PRODUCTION", "formal_evidence_credit": 0}


def temporal(rows: list[dict]) -> dict:
    additions = [row for row in rows if row["shadow_addition"]]
    out = {}
    for dimension, fn in (("by_date", lambda row: row["date"]), ("by_month", lambda row: row["date"][:6]),
                          ("by_venue", lambda row: row["race_id"].split("_")[2])):
        groups = defaultdict(list)
        for row in additions:
            groups[fn(row)].append(row)
        out[dimension] = {key: summary(value) for key, value in sorted(groups.items())}
    lodo = {}
    for date in out["by_date"]:
        lodo[date] = summary([row for row in additions if row["date"] != date])
    rates = [value["top3_rate"] for value in lodo.values() if value["top3_rate"] is not None]
    hits = sum(row["actual_top3"] is True and row["valid_result"] is True for row in additions)
    top = sorted(out["by_date"].items(), key=lambda item: (-item[1]["top3_hits"], item[0]))[:5]
    out["lodo_top3_rate_range"] = {"min": min(rates), "max": max(rates)} if rates else None
    out["date_concentration"] = {"top_contributing_dates": [{"date": date, **value} for date, value in top],
                                  "top_5_dates_hit_share": sum(value["top3_hits"] for _, value in top) / hits if hits else None,
                                  "all_dates_with_additions": len(out["by_date"])}
    return out


def independent_overlap(selection: list[dict]) -> dict:
    with INDEPENDENT.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    independent = defaultdict(set)
    seen = set()
    for row in rows:
        if row["model"].lower() != "v5":
            continue
        key = (row["race_id"], int(row["horse_number"]))
        if key in seen:
            raise RuntimeError("STOP_INDEPENDENT_DUPLICATE_KEY")
        seen.add(key)
        if row["selected"].lower() == "true":
            independent[row["race_id"]].add(int(row["horse_number"]))
        elif row["selected"].lower() != "false":
            raise RuntimeError("STOP_INDEPENDENT_SELECTED_SEMANTICS")
    counts = Counter()
    examples = []
    for row in selection:
        if not row["shadow_addition"]:
            continue
        race_id = row["race_id"]
        if not any(key[0] == race_id for key in seen):
            label = "NOT_COMPARABLE_RACE_ABSENT"
        elif not independent[race_id]:
            label = "NOT_COMPARABLE_NO_INDEPENDENT_SELECTION"
        elif row["horse_number"] in independent[race_id]:
            label = "SAME_HORSE"
        else:
            label = "DIFFERENT_HORSE"
        counts[label] += 1
        examples.append({"race_id": race_id, "shadow_horse_number": row["horse_number"],
                         "independent_selected_horse_numbers": sorted(independent[race_id]), "comparison": label})
    return {"source_path": INDEPENDENT.relative_to(ROOT).as_posix(), "source_sha256": sha(INDEPENDENT),
            "independent_model": "v5", "counts": dict(counts), "race_comparisons": examples,
            "note": "Development overlap only; Independent selection and Shadow selection are unchanged."}


def replication(primary: dict, secondary: dict) -> tuple[str, str]:
    p_add = primary["rank1_additions"]["top3_rate"]
    s_add = secondary["rank1_additions"]["top3_rate"]
    p_lift = primary["raw_combined_lift_vs_current_pt"]
    s_lift = secondary["raw_combined_lift_vs_current_pt"]
    if p_add is None or s_add is None or p_lift is None or s_lift is None:
        return "PARTIALLY_REPEAT", "A valid-denominator metric was unavailable; no performance imputation."
    if p_add > 0 and p_lift > 0 and s_add > 0 and s_lift > 0:
        return "REPEAT", "Added-hit and combined-lift directions both match the primary block."
    if s_add > 0:
        return "PARTIALLY_REPEAT", "Added horses contain Top3 results, but the combined-lift direction differs or is zero."
    return "CONTRADICT", "The secondary additions contained no valid Top3 result."


def main() -> None:
    if OUT.exists():
        raise RuntimeError("STOP_SHADOW_OUTPUT_ROOT_EXISTS")
    if sha(APPROVAL) != APPROVAL_SHA or APPROVAL.with_suffix(".sha256").read_text(encoding="ascii").strip() != APPROVAL_SHA:
        raise RuntimeError("STOP_HUMAN_APPROVAL_RECORD_SHA")
    before = protected_identity()
    pre, shards = load_primary_pre()
    first, semantic = select(pre, 951)
    second, semantic_again = select(pre, 951)
    if semantic != semantic_again or first != second:
        raise RuntimeError("STOP_SHADOW_NONDETERMINISTIC")
    if semantic["state_counts"] != {"PLAY_CONVERGED": 432, "PLAY_UNCONVERGED_4PLUS": 228, "SKIP": 291}:
        raise RuntimeError("STOP_PRIMARY_STATE_COUNTS")
    if sum(row["shadow_addition"] for row in first) != 228 or any(row["shadow_addition"] and (row["race_state"] != "PLAY_UNCONVERGED_4PLUS" or not row["current_candidate"] or row["original_current_buy"]) for row in first):
        raise RuntimeError("STOP_SHADOW_ADDITION_SEMANTICS")
    OUT.mkdir(parents=True)
    implementation = {"approval_record": {"path": APPROVAL.relative_to(ROOT).as_posix(), "sha256": sha(APPROVAL)},
                      "implementation_sha256": sha(Path(__file__)), "population_sha256": sha(POP),
                      "current_rank_authority": {"score_field": "values.adjusted_score", "rank_field": "rank",
                                                 "tie_handling": "persisted rank; original runner sorts adjusted_score descending then horse_number descending",
                                                 "runner_path": "review/target_bulk_prediction_input_shadow_v1.py",
                                                 "runner_sha256": sha(ROOT / "review/target_bulk_prediction_input_shadow_v1.py"),
                                                 "regeneration_path": "review/ws2_deterministic_pre_only_regeneration_v1.py",
                                                 "regeneration_sha256": sha(ROOT / "review/ws2_deterministic_pre_only_regeneration_v1.py")},
                      "pre_shards": shards, "rule": "existing Current candidate with minimum persisted rank in PLAY_UNCONVERGED_4PLUS only",
                      "k": 1, "threshold": None, "pl_used": False}
    write_json("implementation_identity.json", implementation)
    write_json("semantic_validation.json", {"status": "PASS", "primary_races": 951,
                                             "unconverged_races": 228, "original_buy_in_unconverged": 0,
                                             "shadow_selected": 228, "outside_state_additions": 0,
                                             "selected_non_candidates": 0, "rank1_violations": 0,
                                             "unresolved_rank_ties": semantic["unresolved_rank_tie_races"],
                                             "semantic_violations": semantic["semantic_violations"],
                                             "score_tied_races_resolved_by_persisted_rank": semantic["score_tied_races_resolved_by_persisted_rank"]})
    write_json("determinism_check.json", {"status": "PASS", "identical_frozen_pre_input": True,
                                           "horse_level_rows_compared": len(first), "differences": 0})
    fields = list(first[0])
    with (OUT / "primary_shadow_output.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(first)
    annotated, primary_outcome = results_primary(first)
    primary = replay(annotated)
    primary["population"] = {"dates": len({row["date"] for row in first}), "races": 951,
                             "unconverged_races": 228, "horses": len(first)}
    primary["outcome_authority"] = primary_outcome
    write_json("primary_development_replay.json", primary)
    write_json("temporal_stability.json", temporal(annotated))
    write_json("independent_overlap.json", independent_overlap(first))
    secondary_summary = json.loads((SECONDARY / "summary.json").read_text(encoding="utf-8"))["months"]
    secondary_results = {}
    for block, races, horses in (("december", 146, 2093), ("january", 149, 2045)):
        meta = secondary_summary[block]
        if meta["verdict"] != "PASS" or meta["regenerated_races"] != races or meta["regenerated_horses"] != horses or meta["stage_b_semantic_violations"] != 0:
            raise RuntimeError("STOP_SECONDARY_PRE_READINESS:" + block)
        path = SECONDARY / block / "run_a/runtime_pre_only_output.json"
        if sha(path) != meta["run_a_sha256"]:
            raise RuntimeError("STOP_SECONDARY_PRE_SHA:" + block)
        secondary_pre = json.loads(path.read_text(encoding="utf-8"))["generated_rows"]
        secondary_selection, secondary_semantic = select(secondary_pre, races)
        if len(secondary_selection) != horses or len(secondary_semantic["semantic_violations"]) != 0:
            raise RuntimeError("STOP_SECONDARY_SELECTION:" + block)
        secondary_annotated, sources = results_secondary(secondary_selection, meta["source_dates"])
        result = replay(secondary_annotated)
        label, reason = replication(primary, result)
        result.update({"block": block, "population": {"dates": len(meta["source_dates"]), "races": races,
                                                   "unconverged_races": secondary_semantic["state_counts"]["PLAY_UNCONVERGED_4PLUS"],
                                                   "horses": horses},
                       "pre_source": {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)},
                       "result_sources": sources, "replication": label, "replication_reason": reason,
                       "reuse_role": "REUSED_CONSUMED_HOLDOUT_FOR_DEVELOPMENT_ONLY",
                       "new_evidence_credit": 0})
        write_json(f"secondary_{block}_replay.json", result)
        secondary_results[block] = result
    after = protected_identity()
    if before != after:
        raise RuntimeError("STOP_PROTECTED_EXP024_OR_CORE_CHANGED")
    isolation = {"protected_sha_before": before, "protected_sha_after": after,
                 "exp024_files_changed": 0, "engine_files_changed": 0, "evaluation_files_changed": 0,
                 "knowledge_files_changed": 0, "production_changed": False,
                 "current_git_head": __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                 "implementation_committed": False,
                 "git_head_impact": "This uncommitted implementation does not change git_head. Any later commit would change it; EXP-024 Block001 provenance must be checked separately.",
                 "baseline_note": "Protected tree hashes may include pre-existing working-tree changes; only before/after equality is claimed."}
    write_json("exp024_isolation_audit.json", isolation)
    decision = "DEVELOPMENT_SIGNAL_SUPPORTIVE" if (primary["rank1_additions"]["top3_hits"] > 0 and primary["raw_combined_lift_vs_current_pt"] > 0 and all(value["replication"] == "REPEAT" for value in secondary_results.values())) else "DEVELOPMENT_SIGNAL_MIXED" if primary["rank1_additions"]["top3_hits"] > 0 else "DEVELOPMENT_SIGNAL_NEGATIVE"
    lines = ["# CURRENT_UNCONVERGED_RANK1_RESOLUTION_SHADOW_V1", "",
             "Role: Development-only fixed-k1 Shadow. No Production or formal evidence authorization.", "",
             "Primary Current BUY: {top3_hits}/{selected_valid} = {top3_rate:.4%}, invalid {invalid_selected}.".format(**primary["original_current"]),
             "Primary Rank1 additions: {top3_hits}/{selected_valid} = {top3_rate:.4%}, invalid {invalid_selected}.".format(**primary["rank1_additions"]),
             "Primary combined: {top3_hits}/{selected_valid} = {top3_rate:.4%}, invalid {invalid_selected}.".format(**primary["combined_current_plus_additions"]),
             f"Raw combined rate difference: {primary['raw_combined_lift_vs_current_pt']:+.4f} percentage points.", "",
             "| Consumed secondary block | Unconverged races | Added hits / valid | Added rate | Combined hits / valid | Combined rate | Replication |",
             "|---|---:|---:|---:|---:|---:|---|" ]
    for block in ("december", "january"):
        data = secondary_results[block]
        add, combined = data["rank1_additions"], data["combined_current_plus_additions"]
        lines.append(f"| {block.title()} | {data['population']['unconverged_races']} | {add['top3_hits']}/{add['selected_valid']} | {add['top3_rate']:.2%} | {combined['top3_hits']}/{combined['selected_valid']} | {combined['top3_rate']:.2%} | {data['replication']} |")
    lines += ["", "Both secondary blocks are consumed Development checks, not independent evidence. The rank rule was fixed before secondary Result access.",
              "Temporal LODO, date concentration, and Independent overlap are descriptive only and do not alter the rule.",
              "Persisted Current rank resolves all score ties; no new tie-break, PL, threshold, or risk-guard count is used.",
              "", f"Development judgment: {decision}. Claude implementation review ready: YES. Production GO: NO."]
    (OUT / "final_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    outputs = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "artifact_hashes.json")
    write_json("artifact_hashes.json", {"outputs": {path.name: {"sha256": sha(path), "bytes": path.stat().st_size} for path in outputs},
                                        "role": "DEVELOPMENT_ONLY", "formal_evidence_credit": 0})
    print(json.dumps({"status": "COMPLETE", "primary": primary, "secondary": {key: {"additions": value["rank1_additions"], "replication": value["replication"]} for key, value in secondary_results.items()},
                      "semantic_violations": 0, "determinism_differences": 0, "development_judgment": decision,
                      "approval_sha256": sha(APPROVAL), "artifact_hashes_sha256": sha(OUT / "artifact_hashes.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
